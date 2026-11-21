"""10K-4 (D-1390; review 18, SO-4): the backup, audit anchor and log folders are chosen in the box's first-run set-up,
and a PRODUCTION install refuses to finish unless a backup target is shown to be off the box and the anchor folder is
the hospital's audit share.

One check, ``tools/trialbox/finish_check.py`` (``python3 -m tools.trialbox finish-check``), run by ``deploy/install.sh``
(FINISH-EARLY on a re-run before the bundle step, ANCHOR-GATE before anything mounts the anchor, FINISH-GATE before
the stack starts), by ``deploy/box-install.sh`` after the owner's answers are applied, and by
``deploy/settings_guard.sh`` before every start. It accepts only what it can show. The tests give it a host of their
own (:func:`fake_host`) inside a marked test root: a mount table, a ``/sys`` tree (a system disk ``vda`` with
partitions ``vda1`` for ``/`` and ``vda2``, an LVM volume ``dm-0`` on ``vda2``, a second physical disk ``vdb``, a
data disk ``vdc`` holding Docker's data root, a loop device, zram, a LUKS volume on the loop device, a disk with no
hardware behind it), shares on the hospital's NAS and on the box itself, the names a share resolves to, the box's own
address, and a folder that stands for ``/``. No test mounts anything or needs root."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from tb_common import host_folders as hf
from tb_common.box_answers import host_dir, parse

from tools import pglocal
from tools.box import plan as bp
from tools.trialbox import anchors, finish_check

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
OWNER = {
    "site_name": "Site A (synthetic)", "tz": "Asia/Tokyo", "owner_full_name": "Dr Owner", "owner_username": "owner",
    "owner_email": "owner@hospa.test", "backup_kind": "second_disk", "backup_disk": "/dev/sdb",
}  # fmt: skip
#: the fake host's mounts, in mountinfo's order: point -> (major:minor, file system, source, root)
MOUNTS = {
    "/": ("252:1", "ext4", "/dev/vda1", "/"),
    "/var/lib/docker": ("252:33", "ext4", "/dev/vdc1", "/"),  # Docker's data root (the database, the audit volume)
    "/mnt/disk2": ("252:17", "ext4", "/dev/vdb1", "/"),  # the second disk
    "/mnt/data2": ("252:34", "ext4", "/dev/vdc2", "/"),  # another partition of the database's disk
    "/mnt/syspart": ("252:2", "ext4", "/dev/vda2", "/"),  # another partition of the system disk
    "/mnt/lvm": ("253:0", "xfs", "/dev/mapper/vg-data", "/"),  # an LVM volume on the system disk
    "/mnt/loop": ("7:0", "ext4", "/dev/loop0", "/"),  # a file of the system disk, as a disk
    "/mnt/luks": ("253:1", "ext4", "/dev/mapper/crypt", "/"),  # LUKS over that loop device
    "/mnt/zram": ("251:0", "ext4", "/dev/zram0", "/"),  # memory
    "/mnt/nohw": ("252:48", "ext4", "/dev/vdd", "/"),  # a whole disk with no hardware behind it
    "/mnt/nas": ("0:50", "nfs4", "nas.hospa.test:/trialbox", "/"),  # the hospital's share
    "/mnt/audit": ("0:51", "nfs4", "nas.hospa.test:/audit", "/"),  # the hospital's audit share
    "/mnt/audit2": ("0:52", "cifs", "//nas.hospa.test/audit2", "/"),  # another audit share, its folder not there yet
    "/mnt/self": ("0:53", "nfs4", "localhost:/export", "/"),
    "/mnt/self127": ("0:54", "nfs", "127.0.0.1:/export", "/"),
    "/mnt/selfv6": ("0:55", "nfs4", "[::1]:/export", "/"),
    "/mnt/selfcifs": ("0:56", "cifs", "//127.0.0.1/bk", "/"),
    "/mnt/own": ("0:57", "nfs4", "10.0.0.5:/export", "/"),  # the box's own address
    "/mnt/unknown": ("0:58", "nfs4", "nas.nowhere.test:/x", "/"),  # a name that does not resolve
    "/mnt/bindetc": ("252:1", "ext4", "/dev/vda1", "/etc"),  # a bind of /etc
    "/mnt/c": ("0:60", "9p", "C:\\", "/"),  # WSL2's Windows system drive
    "/mnt/ram": ("0:30", "tmpfs", "tmpfs", "/"),
    "/mnt/squash": ("7:1", "squashfs", "/dev/loop1", "/"),
    "/srv/hid/disk": ("252:17", "ext4", "/dev/vdb1", "/"),  # hidden by the tmpfs mounted later on /srv/hid
    "/srv/hid": ("0:31", "tmpfs", "tmpfs", "/"),
}
GOOD = {"backup": "/mnt/disk2/backup", "anchor": "/mnt/audit", "log": "/mnt/disk2/logs"}


def fake_host(tmp: Path, extra_folders: tuple[str, ...] = ()) -> dict[str, Path]:
    """A host of the test's own, inside a marked test root (``tmp``): the mount table, /sys, the names a share
    resolves to, the box's own addresses and the folder that stands for /."""
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / pglocal.MARKER).touch()
    sysr = tmp / "sys"
    pci = sysr / "devices" / "pci"
    disks = {"vda": [("vda1", "252:1"), ("vda2", "252:2")], "vdb": [("vdb1", "252:17")],
             "vdc": [("vdc1", "252:33"), ("vdc2", "252:34")], "vdd": []}  # fmt: skip
    majors = {"vda": "252:0", "vdb": "252:16", "vdc": "252:32", "vdd": "252:48"}

    def link(name: str, dev: Path, mm: str) -> None:
        for p in (sysr / "class" / "block" / name, sysr / "dev" / "block" / mm):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.symlink_to(dev)

    for disk, parts in disks.items():
        d = pci / disk
        d.mkdir(parents=True)
        if disk != "vdd":
            (d / "device").mkdir()  # hardware behind it
        link(disk, d, majors[disk])
        for name, mm in parts:
            (d / name).mkdir()
            (d / name / "partition").write_text("1\n", encoding="utf-8")
            link(name, d / name, mm)
    virt = sysr / "devices" / "virtual" / "block"
    for name, mm, members in (("dm-0", "253:0", ["vda2"]), ("dm-1", "253:1", ["loop0"]), ("loop0", "7:0", []),
                              ("loop1", "7:1", []), ("zram0", "251:0", [])):  # fmt: skip
        d = virt / name
        (d / "slaves").mkdir(parents=True)
        for member in members:
            (d / "slaves" / member).symlink_to(sysr / "class" / "block" / member)
        link(name, d, mm)
    lines = [f"{i} 1 {mm} {root} {point} rw - {fs} {src} rw"
             for i, (point, (mm, fs, src, root)) in enumerate(MOUNTS.items(), 20)]  # fmt: skip
    info = tmp / "mountinfo"
    info.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp / "hosts").write_text("nas.hospa.test 192.0.2.10\n", encoding="utf-8")
    (tmp / "own-addresses").write_text("10.0.0.5 127.0.0.1\n", encoding="utf-8")
    root = tmp / "root"
    for folder in (*GOOD.values(), *[p for p in MOUNTS if p != "/mnt/audit2"], "/mnt/syspart/b", "/mnt/lvm/b",
                   "/mnt/ram/b", "/mnt/nas/backup", "/mnt/data2/b", "/etc", "/srv/plain", "/var/log", "/media/usb",
                   *extra_folders):  # fmt: skip
        (root / folder.lstrip("/")).mkdir(parents=True, exist_ok=True)
    for marked in (GOOD["backup"], "/mnt/syspart/b", "/mnt/data2/b"):  # the nightly rule's mark (one real disk here)
        (root / marked.lstrip("/") / ".trialbox-offbox").write_text("", encoding="utf-8")
    return {"mountinfo": info, "sys": sysr, "root": root, "base": tmp}


