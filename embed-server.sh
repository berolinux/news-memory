#!/bin/bash
# Optional llama.cpp embedding server for Qwen3-Embedding-0.6B.
# setup.sh does not require this: the worker can load the HF model in-process.
# NEWS_MEMORY_EMBED_DEVICE is the in-process torch device (cpu or cuda).
# NEWS_MEMORY_EMBED_SERVER_DEVICE, when set, is this server's llama.cpp --device.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
[ -f "$ROOT/config.env" ] && . "$ROOT/config.env"
MODEL=${NEWS_MEMORY_EMBED_GGUF:-$ROOT/models/Qwen3-Embedding-0.6B-f16.gguf}
SRC=${NEWS_MEMORY_EMBED_MODEL:-$ROOT/models/Qwen3-Embedding-0.6B}
HOST=${NEWS_MEMORY_EMBED_HOST:-127.0.0.1}
PORT=${NEWS_MEMORY_EMBED_BIND:-8092}
PARALLEL=${NEWS_MEMORY_EMBED_SERVER_PARALLEL:-4}
CTX=${NEWS_MEMORY_EMBED_SERVER_CTX:-2048}
DEVICE=${NEWS_MEMORY_EMBED_SERVER_DEVICE:-}
LAYERS=${NEWS_MEMORY_EMBED_GPU_LAYERS:-all}

case "$PARALLEL" in
	''|*[!0-9]*)
		echo "error: NEWS_MEMORY_EMBED_SERVER_PARALLEL must be a whole number" >&2
		exit 1
		;;
esac
case "$CTX" in
	''|*[!0-9]*)
		echo "error: NEWS_MEMORY_EMBED_SERVER_CTX must be a whole number" >&2
		exit 1
		;;
esac

if [ ! -f "$MODEL" ]; then
	if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
		echo "error: no GGUF at $MODEL and no HF dir NEWS_MEMORY_EMBED_MODEL" >&2
		exit 1
	fi
	if ! command -v llama-convert-hf-to-gguf >/dev/null 2>&1; then
		echo "error: llama-convert-hf-to-gguf not found" >&2
		exit 1
	fi
	mkdir -p "$ROOT/models"
	echo "converting $SRC -> $MODEL"
	llama-convert-hf-to-gguf --outfile "$MODEL" --outtype f16 "$SRC"
fi

args=(
	llama-server
	--model "$MODEL"
	--host "$HOST"
	--port "$PORT"
	--embedding
	--pooling last
	--embd-normalize 2
	--ctx-size "$CTX"
	--parallel "$PARALLEL"
)
if [ -n "$DEVICE" ]; then
	args+=(--device "$DEVICE" --n-gpu-layers "$LAYERS")
fi
exec "${args[@]}" "$@"
