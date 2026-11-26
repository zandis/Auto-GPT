"""A script that another script or a systemd unit starts by its path is executable in git (the join of the system
modules lost the bit of deploy/terminology-update.sh, and the install stopped there)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
#: a repository script in command position: first on the line, or after a separator or a word that takes a command (no prose in
#: brackets)
CALL = re.compile(
    r'(?:^|[;&|!]|\b(?:then|else|do|exec|if|while|until|sudo))\s*"?(?:\$\{?ROOT\}?/|\./)?'
    r'((?:deploy|tools)/[\w./-]+\.sh)"?(?=[\s;)]|$)'
)
UNIT = re.compile(r"^Exec\w+=[-+!@]*@TB_ROOT@/((?:deploy|tools)/\S+)", re.MULTILINE)


def _called() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in [*(ROOT / "deploy").glob("**/*.sh"), *(ROOT / "tools").glob("**/*.sh")]:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for m in CALL.finditer(line.split(" # ")[0]):
                out.setdefault(m[1], p.name)
    for p in (ROOT / "deploy").glob("**/*.service"):
        for m in UNIT.finditer(p.read_text(encoding="utf-8")):
            out.setdefault(m[1], p.name)
    return {k: v for k, v in out.items() if (ROOT / k).is_file()}


def test_a_script_called_by_its_path_is_executable_in_git() -> None:
    listed = subprocess.run(["git", "ls-files", "-s", "deploy", "tools"], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout  # fmt: skip
    mode = {line.split("\t", 1)[1]: line[:6] for line in listed.splitlines()}
    called = _called()
    assert {"deploy/terminology-update.sh", "deploy/network.sh"} <= set(called)
    lost = {k: f"{mode.get(k)}, called by {v}" for k, v in called.items() if mode.get(k) != "100755"}
    assert lost == {}
