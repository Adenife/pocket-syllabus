# Verification record

Verified locally on 2026-10-13 with Python 3.12 and CPU-only PyTorch.

- Full regression suite: 55 tests passed, including the opt-in cached MiniLM integration test.
- Actual server/background-worker checks: Markdown, PDF, and DOCX uploads indexed and were searchable; PDF citation reported page 1.
- Original downloads: HTTP byte ranges matched uploaded bytes.
- Document replacement: accepted with an incremented version and queued indexing.
- Temporary live-check documents: deleted after verification; sample library retained.
- Browser check: Library and Search render; a photosynthesis query returned cited results.
- Browser excerpt download: saved `.txt` file contained both citation and expected text.
- Dependency check: all 80 installed packages compatible.
- Synthetic FAISS benchmark: 10,000 vectors, 384 dimensions, 50 queries; recall@10 0.92, mean graph retrieval 0.475 ms, initial build 3.245 s, cached snapshot 0.629 ms.

Benchmark figures exclude query embedding and HTTP/UI latency. They are not an assertion of real-corpus relevance.
Docker configuration was structurally checked; Docker was unavailable, so container build/start was not tested.
Encryption covers stored originals, chunk text, vectors, and saved indexes; metadata and transient plaintext are not fully encrypted.
