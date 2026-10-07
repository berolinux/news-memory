#!/bin/bash
# File news on a machine with one GPU.
#
# worker.py is the ingest to keep when the chat server can stay up, for
# example when the database runs on another machine. This script is the
# other path: the chat model and Qwen3-Embedding cannot share a 16 GB card,
# so they take turns.
#
# Order:
#   1. Stop llama.service. Answer on its public port that the data is updating.
#   2. Start the chat model on 127.0.0.1 (thinking on) and file feeds that are due.
#   3. Stop that model. Start the embedding model on 127.0.0.1 and embed
#      the rows that pass touched.
#   4. Stop the embedding model, drop the maintenance reply, start llama.service.
#
# Filing has to run first: the embedding model does not read articles.
# On failure, llama.service is started again when it was running beforehand.
# A finished run starts llama.service either way.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

CLEANED=0
LLAMA_WAS_ACTIVE=0
PLACEHOLDER_PID=
EXTRACT_PID=
EMBED_PID=
WORKER_PID=
SPAWNED_PID=
PUBLIC_HOST=
PUBLIC_PORT=
PRIVATE_PORT=
EMBED_PORT=
PROBE=127.0.0.1
MODEL=
HOST=
PORT=
API_KEY=
LLAMA_OPTIONS=
LLAMA_ARGS=()
REFRESH_MAX_TOKENS=
REFRESH_EXTRACT_TIMEOUT=
EMBED_DEVICE=

usage() {
	cat <<EOF
Usage: ./refresh-news.sh

Stop the public llama server, file feeds that are due, embed the rows that
pass touched, and start the public server again.

The chat model and the embedding model share one GPU, so this script runs
them one after the other. worker.py is unchanged.

Environment:
  NEWS_MEMORY_REFRESH_EXTRACT_PORT     private filing port (default 8088)
  NEWS_MEMORY_REFRESH_EMBED_PORT       private embedding port (default 8092)
  NEWS_MEMORY_REFRESH_MAX_TOKENS       thinking budget per filing call (default 16384)
  NEWS_MEMORY_REFRESH_EXTRACT_TIMEOUT  seconds to wait for one filing call (default 600)
  NEWS_MEMORY_EMBED_SERVER_DEVICE      llama.cpp device for embeddings (default: the chat model's --device, else Vulkan0)
  NEWS_MEMORY_EMBED_SERVER_PARALLEL    embedding slots (default 1)
  NEWS_MEMORY_EMBED_SERVER_CTX         embedding context (default 8192)
  NEWS_MEMORY_LLAMA_SYSCONFIG          default /etc/sysconfig/llama-server
EOF
}

as_root() {
	if [ "$(id -u)" -eq 0 ]; then
		"$@"
	else
		sudo "$@"
	fi
}

valid_port() {
	case "$1" in
		''|*[!0-9]*) return 1 ;;
	esac
	[ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

port_listening() {
	ss -H -ltn "sport = :$1" 2>/dev/null | grep -q .
}

wait_port_free() {
	local port=$1
	local i
	for i in $(seq 1 90); do
		if ! port_listening "$port"; then
			return 0
		fi
		sleep 1
	done
	echo "error: port $port is still in use" >&2
	return 1
}

probe_host() {
	case "$PUBLIC_HOST" in
		0.0.0.0|::|"") printf '%s\n' "127.0.0.1" ;;
		*) printf '%s\n' "$PUBLIC_HOST" ;;
	esac
}

# Assignments only. The sysconfig file is not executed as a shell script.
load_sysconfig() {
	# shellcheck disable=SC1090
	eval "$(python - "$1" <<'PY'
import shlex
import sys
from pathlib import Path

wanted = ("MODEL", "HOST", "PORT", "API_KEY", "LLAMA_OPTIONS")
vals = {key: "" for key in wanted}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, val = line.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key[7:].strip()
    if key not in vals:
        continue
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    vals[key] = val
for key in wanted:
    print(f"{key}={shlex.quote(vals[key])}")
PY
)"
}

