#!/bin/bash
# Create the news_memory database, extensions, schema, and country seed.
# --wipe drops that database first (articles, dossiers, the Zembla canary)
# and then builds it again. A plain run leaves existing rows in place.
# --download-embed fetches the embedding snapshot into models/ and exits.
# A plain run records that path and does not download the weights.
# Works on this machine and on any other Unix with PostgreSQL 16+ , pgvector, pg_trgm.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

DB_NAME=${NEWS_MEMORY_DB:-news_memory}
DB_USER=${NEWS_MEMORY_DB_USER:-news-memory}
DB_HOST=${NEWS_MEMORY_DB_HOST:-/run/postgresql}
DB_PORT=${NEWS_MEMORY_DB_PORT:-5432}
EMBED_MODEL=${NEWS_MEMORY_EMBED_MODEL:-}
EXTRACT_URL=${NEWS_MEMORY_EXTRACT_URL:-http://127.0.0.1:8080}
EMBED_URL=${NEWS_MEMORY_EMBED_URL:-http://127.0.0.1:8092}
TOOLS_PORT=${NEWS_MEMORY_TOOLS_PORT:-8091}
SKIP_EMBED=0
SKIP_SEED=0
WIPE=0

usage() {
	cat <<EOF
Usage: ./setup.sh [options]

  --db NAME            database name (default: $DB_NAME)
  --user NAME          database role (default: $DB_USER)
  --host HOST          postgres host or socket dir (default: $DB_HOST)
  --port N             tcp port if host is not a socket (default: $DB_PORT)
  --embed-model PATH   Qwen3-Embedding-0.6B directory
  --extract-url URL    llama.cpp server used for extract / dossier rewrite
  --embed-url URL      llama.cpp embedding server (optional)
  --download-embed     fetch Qwen/Qwen3-Embedding-0.6B into models/ and exit
  --skip-embed         do not run the embedding pass during seed
  --skip-seed          only create db + schema
  --wipe               drop the database, then create it again
  --render             write llama-mcp.json and the llama drop-in for this directory
  --install-units      create the news-memory system user and install system units
  --help

Environment: NEWS_MEMORY_DB, NEWS_MEMORY_DB_USER, NEWS_MEMORY_DB_HOST,
NEWS_MEMORY_DB_PORT, NEWS_MEMORY_DB_PASSWORD, NEWS_MEMORY_PG_SUPER,
NEWS_MEMORY_EMBED_MODEL, NEWS_MEMORY_EXTRACT_URL.

Needs: psql, python with psycopg2, packages postgresql-contrib and pgvector.
EOF
}

# @PREFIX@ is this directory. Shipped files keep that token; rendered copies
# get the real path. Python is left as "python" and resolved from PATH.
render() {
	local src=$1 dest=$2
	command -v python >/dev/null 2>&1 || {
		echo "error: python not found" >&2
		exit 1
	}
	mkdir -p "$(dirname "$dest")"
	python -c '
import pathlib, sys
src, dest, root = sys.argv[1:]
text = pathlib.Path(src).read_text(encoding="utf-8")
pathlib.Path(dest).write_text(text.replace("@PREFIX@", root), encoding="utf-8")
' "$src" "$dest" "$ROOT"
}

render_tree() {
	render "$ROOT/data/llama-mcp.json.in" "$ROOT/data/llama-mcp.json"
	render "$ROOT/systemd/llama-news-memory.conf" "$ROOT/run/llama-news-memory.conf"
}

as_root() {
	if [ "$(id -u)" -eq 0 ]; then
		"$@"
	else
		sudo "$@"
	fi
}

as_service_user() {
	if [ "$(id -u)" -eq 0 ]; then
		runuser -u news-memory -- "$@"
	else
		sudo -u news-memory -- "$@"
	fi
}

# config.env is owner-writable and group-readable by the service account.
share_config() {
	if [ ! -f "$ROOT/config.env" ]; then
		return 0
	fi
	if ! getent group news-memory >/dev/null 2>&1; then
		return 0
	fi
	as_root chgrp news-memory "$ROOT/config.env"
	as_root chmod 640 "$ROOT/config.env"
}

install_system_units() {
	local u dir unit
	render_tree
	as_root install -d /etc/sysusers.d /etc/systemd/system
	as_root install -m 0644 "$ROOT/systemd/news-memory.sysusers" /etc/sysusers.d/news-memory.conf
	as_root systemd-sysusers /etc/sysusers.d/news-memory.conf
	dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
	if [ -d "$dir" ]; then
		systemctl --user disable --now news-memory-worker.timer news-memory-worker.service \
			news-memory-tools.service news-memory-chat.service news-memory-embed.service \
			>/dev/null 2>&1 || true
		for u in news-memory-worker.service news-memory-worker.timer \
			news-memory-tools.service news-memory-chat.service news-memory-embed.service; do
			rm -f "$dir/$u"
		done
		systemctl --user daemon-reload >/dev/null 2>&1 || true
	fi
	for u in news-memory-worker.service news-memory-worker.timer \
		news-memory-tools.service news-memory-chat.service news-memory-embed.service; do
		render "$ROOT/systemd/$u" "$ROOT/run/$u"
		as_root install -m 0644 "$ROOT/run/$u" "/etc/systemd/system/$u"
	done
	share_config
	as_root systemctl daemon-reload
	echo "system user: news-memory"
	echo "installed system units in /etc/systemd/system"
	echo "enable with:  sudo systemctl enable --now news-memory-worker.timer"
	if ! as_service_user test -r "$ROOT/worker.py"; then
		echo "warning: news-memory cannot read $ROOT" >&2
		echo "         the install directory must be traversable and readable by that user" >&2
	fi
	if [ -f "$ROOT/config.env" ] && ! as_service_user test -r "$ROOT/config.env"; then
		echo "warning: news-memory cannot read $ROOT/config.env" >&2
	fi
}

# Official snapshot, Apache-2.0, about 1.2 GB. Both the in-process embedder
# and embed-server.sh read this directory.
EMBED_REPO=Qwen/Qwen3-Embedding-0.6B
EMBED_DEST=$ROOT/models/Qwen3-Embedding-0.6B

embed_weights_ready() {
	local dest=$1 size
	[ -s "$dest/config.json" ] || return 1
	[ -s "$dest/tokenizer_config.json" ] || return 1
	[ -f "$dest/tokenizer.json" ] || return 1
	[ -f "$dest/model.safetensors" ] || return 1
	size=$(stat -c %s "$dest/tokenizer.json")
	[ "$size" -gt 1000000 ] || return 1
	size=$(stat -c %s "$dest/model.safetensors")
	[ "$size" -gt 1000000000 ]
}

record_embed_model() {
	local dest=$1
	if [ ! -f "$ROOT/config.env" ]; then
		echo "NEWS_MEMORY_EMBED_MODEL=$dest"
		echo "run ./setup.sh to write config.env; it records this path"
		return 0
	fi
	python - "$ROOT/config.env" "$dest" <<'PY'
import pathlib, sys
path, dest = sys.argv[1:]
if "'" in dest or "\n" in dest or "\r" in dest:
    sys.exit("error: embed model path cannot be recorded")
file = pathlib.Path(path)
text = file.read_text(encoding="utf-8")
key = "NEWS_MEMORY_EMBED_MODEL"
out = []
found = False
for line in text.splitlines():
    stripped = line.strip()
    body = stripped[7:] if stripped.startswith("export ") else stripped
    name, sep, _val = body.partition("=")
    if sep and name.strip() == key:
        out.append(f"{key}='{dest}'")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}='{dest}'")
file.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
	echo "set NEWS_MEMORY_EMBED_MODEL=$dest"
}

download_embed() {
	local dest=$EMBED_DEST
	if embed_weights_ready "$dest"; then
		echo "embedding weights already present: $dest"
	else
		mkdir -p "$dest"
		if ! python -c 'import huggingface_hub' >/dev/null 2>&1; then
			echo "error: --download-embed needs python module huggingface_hub (package python-huggingface_hub)" >&2
			exit 1
		fi
		echo "downloading $EMBED_REPO into $dest"
		python - "$dest" "$EMBED_REPO" <<'PY'
import sys
from huggingface_hub import snapshot_download
dest, repo = sys.argv[1:]
snapshot_download(repo_id=repo, local_dir=dest)
PY
		if ! embed_weights_ready "$dest"; then
			echo "error: $dest is missing $EMBED_REPO weights after download" >&2
			exit 1
		fi
		echo "downloaded $EMBED_REPO into $dest"
	fi
	if [ -d "$dest" ]; then
		dest=$(CDPATH= cd -- "$dest" && pwd)
	fi
	record_embed_model "$dest"
}

while [ $# -gt 0 ]; do
	case $1 in
	--db) DB_NAME=$2; shift 2 ;;
	--user) DB_USER=$2; shift 2 ;;
	--host) DB_HOST=$2; shift 2 ;;
	--port) DB_PORT=$2; shift 2 ;;
	--embed-model) EMBED_MODEL=$2; shift 2 ;;
	--extract-url) EXTRACT_URL=$2; shift 2 ;;
	--embed-url) EMBED_URL=$2; shift 2 ;;
	--skip-embed) SKIP_EMBED=1; shift ;;
	--skip-seed) SKIP_SEED=1; shift ;;
	--wipe) WIPE=1; shift ;;
	--download-embed)
		download_embed
		exit 0
		;;
	--render)
		render_tree
		echo "wrote $ROOT/data/llama-mcp.json"
		echo "wrote $ROOT/run/llama-news-memory.conf"
		echo "install the llama drop-in with:"
		echo "  sudo cp $ROOT/run/llama-news-memory.conf /etc/systemd/system/llama.service.d/news-memory.conf"
		echo "  sudo systemctl daemon-reload && sudo systemctl restart llama.service"
		exit 0
		;;
	--install-units)
		install_system_units
		echo "llama drop-in: $ROOT/run/llama-news-memory.conf"
		exit 0
		;;
	-h|--help) usage; exit 0 ;;
	*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

