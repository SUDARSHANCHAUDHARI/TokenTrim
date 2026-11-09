import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def run(script, event, data, raw=None, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "TOKENTRIM_LIMIT"}
    env.update(env_extra or {})
    start = time.monotonic()
    p = subprocess.run([sys.executable, "-I", str(HOOKS / script), "--data", data],
                       input=raw if raw is not None else json.dumps(event),
                       capture_output=True, text=True, env=env, timeout=10)
    return p, time.monotonic() - start


def bash_event(stdout, command="pnpm test", stderr=""):
    return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s1",
            "tool_input": {"command": command},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}}


class TrimResultsHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_under_limit_prints_nothing(self):
        p, _ = run("trim_results.py", bash_event("ok\n"), self.data)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_over_limit_replaces_output_and_saves_full(self):
        big = "\n".join(f"row {i}" for i in range(3000)) + "\nFAILED 1 test"
        p, elapsed = run("trim_results.py", bash_event(big), self.data)
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        upd = out["updatedToolOutput"]
        self.assertEqual(set(upd), {"stdout", "stderr", "interrupted", "isImage"})
        self.assertLess(len(upd["stdout"]), len(big) // 4)
        self.assertIn("FAILED 1 test", upd["stdout"])
        saved = upd["stdout"].split("Full output: ", 1)[1].split("]", 1)[0]
        self.assertIn("row 1500", Path(saved).read_text())
        self.assertTrue(saved.startswith(str(Path(self.data) / "output" / "s1")))
        self.assertLess(elapsed, 2.0)

    def test_stderr_only_over_limit(self):
        p, _ = run("trim_results.py", bash_event("fine", stderr="warn\n" * 5000), self.data)
        upd = json.loads(p.stdout)["hookSpecificOutput"]["updatedToolOutput"]
        self.assertEqual(upd["stdout"], "fine")
        self.assertIn("tokentrim:", upd["stderr"])

    def test_opt_out_untouched(self):
        p, _ = run("trim_results.py", bash_event("x\n" * 9000, command="cat big.log  # full-output"), self.data)
        self.assertEqual(p.stdout, "")

    def test_other_tool_untouched(self):
        ev = bash_event("x\n" * 9000)
        ev["tool_name"] = "Grep"
        p, _ = run("trim_results.py", ev, self.data)
        self.assertEqual(p.stdout, "")

    def test_bad_input_fails_open(self):
        for raw in ("not json", "", json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                                                "tool_response": "a string"})):
            p, _ = run("trim_results.py", None, self.data, raw=raw)
            self.assertEqual((p.returncode, p.stdout), (0, ""), raw)

    def test_limit_env(self):
        p, _ = run("trim_results.py", bash_event("y\n" * 300), self.data, env_extra={"TOKENTRIM_LIMIT": "100"})
        self.assertIn("updatedToolOutput", p.stdout)


class CheckpointHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = self.tmp.name
        self.transcript = Path(self.tmp.name) / "t.jsonl"
        rows = [
            {"type": "user", "message": {"content": "fix the login bug"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Looking at auth.ts"},
                {"type": "tool_use", "id": "a", "name": "Edit", "input": {"file_path": "/r/auth.ts"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "b", "name": "Write", "input": {"file_path": "/r/new.ts"}},
                {"type": "tool_use", "id": "c", "name": "Edit", "input": {"file_path": "/r/auth.ts"}}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Decided: keep the token check"}]}},
        ]
        self.transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")

    def tearDown(self):
        self.tmp.cleanup()

    def precompact(self):
        return run("checkpoint.py", {"hook_event_name": "PreCompact", "trigger": "auto", "session_id": "s9",
                                     "transcript_path": str(self.transcript)}, self.data)[0]

    def test_precompact_writes_file_and_prints_nothing(self):
        p = self.precompact()
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        text = (Path(self.data) / "checkpoints" / "s9.md").read_text()
        self.assertIn("fix the login bug", text)
        self.assertEqual(text.count("- /r/auth.ts"), 1)
        self.assertIn("- /r/new.ts", text)
        self.assertIn("Decided: keep the token check", text)

    def test_session_start_compact_prints_summary(self):
        self.precompact()
        p, _ = run("checkpoint.py", {"hook_event_name": "SessionStart", "source": "compact", "session_id": "s9"},
                   self.data)
        self.assertIn("checkpoints/s9.md", p.stdout)
        self.assertIn("Open task: fix the login bug", p.stdout)
        self.assertIn("Files touched: 2", p.stdout)

    def test_other_session_start_sources_print_nothing(self):
        self.precompact()
        for source in ("startup", "resume", "clear", "fork"):
            p, _ = run("checkpoint.py", {"hook_event_name": "SessionStart", "source": source, "session_id": "s9"},
                       self.data)
            self.assertEqual(p.stdout, "", source)

    def test_off_switch_writes_and_prints_nothing(self):
        off = {"TOKENTRIM_CHECKPOINT": "off"}
        p, _ = run("checkpoint.py", {"hook_event_name": "PreCompact", "trigger": "auto", "session_id": "s9",
                                     "transcript_path": str(self.transcript)}, self.data, env_extra=off)
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertFalse((Path(self.data) / "checkpoints" / "s9.md").exists())
        self.precompact()
        p, _ = run("checkpoint.py", {"hook_event_name": "SessionStart", "source": "compact", "session_id": "s9"},
                   self.data, env_extra=off)
        self.assertEqual(p.stdout, "")

    def test_missing_transcript_fails_open(self):
        p, _ = run("checkpoint.py", {"hook_event_name": "PreCompact", "session_id": "s9",
                                     "transcript_path": "/nope.jsonl"}, self.data)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


class HooksJson(unittest.TestCase):
    def test_parses_and_points_at_real_scripts(self):
        cfg = json.loads((HOOKS / "hooks.json").read_text())
        self.assertIn("hooks", cfg)
        for event, groups in cfg["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    script = h["command"].split("/hooks/", 1)[1].split('"', 1)[0]
                    self.assertTrue((HOOKS / script).is_file(), f"{event}: {script}")


if __name__ == "__main__":
    unittest.main()
