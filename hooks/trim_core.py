"""Pure trimming logic for TokenTrim's result hook. No I/O except save_full().

A result over the limit becomes: the first lines, every failure-looking line from the middle (with
its line number), the last lines, a count of what was hidden, and the path of the full copy.
"""
import hashlib
import os
import re
import time
from pathlib import Path

DEFAULT_LIMIT = 8000          # characters; about 2,000 tokens
HEAD_LINES = 40
TAIL_LINES = 40
MAX_FAILURE_LINES = 60
OPT_OUT = "# full-output"

FAILURE_RE = re.compile(
    r"error|fail|fatal|exception|traceback|panic|denied|not found|cannot|refused|timed? ?out"
    r"|\bE[A-Z]{3,}\b|✘|✗|ERR!",
    re.IGNORECASE,
)


def opted_out(command):
    return OPT_OUT in (command or "")


def save_full(text, root, session_id):
    """Write the full result to <root>/<session>/<time>-<hash>.log and return the path."""
    folder = Path(root).expanduser() / (session_id or "no-session")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{digest}.log"
    path.write_text(text, encoding="utf-8", errors="replace")
    return str(path)


def trim_text(text, full_path, limit=DEFAULT_LIMIT):
    """Return the trimmed text, or None when the text is within the limit."""
    if len(text) <= limit:
        return None
    lines = text.splitlines()
    if len(lines) <= HEAD_LINES + TAIL_LINES:
        # Few, very long lines: cut by characters instead.
        half = limit // 2
        hidden = len(text) - 2 * half
        return (f"[tokentrim: {len(text):,} chars, {hidden:,} middle chars hidden. Full output: {full_path}]\n"
                f"{text[:half]}\n…\n{text[-half:]}")
    head, middle, tail = lines[:HEAD_LINES], lines[HEAD_LINES:-TAIL_LINES], lines[-TAIL_LINES:]
    failures = [(HEAD_LINES + i + 1, line) for i, line in enumerate(middle) if FAILURE_RE.search(line)]
    shown = failures[:MAX_FAILURE_LINES]
    out = [f"[tokentrim: {len(lines):,} lines, {len(middle):,} middle lines hidden. Full output: {full_path}]"]
    out += head
    out.append(f"[failure-looking middle lines: {len(failures)}"
               + (f", first {MAX_FAILURE_LINES} shown" if len(failures) > MAX_FAILURE_LINES else "") + "]")
    out += [f"{n}: {line}" for n, line in shown]
    out.append(f"[last {len(tail)} lines]")
    out += tail
    return "\n".join(out)


def limit_from_env():
    try:
        value = int(os.environ.get("TOKENTRIM_LIMIT", DEFAULT_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT
    return value if value > 0 else DEFAULT_LIMIT
