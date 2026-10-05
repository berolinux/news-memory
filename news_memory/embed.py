"""Qwen3-Embedding-0.6B via llama.cpp /v1/embeddings, or in-process transformers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterable

from . import config

_local_model = None
_local_tok = None
_http_ok: bool | None = None


def _query_text(text: str) -> str:
    return f"Instruct: {config.QUERY_INSTRUCT}\nQuery:{text}"


def _http_embed(texts: list[str]) -> list[list[float]] | None:
    global _http_ok
    url = (config.EMBED_URL or "").rstrip("/")
    if not url or _http_ok is False:
        return None
    payload = json.dumps({"input": texts, "encoding_format": "float"}).encode()
    req = urllib.request.Request(
        url + "/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": config.USER_AGENT},
        method="POST",
    )
    timeout = 3 if _http_ok is None else 120
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        _http_ok = False
        return None
    items = data.get("data") or []
    if len(items) != len(texts):
        return None
    _http_ok = True
    items = sorted(items, key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


def _load_local():
    global _local_model, _local_tok
    if _local_model is not None:
        return _local_model, _local_tok
    import torch
    from transformers import AutoModel, AutoTokenizer

    path = config.EMBED_MODEL
    if not path or not __import__("pathlib").Path(path).exists():
        raise FileNotFoundError(path)
    _local_tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True, padding_side="left")
    _local_model = AutoModel.from_pretrained(path, trust_remote_code=True)
    _local_model.eval()
    device = config.EMBED_DEVICE or "cpu"
    if device == "cpu":
        _local_model.to("cpu")
    else:
        _local_model.to(device)
    return _local_model, _local_tok


def _local_embed(texts: list[str]) -> list[list[float]]:
    import torch
    import torch.nn.functional as F

    model, tok = _load_local()
    device = next(model.parameters()).device
    batch = tok(texts, padding=True, truncation=True, max_length=2048, return_tensors="pt")
    batch = {k: v.to(device) for k, v in batch.items()}
    with torch.no_grad():
        last = model(**batch).last_hidden_state[:, -1]
        last = F.normalize(last.float(), p=2, dim=1)
    return last.cpu().tolist()


def embed(texts: Iterable[str], query: bool = False) -> list[list[float]]:
    texts = [(_query_text(t) if query else t) for t in texts]
    if not texts:
        return []
    # llama.cpp first (cheap if the embed server is up)
    got = _http_embed(texts)
    if got is not None:
        return got
    if not config.EMBED_LOCAL:
        raise RuntimeError("no embedding server and NEWS_MEMORY_EMBED_LOCAL is not set")
    return _local_embed(texts)


def embed_one(text: str, query: bool = False) -> list[float]:
    return embed([text], query=query)[0]


def available() -> str | None:
    if _http_embed(["ping"]) is not None:
        return "http"
    if config.EMBED_LOCAL:
        from pathlib import Path
        if Path(config.EMBED_MODEL).exists():
            return "local"
    return None