render_tree
echo "wrote $ROOT/data/llama-mcp.json"
echo "wrote $ROOT/run/llama-news-memory.conf"

if [ -z "$EMBED_MODEL" ]; then
	EMBED_MODEL=$EMBED_DEST
	if [ -d "$EMBED_MODEL" ]; then
		EMBED_MODEL=$(CDPATH= cd -- "$EMBED_MODEL" && pwd)
	fi
fi

need() {
	command -v "$1" >/dev/null 2>&1 || {
		echo "error: $1 not found" >&2
		exit 1
	}
}

need psql
need python

if command -v pg_isready >/dev/null 2>&1; then
	if ! pg_isready -q; then
		echo "error: PostgreSQL is not accepting connections (pg_isready failed)" >&2
		echo "start it first, e.g.  sudo systemctl start postgresql" >&2
		exit 1
	fi
fi

if ! python -c 'import psycopg2' 2>/dev/null; then
	if command -v dnf >/dev/null 2>&1; then
		echo "installing python-psycopg2"
		sudo dnf install -y python-psycopg2
	else
		echo "error: python module psycopg2 is missing (package python-psycopg2)" >&2
		exit 1
	fi
fi

psql_super() {
	# Run SQL as a superuser. Tries, in order: current user, NEWS_MEMORY_PG_SUPER,
	# sudo -u postgres, sudo -u pgsql.
	local sql=$1
	if [ -n "${NEWS_MEMORY_PG_SUPER:-}" ]; then
		psql -v ON_ERROR_STOP=1 -d postgres -U "$NEWS_MEMORY_PG_SUPER" -c "$sql"
		return
	fi
	if psql -v ON_ERROR_STOP=1 -d postgres -c 'SELECT usesuper FROM pg_user WHERE usename = current_user' 2>/dev/null | grep -q t; then
		psql -v ON_ERROR_STOP=1 -d postgres -c "$sql"
		return
	fi
	if command -v sudo >/dev/null 2>&1; then
		if sudo -n -u postgres psql -v ON_ERROR_STOP=1 -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
			sudo -n -u postgres psql -v ON_ERROR_STOP=1 -d postgres -c "$sql"
			return
		fi
		if sudo -n -u pgsql psql -v ON_ERROR_STOP=1 -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
			sudo -n -u pgsql psql -v ON_ERROR_STOP=1 -d postgres -c "$sql"
			return
		fi
	fi
	echo "error: need a PostgreSQL superuser. Set NEWS_MEMORY_PG_SUPER or allow sudo -u postgres." >&2
	exit 1
}

