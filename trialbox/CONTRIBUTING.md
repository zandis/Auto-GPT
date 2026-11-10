# Contributing to TrialBox

This file is for anyone who changes `trialbox/`: a person or an agent session. It is short on purpose. The working
plan is TB-PLAN-06 (`docs/plan/28-master-plan-v6.md`); its §6.1 holds the full card rules. The root
`CONTRIBUTING.md` of this repository belongs to the host project and does not apply here.

## One card, one branch, one pull request

* A card of the plan is one pull request and one session. The branch is `agent/<card id>-<slug>`, cut from the
  current `origin/master`.
* Touch only the files in the card's "Files it touches" column. If another file must change, say which and why in
  the pull request under "Files outside the card", or ask the integrator first.
* Open the pull request as a draft. The integrator merges; nobody merges their own card.
* Plain English and short sentences in commits and pull requests.

## Decisions are files

* One decision is one file: `docs/decisions/D-<nnn>-<slug>.md`. Its first line names the number (`**D-nnn Title.**`
  or `# D-nnn Title`) and its first lines name the card (`T-nnn`).
* The number comes from `docs/decisions/REGISTRY.md`. The integrator writes the row before the branch is cut. New
  numbers start at D-300. A pull request never edits the registry.
* `docs/DECISIONS.md` is frozen: it keeps D-01 to D-270 as they are and takes no new entry.
* `python -m tools.decisions_index --check` (CI job `docs`) fails on a number written twice, a decision file with no
  registry row, a new entry in the frozen log, or a number no row covers. `python -m tools.decisions_index` prints
  the index.

## Generated files are regenerated, never hand-merged

These files are written by a tool. Never edit them by hand and never resolve a merge conflict in them by hand:

| File | Generator | Checked in CI job |
| --- | --- | --- |
| `libs/tb_contracts/generated/models.py` | `make contracts` (`tools/gen_contracts.py`) | `contracts` (`make contracts-check`) |
| `docs/plan/25-traceability.csv` | `tools/gen_traceability.py` | `trace` (`--check`) |
| the goldens under `tests/golden/` | `make goldens REASON="D-nnn: why the numbers move"` (`tools/goldens.py`) | `goldens` (`make goldens-check`) |
| the decisions index | `python -m tools.decisions_index` (printed, never committed) | `docs` (`--check`) |

On a conflict in one of them: take master's copy, run the generator, commit the result. CI fails when the committed
file differs from what the generator writes. Only one golden regeneration is in flight at a time; the integrator
calls it.

## Hot documents

`docs/DECISIONS.md`, `docs/RUNBOOK.md`, `docs/DATA.md`, `docs/USER_GUIDE.md` and `docs/SECURITY.md` are edited by
many cards. Until they are split into section files, a card adds a new decision file or a new section and one index
line; it does not rewrite other sections. RUNBOOK section numbers are given by the integrator.

## The safety core

Matching, the criteria engines, the guard, `authz` and the prefill path are the safety core. `.github/CODEOWNERS`
lists their paths. A change there needs the named human safety-core reviewer (owner action OD-9; until that person
is named, the owner alone) and only one safety-core pull request is in review at a time.

## Data and secrets

* Synthetic or public data only: no real name, chart number or other identifier in code, tests, logs, screenshots or
  documents. Run `python -m tools.data_scan` before every push (CI job `data-scan`).
* Secrets live in environment variables only. Never print, echo or commit them.

## Checks before a push

From `trialbox/`, after `make venv`:

```
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m tools.doclint
.venv/bin/python -m tools.decisions_index --check
.venv/bin/python -m tools.data_scan
TB_ENV=DEV PYTHONPATH=libs:services:. .venv/bin/python -m pytest <the tests you touched> -p no:cacheprovider -n 0
```

The full suite (`make test`) is run by CI and the integrator, one run at a time on the shared machine.

## Licence

`pyproject.toml` declares the package "Proprietary". The owner has not yet named a licence for `trialbox/`; there is
no `LICENSE` file here until the owner names one. The `LICENSE` at the repository root is the host project's and does not cover
`trialbox/`.
