"""Test isolation on one machine (D-201, T-003; RUNBOOK §12): every temp root under TB_TEST_ROOT, one cluster per
xdist worker with an owner file, orphans reaped by ``pglocal --gc``, the plugin set pinned, nothing in a fixed /tmp."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import pglocal

ROOT = Path(__file__).resolve().parents[2]


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_cluster_dir_is_under_the_test_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "tb-tests-x"
    monkeypatch.setenv("TB_TEST_ROOT", str(root))
    assert pglocal.cluster_dir("gw3") == root / "pg-gw3"
    assert pglocal.shared_dir() == root / "pglocal"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    assert pglocal.cluster_dir() == root / "pg-gw7"
    monkeypatch.delenv("PYTEST_XDIST_WORKER")
    assert pglocal.cluster_dir() == root / "pg-main"


def test_this_sessions_cluster_is_owned_and_under_the_test_root(pg_cluster_url: str) -> None:
    if os.environ.get("TB_TEST_DB_URL") or os.environ.get("TB_TEST_PG_DIR") or not os.environ.get("TB_TEST_ROOT"):
        pytest.skip("the session's database is given from outside (TB_TEST_DB_URL / TB_TEST_PG_DIR / no test root)")
    here = pglocal.cluster_dir()
    assert here.is_relative_to(Path(os.environ["TB_TEST_ROOT"]))
    assert (here / "data" / "PG_VERSION").exists()
    assert (here / ".owner").read_text().split()[0] == str(os.getpid())
    assert pglocal.owner_alive(here)


def test_two_workers_never_share_a_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TB_TEST_ROOT", str(tmp_path / "r"))
    dirs = [pglocal.cluster_dir(w) for w in ("gw0", "gw1", "gw10", "gw11", "main")]
    for a in dirs:
        for b in dirs:
            if a != b:
                assert not b.is_relative_to(a) and not str(b).startswith(str(a) + "/")
    # and the per-test schema prefix (conftest db_url) carries the worker process's pid
    assert len(set(dirs)) == len(dirs)


def test_without_a_test_root_the_fallback_is_the_scratch_root_never_tmp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_TEST_ROOT", raising=False)
    monkeypatch.delenv("TB_SCRATCH", raising=False)
    root = pglocal.test_root()
    assert root.is_relative_to(Path(f"/var/tmp/trialbox-{os.getuid()}"))
    assert not root.is_relative_to(Path("/tmp"))
    assert root.name.startswith("tb-tests-") and "/" not in root.name
    monkeypatch.setenv("TB_SCRATCH", "/srv/scratch/agent-1")
    assert pglocal.test_root().parent == Path("/srv/scratch/agent-1")


@pytest.mark.parametrize("bad", ["/", "/tmp", "/var/tmp", "/var", "relative/dir", ""])
def test_a_shared_or_root_test_root_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("TB_TEST_ROOT", bad)
    with pytest.raises(ValueError, match="refused"):
        pglocal.check_test_root(Path(bad))
    if bad:
        with pytest.raises(ValueError, match="refused"):
            pglocal.test_root()


def test_a_test_root_of_its_own_is_accepted() -> None:
    assert pglocal.check_test_root(Path("/var/tmp/trialbox-0/tb-tests-x/")) == Path("/var/tmp/trialbox-0/tb-tests-x")


def test_branch_slug_is_one_short_path_segment() -> None:
    slug = pglocal.branch_slug()
    assert slug and len(slug) <= 40 and re.fullmatch(r"[A-Za-z0-9._-]+", slug)


def test_random_order_and_the_shared_cache_are_off(pytestconfig: pytest.Config) -> None:
    """``-p randomly`` on the command line re-enables the plugin where it is installed; this test then fails the
    run. Only the nightly random-order job (review §5.2 (3), TB_TEST_RANDOM=1) may do that."""
    pm = pytestconfig.pluginmanager
    if os.environ.get("TB_TEST_RANDOM") == "1":
        pytest.skip("the nightly random-order run")
    assert pm.is_blocked("randomly") and not pm.has_plugin("randomly")
    assert pm.is_blocked("cacheprovider")
    assert pytestconfig.getini("tmp_path_retention_policy") == "failed"
    assert int(pytestconfig.getini("tmp_path_retention_count")) == 1


def test_the_plugin_set_is_pinned_in_the_lock() -> None:
    import tomllib

    group = tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"]["test"]
    names = {re.split(r"==", g)[0] for g in group}
    assert names == {"pytest", "pytest-timeout", "pytest-cov", "pytest-xdist"}
    assert all("==" in g for g in group)
    lock = (ROOT / "uv.lock").read_text()
    assert 'name = "pytest-randomly"' not in lock
    for g in group:
        name, version = g.split("==")
        assert f'name = "{name}"\nversion = "{version}"' in lock


def test_gc_reaps_dead_owners_only(tmp_path: Path) -> None:
    dead, alive, unowned = tmp_path / "a" / "pg-gw0", tmp_path / "b" / "pg-gw0", tmp_path / "c" / "pg-gw0"
    pglocal.claim(dead, _dead_pid())
    pglocal.claim(alive)
    unowned.mkdir(parents=True)
    (tmp_path / "a" / "pg-gw0" / "data").mkdir()
    assert pglocal.gc([tmp_path]) == [dead]
    assert not dead.exists() and alive.exists() and unowned.exists()


def test_a_reused_pid_is_a_dead_owner(tmp_path: Path) -> None:
    (tmp_path / ".owner").write_text(f"{os.getpid()} 1\n")  # our pid, but not our start time
    assert not pglocal.owner_alive(tmp_path)
    pglocal.claim(tmp_path)
    assert pglocal.owner_alive(tmp_path)


def test_stop_and_remove_are_idempotent(tmp_path: Path) -> None:
    pglocal.stop(tmp_path / "never-made")
    pglocal.remove(tmp_path / "never-made")
    (tmp_path / "empty" / "data").mkdir(parents=True)
    pglocal.stop(tmp_path / "empty")
    pglocal.remove(tmp_path / "empty")
    assert not (tmp_path / "empty").exists()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"


def test_gc_stops_and_removes_the_cluster_of_a_killed_run(tmp_path: Path) -> None:
    """Acceptance (2) of T-003 in small: a cluster whose owner was killed is stopped and deleted by --gc."""
    root = tmp_path / "tb-tests-killed" / "pg-gw0"
    pglocal.claim(root, _dead_pid())
    pglocal.ensure(root)
    server = int((root / "data" / "postmaster.pid").read_text().split()[0])
    assert pglocal.running(root) and _alive(server)
    r = subprocess.run([sys.executable, "-m", "tools.pglocal", "--gc", str(tmp_path)], cwd=ROOT,
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "removed" in r.stdout
    assert not root.exists() and not _alive(server)


def test_a_long_root_gets_a_short_socket(tmp_path: Path) -> None:
    root = tmp_path / ("x" * 60) / ("y" * 40) / "pg-gw0"
    pglocal.claim(root)
    try:
        url = pglocal.ensure(root)
        sock = (root / "run").resolve()
        assert (root / "run").is_symlink() and len(str(sock)) < 60
        assert f"host={sock}" in url and pglocal.running(root)
    finally:
        pglocal.remove(root)
    assert not root.exists() and not sock.exists()


def test_clean_tmp_keeps_what_is_in_use_and_the_two_newest_runs(tmp_path: Path) -> None:
    """Only under tmp_path: no gc of the machine's clusters, a rehearsal folder of the test's own."""
    tmp, repo = tmp_path / "tmp", tmp_path / "repo"
    old = tmp / "pytest-of-x" / "pytest-1"
    busy = tmp / "pytest-of-x" / "pytest-2"
    old.mkdir(parents=True)
    busy.mkdir(parents=True)
    (old / "f").write_bytes(b"0" * 4096)
    (busy / ".lock").write_text(str(os.getpid()))
    (tmp / "tb-e2e-simple").mkdir()
    (tmp / "tb-e2e-simple.json").write_text("{}")
    for run in ("20261101T000000Z-a", "20261102T000000Z-b", "20261103T000000Z-c"):
        shard = repo / ".cache" / "complete-run" / run / "shard-1"
        shard.mkdir(parents=True)
        (shard / "results.tgz").write_bytes(b"1")
        (shard.parent / "report").mkdir()
    (tmp / "reh" / "runs" / "run-a").mkdir(parents=True)
    done = {p for p, _ in pglocal.clean_tmp(repo, tmp=tmp, rehearsal=tmp / "reh", gc_first=False)}
    assert tmp / "reh" / "runs" in done and (tmp / "reh").exists()
    assert old in done and busy not in done and busy.exists()
    assert not (tmp / "tb-e2e-simple").exists() and not (tmp / "tb-e2e-simple.json").exists()
    runs = repo / ".cache" / "complete-run"
    assert not (runs / "20261101T000000Z-a" / "shard-1" / "results.tgz").exists()
    assert (runs / "20261102T000000Z-b" / "shard-1" / "results.tgz").exists()
    assert (runs / "20261103T000000Z-c" / "shard-1" / "results.tgz").exists()
    assert (runs / "20261101T000000Z-a" / "report").exists()


def test_no_test_names_a_fixed_tmp_path() -> None:
    """Review §5.2 (1): no fixed /tmp/tb-* path in the suite; temp files come from tmp_path or TMPDIR."""
    bad = []
    for path in (ROOT / "tests").rglob("*.py"):
        if "rehearsal" in path.parts or path.name == Path(__file__).name:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""["']/tmp/tb[-_]""", line):
                bad.append(f"{path.relative_to(ROOT)}:{n}")
    assert not bad, bad
