import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
import portalocker
from pathlib import Path
from fastapi import HTTPException
from app.ingestion.pipeline import PARSERS
from app.storage.document_repository import DocumentRepository

class DocumentService:
    def __init__(self, db):
        self.db = db
        self.settings = db.settings
        self.repository = DocumentRepository(db)
        self.lock = threading.RLock()

    @contextmanager
    def operation(self):
        with self.lock, portalocker.Lock(str(self.db.path) + '.files.lock', timeout=30):
            yield

    @staticmethod
    def filename(value):
        if not value or len(value) > 255 or '/' in value or '\\' in value or any(ord(c) < 32 for c in value):
            raise HTTPException(400, 'Use a plain filename without directories or control characters')
        suffix = Path(value).suffix.lower()
        if suffix not in PARSERS:
            raise HTTPException(415, 'Supported formats: .md, .txt, .pdf, .docx')
        return value, suffix

    def require(self, identifier, owner, include_deleted=False):
        result = self.repository.get(identifier, owner, include_deleted)
        if not result:
            raise HTTPException(404, 'Document not found')
        return result

    def _queue(self, conn, identifier, owner, version):
        job_id = str(uuid.uuid4())
        now = time.time()
        conn.execute('INSERT INTO jobs(id, document_id, owner_id, version, created_at, updated_at) VALUES (?,?,?,?,?,?)',
                     (job_id, identifier, owner, version, now, now))
        return job_id

    def upload(self, owner, filename, data, identifier=None, expected_version=None, source_key=None):
        filename, suffix = self.filename(filename)
        if not data:
            raise HTTPException(400, 'File is empty')
        if len(data) > self.settings.max_upload_bytes:
            raise HTTPException(413, 'File exceeds upload size limit')
        if suffix in {'.md', '.txt'}:
            try:
                data.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise HTTPException(400, 'Text files must use UTF-8 encoding') from exc
        if suffix == '.pdf' and not data.startswith(b'%PDF-'):
            raise HTTPException(400, 'File is not a PDF')
        if suffix == '.docx' and not data.startswith(b'PK'):
            raise HTTPException(400, 'File is not a DOCX archive')
        digest = hashlib.sha256(data).hexdigest()
        old_path = None
        new_path = None
        with self.operation(), self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = None
            if identifier:
                existing = conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
                if not existing:
                    # Stable identifiers may be imported from another device.
                    try:
                        uuid.UUID(identifier)
                    except ValueError as exc:
                        raise HTTPException(400, 'Document ID must be a UUID') from exc
                    if expected_version not in {None, 0}:
                        raise HTTPException(409, 'Document does not exist at the expected version')
                    if conn.execute('SELECT 1 FROM documents WHERE id=?', (identifier,)).fetchone():
                        raise HTTPException(409, 'Document ID is unavailable')
                elif existing['deleted_at'] is not None:
                    raise HTTPException(409, 'Document was deleted; upload it with a new ID')
                elif expected_version != existing['version']:
                    raise HTTPException(409, 'Version conflict; refresh before replacing the document')
            else:
                duplicate = conn.execute('SELECT id FROM documents WHERE owner_id=? AND content_hash=? AND deleted_at IS NULL', (owner, digest)).fetchone()
                if duplicate:
                    return {'document': self.repository.get(duplicate[0], owner), 'job_id': None, 'duplicate': True}
            if existing and existing['content_hash'] == digest:
                return {'document': self.repository.get(identifier, owner), 'job_id': None, 'duplicate': True}
            if existing and conn.execute("SELECT 1 FROM jobs WHERE document_id=? AND status IN ('queued','running')", (identifier,)).fetchone():
                raise HTTPException(409, 'Document is currently indexing')
            used, count = conn.execute('SELECT COALESCE(SUM(size),0), COUNT(*) FROM documents WHERE owner_id=? AND deleted_at IS NULL', (owner,)).fetchone()
            if used - (existing['size'] if existing else 0) + len(data) > self.settings.max_library_bytes or (not existing and count >= self.settings.max_documents):
                raise HTTPException(413, 'Library quota exceeded')
            identifier = identifier or str(uuid.uuid4())
            version = existing['version'] + 1 if existing else 1
            storage_name = str(uuid.uuid4()) + suffix
            new_path = self.settings.upload_dir / storage_name
            try:
                new_path.write_bytes(self.db.codec.encode(data))
                new_path.chmod(0o600)
                now = time.time()
                if existing:
                    old_path = self.settings.upload_dir / existing['storage_name'] if existing['storage_name'] else None
                    conn.execute("UPDATE documents SET filename=?, content_hash=?, file_type=?, storage_name=?, size=?, status='queued', version=?, error=NULL, updated_at=? WHERE id=?", (filename, digest, suffix, storage_name, len(data), version, now, identifier))
                else:
                    conn.execute('''INSERT INTO documents
                        (id, owner_id, filename, title, content_hash, file_type, storage_name, size, source_key, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                        (identifier, owner, filename, Path(filename).stem, digest, suffix, storage_name, len(data), source_key, now, now))
                job_id = self._queue(conn, identifier, owner, version)
                self.db.event(conn, owner, identifier, version, 'upsert')
            except BaseException:
                new_path.unlink(missing_ok=True)
                raise
        if old_path:
            old_path.unlink(missing_ok=True)
        return {'document': self.repository.get(identifier, owner), 'job_id': job_id, 'duplicate': False}

    def reindex(self, identifier, owner):
        with self.operation(), self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=? AND deleted_at IS NULL', (identifier, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Document not found')
            if not row['storage_name']:
                raise HTTPException(409, 'Upload the original document before reindexing this legacy entry')
            if conn.execute("SELECT 1 FROM jobs WHERE document_id=? AND status IN ('queued','running')", (identifier,)).fetchone():
                raise HTTPException(409, 'Document is already indexing')
            conn.execute("UPDATE documents SET status='queued', error=NULL, updated_at=? WHERE id=?", (time.time(), identifier))
            return self._queue(conn, identifier, owner, row['version'])

    def delete(self, identifier, owner, expected_version=None):
        with self.db.index_lock:
            return self._delete(identifier, owner, expected_version)

    def _delete(self, identifier, owner, expected_version=None):
        with self.operation(), self.db.index_lock, self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Document not found')
            if row['deleted_at']:
                return
            if expected_version is not None and expected_version != row['version']:
                raise HTTPException(409, 'Version conflict')
            now, version = time.time(), row['version'] + 1
            conn.execute("UPDATE documents SET deleted_at=?, updated_at=?, version=?, status='deleted', storage_name='', content_hash='', title='', filename='', size=0, warnings='[]', error=NULL, source_key=NULL, file_type='', model_name=NULL, indexed_version=0 WHERE id=?", (now, now, version, identifier))
            self.db.remove_fts(conn, identifier)
            conn.execute('DELETE FROM chunks WHERE document_id=?', (identifier,))
            conn.execute("UPDATE jobs SET status='cancelled', stage='cancelled', error=NULL WHERE document_id=? AND status IN ('queued','running')", (identifier,))
            conn.execute('DELETE FROM staged_chunks WHERE job_id IN (SELECT id FROM jobs WHERE document_id=?)', (identifier,))
            # FTS rows were removed with the document.
            self.db.bump(conn)
            self.db.event(conn, owner, identifier, version, 'delete')
        if row['storage_name']:
            (self.settings.upload_dir / row['storage_name']).unlink(missing_ok=True)
        # Derived indexes can contain deleted vectors; discard all persisted snapshots.
        for path in self.settings.index_dir.glob('*.index'):
            path.unlink(missing_ok=True)

    def original(self, identifier, owner):
        doc = self.require(identifier, owner)
        if not doc['storage_name']:
            raise HTTPException(404, 'Original file unavailable for this legacy entry')
        path = self.settings.upload_dir / doc['storage_name']
        if not path.exists():
            raise HTTPException(404, 'Original file unavailable')
        return doc, self.db.codec.decode(path.read_bytes())
