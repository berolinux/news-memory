#!/usr/bin/env python
"""OpenAI-compatible front for llama-server that runs the news-memory tool loop.

llama.cpp will not execute MCP tools on /v1/chat/completions (no server-side
agent loop). Point clients at this proxy instead of :8080.

  base_url = http://127.0.0.1:8081/v1
"""

from __future__ import annotations

import json
import sys
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_memory import config, tools  # noqa: E402

MAX_ROUNDS = config.CHAT_MAX_ROUNDS
UPSTREAM = (config.LLAMA_URL or "http://127.0.0.1:8080").rstrip("/")


def _auth_headers(incoming: dict | None = None) -> dict:
    hdrs = {"Content-Type": "application/json", "User-Agent": config.USER_AGENT}
    if incoming:
        for k, v in incoming.items():
            if k.lower() == "authorization" and v:
                hdrs["Authorization"] = v
                break
    if "Authorization" not in hdrs and config.EXTRACT_API_KEY:
        hdrs["Authorization"] = "Bearer " + config.EXTRACT_API_KEY
    return hdrs


def _openai_tools() -> list[dict]:
    spec = json.loads((config.ROOT / "data" / "tools.json").read_text(encoding="utf-8"))
    out = []
    for t in spec.get("tools") or []:
        fn = dict(t.get("function") or {})
        if not fn.get("name"):
            continue
        # Same names llama-server advertises via MCP (news_<tool>).
        fn["name"] = "news_" + fn["name"]
        out.append({"type": "function", "function": fn})
    return out


def _local_name(name: str) -> str:
    return name[5:] if name.startswith("news_") else name


def _run_tool(name: str, arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    local = _local_name(name)
    try:
        result = tools.call(local, arguments)
        return json.dumps(result, default=str, ensure_ascii=False)
    except KeyError:
        return json.dumps({"error": f"unknown tool {name}"})
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"error": str(e)})


def _ensure_system(messages: list) -> list:
    prompt = tools.system_prompt()
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        existing = out[0].get("content") or ""
        if "news tools" not in existing.lower() and "get_background" not in existing:
            out[0]["content"] = prompt + "\n\n" + existing
    else:
        out.insert(0, {"role": "system", "content": prompt})
    return out


def _merge_tools(client_tools) -> list:
    have = set()
    merged = []
    for t in list(client_tools or []) + _openai_tools():
        fn = (t.get("function") or {})
        name = fn.get("name")
        if not name or name in have:
            continue
        have.add(name)
        merged.append(t)
    return merged


def _upstream_chat(payload: dict, headers: dict, timeout: int = 300) -> dict:
    req = Request(
        UPSTREAM + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": {"message": body or str(e), "code": e.code}}
    except (URLError, TimeoutError) as e:
        return {"error": {"message": str(e), "type": "connection_error"}}


def complete(body: dict, incoming_headers: dict | None = None) -> dict:
    headers = _auth_headers(incoming_headers)
    messages = _ensure_system(list(body.get("messages") or []))
    payload = dict(body)
    payload["messages"] = messages
    payload["tools"] = _merge_tools(body.get("tools"))
    payload.pop("stream", None)
    if "tool_choice" not in payload:
        payload["tool_choice"] = "auto"

    last = None
    for _round in range(MAX_ROUNDS):
        last = _upstream_chat(payload, headers)
        if last.get("error"):
            return last
        choice = (last.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            return last
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": calls,
        })
        for call in calls:
            fn = call.get("function") or {}
            tool_id = call.get("id") or ("call_" + uuid.uuid4().hex[:12])
            text = _run_tool(fn.get("name") or "", fn.get("arguments"))
            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": text,
            })
        payload["messages"] = messages
        # After the first tool use, let the model answer or call again.
        payload["tool_choice"] = "auto"
    return last or {"error": {"message": "tool loop exhausted"}}


def _sse(final: dict) -> bytes:
    msg = ((final.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") or ""
    chunk = {
        "id": final.get("id") or "chatcmpl-proxy",
        "object": "chat.completion.chunk",
        "created": final.get("created"),
        "model": final.get("model"),
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    return (
        f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        "data: [DONE]\n\n"
    ).encode()


def _proxy(handler: BaseHTTPRequestHandler) -> None:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b""
    url = UPSTREAM + handler.path
    hdrs = _auth_headers({k: handler.headers[k] for k in handler.headers.keys()})
    # drop hop-by-hop
    hdrs.pop("Content-Length", None)
    if handler.command == "GET" or handler.command == "HEAD":
        req = Request(url, headers=hdrs, method=handler.command)
    else:
        if raw and "Content-Type" not in {k.title(): 1 for k in hdrs}:
            hdrs["Content-Type"] = handler.headers.get("Content-Type") or "application/json"
        req = Request(url, data=raw or None, headers=hdrs, method=handler.command)
    try:
        with urlopen(req, timeout=300) as resp:
            body = resp.read()
            handler.send_response(resp.status)
            ctype = resp.headers.get("Content-Type") or "application/json"
            handler.send_header("Content-Type", ctype)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            if handler.command != "HEAD":
                handler.wfile.write(body)
    except HTTPError as e:
        body = e.read()
        handler.send_response(e.code)
        handler.send_header("Content-Type", e.headers.get("Content-Type") or "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as e:
        err = json.dumps({"error": {"message": str(e)}}).encode()
        handler.send_response(502)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(err)))
        handler.end_headers()
        handler.wfile.write(err)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        if self.path in ("/", "/health"):
            body = json.dumps({"ok": True, "upstream": UPSTREAM, "role": "news-memory chat proxy"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        _proxy(self)

    def do_HEAD(self):
        _proxy(self)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/v1/chat/completions":
            _proxy(self)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            err = b'{"error":{"message":"invalid json"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return
        incoming = {k: self.headers[k] for k in self.headers.keys()}
        result = complete(body, incoming)
        if body.get("stream") and not result.get("error"):
            payload = _sse(result)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps(result, default=str, ensure_ascii=False).encode()
        code = 200 if not result.get("error") else 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    host = config.CHAT_HOST
    port = config.CHAT_PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"news-memory chat proxy on http://{host}:{port}  ->  {UPSTREAM}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
