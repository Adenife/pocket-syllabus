# Running the tests

From the project root, activate `.venv` and run:

```bash
python -m unittest discover -s tests -v
```

For a fresh environment, first install `requirements-dev.txt` (it includes the
application dependencies and HTTPX for in-process API requests).

The suite covers markdown chunk boundaries and citations, input validation,
SQLite ingestion and reindexing, preserving the index on embedding failure,
cosine ranking, malformed vectors, API success/error responses, and Streamlit
search, citations, download controls, persistence across reruns, and errors.

Tests use temporary databases, deterministic embeddings, in-process HTTP
requests, and mocked frontend HTTP responses. They do not download models,
contact external services, or modify `database/syllabus.db`. Actual embedding
model quality and browser download contents are outside this suite's scope.
