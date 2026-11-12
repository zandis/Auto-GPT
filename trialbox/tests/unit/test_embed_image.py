"""ENG-003 / HW-002 (D-563): the embedder has an image of its own, installed from a second hashed lock with CPU
wheels; the registry names the embedder; compose runs the embed service from that image; the install pins the
embedder with the pair. The start itself is ``tests/integration/test_embed_production_start.py`` (Docker)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import pin_model, tiny_embedder
from tools.supply_chain import lock

ROOT = Path(__file__).resolve().parents[2]
EMBED_LOCK = ROOT / "deploy" / "requirements-embed.lock"
REVISION = "7b44caba5c06fd6f1ef1d2786261e636c38e4295"

pytestmark = pytest.mark.nodb


def _pins(path: Path) -> dict[str, list[lock.Requirement]]:
    out: dict[str, list[lock.Requirement]] = {}
    for r in lock.parse_requirements(path.read_text(encoding="utf-8")):
        if r.name:
            out.setdefault(r.name.lower(), []).append(r)
    return out


# ------------------------------------------------------------------------------------------------ the second lock
def test_the_embed_lock_is_hashed_and_holds_the_embedders_library_on_cpu_wheels() -> None:
    text = EMBED_LOCK.read_text(encoding="utf-8")
    assert lock.check_requirements_hashes(text) == []
    pins = _pins(EMBED_LOCK)
    assert "sentence-transformers" in pins and "transformers" in pins
    linux = [r for r in pins["torch"] if r.marker and "== 'linux'" in r.marker]
    assert len(linux) == 1 and str(linux[0].version).endswith("+cpu")  # the publisher's CPU build on a box
    assert not [n for n in pins if lock.GPU_ONLY.match(n)]  # no CUDA stack in an image that runs on the CPU


def test_the_embed_lock_is_the_base_lock_plus_the_extra() -> None:
    base, embed = _pins(lock.REQUIREMENTS_LOCK), _pins(EMBED_LOCK)
    for name, reqs in base.items():
        assert name in embed, name
        assert {(r.version, r.hashes) for r in reqs} == {(r.version, r.hashes) for r in embed[name]}, name
    assert len(embed) > len(base)


def test_the_lock_check_holds_the_embed_lock(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    assert "missing" in lock.check_embed_lock(tmp_path)[0]
    assert lock.check_embed_lock.__name__ in lock.lock_check.__code__.co_names  # part of `make lock-check`


def test_one_name_twice_is_allowed_only_when_uv_forked_it_by_environment() -> None:
    h = "--hash=sha256:" + "ab" * 32
    forked = f"torch==2.15.0 ; sys_platform != 'linux' \\\n    {h}\ntorch==2.15.0+cpu ; sys_platform == 'linux' \\\n    {h}\n"
    assert lock.check_requirements_hashes(forked) == []
    same = f"torch==2.15.0 ; sys_platform == 'linux' \\\n    {h}\ntorch==2.15.0+cpu ; sys_platform == 'linux' \\\n    {h}\n"
    assert lock.check_requirements_hashes(same) == ["torch is listed more than once"]
    bare = f"torch==2.15.0 \\\n    {h}\ntorch==2.15.0+cpu ; sys_platform == 'linux' \\\n    {h}\n"
    assert lock.check_requirements_hashes(bare) == ["torch is listed more than once"]


def test_torch_comes_from_the_cpu_index_and_nothing_else_does() -> None:
    import tomllib

    doc = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(doc["tool"]["uv"]["sources"]) == {"torch"}
    index = doc["tool"]["uv"]["index"]
    assert [(i["name"], i["url"], i["explicit"]) for i in index] == [
        ("pytorch-cpu", "https://download.pytorch.org/whl/cpu", True)
    ]


# ------------------------------------------------------------------------------------------------ the image
def test_the_image_installs_the_embed_lock_in_hash_mode_and_carries_no_weights() -> None:
    df = (ROOT / "deploy" / "docker" / "embed.Dockerfile").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in df.splitlines() if not ln.lstrip().startswith("#"))
    assert "ARG BASE_IMAGE=trialbox-py:1.0.0" in code and "FROM ${BASE_IMAGE}" in code
    assert (
        "COPY deploy/requirements-embed.lock" in code and "--require-hashes" in code and "--only-binary=:all:" in code
    )
    assert code.count("COPY ") == 1  # the lock and nothing else: no weights, no code beside the base image's
    assert "HF_HUB_OFFLINE=1" in code and "TRANSFORMERS_OFFLINE=1" in code
    users = re.findall(r"^USER (\S+)$", code, re.M)
    assert users[-1] == "tb"


def test_compose_and_the_build_name_the_image() -> None:
    base = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = base["services"]["embed-service"]
    assert svc["image"] == "${TB_EMBED_IMAGE:-trialbox-embed:1.0.0}"
    assert "TB_EMBED_MODE" not in svc["environment"]  # no stub on a box (D-429)
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    images = mk[mk.index("\nimages:") :].split("\n\n", 1)[0]
    assert "deploy/docker/embed.Dockerfile" in images and "trialbox-embed:1.0.0" in images
    multi = mk[mk.index("\nimages-multiarch:") :].split("\n\n", 1)[0]
    assert "deploy/docker/embed.Dockerfile" in multi
    assert "trialbox-embed:1.0.0" in next(ln for ln in mk.splitlines() if ln.startswith("SC_OWN_IMAGES"))
    wf = (ROOT.parent / ".github" / "workflows" / "trialbox-images.yml").read_text(encoding="utf-8")
    assert "make embed-start" in wf and "tests/integration/test_embed_production_start.py" in mk


# ------------------------------------------------------------------------------------------------ the registry
def _build() -> dict[str, Any]:
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    return dict(next(b for b in doc["builds"] if b["build_id"] == pin_model.EMBED_BUILD))


def test_the_registry_names_the_embedder() -> None:
    b = _build()
    assert b["repository"] == "BAAI/bge-m3" and b["revision"] == REVISION
    # the publisher's revision holds no safetensors weights: which folder ships is not decided (test_embed_review)
    assert b["provenance"]["source"] == "BAAI/bge-m3" and b["provenance"]["revision"] == REVISION
    assert b["licence"] == {"name": "MIT", "spdx": "MIT", "verified": True, "register": "model-bge-m3"}
    assert b["origin"]["non_prc"] is False and b["origin"]["country"] == "CN"  # said, not left blank
    assert b["expected"]["revision"] == REVISION
    register = (ROOT / "docs" / "licences" / "register.csv").read_text(encoding="utf-8")
    row = next(ln for ln in register.splitlines() if ln.startswith("model-bge-m3,"))
    assert REVISION in row and "cleared" in row


# ------------------------------------------------------------------------------------------------ the install's pin
def _folder(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "embedder"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(b"synthetic weights for a test, not a model")
    (d / "config.json").write_text("{}", encoding="utf-8")
    return d


def _registry_naming(tmp_path: Path, manifest: str) -> Path:
    text = (ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")
    row = text.index(f"build_id: {pin_model.EMBED_BUILD}")
    out = tmp_path / "registry.yaml"
    out.write_text(text[:row] + text[row:].replace("manifest_sha256: null", f"manifest_sha256: {manifest}", 1),
                   encoding="utf-8")  # fmt: skip
    return out


def test_the_install_pins_the_embedder_with_the_pair(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    manifest = pin_model.weight_manifest(folder).sha256
    out = tmp_path / "site" / "registry.site.yaml"
    out.parent.mkdir()
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {},
                                       registry_path=_registry_naming(tmp_path, manifest), with_embedder=True)  # fmt: skip
    line = next(ln for ln in lines if ln.startswith(f"{pin_model.EMBED_BUILD}:"))
    assert f"pinned {manifest[:12]}" in line and "on embed" in line
    assert not ok  # the pair's folders are not here: reported, as before
    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"][pin_model.EMBED_BUILD]
    assert entry["sha256"] == manifest and entry["served"] == {"embed": pin_model.EMBED_BUILD}
    from embed_service import embedder

    assert embedder.pinned_sha256({"TB_REGISTRY_OVERRIDE": str(out)}) == manifest  # what the service reads
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {},
                                       registry_path=_registry_naming(tmp_path, manifest), with_embedder=True)  # fmt: skip
    assert any(ln.startswith(f"{pin_model.EMBED_BUILD}: already pinned") for ln in lines)


def test_every_profile_pins_the_embedder_and_a_missing_folder_is_reported(tmp_path: Path) -> None:
    for gpu in pin_model.PROFILE_PAIRS:
        _ok, lines = pin_model.install_pins(gpu, tmp_path / "none", tmp_path / f"{gpu}.yaml", {}, with_embedder=True)
        assert any(ln.startswith(f"{pin_model.EMBED_BUILD}: no weights in") for ln in lines), gpu


def test_other_files_than_the_expected_ones_are_never_pinned(tmp_path: Path) -> None:
    _folder(tmp_path)
    out = tmp_path / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {},
                                       registry_path=_registry_naming(tmp_path, "f" * 64), with_embedder=True)  # fmt: skip
    line = next(ln for ln in lines if ln.startswith(f"{pin_model.EMBED_BUILD}:"))
    assert not ok and "differs from the expected" in line and not out.exists()


def test_until_the_registry_names_the_manifest_nothing_is_trusted_on_first_use(tmp_path: Path) -> None:
    """The committed row has no manifest yet (lane G hashes the real folder): the install does not pin on trust."""
    assert _build()["expected"]["manifest_sha256"] is None, "the manifest is written: drop this test's premise"
    _folder(tmp_path)
    out = tmp_path / "registry.site.yaml"
    ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {}, with_embedder=True)
    line = next(ln for ln in lines if ln.startswith(f"{pin_model.EMBED_BUILD}:"))
    assert not ok and "no expected weights" in line and not out.exists()


# ------------------------------------------------------------------------------------------------ the test's model
def test_the_tiny_models_vocabulary_is_fixed_and_synthetic() -> None:
    v = tiny_embedder.vocabulary()
    assert v[:5] == ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] and len(v) == len(set(v)) == 5 + 2 * 49
    assert tiny_embedder.DIM == 32
