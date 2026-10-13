"""Cached semantic and keyword retrieval, with document ownership enforced."""
import numpy as np
from app.schemas.resource import SearchResultItem
from app.services.embedding_service import SearchServiceError, encode_texts, get_embedding_model
from app.storage.chunk_repository import ChunkRepository
from app.storage.vector_index import VectorIndex

class SearchService:
    def __init__(self, db, embedder):
        self.db, self.embedder = db, embedder
        self.index = VectorIndex(db)
        self.chunks = ChunkRepository(db)

    def search(self, query, limit=3, owner='local', document_ids=(), hybrid=True):
        index = self.index.snapshot(owner, document_ids)
        if index is None:
            return []
        vector = np.asarray(self.embedder.encode([query]), dtype=np.float32)
        if vector.shape != (1, index.d) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise SearchServiceError('Invalid or incompatible query vector. Reindex with the configured model.')
        vector /= np.linalg.norm(vector)
        count = min(index.ntotal, max(limit * 8, 64))
        scores, ids = index.search(vector, count)
        semantic = sorted([(int(i), float(np.clip(s, -1, 1))) for i, s in zip(ids[0], scores[0]) if i != -1], key=lambda pair: (-pair[1], pair[0]))
        lexical = self.chunks.lexical(query, owner, document_ids, count) if hybrid else []
        score_map = dict(semantic)
        if lexical:
            ranks = {}
            for ranked in [[i for i, _ in semantic], lexical]:
                for rank, identifier in enumerate(ranked, 1):
                    ranks[identifier] = ranks.get(identifier, 0) + 1 / (60 + rank)
            winners = sorted(ranks, key=lambda i: (-ranks[i], i))[:limit]
        else:
            winners = [i for i, _ in semantic[:limit]]
        rows = self.chunks.fetch(winners, owner)
        results = []
        for identifier in winners:
            if identifier not in rows:
                continue  # A concurrent deletion/reindex can remove a snapshot result.
            row = rows[identifier]
            score = score_map.get(identifier)
            if score is None:
                stored = np.frombuffer(self.db.codec.decode(row['embedding']), dtype=np.float32)
                score = float(np.clip(np.dot(stored, vector[0]) / np.linalg.norm(stored), -1, 1))
            results.append(SearchResultItem(id=identifier, document_id=row['document_id'],
                source_title=row['source_title'], section=row['section'], text_excerpt=row['text'], score=score,
                page=row['page'], line=row['line'], filename=row['filename']))
        return results
