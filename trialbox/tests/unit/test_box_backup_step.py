"""OPS-003 (D-566): on a box (``TB_BOX=1``) a backup schedule that cannot be installed is a line in the install's
FAIL list, not a stop: the install goes on to "TrialBox is running" and the wizard. The IT form still stops. The
test runs the installer's own backup block (cut from ``deploy/install.sh``) with a ``python3`` that answers as
``backup-install`` does on a host with no mail relay."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "deploy" / "install.sh"
START = "# T-117b (D-274): the backup cron"
END = "\nfor f in deploy/refdata/pending/*.tar; do"
REFUSAL = "TB_BACKUP_MAILTO is set but this host has no mail transfer agent (sendmail): cron cannot mail"

pytestmark = pytest.mark.nodb


def _block() -> str:
    text = INSTALL.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1
    return text[text.index(START) : text.index(END)]


def _run(tmp_path: Path, rc: int, box: str | None) -> subprocess.CompletedProcess[str]:
    """The block as install.sh runs it (errexit, the same helpers), then what the end of the install prints."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "python3"
    shim.write_text(f"#!/bin/sh\necho \"$*\" > {tmp_path}/called\n[ {rc} = 0 ] || echo '{REFUSAL}'\nexit {rc}\n")
    shim.chmod(0o755)
    script = (
        "set -euo pipefail\n"
        "say() { printf '==> %s\\n' \"$*\"; }\n"
        "die() { printf 'install: %s\\n' \"$*\" >&2; exit 1; }\n"
        "CAN_CRON=1\nFAILS=()\n" + _block() + "\necho 'TrialBox is running.'\n"
        'if [ "${#FAILS[@]}" -gt 0 ]; then printf \'install: FAIL: %s\\n\' "${FAILS[@]}" >&2; exit 1; fi\n'
    )
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    if box is not None:
        env["TB_BOX"] = box
    return subprocess.run(["bash", "-c", script], env=env, cwd=tmp_path, capture_output=True, text=True, check=False)


def test_on_a_box_a_refused_backup_schedule_is_a_fail_line_and_the_install_goes_on(tmp_path: Path) -> None:
    r = _run(tmp_path, 1, "1")
    assert "TrialBox is running." in r.stdout, r.stderr  # box-install.sh: the stack is up, the wizard is served
    assert REFUSAL in r.stdout  # what backup-install said is shown
    fails = [ln for ln in r.stderr.splitlines() if ln.startswith("install: FAIL: ")]
    assert len(fails) == 1 and "backup schedule is not installed yet" in fails[0]
    assert "first-run" in fails[0] and "backup-install --deploy deploy" in fails[0]  # what is next, and by hand
    assert r.returncode == 1  # the list still ends the install with exit 1 (T-632)
    assert "backup-install --deploy deploy" in (tmp_path / "called").read_text(encoding="utf-8")


@pytest.mark.parametrize("box", [None, "0"])
def test_the_it_form_still_stops_at_the_backup_step(tmp_path: Path, box: str | None) -> None:
    r = _run(tmp_path, 1, box)
    assert r.returncode == 1 and "TrialBox is running." not in r.stdout
    assert "install: the backup schedule is not installed (above)" in r.stderr and "FAIL:" not in r.stderr


@pytest.mark.parametrize("box", [None, "1"])
def test_an_installed_schedule_is_neither(tmp_path: Path, box: str | None) -> None:
    r = _run(tmp_path, 0, box)
    assert r.returncode == 0 and "TrialBox is running." in r.stdout and r.stderr == ""


def test_the_box_installer_reads_a_fail_list_as_a_running_stack() -> None:
    """The other half of the contract: box-install.sh stops only when the install did not reach its last line."""
    text = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
    assert 'if [ "$rc" != 0 ] && ! grep -q "TrialBox is running" "$BOX/install.log"; then' in text
    block = _block()
    assert 'TB_BOX:-0}" != 1' in block and "FAILS+=(" in block
