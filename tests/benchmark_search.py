"""Synthetic retrieval benchmark: python tests/benchmark_search.py."""
import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import json
import tempfile
import time
import tracemalloc
from pathlib import Path
import faiss
import numpy as np
from helpers import context,upload_ready


def benchmark(count=10000,dimension=384):
    rng=np.random.default_rng(42)
    vectors=rng.normal(size=(count,dimension)).astype(np.float32)
    faiss.normalize_L2(vectors)
    with tempfile.TemporaryDirectory() as temp:
        ctx=context(temp,ann_threshold=1000)
        identifier=upload_ready(ctx)
        with ctx.db.connect() as conn:
            ctx.db.remove_fts(conn,identifier)
            conn.execute('DELETE FROM chunks')
            conn.executemany('''INSERT INTO chunks(document_id,owner_id,ordinal,source_title,section,text,embedding,model_name)
                VALUES (?,'local',?,'Book','Section',?,?,?)''',
                ((identifier,i,b'benchmark',v.tobytes(),ctx.settings.model_name) for i,v in enumerate(vectors)))
            ctx.db.bump(conn)
        started=time.perf_counter()
        index=ctx.search.index.snapshot('local')
        build_seconds=time.perf_counter()-started
        queries=vectors[rng.choice(count,50,replace=False)].copy()
        exact=faiss.IndexFlatIP(dimension);exact.add(vectors)
        _,expected=exact.search(queries,10)
        started=time.perf_counter();_,actual=index.search(queries,10)
        latency=(time.perf_counter()-started)*1000/len(queries)
        # AUTOINCREMENT IDs continue after the two fixture chunks.
        with ctx.db.connect() as conn:
            mapping=[row[0] for row in conn.execute('SELECT id FROM chunks ORDER BY ordinal')]
        recall=np.mean([len(set(mapping[i] for i in e)&set(a))/10 for e,a in zip(expected,actual)])
        started=time.perf_counter();ctx.search.index.snapshot('local');cache_ms=(time.perf_counter()-started)*1000
        assert recall>=0.8,(recall,'HNSW recall below expected threshold')
        return {'vectors':count,'dimensions':dimension,'build_seconds':round(build_seconds,3),
                'mean_ann_search_ms':round(latency,3),'recall_at_10':round(float(recall),3),
                'cached_snapshot_ms':round(cache_ms,3),'builds':ctx.search.index.build_count}

if __name__=='__main__':
    print(json.dumps(benchmark(),indent=2))