filter_llama_options() {
	python - "$1" <<'PY'
import shlex
import sys

skip = {"--host", "--port", "--api-key", "--api_key"}
args = shlex.split(sys.argv[1] if len(sys.argv) > 1 else "")
out = []
i = 0
while i < len(args):
    arg = args[i]
    if arg in skip:
        i += 2
        continue
    if any(arg.startswith(name + "=") for name in skip):
        i += 1
        continue
    out.append(arg)
    i += 1
sys.stdout.write("\n".join(out))
PY
}

chat_device() {
	python - "$1" <<'PY'
import shlex
import sys

args = shlex.split(sys.argv[1] if len(sys.argv) > 1 else "")
dev = ""
i = 0
while i < len(args):
    arg = args[i]
    if arg == "--device" and i + 1 < len(args):
        dev = args[i + 1]
        i += 2
        continue
    if arg.startswith("--device="):
        dev = arg.split("=", 1)[1]
    i += 1
sys.stdout.write(dev)
PY
}

# Start a command in its own session and record the pid in SPAWNED_PID.
# Call this in the current shell. A command substitution would orphan the child.
spawn_session() {
	local logfile=$1
	shift
	: >"$logfile"
	chmod 600 "$logfile"
	python -c 'import os, sys
os.setsid()
os.closerange(3, 256)
os.execvp(sys.argv[1], sys.argv[1:])' "$@" >>"$logfile" 2>&1 </dev/null &
	SPAWNED_PID=$!
}

kill_group() {
	local pid=${1:-}
	local i
	if [ -z "$pid" ]; then
		return 0
	fi
	if ! kill -0 "$pid" 2>/dev/null; then
		wait "$pid" 2>/dev/null || true
		return 0
	fi
	# The child called setsid, so its pid is the process group.
	kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
	i=0
	while [ "$i" -lt 20 ]; do
		if ! kill -0 "$pid" 2>/dev/null; then
			break
		fi
		sleep 0.25
		i=$((i + 1))
	done
	if kill -0 "$pid" 2>/dev/null; then
		kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
	fi
	wait "$pid" 2>/dev/null || true
}

wait_http() {
	local url=$1
	local seconds=$2
	local mode=${3:-}
	if [ "$mode" = "key" ]; then
		LLAMA_API_KEY="$API_KEY" python - "$url" "$seconds" "$mode" <<'PY'
import os
import sys
import time
import urllib.error
import urllib.request

url, seconds, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
deadline = time.time() + seconds
while time.time() < deadline:
    req = urllib.request.Request(url)
    if mode == "key":
        key = os.environ.get("LLAMA_API_KEY") or ""
        if key:
            req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if 200 <= resp.status < 300:
                raise SystemExit(0)
    except urllib.error.HTTPError as e:
        if e.code == 200:
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(2)
raise SystemExit(1)
PY
	else
		python - "$url" "$seconds" "$mode" <<'PY'
import sys
import time
import urllib.error
import urllib.request

url, seconds = sys.argv[1], int(sys.argv[2])
deadline = time.time() + seconds
while time.time() < deadline:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if 200 <= resp.status < 300:
                raise SystemExit(0)
    except urllib.error.HTTPError as e:
        if e.code == 200:
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(2)
raise SystemExit(1)
PY
	fi
}

maintenance_up() {
	python - "$1" <<'PY'
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
phrase = "The news data is being updated. Try again later."
req = urllib.request.Request(url, headers={"Accept": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=2) as resp:
        body = resp.read().decode("utf-8", "replace")
        code = resp.status
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")
    code = e.code
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if code == 503 and phrase in body else 1)
PY
}

article_count() {
	env -u LLAMA_API_KEY -u API_KEY python -c 'import sys
sys.path.insert(0, sys.argv[1])
from news_memory.db import connect
c = connect()
cur = c.cursor()
cur.execute("SET statement_timeout = %s", ("5s",))
cur.execute("SELECT count(*) FROM articles")
print(cur.fetchone()[0], end="")
c.close()' "$ROOT" 2>/dev/null || printf '?'
}

start_public_llama() {
	local i
	for i in 1 2 3 4 5 6; do
		if as_root systemctl start llama.service; then
			if wait_http "http://${PROBE}:${PUBLIC_PORT}/health" 600 key; then
				echo "llama.service is answering on port ${PUBLIC_PORT}"
				return 0
			fi
			echo "llama.service is up; the model is still loading" >&2
			return 0
		fi
		sleep 3
	done
	echo "error: systemctl start llama.service failed" >&2
	return 1
}

