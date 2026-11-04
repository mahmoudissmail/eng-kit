# Laravel, PHPUnit and Pest

- **Parallel:** `php artisan test --parallel` (needs `brianium/paratest`). Each process gets
  `<database>_test_<n>`; CI can add `--recreate-databases`.
- **Database:** `RefreshDatabase` migrates once per process and wraps each test in a transaction.
  `LazilyRefreshDatabase` skips that for tests that never touch the database.
- **Seed once, not per test:** do not call `$this->seed(SomeSeeder::class)` in every `setUp()` for
  reference data such as roles and permissions. Seed it once per database (`protected $seed = true;` with
  `$seeder`, or the `#[Seed]` / `#[Seeder]` attributes, or a `ParallelTesting::setUpTestDatabase` hook),
  then clear caches that hold it per test (spatie/laravel-permission:
  `app(PermissionRegistrar::class)->forgetCachedPermissions()`). Measure before and after; this is often
  the biggest single gain in Laravel suites.
- **Boot less:** `WithCachedRoutes` / `WithCachedConfig` traits where available (check they work with
  `--parallel` in your version).
- **Fakes in the base TestCase:** `Http::preventStrayRequests()`, `Sleep::fake()`, `Queue::fake()` or
  `QUEUE_CONNECTION=sync`, `Mail::fake()` where tests do not assert real delivery.
- **phpunit.xml env:** `BCRYPT_ROUNDS=4`, `CACHE_STORE=array`, `SESSION_DRIVER=array`,
  `MAIL_MAILER=array`, observability tools (Telescope, Pulse, Nightwatch) off.
- **Livewire / Filament:** prefer `set()` over field-by-field `fill()`; set the Filament panel explicitly;
  for actions, mount → fill → call when a one-step helper behaves differently in the full suite.
- **Schema:** `php artisan schema:dump` (optionally `--prune`) so each parallel test database loads one SQL
  file instead of every migration.
- **PHP runtime:** run tests with Xdebug off (`XDEBUG_MODE=off` or without the extension); use PCOV only in
  the coverage job. Give the CLI enough memory for the full suite (`memory_limit = 1G` in the CI image).
- **Feature switches / settings:** let tests opt in to the switches they need right after `parent::setUp()`
  (with every switch off by default, as in production), instead of enabling everything for every test.
- **Commands:** finish and assert an `artisan()` pending command inside the same test; a held one leaks into
  the next test.
- **Database per run in CI:** `--recreate-databases` with `--parallel`, so stale schemas never leak in.
- **Test database speed:** `databases.md` (tmpfs, relaxed durability).
- **JUnit:** `--log-junit <file>`; CI: `artifacts: reports: junit` (GitLab) for eng-kit's CI import.
