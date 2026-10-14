"""Versioned changes and durable resumable uploads; clients decide conflicts."""
import time
import uuid
from fastapi import HTTPException

class SyncService:
    def __init__(self, documents):
        self.documents = documents
        self.db = documents.db

    def changes(self, owner, after=0, limit=100):
        with self.db.connect() as conn:
            events = conn.execute('SELECT * FROM events WHERE owner_id=? AND seq>? ORDER BY seq LIMIT ?', (owner, after, limit)).fetchall()
            records = []
            for event in events:
                doc = self.documents.repository.get(event['document_id'], owner, include_deleted=True)
                if hasattr(self,'library'):
                    doc['organization']=self.library.portable(doc)
                records.append({'seq': event['seq'], 'action': 'delete' if doc['deleted_at'] else 'upsert', 'document': doc})
            return {'changes': records, 'cursor': events[-1]['seq'] if events else after, 'has_more': len(events) == limit}

    def create_upload(self, owner, filename, total):
        self.documents.filename(filename)
        if total > self.db.settings.max_upload_bytes:
            raise HTTPException(413, 'File exceeds upload size limit')
        identifier = str(uuid.uuid4())
        with self.documents.operation(), self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Limit unfinished sessions and expire abandoned temporary files.
            expired = conn.execute('SELECT id FROM uploads WHERE created_at<?', (time.time() - 86400,)).fetchall()
            for row in expired:
                (self.db.settings.upload_dir / (row['id'] + '.part')).unlink(missing_ok=True)
            conn.execute('DELETE FROM uploads WHERE created_at<?', (time.time() - 86400,))
            count = conn.execute('SELECT COUNT(*) FROM uploads WHERE owner_id=?', (owner,)).fetchone()[0]
            if count >= 3:
                raise HTTPException(429, 'Finish or cancel existing uploads first')
            conn.execute('INSERT INTO uploads(id,owner_id,filename,total,created_at) VALUES (?,?,?,?,?)', (identifier, owner, filename, total, time.time()))
        return self.upload_status(identifier, owner)

    def upload_status(self, identifier, owner):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM uploads WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
        if not row:
            raise HTTPException(404, 'Upload session not found')
        return dict(row)

    def append(self, identifier, owner, offset, data):
        if not data:
            raise HTTPException(400, 'Empty upload segment')
        if len(data) > 1024 * 1024:
            raise HTTPException(413, 'Segments must be at most 1 MiB')
        with self.documents.operation(), self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM uploads WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Upload session not found')
            if row['offset'] != offset:
                raise HTTPException(409, f"Resume at offset {row['offset']}")
            if offset + len(data) > row['total']:
                raise HTTPException(413, 'Segment exceeds declared file size')
            path = self.db.settings.upload_dir / (identifier + '.part')
            previous = self.db.codec.decode(path.read_bytes())[:offset] if path.exists() else b''
            if len(previous) != offset:
                raise HTTPException(409, 'Incomplete session storage; cancel and restart')
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(self.db.codec.encode(previous + data))
            temporary.chmod(0o600)
            temporary.replace(path)
            conn.execute('UPDATE uploads SET offset=? WHERE id=?', (offset + len(data), identifier))
        return self.upload_status(identifier, owner)

    def complete(self, identifier, owner, document_id=None, expected_version=None, expected_metadata_version=None,preserve_trash=False):
        with self.documents.lock:
            row = self.upload_status(identifier, owner)
            if row['offset'] != row['total']:
                raise HTTPException(409, 'Upload is incomplete')
            path = self.db.settings.upload_dir / (identifier + '.part')
            data = self.db.codec.decode(path.read_bytes())
            result = self.documents.upload(owner, row['filename'], data, document_id, expected_version, expected_metadata_version=expected_metadata_version,allow_trashed=preserve_trash)
            self.cancel(identifier, owner)
            return result

    def cancel(self, identifier, owner):
        with self.documents.operation():
            self.upload_status(identifier, owner)
            with self.db.connect() as conn:
                conn.execute('DELETE FROM uploads WHERE id=? AND owner_id=?', (identifier, owner))
            (self.db.settings.upload_dir / (identifier + '.part')).unlink(missing_ok=True)
