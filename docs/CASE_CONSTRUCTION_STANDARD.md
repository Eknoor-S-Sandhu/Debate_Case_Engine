# Case construction standard

Version: construction-v1. Milestone 1 defines the review contract only; it does
not change prompts, schemas, rendering, scoring, or provider calls.

## Shared standard

Use this contract in future strategy, critique, repair, and writing changes.
Evaluate explanatory quality separately from factual verification. A sound
analytical warrant need not contain a statistic. An attributed statistic does
not establish a causal connection merely by appearing beside it.

1. **Uniqueness:** identify who faces the harm, the present condition or trend,
   the mechanism sustaining it, and why existing responses leave a relevant gap.
   Each background point should support a later step. A solvency condition is
   not evidence that the condition holds. For negative cases, explain what the
   status quo preserves or why the plan worsens an existing harm; a good status
   quo is not universally required.
2. **Warrants:** explain why the actor responds or the outcome follows. Identify
   incentives, constraints, available alternatives, and the premise connecting
   them. Repeating the claim with causal vocabulary is insufficient.
3. **Links:** distinguish sequential steps, alternative causal routes, and
   supporting explanations of the same step. Specify the plan-induced change
   and trace it to the consequence. One defensible route is acceptable; do not
   invent extra routes to meet a quota.
4. **Impacts:** explain the terminal consequence for people or the selected
   framework's objects of concern. Distinguish total problem population,
   reachable population, attributable change, severity, duration, and
   reversibility. Quantify only what evidence supports, keeping geography,
   timeframe, units and denominators consistent. Missing numerical precision
   differs from missing evidence that the effect occurs.
5. **Collapse:** test both within-contention and between-contention independence.
   Identify what survives when one route or the other contention fails, what
   shared premises remain necessary, and why the surviving offense matters in
   the comparison. Different beneficiaries or labels alone do not prove an
   independent winning route. Do not double-count overlapping benefits.
6. **Preempts:** state the objection and defend the mechanism or comparison with
   an explanation. A concession can narrow a claim, but cannot substitute for
   answering the remaining objection. Unresolved central objections remain
   visible; never manufacture an answer.

## How stages should use this standard

- Strategy: construct the causal explanation before expanding it into speech.
- Critique: identify a specific missing connection, the consequence of losing
  it, a plausible opposing response, and a concrete repair goal.
- Repair: strengthen that connection using available evidence or warranted
  analysis. A caveat or research task does not resolve a missing premise.
- Score: use the existing rubric, explaining construction strengths and gaps;
  scores are not calibrated win probabilities or proof of factual accuracy.
- Write/trim/improve: preserve chosen offense and essential warrants. Keep the
  current speech format and brief material qualifications; detailed research
  tasks belong in preparation notes. Remove repetition before reasoning.

Value and fact cases use reasons, evaluative/truth standards and conclusions
rather than artificial policy UQ/L/IL requirements. Alternative frameworks may
terminalize harm to nonhuman objects of concern. NYPDL continues to exclude
motion-unrelated voting arguments, theory, Ks and tricks.

## Evaluation set and review procedure

The annotated source-derived set is stored locally at
`data/parsed/construction-reform-m1/evaluation-examples.json`. It is intentionally
inside the existing private, gitignored archive boundary. Do not publish the
source documents, extracted text, generated case, or private annotations.

The set contains original summaries, not reusable evidence cards. Source page
numbers are one-based PDF pages; generated-case references name the section.
Every example has a dimension, scoped strong/weak/mixed judgment, expected
findings, repair target, and a guard against overclaiming. Judgments concern the
specified passage, not the quality of the entire case. Some examples expose
missing terminalization; their missing material is not a positive exemplar.

For future model evaluation, send only the example ID, dimension, summary and
source-status warning. Keep expected findings, judgment and repair target
withheld as the review key. Never feed the answers into the scored request.
No source example is automatically added to retrieval or inference context.

Review each result against the expected findings. Record detected/missed findings,
unsupported criticisms, proposed repair, and remaining factual uncertainty.
Report results by dimension without treating this small, curated set as a
statistical quality estimate. Model grading requires human inspection.

## Milestone status and next boundary

