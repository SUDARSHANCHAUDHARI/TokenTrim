import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import status  # noqa: E402


class Status(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("TOKENTRIM_LIMIT", "TOKENTRIM_CHECKPOINT", "CLAUDE_PLUGIN_DATA")}
        for k in self.saved:
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_counts_outputs_and_checkpoints(self):
        (self.data / "output" / "s1").mkdir(parents=True)
        (self.data / "output" / "s1" / "a.log").write_text("x" * 2048)
        (self.data / "output" / "s1" / "b.log").write_text("y" * 1024)
        (self.data / "checkpoints").mkdir()
        (self.data / "checkpoints" / "s1.md").write_text("# c")
        text = "\n".join(status.status_lines([self.data]))
        self.assertIn("trim limit: 8,000 chars (default)", text)
        self.assertIn("results trimmed: 2; their full copies on disk: 3 KB", text)
        self.assertIn("checkpoints: 1", text)
        self.assertIn("checkpoint: on", text)

    def test_env_switches_and_empty(self):
        os.environ["TOKENTRIM_LIMIT"] = "500"
        os.environ["TOKENTRIM_CHECKPOINT"] = "off"
        text = "\n".join(status.status_lines([]))
        self.assertIn("trim limit: 500 chars (TOKENTRIM_LIMIT)", text)
        self.assertIn("checkpoint: off", text)
        self.assertIn("no data yet", text)

    def test_data_dirs_prefers_explicit_then_own_env_then_search(self):
        ours = self.data / "plugins" / "data" / "tokentrim-inline"
        ours.mkdir(parents=True)
        self.assertEqual(status.data_dirs(str(self.data)), [self.data])
        os.environ["CLAUDE_PLUGIN_DATA"] = str(ours)
        self.assertEqual(status.data_dirs(), [ours])
        # another plugin's data dir leaking into the shell is ignored
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.data / "plugins" / "data" / "codex-openai-codex")
        old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.data)
        try:
            self.assertEqual(status.data_dirs(), [ours])
        finally:
            if old is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old


if __name__ == "__main__":
    unittest.main()
