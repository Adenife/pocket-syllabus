# PocketSyllabus

PocketSyllabus is a low-bandwidth, offline-first discovery engine for locally
stored Open Educational Resource (OER) study materials. It turns Markdown
syllabi and textbook excerpts into a searchable SQLite index, retrieves relevant
paragraphs using semantic embeddings, and lets readers save cited excerpts as
plain-text files.

The application has three parts: a standalone ingestion CLI, a modular FastAPI
backend, and a Streamlit frontend. Once dependencies and the embedding model
are cached, ingestion and search can operate without internet access.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Adding study materials](#adding-study-materials)
- [Ingestion and database](#ingestion-and-database)
- [API reference](#api-reference)
- [Offline operation](#offline-operation)
- [Configuration](#configuration)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Limitations and development](#limitations-and-development)
- [Licensing](#licensing)

## Features

- Semantic search using `sentence-transformers/all-MiniLM-L6-v2`.
- Local Markdown ingestion with paragraph chunking and heading citations.
- SQLite persistence with NumPy `float32` embedding blobs.
- Cosine similarity ranking with configurable result limits.
- Versioned HTTP search endpoint with Pydantic validation.
- Streamlit search interface with source titles, sections, and similarity scores.
- Individual `.txt` excerpt downloads for offline reading.
- Offline regression tests that avoid downloading the embedding model.

## Architecture

```text
Markdown files in data/
        |
        v
  ingest.py --> embedding model --> database/syllabus.db
                                         |
Browser --> Streamlit --> FastAPI --> SearchService
                                         |
                            embed query, compare chunks,
                            rank by cosine similarity
```

The frontend sends requests only to the local backend. Search embeds the query,
reads the stored chunks, computes cosine similarity, and returns the highest
scoring excerpts. No generative model or remote search service is involved.

The model is loaded lazily and cached in the backend process. The health endpoint
works without loading it. SQLite connections are opened per operation, and search
uses read-only connections. An application lock serializes embedding generation
within each process.

## Project structure

```text
pocket-syllabus/
├── .gitignore
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── ingest.py
├── app.py                         # Streamlit client
├── data/
│   └── sample_syllabus.md
├── database/
│   └── syllabus.db
├── app/                           # FastAPI package
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           └── search.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── resource.py
│   └── services/
│       ├── __init__.py
│       └── search_service.py
└── tests/
    ├── README.md
    ├── test_project.py
    └── test_frontend.py
```

`.venv/` and Python cache files are ignored by Git. The supplied SQLite file is
an empty starter database; run ingestion to create its schema and populate it.

## Requirements

- Python 3.12 is the version used for local verification.
- A Python virtual environment and a package installer such as pip or uv.
- Internet access for the initial dependency installation and model download.
- Disk space for PyTorch, other dependencies, the model cache, and the index.
- A web browser for the Streamlit interface.

A GPU is not required. SQLite is included with Python. Application dependencies
are FastAPI, Uvicorn, Streamlit, Sentence Transformers, NumPy, Pydantic, and
Requests. HTTPX is included in the development requirements for API tests.

## Installation

Run commands from the project root:

```bash
cd pocket-syllabus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

If Debian or Ubuntu reports that `ensurepip` is unavailable, install the virtual
environment package matching your Python version, for example:

```bash
sudo apt install python3.12-venv
```

Then rerun the environment creation command.

If using uv, an alternative installation is:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

For CPU-only PyTorch with uv, install it first from the CPU package index:

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -r requirements.txt
```

The existing local environment was installed with CPU-only PyTorch. A default
installation on another machine may select a different PyTorch distribution.

## Quick start

### 1. Build the local index

With the virtual environment active:

```bash
python ingest.py
```

The first run downloads and caches the embedding model. The included original
sample material covers introductory physics and biology and produces 13 chunks
with the current chunking rules.

### 2. Start the backend

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this terminal running. Visit `http://127.0.0.1:8000/` to check backend health,
or `http://127.0.0.1:8000/docs` to try the interactive API documentation.

### 3. Start the frontend

In a second terminal, enter the project directory and activate the environment:

```bash
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1
```

Open the local address printed by Streamlit, normally `http://127.0.0.1:8501`.
Search for a topic such as “How does photosynthesis work?” or “Newton's laws”.
Choose between 1 and 10 results in the interface.

Each result includes its source title, section, excerpt, and similarity score.
Select **Save Excerpt for Offline Reading (.txt)** to download the excerpt and
its citation. Results remain visible across frontend reruns within the session.

Stop each server with `Ctrl+C` in its terminal.

## Adding study materials

Place UTF-8 `.md` files in `data/`; nested directories are supported. Use a
level-one heading for the source title and smaller headings for sections:

```markdown
# Introductory Biology

## Cell Structure

Cells are the basic units of life. Their membranes regulate transport.

## Photosynthesis

Plants use light energy to synthesize sugars from carbon dioxide and water.
```

Separate paragraphs with blank lines, then rebuild the index:

```bash
python ingest.py
```

If a document has no level-one heading, its filename stem supplies the title.
Text before a heading uses the section `Introduction`. Each encountered heading
sets the current section; citations retain that heading rather than a complete
hierarchical heading path.

Only local Markdown is supported. The application does not crawl websites,
extract PDFs, discover licenses, or download resources automatically. Keep
source URLs, author attribution, and license information in your materials where
appropriate; the application does not have dedicated metadata fields for them.

## Ingestion and database

The CLI reads `.md` files recursively, combines lines into paragraphs, and splits
paragraphs longer than 180 whitespace-separated words into consecutive chunks.
It encodes all chunks and stores the results in SQLite.

```bash
python ingest.py --help
python ingest.py --data-dir ./data --db-path ./database/syllabus.db
```

| Column in `chunks` | Purpose |
| --- | --- |
| `id` | Integer primary key |
| `source_path` | Markdown path relative to the input directory |
| `source_title` | Document title |
| `section` | Current heading or `Introduction` |
| `text` | Chunk text |
| `embedding` | NumPy `float32` vector stored as a BLOB |

Ingestion rebuilds the entire chunk collection; it is not incremental. Removed
materials disappear after a successful rebuild, and repeated ingestion does not
accumulate duplicate rows. Chunk IDs can change after rebuilding and should not
be treated as permanent source identifiers.

Embeddings are generated and checked before existing rows are replaced. Model
failures and invalid embedding arrays leave an existing index intact. The
replacement inserts are committed together in a SQLite transaction.

A custom `--db-path` affects ingestion only. To search that database, also update
`DB_PATH` in `app/core/config.py` and restart the backend.

## API reference

### `GET /`

Returns backend health:

```json
{"status": "ok", "app": "PocketSyllabus"}
```

This confirms that the server responds; it does not verify model or index readiness.

### `POST /api/v1/search`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "How does photosynthesis work?", "limit": 3}'
```

| Request field | Rules |
| --- | --- |
| `query` | Required string; 1–2000 characters; whitespace trimmed; blank input rejected |
| `limit` | Integer from 1 to 50; defaults to 3 |

Illustrative response; actual IDs and scores depend on the index and model:

```json
{
  "query": "How does photosynthesis work?",
  "results": [
    {
      "id": 9,
      "source_title": "Fundamentals of Physics and Biology",
      "section": "Photosynthesis and Cellular Respiration",
      "text_excerpt": "Photosynthesis uses light energy to convert carbon dioxide and water into sugars, releasing oxygen.",
      "score": 0.72
    }
  ]
}
```

Results are sorted by descending cosine similarity, with ascending chunk ID as
the tie breaker. Scores lie between -1 and 1 and represent embedding similarity,
not probabilities or confidence estimates. There is no minimum relevance
threshold, so unrelated queries can still return results. The returned excerpt
is the stored chunk, not an AI-generated summary.

| Status | Meaning |
| --- | --- |
| `200` | Search completed; an empty initialized index returns `results: []` |
| `422` | Request validation failed |
| `503` | Missing/unusable index, unavailable model, or invalid/incompatible vectors |

Errors include a `detail` field. OpenAPI is available at `/openapi.json`, Swagger
UI at `/docs`, and ReDoc at `/redoc`.

## Offline operation

Complete dependency installation and at least one successful ingestion while
online. Keep the downloaded model cache available to the same user account.
Before starting the backend or running ingestion offline, set:

```bash
export POCKET_SYLLABUS_OFFLINE=1
python ingest.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Windows PowerShell:

```powershell
$env:POCKET_SYLLABUS_OFFLINE = "1"
```

This flag tells the embedding loader to use cached model files only. Restart the
backend after changing it because configuration is read when modules are imported.
The frontend still needs the local backend running. Downloaded `.txt` excerpts
can be opened independently without either server.

Default FastAPI `/docs` and `/redoc` pages load browser assets from external
CDNs; they may not render fully without internet. The local JSON API remains
usable. Copying only the SQLite database to another machine is insufficient for
search: that machine also needs the dependencies and the cached embedding model.

## Configuration

Paths are defined in `app/core/config.py` relative to the project root, so they
do not depend on the backend process's working directory.

| Setting | Default | How to change |
| --- | --- | --- |
| `DATA_DIR` | `<project>/data` | Edit config, or use ingestion `--data-dir` |
| `DB_PATH` | `<project>/database/syllabus.db` | Edit config; ingestion also supports `--db-path` |
| `MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Edit config and rebuild the index |
| `OFFLINE_MODE` | Disabled | Set `POCKET_SYLLABUS_OFFLINE=1`, `true`, or `yes` |
| Frontend `API_URL` | `http://127.0.0.1:8000/api/v1/search` | Edit `app.py` |

If you change embedding models, always rebuild the index. Matching vector sizes
alone do not guarantee embeddings from different models are compatible.

## Tests

Install development dependencies if they are not already present:

```bash
python -m pip install -r requirements-dev.txt
# Alternatively: uv pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The current suite contains 26 tests covering:

- Markdown headings, citations, and long-paragraph boundaries.
- Query normalization and invalid request rejection.
- Float32 vector persistence and nested source paths.
- Reindexing without duplicates and preservation on embedding failure.
- Cosine ranking, result limits, ties, and zero/corrupt vectors.
- API health, response serialization, validation, and service errors.
- Streamlit search, citations, download controls, retained results, and errors.

Tests use temporary databases, deterministic embeddings, in-process API requests,
and mocked frontend HTTP responses. They do not contact external services,
download model weights, or modify the project database. Model quality and the
contents of actual browser downloads are outside the automated suite's scope.
See [tests/README.md](tests/README.md) for additional details.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `ensurepip` unavailable during environment creation | Install the matching Python venv package, or create the environment with uv |
| `ModuleNotFoundError` | Activate `.venv` and install the appropriate requirements file |
| No Markdown files or no indexable paragraphs | Check the input path, `.md` extension, and that files contain text beyond headings |
| Index missing/unavailable or search returns `503` | Run `python ingest.py` and check the configured database path |
| Model unavailable in offline mode | Temporarily disable offline mode and run ingestion online to populate the cache |
| Invalid or incompatible vectors | Rebuild the database using the backend's configured embedding model |
| Frontend cannot reach the API | Start Uvicorn on port 8000 and check `API_URL` in `app.py` |
| Port already in use | Stop the conflicting process, or choose another port and update the frontend URL |
| Slow first request | Model loading happens on the first nonempty search in each backend process |
| Unexpectedly unrelated results | Add better source materials or refine the query; search has no relevance cutoff |

The frontend uses a 120-second request timeout. On a slow first download or model
load, the client may time out; complete ingestion first and retry after the backend
is ready. Updating Markdown files alone does not update the index.

## Limitations and development

This implementation targets small, local collections. Every search reads all
stored chunks and compares their vectors in Python; there is no approximate
nearest-neighbor index or database-level vector search. Ingestion also holds
all chunks and embeddings in memory. Large collections will need batching,
index caching, or a dedicated vector index.

The 180-word chunk limit is a word-based heuristic, not a model token budget;
some text can exceed the embedding model's input window. Chunking is basic and
does not implement a full Markdown parser, special code-block handling, or overlap.

There is no authentication, user account system, rate limiting, deployment
configuration, or cross-device synchronization. The commands above bind the
backend and frontend to localhost for local use. The application stores local
materials and embeddings on disk without application-level encryption.

For backend development:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Add transport handlers under `app/api/v1/endpoints/`, request/response models
under `app/schemas/`, and business logic under `app/services/`. Register new
routers in `app/api/v1/__init__.py`. Keep tests independent of model downloads
and use temporary storage for database tests.

Dependencies are currently not pinned to a reproducible lockfile. Record tested
versions or introduce a lockfile when preparing a repeatable deployment.

## Licensing

No software license file has been added to this repository. Choose and add an
appropriate license before distributing the project as licensed open-source
software. The sample syllabus is original mock educational text for testing;
it does not claim to reproduce a textbook or accredited curriculum.

When adding OER materials, retain their attribution and license notices and
verify that their terms permit your intended use. PocketSyllabus does not enforce
or validate content licensing.
