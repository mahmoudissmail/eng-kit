# Test database speed

Test databases hold throwaway data. They do not need crash safety, so turn it off there, and only there.
Never apply these settings to a database that holds real data.

## MySQL / MariaDB

Server options for the test instance:

```text
--innodb-flush-log-at-trx-commit=0   # write the log about once a second, not on every commit
--skip-log-bin                       # no binary log (MySQL 8: --disable-log-bin also works)
--innodb-doublewrite=0               # MySQL 8.0.20+: OFF; older: --skip-innodb-doublewrite
--sync-binlog=0                      # only matters if the binary log stays on
--performance-schema=OFF             # optional: less memory and overhead
```

Data on RAM (tmpfs) removes disk waits entirely:

- **GitLab Docker runner** (`config.toml` of your own runner):

  ```toml
  [runners.docker]
    [runners.docker.services_tmpfs]
      "/var/lib/mysql" = "rw,noexec"
  ```

  and in `.gitlab-ci.yml` the service command:
  `command: ["--innodb-flush-log-at-trx-commit=0", "--skip-log-bin", "--innodb-doublewrite=0"]`.
  GitLab's shared runners cannot use `services_tmpfs`; it needs your own runner.
- **GitHub Actions** service container: `options: --tmpfs /var/lib/mysql:rw` plus the flags above in the
  image's command (or `MYSQL_*` env and a custom `my.cnf`).
- **Docker Compose / local**: `tmpfs: ["/var/lib/mysql"]` on a second, test-only MySQL service (keep the
  normal development database on disk).
- **Laravel Sail**: add a `mysql-test` service with the tmpfs and flags, and point `phpunit.xml`'s
  `DB_HOST` at it.

## PostgreSQL

```text
-c fsync=off -c synchronous_commit=off -c full_page_writes=off
```

Data on tmpfs: `/var/lib/postgresql/data` (same mechanisms as above). With pytest-xdist or Laravel
`--parallel`, each worker gets its own database; keep `max_connections` above workers × pool size.

## Building the schema

- Laravel: `php artisan schema:dump` (optionally `--prune`) so each new test database loads one SQL file
  instead of running every migration. Dump for the connection the tests use; refresh it when migrations
  change.
- Django: `--reuse-db` locally, `--create-db` in CI.
- Node ORMs (Prisma, TypeORM, Knex): build the schema once in `globalSetup` and clone it per worker
  (`CREATE DATABASE … TEMPLATE …` on Postgres) instead of migrating per test file.

## SQLite instead?

In-memory SQLite is the fastest, but it behaves differently from MySQL/Postgres (JSON, locking, strict
mode, collations, date functions). Keep the production engine for the merge gate; SQLite at most as an
optional fast local lane.
