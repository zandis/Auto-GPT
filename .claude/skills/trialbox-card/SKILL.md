---
name: trialbox-card
description: How a TrialBox card lands, from claim to the train-ready line. Use when you start, build, review or hand over a card (a T-nnn, NEW-*, OPS-*, DIN-* or similar item of trialbox/docs/plan/33-plan-v7.md) in trialbox/, or when you are about to push a card's branch.
---

# Landing a TrialBox card

The owner's standing rules are in the repository's `CLAUDE.md`; they bind every step below. Plain English, short
sentences, in code comments, commits and the pull request.

## 1. Claim (push 1 of 3)

* Branch `agent/<card>-<slug>` from `origin/master`; a draft pull request from `.github/PULL_REQUEST_TEMPLATE.md`.
* Read the card's row, its "Files it touches", and the decisions it names. Write the acceptance as tests before code.

## 2. Build, test first

* **A bug: prove it first.** Write the test that shows the bug, run it, see it fail for the right reason, then fix
  and see it pass. A fix with no failing test first is not done. (Adapted from "The Prove-It Pattern", see NOTICE.)
* A new behaviour: the test that names it, red, then the code, green.
* A time limit, row count or memory cap is derived or declared (rule 7); a new `TB_*` name goes into
  `tb_common.config.DECLARED` in the same commit.
* A test that fails only when two cards meet (a registry, an index, a matrix every card writes to) goes into
  `CROSS_CARD_TESTS` in the Makefile.

## 3. One adversarial review by a fresh subagent

Doubt the work before it stands (adapted from "doubt-driven development", see NOTICE):

1. **Extract.** Give the reviewer the diff and the contract (the card's acceptance, the decisions, the owner's rules
   that apply), not your reasoning and not your conclusion. Evidence that contradicts you goes in.
2. **Doubt.** Brief it to find what is wrong: unstated assumptions, edge cases, shared state, a broken convention,
   failure under unexpected input, a rule of `CLAUDE.md` broken. Issues only; "none found after a thorough look" is
   an allowed answer.
3. **Reconcile.** Check every finding against the code: fix it with a test, or answer it in the pull request with
   file and line. A finding you could not confirm says "by reading", not "confirmed".
4. **Stop** after one round unless a finding was a real defect in safety code; then one more round on the fix.

## 4. The local set, then push 2 of 3

From `trialbox/`, output to files, never into `tail`:

```sh
.venv/bin/python -m tools.prepush --tests <every test file the card touches>
make cross-card PYTEST_N=auto CROSS_CARD_TESTS="tests/unit" > <scratch>/unit.log 2>&1   # once per card
```

Exit 0 from prepush, or a skip you name in the pull request (a tool this machine lacks; CI runs it).

## 5. Hand over

* Review fixes are push 3. Then `.venv/bin/python -m tools.train_ready --pr <n>`; it prints the line.
* Send the integrator `train-ready: #<n> <full sha>` and push nothing after it.
* Questions for the owner go in the pull request's "For the owner" section, one line each with your recommendation.
