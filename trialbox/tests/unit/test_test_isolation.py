"""Test isolation on one machine (D-201, T-003; RUNBOOK §13): every temp root under TB_TEST_ROOT, one cluster per
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
    assert slug and len(slug) <= pglocal.SLUG_MAX and re.fullmatch(r"[A-Za-z0-9._-]+", slug)


def test_the_slug_has_one_limit_and_a_long_branch_name_keeps_its_own_root() -> None:
    """D-572: the tool cut at 60 and this file asserted 40, so the cross-card list failed on a developer's machine
    for a branch name of 41 to 60 characters. One constant; a longer name keeps its start and a hash of the whole,
    so two branches with the same first 40 characters do not share a test root."""
    assert pglocal.SLUG_MAX == 40
    assert pglocal.slug_of("agent/T-003-x") == "agent-T-003-x"  # as before
    exact = "agent/" + "x" * 34
    assert len(exact) == 40 and pglocal.slug_of(exact) == "agent-" + "x" * 34  # at the limit: unchanged
    a = pglocal.slug_of("agent/OPS-004-real-installer-rehearsal-and-the-nightly-job-a")
    b = pglocal.slug_of("agent/OPS-004-real-installer-rehearsal-and-the-nightly-job-b")
    for slug in (a, b):
        assert len(slug) <= pglocal.SLUG_MAX and re.fullmatch(r"[A-Za-z0-9._-]+", slug)
        assert slug.startswith("agent-OPS-004-real-installer-r")
    assert a != b and pglocal.slug_of("agent/OPS-004-real-installer-rehearsal-and-the-nightly-job-a") == a
    assert pglocal.slug_of("") == "detached" and pglocal.slug_of("///") == "detached"
    # a socket path under the default scratch folder stays inside the kernel's limit with the longest slug
    path = f"/var/tmp/trialbox-65534/tb-tests-{'s' * pglocal.SLUG_MAX}/pg-gw99/run/.s.PGSQL.5432"
    assert len(path) <= pglocal.SOCK_MAX < len(path.replace("s" * pglocal.SLUG_MAX, "s" * 60))  # 60 did not fit
    text = Path(pglocal.__file__).read_text(encoding="utf-8")
    assert "[:60]" not in text and "[:40]" not in text  # the number lives in the constant


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
    assert names == {"pytest", "pytest-timeout", "pytest-cov", "pytest-xdist", "hypothesis"}
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
    for age, run in enumerate(("20261101T000000Z-a", "20261102T000000Z-b", "20261103T000000Z-c")):
        shard = repo / ".cache" / "complete-run" / run / "shard-1"
        shard.mkdir(parents=True)
        (shard / "results.tgz").write_bytes(b"1")
        (shard.parent / "report").mkdir()
        os.utime(shard.parent, (1_700_000_000 + age * 3600, 1_700_000_000 + age * 3600))  # newest by time
    (tmp / "reh" / "runs" / "run-a").mkdir(parents=True)
    done = {p for p, _ in pglocal.clean_tmp(repo, tmp=tmp, rehearsal=tmp / "reh", gc_first=False, rehearsing=False)}
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


# ------------------------------------------------------------------ the review's Blockers and Highs (D-201)
def test_remove_never_follows_a_run_link_out_of_the_cluster(tmp_path: Path) -> None:
    """B1: a ``run`` link to anything that is not this module's short socket folder is unlinked, never deleted."""
    victim = tmp_path / "victim"
    (victim / "keep").mkdir(parents=True)
    cluster = tmp_path / "tmp" / "tb-pgtest-planted"
    (cluster / "data").mkdir(parents=True)
    (cluster / "data" / "PG_VERSION").write_text("16\n")
    (cluster / "run").symlink_to(victim, target_is_directory=True)
    pglocal.remove(cluster)
    assert (victim / "keep").is_dir() and not cluster.exists()
    cluster2 = tmp_path / "tmp" / "tb-pgtest-planted2"
    (cluster2 / "data").mkdir(parents=True)
    (cluster2 / "run").symlink_to(victim, target_is_directory=True)
    pglocal.clean_tmp(tmp_path / "repo", tmp=tmp_path / "tmp", rehearsal=tmp_path / "reh", gc_first=False)
    assert (victim / "keep").is_dir()