restore() {
	local status=$?
	local gpu=0
	if [ "$CLEANED" = 1 ]; then
		exit "$status"
	fi
	CLEANED=1
	trap '' INT TERM
	set +e
	if [ -n "$WORKER_PID" ]; then
		kill -TERM "$WORKER_PID" 2>/dev/null || true
		wait "$WORKER_PID" 2>/dev/null || true
		WORKER_PID=
	fi
	if [ -n "$EXTRACT_PID" ] || [ -n "$EMBED_PID" ]; then
		gpu=1
	fi
	kill_group "$EXTRACT_PID"
	kill_group "$EMBED_PID"
	EXTRACT_PID=
	EMBED_PID=
	if [ "$gpu" = 1 ]; then
		sleep 5
	fi
	kill_group "$PLACEHOLDER_PID"
	PLACEHOLDER_PID=
	if [ -n "$PUBLIC_PORT" ]; then
		wait_port_free "$PUBLIC_PORT" || true
	fi
	if [ "$status" -eq 0 ] || [ "$LLAMA_WAS_ACTIVE" = 1 ]; then
		echo "==> starting llama.service"
		if ! start_public_llama; then
			echo "error: llama.service is not running. Start it with: sudo systemctl start llama.service" >&2
			status=1
		elif [ "$status" -eq 0 ]; then
			echo "refresh finished in ${SECONDS}s"
		fi
	else
		echo "llama.service was not running before this refresh; leaving it stopped"
	fi
	exit "$status"
}

require_alive() {
	local pid=$1
	local label=$2
	local logfile=$3
	sleep 0.5
	if ! kill -0 "$pid" 2>/dev/null; then
		echo "error: ${label} exited; see ${logfile}" >&2
		exit 1
	fi
}

start_placeholder() {
	spawn_session "$ROOT/run/refresh-placeholder.log" \
		env -u LLAMA_API_KEY -u API_KEY \
		python "$ROOT/updating_server.py" --host "$PUBLIC_HOST" --port "$PUBLIC_PORT"
	PLACEHOLDER_PID=$SPAWNED_PID
}

start_extract() {
	local -a cmd
	cmd=(llama-server --model "$MODEL")
	if [ "${#LLAMA_ARGS[@]}" -gt 0 ]; then
		cmd+=("${LLAMA_ARGS[@]}")
	fi
	cmd+=(--host 127.0.0.1 --port "$PRIVATE_PORT")
	# Inherit LLAMA_API_KEY from this script. Do not put the key on argv.
	spawn_session "$ROOT/run/refresh-extract.log" \
		env -u LLAMA_ARG_HOST -u LLAMA_ARG_PORT \
			-u LLAMA_ARG_MCP_SERVERS_CONFIG -u LLAMA_ARG_UI_CONFIG_FILE \
		"${cmd[@]}"
	EXTRACT_PID=$SPAWNED_PID
}

start_embed() {
	spawn_session "$ROOT/run/refresh-embed.log" \
		env -u LLAMA_API_KEY -u API_KEY -u LLAMA_ARG_HOST -u LLAMA_ARG_PORT \
			-u LLAMA_ARG_MCP_SERVERS_CONFIG -u LLAMA_ARG_UI_CONFIG_FILE \
		NEWS_MEMORY_EMBED_HOST=127.0.0.1 \
		NEWS_MEMORY_EMBED_BIND="$EMBED_PORT" \
		NEWS_MEMORY_EMBED_SERVER_DEVICE="$EMBED_DEVICE" \
		NEWS_MEMORY_EMBED_SERVER_PARALLEL="${NEWS_MEMORY_EMBED_SERVER_PARALLEL:-1}" \
		NEWS_MEMORY_EMBED_SERVER_CTX="${NEWS_MEMORY_EMBED_SERVER_CTX:-8192}" \
		"$ROOT/embed-server.sh"
	EMBED_PID=$SPAWNED_PID
}