def knobs(h: dict[str, Path]) -> dict[str, str]:
    return {"TB_TEST_ROOT": str(h["base"]), "TB_FINISH_MOUNTINFO": str(h["mountinfo"]), "TB_FINISH_SYS": str(h["sys"]),
            "TB_FINISH_TEST_ROOT": str(h["root"])}  # fmt: skip


def host(h: dict[str, Path]) -> finish_check.Host:
    return finish_check.Host(h["mountinfo"].read_text(encoding="utf-8"), h["sys"], str(h["root"]),
                             {"nas.hospa.test": ["192.0.2.10"]}, frozenset({"10.0.0.5", "127.0.0.1"}))  # fmt: skip


def _env(**over: str) -> dict[str, str]:
    base = {"TB_ENV": "PRODUCTION", "TB_BACKUP_TARGETS": GOOD["backup"], "TB_BACKUP_OFFBOX": GOOD["backup"],
            "TB_AUDIT_ANCHOR_TARGETS": GOOD["anchor"], "TB_LOG_DIR": GOOD["log"]}  # fmt: skip
    return base | over


def _problems(tmp: Path, h: dict[str, Path], **over: str) -> list[str]:
    return finish_check.problems(tmp / "box" / "deploy", _env(**over), host(h))


def _env_text(case: str, environment: str = "PRODUCTION") -> str:
    """deploy/.env of a box: good, or broken in one of the card's two ways."""
    backup = "/mnt/syspart/b" if case == "on_box_backups" else GOOD["backup"]
    anchor = "/mnt/audit2" if case == "unmountable_anchor" else GOOD["anchor"]
    return (f"TB_ENV={environment}\nTB_BACKUP_TARGETS={backup}\nTB_BACKUP_OFFBOX={backup}\n"
            f"TB_AUDIT_ANCHOR_TARGETS={anchor}\nCOMPOSE_FILE=deploy/docker-compose.yml\n")  # fmt: skip


