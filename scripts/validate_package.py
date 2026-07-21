#!/usr/bin/env python3
"""Validate the repository's distributable Codex plugin without dependencies."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "context-gardener"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
HOOKS = PLUGIN / "hooks" / "hooks.json"
SKILL = PLUGIN / "skills" / "manage-context" / "SKILL.md"
SCRIPT = PLUGIN / "skills" / "manage-context" / "scripts" / "context_gardener.py"


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: Path) -> dict:
    if not path.is_file():
        fail(f"missing file: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    manifest = load_json(MANIFEST)
    marketplace = load_json(MARKETPLACE)
    hooks = load_json(HOOKS)

    if manifest.get("name") != "context-gardener":
        fail("plugin name must match its folder")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", manifest.get("version", "")):
        fail("plugin version must use semantic versioning")
    for field in ("description", "author", "license", "interface", "skills"):
        if not manifest.get(field):
            fail(f"plugin manifest is missing {field}")
    if manifest.get("license") != "MIT":
        fail("repository and manifest license must be MIT")
    if manifest.get("hooks"):
        fail("default hooks/hooks.json discovery should be used")
    if not (PLUGIN / manifest["skills"].removeprefix("./")).is_dir():
        fail("manifest skills path does not exist")

    if marketplace.get("name") != "codex-context-gardener":
        fail("marketplace name is incorrect")
    entries = marketplace.get("plugins") or []
    if len(entries) != 1 or entries[0].get("name") != manifest["name"]:
        fail("marketplace must expose exactly the Context Gardener plugin")
    if entries[0].get("source", {}).get("path") != "./plugins/context-gardener":
        fail("marketplace source path is incorrect")

    expected_hooks = {
        "SessionStart",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "SubagentStart",
        "SubagentStop",
    }
    if set((hooks.get("hooks") or {}).keys()) != expected_hooks:
        fail("hook event set is incomplete")

    skill_text = SKILL.read_text(encoding="utf-8")
    if not skill_text.startswith("---\nname: manage-context\n"):
        fail("skill frontmatter is malformed")
    if "[TODO" in skill_text or "[TODO" in MANIFEST.read_text(encoding="utf-8"):
        fail("placeholder TODO found")
    compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")

    required = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "SECURITY.md",
        PLUGIN / "scripts" / "run-hook.sh",
        PLUGIN / "scripts" / "run-hook.ps1",
        PLUGIN / "skills" / "manage-context" / "assets" / "vcc-template.md",
        PLUGIN / "skills" / "manage-context" / "assets" / "compact-prompt.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail(f"missing distributable files: {missing}")

    print("Context Gardener package validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
