# Contributing to TrialBox

This file is for anyone who changes `trialbox/`: a person or an agent session. It is short on purpose. The working
plan is TB-PLAN-06 (`docs/plan/28-master-plan-v6.md`); its §6.1 holds the full card rules. The root
`CONTRIBUTING.md` of this repository belongs to the host project and does not apply here.

## One card, one branch, one pull request

* A card of the plan is one pull request and one session. The branch is `agent/<card id>-<slug>`, cut from the
  current `origin/master`.
* Keep to the files in the card's "Files it touches" column where you can; it avoids conflicts. If another file
  must change, change it and say which and why in the pull request under "Files outside the card" (guidance, not a
  stop; D-311).
* Open the pull request as a draft. The integrator merges; nobody merges their own card.
* Plain English and short sentences in commits and pull requests.

## Decisions are files

* One decision is one file: `docs/decisions/D-<nnn>-<slug>.md`. Its first line names the number (`**D-nnn Title.**`
  or `# D-nnn Title`) and its first lines name the card (`T-nnn`).
* Use a number from the block your lane's brief gives you and add its row to `docs/decisions/REGISTRY.md`. With no
  block, write `D-TBD` in the file name and the pull request; the integrator assigns the number (the owner's rule,
  2026-11-13: two sessions taking "the next free number" at once renumbered D-584 to D-589 on 2026-11-12).
* `docs/DECISIONS.md` is frozen: it keeps D-01 to D-270 as they are and takes no new entry.
* `python -m tools.decisions_index --check` (CI job `checks`) fails only on a number written twice; registry
  bookkeeping is printed as notes. `python -m tools.decisions_index` prints the index.

## Generated files are regenerated, never hand-merged

These files are written by a tool. Never edit them by hand and never resolve a merge conflict in them by hand:

| File | Generator | Checked in CI job |
| --- | --- | --- |
| `libs/tb_contracts/generated/models.py` | `make contracts` (`tools/gen_contracts.py`) | `contracts` (`make contracts-check`) |
| `docs/plan/25-traceability.csv` | `tools/gen_traceability.py` | `checks` (`--check`, warnings only) |
| the goldens under `tests/golden/` | `make goldens REASON="why the numbers move"` (`tools/goldens.py`) | `goldens` (`make goldens-check`) |
| the decisions index | `python -m tools.decisions_index` (printed, never committed) | `checks` (`--check`) |

On a conflict in one of them: take master's copy, run the generator, commit the result. CI fails when the committed
file differs from what the generator writes. Only one golden regeneration is in flight at a time; the integrator
calls it.

## Hot documents

`docs/DECISIONS.md`, `docs/RUNBOOK.md`, `docs/DATA.md`, `docs/USER_GUIDE.md` and `docs/SECURITY.md` are edited by
many cards. Until they are split into section files, a card adds a new decision file or a new section and one index
line; it does not rewrite other sections. RUNBOOK section numbers are given by the integrator.

## The safety core

Matching, the criteria engines, the guard, `authz` and the prefill path are the safety core. `.github/CODEOWNERS`
lists their paths, for information. A change there merges on green CI (including the property, mutation and
engine-agreement tests) and one automated adversarial review; no named human reviewer is required (D-311).

## Data and secrets

* Synthetic or public data only: no real name, chart number or other identifier in code, tests, logs, screenshots or
  documents. Run `python -m tools.data_scan` before every push (CI job `data-scan`).
* Secrets live in environment variables only. Never print, echo or commit them.

## Checks before a push

From `trialbox/`, after `make venv`, one command runs every step of CI's fast tier and the security scans, each into
a log file (`tools/prepush.py`; `tests/unit/test_prepush.py` keeps it equal to CI's `checks` job):

```
.venv/bin/python -m tools.prepush --tests <the test files you touched>
```

Exit 0: all passed. Exit 2: a step was skipped because this machine lacks its tool; name it in the pull request. Once
per card, also the whole unit suite (`make cross-card PYTEST_N=auto CROSS_CARD_TESTS="tests/unit"`, output to a
file). A single test run names a time zone (D-315):

```
TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. .venv/bin/python -m pytest <tests> -p no:cacheprovider -n 0
```

When the card is done and pushed, `.venv/bin/python -m tools.train_ready --pr <n>` checks the head (pushed, clean,
the two closing lines in every commit, no model name, no merge of master, a complete prepush run on it) and prints
the `train-ready` line.

## Development gates (D-311)

Building, testing, deploying and sharing the software need no IRB, ethics, conflict-of-interest or hospital review
step, because development uses synthetic or public data only. Rules that apply only when real patient data is read
are in `docs/decisions/D-311-no-development-gates.md`.

## Licence

`pyproject.toml` declares the package "Proprietary". The owner has not yet named a licence for `trialbox/`; there is
no `LICENSE` file here until the owner names one. The `LICENSE` at the repository root is the host project's and does not cover
`trialbox/`.
