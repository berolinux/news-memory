#!/usr/bin/env python
"""Stand-in for llama-server while the news archive is being refreshed.

Every request gets 503. API-shaped paths get a JSON error; a browser gets
the same sentence as plain text.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MESSAGE = "The news data is being updated. Try again later."


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _wants_json(self) -> bool:
        path = self.path.split("?", 1)[0]
        if path == "/v1" or path.startswith("/v1/"):
            return True
        accept = (self.headers.get("Accept") or "").lower()
        return "application/json" in accept

    def _body(self) -> tuple[bytes, str]:
        if self._wants_json():
            payload = {
                "error": {
                    "message": MESSAGE,
                    "type": "unavailable_error",
                    "code": 503,
                }
            }
            return json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8"
        return (MESSAGE + "\n").encode("utf-8"), "text/plain; charset=utf-8"

    def _drain(self) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if n <= 0 or n > 1_000_000:
            return
        remaining = n
        while remaining:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _reply(self) -> None:
        self._drain()
        body, ctype = self._body()
        self.send_response(503)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._reply()

    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_HEAD = do_GET
    do_PATCH = do_GET
    do_OPTIONS = do_GET


def main() -> int:
    p = argparse.ArgumentParser(description="Tell clients the news archive is being updated")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"updating server on http://{args.host}:{args.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
