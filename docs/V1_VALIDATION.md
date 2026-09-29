# V1 live validation after Milestone 17

V1 acceptance remains pending. A completed pipeline establishes transport and
structural validity; it does not establish competitive quality. The quality findings below are agent reviews of saved artifacts unless explicitly
labeled as human feedback; they are not independent human ratings or tournament
results.
Private packets and full case text remain under gitignored `data/parsed/`.

Current checkpoint (2026-09-12): three completed live cases across policy and
value. The expanded batch completed two of three rounds; its fact round timed
out at critique. All three successful saved cases pass source, structure and
handoff-fingerprint revalidation. No completed fact case or research-enabled
live case has yet been established in this validation series.

## First successful round

`m18-codex-test-07/transit-gov`: government, policy, flow judge. The directory
name does not signify completion of Milestone 18.

- Completed six requests in 596.465 seconds, with no recorded stage failures.
- The speech was 859 words against a 975-word budget. Its estimated reading
  time was 343.6 seconds at 150 words/minute; no aloud rehearsal was performed.
- Architecture 1's contention titles and order survived. Reading the original,
  repaired architecture and final case also confirms the two core mechanisms:
  savings on existing trips and access to previously unaffordable trips.
- Revalidating saved strategy, repair and case objects passes source-ID and quote
  checks. Strategy and selected-evaluation handoff fingerprints also match.
- Preparation returned 23 archive items and no research sources. Research status
  was `missing_credentials`; zero search queries were attempted. Empty retrieval
  coverage gaps therefore must not be interpreted as sufficient factual evidence.

### Quality findings

The strongest feature is causal discipline. The case separates existing-trip
savings from new-trip outcomes, avoids counting earnings twice, and distinguishes
attending an interview from getting a job. The proposed actor is jurisdiction
neutral, consistent with an unspecified motion, and the plan covers funding,
timing and enforcement. Fiscal feasibility remains unsupported.

Evidence is the main limit. One contention is new reasoning; the other adapts an
undated transport-opportunity argument in the archive. The final case does not
repeat that source's unverified numerical or sweeping impact claims. It treats
the mechanism as a hypothesis, which is appropriate, but leaves beneficiary
prevalence, service capacity, funding incidence and realized outcomes unresolved.

The repair addresses criticism mainly by bounding claims and conceding strong
alternatives. The final speech repeatedly identifies conditions under which
universal abolition could win without establishing that those conditions hold.
Automatic concessions and immediate hardship support remain an unanswered
comparative challenge. Honest qualifications should be retained; making the
language more confident would not repair this evidentiary deficit.

Flow-oriented causal structure is clear, but the opening weighing paragraph and
repeated qualifications are dense for speech. The two contentions have different
immediate mechanisms but share exposure to financing, service quality and effective
targeting objections. The model's 77/100 score is not an independent quality rating.

Disposition: structurally successful, evidence-limited practice draft; not yet a
competition-ready affirmative. Initial human feedback is recorded below; full
strategic review and spoken rehearsal remain pending.


### Human feedback — 2026-09-12

Reviewer: user. Artifact: `data/parsed/m18-codex-test-07/transit-gov/case.md`.
This records the user's requested changes; it does not mark them as implemented.
No overall good/bad verdict, numerical score, or aloud timing was supplied.

1. **Highest priority: make the language much simpler.** The user finds the case
   hard to read and needs clear, concise, simple language to understand and follow
   it. This applies throughout the case, not just to the opening or plan.
2. **Give the weighing mechanism an explicit name**, such as "Net Benefits" or
   "Structural Violence." If it is not Net Benefits or something equivalent,
   include warrants explaining why the judge should prefer it over Net Benefits
   when necessary.
3. **Remove the roadmap of the advantages.** The user does not need it.
4. **Use simple plan-text defaults.** Default to the resolution with "will"
   instead of "should," adding specifications when strategically useful. For
   this motion: "The government will make public transport free."
   - Funding: "Normal ways and means."
   - Timeframe: "ASAP."
   - Enforcement: "Normal ways and means."

Status: feedback recorded; case revision and engine changes are pending.

### Engine response to human feedback — agent record, 2026-09-12

The human feedback above is preserved as originally recorded. The following is
an implementation/validation record by the agent, not further human feedback or
human approval.

Case-writing prompt version `milestone-14-v2-human-feedback` applies the user's
requirements to drafting, trimming and final improvement:

- Makes clear, concise, simple language the highest writing priority throughout
  the speech, including causal steps, weighing and preempts. Requests short,
  direct sentences and concrete examples while retaining necessary uncertainty.
