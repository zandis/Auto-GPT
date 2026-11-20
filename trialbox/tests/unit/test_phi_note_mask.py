"""T-600 (FR-DEID-01, CR-028, DATA-020, D-337): names, phone numbers and chart numbers in note text are masked before
chunks, the full-text index and the embeddings; the lake's ``document`` table keeps the original under ``phi``."""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from embed_service.embedder import HashEmbedder
from lake.flatten import PHI_COLUMNS
from lake.store import Lake, fts_extension_path
from lake.textproc import tokens
from tb_common.phi_guard import MASK_CHAR, NOTE_MASK_VERSION, mask_note, note_spans

from tools.synth.generator import Generator

REF = date(2026, 10, 5)
SITE_MRN = r"^\d{8}$"
PLANTED = ("name", "chart", "phone", "insurer", "address")  # address: D-745


# ---------------------------------------------------------------------------------------------- the masker
@pytest.mark.parametrize(
    ("text", "kept", "gone"),
    [
        ("記錄者：王志明醫師。血壓穩定。", ["記錄者：", "醫師。血壓穩定。"], ["王志明"]),
        ("家屬林淑芬來電詢問病情。", ["家屬", "來電詢問病情。"], ["林淑芬"]),
        ("病歷號30000012。聯絡電話0912345678。", ["病歷號", "聯絡電話"], ["30000012", "0912345678"]),
        ("健保卡號A123456780。", ["健保卡號"], ["A123456780"]),
        ("陳小明，男，65歲，痛風。", ["，男，65歲，痛風。"], ["陳小明"]),
        ("記載医：佐藤　花子。内服継続。", ["記載医：", "。内服継続。"], ["佐藤", "花子"]),
        ("家族の田中　陽子さんより電話あり。", ["家族の", "さんより電話あり。"], ["田中", "陽子"]),
        ("カルテ番号20000007。連絡先090-1234-5678。", ["カルテ番号", "連絡先"], ["20000007", "090-1234-5678"]),
        ("Seen by Dr James Smith. Gout flare.", ["Seen by Dr ", ". Gout flare."], ["James", "Smith"]),
        ("Daughter Mary Brown phoned. Chart no. 30000099.", ["Daughter ", " phoned. Chart no. "], ["Mary", "30000099"]),
    ],
)
def test_mask_note_masks_identifiers_and_keeps_the_rest(text: str, kept: list[str], gone: list[str]) -> None:
    out = mask_note(text)
    assert len(out) == len(text)
    for k in kept:
        assert k in out
    for g in gone:
        assert g not in out
    assert mask_note(out) == out  # masking masked text changes nothing


def test_clinical_text_is_left_alone() -> None:
    text = "尿酸 9.2 mg/dL，2025年3月2日痛風發作。轉介腎臟科醫師。HbA1c 7.1%。eGFR 45。新陳代謝科追蹤。"
    assert note_spans(text) == []
    assert mask_note(text) == text


def test_site_pattern_masks_an_unlabelled_chart_number_and_keeps_white_space() -> None:
    text = "f/u 30000012\n下次回診"
    assert "30000012" in mask_note(text)  # no label, no site pattern: left
    out = mask_note(text, SITE_MRN)
    assert out == f"f/u {MASK_CHAR * 8}\n下次回診"
    assert MASK_CHAR not in "".join(tokens(out))  # the tokenizer gives the full-text index nothing for a masked span


def _gold(
    seed: int, site: str, n: int, prefix: str, style: str, mix: dict[str, float]
) -> list[tuple[str, dict[str, Any]]]:
    g = Generator(seed, site, REF, n, prefix, style=style, lang_mix=mix, gold=True)
    g.run()
    text = {r["note_no"]: r["text"] for r in g.t["note"]}
    return [(text[gn["note_no"]], gn) for gn in g.gold_notes]


@pytest.mark.parametrize(
    "args",
    [(9, "TW-T", 150, "3", "TW", {"zh-TW": 0.7, "en": 0.3}), (5, "JP-T", 150, "2", "JP", {"ja": 0.8, "en": 0.2})],
    ids=["tw", "jp"],
)
def test_planted_identifiers_in_synthetic_notes_are_masked_and_findings_kept(args: tuple[Any, ...]) -> None:
    """Every planted name, chart number, phone and insurance number is masked; every planted clinical finding is
    left exactly as written; nothing outside the planted PHI is masked."""
    seen = {k: 0 for k in PLANTED}
    for text, gn in _gold(*args):
        out = mask_note(text, SITE_MRN)
        phi: set[int] = set()
        for sp in gn["phi"]:
            phi.update(range(sp["start"], sp["end"]))
            if sp["type"] in PLANTED:
                seen[sp["type"]] += 1
                value = text[sp["start"] : sp["end"]]
                assert all(out[i] == MASK_CHAR or text[i].isspace() for i in range(sp["start"], sp["end"])), value
        for f in gn["findings"]:
            assert out[f["start"] : f["end"]] == text[f["start"] : f["end"]]
        assert all(a == b for i, (a, b) in enumerate(zip(text, out, strict=True)) if i not in phi)
    assert all(seen.values()), seen  # every kind was planted at least once


