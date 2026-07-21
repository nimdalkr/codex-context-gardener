# Codex Context Gardener

Context Gardener is an open-source Codex plugin for long-running, tool-heavy, and multi-agent tasks. It combines:

- **VCC-style checkpoints**: fixed-schema task state used as the compact source of truth.
- **Observation Masking** that replaces oversized model-facing tool results with a concise evidence card while saving a compressed, redacted artifact locally.
- **Dynamic Pruning** that merges duplicate observations and bounds the active ledger while retaining unresolved errors.

The plugin was designed from a local history analysis of 598 Codex sessions. The dominant failure pattern was not a lack of raw context: it was repeated full-history subagent forks, large image and tool observations, and long sessions that compacted many times.

## What it does

Context Gardener bundles one skill and six lifecycle hooks:

| Component | Behavior |
|---|---|
| `manage-context` skill | Creates and maintains `.context-gardener/VCC.md`, scopes delegation, and defines phase boundaries. |
| `PostToolUse` | Masks large or binary-like tool responses before they reach the next model step. |
| `SessionStart` | Reloads a bounded VCC excerpt and unresolved observation summary. |
| `PreCompact` | Snapshots the current VCC before manual or automatic compaction. |
| `PostCompact` | Aggressively bounds the observation ledger after compaction. |
| `SubagentStart` | Injects a small, structured handoff contract into subagents. |
| `SubagentStop` | Optionally asks a subagent for a structured handoff when enforcement is enabled. |

Context Gardener does **not** claim to rewrite Codex internals. It uses documented hook behavior: `PostToolUse` can replace a model-visible tool result with hook feedback, while the original observation is stored under the plugin's writable data directory.

## Requirements

- A current Codex release with plugin and hook support.
- Python 3.9 or newer available as `python3`, `python`, or `py -3`.
- Git, only for cloning the repository.

Plugin command hooks require one-time review and trust in Codex.

## Install

```bash
git clone https://github.com/nimdalkr/codex-context-gardener.git
cd codex-context-gardener
codex plugin marketplace add .
codex plugin add context-gardener@codex-context-gardener
```

Start a new Codex task after installation. In the CLI, open `/hooks`, inspect the six Context Gardener hooks, and trust them. The scripts use only Python's standard library and write runtime data beneath `PLUGIN_DATA`.

Invoke the workflow explicitly with:

```text
Use $context-gardener:manage-context for this task.
```

The skill may also trigger automatically for long, multi-phase, browser/image-heavy, log-heavy, or multi-agent work.

## Default behavior

- Results smaller than 32 KiB pass through unchanged.
- Large results and base64/data-URL payloads are gzip-compressed after best-effort secret redaction.
- The model receives the tool name, size, digest, status, artifact path, duplicate count, and a short textual preview.
- The ledger retains the latest 40 successful observations and 20 unresolved errors by default.
- Artifact files are not automatically deleted. Ledger pruning is context pruning, not destructive artifact cleanup.
- A VCC is read only when `.context-gardener/VCC.md` exists. Installing the plugin alone does not modify a repository.

## Configuration

All settings are optional environment variables inherited by Codex:

| Variable | Default | Meaning |
|---|---:|---|
| `CONTEXT_GARDENER_MASK_BYTES` | `32768` | Mask responses at or above this UTF-8 byte size. |
| `CONTEXT_GARDENER_PREVIEW_CHARS` | `1800` | Maximum characters in a model-facing preview. |
| `CONTEXT_GARDENER_VCC_CHARS` | `6000` | Maximum VCC characters injected on session start. |
| `CONTEXT_GARDENER_SUCCESS_LIMIT` | `40` | Successful ledger entries to retain. |
| `CONTEXT_GARDENER_ERROR_LIMIT` | `20` | Unresolved error entries to retain. |
| `CONTEXT_GARDENER_ENFORCE_HANDOFF` | `0` | Set to `1` to require a structured subagent handoff once. |
| `CONTEXT_GARDENER_DISABLE_MASKING` | `0` | Set to `1` to log without replacing large observations. |

For an additional native Codex guardrail, consider setting `tool_output_token_limit = 8000` in `~/.codex/config.toml`. Keep this separate from the plugin so every installation remains explicit and reversible.

See the skill references for the VCC schema, lifecycle rules, privacy model, and tuning guidance.

## Runtime data and privacy

Masked observations are stored as `.json.gz` files under `PLUGIN_DATA/workspaces/<workspace-hash>/observations/`. Context Gardener applies best-effort redaction for common API keys, bearer tokens, passwords, and secret assignments before writing an artifact. This is a safety aid, not a secret-scanning guarantee.

Do not intentionally print secrets into tool output. Delete the plugin data directory if you need to remove stored artifacts. The project-local VCC may contain file paths and error summaries; keep `.context-gardener/` ignored unless you deliberately want to version it.

## Development

```bash
python -m unittest discover -s tests -v
python scripts/validate_package.py
```

The repository is MIT licensed. Contributions and portability fixes are welcome.

## Related Codex documentation

- [Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Lifecycle hooks](https://learn.chatgpt.com/docs/hooks)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