run_ingest() {
	local tick=0
	local rc=0
	echo "==> filing feeds that are due (thinking on)"
	echo "    log: run/refresh-ingest.log"
	echo "    articles stored before this pass: $(article_count)"
	: >"$ROOT/run/refresh-ingest.log"
	chmod 600 "$ROOT/run/refresh-ingest.log"
	env -u LLAMA_API_KEY -u API_KEY \
		NEWS_MEMORY_EXTRACT_URL="http://127.0.0.1:${PRIVATE_PORT}" \
		NEWS_MEMORY_EXTRACT_THINKING=1 \
		NEWS_MEMORY_EXTRACT_MAX_TOKENS="$REFRESH_MAX_TOKENS" \
		NEWS_MEMORY_EXTRACT_TIMEOUT="$REFRESH_EXTRACT_TIMEOUT" \
		NEWS_MEMORY_EMBED_LOCAL=0 \
		python -u "$ROOT/worker.py" >>"$ROOT/run/refresh-ingest.log" 2>&1 &
	WORKER_PID=$!
	while kill -0 "$WORKER_PID" 2>/dev/null; do
		sleep 1
		tick=$((tick + 1))
		if [ "$tick" -ge 30 ]; then
			tick=0
			if kill -0 "$WORKER_PID" 2>/dev/null; then
				echo "    still filing; $(article_count) articles stored"
			fi
		fi
	done
	wait "$WORKER_PID" || rc=$?
	WORKER_PID=
	if [ "$rc" -ne 0 ]; then
		echo "error: filing failed (exit $rc); see run/refresh-ingest.log" >&2
		exit "$rc"
	fi
	echo "    filing done; $(article_count) articles stored"
}