- Requires an explicit framework name, with a plain explanation of the comparison.
  Non-Net-Benefits frameworks need a reason for preference when that choice needs
  justification. Value criteria must not assume the motion's conclusion.
- Prohibits an advantage roadmap, including one disguised as observations. Keeps
  substantive observations when necessary and preserves required value/fact scope.
- Defaults the transit plan to "The government will make public transport free."
  Funding/enforcement default to "Normal ways and means." and timeframe to "ASAP."
  Additional detail must serve the selected mechanism, motion or a concrete objection.
  These plan conventions do not establish fiscal or practical feasibility.

The renderer now displays the weighing mechanism for value cases as well as
policy/fact cases; it previously hid this field in value exports. Empty sections
remain omitted. No heuristic deletes model-generated prose or silently replaces
its plan: roadmap removal and simple plan choices are writing instructions, whose
actual compliance must be checked in the live artifact.

Checks before the live run: all 591 tests passed; the focused case/reliability/CLI
suite passed 89 tests; changed case-writing files passed Ruff and whitespace checks.
The existing full-project long-line warning noted below is unrelated to this edit.

The user explicitly authorized one new `transit-gov` benchmark through the
configured Codex CLI provider with relevant local material. New output directory:
`data/parsed/v1-transit-gov-human-feedback-01`. Request deadline: 600 seconds.
Research was still unconfigured at launch. Original artifact fingerprints were
saved for a preservation check. This reruns upstream generation as requested,
so differences in the selected architecture can also affect the comparison;
it is not a controlled comparison of only the case-writing prompt.

Live result and agent comparison: pending completion. Human review of the new
artifact and V1 acceptance remain pending.

## Repeatable targeted runs

Select IDs with repeated `--scenario` options. Selection retains corpus order,
removes duplicates, and applies `--limit` after filtering. Unknown IDs fail before
settings or model access. Omit `--live` to inspect the planned selection offline.

```bash
.venv/bin/python scripts/benchmark_v1.py \
  --output data/parsed/v1-codex-next \
  --provider codex_cli \
  --scenario transit-opp --scenario privacy-aff --scenario social-neg \
  --timeout-seconds 300 --live
```

The 300-second request deadline accommodates the first round's 215.979-second
repair stage, which would exceed the benchmark's default 120-second deadline.
The benchmark continues to use fixed architecture 1 for reproducibility, not
automatic best-architecture selection in the product.

`v1-codex-validation-01` attempted these three rounds from the restricted execution
environment. Each stopped at strategy in under 0.3 seconds with `provider_error`;
none returned output or reported usage. Raw diagnostics were discarded by design,
so these records alone do not establish the exact cause or whether any remote
request was transmitted. They are execution failures, not quality evaluations.

## Expanded live batch

`v1-codex-validation-02` retries the same selection with expanded local execution
access. This process loaded the code before the renderer and research-summary
changes below; its saved exports retain the older rendering and report fields.

### Transit opposition — policy, fully lay judge

Completed seven requests in 633.430 seconds, including a trim pass. The final
speech is 850/1125 words, with the repaired architecture's contention titles and
order preserved. Research again reports missing credentials and zero sources;
23 archive items were retrieved, but neither selected contention cites a source.

The speech uses accessible examples: a worker whose shift ends after the last
bus and passengers missing connections when vehicles are full. It makes a
positive comparison through hardship exemptions plus service investment and
correctly separates net revenue from gross fares. The funding and physical
capacity arguments preserve the original architecture's mechanisms, although
repair revised their titles, as allowed before final selection.

Both routes still depend on unestablished conditions: a binding common budget,
useful revenue after collection and exemption costs, and overlapping demand on
routes that cannot expand in time. A funded, capacity-first government plan is
conceded to answer much of the case. The second contention risks becoming an
implementation-sequencing objection rather than a reason to retain fares in
principle. Hardship eligibility also remains broad rather than operationally
precise. Repeated conditional instructions sound more like coaching notes than
a fully persuasive lay speech.

Disposition: structurally successful, clear practice framework, but evidence and
comparative win conditions remain conditional. The model's 74/100 score is not
an independent quality rating. Human review and aloud rehearsal remain pending.

### Privacy affirmation — value, flay judge

Completed six requests in 541.165 seconds without trimming. The final speech is
741/975 words and preserves the selected contention titles and order. It uses
human dignity as its value, includes a criterion and observations, and contains
no policy plan. Preparation again supplied 23 archive items and no research.

This is the most promising speech reviewed so far. Diary and confidential-friend
examples explain intrinsic disclosure control and relational obligations without
depending on unverified psychological effects. Repair strengthened both routes
by explaining a wrong that can exist even if behavior never changes. The one
archive adaptation retains its uncertainty rather than presenting observation
as proof of psychological injury.

