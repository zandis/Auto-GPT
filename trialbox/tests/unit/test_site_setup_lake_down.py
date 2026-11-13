"""NEW-SITE-2 (D-709): the site set-up when the hospital's lake cannot be asked.

D-672 made the lake's client raise when the lake is not healthy (before, it said "no snapshot", a healthy empty
lake). Three things in the site set-up and the orchestrator then went wrong, each held here:

1. an upload, a chart, a code map or a resolve was stored and audited, and then the publish raised: the route
   answered 500 for a change that was saved, and a person who tried again added a second input. The change is
   answered as saved, with the publish waiting for the lake; the batch goes with the next tick;
2. the readiness answer read a lake that could not be asked as "no feed", "no unknown codes" and "scores
   verified": it now says the lake could not be read, and the readiness, patient check and feasibility routes
   answer that instead of failing;
3. the derive status showed no current snapshot: it says the lake could not be asked.

Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from lake.client import LakeUnhealthy
from sitesetup import help, readiness
from sitesetup.service import SiteSetup

from tests.unit.test_site_setup import STUDY, TODAY, pid, site_ruleset, svc  # noqa: F401 - the fixture, by name

MAIN = "main"


class Down:
    """The hospital's lake as the client sees it while it cannot say which snapshot it serves."""

    def __init__(self, lake: Any, error: Exception) -> None:
        self._lake, self._error, self.asked = lake, error, 0

    def snapshot(self) -> str | None:
        self.asked += 1
        raise self._error

    def __getattr__(self, name: str) -> Any:
        return getattr(self._lake, name)


def _unhealthy() -> Exception:
    return LakeUnhealthy(503)


def _unreachable() -> Exception:
    return httpx.ConnectError("connection refused")


def _audit(tmp: Path, event: str) -> list[dict[str, Any]]:
    rows = [json.loads(x) for p in sorted((tmp / "audit").glob("*.jsonl")) for x in p.read_text().splitlines() if x]
    return [r for r in rows if r["event"] == event]


@pytest.fixture(params=[_unhealthy, _unreachable], ids=["answers 503", "cannot be reached"])
def down(svc: SiteSetup, request: pytest.FixtureRequest) -> Any:  # noqa: F811
    up = svc.main_lake
    svc.main_lake = Down(up, request.param())
    yield svc
    svc.main_lake = up


