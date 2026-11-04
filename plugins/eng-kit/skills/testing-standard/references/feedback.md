# Fast feedback while coding (never the merge gate)

Run only what a change can affect while you work; the full suite still runs on the merge request.

| Stack | Changed or affected tests |
| --- | --- |
| Pest | `--dirty` (tests with uncommitted changes); Pest 5 test impact analysis |
| PHPUnit | `--filter`, a single file, or a test-impact tool (PHPUnit TIA ports) |
| Laravel | `php artisan test --filter=… --compact` |
| Vitest | `vitest --changed` (since the last commit) or `--changed <ref>`; watch mode |
| Jest | `jest --onlyChanged` / `--changedSince=<ref>`; watch mode |
| pytest | `pytest-testmon` (`--testmon`), `-k`, `--lf` (last failed) |
| Go | `go test ./pkg/...` for the touched packages |

Selection tools miss config, container bindings, seeders, shared global state and order effects, which
are exactly how many full-suite-only failures happen. Use them for speed while coding, never to decide a
merge.
