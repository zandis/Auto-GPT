# RUNBOOK §13 part: the bench host's CI runner

**Reader:** the people who build TrialBox.

*Card H-105, the owner's ruling (the integrator's comment of 2026-11-24 on #639): the bench host runs the slow CI
jobs beside the hosted runners, to make CI faster and to cut the lanes' work. The hosted runners keep the gate: an
outage of the bench blocks nothing.*

**Status: never installed.** The scripts and the workflow were tested in the repository only, with stand-ins for the
container engine, the card query tool and the code host. The first install is the walk's (while its temporary sudo
grant lasts). Send every output of the steps below; a FAIL line is a finding, not a step to skip.

**Drill:** none. This procedure is not rehearsed by a test: it needs the bench host. What the tests hold is listed at
the end.

## The three harms, and what stands in each one's way

1. **A public repository's self-hosted runner runs strangers' code** if any trigger a fork or a pull request can
   fire reaches it. The bench jobs live in `.github/workflows/trialbox-bench-ci.yml`, reachable from a push to a
   `train/*` branch and from a run by hand by the repository's owner only (each job checks it again); no other
   workflow names the label `tb-bench`, and no other job can run on a self-hosted runner.
   `tests/unit/test_bench_ci_workflow_h105.py` reads every workflow file and fails otherwise.
2. **A job that escapes its container reaches the owner's data and keys.** Each job runs in a fresh single-use
   container started by `tools/bench_ci/launcher.py`: a rootless engine run by the `tb-bench` user (no login, no
   other group, no `sudo`), the job image's own non-root user, one host folder (the job's scratch folder), no engine
   socket, an internal network whose only way out is the egress proxy (port 443, the allow-listed hosts, never an
   address that is not public). Where it can be (CPU jobs), the root is read-only with every capability dropped.
   Jobs that need an engine of their own (`engine` and `gpu` slots) get a nested rootless one inside their
   container, never the host's.
3. **A leaked token lets another machine join as a runner.** The token is typed into a root-only file
   (`/etc/tb-bench-ci/token`, mode 0600) and handed to the runner units as a systemd credential. It is never an
   argument, never in an environment, never in the journal or the repository. The launcher sends it to the code
   host's API address only, to ask for a one-job runner registration; the job's container never sees it.

**Which token.** A one-job registration needs a token that may create runners on this repository: a fine-grained
personal access token of the owner's account, for **this repository only**, with the repository permission
"Administration: read and write" and nothing else, and an expiry no later than the owner wants the runner to live.
A plain registration token from the runner settings page expires within an hour, so it cannot serve one-job runners
for longer than that. This token is stronger than a registration token: keep it in the one root-only file, and revoke
it when the runner is removed.

## Prerequisites (on the bench host)

- Ubuntu 24.04 or newer with systemd 248 or newer, `python3` 3.10 or newer, `curl`, `sha256sum`, `runuser`.
- The rootless container engine that `tools/bench_ci/runner.Dockerfile` installs in the job image, from the host's
  own distribution, version 4.4 or newer, with `uidmap` (`newuidmap`, `newgidmap`).
- For the GPU slot: the card query tool, and the engine's device description of the cards (written by the card
  vendor's container toolkit). Choose the CI cards: never card 1 (the walk's), never a card of the bench.
- A folder for CI scratch only, on a disk with room for the jobs (venvs, the JVM and fonts caches, images of the
  nested engine). Never a folder of the bench, the walk, the datasets, the integration folder or a home.
- A checkout of `master` of this repository, readable by root.

## Install (as the temporary sudo user)

1. Fill in the settings: `sudo install -m 0600 -o root -g root trialbox/tools/bench_ci/settings.example.env
   /etc/tb-bench-ci/settings.env` (make the folder first: `sudo install -d -m 0750 /etc/tb-bench-ci`), then edit
   every `<...>` (`sudoedit /etc/tb-bench-ci/settings.env`). The runner release's version and SHA-256 come from the
   runner's release page (the `linux-x64` archive). The repository holds only the example: no host detail goes into
   it.
