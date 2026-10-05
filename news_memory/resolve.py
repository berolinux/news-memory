"""Gazetteer + trigram + embedding entity resolution."""

from __future__ import annotations

import re
from functools import lru_cache

from .db import vec_literal

_WORD = re.compile(r"[A-Za-z0-9\u00C0-\u024F'.-]+")


@lru_cache(maxsize=1)
def _alias_rows(cur_id: int):
    # cache key unused; we refresh via clear
    return None


def load_gazetteer(cur) -> list[tuple[str, int, str, str]]:
    """Return (alias, entity_id, canonical, type) longest alias first."""
    cur.execute(
        """
        SELECT a.alias, e.id, e.canonical, e.type
        FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        """
    )
    rows = [(r["alias"], r["id"], r["canonical"], r["type"]) for r in cur.fetchall()]
    rows.sort(key=lambda r: len(r[0]), reverse=True)
    return rows


def _contains_alias(text: str, text_l: str, alias: str) -> bool:
    if not alias:
        return False
    # ISO codes and other 1–3 char tokens only match as written (US, not "us"/"me").
    if len(alias) <= 3:
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", text) is not None
    alias_l = alias.lower()
    if " " in alias_l or "-" in alias_l:
        return alias_l in text_l
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(alias_l) + r"(?![A-Za-z0-9])", text_l) is not None


def gazetteer_hits(text: str, gazetteer) -> dict[int, str]:
    text_l = text.lower()
    found: dict[int, str] = {}
    for alias, eid, _canonical, _typ in gazetteer:
        if eid in found:
            continue
        if _contains_alias(text, text_l, alias):
            found[eid] = alias
    return found


def lookup_name(cur, name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    cur.execute(
        """
        SELECT e.*
        FROM entities e
        JOIN entity_aliases a ON a.entity_id = e.id
        WHERE lower(a.alias) = lower(%s)
        ORDER BY e.provisional, e.id
        LIMIT 1
        """,
        (name,),
    )
    row = cur.fetchone()
    if row:
        return dict(row)
    cur.execute(
        """
        SELECT e.*, similarity(a.alias, %s) AS sim
        FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE a.alias %% %s
        ORDER BY similarity(a.alias, %s) DESC, e.provisional, e.id
        LIMIT 5
        """,
        (name, name, name),
    )
    rows = cur.fetchall()
    if rows and float(rows[0]["sim"]) >= 0.70:
        return dict(rows[0])
    return None


def nearest_embedded(cur, name: str, etype: str | None = None, limit: int = 5):
    from . import embed as emb

    if not emb.available():
        return []
    vec = emb.embed_one(name, query=True)
    sql = """
        SELECT id, canonical, type, provisional,
               1 - (embedding <=> %s::vector) AS score
        FROM entities
        WHERE embedding IS NOT NULL
    """
    args = [vec_literal(vec)]
    if etype:
        sql += " AND type = %s"
        args.append(etype)
    sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
    args.extend([vec_literal(vec), limit])
    cur.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def same_entity_llm(name: str, candidate: dict) -> bool | None:
    from . import extract

    prompt = (
        f"Is \"{name}\" the same real-world entity as "
        f"\"{candidate['canonical']}\" (type={candidate['type']}, id={candidate['id']})?\n"
        "Answer JSON {\"same\": true} or {\"same\": false}."
    )
    data = extract.complete_json(
        prompt,
        system="You only decide if two names refer to the same entity. No extra keys.",
        grammar_file="grammars/same_entity.gbnf",
    )
    if not data:
        return None
    return bool(data.get("same"))


def resolve_or_create(
    cur,
    name: str,
    etype: str = "other",
    aliases=(),
    country_iso: str | None = None,
    importance: int = 2,
) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("empty entity name")

    if country_iso:
        cur.execute("SELECT id FROM entities WHERE country_iso = %s", (country_iso.upper(),))
        row = cur.fetchone()
        if row:
            _remember_alias(cur, row["id"], name)
            for a in aliases:
                _remember_alias(cur, row["id"], a)
            return row["id"]

    hit = lookup_name(cur, name)
    if hit:
        if etype and hit["type"] != etype and etype != "other" and hit["type"] != "other":
            pass
        else:
            _remember_alias(cur, hit["id"], name)
            for a in aliases:
                _remember_alias(cur, hit["id"], a)
            return hit["id"]

    near = nearest_embedded(cur, name, etype=etype if etype in ("country", "person", "org") else None)
    if near and near[0]["score"] >= 0.86 and (not etype or near[0]["type"] == etype or etype == "other"):
        _remember_alias(cur, near[0]["id"], name)
        return near[0]["id"]
    if near and near[0]["score"] >= 0.75:
        same = same_entity_llm(name, near[0])
        if same:
            _remember_alias(cur, near[0]["id"], name)
            return near[0]["id"]

    provisional = importance < 2
    cur.execute(
        """
        INSERT INTO entities (canonical, type, country_iso, provisional, mention_count)
        VALUES (%s, %s, %s, %s, 0)
        ON CONFLICT ((lower(canonical)), type)
        DO UPDATE SET provisional = entities.provisional AND EXCLUDED.provisional
        RETURNING id
        """,
        (name, etype, country_iso.upper() if country_iso else None, provisional),
    )
    eid = cur.fetchone()["id"]
    _remember_alias(cur, eid, name)
    for a in aliases:
        _remember_alias(cur, eid, a)
    return eid


def _remember_alias(cur, entity_id: int, alias: str) -> None:
    alias = (alias or "").strip()
    if not alias:
        return
    cur.execute(
        "INSERT INTO entity_aliases (entity_id, alias) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (entity_id, alias),
    )


def bump_mention(cur, entity_id: int) -> None:
    cur.execute(
        """
        UPDATE entities
        SET mention_count = mention_count + 1,
            provisional = CASE WHEN mention_count + 1 >= 2 THEN false ELSE provisional END
        WHERE id = %s
        """,
        (entity_id,),
    )


def office_holders(cur, entity_id: int, as_of: str | None = None,
                   since: str | None = None) -> list[dict]:
    # Current holders on as_of, plus anyone whose term overlapped [since, as_of].
    cur.execute(
        """
        SELECT r.*, s.canonical AS src_name, s.type AS src_type,
               d.canonical AS dst_name, d.type AS dst_type
        FROM entity_relations r
        JOIN entities s ON s.id = r.src_entity_id
        JOIN entities d ON d.id = r.dst_entity_id
        WHERE r.rel_type IN ('president_of','pm_of','monarch_of','leader_of','minister_of')
          AND (r.dst_entity_id = %s OR r.src_entity_id = %s)
          AND (r.valid_from IS NULL OR %s::date IS NULL OR r.valid_from <= %s::date)
          AND (
                r.valid_to IS NULL
                OR %s::date IS NULL
                OR r.valid_to >= COALESCE(%s::date, %s::date)
          )
        ORDER BY r.valid_from NULLS FIRST, r.id
        """,
        (entity_id, entity_id, as_of, as_of, as_of, since, as_of),
    )
    return [dict(r) for r in cur.fetchall()]
