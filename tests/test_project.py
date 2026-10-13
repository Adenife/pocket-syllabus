"""Offline regression tests: python -m unittest discover -s tests -v."""
import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
from pydantic import ValidationError

import ingest
from app.main import app
from app.schemas.resource import SearchQuery
from app.services.search_service import SearchService, SearchServiceError

endpoint = importlib.import_module('app.api.v1.endpoints.search')


def embeddings(texts):
    return np.array([[1.0, 0.0] if 'light' in text.lower() else [0.0, 1.0]
                     for text in texts], dtype=np.float32)


class MarkdownTests(unittest.TestCase):
    def test_headings_and_multiline_paragraph_citations(self):
        chunks = ingest.chunk_markdown(
            'Preface\n\n# Biology\n## Cells\nFirst line\nsecond line\n\n## Energy\nLight.', 'fallback')
        self.assertEqual(chunks, [
            ('fallback', 'Introduction', 'Preface'),
            ('Biology', 'Cells', 'First line second line'),
            ('Biology', 'Energy', 'Light.'),
        ])

    def test_long_paragraph_preserves_every_word(self):
        words = [f'word{i}' for i in range(401)]
        chunks = ingest.chunk_markdown(' '.join(words), 'Book')
        self.assertEqual([len(c[2].split()) for c in chunks], [180, 180, 41])
        self.assertEqual(' '.join(c[2] for c in chunks), ' '.join(words))

    def test_headings_only_have_no_chunks(self):
        self.assertEqual(ingest.chunk_markdown('# Title\n\n## Section', 'Book'), [])


