"""Retrieval tools used by the chat model (and query.py / tools_server.py)."""

from __future__ import annotations

from datetime import date, timedelta

from . import resolve
from . import when as whenmod
from .db import cursor, vec_literal


def _as_of(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return date.today()


def resolve_names(cur, names: list[str]) -> list[dict]:
    out = []
    seen = set()
    for name in names:
        if not name:
            continue
        hit = resolve.lookup_name(cur, name)
        if not hit:
            near = resolve.nearest_embedded(cur, name)
            hit = near[0] if near and near[0]["score"] >= 0.78 else None
        if hit and hit["id"] not in seen:
            seen.add(hit["id"])
            out.append(hit)
    return out


def resolve_query_entities(cur, query: str) -> list[dict]:
    gaz = resolve.load_gazetteer(cur)
    hits = resolve.gazetteer_hits(query, gaz)
    ents = []
    if hits:
        cur.execute("SELECT * FROM entities WHERE id = ANY(%s)", (list(hits.keys()),))
        ents = [dict(r) for r in cur.fetchall()]
    # whole-string lookup only for short names, not questions
    if query and len(query.split()) <= 3:
        extra = resolve.lookup_name(cur, query)
        if extra and extra["id"] not in {e["id"] for e in ents}:
            ents.append(extra)
    return ents


def _embed_search(cur, table: str, query: str, limit: int):
    from . import embed as emb

    if not emb.available():
        return []
    vec = emb.embed_one(query, query=True)
    if table == "dossiers":
        cur.execute(
            """
            SELECT id, slug, title, kind, current_status, updated_at,
                   1 - (embedding <=> %s::vector) AS score
            FROM dossiers
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec_literal(vec), vec_literal(vec), limit),
        )
    elif table == "events":
        cur.execute(
            """
            SELECT ev.id, ev.happened_at, ev.event_type, ev.tags, ev.summary, ev.importance,
                   ev.article_id, 1 - (a.embedding <=> %s::vector) AS score
            FROM events ev
            JOIN articles a ON a.id = ev.article_id
            WHERE a.embedding IS NOT NULL
            ORDER BY a.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec_literal(vec), vec_literal(vec), limit),
        )
    else:
        return []
    return [dict(r) for r in cur.fetchall()]


def search_dossiers(query: str, limit: int = 5) -> dict:
    with cursor() as cur:
        ents = resolve_query_entities(cur, query)
        found = {}
        if len(ents) >= 2:
            ids = [e["id"] for e in ents]
            cur.execute(
                """
                SELECT d.*
                FROM dossiers d
                JOIN dossier_entities a ON a.dossier_id = d.id
                JOIN dossier_entities b ON b.dossier_id = d.id
                WHERE d.kind = 'pair' AND a.entity_id = ANY(%s) AND b.entity_id = ANY(%s)
                  AND a.entity_id <> b.entity_id
                """,
                (ids, ids),
            )
            for r in cur.fetchall():
                found[r["id"]] = dict(r)
        for e in ents:
            cur.execute(
                """
                SELECT d.*
                FROM dossiers d
                JOIN dossier_entities de ON de.dossier_id = d.id
                WHERE de.entity_id = %s
                ORDER BY d.kind = 'entity' DESC, d.updated_at DESC
                """,
                (e["id"],),
            )
            for r in cur.fetchall():
                found.setdefault(r["id"], dict(r))
        cur.execute(
            """
            SELECT id, slug, title, kind, current_status, updated_at
            FROM dossiers
            WHERE to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(current_status,''))
                  @@ plainto_tsquery('simple', %s)
            LIMIT %s
            """,
            (query, limit),
        )
        for r in cur.fetchall():
            found.setdefault(r["id"], dict(r))
        for r in _embed_search(cur, "dossiers", query, limit):
            found.setdefault(r["id"], r)
        items = list(found.values())[:limit]
        for d in items:
            d["timeline"] = _timeline(cur, d["id"], limit=12)
        return {
            "entities": [{"id": e["id"], "canonical": e["canonical"], "type": e["type"]} for e in ents],
            "dossiers": items,
        }


