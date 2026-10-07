# news-memory

news-memory is a local news archive that a llama.cpp chat model can search while it answers. Articles, events, and dossiers live in PostgreSQL. Whichever GGUF `llama-server` has loaded uses the same database and the same tools.

Commands below are run from the news-memory directory, wherever it is installed. Connection settings are in `config.env` (written by `setup.sh`; a commented template is `config.example.env`). `setup.sh` also fills `@PREFIX@` into the files llama-server and systemd actually run. Those files call `python` from `PATH`.

OpenMandriva is the only officially supported platform. `llama.service`, `/etc/sysconfig/llama-server`, and `/usr/share/llama-cpp` are paths from that distribution's packages. Patches that make news-memory work in other environments are welcome.

## Pieces

| Piece | What it does |
|---|---|
| `setup.sh` | Creates the database, extensions, schema, and seed data. `--download-embed` fetches the embedding model |
| `worker.py` | Fetches feeds and files new articles |
| `refresh-news.sh` | Files due feeds on one GPU, with the chat server stopped |
| `updating_server.py` | Maintenance reply used while that refresh runs |
| `data/feeds.json` | Hand-written list of news sources |
| `mcp_server.py` | Tools for the llama.cpp Web UI, over stdio MCP |
| `chat_proxy.py` | Apertus tool loop in front of llama-server (`:8081`) |
| `tools_server.py` | Apertus retrieval API (`:8091`) |
| `query.py` | Run a tool from the shell, with no model |
| `embed-server.sh` | Optional embedding server for semantic search (`:8092`) |

The OpenMandriva package runs the chat server as `llama.service`, configured in `/etc/sysconfig/llama-server`. The news tools are attached by `/etc/systemd/system/llama.service.d/news-memory.conf`.

## Database on another host

The worker, the query tool, and the MCP server all read `config.env`. The Apertus fronts on ports 8081 and 8091 read it too.

A host that starts with `/` is a Unix socket directory. The port is ignored. The default is the local socket:

```bash
NEWS_MEMORY_DB_HOST=/run/postgresql
NEWS_MEMORY_DB_PORT=5432
NEWS_MEMORY_DB=news_memory
NEWS_MEMORY_DB_USER=news-memory
```

Anything else is a TCP host. Set the port, and set a password when the server requires one:

```bash
NEWS_MEMORY_DB_HOST=db.example
NEWS_MEMORY_DB_PORT=5432
NEWS_MEMORY_DB_USER=news-memory
NEWS_MEMORY_DB_PASSWORD=secret
```

`setup.sh` creates the role, the database, and the `vector` and `pg_trgm` extensions through a superuser on the local socket (`sudo -u postgres`, `sudo -u pgsql`, or `NEWS_MEMORY_PG_SUPER`). `--host` is written into `config.env` and is used for the schema load and the seed. Run `setup.sh` on the machine where PostgreSQL is installed, then point `config.env` on the llama machine at that host. Re-running `setup.sh` overwrites `config.env`.

On the database machine:

- Install PostgreSQL 16 or newer, `postgresql-contrib`, and `pgvector`. `python-psycopg2` is required wherever `setup.sh` or the worker runs.
- Let PostgreSQL listen on a network interface (`listen_addresses` in `postgresql.conf`).
- Allow the application user from the llama machine in `pg_hba.conf`, then reload. A typical TCP line is `host news_memory news_memory <llama-ip>/32 scram-sha-256`.
- Open TCP port 5432 from the llama machine.

`llama.service` runs as a dynamic user. The rendered drop-in bind-mounts `/run/postgresql` so that user can use the local socket, and it allows read of this directory so the service can import the tree and read `config.env`. The socket mount is for `/run/postgresql`. A hostname in `NEWS_MEMORY_DB_HOST` is a TCP connection, which the service is already allowed to open. `config.env` has to stay readable by that service user. The drop-in adds `news-memory` to `SupplementaryGroups`, merged with the groups `llama.service` already has. Mode `640` and group `news-memory` is then readable by the dynamic user and by the news-memory services. Mode `600` owned by your account blocks the Web UI tools from opening the database.

Check the remote connection from the llama machine:

```bash
psql "host=db.example port=5432 dbname=news_memory user=news-memory" -c 'SELECT count(*) FROM sources;'
```

`./setup.sh --wipe` drops the database seen by that local superuser connection, then creates it again and re-seeds. It refuses `postgres`, `template0`, and `template1`. Wipe the remote database by running that command on the database host.

## News sources

