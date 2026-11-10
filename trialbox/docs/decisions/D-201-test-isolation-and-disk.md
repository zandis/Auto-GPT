**D-201 Test isolation on one machine: a temp root per branch, a cluster per worker with an owner, the plugin set
locked, the suite in parallel, and the disk cleaned and checked.** Task T-003 of TB-ASSESS-01
(`docs/reviews/2026-11-09-assessment-and-tasks.md` §3.1 and §5.2, §5.3; WS-01.4, R-29; URS-ADM-06, RSK-14,
TST-UNIT-01, TST-CI-01), branch `wave0-ci`, no pull request yet (the integrator opens it). 2026-11-09.

*Why.* Several agents run the suite on one machine at once (P-50 to P-53, P-57). The test cluster sat in
`/tmp/tb-pgtest-*` and the shared one in `/tmp/tb-pglocal-<uid>`; a killed run left its server and data behind
(2.4 GB seen); `/tmp/pytest-of-root` grew to 11 GB; `pytest-randomly` was put into the shared venv by hand with no
lock to undo it; the suite ran serially for 18 minutes; the disk ran out first.

*What.* (1) **One temp root per branch.** `make` sets and exports `TB_TEST_ROOT` (`$TB_SCRATCH/tb-tests-<branch>`;
`TB_SCRATCH` is the agent's scratchpad, default `/var/tmp/trialbox-<uid>`); `/`, a top-level directory, `/tmp`,
`/var/tmp` and the home directory are refused. Under it: pytest's `--basetemp`, the run's `TMPDIR` (so a
`tempfile.mkdtemp()` in any test lands there; emptied after the run), the e2e and drill folders and the shared
cluster of `pglocal.for_work` (`shared_dir()`). (2) **A cluster per xdist worker with an owner.** The
`pg_cluster_url` fixture puts the cluster at `<root>/pg-<worker>`, writes `.owner` (pid and start time, so a reused
pid counts as dead), stops it at teardown and at exit, refuses a root whose cluster has a live owner, and without a
root falls back to a fresh folder under the scratch root, never `/tmp`. `python -m tools.pglocal --gc` stops and
removes every owned cluster whose owner is gone; a cluster without an owner file is never touched by it. `stop` is
idempotent. As root the server runs as `postgres`: `pglocal` adds the search bit (o+x only) to a parent that lacks
it, and moves a socket path too long for Unix to a short private folder that `<cluster>/run` links to. (3) **The
plugin set is the lock's.** `[dependency-groups] test` pins pytest 9.2.0, pytest-timeout 2.4.0, pytest-cov 7.1.0
and pytest-xdist 3.8.0; `uv.lock` (new, committed) locks everything; `make venv` is `uv sync --frozen --group test
--extra dev` (it removes what was installed by hand, and a uv venv has no pip); `make test` first runs `venv-check`
(`uv sync --check`) and refuses a venv that drifted. `addopts` adds `-p no:randomly -p no:cacheprovider`; an
explicit `-p randomly` where the plugin is installed fails the run through a guard test, unless `TB_TEST_RANDOM=1`
(the nightly random-order job of review §5.2 (3), the sibling session's). `tmp_path_retention_count = 1`, policy
`failed`. (4) **In parallel.** `make test` runs `pytest -n auto` (`PYTEST_N` to change). (5) **Disk.** `make
check-disk` fails under `TB_MIN_FREE_GB` (20) and reports the branch root against its 10 GB budget; `make
clean-tmp` removes what earlier runs left and nobody uses now (pytest run folders without a live `.lock`, old
clusters without a client, the drill and e2e folders in `/tmp`, the rehearsal's `runs/`, the tarballs of all but
the two newest `.cache/complete-run` runs), keeping anything a running process holds; the rehearsal keeps the newest
two evidence folders per case. RUNBOOK §12.

*After the adversarial review* (a fresh Fable session, 2026-11-10, on the diff; three Blockers and two Highs of its
findings were in this card, all fixed). B1: `remove()` followed a `run` link wherever it pointed, and `clean-tmp`
fed it any `/tmp/tb-pgtest-*`, so a planted link could delete any folder; now a link is only unlinked, and its
target deleted only when it is this module's own short socket folder (`tbpg-*`, ours, holding only sockets), and a
link left in a cluster is replaced, never followed or chowned. B2: `clean-tmp` stopped an idle server without an owner
(an older checkout's suite between two tests, a demo); now it never stops a running server, and removes only
stopped cluster folders that are ours, look like clusters and no process names. B3: `stop()` signalled the pid in
`postmaster.pid`, which after a reboot or a kill can be another process; now it signals only the postmaster whose
working directory is this data directory. H7: a detached HEAD gave every CI run and review worktree the same root
(`tb-tests-HEAD`), and a second run on a root destroyed the first one's files before the fixture noticed; the slug
is now `detached-<sha>` and `make test` holds `flock` on the root for the whole run (a second run stops at once), and
it stops the branch's shared cluster only when no client uses it. Also from the review: `TB_TEST_ROOT` resolves links
and refuses system directories, folders directly in them and any existing folder of other files (a `.tb-test-root`
marker that `make test` writes); `gc` keeps an unreadable owner file and anything that does not look like a cluster;
the session's `atexit` handler acts only in the process that registered it; a long socket path goes under the
scratch root before `/tmp`; complete-run tarballs are pruned by time; the rehearsal prunes only older copies of the
cases it knows. Not changed: `/tmp/pytest-of-*` of other projects owned by this user are cleaned (the card asks for
it); the `/tmp` defaults of the tools run by hand.

*Evidence.* `tests/unit/test_test_isolation.py`: the cluster under `TB_TEST_ROOT` and owned by the session; worker
folders that never share a prefix; the fallback under the scratch root, never `/tmp`; `/`, `/tmp`, `/var/tmp`,
`/var`, a relative path and "" refused; the plugin and retention settings; the lock pins; gc removes a dead owner's
cluster and keeps a live one and an unowned one; a reused pid is a dead owner; a real cluster of a dead owner is
stopped and deleted by `--gc`; a long root gets a short socket; `clean-tmp` keeps a locked pytest folder and the two
newest runs; no test names a fixed `/tmp/tb-*` path; and, after the review, a planted `run` link is never followed,
a stale pid file signals nobody, a running cluster without an owner is kept, an unreadable owner file is kept, a
folder of other files is no test root, a detached HEAD gets its own slug. Measured on this four-core machine
(acceptance numbers of the card): (1) two `make test` runs at once on two roots, 14 min 37 s and 14 min 28 s, 1,874
passed each (the one failure in each was the clean-tmp test seeing another agent's rehearsal, since fixed, and in one
the flaky test below), nothing new under `/tmp`, no server left; a third run on the first root stopped at once with
"in use by another run"; (2) `kill -9` of a running `make test`'s process group left four worker clusters and their
servers, and `python -m tools.pglocal --gc` removed all four and stopped every server (the branch's stopped shared
`pglocal/` folder stays for the next run); (3) `make check-disk` exits 1 here (5 to 13 GB free against 20); (4) after
`uv pip install pytest-randomly` into the venv `make venv-check` fails and `make venv` removes it; `pytest -p
randomly` fails with "Error importing plugin" without it, and the guard test fails a run in which it was re-enabled;
(5) `make clean-tmp DRY=1` here would free 7.0 to 8.6 GiB (the card's 12 GB was the morning's figure; the 11 GB
`/tmp/pytest-of-root` had been cleaned since, and a running 2.2 GB shared cluster is now kept on purpose); (6) `make
test` with `-n auto` took 9 min 48 s to 12 min 27 s (1,874 to 1,875 tests; 21 min of CPU), not the card's 8: the
parallelism is limited by per-worker session fixtures and a few long tests. `tests/unit/test_gpu_prep.py::
test_the_stub_profile_run_measures_and_extrapolates` is flaky under load (a rounded 0.0 s per patient against a
rounded 0.01 GPU-hour); it passes alone and is the test owner's to fix (this card may not touch test bodies).

*Not done.* The random-order nightly job itself (the sibling's). The per-feature registration files of review §5.2
(5). Moving `.cache/complete-run` out of the tree (§5.3 (2), with T-004). The tools' own `--dir` defaults (`/tmp/tb-*`
in `tools/*.py`) are unchanged: `make` passes folders under the root, and a hand run still uses them.
