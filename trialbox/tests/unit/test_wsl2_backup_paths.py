"""NEW-WIN-7 (D-608): backup paths on a Windows workstation.

Under WSL2 a backup must leave WSL2's virtual disk and the workstation's own drives: the hospital's share, or an
outside drive. Here: how a target is classified from a written ``/proc/mounts``, the record the Windows installer
leaves, the speed measurement on a temporary folder, and ``trialbox doctor``'s ``backup_speed``. The mount lines
are written as WSL2 is documented to print them; no Windows machine ran (P-0 lines 63 to 70)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools.trialbox import backup_schedule as bs
from tools.trialbox.doctor import DoctorInputs, check_backup_speed

ROOT = Path(__file__).resolve().parents[2]
SETUP = str(ROOT / "deploy/windows/wsl-setup.sh")
WSL2 = "6.6.87.2-microsoft-standard-WSL2"
# WSL2's own disk, the system drive, the data drive (it holds the virtual disk), an outside drive in both forms
# WSL2 writes a drive, and the hospital's share in both forms
MOUNTS = """\
/dev/sdc / ext4 rw,relatime 0 0
C:\\134 /mnt/c 9p rw,noatime,dirsync,aname=drvfs;path=C:\\134;uid=0;gid=0;symlinkroot=/mnt/ 0 0
D:\\134 /mnt/d 9p rw,noatime,dirsync,aname=drvfs;path=D:\\134;uid=0;gid=0 0 0
E:\\134 /mnt/e 9p rw,noatime,dirsync,aname=drvfs;path=E:\\134;uid=0;gid=0 0 0
drvfs /mnt/f 9p rw,noatime,aname=drvfs;path=F:\\134;uid=0;gid=0 0 0
\\134\\134nas\\134backup /mnt/share 9p rw,noatime,aname=drvfs;path=\\134\\134nas\\134backup 0 0
drvfs /mnt/share2 9p rw,noatime,aname=drvfs;path=\\134\\134nas\\134backup;uid=0 0 0
"""
OWN = frozenset({"C", "D"})


def _kind(path: str, own: frozenset[str] | None = OWN) -> tuple[str, bool]:
    t = bs.target_kind(Path(path), MOUNTS, (), Path("/nonexistent"), windows_own=own)
    return t.kind, t.offbox


def test_only_a_drive_that_is_not_the_pcs_own_or_a_share_counts_as_off_box() -> None:
    assert _kind("/mnt/e/trialbox") == ("Windows drive E:, not one of this PC's own", True)
    assert _kind("/mnt/f/trialbox") == (
        "Windows drive F:, not one of this PC's own",
        True,
    )  # the letter from the options
    assert _kind("/mnt/share/tb") == ("network share", True)
    assert _kind("/mnt/share2/tb") == ("network share", True)  # the share named only in the options
    assert _kind("/mnt/c/backups") == ("this box", False)  # the system drive
    assert _kind("/mnt/d/backups") == ("this box", False)  # the drive that holds WSL2's virtual disk
    assert _kind("/opt/trialbox/deploy/backups") == ("this box", False)  # inside the virtual disk


def test_without_the_installers_record_no_windows_drive_counts_as_off_box() -> None:
    for path in ("/mnt/c/b", "/mnt/d/b", "/mnt/e/b", "/mnt/f/b"):
        assert _kind(path, own=None) == ("this box", False), path
    assert _kind("/mnt/share/tb", own=None) == ("network share", True)  # a share needs no record


def test_a_linux_mount_is_never_taken_for_a_windows_drive() -> None:
    mounts = "/dev/sdc / ext4 rw 0 0\nE: /mnt/e ext4 rw 0 0\n/dev/sdd1 /mnt/x ext4 rw,path=E:\\134 0 0\n"
    for path in ("/mnt/e/b", "/mnt/x/b"):
        t = bs.target_kind(Path(path), mounts, (), Path("/nonexistent"), windows_own=OWN)
        assert (t.kind, t.offbox) == ("this box", False), path


@pytest.mark.parametrize(("text", "want"), [("C,D\n", {"C", "D"}), ("c, d ,e", {"C", "D", "E"}), ("C", {"C"})])
def test_the_record_of_the_pcs_own_drives_is_read(tmp_path: Path, text: str, want: set[str]) -> None:
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/windows-drives").write_text(text)
    assert bs.windows_own_drives(tmp_path) == frozenset(want)


@pytest.mark.parametrize("text", ["", "CD", "C,,D", "C;D", "1", "C,D\nE"])
def test_a_record_that_is_not_drive_letters_is_no_record(tmp_path: Path, text: str) -> None:
    assert bs.windows_own_drives(tmp_path) is None  # no file
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/windows-drives").write_text(text)
    assert bs.windows_own_drives(tmp_path) is None


def test_the_boxs_configuration_classifies_with_the_record(tmp_path: Path) -> None:
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/windows-drives").write_text("C,D\n")
    cfg = bs.config(tmp_path, {"TB_BACKUP_TARGETS": "/mnt/e/trialbox", "TB_ENV": "PRODUCTION"}, process_env=False)
    assert bs.windows_own_drives(cfg.deploy) == OWN  # what classify() hands to target_kind


# ------------------------------------------------------------------------------------- the two steps inside WSL2


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TB_WSL_ROOT": str(root), "TB_WSL_NO_ROOT": "1"}
    return subprocess.run(["bash", SETUP, *args], env=env, capture_output=True, text=True, check=False, timeout=120)


def test_the_installer_records_the_pcs_own_drives_and_nothing_else(tmp_path: Path) -> None:
    root = tmp_path / "opt"
    assert _run(root, "windows-drives", "C,D").returncode == 0
    assert (root / "deploy/site/box/windows-drives").read_text() == "C,D\n"
    assert bs.windows_own_drives(root / "deploy") == OWN
    for bad in ("", "c,d", "C,D,", "CD", "C,D\nE", "C;rm -rf /"):
        r = _run(root, "windows-drives", bad)
        assert r.returncode == 1 and "want drive letters" in r.stderr, bad
    assert (root / "deploy/site/box/windows-drives").read_text() == "C,D\n"


def test_the_speed_of_a_path_is_measured_recorded_and_the_test_file_removed(tmp_path: Path) -> None:
    root, target = tmp_path / "opt", tmp_path / "target folder"
    target.mkdir()
    r = _run(root, "backup-speed", str(target), "2")
    assert r.returncode == 0 and "mbps=" in r.stdout and "written_mib=2" in r.stdout, r.stderr
    assert list(target.iterdir()) == []  # nothing is left on the target
    speeds = bs.measured_speeds(root / "deploy")
    assert list(speeds) == [str(target.resolve())] and speeds[str(target.resolve())] > 0
    # a second measurement of the same path is the one that counts
    with (root / "deploy/site/box/backup-speed").open("a") as fh:
        fh.write(f"3.5\t{target.resolve()}\n")
    assert bs.measured_speeds(root / "deploy")[str(target.resolve())] == 3.5


@pytest.mark.parametrize(("args", "says"), [
    (["/nonexistent/x", "2"], "no such folder"),
    (["TARGET", ""], "want the MiB to write"),
    (["TARGET", "0"], "want the MiB to write"),
    (["TARGET", "2; id"], "want the MiB to write"),
])  # fmt: skip
def test_a_measurement_that_cannot_be_made_is_refused_and_records_nothing(
    tmp_path: Path, args: list[str], says: str
) -> None:
    root, target = tmp_path / "opt", tmp_path / "t"
    target.mkdir()
    r = _run(root, "backup-speed", *[str(target) if a == "TARGET" else a for a in args])
    assert r.returncode == 1 and says in r.stderr
    assert not (root / "deploy/site/box/backup-speed").exists() and list(target.iterdir()) == []


@pytest.mark.parametrize(
    "text", ["fast\t/mnt/e\n", "-1\t/mnt/e\n", "nan\t/mnt/e\n", "5\n", "\t/mnt/e\n", "inf\t/mnt/e\n"]
)
def test_a_line_that_is_not_a_measurement_is_not_read_as_one(tmp_path: Path, text: str) -> None:
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/backup-speed").write_text(text)
    assert bs.measured_speeds(tmp_path) == {}


# ------------------------------------------------------------------------------------- doctor: backup_speed


def _inp(tmp: Path, *, kernel: str = WSL2, mbps: str | None = None, measured: float | None = None) -> DoctorInputs:
    proc, deploy, target = tmp / "proc", tmp / "deploy", tmp / "target"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    (deploy / "site/box").mkdir(parents=True)
    target.mkdir()
    if measured is not None:
        (deploy / "site/box/backup-speed").write_text(f"{measured}\t{target.resolve()}\n")
    env = {"TB_BACKUP_TARGETS": str(target), "TB_ENV": "PRODUCTION"}
    if mbps is not None:
        env["TB_BACKUP_MIN_MBPS"] = mbps
    return DoctorInputs(env=env, deploy=deploy, proc=proc)


def test_a_plain_linux_host_is_not_judged(tmp_path: Path) -> None:
    c = check_backup_speed(_inp(tmp_path, kernel="6.8.0-48-generic"))
    assert c.status == "PASS" and "not WSL2" in c.detail


def test_a_path_that_was_never_measured_is_a_warning_with_the_command(tmp_path: Path) -> None:
    c = check_backup_speed(_inp(tmp_path))
    assert c.status == "WARN" and "not measured (wsl-setup.sh backup-speed" in c.detail


def test_a_limit_above_the_paths_speed_fails_and_names_the_setting_to_use(tmp_path: Path) -> None:
    # the declared 5 MB/s assumes a box disk; this path writes 3 MB/s: every large step would be cut as hung
    c = check_backup_speed(_inp(tmp_path, measured=3.0))
    assert (
        c.status == "FAIL"
        and "measured 3 MB/s, and TB_BACKUP_MIN_MBPS is 5" in c.detail
        and "Set it to 0.3" in c.detail
    )


def test_a_limit_above_a_tenth_of_the_speed_is_a_warning_and_a_tenth_or_less_passes(tmp_path: Path) -> None:
    c = check_backup_speed(_inp(tmp_path, measured=20.0))
    assert c.status == "WARN" and "more than a tenth" in c.detail and "Set it to 2" in c.detail
    c = check_backup_speed(_inp(tmp_path / "b", measured=20.0, mbps="2"))
    assert c.status == "PASS" and "20 MB/s" in c.detail
    c = check_backup_speed(_inp(tmp_path / "c", measured=80.0))
    assert c.status == "PASS"


def test_no_target_is_said(tmp_path: Path) -> None:
    inp = _inp(tmp_path)
    inp = DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=inp.deploy, proc=inp.proc)
    c = check_backup_speed(inp)
    assert c.status == "WARN" and "no backup target" in c.detail
