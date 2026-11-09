# TokenTrim

A Claude Code plugin that shows where a session's tokens go before the first prompt, trims long
Bash results, keeps a checkpoint across compaction, and proves each cut with an A/B count taken
from real transcripts.

Python 3, standard library only. No daemon, no network calls, and no change to your settings:
TokenTrim reports, and you decide what to trim.

## What it does

| Part | When it runs | What it does |
|---|---|---|
| `audit` | `/tokentrim:tokentrim audit` | Estimates the tokens your config loads before the first prompt: CLAUDE.md and its imports, rules, the memory index, the skills and agents listings. One line per source, largest first. |
| Result trimming | after every Bash call | A result over 8,000 characters is saved to a file. The model gets the first 40 lines, every failure-looking line from the middle with its line number, the last 40 lines and the file path. |
| Checkpoint | before compaction, and on the session start that follows it | Writes the open task, the files edited and the last replies to a file, then puts its path and a short summary back into context. |
| `status` | `/tokentrim:tokentrim status` | Shows the limit, the switches, and how many results and checkpoints have been saved. |
| `prove` | `/tokentrim:tokentrim prove <feature>` | Runs the same headless task with a feature on and off and compares billed tokens and a comprehension answer. Spends real tokens. |

## Install

Try it for one session without installing:

```bash
claude --plugin-dir /path/to/TokenTrim
```

Or add it through a local marketplace the same way as any other plugin, then restart.

## Settings

All by environment variable; nothing is written to your settings.

| Variable | Default | Effect |
|---|---|---|
| `TOKENTRIM_LIMIT` | `8000` | Characters above which a Bash result is trimmed |
| `TOKENTRIM_CHECKPOINT` | on | `off` turns the checkpoint off |

Add `# full-output` to a Bash command to get its result untouched.

Saved results and checkpoints live in the plugin's data folder (`${CLAUDE_PLUGIN_DATA}`), under
`output/<session>/` and `checkpoints/`.

## What it does not do

- It does not trim failed Bash results. Claude Code lets a hook replace only a successful result;
  for a failure a hook can only add context.
- It does not help with very large results. Claude Code already replaces those with a short
  preview and a file path (seen on an 81 KB result, on both sides of an A/B), so TokenTrim's
  effect is on results between its limit and that size. An 18 KB result was below it.
- `audit` counts only what is readable offline. The system prompt, built-in tools, MCP server
  instructions and SessionStart hook output are not counted, and in an interactive session they are
  most of the fixed context.

## Proving a feature

```bash
python3 -I scripts/prove.py control --runs 20   # both sides identical: measures the noise
python3 -I scripts/prove.py trim --runs 20
python3 -I scripts/prove.py checkpoint --runs 20
```

Each run is a fresh `claude -p` session in its own folder with the plugin loaded on both sides; only
the feature's switch differs, and the sides alternate. Billed input is input plus cache creation plus
cache read, counted once per message from the run's transcript. A feature is kept only if it saves
tokens beyond the control's noise and passes the comprehension check on every run.

## Tests

```bash
python3 -I -m unittest discover -s tests
```

## Licence

MIT. See [LICENSE](LICENSE).