psql_super_db() {
	local sql=$1
	if [ -n "${NEWS_MEMORY_PG_SUPER:-}" ]; then
		psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -U "$NEWS_MEMORY_PG_SUPER" -c "$sql"
		return
	fi
	if psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c 'SELECT usesuper FROM pg_user WHERE usename = current_user' 2>/dev/null | grep -q t; then
		psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c "$sql"
		return
	fi
	if command -v sudo >/dev/null 2>&1; then
		if sudo -n -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c 'SELECT 1' >/dev/null 2>&1; then
			sudo -n -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c "$sql"
			return
		fi
		if sudo -n -u pgsql psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c 'SELECT 1' >/dev/null 2>&1; then
			sudo -n -u pgsql psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c "$sql"
			return
		fi
	fi
	echo "error: could not open $DB_NAME as superuser to create extensions" >&2
	exit 1
}

ident_ok() {
	# SQL identifier: letters, digits, underscore, hyphen. Quoted before use.
	echo "$1" | grep -Eq '^[A-Za-z_][A-Za-z0-9_-]*$'
}

sql_ident() {
	printf '"%s"' "$(printf '%s' "$1" | sed 's/"/""/g')"
}

ident_ok "$DB_NAME" || { echo "error: bad database name $DB_NAME" >&2; exit 1; }
ident_ok "$DB_USER" || { echo "error: bad role name $DB_USER" >&2; exit 1; }

