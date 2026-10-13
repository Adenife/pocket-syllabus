import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from cryptography.fernet import Fernet
from backup import backup,restore
from helpers import context,upload_ready

class OperationsTests(unittest.TestCase):
    def test_backup_restore_with_originals_and_pending_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            ctx=context(root/'source')
            identifier=upload_ready(ctx)
            pending=ctx.documents.upload('local','queued.txt',b'Motion and speed.')
            archive=backup(ctx.settings,root/'backup.zip')
            restored=restore(archive,root/'restored')
            settings=ctx.settings
            from app.services.context import Context
            from app.core.config import Settings
            recovered=Context(Settings(db_path=restored/'syllabus.db',upload_dir=restored/'uploads',index_dir=restored/'indexes',worker_enabled=False),ctx.embedder)
            self.assertTrue(recovered.documents.original(identifier,'local')[1])
            self.assertTrue(recovered.worker.acquire())
            recovered.worker.run_once()
            recovered.worker.close()
            self.assertEqual(recovered.documents.require(pending['document']['id'],'local')['status'],'ready')
            self.assertTrue(recovered.search.search('motion'))
    def test_unsafe_restore_and_nonempty_destination_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('manifest.json',json.dumps({'format':1,'files':[]}))
                z.writestr('library.db',b'')
                z.writestr('../escape',b'bad')
            with self.assertRaises(ValueError):
                restore(archive,root/'destination')
            self.assertFalse((root/'escape').exists())
    def test_legacy_database_migration_preserves_search(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with sqlite3.connect(root/'library.db') as conn:
                conn.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY,source_path TEXT,source_title TEXT,section TEXT,text TEXT,embedding BLOB)')
                conn.execute('INSERT INTO chunks VALUES (1,?,?,?,?,?)',('book.md','Book','Energy','Light powers plants.',np.array([1,0,0],dtype=np.float32).tobytes()))
            ctx=context(root)
            self.assertEqual(ctx.search.search('light')[0].text_excerpt,'Light powers plants.')
            self.assertEqual(ctx.documents.repository.list('local')[0]['status'],'ready')
    def test_cli_incremental_pruning_does_not_delete_uploads(self):
        from ingest import ingest
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'data';data.mkdir()
            ctx=context(root/'library')
            uploaded=upload_ready(ctx,'Private uploaded notes.','upload.txt')
            (data/'a.md').write_text('Light travels.')
            (data/'b.txt').write_text('Motion changes.')
            ingest(data,context=ctx)
            initial=len(ctx.documents.repository.list('local'))
            ingest(data,context=ctx)
            self.assertEqual(len(ctx.documents.repository.list('local')),initial)
            (data/'a.md').unlink()
            ingest(data,context=ctx)
            self.assertIsNotNone(ctx.documents.require(uploaded,'local'))
            self.assertEqual(len(ctx.documents.repository.list('local')),initial-1)
