"""10K-4 (D-1390; review 18, SO-4): the backup, audit anchor and log folders are chosen in the box's first-run
set-up, and a PRODUCTION install refuses to finish with its backups only on the box's own disks or with an audit
anchor folder that cannot be mounted.

The refusal is one check, ``tools/trialbox/finish_check.py`` (``python3 -m tools.trialbox finish-check``), run by
``deploy/install.sh`` before it starts the stack (the IT form and the box's unattended install; block FINISH-GATE)
and by ``deploy/box-install.sh`` after the owner's answers are applied, before the restart and the last line. The
installers run here for real (install.sh's block as it stands in the file; box-install.sh whole, after the set-up,
with stand-ins only for compose and the host check), with the host's ``python3`` reading the real mount table: a
folder of the test's own disk is "this box", and a folder declared off the box counts when it carries the
``.trialbox-offbox`` file, as ``backup_schedule`` rules (no mount needs root here)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common.box_answers import host_dir, parse

from tools.box import plan as bp
from tools.trialbox import anchors, finish_check
from tools.trialbox.backup_schedule import OFFBOX_MARKER

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
FINISHED = {"install.sh": "TrialBox is running.", "box-install.sh": "TrialBox is ready"}
OWNER = {
    "site_name": "Site A (synthetic)", "tz": "Asia/Tokyo", "owner_full_name": "Dr Owner", "owner_username": "owner",
    "owner_email": "owner@hospa.test", "backup_kind": "second_disk", "backup_disk": "/dev/sdb",
}  # fmt: skip


def _folders(tmp: Path) -> dict[str, Path]:
    """A backup folder declared off the box (the mark), an on-box one, and an anchor folder that is there."""
    off, on, anchor = tmp / "off-box-backup", tmp / "on-box-backup", tmp / "anchor"
    for d in (off, on, anchor):
        d.mkdir(parents=True, exist_ok=True)
    (off / OFFBOX_MARKER).write_text("", encoding="utf-8")
    return {"off": off, "on": on, "anchor": anchor}


def _env_text(tmp: Path, case: str, environment: str = "PRODUCTION") -> str:
    """deploy/.env of a box: good, or broken in one of the card's two ways."""
    f = _folders(tmp)
    backup = f["on"] if case == "on_box_backups" else f["off"]
    anchor = tmp / "no-such-share" if case == "unmountable_anchor" else f["anchor"]
    return (f"TB_ENV={environment}\nTB_BACKUP_TARGETS={backup}\nTB_BACKUP_OFFBOX={f['off']}\n"
            f"TB_AUDIT_ANCHOR_TARGETS={anchor}\nCOMPOSE_FILE=deploy/docker-compose.yml\n")  # fmt: skip


def _box(tmp: Path, env_text: str) -> Path:
    """An install folder: the two installers copied, the code linked, deploy/.env as given."""
    box = tmp / "box"
    (box / "deploy" / "site" / "box").mkdir(parents=True)
    for name in ("install.sh", "box-install.sh"):
        shutil.copy2(ROOT / "deploy" / name, box / "deploy" / name)
    for name in ("libs", "services", "tools"):
        (box / name).symlink_to(ROOT / name)
    (box / "deploy" / ".env").write_text(env_text, encoding="utf-8")
    (box / "deploy" / ".env").chmod(0o600)
    return box


def _bin(tmp: Path) -> Path:
    """The host's python3 is this interpreter (it has PyYAML, as install.sh's HOST-PYTHON block requires)."""
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    py = b / "python3"
    if not py.exists():
        py.symlink_to(sys.executable)
    return b


def _gate_block() -> str:
    start = INSTALL.index("# FINISH-GATE (10K-4, D-1390)")
    return INSTALL[start : INSTALL.index("# ---- end of FINISH-GATE", start)]


