#!/usr/bin/env python3
"""TokenTrim prove: A/B a feature with real headless Claude runs and count billed tokens.

Each run is a fresh `claude -p` session in its own folder, with this plugin loaded on both sides;
only the feature's switch differs. Sides alternate (on, off, on, off, ...) so drift hits both.
Tokens come from the run's transcript JSONL, one count per message id:
billed input = input + cache creation + cache read; output counted separately.
Every run also answers a question whose answer sits inside the output the feature touches.

features:
  control     trim on, both sides. The difference must be near zero before any result counts.
  trim        Bash result trimming on vs off (off = a limit no output reaches)
  checkpoint  compaction checkpoint on vs off (TOKENTRIM_CHECKPOINT=off)

usage: prove.py <feature> [--runs N] [--model M] [--claude PATH] [--budget-usd X]
                [--workdir DIR] [--out FILE] [--with-user-settings]
Spends real tokens: runs x 2 sides x (1 call, or 3 for checkpoint).
"""
import argparse
import json
import os
import random
import re
import shutil
import statistics
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
OFF_LIMIT = str(10 ** 12)
# About 18 KB: above TokenTrim's 8,000-char limit, below the size where Claude Code already swaps the
# result for a ~2 KB "<persisted-output>" preview itself (an 81 KB run showed that on both sides).
NOISE_LINES = 900

SIDES = {
    "control": ({}, {}),
    "trim": ({}, {"TOKENTRIM_LIMIT": OFF_LIMIT}),
    "checkpoint": ({}, {"TOKENTRIM_CHECKPOINT": "off"}),
}


