# eng-kit

Local, per-project test-speed tracking and optimization for Claude Code. It records every full test run
(automatically when Claude runs the suite), compares it with a baseline, imports GitLab CI runs, builds a
ranked speed plan that Claude applies one measured change at a time, measures release lead times, and builds
an offline dashboard. It also gives Claude a testing standard and a speed playbook. Works with any stack that writes
JUnit XML: Laravel, PHPUnit, Pest, Vitest, Jest, pytest, Go, Maven, Gradle, .NET, RSpec, Rust.

## Install

```text
/plugin install eng-kit --marketplace mahmoudissmail/eng-kit
```

On Claude Code before 2.1.275: `/plugin marketplace add mahmoudissmail/eng-kit`, then `/plugin install eng-kit@eng-kit-plugins`.

## Use

```text
/eng-kit:init                  # once per project
/eng-kit:import-ci <job>       # optional: a GitLab CI run (read-only, your own token)
/eng-kit:measure               # run the full suite locally and record it
/eng-kit:dashboard             # open .eng-kit/dashboard.html
/eng-kit:status                # latest full run against the baseline
/eng-kit:optimize              # ranked speed plan; apply one item with your approval, then measure it
/eng-kit:release-speed         # code ready -> staging / production lead times (GitLab)
```

All data stays in the project's `.eng-kit/` folder, hidden from Git through `.git/info/exclude`. Requires
Python 3.9+ as `python3`; no packages to install.

Full documentation: see the repository README (install for a team, configuration, data format, privacy,
performance, troubleshooting).
