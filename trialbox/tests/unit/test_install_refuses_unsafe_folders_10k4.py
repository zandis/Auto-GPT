"""10K-4 (D-1390; review 18, SO-4): the backup, audit anchor and log folders are chosen in the box's first-run set-up,
and a PRODUCTION install refuses to finish with its backups only on the box or with an audit anchor folder that may
not be given to the console.

One check, ``tools/trialbox/finish_check.py`` (``python3 -m tools.trialbox finish-check``), run by ``deploy/install.sh``
(FINISH-EARLY on a re-run, before the bundle step; FINISH-GATE before the stack starts) and by ``deploy/box-install.sh``
after the owner's answers are applied. It judges each folder by what it is: its real path, its mount in
``/proc/self/mountinfo`` and the whole disks under it in ``/sys``. The tests give it a host of their own
(:func:`fake_host`): a mount table, a ``/sys`` tree with a system disk ``vda`` (partitions ``vda1`` for ``/`` and
``vda2``, and an LVM volume ``dm-0`` on ``vda2``), a second disk ``vdb``, an NFS share, a tmpfs and a squashfs, and a
folder that stands for ``/``, so no test mounts anything or needs root."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import host_folders as hf
from tb_common.box_answers import host_dir, parse

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
#: the fake host's mounts: point -> (major:minor, file system, source)
MOUNTS = {
    "/": ("252:1", "ext4", "/dev/vda1"),
    "/mnt/disk2": ("252:17", "ext4", "/dev/vdb1"),  # the second disk
    "/mnt/syspart": ("252:2", "ext4", "/dev/vda2"),  # another partition of the system disk
    "/mnt/lvm": ("253:0", "xfs", "/dev/mapper/vg-data"),  # an LVM volume on the system disk
    "/mnt/nas": ("0:50", "nfs4", "nas.hospa.test:/trialbox"),  # the hospital's share
    "/mnt/ram": ("0:30", "tmpfs", "tmpfs"),  # memory
    "/mnt/squash": ("7:0", "squashfs", "/dev/loop0"),
}
GOOD = {"backup": "/mnt/disk2/backup", "anchor": "/mnt/nas/audit", "log": "/mnt/disk2/logs"}


def fake_host(tmp: Path, extra_folders: tuple[str, ...] = ()) -> dict[str, Path]:
    """A host of the test's own: the mount table file, the /sys tree and the folder that stands for /."""
    sysr = tmp / "sys"
    disks: dict[str, list[tuple[str, str]]] = {
        "vda": [("vda", "252:0"), ("vda1", "252:1"), ("vda2", "252:2")],
        "vdb": [("vdb", "252:16"), ("vdb1", "252:17")],
    }
    for disk, devices in disks.items():
        d = sysr / "devices" / "pci" / disk
        d.mkdir(parents=True)
        for name, mm in devices:
            dev = d if name == disk else d / name
            dev.mkdir(exist_ok=True)
            if name != disk:
                (dev / "partition").write_text("1\n", encoding="utf-8")
            for link in (sysr / "class" / "block" / name, sysr / "dev" / "block" / mm):
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(dev)
    dm = sysr / "devices" / "virtual" / "dm-0"
    (dm / "slaves").mkdir(parents=True)
    (dm / "slaves" / "vda2").symlink_to(sysr / "devices" / "pci" / "vda" / "vda2")
    (sysr / "class" / "block" / "dm-0").symlink_to(dm)
    (sysr / "dev" / "block" / "253:0").symlink_to(dm)
    lines = [f"{i} 1 {mm} / {point} rw - {fs} {src} rw" for i, (point, (mm, fs, src)) in enumerate(MOUNTS.items(), 20)]
    info = tmp / "mountinfo"
    info.write_text("\n".join(lines) + "\n", encoding="utf-8")
    root = tmp / "root"
    for folder in (*GOOD.values(), "/mnt/syspart/b", "/mnt/lvm/b", "/mnt/ram/b", "/mnt/squash/b", "/mnt/nas/backup",
                   "/etc", "/srv/plain", *extra_folders):  # fmt: skip
        (root / folder.lstrip("/")).mkdir(parents=True, exist_ok=True)
    return {"mountinfo": info, "sys": sysr, "root": root}


