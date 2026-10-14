import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from streamlit.testing.v1 import AppTest

APP_PATH=Path(__file__).resolve().parents[2]/'app.py'

class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.result={'query':'cells','results':[{'id':7,'document_id':'doc7','filename':'biology.md','source_title':'Biology','section':'Cells','text_excerpt':'Cells contain DNA.','score':0.9,'page':None,'line':3}]}
        self.calls=[]
        self.patch=patch('requests.request',side_effect=self.request)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.ui=AppTest.from_file(str(APP_PATH)).run(timeout=20)
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        response=Mock(ok=True,status_code=200)
        if url.endswith('/auth/mode'):
            response.json.return_value={'auth_enabled':False,'registration_enabled':False}
        elif url.endswith('/library/catalog'):
            response.json.return_value={'subjects':[],'tags':[],'collections':[]}
        elif url.endswith('/library/statistics'):
            response.json.return_value={'documents':0,'favorites':0,'trash_documents':0,'storage_bytes':0,'quota_bytes':1000000,'status_counts':{},'subjects':[]}
        elif url.endswith('/library/bookmarks'):
            response.json.return_value=[]
        elif method=='GET' and url.endswith('/library/documents'):
            response.json.return_value={'items':[],'total':0}
        elif method=='GET' and url.endswith('/documents'):
            response.json.return_value=[]
        elif url.endswith('/search'):
            response.json.return_value=self.result
        elif method=='POST' and url.endswith('/documents'):
            response.json.return_value={'document':{'id':'new'},'job_id':'job','duplicate':False}
        return response
    def click(self,label):
        next(button for button in self.ui.button if button.label==label).click().run(timeout=20)
    def test_library_and_note_controls_present(self):
        self.assertEqual(len(self.ui.exception),0)
        self.assertTrue({'Search','Library','Settings'}.issubset({tab.label for tab in self.ui.tabs}))
        self.assertIn('Trash',[tab.label for tab in self.ui.tabs])
        self.assertEqual(len(self.ui.get('file_uploader')),2)
        self.assertTrue(any(button.label=='Upload and index' for button in self.ui.button))
    def test_blank_query_makes_no_search_request(self):
        self.click('Search')
        self.assertTrue(any('Enter a topic' in warning.value for warning in self.ui.warning))
        self.assertFalse(any(url.endswith('/search') for _,url,_ in self.calls))
    def test_search_citations_download_and_rerun(self):
        next(item for item in self.ui.text_input if item.label=='What would you like to learn?').set_value(' cells ')
        self.click('Search')
        self.assertEqual(len(self.ui.exception),0)
        self.assertTrue(any('Line 3' in caption.value for caption in self.ui.caption))
        self.assertEqual(len(self.ui.get('download_button')),1)
        before=len([url for _,url,_ in self.calls if url.endswith('/search')])
        self.ui.run()
        self.assertEqual(before,len([url for _,url,_ in self.calls if url.endswith('/search')]))
    def test_save_note_uploads_markdown(self):
        next(item for item in self.ui.text_input if item.label=='Note title').set_value('Biology notes')
        self.ui.text_area[0].set_value('Cells contain DNA.')
        self.click('Save and index note')
        uploads=[kwargs for method,url,kwargs in self.calls if method=='POST' and url.endswith('/documents')]
        self.assertEqual(len(uploads),1)
        self.assertIn(b'# Biology notes',uploads[0]['files']['file'][1])
        self.assertTrue(any('Note queued' in success.value for success in self.ui.success))
    def test_connection_error(self):
        with patch('requests.request',side_effect=requests.ConnectionError('offline')):
            self.ui.run()
        self.assertEqual(len(self.ui.exception),0)
        self.assertTrue(any('Cannot reach the backend' in error.value for error in self.ui.error))

    def test_edit_and_delete_document_controls(self):
        doc={'id':'doc7','filename':'notes.md','title':'Notes','file_type':'.md',
             'size':30,'status':'ready','chunk_count':1,'version':1,'indexed_version':1,
             'warnings':[],'error':None}
        normal=self.request
        def request(method,url,**kwargs):
            response=normal(method,url,**kwargs)
            if method=='GET' and url.endswith('/library/documents'):
                response.json.return_value={'items':[] if kwargs.get('params',{}).get('trash') else [doc],'total':0 if kwargs.get('params',{}).get('trash') else 1}
            elif method=='GET' and url.endswith('/documents'):
                response.json.return_value=[doc]
            if method=='GET' and url.endswith('/original'):
                response.content=b'# Notes\n\nOriginal text.'
            return response
        with patch('requests.request',side_effect=request):
            self.ui.run()
            trash=next(button for button in self.ui.button if button.label=='Move to trash')
            self.assertFalse(trash.disabled)
            self.click('Edit note')
            next(area for area in self.ui.text_area if area.label=='Edit document text').set_value('# Notes\n\nUpdated text.')
            self.click('Save changes')
            uploads=[kwargs for method,url,kwargs in self.calls if method=='POST' and url.endswith('/documents')]
            self.assertEqual(uploads[-1]['params'],{'document_id':'doc7','expected_version':1})
            self.assertIn(b'Updated text',uploads[-1]['files']['file'][1])
            self.assertTrue(any(button.label=='Move to trash' for button in self.ui.button))

    def test_account_sign_in(self):
        normal=self.request
        def request(method,url,**kwargs):
            response=normal(method,url,**kwargs)
            if url.endswith('/auth/mode'):
                response.json.return_value={'auth_enabled':True,'registration_enabled':True}
            if url.endswith('/auth/login'):
                response.json.return_value={'access_token':'opaque-token'}
            return response
        with patch('requests.request',side_effect=request):
            self.ui.run()
            next(item for item in self.ui.text_input if item.label=='Username').set_value('alice')
            next(item for item in self.ui.text_input if item.label=='Password').set_value('verysecret123')
            self.click('Sign in')
        self.assertEqual(len(self.ui.exception),0)
        self.assertEqual(self.ui.session_state['access_token'],'opaque-token')
        self.assertTrue(any(kwargs.get('headers',{}).get('Authorization')=='Bearer opaque-token' for _,_,kwargs in self.calls))

    def test_sort_filters_and_search_organization_controls(self):
        self.assertTrue(any(item.label=='Sort by' for item in self.ui.selectbox))
        next(item for item in self.ui.selectbox if item.label=='Sort by').select('Title')
        next(item for item in self.ui.selectbox if item.label=='Sort direction').select('Ascending')
        next(item for item in self.ui.text_input if item.label=='Find a document').set_value('Physics')
        self.click('Apply filters')
        calls=[kwargs for method,url,kwargs in self.calls if method=='GET' and url.endswith('/library/documents') and not kwargs.get('params',{}).get('trash')]
        self.assertEqual(calls[-1]['params']['sort_by'],'title')
        self.assertEqual(calls[-1]['params']['sort_order'],'asc')
        self.assertEqual(calls[-1]['params']['q'],'Physics')
        self.assertTrue(any(item.label=='Search collections' for item in self.ui.multiselect))
    def test_metadata_editor_sends_version_and_fields(self):
        doc={'id':'doc7','filename':'notes.md','title':'Notes','file_type':'.md','size':30,
             'status':'ready','chunk_count':1,'version':1,'indexed_version':1,'warnings':[],'error':None,'metadata_version':3}
        normal=self.request
        def request(method,url,**kwargs):
            response=normal(method,url,**kwargs)
            if method=='GET' and url.endswith('/library/documents') and not kwargs.get('params',{}).get('trash'):
                response.json.return_value={'items':[doc],'total':1}
            if method=='PATCH' and url.endswith('/library/documents/doc7'):
                doc.update(title=kwargs['json']['title'],metadata_version=4)
                response.json.return_value=doc
            return response
        with patch('requests.request',side_effect=request):
            self.ui.run()
            next(item for item in self.ui.text_input if item.label=='Display title').set_value('My revision notes')
            self.click('Save details')
        self.assertEqual(len(self.ui.exception),0)
        payload=next(kwargs['json'] for method,url,kwargs in self.calls if method=='PATCH' and url.endswith('/library/documents/doc7'))
        self.assertEqual(payload['expected_metadata_version'],3)
        self.assertEqual(payload['title'],'My revision notes')
    def test_preview_and_related_controls_use_separate_state_keys(self):
        doc={'id':'doc7','filename':'notes.md','title':'Notes','file_type':'.md','size':30,
             'status':'ready','chunk_count':1,'version':1,'indexed_version':1,'warnings':[],'error':None}
        normal=self.request
        def request(method,url,**kwargs):
            response=normal(method,url,**kwargs)
            if method=='GET' and url.endswith('/library/documents') and not kwargs.get('params',{}).get('trash'):
                response.json.return_value={'items':[doc],'total':1}
            if url.endswith('/preview'):
                response.json.return_value={'items':[{'id':7,'text':'Cells contain DNA.','section':'Cells','page':None,'line':3}],'total':1}
            if url.endswith('/related'):
                response.json.return_value=[]
            return response
        with patch('requests.request',side_effect=request):
            self.ui.run();self.click('Load preview');self.click('Find related materials')
        self.assertEqual(len(self.ui.exception),0)
        self.assertIsInstance(self.ui.session_state['preview-data-doc7'],dict)
        self.assertIsInstance(self.ui.session_state['related-data-doc7'],list)

    def test_author_edit_does_not_pin_extracted_title(self):
        doc={'id':'doc7','filename':'notes.md','title':'Extracted title','display_title':None,'file_type':'.md',
             'size':30,'status':'ready','chunk_count':1,'version':1,'indexed_version':1,'warnings':[],'error':None,'metadata_version':1}
        normal=self.request
        def request(method,url,**kwargs):
            response=normal(method,url,**kwargs)
            if method=='GET' and url.endswith('/library/documents') and not kwargs.get('params',{}).get('trash'):
                response.json.return_value={'items':[doc],'total':1}
            return response
        with patch('requests.request',side_effect=request):
            self.ui.run()
            next(item for item in self.ui.text_input if item.label=='Author').set_value('A. Writer')
            self.click('Save details')
        payload=next(kwargs['json'] for method,url,kwargs in self.calls if method=='PATCH' and url.endswith('/library/documents/doc7'))
        self.assertIsNone(payload['title'])
        self.assertEqual(payload['author'],'A. Writer')
