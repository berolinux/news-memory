"""Constrained JSON completion against a llama.cpp / OpenAI-compatible server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "headline", "summary", "summary_en", "lang", "happened_at", "event_type", "tags",
        "importance", "geo_countries", "entities", "relations", "pair_topics",
    ],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "summary_en": {"type": "string"},
        "lang": {"type": "string"},
        "happened_at": {"type": "string"},
        "event_type": {
            "type": "string",
            "enum": ["conflict", "diplomacy", "politics", "economy",
                     "disaster", "legal", "science", "society", "other"],
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "war", "sanctions", "ceasefire", "treaty", "election",
                    "coup", "resignation", "appointment", "protest", "inflation",
                    "tax", "budget", "recession", "scandal", "court",
                    "legislation", "strike", "epidemic", "disaster", "speech",
                    "refugees", "energy", "trade", "other",
                ],
            },
        },
        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
        "geo_countries": {"type": "array", "items": {"type": "string"}},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type", "role", "aliases", "country_iso"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string",
                             "enum": ["country", "person", "org", "place", "armed_group", "other"]},
                    "role": {"type": "string",
                             "enum": ["actor", "target", "affected", "issuer", "other"]},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "country_iso": {"type": ["string", "null"]},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["src", "rel", "dst", "valid_from", "valid_to", "fact"],
                "properties": {
                    "src": {"type": "string"},
                    "rel": {"type": "string",
                            "enum": ["president_of", "pm_of", "monarch_of", "minister_of",
                                     "leader_of", "member_of", "capital_of", "ally_of",
                                     "rival_of", "part_of", "other"]},
                    "dst": {"type": "string"},
                    "valid_from": {"type": ["string", "null"]},
                    "valid_to": {"type": ["string", "null"]},
                    "fact": {"type": "string"},
                },
            },
        },
        "pair_topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["a", "b", "kind"],
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                    "kind": {"type": "string",
                             "enum": ["conflict", "diplomacy", "politics", "economy", "legal", "other"]},
                },
            },
        },
    },
}


def _headers() -> dict:
    hdrs = {"Content-Type": "application/json", "User-Agent": config.USER_AGENT}
    if config.EXTRACT_API_KEY:
        hdrs["Authorization"] = "Bearer " + config.EXTRACT_API_KEY
    return hdrs


def _post(url: str, payload: dict, timeout: int | None = None) -> dict | None:
    if timeout is None:
        timeout = config.EXTRACT_TIMEOUT
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return {"_unavailable": True, "error": "model loading"}
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _get(url: str, timeout: int = 2):
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    return urllib.request.urlopen(req, timeout=timeout)


def _content(data: dict | None) -> str | None:
    if not data:
        return None
    if data.get("choices"):
        ch = data["choices"][0]
        msg = ch.get("message") or {}
        if msg.get("content"):
            return msg["content"]
        if ch.get("text"):
            return ch["text"]
    if data.get("content"):
        return data["content"]
    return None


def _parse_json(text: str | None) -> dict | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def complete_json(user: str, system: str, grammar_file: str | None = None,
                  json_schema: dict | None = None) -> dict | None:
    base = (config.EXTRACT_URL or "").rstrip("/")
    if not base:
        return None
    grammar = None
    if grammar_file:
        path = config.ROOT / grammar_file
        if path.is_file():
            grammar = path.read_text(encoding="utf-8")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    payload = {
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": config.EXTRACT_MAX_TOKENS,
    }
    if config.EXTRACT_THINKING is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": config.EXTRACT_THINKING}
    if json_schema is not None:
        payload["json_schema"] = json_schema
    elif grammar:
        payload["grammar"] = grammar

    data = _post(base + "/v1/chat/completions", payload)
    if data and data.get("_unavailable"):
        return None
    parsed = _parse_json(_content(data))
    if parsed is not None:
        return parsed

    # completion endpoint fallback
    prompt = f"{system}\n\n{user}\n"
    comp = {"prompt": prompt, "temperature": 0.1, "n_predict": config.EXTRACT_MAX_TOKENS}
    if grammar:
        comp["grammar"] = grammar
    data = _post(base + "/completion", comp)
    return _parse_json(_content(data) or (data or {}).get("content"))


def extract_article(title: str, published: str, source: str, body: str,
                    known_entities: list[dict]) -> dict | None:
    system = config.read_text("prompts/extract.txt")
    lines = []
    for e in known_entities[:40]:
        extra = f" iso={e['country_iso']}" if e.get("country_iso") else ""
        aliases = e.get("aliases") or []
        alias_s = (", aliases: " + "; ".join(aliases[:8])) if aliases else ""
        lines.append(f"- id={e['id']} {e['canonical']} ({e['type']}){extra}{alias_s}")
    known = "\n".join(lines) or "(none matched by gazetteer)"
    user = (
        f"Source: {source}\nPublished: {published}\nTitle: {title}\n\n"
        f"Known entities already in the text:\n{known}\n\n"
        f"Article:\n{body[:12000]}\n"
    )
    return complete_json(
        user,
        system,
        grammar_file="grammars/extract.gbnf",
        json_schema=EXTRACT_SCHEMA,
    )


def rewrite_status(title: str, old_status: str, timeline: list[str], new_event: str) -> str | None:
    system = config.read_text("prompts/dossier_status.txt").replace(
        "{pivot_lang}", config.PIVOT_LANG
    )
    bullets = "\n".join(f"- {b}" for b in timeline[-40:])
    user = (
        f"Dossier: {title}\n\nOld current_status:\n{old_status or '(empty)'}\n\n"
        f"Timeline:\n{bullets or '(none)'}\n\nNew event:\n{new_event}\n"
    )
    data = complete_json(
        user,
        system,
        grammar_file="grammars/dossier_status.gbnf",
    )
    if not data:
        return None
    return (data.get("current_status") or "").strip() or None


_extract_ok: bool | None = None


def extract_available() -> bool:
    global _extract_ok
    if _extract_ok is not None:
        return _extract_ok
    base = (config.EXTRACT_URL or "").rstrip("/")
    if not base:
        _extract_ok = False
        return False
    try:
        with _get(base + "/health", timeout=2) as resp:
            _extract_ok = 200 <= resp.status < 300
            return _extract_ok
    except urllib.error.HTTPError as e:
        # 503 = weights still loading; the endpoint is the right one.
        if e.code == 503:
            _extract_ok = None
            return False
        if e.code in (401, 403):
            _extract_ok = False
            return False
    except Exception:
        pass
    try:
        with _get(base + "/v1/models", timeout=2) as resp:
            _extract_ok = 200 <= resp.status < 300
            return _extract_ok
    except Exception:
        _extract_ok = False
        return False
