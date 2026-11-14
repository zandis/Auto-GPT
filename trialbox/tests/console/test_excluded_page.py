"""Review 2026-11-09 P-04 (D-143): "Criteria not matched" (T-506; "Excluded patients and why" before), one page per study. Every patient the latest
screening run excluded, with the criterion that excluded them, where the answer came from (the coded records, a
confirmed fact, the notes with both models agreeing) and the evidence; "This is wrong, send to review" is audited. The
investigator and the coordinator see it; a viewer and a CRO account do not."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console.test_console_app import VIEWER_PW, _done_screen, _ulid, box, login, name_pi  # noqa: F401

PW = "excluded-page-password-01"
EXCLUDED = {
    "ruleset": "GZQO",
    "version": "1.0.0",
    "run_date": "2026-10-05",
    "snapshot": "2026-10-04",
    "rows": [
        {"pid": "c" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-02", "source": "notes", "reason": "note", "quote": "history of breast cancer 2019",
             "quote_date": "2025-03-01", "resource_refs": ["DocumentReference/d1"]}]},
        {"pid": "d" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["cond-1", "cond-2"]}]},
        {"pid": "e" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-01", "source": "fact", "reason": "coded", "resource_refs": ["fact-1"]}]},
        {"pid": "f" * 32, "actions": ["contact: deny (FHIR Consent) — never listed"], "criteria": []},
    ],
}  # fmt: skip


def _with_excluded(b: dict[str, Any]) -> str:
    job = _done_screen(b["backend"], _ulid(961))
    data = json.dumps(EXCLUDED).encode()
    key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
    b["backend"].objects[key] = data
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key, recipients=[],
                    tag="phi")  # fmt: skip
    b["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    return job.job_id


def test_the_excluded_list_with_criterion_source_and_evidence(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_excluded(box)
    for name, role in (("pi", "investigator"), ("crc", "coordinator"), ("cra", "cro")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    box["users"].set_scope("cra", "cro", "GZQO", None)  # D-380 (ROLE-011): a CRO account names its studies
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "pi", PW)
    page = pi.get("/studies/GZQO/excluded").text
    assert 'data-testid="excluded"' in page and "criteria not matched for 4 patients" in page
    assert 'data-testid="ex-cccccccc"' in page and "history of breast cancer 2019" in page and "2025-03-01" in page
    assert "the notes, both models agreed" in page and "the coded records" in page and "a confirmed fact" in page
    assert "no research-contact consent" in page and "FHIR Consent" not in page  # a rule, in plain words
    assert "2 records" in page and 'data-testid="to-excluded"' in pi.get("/studies/GZQO/week").text
    only = pi.get("/studies/GZQO/excluded?src=fact").text
    assert 'data-testid="ex-eeeeeeee"' in only and 'data-testid="ex-dddddddd"' not in only
    # "this is wrong, send to review": audited, shown with who and when, first on the page
    crc, ccsrf = login(box["app"], "crc", PW)
    r = crc.post(f"/studies/GZQO/excluded/{'d' * 32}/review",
                 data={"csrf": ccsrf, "crit": "GZQO-EXC-01", "note": "the code is a suspected diagnosis"})  # fmt: skip
    assert 'data-testid="ex-sent"' in r.text and 'data-testid="ex-sent-dddddddd"' in r.text
    assert "the code is a suspected diagnosis" in r.text and 'data-testid="ex-sent-count"' in r.text
    assert r.text.index("ex-dddddddd") < r.text.index("ex-cccccccc")
    rec = [x for x in box["backend"].audit(jid) if x.event == "console.excluded_review"]
    assert len(rec) == 1 and rec[0].actor == "console:crc" and rec[0].detail["role"] == "coordinator"
    assert crc.post(f"/studies/GZQO/excluded/{'a' * 32}/review", data={"csrf": ccsrf}).status_code == 404
    # Japanese: the page's own words, the study's words as written
    ja, jcsrf = login(box["app"], "pi", PW)
    ja.post("/lang", data={"csrf": jcsrf, "lang": "ja", "back": "/"})
    jp = ja.get("/studies/GZQO/excluded").text
    assert "基準に合致しない患者" in jp and "カルテ記載（2 つのモデルが一致）" in jp and "確認に回しました" in jp
    # roles: a viewer and a CRO account never see it
    viewer, _ = login(box["app"], "viewer", VIEWER_PW)
    assert viewer.get("/studies/GZQO/excluded").status_code == 403
    cra, _ = login(box["app"], "cra", PW)
    assert cra.get("/studies/GZQO/excluded").status_code in (403, 404)


def test_the_old_path_answers_301_to_criteria_not_matched(box: dict[str, Any]) -> None:  # noqa: F811
    """T-116 (D-351): the page lives at /not-matched; /excluded answers 301 with the query kept, for one release, and
    a review form posted to the old path still lands; the page's own links and form use the new path."""
    _with_excluded(box)
    for name, role in (("pi", "investigator"), ("crc", "coordinator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "pi", PW)
    r = pi.get("/studies/GZQO/excluded?src=fact&page=1", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/studies/GZQO/not-matched?src=fact&page=1"
    assert pi.get("/studies/GZQO/excluded", follow_redirects=False).headers["location"] == "/studies/GZQO/not-matched"
    crc, ccsrf = login(box["app"], "crc", PW)
    page = crc.get("/studies/GZQO/not-matched")
    assert page.status_code == 200 and 'data-testid="excluded"' in page.text
    assert "/studies/GZQO/excluded" not in page.text  # filters and the review form point at the new path
    assert f'action="/studies/GZQO/not-matched/{"d" * 32}/review"' in page.text
    for pid, old in (("d" * 32, True), ("c" * 32, False)):
        path = f"/studies/GZQO/{'excluded' if old else 'not-matched'}/{pid}/review"
        r = crc.post(path, data={"csrf": ccsrf, "crit": "GZQO-EXC-01", "note": "x"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/studies/GZQO/not-matched?done=sent")
    # the redirect gives nothing away: a viewer who follows it still gets 403
    viewer, _ = login(box["app"], "viewer", VIEWER_PW)
    assert viewer.get("/studies/GZQO/excluded").status_code == 403


def test_no_excluded_list_says_so(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(962))
    box["users"].create("crc", "coordinator", PW)  # D-280 (OD-5): the administrator reads no patient list
    c, _ = login(box["app"], "crc", PW)
    assert 'data-testid="ex-norun"' in c.get("/studies/GZQO/excluded").text
    assert login(box["app"])[0].get("/studies/GZQO/excluded").status_code == 403


def test_the_screening_run_stores_the_excluded_list_with_the_source() -> None:
    """The orchestrator's side: every excluded row, its failing criteria and where each answer came from."""
    from orchestrator.scenarios import screen
    from tb_contracts import CandidateRow, CriterionVerdict, Evidence

    def v(cid: str, verdict: str, **ev: Any) -> CriterionVerdict:
        return CriterionVerdict(id=cid, verdict=verdict, evidence=Evidence(**ev))  # type: ignore[arg-type]

    rows = [
        CandidateRow(pid="p1", tier="excluded", criteria=[v("X-1", "pass", reason="coded"),
                     v("X-2", "fail", reason="note", quote="q", quote_date="2026-01-01")], actions=[]),
        CandidateRow(pid="p2", tier="excluded", criteria=[v("X-2", "fail", reason="coded",
                     resource_refs=["Condition/f-9"])], actions=[]),
        CandidateRow(pid="p3", tier="excluded", criteria=[v("X-2", "fail", reason="coded", resource_refs=["c-1"])],
                     actions=[]),
        CandidateRow(pid="p4", tier="review", criteria=[], actions=[]),
    ]  # fmt: skip
    # the lake's own call shape (sql, params, snapshot): the read now goes through tb_common.lakeprobe (D-652)
    lake = SimpleNamespace(query=lambda _sql, *_a: SimpleNamespace(to_pylist=lambda: [{"fid": "f-9"}]))
    ctx = SimpleNamespace(services=SimpleNamespace(lake=lake))
    run = SimpleNamespace(rs=SimpleNamespace(id="X", version="1"), run_date=date(2026, 11, 2), snapshot="2026-11-01",
                          judging={"mode": "agreement"}, rows=rows)  # fmt: skip
    doc = screen.excluded_doc(ctx, run)  # type: ignore[arg-type]
    by = {r["pid"]: r for r in doc["rows"]}
    assert set(by) == {"p1", "p2", "p3"}
    assert [c["id"] for c in by["p1"]["criteria"]] == ["X-2"] and by["p1"]["criteria"][0]["source"] == "notes"
    assert by["p2"]["criteria"][0]["source"] == "fact" and by["p3"]["criteria"][0]["source"] == "coded"
    assert doc["confirmed_facts"] == "read" and doc["coded_values"] == "read"