`data/feeds.json` is the list of outlets you edit. Each entry looks like this:

```json
{
  "name": "BBC World",
  "homepage": "https://www.bbc.com/news/world",
  "feed_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
  "feed_type": "rss",
  "lang": "en",
  "interval_minutes": 30
}
```

`name` is the identity of the source. `feed_type` is `rss` (RSS or Atom) or `wikipedia_current_events`. `lang` is the feed's language. `country_iso` is optional. `interval_minutes` is the minimum time between fetches of that source.

The sample list tries to capture as wide a range of views as possible, with outlets from different countries and political directions, so the same event can be filed from more than one account.

Seeding also adds sources that are not in the file:

- Wikipedia current-events portals for a set of languages, every 90 minutes. The list is `WIKI_PORTALS` in `news_memory/country_langs.py`. The English portal is also in `feeds.json`.
- A Google News RSS search for each country that is not already covered by the large wires, in up to two local languages. Those countries are everyone outside `WELL_COVERED` in the same file. The interval is 180 or 360 minutes.

Load the file into the database after editing it:

```bash
python -m news_memory.seed
```

That updates rows matched by `name` and inserts new ones. It does not delete a source you removed from the file, and the generated Wikipedia and Google News rows come back on the next seed.

To stop a feed that seed will not recreate, clear its URL. The worker ignores a source with no URL:

```bash
psql -h /run/postgresql -U news-memory -d news_memory -c "UPDATE sources SET feed_url = NULL WHERE name = 'AP Top News';"
```

To stop one that seed recreates, remove it from `feeds.json` or add the country to `WELL_COVERED`, run the seed again, then clear the URL. Deleting the `sources` row is blocked while articles still point at it.

See what is configured:

```bash
psql -h /run/postgresql -U news-memory -d news_memory -c \
  "SELECT feed_type, count(*) FROM sources GROUP BY 1 ORDER BY 1;"
```

## How llama.cpp is wired

Nothing in this tree is compiled for one model. `llama.service` loads whatever `MODEL` is set to in `/etc/sysconfig/llama-server`. The drop-in adds two settings on top of that:

- `LLAMA_ARG_MCP_SERVERS_CONFIG` points at `data/llama-mcp.json` in this directory
- `LLAMA_ARG_UI_CONFIG_FILE` points at `data/ui-config.json`

`llama-mcp.json` starts `mcp_server.py`. llama.cpp names the server `news` and prefixes each tool, so the Web UI sees `news_get_background`, `news_get_timeline`, `news_search_dossiers`, `news_search_events`, `news_get_article`, and `news_resolve_entity`. The tools read the database directly. `ui-config.json` is the Web UI system message: it tells the model that its built-in knowledge ends around mid-2026 and to call those tools. `showToolCallInProgress` and `alwaysShowAgenticTurns` make the tool calls visible in the UI.

`systemd/llama-news-memory.conf` and `data/llama-mcp.json.in` are templates. Render them for this install, then restart the chat server:

```bash
./setup.sh --render
sudo cp run/llama-news-memory.conf /etc/systemd/system/llama.service.d/news-memory.conf
sudo systemctl daemon-reload
sudo systemctl restart llama.service
```

`data/llama-mcp.json` is the rendered file. A normal `./setup.sh` writes it too.

For a model whose own chat template llama.cpp can compile, changing `MODEL=` and restarting points the same tools at that GGUF. Qwen3.6 answering with the Zembla canary is that path: the Web UI on port 8080 runs the tool loop inside llama-server. Leave those clients pointed at `:8080`. Zembla is fictional material inserted by `python -m news_memory.selftest` (Helena Voss, Zed City, the staple tax, 12 March 2028). Those details come from the database.

`query.py` calls the tools in-process:

```bash
python query.py get_background 'why did Zembla oust its president'
python query.py prompt
```

If `API_KEY` is set in `/etc/sysconfig/llama-server`, clients send `Authorization: Bearer <that key>`. The worker reads the same file when it asks the chat model to file an article, unless `NEWS_MEMORY_EXTRACT_API_KEY` is set.