class SchemaTests(unittest.TestCase):
    def test_trim_and_default_limit(self):
        query = SearchQuery(query='  light  ')
        self.assertEqual((query.query, query.limit), ('light', 3))

    def test_invalid_requests(self):
        for payload in [{'query': ''}, {'query': '   '}, {'query': 'x' * 2001},
                        {'query': 'x', 'limit': 0}, {'query': 'x', 'limit': 51}, {}]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                SearchQuery(**payload)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.db = self.root / 'database' / 'syllabus.db'
        (self.data / 'book.md').write_text('# Biology\n## Energy\nLight powers plants.\n\nCells contain DNA.', encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch('ingest.encode_texts', side_effect=embeddings).start()
        patch('app.services.search_service.encode_texts', side_effect=embeddings).start()

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute('SELECT * FROM chunks ORDER BY id').fetchall()

    def test_ingestion_persists_citations_and_float32_vectors(self):
        self.assertEqual(ingest.ingest(self.data, self.db), 2)
        row = self.rows()[0]
        self.assertEqual(row[1:5], ('book.md', 'Biology', 'Energy', 'Light powers plants.'))
        np.testing.assert_array_equal(np.frombuffer(row[5], dtype=np.float32), [1, 0])

    def test_reindex_replaces_removed_material_without_duplicates(self):
        ingest.ingest(self.data, self.db)
        (self.data / 'book.md').unlink()
        nested = self.data / 'nested'
        nested.mkdir()
        (nested / 'new.md').write_text('New material.', encoding='utf-8')
        ingest.ingest(self.data, self.db)
        ingest.ingest(self.data, self.db)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'nested/new.md')

    def test_model_failure_preserves_existing_index(self):
        ingest.ingest(self.data, self.db)
        before = self.rows()
        with patch('ingest.encode_texts', side_effect=SearchServiceError('Model unavailable')):
            with self.assertRaises(SearchServiceError):
                ingest.ingest(self.data, self.db)
        self.assertEqual(self.rows(), before)

    def test_invalid_embeddings_preserve_existing_index(self):
        ingest.ingest(self.data, self.db)
        before = self.rows()
        for vectors in [np.array([[1, 0]], dtype=np.float32), np.full((2, 2), np.nan)]:
            with self.subTest(vectors=vectors), patch('ingest.encode_texts', return_value=vectors):
                with self.assertRaises(ValueError):
                    ingest.ingest(self.data, self.db)
            self.assertEqual(self.rows(), before)

    def test_missing_or_empty_materials_do_not_create_database(self):
        for path in self.data.glob('*.md'):
            path.unlink()
        with self.assertRaisesRegex(ValueError, 'No markdown'):
            ingest.ingest(self.data, self.db)
        (self.data / 'empty.md').write_text('# Heading', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'no indexable'):
            ingest.ingest(self.data, self.db)
        self.assertFalse(self.db.exists())

    def test_cosine_ranking_is_scale_invariant_and_limited(self):
        ingest.ingest(self.data, self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE chunks SET embedding=? WHERE id=1',
                         (np.array([7, 0], dtype=np.float32).tobytes(),))
        results = SearchService(self.db).search('light', 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1)
        self.assertAlmostEqual(results[0].score, 1.0)
        self.assertEqual(results[0].source_title, 'Biology')

    def test_equal_scores_use_stable_id_order(self):
        ingest.ingest(self.data, self.db)
        with patch('app.services.search_service.encode_texts', return_value=np.array([[1, 1]], dtype=np.float32)):
            results = SearchService(self.db).search('both', 50)
        self.assertEqual([r.id for r in results], [1, 2])
        self.assertAlmostEqual(results[0].score, results[1].score)

    def test_empty_index_does_not_load_model(self):
        ingest.ingest(self.data, self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('DELETE FROM chunks')
        with patch('app.services.search_service.encode_texts') as encode:
            self.assertEqual(SearchService(self.db).search('light'), [])
            encode.assert_not_called()

    def test_missing_and_uninitialized_index_report_actionable_error(self):
        with self.assertRaisesRegex(SearchServiceError, 'Run python ingest.py'):
            SearchService(self.db).search('light')
        self.assertFalse(self.db.exists())
        self.db.parent.mkdir()
        sqlite3.connect(self.db).close()
        with self.assertRaisesRegex(SearchServiceError, 'Run python ingest.py'):
            SearchService(self.db).search('light')

    def test_corrupt_vectors_report_reindex_error(self):
        ingest.ingest(self.data, self.db)
        for blob in [b'bad', np.array([1, 2, 3], dtype=np.float32).tobytes(),
                     np.array([np.nan, 0], dtype=np.float32).tobytes()]:
            with self.subTest(blob=blob):
                with sqlite3.connect(self.db) as conn:
                    conn.execute('UPDATE chunks SET embedding=? WHERE id=1', (blob,))
                with self.assertRaises(SearchServiceError):
                    SearchService(self.db).search('light')

    def test_zero_or_nonfinite_query_vector_is_rejected(self):
        ingest.ingest(self.data, self.db)
        for vector in [[[0, 0]], [[np.nan, 1]]]:
            with self.subTest(vector=vector), patch('app.services.search_service.encode_texts', return_value=np.array(vector)):
                with self.assertRaisesRegex(SearchServiceError, 'invalid query'):
                    SearchService(self.db).search('light')

    def test_zero_stored_vector_returns_finite_score(self):
        ingest.ingest(self.data, self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE chunks SET embedding=? WHERE id=1', (np.zeros(2, dtype=np.float32).tobytes(),))
        self.assertTrue(all(r.score == 0 for r in SearchService(self.db).search('light')))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health(self):
        response = await self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'app': 'PocketSyllabus'})

    async def test_search_response_and_normalized_query(self):
        from app.schemas.resource import SearchResultItem
        item = SearchResultItem(id=1, source_title='Book', section='Cells', text_excerpt='DNA', score=0.9)
        with patch.object(endpoint.service, 'search', return_value=[item]) as search:
            response = await self.client.post('/api/v1/search', json={'query': ' cells ', 'limit': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'query': 'cells', 'results': [item.model_dump()]})
        search.assert_called_once_with('cells', 1)

    async def test_validation_prevents_service_calls(self):
        with patch.object(endpoint.service, 'search') as search:
            for payload in [{}, {'query': ' '}, {'query': 'x', 'limit': 0}, {'query': 'x', 'limit': 51}]:
                with self.subTest(payload=payload):
                    response = await self.client.post('/api/v1/search', json=payload)
                    self.assertEqual(response.status_code, 422)
            search.assert_not_called()

    async def test_index_failure_returns_503(self):
        with patch.object(endpoint.service, 'search', side_effect=SearchServiceError('Run python ingest.py first.')):
            response = await self.client.post('/api/v1/search', json={'query': 'cells'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'Run python ingest.py first.')

    async def test_empty_results_are_successful(self):
        with patch.object(endpoint.service, 'search', return_value=[]):
            response = await self.client.post('/api/v1/search', json={'query': 'cells'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])


if __name__ == '__main__':
    unittest.main()