if [ "$WIPE" -eq 1 ]; then
	case $DB_NAME in
	postgres|template0|template1)
		echo "error: refusing to wipe database $DB_NAME" >&2
		exit 1
		;;
	esac
	echo "==> wiping database $DB_NAME"
	echo "    this drops articles, dossiers, entities, and feed state"
	echo "    open connections (llama MCP included) are terminated"
	# PostgreSQL 13+. One statement, so a reconnect cannot land between
	# terminate and drop. The role is kept.
	psql_super "DROP DATABASE IF EXISTS $(sql_ident "$DB_NAME") WITH (FORCE);"
fi

echo "==> creating role $DB_USER and database $DB_NAME"
QI_USER=$(sql_ident "$DB_USER")
QI_DB=$(sql_ident "$DB_NAME")
psql_super "
DO \$\$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER') THEN
		CREATE ROLE $QI_USER LOGIN;
	END IF;
END
\$\$;
"

if ! psql_super "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
	psql_super "CREATE DATABASE $QI_DB OWNER $QI_USER;"
else
	echo "    database $DB_NAME already exists"
	psql_super "ALTER DATABASE $QI_DB OWNER TO $QI_USER;"
	psql_super "GRANT ALL ON DATABASE $QI_DB TO $QI_USER;"
fi

echo "==> extensions"
psql_super_db "CREATE EXTENSION IF NOT EXISTS vector;"
psql_super_db "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
psql_super_db "GRANT ALL ON SCHEMA public TO $QI_USER;"
psql_super_db "ALTER SCHEMA public OWNER TO $QI_USER;"

export_psql() {
	export PGUSER=$DB_USER
	export PGDATABASE=$DB_NAME
	if [ -n "${NEWS_MEMORY_DB_PASSWORD:-}" ]; then
		export PGPASSWORD=$NEWS_MEMORY_DB_PASSWORD
	fi
	if [ -n "$DB_HOST" ]; then
		export PGHOST=$DB_HOST
	fi
	if ! [ -d "$DB_HOST" ]; then
		export PGPORT=$DB_PORT
	fi
}

export_psql

echo "==> schema"
psql -v ON_ERROR_STOP=1 -f "$ROOT/schema.sql"

if [ -d "$DB_HOST" ]; then
	HOSTLINE=$DB_HOST
else
	HOSTLINE=$DB_HOST
fi

cat > "$ROOT/config.env" <<EOF
NEWS_MEMORY_HOME=$ROOT
NEWS_MEMORY_DB=$DB_NAME
NEWS_MEMORY_DB_USER=$DB_USER
NEWS_MEMORY_DB_HOST=$HOSTLINE
NEWS_MEMORY_DB_PORT=$DB_PORT
NEWS_MEMORY_EMBED_MODEL=$EMBED_MODEL
NEWS_MEMORY_EMBED_URL=$EMBED_URL
NEWS_MEMORY_EMBED_DEVICE=${NEWS_MEMORY_EMBED_DEVICE:-cpu}
NEWS_MEMORY_EXTRACT_URL=$EXTRACT_URL
NEWS_MEMORY_LLAMA_SYSCONFIG=${NEWS_MEMORY_LLAMA_SYSCONFIG:-/etc/sysconfig/llama-server}
NEWS_MEMORY_TOOLS_PORT=$TOOLS_PORT
NEWS_MEMORY_PIVOT_LANG=${NEWS_MEMORY_PIVOT_LANG:-en}
EOF
if [ -n "${NEWS_MEMORY_DB_PASSWORD:-}" ]; then
	printf 'NEWS_MEMORY_DB_PASSWORD=%s\n' "$NEWS_MEMORY_DB_PASSWORD" >> "$ROOT/config.env"
fi
echo "    wrote $ROOT/config.env"
share_config

if [ "$SKIP_SEED" -eq 0 ]; then
	echo "==> seed countries, capitals, orgs, feeds"
	if [ "$SKIP_EMBED" -eq 1 ]; then
		NEWS_MEMORY_EMBED_URL= NEWS_MEMORY_EMBED_LOCAL=0 \
			PYTHONPATH=$ROOT python -m news_memory.seed
	else
		NEWS_MEMORY_EMBED_LOCAL=1 PYTHONPATH=$ROOT python -m news_memory.seed
	fi
fi

echo
echo "Setup complete."
echo "  config:   $ROOT/config.env"
echo "  ingest:   $ROOT/worker.py"
echo "  query:    $ROOT/query.py get_background 'why did Zembla oust its president'"
echo "  tools:    $ROOT/tools_server.py"
echo "  selftest: python -m news_memory.selftest"
echo "  units:    $ROOT/systemd/"
echo
echo "Point llama.cpp chat at $EXTRACT_URL and give it the tools from"
echo "  $ROOT/data/tools.json"
echo "plus the system prompt from: $ROOT/query.py prompt"