def knobs(h: dict[str, Path]) -> dict[str, str]:
    return {"TB_FINISH_MOUNTINFO": str(h["mountinfo"]), "TB_FINISH_SYS": str(h["sys"]),
            "TB_FINISH_TEST_ROOT": str(h["root"])}  # fmt: skip


def host(h: dict[str, Path]) -> finish_check.Host:
    return finish_check.Host(h["mountinfo"].read_text(encoding="utf-8"), h["sys"], str(h["root"]))


def _env(**over: str) -> dict[str, str]:
    base = {"TB_ENV": "PRODUCTION", "TB_BACKUP_TARGETS": GOOD["backup"], "TB_BACKUP_OFFBOX": GOOD["backup"],
            "TB_AUDIT_ANCHOR_TARGETS": GOOD["anchor"], "TB_LOG_DIR": GOOD["log"]}  # fmt: skip
    return base | over


def _problems(tmp: Path, h: dict[str, Path], **over: str) -> list[str]:
    return finish_check.problems(tmp / "box" / "deploy", _env(**over), host(h))


def _env_text(case: str, environment: str = "PRODUCTION") -> str:
    """deploy/.env of a box: good, or broken in one of the card's two ways."""
    backup = "/mnt/syspart/b" if case == "on_box_backups" else GOOD["backup"]
    anchor = "/mnt/nas/no-such-share" if case == "unmountable_anchor" else GOOD["anchor"]
    return (f"TB_ENV={environment}\nTB_BACKUP_TARGETS={backup}\nTB_BACKUP_OFFBOX={backup}\n"
            f"TB_AUDIT_ANCHOR_TARGETS={anchor}\nCOMPOSE_FILE=deploy/docker-compose.yml\n")  # fmt: skip


