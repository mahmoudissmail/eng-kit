# CI: runner and pipeline

## Runner: give the test job cores

Parallel runs scale with cores. GitLab's shared runners on the free tier have 2 vCPU, so a parallel suite
gains little there; the same suite on a 16-core machine was 57% faster with no other change.

- **Own GitLab runner** (Docker executor) on a machine with spare cores; tag it and put `tags: [<tag>]` on
  the test job. Set `concurrent` so one test job gets most cores. Add `services_tmpfs` for the database
  (`databases.md`). Keep the shared-runner job as a manual fallback.
- **GitHub**: larger hosted runners or a self-hosted runner (`runs-on: [self-hosted, linux]`).
- Set the worker count to the runner's cores (ParaTest `--processes`, pytest `-n auto`, Vitest/Jest
  `--maxWorkers`), leaving one core for the database.

## Pipeline

GitLab:

```yaml
workflow:
  auto_cancel:
    on_new_commit: interruptible      # a new push cancels the old pipeline's interruptible jobs

default:
  interruptible: true                 # not on deploy jobs

tests:
  needs: [lint, build]                # start as soon as what it needs is done
  cache:
    key: { files: [composer.lock] }   # or package-lock.json, poetry.lock …
    paths: [vendor/]
    policy: pull
  script:
    - php artisan test --parallel --recreate-databases --log-junit junit.xml
  artifacts:
    when: always
    reports:
      junit: junit.xml                # shows failures in the MR; eng-kit import-ci reads it
```

- Make the full test job automatic on merge requests once it is fast or on your own runner; a manual job
  adds waiting before it even starts.
- Prebuilt CI image with PHP extensions / Node / Python and tools baked in, instead of installing them in
  every job.
- Sharding (`parallel: N`) only when you have more than one runner machine; on one machine a single job
  with parallel workers wastes less on start-up. Balance shards by test timing (JUnit data), not by file
  count.
- Raise a job `timeout` only as a stopgap, and say so; the fix is speed.

GitHub Actions:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true            # not for deploy workflows
```

plus `actions/cache` (or the `cache:` input of `setup-node`/`setup-python`) keyed on the lock file, and
`actions/upload-artifact` for the JUnit file.

## Nightly random-order run (does not block merges)

GitLab (scheduled pipeline):

```yaml
tests-random-order:
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  script:
    - php artisan test --parallel --order-by=random --random-order-seed=$CI_PIPELINE_ID
```

pytest: `pytest -p random_order --random-order --random-order-seed=$SEED` (pytest-random-order);
Vitest: `vitest run --sequence.shuffle --sequence.seed=$SEED`; Jest: `jest --randomize --seed=$SEED`.
GitHub: `on: schedule: - cron: "0 2 * * *"`. Print the seed; a failure is reproduced with the same seed.

## Merge trains / merge queues

GitLab merge trains (Premium) and GitHub merge queues test each change on top of the ones queued ahead of
it. Worth it once the gate is under about 10 minutes and many people merge daily; on a free tier, "rebase on
the target branch, re-run, then merge" gives the same safety by hand.
