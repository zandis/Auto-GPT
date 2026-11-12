"""T-310a (D-446; URS-PI-05, CR-014, FIT-007, UX-032): the weekly PI sample of "criteria not matched", the send-back
that puts a patient on the PI's weekly list again, and the site's check that opens the list where the gate is on.

Acceptance of the card: a sample of ten is recorded (with the run and the run's own snapshot); a sent-back patient
returns to the PI list; the list is held by default in PRODUCTION. Negative: an opted-out patient is never sampled
and never sent back; only the study's PI, and a sub-investigator with the "screen" tick, answer the sample."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.crypto import sha256_bytes
from tb_common.notmatched import NotMatchedError, NotMatchedStore, draw, gate_on, iso_week
from tb_common.optout import OptOutRegister
from tb_contracts import JobOutput

from tests.console import test_console_app as tca
from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    STW_PW,
    VIEWER_PW,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
    sub_investigator,
)

PW = "not-matched-sample-pw-01"
PIDS = [f"{i:02d}" * 16 for i in range(14)]  # 14 not-matched patients, 32 characters each
DOC = {
    "ruleset": "GZQO",
    "version": "1.0.0",
    "run_date": "2026-10-05",
    "snapshot": "2026-10-04",
    "rows": [
        {"pid": p, "actions": [], "criteria": [{"id": "GZQO-EXC-01", "source": "coded", "reason": "coded",
                                                "resource_refs": ["cond-1"]}]}
        for p in PIDS
    ],
}  # fmt: skip


def _with_list(b: dict[str, Any], n: int = 971) -> str:
    job = _done_screen(b["backend"], _ulid(n))
    data = json.dumps(DOC).encode()
    key = f"outputs/{job.job_id}/excluded_GZQO_v1.0.0.json"
    b["backend"].objects[key] = data
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key=key, recipients=[],
                    tag="phi")  # fmt: skip
    b["backend"].jobs[job.job_id] = job.model_copy(update={"outputs": [*(job.outputs or []), out]})
    return job.job_id


def _pi(b: dict[str, Any]) -> tuple[Any, str]:
    b["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(b, "pi")
    return login(b["app"], "pi", PW)


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """The raw audit records of one event (the console's audit reader shows metadata keys only)."""
    out = []
    for f in sorted(b["backend"].audit_dir.glob("*.jsonl")):
        out += [r for r in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if r.get("event") == name]
    return out


def _week(b: dict[str, Any]) -> str:
    return iso_week(b["app"].state.helpers.today())


# ---------------------------------------------------------------------------------------------- the sample
def test_a_sample_of_ten_is_recorded_from_the_runs_own_list(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_list(box)
    OptOutRegister().add(PIDS[3], "paper", "", "console:office", datetime.now(UTC).isoformat())
    pi, _ = _pi(box)
    page = pi.get("/studies/GZQO/not-matched/sample")
    assert page.status_code == 200 and 'data-testid="nm-sample"' in page.text
    assert "0 of 10 looked at this week" in page.text and "records of 2026-10-04" in page.text
    got = NotMatchedStore().sample("GZQO", _week(box))
    assert len(got) == 10 and len({t.pid for t in got}) == 10
    assert PIDS[3] not in {t.pid for t in got}  # never an opted-out patient
    assert {(t.job_id, t.snapshot, t.ruleset_version) for t in got} == {(jid, "2026-10-04", "1.0.0")}
    assert all(t.criteria == ("GZQO-EXC-01",) and t.answer is None for t in got)
    # the same ten for everyone, and a second view draws nothing new
    assert NotMatchedStore().sample("GZQO", _week(box)) == got
    pi.get("/studies/GZQO/not-matched/sample")
    assert NotMatchedStore().sample("GZQO", _week(box)) == got
    drawn = _events(box, "notmatched.sample")
    assert (
        len(drawn) == 1
        and drawn[0]["job_id"] == jid
        and drawn[0]["detail"]["n"] == 10
        and drawn[0]["detail"]["snapshot"] == "2026-10-04"
    )
    # the list page links to the sample for the PI
    assert 'data-testid="to-nm-sample"' in pi.get("/studies/GZQO/not-matched").text


def test_an_answer_is_recorded_once_with_a_counter(box: dict[str, Any]) -> None:  # noqa: F811
    _with_list(box)
    pi, csrf = _pi(box)
    pi.get("/studies/GZQO/not-matched/sample")
    first = NotMatchedStore().sample("GZQO", _week(box))[0].pid
    r = pi.post(f"/studies/GZQO/not-matched/sample/{first}", data={"csrf": csrf, "answer": "agree", "note": "ok"})
    assert r.status_code == 200 and 'data-testid="nm-done"' in r.text and "1 of 10 looked at this week" in r.text
    assert f'data-testid="nm-answer-{first[:8]}"' in r.text
    again = pi.post(f"/studies/GZQO/not-matched/sample/{first}", data={"csrf": csrf, "answer": "send_back"},
                    follow_redirects=False)  # fmt: skip
    assert again.status_code == 409
    assert pi.post(f"/studies/GZQO/not-matched/sample/{PIDS[0]}", data={"csrf": csrf, "answer": "maybe"},
                   follow_redirects=False).status_code == 400  # fmt: skip
    t = next(x for x in NotMatchedStore().sample("GZQO", _week(box)) if x.pid == first)
    assert (t.answer, t.note, t.answered_by) == ("agree", "ok", "console:pi")
    assert NotMatchedStore().counts("GZQO") == {"weeks": 1, "sampled": 10, "answered": 1, "sent_back": 0}


def test_a_sent_back_patient_returns_to_the_pi_list(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_list(box)
    pi, csrf = _pi(box)
    pi.get("/studies/GZQO/not-matched/sample")
    back = NotMatchedStore().sample("GZQO", _week(box))[0].pid
    assert f'data-testid="sent-back-{back[:8]}"' not in pi.get("/studies/GZQO/week?list=all").text
    r = pi.post(f"/studies/GZQO/not-matched/sample/{back}", data={"csrf": csrf, "answer": "send_back"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith(f"done=send_back#s-{back[:8]}")
    week = pi.get("/studies/GZQO/week?list=all").text
    assert f'data-testid="sent-back-{back[:8]}"' in week and "sent back from criteria not matched" in week
    # on the list it is marked like any other patient
    m = pi.post(f"/studies/GZQO/patients/{back}/mark", data={"csrf": csrf, "mark": "need_info"}, follow_redirects=False)
    assert m.status_code == 303, m.text[-300:]
    audit = _events(box, "console.notmatched_answer")
    assert len(audit) == 1 and audit[0]["job_id"] == jid
    assert audit[0]["detail"]["answer"] == "send_back" and audit[0]["detail"]["pid"] == back
    # "send to review" from the list brings the patient back too (CR-014)
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    crc, ccsrf = login(box["app"], "crc", PW)
    other = next(p for p in PIDS if p not in {t.pid for t in NotMatchedStore().sample("GZQO", _week(box))})
    crc.post(f"/studies/GZQO/not-matched/{other}/review", data={"csrf": ccsrf, "crit": "GZQO-EXC-01", "note": "x"})
    assert f'data-testid="sent-back-{other[:8]}"' in pi.get("/studies/GZQO/week?list=all").text


def test_an_opted_out_patient_is_never_sent_back(box: dict[str, Any]) -> None:  # noqa: F811
    _with_list(box)
    pi, csrf = _pi(box)
    pi.get("/studies/GZQO/not-matched/sample")
    gone = NotMatchedStore().sample("GZQO", _week(box))[1].pid
    OptOutRegister().add(gone, "paper", "", "console:office", datetime.now(UTC).isoformat())
    page = pi.get("/studies/GZQO/not-matched/sample").text
    assert f'data-testid="nm-{gone[:8]}"' not in page and 'data-testid="nm-removed"' in page
    r = pi.post(f"/studies/GZQO/not-matched/sample/{gone}", data={"csrf": csrf, "answer": "send_back"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 404
    assert gone not in box["app"].state.helpers.store.excluded_reviews("GZQO")
    assert f"sent-back-{gone[:8]}" not in pi.get("/studies/GZQO/week?list=all").text


def test_who_answers_the_sample(box: dict[str, Any]) -> None:  # noqa: F811
    _with_list(box)
    _pi(box)
    for name, role in (("crc", "coordinator"), ("subscreen", "investigator"), ("subnone", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    sub_investigator(box, "subscreen", ("screen",))
    sub_investigator(box, "subnone", ("refer",))
    assert login(box["app"], "subscreen", PW)[0].get("/studies/GZQO/not-matched/sample").status_code == 200
    for name in ("crc", "subnone"):
        assert login(box["app"], name, PW)[0].get("/studies/GZQO/not-matched/sample").status_code == 403
    assert login(box["app"], "viewer", VIEWER_PW)[0].get("/studies/GZQO/not-matched/sample").status_code == 403
    assert login(box["app"])[0].get("/studies/GZQO/not-matched/sample").status_code == 403  # the administrator


def test_the_api_twins_check_the_session_first(box: dict[str, Any]) -> None:  # noqa: F811
    from fastapi.testclient import TestClient

    _with_list(box)
    _pi(box)
    token, _ = box["users"].new_session(box["users"].get("pi"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    got = api.get("/api/v1/studies/GZQO/not-matched/sample").json()
    assert got["shown"] and got["size"] == 10 and got["snapshot"] == "2026-10-04"
    pid = got["patients"][0]["pid"]
    r = api.post(f"/api/v1/studies/GZQO/not-matched/sample/{pid}", json={"answer": "send_back", "note": "check"})
    assert r.status_code == 200 and r.json()["on_pi_list"] is True
    assert api.post(f"/api/v1/studies/GZQO/not-matched/sample/{pid}", json={"answer": "agree"}).status_code == 409
    anon = TestClient(box["app"])
    for path in (f"/api/v1/studies/GZQO/not-matched/sample/{pid}", "/api/v1/studies/GZQO/not-matched/check",
                 f"/api/v1/studies/GZQO/not-matched/{pid}/review"):  # fmt: skip
        assert anon.post(path, content=b"not json", headers={"content-type": "application/json"}).status_code == 401
    other = next(p for p in PIDS if p != pid)
    r = api.post(f"/api/v1/studies/GZQO/not-matched/{other}/review", json={"crit": "GZQO-EXC-01"})
    assert r.status_code == 200 and r.json()["sent_back"] is True


# ---------------------------------------------------------------------------------------------- the site's check
def test_the_list_waits_for_the_sites_check_where_the_gate_is_on(box: dict[str, Any]) -> None:  # noqa: F811
    _with_list(box)
    pi, csrf = _pi(box)
    box["app"].state.helpers.not_matched.gated = True  # as in VALIDATION and PRODUCTION
    held = pi.get("/studies/GZQO/not-matched").text
    assert 'data-testid="nm-held"' in held and 'data-testid="excluded"' not in held
    assert 'data-testid="nm-held"' in pi.get("/studies/GZQO/not-matched/sample").text
    assert NotMatchedStore().sample("GZQO", _week(box)) == []  # no sample is drawn while held
    r = pi.post(f"/studies/GZQO/not-matched/{PIDS[0]}/review", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 409
    # the steward records the check; only the steward
    assert pi.post("/studies/GZQO/not-matched/check", data={"csrf": csrf, "passed": "yes", "record": "DR-1"},
                   follow_redirects=False).status_code == 403  # fmt: skip
    stw, scsrf = login(box["app"], "stw-setup", STW_PW)
    assert stw.post("/studies/GZQO/not-matched/check", data={"csrf": scsrf, "passed": "yes"},
                    follow_redirects=False).status_code == 400  # fmt: skip  # passed needs the record id
    r = stw.post("/studies/GZQO/not-matched/check", data={"csrf": scsrf, "passed": "yes", "record": "DRYRUN-7"})
    assert 'data-testid="nm-check-done"' in r.text and "record DRYRUN-7" in r.text
    shown = pi.get("/studies/GZQO/not-matched").text
    assert 'data-testid="excluded"' in shown and "Site check passed: record DRYRUN-7" in shown
    assert len(NotMatchedStore().sample("GZQO", _week(box))) == 0
    pi.get("/studies/GZQO/not-matched/sample")
    assert len(NotMatchedStore().sample("GZQO", _week(box))) == 10
    # taking it back needs a note and holds the list again
    assert stw.post("/studies/GZQO/not-matched/check", data={"csrf": scsrf, "passed": "no"},
                    follow_redirects=False).status_code == 400  # fmt: skip
    stw.post("/studies/GZQO/not-matched/check", data={"csrf": scsrf, "passed": "no", "note": "threshold missed"})
    assert 'data-testid="nm-held"' in pi.get("/studies/GZQO/not-matched").text
    assert [e["detail"]["passed"] for e in _events(box, "console.notmatched_check")] == [True, False]
    token, _ = box["users"].new_session(box["users"].get("stw-setup"), via="api")
    from fastapi.testclient import TestClient

    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    got = api.post("/api/v1/studies/GZQO/not-matched/check", json={"passed": True, "record": "DRYRUN-8"}).json()
    assert got["shown"] and got["check"]["record"] == "DRYRUN-8"
    assert api.get("/api/v1/studies/GZQO/not-matched/check").json()["gated"] is True


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(tca.PILOT_ENV, "TB_ENV", "PRODUCTION")


def test_the_list_is_held_by_default_in_production(production: None, box: dict[str, Any]) -> None:  # noqa: F811
    nm = box["app"].state.helpers.not_matched
    assert nm.gated and not nm.shown("GZQO")


def test_the_gate_setting() -> None:
    assert gate_on({"TB_ENV": "PRODUCTION"}) and gate_on({}) and gate_on({"TB_ENV": "VALIDATION"})
    assert not gate_on({"TB_ENV": "DEV"}) and not gate_on({"TB_ENV": "TEST"})
    assert gate_on({"TB_ENV": "DEV", "TB_NOT_MATCHED_GATE": "on"})
    assert not gate_on({"TB_ENV": "STAGING", "TB_NOT_MATCHED_GATE": "off"})
    for bad in ({"TB_ENV": "PRODUCTION", "TB_NOT_MATCHED_GATE": "off"}, {"TB_NOT_MATCHED_GATE": "maybe"}):
        with pytest.raises(ValueError):
            gate_on(bad)


def test_the_draw_is_fair_and_repeatable() -> None:
    rows = [{"pid": p} for p in PIDS]
    a = draw(rows, "GZQO|2026-W46|J1")
    assert len(a) == 10 and a == draw(list(reversed(rows)), "GZQO|2026-W46|J1")
    assert {r["pid"] for r in a} != {r["pid"] for r in draw(rows, "GZQO|2026-W47|J1")}
    assert PIDS[0] not in {r["pid"] for r in draw(rows, "s", skip=[PIDS[0]], n=14)}
    assert len(draw([{"pid": "short"}, {"pid": PIDS[0]}, {"pid": PIDS[0]}], "s")) == 1


def test_the_store_refuses_what_it_cannot_record() -> None:
    s = NotMatchedStore()
    with pytest.raises(NotMatchedError, match="nm.err.not_sampled"):
        s.answer("GZQO", "2026-W01", PIDS[0], "agree", "", "console:pi", "2026-01-02T00:00:00+00:00")
    with pytest.raises(NotMatchedError, match="nm.err.answer"):
        s.answer("GZQO", "2026-W01", PIDS[0], "yes", "", "console:pi", "2026-01-02T00:00:00+00:00")
    with pytest.raises(NotMatchedError, match="nm.err.study"):
        s.record_check("bad study", passed=True, record="x", note="", by="b", at="2026-01-02T00:00:00+00:00")
    with pytest.raises(NotMatchedError):
        s.record_sample("GZQO", "2026-W01", [{"pid": PIDS[0]}], job_id="J", snapshot="", version="", by="b",
                        at="2026-01-02T00:00:00")  # fmt: skip  # a time without an offset
    assert s.shown("GZQO", gated=False) and not s.shown("GZQO", gated=True)


# ---------------------------------------------------------------------------------------------- the weekly job
class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


def _orch(snapshot: date | None = date(2026, 10, 4)) -> Any:
    from tb_contracts import Job

    data = json.dumps(DOC).encode()
    out = JobOutput(filename="excluded_GZQO_v1.0.0.json", sha256=sha256_bytes(data), minio_key="k/excluded.json",
                    recipients=[], tag="phi")  # fmt: skip
    now = datetime(2026, 10, 5, tzinfo=UTC)
    job = Job(job_id=_ulid(975), type="SCREEN", state="done", ruleset="GZQO", requested_by="scheduler",
              received_at=now, updated_at=now, outputs=[out], snapshot_date=snapshot)  # fmt: skip
    older = job.model_copy(update={"job_id": _ulid(974), "outputs": []})

    def find(**kw: Any) -> list[Any]:
        assert kw.get("type_") == "SCREEN" and kw.get("state") == "done"
        return [job, older]

    # no lake here: the job reads the run's stored list and the run's own snapshot, never the lake's current one
    return SimpleNamespace(db=SimpleNamespace(find=find), store=SimpleNamespace(get=lambda key: data),
                           audit=_Audit(), cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei")), job=job)  # fmt: skip


def test_the_weekly_job_draws_ten_per_study_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import notmatched_sample

    monkeypatch.setattr(notmatched_sample, "opted_out", lambda: frozenset({PIDS[5]}))
    orch = _orch()
    day = date(2026, 11, 9)
    assert notmatched_sample.weekly(orch, today=day, env={"TB_ENV": "TEST"}) == {"GZQO": 10}
    got = NotMatchedStore().sample("GZQO", "2026-W46")
    assert len(got) == 10 and PIDS[5] not in {t.pid for t in got}
    assert {(t.job_id, t.snapshot, t.drawn_by) for t in got} == {(orch.job.job_id, "2026-10-04", "scheduler")}
    assert orch.audit.events[0][0] == "notmatched.sample" and orch.audit.events[0][1]["detail"]["n"] == 10
    assert notmatched_sample.weekly(orch, today=day, env={"TB_ENV": "TEST"}) == {"GZQO": 0}  # the week has one


def test_the_weekly_job_holds_a_study_without_a_passed_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import notmatched_sample

    monkeypatch.setattr(notmatched_sample, "opted_out", frozenset)
    orch = _orch(snapshot=None)
    assert notmatched_sample.weekly(orch, today=date(2026, 11, 9), env={"TB_ENV": "PRODUCTION"}) == {}
    assert orch.audit.events == [("notmatched.held", {"ruleset": "GZQO", "detail": {"week": "2026-W46"}})]
    NotMatchedStore().record_check("GZQO", passed=True, record="DRYRUN-1", note="", by="console:stw",
                                   at="2026-11-08T00:00:00+00:00")  # fmt: skip
    assert notmatched_sample.weekly(orch, today=date(2026, 11, 9), env={"TB_ENV": "PRODUCTION"}) == {"GZQO": 10}
    assert {t.snapshot for t in NotMatchedStore().sample("GZQO", "2026-W46")} == {"2026-10-04"}  # the list's own


def test_the_weekly_job_draws_nothing_when_the_register_does_not_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import notmatched_sample

    def down() -> frozenset[str]:
        raise OSError("register down")

    monkeypatch.setattr(notmatched_sample, "opted_out", down)
    assert notmatched_sample.weekly(_orch(), today=date(2026, 11, 9), env={"TB_ENV": "TEST"}) == {}
    assert NotMatchedStore().sample("GZQO", "2026-W46") == []


def test_the_timer_schedules_the_weekly_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import notmatched_sample, scheduler

    added: dict[str, Any] = {}

    class _Sched:
        def __init__(self, **kw: Any) -> None:
            pass

        def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
            added[id] = (fn, kw)

        def start(self) -> None:
            pass

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", _Sched)
    monkeypatch.setattr("tb_common.config.schedule_on_demand", lambda settings, env: False)
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(settings=SimpleNamespace(schedule=None), env=SimpleNamespace(tz="Asia/Tokyo", extra={}))
    )
    scheduler.start(orch)
    fn, kw = added["not_matched_sample"]
    assert fn is notmatched_sample.weekly and kw == {"hour": 6, "minute": 0, "day_of_week": "mon"}
