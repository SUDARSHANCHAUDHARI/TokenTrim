#!/usr/bin/env python3
"""Compaction checkpoint.

PreCompact: write the open task, the files touched and the last replies to
<data>/checkpoints/<session>.md. Prints nothing: PreCompact stdout becomes compaction instructions.
SessionStart with source "compact": print the checkpoint path and a short summary, which the host
adds to context. Any other source prints nothing. Fails open: errors exit 0 with no output.
TOKENTRIM_CHECKPOINT=off turns both halves off.

usage (hooks.json): checkpoint.py --data "${CLAUDE_PLUGIN_DATA}"
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trim_results import data_dir  # noqa: E402

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
LAST_REPLIES = 3
REPLY_CHARS = 600


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_transcript(path):
    """(last real user prompt, files touched in order, last assistant replies)."""
    prompt, files, replies = "", [], []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            msg = o.get("message") or {}
            content = msg.get("content")
            if o.get("type") == "user" and not o.get("isMeta"):
                text = text_of(content).strip()
                if text and not text.startswith("<"):  # skip tool results and injected tags
                    prompt = text
            elif o.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                        f = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if f and f not in files:
                            files.append(f)
                reply = text_of(content).strip()
                if reply:
                    replies = (replies + [reply])[-LAST_REPLIES:]
    return prompt, files, replies


def checkpoint_path(root, session_id):
    return Path(root).expanduser() / "checkpoints" / f"{session_id or 'no-session'}.md"


def write_checkpoint(event, root):
    prompt, files, replies = read_transcript(event["transcript_path"])
    path = checkpoint_path(root, event.get("session_id"))
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"# Checkpoint before compaction ({event.get('trigger', '?')}), {time.strftime('%Y-%m-%d %H:%M')}",
            "", "## Open task", "", prompt or "(no user prompt found)", "", "## Files touched", ""]
    body += [f"- {f}" for f in files] or ["- none"]
    body += ["", "## Last replies", ""]
    body += [f"> {r[:REPLY_CHARS]}".replace("\n", "\n> ") + "\n" for r in replies] or ["(none)"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def session_start_text(event, root):
    if event.get("source") != "compact":
        return ""
    path = checkpoint_path(root, event.get("session_id"))
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    files = [l for l in text.splitlines() if l.startswith("- ") and l != "- none"]
    task = text.split("## Open task", 1)[-1].split("##", 1)[0].strip().splitlines()
    first = task[0][:200] if task else ""
    return f"TokenTrim checkpoint from before compaction: {path}\nOpen task: {first}\nFiles touched: {len(files)}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if os.environ.get("TOKENTRIM_CHECKPOINT", "").lower() == "off":  # the off side of `prove`
            return 0
        event = json.load(sys.stdin)
        root = data_dir(argv)
        name = event.get("hook_event_name")
        if name == "PreCompact":
            write_checkpoint(event, root)
        elif name == "SessionStart":
            text = session_start_text(event, root)
            if text:
                print(text)
    except Exception:  # fail open
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
