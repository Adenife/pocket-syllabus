"""SQLite schema management and transactions. Database is the source of truth."""
import hashlib
import sqlite3
import time
import threading
import uuid
from contextlib import contextmanager
from app.core.config import BASE_DIR
from app.core.security import Codec

class Database:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.db_path
        self.codec = Codec(settings.encryption_key)
        self.index_lock = threading.RLock()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA secure_delete=ON')
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings.index_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            columns = [r['name'] for r in conn.execute('PRAGMA table_info(chunks)')]
            if columns and 'document_id' not in columns:
                if self.settings.encryption_key:
                    raise ValueError('Migrate legacy data without encryption first, then use a fresh encrypted library')
                conn.execute('ALTER TABLE chunks RENAME TO legacy_chunks')
            conn.executescript((BASE_DIR / 'database/migrations/001_library.sql').read_text())
            # Refuse mismatched keys, rather than silently writing a mixed-format library.
            marker = hashlib.sha256(self.settings.encryption_key.encode()).hexdigest()
            existing = conn.execute("SELECT value FROM meta WHERE key='encryption'").fetchone()
            if existing and existing['value'] != marker:
                raise ValueError('Storage encryption key differs from the library key')
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('encryption', ?)", (marker,))
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('library_id', ?)", (str(uuid.uuid4()),))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_chunks'").fetchone():
                self._migrate_legacy(conn)
        self.path.chmod(0o600)

    def _migrate_legacy(self, conn):
        for source in conn.execute('SELECT DISTINCT source_path FROM legacy_chunks').fetchall():
            rows = conn.execute('SELECT * FROM legacy_chunks WHERE source_path=? ORDER BY id', (source[0],)).fetchall()
            identifier = str(uuid.uuid4())
            now = time.time()
            conn.execute("""INSERT INTO documents
                (id, owner_id, filename, title, content_hash, file_type, storage_name, size, status,
                 indexed_version, model_name, source_key, created_at, updated_at, warnings)
                VALUES (?, 'local', ?, ?, '', '.md', '', 0, 'ready', 1, ?, ?, ?, ?, ?)""",
                (identifier, source[0], rows[0]['source_title'], self.settings.model_name,
                 'legacy:' + source[0], now, now, '["Legacy index: upload the original to enable downloads."]'))
            for order, row in enumerate(rows):
                conn.execute("""INSERT INTO chunks
                    (document_id, owner_id, ordinal, source_title, section, text, embedding, model_name)
                    VALUES (?, 'local', ?, ?, ?, ?, ?, ?)""",
                    (identifier, order, row['source_title'], row['section'], row['text'].encode(),
                     row['embedding'], self.settings.model_name))
            self.event(conn, 'local', identifier, 1, 'upsert')
        conn.execute('DROP TABLE legacy_chunks')
        self.refresh_fts(conn)
        self.bump(conn)

    def refresh_fts(self, conn):
        conn.execute('DELETE FROM chunks_fts')
        if not self.settings.encryption_key:
            conn.execute('INSERT INTO chunks_fts(rowid, text) SELECT id, CAST(text AS TEXT) FROM chunks')

    def remove_fts(self, conn, identifier):
        conn.execute('DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE document_id=?)', (identifier,))

    def add_fts(self, conn, identifier):
        if not self.settings.encryption_key:
            conn.execute('INSERT INTO chunks_fts(rowid,text) SELECT id,CAST(text AS TEXT) FROM chunks WHERE document_id=?', (identifier,))

    @staticmethod
    def bump(conn):
        conn.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")

    @staticmethod
    def event(conn, owner, identifier, version, action):
        conn.execute('INSERT INTO events(owner_id, document_id, version, action, created_at) VALUES (?,?,?,?,?)',
                     (owner, identifier, version, action, time.time()))