def _run_install(tmp: Path, box: Path, tb_box: str | None = None) -> subprocess.CompletedProcess[str]:
    """install.sh's FINISH-GATE block as install.sh runs it (errexit, its die, TB_ENV_SITE from deploy/.env), then the
    install's last banner."""
    script = (
        "set -euo pipefail\n"
        "die() { printf 'install: %s\\n' \"$*\" >&2; exit 1; }\n"
        f'ROOT={str(box)!r}\ncd "$ROOT"\n'
        "TB_ENV_SITE=\"$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)\"\n"
        + _gate_block()
        + "\necho '  TrialBox is running.'\n"
    )
    env = {"PATH": f"{_bin(tmp)}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp)}
    if tb_box is not None:
        env["TB_BOX"] = tb_box
    return subprocess.run(["bash", "-c", script], cwd=box, env=env, capture_output=True, text=True, check=False,
                          timeout=120)  # fmt: skip


def _run_box_firstrun(tmp: Path, box: Path) -> subprocess.CompletedProcess[str]:
    """box-install.sh --firstrun after the owner's answers were applied (deploy/site/box/applied): what follows the
    apply, for real, with stand-ins for compose and the host check."""
    site = box / "deploy" / "site" / "box"
    (site / "answers.json").write_text('{"tls_hostname": "trialbox.local", "tz": "Asia/Tokyo"}\n', encoding="utf-8")
    (site / "hardware.json").write_text('{"tpm": true}\n', encoding="utf-8")
    (site / "applied").write_text("2026-11-21T00:00:00Z\n", encoding="utf-8")
    stubs = tmp / "stubs"
    stubs.mkdir(exist_ok=True)
    for name in ("compose", "hostcheck"):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {tmp}/calls.log\n', encoding="utf-8")
        (stubs / name).chmod(0o755)
    env = {
        "PATH": f"{_bin(tmp)}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp), "TB_BOX_NO_ROOT": "1",
        "TB_BOX_PY": sys.executable, "TB_BOX_COMPOSE": str(stubs / "compose"),
        "TB_BOX_HOST_CHECK": str(stubs / "hostcheck"), "TB_ISSUE_DIR": str(tmp / "issue.d"),
        "TB_FIRSTRUN_HOST_DIR": str(tmp / "firstrun"), "TB_SYSTEMD": "0", "TB_BOX_WSL2": "0",
    }  # fmt: skip
    return subprocess.run(["bash", str(box / "deploy" / "box-install.sh"), "--firstrun"], cwd=tmp, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=120)  # fmt: skip


def _run(installer: str, tmp: Path, box: Path) -> subprocess.CompletedProcess[str]:
    return _run_install(tmp, box) if installer == "install.sh" else _run_box_firstrun(tmp, box)


# ------------------------------------------------------------------------------------------------ the card's promise
@pytest.mark.parametrize("installer", ["install.sh", "box-install.sh"])
@pytest.mark.parametrize("case", ["on_box_backups", "unmountable_anchor"])
def test_a_production_install_exits_before_finished_with_on_box_backups_or_an_unmountable_anchor(
    tmp_path: Path, installer: str, case: str
) -> None:
    """The card's proof: "the install test exits before 'finished' in both cases", for the IT form (and the box's
    unattended install: install.sh) and for the box after its first-run set-up (box-install.sh). The same box with a
    backup off the box and its anchor folder there finishes."""
    box = _box(tmp_path, _env_text(tmp_path, case))
    r = _run(installer, tmp_path, box)
    assert r.returncode == 1, r.stdout[-2000:] + r.stderr[-2000:]
    assert FINISHED[installer] not in r.stdout
    said = "every backup target is on the box's own disks" if case == "on_box_backups" else "is not there"
    assert said in r.stderr and "finish-check:" in r.stderr, r.stderr
    if installer == "box-install.sh":  # nothing restarted on the refused settings; the way on is said
        assert not (tmp_path / "calls.log").exists() and "box-install.sh --firstrun" in r.stderr
    good = _box(tmp_path / "good", _env_text(tmp_path / "good", "good"))
    r = _run(installer, tmp_path / "good", good)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert FINISHED[installer] in r.stdout


# ------------------------------------------------------------------------------------------------ the check
def _env(tmp: Path, **over: str) -> dict[str, str]:
    f = _folders(tmp)
    base = {"TB_ENV": "PRODUCTION", "TB_BACKUP_TARGETS": str(f["off"]), "TB_BACKUP_OFFBOX": str(f["off"]),
            "TB_AUDIT_ANCHOR_TARGETS": str(f["anchor"])}  # fmt: skip
    return {k: v for k, v in (base | over).items() if v is not None}


def test_a_ready_production_box_has_no_problem(tmp_path: Path) -> None:
    assert finish_check.problems(tmp_path, _env(tmp_path)) == []


@pytest.mark.parametrize(
    ("over", "said"),
    [
        ({"TB_BACKUP_TARGETS": ""}, "no backup target"),
        ({"TB_BACKUP_OFFBOX": ""}, "every backup target is on the box's own disks"),  # not declared: this box
        ({"TB_BACKUP_TARGETS": "/var/tmp/no-such-second-disk-10k4"}, "on the box's own disks"),  # not mounted
        ({"TB_AUDIT_ANCHOR_TARGETS": ""}, "no audit anchor folder"),
        ({"TB_AUDIT_ANCHOR_TARGETS": "/var/tmp/no-such-share-10k4"}, "is not there"),
        ({"TB_AUDIT_ANCHOR_TARGETS": "relative/folder"}, "cannot be mounted"),
        ({"TB_AUDIT_ANCHOR_TARGETS": "/srv/../etc"}, "cannot be mounted"),
    ],
)
def test_each_way_a_production_box_may_not_finish(tmp_path: Path, over: dict[str, str], said: str) -> None:
    found = finish_check.problems(tmp_path, _env(tmp_path, **over))
    assert len(found) == 1 and said in found[0], found


def test_a_backup_on_the_box_beside_one_off_it_is_enough(tmp_path: Path) -> None:
    f = _folders(tmp_path)
    env = _env(tmp_path, TB_BACKUP_TARGETS=f"{f['on']},{f['off']}")  # backup_schedule: comma or space
    assert finish_check.problems(tmp_path, env) == []


@pytest.mark.parametrize("environment", ["VALIDATION", "TEST", "DEV"])
def test_outside_production_nothing_is_refused(tmp_path: Path, environment: str) -> None:
    env = _env(tmp_path, TB_ENV=environment, TB_BACKUP_TARGETS="", TB_AUDIT_ANCHOR_TARGETS="")
    assert finish_check.problems(tmp_path, env) == []


def test_no_environment_is_production(tmp_path: Path) -> None:
    """D-127: a box is PRODUCTION unless TB_ENV says otherwise."""
    env = _env(tmp_path, TB_ENV="", TB_AUDIT_ANCHOR_TARGETS="")
    assert [p.split(":")[0] for p in finish_check.problems(tmp_path, env)] == ["no audit anchor folder"]


def test_the_check_writes_nothing(tmp_path: Path) -> None:
    box = _box(tmp_path, _env_text(tmp_path, "on_box_backups"))
    before = sorted(p.relative_to(box) for p in (box / "deploy").rglob("*"))
    assert finish_check.main_action(box / "deploy") == 1
    assert sorted(p.relative_to(box) for p in (box / "deploy").rglob("*")) == before


# ------------------------------------------------------------------------------------------------ install.sh's block
def test_the_box_s_own_install_before_its_set_up_is_not_checked(tmp_path: Path) -> None:
    """TB_BOX=1: the owner has not chosen the folders yet (the first-run set-up comes after the stack is up)."""
    box = _box(tmp_path, _env_text(tmp_path, "on_box_backups"))
    r = _run_install(tmp_path, box, tb_box="1")
    assert r.returncode == 0 and "TrialBox is running." in r.stdout, r.stderr
    r = _run_install(tmp_path, box, tb_box="0")  # the box's unattended install: install.sh checks
    assert r.returncode == 1 and "TrialBox is running." not in r.stdout


def test_a_validation_install_is_not_refused(tmp_path: Path) -> None:
    box = _box(tmp_path, _env_text(tmp_path, "on_box_backups", environment="VALIDATION"))
    r = _run_install(tmp_path, box)
    assert r.returncode == 0 and "TrialBox is running." in r.stdout, r.stderr


def test_the_gate_comes_before_the_stack_starts_and_after_the_backup_default() -> None:
    gate = INSTALL.index("# FINISH-GATE (10K-4, D-1390)")
    default = INSTALL.index("grep -q '^TB_BACKUP_TARGETS=' deploy/.env ||")
    assert default < gate < INSTALL.index('say "starting the stack')
    assert "TB_ENV_SITE=" in INSTALL[:gate]


def test_install_sh_runs_the_check_without_a_value_of_the_site_in_its_command() -> None:
    """The block's one command names fixed words and the quoted install folder; nothing from deploy/.env or the owner
    is put into a command line (the check reads the file itself)."""
    block = _gate_block()
    code = [ln for ln in block.splitlines() if not ln.lstrip().startswith("#")]
    assert 'python3 -m tools.trialbox finish-check --deploy "$ROOT/deploy"' in "\n".join(code)
    assert "eval" not in block and "sh -c" not in block and "envget" not in block


# ------------------------------------------------------------------------------------------------ box-install.sh
def test_box_install_mounts_the_chosen_anchor_folder_into_the_console(tmp_path: Path) -> None:
    box = _box(tmp_path, _env_text(tmp_path, "good"))
    r = _run_box_firstrun(tmp_path, box)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    made = box / "deploy" / anchors.NAME
    assert made.is_file()
    env = anchors.read_env(box / "deploy" / ".env")
    assert env["COMPOSE_FILE"] == f"deploy/docker-compose.yml{os.pathsep}{made}"
    assert anchors.problem(box / "deploy", env) == ""  # doctor's anchor_mount check is content
    assert stat.S_IMODE((box / "deploy" / ".env").stat().st_mode) == 0o600
    assert "compose up -d --wait" in (tmp_path / "calls.log").read_text(encoding="utf-8")
    again = _run_box_firstrun(tmp_path, box)  # a rerun changes nothing
    assert again.returncode == 0 and anchors.read_env(box / "deploy" / ".env")["COMPOSE_FILE"] == env["COMPOSE_FILE"]


def test_box_install_finishes_once_the_share_is_mounted(tmp_path: Path) -> None:
    """Refused, then the folder is there (IT mounted the share): --firstrun again finishes."""
    box = _box(tmp_path, _env_text(tmp_path, "unmountable_anchor"))
    assert _run_box_firstrun(tmp_path, box).returncode == 1
    (tmp_path / "no-such-share").mkdir()
    r = _run_box_firstrun(tmp_path, box)
    assert r.returncode == 0 and "TrialBox is ready" in r.stdout, r.stderr[-2000:]


def test_the_unattended_box_install_is_left_to_install_sh() -> None:
    text = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
    gate = text.index("# FINISH-GATE (10K-4, D-1390)")
    block = text[gate : text.index("\nfi\n", gate)]
    assert 'if [ -z "$OWNER" ]; then' in block and "--mount-anchors" in block
    assert text.index("box_py apply") < gate < text.index("up -d --wait") < text.index("TrialBox is ready")


# ------------------------------------------------------------------------------------------------ mount_anchors
def test_mount_anchors_keeps_the_other_files_and_takes_the_anchor_file_away_when_none_is_set(tmp_path: Path) -> None:
    f = _folders(tmp_path)
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    env_file = deploy / ".env"
    env_file.write_text(f"POSTGRES_PASSWORD=x\nTB_AUDIT_ANCHOR_TARGETS={f['anchor']}\n"
                        "COMPOSE_FILE=/opt/t/deploy/docker-compose.yml:/opt/t/deploy/docker-compose.box.yml\n",
                        encoding="utf-8")  # fmt: skip
    env_file.chmod(0o644)  # a wrong mode is not kept: the file is written owner-only
    assert finish_check.mount_anchors(deploy) == ""
    env = anchors.read_env(env_file)
    assert env["COMPOSE_FILE"].split(os.pathsep) == [
        "/opt/t/deploy/docker-compose.yml", "/opt/t/deploy/docker-compose.box.yml", str(deploy / anchors.NAME),
    ]  # fmt: skip
    assert env["POSTGRES_PASSWORD"] == "x" and stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert not [p for p in deploy.iterdir() if p.name.startswith(".env.")]  # no temporary file left
    env_file.write_text(env_file.read_text(encoding="utf-8").replace(f"TB_AUDIT_ANCHOR_TARGETS={f['anchor']}\n", ""),
                        encoding="utf-8")  # fmt: skip
    assert finish_check.mount_anchors(deploy) == ""
    assert anchors.read_env(env_file)["COMPOSE_FILE"].split(os.pathsep) == [
        "/opt/t/deploy/docker-compose.yml", "/opt/t/deploy/docker-compose.box.yml",
    ]  # fmt: skip
    assert not (deploy / anchors.NAME).exists()


def test_mount_anchors_guesses_no_compose_file_and_refuses_a_missing_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    text = f"TB_AUDIT_ANCHOR_TARGETS={_folders(tmp_path)['anchor']}\n"
    (deploy / ".env").write_text(text, encoding="utf-8")
    assert finish_check.mount_anchors(deploy) == ""  # no COMPOSE_FILE line: none is made up, the note says why
    assert "no COMPOSE_FILE line" in capsys.readouterr().out
    assert (deploy / ".env").read_text(encoding="utf-8") == text and not (deploy / anchors.NAME).exists()
    (deploy / ".env").write_text("TB_AUDIT_ANCHOR_TARGETS=/var/tmp/no-such-share-10k4\nCOMPOSE_FILE=a.yml\n",
                                 encoding="utf-8")  # fmt: skip
    assert "no such folder" in finish_check.mount_anchors(deploy)
    assert not (deploy / anchors.NAME).exists()


# ------------------------------------------------------------------------------------------------ the answers
@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("", ""), ("/mnt/trialbox-audit", "/mnt/trialbox-audit"), ("/srv/backup/", "/srv/backup"),
        ("/", None), ("relative", None), ("/srv/../etc", None), ("/srv/./x", None), ("/srv//x", None),
        ("/a b", None), ("/a$(id)", None), ('/a"b', None), ("/a\nTB_ENV=DEV", None), ("/" + "a" * 255, None),
    ],
)  # fmt: skip
def test_a_folder_is_one_plain_full_path(raw: str, want: str | None) -> None:
    assert host_dir(raw) == want