# ------------------------------------------------------------------ 1. a saved change is answered as saved
def test_an_upload_while_the_lake_is_down_is_saved_once_and_published_when_it_is_back(
    down: SiteSetup, tmp_path: Path
) -> None:
    inp = help.practice_inputs()
    lake_down, up = down.main_lake, down.main_lake._lake
    out = down.add_sheet(MAIN, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    assert out["publish"] == "waits_for_lake" and out["patients"] == 4
    assert lake_down.asked >= 1
    assert len(down.store.inputs(MAIN)) == 1  # saved, and nobody has a reason to send it a second time
    assert len(_audit(tmp_path, "setup.input")) == 1  # the upload's own audit event, which came after the publish
    assert down.store.published(MAIN) is None and _audit(tmp_path, "setup.publish") == []
    waits = _audit(tmp_path, "setup.publish_waits")
    assert waits and waits[-1]["detail"] == {"ws": MAIN, "why": "lake"}
    # the lake is back: the tick publishes what waited, with no second upload
    down.main_lake = up
    down.flush(MAIN)
    assert down.store.published(MAIN) is not None and len(down.store.inputs(MAIN)) == 1


def test_a_chart_a_code_map_and_a_resolve_are_answered_as_saved(down: SiteSetup, tmp_path: Path) -> None:
    inp = help.practice_inputs()
    no, text = inp["charts"][0]
    out = down.add_chart(MAIN, no, "pasted.txt", text.encode(), "crc", "ja", pasted=True)
    assert out["publish"] == "waits_for_lake" and len(down.store.inputs(MAIN, "chart")) == 1
    assert len(_audit(tmp_path, "setup.chart")) == 1
    down.add_sheet(MAIN, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    c = next(c for c in down.store.locals(MAIN) if c["suggested_code"])
    target = {"system": c["suggested_system"], "code": c["suggested_code"]}
    out = down.map_code(MAIN, c["domain"], c["system"], c["code"], target, "crc")
    assert out["publish"] == "waits_for_lake" and len(_audit(tmp_path, "setup.map")) == 1
    assert any(x["mapped_code"] == c["suggested_code"] for x in down.store.locals(MAIN))
    down.add_sheet(MAIN, "sheet", inp["sheet"][0], inp["sheet"][1], {}, "crc")
    for chk in down.store.checks(MAIN, open_only=True):
        down.answer(int(chk["id"]), "drop" if chk["key"] == "chart_column:ID" else chk["suggestion"], "crc")
    out = down.resolve(MAIN, pid("10000002"), "birth_date", "1971-06-05", "crc")
    assert out["publish"] == "waits_for_lake" and out["rejected"] >= 1
    assert len(_audit(tmp_path, "setup.resolve")) == 1


def test_a_publish_a_person_asks_for_still_fails_and_another_error_is_not_swallowed(svc: SiteSetup) -> None:  # noqa: F811
    inp = help.practice_inputs()
    up = svc.main_lake
    svc.main_lake = Down(up, _unhealthy())
    assert svc.add_sheet(MAIN, "sheet", inp["sheet"][0], inp["sheet"][1], {}, "crc")["publish"] == "waits_for_lake"
    with pytest.raises(LakeUnhealthy):  # the person pressed Publish: "saved, waiting" would be untrue of it
        svc.publish(MAIN, "crc", force=True)
    svc.main_lake = Down(up, RuntimeError("a fault of the code"))
    with pytest.raises(RuntimeError):
        svc.add_sheet(MAIN, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    svc.main_lake = up


def test_a_change_with_the_lake_up_says_nothing_of_waiting(svc: SiteSetup) -> None:  # noqa: F811
    inp = help.practice_inputs()
    out = svc.add_sheet("newsite", "dump", inp["dump"][0], inp["dump"][1], {}, "crc")
    assert "publish" not in out


# ------------------------------------------------------------------ 2. readiness says "could not be read"
def test_the_readiness_answer_says_the_lake_could_not_be_read_not_that_there_is_no_feed(down: SiteSetup) -> None:
    rd = readiness.readiness(down, MAIN, STUDY, {"forms": 7})
    assert rd["lake_unread"] is True and rd["feed"] is None
    q = rd["questions"]["patients"]
    assert q["missing"][0]["key"] == "patients.lake_unread"
    assert q["state"] == "amber" and rd["overall"] == "amber"  # not known: neither "no patients" nor "ready"
    assert "patients.unknown_share" not in {m["key"] for m in q["missing"]}


def test_the_three_readers_raise_instead_of_answering_nothing(down: SiteSetup, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(readiness.DB_ENV, "postgresql://nowhere/none")
    for fn, args in ((readiness.feed_loaded, (down,)), (readiness.unknown_share, (down, MAIN)),
                     (readiness.scores_unverified, (down,))):  # fmt: skip
        with pytest.raises(readiness.LAKE_DOWN):
            fn(*args)


def test_the_lake_up_is_read_as_before(svc: SiteSetup) -> None:  # noqa: F811
    rd = readiness.readiness(svc, MAIN, STUDY, {"forms": 7})
    assert "lake_unread" not in rd and rd["questions"]["patients"]["state"] == "red"  # an empty box: no patients


def test_the_routes_answer_that_the_lake_could_not_be_read(down: SiteSetup) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from orchestrator.setup_api import router as setup_router

    rs = site_ruleset()
    inp = help.practice_inputs()
    api = FastAPI()
    api.include_router(setup_router(lambda: down, lambda rid: {**STUDY, "id": rid}, lambda rid: {"forms": 7},
                                    lambda rid: rs, lambda: False, lambda *a, **k: None))  # fmt: skip
    c = TestClient(api, raise_server_exceptions=False)
    r = c.get(f"/setup/{MAIN}/feasibility?study=SITE5B")  # nothing uploaded: still not "needs a bulk input"
    assert r.status_code == 200 and r.json()["lake_unread"] is True and r.json()["needs_bulk"] is False
    down.add_sheet(MAIN, "dump", inp["dump"][0], inp["dump"][1], {}, "crc")  # patients of the set-up's own store
    r = c.get(f"/setup/{MAIN}/readiness?study=SITE5B")
    assert r.status_code == 200 and r.json()["lake_unread"] is True
    r = c.get(f"/setup/{MAIN}/patients?study=SITE5B")
    assert r.status_code == 200 and r.json() == {"study": "SITE5B", "approved": True, "patients": [],
                                                 "lake_unread": True}  # fmt: skip
    r = c.get(f"/setup/{MAIN}/feasibility?study=SITE5B")
    assert r.status_code == 200 and r.json()["feas"] is None and r.json()["lake_unread"] is True


# ------------------------------------------------------------------ 3. the derive status
def test_the_derive_status_says_the_lake_could_not_be_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from orchestrator import derive
    from tb_common.metrics import OK, WARN, check_derive

    last = {"snapshot": "2026-11-09", "finished_at": "x", "failed": 0}
    monkeypatch.setattr(derive, "url_of", lambda orch: "postgresql://x")
    monkeypatch.setattr(derive, "shared_store", lambda url: SimpleNamespace(last_batch=lambda: last))
    monkeypatch.setattr("tb_common.flags.read", lambda name, url: "on")
    orch = SimpleNamespace(services=SimpleNamespace(lake=Down(None, _unhealthy())))
    got = derive.status(orch)
    assert got == {"flag": "on", "current": None, "last": last, "lake_unread": True}
    line = check_derive(got)
    assert line.level == WARN and "could not be asked" in line.text and "2026-11-09" in line.text
    # asked and answered: as before
    orch = SimpleNamespace(services=SimpleNamespace(lake=SimpleNamespace(snapshot=lambda: "2026-11-09")))
    got = derive.status(orch)
    assert got is not None and "lake_unread" not in got and check_derive(got).level == OK
