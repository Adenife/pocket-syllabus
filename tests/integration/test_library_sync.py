import tempfile
import unittest
from pathlib import Path
from app.schemas.library import CategoryCreate,CategoryEdit,MetadataPatch,BookmarkCreate,PortableMetadata
from app.services.sync_client import SyncClient,signature
from helpers import context,upload_ready
from integration.test_sync import LocalPeer

class LibrarySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.left=context(root/'left');self.right=context(root/'right')
        self.client=SyncClient(LocalPeer(self.left,'left'),LocalPeer(self.right,'right'),root/'state.json')
        self.identifier=upload_ready(self.left)
    def patch(self,ctx,**fields):
        doc=ctx.documents.require(self.identifier,'local')
        return ctx.library.patch(self.identifier,'local',MetadataPatch(expected_metadata_version=doc['metadata_version'],**fields))
    def test_metadata_and_bookmarks_sync_without_original_transfer(self):
        self.client.run()
        original=self.right.documents.require(self.identifier,'local')['version']
        subject=self.left.library.create_category('local',CategoryCreate(kind='subject',name='Biology'))
        self.patch(self.left,title='Exam notes',subject_ids=[subject['id']],favorite=True)
        chunk=self.left.library.preview(self.identifier,'local')['items'][0]
        self.left.library.create_bookmark('local',BookmarkCreate(chunk_id=chunk['id'],annotation='Remember this'))
        self.assertEqual(self.client.run()['conflicts'],[])
        doc=self.right.documents.require(self.identifier,'local')
        self.assertEqual(doc['version'],original)
        self.assertEqual(doc['title'],'Exam notes')
        self.assertEqual(doc['subjects'][0]['name'],'Biology')
        self.assertEqual(self.right.library.bookmarks('local')[0]['annotation'],'Remember this')
        self.assertEqual(self.client.run()['transferred'],0)
    def test_concurrent_metadata_edits_preserved(self):
        self.client.run()
        self.patch(self.left,author='Local author')
        self.patch(self.right,author='Remote author')
        self.assertIn(self.identifier,self.client.run()['conflicts'])
        self.assertEqual(self.left.documents.require(self.identifier,'local')['author'],'Local author')
        self.assertEqual(self.right.documents.require(self.identifier,'local')['author'],'Remote author')
    def test_trash_restore_and_purge_propagate_distinct_states(self):
        self.client.run()
        self.left.documents.trash(self.identifier,'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertIsNotNone(self.right.documents.require(self.identifier,'local',True)['deleted_at'])
        self.assertIsNone(self.right.documents.require(self.identifier,'local',True)['purged_at'])
        self.left.documents.restore(self.identifier,'local');self.left.worker.run_once()
        self.assertEqual(self.client.run()['conflicts'],[])
        self.right.worker.run_once()
        self.assertIsNone(self.right.documents.require(self.identifier,'local')['deleted_at'])
        self.left.documents.delete(self.identifier,'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertIsNotNone(self.right.documents.require(self.identifier,'local',True)['purged_at'])
    def test_empty_collection_description_rename_and_removal_sync(self):
        collection=self.left.library.create_category('local',CategoryCreate(kind='collection',name='Exams',description='Study together'))
        result=self.client.run();self.assertEqual(result['conflicts'],[])
        remote=self.right.library.catalog('local')['collections'][0]
        self.assertEqual(remote['description'],'Study together')
        self.left.library.change_category(collection['id'],'local',CategoryEdit(name='Final exams',description='Final revision'))
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertEqual(self.right.library.catalog('local')['collections'][0]['name'],'Final exams')
        self.left.library.change_category(collection['id'],'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertEqual(self.right.library.catalog('local')['collections'],[])
    def test_category_rename_with_memberships_consolidates_derived_labels(self):
        category=self.left.library.create_category('local',CategoryCreate(kind='subject',name='Biology',description='Living organisms'))
        self.patch(self.left,subject_ids=[category['id']]);self.client.run()
        self.left.library.change_category(category['id'],'local',CategoryEdit(name='Life sciences',description='Cells and organisms'))
        result=self.client.run();self.assertEqual(result['conflicts'],[],result)
        catalog=self.right.library.catalog('local')['subjects']
        self.assertEqual(len(catalog),1)
        self.assertEqual(catalog[0]['name'],'Life sciences')
    def test_conflicting_collection_descriptions_preserved(self):
        first=self.left.library.create_category('local',CategoryCreate(kind='collection',name='Exams'))
        self.client.run();second=self.right.library.catalog('local')['collections'][0]
        self.left.library.change_category(first['id'],'local',CategoryEdit(name='Exams',description='Local plan'))
        self.right.library.change_category(second['id'],'local',CategoryEdit(name='Exams',description='Remote plan'))
        self.assertTrue(any(item.startswith('category:') for item in self.client.run()['conflicts']))
        self.assertEqual(self.left.library.catalog('local')['collections'][0]['description'],'Local plan')
        self.assertEqual(self.right.library.catalog('local')['collections'][0]['description'],'Remote plan')

    def test_replacement_before_trash_preserves_latest_original_on_restore(self):
        self.client.run()
        self.left.documents.upload('local','book.md',b'Updated notes about DNA.',self.identifier,1)
        self.left.worker.run_once()
        self.left.documents.trash(self.identifier,'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertEqual(self.right.documents.original(self.identifier,'local',include_deleted=True)[1],b'Updated notes about DNA.')
        self.right.documents.restore(self.identifier,'local');self.right.worker.run_once()
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertEqual(self.left.documents.original(self.identifier,'local')[1],b'Updated notes about DNA.')
    def test_fresh_peer_receives_recoverable_trash_and_purge_tombstone(self):
        self.left.documents.trash(self.identifier,'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertIsNone(self.right.documents.require(self.identifier,'local',True)['purged_at'])
        self.assertTrue(self.right.documents.original(self.identifier,'local',include_deleted=True)[1])
        another=upload_ready(self.left,'Motion changes.','deleted.txt')
        self.left.documents.delete(another,'local')
        self.assertEqual(self.client.run()['conflicts'],[])
        self.assertIsNotNone(self.right.documents.require(another,'local',True)['purged_at'])
    def test_removing_subject_from_trashed_document_syncs(self):
        category=self.left.library.create_category('local',CategoryCreate(kind='subject',name='Biology'))
        self.patch(self.left,subject_ids=[category['id']]);self.client.run()
        self.left.documents.trash(self.identifier,'local');self.client.run()
        self.left.library.change_category(category['id'],'local')
        result=self.client.run()
        self.assertEqual(result['conflicts'],[],result)
        self.assertEqual(self.right.library.catalog('local')['subjects'],[])
