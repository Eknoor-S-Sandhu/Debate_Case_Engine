# Debate Case Engine

A local Parliamentary Debate preparation system. Everything runs on your own
machine against your own debate library.

## Current status: Phase 1, Milestone 1

Phase 1 builds the **knowledge and retrieval foundation** - ingesting a debate
library, chunking it into arguments, and searching it semantically.

Milestone 1 is the scaffold only: project configuration, settings, schemas,
logging, and tests. There is no ingestion, no search, and no user interface
yet. Later phases add the agent layer.

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
| `data/parsed/` | Extracted text and chunks produced by ingestion |
| `data/indexes/` | SQLite metadata database and the vector index |
| `data/models/` | Cached embedding model weights |

None of these directories accept files yet; ingestion arrives in Milestone 2.

> **Your debate archive is never committed.** Everything under `data/` is
> gitignored apart from the `.gitkeep` placeholders that keep the folders
> tracked, and `.docx`, `.doc`, and `.pdf` files are ignored repository-wide as
> a second line of defence. Verify at any time with `git status --short`.

## Planning

See [docs/PHASE_1_PLAN.md](docs/PHASE_1_PLAN.md) for the full Phase 1
architecture, dependency rationale, and milestone sequence.
