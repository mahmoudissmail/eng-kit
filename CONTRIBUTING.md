# Contributing

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog (eng-kit-plugins)
plugins/eng-kit/                  the plugin
  .claude-plugin/plugin.json      manifest
  skills/                         commands (init, measure, import-ci, dashboard, status, optimize, report, setup-ci,
                                  release-speed) and skills (testing-standard, speed-playbook)
  hooks/hooks.json                PreToolUse / PostToolUse on Bash
  scripts/engkit.py               CLI and logic (Python 3.9+, standard library only)
  scripts/hook.py                 tiny hook entry point
  scripts/dashboard.py            dashboard builder + dashboard_template.html
  scripts/analyze.py              optimization plan (analyze, plan)
  scripts/release.py              release speed (local Git history; optional GitLab API)
  scripts/github.py               GitHub Actions import
  scripts/report.py               markdown report
  tests/                          unittest suite and JUnit fixtures
```

## Rules

- Standard library only; Python 3.9+. No network except `import-ci`.
- Every change keeps `python3 -m unittest discover -s plugins/eng-kit/tests` and
  `claude plugin validate ./plugins/eng-kit --strict` green.
- The hook stays fast: no new imports in `scripts/hook.py`.

## Try a change locally

```bash
claude --plugin-dir ./plugins/eng-kit          # load the working copy for one session
python3 plugins/eng-kit/scripts/engkit.py --project /path/to/project status
```

## Release

1. Update `version` in `plugins/eng-kit/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and
   `VERSION` in `scripts/engkit.py`; move the CHANGELOG entry from "unreleased" to the date.
2. Merge to `main` with CI green.
3. Tag `vX.Y.Z` and create a GitHub release with the CHANGELOG entry.
4. Users update with `/plugin marketplace update eng-kit-plugins`.
