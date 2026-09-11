# Debate Case Engine

A Parliamentary Debate preparation system with local archive retrieval and
optional cloud research and strategy generation.

## Current status: Milestone 12 — Strategy architectures

Phase 1 builds the **knowledge and retrieval foundation** - ingesting a debate
library, chunking it into arguments, and searching it semantically.

Milestone 8 combines bounded semantic and lexical candidate retrieval with
deterministic debate-aware scoring. It returns related full arguments and
reusable submodules, applies relevance-gated source/masterfile preferences,
enforces theory/K eligibility, suppresses duplicates, and diversifies repeated
argumentative functions. Scores and hierarchy expansion are inspectable.
Milestone 9 adds a local Streamlit retrieval tester. Milestone 10 adds the
Round Director and Knowledge Agent, producing a structured archive packet
for a round. Milestone 11 adds judge adaptation and permission-gated live
research. Milestone 12 generates three distinct, unranked case architectures
from the packet and judge guidance. Evaluation, selection, and case writing
remain outside this milestone.

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

## Prepare a round (Milestones 10–11)

The Streamlit sidebar now includes **Round preparation**. Enter your motion,
side, round type, judge category or paradigm notes, and prep rules. Preview the retrieval plan
without opening indexes, or prepare an organized Knowledge Packet. The packet
shows original text, source paths, ranking scores, judge guidance, research, and verification notes, and
can be downloaded as JSON for later stages.

The same workflow is available from the repository root:

```bash
.venv/bin/python scripts/prepare_round.py docs/examples/round_input.json --plan-only
.venv/bin/python scripts/prepare_round.py docs/examples/round_input.json --json
```

Copy the example JSON and replace its values for your round. The command also
accepts `--database PATH`. Plan-only needs no database or model. Packet creation
requires SQLite; semantic retrieval requires a matching existing Chroma index
and cached embedding model. Missing semantic resources fall back to lexical
retrieval with warnings; absent SQLite produces an error without creating it.

Round preparation never downloads models, including when internet research is
permitted. Build/cache resources before prep. Internet permission is recorded
for live research in Milestone 11. Clear judge labels in notes can be classified;
ambiguous notes remain unclassified and explicit judge settings win. The director uses conservative motion-prefix
inference only when round type is omitted; explicit values take precedence.

The packet retains selected argument excerpts, not whole reconstructed cases.
Freshness notes flag material to verify, and coverage gaps describe this set of
retrieved modules only. No facts or source text are rewritten. The existing
retrieval tester and build commands retain their behavior.
See [the Milestone 10 scope](docs/MILESTONE_10.md) for the original packet design.

### Configure live research

Set `DEBATE_ENGINE_RESEARCH__API_KEY` to your Tavily key in your local `.env` or
environment. Keep credentials out of round inputs and source control. Search
uses your provider credits only when internet is permitted and preparation is
submitted; previews and offline rounds never call the provider. Only motion,
explicit concepts, and round year form search queries. Archive text and judge
notes are not sent.

Without a key, online preparation returns the archive packet with a clear
`missing_credentials` research status. Live results preserve URLs, provider
publication dates when available, retrieval timestamps, and excerpts. They are
**unverified search excerpts**, not verified facts or full-study reviews. Failed
queries produce a partial/failed status without discarding archive material.

Judge guidance is rule-based, preserves original notes, and is applied before
retrieval. Specific no-theory/no-K preferences affect retrieval unless an explicit
round option overrides them. This milestone does not generate strategies.
See [Milestone 11 setup and behavior](docs/MILESTONE_11.md) for details.

## Generate architectures (Milestone 12)

After preparing a Knowledge Packet, use **Generate three architectures** on the
Round preparation page, or run:

```bash
.venv/bin/python scripts/generate_strategies.py knowledge_packet.json
.venv/bin/python scripts/generate_strategies.py knowledge_packet.json --preferences "Emphasize clear causal mechanisms" --json
```

Set `DEBATE_ENGINE_STRATEGY__ALLOW_REMOTE=true`,
`DEBATE_ENGINE_STRATEGY__API_KEY`, and `DEBATE_ENGINE_STRATEGY__MODEL` in your
local `.env` or environment. Supply an OpenAI model available to your account
that supports Responses structured output. Generation uses provider credits
and sends selected archive excerpts, judge notes, research excerpts, and strategy
preferences to OpenAI. It requires internet-permitted prep, a concrete side,
and a policy, value, or fact round type. Missing configuration makes no request.

Results include two or three developed contentions per architecture, source IDs,
exact source quotes when used, assumptions, verification needs, judge adaptation,
and an initial vulnerability. They can be downloaded as JSON. No ranking,
Red Team, repair, selection, or final case-writing stage runs.
See [Milestone 12 scope and validation](docs/MILESTONE_12.md).

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
