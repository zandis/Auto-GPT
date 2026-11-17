"""H-22 finding 5, the owner's ruling D-1066 (D-998): a PRODUCTION box without a GPU is a product form.

A feasibility-only site installs with ``--mode stub``: structured criteria only, and a GPU may be added later. On lane
H's PRODUCTION stub box every service became healthy but ``embed-service``, which refuses to start in PRODUCTION
without a pinned embedder (``EmbedderRefused``): the installer pinned models in GPU mode only. Now:

* ``pin_model --install-embedder`` pins ``e-embed-1`` alone, strictly: no weights, other weights or a pin that is not
  the release's expected manifest each fail;
* ``install.sh`` runs it in stub mode (a failure stops a PRODUCTION install and is a warning elsewhere, where the
  embed service runs its hash stub), and checks every pin with ``--verify-all`` in both modes;
* ``release check`` (and so ``make_bundle.sh``) refuses a bundle for a site whose ``embedder/`` does not hash to the
  registry's expected manifest for ``e-embed-1``: every site bundle carries the embedder (about 2.3 GB). A rehearsal
  bundle (D-726), which a site box refuses, is exempt and says so.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import pin_model as pm
from tools import release as rl

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


def _embedder(d: Path, tag: str = "synthetic") -> Path:
    d.mkdir(parents=True)
    (d / "config.json").write_text('{"model_type": "xlm-roberta"}\n', encoding="utf-8")
    (d / "model.safetensors").write_bytes(f"not a model: {tag}".encode())
    (d / "README.md").write_text("synthetic embedder for a test\n", encoding="utf-8")
    return d


def _registry(tmp: Path, digest: str) -> Path:
    """The release's registry with e-embed-1's expected manifest made the synthetic folder's."""
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    row = next(b for b in doc["builds"] if b.get("build_id") == pm.EMBED_BUILD)
    row["expected"]["manifest_sha256"] = digest
    out = tmp / "registry.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return out


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Path]:
    models = tmp_path / "deploy" / "models"
    d = _embedder(models / "embedder")
    reg = _registry(tmp_path, pm.weight_manifest(d).sha256)
    return {"models": models, "embedder": d, "reg": reg, "out": tmp_path / "deploy" / "site" / "registry.site.yaml"}


def _install(b: dict[str, Path], env: dict[str, str] | None = None) -> tuple[bool, list[str]]:
    return pm.install_embedder(b["models"], b["out"], env or {"TB_ENV": "PRODUCTION"}, b["reg"])


# ------------------------------------------------------------------------------------------------ the pin
def test_it_pins_the_embedder_alone_from_the_release_weights(box: dict[str, Path]) -> None:
    ok, lines = _install(box)
    assert ok, lines
    doc = yaml.safe_load(box["out"].read_text(encoding="utf-8"))
    entry = doc["builds"][pm.EMBED_BUILD]
    assert entry["served"] == {"embed": pm.EMBED_BUILD} and entry["status"] == "candidate"
    assert entry["weights"]["trust"] == "expected"
    assert set(doc["builds"]) == {pm.EMBED_BUILD}  # no pair is pinned on a box without a GPU
    again_ok, again = _install(box)
    assert again_ok and "already pinned" in again[0]


def test_no_weights_fail_and_name_the_ruling(box: dict[str, Path]) -> None:
    for f in box["embedder"].iterdir():
        f.unlink()
    box["embedder"].rmdir()
    ok, lines = _install(box)
    assert not ok and "no weights" in lines[0] and "D-1066" in lines[0]
    assert not box["out"].exists()


def test_other_weights_are_refused(box: dict[str, Path]) -> None:
    (box["embedder"] / "model.safetensors").write_bytes(b"other weights")
    ok, lines = _install(box)
    assert not ok and "not the weights of e-embed-1" in lines[0]
    assert not box["out"].exists()


def test_a_pin_that_is_not_the_expected_manifest_is_refused(box: dict[str, Path], tmp_path: Path) -> None:
    assert _install(box)[0]
    (tmp_path / "other").mkdir()
    reg = _registry(tmp_path / "other", "0" * 64)
    ok, lines = pm.install_embedder(box["models"], box["out"], {"TB_ENV": "PRODUCTION"}, reg)
    assert not ok and "not the expected manifest" in lines[0]


