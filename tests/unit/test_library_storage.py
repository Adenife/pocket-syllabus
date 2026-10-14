import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from cryptography.fernet import Fernet
from app.schemas.library import MetadataPatch,BookmarkCreate,CategoryCreate
from app.services.context import Context
from app.core.config import Settings
from backup import backup,restore
from helpers import context,upload_ready,Embedder

class LibraryStorageTests(unittest.TestCase):
    def test_encrypted_bookmarks_and_annotations_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            key=Fernet.generate_key().decode()
            ctx=context(temp,encryption_key=key)
            identifier=upload_ready(ctx)
            chunk=ctx.library.preview(identifier,'local')['items'][0]
            ctx.library.create_bookmark('local',BookmarkCreate(chunk_id=chunk['id'],annotation='Private revision note'))
            with ctx.db.connect() as conn:
                row=conn.execute('SELECT excerpt,annotation FROM bookmarks').fetchone()
                self.assertNotIn(b'Private revision',row['annotation'])
                self.assertNotIn(b'Light powers',row['excerpt'])
            restarted=context(temp,encryption_key=key)
            self.assertEqual(restarted.library.bookmarks('local')[0]['annotation'],'Private revision note')
    def test_backup_restores_trash_originals_and_organization(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            ctx=context(root/'source');identifier=upload_ready(ctx)
            subject=ctx.library.create_category('local',CategoryCreate(kind='subject',name='Biology'))
            ctx.library.patch(identifier,'local',MetadataPatch(expected_metadata_version=1,title='Revision',subject_ids=[subject['id']]))
            ctx.documents.trash(identifier,'local')
            archive=backup(ctx.settings,root/'backup.zip')
            destination=restore(archive,root/'restored')
            recovered=Context(Settings(db_path=destination/'syllabus.db',upload_dir=destination/'uploads',index_dir=destination/'indexes',worker_enabled=False),Embedder())
            doc=recovered.documents.require(identifier,'local',True)
            self.assertEqual(doc['title'],'Revision')
            self.assertEqual(doc['subjects'][0]['name'],'Biology')
            self.assertTrue(recovered.documents.original(identifier,'local',include_deleted=True)[1])
            recovered.documents.restore(identifier,'local');recovered.worker.run_once()
            self.assertEqual(recovered.documents.require(identifier,'local')['status'],'ready')
    def test_reinitializing_schema_preserves_document_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=context(temp);identifier=upload_ready(ctx)
            ctx.library.patch(identifier,'local',MetadataPatch(expected_metadata_version=1,title='User title',favorite=True))
            ctx.db.initialize();ctx.db.initialize()
            self.assertEqual(ctx.documents.require(identifier,'local')['title'],'User title')
            self.assertTrue(ctx.documents.require(identifier,'local')['favorite'])
    def test_cancelled_job_failure_cannot_damage_restored_document(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=context(temp);identifier=upload_ready(ctx)
            ctx.documents.reindex(identifier,'local');job=ctx.worker.claim()
            def fail_after_restore(texts):
                ctx.documents.trash(identifier,'local')
                ctx.documents.restore(identifier,'local')
                raise RuntimeError('Old cancelled worker failed')
            with patch.object(ctx.embedder,'encode',side_effect=fail_after_restore):
                ctx.ingestion.run(job)
            self.assertEqual(ctx.documents.require(identifier,'local')['status'],'queued')
            ctx.worker.run_once()
            self.assertEqual(ctx.documents.require(identifier,'local')['status'],'ready')
