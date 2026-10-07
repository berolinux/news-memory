#!/usr/bin/env python
"""One ingest pass, or a loop. Safe to run from cron / systemd."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_memory import ingest, seed  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch and file news into news_memory")
    p.add_argument("--loop", type=int, metavar="SECONDS", help="repeat every N seconds")
    p.add_argument("--no-body", action="store_true", help="do not fetch full article HTML")
    p.add_argument("--force", action="store_true", help="ignore per-feed interval")
    p.add_argument("--embed-pending", action="store_true", help="embed entities still missing vectors")
    p.add_argument(
        "--embed-filed",
        action="store_true",
        help="embed articles, mentioned entities, and dossiers that have no vector yet",
    )
    args = p.parse_args()
    if args.embed_filed:
        from news_memory.db import connect
        import psycopg2.extras

        conn = connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            counts = seed.embed_filed(cur)
            conn.commit()
            print(
                "embedded {articles} articles, {entities} entities, {dossiers} dossiers".format(
                    **counts
                )
            )
        finally:
            conn.close()
        return 0
    if args.embed_pending:
        from news_memory import config as cfg
        from news_memory.db import connect
        import psycopg2.extras

        cfg.EMBED_LOCAL = True
        print(f"in-process embeddings on {cfg.EMBED_DEVICE}", flush=True)

        conn = connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            n = seed.embed_entities(cur)
            conn.commit()
            print(f"embedded {n} entities")
        finally:
            conn.close()
        return 0

    def once():
        n = ingest.run_once(fetch_body=not args.no_body, force=args.force)
        print(f"ingested {n} new articles")
        return n

    if args.loop:
        while True:
            try:
                once()
            except Exception as e:
                print(f"ingest error: {e}", file=sys.stderr)
            time.sleep(args.loop)
    else:
        once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