The security exception is specific: grave danger, a credible preventive link,
no comparably effective less intrusive option, and proportional scope/duration.
That is more defensible than an absolute privacy veto. However, the criterion
already assigns privacy presumptive priority. The case must still justify why
this hierarchy follows, rather than merely showing that privacy has value and
that negligible security gains do not automatically outweigh it. Both contentions
depend on disclosure control having independent moral weight; their relational
and individual accounts differ but are not wholly insulated from that objection.
The long criterion and source-audit language could be made easier to deliver.

Disposition: promising value-debate practice draft, pending adversarial human
review of the priority argument and aloud rehearsal. Missing empirical research
is less damaging to its explicit normative reasoning than to the transit cases,
but does not support its contingent behavioral claims. The model's 91/100 score
must not be treated as an externally validated quality result.

### Social-media negation — fact, flow judge

Strategy completed in 112.459 seconds. Red Team then timed out at 300.055
seconds, leaving no accepted critique or final case. Round latency was 413.039
seconds. This is a timeout failure, not a rejected argument or a quality rating.
The saved accepted strategy and packet permit a recovery beginning at evaluation.

The entire expanded batch made 15 recorded inference calls: 14 received responses
and one timeout. Its two completions are useful breadth evidence, not a reliable
estimate of long-run success rates. No later run overwrites this failure.

A proposed recovery uses the saved fact packet and strategies, fixed architecture
1, a 600-second request limit, and a new output directory. Automatic approval
review rejected execution pending explicit permission to send that saved private
payload through ChatGPT-authenticated Codex CLI. No recovery calls were made.

## Validation-driven changes

- Added targeted scenario selection to avoid repeating unrelated rounds.
- Future benchmark rows record research status, source count and archive item
  count, making missing research visible alongside completion status.
- Case rendering omits empty optional sections and blank plan fields for
  status-quo opposition. Saved historical exports are preserved unchanged.
- The benchmark accepts request deadlines up to 600 seconds, matching existing
  provider settings. Its default remains 120 seconds; this does not establish
  that longer waits fix the observed timeout or meet real prep-time requirements.
- Removed temporary raw exception output from rejected strategies, restoring
  safe diagnostics without changing validation rules. A regression test checks
  that rejected private content is not included in exported errors.

The earlier validation pass did not change generation prompts, provenance checks,
provider defaults or later milestone features. The subsequent human-feedback
revision above updates case-writing instructions and their exported version.

Validation: 591 tests pass. Changed Python files pass Ruff and whitespace checks.
Full-project Ruff still reports a pre-existing long line in `strategy_prompt.py:8`.

## Remaining acceptance work

- Complete and review additional live policy, value and fact rounds with different
  sides and judge categories; then extend to the remaining corpus scenarios.
- Repeat matching scenarios to measure reliability across runs, not just breadth.
- Test research-enabled preparation once the configured research service is
  available, and inspect whether its supplied evidence resolves decisive gaps.
- Compare a few matching scenarios with another configured provider when available.
- Obtain human strategic review and aloud timing before declaring usable case quality.

The user selected research-enabled validation as the next direction. Tavily
configuration is pending in the local environment; do not ask for keys in chat.
The next milestone remains V1 readiness, not topic/side selection or live refutation.


## Follow-up human feedback — 2026-09-27

The user reviewed the revised transit-government case and requested:
- Use exactly "Net Benefits" without explanation when that is the framework.
  Other frameworks need a justification for preference over Net Benefits.
- Develop terminal impacts, including the affected population, supported magnitude
  of benefit and why it matters, rather than stopping at savings or opportunity.
- Design contentions for independent later-round collapses. For this motion the
  preferred mix is poverty and environment, each with its own ballot story, rather
  than two closely related affordability routes.

Engine instructions now apply these preferences to writing, strategy construction,
critique, repair and scoring as relevant. Quantities require supplied evidence;
missing quantities remain research needs. No new live case has been generated with
these instructions and human acceptance remains pending.

The earlier feedback rerun did complete: its saved report records 817/975 words,
seven requests, 693.538 seconds, preserved selection, and no research sources
(`missing_credentials`). This supersedes the pending-run note above, not the
pending human acceptance decision. The user has a Tavily key to configure locally.


## NYPDL/UI segment and research checkpoint — 2026-09-27

The current work is segmented at the user's request:
1. NYPDL permissions, profile rules, UI polish, saved-checkpoint loading and validation.
2. Research-backed transit case: complete scoring, human architecture selection,
   case writing, strategic review and aloud rehearsal.
