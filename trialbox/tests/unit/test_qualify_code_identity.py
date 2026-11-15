"""D-881: qualify on a box names its code by the signed release tree; without one it says so plainly.

`trialbox eval qualify --box` runs in the trialbox-py image (the host's python3 lacks qualify's libraries): there /app
has no git and no HOST-SHA256SUMS, so serving_record said "no git HEAD and no signed release tree". On the host the
box wrapper now starts qualify in the image itself, with the release tree (/opt/trialbox/current) mounted read-only
as TB_RELEASE_TREE, the image's id as TB_CODE_IMAGE, and every path it found or was given mounted where it is. The
record names ``release:<sha256>``. Lane G's direct route has no release tree: the code is named by the image id, said
plainly, which passes only under TB_HOST_PROFILE=poc."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from tools import box_qualify as bq
from tools import code_identity as ci
from tools import qualify as q

pytestmark = pytest.mark.nodb

IMAGE_ID = "sha256:" + "d" * 64


def _tree(root: Path) -> Path:
    root.mkdir()
    (root / "tools").mkdir()
    (root / "tools" / "x.py").write_text("x = 1\n", encoding="utf-8")
    line = f"{hashlib.sha256(b'x = 1' + bytes([10])).hexdigest()}  tools/x.py\n"
    (root / ci.SUMS).write_text(line, encoding="utf-8")
    return root


def test_the_release_tree_names_the_code_in_the_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tmp_path / "app"
    app.mkdir()
    tree = _tree(tmp_path / "release")
    monkeypatch.setenv("TB_RELEASE_TREE", str(tree))
    name, dirty = ci.head(app)
    assert name == "release:" + hashlib.sha256((tree / ci.SUMS).read_bytes()).hexdigest() and not dirty


def test_without_a_tree_the_image_names_the_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.delenv("TB_RELEASE_TREE", raising=False)
    monkeypatch.setenv("TB_CODE_IMAGE", IMAGE_ID)
    assert ci.head(app) == (f"image:{IMAGE_ID}", False)
    monkeypatch.delenv("TB_CODE_IMAGE")
    assert ci.head(app) == ("unknown", True)


def test_an_image_only_identity_passes_only_under_the_poc_profile() -> None:
    assert q.code_problems(f"image:{IMAGE_ID}", {"TB_HOST_PROFILE": "poc"}) == []
    assert q.code_note(f"image:{IMAGE_ID}") == "no release tree: code named by the image digest"
    site = q.code_problems(f"image:{IMAGE_ID}", {})
    assert site and "release tree" in site[0]
    assert q.code_problems("release:" + "a" * 64, {}) == [] and q.code_problems("a" * 40, {}) == []
    assert q.code_problems("unknown", {"TB_HOST_PROFILE": "poc"})


def test_on_the_host_the_wrapper_starts_qualify_in_the_image(tmp_path: Path) -> None:
    host_root = tmp_path / "opt" / "trialbox" / "releases" / "b1"
    host_root.mkdir(parents=True)  # a release tree: tools, libs, deploy, no services/
    out = tmp_path / "out"
    log = tmp_path / "j.log"
    log.write_text("", encoding="utf-8")
    weights = tmp_path / "models" / "gemma"
    weights.mkdir(parents=True)
    filled = ["--profile", "rtxpro6000", "--out", str(out), "--model-dir", f"judge={weights}", "--server-log", str(log)]
    seen: list[list[str]] = []

    def run(cmd: list[str], **_: Any) -> str:
        seen.append(cmd)
        if cmd[-4:-1] == ["image", "inspect", "-f"] or ("inspect" in cmd and "{{.Id}}" in cmd):
            return IMAGE_ID + "\n"
        if "inspect" in cmd:
            return '[{"NetworkSettings": {"Networks": {"trialbox_default": {}}}}]'
        return "cid-gateway\n"

    cmd = bq.relaunch_command(filled, host_root, run, env={"TB_HOST_PROFILE": "poc", "TB_SERVICE_TOKEN": "x"})
    joined = " ".join(cmd)
    assert cmd[:3] == ["docker", "run", "--rm"] and cmd[-len(filled) - 3 : -len(filled)] == [
        "python",
        "-m",
        "tools.qualify",
    ]
    assert f"-v {host_root}:/release:ro" in joined and "-e TB_RELEASE_TREE=/release" in joined
    assert f"-e TB_CODE_IMAGE={IMAGE_ID}" in joined
    assert f"-v {weights}:{weights}:ro" in joined and f"-v {log}:{log}:ro" in joined and f"-v {out}:{out}" in joined
    assert "--network trialbox_default" in joined
    assert "-e TB_SERVICE_TOKEN " in joined and "TB_SERVICE_TOKEN=x" not in joined and "x" not in cmd  # by name only
    assert "-e TB_HOST_PROFILE " in joined
    assert cmd[-len(filled) :] == filled and "--box" not in cmd


def test_in_the_image_the_wrapper_runs_qualify_itself() -> None:
    assert bq.in_image(Path(bq.__file__).resolve().parents[1])  # this checkout has services/
