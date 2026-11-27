"""P2-11 (ASSESS-1-ADDENDUM D7): the site declares its concurrent users at install, the console is sized from them.

The audit's load run found no declared number of concurrent users and one console process (25 users: p95 2.76 s,
the process at 120-135 % CPU). Here: ``TB_SITE_USERS`` is declared beside ``TB_SITE_PATIENTS`` (25 by default) and the
installer writes it with ``TB_CONSOLE_WORKERS`` sized from it; compose starts that many uvicorn workers; the service
level (p95 under 1 s on the common pages at the declared users) has its measuring function. Several workers must not
change what a person sees: the timers run in one process only (a notice goes once), and what one request leaves for
the next (the one-time password, a pilot proposal) is seen by every process.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest
from console import timers
from console.held import Held
from console.proposals import Proposal
from tb_common.config import DECLARED

from tests.unit.test_compose_limits import BASE, DEPLOY, _merge
from tools import console_timing
from tools.trialbox import console_size

ROOT = DEPLOY.parent


def test_the_concurrent_users_are_declared_with_the_patient_count() -> None:
    assert DECLARED["TB_SITE_USERS"].default == "25" and DECLARED["TB_SITE_USERS"].kind == "int"
    assert "TB_CONSOLE_WORKERS" in DECLARED
    assert console_size.DEFAULT_USERS == 25 and console_size.SLO_P95_S == 1.0
    runbook = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8")
    assert "`TB_SITE_USERS`" in runbook and "within 1 s at the 95th percentile" in runbook


@pytest.mark.parametrize(
    ("users", "cpus", "want"), [(25, 16, 3), (1, 16, 1), (10, 16, 1), (11, 16, 2), (25, 2, 2), (100, 16, 4)]
)
def test_workers_from_the_users(users: int, cpus: int, want: int) -> None:
    assert console_size.workers(users, cpus) == want


def test_install_writes_the_default_then_follows_a_declared_number(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_ENV=DEV\nTB_SITE_PATIENTS=50000\n", encoding="utf-8")
    assert console_size.main(["--env-file", str(env), "--write", "--cpus", "16"]) == 0
    text = env.read_text(encoding="utf-8")
    assert "TB_SITE_USERS=25\n" in text and "TB_CONSOLE_WORKERS=3\n" in text and "TB_SITE_PATIENTS=50000" in text
    assert env.stat().st_mode & 0o777 == 0o600
    env.write_text(text.replace("TB_SITE_USERS=25", "TB_SITE_USERS=40"), encoding="utf-8")
    console_size.main(["--env-file", str(env), "--write", "--cpus", "16"])
    assert "TB_CONSOLE_WORKERS=4\n" in env.read_text(encoding="utf-8")


def test_a_worker_count_set_by_hand_is_kept_and_a_bad_number_refused(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TB_SITE_USERS=60\nTB_CONSOLE_WORKERS=2\n", encoding="utf-8")
    console_size.main(["--env-file", str(env), "--write", "--cpus", "16"])
    assert "TB_CONSOLE_WORKERS=2\n" in env.read_text(encoding="utf-8")
    env.write_text("TB_SITE_USERS=many\n", encoding="utf-8")
    with pytest.raises(ValueError, match="TB_SITE_USERS"):
        console_size.main(["--env-file", str(env)])
    for bad in ("0", "-1", "two"):
        env.write_text(f"TB_CONSOLE_WORKERS={bad}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="TB_CONSOLE_WORKERS"):
            console_size.main(["--env-file", str(env), "--write"])


def test_compose_starts_the_sized_workers_and_install_sizes_them() -> None:
    console = _merge((BASE,))["console"]
    cmd = [str(x) for x in console["command"]]
    assert cmd[cmd.index("--workers") + 1] == "${TB_CONSOLE_WORKERS:-1}"
    # what console.held keeps is in memory: the container's /tmp is a tmpfs under a read-only root
    assert console["read_only"] is True and "/tmp" in [str(x).split(":")[0] for x in console["tmpfs"]]
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "python3 -m tools.trialbox.console_size --env-file deploy/.env --write" in install
    assert install.index("tools.trialbox.console_size") < install.index("tools.trialbox.pgsize")  # before the start


def test_the_timers_run_in_one_worker_process(tmp_path: Path) -> None:
    lock = tmp_path / "timers.lock"
    assert timers.owns(lock)
    other = subprocess.run(
        [sys.executable, "-c", "import sys; from console import timers; print(timers.owns(__import__('pathlib').Path(sys.argv[1])))",
         str(lock)],
        capture_output=True, text=True, check=True, env={"PYTHONPATH": ":".join(sys.path)},
    )  # fmt: skip
    assert other.stdout.strip() == "False"  # another process: the timers are this one's
    assert timers.start(None, {"TB_CONSOLE_TIMERS": "on"}, "UTC", lock=lock) is None  # a second start here neither


def test_what_one_request_leaves_is_seen_by_another_process_once(tmp_path: Path) -> None:
    mine, other = Held("t", 60.0, tmp_path), Held("t", 60.0, tmp_path)  # two processes' views of the same tmpfs
    mine.put("session-sha", ("alice", "pw", 1.0))
    assert other.get("session-sha") == ["alice", "pw", 1.0]  # JSON: a tuple comes back as a list
    assert other.pop("session-sha") == ["alice", "pw", 1.0]
    assert mine.pop("session-sha") is None  # taken once
    assert (mine.folder.stat().st_mode & 0o777) == 0o700
    stale = Held("s", 0.05, tmp_path)
    stale.put("k", 1)
    time.sleep(0.1)
    assert stale.get("k") is None and not list(stale.folder.iterdir())  # never returned, and removed
    # a pilot proposal travels as its fields and comes back equal (app.py: asdict, then Proposal(**...))
    prop = Proposal(line="screen S-1", source="grammar", intent="screen", notes=("a", "b"))
    mine.put("pid", {"proposal": asdict(prop), "session_sha": "s", "created": 1.0})
    raw = other.pop("pid")
    assert Proposal(**{**raw["proposal"], "notes": tuple(raw["proposal"]["notes"])}) == prop


def test_a_folder_made_by_someone_else_is_not_used(tmp_path: Path) -> None:
    folder = Held("x", 60.0, tmp_path).folder
    folder.chmod(0o755)
    with pytest.raises(PermissionError):
        Held("x", 60.0, tmp_path)


def test_the_service_level_is_measured_with_the_users_at_once() -> None:
    def fast(_path: str) -> tuple[int, dict[str, str]]:
        time.sleep(0.002)
        return 200, {}

    p95, bad = console_timing.under_load(fast, ["/home", "/studies"], users=25, rounds=2)
    assert bad == 0 and p95 < console_size.SLO_P95_S
    p95, bad = console_timing.under_load(lambda _p: (503, {}), ["/about"], users=3, rounds=1)
    assert bad == 3

    def one_slow(path: str) -> tuple[int, dict[str, str]]:
        time.sleep(0.05 if path == "/slow" else 0.0)
        return 200, {}

    fast_paths = [f"/p{i}" for i in range(30)]
    p95, _bad = console_timing.under_load(one_slow, [*fast_paths, "/slow"], users=2, rounds=2)
    assert p95 >= 0.05  # the slow page is not hidden among thirty fast ones
