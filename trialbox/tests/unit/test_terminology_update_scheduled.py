"""OCR 1523-2: the scheduled code-system update really runs. The timer and its service are read as systemd reads them
(the timer starts the service of its name, the installer enables and starts the timer, the service runs its command in
its folder with no environment of its own), and the command is run so: it finds the pack the folders of deploy/.env
name, and gives the container what it needs to apply it."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "deploy" / "systemd"


def _unit(name: str, root: Path = ROOT) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # type: ignore[assignment,method-assign]
    cp.read_string((UNITS / name).read_text(encoding="utf-8").replace("@TB_ROOT@", str(root)))
    return cp


def test_the_timer_is_on_after_the_install_and_starts_its_service() -> None:
    timer = _unit("trialbox-terminology.timer")
    assert timer["Timer"]["OnCalendar"] and timer["Install"]["WantedBy"] == "timers.target"
    assert (UNITS / timer["Timer"].get("Unit", "trialbox-terminology.service")).is_file()
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    for verb in ("enable", "start"):  # each `systemctl <verb>` command, its continued lines with it
        named = " ".join(re.findall(rf"systemctl {verb} ((?:[^\n]*\\\n)*[^\n]*)", text))
        assert "trialbox-terminology.timer" in named, verb


@pytest.mark.parametrize("key", ["TB_TERMINOLOGY_UPDATE_DIR", "TB_TERMINOLOGY_STICK"])
@pytest.mark.parametrize("quote", ["", '"'])
def test_the_service_s_command_run_as_systemd_runs_it_applies_the_pack_deploy_env_names(
    tmp_path: Path, key: str, quote: str
) -> None:
    box = tmp_path / "box"
    (box / "deploy").mkdir(parents=True)
    shutil.copy(ROOT / "deploy" / "terminology-update.sh", box / "deploy")
    for d in ("tools", "libs"):
        (box / d).symlink_to(ROOT / d)
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.json").write_text('{"version": "2026.11"}\n', encoding="utf-8")
    (box / "deploy" / ".env").write_text(
        f"COMPOSE_PROJECT_NAME=tbt-x\n{key}={quote}{pack}{quote}\nTB_TERMINOLOGY_NIGHT=02:00-06:00\n", encoding="utf-8"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text('#!/bin/sh\necho "docker $*"\n', encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    service = _unit("trialbox-terminology.service", box)["Service"]
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}  # as the unit: nothing else
    done = subprocess.run(service["ExecStart"].split(), env=env, cwd=service["WorkingDirectory"],
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert done.returncode == 0 and "no pack waiting" not in done.stdout, done.stdout + done.stderr
    ran = done.stdout
    assert f"{pack}:/pack:ro" in ran and "criteria-compiler" in ran
    # the service's own mount of the code systems is read-only and its user is not the volume's owner
    assert "tbt-x_tb-terminology:/data/terminology-rw" in ran and "--terminology /data/terminology-rw" in ran
    assert "--user 0:0" in ran
    assert "TB_TERMINOLOGY_NIGHT=02:00-06:00" in ran  # the night it waits for
    assert "audit-data" not in ran  # D-394: only the audit writer writes the audit volume


def test_the_update_s_audit_line_goes_where_the_service_s_events_go() -> None:
    """The journal on a box (``open_audit``), never the chain's own files: a file root made there would stop the box's
    audit writer."""
    text = (ROOT / "tools" / "terminology_pack.py").read_text(encoding="utf-8")
    assert "open_audit(" in text and "AuditLog(" not in text
