# H105: the bench host's CI runner

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-105 (the owner's ruling, the integrator's comment 7117447272 on #639, widened by 7117870645 item 8):
  the bench host runs CI jobs beside the hosted runners, for trains and this repository's lane branches, made safe
  for a public repository
- **Date:** 2026-11-24
- **Install page:** [RUNBOOK §13 part: the bench host's CI runner](../runbook/13-bench-ci-runner.md)
- **Findings:** [`bench-ci-runner-h105-2026-11-24/findings.json`](bench-ci-runner-h105-2026-11-24/findings.json)
  (H105-01 to H105-07)
- **Files:** `.github/workflows/trialbox-bench-ci.yml` (new), `tools/bench_ci/` (new: the launcher, the cards' check,
  the egress proxy, the job image, the units, the install script, the example settings),
  `tests/unit/test_bench_ci_workflow_h105.py`, `tests/unit/test_bench_ci_launcher_h105.py`, the install page, this
  page and its findings, and `docs/RUNBOOK.md` (the generated index line of §13 only). Outside `trialbox/`: the
  new workflow and a new `.github/actionlint.yaml`, which declares the four bench labels so that the `checks` job's
  actionlint knows them (a test holds it to the launcher's labels; question 5). No existing workflow changes.

## What was built

1. **Triggers.** A workflow of its own, `TrialBox bench CI`. Its triggers are exactly a push to `train/*`, `agent/*`,
   `claude/*` or `lane-*` (a push needs write access to this repository; a fork's pull request does not) and
   `workflow_dispatch`; every job's `if` repeats the guard: a push to one of those refs, or a run by hand whose actor
   and triggering actor are the repository's owner (`github.repository_owner`, no name written). Concurrency: one
   group per lane branch, whose newer push cancels the older run; a train's run has a group of its own and is never
   cancelled or replaced. `permissions:
   contents: read`, no secret named, every action pinned by its full commit id, every checkout without a kept
   credential. The test reads every workflow file in `.github/workflows` and fails when a job that can run on a
   self-hosted runner is in any other workflow, when another workflow names the label `tb-bench` or waits for this
   one, or when this one gains any trigger (`pull_request`, `pull_request_target`, `issue_comment`, `workflow_run`,
   ...), branch, tag, input, permission, secret, unpinned action, job guard or concurrency change.
   A `runs-on` it cannot prove (a runner group, an expression that is not a matrix of literals, a reusable workflow
   of another repository) counts as the bench.
2. **Isolation.** `tools/bench_ci/launcher.py`, run by one systemd unit per slot as the `tb-bench` user (no login,
   no other group): each start registers one one-job runner and runs it in a fresh container of a rootless engine,
   as the image's user 1001, with one host folder (the job's scratch folder, made for it and deleted after it), no
   engine socket, the internal jobs network (no route out) and the egress proxy as the only way out (CONNECT to 443,
   the allow-listed names, never an address that is not public). CPU slots: read-only root, every capability
   dropped, no new privileges. Engine and GPU slots: a nested rootless engine of the job's own (H105-02).
3. **GPUs.** The CI cards, their cap and the reserved cards (card 1, the walk's, which the settings must hold, and the
   bench's) are in the host's settings file; the repository has an example with placeholders. The GPU slots share
   the CI cards (the lead's relay of the ruling: several jobs at once, under caps). A CI card that is reserved,
   missing or busy beyond its cap (more memory or load than the settings allow, or a reading the tool cannot give)
   stops the GPU slot before any registration, with a message naming the card; the job checks the same cards again,
   by UUID, as the runner's job-started hook. Tested with a stand-in for the card query tool.
4. **Jobs.** Unit shards (8) and the integration run on CPU slots, the GPU suites and `make full-set` on the GPU slot,
   the box rehearsal on an engine slot. The hosted runners keep the gate: this is **a separate workflow no branch
   rule requires**, not `continue-on-error`, so a failing bench job shows red (its result and time are the measure)
   and an outage of the bench blocks nothing. Nothing moved off the hosted runners.
5. **Install.** The page: prerequisites, install as the temporary sudo user, the token typed or pasted at a prompt
   into a root-only file (handed to the units as a systemd credential), verify (the named folders as `tb-bench`, a
   probe container with the CPU jobs' arguments exactly), and removal of everything, with what the owner removes on
   the code host.
6. **Times.** Each bench job writes its wall time to its summary and a small record; the hosted job `bench times`
   puts them in one table, to read against the hosted runners' times of the same train.

## What is proven by tests, and what only by the walk's install

| Part | Held by | Not shown |
| --- | --- | --- |
| No trigger but a push to a train or lane branch, or the owner's run by hand, reaches the bench label | `test_no_other_trigger_reaches_the_bench_label` and 30 planted mutants | the code host honouring the guard |
| The job container's arguments, per profile | the launcher tests (26 planted mutants caught) | the engine honouring them; the image building |
| The CI cards' check | a stand-in for the card query tool | the real tool's output on the bench's cards |
| The token's way | the code host's API host only, whatever a caller's proxy says; the configuration on stdin | the code host's answer (no call was made) |
| The egress proxy | the allow-list and a loopback socket (403 for plain HTTP, an unlisted host, a private address) | the allow-list being enough (H105-05) |
| Install, token, verify, remove | shellcheck and the script's text | every step: the walk runs them first |

## Questions

1. The GPU suites' model endpoint on the bench (H105-03): may a GPU job fetch the pinned public weights through the
   proxy and serve them on its own cards with its nested engine, or is a read-only volume of public weights wanted
   (a host folder the ruling does not allow today)?
2. The real-model rehearsal (H105-04): wire it as a bench job on the GPU slot (H-89's probe on the job's card), as a
   later card?
3. The minting token (H105-01): the owner's choice of credential and expiry.
4. A RUNBOOK number of its own for the install page (H105-07)?
5. `.github/actionlint.yaml` declares the bench labels (actionlint names an unknown runner label an error). It
   suppresses no finding, but it is a list in a lint's configuration: does the rule against allow-list entries
   cover it? actionlint was not run in the card's container; CI's `checks` job runs it.
