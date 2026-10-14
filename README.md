# PocketSyllabus

PocketSyllabus is a local-first study library for textbooks, syllabi, and notes.
Upload your materials, let them index in the background, then search by meaning
or keyword and save cited excerpts for offline reading.

The application includes a modular FastAPI backend, a Streamlit interface,
durable SQLite storage, CPU embedding generation, a cached FAISS vector index,
and a synchronization CLI. You can use it on one computer without accounts, or
enable isolated user accounts for a hosted deployment.

## Contents

- [Features](#features)
- [Architecture and project structure](#architecture)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Everyday workflow](#everyday-workflow)
- [Supported documents and chunking](#supported-documents-and-chunking)
- [Indexing and local-folder ingestion](#indexing-and-local-folder-ingestion)
- [Search and scaling](#search-and-scaling)
- [API](#api)
- [Offline operation](#offline-operation)
- [Accounts and security](#accounts-and-security)
- [Synchronization](#synchronization)
- [Backup and restore](#backup-and-restore)
- [Configuration](#configuration)
- [Tests and verification](#tests-and-verification)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Licensing](#licensing)

## Features

- Upload Markdown, UTF-8 text, searchable PDF, and DOCX files.
- Write and edit notes directly in the Library tab.
- Organize documents by subjects, tags, collections, material type, and favorites.
- Filter, sort, preview, replace, reindex, and download documents.
- Save cited bookmarks with annotations; recover documents from Trash.
- Export/import collection archives and review related materials or possible editions.
- Background indexing with persistent jobs and restart recovery.
- Model-token-aware chunking, overlap, heading paths, and page/line citations.
- Bounded embedding batches and incremental per-document replacement.
- Cached exact vector search for small libraries; HNSW for larger libraries.
- Optional hybrid semantic/SQLite full-text retrieval and document filters.
- Account registration, password hashing, expiring/revocable bearer sessions,
  owner isolation, upload quotas, and request rate limits.
- Optional encryption of originals, extracted text, embeddings, and saved indexes.
- Two-way original-file synchronization with resumable transfers, version checks,
  deletion tombstones, and conflict reporting.
- Consistent database/original-file backup and restore tooling.

## Architecture

```text
Library upload / note / ingest.py
             |
   validate and persist original
             |
    durable SQLite job queue
             |
      single indexing worker
             |
  format parser -> token chunker -> embedding batches -> staging rows
             |
   atomic replacement of one document's searchable chunks
             |
 cached FAISS index + optional SQLite full-text search
             |
  FastAPI -> Streamlit -> cited excerpts / original downloads
```

SQLite is the source of truth. Vector index files are disposable snapshots.
Generations invalidate caches after indexing or deletion. Search loads vector
snapshots once, then fetches text only for the winning chunks. Filters and owner
boundaries are applied before vector retrieval, not after ranking.

## Project structure

```text
pocket-syllabus/
├── app.py                         # Streamlit entry point
├── ingest.py                      # Incremental local-folder ingestion
├── sync.py                        # Two-way synchronization CLI
├── backup.py                      # Backup/restore CLI
├── requirements.txt
├── requirements-dev.txt
├── app/
│   ├── main.py                    # App factory, lifespan, health/readiness
│   ├── core/                      # Settings, security, middleware, logging
│   ├── api/v1/endpoints/           # Library, documents, jobs, search, accounts, sync
│   ├── schemas/                   # API validation and serialization
│   ├── ingestion/
│   │   ├── parsers/                # Markdown, TXT, PDF, DOCX
│   │   ├── chunker.py
│   │   └── pipeline.py
│   ├── services/                  # Documents, ingestion, embeddings, search, sync
│   ├── storage/                   # Database, repositories, FAISS snapshots
│   └── workers/indexing_worker.py
├── frontend/                      # Client, library, organization, reading tools, search, settings
├── data/
│   ├── samples/sample_syllabus.md
│   └── uploads/                   # Private runtime files, ignored by Git
├── database/
│   ├── migrations/001_library.sql
│   ├── migrations/002_organization.sql
│   ├── syllabus.db                # Runtime database, ignored by Git
│   └── indexes/                   # Derived snapshots, ignored by Git
├── deployment/                    # Dockerfile and Compose configuration
└── tests/
    ├── unit/
    ├── integration/
    ├── ui/
    ├── fixtures/
    ├── helpers.py
    └── benchmark_search.py
```

User uploads, runtime databases/indexes, environment files, and synchronization
checkpoints are excluded from Git. Sample materials are original mock curriculum
text for testing.

## Installation

Python 3.12 was used for verification. A GPU is not required. Dependencies and
model weights need internet access on first installation.

```bash
cd pocket-syllabus
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.
If Ubuntu/Debian reports missing `ensurepip`, install the matching venv package
(for example `sudo apt install python3.12-venv`) and recreate the environment.

Alternatively, with uv and CPU-only PyTorch:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -r requirements.txt
```

## Quick start

Optionally index the included sample to download/cache the model:

```bash
python ingest.py
```

Start the API:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, activate the same environment and start the interface:

```bash
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open [PocketSyllabus](http://127.0.0.1:8501). In **Library**, upload textbooks or
notes, or write a note. Status progresses from `queued` to `indexing` to `ready`;
the view refreshes every ten seconds. Failed extraction or model loading is
shown with an error. After indexing, search in the **Search** tab.

Select documents to narrow a search, or leave the selection empty for the whole
library. The selector shows the latest 100 documents; the API supports explicit
filters for any accessible document. Each result includes section, filename,
and page or line location when available. Download an excerpt as `.txt`, or
prepare a download of the original from the Library.

Text/Markdown documents have an **Edit note** action. Any document can be
replaced by an updated file. Concurrent replacements are rejected with a version
conflict. A previous successful index stays searchable if a replacement fails.

Move documents to **Trash** to hide them from browsing and search and cancel pending indexing.
Restore them from the Trash tab to queue indexing again. Permanent deletion requires
a confirmation checkbox and removes originals, chunks, bookmarks, and memberships;
a minimal synchronization tombstone remains. Trashed originals still count toward
storage quotas and are included in backups. Stop each server with `Ctrl+C`.

## Organize and read your library

Create **subjects** for fields such as Physics, **tags** for flexible labels such
as Exam revision, and **collections** for courses or reading lists. A document
can belong to several of each. Category names are unique ignoring case within
an owner and category kind. Rename or remove categories from the organization
controls; removing a category keeps its documents.

Edit each document's display title, description, author, publication year,
edition, material type, favorite flag, and category memberships. Material types
include textbook, lecture notes, syllabus, assignment, revision notes, other,
and unspecified. Metadata survives file replacement and reindexing. Metadata
has its own concurrency version, separate from the original-file version.
An explicit `title: null` API update resets the display title to the extracted title.

Filter by category, material/file type, indexing status, or favorites. The library
text filter matches title, filename, and author. Multiple selected categories of
the same kind match any selected value; filters across kinds must all match.
Sort ascending or descending by title, added/updated date, size, status, author,
publication year, or last opened. Browsing is paginated, and semantic search also
supports subject, tag, and collection scopes. Bulk actions can assign/remove
categories, mark favorites, reindex, move to Trash, or restore up to 100 documents.

Preview extracted chunks with available page/line citations, open originals,
and discover semantically related documents. Preview is extracted text rather
than a graphical PDF viewer. Opening records a local reading timestamp. Save
search results as bookmarks, add annotations in **Bookmarks**, and download them
as text. Bookmarks retain their original excerpt and citation after reindexing.
**Insights** shows library statistics and possible editions grouped by normalized
title. These groups are review suggestions; they do not merge files automatically.
Local keyword-based classification suggestions require your review before applying.

Export a collection or selected documents as a ZIP containing originals, metadata,
and bookmarks. Import validates paths, hashes, supported file payloads, and quotas
before uploads, then queues local indexing. Archives contain at most 100 documents
and 200 MiB of expanded original content; ordinary per-file upload limits also apply.
Empty collections are supported. Identical originals are reused and imported
organization is merged. Embeddings are rebuilt rather than exported. A disk failure
can leave successfully imported documents in place; retrying deduplicates them.
Archives contain readable originals and annotations, even with storage encryption
enabled, so keep them private.

Library APIs live under `/api/v1/library`:

| Route | Purpose |
| --- | --- |
| `GET /documents` | Paginated filters and sorting; returns items, total, offset, limit |
| `GET /catalog`, `POST /categories`, `PATCH/DELETE /categories/{id}` | Manage subjects, tags, collections |
| `PATCH /documents/{id}` | Metadata update with required expected_metadata_version |
| `POST /bulk` | Apply an action to selected documents |
| `POST /documents/{id}/trash`, `/restore`, `/opened` | Recovery and reading history |
| `GET /documents/{id}/preview`, `/suggestions`, `/related` | Reading and discovery |
| `GET/POST /bookmarks`, `PATCH/DELETE /bookmarks/{id}` | Saved excerpts and annotations |
| `GET /statistics`, `/duplicates` | Library overview and edition review |
| `POST /export`, `/import` | Portable collection archives |

The existing `/api/v1/documents` list contract is preserved. Its DELETE endpoint
permanently purges a document; use the library trash endpoint for recoverable removal.
See `/docs` for complete request schemas.

## Everyday workflow

1. Open **Library** and select one or more textbooks or notes, then click
   **Upload and index**. The displayed per-file limit comes from the backend.
2. Watch the document status. While indexing, its details show the current stage
   and the number of chunks processed. Wait for `ready` before searching a new file.
3. Open **Search**, enter a question, and optionally select documents. Keyword
   matches are enabled by default; turn them off for semantic-only retrieval.
4. Read the source citation and download useful excerpts for offline reading.
5. To update materials, expand a Library entry and replace its file. For text
   or Markdown, use **Edit note**, edit the content, and click **Save changes**.
6. If indexing fails, read the error, correct the problem, and use **Reindex**.
   An earlier successful version remains searchable; it may differ from the
   currently uploaded original until the new version finishes indexing.

For a new note, expand **Write a note**, enter a title and content, then choose
**Save and index note**. Notes support Markdown headings, lists, and code blocks.
Identical uploads are detected within the same owner's library and return the
existing document rather than another indexing job.

The sample syllabus is optional demonstration content. Your own materials are
stored separately in `data/uploads/`; you do not need to edit or replace the sample.

## Supported documents and chunking

| Format | Extraction and citations |
| --- | --- |
| `.md` | CommonMark parser, heading paths, original line locations, fenced code |
| `.txt` | UTF-8 paragraphs with starting line numbers |
| `.pdf` | Extractable text per page and one-based page numbers |
| `.docx` | Paragraphs, heading paths, and table rows; no rendered page numbers |

Scanned PDFs need OCR before uploading. Password-protected PDFs are rejected.
The pipeline reports pages with no extracted text. PDF layout, equations, and
complex tables may extract imperfectly; inspect important source passages.

Chunks respect the embedding model's token window, including special tokens.
The default requested budget is 220 content tokens, with up to 32 overlapping
tokens; the effective budget is capped by the model. Long blocks prefer sentence
boundaries where possible. Code whitespace is retained. Overlap stays within a
block rather than joining unrelated headings or pages. Line citations identify
the starting source block and may repeat across windows from that block.

The default file limit is 50 MiB, library quota 1 GiB, and document limit 1,000 per
owner. These include original sizes, not total database or model-cache disk use.

## Indexing and local-folder ingestion

```bash
python ingest.py --data-dir ./data/samples
python ingest.py --data-dir /path/to/study-materials --db-path ./database/syllabus.db
```

Files are indexed recursively, one document at a time. Unchanged content is
skipped using SHA-256 hashes. Only documents managed by the same CLI input root
are pruned when files disappear; uploads through the API are preserved.

Originals use generated filenames. Embeddings are generated in batches and
written to `staged_chunks`; only a completed job replaces active chunks in one
SQLite transaction. Malformed data, model failure, or cancellation leaves a
previous index intact. Recovery resets interrupted jobs and discards partial
staging rows before retrying. After three interrupted attempts, the job is marked
failed for manual inspection and reindexing.

The API runs one background worker by default. A process lock prevents a second
worker from claiming the same library. To run a standalone worker instead:

```bash
export POCKET_WORKER_ENABLED=0
uvicorn app.main:app --host 127.0.0.1 --port 8000
# In another terminal with the same storage settings:
python -m app.workers.indexing_worker
```

Do not start several API workers for this configuration; rate limits and index
caches are process-local. Embedding batches are bounded, but individual files
are capped and may be held in memory during upload or parsing. PDF processing is
page-based; DOCX expanded size is capped at 100 MiB. Vector indexes themselves
still require memory proportional to the library.

Older project databases are migrated automatically to document records without
losing searchable chunks. Legacy entries lack uploaded originals until the
sample is reingested or a new original is uploaded. Back up existing data before
upgrading. The legacy SQLite migration is not an encryption conversion tool.

## Search and scaling

Libraries below `POCKET_ANN_THRESHOLD` use a cached exact FAISS inner-product
index with normalized vectors. Larger libraries use an HNSW graph index.
Snapshots are saved and reused across restarts, and invalidated by generation
changes. At most eight library/filter snapshots are retained in memory and 32
snapshots on disk. Old snapshots are rebuildable from SQLite.

Hybrid retrieval combines semantic and full-text ranks using reciprocal rank
fusion. `score` remains cosine similarity; hybrid results are ordered by fused
rank rather than cosine score alone. Similarity is not a confidence probability.
There is no relevance cutoff, so unrelated queries can return excerpts.

Full-text retrieval is disabled in encrypted libraries to avoid a plaintext
copy of protected text. Search still uses semantic vectors. Changing embedding
models requires reindexing existing documents; model identifiers are checked
before search.

A repeatable synthetic benchmark is included:

```bash
python tests/benchmark_search.py
```

On the development machine, 10,000 normalized 384-dimensional vectors produced
92% recall@10 and approximately 0.48 ms mean graph search time, with a 3.25-second
index build. This measures vector retrieval, not total query embedding/network
latency or real-corpus relevance. Hardware and library composition affect results.

Implementation references: [FAISS index documentation](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes),
[PDF text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
and [SentenceTransformer model API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

## API

Swagger UI is at `/docs`, OpenAPI JSON at `/openapi.json`. `/` checks HTTP health;
`/ready` checks database availability without loading the model. Default Swagger
assets use an external CDN and may be unavailable offline.

All library/job/sync operations are scoped to the authenticated owner in account
mode. Local mode uses the single `local` library.

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/documents` | Multipart upload (`file`), returns document and job ID |
| `GET /api/v1/documents` | List (`offset`, `limit` up to 100) |
| `GET /api/v1/documents/{id}` | Metadata, status, warnings, chunk count |
| `POST /api/v1/documents/{id}/reindex` | Queue reindexing |
| `GET /api/v1/documents/{id}/original` | Download; byte ranges and ETag supported |
| `DELETE /api/v1/documents/{id}` | Delete, optional `expected_version` guard |
| `GET /api/v1/jobs/{id}` | Stage, progress, chunk count, errors |
| `POST /api/v1/search` | Semantic/hybrid retrieval |
| `GET /api/v1/auth/mode` | Account-mode availability |
| `POST /api/v1/auth/register` | Create an account when registration is enabled |
| `POST /api/v1/auth/login` | Issue a bearer session |
| `POST /api/v1/auth/logout` | Revoke the current session |
| `GET /api/v1/sync/changes` | Owner-scoped changes after a sequence cursor |
| `POST /api/v1/sync/uploads` | Create a resumable upload (`filename`, `total`) |
| `GET /api/v1/sync/uploads/{id}` | Recover acknowledged byte offset |
| `PATCH /api/v1/sync/uploads/{id}?offset=N` | Append up to 1 MiB of raw bytes |
| `POST /api/v1/sync/uploads/{id}/complete` | Finalize and queue indexing |
| `DELETE /api/v1/sync/uploads/{id}` | Cancel a partial upload |

Replace a document using `POST /documents?document_id=ID&expected_version=N`.
Use the current version from its metadata. Stable UUIDs can be imported with
`expected_version=0`. Deleted IDs cannot be resurrected; upload with a new ID.

```bash
curl -F 'file=@notes.md' http://127.0.0.1:8000/api/v1/documents
curl -X POST http://127.0.0.1:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"How do plants use sunlight?","limit":3,"hybrid":true,"document_ids":[]}'
```

Search accepts nonblank queries up to 2,000 characters, limits 1–50 (default 3),
and up to 100 document IDs. Results include `id`, `document_id`, `filename`,
`source_title`, `section`, `page`, `line`, `text_excerpt`, and `score`.

Common errors: `400` invalid file/input, `401` unauthenticated, `404` inaccessible
resource, `409` version/offset conflict, `413` size/quota exceeded, `415` unsupported
format, `422` validation failure, `429` rate limit, `503` unavailable search model
or incompatible index. Jobs report parser/model failures in their status.

## Offline operation

After installing dependencies and successfully indexing once online:

```bash
export POCKET_SYLLABUS_OFFLINE=1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Set the same flag before offline CLI ingestion. Keep the model cache accessible
to the user running the process. The frontend needs the local API; saved text
excerpts can be read independently. Synchronization requires connectivity to the
other server, but local indexing/search continues independently.

## Accounts and security

For hosted accounts, use a separate library database and enable authentication:

```bash
export POCKET_AUTH_ENABLED=1
export POCKET_DB_PATH=/path/to/hosted/syllabus.db
export POCKET_UPLOAD_DIR=/path/to/hosted/uploads
export POCKET_INDEX_DIR=/path/to/hosted/indexes
```

Users can register/sign in from the frontend. Usernames contain letters, digits,
underscores, periods, or hyphens; passwords must be 10–128 characters. Passwords
use salted scrypt hashes. Bearer tokens are stored as hashes, expire after seven
days, and can be revoked by sign-out. Set `POCKET_REGISTRATION_ENABLED=0` after
creating permitted accounts if open registration is undesirable.

Never expose local unauthenticated mode to the internet. Put hosted services
behind a TLS reverse proxy with upload limits and shared rate controls when
scaling beyond one process. The built-in limiter allows 120 requests/minute per
IP by default and 10/minute for registration/login. Reverse-proxy forwarded-header
trust must be configured for your actual proxy rather than arbitrary clients.

Usernames/document metadata are local database records; account recovery,
password reset, email verification, administrator roles, and MFA are not included.

### Optional storage encryption

Generate and securely retain a Fernet key, then set it **before creating a new
library**:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
export POCKET_ENCRYPTION_KEY='your-generated-key'
```

Originals, chunk text, embeddings, resumable server upload segments, and persisted
FAISS snapshots are encrypted. Database metadata such as titles, sections,
filenames, hashes, ownership, and timestamps remains readable. Decrypted data
exists in process memory and transient parser scratch files; full-disk encryption
is still appropriate for protecting temporary files, swap, and metadata. Interrupted
worker scratch directories are removed when the worker recovers.

The library rejects a different or absent key on restart. Losing the key loses
access to encrypted content. Keys are not included in backups. Existing plaintext
libraries need a new encrypted library and document reuploads; toggling the flag
cannot retroactively encrypt them. Deletion is logical/storage cleanup, not a
guarantee of forensic erasure from backups or storage media.

## Synchronization

Run both servers and synchronize from the client machine:

```bash
export POCKET_REMOTE_TOKEN='token-from-remote-login'
# Set POCKET_LOCAL_TOKEN too if the local API requires accounts.
python sync.py --remote-url https://your-server.example/api/v1
```

Use `--local-url` for a nondefault local backend and `--state-file` for a custom
checkpoint location. Non-loopback remote URLs require HTTPS; tokens are read
from environment variables and are never written into checkpoints.

The client exchanges metadata and original files, not embeddings or model
weights. Destination indexing happens locally in the background. Downloads use
byte-range resume and SHA-256 verification; uploads resume from server-acknowledged
offsets. Server upload sessions expire after 24 hours and each owner may have
three unfinished sessions. Rerun the same command after interruption.

The client compares current content/deletion signatures with its last successful
checkpoint. One-sided changes propagate; different edits on both sides are
reported and preserved, with exit code 2. Resolve a conflict by intentionally
making both originals agree, or keep both as separate document IDs. Version
guards reject races detected during transfer. Pending replacements on a target
must finish indexing before another replacement can be accepted.

Synchronization exit codes are `0` for success, `1` for a transfer/configuration
failure, and `2` for preserved conflicts. Use the same checkpoint file when retrying
and a separate file for each pair of peers. Redirects are rejected: supply the
final HTTPS API URL directly.

Synchronization also transfers custom metadata, favorites, category memberships,
bookmarks/annotations, empty collections and category descriptions, and recoverable
Trash state. Metadata-only changes skip original-file transfers. Concurrent
organization edits are preserved as conflicts, including unsafe category removal.
Reading timestamps remain local.

Checkpoints cache manifests and consume changes incrementally after their saved
cursors. Peer library/account identity and rolled-back event sequences are checked.
Use a new state file when upgrading an older checkpoint to format 2. Checkpoints
and partial downloads contain sensitive metadata, excerpts, and content; protect
the client directory. Event history is not compacted.

## Backup and restore

```bash
python backup.py create /path/to/backups/library.zip
python backup.py restore /path/to/backups/library.zip /path/to/restored-library
```

Backups take a consistent SQLite snapshot and copy referenced originals and
acknowledged partial uploads under a shared file-operation lock. Index snapshots
and model caches are omitted and can be regenerated. Restore requires an empty
destination; afterward set `POCKET_DB_PATH` to its `syllabus.db`,
`POCKET_UPLOAD_DIR` to its `uploads`, and `POCKET_INDEX_DIR` to a new index directory.
Use the same encryption key when applicable. Restore only trusted backup archives.

## Configuration

| Environment variable | Default |
| --- | --- |
| `POCKET_DB_PATH` | `database/syllabus.db` |
| `POCKET_UPLOAD_DIR` | `data/uploads` |
| `POCKET_INDEX_DIR` | `database/indexes` |
| `POCKET_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` |
| `POCKET_SYLLABUS_OFFLINE` | `0` |
| `POCKET_AUTH_ENABLED` | `0` |
| `POCKET_REGISTRATION_ENABLED` | `1` |
| `POCKET_WORKER_ENABLED` | `1` |
| `POCKET_ENCRYPTION_KEY` | Empty; encryption disabled |
| `POCKET_MAX_UPLOAD_BYTES` | `52428800` |
| `POCKET_MAX_LIBRARY_BYTES` | `1073741824` |
| `POCKET_MAX_DOCUMENTS` | `1000` |
| `POCKET_BATCH_SIZE` | `32` |
| `POCKET_EMBEDDING_THREADS` | `2` CPU threads |
| `POCKET_CHUNK_TOKENS` | `220` |
| `POCKET_OVERLAP_TOKENS` | `32` |
| `POCKET_ANN_THRESHOLD` | `5000` |
| `POCKET_RATE_LIMIT` | `120` requests/minute |
| `POCKET_API_URL` | Frontend: `http://127.0.0.1:8000/api/v1` |

Restart processes after changing settings. Boolean settings accept `1`, `true`,
or `yes` to enable. Relative path overrides are resolved from the process working
directory; default paths are project-relative.

## Tests and verification

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Normal tests use deterministic embeddings and temporary databases. They exercise
format extraction, token boundaries, citations, batch staging, replacement failures,
cache persistence/invalidation, HNSW, encrypted storage, migration, account
isolation, HTTP uploads/downloads, resumable transfers, synchronization conflicts,
backup/restore, and Streamlit notes/search/download controls.

For the cached real model:

```bash
POCKET_REAL_MODEL_TESTS=1 HF_HUB_OFFLINE=1 python -m unittest discover -s tests -v
```

The normal suite skips that integration check so model downloads are never required.
The verified suite contains **89 tests**: 31 unit tests, 47 integration tests,
and 11 UI tests. A normal run passes 88 and skips the cached-model check; enabling
`POCKET_REAL_MODEL_TESTS=1` runs all 89. The latest full verification passed all
89, including library organization, archives, bookmark persistence, trash recovery,
metadata/category synchronization, worker cancellation races, and long input split with the actual model tokenizer.

Earlier live verification also exercised Markdown, PDF, and DOCX uploads, background
indexing, filtered searches, PDF page citations, byte-range original downloads,
and versioned replacements. A browser-downloaded excerpt was checked for both
its citation and text. These manual checks supplement the automated suite.

See [tests/README.md](tests/README.md) for focused commands and
[the verification record](tests/verification.md) for measured results and coverage
boundaries. The benchmark is separate from unit tests.

## Deployment

```bash
docker compose -f deployment/compose.yaml up --build
```

The containers run as an unprivileged user, bind published ports to localhost,
use persistent library/model volumes, enable account mode, and check readiness.
A TLS reverse proxy is required for external hosted access. The frontend container
uses the internal API address. To preserve offline startup, populate the model
cache while online before setting offline mode.

Container configuration is provided, but Docker was unavailable in the development
environment, so container build/start was not executed there. Dependencies currently
use version ranges/unpinned packages; pin a tested deployment environment before
reproducing it elsewhere.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Upload remains queued | Ensure the embedded or standalone indexing worker is running |
| Indexing fails on a scanned PDF | Run OCR externally, then upload a searchable PDF |
| Model unavailable offline | Cache the configured model online and retry/reindex |
| Old excerpts after replacement failure | Fix the file/model problem and reindex; the previous index is preserved |
| Version conflict | Refresh document metadata and review concurrent changes |
| Sync offset conflict | Query the upload session and resume at its acknowledged offset |
| Encryption key mismatch | Restore the original key or use the correct library paths |
| API connection failure | Check port 8000 and `POCKET_API_URL` |
| Request limit exceeded | Wait for the window to reset or configure appropriate deployment limits |
| Index model mismatch | Reindex all affected documents with the configured model |

## Licensing

No software license has been selected. Add one before distributing the repository
as licensed open-source software. Preserve attribution, source links, and licenses
for imported OER materials; PocketSyllabus does not validate their permissions.