def test_a_stale_pid_file_signals_nobody(tmp_path: Path) -> None:
    """B3: ``postmaster.pid`` naming a live process that is not this data directory's postmaster is left alone."""
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / "pg-x" / "data").mkdir(parents=True)
        (tmp_path / "pg-x" / "data" / "postmaster.pid").write_text(f"{sleeper.pid}\n/elsewhere\n")
        pglocal.stop(tmp_path / "pg-x")
        assert sleeper.poll() is None  # still running: not ours, not signalled
    finally:
        sleeper.kill()
        sleeper.wait()


def test_clean_tmp_keeps_a_running_cluster_without_an_owner(tmp_path: Path) -> None:
    """B2: an idle server from an older checkout (no ``.owner``) is never stopped by clean-tmp."""
    root = tmp_path / "tmp" / "tb-pgtest-legacy"
    pglocal.ensure(root)
    try:
        done = {p for p, _ in pglocal.clean_tmp(tmp_path / "repo", tmp=tmp_path / "tmp", gc_first=False)}
        assert root not in done and pglocal.running(root)
    finally:
        pglocal.remove(root)
    stopped = tmp_path / "tmp" / "tb-pgtest-stopped"
    (stopped / "data").mkdir(parents=True)
    (stopped / "data" / "PG_VERSION").write_text("16\n")
    done = {p for p, _ in pglocal.clean_tmp(tmp_path / "repo", tmp=tmp_path / "tmp", gc_first=False)}
    assert stopped in done and not stopped.exists()


def test_gc_keeps_what_does_not_look_like_a_cluster(tmp_path: Path) -> None:
    """M3: an unreadable ``.owner`` is kept; a folder of other files with a dead owner is not a cluster."""
    garbled = tmp_path / "a" / "pg-gw0"
    garbled.mkdir(parents=True)
    (garbled / ".owner").write_text("not a pid\n")
    other = tmp_path / "b" / "notes"
    other.mkdir(parents=True)
    pglocal.claim(other, _dead_pid())
    (other / "thesis.md").write_text("keep me")
    pglocal.claim(tmp_path, _dead_pid())  # an owner file in the base itself is never a target
    assert pglocal.gc([tmp_path]) == []
    assert garbled.exists() and (other / "thesis.md").exists()


def test_an_existing_folder_of_other_files_is_no_test_root(tmp_path: Path) -> None:
    """M1: a non-empty folder without the marker, a system directory and one directly inside it are refused."""
    (tmp_path / "work" / "src").mkdir(parents=True)
    with pytest.raises(ValueError, match="marker"):
        pglocal.check_test_root(tmp_path / "work")
    for bad in ("/usr/local", "/etc/ssl", "/var/lib/postgresql", "/home/someone"):
        with pytest.raises(ValueError, match="refused"):
            pglocal.check_test_root(Path(bad))
    fresh = pglocal.mark_test_root(tmp_path / "tb-tests-y")
    (fresh / "pytest").mkdir()
    assert pglocal.check_test_root(fresh) == fresh.resolve()


def test_a_detached_head_gets_its_own_slug(tmp_path: Path) -> None:
    """H7: a detached checkout is ``detached-<sha>``, not ``HEAD`` shared by every CI run and review worktree."""
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit",
                    "-q", "--allow-empty", "-m", "x"], check=True)  # fmt: skip
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", sha.strip()], check=True)
    slug = pglocal.branch_slug(repo)
    assert slug.startswith("detached-") and slug != "detached-" and "HEAD" not in slug


def test_a_long_socket_folder_stays_out_of_tmp_when_the_scratch_root_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8: the short socket folder goes under a short scratch root, not /tmp."""
    monkeypatch.setenv("TB_SCRATCH", "/var/tmp/trialbox-sock-test")
    assert pglocal._short_socket_parent() == Path("/var/tmp/trialbox-sock-test")
    monkeypatch.setenv("TB_SCRATCH", "/var/tmp/" + "s" * 90)
    assert pglocal._short_socket_parent() == Path("/tmp")
