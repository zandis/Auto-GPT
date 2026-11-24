# RUNBOOK §13 part: the bench host's CI runner

**Reader:** the people who build TrialBox.

*Card H-105, the owner's rulings (the integrator's comments of 2026-11-24 on #639, and item 8 of the next): the
bench host runs the slow CI jobs beside the hosted runners, for every train and every lane branch of this
repository, to make CI faster and to cut the lanes' work. The hosted runners keep the gate: an outage of the bench
blocks nothing.*

**Status: never installed.** The scripts and the workflow were tested in the repository only, with stand-ins for the
container engine, the card query tool and the code host. The first install is the walk's (while its temporary sudo
grant lasts). Send every output of the steps below; a FAIL line is a finding, not a step to skip.

**Drill:** none. This procedure is not rehearsed by a test: it needs the bench host. What the tests hold is listed at
the end.

## The three harms, and what stands in each one's way

1. **A public repository's self-hosted runner runs strangers' code** if any job a fork or a pull request can start
   reaches it, and a fork's pull request brings its own workflow files: the workflow on master and its test are no
   boundary. **The boundary is the host's gate** (`tools/bench_ci/gate.py`), run by the runner's job-started hook
   before the job's first step. It runs a job only when all hold: the event is a push or a run by hand; the
   repository is this one and not a fork; the ref is a `train/`, `agent/`, `claude/` or `lane-` branch (one level;
   for a run by hand also `master`); a run by hand is the owner's (actor and triggering actor); the workflow is
   `.github/workflows/trialbox-bench-ci.yml` at that ref; and that file, at the job's workflow commit, is the same
   blob as master's file now (read at the job's start by master's current commit). A refused job ends there; the
   cleanup leaves nothing behind. An accepted job leaves a mark the run step counts the job's hours from.
   **What the gate trusts, and why.** The job's facts: the `GITHUB_*` variables and the event payload the runner
   service sets from the code host's job message, before any step runs (no step has run yet, and a workflow cannot
   set a `GITHUB_*` variable). What the job must be: the job file the host's root mint step writes (the repository,
   the workflow's path, the proxy's address), and master's file, which the gate's own code reads from the code host at
   the job's start (master's current commit from the code host's ref list, then the file by that commit), before any
   code of the job runs. Both files are read by commit id (immutable). A branch on an older master
   whose copy of the file is unchanged has the same blob and runs; a branch that changed the file, or lacks a change
   master made to it, is refused until it carries master's file (so this card's own change to the file runs on the
   bench only once it is on master).
   **The switch and the guards are scheduling, not security.** A pushed branch runs its own copy of the workflow: it
   could drop the repository variable `TB_BENCH_CI`, the guard in each job's `if` and any trigger. The gate refuses
   such a job, because its file is not master's. Everyone with write access, and every write credential (an agent
   session's too), is trusted to start the jobs master's workflow defines on the bench; a branch rule that limits who
   may push `agent/*`, `claude/*` and `lane-*` narrows that. In an incident, stop the runner units (or remove the
   runners on the code host); unsetting the variable only stops new runs being scheduled.
   **Outside contributors:** the owner sets the repository's Actions setting for fork pull request workflows to its
   strictest choice, "Require approval for all outside collaborators" (Settings, Actions, General; the code host may
   word it "all external contributors"), so that no fork's workflow runs anywhere before someone has read it.
2. **A job that escapes its container reaches the owner's data and keys.** Each job runs in a fresh single-use
   container: a rootless engine run by the `tb-bench` user (no login, no other group, no `sudo`), the job image's own
   non-root user, the job's scratch folder (and for a GPU job the weights folder, read-only), no engine socket, a
   network of its own (internal: no route out, no name service) whose only way out is the egress proxy at a fixed
   address (port 443; the allow-listed hosts by exact name; never an address that is not public). Every profile has a
   read-only root, every capability dropped and no fuse or tun device. The `engine` and `gpu` profiles keep two
   capabilities, SETUID and SETGID, and so cannot set no-new-privileges: the nested rootless engine of the job's own
   maps its user namespace with the set-id helpers (`newuidmap`, `newgidmap`). Those two profiles therefore run on
   trains and the owner's runs only, never on a lane push.
