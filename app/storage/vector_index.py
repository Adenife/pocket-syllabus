"""Per-library cached FAISS snapshots; HNSW above the configured threshold."""
import hashlib
import os
import threading
import uuid
from collections import OrderedDict
import faiss
import numpy as np
from app.services.embedding_service import SearchServiceError

class VectorIndex:
    def __init__(self, db):
        self.db = db
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        self.build_count = 0
        # Avoid oversubscribing CPUs when the embedding model is also active.
        faiss.omp_set_num_threads(1)

    def snapshot(self, owner, document_ids=()):
        document_ids = tuple(sorted(set(document_ids)))
        with self.lock, self.db.index_lock, self.db.connect() as conn:
            conn.execute('BEGIN')
            generation = int(conn.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])
            library_id = conn.execute("SELECT value FROM meta WHERE key='library_id'").fetchone()[0]
            key = (owner, document_ids, generation, self.db.settings.model_name, library_id)
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            tag = hashlib.sha256(repr(key).encode()).hexdigest()
            path = self.db.settings.index_dir / (tag + '.index')
            where = 'owner_id=?'
            args = [owner]
            if document_ids:
                where += ' AND document_id IN (' + ','.join('?' for _ in document_ids) + ')'
                args.extend(document_ids)
            models = {row[0] for row in conn.execute('SELECT DISTINCT model_name FROM chunks WHERE ' + where, args)}
            if models and models != {self.db.settings.model_name}:
                raise SearchServiceError('Library uses another embedding model. Reindex the affected documents.')
            if path.exists():
                try:
                    index = faiss.deserialize_index(np.frombuffer(self.db.codec.decode(path.read_bytes()), dtype=np.uint8))
                except Exception:
                    path.unlink(missing_ok=True)
                    index = self._build(conn, where, args)
            else:
                index = self._build(conn, where, args)
            if index is not None and not path.exists():
                temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                try:
                    temporary.write_bytes(self.db.codec.encode(faiss.serialize_index(index).tobytes()))
                    temporary.chmod(0o600)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            # Bounded number of resident library/filter snapshots, and bounded disk snapshots.
            self.cache = OrderedDict((k, v) for k, v in self.cache.items() if k[2] == generation)
            self.cache[key] = index
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
            files = sorted(self.db.settings.index_dir.glob('*.index'), key=lambda p: p.stat().st_mtime)
            for stale in files[:-32]:
                stale.unlink(missing_ok=True)
            return index

    def _build(self, conn, where, args):
        count = conn.execute('SELECT COUNT(*) FROM chunks WHERE ' + where, args).fetchone()[0]
        if not count:
            return None
        index = None
        cursor = conn.execute('SELECT id, embedding FROM chunks WHERE ' + where + ' ORDER BY id', args)
        while rows := cursor.fetchmany(256):
            vectors = []
            for row in rows:
                try:
                    vector = np.frombuffer(self.db.codec.decode(row['embedding']), dtype=np.float32).copy()
                except Exception as exc:
                    raise SearchServiceError('Invalid index vector. Reindex the document.') from exc
                if not len(vector) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                    raise SearchServiceError('Invalid index vector. Reindex the document.')
                vectors.append(vector)
            try:
                matrix = np.array(vectors, dtype=np.float32)
            except ValueError as exc:
                raise SearchServiceError('Incompatible vector dimensions. Reindex the document.') from exc
            if index is None:
                base = (faiss.IndexHNSWFlat(matrix.shape[1], 32, faiss.METRIC_INNER_PRODUCT)
                        if count >= self.db.settings.ann_threshold else faiss.IndexFlatIP(matrix.shape[1]))
                if hasattr(base, 'hnsw'):
                    base.hnsw.efConstruction = 80
                    base.hnsw.efSearch = 96
                index = faiss.IndexIDMap2(base)
            if index.d != matrix.shape[1]:
                raise SearchServiceError('Incompatible vector dimensions. Reindex the document.')
            faiss.normalize_L2(matrix)
            index.add_with_ids(matrix, np.array([row['id'] for row in rows], dtype=np.int64))
        self.build_count += 1
        return index
