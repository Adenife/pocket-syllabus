import hashlib
import tempfile
import unittest
from pathlib import Path
from fastapi import HTTPException
from app.services.sync_client import SyncClient, Peer
from helpers import context, upload_ready

class LocalPeer:
    def __init__(self,ctx,url):
        self.ctx,self.url=ctx,url
    def manifest(self):
        with self.ctx.db.connect() as conn:
            ids=[row[0] for row in conn.execute('SELECT id FROM documents')]
        return {identifier:self.ctx.documents.require(identifier,'local',True) for identifier in ids}
    def download(self,doc,folder):
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(doc['id']+'.part')
        path.write_bytes(self.ctx.documents.original(doc['id'],'local')[1])
        return path
    def upload(self,doc,path,destination,transfers,save):
        result=self.ctx.documents.upload('local',doc['filename'],path.read_bytes(),doc['id'],destination['version'] if destination else 0)
        self.ctx.worker.run_once()
        return result['document']
    def delete(self,doc):
        self.ctx.documents.delete(doc['id'],'local',doc['version'])

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.left=context(root/'left')
        self.right=context(root/'right')
        self.path=root/'sync.json'
        self.client=SyncClient(LocalPeer(self.left,'left'),LocalPeer(self.right,'right'),self.path)
    def test_two_way_transfer_no_duplicates_and_delete_propagation(self):
        first=upload_ready(self.left)
        second=upload_ready(self.right,'Motion and speed.','motion.txt')
        result=self.client.run()
        self.assertEqual(result['transferred'],2)
        self.assertEqual(result['conflicts'],[])
        self.assertEqual(self.client.run()['transferred'],0)
        self.assertEqual(set(self.client.local.manifest()),{first,second})
        self.left.documents.delete(first,'local',1)
        self.assertEqual(self.client.run()['transferred'],1)
        self.assertIsNotNone(self.right.documents.require(first,'local',True)['deleted_at'])
    def test_conflicting_edits_preserved_and_checkpoint_survives_restart(self):
        identifier=upload_ready(self.left)
        self.client.run()
        for ctx,text in [(self.left,b'Local edited notes'),(self.right,b'Remote edited notes')]:
            ctx.documents.upload('local','book.md',text,identifier,1)
            ctx.worker.run_once()
        client=SyncClient(self.client.local,self.client.remote,self.path)
        self.assertEqual(client.run()['conflicts'],[identifier])
        self.assertEqual(self.left.documents.original(identifier,'local')[1],b'Local edited notes')
        self.assertEqual(self.right.documents.original(identifier,'local')[1],b'Remote edited notes')
    def test_one_sided_edit_propagates(self):
        identifier=upload_ready(self.left)
        self.client.run()
        self.right.documents.upload('local','book.md',b'Motion changes position.',identifier,1)
        self.right.worker.run_once()
        self.assertEqual(self.client.run()['transferred'],1)
        self.assertEqual(self.left.documents.original(identifier,'local')[1],b'Motion changes position.')
    def test_upload_session_resumes_across_context_restart(self):
        session=self.left.sync.create_upload('local','note.txt',11)
        self.left.sync.append(session['id'],'local',0,b'Light ')
        restarted=context(self.left.db.path.parent)
        self.assertEqual(restarted.sync.upload_status(session['id'],'local')['offset'],6)
        restarted.sync.append(session['id'],'local',6,b'waves')
        result=restarted.sync.complete(session['id'],'local')
        restarted.worker.run_once()
        self.assertEqual(restarted.documents.original(result['document']['id'],'local')[1],b'Light waves')
    def test_upload_sessions_are_owner_scoped_and_limited(self):
        session=self.left.sync.create_upload('alice','note.txt',11)
        with self.assertRaises(HTTPException):
            self.left.sync.upload_status(session['id'],'bob')
        self.left.sync.create_upload('alice','a.txt',1)
        self.left.sync.create_upload('alice','b.txt',1)
        with self.assertRaises(HTTPException) as error:
            self.left.sync.create_upload('alice','c.txt',1)
        self.assertEqual(error.exception.status_code,429)
    def test_remote_http_and_embedded_credentials_rejected(self):
        for url in ['http://example.com/api/v1','https://user:pass@example.com/api/v1','file:///tmp']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                Peer(url)
