#!/usr/bin/env python
"""CLI for the retrieval tools the chat model will call."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from news_memory import tools  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Query the news-memory store")
    p.add_argument("tool", nargs="?", help="search_dossiers|search_events|get_timeline|get_background|get_article|resolve_entity|prompt")
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--entities", nargs="*", default=None)
    p.add_argument("--event-type")
    p.add_argument("--from")
    p.add_argument("--to")
    p.add_argument("--as-of")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--article-id", type=int)
    args = p.parse_args()

    if not args.tool or args.tool == "prompt":
        print(tools.system_prompt())
        if not args.tool:
            print("\nTools: search_dossiers, search_events, get_timeline, get_background, get_article, resolve_entity",
                  file=sys.stderr)
        return 0

    if args.tool == "search_dossiers":
        out = tools.search_dossiers(args.query, limit=args.limit)
    elif args.tool == "search_events":
        out = tools.search_events(
            query=args.query or None,
            entities=args.entities,
            event_type=args.event_type,
            date_from=getattr(args, "from"),
            date_to=args.to,
            limit=args.limit,
        )
    elif args.tool == "get_timeline":
        names = args.entities or ([args.query] if args.query else [])
        out = tools.get_timeline(names, date_from=getattr(args, "from"), date_to=args.to, limit=args.limit)
    elif args.tool == "get_background":
        out = tools.get_background(args.query, as_of=args.as_of, years=args.years)
    elif args.tool == "get_article":
        out = tools.get_article(args.article_id or int(args.query))
    elif args.tool == "resolve_entity":
        out = tools.resolve_entity(args.query)
    else:
        print(f"unknown tool {args.tool}", file=sys.stderr)
        return 2
    print(json.dumps(out, default=str, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
