"""D-418 (T-619c, DATA-016): a qualitative result a FHIR feed sends as text is read like a mapped one.

The mapped sources (CSV, CGRD, SS-MIX2) read 陰性, 陽性, 未檢出 and Non-reactive in the mapping step (D-334). A
``fhir_bulk`` feed has no mapping step, so its ``valueString`` stayed text and a hepatitis B, IGRA or pregnancy
criterion on it was always unknown. The adapter now reads the word into the LOINC answer; a held word stays text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapter.pipeline import VALUE_SOURCE, AdapterConfig, apply_presence_words, run_ingest
from lake.flatten import Flattener

ROOT = Path(__file__).resolve().parents[2]
LOINC = "http://loinc.org"
HBSAG, IGRA = "5196-1", "71774-4"
SNAP = "2026-10-04"


def _obs(oid: str, text: str, code: str = HBSAG, system: str = LOINC) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "subject": {"reference": "Patient/p1"},
        "code": {"coding": [{"system": system, "code": code}]},
        "effectiveDateTime": "2026-09-20T09:00:00+08:00",
        "valueString": text,
    }


def _answer(r: dict[str, Any]) -> str | None:
    cc = r.get("valueCodeableConcept")
    return cc["coding"][0]["code"] if cc else None


def test_presence_words_become_the_loinc_answer_and_keep_their_text() -> None:
    obs = [
        _obs("ja-pos", "陽性"),
        _obs("ja-neg", "陰性(-)"),
        _obs("zh-neg", "未檢出", IGRA),
        _obs("en-neg", "Non-reactive"),
        _obs("plus", "2+"),
        _obs("held", "判定保留"),  # held: a person reads it
        _obs("pm", "±"),
        _obs("clash", "陰性(+)"),  # word and sign disagree
        _obs("note", "see comment"),
        _obs("number", "0.3"),
        _obs("local", "陽性", "HBS", "urn:site:lab"),  # not LOINC: no answer list to read into
    ]
    assert apply_presence_words(obs) == 5
    got = {r["id"]: r for r in obs}
    assert {k: _answer(got[k]) for k in ("ja-pos", "ja-neg", "zh-neg", "en-neg", "plus")} == {
        "ja-pos": "LA6576-8",
        "ja-neg": "LA6577-6",
        "zh-neg": "LA6577-6",
        "en-neg": "LA6577-6",
        "plus": "LA6576-8",
    }
    assert got["ja-pos"]["valueCodeableConcept"]["text"] == "陽性" and "valueString" not in got["ja-pos"]
    assert {"system": VALUE_SOURCE, "code": "presence-word"} in got["ja-pos"]["meta"]["tag"]
    for k in ("held", "pm", "clash", "note", "number", "local"):
        assert "valueCodeableConcept" not in got[k] and "valueString" in got[k] and "meta" not in got[k], k


def test_the_lake_reads_the_answer_a_criterion_compares() -> None:
    obs = [_obs("pos", "陽性"), _obs("held", "判定保留")]
    apply_presence_words(obs)
    rows = {r["oid"]: r for r in Flattener("Asia/Taipei").flatten({"Observation": obs})["observation"]}
    assert rows["pos"]["value_code"] == "LA6576-8"
    assert rows["held"]["value_code"] is None  # unknown to every engine, never a negative


def test_a_fhir_feed_reads_presence_words_into_its_snapshot_and_counts_them(tmp_path: Path) -> None:
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(
        lake_dir=tmp_path / "lake",
        secrets_dir=sec,
        site_id="T",
        audit_dir=tmp_path / "audit",
        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml",
    )
    exp = tmp_path / "bulk"
    exp.mkdir()
    feed = {
        "Patient": [{"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "1971-03-01"}],
        "Observation": [_obs("pos", "陽性"), _obs("neg", "Negative", IGRA), _obs("held", "判定保留")],
    }
    for rtype, items in feed.items():
        (exp / f"{rtype}.ndjson").write_text("\n".join(json.dumps(r) for r in items) + "\n", encoding="utf-8")
    run_ingest(cfg, "fhir_bulk", str(exp), snapshot=SNAP, load_fhir=False, rebuild_lake=False, validate=False)
    out = tmp_path / "lake" / "ndjson" / SNAP / "Observation.ndjson"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    answers = sorted(_answer(r) or r.get("valueString") for r in rows)
    assert answers == ["LA6576-8", "LA6577-6", "判定保留"]
    audit = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").rglob("*") if p.is_file())
    assert '"presence_words_read":2' in audit
