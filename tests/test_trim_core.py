import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import trim_core as tc  # noqa: E402


class TrimText(unittest.TestCase):
    def test_under_limit_untouched(self):
        self.assertIsNone(tc.trim_text("short output\n", "/p", limit=100))

    def test_over_limit_keeps_head_tail_and_path(self):
        lines = [f"line {i}" for i in range(1, 501)]
        out = tc.trim_text("\n".join(lines), "/full.log", limit=100)
        self.assertIn("Full output: /full.log", out)
        self.assertIn("500 lines, 420 middle lines hidden", out)
        self.assertIn("line 1\n", out)
        self.assertIn("line 40\n", out)
        self.assertNotIn("line 41\n", out)
        self.assertTrue(out.endswith("line 500"))

    def test_failure_lines_in_middle_kept_with_line_number(self):
        lines = [f"ok {i}" for i in range(1, 301)]
        lines[149] = "npm ERR! code ENOENT"
        lines[199] = "Traceback (most recent call last):"
        out = tc.trim_text("\n".join(lines), "/f", limit=100)
        self.assertIn("150: npm ERR! code ENOENT", out)
        self.assertIn("200: Traceback (most recent call last):", out)
        self.assertIn("[failure-looking middle lines: 2]", out)
        self.assertNotIn("ok 150", out)

    def test_failure_lines_capped(self):
        lines = ["error x"] * 500
        out = tc.trim_text("\n".join(lines), "/f", limit=100)
        self.assertIn(f"first {tc.MAX_FAILURE_LINES} shown", out)
        self.assertEqual(out.count("error x"), tc.HEAD_LINES + tc.MAX_FAILURE_LINES + tc.TAIL_LINES)

    def test_few_long_lines_cut_by_characters(self):
        text = "a" * 5000 + "\n" + "b" * 5000
        out = tc.trim_text(text, "/f", limit=1000)
        self.assertIn("middle chars hidden", out)
        self.assertLess(len(out), 1300)
        self.assertTrue(out.startswith("[tokentrim:"))


class Helpers(unittest.TestCase):
    def test_opt_out(self):
        self.assertTrue(tc.opted_out("pnpm test  # full-output"))
        self.assertFalse(tc.opted_out("pnpm test"))
        self.assertFalse(tc.opted_out(None))

    def test_save_full_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = tc.save_full("full text ✓", d, "sess1")
            self.assertTrue(p.startswith(os.path.join(d, "sess1")))
            self.assertEqual(Path(p).read_text(encoding="utf-8"), "full text ✓")

    def test_limit_from_env(self):
        old = os.environ.get("TOKENTRIM_LIMIT")
        try:
            os.environ["TOKENTRIM_LIMIT"] = "500"
            self.assertEqual(tc.limit_from_env(), 500)
            for bad in ("abc", "0", "-5"):
                os.environ["TOKENTRIM_LIMIT"] = bad
                self.assertEqual(tc.limit_from_env(), tc.DEFAULT_LIMIT)
        finally:
            if old is None:
                os.environ.pop("TOKENTRIM_LIMIT", None)
            else:
                os.environ["TOKENTRIM_LIMIT"] = old


if __name__ == "__main__":
    unittest.main()
