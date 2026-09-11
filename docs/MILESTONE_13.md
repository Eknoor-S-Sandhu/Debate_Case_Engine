# Milestone 13 — Red Team, repair, and strategy selection

This stage takes the completed Milestone 12 architecture export and its original
Knowledge Packet. It performs one critique pass, one repair pass, and one scoring
pass across all three architectures. The user chooses the architecture afterward.
Milestone 14 is outside this implementation: no case writer, speech-length/time
budget, or final case-improvement pass is invoked.

## Workflow and contracts

1. **Red Team:** Each architecture receives concrete weaknesses, hypothetical
   opponent responses, severity, affected contention (or architecture overall),
   rubric criterion, and repair goal. At least one finding per architecture is
   required; affected contention numbers must exist.
2. **Repair:** Each architecture retains its ID and name, returns a revised outline,
   records changes, and responds to every finding exactly once. Responses distinguish
   addressed, partially addressed, and unresolved findings. Remaining risks are
   mandatory. Revised outlines pass Milestone 12's structure, citation, quotation,
   freshness, theory/K eligibility, and diversity checks again. Repair is one pass;
   unresolved weaknesses do not trigger an automatic retry loop.
3. **Scoring:** The repaired architectures receive bounded integer scores and a
   rationale for every rubric criterion, plus comparative tradeoffs. Totals and
   rankings are calculated locally, never accepted from model output.
4. **User choice:** All three are ranked; none is automatically selected. The user
   may choose any of them. Selection records the original architecture ID alongside
   its repaired outline, critiques and scores in the export, without a model call.

The rubric from the project's “Build Debate Agent” roadmap is:

- Win condition strength: 20 points
- Link-chain quality: 20 points
- Preemptive value: 15 points
- Uniqueness: 10 points
- Diversity of offense: 10 points
- Impact quality: 10 points
- Judge fit: 10 points
- Novelty/surprise: 5 points

Maximum total: 100. Ties share their competition rank (for example 1, 1, 3),
and tied entries display in original architecture-ID order. Scores are subjective
judgments, not calibrated win probabilities. The prompts adapt reasoning standards
to policy/value/fact rounds and specific judge preferences. Automated validation
cannot establish argument quality, evidence entailment, strategic identity beyond
IDs/names, or whether the proposed repair really defeats an objection.

## Run in the UI

Prepare a Knowledge Packet, generate three architectures, then click
**Evaluate three architectures**. Inspect the Red Team findings, repaired outlines,
remaining risks, rubric scores and tradeoffs. Choose an architecture and click
**Confirm architecture choice**, then download the evaluation and choice JSON.
Changing the dropdown alone does not replace a previously confirmed choice.
Regenerating architectures or submitting a new plan/packet clears the evaluation
and choice. Selection and ordinary UI reruns do not repeat evaluation requests.

## Run from the command line

From the repository root, using exported packet and architecture JSON files:

```bash
.venv/bin/python scripts/evaluate_strategies.py evaluate knowledge_packet.json strategy_architectures.json
.venv/bin/python scripts/evaluate_strategies.py evaluate knowledge_packet.json strategy_architectures.json --json > strategy_evaluation.json
.venv/bin/python scripts/evaluate_strategies.py select strategy_evaluation.json 2 > selected_strategy.json
```

The last command chooses original architecture ID 2, regardless of its rank.
It works offline and never calls a provider. Keep exports beside their original
packet for source lookup. Failed evaluations exit with code 1; JSON mode still
provides their status, failed stage, warnings, and any earlier validated work.

## Configuration and limits

Evaluation reuses the explicit `DEBATE_ENGINE_STRATEGY__ALLOW_REMOTE`, `API_KEY`,
and `MODEL` configuration and Responses adapter from Milestone 12. It sends the
round context, selected excerpts, judge notes, architectures and intermediate
critique/repair output to the configured OpenAI model. Each run makes up to three
sequential requests and may consume provider credits. The existing per-request
input/output size limits, socket timeout, no-redirect policy, no-retry policy,
and `store=false` request setting apply. Input size is checked before every stage;
large intermediate outputs can exceed the configured input budget and stop a run.

Offline prep blocks all stages before provider access, including injected providers.
Missing configuration makes no network call. Input must be a completed strategy
set with a matching packet fingerprint. The original source pool cannot expand:
only the source IDs supplied during generation are eligible for evaluation/repair.
Changed context limits that make those sources unavailable require restoring the
limits or regenerating architectures. Current eligible excerpts must still support
any exact quotes. No fresh searches or factual verification occur during repair.

Provider failure, refusal, malformed output or contract failure stops immediately.
Earlier validated critiques/repairs remain inspectable, but incomplete evaluations
have no rankings or selection. Raw provider error text is not exported. Packet and
strategy fingerprints bind the evaluation to its input versions; they are integrity
identifiers, not cryptographic proof of authorship or semantic correctness.

## Verification

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Tests exercise stage order and handoffs, exact three-ID coverage, source limits,
invalid repairs and scores, ties, failure redaction, early stops, explicit selection,
CLI exports, and Streamlit state invalidation. Existing Milestone 12 tests continue
to cover the shared provider transport and source validator. Tests use simulated
provider responses; no paid live model run or qualitative benchmark is implied.
