---
name: init
description: Set up eng-kit test-speed tracking in the current project (one time). Detects the stack and the full-suite test command, creates the local .eng-kit/ folder and hides it from Git.
disable-model-invocation: true
argument-hint: "[--force]"
---

# /eng-kit:init

1. Run, from the project root:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" init $ARGUMENTS
   ```

2. Show the person the printed stack, test command and JUnit path, and any `Note:` lines.
3. If the stack is `unknown` or a note says a JUnit reporter is missing, ask the person for the command
   that runs the **full** suite and writes JUnit XML, then set it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" config set test_command '<command>'
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" config set junit_paths '<file-or-folder>[,<more>]'
   ```

   Do not install packages or edit project files to add a reporter unless the person asks.
4. Close with the next step in one line: record a first full run with `/eng-kit:measure`, or import a CI run
   with `/eng-kit:import-ci <job id>`; the first full passed run becomes the baseline.

Nothing here touches the repository's tracked files: `.eng-kit/` is listed in `.git/info/exclude`, which
is local to this clone.
