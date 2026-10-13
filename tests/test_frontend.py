"""Exercise the Streamlit UI without starting a backend server."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.ui = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        self.assertEqual(len(self.ui.exception), 0)

    def test_blank_search_shows_warning_without_http_request(self):
        with patch('requests.post') as post:
            self.ui.button[0].click().run()
        post.assert_not_called()
        self.assertEqual(self.ui.warning[0].value, 'Enter a topic or question to search.')

    def test_search_displays_citations_and_download(self):
        response = Mock(ok=True)
        response.json.return_value = {
            'query': 'cells',
            'results': [{'id': 7, 'source_title': 'Biology', 'section': 'Cells',
                         'text_excerpt': 'Cells contain DNA.', 'score': 0.9}],
        }
        with patch('requests.post', return_value=response) as post:
            self.ui.text_input[0].set_value(' cells ')
            self.ui.button[0].click().run()
        post.assert_called_once_with(
            'http://127.0.0.1:8000/api/v1/search',
            json={'query': 'cells', 'limit': 3}, timeout=120,
        )
        self.assertEqual(len(self.ui.exception), 0)
        self.assertIn('Cells contain DNA.', [item.value for item in self.ui.markdown])
        self.assertTrue(any('Biology — Cells (local chunk 7)' in item.value for item in self.ui.caption))
        downloads = self.ui.get('download_button')
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0].proto.label, 'Save Excerpt for Offline Reading (.txt)')
        # Streamlit reruns must keep results without issuing another HTTP request.
        with patch('requests.post') as post:
            self.ui.run()
        post.assert_not_called()
        self.assertEqual(len(self.ui.get('download_button')), 1)

    def test_backend_connection_error_is_visible(self):
        with patch('requests.post', side_effect=requests.ConnectionError('offline')):
            self.ui.text_input[0].set_value('physics')
            self.ui.button[0].click().run()
        self.assertEqual(len(self.ui.exception), 0)
        self.assertIn('Cannot reach the local API', self.ui.error[0].value)

    def test_backend_error_detail_is_visible(self):
        response = Mock(ok=False)
        response.json.return_value = {'detail': 'Run python ingest.py first.'}
        with patch('requests.post', return_value=response):
            self.ui.text_input[0].set_value('physics')
            self.ui.button[0].click().run()
        self.assertEqual(self.ui.error[0].value, 'Search failed: Run python ingest.py first.')
