---
name: dashboard
description: Build and open the local eng-kit test-speed dashboard for this project (an offline HTML page in .eng-kit/).
disable-model-invocation: true
argument-hint: "[--no-open]"
---

# /eng-kit:dashboard

1. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" dashboard $ARGUMENTS
   ```

2. Give the person the printed path. If it could not open a browser (for example over SSH), say they can
   open that file in any browser; it needs no network and sends nothing anywhere.
3. Add one line with the headline from
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" status` (latest full run against the baseline).
