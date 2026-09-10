# Phase 1 Plan — Knowledge-Base Foundation

Status: Milestone 0 complete (inspection + plan). No implementation code written yet.

---

## 1. Repository Inspection

The repository was **empty at the time of inspection**:

- Working tree contained only `.git/` — zero tracked files, zero untracked files.
- Branch `main` exists but is **unborn** (no commits yet).
- Remote `origin` is configured: `https://github.com/Eknoor-S-Sandhu/Debate_Case_Engine.git`.
- **No** `pyproject.toml`, `requirements.txt`, `setup.py`, `.gitignore`, or virtualenv.
- **No existing dependencies**, and therefore **no dependency conflicts**.

There is nothing in the repository that conflicts with the planned architecture. Phase 1
starts from a clean slate.

### Local environment findings

| Item | Finding | Consequence |
| --- | --- | --- |
| Project interpreter | **Python 3.13.13** (miniforge) at `/Users/eknoorsandhu/miniforge3/bin/python3.13` | Confirmed target. Create the venv from this explicit path. |
| Bare `python3` on `PATH` | 3.9.6 (Apple Command Line Tools) | `/usr/bin` precedes miniforge on `PATH`, so `python3` still resolves to 3.9.6. Never invoke the project through a bare `python3`. |
| Architecture | arm64 (Apple Silicon) | PyTorch installs CPU/MPS wheels; fine. |
| SQLite (via Python) | 3.53.1 | Modern. `FTS5` + `JSON1` available for hybrid keyword search. |
| LibreOffice / `antiword` | Not installed | Legacy `.doc` handled via `/usr/bin/textutil` (present). |
| Free disk | ~29 GB (volume 87% full) | PyTorch + deps ≈ 3–4 GB. Workable but worth watching. |
| `uv` / `pyenv` | Not installed | Use stdlib `venv`; miniforge available as fallback. |

---

## 2. Risks and Conflicts to Manage

1. **`.gitignore` must land in the very first commit.** `data/raw/` will hold hundreds of
   debate files (potentially hundreds of MB), and a GitHub remote is already wired up. If
   ingestion runs before `.gitignore` exists, the library and the vector index get committed.
   This is the single highest-consequence ordering constraint in Phase 1.
2. **Python version drift.** The project targets **3.13.13**, but a bare `python3` on this
   machine is still 3.9.6 because `/usr/bin` precedes miniforge on `PATH`. Every script, test,
   and tool must run through the project venv. Add a `.python-version` marker and a version
   assertion in `config.py` so a wrong interpreter fails loudly instead of mysteriously.
3. **Wheel availability on 3.13.** `torch`, `chromadb`, and `sentence-transformers` all ship
   3.13 wheels, so this should be smooth. Contingency only if a resolve fails:
   `conda create -n debate python=3.12` using the existing miniforge install.
4. **`textutil` is macOS-only.** The `.doc` parser must be a pluggable backend that reports a
   clear "unsupported on this platform" error elsewhere, rather than crashing ingestion.
5. **Scanned / image-only PDFs.** `pypdf` returns empty strings for these. Ingestion needs an
   explicit low-text-yield detector that quarantines such files into a review list. OCR is
   deliberately out of scope for Phase 1.
6. **ChromaDB's default embedding function.** Chroma will silently download its own ONNX
   MiniLM if no embedding function is passed. We must always inject our `sentence-transformers`
   embedder explicitly so we never end up with two different models writing to one index.
7. **Formatting in debate files — best-effort, not blocking.** Bold / underline / highlight in
   `.docx` often marks the operative claim or warrant, and `python-docx` exposes it at the run
   level. We capture it as optional chunk metadata where it falls out cheaply, but **retrieval
   quality takes priority over faithful formatting reconstruction**. No parser, chunker, or
   test in Phase 1 may depend on formatting being present, and a document whose formatting we
   cannot recover still ingests normally.

---

## 3. Recommended Repository Structure

This follows the requested layout with two deliberate adjustments (explained below).

```
Debate_Case_Engine/
├── README.md
├── pyproject.toml                  # single source of truth for deps + tooling
├── .gitignore
├── .python-version
├── debate_engine/                  # the importable package
│   ├── __init__.py
│   ├── config.py                   # pydantic-settings: paths, chunk sizes, model name
│   ├── logging.py
│   ├── schemas/                    # (requested `models/`) Pydantic domain models
│   │   ├── document.py             # SourceDocument, ParsedDocument
│   │   └── chunk.py                # Chunk, ChunkType, ChunkMetadata
│   ├── ingestion/
│   │   ├── discovery.py            # recursive walk, file typing, content hashing
│   │   ├── parsers/
│   │   │   ├── base.py             # Parser protocol + registry
│   │   │   ├── docx_parser.py      # python-docx; run formatting captured best-effort
│   │   │   ├── doc_parser.py       # /usr/bin/textutil backend
│   │   │   ├── pdf_parser.py       # pypdf
│   │   │   └── text_parser.py      # .md / .txt
│   │   ├── structure.py            # debate-specific structure detection
│   │   ├── chunking.py             # argument-level + submodule-level chunks
│   │   ├── metadata.py
│   │   └── dedupe.py               # rapidfuzz near-duplicate detection
│   ├── storage/
│   │   ├── db.py                   # SQLite schema, migrations, queries
│   │   └── vector_store.py         # Chroma wrapper
│   └── retrieval/
│       ├── embedder.py             # sentence-transformers wrapper
│       └── search.py               # hierarchical retrieval
├── scripts/
│   ├── ingest.py                   # CLI: raw files -> parsed + SQLite
│   ├── build_index.py              # CLI: parsed -> embeddings -> Chroma
│   └── inspect_db.py               # CLI: corpus stats / sanity checks
├── ui/
│   └── retrieval_app.py            # Streamlit retrieval tester
├── data/                           # all gitignored except .gitkeep files
│   ├── raw/                        # your debate library
│   ├── parsed/                     # JSONL intermediates
│   ├── indexes/                    # chroma/ + debate.sqlite3
│   └── models/                     # cached sentence-transformers weights
├── tests/
│   ├── fixtures/                   # small, committed sample debate files
│   └── ...
└── docs/
    └── PHASE_1_PLAN.md
```

