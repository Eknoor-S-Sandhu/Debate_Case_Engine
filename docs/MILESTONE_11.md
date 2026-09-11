# Milestone 11 — Research and Judge adaptation

Scope: classify supplied judge information before retrieval, preserve specific
preferences, and attach a cited live-search packet when prep rules permit it.
No Strategy Agent, architectures, Red Team, case writing, or Milestone 12 work.

## Judge adaptation

`JudgeAgent.analyze` preserves the exact supplied notes and returns the category,
classification source, matched clauses, specific preferences, guidance, and
warnings. Explicit category selections override note labels. Without an explicit
selection, clear self-descriptions or labeled categories can establish TECH,
FLOW, FLAY, or FULLY_LAY. Ambiguous, absent, negated, and conflicting labels do
not force a category. This is a conservative rule-based parser, not an LLM or a
complete natural-language paradigm interpreter.

Direct requests such as “No spreading,” “No theory,” and “No Ks” are recognized.
Conditional exclusions remain text for inspection. Specific exclusions are
applied before retrieval when the corresponding explicit round option is absent;
explicit round options win with a warning. Specific preferences are retained
alongside category guidance for later Strategy use. No judge names or websites
are looked up automatically. Unrecognized prose remains in original_notes.

## Research

The default provider implements the documented
[Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
using the standard library. No new package or LLM runtime is required. Set this
in your local, gitignored `.env` or environment:

```text
DEBATE_ENGINE_RESEARCH__API_KEY=your-tavily-api-key
```

Do not put credentials in round JSON files. The key is a masked configuration
secret and is not included in plan/packet exports. Search may consume provider
credits. Configure the key only if you want this provider used during online prep.

Both the round's `prep_rules.internet_allowed` and provider configuration are
required. Offline rounds return `disabled_by_prep_rules` before provider access,
even with a key or injected provider. Plan previews never issue searches.
Online prep without a key reports `missing_credentials` while preserving the
Knowledge Packet. Provider failures never erase retrieved archive material.

Only the motion, explicit concepts, and round year form external queries. No
archive excerpts, source paths, or judge notes are sent. Three queries seek
current official statistics, research studies with limitations, and recent
outcomes/risks. These are search targets, not guarantees of authoritative results.
Default limits: 3 queries, 4 results each, 10-second per-request socket timeout,
2 MB maximum response, 2,000 characters per excerpt. There are no retries or
redirects. Limits are configurable under `DEBATE_ENGINE_RESEARCH__...`; queries
are capped at 3, results at 10 per query, timeouts at 20 seconds. This is bounded
request work, not a hard round-wide deadline or OS network sandbox.

Every retained source has a stable URL-derived ID, title, web link, provider
excerpt, provider publication date when parseable, retrieval timestamp, matching
queries, and verification notes. Duplicate URLs merge across queries; fragments
and UTM tracking parameters do not make new sources. Unsupported URL schemes,
local IP links, malformed rows, and empty excerpts are skipped. Source pages are
not fetched separately and provider-generated answers are disabled.

All excerpts are explicitly `unverified_search_excerpt`. Publication and retrieval
dates are distinct. Missing dates stay unknown; older dates receive currency
notes. The application does not convert a snippet into a verified statistic,
claim to have read a full study, or overwrite stale archive evidence. Original
archive items and research sources remain separate in the exported packet.
Archive chunk IDs needing verification and selected coverage gaps are retained
as follow-up needs, not marked resolved merely because searches returned results.

Statuses distinguish disabled, missing credentials, no results, complete search
execution, partial results, and total failure. “Completed” describes search
execution, not factual verification. Errors do not include provider response
bodies, keys, or untrusted exception text.

## Running and testing

The existing CLI and Round preparation page now show judge guidance and research
results. JSON exports include `plan.judge_profile` and `research` while retaining
existing Knowledge Packet fields. The new fields have defaults so old packet
JSON remains readable. Use the same example input; set internet_allowed to true
only for rounds that permit live research.

```bash
.venv/bin/python scripts/prepare_round.py docs/examples/round_input.json --plan-only
.venv/bin/python scripts/prepare_round.py docs/examples/round_input.json --json
.venv/bin/python -m streamlit run ui/app.py --server.address 127.0.0.1
```

Tests cover precedence and ambiguity, offline gating, missing credentials,
bounded provider calls, malformed responses, URL deduplication, error redaction,
publication dates, HTTP request shape, round orchestration, and CLI/UI exports.
Provider tests use injected responses and never require credentials or paid calls.
