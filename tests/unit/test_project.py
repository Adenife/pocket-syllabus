"""Offline unit tests for document storage, ingestion, and search."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from app.ingestion.chunker import chunk_blocks
from app.ingestion.parsers.markdown import parse
from app.ingestion.parsers.text import Block
from app.schemas.resource import SearchQuery
from app.services.embedding_service import SearchServiceError
from app.services.search_service import SearchService
from helpers import Tokenizer, context, upload_ready

class SchemaTests(unittest.TestCase):
    def test_defaults_and_trim(self):
        q = SearchQuery(query=' light ')
        self.assertEqual((q.query, q.limit, q.document_ids, q.hybrid), ('light', 3, [], True))
    def test_invalid(self):
        for payload in [{}, {'query': ' '}, {'query': 'x'*2001}, {'query':'x','limit':0}, {'query':'x','limit':51}]:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                SearchQuery(**payload)

class ChunkTests(unittest.TestCase):
    def test_budget_special_tokens_and_overlap(self):
        words = ['w'+str(i) for i in range(35)]
        blocks = [Block(' '.join(words), 'Book')]
        chunks = list(chunk_blocks(blocks, Tokenizer(), 16, budget=40, overlap=2))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(Tokenizer().encode(c.text)) <= 16 for c in chunks))
        self.assertEqual(chunks[0].text.split()[-2:], chunks[1].text.split()[:2])
        self.assertEqual(set(' '.join(c.text for c in chunks).split()), set(words))
    def test_structure_and_code_fences(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'note.md'
            path.write_text('# Physics\n## Code\n```python\n# not a heading\na = 1\n```\n\n### Motion\nSpeed changes.\n')
            blocks = list(parse(path, 'fallback', []))
        self.assertEqual(blocks[0].section, 'Physics / Code')
        self.assertIn('# not a heading', blocks[0].text)
        self.assertEqual(blocks[1].section, 'Physics / Code / Motion')
        self.assertIsNotNone(blocks[1].line)
    def test_sentence_boundary(self):
        text = 'One two three four five six. Seven eight nine ten eleven twelve thirteen fourteen fifteen.'
        chunks = list(chunk_blocks([Block(text,'Book')], Tokenizer(),16,budget=10,overlap=0))
        self.assertTrue(chunks[0].text.endswith('six.'))
    def test_no_empty_chunks(self):
        self.assertEqual(list(chunk_blocks([Block('','Book')],Tokenizer(),16)), [])

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx = context(self.temp.name)
    def test_upload_index_duplicate_and_original(self):
        identifier = upload_ready(self.ctx)
        doc = self.ctx.documents.require(identifier,'local')
        self.assertEqual((doc['status'],doc['chunk_count'],doc['indexed_version']),('ready',2,1))
        doc2, data = self.ctx.documents.original(identifier,'local')
        result = self.ctx.documents.upload('local', doc2['filename'], data)
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['document']['id'],identifier)
    def test_batches_and_failed_replacement_preserve_chunks(self):
        identifier = upload_ready(self.ctx)
        doc = self.ctx.documents.require(identifier,'local')
        self.ctx.documents.upload('local','book.md',('new text '*60).encode(),identifier,doc['version'])
        self.ctx.embedder.fail = True
        self.ctx.worker.run_once()
        doc = self.ctx.documents.require(identifier,'local')
        self.assertEqual(doc['status'],'failed')
        self.assertEqual(doc['indexed_version'],1)
        self.assertEqual(doc['chunk_count'],2)
        self.ctx.embedder.fail = False
        self.assertTrue(self.ctx.search.search('light',hybrid=False))
        self.ctx.documents.reindex(identifier,'local')
        self.ctx.worker.run_once()
        self.assertEqual(self.ctx.documents.require(identifier,'local')['status'],'ready')
        self.assertTrue(all(len(batch)<=2 for batch in self.ctx.embedder.calls))
    def test_reindex_does_not_duplicate(self):
        identifier=upload_ready(self.ctx)
        self.ctx.documents.reindex(identifier,'local')
        self.ctx.worker.run_once()
        self.assertEqual(self.ctx.documents.require(identifier,'local')['chunk_count'],2)
    def test_empty_file_and_unsupported_and_traversal(self):
        for name, data, status in [('a.md',b'',400),('a.exe',b'a',415),('../a.md',b'a',400),('a.txt',b'\xff',400),('a.pdf',b'fake',400),('a.docx',b'fake',400)]:
            with self.subTest(name=name), self.assertRaises(HTTPException) as error:
                self.ctx.documents.upload('local',name,data)
            self.assertEqual(error.exception.status_code,status)
    def test_heading_only_fails_with_actionable_error(self):
        result=self.ctx.documents.upload('local','empty.md',b'# Heading')
        self.ctx.worker.run_once()
        doc=self.ctx.documents.require(result['document']['id'],'local')
        self.assertEqual(doc['status'],'failed')
        self.assertIn('No extractable text',doc['error'])
    def test_delete_removes_original_chunks_jobs_and_persisted_index(self):
        identifier=upload_ready(self.ctx)
        self.ctx.search.search('light')
        self.ctx.documents.reindex(identifier,'local')
        self.ctx.documents.delete(identifier,'local',1)
        self.assertEqual(self.ctx.search.search('light'),[])
        self.assertEqual(list(self.ctx.settings.upload_dir.glob('*.md')),[])
        self.assertEqual(list(self.ctx.settings.index_dir.glob('*.index')),[])
        with self.ctx.db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM chunks_fts').fetchone()[0],0)
        self.assertEqual(self.ctx.sync.changes('local')['changes'][-1]['action'],'delete')
    def test_version_conflict_preserves_document(self):
        identifier=upload_ready(self.ctx)
        with self.assertRaises(HTTPException) as error:
            self.ctx.documents.upload('local','book.md',b'changed',identifier,99)
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.ctx.documents.require(identifier,'local')['version'],1)
    def test_owner_isolation_and_document_filter(self):
        first=upload_ready(self.ctx,owner='alice')
        second=upload_ready(self.ctx,text='Motion and speed.',filename='motion.txt',owner='bob')
        self.assertEqual(self.ctx.search.search('motion',owner='alice',document_ids=[second]),[])
        self.assertTrue(all(item.document_id==first for item in self.ctx.search.search('light',owner='alice')))
        with self.assertRaises(HTTPException):
            self.ctx.documents.original(first,'bob')
    def test_cached_index_reload_invalidation_and_persisted_snapshot(self):
        upload_ready(self.ctx)
        self.ctx.search.search('light')
        builds=self.ctx.search.index.build_count
        self.ctx.search.search('DNA')
        self.assertEqual(self.ctx.search.index.build_count,builds)
        other=SearchService(self.ctx.db,self.ctx.embedder)
        self.assertTrue(other.search('light'))
        self.assertEqual(other.index.build_count,0)
        upload_ready(self.ctx,'Motion and speed.','motion.txt')
        self.ctx.search.search('motion')
        self.assertEqual(self.ctx.search.index.build_count,builds+1)
    def test_hnsw_returns_relevant_results(self):
        self.ctx.settings.ann_threshold=1
        identifier=upload_ready(self.ctx)
        self.assertEqual(self.ctx.search.search('light',1,hybrid=False)[0].document_id,identifier)
        self.assertAlmostEqual(self.ctx.search.search('light',1,hybrid=False)[0].score,1)
    def test_corrupt_vectors_and_query_fail_cleanly(self):
        upload_ready(self.ctx)
        with self.ctx.db.connect() as conn:
            conn.execute('UPDATE chunks SET embedding=?',(b'bad',))
        with self.assertRaises(SearchServiceError):
            self.ctx.search.search('light')
    def test_lexical_search_and_encrypted_mode(self):
        upload_ready(self.ctx)
        self.assertTrue(self.ctx.search.chunks.lexical('DNA','local',[],10))
        encrypted=context(Path(self.temp.name)/'encrypted',encryption_key=Fernet.generate_key().decode())
        identifier=upload_ready(encrypted)
        doc,data=encrypted.documents.original(identifier,'local')
        path=encrypted.settings.upload_dir/doc['storage_name']
        self.assertNotIn(b'Light powers',path.read_bytes())
        self.assertTrue(encrypted.search.search('light'))
        self.assertEqual(encrypted.search.chunks.lexical('DNA','local',[],10),[])
        with encrypted.db.connect() as conn:
            row=conn.execute('SELECT text,embedding FROM chunks LIMIT 1').fetchone()
            self.assertNotIn(b'Light powers',row['text'])
        with self.assertRaises(ValueError):
            context(Path(self.temp.name)/'encrypted')
    def test_quota(self):
        self.ctx.settings.max_upload_bytes=2
        with self.assertRaises(HTTPException) as error:
            self.ctx.documents.upload('local','book.md',b'123')
        self.assertEqual(error.exception.status_code,413)
    def test_recover_interrupted_job_and_single_worker_lock(self):
        result=self.ctx.documents.upload('local','a.txt',b'Light travels.')
        self.ctx.worker.claim()
        self.assertTrue(self.ctx.worker.acquire())
        other=context(self.temp.name)
        self.assertFalse(other.worker.acquire())
        self.ctx.worker.run_once()
        self.ctx.worker.close()
        self.assertEqual(self.ctx.documents.require(result['document']['id'],'local')['status'],'ready')
    def test_deleting_running_job_prevents_resurrection(self):
        result=self.ctx.documents.upload('local','a.txt',b'Light travels.')
        job=self.ctx.worker.claim()
        self.ctx.documents.delete(result['document']['id'],'local')
        self.ctx.ingestion.run(job)
        self.assertEqual(self.ctx.search.search('light'),[])

class StreamingLimitsTests(unittest.TestCase):
    def test_invalid_dimension_later_batch_preserves_old_index(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=context(temp)
            identifier=upload_ready(ctx)
            ctx.documents.upload('local','book.md',('Light travels.\n\n'*8).encode(),identifier,1)
            calls=0
            def mismatched(texts):
                nonlocal calls
                calls+=1
                return np.ones((len(texts),3 if calls==1 else 4),dtype=np.float32)
            with patch.object(ctx.embedder,'encode',side_effect=mismatched):
                ctx.worker.run_once()
            doc=ctx.documents.require(identifier,'local')
            self.assertEqual(doc['status'],'failed')
            self.assertEqual(doc['chunk_count'],2)
            self.assertIn('dimensions changed',doc['error'])

    def test_shared_index_directory_does_not_cross_library_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            from app.core.config import Settings
            from app.services.context import Context
            from helpers import Embedder
            root=Path(temp)
            first=context(root/'first')
            second=Context(Settings(db_path=root/'second.db',upload_dir=root/'second-uploads',
                           index_dir=first.settings.index_dir,worker_enabled=False),Embedder())
            upload_ready(first,'Light in plants.','light.txt')
            upload_ready(second,'Motion in physics.','motion.txt')
            self.assertIn('Light',first.search.search('light')[0].text_excerpt)
            self.assertIn('Motion',second.search.search('motion')[0].text_excerpt)
