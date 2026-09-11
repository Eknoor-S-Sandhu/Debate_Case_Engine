# Milestone 15 — Multi-provider inference

Scope: OpenAI, Anthropic, and Gemini inference for strategy generation, Red Team,
repair, scoring, case drafting, trimming and improvement. Provider choice is
explicit. This milestone does not implement Milestone 16, automatic fallback,
provider ensembles, local endpoints, or additional debate stages.

## Configuration

Use `.env.example` as a reference. Put actual settings in the existing gitignored
`.env` file or environment; credentials never belong in filenames or exported
round JSON. Each provider has independent credentials and an explicit model ID:

```text
DEBATE_ENGINE_STRATEGY__PROVIDER=gemini
DEBATE_ENGINE_GEMINI__ALLOW_REMOTE=true
DEBATE_ENGINE_GEMINI__API_KEY=your-gemini-api-key
DEBATE_ENGINE_GEMINI__MODEL=your-supported-gemini-model
```

Replace `GEMINI` with `OPENAI` or `ANTHROPIC` for those providers, and choose the
matching lowercase provider name. No model is selected automatically; choose one
available to your account supporting the adapter's structured-output endpoint.
Invalid provider names fail configuration validation.

`DEBATE_ENGINE_STRATEGY__ALLOW_REMOTE` remains the shared default, false initially.
A provider-specific `ALLOW_REMOTE=true` or `false` overrides that default for that
provider. Missing credentials, blank credentials or a missing model result in
`not_configured` before any network call. Offline prep always blocks all three
providers, regardless of remote configuration. The research provider remains
Tavily and is not changed by inference selection.

For existing OpenAI users, `DEBATE_ENGINE_STRATEGY__API_KEY` and `MODEL` remain
fallback settings for OpenAI only. New `OPENAI__API_KEY` and `OPENAI__MODEL` values
take precedence when present. Legacy credentials are never reused for Anthropic
or Gemini. Keys are masked by the configuration schema and excluded from prompts,
exports and errors.

## UI and CLI

The Round preparation page has an **Inference provider** selector showing the
model and whether configuration is missing. Selecting a provider makes no request.
The choice controls the next explicitly requested generation/evaluation/writing
operation. You can generate with one provider, switch, and evaluate or write with
another. Existing outputs retain their original provider/model labels. No provider
is changed automatically after failure, and switching does not regenerate work.

The three generation commands accept `--provider`:

```bash
.venv/bin/python scripts/generate_strategies.py knowledge_packet.json --provider gemini --json
.venv/bin/python scripts/evaluate_strategies.py evaluate knowledge_packet.json strategy_architectures.json --provider anthropic --json
.venv/bin/python scripts/write_case.py knowledge_packet.json strategy_architectures.json selected_strategy.json --provider openai --json
```

Omit the option to use `DEBATE_ENGINE_STRATEGY__PROVIDER`, which defaults to OpenAI.
The CLI override does not rewrite `.env` or cached settings. The offline `select`
command needs no inference provider. Restart the UI after editing environment
configuration because settings are cached.

## Adapter behavior

OpenAI uses Responses with `text.format` JSON schema and `store=false`, preserving
the existing request contract. See the official
[OpenAI structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

Anthropic uses Messages with `output_config.format`. Unsupported numeric, string,
and array bounds are moved into schema descriptions for the provider grammar;
the original Pydantic constraints are still enforced after generation. See
[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

Gemini uses the native GenerateContent endpoint, `systemInstruction`, and
`generationConfig.responseMimeType` / `responseJsonSchema` JSON schema
(corrected by Milestone 16 live validation). API keys are sent in a header,
never the URL. Only a single candidate ending with `STOP` is accepted; blocked
requests, truncated responses and unexpected content fail. Thought text, if
returned separately, is excluded from the JSON result. See
[Gemini GenerateContent structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

All adapters use fixed official HTTPS hosts. No tools, automatic retries,
redirects, or provider fallback are enabled. Existing per-request socket timeout,
input/output limits and 2 MB response cap apply. Provider configuration is copied
for each operation; one operation's stages use the same selected adapter. Each
provider receives the selected private excerpts, judge information and stage
context required by the operation. Provider-specific retention policies apply;
OpenAI's `store=false` is not represented as a cross-provider retention guarantee.

Refusal, incomplete output, malformed JSON, non-object output, HTTP failures,
timeouts and oversized responses produce redacted failures. JSON is accepted only
after the existing stage validators check structure, exact source references,
quotations, diversity, scoring bounds, repair coverage or speech length as relevant.
There is no weaker plain-text fallback when a model rejects a schema. Unsupported
models or complex schemas may still be rejected by provider APIs.

## Exports and compatibility

New strategy, evaluation and case exports record `provider` and `model` for the
operation. Injected test providers are labeled `injected` with no claimed model.
Older exports without provider metadata remain readable. Their fingerprints omit
the absent metadata field so Milestone 12–14 handoffs still work. New provider
metadata participates in fingerprints to bind later stages to the actual export.
No automatic migration or rewrite of existing files is performed.

## Validation and limitations

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

Tests exercise all three native request/response formats, full case pipelines,
explicit mixed-provider workflows, credential isolation, refusals/truncation,
HTTP failures, size limits, missing setup, offline gating, legacy exports, CLI
selection, and UI selection without network calls. Automated tests isolate the
user's local `.env` and provider environment variables so real credentials cannot
activate generation or affect expected defaults.

These checks use simulated HTTP responses. No paid live call, account/model
availability test, or qualitative comparison of generated cases has been performed.
