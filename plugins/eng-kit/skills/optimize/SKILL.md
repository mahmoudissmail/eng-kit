---
name: optimize
description: Make this project's test suite faster, one measured change at a time - builds a ranked plan from eng-kit's measurements and the project's test and CI files, applies the change the person picks (with approval), measures it against the baseline and records the result. Never weakens a test.
disable-model-invocation: true
argument-hint: "[plan | next | <item id>]"
---

# /eng-kit:optimize

Speed comes from cheaper setup and better use of hardware, never from checking less. The full suite on
the merge request stays the merge gate. The project's own rules (CLAUDE.md, CONTRIBUTING, the prompt you
were given) come first, for example a rule that the full suite must not run locally.

## 1. Measure and plan (read-only)

1. If `.eng-kit/config.json` is missing, stop and offer `/eng-kit:init`.
2. If `/eng-kit:status` shows no full passed run, ask the person for a baseline first: a CI job id for
   `/eng-kit:import-ci`, or their go for `/eng-kit:measure`. Do not guess numbers.
3. Build the plan:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" analyze
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" plan show
   ```

4. Show the open items as a short table: id, change, expected gain, risk. Lead with the top one and say
   why it is first (evidence from the plan). The checks are heuristics: confirm each piece of evidence in
   the files before you act on it, and say if it does not hold.
5. With `$ARGUMENTS` = `plan`, stop here.

## 2. Apply one item (only with the person's go)

1. Take `$ARGUMENTS` as the item id, `next` for the top open item, or ask which one.
2. Read the guide for it before changing anything:
   - setup, seeding, fakes, boot: `testing-standard` (and its stack reference),
   - parallel and isolation: `testing-standard/references/parallel-safety.md`,
   - database speed: `testing-standard/references/databases.md`,
   - CI items: `testing-standard/references/ci.md`,
   - guards and the random-order run: `testing-standard/references/guards.md`,
   - the overall order and gains: `speed-playbook`.
3. Propose the exact change: files, what changes, how it will be verified, what could break. Wait for an
   explicit yes. Never touch secrets, CI variables, runners, branch protection or production settings; give
   those to the person as steps instead.
4. Make the change on a new branch. One plan item per branch and merge request.
5. Prove it still checks the same things: run the tests the change touches (filtered), plus lint. Never
   remove an assertion, skip a test, lower a check, or raise a time limit to make it pass. If the only fix
   would change product behaviour, stop and ask.
6. Mark it applied: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" plan set <item> applied --note "<branch or MR>"`.

## 3. Measure the effect

1. After the merge request's CI test job finishes, ask for the job id and run `/eng-kit:import-ci <job>`;
   or, where the project allows a local full run and the person agrees, `/eng-kit:measure`.
2. Compare like with like (same environment as the baseline). Then:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/engkit.py" plan set <item> verified --run <run id> --note "<minutes before -> after, % change>"`.
   If it got slower or broke tests, say so plainly, set it back to `open` with a note, and propose the fix or
   the revert.
3. Run `analyze` again (the next item may have changed) and offer `/eng-kit:dashboard`.

## Rules that do not bend

- One change at a time, each measured; the baseline never moves to flatter a result.
- Approval before every write and before any full-suite run.
- Speed never comes from running fewer or weaker tests.
