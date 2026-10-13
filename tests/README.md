# PocketSyllabus tests

The suite uses Python's built-in `unittest` runner. Run commands from the project
root, not from inside this directory.

## Setup

Activate the project environment and install the development requirements:

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

If the environment was created with uv and has no pip:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.
Development requirements include application dependencies and HTTPX for
in-process API requests. A model download is not needed for the normal suite.

## Run the suite

```bash
python -m unittest discover -s tests -v
```

There are **55 tests**. The standard run passes 54 and skips one cached-model
integration test. Tests create temporary databases, uploads, vector indexes,
backups, and sync checkpoints; they do not modify the user's library.

Embedding and tokenizer doubles make the normal suite deterministic and offline.
API requests use in-process transports; frontend HTTP requests are mocked.
Streamlit and FastAPI tests need a runtime that permits worker threads. In
restricted execution environments, a stalled in-process HTTP test may require
running the suite outside that sandbox.

## Coverage and layout

| Directory/file | Coverage |
| --- | --- |
| `unit/test_project.py` | Validation, chunk budgets and overlap, Markdown structure, document storage, deduplication, replacement failures, quotas, deletion, index caching, HNSW, encryption, ownership, recovery |
| `unit/test_parsers.py` | TXT line locations, PDF page citations, scanned-PDF errors, DOCX headings and tables |
| `integration/test_api.py` | Upload-to-search flow, jobs, downloads, versions, resumable uploads, body limits, accounts, expired tokens, logout, rate limiting |
| `integration/test_operations.py` | SQLite migration, incremental CLI ingestion, upload preservation, backup/restore, archive path rejection |
| `integration/test_sync.py` | Two-way transfer, no-op repeat runs, edit conflicts, deletion propagation, session recovery, owner isolation, URL validation |
| `integration/test_transfer.py` | Actual sync HTTP client against two isolated APIs: resumed uploads/downloads, replacement, and deletion |
| `integration/test_real_model.py` | Opt-in MiniLM semantic retrieval and actual token budgets on long input |
| `ui/test_frontend.py` | Library controls, note creation/editing, deletion confirmation, sign-in, search, citations, excerpt controls, retained results, connection errors |
| `helpers.py` | Isolated contexts and deterministic tokenizer/embedding doubles |
| `fixtures/` | Small reusable sample study material |
| `benchmark_search.py` | Separate synthetic FAISS recall/latency benchmark |

The suite has 27 unit tests, 21 integration tests, and 7 UI tests.

## Run a focused group

Discovery recursively finds tests in the package directories:

```bash
python -m unittest discover -s tests -p 'test_api.py' -v
python -m unittest discover -s tests -p 'test_parsers.py' -v
python -m unittest discover -s tests -p 'test_frontend.py' -v
python -m unittest discover -s tests -p 'test_sync.py' -v
```

Using the `tests` discovery root keeps shared helpers importable.

## Verify the real embedding model

First cache the configured model by successfully running `python ingest.py`
with internet access. Then run:

```bash
POCKET_REAL_MODEL_TESTS=1 HF_HUB_OFFLINE=1 python -m unittest discover -s tests -v
```

Or run only the model check:

```bash
POCKET_REAL_MODEL_TESTS=1 HF_HUB_OFFLINE=1 python -m unittest discover -s tests -p 'test_real_model.py' -v
```

On Windows PowerShell, set `$env:POCKET_REAL_MODEL_TESTS = "1"` and
`$env:HF_HUB_OFFLINE = "1"` before running the command without shell prefixes.
The opt-in check uses the locally cached MiniLM model and CPU inference. A missing
cache causes failure rather than downloading weights. Model loading and available
memory affect execution time; a slow first run is not an ANN benchmark.

## Retrieval benchmark

```bash
python tests/benchmark_search.py
```

The benchmark uses a fixed random seed, 10,000 normalized 384-dimensional vectors,
and 50 queries. It compares HNSW top-10 results against exact search and asserts
recall@10 is at least 0.8. It reports build time, mean vector-query latency,
cached snapshot latency, and number of index builds.

Recorded locally: recall@10 **0.92**, mean graph query **0.475 ms**, initial build
**3.245 seconds**, and cached snapshot **0.629 ms**. These figures exclude query
embedding, HTTP overhead, and UI rendering. Synthetic recall is not a measure of
real educational-content relevance, and timings vary by machine.

## Verification boundaries

All 55 tests passed in the latest full verification. See
[verification.md](verification.md) for live-server and browser checks, including
an actual excerpt download whose text and citation were inspected.

Docker configuration was checked structurally, but Docker was unavailable for
container build/start. Automated UI tests inspect download controls rather than
browser-saved file bytes. The suite does not test OCR, external TLS infrastructure,
multiple physical devices, forensic erasure, or educational accuracy of arbitrary
uploaded materials.

## Adding tests

Use temporary storage through `helpers.context()` and keep the normal suite
independent of model downloads and external services. Exercise observable
behavior: ownership, returned citations, persistence, conflict handling, and
recovery. Add new format fixtures without copying private study materials into Git.
Model-dependent checks should remain explicitly opt-in.
