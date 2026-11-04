# Security

## What eng-kit touches

- It reads and writes only inside the project's `.eng-kit/` folder, plus one line in `.git/info/exclude`
  (local to the clone, never committed).
- It makes network requests only in `import-ci`, only to the GitLab host in `.eng-kit/config.json`
  (default `https://gitlab.com`), only `GET` requests, with the token in a request header.
- The dashboard is a static file with a strict Content-Security-Policy (`default-src 'none'`): it loads
  nothing and sends nothing.
- Hooks run on every Bash call in Claude Code. They print nothing, never block the call, exit after a few
  file checks in projects without `.eng-kit/`, and write errors only to `.eng-kit/hook-errors.log`.

## Tokens

- The GitLab token is read at call time from an environment variable (default `GITLAB_TOKEN`) or a file
  you point to. It is never written to `.eng-kit/`, printed, or passed on a command line.
- Use a token with the `read_api` scope only.

## Token safety

- Tokens go only to trusted hosts: the public GitLab and GitHub, plus hosts you add yourself in
  `ENGKIT_TRUSTED_HOSTS` (comma-separated) or `~/.config/eng-kit/trusted-hosts` (one per line). A cloned project's
  `.eng-kit/config.json` cannot add hosts, and only `https` is used.
- eng-kit trusts only local data it created: a `.eng-kit/config.json` committed to a repository is refused, links
  inside `.eng-kit/` are refused, and the hook never looks above the repository root.

## Reporting a problem

Please report security issues privately to the maintainers through GitHub's
"Report a vulnerability" (Security tab) rather than in a public issue.
