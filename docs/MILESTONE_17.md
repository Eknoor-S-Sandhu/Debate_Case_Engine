# Milestone 17 — Codex CLI inference

The updated direction in **Build Debate Agent** makes Codex CLI the primary
inference transport, Gemini the manually selected backup, and the existing
OpenAI and Anthropic APIs additional options. This supersedes the older plan for
topic/side selection as the next milestone. No topic selection, live refutation,
or later feature work is included.

## Setup

Install Codex CLI and run `codex login` to sign in with ChatGPT, then check
`codex login status`. The adapter accepts ChatGPT login only. It does not launch
an interactive sign-in flow or accept API-key login. ChatGPT authentication uses
subscription access, subject to your account's allowance and limits; it does not
promise unlimited generation. See the official [authentication guide](https://learn.chatgpt.com/docs/auth).

Configure the local, gitignored `.env`:

```dotenv
DEBATE_ENGINE_STRATEGY__PROVIDER=codex_cli
DEBATE_ENGINE_CODEX_CLI__ALLOW_REMOTE=true
DEBATE_ENGINE_CODEX_CLI__EXECUTABLE=codex
DEBATE_ENGINE_CODEX_CLI__TIMEOUT_SECONDS=180
```

`EXECUTABLE` may be an absolute executable path if the app cannot find `codex` on
its PATH. It is a single executable, not a shell command with arguments. An
optional `DEBATE_ENGINE_CODEX_CLI__MODEL` selects a model explicitly. When unset,
Codex uses its built-in default, and engine exports leave the model field null
rather than claiming an exact model. Personal CLI configuration is not loaded.
The installed CLI must support `--ignore-user-config`, `--ephemeral`,
`--output-schema`, `--output-last-message`, and JSON events (tested with 0.153.4).

Codex is the default for new configurations. Legacy `STRATEGY__API_KEY` or
`STRATEGY__MODEL` settings without an explicit provider still select OpenAI.
An explicit provider always wins. Keep Gemini credentials in `.env` and select
**Gemini (backup)** in the UI, or pass `--provider gemini` to generation commands,
to use it. A failed Codex request never silently sends your context to Gemini.

## Behavior

The strategy, Red Team, repair, scoring, draft, trim and improvement stages use
the same provider interface and the same strict local validation. The UI labels
Codex as primary and explains the ChatGPT login requirement. Provider metadata
and per-stage timing, status and reported token usage are preserved in exports.
Readiness checks installation and remote permission; authentication is checked
when generation starts. Offline prep still blocks every inference stage.

The adapter invokes `codex exec` directly without a shell, passes the prompt via
stdin and requests a schema-conforming final answer. It requires a successful
exit, a completed turn event, no failed/error events, and a JSON object in the
final-answer file. Arbitrary terminal chatter is never treated as a case.
See [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

Each invocation runs in a private temporary working directory, uses a read-only
sandbox and ephemeral sessions, disables shell, browser, plugin, app and
subagent features, and skips personal CLI configuration and AGENTS document
loading. Managed Codex policies still apply. The child receives a minimal
environment that preserves the user's existing Codex authentication location;
API keys and parent app session variables are not forwarded. No credentials are
read or copied by the engine. Codex is still remote inference: the selected
context is sent through the user's ChatGPT-authenticated account.

The engine deletes its temporary prompt, schema, event and answer files after
success or failure. Codex's own diagnostic storage and account data handling
remain governed by Codex. A 10-second login-check deadline precedes the generation
deadline (default 180 seconds, configurable up to 600). Generation timeout or
output overflow terminates and reaps the child process group on POSIX; Windows
terminates the direct child. Each output file is bounded to 2 MB on read and
monitored during execution. The shared API `max_output_tokens` setting is not
passed to Codex; output size and duration are the adapter's bounds.

Missing CLI/login, incompatible flags, quota/usage errors, timeout and invalid
responses fail clearly. Raw stderr, prompts, authentication tokens and error event payloads
are excluded from exported diagnostics. There is no engine retry or automatic
provider fallback; the CLI may perform its own transport retries within the
engine's deadline. Reported token counts are observations, not billing estimates.

## Validation

The test suite runs real local child processes with a simulated CLI protocol to
verify stdin/argument separation, credential isolation, ChatGPT-only login,
timeouts, temporary-file cleanup, output bounds, malformed responses, errors,
usage reporting and the full strategy-to-case pipeline. No model calls occur
in the automated tests. All 585 tests pass, including the existing API-provider
and offline tests; Ruff and whitespace checks also pass.

A live minimal public JSON prompt succeeded through the installed CLI and
ChatGPT login, returning `{"status":"ok"}` and reported usage. This establishes
the real CLI transport. A second live test using the full strategy schema and
synthetic public-transit context produced three accepted architectures in 105
seconds (11,642 input and 3,373 output tokens reported). No private archive was
used in these live tests. These checks do not establish competitive case quality
or close Milestone 16's pending live acceptance checks.

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/python scripts/benchmark_v1.py --output data/parsed/m17-new --provider codex_cli
```

The benchmark is dry by default. Add `--live --timeout-seconds 120` only when
ready to send selected archive excerpts through the chosen provider. The
benchmark timeout flag applies to both API and CLI providers.
