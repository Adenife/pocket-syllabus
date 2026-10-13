"""Local embedding generation and SQLite cosine-similarity retrieval."""
import sqlite3
from functools import lru_cache
from pathlib import Path
from threading import Lock

import numpy as np

from app.core.config import DB_PATH, MODEL_NAME, OFFLINE_MODE
from app.schemas.resource import SearchResultItem


class SearchServiceError(RuntimeError):
    """An actionable indexing or model availability error."""


_model_lock = Lock()


@lru_cache(maxsize=1)
def get_embedding_model():
    # Lazy loading lets health checks work before the model is installed/cached.
    from sentence_transformers import SentenceTransformer
    try:
        return SentenceTransformer(MODEL_NAME, local_files_only=OFFLINE_MODE)
    except Exception as exc:
        raise SearchServiceError(
            "Embedding model unavailable. Run python ingest.py with internet access "
            "once to cache the model before enabling offline mode."
        ) from exc


def encode_texts(texts: list[str]) -> np.ndarray:
    with _model_lock:
        model = get_embedding_model()
        return np.asarray(model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        ), dtype=np.float32)


class SearchService:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)

    def search(self, query: str, limit: int = 3) -> list[SearchResultItem]:
        if not self.db_path.is_file():
            raise SearchServiceError("Index missing. Run python ingest.py first.")
        try:
            # Read-only connections never create an empty database by accident.
            with sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                rows = conn.execute(
                    "SELECT id, source_title, section, text, embedding FROM chunks"
                ).fetchall()
        except sqlite3.Error as exc:
            raise SearchServiceError("Index unavailable. Run python ingest.py to rebuild it.") from exc
        if not rows:
            return []
        query_vector = encode_texts([query])[0]
        query_norm = float(np.linalg.norm(query_vector))
        if not np.isfinite(query_norm) or query_norm == 0:
            raise SearchServiceError("Model returned an invalid query embedding.")
        ranked = []
        for chunk_id, title, section, text, blob in rows:
            try:
                vector = np.frombuffer(blob, dtype=np.float32)
            except (ValueError, TypeError) as exc:
                raise SearchServiceError("Invalid index vector. Run python ingest.py again.") from exc
            if vector.shape != query_vector.shape or not np.isfinite(vector).all():
                raise SearchServiceError("Index embeddings are incompatible. Run python ingest.py again.")
            norm = float(np.linalg.norm(vector))
            score = float(np.dot(query_vector, vector) / (query_norm * norm)) if norm else 0.0
            ranked.append(SearchResultItem(
                id=chunk_id, source_title=title, section=section,
                text_excerpt=text, score=float(np.clip(score, -1.0, 1.0)),
            ))
        return sorted(ranked, key=lambda item: (-item.score, item.id))[:limit]
