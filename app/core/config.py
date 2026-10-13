"""Paths are independent of the process working directory."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "database" / "syllabus.db"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Set POCKET_SYLLABUS_OFFLINE=1 after the first model download.
OFFLINE_MODE = os.getenv("POCKET_SYLLABUS_OFFLINE", "0").lower() in {"1", "true", "yes"}
