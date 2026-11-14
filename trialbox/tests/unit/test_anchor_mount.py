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


def _installer(
    box: dict[str, Any], targets: str, *, docker: str = "return 0", python: bool = True
) -> subprocess.CompletedProcess[str]:
    """The installer's block as it stands in install.sh, with the names it uses from earlier lines; ``docker`` is
    the body of a stand-in that records how it was called."""
    (box["deploy"] / ".env").write_text(f"TB_ENV=TEST\nTB_AUDIT_ANCHOR_TARGETS={targets}\n", encoding="utf-8")
    hide = 'command() { [ "$2" = python3 ] && return 1; builtin command "$@"; }\n' if not python else ""
    script = (
        "set -euo pipefail\n"
        f'ROOT="{box["root"]}"\ncd "$ROOT"\nIMAGE_PY=trialbox-py:test\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        f'docker() {{ printf "%s\\n" "$*" >> "$ROOT/docker.calls"; {docker}; }}\n'
        f"{hide}"
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
    assert not (box["root"] / "docker.calls").exists()


def test_the_block_is_after_the_pinned_files_and_before_the_sites_own_override() -> None:
    """Not among the files whose images are checked against the lock (it names no image), before the site's own
    override (the last word is the site's), and before the list is kept for every later compose command."""
    at = INSTALL.index("# ANCHOR-MOUNT (D-638)")
    assert INSTALL.index('LOCK_FILES="$FILES"') < at < INSTALL.index('if [ -n "${TB_COMPOSE_OVERRIDE:-}" ]')
    assert at < INSTALL.index('echo "COMPOSE_FILE=$FILES" >> deploy/.env')
    assert INSTALL.index('IMAGE_PY="') < at and INSTALL.index("envget() {") < at


def test_the_installer_stops_on_a_folder_that_is_not_there(box: dict[str, Any]) -> None:
    gone = box["root"] / "mnt" / "not mounted yet"
    r = _installer(box, f"{box['a']}:{gone}")
    assert r.returncode == 1 and f"no such folder {gone}" in r.stderr and "mount the hospital's share" in r.stderr
    assert not (box["root"] / MADE).exists()  # nothing half-made is left for a later compose command


def test_a_pattern_in_a_folder_name_is_a_name_not_a_search(box: dict[str, Any]) -> None:
    (box["root"] / "mnt" / "anc1").mkdir()
    (box["root"] / "mnt" / "anc2").mkdir()
    r = _installer(box, str(box["root"] / "mnt" / "anc?"))
    assert r.returncode == 1 and "no such folder" in r.stderr and "anc?" in r.stderr


def test_the_installer_asks_the_consoles_own_image_whether_it_can_read_each_folder(box: dict[str, Any]) -> None:
    r = _installer(box, box["env"]["TB_AUDIT_ANCHOR_TARGETS"])
    assert r.returncode == 0, r.stderr
    calls = (box["root"] / "docker.calls").read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2 and all(c.startswith("run --rm --network none ") for c in calls)
    assert f"-v {box['a']}:/anchor:ro trialbox-py:test " in calls[0] and f"-v {box['b']}:/anchor:ro" in calls[1]
    assert all("--user" not in c for c in calls)  # as the image's own user, which is the console's


def test_the_installer_stops_on_a_folder_the_console_cannot_read(box: dict[str, Any]) -> None:
    r = _installer(box, box["env"]["TB_AUDIT_ANCHOR_TARGETS"], docker="return 1")
    assert r.returncode == 1 and "the console's user cannot read" in r.stderr and str(box["a"]) in r.stderr


def test_without_python_the_installer_says_that_the_page_will_not_check_the_heads(box: dict[str, Any]) -> None:
    r = _installer(box, box["env"]["TB_AUDIT_ANCHOR_TARGETS"], python=False)
    assert r.returncode == 0, r.stderr
    assert "python3" in r.stderr and "audit page" in r.stderr
    assert r.stdout.splitlines() == [f"{box['root']}/deploy/docker-compose.yml", "docker", "compose"]


def test_a_quoted_value_and_a_windows_line_end_in_the_env_file_are_read_as_doctor_reads_them(
    box: dict[str, Any],
) -> None:
    (box["deploy"] / ".env").write_bytes(f'TB_AUDIT_ANCHOR_TARGETS="{box["a"]}"\r\n'.encode())
    assert anchors.read_env(box["deploy"] / ".env") == {"TB_AUDIT_ANCHOR_TARGETS": str(box["a"])}


@pytest.mark.parametrize("odd", ["/srv/x\u0085y", "/srv/n\u00a0", "/srv/a\u200bb", "/srv/a\u2028b", "/srv/\u202ea"])
def test_a_folder_name_compose_would_read_as_another_name_is_refused(odd: str) -> None:
    """Found by the review: a next-line character became a space in what compose mounted, and a no-break space at
    the end was cut, so the console would have read another folder than the night writes."""
    with pytest.raises(anchors.AnchorError):
        anchors.plan({"TB_AUDIT_ANCHOR_TARGETS": odd})


def test_other_letters_are_kept_and_written_so_that_every_reader_agrees(box: dict[str, Any]) -> None:
    import yaml

    name = "/mnt/病院の共有/監査"
    text = anchors.compose_text(anchors.plan({"TB_AUDIT_ANCHOR_TARGETS": name}))
    assert text.isascii()
    got = yaml.safe_load(text)["services"]["console"]["volumes"][0]
    assert got["source"] == name and got["target"] == "/anchors/0/監査"


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


def test_doctor_reads_the_entry_of_the_compose_file_list_not_its_ending(box: dict[str, Any]) -> None:
    anchors.write(box["deploy"], box["env"])
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml:/somewhere/else/site/compose.anchors.yml")
    assert c.status == "WARN" and "COMPOSE_FILE" in c.detail


def test_doctor_in_the_box_image_reads_the_hosts_path_below_its_own_deploy_folder(box: dict[str, Any]) -> None:
    anchors.write(box["deploy"], box["env"])
    c = _doctor(
        box, COMPOSE_FILE="/opt/trialbox/deploy/docker-compose.yml:/opt/trialbox/deploy/site/compose.anchors.yml"
    )
    assert c.status == "PASS", c.detail  # check_host.sh: deploy/ is mounted at another path than on the host


def test_doctor_compares_what_the_file_says_not_its_bytes(box: dict[str, Any]) -> None:
    path = anchors.write(box["deploy"], box["env"])
    assert path is not None
    path.write_text(
        "# a later release words this line otherwise\n" + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml:{path}")
    assert c.status == "PASS", c.detail
    path.write_text(path.read_text(encoding="utf-8").replace("read_only: true", "read_only: false"), encoding="utf-8")
    c = _doctor(box, COMPOSE_FILE=f"{box['deploy']}/docker-compose.yml:{path}")
    assert c.status == "WARN"  # a file that mounts a folder for writing is not the installer's