2. `sudo trialbox/tools/bench_ci/install.sh install`: checks the prerequisites and the settings, makes the
   `tb-bench` user and its id range, lays out `/opt/tb-bench-ci`, the units and the scratch folder, downloads the
   runner archive and checks its SHA-256, builds the job image as `tb-bench`, makes the two networks (the jobs'
   internal one, the proxy's way out) and starts the egress proxy. It prints each step; it stops at the first problem.
3. The token: the owner makes it (above) and gives it to the operator by hand. The operator runs
   `sudo trialbox/tools/bench_ci/install.sh token` and pastes it at the prompt (nothing is shown). Never pass it as an
   argument or a variable, and never paste it into a chat or a file anywhere else. The runner slots start.

## Verify

`sudo trialbox/tools/bench_ci/install.sh verify FOLDER...`, naming each folder a job must never see: the owner's home,
the keys, the datasets, the integration folder, the bench's and the walk's working folders. The names are typed here
and go nowhere else. Every line says PASS or FAIL:

- the token file is root's and 0600, and `tb-bench` cannot read it; `tb-bench` is in no other group;
- `tb-bench` can neither read nor write any named folder;
- the proxy and every slot unit run; the CI cards are free (GPU slot);
- the probe: a container with the CPU jobs' arguments exactly runs as a user that is not root, sees no engine
  socket, has no host folder but `/scratch` and a read-only root, cannot go out but through the proxy, reaches the
  code host and the package registry through it, and is refused a host off the list and an address written as a
  number.

Then, on the code host: the repository's runner list shows the waiting runners named `tb-bench-<slot>-<id>`, and a
run of "TrialBox bench CI" by hand (Actions, the workflow, Run workflow, on `master`) takes them. Its summary's
`bench times` table holds each job's wall time; read it against the hosted runners' times of the same train.

## The jobs it takes

Unit shards (eight, CPU), the integration run (CPU), the GPU suites (`make full-set` stage `gpu`, on the CI cards),
`make full-set` (the GPU slot with its nested engine) and the box rehearsal (an engine slot). A GPU job does not
start when its cards are busy: the launcher registers no GPU runner while they are, and the job itself checks them
again before its first step (the runner's job-started hook), with a message naming the card and why. The workflow is
separate and no branch rule requires it, so its jobs show red when they fail and block nothing; nothing moves off
the hosted runners until the owner's ruling says so.

## Remove it completely

1. `sudo trialbox/tools/bench_ci/install.sh remove`: stops and removes every slot unit and the proxy, every container,
   network and image of `tb-bench`, the scratch folder, the token (shredded), `/etc/tb-bench-ci`, `/opt/tb-bench-ci`,
   the user, its home and its id range. It prints a `LEFT` line for anything still there and exits 1 if any is.
2. On the code host, by the owner: the repository's Settings, Actions, Runners: remove any runner named
   `tb-bench-*`; and revoke the token where it was made.
3. If the runner is not to come back, the workflow stays harmless: with no runner holding the label, its jobs wait
   and time out, and nothing else depends on them.

## What the tests hold, and what only the install can show

Held by tests in the repository: the triggers (every workflow file, with planted mutants), the job container's
arguments, the CI cards' check with a stand-in for the card query tool, the token's way (the code host's API only,
whatever a caller's proxy settings say; the configuration on the container's standard input), the egress proxy's
allow-list on a loopback socket, and the install script's token, verify and remove steps as text
(`tests/unit/test_bench_ci_workflow_h105.py`, `tests/unit/test_bench_ci_launcher_h105.py`).

Shown only on the bench host: that the image builds, that the rootless engine honours every argument, that the
nested engine runs the repository's compose, POC and rehearsal paths, that the cards pass through, that the proxy's
allow-list is enough for every job, that the units start, and the times. The card page:
`docs/handover/bench-ci-runner-h105-2026-11-24.md`.