### Deviations from the requested sketch

- **One package root (`debate_engine/`) instead of flat top-level `ingestion/`, `retrieval/`,
  `models/`.** Those names are generic enough to shadow or be shadowed by installed packages,
  and flat layout forces `sys.path` juggling from `tests/`. A single package makes
  `pip install -e .` clean and imports unambiguous:
  `from debate_engine.ingestion.chunking import ...`.
- **`models/` renamed to `schemas/`.** In a project that also loads embedding models,
  "models" is ambiguous. `schemas/` = Pydantic types; `data/models/` = downloaded weights.
- **No root-level `config.py`.** Config lives at `debate_engine/config.py` so there is exactly
  one source of truth. A root shim would create two import paths for the same settings object.
- **`pyproject.toml` over `requirements.txt`.** Needed anyway for editable install, and it
  carries `pytest` and `ruff` configuration in the same file.

---

## 4. Recommended Dependencies

### Runtime

- `pydantic` >= 2.7 — schemas and validation
- `pydantic-settings` — typed config from env / defaults
- `python-docx` — `.docx` parsing with run-level formatting
- `pypdf` — PDF text extraction
- `rapidfuzz` — near-duplicate detection (C++ backed, very fast on hundreds of files)
- `chromadb` — persistent local vector store
- `sentence-transformers` (pulls `torch`) — local embeddings, per your decision
- `typer` — CLI for `scripts/` (small; better UX than argparse)
- `tqdm` — progress reporting across hundreds of files
- `streamlit` — retrieval testing UI (last Phase 1 milestone only)

Legacy `.doc` needs **no dependency** — it shells out to macOS `/usr/bin/textutil`.
SQLite is stdlib.

### Development

- `pytest`, `pytest-cov`
- `ruff` — lint + format in one tool (replaces black + flake8 + isort)
- `mypy` — optional, worth it given the Pydantic-heavy design

### Embedding model (decided)

**`BAAI/bge-small-en-v1.5`** — 384-dim, ~130 MB. Chosen over `all-MiniLM-L6-v2`: notably
stronger on retrieval benchmarks at nearly the same size and speed, and the extra quality is
worth it here. Two implementation notes: BGE models expect a query prefix
(`"Represent this sentence for searching relevant passages: "`) on the **query** side only, not
on stored passages, and they are trained for cosine similarity, so the Chroma collection must
be created with `hnsw:space = "cosine"`. `embedder.py` keeps the model name in config so it can
be swapped without touching call sites.

### Deliberately excluded

- **LangChain / LlamaIndex** — we need precise control over debate-specific chunking and
  hierarchical retrieval, which is exactly the part these frameworks abstract away. They would
  add a large dependency surface and buy us nothing here.
- **`unstructured`** — very large transitive dependency tree; our five formats are covered by
  targeted parsers.
- **FAISS** — Chroma already provides persistence plus metadata filtering.
- **pandas** — not needed for this workload.

---

## 5. Proposed Milestones

Each milestone is a stopping point with a testable artifact.

- **M1 — Scaffold.** Directory tree, `pyproject.toml`, `.gitignore` (first!), `config.py`,
  logging, Pydantic schemas, venv on Python 3.13.13, one smoke test. Nothing parses yet.
- **M2 — Discovery + raw text extraction.** Recursive walk, format detection, content hashing,
  all five parsers, failure quarantine. Output: `data/parsed/*.jsonl` with full provenance.
  Clean text extraction is the acceptance bar; formatting metadata is a bonus, not a gate.
- **M3 — Debate structure detection.** Detect motion/topic headers, side and speaker markers
  (Gov/Opp, PM/LO/DPM/MG/MO/PMR/Whip), argument headings, and rebuttal blocks. Parliamentary
  format specifically — briefs and motion analyses rather than policy-style evidence cards.
- **M4 — Chunking + metadata.** Argument-level chunks with submodule-level children
  (claim / warrant / impact / weighing / response), each carrying topic, side, and source
  metadata.
- **M5 — Near-duplicate detection.** Exact hash pass, then `rapidfuzz` fuzzy pass; mark
  duplicate clusters and elect a canonical chunk.
- **M6 — SQLite persistence.** Tables for documents, chunks, hierarchy edges, and duplicate
  clusters, plus an `FTS5` table for keyword search.
- **M7 — Embeddings + Chroma index.** Batch embedding with the explicit injected embedder,
  incremental re-index keyed on content hash.
- **M8 — Hierarchical retrieval.** Search submodules, roll results up to parent arguments,
  return a ranked argument list with matched submodule evidence. Metadata filters for topic
  and side.
- **M9 — Streamlit retrieval tester.** Query box, filters, ranked results, source provenance.

---

## 6. Open Items for Later Phases

- OCR fallback for scanned PDFs.
- Cross-platform `.doc` support (currently macOS-only).
- Hybrid search combining `FTS5` keyword results with vector results.
- Reranking — deferred until we can measure whether retrieval quality actually needs it.
