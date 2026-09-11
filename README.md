# Debate Case Engine

A local Parliamentary Debate preparation system. Everything runs on your own
machine against your own debate library.

## Current status: Phase 1, Milestone 9

Phase 1 builds the **knowledge and retrieval foundation** - ingesting a debate
library, chunking it into arguments, and searching it semantically.

Milestone 8 combines bounded semantic and lexical candidate retrieval with
deterministic debate-aware scoring. It returns related full arguments and
reusable submodules, applies relevance-gated source/masterfile preferences,
enforces theory/K eligibility, suppresses duplicates, and diversifies repeated
argumentative functions. Scores and hierarchy expansion are inspectable. Milestone 9 adds a local Streamlit retrieval tester. It does not generate
cases or run agents.

## Requirements

- Python 3.12 or newer (developed against 3.13)
- macOS or Linux

## Setup

From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Every command below assumes the virtual environment is active. If a bare
`python3` on your `PATH` is an older system interpreter, activating the venv is
what makes `python` resolve to the right one - and `debate_engine.config` will
raise a clear error if it does not.

## Development commands

```bash
pytest              # run the test suite
ruff check .        # lint
ruff format .       # format
```

## Inspect a debate library

Pass any local archive folder to the read-only inspector:

```bash
python scripts/inspect_library.py "/path/to/debate/archive"
python scripts/inspect_library.py "/path/to/debate/archive" --limit 20
```

The command recursively discovers supported documents and prints counts by
format, inferred source group, and parse status. It does not modify source
files or persist extracted text. Unsupported files, malformed documents,
legacy `.doc` conversion failures, and likely scanned PDFs are reported.

Legacy `.doc` parsing uses macOS `/usr/bin/textutil` when available. No OCR is
performed.

## Inspect detected debate structure

Print the normalized section tree for one supported document:

```bash
python scripts/inspect_structure.py "/path/to/debate/file.docx"
python scripts/inspect_structure.py "/path/to/debate/file.docx" \
  --show-confidence --show-text --max-depth 3
```

Detection is deterministic and rule-based; it does not call an LLM. Weakly
structured text remains available as unstructured/orphan content rather than
being forced into a debate format.

## Inspect generated chunks

Preview in-memory chunks for one document:

```bash
python scripts/inspect_chunks.py "/path/to/debate/file.docx"
python scripts/inspect_chunks.py "/path/to/debate/file.docx" \
  --level submodule --show-text --show-metadata --limit 10
```

This command parses and structures the file before printing chunk summaries.
It does not write chunks, load an embedding model, or initialize a database.

## Inspect duplicate groups

Inspect one file or compare an archive folder entirely in memory:

```bash
python scripts/inspect_duplicates.py "/path/to/debate/archive"
python scripts/inspect_duplicates.py "/path/to/debate/archive" \
  --only-duplicates --show-text --limit 20
```

Exact matching uses a stable normalized-content hash. Near matching uses
conservative RapidFuzz scoring with structural and candidate-blocking
safeguards. Duplicate groups preserve all original chunks.

## Build the SQLite knowledge base

Build or incrementally upsert an archive into the configured database
(`data/indexes/debate.db` by default):

```bash
python scripts/build_database.py "/path/to/debate/archive"
python scripts/build_database.py "/path/to/debate/archive" --rebuild
python scripts/build_database.py "/path/to/debate/archive" \
  --database "/another/local/path/debate.db"
```

The build runs discovery, parsing, structure detection, chunking, duplicate
detection, and persistence. Each source file is committed independently so a
bad document does not roll back successful files. Failures, scanned PDFs that
need OCR, and legacy `.doc` failures are reported without invented placeholder
content. `--rebuild` drops and recreates the knowledge-base schema; the default
mode upserts deterministic IDs and preserves documents from other prior runs.

Inspect the result without modifying it:

```bash
python scripts/inspect_db.py stats
python scripts/inspect_db.py documents
python scripts/inspect_db.py document "case filename"
python scripts/inspect_db.py chunk "chunk-id"
python scripts/inspect_db.py duplicate-group "duplicate-group-id"
python scripts/inspect_db.py search "public transit"
```

All commands accept `--database` to inspect a non-default database. FTS5 search
is lexical only and does not replace the semantic retrieval layer planned for
later milestones.

Delete behavior is deliberate: deleting a document cascades to its chunks;
chunk deletion cascades to duplicate memberships; deleting a representative
chunk removes its duplicate group; deleting a group clears the denormalized
group marker on its chunks; and deleting an argument clears, rather than
deletes, its surviving submodules' parent reference.

## Build and inspect the vector index

Build the SQLite database first, then synchronize eligible chunks into Chroma:

```bash
python scripts/build_database.py "/path/to/debate/archive"
python scripts/build_vector_index.py
```

The first vector build lazily downloads and caches
`BAAI/bge-small-en-v1.5`, then embeds chunks in bounded batches. Subsequent
runs compare deterministic embedding-input fingerprints: unchanged vectors
are skipped, changed/new chunks are embedded, and vectors absent from SQLite
are deleted. SQLite remains authoritative and Chroma can be rebuilt entirely
from it:

```bash
python scripts/build_vector_index.py --rebuild
python scripts/build_vector_index.py --batch-size 16
python scripts/build_vector_index.py --include-duplicates
python scripts/inspect_vector_index.py
```

By default, singleton chunks and each duplicate group's preferred
representative are indexed. `--include-duplicates` intentionally indexes every
preserved variant instead. Collection metadata records the model, dimension,
normalization setting, and embedding-text schema; incompatible configuration
requires `--rebuild`.

