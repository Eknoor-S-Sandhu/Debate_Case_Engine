# Milestone 10 — Round Director and Knowledge Agent

Scope follows the original Build Debate Agent roadmap: round input → Round
Director → archive retrieval → structured Knowledge Packet. Milestone 11 adds
Research and Judge adaptation; strategy and writing come later.

The director preserves explicit inputs and generates inspectable retrieval
queries through Milestone 8. Missing round types are inferred only for explicit
THW/This House Would (policy) and preference/regret prefixes (value). Other
motions remain unspecified, including ambiguous THBT motions. Explicit types,
sides, eligibility overrides, and judge categories win over inference. Judge
notes are stored verbatim, not classified. Prep minutes are recorded, not a
running deadline. Internet permission is recorded; no research is dispatched.

The Knowledge Agent uses one bounded multi-query hierarchical retrieval run,
retaining its relevance, diversity, duplicate and theory/K policies. It groups
selected evidence by argumentative function, preserving exact original text,
source paths, heading paths, chunk IDs, scores, and original freshness labels.
Items are stored once and category lists reference their IDs. Unknown section
types go into other_modules. Related arguments are excerpts, not full cases.
Unranked parent/child text is not copied into the packet; parent IDs remain in
chunk metadata and the retrieval tester still exposes hierarchy inspection.

Coverage gaps concern categories among selected modules only, not assertions
that the archive lacks evidence. Potentially stale or undated empirical sections
receive verification notes, not factual updates. Prior-year empirical sections
are conservatively flagged even if tagged current. Conceptual theory/K sections
are not penalized merely for age. This layer does not claim any fact is verified.

Runtime is deterministic and local. No LLM provider, API key, online reranker,
judge-paradigm parser, research, strategy, or case writing is introduced. Both
online and offline prep use cache-only embeddings and disable Chroma telemetry.
Absent vector indexes/collections or cached models produce backend warnings and
permit the existing lexical fallback; absent SQLite fails without creating it.
Build indexes and cache the embedding model before a round. This is application
behavior, not an operating-system network sandbox.

Entry points:

- `RoundDirector.plan(RoundInput(...))`: no index access or model load.
- `RoundDirector.prepare(...)`: complete Knowledge Packet.
- `KnowledgeAgent(..., retriever=...)`: injectable retrieval for isolated tests.
- `python scripts/prepare_round.py docs/examples/round_input.json --plan-only`
- `python scripts/prepare_round.py docs/examples/round_input.json --json`
- Streamlit sidebar → Round preparation; existing retrieval tester unchanged.

Validation uses synthetic SQLite/FTS fixtures, mocked semantic retrieval and
cache failures, CLI JSON round trips, and Streamlit AppTest. No private archive
is required or ingested. No automatic commits or Milestone 11 work are included.
