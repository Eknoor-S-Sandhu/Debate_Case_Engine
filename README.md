# Debate Case Engine

A local Parliamentary Debate preparation system. Everything runs on your own
machine against your own debate library.

## Current status: Phase 1, Milestone 3

Phase 1 builds the **knowledge and retrieval foundation** - ingesting a debate
library, chunking it into arguments, and searching it semantically.

Milestone 3 recognizes debate-specific document structure after extracting
`.docx`, `.doc`, `.pdf`, `.md`, and `.txt` files. It normalizes common policy,
value, fact, theory, kritik, and answer headings while preserving original
headings, body text, formatting signals, and uncertain material. It does not
yet create retrieval chunks, persist documents, search, or provide a user
interface. Later phases add those capabilities and the agent layer.

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

## Configuration

Settings live in `debate_engine/config.py` and can be overridden with
environment variables prefixed `DEBATE_ENGINE_`, or through a local `.env`
file. Nested values use a double underscore:

```bash
DEBATE_ENGINE_DEFAULT_TOP_K=30
DEBATE_ENGINE_SOURCE_WEIGHTS__PERSONAL=1.2
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
> a second line of defence. Verify at any time with `git status --short`.

## Planning

See [docs/PHASE_1_PLAN.md](docs/PHASE_1_PLAN.md) for the full Phase 1
architecture, dependency rationale, and milestone sequence.
