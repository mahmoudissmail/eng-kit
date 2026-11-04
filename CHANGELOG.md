# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-04

### Added
- `eng-kit` plugin for Claude Code with the `eng-kit-plugins` marketplace.
- Commands: `/eng-kit:init`, `/eng-kit:measure`, `/eng-kit:import-ci`, `/eng-kit:dashboard`, `/eng-kit:status`,
  `/eng-kit:optimize` (ranked plan, apply one item with approval, measure it) and `/eng-kit:release-speed`
  (lead time from each change's first commit to staging and to production, computed from the local Git history
  with exact ancestry, no network; commits already on the production branch are not counted as the change's work; back-merges and release branches left out; `--list` shows every change;
  optional GitLab API mode with merge request open → merged and deployments).
- GitLab calls retry rate limits (429, honouring Retry-After), gateway errors and timeouts, then stop with a
  message that names the real cause.
- Analyzer (`analyze`, `plan`): checks for measurements, Laravel/PHPUnit/Pest, JavaScript, Python, GitLab CI and
  GitHub Actions; item states and results kept across runs.
- GitHub Actions import (`import-ci` with a run id, URL or `latest`; JUnit from the run's artifact, wall time from the
  test job), GitLab `import-ci latest`, CI host detected from the remote.
- `/eng-kit:setup-ci`: CI templates for GitLab and GitHub (full suite on every request, cancel on new push, database
  in RAM, JUnit report, nightly random order) and a runner guide for GitLab project runners and GitHub self-hosted runners.
- `/eng-kit:report`: shareable markdown report, with an `--anonymous` mode.
- Automatic recording also watches the JUnit path named in a test command (`--log-junit`, `--junitxml`,
  `--outputFile.junit`, `--junitfile`, `JEST_JUNIT_OUTPUT_FILE`).
- Release speed understands GitHub pull-request merges and single-branch flows.
- Speed guides: test databases (tmpfs, durability, schema), CI runner and pipeline, guard tests, nightly
  random-order jobs, changed-only runs while coding.
- Like-with-like comparison: each run is compared with the baseline of its own environment.
- Per-test seeding found by matching the whole `setUp()` body (closures, long bodies, docblocks); the guard-test
  example uses PHP's tokenizer for the same check.
- Skills Claude uses on its own: `testing-standard` (Laravel/PHPUnit/Pest, Vitest, Jest, pytest, Go, Java,
  .NET, Ruby, Rust) and `speed-playbook`.
- Automatic recording of full test runs that Claude starts (PreToolUse/PostToolUse hooks on Bash).
- JUnit XML parser for files and folders (PHPUnit/ParaTest, Pest, Jest, Vitest, pytest, Maven Surefire, Gradle).
- GitLab CI import (read-only): job duration, runner type and the pipeline's parsed test report.
- Offline, self-contained HTML dashboard with light and dark mode, including the plan and release speed.
- Stack detection for Laravel, Pest, PHPUnit, Vitest, Jest, pytest, Go, Maven, Gradle, .NET and RSpec.
