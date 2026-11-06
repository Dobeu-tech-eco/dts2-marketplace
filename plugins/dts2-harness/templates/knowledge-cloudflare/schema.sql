-- Personal knowledge store schema (entry model matches scripts/knowledge.py).
-- Apply with: npx wrangler d1 execute dts2-knowledge --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS entries (
  "key"     TEXT PRIMARY KEY CHECK ("key" GLOB '[a-z0-9]*' AND length("key") <= 64),
  kind      TEXT NOT NULL DEFAULT 'preference' CHECK (kind IN ('preference', 'term', 'learning')),
  value     TEXT NOT NULL,
  aliases   TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
  tags      TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
  updated   TEXT NOT NULL,               -- UTC, YYYY-MM-DDTHH:MM:SSZ
  "by"      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS entries_kind ON entries (kind);

CREATE TABLE IF NOT EXISTS meta (
  "key"   TEXT PRIMARY KEY,
  value   TEXT NOT NULL
);

-- Edit the owner label before applying (any short name; not a secret).
INSERT OR IGNORE INTO meta ("key", value) VALUES ('owner', 'acme');
