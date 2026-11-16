# Developing TrialBox

*Owner: Aimedics engineer. Status: living; changed in the same pull request as the code it describes. History: the
git log of this file. Added by T-635 (D-390, OPS-073): the RUNBOOK is for the site's IT, this page is for the people
and agent sessions who build TrialBox.*

The [Runbook](RUNBOOK.md) is what a hospital's IT reads. Half of it used to be developer content. This page is the
team's way in: what to run before a push, where the team's procedures are, and how a change is recorded. The card
rules are in [`CONTRIBUTING.md`](../CONTRIBUTING.md) and TB-PLAN-06 §6.1 (`docs/plan/28-master-plan-v6.md`); they are
not repeated here.

## The team's RUNBOOK sections

These sections are numbered in the RUNBOOK because other documents link them by number. Their audience is the team
(the *Audience* column of the RUNBOOK's section-numbers table), and a site's IT can skip them.

| Section | For |
| --- | --- |
| [§3, the build-gate parts](runbook/03-accounts.md#build-gate-the-ci-jobs-d-206) | the data-handling scan and the CI jobs: what gates a merge |
| [§11 Cloud runs](runbook/11-cloud-runs.md) and [qualify a model pair](runbook/11-qualify.md) | GPU runs on rented machines, with the owner's OK first |
| [§13 Working in parallel on one machine](runbook/13-parallel-work-on-one-machine.md) | temp roots, ports and databases per branch (D-201) |
| [§14 Judge bake-off](runbook/14-judge-bake-off.md) | comparing a judge candidate against the current judge |
| [§16 Box-install rehearsal](runbook/16-box-install-rehearsal.md) | `make rehearse-box` before a site's IQ |
| [§18 Developing a site mapping without the site's data](runbook/18-site-mapping-without-site-data.md) | the steward's procedure: no row of site data leaves the hospital |

A new section for the team takes the audience `team` in that table. A procedure that is for the team only and that no
site document links may live here instead.

## Before a push

From `trialbox/`, after `make venv` (the list in `CONTRIBUTING.md` is the source):

```sh
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m tools.doclint
.venv/bin/python -m tools.decisions_index --check
.venv/bin/python -m tools.data_scan
.venv/bin/python -m mypy <every .py file you changed>
TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. .venv/bin/python -m pytest <the tests you touched> -p no:cacheprovider -n 0
```

There is no default site time zone (D-315): a test run names one. The full suite (`make test`) is CI's.

**One shard of CI's unit run (T-747, D-475).** CI runs the unit suite in N parallel jobs `unit-shard (i/N)`; the
required check `unit` passes when every shard passed, the shards together ran every collected test exactly once and
the coverage ratchet holds on their combined coverage. A test file is in one shard, chosen by a hash of its path, so a
failing shard is repeated locally with the same split (the shard number and N are in the job's name):

```sh
make test SHARD=3/6                       # shard 3 of 6, as in CI
.venv/bin/python -m tools.test_shard files 3/6   # which test files that is
make cross-card                           # the tests that fail when two cards meet (CI job `cross-card`, minutes)
```

The cross-card list is `CROSS_CARD_TESTS` in the Makefile: a test that fails only when two cards meet (a registry, an
index or a matrix every card writes to) belongs there. N is the matrix of `unit-shard` in
`.github/workflows/trialbox-ci.yml`; changing it moves files between shards and nothing else.

## CI tiers and the merge train (D-564)

A push starts one of two tiers. `tests/unit/test_ci_tiers.py` holds the lists; a new job is put in one.

| Tier | Runs | Jobs |
| --- | --- | --- |
| fast tier | on every push to a pull request, draft or not | `changes`, `checks`, `data-scan`, `cross-card`, `powershell`, `differential` (and `lock` of the supply-chain workflow) |
| full tier | when the pull request is not a draft (marking it ready for review starts it), on a branch named `train/*`, on a push to `master`, and by hand | `unit-shard`, `unit`, `property`, `goldens`, `e2e-simple`, `demo-boot`, `security`, `standards`, `images` |

Three rules keep the billed runner minutes down (D-578):

* `checks` is one job with a step for each short check: ruff, actionlint, mypy, doclint, decision numbers, licence
  register, limits lint, generated contracts, shipped rulesets, traceability, shellcheck, the PoC host scripts.
  Every step runs even when an earlier one failed; the log names each.
* The image gates (`trialbox-images.yml`) run for a merge train, on `master` when what goes into an image changed,
  for a release tag, weekly and by hand. They do not run on a card's pull request: a card that changes an image
  says so, and the integrator puts it on a train early. The arm64 leg runs for a train, `master` and a release tag.
* A push to `master` whose tree a merged train already proved runs the fast tier only
  (`tools/ci_proved_tree.py`: the merge commit's tree equals the train head's, master had nothing the train lacked,
  and every full-tier check passed on that head). Any doubt runs the full tier.

* A card's pull request stays a draft while it is built. It needs the fast tier green on its head, its targeted
  tests and, where the plan asks, its adversarial review. On a draft the check `unit` shows as skipped, never as
  success: nothing merges on it.
* A new push cancels the older run of the same pull request.
* **The merge train.** The integrator builds `train/<n>` from `master` by merging the heads of several reviewed
  pull requests (`git merge --no-ff <head>` for each) and opens it as a pull request. The full tier runs once on
  it. A green train is merged with a merge commit, not a squash, so the card pull requests show as merged. A red
  train names the failing tests: the card that owns them is dropped and the train rebuilt.
* To repeat a train's failure: `make test SHARD=i/N` for a unit shard, the job's own `make` target for the others
  (RUNBOOK §3, the build-gate parts).

## Where the heavy jobs run

Repository variable `TB_RUNNER`, under Settings → Secrets and variables → Actions → Variables.

* Unset, empty, or any value other than `trialbox`: every job stays on the GitHub-hosted image it uses today.
* `trialbox`: the heavy jobs run on the self-hosted runner labelled `self-hosted`, `Linux`, `ARM64` and `trialbox`.
* A pull request whose head repository is not this repository stays on the GitHub-hosted image even when the
  variable is `trialbox`.

The heavy jobs are `unit-shard`, `e2e-simple`, `goldens` and `demo-boot`; the nightly runs `public-e2e`,
`backup-drill`, `update-drill`, `perf-5k`, `random-order` and `compose`; and the nightly-quality shards `mutation`
and `branch-coverage-shard`. `tests/unit/test_ci_runner.py` holds that list. The image gates, the supply-chain lock,
the short checks and `scale-50k` stay on GitHub-hosted runners. `tools/ci_postgres.sh` installs PostgreSQL 16 when
the runner does not already have it, and drops the TCP cluster that package starts.

While this repository is public, a fork can edit a workflow and remove the fork check. Fork pull request workflows
from outside collaborators should require approval before they run. This page does not change that setting.

## Documents

* **Nine documents.** README and the eight under `docs/`: Architecture, Runbook, Security, Data, Validation, User
  guide, Decisions, and this page. `tools/doclint.py` fails on any other Markdown file in `docs/` (D-139, D-390).
* **Section files.** Runbook, Security, Data and User guide are one file per numbered section (D-352). Edit the
  section file, then run `python -m tools.doclint --write` to rewrite the index. A part of a section is another
  `NN-<slug>.md` file whose first line is not `# N. Title` (for example `runbook/22-planned-power-cut.md`).
* **Decisions are files**: `docs/decisions/D-nnn-<slug>.md` and a row in `docs/decisions/REGISTRY.md` (D-306, D-311).
  `docs/DECISIONS.md` is frozen.

## The scale gate and the limits lint

OD-10 (TB-PLAN-06.1): every time limit, memory cap and count in the product is derived from the hardware, the model's
measured speed or the size of the data, or it is a declared setting with a reason. Two checks hold it (T-687, D-471):

* **The limits lint** (`python -m tools.limits_lint`, CI job `checks`). A new `timeout=` over 60 s or a new `LIMIT n` /
  `limit=n` literal in `services/` fails until it has a line in `tools/limits_allow.yaml` whose reason names its
  scale-review finding (`F-nn`), the card that removes it, or why it is not a cut. A card that removes a limit removes
  its line in the same pull request (a stale line fails too). `--list` prints what it finds.
* **The scale gate** (`tests/perf/test_scale_gate.py`, nightly job `scale-50k` of `trialbox-e2e.yml`). The night at
  50,000 synthetic patients: ingest, the lake rebuild through the site publish, the screen with the slow model
  stand-in (seconds per call, a 40 s outage, a restart) and the backup, each part in its own process under the
  `mem_limit` of its compose service, enforced by a cgroup (`systemd-run`). Today's failures are listed in `EXPECTED`
  of `tools/scale_gate.py` with their findings and cards (empty since T-689: F-01, F-02, F-05 and F-04 were removed when T-690, T-691, T-692 and T-689 fixed them): they show as
  XFAIL and keep the job green; the card that fixes one removes its line, because a pass of a listed check fails the
  job. A small run on this machine: `TB_ENV=DEV TB_TZ=Asia/Taipei PYTHONPATH=libs:services:. .venv/bin/python -m
  tools.scale_gate --patients 300` (no cgroup here: the memory is measured and a part over its cap is killed). The
  gate's own logic runs on every pull request at 200 patients (`tests/unit/test_scale_gate_logic.py`).

## Operations drills

Every site page of the RUNBOOK names its drill, in a line `**Drill (T-213b):**` with the name of a test. T-213b
writes those tests (Docker drills as code, `tests/integration/`); a drill whose recovery step is missing from its
page fails. `tests/unit/test_operations_docs.py` holds the pages of T-635 to that rule until then.
