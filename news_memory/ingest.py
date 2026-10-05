"""Fetch → cheap gazetteer → optional LLM extract → dossiers."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from psycopg2.extras import Json, RealDictCursor

import time

from . import dossiers, extract, language, resolve
from .db import connect, vec_literal
from .feeds import fetch_fulltext, fetch_rss, fetch_wikipedia_current_events, simhash64

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _log(cur, level: str, message: str, payload=None) -> None:
    cur.execute(
        "INSERT INTO ingest_log (level, message, payload) VALUES (%s, %s, %s)",
        (level, message, None if payload is None else Json(payload)),
    )


def _parse_day(value, fallback: date) -> date:
    if not value:
        return fallback
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value)[:10]
    if ISO_DATE.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return fallback
    return fallback


def _near_duplicate(cur, sim: int) -> bool:
    if not sim:
        return False
    cur.execute("SELECT simhash FROM articles WHERE simhash IS NOT NULL ORDER BY id DESC LIMIT 400")
    for row in cur.fetchall():
        a = int(row["simhash"]) & ((1 << 64) - 1)
        b = int(sim) & ((1 << 64) - 1)
        if bin(a ^ b).count("1") <= 3:
            return True
    return False


def _store_article(cur, source_id, item, body: str | None) -> int | None:
    url = (item.get("url") or "").strip()
    title = (item.get("title") or "").strip()
    if not url or not title:
        return None
    cur.execute("SELECT id FROM articles WHERE url = %s", (url,))
    if cur.fetchone():
        return None
    summary = item.get("summary") or ""
    blob = f"{title} {summary} {body or ''}"
    sim = simhash64(blob)
    if _near_duplicate(cur, sim):
        return None
    published = item.get("published_at") or datetime.now(timezone.utc)
    if isinstance(published, datetime) and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    lang = item.get("lang")
    cur.execute(
        """
        INSERT INTO articles
            (source_id, url, simhash, published_at, title, body, summary, lang, extract_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id
        """,
        (source_id, url, sim, published, title, body, summary, lang),
    )
    return cur.fetchone()["id"]


def _cheap_extract(title: str, summary: str, body: str, gaz) -> dict:
    text = f"{title}\n{summary}\n{body or ''}"
    hits = resolve.gazetteer_hits(text, gaz)
    return {
        "headline": title,
        "summary": (summary or title)[:1500],
        "summary_en": "",
        "lang": language.detect(text),
        "happened_at": None,
        "event_type": "other",
        "tags": [],
        "importance": 2 if hits else 1,
        "geo_countries": [],
        "entities": [
            {"name": None, "id": eid, "type": None, "role": "other", "aliases": [], "country_iso": None}
            for eid in hits
        ],
        "relations": [],
        "pair_topics": [],
        "_hit_ids": list(hits.keys()),
    }


def _embed_article(cur, article_id: int) -> None:
    from . import embed as emb

    if not emb.available():
        return
    cur.execute("SELECT title, summary, summary_en FROM articles WHERE id = %s", (article_id,))
    a = cur.fetchone()
    vec = emb.embed_one(
        f"{a['title']}\n{a['summary'] or ''}\n{a.get('summary_en') or ''}",
        query=False,
    )
    cur.execute("UPDATE articles SET embedding = %s::vector WHERE id = %s",
                (vec_literal(vec), article_id))


def process_article(cur, article_id: int, gaz, data=None) -> None:
    cur.execute(
        """
        SELECT a.*, s.name AS source_name
        FROM articles a
        LEFT JOIN sources s ON s.id = a.source_id
        WHERE a.id = %s
        """,
        (article_id,),
    )
    art = cur.fetchone()
    text = f"{art['title']}\n{art['summary'] or ''}\n{art['body'] or ''}"
    hits = resolve.gazetteer_hits(text, gaz)
    known = []
    if hits:
        cur.execute(
            "SELECT id, canonical, type, country_iso FROM entities WHERE id = ANY(%s)",
            (list(hits.keys()),),
        )
        known = [dict(r) for r in cur.fetchall()]
        for e in known:
            cur.execute(
                "SELECT alias FROM entity_aliases WHERE entity_id = %s ORDER BY length(alias) DESC LIMIT 12",
                (e["id"],),
            )
            e["aliases"] = [r["alias"] for r in cur.fetchall()]

    status = "supplied"
    if data is None:
        status = "cheap"
        if extract.extract_available():
            data = extract.extract_article(
                art["title"],
                str(art["published_at"]),
                art["source_name"] or "",
                text,
                known,
            )
            if data:
                status = "llm"
        if not data:
            data = _cheap_extract(art["title"], art["summary"] or "", art["body"] or "", gaz)

    pub_day = art["published_at"].date() if hasattr(art["published_at"], "date") else date.today()
    happened = _parse_day(data.get("happened_at"), pub_day)
    if abs((happened - pub_day).days) > 366 and status == "llm":
        # likely a historical aside; keep pub day unless the model dated it clearly in-range
        happened = pub_day

    importance = int(data.get("importance") or 2)
    importance = max(1, min(5, importance))
    event_type = data.get("event_type") or "other"
    tags = list(data.get("tags") or [])
    summary = (data.get("summary") or art["summary"] or art["title"]).strip()
    summary_en = (data.get("summary_en") or "").strip() or None
    lang = language.detect(
        text, hint=data.get("lang") or art.get("lang") or None,
    )
    filed = summary_en or summary

    name_to_id: dict[str, int] = {}
    entity_ids: list[int] = []

    # gazetteer hits first
    for e in known:
        name_to_id[e["canonical"].lower()] = e["id"]
        for a in e.get("aliases") or []:
            name_to_id[a.lower()] = e["id"]
        entity_ids.append(e["id"])

    for raw in data.get("entities") or []:
        if raw.get("id") and not raw.get("name"):
            eid = int(raw["id"])
            entity_ids.append(eid)
            continue
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        iso = raw.get("country_iso")
        if isinstance(iso, str):
            iso = iso.upper().strip() or None
        else:
            iso = None
        eid = resolve.resolve_or_create(
            cur,
            name,
            etype=raw.get("type") or "other",
            aliases=raw.get("aliases") or [],
            country_iso=iso,
            importance=importance,
        )
        name_to_id[name.lower()] = eid
        entity_ids.append(eid)

    for iso in data.get("geo_countries") or []:
        iso = str(iso).upper().strip()
        if len(iso) != 2:
            continue
        cur.execute("SELECT id, canonical FROM entities WHERE country_iso = %s", (iso,))
        row = cur.fetchone()
        if row:
            name_to_id[row["canonical"].lower()] = row["id"]
            entity_ids.append(row["id"])

    # unique preserve order
    seen = set()
    uniq = []
    for eid in entity_ids:
        if eid in seen:
            continue
        seen.add(eid)
        uniq.append(eid)
        resolve.bump_mention(cur, eid)
    entity_ids = uniq

    cur.execute(
        """
        INSERT INTO events (article_id, happened_at, event_type, tags, summary, importance)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (article_id, happened, event_type, tags, filed, importance),
    )
    event_id = cur.fetchone()["id"]
    for raw in data.get("entities") or []:
        name = (raw.get("name") or "").strip()
        eid = raw.get("id") or name_to_id.get(name.lower())
        if not eid:
            continue
        cur.execute(
            """
            INSERT INTO event_entities (event_id, entity_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (event_id, entity_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (event_id, eid, raw.get("role") or "other"),
        )
    for eid in entity_ids:
        cur.execute(
            """
            INSERT INTO event_entities (event_id, entity_id, role)
            VALUES (%s, %s, 'other')
            ON CONFLICT DO NOTHING
            """,
            (event_id, eid),
        )

    for rel in data.get("relations") or []:
        src = name_to_id.get((rel.get("src") or "").lower())
        dst = name_to_id.get((rel.get("dst") or "").lower())
        if not src:
            src = (resolve.lookup_name(cur, rel.get("src") or "") or {}).get("id")
        if not dst:
            dst = (resolve.lookup_name(cur, rel.get("dst") or "") or {}).get("id")
        if not src or not dst:
            continue
        dossiers.apply_relation(
            cur, src, dst, rel.get("rel") or "other",
            _parse_day(rel.get("valid_from"), None) if rel.get("valid_from") else None,
            _parse_day(rel.get("valid_to"), None) if rel.get("valid_to") else None,
            article_id, rel.get("fact") or "",
        )

    pairs = []
    for p in data.get("pair_topics") or []:
        a = name_to_id.get((p.get("a") or "").lower())
        b = name_to_id.get((p.get("b") or "").lower())
        if a and b and a != b:
            pairs.append((a, b, p.get("kind") or "other"))
    # domestic politics still gets a pair between a person and their country
    if not pairs and len(entity_ids) >= 2 and event_type in ("politics", "economy", "legal", "conflict", "diplomacy"):
        pairs.append((entity_ids[0], entity_ids[1], event_type))

    dossiers.apply_event(cur, event_id, entity_ids, pairs)

    cur.execute(
        """
        UPDATE articles
        SET summary = %s, summary_en = %s, lang = %s, importance = %s,
            extract_json = %s, extract_status = %s
        WHERE id = %s
        """,
        (summary, summary_en, lang, importance,
         Json({k: v for k, v in data.items() if not str(k).startswith("_")}),
         status, article_id),
    )
    _embed_article(cur, article_id)


def ingest_source(cur, source: dict, gaz, fetch_body: bool = True, force: bool = False) -> int:
    added = 0
    cur.execute("SELECT * FROM feed_state WHERE source_id = %s", (source["id"],))
    state = cur.fetchone() or {}
    interval = int(source.get("interval_minutes") or 30)
    if not force and state.get("last_ok_at") and interval > 0:
        last = state["last_ok_at"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - last).total_seconds()
        if age < interval * 60:
            return 0
    try:
        if source["feed_type"] == "wikipedia_current_events":
            items = fetch_wikipedia_current_events(source["feed_url"])
            etag = lm = None
        else:
            items, etag, lm = fetch_rss(
                source["feed_url"],
                etag=state.get("etag"),
                last_modified=state.get("last_modified"),
            )
        src_lang = source.get("lang")
        for item in items:
            if src_lang and not item.get("lang"):
                item["lang"] = src_lang
            body = None
            if fetch_body and item.get("url") and source["feed_type"] != "wikipedia_current_events":
                body = fetch_fulltext(item["url"])
            aid = _store_article(cur, source["id"], item, body)
            if aid is None:
                continue
            process_article(cur, aid, gaz)
            added += 1
        cur.execute(
            """
            INSERT INTO feed_state (source_id, etag, last_modified, last_ok_at, last_error)
            VALUES (%s, %s, %s, now(), NULL)
            ON CONFLICT (source_id) DO UPDATE
            SET etag = EXCLUDED.etag,
                last_modified = EXCLUDED.last_modified,
                last_ok_at = now(),
                last_error = NULL
            """,
            (source["id"], etag, lm),
        )
        _log(cur, "info", f"{source['name']}: +{added}", {"added": added})
        if source.get("country_iso"):
            time.sleep(0.15)
    except Exception as e:
        cur.execute(
            """
            INSERT INTO feed_state (source_id, last_error)
            VALUES (%s, %s)
            ON CONFLICT (source_id) DO UPDATE SET last_error = EXCLUDED.last_error
            """,
            (source["id"], str(e)[:500]),
        )
        _log(cur, "error", f"{source['name']}: {e}")
    return added


def run_once(fetch_body: bool = True, force: bool = False) -> int:
    conn = connect()
    added = 0
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        gaz = resolve.load_gazetteer(cur)
        cur.execute("SELECT * FROM sources WHERE feed_url IS NOT NULL ORDER BY id")
        sources = [dict(r) for r in cur.fetchall()]
        for src in sources:
            added += ingest_source(cur, src, gaz, fetch_body=fetch_body, force=force)
            conn.commit()
            gaz = resolve.load_gazetteer(cur)
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return added


def ingest_manual(title: str, body: str, published: str | None = None,
                  url: str | None = None, source_name: str = "manual",
                  extract_data=None) -> int:
    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO sources (name, feed_type)
            VALUES (%s, 'manual')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (source_name,),
        )
        sid = cur.fetchone()["id"]
        if not url:
            url = f"manual://{simhash64(title + body)}/{datetime.now(timezone.utc).timestamp()}"
        pub = datetime.fromisoformat(published) if published else datetime.now(timezone.utc)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        item = {"url": url, "title": title, "summary": body[:400], "published_at": pub}
        aid = _store_article(cur, sid, item, body)
        if aid is None:
            cur.execute("SELECT id FROM articles WHERE url = %s", (url,))
            aid = cur.fetchone()["id"]
            conn.commit()
            return aid
        gaz = resolve.load_gazetteer(cur)
        process_article(cur, aid, gaz, data=extract_data)
        conn.commit()
        return aid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
