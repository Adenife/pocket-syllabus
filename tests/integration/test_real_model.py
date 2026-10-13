"""Opt-in integration checks using the locally cached MiniLM model."""
import os
import tempfile
import unittest
from pathlib import Path
from app.core.config import Settings
from app.services.context import Context

@unittest.skipUnless(os.getenv('POCKET_REAL_MODEL_TESTS')=='1','Enable POCKET_REAL_MODEL_TESTS=1 with a cached model')
class RealModelTests(unittest.TestCase):
    def test_upload_token_bounds_and_semantic_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            ctx=Context(Settings(db_path=root/'library.db',upload_dir=root/'uploads',index_dir=root/'indexes',offline=True,worker_enabled=False))
            content='# Biology\n## Photosynthesis\nPlants convert sunlight, carbon dioxide and water into sugars and oxygen.\n\n## Genetics\nDNA stores hereditary information.\n'
            content += '\n## Calculation notes\n' + 'alpha_beta := force ** acceleration; ' * 150
            result=ctx.documents.upload('local','biology.md',content.encode())
            ctx.worker.run_once()
            doc=ctx.documents.require(result['document']['id'],'local')
            self.assertEqual(doc['status'],'ready',doc['error'])
            results=ctx.search.search('How do plants use sunlight to make food?',1,hybrid=False)
            self.assertIn('Photosynthesis',results[0].section)
            self.assertGreater(results[0].score,0.4)
            with ctx.db.connect() as conn:
                rows=conn.execute('SELECT text FROM chunks').fetchall()
            self.assertGreater(len(rows),2)
            self.assertTrue(all(len(ctx.embedder.tokenizer.encode(row['text'].decode()))<=ctx.embedder.max_tokens for row in rows))
