---
name: status
description: Report how fast this project's test suite is now, from eng-kit's local records - latest full run, baseline, change, slowest class. Use when the person asks how long the tests take, whether the suite got faster or slower, or for the test-speed status of the project.
argument-hint: "[--json]"
---

# /eng-kit:status

1. If `.eng-kit/config.json` does not exist in the project, say eng-kit is not set up here and offer
   `/eng-kit:init`. Stop.
2. Run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" status $ARGUMENTS
   ```

3. Answer with the numbers it printed, lead with the latest full run and the change against the baseline.
   Use only these numbers; if there is no baseline or no full run yet, say so and offer `/eng-kit:measure`
   or `/eng-kit:import-ci`.
4. Compare like with like: a CI run and a local run have different environments; say which is which.