Milestone 1: standard and annotated examples created and locally checked for
coverage and valid source locators. No live model evaluation performed.
Milestone 2: structured strategy construction analysis and compatibility checks.
Milestone 3: critique/repair/scoring enforcement and visible selection risks.
Milestone 4: drafting, trimming and improvement behavior.
Milestone 5: controlled and full-pipeline comparisons, then broader validation.

Pause after each milestone for the user's instruction. Evidence warnings do not
block user selection. Construction precedes new research loops; performance
optimization remains gated on human quality approval.

## Milestone 2 implementation

Strategy prompt version `construction-v1-strategy` requests `construction` for
all new contentions. The optional preparation object contains a status-quo barrier,
proposed change, 1–3 causal routes, 1–3 terminal outcomes, shared dependencies and
surviving ballot argument. Routes cite one-based existing warrant numbers and
source IDs already attributed to their contention. Parent source-pool checks
therefore also cover route citations. Outcomes separate problem population,
reachable population, attributable change, severity, duration and evidence gaps;
unknown quantities remain null. Value/fact comparisons can omit a policy barrier.

Absent/null construction is omitted on serialization, preserving historical hashes.
Strict provider schemas require the field (nullable), while legacy parsing allows
omission. Missing analysis produces a warning, not a drafting or selection gate.
NYPDL's existing explicit off-motion screen also examines construction metadata;
this is not an exhaustive semantic classifier. No additional inference calls,
research, UI sections, critique or writing instructions were introduced here.

Validation: full pytest suite passed, including generation for policy/value/fact,
invalid warrant/source references, legacy serialization, missing-analysis warnings,
and NYPDL metadata screening. All 39 locally saved strategy/evaluation JSON objects
retained identical compact serialization. These checks establish compatibility and
structural behavior, not live model construction quality. Live comparison remains
Milestone 5. Next boundary: Milestone 3 evaluation and selection presentation.

## Milestone 3 implementation

Evaluation prompt version `construction-v1-evaluation` applies the standard to
critique, repair and the unchanged 100-point scoring rubric. Critiques distinguish
central mechanisms, numerical precision and other gaps with optional `gap_kind`.
Absent historical classifications are omitted on serialization and shown as
unclassified, rather than guessed. New strict schemas request the nullable field.
Repair instructions prohibit treating caveats or verification tasks as substantive
resolution and require updating any construction map alongside the prose.
Scoring instructions demand concrete reasons for credit and unresolved weaknesses.

The strategy UI displays high-severity unresolved/partially addressed findings
joined by architecture ID and finding number. Warnings include category, location,
status and repair explanation; they do not disable selection. Expandable architecture
details expose routes, warrant/source references, assumptions, outcomes and shared
dependencies. Collapse summaries are labeled proposed rather than established.

Validation: mocked evaluation checks the three-stage contract, classification,
warning joins, selection despite risk, and preservation across UI reruns. Historical
finding serialization and all 12 saved evaluation objects retain identical JSON.
Old artifacts remain loadable; scoring recovery across different prompt versions
is intentionally rejected by the existing version check. No historical files were
rewritten. No live model call or calibrated semantic-quality evaluation occurred:
the curated expected-findings set remains the review key for Milestone 5, and
prompt instructions do not prove that a model will identify every cosmetic repair.

## Milestone 4 implementation — 2026-09-29

Writer prompt version `construction-v1-writer` applies the standard to drafting,
optional trimming and final improvement. The selected critique now accompanies
its repaired architecture in every writing request, so finding numbers and repair
statuses have their original context. Existing construction maps are retained;
legacy selected strategies remain usable without inventing replacement offense.

Instructions require connected uniqueness, behavioral warrants, honest dependencies,
terminal consequences and substantive preempts. Detailed research tasks remain in
preparation notes while material uncertainty remains beside the spoken claim.
Trimming prioritizes repetition over essential reasoning. The existing renderer,
speech schema, selection rules, source checks and inference-stage count are unchanged.

Scripted pipeline tests cover two-pass and trim-required writing, selected map and
critique transport at every stage, prior validated draft handoff, source attribution,
verification notes, speech formatting, word budget and input immutability. These
checks verify transport and contracts, not actual model reasoning quality. The trim
fixture was corrected to exceed the speech budget without exceeding per-point text
limits, and handoff comparison uses normalized validated text. Live comparisons and
human review remain Milestone 5; no new case was generated in this milestone.
