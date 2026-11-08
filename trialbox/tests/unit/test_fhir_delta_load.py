"""Delta loads into fhir-store (TB-PLAN-03 step 7, D-122): a night where 1 % of patients changed sends only them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from adapter import load_fhir
from adapter.ndjson import write_snapshot


def _snap(path: Path, n: int, changed: set[int]) -> Path:
    pats = [{"resourceType": "Patient", "id": f"p{i}", "gender": "female" if i % 2 else "male"} for i in range(n)]
    conds = [
        {
            "resourceType": "Condition",
            "id": f"c{i}",
            "subject": {"reference": f"Patient/p{i}"},
            "code": {
                "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9" if i in changed else "I10"}]
            },
        }
        for i in range(n)
    ]
    for i in changed:  # the patient record itself changed too (a new birth date correction)
        pats[i]["birthDate"] = "1950-01-01"
    write_snapshot(path, {"Patient": pats, "Condition": conds})
    return path


def test_one_percent_changed_reloads_only_those(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.extend(e["request"]["url"] for e in json.loads(req.content)["entry"])
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    ledger = tmp_path / "ledger"
    n = 1000
    loaded, deleted = load_fhir.sync_snapshot("http://hapi/fhir", _snap(tmp_path / "s1", n, set()), ledger)
    assert (loaded, deleted) == (2 * n, 0)
    sent.clear()
    changed = set(range(0, n, 100))  # 10 of 1000 patients = 1 %
    loaded, deleted = load_fhir.sync_snapshot("http://hapi/fhir", _snap(tmp_path / "s2", n, changed), ledger)
    assert (loaded, deleted) == (2 * len(changed), 0)
    assert sorted(sent) == sorted([f"Patient/p{i}" for i in changed] + [f"Condition/c{i}" for i in changed])
    sent.clear()
    assert load_fhir.sync_snapshot("http://hapi/fhir", _snap(tmp_path / "s3", n, changed), ledger) == (0, 0)
    assert sent == []
    # a full reload stays available (after a store restore)
    load_fhir.sync_snapshot("http://hapi/fhir", tmp_path / "s3", ledger, full=True)
    assert len(sent) == 2 * n


def test_a_failed_night_reloads_its_changes_the_next_night(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, Any] = {"fail": False, "sent": []}

    def handler(req: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500, text="down")
        state["sent"].extend(e["request"]["url"] for e in json.loads(req.content)["entry"])
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    ledger = tmp_path / "ledger"
    load_fhir.sync_snapshot("http://hapi/fhir", _snap(tmp_path / "s1", 50, set()), ledger)
    state["fail"] = True
    with pytest.raises(RuntimeError):
        load_fhir.sync_snapshot("http://hapi/fhir", _snap(tmp_path / "s2", 50, {3}), ledger)
    state["fail"], state["sent"] = False, []
    assert load_fhir.sync_snapshot("http://hapi/fhir", tmp_path / "s2", ledger) == (2, 0)
    assert sorted(state["sent"]) == ["Condition/c3", "Patient/p3"]


def test_a_ledger_from_before_the_upgrade_loads_everything_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.extend(e["request"]["url"] for e in json.loads(req.content)["entry"])
        return httpx.Response(200, json={"resourceType": "Bundle", "type": "transaction-response"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "Patient.txt").write_text("".join(f"p{i}\n" for i in range(20)), encoding="utf-8")  # ids only
    snap = _snap(tmp_path / "s1", 20, set())
    assert load_fhir.sync_snapshot("http://hapi/fhir", snap, ledger) == (40, 0)
    assert load_fhir.sync_snapshot("http://hapi/fhir", snap, ledger) == (0, 0)
