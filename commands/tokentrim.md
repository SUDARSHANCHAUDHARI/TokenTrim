---
description: TokenTrim. `audit` estimates fixed context, `status` shows what the hooks saved, `prove` A/B tests a feature.
argument-hint: audit | status | prove <control|trim|checkpoint> [--runs N]
---

Run the TokenTrim subcommand in `$ARGUMENTS`. Show each script's output as is. Do not change any
file: TokenTrim only reports; the user decides what to trim. Commands carry no shell variables, so a
permission rule like `Bash(python3 -I *)` matches them.

- `audit` (or no argument): run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py"` (it reads
  `CLAUDE_CONFIG_DIR` and the current directory itself). Then name the three largest sources in one
  line each.
- `status`: run `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/status.py"`.
- `prove <feature> [--runs N]`: this spends real tokens (runs x 2 sides, 3 calls a run for
  checkpoint). Say the run count and ask the user to confirm before starting. Then run
  `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/prove.py" <feature> --runs N`. Run `control` before a
  feature result is trusted.
- Anything else: list the three subcommands.
