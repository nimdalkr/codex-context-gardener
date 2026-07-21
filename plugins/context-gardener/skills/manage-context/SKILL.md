---
name: manage-context
description: Manage long-running Codex context with a VCC checkpoint, masked tool observations, bounded state pruning, and minimal-context subagent handoffs. Use for multi-phase coding or design work, debugging with long logs, browser or image-heavy tasks, sessions likely to need compaction, multi-agent delegation, or whenever the user asks to keep a Codex task precise across long runs or fresh threads.
---

# Manage Context

Keep one compact source of truth and keep noisy evidence outside active model context. Do not promise that a hook can remove history that Codex has already consumed.

## Start the task

1. Resolve the active workspace and this skill directory.
2. Run `python3 <skill-dir>/scripts/context_gardener.py init --cwd <workspace>`, using `python` or `py -3` when that is the available Python 3 launcher.
3. Read `.context-gardener/VCC.md`. Update it before broad exploration when the task already has verified state.
4. State the current phase and completion condition in the VCC before using many tools.

Do not create a VCC for a short single-answer task. Do not copy chat transcripts, full files, base64 data, or long logs into it.

## Maintain the VCC

Update `.context-gardener/VCC.md` after:

- a phase completes;
- a root cause or important constraint is verified;
- files change materially;
- a test changes the known state;
- a subagent is about to start or has returned;
- the first compaction occurs;
- the task is handed to a fresh thread.

Keep the VCC under roughly 6,000 characters. Preserve verified facts, unresolved errors, exact file paths, validation commands, and the next three actions. Remove completed exploration notes after their conclusion is captured.

Read [VCC format](references/vcc-format.md) only when creating, repairing, or handing off a checkpoint.

## Handle observations

The `PostToolUse` hook handles oversized observations mechanically. Follow the same policy for manual summaries:

- Retain the command or tool name, status, size, digest, artifact path, and a short relevant excerpt.
- Retain the exact error signature until its cause is verified.
- Refer to large files and images by path plus the observation made from them.
- Re-read a masked artifact only with a targeted query, range, or head/tail request.
- Never paste an entire masked artifact back into the conversation.

If a result is unexpectedly masked, use the artifact path from the evidence card. Treat stored artifacts as sensitive even though common secrets are redacted best-effort.

## Delegate with bounded context

Before spawning a subagent:

1. Update the VCC.
2. Give the subagent one bounded objective, relevant files, constraints, and done criteria.
3. Use `fork_turns: "none"` by default. Use only the minimum recent-turn count when the task truly depends on conversational wording.
4. Include only the relevant VCC slice, not the entire VCC when a smaller handoff is sufficient.
5. Ask for Outcome, Evidence, Changed files, Unresolved issues, and Recommended next action.

Do not delegate write-heavy overlapping work without explicit file ownership.

## Prune at phase boundaries

After a completed phase:

- collapse duplicate commands to the latest result plus occurrence count;
- remove resolved errors from the active VCC while preserving the verified cause;
- discard superseded plans and exploration notes;
- retain the latest successful validation and every unresolved failure;
- run `python3 <skill-dir>/scripts/context_gardener.py checkpoint --cwd <workspace>` before a fresh thread or risky handoff, using the available Python 3 launcher.

Start a fresh task when the goal changes, when one phase can be verified independently, or after repeated compactions. Continue from the VCC rather than asking the new task to reconstruct the old chat.

## Inspect and tune

Run these commands when diagnosing the plugin:

- `python3 <skill-dir>/scripts/context_gardener.py status --cwd <workspace>`
- `python3 <skill-dir>/scripts/context_gardener.py doctor --cwd <workspace>`
- `python3 <skill-dir>/scripts/context_gardener.py prune --cwd <workspace> --aggressive`

Read [configuration](references/configuration.md) only when changing thresholds, privacy behavior, compaction prompting, or handoff enforcement.
