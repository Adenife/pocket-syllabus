import re

class ChunkRepository:
    def __init__(self, db):
        self.db = db

    def fetch(self, ids, owner):
        if not ids:
            return {}
        with self.db.connect() as conn:
            rows = conn.execute('''SELECT c.*, d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE c.owner_id=? AND d.deleted_at IS NULL AND c.id IN (''' + ','.join('?' for _ in ids) + ')', [owner, *ids]).fetchall()
        result = {}
        for row in rows:
            record = dict(row)
            record['text'] = self.db.codec.decode(record['text']).decode()
            result[row['id']] = record
        return result

    def lexical(self, query, owner, document_ids, limit):
        if self.db.settings.encryption_key:
            return []  # No plaintext full-text mirror in encrypted libraries.
        terms = re.findall(r'\w+', query, flags=re.UNICODE)[:32]
        if not terms:
            return []
        expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        with self.db.connect() as conn:
            sql = '''SELECT f.rowid FROM chunks_fts f JOIN chunks c ON c.id=f.rowid
                WHERE chunks_fts MATCH ? AND c.owner_id=?'''
            args = [expression, owner]
            if document_ids:
                sql += ' AND c.document_id IN (' + ','.join('?' for _ in document_ids) + ')'
                args.extend(document_ids)
            return [row[0] for row in conn.execute(sql + ' ORDER BY bm25(chunks_fts), f.rowid LIMIT ?', [*args, limit])]
