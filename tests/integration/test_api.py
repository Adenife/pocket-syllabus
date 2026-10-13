import tempfile
import unittest
from unittest.mock import patch
import httpx
from app.main import create_app
from helpers import context

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ctx=context(self.temp.name)
        self.app=create_app(self.ctx.settings,self.ctx)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
    async def asyncTearDown(self):
        await self.client.aclose()
        self.ctx.worker.close()
        self.temp.cleanup()
    async def upload(self, filename='book.md',data=b'# Biology\n## Energy\nLight powers plants.'):
        response=await self.client.post('/api/v1/documents',files={'file':(filename,data)})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()
    async def test_full_upload_job_search_download_delete_flow(self):
        self.assertEqual((await self.client.get('/')).status_code,200)
        self.assertEqual((await self.client.get('/ready')).status_code,200)
        result=await self.upload()
        identifier=result['document']['id']
        self.assertEqual((await self.client.get('/api/v1/jobs/'+result['job_id'])).json()['status'],'queued')
        self.ctx.worker.run_once()
        self.assertEqual((await self.client.get('/api/v1/jobs/'+result['job_id'])).json()['status'],'completed')
        response=await self.client.post('/api/v1/search',json={'query':' light ','limit':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['results'][0]['document_id'],identifier)
        self.assertIn('line',response.json()['results'][0])
        response=await self.client.get(f'/api/v1/documents/{identifier}/original',headers={'Range':'bytes=0-8'})
        self.assertEqual((response.status_code,response.content),(206,b'# Biology'))
        self.assertEqual((await self.client.get(f'/api/v1/documents/{identifier}/original',headers={'Range':'bytes=999-'})).status_code,416)
        self.assertEqual((await self.client.delete('/api/v1/documents/'+identifier)).status_code,204)
        self.assertEqual((await self.client.get('/api/v1/documents/'+identifier)).status_code,404)
        self.assertEqual((await self.client.post('/api/v1/search',json={'query':'light'})).json()['results'],[])
    async def test_validation_and_upload_limits(self):
        for payload in [{},{'query':' '},{'query':'light','limit':0}]:
            self.assertEqual((await self.client.post('/api/v1/search',json=payload)).status_code,422)
        self.assertEqual((await self.client.post('/api/v1/documents',files={'file':('a.exe',b'data')})).status_code,415)
        self.ctx.settings.max_upload_bytes=2
        self.assertEqual((await self.client.post('/api/v1/documents',files={'file':('a.md',b'data')})).status_code,413)
    async def test_resumable_upload_offset_conflict_and_completion(self):
        response=await self.client.post('/api/v1/sync/uploads',json={'filename':'notes.txt','total':11})
        self.assertEqual(response.status_code,201)
        identifier=response.json()['id']
        path='/api/v1/sync/uploads/'+identifier
        self.assertEqual((await self.client.patch(path,params={'offset':0},content=b'Light ')).status_code,200)
        self.assertEqual((await self.client.patch(path,params={'offset':0},content=b'Light ')).status_code,409)
        self.assertEqual((await self.client.post(path+'/complete')).status_code,409)
        self.assertEqual((await self.client.patch(path,params={'offset':6},content=b'waves')).status_code,200)
        response=await self.client.post(path+'/complete')
        self.assertEqual(response.status_code,202,response.text)
        self.ctx.worker.run_once()
        self.assertEqual((await self.client.get(path)).status_code,404)
        self.assertTrue((await self.client.post('/api/v1/search',json={'query':'light'})).json()['results'])
    async def test_changes_pagination_and_versions(self):
        result=await self.upload()
        identifier=result['document']['id']
        response=await self.client.get('/api/v1/sync/changes',params={'limit':1})
        self.assertEqual(len(response.json()['changes']),1)
        cursor=response.json()['cursor']
        self.ctx.worker.run_once()
        response=await self.client.post('/api/v1/documents',params={'document_id':identifier,'expected_version':99},files={'file':('book.md',b'Changed text')})
        self.assertEqual(response.status_code,409)
        await self.client.delete('/api/v1/documents/'+identifier)
        response=await self.client.get('/api/v1/sync/changes',params={'after':cursor})
        self.assertEqual(response.json()['changes'][0]['action'],'delete')
        self.assertEqual(response.json()['changes'][0]['document']['version'],2)
    async def test_authentication_ownership_and_logout(self):
        self.ctx.settings.auth_enabled=True
        credentials={'username':'alice','password':'verysecret123'}
        self.assertEqual((await self.client.get('/api/v1/documents')).status_code,401)
        self.assertEqual((await self.client.post('/api/v1/auth/register',json=credentials)).status_code,201)
        response=await self.client.post('/api/v1/auth/login',json=credentials)
        self.assertEqual(response.status_code,200)
        token=response.json()['access_token']
        self.client.headers['Authorization']='Bearer '+token
        result=await self.upload()
        identifier=result['document']['id']
        self.ctx.worker.run_once()
        await self.client.post('/api/v1/auth/register',json={'username':'bob','password':'othersecret123'})
        response=await self.client.post('/api/v1/auth/login',json={'username':'bob','password':'othersecret123'})
        self.client.headers['Authorization']='Bearer '+response.json()['access_token']
        for path in ['/documents/'+identifier,'/documents/'+identifier+'/original','/jobs/'+result['job_id']]:
            self.assertEqual((await self.client.get('/api/v1'+path)).status_code,404)
        self.assertEqual((await self.client.get('/api/v1/documents')).json(),[])
        self.assertEqual((await self.client.post('/api/v1/search',json={'query':'light'})).json()['results'],[])
        self.assertEqual((await self.client.post('/api/v1/search',json={'query':'light','document_ids':[identifier]})).status_code,404)
        self.assertEqual((await self.client.post('/api/v1/auth/logout')).status_code,204)
        self.assertEqual((await self.client.get('/api/v1/documents')).status_code,401)
    async def test_rate_limit(self):
        self.ctx.settings.rate_limit=2
        app=create_app(self.ctx.settings,self.ctx)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://rate') as client:
            self.assertEqual((await client.get('/')).status_code,200)
            self.assertEqual((await client.get('/')).status_code,200)
            self.assertEqual((await client.get('/')).status_code,429)
    async def test_failed_model_returns_503(self):
        await self.upload()
        self.ctx.worker.run_once()
        self.ctx.embedder.fail=True
        self.assertEqual((await self.client.post('/api/v1/search',json={'query':'light'})).status_code,503)

    async def test_chunked_request_size_limit(self):
        self.ctx.settings.max_upload_bytes=1
        async def body():
            for _ in range(18):
                yield b'x'*65536
        response=await self.client.patch('/api/v1/sync/uploads/missing',params={'offset':0},content=body())
        self.assertEqual(response.status_code,413)

    async def test_invalid_password_expired_token_and_disabled_registration(self):
        import time
        self.ctx.settings.auth_enabled=True
        credentials={'username':'alice','password':'verysecret123'}
        await self.client.post('/api/v1/auth/register',json=credentials)
        response=await self.client.post('/api/v1/auth/login',json={**credentials,'password':'incorrect-password'})
        self.assertEqual(response.status_code,401)
        response=await self.client.post('/api/v1/auth/login',json=credentials)
        token=response.json()['access_token']
        with self.ctx.db.connect() as conn:
            stored=conn.execute('SELECT hash FROM tokens').fetchone()[0]
            self.assertNotEqual(stored,token)
            conn.execute('UPDATE tokens SET expires_at=?',(time.time()-1,))
        self.client.headers['Authorization']='Bearer '+token
        self.assertEqual((await self.client.get('/api/v1/documents')).status_code,401)
        self.ctx.settings.registration_enabled=False
        self.assertEqual((await self.client.post('/api/v1/auth/register',json={'username':'bob','password':'othersecret123'})).status_code,403)
