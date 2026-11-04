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

## Reporting a problem

Please report security issues privately to the maintainers through GitHub's
"Report a vulnerability" (Security tab) rather than in a public issue.