3. **A leaked token lets another machine join as a runner, and more** (the token can change the repository's
   settings). It is typed into a root-only file (`/etc/tb-bench-ci/token`, root's, mode 0600). Only the units' root
   steps read it (the mint step before a job, the cleanup after one); the jobs' user never can, and no unit hands it
   a copy. What reaches the jobs' user is one job's runner configuration, as a file the container's entry point reads,
   deletes and unpacks into the runner's own files (never an argument); a job can read its own runner's credentials,
   which end with the job. The token goes to the code host's API address only.

**Which token** (the owner's choice, 2026-11-24): a fine-grained personal access token of the owner's account, for
**this repository only**, with the repository permission **"Administration: write"** and nothing else, a **30-day
expiry**, kept in the one root-only file. A plain registration token from the runner settings page expires within an
hour, so it cannot serve one-job runners. Revoke it with the removal below, and make a new one before it expires
(`install.sh token` again). Changing the token restarts every slot:
**a slot that is running a job is restarted too** (its job is stopped), so change it when no run is going.

**The egress allow-list.** Exact host names only: the code host (its web and API hosts and the archives the runner
downloads actions from), the code host's job service (the one suffix), its storage accounts named one by one, the
package registries and the container registries. No storage wildcard, no user-content wildcard, and no upload host
that the proxy can tell from a download host: it sees the name only, so a host that takes uploads and downloads under
one name (the code host's API, the registries) is reachable for both. The workflow's token is read-only (master's
workflow, which the gate holds every job to, asks for that); a job's own code could still carry a credential of its
own, which is the trust harm 1 states (everyone with write access). Each refusal is in the proxy's log by host name; a job that needs a
missing host shows it there.

## Prerequisites (on the bench host)

- The distribution release of the job image's base (or newer), with a service manager of version 248 or newer
  (`systemctl --version`), `python3` 3.10 or newer, `curl`, `sha256sum`, `runuser`.
- Two packages a fresh host lacks, installed first from the host's own distribution (the walk's first install had to
  add both): the rootless container engine that `tools/bench_ci/runner.Dockerfile` installs in the job image,
  version 4.4 or newer, and `uidmap` (`newuidmap`, `newgidmap`). Its network helpers (`netavark`, `aardvark-dns`, and
  `slirp4netns` or `passt`) come with it from the distribution. `install.sh install` stops before any change if
  any is missing, and says which.
- The folder `/var/lib/cni` (the install makes it, empty and root's, if it is not there, and remove takes it away
  again if it made it and it is still empty). Without it the distribution's engine 4.9 mounts an empty folder over
  `/var/lib` while it sets up a rootless user's own network, which hides `tb-bench`'s home and its networks: "network
  not found" for every network the user made, while the default network works (the walk's red, reproduced on 4.9.3
  with netavark 1.4). The jobs never use the default network: the egress-limited network is the boundary.
- For the GPU slots: the card query tool, and the engine's device description of the cards (written by the card
  vendor's container toolkit). Choose the CI cards (never card 1, the walk's; never a card of the bench) and their
  cap: the most memory and load a CI card may already carry when a GPU job starts. The GPU jobs share the CI cards.
  The weights folder (the integrator's ruling of 2026-11-24 on H105-03): readable by `tb-bench`, writable by root only;
  GPU jobs see it read-only at `/weights`, and the version check uses the pinned hashes. Nothing is downloaded.
- An unused private /16 for the jobs' networks (`BENCH_SUBNET_PREFIX`: 10.x, 172.16 to 172.31 or 192.168): each
  slot gets its own /24 in it.
- `BENCH_JOB_HOURS`: the most hours a job runs once the gate accepted it, and the most a runner waits for a job; at
  least the bench workflow's longest timeout (full-set: 600 minutes, so 11). While a slot waits or runs, it joins the
  egress proxy to its network again every 30 seconds, so a restarted proxy reaches every slot within that time.
- On the code host, by the owner: the Actions setting "Require approval for all outside collaborators" (above).
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
   runner archive and checks its SHA-256, builds the job image as `tb-bench`, makes the proxy's network (each job's
   own network is made at its start) and starts the egress proxy. The proxy's own start makes its network again if
   `tb-bench`'s engine does not see it, and every step of `tb-bench` sets the engine's runtime folder from its own
   user id (a system unit's `%U` is 0, so the units name none). It prints each step; it stops at the first problem.
3. The token: the owner makes it (above) and gives it to the operator by hand. The operator runs
   `sudo trialbox/tools/bench_ci/install.sh token` and pastes it at the prompt (nothing is shown). Never pass it as an
   argument or a variable, and never paste it into a chat or a file anywhere else. The runner slots start.

## The real-host test (before the token, and after any change to these files)

`sudo trialbox/tools/bench_ci/host_test.sh FOLDER...`, with the settings filled in and no token given: it runs
install, checks that the egress proxy starts and stays up with no restart in `tb-bench`'s own store and runtime
folder, runs verify (the token's lines and the slots' say NOT RUN: there is no token, and they are counted as not
run), then remove, and checks that nothing install recorded is left and that the settings are kept. It ends with one
line of counts and exits 1 on any failure. When the install step fails, nothing after it runs, remove least of all:
read the install's lines first. A signal (Ctrl-C) ends it with the step it stopped in and what to run next. Its
report names no folder, path, user, address or host (each is a stand-in such as `<folder 1>`, `<scratch>`,
`<checkout>`, `<user>` or `<address>`), so the walk posts it on the pull request as it is; the whole logs stay on the
host in a root-only folder under `/var/tmp`. It refuses to start while a token is installed, because its last step
removes what install made, the token too. A change to `install.sh`, the units or the launcher rides only after this
run is clean on the bench host (the integrator's ruling on 1448-19 (3)).

## Verify

`sudo trialbox/tools/bench_ci/install.sh verify FOLDER...`, naming each folder a job must never see: the owner's home,
the keys, the datasets, the integration folder, the bench's and the walk's working folders. The names are typed here
and go nowhere else. Every line says PASS or FAIL (or NOT RUN, before the token step: the token's lines and the
slots'):

- the token file is root's and 0600, `tb-bench` cannot read it, and no unit holds a copy of it; `tb-bench` is in no
  other group;
- `tb-bench` can neither read nor write any named folder, nor write the weights folder (GPU slots);
- the proxy and every slot unit run; the CI cards are within their cap (GPU slots);
- the probe, once for each profile that has slots, with that profile's arguments exactly: a user that is not root,
  no engine socket, no host folder but `/scratch` (and `/weights`, read-only, for GPU), a read-only root, no fuse or
  tun device, no capability (CPU) or only the set-id pair (engine, GPU), no name service, no direct way out; the code
  host and the package registry through the proxy; a host off the list, the upload host and an address written as a
  number refused.

Then, on the code host: the repository's runner list shows the waiting runners named `tb-bench-<slot>-<id>`.

## The owner's switch

Every bench job also needs the repository variable `TB_BENCH_CI` to be `on`. Unset (or anything else), every job of
"TrialBox bench CI" is skipped, so no lane branch or train waits for a runner that is not there. Only a repository
admin sets it (Settings, Secrets and variables, Actions, Variables). It schedules; it is not a security control (the
gate is, harm 1). The install ends here: **the owner sets `TB_BENCH_CI` to `on`** once verify has passed. Then a run of
"TrialBox bench CI" by hand (Actions, the workflow, Run workflow, on `master`) takes the runners; its summary's
`bench times` table holds each job's wall time, to read against the hosted runners' times of the same train.

**When the bench is down** (an outage, maintenance, the cards wanted for something else): first **unset
`TB_BENCH_CI`** (or set it to `off`); the bench jobs are skipped from the next push on. Set it to `on` again when the
bench is back. **In an incident** (a job that should not have run, a leaked credential): stop the runner units
(`sudo systemctl stop 'tb-bench-runner@*'`), then unset the variable, then remove the runners on the code host.

## The jobs it takes

Unit shards (eight, CPU), the integration run (CPU), the GPU suites (`make full-set` stage `gpu`, on the CI cards),
`make full-set` (a GPU slot with its nested engine) and the box rehearsal (an engine slot). A push to a lane branch
gets the unit shards and the integration run (the CPU profile, the hardest); the GPU suites, `make full-set` (600
minutes) and the box rehearsal run only for a train and the owner's run by hand (harm 2). The GPU slots share the
CI cards. A GPU job does not start when a CI card is busy beyond its cap (more memory or load than the settings
allow, or a reading the tool cannot give): the launcher registers no GPU runner while one is, and the job itself
checks again before its first step (the runner's job-started hook): it waits up to 30 minutes for busy cards to come
within the cap, checking every 30 seconds, then refuses with a message naming the card and why (wrong cards are
refused at once). The GPU box rehearsal (`tools/bench_ci/gpu_box.sh`, a GPU slot, a train or the owner's run by hand)
records the TPM ("no TPM: the passphrase path" in a container), the GPU record of its cards (model, memory, driver,
count; no serial or UUID), that the weights folder is mounted read-only, and that its own engine answers; the box
install under a real init, the first-run step, the unit start and the serving step say NOT RUN (a NOT RUN is never
counted as a pass). A run by hand is scheduled only on master or an allowed branch. The
workflow is separate and no branch rule requires it, so its jobs show red when they fail and block nothing; nothing moves off
the hosted runners until the owner's ruling says so.

## Remove it completely

1. The owner unsets the repository variable `TB_BENCH_CI` first, so that no new job asks for the runners.
2. `sudo trialbox/tools/bench_ci/install.sh remove`: stops every slot unit and the proxy, then removes only what
   install recorded that it made (`/etc/tb-bench-ci/made`, root's, written before each thing is made): the units,
   every container, network and image of `tb-bench`, the scratch folder, the token (shredded), `/opt/tb-bench-ci`,
   `/var/lib/cni` if it is still empty, the user, its linger, its home and its id range. What was there before stays:
   the settings file (the operator's), a scratch folder install refused, a user or folder of the same name. With no
   record (an install from before the record) it stops the units, deletes nothing and exits 1: the owner decides what
   goes. It prints a `LEFT` line for anything recorded that is still there and exits 1 if any is.
3. On the code host, by the owner: the repository's Settings, Actions, Runners: remove any runner named
   `tb-bench-*`; and revoke the token where it was made.
4. If the runner is not to come back, the workflow stays harmless: with the variable unset its jobs are skipped, and
   nothing else depends on them.

## What the tests hold, and what only the install can show

Held by tests in the repository: the gate's decision for a fork's pull request and for each condition broken alone
(`tests/unit/test_bench_ci_gate_h105.py`), the schedule (every workflow file, with planted mutants), each profile's
container arguments and network, the CI cards' check with a stand-in for the card query tool, the token's way (read
by the root mint step only, sent to the code host's API only, whatever a caller's proxy settings say), the one-job
configuration as a file (`tests/unit/test_bench_ci_unpack_jit_h105.py`), the egress proxy's allow-list on a loopback
socket, the install script's token step and its scratch and image steps as run with stand-ins, its verify and
remove steps as text (`tests/unit/test_bench_ci_workflow_h105.py`,
`tests/unit/test_bench_ci_launcher_h105.py`).

Shown only on the bench host: that the runner hands the hook the `GITHUB_*` variables and the payload the gate
reads; that the one-job configuration has the three-file form `unpack_jit.py` expects; that the image builds; that
the rootless engine honours every argument (no name service with `--dns none`, the proxy's fixed address, the
read-only root); that the nested engine runs with only the set-id pair, plain-folder storage and no tun device, and
runs the repository's compose, POC and rehearsal paths; that the cards pass through; that the allow-list is enough
for every job; that the units start and a stop cleans up; and the times. The real-host test (above) shows the install,
the proxy, verify and remove on the host. The card page:
`docs/handover/bench-ci-runner-h105-2026-11-24.md`.
