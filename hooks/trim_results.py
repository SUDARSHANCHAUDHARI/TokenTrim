#!/usr/bin/env python3
"""PostToolUse hook on Bash: hand the model a trimmed result when the output is over the limit.

The full output is saved to a file first and the trimmed text names its path. Fails open: any
error exits 0 with no output, so the model sees the original result.

usage (hooks.json): trim_results.py --data "${CLAUDE_PLUGIN_DATA}"
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trim_core  # noqa: E402


def data_dir(argv):
    if "--data" in argv:
        i = argv.index("--data")
        if i + 1 < len(argv) and argv[i + 1]:
            return argv[i + 1]
    return os.environ.get("TOKENTRIM_DIR") or "~/.cache/tokentrim"


def build_output(event, root, limit):
    """The hook's stdout as a dict, or None to leave the result alone."""
    if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command") or ""
    if trim_core.opted_out(command):
        return None
    response = event.get("tool_response")
    if not isinstance(response, dict):
        return None
    stdout, stderr = response.get("stdout") or "", response.get("stderr") or ""
    if len(stdout) <= limit and len(stderr) <= limit:
        return None
    full = trim_core.save_full(f"$ {command}\n--- stdout\n{stdout}\n--- stderr\n{stderr}",
                               Path(root) / "output", event.get("session_id"))
    updated = dict(response)  # keep every other field so the shape matches the tool's own
    updated["stdout"] = trim_core.trim_text(stdout, full, limit) or stdout
    updated["stderr"] = trim_core.trim_text(stderr, full, limit) or stderr
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        out = build_output(json.load(sys.stdin), data_dir(argv), trim_core.limit_from_env())
        if out:
            print(json.dumps(out))
    except Exception:  # fail open: never block or break a tool result
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
