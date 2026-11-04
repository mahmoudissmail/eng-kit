---
name: setup-ci
description: Set up CI that runs the full test suite on every merge or pull request - on GitLab or GitHub, on hosted runners or your own machine - with the JUnit report eng-kit reads, cancel-on-new-push, a test database in RAM and a nightly random-order run. Use when the person asks to set up CI, a runner, a self-hosted runner, or to make tests run automatically on merge requests.
disable-model-invocation: true
argument-hint: "[gitlab | github]"
---

# /eng-kit:setup-ci

1. **Find the host.** `git remote get-url origin` (github.com → GitHub, otherwise GitLab), or take `$ARGUMENTS`.
2. **Read what exists.** `.gitlab-ci.yml` or `.github/workflows/*.yml`. If there is CI already, never replace it:
   propose only the missing pieces as a diff (test job, JUnit report, cancel-on-new-push, nightly random order).
3. **Start from the template** for the stack:
   - GitLab + Laravel: `${CLAUDE_PLUGIN_ROOT}/skills/setup-ci/templates/gitlab-ci.laravel.yml`
   - GitHub + Laravel: `${CLAUDE_PLUGIN_ROOT}/skills/setup-ci/templates/github-actions.laravel.yml`
   - Other stacks: keep the same structure and swap the test command for the one in `.eng-kit/config.json`
     (`test_command`), so it writes JUnit XML; see `testing-standard/references/ci.md`.
   Show the exact file and wait for an explicit yes before writing it, on a new branch.
4. **Runner.** Ask which runner the person wants:
   - **Hosted** (GitLab shared runners / GitHub `ubuntu-latest`): nothing to install; uses CI minutes.
   - **Own machine**: give the owner steps from `references/runners.md` for their host. Steps in the GitLab or GitHub
     UI, and registering with the runner token, are **the person's to do**: never ask for, read, print or store a
     runner or registration token, and never paste one into a command line yourself. You may check afterwards that the
     runner container or service is running (`docker ps`, `./svc.sh status`) and that jobs show the runner's name.
5. **Security.** If they choose their own machine, say plainly: every job of the project will run on it; keep the
   project private, push access limited to trusted people and bots; never on a public GitHub repository.
6. **Measure.** After the first green run: `/eng-kit:import-ci latest`, then `/eng-kit:status`. If the project has no
   eng-kit data yet, run `/eng-kit:init` first.
