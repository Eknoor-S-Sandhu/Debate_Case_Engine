# NYPDL preparation and research practice

## Local setup

The project-root `.env` is gitignored. Add or replace this single active entry:

```dotenv
DEBATE_ENGINE_RESEARCH__API_KEY=your_actual_key
```

Do not paste the key into chat, exports, or round JSON. Restart Streamlit after
changing it, from the repository root:

```bash
.venv/bin/python -m streamlit run ui/app.py --server.address 127.0.0.1
```

The advanced connection panel reports only whether a key is configured. Preparing
a research-enabled round makes real Tavily requests; previewing a plan does not.

## Permissions and profiles

`prep_rules.internet_allowed` controls web research. The new optional
`prep_rules.cloud_inference_allowed` separately controls generation, evaluation,
and writing. When absent or null, it falls back to `internet_allowed`, preserving
legacy offline behavior. Explicit false blocks even injected providers.

Exactly 15 minutes with research disabled resolves to NYPDL. All other settings
resolve to general. The UI explicitly enables cloud access by default; the JSON
contract does not silently enable it for old inputs. For example:

```json
{
  "motion": "THW make public transport free",
  "side": "gov",
  "round_type": "policy",
  "prep_rules": {
    "minutes": 15,
    "internet_allowed": false,
    "cloud_inference_allowed": true
  }
}
```

NYPDL disables theory/K retrieval even when inclusion controls or judge notes ask
for it. Knowledge/context construction also excludes structurally labeled tricks.
Generated theory/K styles are rejected, along with explicit automatic-win patterns;
trusted profile instructions additionally prohibit off-motion offense. These checks
are not a complete semantic classifier: a substantive-labeled disguised trick can
still require critique and human review. Motion-focused moral/environmental weighing
and ordinary clarification remain allowed. Definitions, scope, intensity and fair
opposition ground are checked through critique/repair instructions.

Source: the user-supplied NYPDL Rulebook 2026–27, sections 3–5 and 9–13. This is the
user's archive-plus-AI/no-web adaptation, not full tournament compliance. The rulebook
also restricts prewritten materials, AI and in-person computer use.

Opening speeches retain 7-minute GOV and 8-minute OPP limits, with user-configured
reserve for pauses and POIs. Grace time is not added. Constructive offense should
support independent collapses; future rebuttal generation is not implemented.

## UI workflow

Round setup → Sources → Strategies → Final case. Model settings and diagnostics
are collapsed. Strategies show ballot stories, contention impacts and verification
needs, with explicit selection after evaluation. Final speeches separate source
notes from delivery text. Three columns stack on narrow screens.

Unchanged resubmissions reuse the current packet and preserve downstream work.
Submitting changed or invalid round settings clears dependent results. Regenerating
strategies clears evaluation and the case; confirming a different architecture clears
the case. Ordinary widget reruns do not make provider calls.

Confirm sides and start the optional timer after previewing/submitting the round.
It starts only on that button, persists through reruns and expires at zero. A changed
submitted round resets it. It is a guide, not an inference deadline. The timer can be
restarted explicitly with the same button.

Open a saved checkpoint loads local packet/strategy/evaluation files without model
calls and verifies their handoff fingerprints. It finds the matching packet when a
run contains both original and reviewed variants. Historical exports are not rewritten.
Missing new permission fields are omitted on serialization to preserve old hashes.

## Research and performance checkpoints

One concept per line now creates separate bounded research queries (up to the existing
three-query limit), followed by generic searches if there is room. Snippets remain
unverified. Check source geography, dates, population, units and causal design before
using numerical impacts. Research practice must have web research enabled.

Preparation telemetry now separates retrieval and research; the benchmark includes
those timings. The UI separately measures engine requests and time between completed
evaluation and human selection. Existing per-inference timing/token diagnostics remain.
No concurrency, context compression, or stage removal has been introduced. Speed
optimization is deferred until the human quality baseline is approved. The five-minute
goal is a target, not a measured outcome.

## Recover a failed scoring stage

When critique and repair completed but scoring failed, **Retry scoring only** reuses
those accepted stages. It revalidates all three IDs, source references, repair
responses, input fingerprints, prompt version, and provider/model identity before
making one scoring call. Original failed-call diagnostics remain in the result.
No architecture is selected automatically. Invalid or incompatible checkpoints
are rejected without contacting the model.

The CLI equivalent writes to a new file:

```bash
.venv/bin/python scripts/evaluate_strategies.py resume-score \
  packet-reviewed.json strategy.json evaluation.json \
  --output evaluation-resumed-01.json
```

The UI checkpoint loader selects the most recently written `evaluation*.json` and
verifies its fingerprints. It never rewrites the original evaluation. Recovery
currently supports a failed scoring stage only; other failed stages require a
separate evaluation run.