def token(n=8):
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def make_fixture(folder, secret):
    """A script printing NOISE_LINES lines with one ERROR line carrying `secret` in the middle."""
    path = Path(folder) / "noisy.py"
    path.write_text(
        "for i in range(%d):\n"
        "    print('ERROR: build id %s' if i == %d else f'compile step {i} ok')\n" % (NOISE_LINES, secret, NOISE_LINES // 2)
    )
    return path


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def transcript_for(session_id, cwd, config_dir):
    """The run's JSONL: projects/<slug of cwd>/<session>.jsonl, else any project with that id."""
    projects = Path(config_dir).expanduser() / "projects"
    direct = projects / slug(cwd) / f"{session_id}.jsonl"
    if direct.is_file():
        return direct
    found = list(projects.glob(f"*/{session_id}.jsonl"))
    return found[0] if found else None


def sum_usage(path):
    """(billed_input, output) for one transcript, one count per message id."""
    seen, billed, output = set(), 0, 0
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            msg = o.get("message") or {}
            u, mid = msg.get("usage"), msg.get("id")
            if o.get("type") != "assistant" or not u or mid in seen:
                continue
            seen.add(mid)
            billed += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                + (u.get("cache_read_input_tokens") or 0)
            output += u.get("output_tokens") or 0
    return billed, output


def claude_runner(claude, model, budget, user_settings):
    """A function (prompt, cwd, env, allowed, resume) -> parsed `--output-format json` result."""
    def run(prompt, cwd, env, allowed, resume=None):
        cmd = [claude, "-p", prompt, "--plugin-dir", str(PLUGIN_ROOT), "--model", model,
               "--permission-mode", "dontAsk", "--output-format", "json", "--max-budget-usd", str(budget)]
        if allowed:
            cmd += ["--allowedTools", allowed]
        if not user_settings:
            cmd += ["--setting-sources", "local"]
        if resume:
            cmd += ["--resume", resume]
        p = subprocess.run(cmd, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True, timeout=600)
        try:
            return json.loads(p.stdout)
        except ValueError:
            return {"is_error": True, "result": (p.stderr or p.stdout)[-500:]}
    return run


def one_run(feature, run, folder, env):
    """Run the scripted task once. Returns (session_id, passed, error)."""
    folder.mkdir(parents=True, exist_ok=True)
    if feature in ("control", "trim"):
        secret = token()
        fixture = make_fixture(folder, secret)
        r = run(f"Run exactly this Bash command: python3 -I {fixture} . Then reply with only the build id "
                f"from the ERROR line, nothing else.", folder, env, "Bash(python3 *)")
        return r.get("session_id"), secret in str(r.get("result")), r.get("result") if r.get("is_error") else None
    name, word = f"note-{token(6).lower()}.txt", token()
    r = run(f"Use the Write tool to create the file {name} in the current directory containing only the word "
            f"{word}. Then reply DONE.", folder, env, "Write")
    sid = r.get("session_id")
    if r.get("is_error") or not sid:
        return sid, False, r.get("result")
    run("/compact", folder, env, None, resume=sid)
    r = run("What exact filename did you create earlier? Reply with only the filename.", folder, env, None, resume=sid)
    return sid, name in str(r.get("result")), r.get("result") if r.get("is_error") else None


def prove(feature, runs, run, workdir, config_dir):
    on_env, off_env = SIDES[feature]
    rows = []
    for i in range(runs):
        for side, env in (("on", on_env), ("off", off_env)):
            folder = Path(workdir) / f"{side}-{i + 1}"
            sid, passed, error = one_run(feature, run, folder, env)
            path = transcript_for(sid, folder, config_dir) if sid else None
            billed, output = sum_usage(path) if path else (None, None)
            rows.append({"side": side, "run": i + 1, "session_id": sid, "passed": passed,
                         "billed_input": billed, "output": output, "error": error})
    return rows


def summarize(rows):
    out = {}
    for side in ("on", "off"):
        mine = [r for r in rows if r["side"] == side]
        counted = [r for r in mine if r["billed_input"] is not None]
        out[side] = {
            "runs": len(mine),
            "counted": len(counted),
            "passed": sum(1 for r in mine if r["passed"]),
            "mean_billed_input": statistics.mean(r["billed_input"] for r in counted) if counted else None,
            "mean_output": statistics.mean(r["output"] for r in counted) if counted else None,
        }
    on, off = out["on"]["mean_billed_input"], out["off"]["mean_billed_input"]
    out["input_change"] = (on - off) / off if on is not None and off else None
    return out


def report(feature, summary):
    lines = [f"tokentrim prove {feature}"]
    for side in ("on", "off"):
        s = summary[side]
        mi = "-" if s["mean_billed_input"] is None else f"{s['mean_billed_input']:,.0f}"
        mo = "-" if s["mean_output"] is None else f"{s['mean_output']:,.0f}"
        lines.append(f"  {side:3}  runs {s['runs']}  counted {s['counted']}  comprehension {s['passed']}/{s['runs']}"
                     f"  mean billed input {mi}  mean output {mo}")
    ch = summary["input_change"]
    lines.append("  billed input change on vs off: " + ("-" if ch is None else f"{ch:+.1%}"))
    if feature == "control":
        lines.append("  control: both sides identical, so this change is noise; trust a feature result only if "
                     "it is well beyond it")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("feature", choices=sorted(SIDES))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--claude", default=shutil.which("claude") or "claude")
    ap.add_argument("--budget-usd", type=float, default=0.5, help="cap per claude call")
    ap.add_argument("--workdir")
    ap.add_argument("--out")
    ap.add_argument("--with-user-settings", action="store_true",
                    help="also load user settings (their hooks would run on both sides)")
    a = ap.parse_args(argv)
    if a.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2
    workdir = Path(a.workdir or tempfile.mkdtemp(prefix=f"tokentrim-prove-{a.feature}-"))
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
    run = claude_runner(a.claude, a.model, a.budget_usd, a.with_user_settings)
    rows = prove(a.feature, a.runs, run, workdir, config_dir)
    summary = summarize(rows)
    print(report(a.feature, summary))
    out = Path(a.out or workdir / "results.json")
    out.write_text(json.dumps({"feature": a.feature, "model": a.model, "when": time.strftime("%Y-%m-%d %H:%M"),
                               "summary": summary, "runs": rows}, indent=2))
    print(f"  results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
