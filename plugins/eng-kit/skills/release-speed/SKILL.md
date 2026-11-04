---
name: release-speed
description: Measure how long a change takes to reach staging and production in this project, from the local Git history (no network, no token); optional GitLab API mode for merge request and deployment times.
disable-model-invocation: true
argument-hint: "[--days N] [--staging <branch>] [--production <branch>] [--environment <name>] [--list]"
---

# /eng-kit:release-speed

1. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" release-speed $ARGUMENTS
   ```

   It reads the local Git history (`origin/<branch>` when present), so suggest `git fetch` first if the
   output says the history is old. Defaults come from `.eng-kit/config.json` (`release.staging_branch` =
   `staging`, `release.production_branch` = `main`, `release.window_days` = 30); for one main branch set both
   to it. Back-merges and release branches are left out (`release.exclude_source_patterns`); the first line
   says how many. When a number looks wrong, run again with `--list > .eng-kit/release-list.txt` and read the
   file.
2. Explain the numbers in one or two lines:
   - **Code ready → staging**: the change's first commit → its merge into the staging branch.
   - **Code ready → production**: first commit → the first production-branch commit that contains it.
   - **Merge request open → merged** and **merged → deployed**: only in GitLab mode
     (`config set release.source gitlab`), which calls the API with the person's own token.
   Medians matter more than averages; p90 shows the slow tail.
3. In GitLab mode, token handling is the same as `/eng-kit:import-ci`: never print or store the token.
4. Offer `/eng-kit:dashboard`, which shows the latest snapshot.

These are lead times of the team's flow. Test speed is one part of them; review and release habits are
the rest.
