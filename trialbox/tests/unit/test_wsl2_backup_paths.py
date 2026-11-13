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
OWN = frozenset({"C", "D"})


def _mounts(tmp: Path) -> str:
    """WSL2's own disk, the system drive, the data drive (it holds the virtual disk), outside drives in both forms
    WSL2 writes a drive, and the hospital's share in both forms. The mount points are folders under ``tmp``."""
    for name in ("c", "d", "e", "f", "g", "share", "share2"):
        (tmp / name).mkdir(parents=True, exist_ok=True)
    return (
        "/dev/sdc / ext4 rw,relatime 0 0\n"
        f"C:\\134 {tmp}/c 9p rw,noatime,dirsync,aname=drvfs;path=C:\\134;uid=0;gid=0;symlinkroot=/mnt/ 0 0\n"
        f"D:\\134 {tmp}/d 9p rw,noatime,dirsync,aname=drvfs;path=D:\\134;uid=0;gid=0 0 0\n"
        f"E:\\134 {tmp}/e 9p rw,noatime,dirsync,aname=drvfs;path=E:\\134;uid=0;gid=0 0 0\n"
        f"drvfs {tmp}/f 9p rw,noatime,aname=drvfs;path=F:\\134;uid=0;gid=0 0 0\n"
        f"G:\\134 {tmp}/g 9p rw,noatime,aname=drvfs;path=G:\\134;uid=0;gid=0 0 0\n"
        f"\\134\\134nas\\134backup {tmp}/share 9p rw,noatime,aname=drvfs;path=\\134\\134nas\\134backup 0 0\n"
        f"drvfs {tmp}/share2 9p rw,noatime,aname=drvfs;path=\\134\\134nas\\134backup;uid=0 0 0\n"
    )


def _kind(tmp: Path, path: str, own: frozenset[str] | None = OWN, mounts: str | None = None) -> tuple[str, bool]:
    t = bs.target_kind(tmp / path, mounts or _mounts(tmp), (), Path("/nonexistent"), windows_own=own)
    return t.kind, t.offbox


def _mark(tmp: Path, *names: str) -> None:
    _mounts(tmp)
    for name in names:
        (tmp / name / bs.OUTSIDE_MARK).write_text("TrialBox: an outside drive for backups.\n")


def test_a_windows_drive_counts_only_when_it_is_not_the_pcs_own_and_carries_the_installers_mark(tmp_path: Path) -> None:
    _mark(tmp_path, "e", "f")
    assert _kind(tmp_path, "e/trialbox") == ("Windows drive E:, an outside drive", True)
    assert _kind(tmp_path, "f/trialbox") == ("Windows drive F:, an outside drive", True)  # the letter from the options
    # a drive that is not the PC's own by the record, but that the installer never saw on USB: not counted.
    # This is the letter an internal volume gets after the install, or `subst G: D:\\backup`
    assert _kind(tmp_path, "g/trialbox") == (
        "Windows drive G:, not marked as an outside drive (box-install.ps1 -BackupDrive G:)", False)  # fmt: skip
    assert _kind(tmp_path, "share/tb") == ("network share", True)
    assert _kind(tmp_path, "share2/tb") == ("network share", True)  # the share named only in the options
    assert _kind(tmp_path, "c/backups") == ("this box", False)  # the system drive
    assert _kind(tmp_path, "d/backups") == ("this box", False)  # the drive that holds WSL2's virtual disk
    assert bs.target_kind(Path("/opt/trialbox/deploy/backups"), _mounts(tmp_path), (), windows_own=OWN).offbox is False


def test_a_mark_on_one_of_the_pcs_own_drives_changes_nothing(tmp_path: Path) -> None:
    _mark(tmp_path, "c", "d")  # copied there by hand, or the outside disk became the data drive
    assert _kind(tmp_path, "c/backups") == ("this box", False)
    assert _kind(tmp_path, "d/backups") == ("this box", False)


def test_without_the_installers_record_no_windows_drive_counts_as_off_box(tmp_path: Path) -> None:
    _mark(tmp_path, "e", "f")
    for path in ("c/b", "d/b", "e/b", "f/b", "g/b"):
        assert _kind(tmp_path, path, own=None) == ("this box", False), path
    assert _kind(tmp_path, "share/tb", own=None) == ("network share", True)  # a share needs no record


def test_a_record_that_lists_too_few_drives_does_not_make_the_data_drive_off_box(tmp_path: Path) -> None:
    _mounts(tmp_path)
    kind, offbox = _kind(tmp_path, "d/backups", own=frozenset({"C"}))
    assert offbox is False and "not marked as an outside drive" in kind


