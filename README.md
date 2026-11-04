# eng-kit — test speed for Claude Code

**Know how fast your test suite is, make it faster, keep it fast.** eng-kit is a Claude Code plugin that
records every full test run of a project, compares it with a baseline, imports GitLab CI runs, turns the
measurements into a ranked optimization plan that Claude applies one measured change at a time, tracks how
long changes take to reach staging and production, and builds an offline dashboard. It also gives Claude a
testing standard and a speed playbook, so the code it writes keeps the suite fast.

- **Local and private.** All data stays in the project's `.eng-kit/` folder on your machine, hidden from Git.
  No server, no account, nothing sent anywhere.
- **Automatic.** When Claude runs the full suite, the run is recorded on its own. No copy and paste.
- **Fixes, not only numbers.** `/eng-kit:optimize` finds where the time goes (setup, seeding, boot, parallel
  safety, test database, CI runner and pipeline, guards) and applies one change per merge request, each
  measured against the baseline, never by checking less.
- **Any stack that writes JUnit XML.** Laravel, PHPUnit, Pest, Vitest, Jest, pytest, Go, Maven, Gradle,
  .NET, RSpec, Rust.
- **GitLab and GitHub.** Imports CI runs from GitLab jobs or GitHub Actions runs, measures release speed from
  any Git history, and `/eng-kit:setup-ci` gives CI templates and a runner guide for both.
- **Production ready.** Standard-library Python, 53 automated tests, validated with
  `claude plugin validate --strict`, fast hooks (about 25 ms per Bash call).

---

## For a team: start here

