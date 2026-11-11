"""The embedder under control (T-607, D-429; deep review LLM-013, LLM-014, DEP-010).

- the settings wizard writes an embed mode the service accepts, and that output starts the service;
- ``hash`` (and an unset mode) is refused by the embed service in PRODUCTION;
- the embedder is one registry build, pinned by ``tools/pin_model.py`` like a model, and the service loads only the
  weights that match the pin; pickle weights, code and a folder without safetensors are refused.

The weights here are stand-ins (a few bytes named ``model.safetensors``): the real values come from the G1 record
(T-004) and go where D-429 says. sentence-transformers is replaced by a fake module, so nothing is downloaded.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml
from embed_service import embedder as emb
from registry.registry import DEFAULT_PATH

from tools import pin_model, settings_wizard

ROOT = Path(__file__).resolve().parents[2]
ANSWERS_C = ROOT / "tests/fixtures/onboarding/site_c_answers.yaml"


class _FakeST:
    def __init__(self, path: str, device: str = "cpu", trust_remote_code: bool = True) -> None:
        assert trust_remote_code is False  # SEC-63: never run code from the weight folder
        self.path = path

    def encode(self, texts: list[str], **_: Any) -> list[list[float]]:
        return [[1.0] + [0.0] * (emb.DIM - 1) for _ in texts]


@pytest.fixture(autouse=True)
def fake_st(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=_FakeST))


def _weights(folder: Path, name: str = "model.safetensors", data: bytes = b"stand-in weights") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    (folder / "config.json").write_text("{}", encoding="utf-8")
    return folder


def _registry(tmp_path: Path, expected: str | None) -> Path:
    """The committed registry with the embedder's expected manifest filled in, as D-429 says it will be from G1."""
    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    for b in doc["builds"]:
        if b["build_id"] == emb.EMBED_BUILD:
            b["expected"] = {"manifest_sha256": expected, "revision": "0" * 40 if expected else None}
    out = tmp_path / "registry.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return out


def _pin(tmp_path: Path, folder: Path) -> Path:
    """Pin the stand-in embedder through pin_model, as an operator would; returns the site override."""
    reg = _registry(tmp_path, pin_model.weight_manifest(folder).sha256)
    out = tmp_path / "site" / "registry.site.yaml"
    pin_model.pin(
        pin_model.EMBED_BUILD, folder, served_name=pin_model.EMBED_BUILD, endpoint="embed", out=out, registry_path=reg
    )
    return out


def test_one_registry_build_for_the_embedder() -> None:
    doc = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    rows = [b for b in doc["builds"] if b["alias"] == "e-embed"]
    assert [b["build_id"] for b in rows] == [emb.EMBED_BUILD] == [pin_model.EMBED_BUILD]
    assert rows[0]["status"] == "candidate" and "embed" in rows[0]["served"]
    assert rows[0]["sha256"] is None  # no hash is invented before the G1 record


def test_the_wizard_writes_a_mode_the_service_accepts(tmp_path: Path) -> None:
    a = yaml.safe_load(ANSWERS_C.read_text(encoding="utf-8"))
    dirs = [ANSWERS_C.parent / "mapping"]
    _, gpu_env, _ = settings_wizard.build({**a, "llm_mode": "gpu"}, dirs)
    _, stub_env, _ = settings_wizard.build({**a, "llm_mode": "stub"}, dirs)
    assert emb.normalise_mode(gpu_env["TB_EMBED_MODE"]) == "model"
    assert emb.normalise_mode(stub_env["TB_EMBED_MODE"]) == "hash"
    # the wizard's GPU output starts the service in PRODUCTION once the embedder is pinned
    folder = _weights(tmp_path / "models" / "embedder")
    override = _pin(tmp_path, folder)
    e = emb.service_embedder(
        {
            "TB_ENV": "PRODUCTION",
            "TB_EMBED_MODE": gpu_env["TB_EMBED_MODE"],
            "TB_EMBED_MODEL_PATH": str(folder),
            "TB_REGISTRY_OVERRIDE": str(override),
        }
    )
    assert isinstance(e, emb.LocalEmbedder) and e.model == emb.EMBED_BUILD
    assert e.weights_sha256 == yaml.safe_load(override.read_text(encoding="utf-8"))["builds"][emb.EMBED_BUILD]["sha256"]
    assert len(e.embed(["a note"])[0]) == emb.DIM
    # the stub box's output starts a DEV service
    assert isinstance(
        emb.service_embedder({"TB_ENV": "DEV", "TB_EMBED_MODE": stub_env["TB_EMBED_MODE"]}), emb.HashEmbedder
    )


