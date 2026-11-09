import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import prove  # noqa: E402


def write_transcript(path, messages):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\nnot json\n")


def assistant(mid, inp, cc=0, cr=0, out=0):
    return {"type": "assistant", "message": {"id": mid, "usage": {
        "input_tokens": inp, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr, "output_tokens": out}}}


class Usage(unittest.TestCase):
    def test_dedupe_by_message_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            write_transcript(p, [assistant("m1", 10, 100, 5, 7), assistant("m1", 10, 100, 5, 7),
                                 assistant("m2", 1, 0, 200, 3), {"type": "user", "message": {"content": "x"}}])
            self.assertEqual(prove.sum_usage(p), (316, 10))

    def test_transcript_lookup_direct_and_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            cfg, cwd = Path(d) / "cfg", Path(d) / "run"
            cwd.mkdir()
            direct = cfg / "projects" / prove.slug(cwd) / "s1.jsonl"
            write_transcript(direct, [])
            self.assertEqual(prove.transcript_for("s1", cwd, cfg), direct)
            other = cfg / "projects" / "elsewhere" / "s2.jsonl"
            write_transcript(other, [])
            self.assertEqual(prove.transcript_for("s2", cwd, cfg), other)
            self.assertIsNone(prove.transcript_for("s3", cwd, cfg))


class Fixture(unittest.TestCase):
    def test_secret_sits_in_the_middle(self):
        with tempfile.TemporaryDirectory() as d:
            path = prove.make_fixture(d, "ABC123")
            out = subprocess.run([sys.executable, "-I", str(path)], capture_output=True, text=True).stdout.splitlines()
            self.assertEqual(len(out), prove.NOISE_LINES)
            self.assertEqual(out[prove.NOISE_LINES // 2], "ERROR: build id ABC123")
            self.assertEqual(sum("ABC123" in l for l in out), 1)


class FakeClaude:
    """Writes a transcript per call and answers like a model would."""

    def __init__(self, cfg, answer_right=True, cost_by_side=None):
        self.cfg, self.calls, self.n, self.names = Path(cfg), [], 0, {}
        self.answer_right, self.cost_by_side = answer_right, cost_by_side or {}

    def __call__(self, prompt, cwd, env, allowed, resume=None):
        self.calls.append({"prompt": prompt, "env": dict(env), "allowed": allowed, "resume": resume})
        sid = resume or f"sess-{self.n}"
        self.n += 1
        side = "off" if env else "on"
        path = self.cfg / "projects" / prove.slug(cwd) / f"{sid}.jsonl"
        old = path.read_text().splitlines() if path.is_file() else []
        msgs = [json.loads(l) for l in old if l.startswith("{")]
        msgs.append(assistant(f"{sid}-{len(msgs)}", self.cost_by_side.get(side, 100), out=5))
        write_transcript(path, msgs)
        if "build id" in prompt:
            fixture = prompt.split("python3 -I ", 1)[1].split(" .", 1)[0]
            secret = Path(fixture).read_text().split("build id ", 1)[1].split("'", 1)[0]
            return {"session_id": sid, "result": secret if self.answer_right else "no idea"}
        if "create the file " in prompt:
            self.names[sid] = prompt.split("create the file ", 1)[1].split(" ", 1)[0]
        if "filename" in prompt:
            return {"session_id": sid, "result": self.names[sid] if self.answer_right else "?"}
        return {"session_id": sid, "result": "DONE"}


class ProveRuns(unittest.TestCase):
    def test_trim_sides_alternate_with_their_env_and_count_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            fake = FakeClaude(Path(d) / "cfg", cost_by_side={"on": 100, "off": 400})
            rows = prove.prove("trim", 2, fake, Path(d) / "work", Path(d) / "cfg")
            self.assertEqual([r["side"] for r in rows], ["on", "off", "on", "off"])
            self.assertEqual([c["env"] for c in fake.calls],
                             [{}, {"TOKENTRIM_LIMIT": prove.OFF_LIMIT}] * 2)
            s = prove.summarize(rows)
            self.assertEqual((s["on"]["passed"], s["off"]["passed"]), (2, 2))
            self.assertEqual((s["on"]["mean_billed_input"], s["off"]["mean_billed_input"]), (100, 400))
            self.assertAlmostEqual(s["input_change"], -0.75)

    def test_wrong_answer_fails_comprehension(self):
        with tempfile.TemporaryDirectory() as d:
            fake = FakeClaude(Path(d) / "cfg", answer_right=False)
            s = prove.summarize(prove.prove("control", 1, fake, Path(d) / "work", Path(d) / "cfg"))
            self.assertEqual((s["on"]["passed"], s["off"]["passed"]), (0, 0))
            self.assertEqual(s["input_change"], 0)

    def test_checkpoint_runs_three_calls_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            fake = FakeClaude(Path(d) / "cfg")
            rows = prove.prove("checkpoint", 1, fake, Path(d) / "work", Path(d) / "cfg")
            self.assertEqual(len(fake.calls), 6)
            self.assertEqual([c["prompt"] for c in fake.calls[:3]][1], "/compact")
            self.assertEqual(fake.calls[1]["resume"], fake.calls[2]["resume"])
            self.assertEqual(fake.calls[3]["env"], {"TOKENTRIM_CHECKPOINT": "off"})
            self.assertTrue(all(r["passed"] for r in rows))
            self.assertEqual(rows[0]["billed_input"], 300)

    def test_error_run_counts_as_not_counted(self):
        def broken(prompt, cwd, env, allowed, resume=None):
            return {"is_error": True, "result": "auth failed"}
        with tempfile.TemporaryDirectory() as d:
            rows = prove.prove("trim", 1, broken, Path(d) / "work", Path(d) / "cfg")
            s = prove.summarize(rows)
            self.assertEqual(s["on"]["counted"], 0)
            self.assertIsNone(s["input_change"])
            self.assertEqual(rows[0]["error"], "auth failed")
            self.assertIn("-", prove.report("trim", s))

    def test_runs_must_be_positive(self):
        self.assertEqual(prove.main(["trim", "--runs", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