Run a basic semantic-search inspection:

```bash
python scripts/search_vectors.py "economic growth regulation" --top-k 10
python scripts/search_vectors.py "investor confidence" \
  --source-group personal --section-type internal_link \
  --show-text --show-metadata
```

This is direct cosine similarity with optional equality filters. It does not
apply source weights, freshness boosts, masterfile preference, duplicate
diversification, or any other Milestone 8 retrieval policy.

## Run hierarchical retrieval

After building both SQLite and Chroma, retrieve debate material for a round:

```bash
python scripts/retrieve.py \
  "Mexico should lift its ban on planting genetically modified corn" \
  --side aff --round-type policy --judge tech \
  --show-scores --show-text
```

Useful debugging controls include `--source-group personal`,
`--include-theory`, `--include-kritiks`, `--arguments 5`, `--modules 20`,
repeatable `--concept`/`--query` values, and `--database`.

Unlike raw vector search, hierarchical retrieval:

- generates a bounded set of deterministic motion, concept, mechanism, impact,
  and side-aware queries;
- merges Chroma cosine matches with SQLite FTS5 matches before ranking;
- keeps semantic relevance dominant while using Personal, Past Case, and
  Other source hierarchy as a modest close-decision influence;
- gives relevant `Case File Sandhu` mechanisms and `Theory File - Sandhu`
  shells targeted priority without forcing irrelevant masterfile content;
- excludes non-personal theory and Ks; personal theory requires a relevant
  theory request or explicit inclusion, while personal Ks require explicit
  inclusion or a relevant query for a TECH judge;
- returns only preferred duplicate representatives and reduces repeated
  functions, same-parent modules, and highly similar text;
- expands selected submodules to their parent argument and exposes selected
  arguments' direct children for inspection.

Every result includes semantic, lexical, concept, heading, source,
masterfile, motion-similarity, section-fit, compatibility, freshness, and
redundancy components. These are deterministic retrieval-support signals, not
LLM confidence estimates. No case writing or argument adaptation occurs in
Milestone 8.

## Open the retrieval tester (Milestone 9)

From the repository root, after building the database and vector index:

```bash
.venv/bin/python -m streamlit run ui/app.py --server.address 127.0.0.1
```

Open the local URL printed by Streamlit. Enter a motion, choose the round/side
context and optional source filter, then select **Retrieve**. The source filter
restricts results; side and round type are ranking context, not strict filters.
Additional options accept one extra concept or query per line and explicit
include/exclude/automatic theory and kritik eligibility. `None` preserves the
retriever's automatic behavior. Relative database paths resolve from the repo.
The Chroma path uses the existing environment configuration; it must correspond
to the selected SQLite database.

Full arguments and submodules appear separately with original text, source
paths, heading metadata, score components, ranking reasons, and parent/child
context. Search details show the submitted request, generated queries, and
retrieval statistics. Support labels are retrieval signals, not truth estimates.
Results remain tied to the last submitted request until Retrieve is pressed
again; a failed search clears earlier results. Missing databases, no matches,
and backend warnings are shown in the page.

The tester calls the Milestone 8 pipeline only on submission. It does not build
or rebuild indexes. Existing retrieval may initialize Chroma storage and load
or download the configured embedding model on the first search. No LLM or case
generation is used. UI tests use Streamlit AppTest with an isolated retriever.

## Configuration

Settings live in `debate_engine/config.py` and can be overridden with
environment variables prefixed `DEBATE_ENGINE_`, or through a local `.env`
file. Nested values use a double underscore:

```bash
DEBATE_ENGINE_DEFAULT_TOP_K=30
DEBATE_ENGINE_SOURCE_WEIGHTS__PERSONAL=1.2
DEBATE_ENGINE_CHUNKING__FALLBACK_MAX_TOKENS=450
DEBATE_ENGINE_STORAGE__DATABASE_PATH=data/indexes/custom.db
DEBATE_ENGINE_STORAGE__ENABLE_FULL_TEXT_SEARCH=true
DEBATE_ENGINE_VECTOR_INDEX__CHROMA_PATH=data/indexes/chroma
DEBATE_ENGINE_VECTOR_INDEX__EMBEDDING_BATCH_SIZE=32
DEBATE_ENGINE_RETRIEVAL__SEMANTIC_CANDIDATE_POOL=72
DEBATE_ENGINE_RETRIEVAL__LEXICAL_CANDIDATE_POOL=36
```

## Where debate files go

| Directory | Contents |
| --- | --- |
| `data/raw/` | Your debate library - the source `.docx`, `.doc`, `.pdf`, `.md`, and `.txt` files |
| `data/parsed/` | Future extracted text and chunks |
| `data/indexes/` | SQLite metadata database and the vector index |
| `data/models/` | Cached embedding model weights |

You may place an archive under `data/raw/` or inspect it in place elsewhere.
Parsing and structure detection run in memory only and do not write to
`data/parsed/`.

> **Your debate archive is never committed.** Everything under `data/` is
> gitignored apart from the `.gitkeep` placeholders that keep the folders
> tracked, and `.docx`, `.doc`, and `.pdf` files are ignored repository-wide as
> a second line of defence. This includes the SQLite database, Chroma index,
> and downloaded model cache. Verify at any time with `git status --short`.

## Planning

See [docs/PHASE_1_PLAN.md](docs/PHASE_1_PLAN.md) for the full Phase 1
architecture, dependency rationale, and milestone sequence.
