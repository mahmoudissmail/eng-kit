---
name: speed-playbook
description: How to make a slow test suite and a slow release flow faster without weakening tests - read eng-kit's measurements, find where the time goes, and plan the changes in a safe order (measure, setup once, boot less, parallel and isolation, test database, CI runner and pipeline, guards, release flow), each one measured against the baseline. Use when the person asks why the tests or CI are slow, how to speed up the suite, the pipeline or releases, or to plan test-performance work.
---

# Test speed playbook

Speed comes from cheaper setup and better use of hardware, never from running fewer checks. The full suite
on the merge request stays the merge gate. `/eng-kit:optimize` turns this playbook into a ranked plan for
the project and applies it one item at a time.

## The order, with what each step usually gives

| # | Step | Look for | Typical gain | Guide |
| --- | --- | --- | --- | --- |
| 0 | Measure | No baseline; CI and local never compared | Makes the rest measurable | `/eng-kit:import-ci`, `/eng-kit:measure` |
| 1 | Setup once | > 1 s per test; reference data seeded per test; big shared fixtures | -40 to -80% per test | `testing-standard`, stack reference |
| 2 | Boot less, fake the outside | Real HTTP, sleeps, mail, queues; full app boot; observability tools on; Xdebug loaded | -10 to -50% | stack reference |
| 3 | Parallel and isolation | One process; tests that fail only in the full suite | Close to the core count | `parallel-safety.md` |
| 4 | Test database | Durable writes on throwaway data; data on disk; all migrations per database | -5 to -35% | `databases.md` |
| 5 | CI runner | CI much slower than local (2-vCPU shared runners) | Up to the measured CI/local gap | `ci.md` |
| 6 | CI pipeline | Manual test job; no auto-cancel; installs from scratch; no JUnit report | Minutes per pipeline; less waiting | `ci.md` |
| 7 | Guards | Gains slipping back; order-dependent tests | Keeps the gains | `guards.md` |
| 8 | Fast feedback while coding | Running too much while iterating | Seconds per change (never the gate) | `feedback.md` |
| 9 | Release flow | Long wait from merge request to staging and production | Hours to days | `/eng-kit:release-speed` |

## Reading the numbers

- Many tests around the same high time → setup (step 1). A few huge tests → those tests. CI much slower
  than local with the same suite → hardware or worker count (step 5).
- Compare like with like: the same environment, the same test count (eng-kit marks runs with far fewer
  tests as partial).
- The baseline is fixed. A new baseline is a decision, stated with its reason.

## How to work

- One change per merge request, each measured: record the CI run after each merge and state the change in
  minutes and percent.
- Never make a test faster by checking less: no removed assertions, skipped tests or raised time limits.
- Respect the project's rules on what may run locally and what needs approval.

## Worked example (a Laravel application, measured)

- Baseline: 84 min on GitLab shared runners (2 vCPU, already `--parallel`), 36.5 min for the same suite on
  a 16-core machine, about 7.5 s per feature test.
- Findings: `RolePermissionSeeder` seeded in every `setUp()`; empty base TestCase (no
  `preventStrayRequests`, no `Sleep::fake`); MySQL durability already relaxed but not on tmpfs; manual test
  job on shared runners.
- Plan: seed once (T1) → isolation, tmpfs, cached routes/config, base fakes (T2) → own runner as the gate
  with auto-cancel (T3) → guard tests and a nightly random-order run (T4). Targets: gate 6-12 min
  (-86 to -93%), local 6-12 min (-67 to -84%), code ready → staging 20-35 min instead of about 2 h.
