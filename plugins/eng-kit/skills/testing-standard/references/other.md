# Other stacks

| Stack | Parallel | JUnit output |
| --- | --- | --- |
| Go | `go test -p N ./...`, `t.Parallel()` per test | `gotestsum --junitfile <file> ./...` |
| Java (Maven) | Surefire `forkCount` / `parallel` | `target/surefire-reports/` (default) |
| Java (Gradle) | `maxParallelForks` | `build/test-results/test/` (default) |
| .NET | `dotnet test` runs assemblies in parallel; xUnit collections | `JunitXml.TestLogger`: `--logger "junit;LogFilePath=<file>"` |
| Ruby (RSpec) | `parallel_tests` gem | `rspec_junit_formatter` |
| Rust | `cargo test` runs tests in threads | `cargo2junit` or `cargo nextest` JUnit profile |

The same rules apply everywhere: shared setup once, data per test, no shared files or ports, no real
network or sleep, restore global state.
