# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/data-ops`` and ``/api/v1/data/*`` (T-112b, D-443; TB-ASSESS-01 T-112 acceptance 1, 4 and the API contract):
the steward sees the feed red when a night was held and rejects it with a reason (audited, the trail on the batch
page); accept runs the promotion and stays held when it fails; without a promoter accept is refused; the
administrator reads and gets 403 on a decision; every other role gets 403; the API answers the same functions and
checks the session before the body; the ingest history is filtered and paged by the store; the page in three
languages and the link to the conflicts page."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from console import i18n_dataops
from datacore.dataops import HELD, PUBLISHED, REJECTED, DataOps
from tb_common.audit import AuditLog
from tb_common.wording import check

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    box,
    login,
)
from tests.console.test_role_pages import PW, _user
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the fixture is used by name

AT = "2026-11-11T02:00:00+09:00"


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    """NEW-ARCH-3 (D-761): the page reads and decides over the orchestrator's routes (no adapter: cannot publish)."""
    from tests.console.dataops_orch import attach

    box["dataops"] = attach(box["backend"], box["audit"])


def _night(b: dict[str, Any], snap: str, *, held: bool = True, passed: bool = False, source: str = "csv") -> int:
    ops = DataOps()
    try:
        event = "ingest.done" if passed else "ingest.held" if held else "ingest.failed"
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), event, source=source, snapshot=snap,
                                    passed=passed, held=held, by="adapter", at=AT, actor="adapter",
                                    detail={"incomplete": ["lab: missing"], "gate": {"outcome": "held"}})  # fmt: skip
        return batch.id
    finally:
        ops.close()


def _state(bid: int) -> str:
    ops = DataOps()
    try:
        got = ops.batch(bid)
        assert got is not None
        return got.state
    finally:
        ops.close()


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((Path(b["dir"]) / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _bearer(b: dict[str, Any], name: str, role: str) -> dict[str, str]:
    from fastapi.testclient import TestClient

    b["users"].create(name, role, PW, f"{name}@hospa.test")
    tok = TestClient(b["app"]).post("/api/v1/session", json={"username": name, "password": PW}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_the_steward_sees_the_feed_red_and_rejects_the_held_night(box: dict[str, Any]) -> None:
    _night(box, "2026-11-09", held=False, passed=True)
    bid = _night(box, "2026-11-10")
    c = _user(box, "stw", "steward")
    r = c.get("/data-ops")
    assert r.status_code == 200 and "Data operations" in r.text
    assert 'data-source="csv" data-light="red"' in r.text  # the newest night of the feed is held
    assert f'data-testid="held" data-batch="{bid}"' in r.text and "lab: missing" in r.text
    assert 'href="/data/conflicts"' in r.text and 'href="/data-ops"' in r.text  # the two pages link; the menu entry
    assert 'data-testid="dataops-accept-off"' in r.text and 'value="accept"' not in r.text  # no promoter yet
    tok = _csrf(r.text)
    bad = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": "reject", "reason": " "},
                 follow_redirects=False)  # fmt: skip
    assert bad.headers["location"].endswith("err=reason") and _state(bid) == HELD
    off = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": "accept", "reason": "ok"},
                 follow_redirects=False)  # fmt: skip
    assert off.headers["location"].endswith("err=promote") and _state(bid) == HELD
    assert c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": "x", "decision": "reject", "reason": "r"},
                  follow_redirects=False).status_code == 400  # fmt: skip
    ok = c.post(f"/data-ops/batches/{bid}/decide",
                data={"csrf": tok, "decision": "reject", "reason": "lab file truncated"}, follow_redirects=False)  # fmt: skip
    assert ok.status_code == 303 and ok.headers["location"].endswith("done=reject") and _state(bid) == REJECTED
    ev = _events(box, "dataops.decide")
    assert len(ev) == 1 and ev[0]["actor"] == "console:stw" and ev[0]["detail"]["reason"] == "lab file truncated"
    again = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": "reject", "reason": "r"},
                   follow_redirects=False)  # fmt: skip
    assert again.headers["location"].endswith("err=state")
    page = c.get("/data-ops").text
    assert 'data-testid="dataops-held-none"' in page and 'data-source="csv" data-light="amber"' in page
    trail = c.get(f"/data-ops/batches/{bid}").text
    assert 'data-new="REJECTED"' in trail and "lab file truncated" in trail and "dataops.decide" in trail
    assert c.get("/data-ops/batches/99999").status_code == 404
    assert c.post("/data-ops/batches/99999/decide", data={"csrf": tok, "decision": "reject", "reason": "r"},
                  follow_redirects=False).status_code == 404  # fmt: skip


