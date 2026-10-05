"""Living entity and pair dossiers. Entity dossiers hold ALL event types."""

from __future__ import annotations

from . import extract
from .db import vec_literal


def entity_slug(entity_id: int) -> str:
    return f"entity:{entity_id}"


def pair_slug(a: int, b: int) -> str:
    lo, hi = (a, b) if a < b else (b, a)
    return f"pair:{lo}:{hi}"


def ensure_entity_dossier(cur, entity_id: int) -> int:
    cur.execute("SELECT id, canonical FROM entities WHERE id = %s", (entity_id,))
    ent = cur.fetchone()
    if not ent:
        raise ValueError(f"no entity {entity_id}")
    slug = entity_slug(entity_id)
    cur.execute(
        """
        INSERT INTO dossiers (slug, title, kind)
        VALUES (%s, %s, 'entity')
        ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (slug, ent["canonical"]),
    )
    did = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO dossier_entities (dossier_id, entity_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (did, entity_id),
    )
    return did


def ensure_pair_dossier(cur, a: int, b: int, kind: str) -> int:
    if a == b:
        return ensure_entity_dossier(cur, a)
    lo, hi = (a, b) if a < b else (b, a)
    cur.execute("SELECT id, canonical FROM entities WHERE id IN (%s, %s)", (lo, hi))
    names = {r["id"]: r["canonical"] for r in cur.fetchall()}
    title = f"{names.get(lo, lo)} – {names.get(hi, hi)} ({kind})"
    slug = pair_slug(lo, hi)
    cur.execute(
        """
        INSERT INTO dossiers (slug, title, kind)
        VALUES (%s, %s, 'pair')
        ON CONFLICT (slug) DO UPDATE
        SET title = CASE
            WHEN dossiers.title LIKE %s THEN dossiers.title
            ELSE EXCLUDED.title
        END
        RETURNING id
        """,
        (slug, title, "%(%"),
    )
    did = cur.fetchone()["id"]
    for eid in (lo, hi):
        cur.execute(
            "INSERT INTO dossier_entities (dossier_id, entity_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (did, eid),
        )
    return did


def append_bullet(cur, dossier_id: int, happened_at, article_id, event_id,
                  importance: int, event_type: str, tags, bullet: str) -> None:
    cur.execute(
        """
        SELECT 1 FROM dossier_timeline
        WHERE dossier_id = %s AND event_id IS NOT DISTINCT FROM %s AND bullet = %s
        LIMIT 1
        """,
        (dossier_id, event_id, bullet),
    )
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO dossier_timeline
            (dossier_id, happened_at, article_id, event_id, importance, event_type, tags, bullet)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (dossier_id, happened_at, article_id, event_id, importance, event_type, tags or [], bullet),
    )
    cur.execute("UPDATE dossiers SET updated_at = now() WHERE id = %s", (dossier_id,))


def timeline_lines(cur, dossier_id: int, limit: int = 40) -> list[str]:
    cur.execute(
        """
        SELECT happened_at, importance, event_type, tags, bullet
        FROM dossier_timeline
        WHERE dossier_id = %s
        ORDER BY happened_at ASC, id ASC
        """,
        (dossier_id,),
    )
    rows = cur.fetchall()
    if limit and len(rows) > limit:
        rows = rows[-limit:]
    out = []
    for r in rows:
        tags = ",".join(r["tags"] or [])
        extra = f" [{r['event_type']}" + (f"/{tags}" if tags else "") + "]"
        out.append(f"{r['happened_at']} (p{r['importance']}){extra}: {r['bullet']}")
    return out


def maybe_rewrite_status(cur, dossier_id: int, new_event: str, importance: int) -> None:
    if importance < 3:
        return
    cur.execute("SELECT title, current_status, last_status_rewrite FROM dossiers WHERE id = %s",
                (dossier_id,))
    d = cur.fetchone()
    if not d:
        return
    if importance < 4 and d["last_status_rewrite"] is not None:
        cur.execute(
            "SELECT last_status_rewrite < now() - interval '20 hours' AS stale "
            "FROM dossiers WHERE id = %s",
            (dossier_id,),
        )
        if not cur.fetchone()["stale"]:
            return
    if not extract.extract_available():
        # cheap fallback: keep a rolling last-paragraph note
        note = new_event.strip()
        old = (d["current_status"] or "").strip()
        merged = (old + "\n\n" + note).strip()
        if len(merged) > 4000:
            merged = merged[-4000:]
        cur.execute(
            "UPDATE dossiers SET current_status = %s, last_status_rewrite = now() WHERE id = %s",
            (merged, dossier_id),
        )
        return
    status = extract.rewrite_status(
        d["title"], d["current_status"], timeline_lines(cur, dossier_id), new_event,
    )
    if not status:
        return
    cur.execute(
        "UPDATE dossiers SET current_status = %s, last_status_rewrite = now() WHERE id = %s",
        (status, dossier_id),
    )
    _embed_dossier(cur, dossier_id)


def _embed_dossier(cur, dossier_id: int) -> None:
    from . import embed as emb

    if not emb.available():
        return
    cur.execute("SELECT title, current_status, body_compact FROM dossiers WHERE id = %s", (dossier_id,))
    d = cur.fetchone()
    text = f"{d['title']}\n{d['current_status']}\n{d['body_compact']}"
    vec = emb.embed_one(text, query=False)
    cur.execute("UPDATE dossiers SET embedding = %s::vector WHERE id = %s", (vec_literal(vec), dossier_id))


def apply_event(cur, event_id: int, entity_ids: list[int], pair_topics: list[tuple[int, int, str]]) -> None:
    cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
    ev = cur.fetchone()
    if not ev:
        return
    bullet = ev["summary"]
    touched = []
    for eid in entity_ids:
        did = ensure_entity_dossier(cur, eid)
        append_bullet(cur, did, ev["happened_at"], ev["article_id"], ev["id"],
                      ev["importance"], ev["event_type"], ev["tags"], bullet)
        touched.append(did)
    for a, b, kind in pair_topics:
        did = ensure_pair_dossier(cur, a, b, kind)
        append_bullet(cur, did, ev["happened_at"], ev["article_id"], ev["id"],
                      ev["importance"], ev["event_type"], ev["tags"], bullet)
        touched.append(did)
    # rewrite the most specific dossiers (pairs first, then high-importance entities)
    for did in reversed(touched):
        maybe_rewrite_status(cur, did, f"{ev['happened_at']}: {bullet}", ev["importance"])


def apply_relation(cur, src_id: int, dst_id: int, rel_type: str,
                   valid_from, valid_to, article_id, fact: str) -> None:
    office = rel_type in ("president_of", "pm_of", "monarch_of", "leader_of")
    if office and valid_to is None:
        # new holder closes previous open relation of the same office on dst
        cur.execute(
            """
            UPDATE entity_relations
            SET valid_to = COALESCE(%s::date, valid_to), superseded = true
            WHERE dst_entity_id = %s AND rel_type = %s AND superseded = false
              AND valid_to IS NULL AND src_entity_id <> %s
            """,
            (valid_from, dst_id, rel_type, src_id),
        )
    if valid_to is not None:
        cur.execute(
            """
            UPDATE entity_relations
            SET valid_to = %s, superseded = true
            WHERE src_entity_id = %s AND dst_entity_id = %s AND rel_type = %s
              AND superseded = false AND valid_to IS NULL
            """,
            (valid_to, src_id, dst_id, rel_type),
        )
    cur.execute(
        """
        INSERT INTO entity_relations
            (src_entity_id, dst_entity_id, rel_type, valid_from, valid_to, article_id, fact, superseded)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (src_id, dst_id, rel_type, valid_from, valid_to, article_id, fact, valid_to is not None),
    )
