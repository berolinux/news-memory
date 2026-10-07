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
_last_http_error: str | None = None


def unavailable_message() -> str:
    msg = "no embedding server and NEWS_MEMORY_EMBED_LOCAL is not set"
    if _last_http_error:
        return f"{msg} ({_last_http_error})"
    return msg


def _query_text(text: str) -> str:
    return f"Instruct: {config.QUERY_INSTRUCT}\nQuery:{text}"


def _http_embed(texts: list[str]) -> list[list[float]] | None:
    global _http_ok, _last_http_error
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
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode("utf-8", "replace").replace("\n", " ")
        _last_http_error = f"HTTP {e.code}: {detail}".strip()
        _http_ok = False
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        _last_http_error = str(e)
        _http_ok = False
        return None
    items = data.get("data") or []
    if len(items) != len(texts):
        _last_http_error = f"embedding server returned {len(items)} vectors for {len(texts)} inputs"
        return None
    _http_ok = True
    items = sorted(items, key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


# 4×2048 padded tokens fits on the 16 GB card. 16×2048 does not: this torch
# build has no memory-efficient attention, and every row is padded to the
# longest text in the batch.
_GPU_TOKEN_BUDGET = 8192
_MAX_LEN = 2048


def resolve_device(name: str | None) -> str:
    text = (name or "cpu").strip()
    low = text.lower()
    if low in ("gpu", "hip"):
        return "cuda"
    if low.startswith("vulkan"):
        raise RuntimeError(
            "NEWS_MEMORY_EMBED_DEVICE is a torch device (cpu or cuda). "
            "A llama.cpp device such as Vulkan0 belongs in NEWS_MEMORY_EMBED_SERVER_DEVICE."
        )
    return text


def on_gpu(device: str) -> bool:
    text = device.lower()
    return text != "cpu" and not text.startswith("cpu")


def pack_batches(lengths: list[int], budget: int = _GPU_TOKEN_BUDGET) -> list[list[int]]:
    """Group indices so batch_size * longest_length stays within budget."""
    chunks: list[list[int]] = []
    current: list[int] = []
    current_max = 0
    for i, raw in enumerate(lengths):
        n = max(1, min(_MAX_LEN, raw))
        new_max = max(current_max, n)
        if current and new_max * (len(current) + 1) > budget:
            chunks.append(current)
            current = [i]
            current_max = n
        else:
            current.append(i)
            current_max = new_max
    if current:
        chunks.append(current)
    return chunks


def _local_chat_running() -> bool:
    from urllib.parse import urlparse

    base = (config.EXTRACT_URL or "").rstrip("/")
    if not base:
        return False
    host = (urlparse(base).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return False
    req = urllib.request.Request(
        base + "/health",
        method="GET",
        headers={"User-Agent": config.USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _load_local():
    global _local_model, _local_tok
    if _local_model is not None:
        return _local_model, _local_tok
    path = config.EMBED_MODEL
    if not path or not __import__("pathlib").Path(path).exists():
        raise FileNotFoundError(path)
    device = resolve_device(config.EMBED_DEVICE)
    # Before importing torch. A HIP context on this card fights the chat model.
    if on_gpu(device) and _local_chat_running():
        raise RuntimeError(
            "NEWS_MEMORY_EMBED_DEVICE is a GPU and llama.service is using that card. "
            "Stop llama.service, then run the gazetteer pass again."
        )
    import torch
    from transformers import AutoModel, AutoTokenizer

    _local_tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True, padding_side="left")
    load_kwargs = {"trust_remote_code": True}
    if on_gpu(device):
        # The 8192-token budget was measured in bf16. fp32 attention does not fit.
        load_kwargs["dtype"] = torch.bfloat16
    _local_model = AutoModel.from_pretrained(path, **load_kwargs)
    _local_model.eval()
    if device == "cpu":
        _local_model.to("cpu")
    else:
        _local_model.to(device)
    return _local_model, _local_tok


def _forward(model, tok, texts: list[str], device) -> list[list[float]]:
    import torch
    import torch.nn.functional as F

    batch = tok(texts, padding=True, truncation=True, max_length=_MAX_LEN, return_tensors="pt")
    batch = {k: v.to(device) for k, v in batch.items()}
    with torch.no_grad():
        last = model(**batch).last_hidden_state[:, -1]
        last = F.normalize(last.float(), p=2, dim=1)
    return last.cpu().tolist()


def _local_embed(texts: list[str]) -> list[list[float]]:
    model, tok = _load_local()
    device = next(model.parameters()).device
    if not on_gpu(str(device)) or len(texts) <= 1:
        return _forward(model, tok, texts, device)
    lengths = []
    for text in texts:
        ids = tok(text, truncation=True, max_length=_MAX_LEN, add_special_tokens=True)["input_ids"]
        lengths.append(len(ids))
    out: list[list[float] | None] = [None] * len(texts)
    for idxs in pack_batches(lengths):
        vecs = _forward(model, tok, [texts[i] for i in idxs], device)
        for i, vec in zip(idxs, vecs):
            out[i] = vec
    if any(vec is None for vec in out):
        raise RuntimeError("embedding batch was incomplete")
    return [vec for vec in out if vec is not None]


def embed(texts: Iterable[str], query: bool = False) -> list[list[float]]:
    texts = [(_query_text(t) if query else t) for t in texts]
    if not texts:
        return []
    # llama.cpp first (cheap if the embed server is up)
    got = _http_embed(texts)
    if got is not None:
        return got
    if not config.EMBED_LOCAL:
        raise RuntimeError(unavailable_message())
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
