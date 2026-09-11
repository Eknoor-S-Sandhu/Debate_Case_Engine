# Milestone 14 — Case Writer, speech budget, and final improvement

The case writer expands the user's explicitly selected repaired architecture into
a finished case, checks its speech budget, optionally trims an overlong draft,
and performs one final improvement pass. This implements the core case-writing
stage; optional topic/side selection and live refutation remain outside scope.

## Case format

Formatting is adapted from the user's original Case Writer prompt attached to
“Build Debate Agent.” The case renderer produces copyable Markdown with the
Topic, Side, Round, appropriate framing, and numbered points with bold taglines.
It preserves the selected contention titles and order and accepts two or three
contentions. The model is instructed to preserve core offense, judge adaptation,
plain language, short points, and embedded preempts.

Policy includes Observations, Definitions, Inherency, Plan text/CP, and Solvency
headers. Optional sections may be empty. Affirmative/government requires a plan
with action, actor, enforcement actor, funding, timeframe and enforcement.
Opposition can defend status quo with a blank plan block. Contentions render as
ADs for affirmative/government and DAs for negative/opposition, with 3–5 UQ points,
2–3 L points, 0–3 IL points, and 1–2 terminal impact points plus preempts.

Value requires Value and Value Criterion. Fact requires a Weighing Mechanism /
Threshold of Truth. Both require observations and use Claim, 3–5 Warrants, and
1–2 Impacts per contention, with embedded preempts. The renderer omits all policy
plan/inherency/solvency sections from value/fact cases.

Only source IDs from the original generation's eligible source pool may be used.
Exact quotations must match the supplied excerpt, cite a source used by the point,
and appear in that point's text. Source references are retained per point in JSON;
Markdown preparation notes list used archive filenames and research titles/URLs.
Assumptions and verification needs are separate from the timed speech. Research
snippets and stale archive evidence remain unverified. There are no new searches.

## Speech budget and improvement

Government/affirmative gets 7 minutes; opposition/negative gets 8 minutes.
Default reading speed is 150 words per minute with 30 seconds reserved for pauses:
975 words for government, 1,125 for opposition. These are adjustable assumptions,
not measured speaker speeds or tournament rules inferred from the prep duration.
Allowed speeds are 80–400 wpm, with 0–120 seconds reserved.

The local word counter includes speech text, headings, numbered taglines and plan
fields conservatively. It excludes appended preparation notes and UI metadata.
Word limit = floor((speech seconds − reserve seconds) × words per minute / 60).
Estimated duration = counted words × 60 / words per minute. Rehearse aloud to
account for delivery, pauses and the pronunciation of numbers or abbreviations.

The sequence is bounded:

1. Draft the case and validate its structure and sources.
2. If over budget, request one trim, prioritizing redundancy, unnecessary
   background and low-value elaboration before causal links or terminal impacts.
3. Perform one silent final improvement pass for competitive strength, evidence,
   clarity, organization, contradictions, redundancy and length. Validate again.
4. Publish only if the final case fits the budget. Otherwise return `over_budget`
   with no final text. There is no arbitrary truncation or retry loop.

The UI shows the final case, selected strategy score, timing estimate, and relevant
preparation notes. It does not show draft genealogy or a self-improvement report.
The model's qualitative success and factual truth cannot be guaranteed by schema,
source-ID, quote and word-count checks. Tests use simulated provider responses;
no paid live model test or qualitative case benchmark has been performed.

## Using the UI

Prepare a packet, generate architectures, evaluate, and confirm a choice. Under
**Write your case**, adjust reading speed/reserve and click **Write final case**.
Download Markdown for copying into a document, or JSON for structured reuse.
Submitting a new round, regenerating architectures, rerunning evaluation or
confirming a choice clears the old case. Changing timing controls alone does not
rerun paid generation; displayed timing always reflects the last submitted values.

## Using the CLI

From the repository root, using the matching exported files:

```bash
.venv/bin/python scripts/write_case.py knowledge_packet.json strategy_architectures.json selected_strategy.json
.venv/bin/python scripts/write_case.py knowledge_packet.json strategy_architectures.json selected_strategy.json --words-per-minute 160 --reserve-seconds 30 --json > debate_case.json
```

`selected_strategy.json` is the completed evaluation with an explicit choice from
Milestone 13. The writer checks packet and strategy fingerprints before provider
access. No top-ranked architecture is selected by default. JSON includes the
selected strategy score, fingerprints, budget, word count, duration estimate,
structured case and rendered Markdown. Non-completed output exits with code 1.

## Configuration and boundaries

Reuse the Milestone 12 `DEBATE_ENGINE_STRATEGY__ALLOW_REMOTE`, `API_KEY`, and `MODEL`
settings. Writing makes two provider calls, or three when trimming is needed.
Each request uses the existing size/output limits, timeout, no-redirect/no-retry
behavior, and `store=false`. Selected archive excerpts, judge notes, selected
architecture, repair notes, and intermediate case text are sent to OpenAI.
Input size is checked before every request. Provider failures/refusals or invalid
output stop immediately and never expose an intermediate draft as a final case.

Offline prep remains blocked before any provider call, consistent with the
existing cloud-only generation pipeline. The original prompt's offline analytical
case mode is not runnable without a separately implemented local provider; this
milestone does not bypass prep rules by sending offline material to the cloud.
The application does not create native Google Docs or DOCX files in this stage.

## Validation

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Tests cover policy/value/fact formatting, all four sides, chosen architecture
identity, timing, trim/improvement ordering, quote/source/freshness checks,
configuration/offline/input gating, failure redaction, and CLI/UI integration.