class _Adapter:
    """The adapter's publish as the orchestrator's routes call it (NEW-ARCH-3: the publish runs there)."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def publish(self, body: dict[str, Any]) -> dict[str, Any]:
        if body["snapshot"] == "2026-11-08":
            raise RuntimeError("lake refused")
        self.seen.append(body["snapshot"])
        return {"run": "0123456789abcdef", "state": "done"}

    def publish_state(self, rid: str) -> dict[str, Any]:
        return {"run": rid, "state": "done"}


def test_accept_promotes_and_a_failed_promotion_keeps_the_night_held(box: dict[str, Any]) -> None:
    adapter = _Adapter()
    box["dataops"]["adapter"] = adapter
    bad, good = _night(box, "2026-11-08"), _night(box, "2026-11-10")
    c = _user(box, "stw3", "steward")
    page = c.get("/data-ops").text
    tok = _csrf(page)
    assert 'value="accept"' in page
    r = c.post(f"/data-ops/batches/{bad}/decide", data={"csrf": tok, "decision": "accept", "reason": "checked"},
               follow_redirects=False)  # fmt: skip
    # D-489 (review of T-723, HIGH-2): the publish raised and its end is not known, so the accept stays recorded
    # (before: "err=promote" and nothing written). The night is still held
    assert r.headers["location"].endswith("err=publishing") and _state(bad) == HELD
    assert [e["detail"]["phase"] for e in _events(box, "dataops.decide")] == ["started", "ended"]
    r = c.post(f"/data-ops/batches/{good}/decide", data={"csrf": tok, "decision": "accept", "reason": "checked"},
               follow_redirects=False)  # fmt: skip
    assert (
        r.headers["location"].endswith("done=accept") and _state(good) == PUBLISHED and adapter.seen == ["2026-11-10"]
    )
    r = c.post(f"/data-ops/batches/{bad}/decide", data={"csrf": tok, "decision": "maybe", "reason": "r"},
               follow_redirects=False)  # fmt: skip
    assert r.headers["location"].endswith("err=decision") and _state(bad) == HELD


def test_the_accept_says_it_also_accepts_tonights_rates(box: dict[str, Any]) -> None:
    """TOL-HOLDS (SAFE-1 A5): an accept records the night's problem rates as the site's baseline; the form says so."""
    box["dataops"]["adapter"] = _Adapter()
    _night(box, "2026-11-08")
    page = _user(box, "stwbase", "steward").get("/data-ops").text
    assert 'value="accept"' in page and 'data-testid="accept-baseline"' in page


def test_the_administrator_reads_and_may_not_decide(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10")
    c, csrf = login(box["app"], "admin", ADMIN_PW)
    r = c.get("/data-ops")
    assert r.status_code == 200 and f'data-batch="{bid}"' in r.text and "decide-" not in r.text
    assert "Only the data steward" in r.text
    d = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": csrf, "decision": "reject", "reason": "r"})
    assert d.status_code == 403 and _state(bid) == HELD
    assert len(_events(box, "console.denied")) == 1


@pytest.mark.parametrize("role", ["coordinator", "investigator", "viewer", "cro", "privacy"])
def test_every_other_role_gets_403(box: dict[str, Any], role: str) -> None:
    bid = _night(box, "2026-11-10")
    c = _user(box, f"u_{role}", role)
    assert c.get("/data-ops").status_code == 403
    assert c.get(f"/data-ops/batches/{bid}").status_code == 403
    assert c.post(f"/data-ops/batches/{bid}/decide", data={"decision": "reject", "reason": "r"}).status_code == 403
    assert _state(bid) == HELD and len(_events(box, "console.denied")) == 3


def test_the_api_answers_the_same_functions(box: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient

    api = TestClient(box["app"])
    # the session before the body: an empty body without a session is 401, never 422
    assert api.post("/api/v1/data/batches/1/decide").status_code == 401
    assert api.post("/api/v1/data/batches/1/decide", content=b"").status_code == 401
    assert api.get("/api/v1/data/batches").status_code == 401
    bid = _night(box, "2026-11-10")
    old = _night(box, "2026-11-09", held=False, passed=True)
    stw = _bearer(box, "stwapi", "steward")
    src = api.get("/api/v1/data/sources", headers=stw).json()
    assert src["sources"][0]["light"] == "red" and src["counts"] == {HELD: 1, PUBLISHED: 1}
    got = api.get("/api/v1/data/batches", headers=stw).json()
    assert [x["id"] for x in got["batches"]] == [old, bid]  # newest row first
    assert api.get(f"/api/v1/data/batches?state={HELD}", headers=stw).json()["batches"][0]["id"] == bid
    one = api.get(f"/api/v1/data/batches/{bid}", headers=stw).json()
    assert one["batch"]["state"] == HELD and [s["new"] for s in one["steps"]] == ["LANDED", HELD]
    assert api.get("/api/v1/data/batches/99999", headers=stw).status_code == 404
    assert api.post(f"/api/v1/data/batches/{bid}/decide", headers=stw, content=b"[1]").status_code == 400
    r = api.post(f"/api/v1/data/batches/{bid}/decide", headers=stw, json={"decision": "reject", "reason": ""})
    assert r.status_code == 400 and _state(bid) == HELD
    r = api.post(f"/api/v1/data/batches/{bid}/decide", headers=stw, json={"decision": "accept", "reason": "ok"})
    assert r.status_code == 409 and _state(bid) == HELD  # no promoter yet
    r = api.post(f"/api/v1/data/batches/{bid}/decide", headers=stw, json={"decision": "reject", "reason": "bad"})
    assert r.status_code == 200 and r.json()["batch"]["state"] == REJECTED
    assert api.post(f"/api/v1/data/batches/{bid}/decide", headers=stw,
                    json={"decision": "reject", "reason": "x"}).status_code == 409  # fmt: skip
    adm = _bearer(box, "admapi", "admin")
    assert api.get("/api/v1/data/batches", headers=adm).status_code == 200
    assert api.post(f"/api/v1/data/batches/{old}/decide", headers=adm, content=b"").status_code == 403
    crc = _bearer(box, "crcapi", "coordinator")
    assert api.get("/api/v1/data/sources", headers=crc).status_code == 403


def test_the_history_is_filtered_and_paged_by_the_store(box: dict[str, Any]) -> None:
    ids = [_night(box, f"2026-10-{d:02d}", held=False, passed=True) for d in range(1, 8)]
    _night(box, "2026-10-08", source="fhir_bulk")
    ops = DataOps()
    try:
        page1 = ops.history(limit=3)
        assert len(page1) == 3 and page1[0].source == "fhir_bulk"
        page2 = ops.history(limit=3, before=page1[-1].id)
        assert [b.id for b in page2] == ids[::-1][2:5]
        assert [b.source for b in ops.history(source="fhir_bulk")] == ["fhir_bulk"]
        assert ops.history(state=HELD)[0].source == "fhir_bulk"
        assert {b.source for b in ops.sources()} == {"csv", "fhir_bulk"}
    finally:
        ops.close()
    c = _user(box, "stw4", "steward")
    hist = c.get("/data-ops?source=csv").text.split('data-testid="dataops-history"')[1]
    assert hist.count('data-testid="batch"') == 7 and "fhir_bulk" not in hist


@pytest.mark.parametrize(("lang", "title", "held"), [("ja", "データ運用", "保留中の取り込み"),
                                                   ("zh-TW", "資料作業", "暫停中的匯入")])  # fmt: skip
def test_the_page_in_three_languages(box: dict[str, Any], lang: str, title: str, held: str) -> None:
    bid = _night(box, "2026-11-10")
    _user(box, "stwl", "steward")
    c, csrf = login(box["app"], "stwl", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = c.get("/data-ops").text
    assert title in page and held in page and not check(page)
    assert title in c.get(f"/data-ops/batches/{bid}").text


def test_the_catalogues_are_complete_and_clean() -> None:
    assert set(i18n_dataops.EN) == set(i18n_dataops.JA) == set(i18n_dataops.ZH)
    for lang, cat in (("en", i18n_dataops.EN), ("ja", i18n_dataops.JA), ("zh-TW", i18n_dataops.ZH)):
        for key, text in cat.items():
            assert not check(text), (lang, key)
    for state in ("LANDED", "VALIDATED", "MAPPED", "PSEUDONYMISED", "PUBLISHED", "HELD", "FAILED", "REJECTED"):
        assert f"dataops.state.{state}" in i18n_dataops.EN


def test_the_readiness_page_names_the_feed_tier_and_the_night(sb: dict[str, Any]) -> None:
    """T-112b (D-443): the readiness page's one block: the tier the box serves and the newest night's state."""

    class _Rows:
        def __init__(self, n: int) -> None:
            self.n = n

        def to_pylist(self) -> list[dict[str, Any]]:
            return [{"n": self.n, "unknown": 0}]

    class _Lake:
        docs = 0

        def snapshot(self) -> str:
            return "2026-11-09"

        def query(self, sql: str, args: Any = None) -> _Rows:
            return _Rows(self.docs)

    lake = _Lake()
    sb["svc"].main_lake = lake
    sb["state"]["approved"] = False  # no feasibility count on the stand-in lake
    _night(sb, "2026-11-10")
    c, _ = login(sb["app"], "crc", "site-setup-password-0001")
    page = c.get("/site?study=GZQO").text
    assert 'data-testid="site-feed" data-tier="structured"' in page and "tier 1 or 2" in page
    assert 'data-testid="site-feed-night" data-state="HELD"' in page and 'data-testid="miss-feed_held"' in page
    assert 'href="/data-ops"' not in page.split('data-testid="site-feed"')[1]  # the coordinator has no console link
    lake.docs = 3
    assert 'data-tier="notes"' in c.get("/site?study=GZQO").text and "tier 3" in c.get("/site?study=GZQO").text


# ---------------------------------------------------------------------------------------------- D-761's review
class _NoAnswer:
    """The orchestrator unreachable, or its answer lost (``ServiceError`` status 0)."""

    def get_json(self, path: str) -> Any:
        from tb_common.http import ServiceError

        raise ServiceError("orchestrator", 0, "no answer")

    def post_raw(self, path: str, body: Any, headers: Any = None) -> Any:
        from tb_common.http import ServiceError

        raise ServiceError("orchestrator", 0, "no answer")


def test_no_answer_from_the_orchestrator_is_said_never_a_500(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10")
    c = _user(box, "stw9", "steward")
    tok = _csrf(c.get("/data-ops").text)
    shim = box["backend"].orch
    box["backend"].orch_once = _NoAnswer()  # the decision's answer is lost
    r = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": "accept", "reason": "checked"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"].endswith("err=publishing")  # the accept may be recorded
    r = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": "reject", "reason": "bad"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 503
    box["backend"].orch = _NoAnswer()  # the orchestrator is down
    assert c.get("/data-ops").status_code == 503 and c.get(f"/data-ops/batches/{bid}").status_code == 503
    box["backend"].orch = shim


@pytest.mark.parametrize("decision", ["", "acceptxxxxxx"])
def test_a_decision_that_is_neither_is_refused_as_such(box: dict[str, Any], decision: str) -> None:
    bid = _night(box, "2026-11-10")
    c = _user(box, f"stw{len(decision)}", "steward")
    tok = _csrf(c.get("/data-ops").text)
    r = c.post(f"/data-ops/batches/{bid}/decide", data={"csrf": tok, "decision": decision, "reason": "r"},
               follow_redirects=False)  # fmt: skip
    assert r.headers["location"].endswith("err=decision") and _state(bid) == HELD


def test_a_held_night_says_when_its_publish_runs_or_did_not_publish(box: dict[str, Any]) -> None:
    from datacore.dataops import ACCEPTING, NOT_PUBLISHED

    running, refused = _night(box, "2026-11-08"), _night(box, "2026-11-09", source="lab")
    ops = DataOps()
    try:
        ops.note(running, step=ACCEPTING)
        ops.note(refused, step=NOT_PUBLISHED)
    finally:
        ops.close()
    page = _user(box, "stw8", "steward").get("/data-ops").text
    assert 'data-testid="held-publishing"' in page and 'data-testid="held-not-published"' in page