# ---------------------------------------------------------------------------------------------- the lake
NOTES = {
    "d1": "痛風發作，尿酸9.2。記錄者：王志明醫師。家屬林淑芬來電詢問病情。聯絡電話0912345678。病歷號30000012。",
    "d2": "Seen by Dr James Smith. Daughter Mary Brown phoned. Contact 0987654321. Chart no. 30000099. Gout.",
}
IDENTIFIERS = ["王志明", "林淑芬", "0912345678", "30000012", "James", "Smith", "Mary", "Brown", "0987654321",
               "30000099"]  # fmt: skip


class SpyEmbedder(HashEmbedder):
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return super().embed(texts)


def _ndjson(d: Path) -> Path:
    d.mkdir(parents=True)
    pts = [{"resourceType": "Patient", "id": p, "gender": "male", "birthDate": "1960-01-01"} for p in ("p1", "p2")]
    docs = [
        {
            "resourceType": "DocumentReference",
            "id": did,
            "subject": {"reference": f"Patient/p{i + 1}"},
            "date": "2026-01-01T10:00:00+08:00",
            "type": {"text": "progress"},
            "content": [{"attachment": {"data": base64.b64encode(t.encode()).decode()}}],
        }
        for i, (did, t) in enumerate(NOTES.items())
    ]
    for name, rows in (("Patient", pts), ("DocumentReference", docs)):
        (d / f"{name}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    from tb_common import id_rule

    id_rule.write_snapshot_record(d)  # D-1253: a snapshot of this release says its id rule
    return d


def test_planted_identifiers_are_absent_from_chunks_fts_and_embedding_inputs(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", "Asia/Taipei", SITE_MRN)
    spy = SpyEmbedder()
    lake.rebuild("2026-01-02", spy, _ndjson(tmp_path / "nd"))
    con = duckdb.connect(str(tmp_path / "lake" / "db" / "2026-01-02.duckdb"), read_only=True)
    try:
        con.execute(f"LOAD '{fts_extension_path()}'")
        chunks = con.execute("SELECT text, tok FROM document_chunk ORDER BY chunk_key").fetchall()
        originals = dict(con.execute("SELECT did, text FROM document").fetchall())
        fts_terms = {r[0] for r in con.execute("SELECT term FROM fts_main_document_chunk.dict").fetchall()}
        note_mask = con.execute("SELECT note_mask FROM lake_meta").fetchone()
    finally:
        con.close()
    assert chunks and spy.inputs
    for ident in IDENTIFIERS:
        assert all(ident not in text for text, _ in chunks), ident
        assert all(ident not in tok for _, tok in chunks), ident
        assert all(ident not in x for x in spy.inputs), ident
    for ident in ("0912345678", "30000012", "james", "smith", "0987654321", "30000099", "王志", "林淑"):
        assert ident not in fts_terms
    assert "尿酸" in fts_terms and "gout" in fts_terms  # the clinical words are indexed as before
    assert originals == NOTES  # the lake keeps the original under the phi label
    assert PHI_COLUMNS == {"document": ("text",)}
    assert note_mask == (NOTE_MASK_VERSION,)
    hits = lake.search("p1", "0912345678 王志明", HashEmbedder(), k=5)
    assert all("0912345678" not in h["text"] and "王志明" not in h["text"] for h in hits)


def test_embed_service_masks_its_input(monkeypatch: pytest.MonkeyPatch) -> None:
    from embed_service import app as svc
    from tb_contracts import EmbedRequest

    spy = SpyEmbedder()
    monkeypatch.setattr(svc, "_embedder", spy)
    monkeypatch.setattr(svc, "mrn_regex", lambda: SITE_MRN)
    res = svc.embed(EmbedRequest(texts=["病歷號30000012。家屬林淑芬來電。f/u 30000077", "Gout flare."]))
    assert len(res.vectors) == 2
    assert spy.inputs[1] == "Gout flare."
    assert not any(x in spy.inputs[0] for x in ("30000012", "林淑芬", "30000077"))
