CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('generation', '0');
INSERT OR IGNORE INTO meta VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
 hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, filename TEXT NOT NULL, title TEXT NOT NULL,
 content_hash TEXT NOT NULL, file_type TEXT NOT NULL, storage_name TEXT NOT NULL,
 size INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued', version INTEGER NOT NULL DEFAULT 1,
 indexed_version INTEGER NOT NULL DEFAULT 0, model_name TEXT,
 warnings TEXT NOT NULL DEFAULT '[]', error TEXT, source_key TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, deleted_at REAL
);
CREATE INDEX IF NOT EXISTS documents_owner ON documents(owner_id, deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS documents_source ON documents(owner_id, source_key) WHERE source_key IS NOT NULL AND deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL REFERENCES documents(id),
 owner_id TEXT NOT NULL, ordinal INTEGER NOT NULL, source_title TEXT NOT NULL, section TEXT NOT NULL,
 page INTEGER, line INTEGER, text BLOB NOT NULL, embedding BLOB NOT NULL, model_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_owner ON chunks(owner_id, document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text);
CREATE TABLE IF NOT EXISTS staged_chunks (
 job_id TEXT NOT NULL, ordinal INTEGER NOT NULL, source_title TEXT NOT NULL, section TEXT NOT NULL,
 page INTEGER, line INTEGER, text BLOB NOT NULL, embedding BLOB NOT NULL, model_name TEXT NOT NULL,
 PRIMARY KEY(job_id, ordinal)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), owner_id TEXT NOT NULL,
 version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT 'queued',
 progress INTEGER NOT NULL DEFAULT 0, chunks INTEGER NOT NULL DEFAULT 0, error TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active ON jobs(document_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, document_id TEXT NOT NULL,
 version INTEGER NOT NULL, action TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_owner ON events(owner_id, seq);
CREATE TABLE IF NOT EXISTS uploads (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, filename TEXT NOT NULL, total INTEGER NOT NULL,
 offset INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL
);
