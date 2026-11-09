#!/usr/bin/env python3
"""TokenTrim status: current limit, switches, and what the hooks have saved so far. Read only.

usage: status.py [--data DIR]
  --data  plugin data dir (default: $CLAUDE_PLUGIN_DATA when it is a tokentrim* folder, else every
          <config>/plugins/data/tokentrim* folder)
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import trim_core  # noqa: E402


def data_dirs(explicit=None):
    if explicit:
        return [Path(explicit).expanduser()]
    env = os.environ.get("CLAUDE_PLUGIN_DATA")
    # A shell can inherit another plugin's data dir; trust the variable only when it is ours.
    if env and Path(env).name.startswith("tokentrim"):
        return [Path(env)]
    config = Path(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))
    return sorted((config / "plugins" / "data").glob("tokentrim*"))


def folder_stats(folder, pattern):
    files = [f for f in folder.glob(pattern) if f.is_file()] if folder.is_dir() else []
    newest = max(files, key=lambda f: f.stat().st_mtime) if files else None
    return len(files), sum(f.stat().st_size for f in files), newest


def status_lines(dirs):
    limit = trim_core.limit_from_env()
    checkpoint = "off" if os.environ.get("TOKENTRIM_CHECKPOINT", "").lower() == "off" else "on"
    lines = [f"trim limit: {limit:,} chars" + (" (TOKENTRIM_LIMIT)" if os.environ.get("TOKENTRIM_LIMIT") else " (default)"),
             f"opt-out marker: {trim_core.OPT_OUT}",
             f"checkpoint: {checkpoint}"]
    if not dirs:
        lines.append("no data yet: no tokentrim data folder found")
    for d in dirs:
        n_out, size, newest_out = folder_stats(d / "output", "*/*.log")
        n_cp, _, newest_cp = folder_stats(d / "checkpoints", "*.md")
        lines.append(f"data: {d}")
        lines.append(f"  results trimmed: {n_out}; their full copies on disk: {size / 1024:,.0f} KB"
                     + (f", newest {newest_out}" if newest_out else ""))
        lines.append(f"  checkpoints: {n_cp}" + (f", newest {newest_cp}" if newest_cp else ""))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    print("\n".join(status_lines(data_dirs(a.data))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
