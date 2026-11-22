"""Card H-90: a site bundle's models folder carries the embedder's tokenizer file, binary content of no known kind.
``tools/vocab_bundle_check.py`` checks a file the embedder's measured record lists by its measured sha256, not by its
extension; a binary file the record does not list is still refused. The bytes here are synthetic: the real tokenizer
file is not in the repository, so the first test stands its sha256 in for the record's."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import vocab_bundle_check as vbc

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "deploy/measured/embedder_files.e-embed-1.json"
TOKENIZER = "sentencepiece.bpe.model"
BLOB = b"\x00\x01synthetic stand-in for the embedder's tokenizer file\x00"


def _record_sha(path: str) -> str:
    files = json.loads(RECORD.read_text(encoding="utf-8"))["servers"][0]["model_files"]
    return next(str(f["sha256"]) for f in files if f["path"] == path)


def _models(tmp_path: Path, name: str) -> Path:
    m = tmp_path / "models"
    (m / "embedder").mkdir(parents=True)
    (m / "embedder" / name).write_bytes(BLOB)
    (m / "embedder" / "config.json").write_text('{"model_type": "invented"}', encoding="utf-8")
    return m


def test_the_real_records_tokenizer_passes_by_its_measured_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    want = _record_sha(TOKENIZER)
    monkeypatch.setattr(vbc, "_sha256", lambda b: want if b == BLOB else hashlib.sha256(b).hexdigest(), raising=False)
    rep = vbc.check(models=[_models(tmp_path, TOKENIZER)])
    assert rep.problems == []
    assert any(TOKENIZER in n and want[:12] in n for n in rep.notes)


def test_the_tokenizers_name_with_another_hash_fails(tmp_path: Path) -> None:
    rep = vbc.check(models=[_models(tmp_path, TOKENIZER)])
    assert len(rep.problems) == 1
    assert TOKENIZER in rep.problems[0] and "differs from the measured record's" in rep.problems[0]
    assert _record_sha(TOKENIZER)[:12] in rep.problems[0]


def test_an_unlisted_model_file_fails(tmp_path: Path) -> None:
    rep = vbc.check(models=[_models(tmp_path, "unlisted.bpe.model")])
    assert len(rep.problems) == 1
    assert "unlisted.bpe.model: cannot be checked: binary content of an unknown kind" in rep.problems[0]
