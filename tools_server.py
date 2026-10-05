#!/usr/bin/env python
"""Tiny HTTP front for the retrieval tools (llama.cpp / any agent)."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_memory import config, tools  # noqa: E402


def _dump(obj) -> bytes:
    return json.dumps(obj, default=str, ensure_ascii=False).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/health"):
            self._send(200, _dump({"ok": True, "tools": list(tools.DISPATCH)}))
            return
        if u.path == "/prompt":
            self._send(200, _dump({"system": tools.system_prompt()}))
            return
        if u.path == "/tools":
            spec = json.loads((config.ROOT / "data" / "tools.json").read_text(encoding="utf-8"))
            self._send(200, _dump(spec))
            return
        qs = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(u.query).items()}
        name = u.path.strip("/")
        if name in tools.DISPATCH:
            try:
                self._send(200, _dump(tools.call(name, qs)))
            except Exception as e:
                self._send(400, _dump({"error": str(e)}))
            return
        self._send(404, _dump({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, _dump({"error": "invalid json"}))
            return
        u = urlparse(self.path)
        name = payload.get("name") or payload.get("tool") or u.path.strip("/")
        args = payload.get("arguments") or payload.get("args") or payload
        if name in ("arguments", "args", "name", "tool"):
            self._send(400, _dump({"error": "missing tool name"}))
            return
        if name not in tools.DISPATCH:
            self._send(404, _dump({"error": f"unknown tool {name}"}))
            return
        # strip wrapper keys if the whole payload was used as args
        if args is payload:
            args = {k: v for k, v in payload.items() if k not in ("name", "tool", "arguments", "args")}
        try:
            self._send(200, _dump(tools.call(name, args)))
        except Exception as e:
            self._send(400, _dump({"error": str(e)}))


def main() -> int:
    host = config.TOOLS_HOST
    port = config.TOOLS_PORT
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"news-memory tools on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
