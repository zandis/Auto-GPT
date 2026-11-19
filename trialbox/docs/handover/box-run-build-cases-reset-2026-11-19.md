# H-56: the box-run rehearsal's build cases on train 99's CI run (2026-11-19)

**Reader:** the people who build TrialBox: lane H, the integrator, and whoever reads the next red of the box-run
rehearsal's build cases. Findings for builders, so in one language.

## What failed

Train 99's CI run, job 135621934683 (unit shard 4/6), worker gw1, 14:21:46 to 14:23:07 UTC:
the cases `build`, `build-refused` and `build-preempt` of `test_rehearsal_case` in
`tests/unit/test_g1_box_install_run.py`.
In each case steps b01 to b05 finished, then:

    TB-STOP b06-verify: tools/verify_update.py (the Ed25519 signature with the vendor public key): exit 1

`build` and `build-preempt` then read `FAIL the seven build steps, done`. `build-refused` stopped in check.py with
`KeyError: 'refused'`, because the bundle check that writes `refused` runs only after verify_update.py passes.

The `ConnectionResetError: [Errno 104]` in the same log is not from these cases. It is a traceback that another
test's in-process `http.server` printed to stderr from `socketserver.process_request_thread` at about 45 % of the
shard. The build cases start no server and connect to nothing. `box_vm.py models-place` fetches nothing here,
because `tb-model-template` is empty and there is no `tb-embed-list`.

## Cause

`tools/host_tree.py` `pack()` read every file twice: once to hash it into `HOST-SHA256SUMS`, then again for the tar,
with the size taken at that second moment. The rehearsal's `vendor()` packs the live checkout (`tools.host_tree pack
--root $ROOT`). That is git's tracked files plus untracked files git does not ignore, under `deploy/`, `tools/`,
`libs/` and `schemas/`. If a file there changes between the two reads, for example because a parallel test writes
it, the tar no longer matches its own sums. make_bundle signs it anyway, because the manifest hashes the tar as it is.
At b06, verify_update.py checks the host tree against its sums and refuses it.

The run shows only `exit 1`. The refusal text is in the run's `logs/b06-verify.log`, inside a temp folder on the
runner, and the shard's artifact needs a login to download. So the CI run's own text was not read. The local
reproduction below gives the same stop at b06, and the same `KeyError` path for build-refused.

## How it was reproduced

* The three cases alone, and the file under `-n 8` with `PYTHONUNBUFFERED` unset: passed (67 passed).
* The whole shard as CI runs it (`make test PYTEST_N=auto SHARD=4/6`, 4 CPUs): 2687 passed. The concurrent
  writer is a matter of timing.
* `build` while a loop rewrote an untracked file under `tools/` (zz_h56_churn.txt) with random bytes: rc 1, `TB-STOP
  b06-verify ... exit 1`, and in `logs/b06-verify.log`: `REJECTED: trialbox-host.tar: host tree:
  tools/<that file>: sha256 differs from HOST-SHA256SUMS`.
* The old `pack()` against a small tree with the same writer: it crashed with `OSError: unexpected end of data`
  (the file shrank between the stat and the copy). The new one gave 0 torn trees in 25.

## Fix

`pack()` reads each file once. It hashes the file while copying it into a private snapshot folder beside the output
(`<out>.snap`, mode 0700), then writes the tar from the snapshot and removes the snapshot. The tar now always matches
its own `HOST-SHA256SUMS`, whatever happens to the source tree while it is packed. A file that vanishes during the
pack still stops the pack with an error. Nothing is skipped silently.

The same weakness was in the product's packer. `tools/make_bundle.sh` packs the release checkout with the same
`pack()`. On the build VM nothing else writes to that clone, so the risk there was low. On a vendor's workstation, an
editor saving a file during the pack would give a bundle that every box refuses (it fails closed, never open).
`deploy/gcp/box-install-run.sh` has no such weakness: it has no fixed port and no server of its own in these steps.

## Tests

`tests/unit/test_h56_build_cases_host_tree.py`:

* pack under a concurrent writer, 25 times: each tar passes `check_tar`, and no snapshot is left;
* static: `pack()` opens the source files in one place only;
* the rehearsal names no fixed port (every server takes `free_port`, which binds port 0);
* `build`, `build-refused` and `build-preempt` run side by side, each in its own folder.

Findings: `box-run-build-cases-reset-2026-11-19/findings.json` (H56-01).
