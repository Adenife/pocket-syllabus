import threading
from functools import lru_cache
import numpy as np
from app.core.config import settings

class SearchServiceError(RuntimeError):
    pass


class EmbeddingService:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self._model = None

    @property
    def model(self):
        with self.lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                import torch
                torch.set_num_threads(self.settings.embedding_threads)
                try:
                    self._model = SentenceTransformer(self.settings.model_name,
                                                     local_files_only=self.settings.offline, device="cpu")
                except Exception as exc:
                    raise SearchServiceError('Embedding model unavailable. Cache it online before enabling offline mode.') from exc
            return self._model

    @property
    def tokenizer(self):
        return self.model.tokenizer

    @property
    def max_tokens(self):
        return self.model.max_seq_length

    def encode(self, texts):
        with self.lock:
            result = np.asarray(self.model.encode(texts, batch_size=self.settings.batch_size,
                normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)
        if result.ndim != 2 or len(result) != len(texts) or not np.isfinite(result).all():
            raise SearchServiceError('Model returned invalid embeddings')
        if np.any(np.linalg.norm(result, axis=1) == 0):
            raise SearchServiceError('Model returned zero embeddings')
        return result

@lru_cache(maxsize=1)
def get_default_embedder():
    return EmbeddingService(settings)


def encode_texts(texts):
    return get_default_embedder().encode(texts)


def get_embedding_model():
    return get_default_embedder().model
