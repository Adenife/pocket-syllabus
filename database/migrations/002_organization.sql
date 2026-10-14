CREATE TABLE IF NOT EXISTS categories (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('subject','tag','collection')),
 name TEXT NOT NULL, normalized_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 UNIQUE(owner_id,kind,normalized_name)
);
CREATE TABLE IF NOT EXISTS document_categories (
 document_id TEXT NOT NULL REFERENCES documents(id), category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
 PRIMARY KEY(document_id,category_id)
);
CREATE INDEX IF NOT EXISTS category_documents ON document_categories(category_id,document_id);
CREATE TABLE IF NOT EXISTS bookmarks (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, document_id TEXT NOT NULL REFERENCES documents(id),
 excerpt BLOB NOT NULL, annotation BLOB NOT NULL, section TEXT NOT NULL, page INTEGER, line INTEGER,
 document_version INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS bookmarks_owner ON bookmarks(owner_id,document_id);
UPDATE meta SET value='2' WHERE key='schema_version';
