#!/bin/bash
# Optional llama.cpp embedding server for Qwen3-Embedding-0.6B.
# setup.sh does not require this: the worker can load the HF model in-process.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
[ -f "$ROOT/config.env" ] && . "$ROOT/config.env"
MODEL=${NEWS_MEMORY_EMBED_GGUF:-$ROOT/models/Qwen3-Embedding-0.6B-f16.gguf}
SRC=${NEWS_MEMORY_EMBED_MODEL:-$ROOT/models/Qwen3-Embedding-0.6B}
HOST=${NEWS_MEMORY_EMBED_HOST:-127.0.0.1}
PORT=${NEWS_MEMORY_EMBED_BIND:-8092}

if [ ! -f "$MODEL" ]; then
	if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
		echo "error: no GGUF at $MODEL and no HF dir NEWS_MEMORY_EMBED_MODEL" >&2
		exit 1
	fi
	need_convert=1
	if ! command -v llama-convert-hf-to-gguf >/dev/null 2>&1; then
		echo "error: llama-convert-hf-to-gguf not found" >&2
		exit 1
	fi
	mkdir -p "$ROOT/models"
	echo "converting $SRC -> $MODEL"
	llama-convert-hf-to-gguf --outfile "$MODEL" --outtype f16 "$SRC"
fi

exec llama-server \
	--model "$MODEL" \
	--host "$HOST" \
	--port "$PORT" \
	--embedding \
	--pooling last \
	--embd-normalize 2 \
	--ctx-size 2048 \
	--parallel 4 \
	"$@"