main() {
	local state
	local i
	local up
	local sysconfig

	if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
		usage
		exit 0
	fi
	if [ "$#" -gt 0 ]; then
		echo "error: refresh-news.sh does not take arguments" >&2
		usage >&2
		exit 2
	fi

	cd "$ROOT"
	mkdir -p "$ROOT/run"
	exec 9>"$ROOT/run/refresh.lock"
	if ! flock -n 9; then
		echo "error: a refresh is already running" >&2
		exit 1
	fi

	for i in python llama-server systemctl ss flock; do
		if ! command -v "$i" >/dev/null 2>&1; then
			echo "error: $i not found" >&2
			exit 1
		fi
	done

	sysconfig=${NEWS_MEMORY_LLAMA_SYSCONFIG:-/etc/sysconfig/llama-server}
	if [ ! -r "$sysconfig" ]; then
		echo "error: cannot read $sysconfig" >&2
		exit 1
	fi
	load_sysconfig "$sysconfig"
	if [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
		echo "error: MODEL in $sysconfig is missing" >&2
		exit 1
	fi
	if [ -n "$API_KEY" ]; then
		export LLAMA_API_KEY="$API_KEY"
	fi

	PUBLIC_HOST=${HOST:-0.0.0.0}
	PUBLIC_PORT=${PORT:-8080}
	PRIVATE_PORT=${NEWS_MEMORY_REFRESH_EXTRACT_PORT:-8088}
	EMBED_PORT=${NEWS_MEMORY_REFRESH_EMBED_PORT:-8092}
	REFRESH_MAX_TOKENS=${NEWS_MEMORY_REFRESH_MAX_TOKENS:-16384}
	REFRESH_EXTRACT_TIMEOUT=${NEWS_MEMORY_REFRESH_EXTRACT_TIMEOUT:-600}
	PROBE=$(probe_host)

	for i in "$PUBLIC_PORT" "$PRIVATE_PORT" "$EMBED_PORT"; do
		if ! valid_port "$i"; then
			echo "error: bad port $i" >&2
			exit 1
		fi
	done
	if [ "$PRIVATE_PORT" = "$PUBLIC_PORT" ] || [ "$EMBED_PORT" = "$PUBLIC_PORT" ] || [ "$PRIVATE_PORT" = "$EMBED_PORT" ]; then
		echo "error: public, filing, and embedding ports must differ" >&2
		exit 1
	fi
	if port_listening "$PRIVATE_PORT"; then
		echo "error: filing port $PRIVATE_PORT is already in use" >&2
		exit 1
	fi
	if port_listening "$EMBED_PORT"; then
		echo "error: embedding port $EMBED_PORT is already in use" >&2
		exit 1
	fi

	if [ -n "${NEWS_MEMORY_EMBED_SERVER_DEVICE:-}" ]; then
		EMBED_DEVICE=$NEWS_MEMORY_EMBED_SERVER_DEVICE
	else
		EMBED_DEVICE=$(chat_device "$LLAMA_OPTIONS")
		if [ -z "$EMBED_DEVICE" ]; then
			EMBED_DEVICE=Vulkan0
		fi
	fi

	LLAMA_ARGS=()
	if [ -n "$LLAMA_OPTIONS" ]; then
		mapfile -t LLAMA_ARGS < <(filter_llama_options "$LLAMA_OPTIONS")
	fi
	if [ "${#LLAMA_ARGS[@]}" -eq 1 ] && [ -z "${LLAMA_ARGS[0]:-}" ]; then
		LLAMA_ARGS=()
	fi

	state=$(systemctl is-active llama.service 2>/dev/null || true)
	case "$state" in
		active|activating|deactivating) LLAMA_WAS_ACTIVE=1 ;;
		*) LLAMA_WAS_ACTIVE=0 ;;
	esac

	trap restore EXIT
	trap 'exit 130' INT
	trap 'exit 143' TERM

	echo "==> stopping llama.service"
	echo "    feeds that are due are filed with thinking on, then those rows are embedded"
	echo "    an empty database makes every feed due, including multi-day windows"
	as_root systemctl stop llama.service
	wait_port_free "$PUBLIC_PORT"

	echo "==> maintenance reply on ${PUBLIC_HOST}:${PUBLIC_PORT}"
	start_placeholder
	require_alive "$PLACEHOLDER_PID" "maintenance server" "run/refresh-placeholder.log"
	up=0
	for i in 1 2 3 4 5 6 7 8 9 10; do
		if maintenance_up "http://${PROBE}:${PUBLIC_PORT}/v1/models"; then
			up=1
			break
		fi
		sleep 0.3
	done
	if [ "$up" -ne 1 ]; then
		echo "error: maintenance server did not answer; see run/refresh-placeholder.log" >&2
		exit 1
	fi

	# The GPU driver drops the chat allocation after the process has exited.
	sleep 3
	echo "==> starting filing model on 127.0.0.1:${PRIVATE_PORT}"
	start_extract
	require_alive "$EXTRACT_PID" "filing model" "run/refresh-extract.log"
	if ! wait_http "http://127.0.0.1:${PRIVATE_PORT}/health" 600 key; then
		echo "error: filing model did not become ready; see run/refresh-extract.log" >&2
		exit 1
	fi

	run_ingest

	echo "==> stopping filing model"
	kill_group "$EXTRACT_PID"
	EXTRACT_PID=
	sleep 5
	wait_port_free "$PRIVATE_PORT"

	echo "==> starting embedding model on 127.0.0.1:${EMBED_PORT}"
	start_embed
	require_alive "$EMBED_PID" "embedding model" "run/refresh-embed.log"
	if ! wait_http "http://127.0.0.1:${EMBED_PORT}/health" 1200; then
		echo "error: embedding model did not become ready; see run/refresh-embed.log" >&2
		exit 1
	fi

	echo "==> embedding filed rows"
	: >"$ROOT/run/refresh-embed-worker.log"
	chmod 600 "$ROOT/run/refresh-embed-worker.log"
	env -u LLAMA_API_KEY -u API_KEY \
		NEWS_MEMORY_EMBED_URL="http://127.0.0.1:${EMBED_PORT}" \
		NEWS_MEMORY_EMBED_LOCAL=0 \
		python -u "$ROOT/worker.py" --embed-filed 2>&1 | tee -a "$ROOT/run/refresh-embed-worker.log"

	echo "==> stopping embedding model"
	kill_group "$EMBED_PID"
	EMBED_PID=
	sleep 5

	echo "==> removing maintenance reply"
	kill_group "$PLACEHOLDER_PID"
	PLACEHOLDER_PID=
	wait_port_free "$PUBLIC_PORT"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	main "$@"
fi