def _timeline(cur, dossier_id: int, limit: int = 20, date_from=None, date_to=None):
    sql = """
        SELECT happened_at, importance, event_type, tags, bullet, article_id, event_id
        FROM dossier_timeline
        WHERE dossier_id = %s
    """
    args = [dossier_id]
    if date_from:
        sql += " AND happened_at >= %s"
        args.append(date_from)
    if date_to:
        sql += " AND happened_at <= %s"
        args.append(date_to)
    sql += " ORDER BY happened_at DESC, id DESC LIMIT %s"
    args.append(limit)
    cur.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def search_events(query: str | None = None, entities: list[str] | None = None,
                  event_type: str | None = None, date_from: str | None = None,
                  date_to: str | None = None, limit: int = 20) -> dict:
    with cursor() as cur:
        ent_rows = resolve_names(cur, entities or [])
        if query and not ent_rows:
            ent_rows = resolve_query_entities(cur, query)
        if not date_from and not date_to:
            df, dt = whenmod.parse_when(query)
            if df:
                date_from = df.isoformat()
            if dt:
                date_to = dt.isoformat()

        # Never require an English keyword to appear in a German summary.
        # Rank by multilingual embedding when we have one; otherwise by
        # importance inside the date/entity window.
        scored = []
        if query:
            scored = _embed_search(cur, "events", query, max(limit * 4, 40))
            if date_from:
                scored = [r for r in scored if str(r["happened_at"]) >= str(date_from)]
            if date_to:
                scored = [r for r in scored if str(r["happened_at"]) <= str(date_to)]
            if ent_rows:
                ids = {e["id"] for e in ent_rows}
                kept = []
                for r in scored:
                    cur.execute(
                        "SELECT 1 FROM event_entities WHERE event_id = %s AND entity_id = ANY(%s)",
                        (r["id"], list(ids)),
                    )
                    if cur.fetchone():
                        kept.append(r)
                scored = kept
            if event_type:
                scored = [r for r in scored if r.get("event_type") == event_type]

        sql = """
            SELECT ev.id, ev.happened_at, ev.event_type, ev.tags, ev.summary,
                   ev.importance, ev.article_id
            FROM events ev
        """
        wh = []
        args: list = []
        if ent_rows:
            sql += " JOIN event_entities ee ON ee.event_id = ev.id"
            wh.append("ee.entity_id = ANY(%s)")
            args.append([e["id"] for e in ent_rows])
        if event_type:
            wh.append("ev.event_type = %s")
            args.append(event_type)
        if date_from:
            wh.append("ev.happened_at >= %s")
            args.append(date_from)
        if date_to:
            wh.append("ev.happened_at <= %s")
            args.append(date_to)
        if wh:
            sql += " WHERE " + " AND ".join(wh)
        sql += " GROUP BY ev.id ORDER BY ev.importance DESC, ev.happened_at DESC LIMIT %s"
        args.append(max(limit, 40) if (date_from or ent_rows) else limit)
        cur.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]

        if scored:
            by_id = {r["id"]: r for r in rows}
            ordered = []
            seen = set()
            for r in scored:
                seen.add(r["id"])
                merged = dict(by_id.get(r["id"], r))
                merged["score"] = r.get("score")
                ordered.append(merged)
            for r in rows:
                if r["id"] not in seen:
                    ordered.append(r)
            rows = ordered
        return {
            "entities": [{"id": e["id"], "canonical": e["canonical"], "type": e["type"]} for e in ent_rows],
            "date_from": date_from,
            "date_to": date_to,
            "events": rows[:limit],
        }


def get_timeline(entities: list[str], date_from: str | None = None,
                 date_to: str | None = None, limit: int = 40) -> dict:
    with cursor() as cur:
        ent_rows = resolve_names(cur, entities)
        if not ent_rows:
            return {"entities": [], "events": []}
        ids = [e["id"] for e in ent_rows]
        sql = """
            SELECT ev.id, ev.happened_at, ev.event_type, ev.tags, ev.summary,
                   ev.importance, ev.article_id,
                   array_agg(DISTINCT en.canonical) AS entities
            FROM events ev
            JOIN event_entities ee ON ee.event_id = ev.id
            JOIN entities en ON en.id = ee.entity_id
            WHERE ee.entity_id = ANY(%s)
        """
        args: list = [ids]
        if date_from:
            sql += " AND ev.happened_at >= %s"
            args.append(date_from)
        if date_to:
            sql += " AND ev.happened_at <= %s"
            args.append(date_to)
        sql += " GROUP BY ev.id ORDER BY ev.happened_at ASC, ev.id ASC LIMIT %s"
        args.append(limit)
        cur.execute(sql, args)
        return {
            "entities": [{"id": e["id"], "canonical": e["canonical"], "type": e["type"]} for e in ent_rows],
            "events": [dict(r) for r in cur.fetchall()],
        }