def test_the_folders_reach_the_plan_and_the_defaults_stay(tmp_path: Path) -> None:
    hw = bp.Hardware(arch="x86_64", cpu_count=32, ram_gib=128.0, disk_free_gib=1800.0, gpu_name="", gpu_mem_gib=0.0,
                     tpm=True, disks=(bp.Disk("/dev/sdb", 3726.0, "sata"),), lan="192.0.2.0/24", hostname="box1",
                     host_tz="Asia/Tokyo")  # fmt: skip
    a, problems = parse(OWNER, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, hw).env_extra
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == bp.SECOND_DISK_MOUNT
    assert "TB_AUDIT_ANCHOR_TARGETS" not in env and "TB_LOG_DIR" not in env  # not asked: as before
    assert "backup_dir" not in a.to_json() and "anchor_dir" not in a.to_json()
    chosen = {"backup_dir": "/srv/disk2", "anchor_dir": "/mnt/audit", "log_dir": "/srv/logs"}
    a, problems = parse({**OWNER, **chosen}, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, hw).env_extra
    assert env["TB_BACKUP_TARGETS"] == env["TB_BACKUP_OFFBOX"] == "/srv/disk2"
    assert env["TB_AUDIT_ANCHOR_TARGETS"] == "/mnt/audit" and env["TB_LOG_DIR"] == "/srv/logs"
    again, _ = parse(a.to_json(), disks=("/dev/sdb",))  # the apply step reads the file the page wrote
    assert again == a
    share, _ = parse({**OWNER, "backup_kind": "share", "backup_share": "//nas/tb", "backup_dir": "/mnt/nas"})
    assert share is not None and bp.plan(share, hw).env_extra["TB_BACKUP_TARGETS"] == "/mnt/nas"
    assert "TB_BACKUP_OFFBOX" not in bp.plan(share, hw).env_extra  # a share is judged by the mount table
    later, _ = parse({**OWNER, "backup_kind": "later", "backup_dir": "/srv/disk2"})
    assert later is not None and later.backup_dir == "" and "TB_BACKUP_TARGETS" not in bp.plan(later, hw).env_extra
    _, problems = parse({**OWNER, "anchor_dir": "/srv/../etc", "log_dir": "logs"})
    assert sorted((p.field, p.code) for p in problems) == [("anchor_dir", "host_dir"), ("log_dir", "host_dir")]