@pytest.mark.parametrize(
    "line",
    [
        "E: {m} ext4 rw 0 0",  # a Linux file system named like a drive
        "/dev/sdd1 {m} ext4 rw,aname=drvfs;path=E:\\134 0 0",
        "none {m} 9p rw,trans=virtio,path=E: 0 0",  # a 9p mount that is not drvfs
        "E:\\134 {m} 9p rw,aname=drvfs;path=D:\\134 0 0",  # the source and the options name two drives
        "D:\\134backup {m} 9p rw,aname=drvfs;path=D:\\134backup 0 0",  # a folder of a drive, not a drive
    ],
)
def test_a_mount_line_that_is_not_plainly_one_windows_drive_is_this_box(tmp_path: Path, line: str) -> None:
    m = tmp_path / "x"
    m.mkdir()
    (m / bs.OUTSIDE_MARK).write_text("x")
    mounts = "/dev/sdc / ext4 rw 0 0\n" + line.format(m=m) + "\n"
    assert _kind(tmp_path, "x/b", mounts=mounts) == ("this box", False)


@pytest.mark.parametrize(
    "line",
    [
        "\\134\\134localhost\\134D$ {m} 9p rw,aname=drvfs;path=\\134\\134localhost\\134D$ 0 0",
        "drvfs {m} 9p rw,aname=drvfs;path=\\134\\134wsl.localhost\\134TrialBox\\134opt 0 0",
        "//127.0.0.1/share {m} 9p rw 0 0",
        "\\134\\134WSL$\\134TrialBox {m} 9p rw 0 0",
    ],
)
def test_a_share_of_the_pc_itself_is_this_box(tmp_path: Path, line: str) -> None:
    m = tmp_path / "x"
    m.mkdir()
    mounts = "/dev/sdc / ext4 rw 0 0\n" + line.format(m=m) + "\n"
    assert _kind(tmp_path, "x/b", mounts=mounts) == ("this box", False)


def test_a_share_named_in_the_options_of_a_linux_mount_is_not_a_share(tmp_path: Path) -> None:
    m = tmp_path / "x"
    m.mkdir()
    mounts = f"/dev/sdc / ext4 rw 0 0\n/dev/sdd1 {m} ext4 rw,path=//nas/x 0 0\n"
    assert _kind(tmp_path, "x/b", mounts=mounts) == ("this box", False)


def test_a_declared_target_on_a_windows_drive_is_not_off_box_for_being_another_device(tmp_path: Path) -> None:
    # D-274 takes a declared path on another device than "/" as off-box. Under WSL2 every Windows drive is another
    # device, the data drive too: the declaration alone is not enough there
    mounts = _mounts(tmp_path)
    d = tmp_path / "d" / "backups"
    d.mkdir()
    t = bs.target_kind(d, mounts, [str(d)], Path("/nonexistent"), local=(Path("/nonexistent-root"),), windows_own=OWN)
    assert (t.kind, t.offbox) == ("declared, but on this box's disk (no .trialbox-offbox file)", False)
    (d / bs.OFFBOX_MARKER).write_text("")  # the site's own, deliberate statement still stands (D-274)
    assert bs.target_kind(d, mounts, [str(d)], Path("/nonexistent"), windows_own=OWN).offbox


def test_the_boxs_own_check_reads_the_record_and_the_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The record reaches the check: the box's configuration classifies with it, and ``status`` counts the target."""
    deploy, mnt = tmp_path / "deploy", tmp_path / "mnt"
    (deploy / "site/box").mkdir(parents=True)
    text = _mounts(mnt)
    lines = [tuple(bs._unescape(f) for f in ln.split()[:4]) for ln in text.splitlines()]
    monkeypatch.setattr(bs, "_mounts", lambda _text=None: lines)
    env = {"TB_BACKUP_TARGETS": str(mnt / "e" / "trialbox"), "TB_ENV": "PRODUCTION"}
    cfg = bs.config(deploy, env, process_env=False)
    assert cfg.classify(cfg.targets[0]).offbox is False  # no record yet
    assert "no off-box backup target: every target is on this box" in bs.status(cfg)["problems"]
    (deploy / "site/box/windows-drives").write_text("C,D\n")
    assert cfg.classify(cfg.targets[0]).offbox is False  # a record, no mark on the drive
    (mnt / "e" / bs.OUTSIDE_MARK).write_text("x")
    assert cfg.classify(cfg.targets[0]).kind == "Windows drive E:, an outside drive"
    assert "no off-box backup target: every target is on this box" not in bs.status(cfg)["problems"]
    (deploy / "site/box/windows-drives").write_text("C,D,E\n")  # the installer now lists E: as the PC's own
    assert cfg.classify(cfg.targets[0]).offbox is False


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


