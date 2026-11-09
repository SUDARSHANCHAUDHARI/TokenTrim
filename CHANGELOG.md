# Changelog

Notable changes to TokenTrim. Versions follow [semantic versioning](https://semver.org/), and the
version in `.claude-plugin/plugin.json` is the one a release is tagged with.

## [0.1.0] — 2026-11-08

First version. Not yet published.

### Added

- `audit`: estimate of the tokens a config loads before the first prompt, one line per source,
  largest first. Counts CLAUDE.md and its imports, rules, the memory index, and the skills and agents
  listings of the user and of enabled plugins.
- Result trimming on Bash: over `TOKENTRIM_LIMIT` (8,000 characters) the full result is saved and
  the model gets the head, the failure-looking middle lines, the tail and the path. `# full-output`
  in a command opts out. Fails open.
- Compaction checkpoint: PreCompact writes the open task, files edited and last replies;
  SessionStart after a compaction prints the path and a summary. `TOKENTRIM_CHECKPOINT=off` turns it
  off. Fails open.
- `status`: limit, switches, saved results and checkpoints.
- `prove`: A/B runs of `control`, `trim` or `checkpoint` in headless sessions, billed tokens from
  the transcripts, a comprehension check per run, results as JSON.

### Measured

- Live, in a headless session with the plugin loaded: trimming, the opt-out, `audit` and the
  checkpoint all worked.
- `prove trim --runs 2` on haiku: billed input 66,921 with trimming against 74,154 without (-9.8%),
  comprehension 2 of 2 on each side. Too few runs to keep the feature; the 20-run proof is still to
  do, after a 20-run control.