def _box(tmp: Path, env_text: str) -> Path:
    """An install folder: the installers copied, the code linked, the vendor key there, deploy/.env as given."""
    box = tmp / "box"
    (box / "deploy" / "site" / "box").mkdir(parents=True)
    (box / "deploy" / "keys").mkdir()
    (box / "deploy" / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n", encoding="utf-8")
    for name in ("install.sh", "box-install.sh", "settings_guard.sh"):
        shutil.copy2(ROOT / "deploy" / name, box / "deploy" / name)
    for name in ("libs", "services", "tools"):
        (box / name).symlink_to(ROOT / name)
    (box / "deploy" / ".env").write_text(env_text, encoding="utf-8")
    (box / "deploy" / ".env").chmod(0o600)
    return box


def _bin(tmp: Path) -> Path:
    """The host's python3 is this interpreter (it has PyYAML); docker answers as a running engine does."""
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    py = b / "python3"
    if not py.exists():
        py.symlink_to(sys.executable)
    docker = b / "docker"
    # no image: a run that gets past the bundle step stops there
    docker.write_text(f'#!/bin/sh\necho "docker $*" >> {tmp}/docker.log\n'
                      'case "$1 $2" in "version --format") echo 27.0 ;; "image inspect") exit 1 ;; esac\nexit 0\n',
                      encoding="utf-8")  # fmt: skip
    docker.chmod(0o755)
    return b


def _base_env(tmp: Path, h: dict[str, Path]) -> dict[str, str]:
    return {"PATH": f"{_bin(tmp)}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp), **knobs(h)}


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


FINISH_FN = _block(INSTALL, "finish_check() {", "\nif [")


def _run_install_rerun(tmp: Path, box: Path, h: dict[str, Path], **env: str) -> subprocess.CompletedProcess[str]:
    """deploy/install.sh, whole, as an installed box runs it again: a stand-in docker engine, a bundle file."""
    bundle = tmp / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"stand-in bundle")
    return subprocess.run(["bash", str(box / "deploy" / "install.sh"), str(bundle), "--mode", "stub", "--yes"],
                          cwd=box, env={**_base_env(tmp, h), **env}, capture_output=True, text=True, check=False,
                          timeout=180)  # fmt: skip


def _run_block(tmp: Path, box: Path, h: dict[str, Path], start: str, end: str,
               **env: str) -> subprocess.CompletedProcess[str]:  # fmt: skip
    """One block of install.sh as install.sh runs it (errexit, its die and finish_check, TB_ENV_SITE from
    deploy/.env), then the install's last banner."""
    script = (
        "set -euo pipefail\n"
        "die() { printf 'install: %s\\n' \"$*\" >&2; exit 1; }\n"
        f'ROOT={str(box)!r}\ncd "$ROOT"\n'
        "TB_ENV_SITE=\"$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)\"\n"
        + FINISH_FN + "\n" + _block(INSTALL, start, end)
        + "\necho '  TrialBox is running.'\n"
    )  # fmt: skip
    return subprocess.run(["bash", "-c", script], cwd=box, env={**_base_env(tmp, h), **env}, capture_output=True,
                          text=True, check=False, timeout=120)  # fmt: skip


def _run_install_first(tmp: Path, box: Path, h: dict[str, Path], **env: str) -> subprocess.CompletedProcess[str]:
    return _run_block(tmp, box, h, "# FINISH-GATE (10K-4, D-1390)", "# ---- end of FINISH-GATE", **env)


def _run_box_firstrun(tmp: Path, box: Path, h: dict[str, Path],
                      docker_rc: int = 0) -> subprocess.CompletedProcess[str]:  # fmt: skip
    """box-install.sh --firstrun, whole, after the owner's answers were applied (deploy/site/box/applied), with
    stand-ins for compose, the host check and the console image's read probe."""
    site = box / "deploy" / "site" / "box"
    (site / "answers.json").write_text('{"tls_hostname": "trialbox.local", "tz": "Asia/Tokyo"}\n', encoding="utf-8")
    (site / "hardware.json").write_text('{"tpm": true}\n', encoding="utf-8")
    (site / "applied").write_text("2026-11-21T00:00:00Z\n", encoding="utf-8")
    stubs = tmp / "stubs"
    stubs.mkdir(exist_ok=True)
    for name, rc in (("compose", 0), ("hostcheck", 0), ("probe", docker_rc)):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {tmp}/calls.log\nexit {rc}\n', encoding="utf-8")
        (stubs / name).chmod(0o755)
    env = {
        **_base_env(tmp, h), "TB_BOX_NO_ROOT": "1", "TB_BOX_PY": sys.executable,
        "TB_BOX_COMPOSE": str(stubs / "compose"), "TB_BOX_HOST_CHECK": str(stubs / "hostcheck"),
        "TB_BOX_DOCKER": str(stubs / "probe"), "TB_ISSUE_DIR": str(tmp / "issue.d"),
        "TB_FIRSTRUN_HOST_DIR": str(tmp / "firstrun"), "TB_SYSTEMD": "0", "TB_BOX_WSL2": "0",
    }  # fmt: skip
    return subprocess.run(["bash", str(box / "deploy" / "box-install.sh"), "--firstrun"], cwd=tmp, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=120)  # fmt: skip


def _calls(tmp: Path) -> str:
    f = tmp / "calls.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


# ------------------------------------------------------------------------------------------------ the card's promise
@pytest.mark.parametrize("installer", ["install.sh re-run", "install.sh first install", "box-install.sh"])
@pytest.mark.parametrize("case", ["on_box_backups", "unmountable_anchor"])
def test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor(
    tmp_path: Path, installer: str, case: str
) -> None:
    """The card's proof, "the install test exits before 'finished' in both cases", with the real scripts:
    install.sh whole as an installed box runs it again (it stops before the bundle step; a good box goes on to it);
    box-install.sh whole after the first-run set-up. A first install of install.sh cannot run whole here (a signed
    bundle, its images and a compose stack come before its gate), so its FINISH-GATE block runs as it stands in the
    file, followed by its last banner. A good box gets past each."""
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text(case))
    said = "no backup target is shown to be off the box" if case == "on_box_backups" else "is not there"
    runs: dict[str, Callable[[Path, Path, dict[str, Path]], subprocess.CompletedProcess[str]]] = {
        "install.sh re-run": _run_install_rerun, "install.sh first install": _run_install_first,
        "box-install.sh": _run_box_firstrun,
    }  # fmt: skip
    r = runs[installer](tmp_path, box, h)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out[-3000:]
    assert said in r.stderr and "finish-check:" in r.stderr, r.stderr[-2000:]
    assert "TrialBox is running" not in out and "TrialBox is ready" not in out
    if installer == "install.sh re-run":
        assert "bundle: verify" not in out and "nothing was loaded or changed" in r.stderr
    if installer == "box-install.sh":  # nothing restarted on the refused settings
        assert "compose" not in _calls(tmp_path)
    good_tmp = tmp_path / "good"
    good_tmp.mkdir()
    good = _box(good_tmp, _env_text("good"))
    r = runs[installer](good_tmp, good, h)
    out = r.stdout + r.stderr
    if installer == "install.sh re-run":  # past the gate: the bundle step refuses the stand-in bundle
        assert "bundle: verify" in out and "finish-check:" not in r.stderr, out[-3000:]
    else:
        assert r.returncode == 0, out[-3000:]
        assert ("TrialBox is running." if installer == "install.sh first install" else "TrialBox is ready") in out


# ------------------------------------------------------------------------------------------------ H1 (review 2)
def test_the_run_from_the_signed_tree_after_a_load_is_not_checked_early(tmp_path: Path) -> None:
    """The old install.sh loads the new bundle (apply, migrate, restart), then runs the new one from the signed tree
    with TB_INSTALL_SIGNED: the early check would come after the load, so it is skipped there."""
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("on_box_backups"))
    release = tmp_path / "releases" / "r1"
    (release / "deploy").mkdir(parents=True)
    (box / "current").symlink_to(release)
    r = _run_install_rerun(tmp_path, box, h, TB_INSTALL_SIGNED=str(release))
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "the bundle carried no" in r.stderr, out[-3000:]  # past FINISH-EARLY
    assert "nothing was loaded or changed" not in out and "finish-check:" not in out


