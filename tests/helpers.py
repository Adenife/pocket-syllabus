import re
import tempfile
from pathlib import Path
import numpy as np
from app.core.config import Settings
from app.services.context import Context

class Tokenizer:
    def __call__(self, text, **kwargs):
        offsets = [(match.start(), match.end()) for match in re.finditer(r'\S+', text)]
        return {'offset_mapping': offsets, 'input_ids': list(range(len(offsets)))}
    def encode(self, text, add_special_tokens=True):
        return list(range(len(text.split()) + (2 if add_special_tokens else 0)))
    def num_special_tokens_to_add(self, pair=False):
        return 2

class Embedder:
    tokenizer = Tokenizer()
    max_tokens = 16
    def __init__(self):
        self.calls = []
        self.fail = False
    def encode(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            from app.services.embedding_service import SearchServiceError
            raise SearchServiceError('Model unavailable')
        return np.array([[1, 0, 0] if any(term in text.lower() for term in ['light', 'photosynthesis'])
                         else [0, 1, 0] if 'motion' in text.lower() else [0, 0, 1] for text in texts], dtype=np.float32)


def context(folder, **kwargs):
    folder = Path(folder)
    return Context(Settings(db_path=folder / 'library.db', upload_dir=folder / 'uploads',
        index_dir=folder / 'indexes', worker_enabled=False, batch_size=2,
        chunk_tokens=12, overlap_tokens=2, **kwargs), Embedder())


def upload_ready(ctx, text='# Biology\n## Energy\nLight powers plants.\n\nCells contain DNA.', filename='book.md', owner='local'):
    result = ctx.documents.upload(owner, filename, text.encode())
    ctx.worker.run_once()
    return result['document']['id']
