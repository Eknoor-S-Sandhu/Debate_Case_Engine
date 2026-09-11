# Milestone 16 — V1 validation and reliability hardening

Scope: repeatable representative-round validation, safer stage failures, latency
and usage diagnostics, and selection continuity. No Milestone 17 topic selection,
Milestone 18 live refutation, or later product features are added.

## Reliability changes

Every inference stage records elapsed wall-clock seconds, response/validation
status, a safe error category, HTTP status when available, and provider-reported
input/output/total token counts. Missing token counts remain null, not zero.
Total tokens can include provider reasoning tokens and need not equal visible
input plus output counts. These are usage observations, not billing estimates.

Stage records cover strategy, Red Team, repair, scoring, drafting, optional trim,
and improvement. They appear in exported results and a Request diagnostics
expander in the UI. Request count is the number of recorded inference calls;
preparation/retrieval/search time is included separately in benchmark round latency.
Logs contain no API keys, prompts, response bodies or private archive text.

Authentication, permission, unavailable models, rate limit/quota, request/schema,
server, connection and timeout failures give actionable messages. Output refusal,
truncation, malformed JSON and local validation failures stop their stage without
retrying or silently changing providers. HTTP 429 is reported as rate limit or
quota because an HTTP status alone cannot reliably distinguish them. HTTP 400
similarly identifies a rejected request/schema without exposing response bodies.

Old exports remain readable: absent empty diagnostic records are omitted from
fingerprint calculation to preserve previous handoffs. New populated diagnostics
remain bound into the exported version's fingerprint.

## Live-discovered Gemini regression

The first live check against the Milestone 15 adapter returned HTTP 400. The
GenerateContent request now uses `responseMimeType` and `responseJsonSchema`
instead of `responseFormat.text`, following the
[GenerateContent API reference](https://ai.google.dev/api/generate-content).
The request-shape test preserves this regression fix. The fully bounded schema
also returned HTTP 400. The adapter now moves bounds into descriptions for
Gemini, while preserving the original strict local validators. This simplified
request produced accepted strategy and critique responses in the live run.

A subsequent request returned HTTP 404: Gemini reported that the configured
`gemini-2.5-flash` was unavailable to new users and recommended `gemini-3.6-flash`.
The user approved updating the local `.env` model and using it for the benchmark.
That local configuration is not committed. No production automatic fallback or
model-list-based substitution is implemented.

## Benchmark corpus and commands

`docs/benchmarks/v1_motions.json` contains 12 public-motion scenarios: six policy,
four value, two fact; all four side labels and judge categories are represented.
The benchmark runs preparation, strategy, critique/repair/scoring, a fixed
experimental selection of architecture 1, and final case writing. The fixed
selection is for reproducibility and does not alter the production requirement
for explicit user choice. The final architecture ID and contention titles/order
are checked; this does not prove semantic preservation or strategic quality.

Dry run (no settings, archive or model access):

```bash
.venv/bin/python scripts/benchmark_v1.py --output data/parsed/m16-dry
```

Live run (real provider requests, possible charges, selected private archive
excerpts transmitted to the explicitly chosen provider):

```bash
.venv/bin/python scripts/benchmark_v1.py --output data/parsed/m16-run-new --provider gemini --limit 12 --live
```

Use `--timeout-seconds 120` for a 120-second per-request deadline (default 60).
The output directory must be new. `--model` provides an explicit benchmark-only
model override without rewriting `.env`. Use the same corpus with a separately
configured provider for comparison. No additional account is configured on the
user's behalf. Full packets, stage exports and successful Markdown cases remain
under the gitignored output directory. A summary is checkpointed after every round.

Provider authentication, permission, model, quota or request errors stop the batch
rather than spending further requests on a broken setup. Other round failures
are recorded and subsequent scenarios continue. The process exits nonzero if any
round fails or the planned batch is not completed. Token fields remain absent/null
where a provider did not return usage, including some failed requests.

Quality review is explicitly pending until someone reads the cases and checks
argument strength, evidence, actor/plan coherence, judge fit and spoken usability.
Structural validation and model-generated rubric scores do not establish V1
competitive readiness. A reference comparison needs another configured provider;
Gemini is the only inference provider configured in this workspace.

## Tests

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Regression tests cover the corrected Gemini request, categorized HTTP failures,
usage telemetry, unknown token counts, legacy fingerprint compatibility, malformed
outputs and the full selected-case contract over all 12 corpus scenarios. The
corpus contract tests use simulated responses and are labeled separately from
live evidence; they are not qualitative case benchmarks.

## Recorded live outcome and remaining acceptance work

The completed `m16-gemini-live-02` run attempted all 12 scenarios with
`gemini-3.6-flash` and a 120-second deadline. None completed a final case:

- Ten rounds stopped on HTTP 503 service errors: eight at strategy, one at
  Red Team, and one at repair.
- One round passed strategy and Red Team, then timed out during repair.
- One round returned JSON that failed local strategy validation. The raw output
  was discarded, so its precise validation defect cannot be reconstructed.

There were 17 requests: five accepted stage responses, ten HTTP 503 failures,
one timeout, and one rejected output. Token usage was reported for six responses;
usage for failed requests is unknown. The provider's diagnostic message for 503
was “This model is currently experiencing high demand.” Sanitized provider error
fixtures preserve the observed 400, 404 and 503 classifications.

The earlier `m16-gemini-live-01` attempt stopped after one timeout and one HTTP 400;
it did not run the remaining ten scenarios. Private run artifacts remain local
under `data/parsed/` and are excluded from the commit.

**V1 live acceptance has not passed.** The reliability implementation and offline
regressions are complete, but end-to-end live selection preservation and usable
case quality remain unverified. Completion of those acceptance checks requires a
successful rerun when Gemini is available, review of the resulting cases, and a
comparison on a few matching scenarios with a separately configured stronger
provider. OpenAI and Anthropic credentials are not configured here. No Milestone
17 work should be inferred from this implementation or these results.
