---
name: testing-standard
description: A test standard for keeping suites fast and safe when run in parallel - setup paid once instead of per test, isolation rules, which tests to run while working, before a push and in CI, a per-test speed budget, and how to handle a test that fails only in the full suite. Use whenever you write, change, review or run tests, set up a test class or fixture, touch the test runner or CI test job configuration, or a test fails only in the full run. Covers Laravel/PHPUnit/Pest, JS/TS (Vitest, Jest), Python (pytest) and other stacks.
---

# Testing standard

Every second added to one test is paid on every run, by every developer and every CI job. Keep each
test cheap and independent of the others. Where the project's own docs (CLAUDE.md, CONTRIBUTING) or the
prompt you are running say something different, they win.

## 1. Pay for setup once

Most slow tests are slow in setup, not in assertions.

- Shared, read-only reference data (roles, permissions, lookup tables, feature flags) is created **once per
  test database or worker**, not in every test's setup. Each test then runs inside a transaction or
  against data it creates itself.
- A test creates only the rows it reads, with factories or builders. No shared "world" built for every
  test in a class.
- The app boots as little as the test needs: cached config and routes where the framework offers it,
  unit tests without the framework where possible.
- Fake the slow outside: no real network, mail, queues, sleeps or clocks. Block stray network calls so a
  missing fake fails loudly instead of waiting.

Stack-specific ways to do each of these: `references/laravel.md`, `references/javascript.md`,
`references/python.md`, `references/other.md`. Test database speed (tmpfs, durability, schema):
`references/databases.md`. CI runner and pipeline, nightly random order: `references/ci.md`. Guards that
keep the rules from slipping back: `references/guards.md`. Changed-only runs while coding:
`references/feedback.md`.

## 2. Safe beside other tests

Parallel runners give each worker its own process and usually its own database, but share the file
system, caches, ports and anything outside the process. A test that passes alone and fails in the full
suite breaks one of the rules in `references/parallel-safety.md`. Read it before a test touches files,
locks, cache keys, global or static state, the clock, or environment variables.

## 3. Which tests to run, when

| Moment | Run | Why |
| --- | --- | --- |
| While working | The one test or file, filtered | Seconds of feedback |
| Before a push | The files you touched and their neighbours, plus lint and fast unit tests (or the whole suite in parallel, if the project allows it) | Catch breakage before CI |
| On the merge request | The full suite in CI | The only merge gate |
| Fails only in the full suite | That file alone, then its folder in random order with a fixed seed | Finds order dependence |

## 4. Speed budget

- Unit test: under 0.5 s. Integration or feature test: under 2 s. Anything over 5 s gets a reason in the
  code review, so it is fixed or accepted on purpose.
- Never make a test faster by weakening what it checks. A faster test proves the same thing.
- When eng-kit is set up (`.eng-kit/` exists), `/eng-kit:status` shows the current suite time, the
  dashboard lists the slowest classes and tests, and `/eng-kit:optimize` plans and applies speed fixes.

## 5. Recording runs (eng-kit)

When `.eng-kit/config.json` exists and you run the **full** suite, run it with the JUnit output in that file's
`test_command` (for example `--log-junit .eng-kit/junit.xml`, `--junitxml=…`, `--outputFile.junit=…`). eng-kit's
hook then records the run automatically, with its time; any JUnit path named in the command works. Filtered runs
are recorded as partial and never compared with full runs. Respect the project's rules on whether the full suite
may run locally.
