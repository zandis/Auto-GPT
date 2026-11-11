"""T-303 (D-436): the monitor's SDV pages on the REAL orchestrator routers (data core, lifecycle, EDC) on the test's
own database; synthetic data only (``tests.edc_kit``).

* the bug J-MON-03 found: the data core nests the subject under ``subject``; the monitor page read the whole reply
  and refused every enrolled subject. Here the reply comes from ``orchestrator.lifecycle_api`` itself;
* FIT-002's monitor tests: the monitor sees an enrolled subject's cited items and their trail; a candidate, a screen
  failure and another study are refused; an opted-out patient is never shown;
* "limited to the cited record items": per decided CRF value the citation the EDC draft holds, nothing else (no
  open draft, no pseudonym, no chart number);
* the visit record (date, CRA, subjects verified, findings) on the page and ``/api/v1``;
* every read audited with the visit; a monitor's request for a chart number is 403 and audited."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from console.backend import problem_of
from console.sitestore import StudySettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.candidates import CandidateRegistry
from orchestrator.datacore_api import DataService
from orchestrator.datacore_api import router as datacore_router
from orchestrator.db import JobDB
from orchestrator.edc_api import router as edc_router
from orchestrator.lifecycle_api import router as life_router
from tb_common.audit import AuditLog

from tests import edc_kit as k
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name

PW = "monitor-sdv-password-0001"
NO = "GZQO-0001"  # enrolled, with EDC values
PIDS = {"cand": "p-0002-cand", "fail": "p-0003-fail", "gone": "p-0004-gone"}
VISIT = "MV-12"


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _csrf(page: str) -> str:
    import re

    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


@pytest.fixture
def sb(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    """The console on the orchestrator's real data-core, lifecycle and EDC routers (one data core)."""
    svc, _sim, _token = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": NO}])
    audit = AuditLog(tmp_path / "orch-audit")
    reg = CandidateRegistry(JobDB(), audit, tmp_path)
    dsvc = DataService(svc.dc, audit, lambda: k.STAMP, svc.client, None, reg)
    api = FastAPI()
    api.include_router(edc_router(lambda: svc))
    api.include_router(datacore_router(lambda: dsvc))
    api.include_router(life_router(lambda: dsvc))
    oc = TestClient(api)

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        if path == "/redcap/connections":
            return {"connections": [{"token_ref": "edc"}]}
        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = oc.request(method, path, json=body, **kw) if body is not None else oc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    h = box["app"].state.helpers
    for name, role in (("crc", "coordinator"), ("drsato", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    box["users"].create("mon1", "cro", PW, "mon1@cro.test")
    box["users"].set_scope("mon1", affiliation="cro", studies="GZQO")
    name_pi(box, "drsato")
    h.team.add_entry("GZQO", username="crc", name="Chen Mei", role="crc", tasks=(), start="2026-01-01", end=None,
                     training_day="2026-01-01", training_ref="GCP-1", by="admin",
                     at="2026-01-01T00:00:00+00:00")  # fmt: skip
    nos = {k.PID: h.store.assign_screening_no("GZQO", k.PID, StudySettings(), "2026-11-01T00:00:00+00:00")}
    assert nos[k.PID] == NO
    for pid in PIDS.values():
        nos[pid] = h.store.assign_screening_no("GZQO", pid, StudySettings(), "2026-11-01T00:00:00+00:00")
    r = oc.post("/studies/GZQO/subjects/refresh", json={"screening": {n: p for p, n in nos.items()}, "by": "crc"})
    assert r.status_code == 200, r.text

    def step(no: str, *to: str) -> None:
        for s in to:
            body = {"to": s, "by": "crc", "on_day": "2026-11-02"}
            if s == "screen_fail":
                body["reason"] = "declined"
            r = oc.post(f"/studies/GZQO/subjects/{no}/step", json=body)
            assert r.status_code == 200, (no, s, r.text)

    step(NO, "approached", "consented", "enrolled")
    step(nos[PIDS["fail"]], "screen_fail")
    step(nos[PIDS["gone"]], "approached", "consented", "enrolled")
    h.optout.add(PIDS["gone"], "paper", "", "stw", "2026-11-03T00:00:00+00:00")
    # EDC: drafted from the synthetic record; weight confirmed, urate changed with a reason, signed; the rest open
    k.ready(svc)
    svc.build("GZQO", NO, k.PID, "", k.VISIT_DATE, "crc")
    d = {x["item"]: x for x in svc.store.drafts("GZQO", NO)}
    svc.decide("GZQO", d["weight"]["id"], "confirm", by="crc")
    svc.decide("GZQO", d["urate"]["id"], "edit", value="8.5", reason="the lab sheet says 8.5", by="crc",
               citation={"text": "paper lab sheet of 2026-10-20", "day": "2026-10-20"})  # fmt: skip
    svc.sign("GZQO", NO, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I compared each value with its source", lang="en", seen=k.seen(svc, NO))  # fmt: skip
    yield {**box, "svc": svc, "oc": oc, "nos": nos}
    svc.dc.close()


def _grant(b: dict[str, Any]) -> None:
    pi, csrf = login(b["app"], "drsato", PW)
    r = pi.post("/studies/GZQO/team", data={"csrf": csrf, "username": "mon1", "role": "monitor", "start": "2026-01-01",
                                           "end": "2099-12-31", "training_ref": VISIT}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]


def test_the_real_data_core_reply_opens_an_enrolled_subject(sb: dict[str, Any]) -> None:
    """J-MON-03: the real reply nests the subject; the monitor page opens the enrolled one (it refused it before)."""
    reply = sb["oc"].get(f"/studies/GZQO/subjects/{NO}").json()
    assert "state" not in reply and reply["subject"]["state"] == "enrolled"  # the shape the console must unwrap
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get(f"/studies/GZQO/monitor/{NO}")
    assert page.status_code == 200, page.text[-400:]
    assert 'data-state="enrolled"' in page.text and VISIT in page.text


def test_the_sheet_shows_the_cited_items_and_nothing_else(sb: dict[str, Any]) -> None:
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get(f"/studies/GZQO/monitor/{NO}").text
    assert 'data-testid="sdv-item-weight"' in page and 'data-testid="sdv-item-urate"' in page
    cite = page[page.index('data-testid="sdv-cite-weight"') :][:600]
    assert "o1" in cite and "2026-11-01" in cite  # the source row the value was taken from
    assert "8.5" in page and "the lab sheet says 8.5" in page and "Chen Mei" in page  # its change and signature
    assert "paper lab sheet of 2026-10-20" in page  # a changed value cites its own source, and the one it replaced
    for open_item in ("brthdat", "sex", "tophus", "cm_allo"):  # drafts nobody decided: not values, not shown
        assert f'data-testid="sdv-item-{open_item}"' not in page, open_item
    assert k.PID not in page  # never the pseudonym
    api = TestClient(sb["app"])
    tok = api.post("/api/v1/session", json={"username": "mon1", "password": PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    body = api.get(f"/api/v1/studies/GZQO/monitor/{NO}").json()
    assert body["visit"] == VISIT and body["subject"]["state"] == "enrolled" and body["subject"]["enrolled"]
    assert {i["item"] for i in body["items"]} == {"weight", "urate"}
    assert all(i["citation"] for i in body["items"]) and k.PID not in json.dumps(body)
    assert {x["item"] for x in body["decisions"]} == {"weight", "urate"}
    assert body["signatures"] and set(body["signatures"][0]["items"]) == {"weight", "urate"}
    views = [e for e in _events(sb, "console.monitor_view") if e["detail"]["record"] == NO]
    assert len(views) == 2 and {v["detail"]["visit"] for v in views} == {VISIT} and views[0]["detail"]["items"] == 2


def test_refusals_candidate_screen_fail_opted_out_other_study_and_chart_numbers(sb: dict[str, Any]) -> None:
    mon, csrf = login(sb["app"], "mon1", PW)
    assert mon.get(f"/studies/GZQO/monitor/{NO}").status_code == 403  # no grant yet
    assert mon.get("/studies/GZQO/monitor").status_code == 403
    _grant(sb)
    nos = sb["nos"]
    assert mon.get(f"/studies/GZQO/monitor/{nos[PIDS['cand']]}").status_code == 403
    assert mon.get(f"/studies/GZQO/monitor/{nos[PIDS['fail']]}").status_code == 403
    assert mon.get(f"/studies/GZQO/monitor/{nos[PIDS['gone']]}").status_code == 404  # opted out: as if not there
    assert mon.get(f"/studies/OTHER/monitor/{NO}").status_code == 404
    why = [e["detail"].get("why") for e in _events(sb, "console.denied")]
    assert why.count("not_enrolled") == 2 and why.count("opted_out") == 1
    # the list: the enrolled subject only (the opted-out enrolled one is not listed)
    page = mon.get("/studies/GZQO/monitor").text
    assert f'data-testid="sdv-subject-{NO}"' in page
    for pid in PIDS.values():
        assert f'data-testid="sdv-subject-{nos[pid]}"' not in page
    # no chart number, no twin, no other patient page, no EDC page: refused and audited
    before = len(_events(sb, "console.denied"))
    for path in (f"/studies/GZQO/candidates/{k.PID}/reveal", f"/studies/GZQO/patients/{k.PID}/reveal"):
        r = mon.post(path, data={"csrf": csrf, "reason": "sdv", "purpose": "other"})
        assert r.status_code == 403, path
    for path in (f"/studies/GZQO/edc/trail/{NO}", f"/studies/GZQO/subjects/{NO}", f"/studies/GZQO/candidates/{k.PID}"):
        assert mon.get(path).status_code == 403, path
    api = TestClient(sb["app"])
    tok = api.post("/api/v1/session", json={"username": "mon1", "password": PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    assert api.get(f"/api/v1/studies/GZQO/patients/{k.PID}/twin").status_code == 403  # the patient twin stays shut
    assert api.post(f"/api/v1/studies/GZQO/patients/{k.PID}/reveal", json={"reason": "other"}).status_code == 403
    assert len(_events(sb, "console.denied")) >= before + 7
    # the grant reads; nobody else does through it
    crc, _ = login(sb["app"], "crc", PW)
    assert crc.get(f"/studies/GZQO/monitor/{NO}").status_code == 403
    assert crc.get("/studies/GZQO/monitor").status_code == 403


def test_the_visit_record_on_the_page_and_the_api(sb: dict[str, Any]) -> None:
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get("/studies/GZQO/monitor").text
    assert 'data-testid="sdv-visit-form"' in page
    form = {"csrf": _csrf(page), "visit_day": "2026-11-09", "subjects": [NO], "findings": "weight matches the chart"}
    r = mon.post("/studies/GZQO/monitor/visits", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studies/GZQO/monitor?done=1"
    assert mon.post("/studies/GZQO/monitor/visits", data={**form, "visit_day": ""}).status_code == 400
    stray = {**form, "subjects": [NO, sb["nos"][PIDS["cand"]]]}  # a candidate is not a subject a monitor verifies
    assert mon.post("/studies/GZQO/monitor/visits", data=stray).status_code == 403
    page = mon.get("/studies/GZQO/monitor?done=1").text
    assert 'data-testid="sdv-visit-saved"' in page and "weight matches the chart" in page
    # /api/v1: the session and the right before the body
    anon = TestClient(sb["app"])
    assert anon.post("/api/v1/studies/GZQO/monitor/visits", content=b"").status_code == 401
    api = TestClient(sb["app"])
    tok = api.post("/api/v1/session", json={"username": "mon1", "password": PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    r = api.post("/api/v1/studies/GZQO/monitor/visits", json={"visit_day": "2026-11-10", "subjects": [NO],
                                                              "findings": ""})  # fmt: skip
    assert r.status_code == 200 and r.json()["visit"]["cra"] == "mon1" and r.json()["visit"]["visit"] == VISIT
    assert api.post("/api/v1/studies/GZQO/monitor/visits", json=[1]).status_code == 400
    got = api.get("/api/v1/studies/GZQO/monitor").json()
    assert [v["visit_day"] for v in got["visits"]] == ["2026-11-10", "2026-11-09"]
    assert [s["record"] for s in got["subjects"]] == [NO] and "pid" not in got["subjects"][0]
    saved = _events(sb, "console.monitor_visit")
    assert len(saved) == 2 and saved[0]["detail"]["subjects"] == [NO]
    # the PI who gave the grant reads the visit records, not the subject list; a coordinator cannot write one
    pi, _ = login(sb["app"], "drsato", PW)
    page = pi.get("/studies/GZQO/monitor").text
    assert "weight matches the chart" in page and 'data-testid="sdv-subjects"' not in page
    assert 'data-testid="sdv-visit-form"' not in page
    tok = api.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    r = api.post("/api/v1/studies/GZQO/monitor/visits", json={"visit_day": "2026-11-10", "subjects": [NO]},
                 headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert r.status_code == 403


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_the_sheet_in_the_other_languages(sb: dict[str, Any], lang: str) -> None:
    from tb_common.wording import check_page

    _grant(sb)
    mon, csrf = login(sb["app"], "mon1", PW)
    mon.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    for path in (f"/studies/GZQO/monitor/{NO}", "/studies/GZQO/monitor"):
        page = mon.get(path)
        assert page.status_code == 200 and not check_page(page.text), path
    assert ("原資料の参照" if lang == "ja" else "原始資料出處") in mon.get(f"/studies/GZQO/monitor/{NO}").text
