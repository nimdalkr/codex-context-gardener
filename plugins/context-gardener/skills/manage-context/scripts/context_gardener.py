#!/usr/bin/env python3
"""Deterministic lifecycle hooks for the Context Gardener Codex plugin."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterator, Optional


VERSION = 1
VCC_RELATIVE = Path(".context-gardener") / "VCC.md"
DEFAULT_MASK_BYTES = 32_768
DEFAULT_PREVIEW_CHARS = 1_800
DEFAULT_VCC_CHARS = 6_000
DEFAULT_SUCCESS_LIMIT = 40
DEFAULT_ERROR_LIMIT = 20

ERROR_LINE_RE = re.compile(
    r"(?i)(?:\berror\b|\bexception\b|\bfailed\b|\bfailure\b|"
    r"exit\s+code\s*[:=]\s*[1-9]\d*|traceback|panic:|fatal:)"
)
NONZERO_EXIT_RE = re.compile(
    r"(?i)(?:exit\s+code\s*[:=]\s*([1-9]\d*)|"
    r'"exit_code"\s*:\s*([1-9]\d*))'
)

SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;\"']+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
            r"client[_-]?secret)\b(\s*[:=]\s*)[^\s,;\"']+"
        ),
        r"\1\2[REDACTED]",
    ),
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def env_flag(name: str) -> bool:
    return os.getenv(name, "0").strip().casefold() in {"1", "true", "yes", "on"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def safe_segment(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (cleaned or fallback)[:72]


def workspace_key(cwd: Path) -> str:
    normalized = str(cwd.resolve()).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def plugin_data_root() -> Path:
    configured = os.getenv("PLUGIN_DATA") or os.getenv("CLAUDE_PLUGIN_DATA")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex" / "context-gardener-data").resolve()


def workspace_data(cwd: Path) -> Path:
    return plugin_data_root() / "workspaces" / workspace_key(cwd)


def vcc_path(cwd: Path) -> Path:
    return cwd.resolve() / VCC_RELATIVE


def redact_text(text: str) -> str:
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    return value


def looks_binary_string(text: str) -> bool:
    if len(text) < 1_024:
        return False
    lowered = text[:256].casefold()
    if lowered.startswith("data:") and ";base64," in lowered:
        return True
    if len(text) < 4_096 or any(ch.isspace() for ch in text[:4_096]):
        return False
    sample = text[:4_096]
    allowed = sum(ch.isalnum() or ch in "+/=_-" for ch in sample)
    return allowed / max(1, len(sample)) > 0.985


def contains_binary_payload(value: Any) -> bool:
    if isinstance(value, str):
        return looks_binary_string(value)
    if isinstance(value, list):
        return any(contains_binary_payload(item) for item in value)
    if isinstance(value, dict):
        return any(contains_binary_payload(item) for item in value.values())
    return False


def iter_text(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        if not looks_binary_string(value):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_text(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_text(item)


def detect_error(value: Any, serialized: str) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"iserror", "is_error", "error"} and item is True:
                return True
            if detect_error(item, ""):
                return True
    elif isinstance(value, list):
        return any(detect_error(item, "") for item in value)
    if serialized and NONZERO_EXIT_RE.search(serialized):
        return True
    lowered = serialized.casefold() if serialized else ""
    return "script failed" in lowered or "traceback (most recent call last)" in lowered


def make_preview(value: Any, limit: int) -> str:
    chunks: list[str] = []
    length = 0
    for item in iter_text(value):
        cleaned = redact_text(item.replace("\x00", ""))
        if not cleaned.strip():
            continue
        chunks.append(cleaned)
        length += len(cleaned)
        if length >= max(limit * 8, 12_000):
            break

    text = "\n".join(chunks)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    error_lines = [line for line in lines if ERROR_LINE_RE.search(line)][:8]
    error_text = "\n".join(error_lines)
    if len(text) <= limit:
        body = text
    else:
        head = max(300, int(limit * 0.58))
        tail = max(200, limit - head - 40)
        body = f"{text[:head]}\n… [preview clipped] …\n{text[-tail:]}"

    if error_text and error_text not in body:
        combined = f"Error signals:\n{error_text}\n\nPreview:\n{body}"
    else:
        combined = body
    return combined[:limit].strip()


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 3.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()} {utc_now()}".encode("utf-8"))
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 30:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    if not acquired:
        raise TimeoutError(f"could not acquire ledger lock: {path}")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def ledger_path(cwd: Path) -> Path:
    return workspace_data(cwd) / "ledger.json"


def prune_entries(ledger: dict[str, Any], aggressive: bool = False) -> dict[str, Any]:
    entries = list((ledger.get("entries") or {}).values())
    entries.sort(key=lambda item: item.get("last_seen", ""), reverse=True)
    success_limit = env_int(
        "CONTEXT_GARDENER_SUCCESS_LIMIT", DEFAULT_SUCCESS_LIMIT, 5, 500
    )
    error_limit = env_int(
        "CONTEXT_GARDENER_ERROR_LIMIT", DEFAULT_ERROR_LIMIT, 5, 200
    )
    if aggressive:
        success_limit = max(5, success_limit // 2)

    successes = [item for item in entries if item.get("status") == "success"][:success_limit]
    errors = [item for item in entries if item.get("status") != "success"][:error_limit]
    kept = successes + errors
    kept.sort(key=lambda item: item.get("last_seen", ""), reverse=True)
    ledger["entries"] = {item["fingerprint"]: item for item in kept}
    ledger["updated_at"] = utc_now()
    ledger["pruned"] = max(0, len(entries) - len(kept))
    return ledger


def update_ledger(
    cwd: Path,
    event: dict[str, Any],
    *,
    status: str,
    response_bytes: int,
    response_digest: str,
    preview: str,
    artifact: Optional[str],
) -> tuple[dict[str, Any], int]:
    path = ledger_path(cwd)
    lock = path.with_suffix(".lock")
    tool_name = str(event.get("tool_name") or "unknown")
    tool_input = event.get("tool_input")
    input_text = canonical_json(tool_input)
    fingerprint = digest_text(canonical_json({"tool": tool_name, "input": tool_input}))
    now = utc_now()

    with file_lock(lock):
        ledger = read_json(
            path,
            {
                "version": VERSION,
                "workspace": str(cwd.resolve()),
                "created_at": now,
                "updated_at": now,
                "entries": {},
            },
        )
        entries = ledger.setdefault("entries", {})
        previous = entries.get(fingerprint, {})
        occurrences = int(previous.get("occurrences", 0)) + 1
        entries[fingerprint] = {
            "fingerprint": fingerprint,
            "tool": tool_name,
            "input_digest": digest_text(input_text),
            "occurrences": occurrences,
            "first_seen": previous.get("first_seen", now),
            "last_seen": now,
            "status": status,
            "response_bytes": response_bytes,
            "response_digest": response_digest,
            "artifact": artifact or previous.get("artifact"),
            "preview": preview[:500],
            "session_id": str(event.get("session_id") or ""),
        }
        prune_entries(ledger)
        atomic_write_json(path, ledger)
    return entries.get(fingerprint, {}), occurrences


def write_observation(
    cwd: Path,
    event: dict[str, Any],
    response_digest: str,
    status: str,
) -> Path:
    data = workspace_data(cwd) / "observations"
    data.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tool = safe_segment(str(event.get("tool_name") or "tool"), "tool")
    call_id = safe_segment(str(event.get("tool_use_id") or response_digest[:10]), response_digest[:10])
    target = data / f"{stamp}-{tool}-{call_id}.json.gz"
    suffix = 1
    while target.exists():
        target = data / f"{stamp}-{tool}-{call_id}-{suffix}.json.gz"
        suffix += 1

    artifact = {
        "version": VERSION,
        "created_at": utc_now(),
        "workspace": str(cwd.resolve()),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "tool_name": event.get("tool_name"),
        "tool_use_id": event.get("tool_use_id"),
        "status": status,
        "response_digest": response_digest,
        "tool_input": redact_value(event.get("tool_input")),
        "tool_response": redact_value(event.get("tool_response")),
    }
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(artifact, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, target)
    return target.resolve()


def read_event() -> dict[str, Any]:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        print(f"Context Gardener ignored invalid hook JSON: {exc}", file=sys.stderr)
        return {}
    return value if isinstance(value, dict) else {}


def emit(value: dict[str, Any]) -> None:
    # ASCII JSON escapes survive cmd.exe/PowerShell and POSIX hook launchers alike.
    sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")


def event_cwd(event: dict[str, Any]) -> Path:
    return Path(str(event.get("cwd") or os.getcwd())).expanduser().resolve()


def ledger_summary(cwd: Path) -> str:
    ledger = read_json(ledger_path(cwd), {"entries": {}})
    entries = list((ledger.get("entries") or {}).values())
    if not entries:
        return ""
    entries.sort(key=lambda item: item.get("last_seen", ""), reverse=True)
    errors = [item for item in entries if item.get("status") != "success"][:5]
    masked = [item for item in entries if item.get("artifact")][:3]
    lines = [f"Ledger: {len(entries)} active observations; {len(errors)} unresolved errors shown."]
    for item in errors:
        lines.append(
            f"- ERROR {item.get('tool')} x{item.get('occurrences', 1)}: "
            f"{item.get('preview') or 'No textual preview'}"
        )
    for item in masked:
        lines.append(
            f"- MASKED {item.get('tool')} ({item.get('response_bytes', 0)} bytes): "
            f"{item.get('artifact')}"
        )
    return "\n".join(lines)


def bounded_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head - 80
    return f"{text[:head]}\n… [VCC clipped; edit it below {limit} chars] …\n{text[-tail:]}"


def hook_session_start(event: dict[str, Any]) -> None:
    cwd = event_cwd(event)
    limit = env_int("CONTEXT_GARDENER_VCC_CHARS", DEFAULT_VCC_CHARS, 1_000, 12_000)
    checkpoint = vcc_path(cwd)
    vcc = checkpoint.read_text(encoding="utf-8") if checkpoint.is_file() else ""
    summary = ledger_summary(cwd)
    if not vcc and not summary:
        return
    context = [
        "Context Gardener restored bounded task state. Treat the VCC as the source of truth; do not reconstruct the full chat.",
    ]
    if vcc:
        context.extend([f"VCC path: {checkpoint}", bounded_text(vcc, limit)])
    if summary:
        context.extend(["Observation ledger:", bounded_text(summary, 2_000)])
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n\n".join(context),
            }
        }
    )


def hook_post_tool(event: dict[str, Any]) -> None:
    cwd = event_cwd(event)
    response = event.get("tool_response")
    serialized = canonical_json(response)
    response_bytes = len(serialized.encode("utf-8", "replace"))
    response_digest = digest_text(serialized)
    preview_limit = env_int(
        "CONTEXT_GARDENER_PREVIEW_CHARS", DEFAULT_PREVIEW_CHARS, 400, 4_000
    )
    preview = make_preview(response, preview_limit)
    is_error = detect_error(response, serialized)
    status = "error" if is_error else "success"
    threshold = env_int(
        "CONTEXT_GARDENER_MASK_BYTES", DEFAULT_MASK_BYTES, 4_096, 16_777_216
    )
    should_mask = response_bytes >= threshold or contains_binary_payload(response)
    masking_disabled = env_flag("CONTEXT_GARDENER_DISABLE_MASKING")
    artifact: Optional[Path] = None
    if should_mask:
        artifact = write_observation(cwd, event, response_digest, status)

    _, occurrences = update_ledger(
        cwd,
        event,
        status=status,
        response_bytes=response_bytes,
        response_digest=response_digest,
        preview=preview,
        artifact=str(artifact) if artifact else None,
    )
    if not should_mask or masking_disabled:
        return

    lines = [
        "[Context Gardener: observation masked]",
        f"Tool: {event.get('tool_name') or 'unknown'}",
        f"Status: {status}",
        f"Original size: {response_bytes} bytes",
        f"SHA-256: {response_digest}",
        f"Artifact: {artifact}",
        f"Exact-call occurrences in active ledger: {occurrences}",
    ]
    if preview:
        lines.extend(["Relevant preview:", preview])
    lines.append("Use a targeted read of the artifact only if this evidence is insufficient.")
    emit({"continue": False, "stopReason": "\n".join(lines)})


def snapshot_vcc(cwd: Path, trigger: str) -> Optional[Path]:
    source = vcc_path(cwd)
    if not source.is_file():
        return None
    target_dir = workspace_data(cwd) / "checkpoints"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"{stamp}-{safe_segment(trigger, 'checkpoint')}.md"
    counter = 1
    while target.exists():
        target = target_dir / f"{stamp}-{safe_segment(trigger, 'checkpoint')}-{counter}.md"
        counter += 1
    body = source.read_text(encoding="utf-8")
    header = f"<!-- Context Gardener snapshot: {utc_now()} | trigger: {trigger} -->\n"
    atomic_write_text(target, header + body)
    return target.resolve()


def hook_pre_compact(event: dict[str, Any]) -> None:
    cwd = event_cwd(event)
    snapshot = snapshot_vcc(cwd, str(event.get("trigger") or "compact"))
    if snapshot:
        emit(
            {
                "continue": True,
                "systemMessage": f"Context Gardener saved the current VCC snapshot at {snapshot}",
            }
        )
    else:
        emit(
            {
                "continue": True,
                "systemMessage": "Context Gardener found no project VCC to snapshot before compaction.",
            }
        )


def prune_ledger(cwd: Path, aggressive: bool) -> tuple[int, int]:
    path = ledger_path(cwd)
    lock = path.with_suffix(".lock")
    with file_lock(lock):
        ledger = read_json(path, {"version": VERSION, "entries": {}})
        before = len(ledger.get("entries") or {})
        prune_entries(ledger, aggressive=aggressive)
        after = len(ledger.get("entries") or {})
        atomic_write_json(path, ledger)
    return before, after


def hook_post_compact(event: dict[str, Any]) -> None:
    cwd = event_cwd(event)
    before, after = prune_ledger(cwd, aggressive=True)
    emit(
        {
            "continue": True,
            "systemMessage": (
                f"Context Gardener bounded the active observation ledger: {before} -> {after}. "
                "Continue from .context-gardener/VCC.md."
            ),
        }
    )


def hook_subagent_start(event: dict[str, Any]) -> None:
    cwd = event_cwd(event)
    checkpoint = vcc_path(cwd)
    excerpt = ""
    if checkpoint.is_file():
        excerpt = bounded_text(checkpoint.read_text(encoding="utf-8"), 2_400)
    context = [
        "Context Gardener subagent contract:",
        "- Work only on the bounded objective you were assigned.",
        "- Do not reconstruct or reread the parent transcript.",
        "- Keep long logs and binary observations out of your final response.",
        "- Return: Outcome / Evidence / Changed files / Unresolved issues / Recommended next action.",
    ]
    if excerpt:
        context.extend([f"Workspace VCC: {checkpoint}", excerpt])
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": "\n".join(context),
            }
        }
    )


def has_structured_handoff(message: str) -> bool:
    lowered = message.casefold()
    groups = (
        ("outcome", "result", "결과"),
        ("evidence", "근거"),
        ("changed", "files", "변경"),
        ("unresolved", "remaining", "미해결", "남은"),
        ("next", "recommended", "다음", "권장"),
    )
    return sum(any(term in lowered for term in group) for group in groups) >= 4


def hook_subagent_stop(event: dict[str, Any]) -> None:
    if not env_flag("CONTEXT_GARDENER_ENFORCE_HANDOFF"):
        emit({})
        return
    if bool(event.get("stop_hook_active")):
        emit({})
        return
    message = str(event.get("last_assistant_message") or "")
    if has_structured_handoff(message):
        emit({})
        return
    emit(
        {
            "decision": "block",
            "reason": (
                "Return one concise Context Gardener handoff with headings: Outcome, Evidence, "
                "Changed files, Unresolved issues, and Recommended next action. Do not include raw logs."
            ),
        }
    )


def template_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "vcc-template.md"


def command_init(cwd: Path) -> int:
    target = vcc_path(cwd)
    if target.exists():
        print(target)
        return 0
    template = template_path().read_text(encoding="utf-8")
    atomic_write_text(target, template)
    print(target)
    return 0


def command_status(cwd: Path) -> int:
    ledger = read_json(ledger_path(cwd), {"entries": {}})
    entries = list((ledger.get("entries") or {}).values())
    payload = {
        "workspace": str(cwd.resolve()),
        "vcc_path": str(vcc_path(cwd)),
        "vcc_exists": vcc_path(cwd).is_file(),
        "plugin_data": str(plugin_data_root()),
        "active_observations": len(entries),
        "unresolved_errors": sum(item.get("status") != "success" for item in entries),
        "masked_observations": sum(bool(item.get("artifact")) for item in entries),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_checkpoint(cwd: Path) -> int:
    snapshot = snapshot_vcc(cwd, "manual-checkpoint")
    if not snapshot:
        print(f"No VCC found at {vcc_path(cwd)}", file=sys.stderr)
        return 2
    print(snapshot)
    return 0


def command_prune(cwd: Path, aggressive: bool) -> int:
    before, after = prune_ledger(cwd, aggressive=aggressive)
    print(json.dumps({"before": before, "after": after, "aggressive": aggressive}))
    return 0


def command_doctor(cwd: Path) -> int:
    payload = {
        "ok": sys.version_info >= (3, 9),
        "python": sys.version.split()[0],
        "workspace": str(cwd.resolve()),
        "plugin_root": os.getenv("PLUGIN_ROOT"),
        "plugin_data": str(plugin_data_root()),
        "mask_bytes": env_int(
            "CONTEXT_GARDENER_MASK_BYTES", DEFAULT_MASK_BYTES, 4_096, 16_777_216
        ),
        "vcc": str(vcc_path(cwd)),
        "vcc_exists": vcc_path(cwd).is_file(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


HOOK_ACTIONS = {
    "session-start": hook_session_start,
    "post-tool": hook_post_tool,
    "pre-compact": hook_pre_compact,
    "post-compact": hook_post_compact,
    "subagent-start": hook_subagent_start,
    "subagent-stop": hook_subagent_stop,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[*HOOK_ACTIONS, "init", "status", "checkpoint", "prune", "doctor"],
    )
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--aggressive", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action in HOOK_ACTIONS:
        event = read_event()
        if not event:
            if args.action == "subagent-stop":
                emit({})
            return 0
        try:
            HOOK_ACTIONS[args.action](event)
        except Exception as exc:  # Hooks must fail open and avoid breaking user work.
            print(f"Context Gardener hook failed open: {type(exc).__name__}: {exc}", file=sys.stderr)
            if args.action == "subagent-stop":
                emit({})
        return 0

    cwd = args.cwd.expanduser().resolve()
    if args.action == "init":
        return command_init(cwd)
    if args.action == "status":
        return command_status(cwd)
    if args.action == "checkpoint":
        return command_checkpoint(cwd)
    if args.action == "prune":
        return command_prune(cwd, aggressive=args.aggressive)
    if args.action == "doctor":
        return command_doctor(cwd)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
