"""Idempotent country / capital / org seed."""

from __future__ import annotations

import csv
import gettext
import json
import os
from pathlib import Path

from . import config
from .db import connect, vec_literal


def _iso_path() -> Path:
    p = Path(config.ISO_JSON)
    if p.is_file():
        return p
    return config.ROOT / "data" / "iso_3166-1.json"


def _load_iso() -> list[dict]:
    data = json.loads(_iso_path().read_text(encoding="utf-8"))
    return data["3166-1"]


def _translations(english: str) -> set[str]:
    names = set()
    locale_root = Path("/usr/share/locale")
    if not locale_root.is_dir():
        return names
    for lang in os.listdir(locale_root):
        try:
            tr = gettext.translation("iso_3166-1", str(locale_root), languages=[lang])
        except OSError:
            continue
        for src in (english,):
            got = tr.gettext(src)
            if got and got != src:
                names.add(got)
    return names


def _add_alias(cur, entity_id: int, alias: str) -> None:
    alias = (alias or "").strip()
    if not alias:
        return
    cur.execute(
        """
        INSERT INTO entity_aliases (entity_id, alias)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (entity_id, alias),
    )


def _upsert_entity(cur, canonical: str, etype: str, country_iso=None, aliases=()) -> int:
    if country_iso:
        cur.execute("SELECT id FROM entities WHERE country_iso = %s", (country_iso,))
        row = cur.fetchone()
        if row:
            eid = row["id"]
            cur.execute(
                "UPDATE entities SET canonical = %s, type = %s, provisional = false WHERE id = %s",
                (canonical, etype, eid),
            )
        else:
            cur.execute(
                """
                INSERT INTO entities (canonical, type, country_iso, provisional)
                VALUES (%s, %s, %s, false)
                RETURNING id
                """,
                (canonical, etype, country_iso),
            )
            eid = cur.fetchone()["id"]
    else:
        cur.execute(
            "SELECT id FROM entities WHERE lower(canonical) = lower(%s) AND type = %s",
            (canonical, etype),
        )
        row = cur.fetchone()
        if row:
            eid = row["id"]
        else:
            cur.execute(
                """
                INSERT INTO entities (canonical, type, provisional)
                VALUES (%s, %s, false)
                RETURNING id
                """,
                (canonical, etype),
            )
            eid = cur.fetchone()["id"]
    _add_alias(cur, eid, canonical)
    for a in aliases:
        _add_alias(cur, eid, a)
    return eid


def seed_countries(cur) -> dict[str, int]:
    extras = json.loads((config.ROOT / "data" / "aliases.json").read_text(encoding="utf-8"))
    by_iso: dict[str, int] = {}
    for item in _load_iso():
        iso = item["alpha_2"]
        name = item["name"]
        # Do not add ISO 3166-1 alpha-3 (VAT=Vatican, AND=Andorra) — they collide
        # with English words/acronyms. USA is the one people actually type.
        aliases = {item.get("official_name", ""), iso, name}
        if item.get("alpha_3") == "USA":
            aliases.add("USA")
        aliases |= _translations(name)
        if item.get("official_name"):
            aliases |= _translations(item["official_name"])
        for extra in extras.get("country_aliases", {}).get(iso, []):
            aliases.add(extra)
        aliases = {a for a in aliases if a and a != name}
        eid = _upsert_entity(cur, name, "country", country_iso=iso, aliases=aliases)
        by_iso[iso] = eid

    # Drop leftover alpha-3 aliases from older seeds (VAT, AND, ARE, …).
    cur.execute(
        """
        DELETE FROM entity_aliases a
        USING entities e
        WHERE a.entity_id = e.id
          AND e.country_iso IS NOT NULL
          AND a.alias ~ '^[A-Z]{3}$'
          AND a.alias <> 'USA'
        """
    )

    # Kosovo is not always in iso-codes
    if "XK" not in by_iso:
        by_iso["XK"] = _upsert_entity(
            cur, "Kosovo", "country", country_iso="XK",
            aliases=extras.get("country_aliases", {}).get("XK", []),
        )
    return by_iso


def seed_capitals(cur, by_iso: dict[str, int]) -> None:
    path = config.ROOT / "data" / "capitals.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            iso = row["iso"].strip()
            name = row["name"].strip()
            if not name or iso not in by_iso:
                continue
            aliases = [a for a in (row.get("aliases") or "").split("|") if a.strip()]
            cid = _upsert_entity(cur, name, "place", aliases=aliases)
            cur.execute(
                """
                INSERT INTO entity_relations
                    (src_entity_id, dst_entity_id, rel_type, fact, superseded)
                SELECT %s, %s, 'capital_of', %s, false
                WHERE NOT EXISTS (
                    SELECT 1 FROM entity_relations
                    WHERE src_entity_id = %s AND dst_entity_id = %s AND rel_type = 'capital_of'
                )
                """,
                (cid, by_iso[iso], f"{name} is the capital of {iso}", cid, by_iso[iso]),
            )


def seed_orgs_and_places(cur, by_iso: dict[str, int]) -> None:
    extras = json.loads((config.ROOT / "data" / "aliases.json").read_text(encoding="utf-8"))
    for org in extras.get("orgs", []):
        _upsert_entity(cur, org["name"], "org", aliases=org.get("aliases") or [])
    for place in extras.get("subdivisions", []):
        pid = _upsert_entity(cur, place["name"], place.get("type") or "place",
                             aliases=place.get("aliases") or [])
        parent = place.get("part_of")
        if parent and parent in by_iso:
            cur.execute(
                """
                INSERT INTO entity_relations
                    (src_entity_id, dst_entity_id, rel_type, fact, superseded)
                SELECT %s, %s, 'part_of', %s, false
                WHERE NOT EXISTS (
                    SELECT 1 FROM entity_relations
                    WHERE src_entity_id = %s AND dst_entity_id = %s AND rel_type = 'part_of'
                )
                """,
                (pid, by_iso[parent], f"{place['name']} is part of {parent}", pid, by_iso[parent]),
            )


def _upsert_source(cur, name, homepage, feed_url, feed_type="rss",
                   lang=None, country_iso=None, interval_minutes=30) -> None:
    cur.execute(
        """
        INSERT INTO sources (name, homepage, feed_url, feed_type, lang, country_iso, interval_minutes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE
        SET homepage = EXCLUDED.homepage,
            feed_url = EXCLUDED.feed_url,
            feed_type = EXCLUDED.feed_type,
            lang = EXCLUDED.lang,
            country_iso = EXCLUDED.country_iso,
            interval_minutes = EXCLUDED.interval_minutes
        """,
        (name, homepage, feed_url, feed_type, lang, country_iso, interval_minutes),
    )


def seed_feeds(cur) -> None:
    from urllib.parse import quote

    from . import country_langs as cl

    feeds = json.loads((config.ROOT / "data" / "feeds.json").read_text(encoding="utf-8"))
    for feed in feeds:
        _upsert_source(
            cur,
            feed["name"],
            feed.get("homepage"),
            feed.get("feed_url"),
            feed.get("feed_type") or "rss",
            lang=feed.get("lang"),
            country_iso=feed.get("country_iso"),
            interval_minutes=int(feed.get("interval_minutes") or 30),
        )

    for lang, host, page in cl.WIKI_PORTALS:
        enc = quote(page, safe=":")
        url = f"https://{host}/w/api.php?action=parse&page={enc}&prop=wikitext&format=json"
        _upsert_source(
            cur,
            f"Wikipedia Current Events ({lang})",
            f"https://{host}/wiki/{enc}",
            url,
            "wikipedia_current_events",
            lang=lang,
            interval_minutes=90,
        )

    cur.execute("SELECT country_iso, canonical FROM entities WHERE type = 'country' AND country_iso IS NOT NULL")
    countries = [(r["country_iso"], r["canonical"]) for r in cur.fetchall()]
    for iso, canonical in countries:
        if not cl.needs_country_feed(iso):
            continue
        langs = cl.langs_for(iso)[:2]
        extras = cl.EXTRA_QUERIES.get(iso, [])
        cur.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id = "
            "(SELECT id FROM entities WHERE country_iso = %s)",
            (iso,),
        )
        aliases = [r["alias"] for r in cur.fetchall()]
        # local-script / local-language names first, then official extras
        names = []
        for a in extras + aliases + [canonical]:
            if a and a not in names and not (len(a) <= 3 and a.isascii()):
                names.append(a)
            if len(names) >= 6:
                break
        if not names:
            names = [canonical]
        or_q = " OR ".join(f'"{n}"' if " " in n else n for n in names[:5])
        interval = 180 if iso in cl.GL_NEAR else 360
        for lang in langs:
            hl, gl = cl.gnews_market(iso, lang)
            q = quote(f"({or_q}) when:7d")
            url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
            _upsert_source(
                cur,
                f"GNews {iso} {lang}",
                f"https://news.google.com/search?q={quote(canonical)}",
                url,
                "rss",
                lang=lang,
                country_iso=iso,
                interval_minutes=interval,
            )


def seed_dossiers(cur) -> None:
    cur.execute("SELECT id, canonical, type FROM entities WHERE NOT provisional")
    for row in cur.fetchall():
        slug = f"entity:{row['id']}"
        cur.execute(
            """
            INSERT INTO dossiers (slug, title, kind)
            VALUES (%s, %s, 'entity')
            ON CONFLICT (slug) DO NOTHING
            """,
            (slug, row["canonical"]),
        )
        cur.execute("SELECT id FROM dossiers WHERE slug = %s", (slug,))
        did = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO dossier_entities (dossier_id, entity_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
            """,
            (did, row["id"]),
        )


def _embed_rows(cur, rows, text_of, table: str, batch: int) -> int:
    from . import embed as emb

    if not rows:
        return 0
    if not emb.available():
        raise RuntimeError(emb.unavailable_message())
    n = 0
    total = len(rows)
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        vecs = emb.embed([text_of(r) for r in chunk], query=False)
        for row, vec in zip(chunk, vecs):
            cur.execute(
                f"UPDATE {table} SET embedding = %s::vector WHERE id = %s",
                (vec_literal(vec), row["id"]),
            )
        n += len(chunk)
        print(f"embedded {n}/{total} {table}", flush=True)
    return n


def embed_entities(cur) -> int:
    cur.execute(
        """
        SELECT e.id, e.canonical,
               coalesce(string_agg(a.alias, ' '), '') AS aliases
        FROM entities e
        LEFT JOIN entity_aliases a ON a.entity_id = e.id
        WHERE e.embedding IS NULL
        GROUP BY e.id, e.canonical
        ORDER BY e.id
        """
    )
    rows = cur.fetchall()
    if not rows:
        return 0
    from . import embed as emb

    if not emb.available():
        return 0
    return _embed_rows(
        cur,
        rows,
        lambda r: f"{r['canonical']}. Also known as: {r['aliases']}",
        "entities",
        16,
    )


def embed_filed(cur) -> dict[str, int]:
    """Embed rows a news pass actually touched.

    The untouched gazetteer stays for embed_entities / worker --embed-pending.
    """
    cur.execute(
        """
        SELECT id, title, summary, summary_en
        FROM articles
        WHERE embedding IS NULL
        ORDER BY id
        """
    )
    articles = cur.fetchall()
    cur.execute(
        """
        SELECT e.id, e.canonical,
               coalesce(string_agg(a.alias, ' '), '') AS aliases
        FROM entities e
        LEFT JOIN entity_aliases a ON a.entity_id = e.id
        WHERE e.embedding IS NULL AND e.mention_count > 0
        GROUP BY e.id, e.canonical
        ORDER BY e.id
        """
    )
    entities = cur.fetchall()
    cur.execute(
        """
        SELECT d.id, d.title, d.current_status, d.body_compact
        FROM dossiers d
        WHERE d.embedding IS NULL
          AND (
            d.current_status <> ''
            OR d.body_compact <> ''
            OR EXISTS (
                SELECT 1 FROM dossier_timeline t WHERE t.dossier_id = d.id
            )
          )
        ORDER BY d.id
        """
    )
    dossiers = cur.fetchall()
    if not articles and not entities and not dossiers:
        return {"articles": 0, "entities": 0, "dossiers": 0}
    return {
        "articles": _embed_rows(
            cur,
            articles,
            lambda r: f"{r['title']}\n{r['summary'] or ''}\n{r['summary_en'] or ''}",
            "articles",
            8,
        ),
        "entities": _embed_rows(
            cur,
            entities,
            lambda r: f"{r['canonical']}. Also known as: {r['aliases']}",
            "entities",
            4,
        ),
        "dossiers": _embed_rows(
            cur,
            dossiers,
            lambda r: f"{r['title']}\n{r['current_status'] or ''}\n{r['body_compact'] or ''}",
            "dossiers",
            4,
        ),
    }


def run() -> None:
    conn = connect()
    try:
        cur = conn.cursor(cursor_factory=__import__("psycopg2.extras", fromlist=["RealDictCursor"]).RealDictCursor)
        by_iso = seed_countries(cur)
        seed_capitals(cur, by_iso)
        seed_orgs_and_places(cur, by_iso)
        seed_feeds(cur)
        seed_dossiers(cur)
        n = embed_entities(cur)
        conn.commit()
        cur.execute("SELECT count(*) AS n FROM entities WHERE type = 'country'")
        countries = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM entities")
        total = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM sources")
        feeds = cur.fetchone()["n"]
        print(f"seeded {countries} countries, {total} entities, {feeds} feeds, embedded {n}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