3. Broader V1 validation across fact/value/policy and repeated runs.
4. Performance optimization after human quality approval.

Tavily is configured and verified. `v1-research-transit-20260928` preserves an initial
restricted-network preparation failure and a successful network-enabled retry
(`packet-research.json`): three queries, 11 research sources, 23 archive items.
A local review retained five relevant sources and added explicit limitations in
`packet-reviewed.json`; original excerpts and unverified labels were preserved.
The source-review record documents direct/indexed access and unresolved evidence.

The user specifically approved sending the reviewed private archive/research packet
to ChatGPT-authenticated Codex CLI after automatic approval review requested that
specific egress approval. Strategy, critique and repair completed. Scoring failed
with `rate_limit_or_quota`. Strategy and partial evaluation are saved; no selection
or case writing occurred. Do not retry or change providers while the user-requested
segment pause is in effect. A future recovery should reuse accepted earlier stages
rather than repeat the whole run, and must retain handoff/source validation.

Preparation now records retrieval/research timing outside packet schemas; existing
inference timings remain. No claim of speed improvement or V1 acceptance is made.

Segment 1 completed: implementation tests and full-project Ruff/whitespace checks
passed. The full suite passed before the checkpoint loader was added; the affected
UI/agent suites and loader tests passed afterward. All 25 historical saved
packet/strategy handoffs matched their original fingerprints. Desktop (1365px) and
mobile (390px) visual checks passed for setup and saved strategy comparison, including
stacked cards. The localhost preview was restarted after a stale-module import error;
the restarted app successfully loaded the real reviewed research checkpoint without
making provider calls. The research evaluation contains three accepted critiques and
three accepted repairs, with no rankings or selection because scoring hit quota.

Work is paused after Segment 1 per the user's instruction. No further provider calls,
case generation, broader benchmarks, or performance optimization until they continue.

## Segment 2 resumed — scoring recovery

The user authorized continuation. The existing, specifically approved transit
packet was reused through the same Codex CLI provider. A scoring-only recovery
completed in 52.697 seconds and saved `evaluation-resumed-01.json`. Original
strategy/critique/repair/failure artifacts remain unchanged; the recovered result
retains their call diagnostics. Three repaired options received model scores:
poverty/environment 66, healthcare/enforcement 62, operations/social participation
58. These are subjective scores, not independent human assessments.

The app and CLI now support this recovery without rerunning accepted critiques or
repairs. The latest completed evaluation loads in the UI with no selection. The user
has been asked to choose the repaired strategy before case writing. The full test
suite and Ruff passed after the recovery change. The broader three-scenario subset
(transit-opp, privacy-aff, social-neg) passed dry-run selection; no new broader live
benchmark or performance optimization has run at this checkpoint.

## Selected research case completed — 2026-09-28

The user selected repaired architecture 1 (poverty/environment). Selection is saved
in `evaluation-selected-01.json`. The first writing attempt saved failure diagnostics
in `case-option-1.json`: draft accepted at 820 words, final improvement hit quota.
The internal draft was not persisted, so recovery required repeating drafting.

Authorized continuation completed draft and improvement in 81.548 and 83.678 seconds
respectively (165.226 seconds for writing calls only, not full engine runtime).
New artifacts: `case-option-1-retry-01.json`, `case-option-1-retry-01.md`, and the
speech-only `speech-option-1-retry-01.md`. Earlier artifacts were preserved.
The case is 862/975 words, estimated 344.8 seconds at 150 wpm, leaving 75.2 seconds
of a seven-minute speech. No trim call was needed. Saved source/quote checks,
selected contention structure, all three handoff fingerprints, exact Net Benefits
wording and word budget passed. Full pytest suite, Ruff and whitespace checks passed.

Agent quality review: terminal outcomes are explicit (food/utility deprivation and
climate-related harm), and the two routes concern distinct beneficiaries/mechanisms.
However neither independent full-cost ballot threshold is established. The speech
repeatedly concedes unresolved comparisons with automatic concessions and service
investment; beneficiary counts and terminal-impact magnitudes remain unquantified.
The Luxembourg estimate is appropriately bounded and not treated as proof of local
health gains. This is a completed research-informed practice draft, not human quality
acceptance or a competition-ready case. Human review and aloud rehearsal are pending.

Next: review this draft with the user; resolve geographic scope and decisive evidence
gaps before claiming quantified impacts. Broader fact/value/policy validation and
repetitions remain outstanding. Performance optimization remains gated on human
quality approval; this isolated writing duration does not establish the under-five-
minute full-engine target. Persisting validated intermediate case drafts for safe
improvement-only recovery is a reliability follow-up, not implemented here.
