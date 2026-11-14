# 13. Working in parallel on one machine (D-201)

**Reader:** the people who build TrialBox.

For developers and agent sessions that run the suite side by side on one machine; not for a box.

- **One temp root per branch.** `make` sets `TB_TEST_ROOT` to `$TB_SCRATCH/tb-tests-<branch>` (`TB_SCRATCH`: your
  scratchpad, default `/var/tmp/trialbox-<uid>`; a detached checkout is `detached-<sha>`) and exports it. Under it:
  pytest's `--basetemp` (`pytest/`), the test `TMPDIR` (`tmp/`, emptied after each run), one PostgreSQL cluster per
  xdist worker (`pg-gw0` ...), the shared cluster of `e2e_simple` and the drills (`pglocal/`), `e2e-simple/` and
  `backup-drill/`. `make test` marks the root (`.tb-test-root`) and holds `flock` on it for the whole run: a second
  run on the same root stops at once and touches nothing. `/`, a top-level directory, `/tmp`, `/var/tmp`, the home
  directory, a system directory or a folder directly in one, and an existing folder of other files (no marker) are
  refused as a root; links are resolved first. `make e2e-simple` marks the root too, so it passes on a fresh root;
  it names a missing CQL translator jar (`quick-*.jar`, FHIRHelpers) before it starts (`make jvm-deps`; exit 2).
- **Tools run by hand** (`tools.demo`, `tools.e2e_simple`, the drills, `public_e2e`, `complete_run`, `omop_parity`
  and the other demos) default to a folder under `$TB_SCRATCH` (`/var/tmp/trialbox-<uid>/tb-<tool>`), never a fixed
  `/tmp/tb-*` path; `--dir` or the tool's `TB_*_DIR` variable still wins.
- **One venv per branch, exactly the lock.** `make venv` runs `uv sync --frozen --group test --extra dev`: it
  installs `uv.lock` and removes anything installed by hand; the venv has no pip. `make test` first checks that the
  venv still matches the lock (`venv-check`). To change a dependency, edit `pyproject.toml`, run `uv lock`, commit
  both. The test plugins are pinned in `[dependency-groups] test` (pytest, pytest-timeout, pytest-cov,
  pytest-xdist); `addopts` blocks `randomly` and the cache provider, and a guard test fails a run in which
  `-p randomly` brought it back. Random order is a nightly job, not a default: `make test-random` (the nightly
  workflow's `random-order` run) lays `pytest-randomly` over the venv for that run only (`uv run --with`) and sets
  `TB_TEST_RANDOM=1`; the seed is in the header, and `make test-random RANDOM_SEED=<n>` repeats a failing order.
- **The suite in parallel.** `make test` runs `pytest -n auto` (`PYTEST_N=0` for serial, `PYTEST_N=4` to cap).
  pytest keeps one basetemp and, of it, only the failed tests' folders; a green run removes it.
- **Disk.** `make check-disk` first (fails under `TB_MIN_FREE_GB`, default 20 GB; reports the branch root against
  its 10 GB budget). `make clean-tmp` (`DRY=1` to list only) removes what earlier runs left and nobody uses now:
  `/tmp/pytest-of-*` run folders without a live `.lock`, stopped `/tmp/tb-pgtest-*` and `/tmp/tb-pglocal-*`
  clusters, `/tmp/tb-backup-drill*`, `/tmp/tb-drill`, `/tmp/tb-e2e-simple*`, the rehearsal's `runs/` (not while a
  rehearsal runs), and the `src.tgz`/`results.tgz` of every `.cache/complete-run` run but the two newest by time
  (reports stay). It never stops a running server, never follows a link, never touches another user's files or a
  folder a running process names (working directory, open file, command line, environment). The rehearsal keeps the
  newest two evidence folders per case.
- **After a crash.** `python -m tools.pglocal --gc` stops and removes every cluster whose `.owner` process is gone (a
  `kill -9`, a lost session); a cluster without an owner file, an unreadable owner file or a folder that is not a
  cluster is never touched by it. A server is signalled only when the pid file names the postmaster running in that
  data directory, so a stale pid file signals nobody.
- **As root** the throwaway server runs as `postgres`, which must reach the cluster: `pglocal` adds the search bit
  (`o+x`, never `o+r`) to a parent that lacks it and says so on stderr; a socket path too long for Unix (about 100
  characters) moves to a short private folder under the scratch root (under `/tmp` only when that root is long
  too) that `<cluster>/run` links to.