Filing an article uses the model currently served at `NEWS_MEMORY_EXTRACT_URL` (by default the same llama-server) to turn the text into events, relations, and dossier updates. Grammars in `grammars/` hold the JSON shape. If that server is down or still loading, the article is still stored and linked to countries and other known names from the gazetteer. With `NEWS_MEMORY_EXTRACT_THINKING` unset, filing omits the thinking flag and asks for at most 2048 tokens (`NEWS_MEMORY_EXTRACT_MAX_TOKENS`). Each call waits up to 180 seconds (`NEWS_MEMORY_EXTRACT_TIMEOUT`). Semantic search uses a separate embedding model, Qwen3-Embedding-0.6B, either via `embed-server.sh` at `NEWS_MEMORY_EMBED_URL` or in-process when `NEWS_MEMORY_EMBED_LOCAL=1`. Name lookup and full-text search keep working when no embedding server is up.

The weights are the Hugging Face snapshot `Qwen/Qwen3-Embedding-0.6B` (about 1.2 GB, Apache-2.0). `./setup.sh` records that directory as `models/Qwen3-Embedding-0.6B` in `NEWS_MEMORY_EMBED_MODEL`. Fetch the snapshot on its own, whenever you want it:

```bash
./setup.sh --download-embed
```

That command leaves the database alone. When `config.env` already exists, it sets `NEWS_MEMORY_EMBED_MODEL` to the snapshot directory. A directory that already holds the weights is left in place. The download needs the Python module `huggingface_hub` (`python-huggingface_hub`). `embed-server.sh` converts the snapshot to `models/Qwen3-Embedding-0.6B-f16.gguf` the first time it starts.

### Every model

- `--jinja` in `LLAMA_OPTIONS`, so llama-server can turn the model's tool calls into the format the Web UI runs.
- The MCP drop-in and `ui-config.json`.
- The database, the worker, and (for semantic search) the embedding model.
- llama-server on port 8080. That is the port Qwen3.6 uses.

### Apertus only

The Jinja template embedded in the Apertus 1.5 GGUF does not compile in llama.cpp, so tool calls never start. Pass the template llama.cpp ships:

```bash
LLAMA_OPTIONS="--n-gpu-layers all --device Vulkan0 --jinja --chat-template-file /usr/share/llama-cpp/models/templates/swiss-ai-Apertus-v1.5.jinja --cache-type-k q8_0 --cache-type-v q8_0 -c 65536"
```

That line is already commented in `/etc/sysconfig/llama-server`. The shorter `--jinja` line is what Qwen and other models with a template llama.cpp can compile use. Switch `MODEL=` and `LLAMA_OPTIONS` together, then restart `llama.service`. No news-memory file changes with the model.

Apertus also uses two local fronts. Qwen3.6 reaches the tools through port 8080.

`chat_proxy.py` listens on `127.0.0.1:8081` and forwards to `NEWS_MEMORY_LLAMA_URL` (default `http://127.0.0.1:8080`). Point Apertus clients at `http://127.0.0.1:8081/v1`. The proxy adds the prompt in `prompts/chat_system.txt`, sends the tool definitions, runs the tool loop for up to `NEWS_MEMORY_CHAT_MAX_ROUNDS` rounds (default 6), and returns the final answer. A streaming request comes back as one event, after the tools have finished. llama-server's own `/v1/chat/completions` returns the model's message and leaves that loop to the caller, which is what this proxy does.

`tools_server.py` on port 8091 is the same retrieval API over HTTP, for an Apertus agent that calls tools itself. `./setup.sh --install-units` installs it as the system unit `news-memory-tools.service`, running as `news-memory`. The chat proxy is `news-memory-chat.service`. Enable either with `sudo systemctl enable --now`.

## Refresh the news

One pass, from this directory or by path. Feeds fetched more recently than their `interval_minutes` are skipped:

```bash
python worker.py
```

Ignore those intervals and fetch every source that has a URL:

```bash
python worker.py --force
```

File the feed summary without downloading article HTML:

```bash
python worker.py --no-body
```

Keep running and repeat every 30 minutes:

```bash
python worker.py --loop 1800
```

Fill embeddings for entities that do not have one yet. This flag loads Qwen3-Embedding-0.6B in-process from the Hugging Face directory in `NEWS_MEMORY_EMBED_MODEL` (`./setup.sh --download-embed` fetches it). `NEWS_MEMORY_EMBED_DEVICE=cuda` runs that load on the GPU. Stop `llama.service` first, because the chat model already occupies the card. On the GPU each batch stays within 8192 padded tokens, so one long alias list does not pad a whole batch of 16 out to 2048 tokens.

```bash
sudo systemctl stop llama.service
python worker.py --embed-pending
sudo systemctl start llama.service
```

Embed only rows a news pass has already touched: articles without a vector, entities with `mention_count > 0`, and dossiers that have a status, a compact body, or a timeline entry. This uses the embedding server at `NEWS_MEMORY_EMBED_URL`:

