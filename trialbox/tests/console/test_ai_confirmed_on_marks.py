"""D-989 (lane C2's card): a person's decision on a patient a model answered is ``ai.confirmed``.

A PI mark or a "this is wrong, send to review" on a patient with model evidence writes one ``ai.confirmed`` per verdict
a model answered (its ``prov`` not empty): ``record_ref`` (ruleset, version, job, pid, crit), the patient by pseudonym,
``by`` the person, and the decision: Approach ``confirmed``, a review ``rejected``. Not suitable now (a site's own
reasons), Need info, Not now, Withdraw and Undo decide nothing about the model's answer: no event, so the answer stays
unconfirmed (never inferred). A verdict no model answered (``prov`` empty or absent) writes nothing. Synthetic data only."""

from __future__ import annotations

import json
from typing import Any

from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console.test_amendment_rescreen import _csrf, _screen
from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_criterion_labels import _gzqo

PW = "ai-confirmed-password-01"
A, B = "a" * 32, "b" * 32
CALLS = ["01JCALLJUDGE0000000000000A", "01JCALLVERIFY000000000000A"]


def _row(pid: str, tier: str, prov: list[str] | None) -> dict[str, Any]:
    model = {"id": "GZQO-INC-05", "verdict": "pass", "evidence": {"resource_refs": [], "quote": "two flares"}}
    if prov is not None:
        model["prov"] = prov
    return {"pid": pid, "tier": tier, "next_appointment": None, "practitioner_id": "DR-LIN", "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}, "prov": []},
                         model], "actions": [], "n_unknown": 0}  # fmt: skip


def _events(b: dict[str, Any], kind: str = "ai.confirmed") -> list[dict[str, Any]]:
    return [e for f in sorted((b["dir"] / "audit").glob("*.jsonl")) for x in f.read_text().splitlines() if x
            for e in [json.loads(x)] if e["event"] == kind]  # fmt: skip


def _pi(b: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[Any, str, str]:
    _gzqo(b)
    job = _screen(b, 9801, "1.0.0", rows, 0)
    b["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(b, "pi")
    pi, _ = login(b["app"], "pi", PW)
    return pi, _csrf(pi.get("/studies/GZQO/week").text), job.job_id


def test_an_approach_confirms_each_model_answer_of_the_row(box: dict[str, Any]) -> None:  # noqa: F811
    pi, csrf, job = _pi(box, [_row(A, "high", CALLS), _row(B, "review", CALLS)])
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"})
    assert r.status_code == 200, r.text
    (ev,) = _events(box)
    d = ev["detail"]
    assert d["record_kind"] == "verdict" and d["decision"] == "confirmed" and d["by"] == "pi"
    assert d["record_ref"] == {"ruleset": "GZQO", "version": "1.0.0", "job": job, "pid": A, "crit": "GZQO-INC-05"}
    assert d["calls"] == CALLS and ev["actor"] == "console:pi"  # the coded answer (prov empty) writes nothing


def test_not_suitable_now_and_the_other_marks_decide_nothing(box: dict[str, Any]) -> None:  # noqa: F811
    """The integrator's ruling: Not suitable now's reasons are the site's own and may have nothing to do with the
    model, so the chain never reads it as a judgement on the model's answer."""
    from console.sitestore import SiteStore

    pi, csrf, _job = _pi(box, [_row(A, "high", CALLS), _row(B, "review", CALLS)])
    for mark in ("need_info", "not_now", "withdraw"):
        pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": csrf, "mark": mark})
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": csrf, "mark": "not_suitable", "reason": "comorbidity"})
    assert SiteStore().latest_marks("GZQO")[B].mark == "not_suitable"  # the mark is kept
    assert _events(box) == []  # the model's answer stays unconfirmed
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": csrf, "mark": "approach"})
    assert len(_events(box)) == 1
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": csrf, "mark": "undo"})  # back to Not suitable now
    assert len(_events(box)) == 1  # an undo is no decision on the answer


def test_a_row_no_model_answered_writes_nothing(box: dict[str, Any]) -> None:  # noqa: F811
    pi, csrf, _job = _pi(box, [_row(A, "high", None), _row(B, "review", [])])  # before the field, and "no model"
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"})
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": csrf, "mark": "approach"})
    assert _events(box) == []


EXCLUDED = {"ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-10-05", "snapshot": "2026-10-04", "rows": [
    {"pid": "c" * 32, "actions": [], "criteria": [
        {"id": "GZQO-EXC-02", "source": "notes", "reason": "note", "quote": "history of breast cancer 2019",
         "resource_refs": [], "prov": CALLS},
        {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["cond-1"], "prov": []}]},
    {"pid": "d" * 32, "actions": [], "criteria": [
        {"id": "GZQO-EXC-02", "source": "notes", "reason": "note", "quote": "breast cancer", "resource_refs": [],
         "prov": CALLS[:1]},
        {"id": "GZQO-EXC-03", "source": "notes", "reason": "note", "quote": "on dialysis", "resource_refs": [],
         "prov": CALLS[1:]}]},
]}  # fmt: skip


def _with_excluded(b: dict[str, Any]) -> str:
    job = _done_screen(b["backend"], _ulid(9811))
    data = json.dumps(EXCLUDED).encode()
    key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
    b["backend"].objects[key] = data
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key, recipients=[],
                    tag="phi")  # fmt: skip
    b["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    return job.job_id


def test_a_review_rejects_the_model_answers_that_excluded_the_patient(box: dict[str, Any]) -> None:  # noqa: F811
    job = _with_excluded(box)
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    crc, csrf = login(box["app"], "crc", PW)
    r = crc.post(f"/studies/GZQO/not-matched/{'c' * 32}/review", data={"csrf": csrf, "crit": "", "note": "n"})
    assert r.status_code == 200, r.text
    (ev,) = _events(box)  # the coded exclusion (prov empty) writes nothing
    assert ev["detail"]["decision"] == "rejected" and ev["detail"]["by"] == "crc" and ev["detail"]["calls"] == CALLS
    assert ev["detail"]["record_ref"] == {"ruleset": "GZQO", "version": "1.0.0", "job": job, "pid": "c" * 32,
                                         "crit": "GZQO-EXC-02"}  # fmt: skip
    # a criterion named: that verdict only
    crc.post(f"/studies/GZQO/not-matched/{'d' * 32}/review", data={"csrf": csrf, "crit": "GZQO-EXC-03", "note": ""})
    last = _events(box)[1:]
    assert [e["detail"]["record_ref"]["crit"] for e in last] == ["GZQO-EXC-03"] and last[0]["detail"]["calls"] == CALLS[
        1:
    ]


def test_the_api_review_writes_the_same(box: dict[str, Any]) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    _with_excluded(box)
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    users = box["users"]
    token, _sess = users.new_session(users.get("crc"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    r = api.post(f"/api/v1/studies/GZQO/not-matched/{'c' * 32}/review", json={"crit": "GZQO-EXC-02"})
    assert r.status_code == 200, r.text
    (ev,) = _events(box)
    assert ev["detail"]["decision"] == "rejected" and ev["detail"]["record_ref"]["crit"] == "GZQO-EXC-02"