def test_the_old_mode_name_still_starts_and_unknown_modes_are_named() -> None:
    assert emb.normalise_mode("bge-m3") == "model"
    with pytest.raises(ValueError, match="use one of model, hash, http"):
        emb.normalise_mode("bogus")
    with pytest.raises(emb.EmbedderRefused, match="client of this service"):
        emb.service_embedder({"TB_ENV": "DEV", "TB_EMBED_MODE": "http"})


@pytest.mark.parametrize("env", [{"TB_ENV": "PRODUCTION", "TB_EMBED_MODE": "hash"}, {"TB_EMBED_MODE": "hash"}])
def test_hash_is_refused_in_production(env: dict[str, str]) -> None:
    with pytest.raises(emb.EmbedderRefused, match="refused in PRODUCTION"):
        emb.service_embedder(env)


def test_an_unset_mode_in_production_needs_the_pinned_embedder(tmp_path: Path) -> None:
    folder = _weights(tmp_path / "embedder")
    with pytest.raises(emb.EmbedderRefused, match="no pin for e-embed-1"):
        emb.service_embedder({"TB_ENV": "PRODUCTION", "TB_EMBED_MODEL_PATH": str(folder)})
    assert isinstance(emb.service_embedder({"TB_ENV": "DEV"}), emb.HashEmbedder)


def test_weights_that_differ_from_the_pin_are_refused(tmp_path: Path) -> None:
    folder = _weights(tmp_path / "embedder")
    override = _pin(tmp_path, folder)
    (folder / "model.safetensors").write_bytes(b"other weights")
    for env_name in ("PRODUCTION", "DEV"):  # a pin, when there is one, is checked everywhere
        with pytest.raises(emb.EmbedderRefused, match="not the pinned weights"):
            emb.service_embedder(
                {
                    "TB_ENV": env_name,
                    "TB_EMBED_MODE": "model",
                    "TB_EMBED_MODEL_PATH": str(folder),
                    "TB_REGISTRY_OVERRIDE": str(override),
                }
            )


@pytest.mark.parametrize(
    ("name", "why"),
    [("pytorch_model.bin", "refused file types"), ("model.gguf", "no .safetensors"), ("modeling.py", "refused file")],
)
def test_pickle_code_and_non_safetensors_folders_are_refused(tmp_path: Path, name: str, why: str) -> None:
    folder = tmp_path / "embedder"
    folder.mkdir()
    (folder / name).write_bytes(b"x")
    with pytest.raises(emb.EmbedderRefused, match=why):
        emb.LocalEmbedder(str(folder))


def test_the_service_digest_is_pin_models_digest(tmp_path: Path) -> None:
    folder = _weights(tmp_path / "embedder")
    (folder / "sub").mkdir()
    (folder / "sub" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (folder / ".cache").mkdir()
    (folder / ".cache" / "x").write_text("hidden", encoding="utf-8")
    assert emb.manifest_sha256(folder) == pin_model.weight_manifest(folder).sha256


def test_pin_model_succeeds_on_the_embedder_and_verifies_it(tmp_path: Path) -> None:
    folder = _weights(tmp_path / "embedder")
    override = _pin(tmp_path, folder)
    entry = yaml.safe_load(override.read_text(encoding="utf-8"))["builds"][pin_model.EMBED_BUILD]
    assert entry["served"] == {"embed": pin_model.EMBED_BUILD} and entry["weights"]["trust"] == "expected"
    assert (override.parent / "manifests" / f"{pin_model.EMBED_BUILD}.sha256").is_file()
    ok, lines = pin_model.verify_all(tmp_path, override)
    assert ok, lines


def test_pin_model_refuses_an_unexpected_or_gguf_embedder(tmp_path: Path) -> None:
    folder = _weights(tmp_path / "embedder")
    out = tmp_path / "site" / "registry.site.yaml"
    # the committed row has no expected weights yet (G1): no trust on first use
    with pytest.raises(pin_model.PinError, match="no trust on first use"):
        pin_model.pin(pin_model.EMBED_BUILD, folder, served_name="e", endpoint="embed", out=out)
    gguf = tmp_path / "gguf"
    gguf.mkdir()
    (gguf / "model.gguf").write_bytes(b"x")
    reg = _registry(tmp_path, pin_model.weight_manifest(gguf).sha256)
    with pytest.raises(pin_model.PinError, match="needs .safetensors"):
        pin_model.pin(pin_model.EMBED_BUILD, gguf, served_name="e", endpoint="embed", out=out, registry_path=reg)
    assert not out.exists()


def test_the_service_refuses_at_start_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_EMBED_MODE", "hash")
    saved = sys.modules.pop("embed_service.app", None)
    try:
        with pytest.raises(emb.EmbedderRefused):
            importlib.import_module("embed_service.app")
    finally:
        sys.modules.pop("embed_service.app", None)
        if saved is not None:
            sys.modules["embed_service.app"] = saved
