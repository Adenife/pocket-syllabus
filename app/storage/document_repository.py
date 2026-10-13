import json

class DocumentRepository:
    def __init__(self, db):
        self.db = db

    def get(self, identifier, owner, include_deleted=False):
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=?' +
                ('' if include_deleted else ' AND deleted_at IS NULL'), (identifier, owner)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['warnings'] = json.loads(result['warnings'])
            latest = conn.execute('SELECT id,status,stage,progress,chunks,error,attempts,document_id FROM jobs WHERE document_id=? ORDER BY created_at DESC LIMIT 1', (identifier,)).fetchone()
            result['job'] = dict(latest) if latest else None
            result['chunk_count'] = conn.execute('SELECT COUNT(*) FROM chunks WHERE document_id=?', (identifier,)).fetchone()[0]
            return result

    def list(self, owner, offset=0, limit=100):
        with self.db.connect() as conn:
            ids = [row[0] for row in conn.execute('SELECT id FROM documents WHERE owner_id=? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?', (owner, limit, offset))]
        return [self.get(identifier, owner) for identifier in ids]
