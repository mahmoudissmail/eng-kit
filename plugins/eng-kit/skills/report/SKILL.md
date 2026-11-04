---
name: report
description: Write a shareable markdown report of this project's test speed - per-environment baseline and latest time, every recorded run, what each improvement achieved, and release speed. Use when the person asks for a test-speed report, a summary to share with the team, or before-and-after results.
argument-hint: "[--anonymous]"
---

# /eng-kit:report

1. If `.eng-kit/config.json` is missing, offer `/eng-kit:init` and stop.
2. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" report $ARGUMENTS
   ```

   It prints the report and saves it as `.eng-kit/report.md` (or `report-anonymous.md` with `--anonymous`, which leaves
   out the project name, run labels, commits and runner names, for sharing outside the team).
3. Give the person the saved path and the two or three headline numbers (latest time against the baseline per
   environment). Use only numbers from the report.
