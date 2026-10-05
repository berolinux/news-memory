import os
from pathlib import Path


ROOT = Path(os.environ.get("NEWS_MEMORY_HOME", Path(__file__).resolve().parent.parent))


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        os.environ.setdefault(key, val)


_load_env_file(ROOT / "config.env")


def getenv(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val


DB_NAME = getenv("NEWS_MEMORY_DB", "news_memory")
DB_USER = getenv("NEWS_MEMORY_DB_USER") or "news-memory"
DB_HOST = getenv("NEWS_MEMORY_DB_HOST", "/run/postgresql")
DB_PORT = getenv("NEWS_MEMORY_DB_PORT", "5432")
DB_PASSWORD = getenv("NEWS_MEMORY_DB_PASSWORD")

EMBED_URL = getenv("NEWS_MEMORY_EMBED_URL", "http://127.0.0.1:8092")
EMBED_MODEL = getenv(
    "NEWS_MEMORY_EMBED_MODEL",
    str(ROOT / "models" / "Qwen3-Embedding-0.6B"),
)
EMBED_DEVICE = getenv("NEWS_MEMORY_EMBED_DEVICE", "cpu")
EMBED_LOCAL = (getenv("NEWS_MEMORY_EMBED_LOCAL", "0") or "0").lower() in ("1", "true", "yes")
EMBED_DIM = int(getenv("NEWS_MEMORY_EMBED_DIM", "1024"))
QUERY_INSTRUCT = getenv(
    "NEWS_MEMORY_QUERY_INSTRUCT",
    "Given a news question, retrieve relevant events, dossiers, and background.",
)

EXTRACT_URL = getenv("NEWS_MEMORY_EXTRACT_URL", "http://127.0.0.1:8080")
LLAMA_SYSCONFIG = getenv("NEWS_MEMORY_LLAMA_SYSCONFIG", "/etc/sysconfig/llama-server")
PIVOT_LANG = (getenv("NEWS_MEMORY_PIVOT_LANG", "en") or "en").lower()[:8]


def _api_key_from_sysconfig(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() != "API_KEY":
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        return val or None
    return None


EXTRACT_API_KEY = getenv("NEWS_MEMORY_EXTRACT_API_KEY") or _api_key_from_sysconfig(LLAMA_SYSCONFIG or "")
TOOLS_HOST = getenv("NEWS_MEMORY_TOOLS_HOST", "127.0.0.1")
TOOLS_PORT = int(getenv("NEWS_MEMORY_TOOLS_PORT", "8091"))
CHAT_HOST = getenv("NEWS_MEMORY_CHAT_HOST", "127.0.0.1")
CHAT_PORT = int(getenv("NEWS_MEMORY_CHAT_PORT", "8081"))
LLAMA_URL = getenv("NEWS_MEMORY_LLAMA_URL", "http://127.0.0.1:8080")
CHAT_MAX_ROUNDS = int(getenv("NEWS_MEMORY_CHAT_MAX_ROUNDS", "6"))

USER_AGENT = getenv(
    "NEWS_MEMORY_USER_AGENT",
    "news-memory/1.0 (local research archive)",
)

ISO_JSON = getenv(
    "NEWS_MEMORY_ISO_JSON",
    "/usr/share/iso-codes/json/iso_3166-1.json",
)


def dsn() -> str:
    parts = [f"dbname={DB_NAME}", f"user={DB_USER}"]
    if DB_HOST:
        if DB_HOST.startswith("/"):
            parts.append(f"host={DB_HOST}")
        else:
            parts.append(f"host={DB_HOST}")
            parts.append(f"port={DB_PORT}")
    if DB_PASSWORD:
        parts.append(f"password={DB_PASSWORD}")
    return " ".join(parts)


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")
