"""Single-process durable worker; standalone mode uses an exclusive process lock."""
import threading
import time

class IndexingWorker:
    def __init__(self, db, ingestion):
        self.db, self.ingestion = db, ingestion
        self.stop_event = threading.Event()
        self.thread = None
        self.file_lock = None

    def acquire(self):
        import shutil
        import portalocker
        path = self.db.path.with_suffix('.worker.lock')
        self.file_lock = portalocker.Lock(str(path), timeout=0)
        try:
            self.file_lock.acquire()
        except portalocker.exceptions.LockException:
            self.file_lock = None
            return False
        # Remove plaintext extraction scratch directories left by a terminated worker.
        for scratch in self.db.settings.upload_dir.glob('tmp*'):
            if scratch.is_dir():
                shutil.rmtree(scratch)
        with self.db.connect() as conn:
            conn.execute("UPDATE jobs SET status='failed', stage='failed', error='Repeated worker interruptions; inspect the file and reindex' WHERE status='running' AND attempts>=3")
            conn.execute("UPDATE documents SET status='failed', error='Repeated worker interruptions; inspect the file and reindex' WHERE id IN (SELECT document_id FROM jobs WHERE error='Repeated worker interruptions; inspect the file and reindex') AND status='indexing'")
            conn.execute("UPDATE jobs SET status='queued', stage='recovered', progress=0 WHERE status='running'")
            conn.execute('DELETE FROM staged_chunks')
        return True

    def start(self):
        if not self.acquire():
            return False
        self.thread = threading.Thread(target=self.loop, daemon=True, name='indexing-worker')
        self.thread.start()
        return True

    def claim(self):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute("UPDATE jobs SET status='running', stage='extracting', attempts=attempts+1, updated_at=? WHERE id=?", (time.time(), row['id']))
            conn.execute("UPDATE documents SET status='indexing' WHERE id=? AND deleted_at IS NULL", (row['document_id'],))
            return dict(row)

    def run_once(self):
        job = self.claim()
        if job:
            self.ingestion.run(job)
        return bool(job)

    def loop(self):
        import logging
        while not self.stop_event.is_set():
            try:
                if not self.run_once():
                    self.stop_event.wait(0.5)
            except Exception:
                logging.getLogger(__name__).exception('Worker iteration failed')
                self.stop_event.wait(1)

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=30)
        if self.file_lock and (not self.thread or not self.thread.is_alive()):
            self.file_lock.release()
            self.file_lock = None

if __name__ == '__main__':
    from app.core.config import Settings
    from app.services.context import Context
    context = Context(Settings(worker_enabled=False))
    if not context.worker.start():
        raise SystemExit('Another indexing worker is already active')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        context.worker.close()
