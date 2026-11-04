# Parallel safety

## What each worker usually has to itself
- Its own process memory: globals, statics and singletons reset between workers, not between tests.
- Its own database, when the runner creates one per worker (Laravel `--parallel`, pytest-xdist with a
  per-worker database fixture, Vitest/Jest with a per-worker schema).

## What workers share
- The file system: temp folders, storage, uploads, generated files.
- Caches and locks in Redis, Memcached or files; ports and local servers; environment variables set at
  process level; anything on the network.

## Rules
1. **Own your data.** A test creates every record it reads and never relies on ids or rows from another test.
2. **No order dependence.** A test passes first, last or alone.
3. **Separate files.** Use the framework's fake disk or a temp folder per test; where a real path is
   needed, add the worker id (Laravel `ParallelTesting::token()`, pytest-xdist `worker_id`,
   `process.env.VITEST_POOL_ID` / `JEST_WORKER_ID`).
4. **Separate keys, locks and ports** the same way, or use in-memory drivers.
5. **Restore global state** (statics, singletons, config, env vars, the clock) in teardown.
6. **No real network or sleep.** Fake the exact endpoints, block stray calls, fake time.
7. **Finish what you start.** No pending commands, timers, open servers or unawaited promises left for the
   next test.

## A test fails only in the full suite
1. Run its file alone. Passes alone → it depends on another test or on order.
2. Run its folder in random order with a fixed seed (PHPUnit `--order-by=random --random-order-seed=N`,
   pytest `-p random_order --random-order-seed=N` with pytest-random-order, Vitest `--sequence.shuffle --sequence.seed=N`,
   Jest `--randomize --seed=N`); keep the seed that fails.
3. Find the shared thing from the list above.
4. Fix the isolation, not the assertion. If the only fix changes product behaviour, stop and ask.
