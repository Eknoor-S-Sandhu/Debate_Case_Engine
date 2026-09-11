# Milestone 12 — Strategy architectures

Scope: generate exactly three distinct, unranked case architectures from an
existing Knowledge Packet, judge guidance, and optional strategy preferences.
The implementation stops after generation and validation. Milestone 13 is not
started: no Red Team, ranking, selection, repair loop, or final case writing.

## Architecture contract

Each architecture contains a name, framing, central mechanism, route to the
ballot, explanation of its difference from the other proposals, two or three
contentions, judge adaptation, why it can win, and an initial vulnerability.
Each contention includes a claim, warrants, impacts, preempts, provenance basis,
source references, optional exact quotations, assumptions, and verification needs.
Policy substantive contentions require uniqueness, link, and internal link.
Value architectures require value and criterion. The prompt instructs factual
architectures to explain their standards of evaluation without forcing a policy
chain. Specific judge preferences accompany category guidance in the input.

Sources are limited to IDs actually supplied to the model. Quote text must match
an exact substring of the supplied excerpt and cite a source used by its
contention. Archive-only, research-only, mixed-source, and new-reasoning labels
are checked against references; new reasoning must state assumptions. Research
use and archive freshness flags or verification notes require verification needs.
Theory/K material is rechecked against retrieval eligibility and must cite
eligible archive material of the corresponding type.

Duplicate names, duplicate claims within an architecture, near-identical argument
text across architectures, and repeated mechanism/ballot-route pairs are rejected.
These checks do not prove strategic diversity, factual truth, causal strength,
source entailment, or judge suitability. Users must assess those qualities.
The system never marks unverified research excerpts as verified evidence.

## Running

Use the Round preparation page to prepare a packet and then explicitly select
**Generate three architectures**. The page shows developed contentions, sources,
quotes, assumptions, and verification needs, with a JSON download. Generation
reuses the prepared packet; it does not rerun retrieval or research. Submitting
a new plan or packet clears previous architectures.

Alternatively, export a Knowledge Packet and run from the repository root:

```bash
.venv/bin/python scripts/generate_strategies.py knowledge_packet.json
.venv/bin/python scripts/generate_strategies.py knowledge_packet.json --json
```

The CLI accepts `--preferences TEXT`. JSON output contains status, architectures,
warnings, model, prompt version, supplied source IDs, and a fingerprint of the
input packet. Retain the packet alongside the output to resolve source IDs to
original archive metadata and research URLs. Non-completed results exit with
code 1 and no accepted architectures.

Set these in the gitignored local `.env` or environment:

```text
DEBATE_ENGINE_STRATEGY__ALLOW_REMOTE=true
DEBATE_ENGINE_STRATEGY__API_KEY=your-openai-api-key
DEBATE_ENGINE_STRATEGY__MODEL=your-supported-model-id
```

Choose a model available to your account supporting Responses structured output.
This uses provider credits. Selected private archive excerpts, judge notes,
research excerpts, motion, and preferences are transmitted to OpenAI. Archive
source paths are omitted from the source payload. Free-text notes and excerpts
are not automatically scrubbed of sensitive information. Credentials are never
included in exported results. The adapter requests `store=false`.

Internet-permitted prep, a concrete side, and policy/value/fact round type are
required. Offline prep blocks even injected providers. The default adapter
requires all three configuration values; absent setup returns `not_configured`.
Provider errors or refusals return `failed`; structural, source, diversity, or
input validation failures return `invalid_output`. There are no retries, redirects,
or provider tools. Exceptions are redacted rather than exposing response bodies.

Defaults: 24 archive excerpts, 8 research sources, 3,000 characters per excerpt,
120,000 total input characters, 10,000 output tokens, and a 60-second socket
timeout. Preferences are limited to 3,000 characters. Limits are configurable
under `DEBATE_ENGINE_STRATEGY__...`. The timeout is not a round-wide deadline.
No paid model call is required by the automated tests.

## Validation

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Coverage includes exactly-three and contention-count contracts, policy and value
requirements, source and quotation validation, stale evidence, provenance labels,
diversity screening, offline and configuration gating, provider request shape,
incomplete/refused/malformed responses, failure redaction, CLI success/failure,
and Streamlit generation, detailed display, and stale-result clearing.

Automated provider checks use injected responses. A successful paid live model
call and qualitative review of its arguments are not established by these tests.