def _box(tmp: Path, env_text: str) -> Path:
    """An install folder: the two installers copied, the code linked, the vendor key there, deploy/.env as given."""
    box = tmp / "box"
    (box / "deploy" / "site" / "box").mkdir(parents=True)
    (box / "deploy" / "keys").mkdir()
    (box / "deploy" / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n", encoding="utf-8")
    for name in ("install.sh", "box-install.sh"):
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
    docker.write_text(f'#!/bin/sh\necho "docker $*" >> {tmp}/docker.log\n'
                      'case "$1 $2" in "version --format") echo 27.0 ;; esac\nexit 0\n', encoding="utf-8")  # fmt: skip
    docker.chmod(0o755)
    return b


def _base_env(tmp: Path, h: dict[str, Path]) -> dict[str, str]:
    return {"PATH": f"{_bin(tmp)}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp), **knobs(h)}


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


def _run_install_rerun(tmp: Path, box: Path, h: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    """deploy/install.sh, whole, as an installed box runs it again: a stand-in docker engine, a bundle file. It stops
    at FINISH-EARLY, or goes on to the bundle step (where the stand-in bundle is refused)."""
    bundle = tmp / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"stand-in bundle")
    return subprocess.run(["bash", str(box / "deploy" / "install.sh"), str(bundle), "--mode", "stub", "--yes"],
                          cwd=box, env=_base_env(tmp, h), capture_output=True, text=True, check=False, timeout=180)  # fmt: skip


def _run_install_first(tmp: Path, box: Path, h: dict[str, Path],
                       tb_box: str | None = None) -> subprocess.CompletedProcess[str]:  # fmt: skip
    """install.sh's FINISH-GATE block as install.sh runs it on a first install (errexit, its die, TB_ENV_SITE from
    the deploy/.env this run wrote), then the install's last banner."""
    script = (
        "set -euo pipefail\n"
        "die() { printf 'install: %s\\n' \"$*\" >&2; exit 1; }\n"
        f'ROOT={str(box)!r}\ncd "$ROOT"\n'
        "TB_ENV_SITE=\"$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)\"\n"
        + _block(INSTALL, "# FINISH-GATE (10K-4, D-1390)", "# ---- end of FINISH-GATE")
        + "\necho '  TrialBox is running.'\n"
    )
    env = _base_env(tmp, h)
    if tb_box is not None:
        env["TB_BOX"] = tb_box
    return subprocess.run(["bash", "-c", script], cwd=box, env=env, capture_output=True, text=True, check=False,
                          timeout=120)  # fmt: skip


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
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text(case))
    said = "no backup target is off the box" if case == "on_box_backups" else "is not there"
    runs = {"install.sh re-run": _run_install_rerun, "install.sh first install": _run_install_first,
            "box-install.sh": _run_box_firstrun}  # fmt: skip
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


# ------------------------------------------------------------------------------------------------ H1: off the box
@pytest.mark.parametrize(
    ("target", "said"),
    [
        ("/mnt/ram/b", "is on tmpfs"),  # memory
        ("/mnt/squash/b", "is on squashfs"),
        ("/dev/shm", "system folder /dev"),
        ("/proc", "system folder /proc"),
        ("/sys", "system folder /sys"),
        ("/run", "system folder /run"),
        ("/boot", "system folder /boot"),
        ("/home", "system folder /home"),
        ("/mnt/syspart/b", "is on the system disk (vda)"),  # another partition of the system disk
        ("/mnt/lvm/b", "is on the system disk (vda)"),  # an LVM volume on it
        ("/srv/plain", "is on the system disk (vda)"),  # a folder of /
        ("/mnt/disk2/no-such", "is not there"),
    ],
)
def test_a_backup_target_counts_off_the_box_only_on_a_share_or_another_disk(tmp_path: Path, target: str,
                                                                             said: str) -> None:  # fmt: skip
    found = _problems(tmp_path, fake_host(tmp_path), TB_BACKUP_TARGETS=target)
    assert len(found) == 1 and "no backup target is off the box" in found[0] and said in found[0], found


@pytest.mark.parametrize("target", ["/mnt/disk2/backup", "/mnt/nas/backup"])
def test_a_second_disk_or_a_share_is_off_the_box(tmp_path: Path, target: str) -> None:
    assert _problems(tmp_path, fake_host(tmp_path), TB_BACKUP_TARGETS=target) == []


def test_the_off_box_mark_alone_no_longer_counts(tmp_path: Path) -> None:
    """The nightly's rule counts a declared folder with a .trialbox-offbox file; the gate decides by the disk."""
    h = fake_host(tmp_path)
    (h["root"] / "mnt/syspart/b/.trialbox-offbox").write_text("", encoding="utf-8")
    assert _problems(tmp_path, h, TB_BACKUP_TARGETS="/mnt/syspart/b", TB_BACKUP_OFFBOX="/mnt/syspart/b")


def test_a_system_disk_that_cannot_be_told_counts_no_local_disk(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    info = (
        h["mountinfo"].read_text(encoding="utf-8").replace("252:1 / / rw - ext4 /dev/vda1", "0:99 / / rw - overlay x")
    )
    hh = finish_check.Host(info, h["sys"], str(h["root"]))
    deploy = tmp_path / "box" / "deploy"
    assert "the system disk cannot be told" in finish_check.problems(deploy, _env(), hh)[0]
    assert finish_check.problems(deploy, _env(TB_BACKUP_TARGETS="/mnt/nas/backup"), hh) == []  # a share still counts


def test_one_target_off_the_box_beside_the_install_default_is_enough(tmp_path: Path) -> None:
    assert _problems(tmp_path, fake_host(tmp_path), TB_BACKUP_TARGETS=f"{tmp_path}/box/deploy/backups,{GOOD['backup']}") == []  # fmt: skip


# ------------------------------------------------------------------------------------------------ H2: the anchor
@pytest.mark.parametrize(
    "anchor",
    ["/etc", "/root", "/proc/1/root", "/proc/self/root", "/var/lib/docker/volumes", "/", "/var", "/opt/trialbox",
     "/usr/share", "/lib64", "/tmp", "/var/tmp/x", "/dev/shm", "/home/owner"],
)  # fmt: skip
@pytest.mark.parametrize("environment", ["PRODUCTION", "VALIDATION"])
def test_a_system_folder_is_never_given_to_the_console(tmp_path: Path, anchor: str, environment: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path), TB_ENV=environment, TB_AUDIT_ANCHOR_TARGETS=anchor)
    assert found and "the audit anchor folder" in found[0] and "system folder" in found[0], found
    assert host_dir(anchor) is None  # and the page refuses it


def test_the_install_folder_its_secrets_and_the_data_folders_are_never_given_to_the_console(tmp_path: Path) -> None:
    h = fake_host(tmp_path, ("/srv/tb/deploy/secrets", "/srv/feed/in", "/srv/data/audit"))
    deploy = h["root"] / "srv" / "tb" / "deploy"  # the install folder, under the folder that stands for /
    for anchor, said in (("/srv/tb", "the install folder"), ("/srv/tb/deploy/secrets", "the install folder"),
                         ("/srv/feed", "TB_SOURCE_DIR"), ("/srv/data/audit", "TB_AUDIT_HOST_DIR")):  # fmt: skip
        env = _env(TB_AUDIT_ANCHOR_TARGETS=anchor, TB_SOURCE_DIR="/srv/feed/in", TB_AUDIT_HOST_DIR="/srv/data/audit")
        found = finish_check.problems(deploy, env, host(h))
        assert found and said in found[0], (anchor, found)


def test_a_link_in_the_anchor_s_path_is_refused(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    (h["root"] / "mnt/nas/link").symlink_to(h["root"] / "etc")
    (h["root"] / "mnt/nas/sub").mkdir()
    (h["root"] / "mnt/nas/sub/inner").symlink_to(h["root"] / "mnt/disk2", target_is_directory=True)
    for anchor, real in (("/mnt/nas/link", "/etc"), ("/mnt/nas/sub/inner/backup", "/mnt/disk2/backup")):
        found = _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS=anchor)
        assert found and f"has a link in its path: it is really {real}" in found[0], (anchor, found)


@pytest.mark.parametrize(
    ("anchor", "said"),
    [("/mnt/disk2", "the log folder"), ("/mnt/disk2/backup/x", "a backup target"), ("/mnt/disk2/logs", "log folder"),
     ("/mnt/ram/b", "is on tmpfs")],
)  # fmt: skip
def test_the_anchor_holds_no_backup_no_log_and_is_on_a_disk_or_a_share(tmp_path: Path, anchor: str, said: str) -> None:
    h = fake_host(tmp_path)
    (h["root"] / "mnt/disk2/backup/x").mkdir()
    found = _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS=anchor)
    assert found and said in found[0], found


