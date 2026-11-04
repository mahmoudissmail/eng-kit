# eng-kit for developers — one page

**What it is.** A Claude Code plugin that measures how long your test suite takes, shows where the time goes, helps
make it faster without weakening any test, and runs the full suite on every merge or pull request.

## 1. Install (once)

```text
claude plugin install eng-kit --marketplace mahmoudissmail/eng-kit
```

Needs Python 3.9+ (`python3`) and Git. Nothing else to install.

## 2. Set up a project (once per project)

In Claude Code, inside the project:

```text
/eng-kit:init
```

It detects the stack and the full-suite command and keeps its data in `.eng-kit/`, hidden from Git. Your records
stay on your machine.

## 3. Every day

| You want | Type |
| --- | --- |
| How fast are the tests now? | `/eng-kit:status` |
| Record the latest CI run | `/eng-kit:import-ci latest` |
| See the trend, slowest tests, plan | `/eng-kit:dashboard` |
| Make the suite faster | `/eng-kit:optimize` (one change at a time, only with your yes) |
| Share results | `/eng-kit:report` (`--anonymous` for outside the team) |
| Tests on every merge/pull request | `/eng-kit:setup-ci` |

When Claude runs the full suite itself, the run is recorded automatically.

## 4. Tokens (only for importing CI runs)

- GitLab: `export GITLAB_TOKEN=…` (scope `read_api`).
- GitHub: `export GITHUB_TOKEN=…` (fine-grained, `Actions: read`).

Or point eng-kit at a file that holds the token: `config set ci.token_file …`. Tokens are never printed or stored.

## 5. Rules everyone keeps

- Never make a test faster by checking less.
- One speed change per merge request, measured against the baseline.
- The full suite on the merge request is the gate.
- Own CI runners only on private projects, with push access for trusted people only.
