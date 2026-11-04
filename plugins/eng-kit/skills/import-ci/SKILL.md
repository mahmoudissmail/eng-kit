---
name: import-ci
description: Record a CI test run in eng-kit - a GitLab job (id, URL or latest) or a GitHub Actions run (id, URL or latest) - read-only, using the person's own token. Use when the person wants a CI run on the local dashboard or asks how long the last CI run took.
disable-model-invocation: true
argument-hint: "<latest | GitLab job id or URL | GitHub run id or URL> [--label <text>]"
---

# /eng-kit:import-ci

Read-only: it reads the run's duration, runner and test report from the CI host and records them locally. It never
writes to GitLab or GitHub.

1. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" import-ci $ARGUMENTS
   ```

   - `latest` takes the newest finished job named `ci.job_name` (default `tests`) on GitLab, or the newest completed
     GitHub run with an artifact named `ci.artifact` (default `junit`).
   - The host is taken from the URL, from `ci.provider` if set, or from the `origin` remote (github.com → GitHub).
2. Tokens are read at call time, never printed, stored or put on a command line:
   - GitLab: `GITLAB_TOKEN` (scope `read_api`), or `ci.token_file` + `ci.token_key`.
   - GitHub: `GITHUB_TOKEN` (fine-grained, `Actions: read` on the repository), or `ci.github_token_file` +
     `ci.github_token_key`.
   If the script says there is no token, tell the person which variable or file it looked for.
3. If the host answers 401/403/404, say what the script says (token scope, project path `config set ci.project …`,
   self-hosted GitLab or GitHub Enterprise `config set ci.host …`).
4. If the run has no test report: GitLab needs `artifacts: reports: junit`; GitHub needs `actions/upload-artifact`
   with `name: junit` (see `/eng-kit:setup-ci`).
5. Report the `Recorded …` line exactly and offer `/eng-kit:dashboard`.