def test_after_a_load_the_gate_says_what_was_done(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    r = _run_install_first(tmp_path, _box(tmp_path, _env_text("on_box_backups")), h, TB_INSTALL_SIGNED="releases/r1")
    last = r.stderr.strip().splitlines()[-1]
    assert r.returncode == 1 and "the bundle this run loaded stays" in last and "applied and running" in last
    assert "the install's own start, units, cron and checks were not run" in last and "nothing" not in last


# ------------------------------------------------------------------------------------------------ H2: what a disk is
@pytest.mark.parametrize(
    ("target", "said"),
    [
        ("/mnt/loop", "its disk cannot be told (/dev/loop0)"),  # a file of the system disk
        ("/mnt/luks", "its disk cannot be told (/dev/mapper/crypt)"),  # LUKS over that loop device
        ("/mnt/zram", "its disk cannot be told (/dev/zram0)"),  # memory
        ("/mnt/nohw", "its disk cannot be told (/dev/vdd)"),  # no hardware behind it
        ("/mnt/syspart/b", "is on a disk of the box itself (vda"),  # another partition of the system disk
        ("/mnt/lvm/b", "is on a disk of the box itself (vda"),  # an LVM volume on it
        ("/mnt/data2/b", "is on a disk of the box itself (vdc"),  # the database's disk (Docker's data root)
        ("/srv/plain", "is on a disk of the box itself (vda"),
        ("/mnt/ram/b", "is on tmpfs"),
        ("/mnt/squash", "is on squashfs"),
        ("/dev/shm", "system folder /dev"),
        ("/proc", "system folder /proc"),
        ("/srv/hid/disk", "is on tmpfs"),  # L2: the disk under a later tmpfs is hidden; the tmpfs is what is there
        ("/mnt/disk2/no-such", "is not there"),
    ],
)
def test_a_backup_target_counts_off_the_box_only_when_it_is_shown(tmp_path: Path, target: str, said: str) -> None:
    h = fake_host(tmp_path / "host")
    found = _problems(tmp_path, h, TB_BACKUP_TARGETS=target, TB_BACKUP_OFFBOX=target)
    assert len(found) == 1 and "no backup target is shown to be off the box" in found[0] and said in found[0], found


def test_a_disk_holding_the_audit_folder_is_the_box_s(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host", ("/mnt/disk2/audit",))
    found = _problems(tmp_path, h, TB_AUDIT_HOST_DIR="/mnt/disk2/audit")
    assert found and "is on a disk of the box itself (vdb" in found[0], found


def test_a_btrfs_with_a_member_on_the_system_disk_is_the_box_s(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host", ("/mnt/raid/b",))
    devices = h["sys"] / "fs" / "btrfs" / "fsid-1" / "devices"
    devices.mkdir(parents=True)
    for member in ("vdb1", "vda2"):
        (devices / member).symlink_to(h["sys"] / "class" / "block" / member)
    info = h["mountinfo"].read_text(encoding="utf-8") + "90 1 0:70 / /mnt/raid rw - btrfs /dev/vdb1 rw\n"
    hh = finish_check.Host(info, h["sys"], str(h["root"]), {}, frozenset())
    found = finish_check.problems(tmp_path / "box" / "deploy", _env(TB_BACKUP_TARGETS="/mnt/raid/b",
                                  TB_BACKUP_OFFBOX="/mnt/raid/b"), hh)  # fmt: skip
    assert found and "is on a disk of the box itself (vda" in found[-1], found
    shutil.rmtree(h["sys"] / "fs")  # its members cannot be read: cannot be told
    found = finish_check.problems(tmp_path / "box" / "deploy", _env(TB_BACKUP_TARGETS="/mnt/raid/b",
                                  TB_BACKUP_OFFBOX="/mnt/raid/b"), hh)  # fmt: skip
    assert found and "cannot be told" in found[-1], found


@pytest.mark.parametrize("target", ["/mnt/disk2/backup", "/mnt/nas/backup"])
def test_a_second_physical_disk_or_the_hospital_s_share_is_off_the_box(tmp_path: Path, target: str) -> None:
    assert _problems(tmp_path, fake_host(tmp_path / "host"), TB_BACKUP_TARGETS=target) == []


def test_a_system_disk_that_cannot_be_told_counts_no_local_disk(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    info = h["mountinfo"].read_text(encoding="utf-8")
    info = info.replace("252:1 / / rw - ext4 /dev/vda1", "0:99 / / rw - overlay x")
    hh = finish_check.Host(info, h["sys"], str(h["root"]), {"nas.hospa.test": ["192.0.2.10"]}, frozenset({"10.0.0.5"}))
    deploy = tmp_path / "box" / "deploy"
    assert "cannot be told, so no local disk is counted" in finish_check.problems(deploy, _env(), hh)[0]
    assert finish_check.problems(deploy, _env(TB_BACKUP_TARGETS="/mnt/nas/backup"), hh) == []  # a share still counts


# ------------------------------------------------------------------------------------------------ M4: the nightly rule
def test_a_second_disk_not_named_in_tb_backup_offbox_is_refused(tmp_path: Path) -> None:
    found = _problems(tmp_path, fake_host(tmp_path / "host"), TB_BACKUP_OFFBOX="")
    assert found and "TB_BACKUP_OFFBOX does not name it" in found[0], found


@pytest.mark.parametrize("target", ["/mnt/disk2/backup", "/mnt/nas/backup"])
def test_the_nightly_backup_counts_every_target_the_gate_accepts(tmp_path: Path, target: str) -> None:
    """The gate and the nightly backup never disagree: on each accepted case, backup_schedule.target_kind (the
    nightly backup's rule) is run on the same folder and says off the box."""
    from tools.trialbox import backup_schedule as bs

    h = fake_host(tmp_path / "host")
    hh = host(h)
    assert finish_check.off_the_box(target, hh, tmp_path / "box" / "deploy", _env(TB_BACKUP_TARGETS=target)) == ""
    mounts = "".join(f"{m.source} {hh.on_disk(m.point)} {m.fstype} {m.options}\n" for m in hh.visible())
    t = bs.target_kind(Path(hh.on_disk(target)), mounts_text=mounts, declared=[hh.on_disk(GOOD["backup"])],
                       local=(Path(hh.on_disk("/")),))  # fmt: skip
    assert t.offbox, t


# ------------------------------------------------------------------------------------------------ M5: the box's shares
@pytest.mark.parametrize(
    ("target", "said"),
    [("/mnt/self", "served by this box (localhost)"), ("/mnt/self127", "served by this box (127.0.0.1"),
     ("/mnt/selfv6", "served by this box ([::1]"), ("/mnt/selfcifs", "served by this box (127.0.0.1"),
     ("/mnt/own", "served by this box (10.0.0.5"), ("/mnt/unknown", "cannot be told (the name does not resolve)")],
)  # fmt: skip
def test_a_share_the_box_serves_or_cannot_place_is_not_off_the_box(tmp_path: Path, target: str, said: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path / "host"), TB_BACKUP_TARGETS=target)
    assert found and said in found[-1], found


def test_a_share_is_not_counted_when_the_box_s_own_addresses_cannot_be_read(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    hh = finish_check.Host(h["mountinfo"].read_text(encoding="utf-8"), h["sys"], str(h["root"]),
                           {"nas.hospa.test": ["192.0.2.10"]}, None)  # fmt: skip
    found = finish_check.problems(tmp_path / "box" / "deploy", _env(TB_BACKUP_TARGETS="/mnt/nas/backup"), hh)
    assert found and "own addresses cannot be read" in found[0], found


# ------------------------------------------------------------------------------------------------ H2 (1): the anchor
@pytest.mark.parametrize(
    "anchor",
    ["/etc", "/root", "/proc/1/root", "/proc/self/root", "/var/lib/docker/volumes", "/", "/var", "/opt/trialbox",
     "/usr/share", "/lib64", "/tmp", "/var/tmp/x", "/dev/shm", "/home/owner", "/var/log", "/media/usb", "/efi"],
)  # fmt: skip
@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION"])
def test_a_system_folder_is_never_given_to_the_console(tmp_path: Path, anchor: str, environment: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path / "host"), TB_ENV=environment, TB_AUDIT_ANCHOR_TARGETS=anchor)
    assert found and "the audit anchor folder" in found[0] and "system folder" in found[0], found
    assert host_dir(anchor) is None  # and the page refuses it


@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION"])
def test_a_bind_mount_of_etc_is_etc(tmp_path: Path, environment: str) -> None:
    found = _problems(
        tmp_path, fake_host(tmp_path / "host"), TB_ENV=environment, TB_AUDIT_ANCHOR_TARGETS="/mnt/bindetc"
    )
    assert found and "is a bind mount of /etc" in found[0], found


def test_a_bind_mount_whose_source_cannot_be_placed_is_refused(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host", ("/mnt/orphan",))
    info = h["mountinfo"].read_text(encoding="utf-8") + "91 1 0:80 /sub /mnt/orphan rw - xfs /dev/vdb9 rw\n"
    hh = finish_check.Host(info, h["sys"], str(h["root"]), {}, frozenset())
    found = finish_check.problems(tmp_path / "box" / "deploy", _env(TB_ENV="VALIDATION",
                                  TB_AUDIT_ANCHOR_TARGETS="/mnt/orphan"), hh)  # fmt: skip
    assert found and "bind mount whose source cannot be told" in found[0], found


@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION"])
def test_a_windows_drive_is_never_given_to_the_console(tmp_path: Path, environment: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path / "host"), TB_ENV=environment, TB_AUDIT_ANCHOR_TARGETS="/mnt/c")
    assert found and "Windows drive or share of WSL2" in found[0], found


def test_the_install_folder_its_secrets_and_the_data_folders_are_never_given_to_the_console(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host", ("/srv/tb/deploy/secrets", "/srv/feed/in", "/srv/data/audit"))
    deploy = h["root"] / "srv" / "tb" / "deploy"  # the install folder, under the folder that stands for /
    for anchor, said in (("/srv/tb", "the install folder"), ("/srv/tb/deploy/secrets", "the install folder"),
                         ("/srv/feed", "TB_SOURCE_DIR"), ("/srv/data/audit", "TB_AUDIT_HOST_DIR")):  # fmt: skip
        env = _env(TB_AUDIT_ANCHOR_TARGETS=anchor, TB_SOURCE_DIR="/srv/feed/in", TB_AUDIT_HOST_DIR="/srv/data/audit")
        found = finish_check.problems(deploy, env, host(h))
        assert found and said in found[0], (anchor, found)


def test_a_link_in_the_anchor_s_path_is_refused(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    (h["root"] / "mnt/nas/link").symlink_to(h["root"] / "etc")
    (h["root"] / "mnt/nas/sub").mkdir()
    (h["root"] / "mnt/nas/sub/inner").symlink_to(h["root"] / "mnt/disk2", target_is_directory=True)
    for anchor, real in (("/mnt/nas/link", "/etc"), ("/mnt/nas/sub/inner/backup", "/mnt/disk2/backup")):
        found = _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS=anchor)
        assert found and f"has a link in its path: it is really {real}" in found[0], (anchor, found)


def test_an_anchor_under_a_folder_others_may_write_is_refused(tmp_path: Path) -> None:
    """M3: a parent another account may write could get a link in the anchor's place before the next start."""
    h = fake_host(tmp_path / "host", ("/srv/open/anchor",))
    (h["root"] / "srv" / "open").chmod(0o777)
    found = _problems(tmp_path, h, TB_ENV="VALIDATION", TB_AUDIT_ANCHOR_TARGETS="/srv/open/anchor")
    assert found and "has a parent folder /srv/open that another account owns or may write" in found[0], found


@pytest.mark.parametrize(
    ("anchor", "said"),
    [("/mnt/disk2", "the log folder"), ("/mnt/disk2/backup/x", "a backup target"), ("/mnt/ram/b", "is on tmpfs"),
     ("/srv/plain", "is not the hospital's audit share itself"), ("/mnt/nas/backup", "is not the hospital's audit share"),
     ("/mnt/self", "served by this box")],
)  # fmt: skip
def test_in_production_the_anchor_is_the_hospital_s_audit_share_itself(tmp_path: Path, anchor: str, said: str) -> None:
    h = fake_host(tmp_path / "host")
    (h["root"] / "mnt/disk2/backup/x").mkdir()
    found = _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS=anchor)
    assert found and said in found[0], found


def test_outside_production_a_local_folder_of_its_own_may_be_the_anchor(tmp_path: Path) -> None:
    assert _problems(tmp_path, fake_host(tmp_path / "host"), TB_ENV="VALIDATION", TB_AUDIT_ANCHOR_TARGETS="/srv/plain",
                     TB_BACKUP_TARGETS="") == []  # fmt: skip


def test_no_anchor_folder_is_refused_in_production_only(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    assert "no audit anchor folder" in _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS="")[0]
    assert _problems(tmp_path, h, TB_ENV="VALIDATION", TB_AUDIT_ANCHOR_TARGETS="", TB_BACKUP_TARGETS="") == []


# ------------------------------------------------------------------------------------------------ M3: every start
def _guard(tmp: Path, box: Path, h: dict[str, Path], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(box / "deploy" / "settings_guard.sh"), str(box / "deploy")], cwd=tmp,
                          env={**_base_env(tmp, h), **env}, capture_output=True, text=True, check=False, timeout=60)  # fmt: skip


def test_every_start_checks_the_anchor_again(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good"))
    (box / "deploy" / "site" / "compose.anchors.yml").write_text("services: {}\n", encoding="utf-8")
    r = _guard(tmp_path, box, h)
    assert r.returncode == 0, r.stderr
    anchor = h["root"] / "mnt" / "audit"
    anchor.rmdir()  # somebody with root swapped a link in after the install
    anchor.symlink_to(h["root"] / "etc")
    r = _guard(tmp_path, box, h)
    assert r.returncode == 1 and "TrialBox REFUSED to start" in r.stderr and "has a link in its path" in r.stderr
    (box / "deploy" / "site" / "compose.anchors.yml").unlink()  # no anchor mounted: nothing to check
    assert _guard(tmp_path, box, h).returncode == 0


# ------------------------------------------------------------------------------------------------ M1: the stand-ins
@pytest.mark.parametrize("how", ["no test root", "no marker", "outside the test root"])
def test_the_stand_ins_are_honoured_only_inside_a_marked_test_root(tmp_path: Path, how: str) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good"))
    env = {"PATH": "/usr/bin:/bin", **knobs(h)}
    if how == "no test root":
        env.pop("TB_TEST_ROOT")
    elif how == "no marker":
        (h["base"] / pglocal.MARKER).unlink()
    else:
        env["TB_TEST_ROOT"] = str(tmp_path / "elsewhere")
        (tmp_path / "elsewhere").mkdir()
        (tmp_path / "elsewhere" / pglocal.MARKER).touch()
    cmd = [sys.executable, "-m", "tools.trialbox", "finish-check", "--deploy", str(box / "deploy")]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "outside a marked test root" in r.stderr and "sudo -E" in r.stderr, r.stderr
    assert finish_check.MARKER == pglocal.MARKER


# ------------------------------------------------------------------------------------------------ L1, L2: reading
def test_tb_env_is_read_as_install_sh_reads_it(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("TB_ENV=PRODUCTION\n TB_ENV=DEV\nTB_ENV =DEV\n", encoding="utf-8")
    assert finish_check.environment(finish_check.read_env(f)) == "PRODUCTION"


def test_the_real_mount_table_is_read(tmp_path: Path) -> None:
    """L6: the parser on this machine's own /proc/self/mountinfo finds the mount of /."""
    mounts = finish_check.parse_mountinfo(Path("/proc/self/mountinfo").read_text(encoding="utf-8"))
    assert any(m.point == "/" for m in mounts)
    assert finish_check.Host(Path("/proc/self/mountinfo").read_text(encoding="utf-8")).mount_of("/") is not None


# ------------------------------------------------------------------------------------------------ L8: the log folder
@pytest.mark.parametrize(("log", "said"), [("/tmp/logs", "system folder"), ("/mnt/ram/b", "tmpfs"),
                                           ("/mnt/disk2/backup", "a backup target")])  # fmt: skip
def test_a_log_folder_that_breaks_the_rule_is_refused(tmp_path: Path, log: str, said: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path / "host"), TB_LOG_DIR=log)
    assert found and "the log folder" in found[0] and said in found[0], found


def test_the_install_s_own_log_folder_and_audit_archive_stay_allowed(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host", ("/srv/tb/deploy/logs/audit-archive",))
    deploy = h["root"] / "srv" / "tb" / "deploy"
    env = _env(TB_LOG_DIR="/srv/tb/deploy/logs", TB_AUDIT_ARCHIVE_DIR="/srv/tb/deploy/logs/audit-archive")
    assert finish_check.problems(deploy, env, host(h)) == []


# ------------------------------------------------------------------------------------------------ install.sh's blocks
@pytest.mark.parametrize("written", ['"PRODUCTION"', "production", " Production\r", ""])
def test_install_sh_reads_tb_env_as_the_check_does(tmp_path: Path, written: str) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("on_box_backups").replace("TB_ENV=PRODUCTION", f"TB_ENV={written}"))
    r = _run_install_first(tmp_path, box, h)
    assert r.returncode == 1 and "TrialBox is running." not in r.stdout, r.stderr


def test_the_box_s_own_install_before_its_set_up_is_not_checked(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("on_box_backups"))
    assert _run_install_first(tmp_path, box, h, TB_BOX="1").returncode == 0
    assert _run_install_first(tmp_path, box, h, TB_BOX="0").returncode == 1  # the unattended install is checked


def test_the_anchor_is_judged_before_anything_mounts_it_whatever_tb_box_says(tmp_path: Path) -> None:
    """L3: ANCHOR-GATE comes before ANCHOR-MOUNT (the read probe, the console) and does not look at TB_BOX."""
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good", "VALIDATION").replace(GOOD["anchor"], "/mnt/bindetc"))
    for tb_box in ("1", "0"):
        r = _run_block(tmp_path, box, h, "# ANCHOR-GATE (10K-4", "# ---- end of ANCHOR-GATE", TB_BOX=tb_box)
        assert r.returncode == 1 and "bind mount of /etc" in r.stderr and "nothing was mounted" in r.stderr
    gate = INSTALL.index("# ANCHOR-GATE (10K-4")
    assert gate < INSTALL.index("# ANCHOR-MOUNT (D-638)") < INSTALL.index("# FINISH-GATE (10K-4")
    assert "TB_BOX" not in _block(INSTALL, "# ANCHOR-GATE (10K-4", "# ---- end of ANCHOR-GATE").split("\nif ", 1)[1]


def test_a_check_that_did_not_run_is_not_called_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L4: exit 2 when the check itself fails; the shell then says it did not run."""

    def boom(*a: object, **k: object) -> list[str]:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(finish_check, "problems", boom)
    assert finish_check.main_action(tmp_path) == 2
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good"))
    shim = tmp_path / "crash"
    shim.mkdir()
    (shim / "python3").write_text("#!/bin/sh\necho 'Traceback (synthetic)' >&2\nexit 2\n", encoding="utf-8")
    (shim / "python3").chmod(0o755)
    r = _run_install_first(tmp_path, box, h, PATH=f"{shim}{os.pathsep}/usr/bin:/bin")
    assert r.returncode == 1 and "the finish check did not run (exit 2" in r.stderr
    assert "the setting to change" not in r.stderr


def test_a_validation_install_is_refused_only_for_its_anchor(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("on_box_backups", environment="VALIDATION"))
    assert _run_install_first(tmp_path, box, h).returncode == 0
    (box / "deploy" / ".env").write_text(_env_text("good", "VALIDATION").replace(GOOD["anchor"], "/etc"),
                                         encoding="utf-8")  # fmt: skip
    r = _run_install_first(tmp_path, box, h)
    assert r.returncode == 1 and "system folder /etc" in r.stderr


def test_the_re_run_check_comes_before_the_bundle_step_and_changes_nothing(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("on_box_backups"))
    before = {p.relative_to(box): p.read_bytes() for p in (box / "deploy").rglob("*") if p.is_file()}
    r = _run_install_rerun(tmp_path, box, h)
    assert r.returncode == 1 and "nothing was loaded or changed" in r.stderr
    after = {p.relative_to(box): p.read_bytes() for p in (box / "deploy").rglob("*") if p.is_file()}
    assert after == before
    early = INSTALL.index("# FINISH-EARLY (10K-4, D-1390)")
    assert INSTALL.index("# ---- end of REHEARSAL") < early < INSTALL.index('say "bundle: verify and load')
    gate = INSTALL.index("# FINISH-GATE (10K-4, D-1390)")
    default = INSTALL.index("grep -q '^TB_BACKUP_TARGETS=' deploy/.env ||")
    assert default < gate < INSTALL.index('say "starting the stack')


def test_install_sh_runs_the_check_without_a_value_of_the_site_in_its_command() -> None:
    code = "\n".join(ln for ln in FINISH_FN.splitlines() if not ln.lstrip().startswith("#"))
    assert 'python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy" "$@"' in code
    for start, end in (("# FINISH-EARLY (10K-4", "# ---- end of FINISH-EARLY"),
                       ("# ANCHOR-GATE (10K-4", "# ---- end of ANCHOR-GATE"),
                       ("# FINISH-GATE (10K-4", "# ---- end of FINISH-GATE")):  # fmt: skip
        block = _block(INSTALL, start, end)
        assert "eval" not in block and "sh -c" not in block and "envget" not in block


# ------------------------------------------------------------------------------------------------ the box path
def test_a_box_refusal_says_how_to_correct_a_folder(tmp_path: Path) -> None:
    r = _run_box_firstrun(tmp_path, _box(tmp_path, _env_text("on_box_backups")), fake_host(tmp_path / "host"))
    assert r.returncode == 1
    assert "set TB_BACKUP_TARGETS in" in r.stderr and "TB_BACKUP_OFFBOX to the same folder" in r.stderr
    assert "first-run page does not open again" in r.stderr and "box-install.sh --firstrun" in r.stderr


def test_box_install_asks_the_console_image_to_read_the_anchor_then_mounts_it(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good"))
    r = _run_box_firstrun(tmp_path, box, h)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    calls = _calls(tmp_path)
    assert f"probe run --rm --network none -v {GOOD['anchor']}:/anchor:ro" in calls
    assert calls.index("probe run") < calls.index("compose up -d --wait")
    made = box / "deploy" / anchors.NAME
    env = anchors.read_env(box / "deploy" / ".env")
    assert env["COMPOSE_FILE"] == f"deploy/docker-compose.yml{os.pathsep}{made}"
    assert stat.S_IMODE((box / "deploy" / ".env").stat().st_mode) == 0o600
    again = _run_box_firstrun(tmp_path, box, h)
    assert again.returncode == 0 and anchors.read_env(box / "deploy" / ".env")["COMPOSE_FILE"] == env["COMPOSE_FILE"]


def test_box_install_stops_when_the_console_image_cannot_read_the_anchor(tmp_path: Path) -> None:
    box = _box(tmp_path, _env_text("good"))
    r = _run_box_firstrun(tmp_path, box, fake_host(tmp_path / "host"), docker_rc=1)
    assert r.returncode == 1 and "the console's user cannot read" in r.stderr
    assert "compose up" not in _calls(tmp_path) and not (box / "deploy" / anchors.NAME).exists()


def test_box_install_finishes_once_the_share_is_mounted(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("unmountable_anchor"))
    assert _run_box_firstrun(tmp_path, box, h).returncode == 1
    (h["root"] / "mnt/audit2").mkdir()
    r = _run_box_firstrun(tmp_path, box, h)
    assert r.returncode == 0 and "TrialBox is ready" in r.stdout, r.stderr[-2000:]


def test_the_unattended_box_install_is_left_to_install_sh() -> None:
    gate = BOX_INSTALL.index("# FINISH-GATE (10K-4, D-1390)")
    block = BOX_INSTALL[gate : BOX_INSTALL.index('HOST="$(json_get', gate)]
    assert 'if [ -z "$OWNER" ]; then' in block and "--mount-anchors" in block and "--print-anchors" in block
    assert BOX_INSTALL.index("box_py apply") < gate < BOX_INSTALL.index("up -d --wait")


# ------------------------------------------------------------------------------------------------ no PyYAML, .env
def test_a_host_python_without_yaml_gets_a_true_message(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    box = _box(tmp_path, _env_text("good", "VALIDATION").replace(f"TB_AUDIT_ANCHOR_TARGETS={GOOD['anchor']}\n", ""))
    env = {"PATH": "/usr/bin:/bin", **knobs(h)}
    cmd = [sys.executable, "-S", "-m", "tools.trialbox", "finish-check", "--deploy", str(box / "deploy")]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    (box / "deploy" / ".env").write_text(_env_text("good"), encoding="utf-8")
    r = subprocess.run([*cmd, "--mount-anchors"], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "python3-yaml" in r.stderr, r.stderr


def test_mount_anchors_keeps_the_file_as_it_was_but_its_one_line(tmp_path: Path) -> None:
    h = fake_host(tmp_path / "host")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    anchor = h["root"] / "mnt/audit"  # mount_anchors runs once the check has passed: a real folder here
    env_file = deploy / ".env"
    old = "COMPOSE_FILE=/opt/t/a.yml:/opt/t/b.yml"
    text = f"POSTGRES_PASSWORD=x\r\nTB_AUDIT_ANCHOR_TARGETS={anchor}\r\n{old}\r\nLAST=1"
    env_file.write_bytes(text.encode("utf-8"))
    env_file.chmod(0o640)
    assert finish_check.mount_anchors(deploy) == ""
    got = env_file.read_bytes().decode("utf-8")
    assert got == text.replace(old, f"{old}:{deploy / anchors.NAME}")  # the CRs and the missing last line end kept
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
    assert not [p for p in deploy.iterdir() if p.name.startswith(".env.")]
    real = tmp_path / "real.env"
    env_file.rename(real)
    env_file.symlink_to(real)
    assert "is a link" in finish_check.mount_anchors(deploy) and env_file.is_symlink()


def test_mount_anchors_guesses_no_compose_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    text = f"TB_AUDIT_ANCHOR_TARGETS={tmp_path}\n"
    (deploy / ".env").write_text(text, encoding="utf-8")
    assert finish_check.mount_anchors(deploy) == ""
    assert "no COMPOSE_FILE line" in capsys.readouterr().out
    assert (deploy / ".env").read_text(encoding="utf-8") == text and not (deploy / anchors.NAME).exists()


# ------------------------------------------------------------------------------------------------ the page's rule
@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("", ""), ("/mnt/trialbox-audit", "/mnt/trialbox-audit"), ("/srv/backup/", "/srv/backup"), ("/data", "/data"),
        ("/", None), ("relative", None), ("/srv/../etc", None), ("/srv/./x", None), ("/srv//x", None),
        ("/a b", None), ("/a$(id)", None), ('/a"b', None), ("/a\nTB_ENV=DEV", None), ("/" + "a" * 255, None),
        ("/etc", None), ("/etc/trialbox", None), ("/root", None), ("/home/owner", None), ("/opt/trialbox", None),
        ("/usr", None), ("/var/lib/docker/volumes", None), ("/var", None), ("/boot", None), ("/lib", None),
        ("/lib64", None), ("/proc/1/root", None), ("/proc/self/root", None), ("/sys", None), ("/dev/shm", None),
        ("/run/x", None), ("/tmp", None), ("/var/tmp/x", None), ("/var/log", None), ("/var/cache/x", None),
        ("/var/spool", None), ("/var/mail", None), ("/var/backups", None), ("/media/usb", None), ("/efi", None),
    ],
)  # fmt: skip
def test_a_typed_folder_is_allowed_only_by_the_rule(raw: str, want: str | None) -> None:
    assert host_dir(raw) == want and hf.allowed(raw) == want


@pytest.mark.parametrize(
    ("over", "field"),
    [({"anchor_dir": "/mnt/a", "log_dir": "/mnt/a"}, "log_dir"),
     ({"backup_dir": "/mnt/b", "anchor_dir": "/mnt/b/audit"}, "anchor_dir"),
     ({"anchor_dir": "/mnt/x/logs", "log_dir": "/mnt/x"}, "log_dir")],
)  # fmt: skip
def test_the_three_folders_are_three_separate_folders(over: dict[str, str], field: str) -> None:
    _, problems = parse({**OWNER, **over}, disks=("/dev/sdb",))
    assert [(p.field, p.code) for p in problems] == [(field, "host_dir_overlap")]


def test_the_folders_reach_the_plan_and_the_defaults_stay() -> None:
    hw = bp.Hardware(arch="x86_64", cpu_count=32, ram_gib=128.0, disk_free_gib=1800.0, gpu_name="", gpu_mem_gib=0.0,
                     tpm=True, disks=(bp.Disk("/dev/sdb", 3726.0, "sata"),), lan="192.0.2.0/24", hostname="box1",
                     host_tz="Asia/Tokyo")  # fmt: skip
    a, problems = parse(OWNER, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, hw).env_extra
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == bp.SECOND_DISK_MOUNT == "/srv/trialbox-backup"
    assert "TB_AUDIT_ANCHOR_TARGETS" not in env and "TB_LOG_DIR" not in env  # not asked: as before
    chosen = {"backup_dir": "/srv/disk2", "anchor_dir": "/mnt/audit", "log_dir": "/srv/logs"}
    a, problems = parse({**OWNER, **chosen}, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, hw).env_extra
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == "/srv/disk2"  # the nightly rule's declaration
    assert env["TB_AUDIT_ANCHOR_TARGETS"] == "/mnt/audit" and env["TB_LOG_DIR"] == "/srv/logs"
    again, _ = parse(a.to_json(), disks=("/dev/sdb",))
    assert again == a
    later, _ = parse({**OWNER, "backup_kind": "later", "backup_dir": "/srv/disk2"})
    assert later is not None and later.backup_dir == ""


# ------------------------------------------------------------------------------------------------ the runbook
def test_runbook_05_says_which_steps_now_stop_and_what_is_checked() -> None:
    text = (ROOT / "docs/runbook/05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    para = " ".join(text[text.index("**A PRODUCTION install needs a backup target off the box") :].split())
    for words in ("runs `deploy/install.sh` again", "(02,", "05, after a restore", "12, the TLS check",
                  "another partition of it", "TB_BACKUP_OFFBOX", "box-install.sh --firstrun",
                  "the release that run brought is applied", "nosuid,nodev", "at every start"):  # fmt: skip
        assert words in para, words