def test_the_command_line(box: dict[str, Path]) -> None:
    argv = [sys.executable, "-m", "tools.pin_model", "--install-embedder", "--models-root", str(box["models"]),
            "--out", str(box["out"]), "--registry", str(box["reg"])]  # fmt: skip
    got = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    assert got.returncode == 0, got.stderr
    assert "e-embed-1: pinned" in got.stdout
    (box["embedder"] / "model.safetensors").write_bytes(b"changed after the pin")
    box["out"].unlink()
    bad = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    assert bad.returncode == 1


# ------------------------------------------------------------------------------------------------ the installer
def _branch(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end, text.index(start))]


def test_stub_mode_pins_the_embedder_and_stops_a_production_install_without_it() -> None:
    block = _branch(INSTALL, "# ---- PINS", "# ---- end of PINS")
    stub = block[block.index("else") :]
    assert "python -m tools.pin_model --install-embedder --models-root /d/models" in stub
    assert '-e TB_ENV="$TB_ENV_SITE"' in stub and "-e EMBED_MODEL_DIR -e EMBED_MODEL" in stub
    assert re.search(r'if \[ "\$TB_ENV_SITE" = PRODUCTION \]; then\s+die "[^"]*D-1066', stub)
    # both modes: every pin is checked against its weights before the stack starts
    verify = block[block.index("--verify-all") - 400 :]
    assert "fi\nif ls deploy/site/registry.site.yaml" in block and "--verify-all /d/models" in verify


# ------------------------------------------------------------------------------------------------ the bundle
def _manifest(files: dict[str, bytes]) -> dict[str, Any]:
    return {"files": [{"path": p, "kind": "model", "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
                      for p, b in files.items()]}  # fmt: skip


def test_a_site_bundle_without_the_embedder_is_refused() -> None:
    got = rl.embedder_problems({"release_seq": 1}, _manifest({"judge/model.safetensors": b"x"}))
    assert len(got) == 1 and "e-embed-1" in got[0] and "embedder/" in got[0] and "D-1066" in got[0]
    assert "BAAI/bge-m3 at 7b44caba5c06" in got[0]  # the release registry's own row


def test_a_site_bundle_with_the_release_embedder_passes(tmp_path: Path) -> None:
    d = _embedder(tmp_path / "e")
    files = {f"embedder/{p.name}": p.read_bytes() for p in d.iterdir()}
    reg = _registry(tmp_path, pm.weight_manifest(d).sha256)
    assert rl.embedder_problems({"release_seq": 1}, _manifest(files), registry_path=reg) == []
    files["embedder/model.safetensors"] = b"other"
    bad = rl.embedder_problems({"release_seq": 1}, _manifest(files), registry_path=reg)
    assert bad and "not the release's e-embed-1" in bad[0]


def test_a_rehearsal_bundle_is_exempt() -> None:
    assert rl.embedder_problems({"rehearsal": True}, _manifest({})) == []


def test_release_check_runs_it() -> None:
    src = (ROOT / "tools" / "release.py").read_text(encoding="utf-8")
    body = src[src.index("def check_bundle(") :]
    assert "embedder_problems(release, manifest)" in body[: body.index("\ndef ")]


def test_the_box_plan_and_the_installer_agree_on_a_box_without_a_gpu() -> None:
    """The box form's no-GPU board (tools/box/plan.py) installs with --mode stub on PRODUCTION (D-822): that is the
    installer's branch that pins the embedder."""
    from tools.box.plan import BoxPlan

    stub = BoxPlan.__new__(BoxPlan)
    stub.mode = "stub"
    assert stub.install_args == ["--mode", "stub"]
    mode = re.search(r'stub\) echo "    no GPU: ([^"]*)"', INSTALL)
    assert mode and "structured criteria" in mode.group(1)
    block = _branch(INSTALL, "# ---- PINS", "# ---- end of PINS")
    assert block.startswith("# ---- PINS") and 'if [ "$MODE" = gpu ]; then' in block and "--install-embedder" in block
