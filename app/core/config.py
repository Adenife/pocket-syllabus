"""Runtime settings; paths can be relocated for tests and containers."""
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

def flag(name, default="0"):
    return os.getenv(name, default).lower() in {"1", "true", "yes"}

@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("POCKET_DB_PATH", str(BASE_DIR / "database/syllabus.db"))))
    upload_dir: Path = field(default_factory=lambda: Path(os.getenv("POCKET_UPLOAD_DIR", str(BASE_DIR / "data/uploads"))))
    index_dir: Path = field(default_factory=lambda: Path(os.getenv("POCKET_INDEX_DIR", str(BASE_DIR / "database/indexes"))))
    model_name: str = field(default_factory=lambda: os.getenv("POCKET_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"))
    offline: bool = field(default_factory=lambda: flag("POCKET_SYLLABUS_OFFLINE"))
    auth_enabled: bool = field(default_factory=lambda: flag("POCKET_AUTH_ENABLED"))
    registration_enabled: bool = field(default_factory=lambda: flag("POCKET_REGISTRATION_ENABLED", "1"))
    worker_enabled: bool = field(default_factory=lambda: flag("POCKET_WORKER_ENABLED", "1"))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("POCKET_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)))
    max_library_bytes: int = field(default_factory=lambda: int(os.getenv("POCKET_MAX_LIBRARY_BYTES", 1024 * 1024 * 1024)))
    max_documents: int = field(default_factory=lambda: int(os.getenv("POCKET_MAX_DOCUMENTS", 1000)))
    embedding_threads: int = field(default_factory=lambda: int(os.getenv('POCKET_EMBEDDING_THREADS', 2)))
    batch_size: int = field(default_factory=lambda: int(os.getenv("POCKET_BATCH_SIZE", 32)))
    chunk_tokens: int = field(default_factory=lambda: int(os.getenv("POCKET_CHUNK_TOKENS", 220)))
    overlap_tokens: int = field(default_factory=lambda: int(os.getenv("POCKET_OVERLAP_TOKENS", 32)))
    ann_threshold: int = field(default_factory=lambda: int(os.getenv("POCKET_ANN_THRESHOLD", 5000)))
    rate_limit: int = field(default_factory=lambda: int(os.getenv("POCKET_RATE_LIMIT", 120)))
    encryption_key: str = field(default_factory=lambda: os.getenv("POCKET_ENCRYPTION_KEY", ""))

    def __post_init__(self):
        if min(self.embedding_threads, self.batch_size, self.chunk_tokens, self.ann_threshold, self.rate_limit,
               self.max_upload_bytes, self.max_library_bytes, self.max_documents) < 1:
            raise ValueError("Limits must be positive")
        if not 0 <= self.overlap_tokens < self.chunk_tokens:
            raise ValueError("Overlap must be smaller than the chunk budget")

settings = Settings()
DB_PATH = settings.db_path
DATA_DIR = BASE_DIR / "data/samples"
MODEL_NAME = settings.model_name
OFFLINE_MODE = settings.offline