def test_the_anchor_may_be_on_a_local_disk(tmp_path: Path) -> None:
    """The card says "unmountable": a folder of its own on a real disk is allowed (the preflight shows it amber)."""
    assert _problems(tmp_path, fake_host(tmp_path), TB_AUDIT_ANCHOR_TARGETS="/srv/plain") == []


def test_no_anchor_folder_is_refused_in_production_only(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    assert "no audit anchor folder" in _problems(tmp_path, h, TB_AUDIT_ANCHOR_TARGETS="")[0]
    assert _problems(tmp_path, h, TB_ENV="VALIDATION", TB_AUDIT_ANCHOR_TARGETS="", TB_BACKUP_TARGETS="") == []


# ------------------------------------------------------------------------------------------------ L8: the log folder
@pytest.mark.parametrize(("log", "said"), [("/tmp/logs", "system folder"), ("/mnt/ram/b", "tmpfs"),
                                           ("/mnt/disk2/backup", "a backup target")])  # fmt: skip
def test_a_log_folder_that_breaks_the_rule_is_refused(tmp_path: Path, log: str, said: str) -> None:
    found = _problems(tmp_path, fake_host(tmp_path), TB_LOG_DIR=log)
    assert found and "the log folder" in found[0] and said in found[0], found


def test_the_install_s_own_log_folder_and_audit_archive_stay_allowed(tmp_path: Path) -> None:
    h = fake_host(tmp_path, ("/srv/tb/deploy/logs/audit-archive",))
    deploy = h["root"] / "srv" / "tb" / "deploy"
    env = _env(TB_LOG_DIR="/srv/tb/deploy/logs", TB_AUDIT_ARCHIVE_DIR="/srv/tb/deploy/logs/audit-archive")
    assert finish_check.problems(deploy, env, host(h)) == []


# ------------------------------------------------------------------------------------------------ L2, L3: TB_ENV
@pytest.mark.parametrize("written", ['"PRODUCTION"', "production", " Production\r", ""])
def test_install_sh_reads_tb_env_as_the_check_does(tmp_path: Path, written: str) -> None:
    """A hand-written TB_ENV the tools read as PRODUCTION does not skip install.sh's gate."""
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text("on_box_backups").replace("TB_ENV=PRODUCTION", f"TB_ENV={written}"))
    r = _run_install_first(tmp_path, box, h)
    assert r.returncode == 1 and "TrialBox is running." not in r.stdout, r.stderr


