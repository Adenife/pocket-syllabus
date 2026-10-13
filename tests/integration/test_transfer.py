"""Exercise real HTTP sync clients against two isolated in-process API servers."""
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
import requests
from app.main import create_app
from app.services.sync_client import Peer, SyncClient
from helpers import context, upload_ready

class BridgeSession:
    def __init__(self,client):
        self.client=client
        self.headers={}
    def request(self,method,url,timeout=None,stream=False,allow_redirects=False,**kwargs):
        path=url.split('/api/v1',1)[1]
        if 'data' in kwargs:
            kwargs['content']=kwargs.pop('data')
        response=self.client.request(method,'/api/v1'+path,**kwargs)
        bridged=requests.Response()
        bridged.status_code=response.status_code
        bridged._content=response.content
        bridged._content_consumed=True
        bridged.headers.update(response.headers)
        bridged.url=url
        return bridged
    def get(self,url,**kwargs):
        return self.request('GET',url,**kwargs)

class TransferTests(unittest.TestCase):
    def test_actual_client_resumes_upload_download_and_two_way_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            left=context(root/'left');right=context(root/'right')
            identifier=upload_ready(left)
            with TestClient(create_app(left.settings,left)) as lc, TestClient(create_app(right.settings,right)) as rc:
                local=Peer('http://127.0.0.1:8000/api/v1');remote=Peer('http://127.0.0.1:8001/api/v1')
                local.session=BridgeSession(lc);remote.session=BridgeSession(rc)
                doc=local.manifest()[identifier]
                # Simulate interruption after the first download bytes.
                folder=root/'downloads';folder.mkdir()
                partial=folder/(identifier+'-'+doc['content_hash']+'.part')
                partial.write_bytes(left.documents.original(identifier,'local')[1][:10])
                path=local.download(doc,folder)
                self.assertEqual(path.read_bytes(),left.documents.original(identifier,'local')[1])
                # Resume an existing server upload session using its persisted offset.
                session=right.sync.create_upload('local',doc['filename'],doc['size'])
                right.sync.append(session['id'],'local',0,path.read_bytes()[:10])
                transfers={remote.url+':'+identifier:{'session':session['id'],'hash':doc['content_hash']}}
                remote.upload(doc,path,None,transfers,lambda:None)
                right.worker.run_once()
                self.assertEqual(right.documents.original(identifier,'local')[1],path.read_bytes())
                self.assertEqual(transfers,{})
                sync=SyncClient(local,remote,root/'state.json')
                self.assertEqual(sync.run()['conflicts'],[])
                left.documents.upload('local',doc['filename'],b'Motion changes position.',identifier,1)
                left.worker.run_once()
                self.assertEqual(sync.run()['transferred'],1)
                right.worker.run_once()
                self.assertEqual(right.documents.original(identifier,'local')[1],b'Motion changes position.')
                right.documents.delete(identifier,'local',2)
                self.assertEqual(sync.run()['transferred'],1)
                self.assertIsNotNone(left.documents.require(identifier,'local',True)['deleted_at'])
