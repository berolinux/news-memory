#!/usr/bin/env python
"""stdio MCP server for llama.cpp (--mcp-servers-config). NDJSON, not LSP headers."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_memory import tools  # noqa: E402

# llama.cpp prefixes tools as <server>_<name>. Keep names short.
TOOL_META = {
    "search_dossiers": {
        "description": (
            "Find living topic dossiers (country, person, or pair). "
            "Use for 'what is going on with X' or 'relations between A and B'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    "search_events": {
        "description": (
            "Search dated events in any language. English keywords need not "
            "appear in the source. Pass a date in the query (e.g. July 2027) "
            "or date_from/date_to. Pass country/person in entities when known."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "string"}},
                "event_type": {"type": "string"},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    "get_timeline": {
        "description": "Ordered timeline for named entities.",
        "schema": {
            "type": "object",
            "properties": {
                "entities": {"type": "array", "items": {"type": "string"}},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["entities"],
        },
    },
    "get_background": {
        "description": (
            "Assemble background for why/how/current-state questions. "
            "Use for 'why was the president ousted', 'context of A vs B', "
            "'what is the current VAT in Liechtenstein', 'major wildfires in July 2027'."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "as_of": {"type": "string"},
                "years": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    "get_article": {
        "description": "Fetch one source article by id from a timeline or event.",
        "schema": {
            "type": "object",
            "properties": {"article_id": {"type": "integer"}},
            "required": ["article_id"],
        },
    },
    "resolve_entity": {
        "description": "Look up a country, person, org, or place, including aliases.",
        "schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}


def _reply(msg_id, result=None, error=None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out, default=str, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(req: dict) -> None:
    method = req.get("method")
    msg_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        _reply(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "news-memory", "version": "1.0"},
            "instructions": tools.system_prompt(),
        })
        return
    if method == "notifications/initialized" or method == "initialized":
        return
    if method == "tools/list":
        listed = []
        for name, meta in TOOL_META.items():
            listed.append({
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            })
        _reply(msg_id, {"tools": listed})
        return
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in TOOL_META:
            _reply(msg_id, result={
                "content": [{"type": "text", "text": f"unknown tool {name}"}],
                "isError": True,
            })
            return
        try:
            data = tools.call(name, args)
            text = json.dumps(data, default=str, ensure_ascii=False)
            _reply(msg_id, result={"content": [{"type": "text", "text": text}]})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            _reply(msg_id, result={
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            })
        return
    if method == "ping":
        _reply(msg_id, {})
        return
    if msg_id is not None:
        _reply(msg_id, error={"code": -32601, "message": f"unknown method {method}"})


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"bad json: {e}\n")
            continue
        try:
            _handle(req)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            if isinstance(req, dict) and "id" in req:
                _reply(req["id"], error={"code": -32603, "message": "internal error"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
