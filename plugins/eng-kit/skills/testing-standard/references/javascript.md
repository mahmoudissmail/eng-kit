# JavaScript and TypeScript (Vitest, Jest)

- **Workers:** Vitest runs files in parallel by default (`--pool=threads|forks`, `--maxWorkers`); Jest via
  `--maxWorkers`. Tests inside one file run in order unless marked concurrent.
- **Isolation cost:** Vitest `--no-isolate` / Jest without per-file module isolation is faster but leaks
  module state; use only when the suite is clean.
- **Setup once:** `globalSetup` for things that start once (a test database, a server); `setupFiles` for
  per-file setup kept small. Database: one schema or database per worker (`VITEST_POOL_ID`,
  `JEST_WORKER_ID`), each test in a transaction or truncating only its own tables.
- **Fakes:** fake timers (`vi.useFakeTimers()`, `jest.useFakeTimers()`), mock network with MSW or nock and
  fail on unhandled requests.
- **Transpile cost:** prefer the fast transform (esbuild/SWC) over full type-checking during tests; type
  check in a separate CI step.
- **JUnit:** Vitest `--reporter=junit --outputFile.junit=<file>`; Jest `jest-junit` reporter
  (`JEST_JUNIT_OUTPUT_FILE=<file>`).
- **Database:** build the schema once in `globalSetup`, clone it per worker (Postgres `TEMPLATE`), see
  `databases.md`.
- **Watch and changed-only runs** while coding: `feedback.md`.
- **Slow-test report:** `slowTestThreshold` (Vitest, Jest); a time budget in CI: `guards.md`.