```bash
python worker.py --embed-filed
```

The worker needs the Python modules `feedparser` and `lxml` (`python-feedparser` and `python-lxml`). Without `feedparser`, an RSS source contributes nothing.

### One GPU

`worker.py` is the ingest to keep when the chat server can stay up. That is the right path when the database runs on another machine and this GPU can stay on the chat model.

`refresh-news.sh` is the path for one GPU. The chat model and Qwen3-Embedding both need the card, so the script runs them one after the other:

1. Stops `llama.service` and answers on its public port with "The news data is being updated. Try again later."
2. Starts the chat model on `127.0.0.1:8088` and files every feed that is due. Thinking is on for this run.
3. Stops that model, starts the embedding model on `127.0.0.1:8092`, and embeds the rows that pass touched.
4. Stops the embedding model, removes the maintenance reply, and starts `llama.service`.

Filing uses the chat model, so it runs while that model has the GPU. Embedding runs after those rows exist. `updating_server.py` is the process bound to the public port during the window. Chat requests, including ones proxied from port 8081, receive the 503 text. A request to the proxy's own `/health` still reports the proxy.

`refresh-news.sh` sets `NEWS_MEMORY_EXTRACT_THINKING=1`, `NEWS_MEMORY_EXTRACT_MAX_TOKENS` to 16384 (`NEWS_MEMORY_REFRESH_MAX_TOKENS`), and `NEWS_MEMORY_EXTRACT_TIMEOUT` to 600 seconds (`NEWS_MEMORY_REFRESH_EXTRACT_TIMEOUT`). A normal `python worker.py` leaves those at the defaults above.

Feeds fetched more recently than their `interval_minutes` are skipped, the same rule as `python worker.py` with no `--force`. On an empty database every feed is due. The first run files whatever those feeds are publishing now, including the multi-day Google News windows, so the chat can stay offline for much longer than a later night.

`--embed-filed` skips the untouched gazetteer. The full name list is still `python worker.py --embed-pending`.

The embedding server listens on loopback. `NEWS_MEMORY_EMBED_SERVER_DEVICE` selects its GPU (the chat model's `--device`, or `Vulkan0`). `NEWS_MEMORY_EMBED_DEVICE` is the separate in-process torch device (`cpu` or `cuda`) used by `python worker.py --embed-pending`. Query-time semantic search still needs the embedding server or `NEWS_MEMORY_EMBED_LOCAL=1` once the chat model is back, because this script stops the embedding server and then starts `llama.service`.

If the script stops early, it starts `llama.service` again when that service was running. A finished run starts `llama.service` either way. `run/refresh.lock` keeps a second refresh from starting.

```bash
./refresh-news.sh
```

Leave `news-memory-worker.timer` off while this script is how the archive is updated. The timer files on its own schedule through whatever server is on the extract URL.

A system timer does the same one-shot pass every 30 minutes, with a short random delay. It runs as the system user `news-memory`, created from `systemd/news-memory.sysusers`, and it starts at boot rather than at login. The database role is `news-memory` as well (`--user` changes it). That is the name `peer` authentication expects.

```bash
./setup.sh --install-units
sudo systemctl enable --now news-memory-worker.timer
sudo systemctl start news-memory-worker.service
```

`--install-units` also installs `news-memory-tools.service`, `news-memory-chat.service`, and `news-memory-embed.service` as system units under the same account. The tools unit is the Apertus API on port 8091. The embedding unit writes a converted GGUF only when `models/` exists and is writable by `news-memory`. `config.env` is left owned by the installing user, group `news-memory`, mode `640`, so the service can read it. The llama drop-in adds that same group to the dynamic user, which is what lets the Web UI open the file. The install directory itself has to be traversable by that user, which means it cannot live in a home directory mode `700`.

See whether a pass worked:

```bash
psql -h /run/postgresql -U news-memory -d news_memory -c \
  "SELECT s.name, f.last_ok_at, f.last_error
   FROM sources s
   LEFT JOIN feed_state f ON f.source_id = s.id
   ORDER BY f.last_ok_at DESC NULLS LAST
   LIMIT 30;"

psql -h /run/postgresql -U news-memory -d news_memory -c \
  "SELECT at, level, message FROM ingest_log ORDER BY id DESC LIMIT 30;"
```

Ask the store directly after a refresh:

```bash
python query.py search_events 'election' --limit 5
python query.py get_timeline --entities France --from 2026-01-01
```
