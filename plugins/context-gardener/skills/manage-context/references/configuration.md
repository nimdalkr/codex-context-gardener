# Configuration and behavior

## Environment variables

Context Gardener reads these variables from the Codex hook environment:

- `CONTEXT_GARDENER_MASK_BYTES`: model-facing response size that triggers masking; default `32768`.
- `CONTEXT_GARDENER_PREVIEW_CHARS`: textual evidence preview; default `1800`.
- `CONTEXT_GARDENER_VCC_CHARS`: VCC injection limit; default `6000`.
- `CONTEXT_GARDENER_SUCCESS_LIMIT`: successful ledger entries retained; default `40`.
- `CONTEXT_GARDENER_ERROR_LIMIT`: unresolved errors retained; default `20`.
- `CONTEXT_GARDENER_DISABLE_MASKING`: set `1` to keep logging but pass large results through.
- `CONTEXT_GARDENER_ENFORCE_HANDOFF`: set `1` to request one structured subagent handoff when missing.

Invalid integers fall back to defaults. Limits are clamped to safe minimums and maximums.

## Observation masking

Masking triggers when the serialized tool response exceeds the byte threshold or contains a large base64/data-URL payload. The hook:

1. computes a digest over the received response;
2. applies best-effort redaction to common secret forms;
3. writes a gzip-compressed JSON artifact under `PLUGIN_DATA`;
4. merges the call into the workspace ledger;
5. returns `continue: false` with a compact evidence card so Codex replaces the original model-facing result.

Small results pass through unchanged but still update the bounded ledger.

## Dynamic pruning

Pruning affects the ledger, not observation artifacts:

- exact tool and input fingerprints merge into one entry with an occurrence count;
- successful entries are capped separately from unresolved errors;
- post-compaction pruning uses a smaller success cap;
- artifacts are not deleted automatically because a VCC may still reference them.

Run the `prune` command after changing limits. Delete plugin data manually when stored artifacts are no longer needed.

## Compaction

The plugin snapshots an existing VCC before compaction and reloads a bounded excerpt when a session starts or resumes after compaction. It does not parse transcript files and does not replace Codex's compaction algorithm.

For an optional native compaction prompt, copy `assets/compact-prompt.md` to a stable location and point `experimental_compact_prompt_file` at it in `~/.codex/config.toml`. This is an explicit user configuration change and is not performed during installation.

## Privacy model

Redaction covers common API key prefixes, bearer tokens, authorization headers, passwords, and secret-like assignments. It cannot recognize every secret. Avoid producing sensitive output and treat `PLUGIN_DATA` as private local data.
