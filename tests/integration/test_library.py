"""End-to-end library organization and owner isolation."""
import tempfile
import unittest
import httpx
from app.main import create_app
from helpers import context,upload_ready

class LibraryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ctx=context(self.temp.name)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.ctx.settings,self.ctx)),base_url='http://library')
        self.first=upload_ready(self.ctx,'# Physics\n\nMotion is a change in position.','physics.md')
        self.second=upload_ready(self.ctx,'# Biology\n\nLight powers photosynthesis.','biology.md')
    async def asyncTearDown(self):
        await self.client.aclose();self.temp.cleanup()
    async def category(self,kind,name):
        response=await self.client.post('/api/v1/library/categories',json={'kind':kind,'name':name})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']
    async def patch(self,identifier,**fields):
        doc=self.ctx.documents.require(identifier,'local')
        response=await self.client.patch('/api/v1/library/documents/'+identifier,json={'expected_metadata_version':doc['metadata_version'],**fields})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()
    async def listing(self,**params):
        response=await self.client.get('/api/v1/library/documents',params=params)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()
    async def test_combined_filters_sort_total_and_stable_pages(self):
        subject=await self.category('subject','Physics');tag=await self.category('tag','Exam prep');collection=await self.category('collection','Year One')
        await self.patch(self.first,title='A Physics',author='Newton',material_type='textbook',favorite=True,subject_ids=[subject],tag_ids=[tag],collection_ids=[collection])
        result=await self.listing(subject_ids=[subject],tag_ids=[tag],collection_ids=[collection],material_type='textbook',favorite=True,q='Newton',sort_by='title',sort_order='asc',limit=1)
        self.assertEqual((result['total'],result['items'][0]['id']),(1,self.first))
        all_docs=await self.listing(sort_by='title',sort_order='asc',limit=1)
        second_page=await self.listing(sort_by='title',sort_order='asc',limit=1,offset=1)
        self.assertNotEqual(all_docs['items'][0]['id'],second_page['items'][0]['id'])
        self.assertEqual(all_docs['total'],2)
    async def test_invalid_sort_and_cross_owner_categories(self):
        response=await self.client.get('/api/v1/library/documents',params={'sort_by':'title; DROP TABLE documents'})
        self.assertEqual(response.status_code,422)
        from app.schemas.library import CategoryCreate
        foreign=self.ctx.library.create_category('other',CategoryCreate(kind='subject',name='Private'))
        response=await self.client.get('/api/v1/library/documents',params={'subject_ids':[foreign['id']]})
        self.assertEqual(response.status_code,404)
        response=await self.client.patch('/api/v1/library/documents/'+self.first,json={'expected_metadata_version':1,'subject_ids':[foreign['id']]})
        self.assertEqual(response.status_code,404)
    async def test_metadata_preserved_by_reindex_and_title_reflected_in_search(self):
        await self.patch(self.first,title='My Physics Notes',description='Revision material',publication_year=2025,edition='Second')
        self.ctx.documents.reindex(self.first,'local');self.ctx.worker.run_once()
        doc=self.ctx.documents.require(self.first,'local')
        self.assertEqual((doc['title'],doc['description'],doc['publication_year']),('My Physics Notes','Revision material',2025))
        response=await self.client.post('/api/v1/search',json={'query':'motion','document_ids':[self.first]})
        self.assertEqual(response.json()['results'][0]['source_title'],'My Physics Notes')
        response=await self.client.patch('/api/v1/library/documents/'+self.first,json={'expected_metadata_version':1,'favorite':True})
        self.assertEqual(response.status_code,409)
    async def test_subject_collection_search_and_empty_matches(self):
        subject=await self.category('subject','Biology');empty=await self.category('collection','Empty collection')
        await self.patch(self.second,subject_ids=[subject])
        response=await self.client.post('/api/v1/search',json={'query':'motion','subject_ids':[subject]})
        self.assertTrue(all(item['document_id']==self.second for item in response.json()['results']))
        response=await self.client.post('/api/v1/search',json={'query':'motion','collection_ids':[empty]})
        self.assertEqual(response.json()['results'],[])
    async def test_bulk_assignment_favorites_and_atomic_ownership_failure(self):
        subject=await self.category('subject','General Science')
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'assign','category_ids':[subject]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await self.listing(subject_ids=[subject]))['total'],2)
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,'missing'],'action':'favorite'})
        self.assertEqual(response.status_code,404)
        self.assertFalse(self.ctx.documents.require(self.first,'local')['favorite'])
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'favorite'})
        self.assertEqual(response.json()['updated'],2)
        self.assertEqual((await self.listing(favorite=True))['total'],2)
    async def test_category_rename_remove_and_case_insensitive_duplicate(self):
        subject=await self.category('subject','Physics')
        await self.patch(self.first,subject_ids=[subject])
        response=await self.client.post('/api/v1/library/categories',json={'kind':'subject','name':'physics'})
        self.assertEqual(response.status_code,409)
        response=await self.client.patch('/api/v1/library/categories/'+subject,json={'name':'Physical Science'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.ctx.documents.require(self.first,'local')['subjects'][0]['name'],'Physical Science')
        await self.client.delete('/api/v1/library/categories/'+subject)
        self.assertEqual(self.ctx.documents.require(self.first,'local')['subjects'],[])
    async def test_preview_bookmark_annotation_survives_reindex(self):
        response=await self.client.get('/api/v1/library/documents/'+self.first+'/preview')
        self.assertEqual(response.status_code,200)
        self.assertIsNotNone(self.ctx.documents.require(self.first,'local')['last_opened'])
        chunk=response.json()['items'][0]
        response=await self.client.post('/api/v1/library/bookmarks',json={'chunk_id':chunk['id'],'annotation':'Review before exam'})
        self.assertEqual(response.status_code,201,response.text)
        identifier=response.json()['id']
        self.ctx.documents.reindex(self.first,'local');self.ctx.worker.run_once()
        response=await self.client.get('/api/v1/library/bookmarks')
        self.assertEqual(response.json()[0]['annotation'],'Review before exam')
        self.assertIn('Motion',response.json()[0]['excerpt'])
        await self.client.patch('/api/v1/library/bookmarks/'+identifier,json={'annotation':'Reviewed'})
        self.assertEqual((await self.client.get('/api/v1/library/bookmarks')).json()[0]['annotation'],'Reviewed')
    async def test_trash_restore_purge_and_statistics(self):
        response=await self.client.post('/api/v1/library/documents/'+self.first+'/trash')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await self.listing())['total'],1)
        self.assertEqual((await self.listing(trash=True))['total'],1)
        self.assertFalse(any(item.document_id==self.first for item in self.ctx.search.search('motion')))
        stats=(await self.client.get('/api/v1/library/statistics')).json()
        self.assertEqual(stats['trash_documents'],1)
        self.assertGreater(stats['storage_bytes'],0)
        response=await self.client.post('/api/v1/library/documents/'+self.first+'/restore')
        self.assertEqual(response.status_code,200,response.text)
        self.ctx.worker.run_once()
        self.assertEqual((await self.listing())['total'],2)
        await self.client.post('/api/v1/library/documents/'+self.first+'/trash')
        response=await self.client.delete('/api/v1/documents/'+self.first)
        self.assertEqual(response.status_code,204,response.text)
        self.assertEqual((await self.listing(trash=True))['total'],0)
        self.assertIsNotNone(self.ctx.documents.require(self.first,'local',True)['purged_at'])
    async def test_suggestions_are_explicit_and_related_excludes_self(self):
        response=await self.client.get('/api/v1/library/documents/'+self.first+'/suggestions')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('Physics',[item['name'] for item in response.json()['subjects']])
        self.assertEqual(self.ctx.documents.require(self.first,'local')['subjects'],[])
        response=await self.client.get('/api/v1/library/documents/'+self.first+'/related')
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(all(item['document']['id']!=self.first for item in response.json()))
    async def test_export_import_preserves_classification_and_bookmarks(self):
        collection=await self.category('collection','Revision')
        await self.patch(self.first,title='Revision physics',collection_ids=[collection])
        chunk=self.ctx.library.preview(self.first,'local')['items'][0]
        self.ctx.library.create_bookmark('local',__import__('app.schemas.library',fromlist=['BookmarkCreate']).BookmarkCreate(chunk_id=chunk['id'],annotation='Remember'))
        response=await self.client.post('/api/v1/library/export',json={'collection_id':collection})
        self.assertEqual(response.status_code,200,response.text[:100])
        exported=response.content
        self.ctx.documents.delete(self.first,'local')
        response=await self.client.post('/api/v1/library/import',files={'file':('library.zip',exported)})
        self.assertEqual(response.status_code,202,response.text)
        identifier=response.json()['documents'][0]['id']
        self.ctx.worker.run_once()
        doc=self.ctx.documents.require(identifier,'local')
        self.assertEqual(doc['title'],'Revision physics')
        self.assertEqual(doc['collections'][0]['name'],'Revision')
        self.assertEqual(self.ctx.library.bookmarks('local',identifier)[0]['annotation'],'Remember')

    async def test_literal_filename_search_and_duplicate_edition_review(self):
        await self.patch(self.first,title='100% Physics',edition='First')
        await self.patch(self.second,title='100% Physics',edition='Second')
        self.assertEqual((await self.listing(q='%'))['total'],2)
        self.assertEqual((await self.listing(q='_'))['total'],0)
        response=await self.client.get('/api/v1/library/duplicates')
        self.assertEqual(len(response.json()),1)
        self.assertEqual(len(response.json()[0]['documents']),2)
    async def test_invalid_archive_and_import_quota_do_not_write_documents(self):
        import io,json,zipfile
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('manifest.json',json.dumps({'format':1,'documents':[]}))
            archive.writestr('../unsafe',b'bad')
        response=await self.client.post('/api/v1/library/import',files={'file':('bad.zip',stream.getvalue())})
        self.assertEqual(response.status_code,400)
        self.assertEqual((await self.listing())['total'],2)
        response=await self.client.post('/api/v1/library/export',json={'document_ids':[self.first]})
        self.ctx.documents.delete(self.first,'local')
        self.ctx.settings.max_library_bytes=1
        response=await self.client.post('/api/v1/library/import',files={'file':('library.zip',response.content)})
        self.assertEqual(response.status_code,413,response.text)
        self.assertEqual((await self.listing())['total'],1)
    async def test_empty_collection_export_import(self):
        collection=await self.category('collection','No documents yet')
        response=await self.client.post('/api/v1/library/export',json={'collection_id':collection})
        self.assertEqual(response.status_code,200,response.text)
        archive=response.content
        await self.client.delete('/api/v1/library/categories/'+collection)
        response=await self.client.post('/api/v1/library/import',files={'file':('empty.zip',archive)})
        self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(response.json()['imported'],0)
        self.assertIn('No documents yet',[item['name'] for item in (await self.client.get('/api/v1/library/catalog')).json()['collections']])
    async def test_preview_bookmark_and_export_are_owner_scoped(self):
        other=upload_ready(self.ctx,'Private notes.','private.txt',owner='other')
        with self.ctx.db.connect() as conn:
            chunk=conn.execute('SELECT id FROM chunks WHERE document_id=?',(other,)).fetchone()[0]
        for suffix in ['preview','suggestions','related']:
            response=await self.client.get('/api/v1/library/documents/'+other+'/'+suffix)
            self.assertEqual(response.status_code,404)
        response=await self.client.post('/api/v1/library/bookmarks',json={'chunk_id':chunk})
        self.assertEqual(response.status_code,404)
        response=await self.client.post('/api/v1/library/export',json={'document_ids':[other]})
        self.assertEqual(response.status_code,404)
    async def test_bulk_reindex_preflight_and_metadata_conflict_are_atomic(self):
        self.ctx.documents.reindex(self.second,'local')
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'reindex'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.ctx.documents.require(self.first,'local')['status'],'ready')
        await self.patch(self.second,author='Updated author')
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'favorite','expected_metadata_versions':{self.first:1,self.second:1}})
        self.assertEqual(response.status_code,409)
        self.assertFalse(self.ctx.documents.require(self.first,'local')['favorite'])
    async def test_bulk_restore_and_membership_limit(self):
        await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'trash'})
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'restore'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['updated'],2)
        ids=[await self.category('subject','Subject '+str(i)) for i in range(31)]
        response=await self.client.post('/api/v1/library/bulk',json={'document_ids':[self.first,self.second],'action':'assign','category_ids':ids})
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.ctx.documents.require(self.first,'local')['subjects'],[])

    async def test_archive_validates_all_file_payloads_before_uploading(self):
        import hashlib,io,json,zipfile,uuid
        stream=io.BytesIO();items=[]
        with zipfile.ZipFile(stream,'w') as archive:
            for filename,data in [('valid.txt',b'New valid notes.'),('invalid.pdf',b'Not a PDF')]:
                path='documents/'+str(uuid.uuid4())+'/'+filename
                archive.writestr(path,data)
                items.append({'filename':filename,'path':path,'content_hash':hashlib.sha256(data).hexdigest(),'metadata':{}})
            archive.writestr('manifest.json',json.dumps({'format':1,'documents':items,'collection':{'name':'Should not be created','description':''}}))
        response=await self.client.post('/api/v1/library/import',files={'file':('library.zip',stream.getvalue())})
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual((await self.listing())['total'],2)
        self.assertEqual((await self.client.get('/api/v1/library/catalog')).json()['collections'],[])
