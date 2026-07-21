from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Optional
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins"
    / "context-gardener"
    / "skills"
    / "manage-context"
    / "scripts"
    / "context_gardener.py"
)


class ContextGardenerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.plugin_data = self.base / "plugin-data"
        self.env = os.environ.copy()
        self.env["PLUGIN_DATA"] = str(self.plugin_data)
        self.env["CONTEXT_GARDENER_MASK_BYTES"] = "4096"
        self.env["CONTEXT_GARDENER_PREVIEW_CHARS"] = "700"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    def run_hook(
        self,
        action: str,
        event: dict,
        env: Optional[dict[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), action],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    def event(self, response: object, *, command: str = "echo ok", call_id: str = "call-1") -> dict:
        return {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.workspace),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_use_id": call_id,
            "tool_input": {"command": command},
            "tool_response": response,
        }

    def ledger(self) -> dict:
        files = list(self.plugin_data.glob("workspaces/*/ledger.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_init_creates_vcc_without_overwriting(self) -> None:
        first = self.run_cli("init", "--cwd", str(self.workspace))
        self.assertEqual(first.returncode, 0, first.stderr)
        vcc = self.workspace / ".context-gardener" / "VCC.md"
        self.assertTrue(vcc.is_file())
        vcc.write_text("custom checkpoint\n", encoding="utf-8")
        second = self.run_cli("init", "--cwd", str(self.workspace))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(vcc.read_text(encoding="utf-8"), "custom checkpoint\n")

    def test_small_output_passes_through_and_updates_ledger(self) -> None:
        result = self.run_hook("post-tool", self.event({"output": "ok", "exit_code": 0}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        entries = list(self.ledger()["entries"].values())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "success")
        self.assertIsNone(entries[0]["artifact"])

    def test_large_output_is_masked_redacted_and_compressed(self) -> None:
        response = {"output": "password=supersecret\n" + ("useful line\n" * 600), "exit_code": 0}
        result = self.run_hook("post-tool", self.event(response))
        self.assertEqual(result.returncode, 0, result.stderr)
        hook_output = json.loads(result.stdout)
        self.assertFalse(hook_output["continue"])
        self.assertIn("observation masked", hook_output["stopReason"])
        entry = next(iter(self.ledger()["entries"].values()))
        artifact = Path(entry["artifact"])
        self.assertTrue(artifact.is_file())
        with gzip.open(artifact, "rt", encoding="utf-8") as handle:
            stored = handle.read()
        self.assertNotIn("supersecret", stored)
        self.assertIn("[REDACTED]", stored)

    def test_binary_like_output_is_masked_below_size_threshold(self) -> None:
        env = self.env.copy()
        env["CONTEXT_GARDENER_MASK_BYTES"] = "16777216"
        response = {"data": "data:image/png;base64," + ("A" * 9000)}
        result = self.run_hook("post-tool", self.event(response), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["continue"])

    def test_duplicate_calls_merge_and_resolve_error(self) -> None:
        failed = self.run_hook(
            "post-tool",
            self.event({"output": "Exit code: 1\nfatal: broken", "exit_code": 1}),
        )
        self.assertEqual(failed.returncode, 0, failed.stderr)
        succeeded = self.run_hook(
            "post-tool",
            self.event({"output": "fixed", "exit_code": 0}, call_id="call-2"),
        )
        self.assertEqual(succeeded.returncode, 0, succeeded.stderr)
        entries = list(self.ledger()["entries"].values())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["occurrences"], 2)
        self.assertEqual(entries[0]["status"], "success")

    def test_session_start_injects_bounded_vcc(self) -> None:
        self.run_cli("init", "--cwd", str(self.workspace))
        event = {
            "session_id": "session-1",
            "cwd": str(self.workspace),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
        result = self.run_hook("session-start", event)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("source of truth", context)
        self.assertIn("# VCC", context)

    def test_precompact_snapshots_vcc(self) -> None:
        self.run_cli("init", "--cwd", str(self.workspace))
        event = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.workspace),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
        result = self.run_hook("pre-compact", event)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["continue"])
        checkpoints = list(self.plugin_data.glob("workspaces/*/checkpoints/*.md"))
        self.assertEqual(len(checkpoints), 1)

    def test_subagent_start_adds_handoff_contract(self) -> None:
        event = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.workspace),
            "hook_event_name": "SubagentStart",
            "agent_id": "agent-1",
            "agent_type": "explorer",
        }
        result = self.run_hook("subagent-start", event)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Outcome / Evidence", context)

    def test_subagent_handoff_enforcement_is_opt_in_and_one_shot(self) -> None:
        event = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(self.workspace),
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-1",
            "agent_type": "explorer",
            "stop_hook_active": False,
            "last_assistant_message": "done",
        }
        default = self.run_hook("subagent-stop", event)
        self.assertEqual(json.loads(default.stdout), {})
        env = self.env.copy()
        env["CONTEXT_GARDENER_ENFORCE_HANDOFF"] = "1"
        enforced = self.run_hook("subagent-stop", event, env=env)
        self.assertEqual(json.loads(enforced.stdout)["decision"], "block")
        event["stop_hook_active"] = True
        repeated = self.run_hook("subagent-stop", event, env=env)
        self.assertEqual(json.loads(repeated.stdout), {})

    def test_pruning_bounds_successes_but_retains_errors(self) -> None:
        env = self.env.copy()
        env["CONTEXT_GARDENER_SUCCESS_LIMIT"] = "5"
        env["CONTEXT_GARDENER_ERROR_LIMIT"] = "5"
        for index in range(8):
            result = self.run_hook(
                "post-tool",
                self.event(
                    {"output": f"ok-{index}", "exit_code": 0},
                    command=f"echo {index}",
                    call_id=f"call-{index}",
                ),
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        error = self.run_hook(
            "post-tool",
            self.event(
                {"output": "Exit code: 1\nfatal: keep me", "exit_code": 1},
                command="broken",
                call_id="error",
            ),
            env=env,
        )
        self.assertEqual(error.returncode, 0, error.stderr)
        entries = list(self.ledger()["entries"].values())
        self.assertEqual(sum(item["status"] == "success" for item in entries), 5)
        self.assertEqual(sum(item["status"] == "error" for item in entries), 1)


if __name__ == "__main__":
    unittest.main()
