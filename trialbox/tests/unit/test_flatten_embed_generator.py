from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime

from embed_service.embedder import HashEmbedder
from lake.flatten import Flattener

from tools.synth.generator import SiteData, das28, egfr_ckd_epi_2021, generate


def test_flatten_timezone_and_components() -> None:
    f = Flattener("Asia/Taipei")
    obs = {
        "resourceType": "Observation",
        "id": "o1",
        "subject": {"reference": "Patient/p"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9"}]},
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "effectiveDateTime": "2026-03-01T23:30:00+00:00",
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                "valueQuantity": {"value": 150, "code": "mm[Hg]"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                "valueQuantity": {"value": 90, "code": "mm[Hg]"},
            },
        ],
    }
    rows = f.observations(obs)
    assert [r["code"] for r in rows] == ["85354-9", "8480-6", "8462-4"]
    assert rows[1]["value_num"] == 150.0 and rows[1]["oid"] == "o1.8480-6"
    assert rows[0]["effective"] == datetime(2026, 3, 2, 7, 30)  # converted to Asia/Taipei local time
    doc = {
        "resourceType": "DocumentReference",
        "id": "d",
        "subject": {"reference": "Patient/p"},
        "date": "2026-01-01T10:00:00+08:00",
        "type": {"text": "progress"},
        "content": [{"attachment": {"data": base64.b64encode("病歷".encode()).decode()}}],
    }
    assert f.document(doc)["text"] == "病歷"
    assert f.d("2026-01-01") == date(2026, 1, 1)


def test_hash_embedder_deterministic_unit_norm() -> None:
    e = HashEmbedder()
    v1, v2 = e.embed(["痛風發作兩次", "痛風發作兩次"])
    assert v1 == v2 and len(v1) == 1024
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9
    a, b, c = e.embed(["痛風急性發作", "急性痛風發作", "類風濕性關節炎"])

    def dot(x: list[float], y: list[float]) -> float:
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert dot(a, b) > dot(a, c)


def test_generator_is_deterministic_and_covers_states() -> None:
    a = generate(seed=7, n=200)
    b = generate(seed=7, n=200)

    def h(d: SiteData) -> str:
        return hashlib.sha256(json.dumps(d.tables, sort_keys=True, default=str).encode()).hexdigest()

    assert h(a) == h(b)
    states = [s for s in a.states.values()]
    for key, required in {
        "bmi": {">30", "<24", "missing"},
        "urate": {"good", "bad", "missing"},
        "ult": {"long", "none"},
        "das28_recent": {"high", "low", "none"},
    }.items():
        seen = {s[key] for s in states if key in s}
        assert required <= seen, (key, seen)
    assert len(a.needles) == 20


def test_reference_formulas_published_examples() -> None:
    # CKD-EPI 2021 (race-free): 50-year-old man, creatinine 1.0 mg/dL -> 92 mL/min/1.73m2 (NKF calculator)
    assert round(egfr_ckd_epi_2021(1.0, 50, female=False)) == 92
    # 60-year-old woman, creatinine 0.8 -> 84
    assert round(egfr_ckd_epi_2021(0.8, 60, female=True)) == 84
    # DAS28-ESR with TJC 4, SJC 2, ESR 30, GH 50 -> 4.60
    assert round(das28(4, 2, 50, 30, None), 2) == 4.60
