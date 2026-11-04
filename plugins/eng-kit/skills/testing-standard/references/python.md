# Python (pytest)

- **Workers:** pytest-xdist `-n auto`; use `--dist loadfile` or `loadgroup` when tests in one file share
  expensive fixtures.
- **Setup once:** `scope="session"` fixtures for expensive, read-only setup (a database schema, reference
  data), `scope="function"` transactions around each test. With xdist, key per-worker resources on the
  `worker_id` fixture.
- **Django:** `--reuse-db` locally, `--create-db` in CI; `pytest-django` gives each xdist worker its own
  database.
- **Fakes:** `responses` / `respx` for HTTP with unmatched requests failing, `freezegun` or
  `time-machine` for the clock.
- **Find the slow part:** `--durations=25` lists the slowest setups and calls separately.
- **JUnit:** `--junitxml=<file>`.
- **Database:** `fsync=off`, `synchronous_commit=off` and tmpfs for the test Postgres: `databases.md`.
- **Changed-only runs** while coding: `pytest-testmon`, `--lf`: `feedback.md`.
- **Hard cap on runaway tests:** `pytest-timeout`; budget report in CI: `guards.md`.
