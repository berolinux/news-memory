-- news-memory schema. Idempotent. Requires extensions vector + pg_trgm
-- (setup.sh creates those as a superuser before applying this file).

CREATE TABLE IF NOT EXISTS sources (
	id          smallserial PRIMARY KEY,
	name        text UNIQUE NOT NULL,
	homepage    text,
	feed_url    text,
	feed_type          text NOT NULL DEFAULT 'rss',
	lang               text,
	country_iso        char(2),
	interval_minutes   integer NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS feed_state (
	source_id      smallint PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
	etag           text,
	last_modified  text,
	last_ok_at     timestamptz,
	last_error     text
);

CREATE TABLE IF NOT EXISTS articles (
	id             bigserial PRIMARY KEY,
	source_id      smallint REFERENCES sources(id),
	url            text UNIQUE NOT NULL,
	simhash        bigint,
	published_at   timestamptz NOT NULL,
	ingested_at    timestamptz NOT NULL DEFAULT now(),
	title          text NOT NULL,
	body           text,
	summary        text,
	summary_en     text,
	lang           text,
	importance     smallint,
	extract_json   jsonb,
	extract_status text NOT NULL DEFAULT 'pending',
	embedding      vector(1024)
);

CREATE INDEX IF NOT EXISTS articles_published_idx ON articles (published_at DESC);
CREATE INDEX IF NOT EXISTS articles_simhash_idx ON articles (simhash);
CREATE INDEX IF NOT EXISTS articles_extract_idx ON articles (extract_status);
CREATE INDEX IF NOT EXISTS articles_fts_idx ON articles
	USING gin (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, '')));
CREATE INDEX IF NOT EXISTS articles_embedding_idx ON articles
	USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS entities (
	id             bigserial PRIMARY KEY,
	canonical      text NOT NULL,
	type           text NOT NULL,
	country_iso    char(2),
	wikidata_qid   text,
	provisional    boolean NOT NULL DEFAULT false,
	mention_count  integer NOT NULL DEFAULT 0,
	embedding      vector(1024),
	created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS entities_country_iso_idx
	ON entities (country_iso) WHERE country_iso IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS entities_canonical_type_idx
	ON entities (lower(canonical), type);
CREATE INDEX IF NOT EXISTS entities_type_idx ON entities (type);
CREATE INDEX IF NOT EXISTS entities_embedding_idx ON entities
	USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS entity_aliases (
	entity_id  bigint NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
	alias      text NOT NULL,
	PRIMARY KEY (entity_id, alias)
);

CREATE INDEX IF NOT EXISTS entity_aliases_lower_idx
	ON entity_aliases (lower(alias));
CREATE INDEX IF NOT EXISTS entity_aliases_trgm_idx
	ON entity_aliases USING gin (alias gin_trgm_ops);

CREATE TABLE IF NOT EXISTS events (
	id            bigserial PRIMARY KEY,
	article_id    bigint REFERENCES articles(id) ON DELETE CASCADE,
	happened_at   date NOT NULL,
	event_type    text NOT NULL,
	tags          text[] NOT NULL DEFAULT '{}',
	summary       text NOT NULL,
	importance    smallint NOT NULL
);

CREATE INDEX IF NOT EXISTS events_when_idx ON events (happened_at DESC, event_type);
CREATE INDEX IF NOT EXISTS events_tags_idx ON events USING gin (tags);
CREATE INDEX IF NOT EXISTS events_fts_idx ON events
	USING gin (to_tsvector('simple', coalesce(summary, '')));

CREATE TABLE IF NOT EXISTS event_entities (
	event_id   bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
	entity_id  bigint NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
	role       text NOT NULL,
	PRIMARY KEY (event_id, entity_id)
);

CREATE INDEX IF NOT EXISTS event_entities_entity_idx ON event_entities (entity_id);

CREATE TABLE IF NOT EXISTS entity_relations (
	id             bigserial PRIMARY KEY,
	src_entity_id  bigint NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
	dst_entity_id  bigint NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
	rel_type       text NOT NULL,
	valid_from     date,
	valid_to       date,
	article_id     bigint REFERENCES articles(id) ON DELETE SET NULL,
	fact           text,
	superseded     boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS entity_relations_dst_idx
	ON entity_relations (dst_entity_id, rel_type, superseded);
CREATE INDEX IF NOT EXISTS entity_relations_src_idx
	ON entity_relations (src_entity_id, rel_type, superseded);

CREATE TABLE IF NOT EXISTS dossiers (
	id                   bigserial PRIMARY KEY,
	slug                 text UNIQUE NOT NULL,
	title                text NOT NULL,
	kind                 text NOT NULL,
	current_status       text NOT NULL DEFAULT '',
	body_compact         text NOT NULL DEFAULT '',
	updated_at           timestamptz NOT NULL DEFAULT now(),
	last_status_rewrite  timestamptz,
	embedding            vector(1024)
);

CREATE INDEX IF NOT EXISTS dossiers_kind_idx ON dossiers (kind);
CREATE INDEX IF NOT EXISTS dossiers_fts_idx ON dossiers
	USING gin (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(current_status, '') || ' ' || coalesce(body_compact, '')));
CREATE INDEX IF NOT EXISTS dossiers_embedding_idx ON dossiers
	USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS dossier_entities (
	dossier_id  bigint NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
	entity_id   bigint NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
	PRIMARY KEY (dossier_id, entity_id)
);

CREATE INDEX IF NOT EXISTS dossier_entities_entity_idx ON dossier_entities (entity_id);

CREATE TABLE IF NOT EXISTS dossier_timeline (
	id           bigserial PRIMARY KEY,
	dossier_id   bigint NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
	happened_at  date NOT NULL,
	article_id   bigint REFERENCES articles(id) ON DELETE SET NULL,
	event_id     bigint REFERENCES events(id) ON DELETE SET NULL,
	importance   smallint NOT NULL DEFAULT 2,
	event_type   text,
	tags         text[] NOT NULL DEFAULT '{}',
	bullet       text NOT NULL
);

CREATE INDEX IF NOT EXISTS dossier_timeline_lookup_idx
	ON dossier_timeline (dossier_id, happened_at DESC);

CREATE TABLE IF NOT EXISTS ingest_log (
	id         bigserial PRIMARY KEY,
	at         timestamptz NOT NULL DEFAULT now(),
	level      text NOT NULL,
	message    text NOT NULL,
	payload    jsonb
);

-- upgrades for databases created before multilingual columns existed
ALTER TABLE sources ADD COLUMN IF NOT EXISTS lang text;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS country_iso char(2);
ALTER TABLE sources ADD COLUMN IF NOT EXISTS interval_minutes integer NOT NULL DEFAULT 30;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS summary_en text;
