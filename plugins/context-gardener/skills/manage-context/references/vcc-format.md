# VCC format

A VCC is the active task's compact source of truth. Keep it factual, editable, and small enough to reload after compaction or in a fresh thread.

## Required sections

```markdown
# VCC

## Goal and done condition
- Goal:
- Done when:

## Current phase
- Phase:
- Scope boundary:

## Verified facts and decisions
- Fact or decision — evidence path, line, command, or artifact

## Changed files
- `path` — purpose and verification status

## Unresolved errors and risks
- Error signature — latest evidence — next diagnostic

## Last validation
- Command:
- Result:
- Timestamp:

## Next three actions
1.
2.
3.

## Observation artifacts
- Artifact path — digest — why it may need targeted rereading
```

## Editing rules

- Replace stale state; do not append a diary.
- Keep only verified conclusions from completed exploration.
- Preserve exact paths, symbols, error signatures, and validation commands.
- Mark assumptions explicitly and remove them when resolved.
- Never include secrets, full logs, full source files, image data, or transcript text.
- Keep the newest successful validation and all unresolved failures.

## Subagent slice

For a subagent, pass only:

```markdown
Objective:
Relevant files:
Known facts:
Constraints:
Done when:
Return: Outcome / Evidence / Changed files / Unresolved / Next action
```
