#!/usr/bin/env python3
"""TokenTrim audit: estimate the tokens a Claude Code config loads before the first prompt.

Read only. One line per source, largest first. Sizes are chars/4 estimates; the model's own
tokenizer is not available offline.

usage: audit.py [--config DIR] [--project PATH]
  --config   Claude config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)
  --project  working directory whose auto-memory index (MEMORY.md) should be counted (default: cwd)
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

NOT_COUNTED = ("system prompt and built-in tools", "MCP server instructions and tool names",
               "SessionStart hook output")


def tokens(text):
    return len(text) // 4


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def frontmatter(text):
    """name and description from a leading --- block. Folded (>, |) values are joined."""
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out, key = {}, None
    for line in m.group(1).splitlines():
        kv = re.match(r"([A-Za-z_-]+):\s*(.*)", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            out[key] = "" if val in (">", "|", ">-", "|-") else val.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def claude_md(path, seen):
    """A CLAUDE.md file plus every @import it pulls in, each as its own source."""
    path = Path(os.path.expanduser(str(path))).resolve()
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    text = read(path)
    rows = [(f"CLAUDE.md {path}", tokens(text))]
    for ref in re.findall(r"^@(\S+)", text, re.M):
        target = Path(os.path.expanduser(ref))
        rows += claude_md(target if target.is_absolute() else path.parent / target, seen)
    return rows


def listing(files):
    """Tokens for the "- name: description" lines the model sees for skills or agents."""
    total = count = 0
    for f in files:
        fm = frontmatter(read(f))
        fallback = Path(f).parent.name if Path(f).name == "SKILL.md" else Path(f).stem
        total += tokens(f"- {fm.get('name') or fallback}: {fm.get('description', '')}\n")
        count += 1
    return total, count


def enabled_plugin_dirs(config):
    try:
        enabled = json.loads(read(config / "settings.json") or "{}").get("enabledPlugins", {})
        installed = json.loads(read(config / "plugins" / "installed_plugins.json") or "{}").get("plugins", {})
    except ValueError:
        return []
    dirs = []
    for key, on in enabled.items():
        if not on:
            continue
        for inst in installed.get(key, []):
            if inst.get("scope") == "user" and inst.get("installPath"):
                dirs.append(Path(inst["installPath"]))
                break
    return dirs


def project_slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def audit(config, project=None):
    config = Path(config)
    rows = claude_md(config / "CLAUDE.md", set())
    for f in sorted((config / "rules").glob("*.md")):
        rows.append((f"rule {f.name}", tokens(read(f))))
    if project:
        mem = config / "projects" / project_slug(project) / "memory" / "MEMORY.md"
        if mem.is_file():
            rows.append(("memory index MEMORY.md", tokens(read(mem))))

    plugins = enabled_plugin_dirs(config)
    groups = {
        "skills listing (user)": list((config / "skills").glob("*/SKILL.md")),
        "agents listing (user)": list((config / "agents").glob("*.md")),
        "skills listing (plugins)": [f for p in plugins for f in p.glob("skills/*/SKILL.md")]
        + [f for p in plugins for f in p.glob("commands/*.md")],
        "agents listing (plugins)": [f for p in plugins for f in p.glob("agents/*.md")],
    }
    for label, files in groups.items():
        tok, n = listing(files)
        if n:
            rows.append((f"{label}, {n} items", tok))
    return sorted(rows, key=lambda r: -r[1])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    ap.add_argument("--project", default=os.getcwd())
    a = ap.parse_args(argv)
    config = Path(os.path.expanduser(a.config))
    if not config.is_dir():
        print(f"no config dir at {config}", file=sys.stderr)
        return 2
    rows = audit(config, a.project)
    total = sum(t for _, t in rows)
    for label, tok in rows:
        print(f"{tok:>8,}  {tok / total if total else 0:6.1%}  {label}")
    print(f"{total:>8,}  total (estimate, chars/4)")
    print("not counted (needs a live session): " + "; ".join(NOT_COUNTED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
