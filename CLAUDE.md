# Working rules for this repository

## What this is

TrialBox lives under `trialbox/`. The default branch is `master`.
Work rides "trains": the integrator forms each train from the train-ready lines on pull request #639.

## Binding rules (the owner's)

- Synthetic or public data only. No real patient data anywhere.
- Never print, commit or echo a secret. Never read `secrets.env`, anything under `uploads/`, or any key file.
- Nothing that costs money, no cloud calls. Every paid or GPU run goes through the integrator, with its estimate.
- No model names or model IDs in commits, pull request titles or bodies, code comments or docs.
- The commit trailer is exactly `Co-Authored-By: Claude <noreply@anthropic.com>`,
  plus the committing session's `Claude-Session:` line.
- Never `git stash`. Never rewrite history. Never push an empty commit.
- Never skip, gate or weaken a test. Changing what a test asserts needs the integrator's ruling.
- No scan allow-list entry. An inline ignore comment is one.
- No site zone in code.
- No REDCap source, SQL or text in the repository.
- Other lanes own their files. No change to their files or interfaces without a `question:` line and a go.
  Then change bodies only, and name the files under "Files outside the card".
- Only the register's keeper edits `trialbox/docs/handover/findings-register.md` and
  `trialbox/tests/unit/test_findings_register.py`. Findings go on the card's own page, and in a `findings.json`
  beside it in the register's `--add-from` form (the card name without a hyphen).
- Report outcomes faithfully: failures with their test ids, what was not run, what was not verified.
- Before a card is started, grep the tree for its subject. It may already be built.

## The line forms on #639

- A comment starts `Lane X to the integrator:`. Add `(lane Y to read)` when a lane's file is touched.
- The kinds are `train-ready:`, `question:`, `red:` (and `fix:`).
- The train-ready form: `train-ready: #<PR> <full head sha> base <full master sha>`.
  Under it: what was run, with counts; findings in a few bullets; any question.
  At most five lines of text under it.
- One comment per card. No progress notes.
- If CI fails for a reason outside the diff, say so with the job id. Do not re-run it or work around it.

## Checks before a train-ready line

Run from `trialbox/`, on the branch merged once with current master.

```
make lint
.venv/bin/python tools/doclint.py
make data-scan
make security-scan
PYTHONPATH=libs:services:. .venv/bin/python -m tools.limits_lint
PYTHONPATH=libs:services:. .venv/bin/python -m tools.text_keys        # if text changed
PYTHONPATH=libs:services:. .venv/bin/python -m tools.decisions_index --check
.venv/bin/python -m tools.findings_register --check
make cross-card
make guard
.venv/bin/python -m pytest tests --collect-only -q                     # rc 0, unique test basenames
```

- For a docs-only card, `make cross-card` takes CI's docs-only form. From the repository root:
  `git diff --name-only origin/master HEAD | python3 trialbox/tools/ci_docs_only.py tests`.
  If it prints tests, run `make cross-card PYTEST_N=auto CROSS_CARD_TESTS="<its output>"`;
  else plain `make cross-card`.
- Run the card's own tests and the tests of the files it touches.
- Run the whole unit and integration run once, only when `services/` or `libs/` change materially.
- Run the whole `tests/console` when a console template or console test changes.
- Run `.venv/bin/python -m pytest tests -k "runbook or planted or restore or findings"` when a runbook page changes.

## Output rules

- Every test and scan writes its output to a file. Read only the failing lines and the last line.
- Never pipe a test or scan into `tail` or `head` inside an `&&` chain.
- A worker's hand-back is at most 12 lines: files changed, commands with counts, what is not verified.
  The rest goes in the pull request.

## CI differs from a session's container

- CI runs non-root, without `PYTHONUNBUFFERED`, with temp paths over 100 characters, and with `pytest -n auto`.
- A fresh container needs `make fonts` and `make jvm-deps`.

## Where things are

- The plan: `trialbox/docs/plan/47-plan-10-2026-11-18.md`.
- Decisions: `trialbox/docs/decisions/` and its `REGISTRY.md`.
  A lane uses numbers from its own block, rows as reserved.
- The findings register: `trialbox/docs/handover/findings-register.md`.
- The runbook: `trialbox/docs/RUNBOOK.md` and its pages in `trialbox/docs/runbook/`.
- Reviews: `trialbox/docs/reviews/`.