def test_the_box_s_own_install_before_its_set_up_is_not_checked(tmp_path: Path) -> None:
    """TB_BOX=1: the owner has not chosen the folders yet (the first-run set-up comes after the stack is up)."""
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text("on_box_backups"))
    assert _run_install_first(tmp_path, box, h, tb_box="1").returncode == 0
    assert _run_install_first(tmp_path, box, h, tb_box="0").returncode == 1  # the unattended install is checked


def test_a_validation_install_is_refused_only_for_its_anchor(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text("on_box_backups", environment="VALIDATION"))
    assert _run_install_first(tmp_path, box, h).returncode == 0
    (box / "deploy" / ".env").write_text(_env_text("good", "VALIDATION").replace(GOOD["anchor"], "/etc"),
                                         encoding="utf-8")  # fmt: skip
    r = _run_install_first(tmp_path, box, h)
    assert r.returncode == 1 and "system folder /etc" in r.stderr


# ------------------------------------------------------------------------------------------------ M1: before changes
def test_the_re_run_check_comes_before_the_bundle_step_and_changes_nothing(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
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


def test_the_first_install_refusal_says_what_was_written(tmp_path: Path) -> None:
    r = _run_install_first(tmp_path, _box(tmp_path, _env_text("on_box_backups")), fake_host(tmp_path))
    last = r.stderr.strip().splitlines()[-1]
    assert "the stack was not started" in last and "goes on from what this run wrote" in last
    assert "nothing" not in last  # no claim that nothing was written


def test_install_sh_runs_the_check_without_a_value_of_the_site_in_its_command() -> None:
    for start, end in (("# FINISH-EARLY (10K-4", "# ---- end of FINISH-EARLY"),
                       ("# FINISH-GATE (10K-4", "# ---- end of FINISH-GATE")):  # fmt: skip
        block = _block(INSTALL, start, end)
        code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
        assert 'python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy"' in code
        assert "eval" not in code and "sh -c" not in code and "envget" not in code


# ------------------------------------------------------------------------------------------------ M3, L5: box path
def test_a_box_refusal_says_how_to_correct_a_folder(tmp_path: Path) -> None:
    r = _run_box_firstrun(tmp_path, _box(tmp_path, _env_text("on_box_backups")), fake_host(tmp_path))
    assert r.returncode == 1
    assert "set TB_BACKUP_TARGETS in deploy/.env" in r.stderr and "TB_BACKUP_OFFBOX to the same folder" in r.stderr
    assert "first-run page does not open again" in r.stderr and "box-install.sh --firstrun" in r.stderr


def test_box_install_asks_the_console_image_to_read_the_anchor_then_mounts_it(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
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
    again = _run_box_firstrun(tmp_path, box, h)  # a rerun changes nothing
    assert again.returncode == 0 and anchors.read_env(box / "deploy" / ".env")["COMPOSE_FILE"] == env["COMPOSE_FILE"]


def test_box_install_stops_when_the_console_image_cannot_read_the_anchor(tmp_path: Path) -> None:
    box = _box(tmp_path, _env_text("good"))
    r = _run_box_firstrun(tmp_path, box, fake_host(tmp_path), docker_rc=1)
    assert r.returncode == 1 and "the console's user cannot read" in r.stderr
    assert "compose up" not in _calls(tmp_path) and not (box / "deploy" / anchors.NAME).exists()


def test_box_install_finishes_once_the_share_is_mounted(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text("unmountable_anchor"))
    assert _run_box_firstrun(tmp_path, box, h).returncode == 1
    (h["root"] / "mnt/nas/no-such-share").mkdir()
    r = _run_box_firstrun(tmp_path, box, h)
    assert r.returncode == 0 and "TrialBox is ready" in r.stdout, r.stderr[-2000:]


def test_the_unattended_box_install_is_left_to_install_sh() -> None:
    gate = BOX_INSTALL.index("# FINISH-GATE (10K-4, D-1390)")
    block = BOX_INSTALL[gate : BOX_INSTALL.index('HOST="$(json_get', gate)]
    assert 'if [ -z "$OWNER" ]; then' in block and "--mount-anchors" in block and "--print-anchors" in block
    assert BOX_INSTALL.index("box_py apply") < gate < BOX_INSTALL.index("up -d --wait")


# ------------------------------------------------------------------------------------------------ L1: no PyYAML
def test_a_host_python_without_yaml_gets_a_true_message(tmp_path: Path) -> None:
    """``python3 -S``: no site packages, so no yaml. The check itself needs none; writing the mount says so."""
    h = fake_host(tmp_path)
    box = _box(tmp_path, _env_text("good", "VALIDATION").replace(f"TB_AUDIT_ANCHOR_TARGETS={GOOD['anchor']}\n", ""))
    env = {"PATH": "/usr/bin:/bin", **knobs(h)}
    cmd = [sys.executable, "-S", "-m", "tools.trialbox", "finish-check", "--deploy", str(box / "deploy")]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    (box / "deploy" / ".env").write_text(_env_text("good"), encoding="utf-8")
    r = subprocess.run([*cmd, "--mount-anchors"], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "python3-yaml" in r.stderr, r.stderr


# ------------------------------------------------------------------------------------------------ L4: the .env write
def test_mount_anchors_keeps_the_file_as_it_was_but_its_one_line(tmp_path: Path) -> None:
    h = fake_host(tmp_path)
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    anchor = h["root"] / "mnt/nas/audit"  # mount_anchors runs once the check has passed: a real folder here
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
        ("/run/x", None), ("/tmp", None), ("/var/tmp/x", None),
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
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == "/srv/disk2"
    assert env["TB_AUDIT_ANCHOR_TARGETS"] == "/mnt/audit" and env["TB_LOG_DIR"] == "/srv/logs"
    again, _ = parse(a.to_json(), disks=("/dev/sdb",))  # the apply step reads the file the page wrote
    assert again == a
    later, _ = parse({**OWNER, "backup_kind": "later", "backup_dir": "/srv/disk2"})
    assert later is not None and later.backup_dir == ""


# ------------------------------------------------------------------------------------------------ M4: the runbook
def test_runbook_05_says_which_steps_now_stop_and_what_is_checked() -> None:
    text = (ROOT / "docs/runbook/05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    para = " ".join(text[text.index("**A PRODUCTION install needs a backup target off the box") :].split())
    for words in ("runs `deploy/install.sh` again", "(02,", "05, after a restore", "12, the TLS check",
                  "another partition of it is not enough", "TB_BACKUP_OFFBOX", "box-install.sh --firstrun",
                  "the console is given, read-only"):  # fmt: skip
        assert words in para, words
