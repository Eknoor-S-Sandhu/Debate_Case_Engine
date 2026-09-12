# V1 live validation after Milestone 17

V1 acceptance remains pending. A completed pipeline establishes transport and
structural validity; it does not establish competitive quality. These are agent
reviews of saved artifacts, not independent human ratings or tournament results.
Private packets and full case text remain under gitignored `data/parsed/`.

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
competition-ready affirmative. Human review and spoken rehearsal remain pending.

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

## Validation-driven changes

- Added targeted scenario selection to avoid repeating unrelated rounds.
- Future benchmark rows record research status, source count and archive item
  count, making missing research visible alongside completion status.
- Case rendering omits empty optional sections and blank plan fields for
  status-quo opposition. Saved historical exports are preserved unchanged.

No generation prompts, provenance checks, provider defaults or later milestone
features were changed in this validation pass.

## Remaining acceptance work

- Complete and review additional live policy, value and fact rounds with different
  sides and judge categories; then extend to the remaining corpus scenarios.
- Repeat matching scenarios to measure reliability across runs, not just breadth.
- Test research-enabled preparation once the configured research service is
  available, and inspect whether its supplied evidence resolves decisive gaps.
- Compare a few matching scenarios with another configured provider when available.
- Obtain human strategic review and aloud timing before declaring usable case quality.
