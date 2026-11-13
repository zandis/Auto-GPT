"""ENG-003 (D-563): the cases the adversarial review of PR #341 found. The serving checks ask a model server for
its model list, and the embed service is not one; no profile asks the CPU image for a GPU; the test stack, the PoC
and the box rehearsal do not need the embed image; the install's exit code is the pair's unless the embedder's
folder is wrong; the registry row does not claim weights the publisher's revision does not hold."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from gateway.app import served_problems
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from registry.registry import Registry
from tb_common.audit import AuditLog

from tools import pin_model
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]

MANIFEST_FIELD = re.compile(r"manifest_sha256: (?:[0-9a-f]{64}|null)")

pytestmark = pytest.mark.nodb


class _Loader(yaml.SafeLoader):
    """Compose's own tags (``!reset``, ``!override``) read as nothing: these tests read other keys."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _compose(path: Path) -> dict[str, Any]:
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    assert isinstance(doc, dict)
    return doc


def _pinned(tmp_path: Path) -> tuple[Path, Path]:
    """A site override that pins the embedder, and the registry that names its manifest."""
    d = tmp_path / "models" / "embedder"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(b"synthetic weights for a test, not a model")
    manifest = pin_model.weight_manifest(d).sha256
    text = (ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")
    row = text.index(f"build_id: {pin_model.EMBED_BUILD}")
    reg = tmp_path / "registry.yaml"
    reg.write_text(text[:row] + MANIFEST_FIELD.sub(f"manifest_sha256: {manifest}", text[row:], count=1),
                   encoding="utf-8")  # fmt: skip
    out = tmp_path / "registry.site.yaml"
    _ok, lines = pin_model.install_pins("rtxpro6000", tmp_path / "models", out, {}, registry_path=reg,
                                        with_embedder=True)  # fmt: skip
    assert any(ln.startswith(f"{pin_model.EMBED_BUILD}: pinned") for ln in lines), lines
    return out, reg


# ------------------------------------------------------------------------------------------------ H2
def test_doctor_serving_does_not_ask_the_embed_service_for_a_model_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the embedder pinned, `install.sh` died at `doctor --serving`: the embed service has no /v1/models."""
    out, _reg = _pinned(tmp_path)
    asked: list[str] = []

    def get(url: str, key: str, timeout: float = 10.0) -> tuple[int | None, Any]:
        asked.append(url)
        return 404, None

    monkeypatch.setattr(doctor, "_get_models", get)
    c = doctor.check_serving(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_REGISTRY_OVERRIDE": str(out)}))
    assert asked == [] and c.status != "FAIL", c.detail


def test_the_gateways_start_check_leaves_the_embedder_alone(tmp_path: Path) -> None:
    out, reg = _pinned(tmp_path)
    gw = Gateway(RoutingPolicy.load(), Registry.load(reg, out), AuditLog(tmp_path / "audit"), GatewayConfig(), env={})
    asked: list[str] = []

    def get(url: str, key: str) -> tuple[int | None, Any]:
        asked.append(url)
        return 404, None

    assert served_problems(gw, {}, get) == ([], []) and asked == []


# ------------------------------------------------------------------------------------------------ H3
def test_no_profile_asks_the_cpu_image_for_a_gpu() -> None:
    """The GB10 overlay defaulted TB_EMBED_DEVICE to cuda: torch's CPU build then stops the service at start."""
    for path in sorted((ROOT / "deploy").rglob("docker-compose*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            assert not ("TB_EMBED_DEVICE" in code and "cuda" in code), f"{path.name}: {line.strip()}"


# ------------------------------------------------------------------------------------------------ M2, M3
def test_the_embed_image_is_built_from_its_own_file_and_the_stub_stacks_do_not_need_it() -> None:
    base = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    build = base["services"]["embed-service"]["build"]
    assert build["dockerfile"] == "deploy/docker/embed.Dockerfile"  # not the anchor's python.Dockerfile under this tag
    for name in ("deploy/docker-compose.test.yml", "deploy/docker-compose.poc.yml", "tools/rehearse_box/standins.yml"):
        svc = _compose(ROOT / name)["services"]["embed-service"]
        assert svc["image"] == "${TB_EMBED_IMAGE:-trialbox-py:1.0.0}", name  # the hash embedder needs no library
        assert svc["build"]["dockerfile"] == "deploy/docker/python.Dockerfile", name


# ------------------------------------------------------------------------------------------------ M1
def test_the_installs_exit_code_is_the_pairs_unless_the_embedders_folder_is_wrong(tmp_path: Path) -> None:
    """The platform's pin job and every install before the manifest is written: the embedder is reported, and the
    result is the pair's. A folder that is there and is not the expected weights is a failure."""
    models = tmp_path / "models"
    lines_of = {}
    for name in ("gemma-4-26b-a4b-it-4bit", "qwen3.5-9b-4bit"):
        (models / name).mkdir(parents=True)
    pair_ok, _ = pin_model.install_pins("rtxpro6000", models, tmp_path / "a.yaml", {})
    ok, lines = pin_model.install_pins("rtxpro6000", models, tmp_path / "b.yaml", {}, with_embedder=True)
    lines_of["absent"] = next(ln for ln in lines if ln.startswith(pin_model.EMBED_BUILD))
    assert ok == pair_ok and "no weights in" in lines_of["absent"]
    (models / "embedder").mkdir()
    (models / "embedder" / "model.safetensors").write_bytes(b"synthetic")
    text = (ROOT / "models" / "registry.yaml").read_text(encoding="utf-8")
    row = text.index(f"build_id: {pin_model.EMBED_BUILD}")
    unnamed = tmp_path / "registry.unnamed.yaml"  # a row with no manifest yet, as the committed one was
    unnamed.write_text(text[:row] + MANIFEST_FIELD.sub("manifest_sha256: null", text[row:], count=1), encoding="utf-8")
    ok, lines = pin_model.install_pins("rtxpro6000", models, tmp_path / "c.yaml", {}, registry_path=unnamed,
                                       with_embedder=True)  # fmt: skip
    assert ok == pair_ok and any("no expected weights" in ln for ln in lines)
    reg = tmp_path / "registry.yaml"
    reg.write_text(text[:row] + MANIFEST_FIELD.sub(f"manifest_sha256: {'f' * 64}", text[row:], count=1),
                   encoding="utf-8")  # fmt: skip
    ok, lines = pin_model.install_pins("rtxpro6000", models, tmp_path / "d.yaml", {}, registry_path=reg,
                                       with_embedder=True)  # fmt: skip
    assert not ok and any("differs from the expected" in ln for ln in lines)


# ------------------------------------------------------------------------------------------------ H1
def test_the_row_names_the_publishers_last_revision_with_safetensors_and_leaves_the_pickles_out() -> None:
    """The publisher's main holds pickle weights only (D-429 refuses them). The owner's ruling of 2026-11-12: the
    publisher's own revision that carries model.safetensors; no conversion, no other embedder."""
    doc = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    b = next(x for x in doc["builds"] if x["build_id"] == pin_model.EMBED_BUILD)
    rev = "7b44caba5c06fd6f1ef1d2786261e636c38e4295"
    assert b["revision"] == b["expected"]["revision"] == b["provenance"]["revision"] == rev
    assert b["provenance"]["copy"] == "publisher-subset"
    assert set(b["provenance"]["left_out"]) == {"pytorch_model.bin", "colbert_linear.pt", "sparse_linear.pt"}
    assert all(name.endswith(pin_model.REFUSED_SUFFIXES) for name in b["provenance"]["left_out"])
    # from the first hash of the real folder (lane G, 2026-11-12), never guessed
    assert b["expected"]["manifest_sha256"] == "e131f3203849cd7ba89144fdefce52c950bd748c285c2235c1f5628ddcc6e895"
    register = (ROOT / "docs" / "licences" / "register.csv").read_text(encoding="utf-8")
    assert f"revision {rev},BAAI/bge-m3" in register


# ------------------------------------------------------------------------------------------------ M6
def test_the_image_gates_run_when_the_embed_service_or_its_pin_changes() -> None:
    wf = (ROOT.parent / ".github" / "workflows" / "trialbox-images.yml").read_text(encoding="utf-8")
    paths = wf[wf.index("pull_request:") : wf.index("push:")]
    for p in ("trialbox/services/embed_service/**", "trialbox/tools/pin_model.py", "trialbox/models/registry.yaml",
              "trialbox/tools/tiny_embedder.py", "trialbox/tests/integration/test_embed_production_start.py"):  # fmt: skip
        assert f'"{p}"' in paths, p
