"""Card H-90: in a models folder, every file a measured record lists passes only on a sha256 recorded for it, whatever
its kind, and is not read; a file no record lists goes through the vocabulary check as before. The records are those
the registry rows of the deployed pairs and of the embedder name (``deploy/measured/``). The bytes here are synthetic:
the real files are not in the repository, so where a test needs a recorded hash to match, it stands a synthetic file's
digest in for the record's (the record's own entry is read)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import vocab_bundle_check as vbc

ROOT = Path(__file__).resolve().parents[2]
EMBEDDER = ROOT / "deploy/measured/embedder_files.e-embed-1.json"
SERVING = ROOT / "deploy/measured/serving_config.rtxpro6000.json"
TOKENIZER = "sentencepiece.bpe.model"
VERIFIER = "qwen3.5-9b-4bit"  # the verifier's default folder (tools.pin_model.PROFILE_PAIRS)
BLOB = b"\x00\x01synthetic stand-in for a measured file\x00"
MEASURED = vbc.measured_files()


def _record_sha(record: Path, path: str, server: int = 0) -> str:
    files = json.loads(record.read_text(encoding="utf-8"))["servers"][server]["model_files"]
    return next(str(f["sha256"]) for f in files if f["path"] == path)


def _models(tmp_path: Path, rel: str, blob: bytes = BLOB) -> Path:
    m = tmp_path / "models"
    (m / rel).parent.mkdir(parents=True, exist_ok=True)
    (m / rel).write_bytes(blob)
    return m


def _stand_in(monkeypatch: pytest.MonkeyPatch, blob: bytes, digest: str) -> None:
    """The synthetic ``blob`` hashes to ``digest``; every other file to its own sha256."""

    def fake(path: Path) -> str:
        data = path.read_bytes()
        return digest if data == blob else hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(vbc, "_sha256", fake, raising=False)


def test_the_records_cover_the_embedder_and_the_serving_pairs_folders() -> None:
    assert MEASURED[f"embedder/{TOKENIZER}"] == {_record_sha(EMBEDDER, TOKENIZER)}
    assert MEASURED[f"{VERIFIER}/recipe.yaml"] == {_record_sha(SERVING, "recipe.yaml", server=1)}
    assert {k.split("/")[0] for k in MEASURED} == {"embedder", VERIFIER, "gemma-4-26b-a4b-it-4bit"}
    embedder = json.loads(EMBEDDER.read_text(encoding="utf-8"))["servers"][0]["model_files"]
    assert {k for k in MEASURED if k.startswith("embedder/")} == {f"embedder/{f['path']}" for f in embedder}
    assert MEASURED["embedder/1_Pooling/config.json"] == {_record_sha(EMBEDDER, "1_Pooling/config.json")}


def test_the_real_records_tokenizer_passes_by_its_measured_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    want = _record_sha(EMBEDDER, TOKENIZER)
    _stand_in(monkeypatch, BLOB, want)
    rep = vbc.check(models=[_models(tmp_path, f"embedder/{TOKENIZER}")])
    assert rep.problems == []
    assert any(TOKENIZER in n and want[:12] in n for n in rep.notes)


def test_the_tokenizers_name_with_another_hash_fails(tmp_path: Path) -> None:
    rep = vbc.check(models=[_models(tmp_path, f"embedder/{TOKENIZER}")])
    assert len(rep.problems) == 1
    assert TOKENIZER in rep.problems[0] and "is not the measured record's" in rep.problems[0]
    assert _record_sha(EMBEDDER, TOKENIZER)[:12] in rep.problems[0]


def test_an_unlisted_model_file_fails(tmp_path: Path) -> None:
    rep = vbc.check(models=[_models(tmp_path, "embedder/unlisted.bpe.model")])
    assert len(rep.problems) == 1
    assert "unlisted.bpe.model: cannot be checked: binary content of an unknown kind" in rep.problems[0]


def test_a_listed_text_file_with_one_changed_byte_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = b'{"model_type": "invented", "hidden_size": 1024}\n'
    _stand_in(monkeypatch, text, _record_sha(EMBEDDER, "config.json"))
    assert vbc.check(models=[_models(tmp_path / "a", "embedder/config.json", text)]).problems == []
    changed = text.replace(b"1024", b"1025")
    rep = vbc.check(models=[_models(tmp_path / "b", "embedder/config.json", changed)])
    assert (
        len(rep.problems) == 1
        and "config.json" in rep.problems[0]
        and "is not the measured record's" in rep.problems[0]
    )


def test_a_listed_recipe_with_the_recorded_hash_passes_unparsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = b"recipe: [an unclosed list\n  stage: {\n"
    m = _models(tmp_path / "a", "unlisted-model/recipe.yaml", broken)
    assert any("does not parse" in p or "cannot" in p for p in vbc.check(models=[m]).problems)  # read when unlisted
    _stand_in(monkeypatch, broken, _record_sha(SERVING, "recipe.yaml", server=1))
    rep = vbc.check(models=[_models(tmp_path / "b", f"{VERIFIER}/recipe.yaml", broken)])
    assert rep.problems == [] and any("recipe.yaml" in n for n in rep.notes)


def test_stand_in_weights_under_a_measured_folder_are_refused(tmp_path: Path) -> None:
    m = tmp_path / "models/embedder"
    m.mkdir(parents=True)
    (m / "config.json").write_text('{"model_type": "invented"}', encoding="utf-8")
    (m / "model.safetensors").write_bytes(b"\x00not a model")
    (m / "README.md").write_text("an invented embedder\n", encoding="utf-8")
    rep = vbc.check(models=[tmp_path / "models"])
    assert len(rep.problems) == 3 and all("is not the measured record's" in p for p in rep.problems)


@pytest.mark.parametrize("rel", sorted(MEASURED))
def test_no_listed_file_passes_with_a_hash_other_than_the_records(tmp_path: Path, rel: str) -> None:
    """The invariant: every file any measured record lists, given bytes of another hash, is refused."""
    blob = b"synthetic bytes, not the measured file: " + rel.encode()
    assert hashlib.sha256(blob).hexdigest() not in MEASURED[rel]
    rep = vbc.check(models=[_models(tmp_path, rel, blob)])
    assert len(rep.problems) == 1 and rel in rep.problems[0] and "is not the measured record's" in rep.problems[0]


def test_a_record_that_is_not_the_rows_expected_manifest_covers_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    doc = yaml.safe_load((ROOT / "models/registry.yaml").read_text(encoding="utf-8"))
    for row in doc["builds"]:
        if row.get("build_id") == "e-embed-1":
            row["expected"]["manifest_sha256"] = "0" * 64
    reg = tmp_path / "registry.yaml"
    reg.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("TB_RELEASE_REGISTRY", str(reg))
    got = vbc.measured_files()
    assert not [k for k in got if k.startswith("embedder/")] and {k for k in got} == {
        k for k in MEASURED if not k.startswith("embedder/")
    }
