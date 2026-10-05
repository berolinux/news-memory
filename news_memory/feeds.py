"""RSS / Atom / Wikipedia current-events fetchers."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

from . import config

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    from lxml import html as lxml_html
except ImportError:
    lxml_html = None


def _open(url: str, headers: dict | None = None, timeout: int = 30):
    hdrs = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    return urllib.request.urlopen(req, timeout=timeout)


def _parse_date(value) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc)
    try:
        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(str(value)[:26], fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def simhash64(text: str) -> int:
    text = re.sub(r"\s+", " ", (text or "").lower()).strip()
    grams = [text[i:i + 3] for i in range(max(len(text) - 2, 1))]
    if not grams:
        return 0
    acc = [0] * 64
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
        for b in range(64):
            acc[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b, v in enumerate(acc):
        if v >= 0:
            out |= 1 << b
    # fit in signed bigint
    if out >= 2**63:
        out -= 2**64
    return out


def strip_html(raw: str) -> str:
    raw = raw or ""
    if lxml_html is not None:
        try:
            doc = lxml_html.fromstring(raw)
            for bad in doc.xpath("//script|//style|//noscript"):
                parent = bad.getparent()
                if parent is not None:
                    parent.remove(bad)
            text = " ".join(doc.xpath("//text()"))
            return re.sub(r"\s+", " ", text).strip()
        except Exception:
            pass
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def fetch_fulltext(url: str) -> str | None:
    try:
        with _open(url, timeout=20) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                return None
            raw = resp.read(400_000)
    except (urllib.error.URLError, TimeoutError):
        return None
    try:
        page = raw.decode("utf-8", errors="replace")
    except Exception:
        return None
    if lxml_html is None:
        return strip_html(page)[:20000]
    try:
        doc = lxml_html.fromstring(page)
        chunks = []
        for sel in ('//article', '//*[@role="main"]', '//main', '//div[contains(@class,"article")]'):
            for node in doc.xpath(sel):
                chunks.append(" ".join(node.xpath(".//p//text()")))
        text = max(chunks, key=len) if chunks else " ".join(doc.xpath("//p//text()"))
        text = re.sub(r"\s+", " ", text).strip()
        return text[:20000] or None
    except Exception:
        return strip_html(page)[:20000]


def fetch_rss(url: str, etag=None, last_modified=None) -> tuple[list[dict], str | None, str | None]:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with _open(url, headers=headers) as resp:
            new_etag = resp.headers.get("ETag")
            new_lm = resp.headers.get("Last-Modified")
            raw = resp.read()
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return [], etag, last_modified
        raise
    if status == 304:
        return [], etag, last_modified
    items = []
    if feedparser is None:
        return items, new_etag, new_lm
    parsed = feedparser.parse(raw)
    for e in parsed.entries:
        link = e.get("link") or e.get("id") or ""
        title = strip_html(e.get("title") or "")
        summary = strip_html(e.get("summary") or e.get("description") or "")
        published = _parse_date(e.get("published") or e.get("updated") or e.get("created"))
        items.append({
            "url": link,
            "title": title,
            "summary": summary,
            "published_at": published,
            "lang": (getattr(parsed.feed, "language", None) or "")[:8] or None,
        })
    return items, new_etag, new_lm


_WIKI_BULLET = re.compile(r"^\*\s*(.+)$", re.M)


def fetch_wikipedia_current_events(url: str) -> list[dict]:
    try:
        with _open(url) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    wikitext = (data.get("parse") or {}).get("wikitext", {})
    if isinstance(wikitext, dict):
        wikitext = wikitext.get("*") or ""
    items = []
    today = datetime.now(timezone.utc)
    host = urlparse(url).netloc or "en.wikipedia.org"
    lang = host.split(".")[0] if host.endswith(".wikipedia.org") else None
    for i, m in enumerate(_WIKI_BULLET.findall(wikitext or "")):
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", m)
        text = re.sub(r"\{\{[^}]+\}\}", "", text)
        text = strip_html(text)
        if len(text) < 40:
            continue
        url_i = f"https://{host}/wiki/Portal:Current_events#{today.date().isoformat()}-{i}"
        items.append({
            "url": url_i,
            "title": text[:180],
            "summary": text,
            "published_at": today,
            "lang": lang,
        })
    return items[:40]
