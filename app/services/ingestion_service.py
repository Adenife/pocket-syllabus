"""Durable staging: bounded embedding batches, atomic document replacement."""
import json
import tempfile
import time
from itertools import islice
from pathlib import Path
import numpy as np
from app.ingestion.pipeline import parse_document
from app.ingestion.chunker import chunk_blocks

class IngestionService:
    def __init__(self, db, embedder):
        self.db, self.embedder = db, embedder

    def run(self, job):
        settings = self.db.settings
        warnings = []
        job_id, identifier = job['id'], job['document_id']
        try:
            with self.db.connect() as conn:
                document = conn.execute('SELECT * FROM documents WHERE id=?', (identifier,)).fetchone()
            if not document or document['deleted_at']:
                return
            original = settings.upload_dir / document['storage_name']
            with tempfile.TemporaryDirectory(dir=settings.upload_dir) as temp:
                path = Path(temp) / ('original' + document['file_type'])
                path.write_bytes(self.db.codec.decode(original.read_bytes()))
                path.chmod(0o600)
                blocks = parse_document(path, document['filename'], warnings)
                chunks = iter(chunk_blocks(blocks, self.embedder.tokenizer, self.embedder.max_tokens,
                                           settings.chunk_tokens, settings.overlap_tokens))
                count, title, dimension = 0, document['title'], None
                while True:
                    batch = list(islice(chunks, settings.batch_size))
                    if not batch:
                        break
                    vectors = self.embedder.encode([chunk.text for chunk in batch])
                    if vectors.ndim != 2 or len(vectors) != len(batch) or not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0):
                        raise ValueError('Invalid embedding batch')
                    if dimension is not None and dimension != vectors.shape[1]:
                        raise ValueError('Embedding dimensions changed during indexing')
                    dimension = vectors.shape[1]
                    with self.db.connect() as conn:
                        active = conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
                        if not active or active['status'] != 'running':
                            return
                        conn.executemany('''INSERT INTO staged_chunks
                            (job_id, ordinal, source_title, section, page, line, text, embedding, model_name)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                            [(job_id, count + i, chunk.title, chunk.section, chunk.page, chunk.line,
                              self.db.codec.encode(chunk.text.encode()), self.db.codec.encode(vector.astype(np.float32).tobytes()), settings.model_name)
                             for i, (chunk, vector) in enumerate(zip(batch, vectors))])
                        count += len(batch)
                        title = batch[0].title
                        conn.execute("UPDATE jobs SET stage='embedding', progress=50, chunks=?, updated_at=? WHERE id=?", (count, time.time(), job_id))
                if not count:
                    raise ValueError('No extractable text. Scanned PDFs require OCR; heading-only files cannot be indexed.')
            with self.db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                active = conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
                current = conn.execute('SELECT version, deleted_at FROM documents WHERE id=?', (identifier,)).fetchone()
                if not active or active['status'] != 'running' or current['deleted_at'] or current['version'] != job['version']:
                    conn.execute('DELETE FROM staged_chunks WHERE job_id=?', (job_id,))
                    return
                self.db.remove_fts(conn, identifier)
                conn.execute('DELETE FROM chunks WHERE document_id=?', (identifier,))
                conn.execute('''INSERT INTO chunks
                    (document_id, owner_id, ordinal, source_title, section, page, line, text, embedding, model_name)
                    SELECT ?, ?, ordinal, source_title, section, page, line, text, embedding, model_name
                    FROM staged_chunks WHERE job_id=? ORDER BY ordinal''', (identifier, job['owner_id'], job_id))
                conn.execute('DELETE FROM staged_chunks WHERE job_id=?', (job_id,))
                conn.execute("UPDATE documents SET status='ready', indexed_version=?, model_name=?, title=?, warnings=?, error=NULL, updated_at=? WHERE id=?", (job['version'], settings.model_name, title, json.dumps(warnings[:100]), time.time(), identifier))
                conn.execute("UPDATE jobs SET status='completed', stage='completed', progress=100, updated_at=? WHERE id=?", (time.time(), job_id))
                self.db.add_fts(conn, identifier)
                self.db.bump(conn)
        except Exception as exc:
            # Do not expose internal filesystem paths or arbitrary parser traces to clients.
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Document processing failed; check format and try again'
            with self.db.connect() as conn:
                conn.execute('DELETE FROM staged_chunks WHERE job_id=?', (job_id,))
                conn.execute("UPDATE jobs SET status='failed', stage='failed', error=?, updated_at=? WHERE id=? AND status='running'", (message[:1000], time.time(), job_id))
                conn.execute("UPDATE documents SET status='failed', error=?, warnings=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (message[:1000], json.dumps(warnings[:100]), time.time(), identifier))
