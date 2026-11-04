# Runners: GitLab and GitHub

| | GitLab | GitHub |
| --- | --- | --- |
| Machines run by the host (billed in minutes) | Shared / instance runners | GitHub-hosted runners (`ubuntu-latest`) |
| Your own machine | Project runner (created in the UI, the `gitlab-runner` program runs on your machine) | Self-hosted runner (created in the UI, the `actions-runner` program runs on your machine) |
| How jobs pick a runner | Tags (`tags: [<tag>]`); "Run untagged jobs" on the runner | Labels (`runs-on: [self-hosted, linux]`) |
| Job containers | Docker executor: every job in fresh containers | Steps run on the machine; `services:` and `container:` need Docker |
| Database in RAM | Runner `config.toml`: `[runners.docker.services_tmpfs]` | Service `options: --tmpfs /var/lib/mysql:rw` |
| Cancel superseded runs | `workflow: auto_cancel: on_new_commit: interruptible` | `concurrency: { group: …, cancel-in-progress: true }` |
| Test report for eng-kit | `artifacts: reports: junit: junit.xml` | `actions/upload-artifact` with `name: junit` |
| Import into eng-kit | `/eng-kit:import-ci latest` (token: `GITLAB_TOKEN`, `read_api`) | `/eng-kit:import-ci latest` (token: `GITHUB_TOKEN`, `actions:read`) |

Both work the same way: the runner program on your machine asks the host for work over outgoing HTTPS (no
inbound port), runs the job, and sends logs and results back. Your own runner costs no CI minutes; it works only
while the machine is on (jobs wait as pending otherwise).

## GitLab project runner in Docker (Linux, macOS or WSL)

Owner or Maintainer steps in the UI; the token never goes through a chat or a file in the repository.

1. **Settings → CI/CD → Runners → Create project runner**: a tag (for example `project-runner`), tick **Run untagged
   jobs**, a description. Copy the `glrt-…` token (shown once).
2. In the terminal of the user that runs Docker (on WSL: the Ubuntu user, not PowerShell):

   ```bash
   mkdir -p ~/gitlab-runner/config && chmod 700 ~/gitlab-runner/config
   read -rs RUNNER_TOKEN          # paste the token, Enter (not shown, not in history)
   docker run --rm -v ~/gitlab-runner/config:/etc/gitlab-runner gitlab/gitlab-runner:latest register \
     --non-interactive --url https://gitlab.com --token "$RUNNER_TOKEN" --executor docker \
     --docker-image alpine:3 --description "$(hostname)"
   unset RUNNER_TOKEN
   ```

   It must end with `Runner registered successfully`.
3. In `~/gitlab-runner/config/config.toml` (root-owned; edit with `sudo` or a throw-away container):
   `concurrent = 2`, and under the runner: `request_concurrency = 2`; at the end of `[runners.docker]`:

   ```toml
     [runners.docker.services_tmpfs]
       "/var/lib/mysql" = "rw,noexec"
   ```

4. Start it for good:
   `docker run -d --name gitlab-runner --restart always -v ~/gitlab-runner/config:/etc/gitlab-runner -v /var/run/docker.sock:/var/run/docker.sock gitlab/gitlab-runner:latest`
5. **Settings → CI/CD → Runners → Instance** tab: switch **Turn on instance runners for this project** off. Pin jobs with
   `default: tags: [<tag>]`.
6. Check: the runner shows a green **Online** dot; the next pipeline's jobs show it as their runner.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `config.toml` missing | Registered as another user or distro | Repeat step 2 in the right terminal (`whoami`, `echo $HOME`) |
| Runner "Never contacted" | Created in the UI but not registered | Step 2 with that runner's token, or create a new runner |
| Jobs run on shared runners | Instance runners still on | Step 5 |
| Jobs stay pending | Tag mismatch or "Run untagged jobs" off | Edit the runner (pencil) |
| `tls: bad record MAC` on uploads | A network or security product rewrites HTTPS | Test a 20 MB upload on another network; ask IT to exclude the host from inspection; avoid large artifacts |
| Second job waits | `request_concurrency` 1 | Step 3 |

## GitHub self-hosted runner (Linux, macOS or WSL)

1. **Settings → Actions → Runners → New self-hosted runner**, pick Linux x64. GitHub shows download and `config.sh`
   commands with a registration token that expires after one hour.
2. As a normal user (not root), in a folder of its own:

   ```bash
   mkdir -p ~/actions-runner && cd ~/actions-runner
   # paste GitHub's download + tar lines, then:
   ./config.sh --url https://github.com/<owner>/<repo> --token <token from the page> \
     --labels self-hosted,linux --name "$(hostname)" --unattended
   sudo ./svc.sh install && sudo ./svc.sh start      # or ./run.sh to try it in the foreground
   ```

3. Docker must be installed and the runner's user in the `docker` group, because `services:` (MySQL) run in containers.
4. In the workflow: `runs-on: [self-hosted, linux]`; keep `concurrency` with `cancel-in-progress: true`.
5. **Settings → Actions → General**: require approval for workflows from outside collaborators.
6. Check: the runner shows **Idle** in green; the next run's job log names it.

**Never attach a self-hosted runner to a public repository**: anyone opening a pull request from a fork could run code
on your machine.

## Security, for both

- Your own runner runs every job of the project on your machine. Keep the project **private**, give push access only
  to people and bots you trust, and rotate bot tokens (for example every 3 months).
- Jobs run without privileged mode or host folders. Keep it that way.
- Prefer a dedicated machine or VM for the runner when the team grows.
