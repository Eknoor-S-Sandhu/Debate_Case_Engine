# Casebook writing workspace

The new website uses the approved light writing-workspace design throughout
round setup, sources, strategy review, the final case, saved runs and settings.
It is a custom HTML/CSS/JavaScript interface served by Python; no Node install,
frontend build step or additional Python package is needed.

## Launch

In Terminal:

```bash
cd /Users/eknoorsandhu/Debate_Case_Engine
.venv/bin/python -m ui.server
```

Open http://127.0.0.1:8768 in your browser. Keep the terminal running.
Stop with Control-C. If the port is occupied, launch with `--port 8769` and
open http://127.0.0.1:8769 instead.

## Try the existing case first

Choose **Saved runs**, select `v1-research-transit-20260928`, then **Open saved run**.
This loads the saved selected strategy and matching completed speech without
research or model requests. The historical case predates the latest construction
reform and is not a new quality-validation result.

## Make a new case

1. Save the motion, optional infoslide, side, round type, judge and preparation rules in **Round setup**.
2. **Prepare sources**, then inspect excerpts and provenance in **Sources**.
3. In **Strategies**, generate three options, then run **Critique, repair & score**.
   Review reasoning, independent offense, construction details and unresolved risks.
4. Explicitly choose an option. In **Final case**, set delivery preferences if needed
   and choose **Write selected case**. The engine keeps its existing drafting and
   improvement stages. Review and rehearse, then copy the entire speech or download Markdown or JSON.

Research focus guides archive retrieval and permitted web searches. Strategy preferences
guide argument construction from the prepared packet; they do not trigger new searches.
Judge Paradigm/Notes independently controls judge adaptation. Infoslides accompany
local retrieval and all model stages as round context. They are not sent verbatim
to Tavily; use Research focus for particular web-search topics.

Research and cloud model permissions are separate. Fifteen-minute no-web rounds
use the existing NYPDL adaptation and exclude theory, Ks and tricks. The optional
timer begins only when you confirm sides; it does not enforce an engine deadline.

Provider and Tavily settings remain in `.env`; restart after changing them.
The settings screen shows configuration status without exposing keys. Model
stages send the selected packet contents and relevant notes to your configured
provider when you start them. Source preparation can use Tavily when permitted.

## Keeping work

Browser refresh preserves the active server workspace and does not repeat model
requests. Changing saved round settings clears dependent outputs; changing the
selected option clears the dependent case. Unchanged settings reuse the packet.
Each finished stage/changed selection saves a new snapshot under `data/parsed`.
Historical runs are never overwritten.

The Saved runs picker restores checkpoints with a completed strategy and matching
fingerprints, including matching evaluations and completed cases. Packet-only
snapshots remain on disk but are not yet restorable through this picker.
After stopping/restarting the server, open a saved run again. Do not stop the
server while a model stage is running if you want that stage to finish.

This is a local, single-user app. Browser tabs share one active workspace.
The existing Streamlit app remains available with:

```bash
.venv/bin/python -m streamlit run ui/app.py --server.address 127.0.0.1
```

## Milestone handoff

Construction milestones 1–4 are implemented. The website is the current review
boundary. Milestone 5 remains paused: first compare the revised writer using the
saved transit packet and selected architecture; then regenerate and evaluate
architectures and pause for selection before drafting. Broader fact/value/policy
validation follows. No new live model call is part of website acceptance.