def test_a_record_that_is_not_text_is_no_record_and_does_not_break_the_check(tmp_path: Path) -> None:
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/windows-drives").write_bytes("C,D".encode("utf-16"))
    (tmp_path / "site/box/backup-speed").write_bytes(b"5.0\t1024\t/mnt/bad\xff\n")
    assert bs.windows_own_drives(tmp_path) is None
    assert bs.measured_speeds(tmp_path) == {}


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
    assert list(speeds) == [str(target.resolve())]
    assert speeds[str(target.resolve())][0] > 0 and speeds[str(target.resolve())][1] == 2
    # a second measurement of the same path replaces the first: one line per path
    assert _run(root, "backup-speed", str(target), "3").returncode == 0
    lines = (root / "deploy/site/box/backup-speed").read_text().splitlines()
    assert len(lines) == 1 and lines[0].split("\t")[1:] == ["3", str(target.resolve())]


def test_the_speed_test_never_writes_through_a_link_someone_placed_on_the_target(tmp_path: Path) -> None:
    """The step runs as root on a share or an outside disk others can write to (review H2)."""
    root, target, victim = tmp_path / "opt", tmp_path / "t", tmp_path / "victim"
    target.mkdir()
    victim.write_text("the box's own file\n")
    # the old, guessable name for every plausible process id, each a link to a file of the box
    for pid in range(1, 400):
        (target / f".trialbox-speed-test.{pid}").symlink_to(victim)
    assert _run(root, "backup-speed", str(target), "1").returncode == 0
    assert victim.read_text() == "the box's own file\n"
    sh = Path(SETUP).read_text(encoding="utf-8")
    assert 'mktemp "$real/.trialbox-speed-test.XXXXXXXXXX"' in sh and "oflag=nofollow" in sh and "notrunc" in sh


def test_the_speed_test_does_not_fill_the_target(tmp_path: Path) -> None:
    root, target = tmp_path / "opt", tmp_path / "t"
    target.mkdir()
    r = _run(root, "backup-speed", str(target), "9999999")  # about 10 TB: more than twice the free space here
    assert r.returncode == 1 and "MiB free; the test wants twice" in r.stderr
    assert list(target.iterdir()) == [] and not (root / "deploy/site/box/backup-speed").exists()


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
    "text",
    ["fast\t1024\t/mnt/e\n", "-1\t1024\t/mnt/e\n", "nan\t1024\t/mnt/e\n", "5\n", "\t1024\t/mnt/e\n", "inf\t1024\t/mnt/e\n",
     "5\t/mnt/e\n", "5\t0\t/mnt/e\n", "5\tmany\t/mnt/e\n"],
)  # fmt: skip
def test_a_line_that_is_not_a_measurement_is_not_read_as_one(tmp_path: Path, text: str) -> None:
    (tmp_path / "site/box").mkdir(parents=True)
    (tmp_path / "site/box/backup-speed").write_text(text)
    assert bs.measured_speeds(tmp_path) == {}


# ------------------------------------------------------------------------------------- doctor: backup_speed


def _inp(
    tmp: Path, *, kernel: str = WSL2, mbps: str | None = None, measured: float | None = None, written: int = 1024
) -> DoctorInputs:
    proc, deploy, target = tmp / "proc", tmp / "deploy", tmp / "target"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    (deploy / "site/box").mkdir(parents=True)
    target.mkdir()
    if measured is not None:
        (deploy / "site/box/backup-speed").write_text(f"{measured}\t{written}\t{target.resolve()}\n")
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


@pytest.mark.parametrize(
    ("measured", "advice"), [(3.57, "0.35"), (19.96, "1.9"), (1234.0, "120"), (20.0, "2"), (0.5, "0.05")]
)
def test_the_value_the_line_names_clears_the_line_when_it_is_set(tmp_path: Path, measured: float, advice: str) -> None:
    """Rounded down, in plain figures (review M4): setting what the line says must end the warning."""
    c = check_backup_speed(_inp(tmp_path, measured=measured, mbps=str(measured)))
    assert f"Set it to {advice}" in c.detail and "e+" not in c.detail, c.detail
    assert check_backup_speed(_inp(tmp_path / "again", measured=measured, mbps=advice)).status == "PASS"


def test_a_measurement_too_small_to_get_past_the_write_cache_is_never_a_pass(tmp_path: Path) -> None:
    c = check_backup_speed(_inp(tmp_path, measured=900.0, written=1))
    assert (
        c.status == "WARN"
        and "measured with 1 MiB only" in c.detail
        and "backup-speed" in c.detail
        and " 1024" in c.detail
    )
    from tb_common.config import DECLARED

    assert DECLARED["TB_BACKUP_SPEED_TEST_MIB"].default == "1024"


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_a_limit_that_is_not_a_speed_fails_instead_of_passing_on_the_default(tmp_path: Path, value: str) -> None:
    c = check_backup_speed(_inp(tmp_path, measured=80.0, mbps=value))
    assert c.status == "FAIL" and "TB_BACKUP_MIN_MBPS" in c.detail


def test_no_target_is_said(tmp_path: Path) -> None:
    inp = _inp(tmp_path)
    inp = DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=inp.deploy, proc=inp.proc)
    c = check_backup_speed(inp)
    assert c.status == "WARN" and "no backup target" in c.detail
