"""NEW-WIN-13 (D-616; owner rulings D-510, D-504): the P-0 media built by a workflow and attached to a release.

The workflow cannot run here; its rules are read from the file. The build script's stage A runs on stand-in inputs
(the same ones tests/unit/test_windows_media.py builds a media from); nothing is fetched."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1].parent
WF_PATH = ROOT.parent / ".github" / "workflows" / "trialbox-p0-media.yml"


def _wf() -> dict[Any, Any]:
    data = yaml.safe_load(WF_PATH.read_text())
    assert isinstance(data, dict)
    return data


def test_the_workflow_runs_by_hand_only_and_may_write_only_the_release() -> None:
    wf = _wf()
    on = wf.get("on", wf.get(True))
    assert on is not None
    assert list(on) == ["workflow_dispatch"]
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    assert list(jobs) == ["media"] and jobs["media"]["permissions"] == {"contents": "write"}
    assert on["workflow_dispatch"]["inputs"]["skip_bitlocker"]["default"] is True  # until the owner decides


def test_inputs_reach_the_shell_through_the_environment_and_the_tag_is_checked_first() -> None:
    steps = _wf()["jobs"]["media"]["steps"]
    for s in steps:
        assert "${{" not in s.get("run", ""), s.get("name")
    assert "^p0-[a-z0-9.-]+$" in steps[0]["run"]
    assert any("tools/p0_media.sh" in s.get("run", "") for s in steps)


def test_every_action_is_pinned_to_a_commit() -> None:
    for s in _wf()["jobs"]["media"]["steps"]:
        if "uses" in s:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", s["uses"]), s["uses"]


def _stand_in_inputs(tmp: Path) -> Path:
    spec = importlib.util.spec_from_file_location("twm", Path(__file__).with_name("test_windows_media.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    made = mod._inputs(tmp / "made")
    inp = tmp / "in"
    inp.mkdir()
    shutil.copy(made["rootfs"], inp / "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz")
    shutil.copy(made["wsl_msi"], inp / "wsl.2.6.1.0.x64.msi")
    shutil.copytree(made["debs"], inp / "debs")
    return inp


def test_stage_a_makes_the_release_files_and_the_launcher_names_this_release(tmp_path: Path) -> None:
    inp = _stand_in_inputs(tmp_path)
    env = {**os.environ, "TB_P0_NO_FETCH": "1", "TB_P0_PYTHON": sys.executable,
           "TB_RELEASE_BASE": "https://github.com/o/r/releases/download/p0-a-test"}  # fmt: skip
    out = subprocess.run(
        ["bash", "tools/p0_media.sh", "a", str(tmp_path / "p0"), "--skip-bitlocker", "--inputs", str(inp)],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    rel = tmp_path / "p0/release"
    names = sorted(p.name for p in rel.iterdir())
    assert names == ["Get-TrialBox-P0.cmd", "NOTES.md", "TRIALBOX-p0a.manifest.json", "TRIALBOX-p0a.tar.part-001",
                     "get-p0-media.ps1"]  # fmt: skip
    cmd = (rel / "Get-TrialBox-P0.cmd").read_text()
    assert 'set "TB_BASE=https://github.com/o/r/releases/download/p0-a-test"' in cmd
    assert 'set "TB_MANIFEST=TRIALBOX-p0a.manifest.json"' in cmd
    import hashlib

    assert f'set "TB_SHA={hashlib.sha256((rel / "get-p0-media.ps1").read_bytes()).hexdigest()}"' in cmd
    assert not re.search(r"@[A-Z_0-9]+@", cmd)  # no mark left unfilled
    msha = hashlib.sha256((rel / "TRIALBOX-p0a.manifest.json").read_bytes()).hexdigest()
    assert f'set "TB_MANIFEST_SHA={msha}"' in cmd  # the manifest is checked against the release's build (review 8)
    assert not (tmp_path / "p0/media").exists()  # in the parts now (review 6)
    notes = (rel / "NOTES.md").read_text()
    assert "MIT licence" in notes and "ubuntu.com/legal" in notes
    assert "docker-ce_27.3.1_amd64.deb: from download.docker.com" in notes  # the real origin (review 7)
    assert "nvidia-container-toolkit_1.17.0_amd64.deb: from nvidia.github.io" in notes
    assert "Source code for the GPL and LGPL programs" in notes
    import io
    import tarfile

    joined = b"".join(p.read_bytes() for p in sorted(rel.glob("TRIALBOX-p0a.tar.part-*")))
    with tarfile.open(fileobj=io.BytesIO(joined)) as t:
        member = t.extractfile("TRIALBOX-p0a/windows/p0.json")
        assert member is not None
        assert json.loads(member.read()) == {"rehearsal": False, "skip_bitlocker": True}


def test_stage_b_signs_with_a_key_of_its_own_and_removes_its_private_half() -> None:
    sh = (ROOT / "tools/p0_media.sh").read_text()
    assert 'rm -f "$KEYS"/*.key' in sh and "trap cleanup EXIT" in sh
    assert "--rehearsal --key" in sh and "CHOICES+=(--rehearsal)" in sh
    assert "trialbox-embed:1.0.0" in sh  # the embed service always runs (review 2)


def test_a_tag_that_exists_stops_the_run_before_anything_is_built() -> None:
    first = _wf()["jobs"]["media"]["steps"][0]["run"]
    assert "git/ref/tags/$TAG" in first and "exit 1" in first