def get_article(article_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.url, a.published_at, a.title, a.summary, a.summary_en,
                   a.body, a.lang, a.importance, s.name AS source
            FROM articles a
            LEFT JOIN sources s ON s.id = a.source_id
            WHERE a.id = %s
            """,
            (article_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def resolve_entity(name: str) -> dict | None:
    with cursor() as cur:
        hit = resolve.lookup_name(cur, name)
        if not hit:
            near = resolve.nearest_embedded(cur, name)
            return {"match": None, "near": near}
        cur.execute("SELECT alias FROM entity_aliases WHERE entity_id = %s", (hit["id"],))
        hit["aliases"] = [r["alias"] for r in cur.fetchall()]
        hit["offices"] = resolve.office_holders(cur, hit["id"])
        return {"match": hit}


def get_background(query: str, as_of: str | None = None, years: int = 5) -> dict:
    """The tool for 'why did A oust its president' / 'context of A vs B'."""
    day = _as_of(as_of)
    start = date(day.year - max(int(years or 5), 1), day.month, day.day)
    win_from, win_to = whenmod.parse_when(query)
    if win_to and win_to > day:
        day = win_to
    if win_from and win_from < start:
        start = win_from
    if win_from and win_to:
        # a dated question ("in July 2027") should not drag in five extra years
        start, day = win_from, win_to
    with cursor() as cur:
        ents = resolve_query_entities(cur, query)
        if not ents:
            found = search_events(
                query=query,
                date_from=start.isoformat(),
                date_to=day.isoformat(),
                limit=30,
            )
            ev_ents = []
            seen_e = set()
            with cursor() as cur2:
                for ev in found.get("events") or []:
                    cur2.execute(
                        """
                        SELECT en.id, en.canonical, en.type
                        FROM event_entities ee
                        JOIN entities en ON en.id = ee.entity_id
                        WHERE ee.event_id = %s
                        """,
                        (ev["id"],),
                    )
                    for row in cur2.fetchall():
                        if row["id"] not in seen_e:
                            seen_e.add(row["id"])
                            ev_ents.append(dict(row))
            doss = search_dossiers(query, limit=5).get("dossiers") or []
            return {
                "as_of": day.isoformat(),
                "since": start.isoformat(),
                "entities": ev_ents,
                "office_holders": [],
                "dossiers": doss,
                "events": found.get("events") or [],
            }

        extra = []
        for e in ents:
            extra.extend(resolve.office_holders(
                cur, e["id"], as_of=day.isoformat(), since=start.isoformat(),
            ))
        people = []
        seen = {e["id"] for e in ents}
        for rel in extra:
            for key, name_key, type_key in (
                ("src_entity_id", "src_name", "src_type"),
                ("dst_entity_id", "dst_name", "dst_type"),
            ):
                if rel[key] not in seen:
                    seen.add(rel[key])
                    people.append({
                        "id": rel[key],
                        "canonical": rel[name_key],
                        "type": rel[type_key],
                    })
                    ents.append({
                        "id": rel[key],
                        "canonical": rel[name_key],
                        "type": rel[type_key],
                    })

        ids = [e["id"] for e in ents]
        cur.execute(
            """
            SELECT d.id, d.slug, d.title, d.kind, d.current_status, d.body_compact, d.updated_at
            FROM dossiers d
            JOIN dossier_entities de ON de.dossier_id = d.id
            WHERE de.entity_id = ANY(%s)
            ORDER BY d.kind = 'pair' DESC, d.updated_at DESC
            """,
            (ids,),
        )
        doss = []
        seen_d = set()
        for r in cur.fetchall():
            if r["id"] in seen_d:
                continue
            seen_d.add(r["id"])
            item = dict(r)
            item["timeline"] = _timeline(cur, r["id"], limit=30, date_from=start, date_to=day)
            doss.append(item)

        cur.execute(
            """
            SELECT ev.id, ev.happened_at, ev.event_type, ev.tags, ev.summary,
                   ev.importance, ev.article_id,
                   array_agg(DISTINCT en.canonical) AS entities
            FROM events ev
            JOIN event_entities ee ON ee.event_id = ev.id
            JOIN entities en ON en.id = ee.entity_id
            WHERE ee.entity_id = ANY(%s)
              AND ev.happened_at BETWEEN %s AND %s
            GROUP BY ev.id
            ORDER BY ev.happened_at ASC, ev.importance DESC
            LIMIT 80
            """,
            (ids, start, day),
        )
        events = [dict(r) for r in cur.fetchall()]
        return {
            "as_of": day.isoformat(),
            "since": start.isoformat(),
            "entities": [{"id": e["id"], "canonical": e["canonical"], "type": e.get("type")} for e in ents],
            "office_holders": [
                {
                    "person": r["src_name"],
                    "office": r["rel_type"],
                    "of": r["dst_name"],
                    "valid_from": str(r["valid_from"]) if r["valid_from"] else None,
                    "valid_to": str(r["valid_to"]) if r["valid_to"] else None,
                    "fact": r["fact"],
                }
                for r in extra
            ],
            "dossiers": doss[:8],
            "events": events,
        }


DISPATCH = {
    "search_dossiers": lambda **kw: search_dossiers(
        kw.get("query") or "", int(kw.get("limit") or 5)
    ),
    "search_events": lambda **kw: search_events(
        query=kw.get("query"),
        entities=kw.get("entities"),
        event_type=kw.get("event_type"),
        date_from=kw.get("date_from"),
        date_to=kw.get("date_to"),
        limit=int(kw.get("limit") or 20),
    ),
    "get_timeline": lambda **kw: get_timeline(
        kw.get("entities") or [],
        date_from=kw.get("date_from"),
        date_to=kw.get("date_to"),
        limit=int(kw.get("limit") or 40),
    ),
    "get_background": lambda **kw: get_background(
        kw.get("query") or "",
        as_of=kw.get("as_of"),
        years=int(kw.get("years") or 5),
    ),
    "get_article": lambda **kw: get_article(int(kw["article_id"])),
    "resolve_entity": lambda **kw: resolve_entity(kw.get("name") or ""),
}


def call(name: str, arguments: dict):
    if name not in DISPATCH:
        raise KeyError(name)
    return DISPATCH[name](**(arguments or {}))


def system_prompt(today: str | None = None) -> str:
    from . import config

    text = config.read_text("prompts/chat_system.txt")
    return text.replace("{today}", today or date.today().isoformat())
