"""Index markdown locally: python ingest.py [--data-dir PATH] [--db-path PATH]."""
import argparse
import re
import sqlite3
from pathlib import Path

import numpy as np

from app.core.config import DATA_DIR, DB_PATH
from app.services.search_service import encode_texts, SearchServiceError


def chunk_markdown(content: str, fallback_title: str, max_words: int = 180):
    """Preserve heading citations; split long paragraphs into bounded chunks."""
    title = fallback_title
    section = "Introduction"
    paragraphs = []
    buffer = []

    def flush():
        if buffer:
            words = " ".join(buffer).split()
            for start in range(0, len(words), max_words):
                paragraphs.append((title, section, " ".join(words[start:start + max_words])))
            buffer.clear()

    for line in content.splitlines():
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush()
            if len(heading.group(1)) == 1:
                title = heading.group(2)
            section = heading.group(2)
        elif not line.strip():
            flush()
        else:
            buffer.append(line.strip())
    flush()
    return paragraphs


def ingest(data_dir: Path = DATA_DIR, db_path: Path = DB_PATH) -> int:
    data_dir, db_path = Path(data_dir), Path(db_path)
    paths = sorted(data_dir.rglob("*.md")) if data_dir.is_dir() else []
    if not paths:
        raise ValueError(f"No markdown files found in {data_dir}")
    chunks = []
    for path in paths:
        source = path.relative_to(data_dir).as_posix()
        for title, section, text in chunk_markdown(path.read_text(encoding="utf-8"), path.stem):
            chunks.append((source, title, section, text))
    if not chunks:
        raise ValueError("Markdown files contain no indexable paragraphs")
    # Finish model work before replacing the existing index.
    embeddings = encode_texts([chunk[3] for chunk in chunks])
    if embeddings.ndim != 2 or len(embeddings) != len(chunks) or not np.isfinite(embeddings).all():
        raise ValueError("Model returned invalid embeddings")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_title TEXT NOT NULL,
            section TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL
        )""")
        conn.execute("DELETE FROM chunks")
        conn.executemany(
            "INSERT INTO chunks (source_path, source_title, section, text, embedding) VALUES (?, ?, ?, ?, ?)",
            [(*chunk, sqlite3.Binary(vector.astype(np.float32).tobytes()))
             for chunk, vector in zip(chunks, embeddings)],
        )
    return len(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the local PocketSyllabus index")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    args = parser.parse_args()
    try:
        count = ingest(args.data_dir, args.db_path)
    except (ValueError, OSError, sqlite3.Error, SearchServiceError) as exc:
        parser.exit(1, f"Indexing failed: {exc}\n")
    print(f"Indexed {count} chunks into {args.db_path}")
