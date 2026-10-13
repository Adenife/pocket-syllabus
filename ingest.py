"""Incrementally index local files through the same pipeline as uploads."""
import argparse
import time
from pathlib import Path
from fastapi import HTTPException
from app.core.config import DATA_DIR, Settings
from app.ingestion.pipeline import PARSERS
from app.services.context import Context


def ingest(data_dir=DATA_DIR, db_path=None, context=None):
    data_dir = Path(data_dir).resolve()
    paths = sorted(path for path in data_dir.rglob('*') if path.is_file() and path.suffix.lower() in PARSERS) if data_dir.is_dir() else []
    if not paths:
        raise ValueError(f'No supported documents found in {data_dir}')
    context = context or Context(Settings(**({'db_path': Path(db_path)} if db_path else {})))
    owner = 'local'
    prefix = 'cli:' + str(data_dir) + ':'
    keys, job_ids = set(), []
    for path in paths:
        key = prefix + path.relative_to(data_dir).as_posix()
        keys.add(key)
        with context.db.connect() as conn:
            row = conn.execute('SELECT id,version,content_hash FROM documents WHERE owner_id=? AND source_key=? AND deleted_at IS NULL', (owner, key)).fetchone()
        if path.stat().st_size > context.settings.max_upload_bytes:
            raise ValueError(f'{path.name} exceeds the upload limit')
        data = path.read_bytes()
        if row:
            result = context.documents.upload(owner, path.name, data, row['id'], row['version'])
        else:
            result = context.documents.upload(owner, path.name, data, source_key=key)
        if result['job_id']:
            job_ids.append(result['job_id'])
    # Only prune documents managed by this CLI input root; user uploads are untouched.
    with context.db.connect() as conn:
        managed = conn.execute('SELECT id,source_key FROM documents WHERE owner_id=? AND deleted_at IS NULL', (owner,)).fetchall()
    for row in managed:
        if row['source_key'] and row['source_key'].startswith(prefix) and row['source_key'] not in keys:
            context.documents.delete(row['id'], owner)
        elif row['source_key'] and row['source_key'].startswith('legacy:') and any(path.name == row['source_key'][7:] for path in paths):
            context.documents.delete(row['id'], owner)
    acquired = context.worker.acquire()
    try:
        for identifier in job_ids:
            deadline = time.monotonic() + 600
            while True:
                with context.db.connect() as conn:
                    job = conn.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
                if job['status'] in {'completed', 'failed', 'cancelled'}:
                    if job['status'] != 'completed':
                        raise ValueError(job['error'] or job['status'])
                    break
                if time.monotonic() > deadline:
                    raise ValueError('Indexing wait timed out; check the jobs endpoint')
                if acquired:
                    context.worker.run_once()
                else:
                    time.sleep(0.2)
    finally:
        if acquired:
            context.worker.close()
    with context.db.connect() as conn:
        return conn.execute('SELECT COUNT(*) FROM chunks WHERE owner_id=?', (owner,)).fetchone()[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Incrementally index Markdown, TXT, PDF and DOCX')
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--db-path', type=Path)
    args = parser.parse_args()
    try:
        count = ingest(args.data_dir, args.db_path)
    except (ValueError, OSError, HTTPException) as exc:
        parser.exit(1, f'Indexing failed: {getattr(exc, "detail", str(exc))}\n')
    print(f'Library contains {count} searchable chunks')
