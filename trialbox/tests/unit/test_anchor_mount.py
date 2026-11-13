"""ANCHOR-MOUNT (D-638): the console of an installed box reads the signed heads. The anchor folders of
``TB_AUDIT_ANCHOR_TARGETS`` are host paths; compose cleared the name for the console because it did not mount them,
so the audit page's Verify never checked a signed head on a box. The installer now writes a compose file that
mounts each folder into the console, read-only, and gives it the name; doctor says when it is missing or old."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit

from tools import network_sheet
from tools.trialbox import anchors, doctor

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
BASE = "deploy/docker-compose.yml"
MADE = "deploy/site/compose.anchors.yml"

pytestmark = pytest.mark.nodb


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Any]:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    shutil.copy(ROOT / BASE, deploy / "docker-compose.yml")
    a, b = tmp_path / "mnt" / "hospital share", tmp_path / "second" / "heads"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    env = {"TB_AUDIT_ANCHOR_TARGETS": os.pathsep.join([str(a), str(b)])}
    return {"root": tmp_path, "deploy": deploy, "a": a, "b": b, "env": env}


def _services(box: dict[str, Any], *more: str) -> dict[str, Any]:
    got: dict[str, Any] = network_sheet.load([BASE, *more], root=box["root"])["services"]
    return got


def test_compose_alone_gives_the_console_no_anchor_folder(box: dict[str, Any]) -> None:
    """Why the card: on the shipped compose file the console has neither the name nor a folder."""
    c = _services(box)["console"]
    assert c["environment"]["TB_AUDIT_ANCHOR_TARGETS"] == ""
    assert not [v for v in c["volumes"] if "anchor" in str(v)]


def test_the_console_of_an_installed_box_gets_the_name_and_each_folder_read_only(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    assert path == box["root"] / MADE
    before, after = _services(box), _services(box, MADE)
    c = after["console"]
    inside = [Path(p) for p in c["environment"]["TB_AUDIT_ANCHOR_TARGETS"].split(os.pathsep)]
    assert [p.name for p in inside] == ["hospital share", "heads"]  # the page shows the folder's own name
    assert audit.anchor_targets(c["environment"]) == inside
    mounts = [v for v in c["volumes"] if isinstance(v, dict)]
    assert [(m["source"], m["target"]) for m in mounts] == [
        (str(box["a"]), str(inside[0])),
        (str(box["b"]), str(inside[1])),
    ]
    for m in mounts:
        assert m["type"] == "bind" and m["read_only"] is True
        assert m["bind"] == {"create_host_path": False}  # a folder that is not there is not made on the host
    assert all(str(p).startswith("/anchors/") for p in inside)  # never over a folder of the image
    assert {k: v for k, v in after.items() if k != "console"} == {k: v for k, v in before.items() if k != "console"}
    assert len(c["volumes"]) == len(before["console"]["volumes"]) + 2  # added to the console's own, none replaced
    rest = {k: v for k, v in c.items() if k not in ("environment", "volumes")}
    assert rest == {k: v for k, v in before["console"].items() if k not in ("environment", "volumes")}
    assert {k: v for k, v in c["environment"].items() if k != "TB_AUDIT_ANCHOR_TARGETS"} == {
        k: v for k, v in before["console"]["environment"].items() if k != "TB_AUDIT_ANCHOR_TARGETS"
    }


def test_two_folders_of_one_name_are_two_places_and_a_folder_named_twice_is_one(tmp_path: Path) -> None:
    a, b = tmp_path / "x" / "heads", tmp_path / "y" / "heads"
    got = anchors.plan({"TB_AUDIT_ANCHOR_TARGETS": f"{a}:{b}:{a}"})
    assert [h for h, _ in got] == [str(a), str(b)]
    assert len({i for _, i in got}) == 2 and all(Path(i).name == "heads" for _, i in got)


@pytest.mark.parametrize("bad", ["relative/heads", "/mnt/../etc", "/mnt/a\nb", "/", "/mnt/he\x00ads", "/mnt/./x"])
def test_a_folder_that_is_not_a_plain_absolute_path_is_refused(bad: str) -> None:
    with pytest.raises(anchors.AnchorError):
        anchors.plan({"TB_AUDIT_ANCHOR_TARGETS": bad})


def test_a_dollar_in_a_folder_name_is_not_a_compose_variable(box: dict[str, Any]) -> None:
    odd = box["root"] / "mnt" / "share$HOME ${X}"
    text = anchors.compose_text(anchors.plan({"TB_AUDIT_ANCHOR_TARGETS": str(odd)}))
    assert "share$$HOME $${X}" in text and "share$HOME" not in text


def test_no_folder_no_file_and_an_old_file_is_taken_away(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    assert path is not None and path.is_file()
    assert anchors.write(box["deploy"], {}) is None and not path.exists()


def test_the_file_is_for_its_owner_to_change_only(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    assert path is not None and path.stat().st_mode & 0o022 == 0  # every later compose command reads it, as root


# ---------------------------------------------------------------------------------------------------- install.sh
def _block() -> str:
    start = INSTALL.index("# ANCHOR-MOUNT (D-638)")
    return INSTALL[start : INSTALL.index("\nfi\n", start) + 4]


def _installer(box: dict[str, Any], targets: str) -> subprocess.CompletedProcess[str]:
    (box["deploy"] / ".env").write_text(f"TB_ENV=TEST\nTB_AUDIT_ANCHOR_TARGETS={targets}\n", encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{box["root"]}"\ncd "$ROOT"\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'COMPOSE=(docker compose); FILES="$ROOT/deploy/docker-compose.yml"\n'
        f'{_block()}\nprintf "%s\\n" "$FILES" "${{COMPOSE[@]}}"\n'
    )
    env = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'libs'}"}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def test_the_installer_adds_the_file_to_this_and_every_later_compose_command(box: dict[str, Any]) -> None:
    r = _installer(box, box["env"]["TB_AUDIT_ANCHOR_TARGETS"])
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    made = box["root"] / MADE
    assert made.is_file()
    assert out[0] == f"{box['root']}/deploy/docker-compose.yml:{made}"  # what goes to COMPOSE_FILE in deploy/.env
    assert out[-2:] == ["-f", str(made)]


def test_the_installer_of_a_box_with_no_anchor_folder_adds_nothing(box: dict[str, Any]) -> None:
    (box["root"] / MADE).write_text("services: {}\n", encoding="utf-8")  # from an earlier install with a folder
    r = _installer(box, "")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [f"{box['root']}/deploy/docker-compose.yml", "docker", "compose"]
    assert not (box["root"] / MADE).exists()


def test_the_installer_stops_on_a_folder_it_cannot_mount(box: dict[str, Any]) -> None:
    r = _installer(box, "relative/heads")
    assert r.returncode == 1 and "TB_AUDIT_ANCHOR_TARGETS" in r.stderr and "relative/heads" in r.stderr


def test_the_block_runs_before_the_compose_file_list_is_kept() -> None:
    assert INSTALL.index("# ANCHOR-MOUNT (D-638)") < INSTALL.index('echo "COMPOSE_FILE=$FILES" >> deploy/.env')


# -------------------------------------------------------------------------------------------------------- doctor
def _doctor(box: dict[str, Any], **env: str) -> doctor.Check:
    return doctor.check_anchor_mount(doctor.DoctorInputs(env={**box["env"], **env}, deploy=box["deploy"]))


def test_doctor_passes_a_box_whose_console_mounts_the_folders(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml:{path}")
    assert (c.name, c.status) == ("anchor_mount", "PASS"), c.detail


def test_doctor_says_when_the_folders_are_set_and_not_mounted(box: dict[str, Any]) -> None:
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml")  # a box installed before this release
    assert c.status == "WARN" and "install.sh" in c.detail and "audit page" in c.detail
    anchors.write(box["deploy"], box["env"])
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml")  # written, not in the compose file list
    assert c.status == "WARN" and "COMPOSE_FILE" in c.detail


def test_doctor_says_when_the_folders_changed_after_the_install(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml:{path}", TB_AUDIT_ANCHOR_TARGETS=str(box["a"]))
    assert c.status == "WARN" and "install.sh" in c.detail


def test_doctor_has_nothing_to_say_without_an_anchor_folder(box: dict[str, Any]) -> None:
    c = doctor.check_anchor_mount(doctor.DoctorInputs(env={}, deploy=box["deploy"]))
    assert c.status == "PASS"  # check audit_heads is the one that fails a box with no folder
