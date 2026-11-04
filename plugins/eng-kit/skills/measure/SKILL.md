---
name: measure
description: Run the project's full test suite, time it, and record the run in eng-kit (local only). Use when the person asks to measure or benchmark the full suite.
disable-model-invocation: true
argument-hint: "[--label <text>] [--command '<full-suite command>']"
---

# /eng-kit:measure

The full suite can take a long time. Run it so it is not cut off by a tool time limit:

1. Read the configured command:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" config get test_command`
2. Tell the person, in one line, the command and that it runs the **whole** suite on this machine.
3. Start it in the background (it writes its output to `.eng-kit/last-run.log`):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" measure $ARGUMENTS
   ```

   Use the Bash tool's background mode for suites that may take longer than a few minutes, then wait for
   it to finish; do not start a second run meanwhile.
4. When it ends, report exactly the `Recorded …` line it printed (minutes, tests, result, change against
   the baseline). If it says no JUnit XML was written, show the printed tail of the log and suggest
   `config set junit_paths …`; do not guess numbers.
5. Offer `/eng-kit:dashboard`.

Never change test files, limits or the command to make a run faster here; this skill only measures.