1. **Install once per developer** (see [Install](#install)), or ask an admin to add it to managed settings.
2. **In each project, once:** `/eng-kit:init`. It hides `.eng-kit/` from Git, so every developer has their own
   local records.
3. **CI on every request:** `/eng-kit:setup-ci` writes the CI file from a template (GitLab or GitHub) after your yes,
   and explains how to run it on your own machine if you want no CI minutes.
4. **Day to day:**
   - Claude records full runs it starts on its own (any command that writes JUnit);
   - `/eng-kit:import-ci latest` after a CI run;
   - `/eng-kit:status` or `/eng-kit:dashboard` to see where you stand;
   - `/eng-kit:optimize` to make it faster;
   - `/eng-kit:report` to share the results.

Every developer gets the same skills and commands; results stay on each machine unless someone shares a report.
See [docs/TEAM.md](docs/TEAM.md) for a one-page guide to hand to new developers.

## Contents

1. [What you get](#what-you-get)
2. [Supported stacks](#supported-stacks)
3. [Requirements](#requirements)
4. [Install](#install)
5. [Quick start](#quick-start)
6. [Commands](#commands)
7. [Skills Claude uses on its own](#skills-claude-uses-on-its-own)
8. [Automatic recording](#automatic-recording)
9. [Importing CI runs (GitLab and GitHub)](#importing-ci-runs-gitlab-and-github)
10. [Optimizing a project](#optimizing-a-project)
11. [Release speed](#release-speed)
12. [The dashboard](#the-dashboard)
13. [How runs are compared](#how-runs-are-compared)
14. [Configuration](#configuration)
15. [Data format](#data-format)
16. [Privacy and security](#privacy-and-security)
17. [Performance](#performance)
18. [Best practices for a fast suite](#best-practices-for-a-fast-suite)
19. [Troubleshooting](#troubleshooting)
20. [Update and uninstall](#update-and-uninstall)
21. [Limits and roadmap](#limits-and-roadmap)
22. [Project layout, contributing, license](#project-layout-contributing-license)

---

## What you get

| Piece | What it does |
| --- | --- |
| `/eng-kit:init` | One-time setup per project: detects the stack and the full-suite command, creates `.eng-kit/`, hides it from Git |
| `/eng-kit:measure` | Runs the full suite, times it, records it |
| `/eng-kit:import-ci latest` | Records the latest CI test run (GitLab job or GitHub Actions run): duration, runner, every test's time, read-only |
| `/eng-kit:dashboard` | Builds and opens `.eng-kit/dashboard.html` |
| `/eng-kit:status` | Latest full run against the baseline, per environment, in the terminal |
| `/eng-kit:optimize [plan \| next \| <item>]` | Ranked, evidence-based speed plan; applies one item at a time with your approval, then measures it |
| `/eng-kit:release-speed` | Code ready → staging and → production lead times from the local Git history (GitLab and GitHub merges) |
| `/eng-kit:report [--anonymous]` | A shareable markdown report: per-environment before/after, every run, improvements, release speed |
| `/eng-kit:setup-ci` | CI on every merge/pull request for GitLab or GitHub (templates), and the guide to running tests on your own machine |
| Automatic recording | Hooks record a full run whenever Claude runs the suite |
| `testing-standard` skill | Rules Claude follows when it writes or runs tests: setup once, parallel safety, speed budget |
| `speed-playbook` skill | How Claude diagnoses a slow suite and plans the fixes, each measured |
| Speed guides | Test database (tmpfs, durability, schema dump), CI runner and pipeline, guard tests, nightly random order, changed-only runs while coding |

## Supported stacks

`init` detects these and writes the matching command. Anything else works too: set the command and the
JUnit path yourself (see [Configuration](#configuration)).

| Stack | Detected from | Full-suite command eng-kit sets | Notes |
| --- | --- | --- | --- |
| Laravel | `artisan` + `laravel/framework` | `php artisan test --parallel --log-junit .eng-kit/junit.xml` | `--parallel` only when `brianium/paratest` is installed |
| Pest | `pestphp/pest` or `vendor/bin/pest` | `vendor/bin/pest --log-junit .eng-kit/junit.xml` | |
| PHPUnit | `phpunit/phpunit` or `phpunit.xml` | `vendor/bin/phpunit --log-junit .eng-kit/junit.xml` | |
| Vitest | `vitest` in `package.json` | `npx vitest run --reporter=default --reporter=junit --outputFile.junit=.eng-kit/junit.xml` | |
| Jest | `jest` in `package.json` | `JEST_JUNIT_OUTPUT_FILE=.eng-kit/junit.xml npx jest --ci --reporters=default --reporters=jest-junit` | Needs `jest-junit` |
| pytest | `pytest` in project files, `conftest.py`, `pytest.ini` | `python -m pytest [-n auto] --junitxml=.eng-kit/junit.xml` | `-n auto` when `pytest-xdist` is listed |
| Go | `go.mod` | `gotestsum --junitfile .eng-kit/junit.xml ./...` | Needs `gotestsum` |
| Maven | `pom.xml` | `mvn -q test` | Reads `target/surefire-reports/` |
| Gradle | `build.gradle(.kts)` | `./gradlew test` | Reads `build/test-results/test/` |
| .NET | `*.sln`, `*.csproj` | `dotnet test --logger "junit;LogFilePath=.eng-kit/junit.xml"` | Needs `JunitXml.TestLogger` |
| RSpec | `Gemfile` | `bundle exec rspec … --format RspecJunitFormatter --out .eng-kit/junit.xml` | Needs `rspec_junit_formatter` |

The parser reads any JUnit XML: single files, several files, or folders of them (merged into one run).

## Requirements

- Claude Code with plugin support.
- Python 3.9 or later on `PATH` as `python3` (preinstalled on macOS with the developer tools, on Ubuntu and
  on WSL). No packages to install.
- Git (for hiding `.eng-kit/` and for branch/commit on each run). Without Git everything still works.
- For CI import: a GitLab token with the `read_api` scope.

Tested on Linux and macOS through CI (Python 3.9 to 3.13). Windows: use WSL.

## Install

### For yourself

In Claude Code (2.1.275 or later):

```text
/plugin install eng-kit --marketplace mahmoudissmail/eng-kit
```

On earlier versions:

```text
/plugin marketplace add mahmoudissmail/eng-kit
/plugin install eng-kit@eng-kit-plugins
```

### For a team or a whole company

Add the marketplace and the plugin to each developer's `~/.claude/settings.json`, or to Claude Code's
managed settings so an administrator does it once for everyone:

```json
{
  "extraKnownMarketplaces": {
    "eng-kit-plugins": { "source": { "source": "github", "repo": "mahmoudissmail/eng-kit" } }
  },
  "enabledPlugins": { "eng-kit@eng-kit-plugins": true }
}
```

The same two keys can go in a repository's `.claude/settings.json`; Claude Code then offers the plugin to
anyone who trusts that folder.

### Try a local copy first

```text
/plugin marketplace add /path/to/eng-kit
/plugin install eng-kit@eng-kit-plugins
```

## Quick start

In any project, in Claude Code:

```text
/eng-kit:init                     # once per project
/eng-kit:import-ci 1234567890     # optional: a CI run as the baseline (GitLab job id or URL)
/eng-kit:measure                  # or run the full suite locally
/eng-kit:dashboard
```

From then on, whenever Claude runs the project's full suite (for example while fixing a test), the run is
recorded automatically. Ask "how fast are the tests now?" and Claude answers from the records.

## Commands

All commands are also available in a terminal as
`python3 <plugin>/scripts/engkit.py [--project PATH] <command>`.

| Command | Terminal form | What it does |
| --- | --- | --- |
| `/eng-kit:init [--force]` | `init [--force]` | Creates `.eng-kit/` (config, status note, runs file) and adds `/.eng-kit/` to `.git/info/exclude`. Safe to run again; `--force` re-detects |
| `/eng-kit:measure [--label T] [--command C]` | `measure …` | Runs the test command (configured or given), writes output to `.eng-kit/last-run.log`, times it, records the JUnit report it produced. Returns the command's exit code |
| `/eng-kit:import-ci <job id or URL>` | `import-ci REF [--label T]` | GitLab: reads the job's duration and runner, then the pipeline's parsed test report, and records it |
| `/eng-kit:dashboard [--no-open]` | `dashboard [--no-open] [--out PATH]` | Writes `.eng-kit/dashboard.html` and opens it (wslview / explorer.exe on WSL, `open` on macOS, `xdg-open` on Linux) |
| `/eng-kit:status [--json]` | `status [--json]` | Runs recorded, baseline, latest full run, change, average per test, slowest class |
| `/eng-kit:optimize` | `analyze [--json]`, `plan show`, `plan set ITEM open\|applied\|verified\|skipped [--run ID] [--note T]` | Builds `.eng-kit/plan.md` from the runs and the project's test and CI files; tracks each item's state and measured result |
| `/eng-kit:release-speed [--days N] [--staging B] [--production B] [--environment E] [--list]` | `release-speed …` | Lead times from GitLab merge requests (median, p75, p90), saved to `.eng-kit/release.jsonl` |
| — | `record PATH… [--wall-minutes M \| --wall-seconds S] [--source local\|ci\|agent] [--environment E] [--label T]` | Records any JUnit XML file(s) or folder(s), for runs started outside Claude or other CI systems |
| — | `baseline [RUN_ID \| latest \| clear]` | Shows or changes the baseline |
| — | `config get\|set KEY [VALUE]` | Reads or changes a setting (dotted keys, e.g. `ci.project`) |
| — | `export [--format csv\|json]` | Prints every run |
| — | `detect` | Prints what `init` would detect |

## Skills Claude uses on its own

- **`testing-standard`**: used whenever Claude writes, changes, reviews or runs tests. Shared reference data
  set up once (not per test), data created per test, the slow outside faked (network, clock, sleeps, mail,
  queues), rules for safe parallel runs, which tests to run while working, before a push and in CI, a speed
  budget (unit < 0.5 s, feature < 2 s, anything over 5 s explained), and how to find a test that fails only in
  the full suite. Stack references: Laravel/PHPUnit/Pest, JavaScript/TypeScript, Python, and a table for Go,
  Java, .NET, Ruby and Rust; plus `databases.md` (MySQL/MariaDB/Postgres on tmpfs with relaxed durability,
  GitLab `services_tmpfs`, GitHub service options, schema dumps), `ci.md` (runner cores, auto-cancel,
  interruptible jobs, caching, prebuilt images, sharding, nightly random-order jobs, merge trains),
  `guards.md` (a ready guard test against per-test seeding, time-budget reports per stack) and `feedback.md`
  (changed-only runs while coding, never the gate). A project's own docs (CLAUDE.md, CONTRIBUTING) take
  precedence.
- **`speed-playbook`**: used when you ask why the suite is slow or how to speed it up. Claude measures first,
  reads where the time goes, and plans changes in a safe order (setup once, parallel, isolation, CI cores,
  guards), each one measured against the baseline, never by running fewer tests.

## Automatic recording

When Claude runs the full suite with a command that writes JUnit XML, the run is recorded with no command from you.
The `testing-standard` skill tells Claude to use the configured `test_command`, which writes JUnit. Any JUnit path
named in the command is also watched: `--log-junit`, `--junitxml`, `--outputFile.junit`, `--junitfile`,
`JEST_JUNIT_OUTPUT_FILE`. eng-kit registers two hooks on Claude Code's Bash tool:

1. **Before a Bash call**: if the project has `.eng-kit/config.json` and the command looks like a test run,
   the start time is noted in `.eng-kit/.pending.json`.
2. **After a Bash call**: if a configured JUnit file is newer than the last one recorded, it is parsed and
   recorded as source `agent`, with the wall time from the noted start (`wall_source: hook`), or from the
   JUnit file's time when the suite ran in the background (`hook-estimate`).

Rules that keep it safe:

- In projects without `.eng-kit/`, the hook exits after a few file checks.
- It never prints, never blocks or changes the Bash call, and always exits 0.
- Errors go to `.eng-kit/hook-errors.log` only.
- The same JUnit report is never recorded twice (SHA-256 of the file).
- Turn it off per project with `config set hook.enabled false`.

Runs you start yourself outside Claude are not seen by the hook; use `measure` or `record`.

## Importing CI runs (GitLab and GitHub)

`/eng-kit:import-ci latest` takes the newest finished test run. You can also give a GitLab job id or URL
(`…/-/jobs/<id>`) or a GitHub Actions run id or URL (`…/actions/runs/<id>`). The host comes from the URL, from
`config set ci.provider gitlab|github`, or from the `origin` remote.

**GitHub Actions:** the workflow uploads its JUnit file as an artifact named `junit` (`ci.artifact`). eng-kit
downloads it, reads every XML file in it, and takes the wall time from the job named `tests` (`ci.job_name`). The
token is `GITHUB_TOKEN` (a fine-grained token with `Actions: read`), or `ci.github_token_file` and
`ci.github_token_key`. The artifact download follows GitHub's redirect without sending the token to the storage host.

**GitLab:**

- `GET /projects/:project/jobs/:id`: duration, runner (shared or project), pipeline, branch, URL.
- `GET /projects/:project/pipelines/:pipeline/test_report`: every test with its class, time and status.
- The CI job must publish its JUnit report (`artifacts: reports: junit: junit.xml`).

Project: taken from the job URL, from `ci.project`, or from the `origin` remote. Host: `ci.host`
(self-hosted GitLab works). Token: the environment variable named in `ci.token_env` (default
`GITLAB_TOKEN`), or the `ci.token_key` line in the file at `ci.token_file`:

```bash
export GITLAB_TOKEN=…                                  # or:
python3 …/engkit.py config set ci.token_file ~/.config/gitlab.env
python3 …/engkit.py config set ci.token_key GITLAB_TOKEN
```

Other CI systems: download the JUnit XML and run
`record <file-or-folder> --wall-minutes <m> --source ci --environment "<runner name>"`.

## CI and runners (GitLab and GitHub)

`/eng-kit:setup-ci` proposes a CI file from `skills/setup-ci/templates/` and changes nothing until you agree:
- the full suite on every merge or pull request, with a new push cancelling the old run;
- the test database in RAM;
- the JUnit report eng-kit imports;
- a nightly random-order run.

For your own machine, `skills/setup-ci/references/runners.md` gives the steps for a **GitLab project runner in Docker**
and a **GitHub self-hosted runner**, side by side, with a troubleshooting table and the security rules. In short: your
own runner costs no CI minutes and uses all your cores, but every job of the project runs on that machine, so keep the
project private and push access limited to people you trust. Never put a self-hosted runner on a public GitHub
repository.

## Optimizing a project

`/eng-kit:optimize` works in three steps.

1. **Plan (read-only).** `analyze` combines the recorded runs with the project's files and writes a ranked
   plan to `.eng-kit/plan.md` (and `analysis.json`). Every item names its evidence, the change, the expected
   gain, the risk and how to verify it. Checks in version 1.0:

   | Area | What it looks for |
   | --- | --- |
   | Measurements | No baseline; more than 1 s of wall clock per test (setup cost); over 20% of tests above 5 s; ten classes holding a large share; CI much slower than local |
   | Laravel / PHPUnit / Pest | `->seed()` in `setUp()`; ParaTest missing or `--parallel` unused; base TestCase without `Http::preventStrayRequests()` / `Sleep::fake()`; `phpunit.xml` missing BCRYPT_ROUNDS=4, array cache/session/mail, sync queue; Telescope/Pulse/Nightwatch on in tests; no cached routes/config; 80+ migrations without a schema dump; Xdebug loaded; no random-order run; no guard test |
   | JavaScript | Seeding or migrating in `beforeEach`; Jest without `jest-junit`; no HTTP mocking library |
   | Python | No pytest-xdist; function-scoped fixtures loading data; Django without `--reuse-db` |
   | GitLab CI | No auto-cancel; jobs not interruptible; durable MySQL in tests; manual full test job; no own runner tag; no JUnit report |
   | GitHub Actions | No `cancel-in-progress`; no dependency cache |

   The checks are heuristics; Claude confirms each piece of evidence in the files before acting on it.
2. **Apply one item** (only with your go): Claude reads the matching guide, shows the exact change, makes it
   on its own branch, runs the affected tests and lint, and marks the item `applied`. It never removes an
   assertion, skips a test or raises a time limit, and it never touches secrets, runners or production
   settings (those come back to you as steps).
3. **Measure.** After the merge request's CI job, `/eng-kit:import-ci <job>` (or `/eng-kit:measure` where the
   project allows local full runs); the item becomes `verified` with the run and the before/after minutes.
   Re-running `analyze` keeps every item's state and result.

## Release speed

`/eng-kit:release-speed` answers "how long from code ready to staging and to production?" **from the local Git
history: no network, no token.**

- Each merge into the staging branch is one change. **Code ready → staging** runs from the earliest commit the
  merge brought in to the merge itself. Commits that were already on the production branch when it merged are
  not counted (a branch cut from main carries them, but they are not that change's work).
- **Code ready → production** ends at the first commit on the production branch's first-parent line that
  contains the change (checked with `git merge-base --is-ancestor`, so it is exact, not a time guess). Changes
  not on the production branch yet are counted separately.
- Back-merges and release branches (source branches matching `release.exclude_source_patterns`, default
  `^back-?merge`, `^release`, `^main$`, `^master$`) are left out, because they are not new work. In a
  merge-commit flow, direct commits on the staging branch are left out too; in a squash or fast-forward flow,
  every commit on the branch counts as a change.
- It reads `origin/<branch>` when it exists, so run `git fetch` first for current data; the output says how
  fresh the history is.
- `--list` prints every change counted and left out, so the numbers can be checked.

Optional: `config set release.source gitlab` reads merge requests from the GitLab API instead (adds
"merge request open → merged" and, with `--environment`, "merged → deployed" from GitLab deployments). That
mode makes one API call per merge request (4 at a time, cached, with retries on rate limits).

Median, p75 and p90 over the last 30 days by default. Branches and window come from `release.*` in the
configuration (defaults `staging`, `main`, 30 days); for a single-branch flow set both branches to the same
name. The dashboard shows the latest snapshot.

## The dashboard

One HTML file per project, `.eng-kit/dashboard.html`, rebuilt by `/eng-kit:dashboard`:

- Tiles: latest full run, baseline, change against the baseline (percent and times faster), test count,
  wall time per test (wall clock ÷ tests) and test time per test summed over all parallel workers.
- Chart: wall-clock minutes of every full, passed run over time, coloured by environment, with the baseline
  and the optional target band.
- Slowest classes in the latest run with their change against the baseline run.
- Slowest single tests, and how test time is spread (0–0.5 s, 0.5–2 s, 2–5 s, 5–10 s, over 10 s).
- The optimization plan with each item's state and measured result, and the release-speed snapshot.
- The project's status note (`.eng-kit/status.md`), and every run with source, scope, result, minutes,
  change, commit and label.
- Environment filter, light and dark mode, works offline, about 80 KB for 30 runs.

## How runs are compared

- **Baseline**: the first full, passed run with a wall time, unless you set another
  (`baseline <id>`, `baseline latest`). It is never moved automatically after that.
- **Change** = 1 − run ÷ baseline (wall clock), always within one environment: a CI run is compared with the
  CI baseline, a local run with the local one (the configured baseline if it ran there, otherwise that
  environment's first full passed run). 0.40 means 40% faster; negative means slower.
- **Full or partial**: a run with fewer than 80% of the baseline's tests is `partial` (for example a
  filtered run) and is left out of the chart and the "latest" figures.
- **Environment** keeps CI and local apart (`CI shared runners`, `CI runner <name>`,
  `Local <os> <cores>-core`). Compare like with like; the filter on the dashboard helps.
- **Summed test time vs wall clock**: parallel runs finish much faster than the sum of their tests; eng-kit
  stores both and compares wall clock. "Test time per test" is summed over all workers, so it can rise when more
  workers share the CPU even while the wall clock falls; "wall time per test" is the figure to compare.

## Configuration

`.eng-kit/config.json` (change it with `config set`):

| Key | Default | Meaning |
| --- | --- | --- |
| `stack` | detected | Label only |
| `test_command` | detected | Command that runs the full suite and writes JUnit XML |
| `junit_paths` | `[".eng-kit/junit.xml"]` | Files or folders to read (comma-separated with `config set`) |
| `environment` | `Local <os> <cores>-core` | Name for local runs |
| `baseline_run_id` | first full passed run | See [How runs are compared](#how-runs-are-compared) |
| `targets.wall_minutes_low` / `_high` | `null` | Draws a target band on the chart |
| `hook.enabled` | `true` | Automatic recording on or off |
| `ci.host` | `https://gitlab.com` | GitLab host |
| `ci.project` | from the remote | `group/name` |
| `ci.token_env` | `GITLAB_TOKEN` | Environment variable holding the token |
| `ci.token_file`, `ci.token_key` | `null`, `GITLAB_TOKEN` | Optional file holding `KEY=value` |
| `ci.provider` | from the remote | `gitlab` or `github` |
| `ci.job_name` | `tests` | Test job used by `import-ci latest` and for GitHub wall time |
| `ci.artifact` | `junit` | GitHub artifact holding the JUnit file |
| `ci.github_token_env`, `ci.github_token_file`, `ci.github_token_key` | `GITHUB_TOKEN`, `null`, `GITHUB_TOKEN` | GitHub token lookup |
| `release.staging_branch` | `staging` | Branch that counts as "on staging" |
| `release.production_branch` | `main` | Branch that counts as "released" |
| `release.environment` | `null` | GitLab environment for merged → deployed |
| `release.window_days` | `30` | Period for release speed |
| `release.source` | `git` | `git` (local history, no network) or `gitlab` (API, your token) |
| `release.start` | `first_commit` | GitLab mode only: where "code ready" starts, `first_commit` or `mr_opened` |
| `release.exclude_source_patterns` | `["^back-?merge", "^release", "^main$", "^master$"]` | Source branches that are not new work (regular expressions) |

## Data format

Everything lives in `.eng-kit/` (hidden from Git):

| File | Content |
| --- | --- |
| `config.json` | Settings above, `schema: 1` |
| `runs.jsonl` | One JSON object per run, append-only (about 9 KB per run) |
| `status.md` | Your notes, shown on the dashboard |
| `dashboard.html` | Generated |
| `last-run.log` | Output of the last `measure` |
| `ci/pipeline-<id>.xml` | Test reports fetched by `import-ci` |
| `analysis.json`, `plan.md` | The optimization plan and each item's state |
| `release.jsonl` | Release-speed snapshots |
| `report.md`, `report-anonymous.md` | Reports from `/eng-kit:report` |
| `.pending.json`, `.seen.json`, `.lock`, `hook-errors.log` | Hook bookkeeping |

A run in `runs.jsonl`:

```json
{
  "id": "r0003-1a2b3c", "recorded_at": "2026-11-01T10:00:00Z",
  "source": "local | ci | agent", "environment": "Local linux 16-core", "label": "", "command": "…",
  "wall_seconds": 2190.0, "wall_source": "measured | ci-job-duration | hook | hook-estimate | unknown",
  "scope": "full | partial", "git": {"branch": "staging", "commit": "ff04fd0"},
  "ci": {"provider": "gitlab", "job_id": 1, "pipeline_id": 2, "url": "…", "finished_at": "…"},
  "tests": 3301, "failures": 0, "errors": 0, "skipped": 4, "passed": true,
  "test_seconds": 24750.2, "seconds_per_test": 7.498,
  "spread": {"0-0.5s": 120, "0.5-2s": 400, "2-5s": 900, "5-10s": 1500, ">10s": 381},
  "slowest_classes": [{"class": "…", "tests": 22, "seconds": 410.2, "seconds_per_test": 18.6}],
  "slowest_tests": [{"class": "…", "test": "…", "seconds": 31.2}],
  "class_seconds": {"…": 410.2},
  "junit_sha256": "…"
}
```

## Privacy and security

- Reads and writes only inside `.eng-kit/` and one line of `.git/info/exclude` (local to your clone).
- Network: only `import-ci` (and `release-speed` if you switch it to `gitlab`), only `GET` requests to the
  configured GitLab host, token in a header. Everything else, release speed included, works offline.
- `/eng-kit:optimize` changes project files only after you approve each change, on its own branch.
- The token is read at call time from an environment variable or a file you name; it is never stored in
  `.eng-kit/`, printed, or put on a command line.
- The dashboard has a strict Content-Security-Policy (`default-src 'none'`): it loads and sends nothing,
  and every value is written as text, not HTML.
- Each person's data stays on their machine. Nothing is shared unless someone commits `.eng-kit/` on purpose.

See [SECURITY.md](SECURITY.md).

## Performance

Measured on Linux, Python 3.12:

| Operation | Time |
| --- | --- |
| Hook, project without `.eng-kit/` | about 25 ms per Bash call (Python start-up) |
| Hook, set-up project, ordinary command | about 25–30 ms |
| Hook, test command start | about 50 ms |
| Parse a 3,301-test JUnit report | about 20 ms |
| Build the dashboard with 30 runs | under 10 ms, 83 KB file |
| `analyze` on 450 Laravel test files and 250 migrations | about 30 ms |
| `release-speed` (local Git) | A few seconds for about 150 merges (one `git log` per merge plus an ancestry check) |

## Best practices for a fast suite

The `testing-standard` and `speed-playbook` skills carry these, and `/eng-kit:optimize` applies them; in
order of usual gain:

| # | Practice | Typical gain |
| --- | --- | --- |
| 0 | Measure before changing anything; one fixed baseline per environment | Makes the rest measurable |
| 1 | Pay for setup once: reference data (roles, permissions, lookups) once per test database, data per test | -40 to -80% per test |
| 2 | Boot less, fake the outside: block stray HTTP, fake clock and sleeps, array drivers, observability off, Xdebug off, cached routes/config | -10 to -50% |
| 3 | Run in parallel and fix isolation instead of turning parallel off | Close to the core count |
| 4 | Fast test database: tmpfs, relaxed durability, schema dump | -5 to -35% |
| 5 | Give CI cores: own or larger runner (2-vCPU shared runners gain little from parallel) | Up to the CI/local gap |
| 6 | Lean pipeline: automatic test job, auto-cancel, interruptible, caches, prebuilt image, JUnit report | Minutes per pipeline |
| 7 | Guard the gain: guard tests, time budget, nightly random order | Keeps the gains |
| 8 | Changed-only runs while coding (never the gate) | Seconds per change |
| 9 | Watch release speed, not only test speed | Hours to days |

**Never make a test faster by checking less.** The full suite on the merge request stays the gate.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `this project is not set up yet` | Run `/eng-kit:init` in the project |
| Stack `unknown` | `config set test_command '<full-suite command writing JUnit>'` and `config set junit_paths <path>` |
| `wrote no new JUnit XML` after `measure` | The command did not write to `junit_paths`; check `.eng-kit/last-run.log` and the paths |
| A run was not recorded automatically | The run must write to a configured JUnit path; check `hook.enabled` and `.eng-kit/hook-errors.log` |
| `already recorded` | That exact report is already in `runs.jsonl` |
| Run marked `partial` | It had under 80% of the baseline's tests (filtered run) |
| `import-ci`: `no GitLab token` | Export `GITLAB_TOKEN` or set `ci.token_file` |
| `import-ci`: 401 / 403 / 404 | Token scope `read_api`, `ci.project`, `ci.host` |
| `has no test report` | The CI job must publish `artifacts: reports: junit` |
| Dashboard did not open | Open `.eng-kit/dashboard.html` in any browser |
| `python3: not found` | Install Python 3.9+ |
| `analyze` lists something that does not apply | The checks are heuristics: `plan set <item> skipped --note "<why>"` |
| `release-speed` shows 0 changes | Check `release.staging_branch` / `release.production_branch`, the window (`--days`), and run `git fetch` |
| GitLab mode: `429` | GitLab's rate limit; eng-kit retries, then stops with that message. Wait a few minutes, or use the default local mode |

## Update and uninstall

```text
/plugin marketplace update eng-kit-plugins     # get new versions
/plugin uninstall eng-kit@eng-kit-plugins
```

Uninstalling leaves each project's `.eng-kit/` folder; delete it and the `/.eng-kit/` line in
`.git/info/exclude` to remove all data.

## Limits and roadmap

Version 1.0 limits:

- CI import supports GitLab and GitHub Actions. Other CI systems use `record` with a downloaded JUnit file.
  Release speed works with any Git host (local history); its optional API mode supports GitLab only.
- Release speed needs merge commits to see a change's first commit. With squash merges, each change counts from its
  squashed commit's author time.
- `analyze` uses heuristics on file contents; it reports evidence for Claude to confirm, not certainties.
- "Code ready → production" needs the change to reach the production branch through Git history (a merge or
  a fast-forward). Cherry-picked hotfixes are not linked to their staging change.
- Lead time starts at the first commit. Work done before anything is committed (common when an agent builds
  locally and commits at the end) is not visible to Git, so it is not counted.
- Runs started outside Claude are recorded only through `measure`, `record` or `import-ci`.
- Wall time of a suite Claude runs in the background is estimated from the JUnit file's time.
- Native Windows is not tested; use WSL.

Planned: more analyzer checks (Go, Java, .NET), GitHub deployment times, an optional CI step that records each
pipeline, opt-in team summaries, and alerts when a run is slower than the baseline by a set margin.

## Project layout, contributing, license

```
.claude-plugin/marketplace.json     the eng-kit-plugins marketplace
plugins/eng-kit/                    the plugin (manifest, skills, hooks, scripts, tests)
.github/workflows/ci.yml            tests on Python 3.9–3.13 (Linux, macOS) + plugin validation
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and [SECURITY.md](SECURITY.md).
Licensed under the [MIT License](LICENSE).
