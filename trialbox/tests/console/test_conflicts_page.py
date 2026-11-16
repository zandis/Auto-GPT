# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/data/conflicts`` (T-201, D-426): the steward lists the clinical conflicts and resolves one with a claimed value
or "unknown" and a reason (audited); every other role gets 403 on both routes; a value nobody claimed, a missing
reason or a settled conflict is refused; the page in three languages; the study page's new name (FIT-018)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from console import conflicts_page, i18n_conflicts, i18n_data

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    box,
    login,
)
from tests.console.test_role_pages import PW, _user

PID = "p" + "1" * 31  # a synthetic pseudonym


@pytest.fixture(autouse=True)
def _over_the_orchestrator(box: dict[str, Any]) -> Iterator[None]:
    """NEW-ARCH-3 slice 2 (D-865): the page asks the orchestrator's conflicts routes, here in process, through a
    client that signs nothing itself: the console's own signing is what the orchestrator verifies."""
    from console.backend import problem_of
    from fastapi import FastAPI
    from omop import schema
    from orchestrator.conflicts_api import router

    from tests.actor3 import SignedClient

    held: dict[str, Any] = {}

    def store() -> Any:
        if "db" not in held:
            held["db"] = schema.connect()
        return held["db"]

    api = FastAPI()
    api.include_router(router(store))
    coc = SignedClient(api, strict=True)

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = coc.request(method, path, json=body, **kw) if body is not None else coc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    yield
    if "db" in held:
        held["db"].close()


def _plant(state: str = "open") -> int:
    from omop import schema

    db = schema.connect()
    db.execute("INSERT INTO tb_id_map (id_kind, source_id, omop_id) VALUES ('person', ?, 7)", (PID,))
    claims = [{"value": "1960-02-03", "source": ["feed", "Patient", "x"]},
              {"value": "1961-02-03", "source": ["site", "Patient", "x"]}]  # fmt: skip
    cid = int(
        db.fetchval(
            "INSERT INTO tb_conflict (person_id, kind, item, values_sha, claims, state, detected_batch) "
            "VALUES (7, 'source_vs_source', 'birth_date', 'sha', ?::jsonb, ?, '2026-10-04') RETURNING conflict_id",
            (json.dumps(claims), state),
        )
    )
    db.close()
    return cid


def _row(cid: int) -> tuple[Any, ...]:
    from omop import schema

    db = schema.connect()
    try:
        r = db.fetchone("SELECT state, resolution, resolved_value, reason, resolved_by FROM tb_conflict "
                        "WHERE conflict_id = ?", (cid,))  # fmt: skip
        assert r is not None
        return tuple(r)
    finally:
        db.close()


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def test_the_steward_lists_and_resolves_with_a_value(box: dict[str, Any]) -> None:
    cid = _plant()
    c = _user(box, "stw", "steward")
    r = c.get("/data/conflicts")
    assert r.status_code == 200
    assert "Clinical conflicts" in r.text and PID in r.text and "1960-02-03" in r.text and "1961-02-03" in r.text
    assert 'data-item="birth_date" data-n="1"' in r.text and 'href="/data/conflicts"' in r.text  # the menu entry
    tok = _csrf(r.text)
    bad = c.post(f"/data/conflicts/{cid}/resolve", data={"csrf": tok, "choice": "1900-01-01", "reason": "typed"},
                 follow_redirects=False)  # fmt: skip
    assert bad.headers["location"].endswith("err=choice") and _row(cid)[0] == "open"
    bad = c.post(f"/data/conflicts/{cid}/resolve", data={"csrf": tok, "choice": "1961-02-03", "reason": " "},
                 follow_redirects=False)  # fmt: skip
    assert bad.headers["location"].endswith("err=reason") and _row(cid)[0] == "open"
    assert c.post(f"/data/conflicts/{cid}/resolve", data={"csrf": "x", "choice": "1961-02-03", "reason": "r"},
                  follow_redirects=False).status_code == 400  # fmt: skip
    ok = c.post(f"/data/conflicts/{cid}/resolve",
                data={"csrf": tok, "choice": "1961-02-03", "reason": "the chart says so"}, follow_redirects=False)  # fmt: skip
    assert ok.status_code == 303 and ok.headers["location"].endswith("done=1")
    assert _row(cid) == ("resolved", "value", "1961-02-03", "the chart says so", "console:stw")
    ev = _events(box, "console.conflict_resolved")
    assert len(ev) == 1 and ev[0]["detail"]["conflict"] == cid and ev[0]["detail"]["resolution"] == "value"
    again = c.post(f"/data/conflicts/{cid}/resolve", data={"csrf": tok, "choice": "1960-02-03", "reason": "r"},
                   follow_redirects=False)  # fmt: skip
    assert again.headers["location"].endswith("err=state")
    assert c.get("/data/conflicts").text.count('data-testid="conflict"') == 0
    trail = c.get("/data/conflicts?all=1").text
    assert 'data-state="resolved"' in trail and "the chart says so" in trail
    assert c.post("/data/conflicts/99999/resolve", data={"csrf": tok, "choice": "unknown", "reason": "r"},
                  follow_redirects=False).status_code == 404  # fmt: skip


def test_the_steward_keeps_the_item_unknown(box: dict[str, Any]) -> None:
    cid = _plant()
    c = _user(box, "stw2", "steward")
    tok = _csrf(c.get("/data/conflicts").text)
    c.post(f"/data/conflicts/{cid}/resolve", data={"csrf": tok, "choice": "unknown", "reason": "ask the ward"})
    assert _row(cid)[:3] == ("resolved", "unknown", None)


@pytest.mark.parametrize("role", ["admin", "coordinator", "investigator", "viewer", "cro", "privacy"])
def test_every_other_role_gets_403(box: dict[str, Any], role: str) -> None:
    cid = _plant()
    c = _user(box, f"u_{role}", role)
    r = c.get("/data/conflicts")
    assert r.status_code == 403 and PID not in r.text
    assert c.post(f"/data/conflicts/{cid}/resolve", data={"choice": "unknown", "reason": "r"}).status_code == 403
    assert _row(cid)[0] == "open"
    assert len(_events(box, "console.denied")) == 2


@pytest.mark.parametrize(("lang", "title"), [("ja", "臨床データの矛盾"), ("zh-TW", "臨床資料矛盾")])
def test_the_page_in_three_languages(box: dict[str, Any], lang: str, title: str) -> None:
    _plant()
    _user(box, "stw", "steward")
    c, csrf = login(box["app"], "stw", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    assert title in c.get("/data/conflicts").text
    assert conflicts_page.ACTION == "conflicts.resolve"
    assert set(i18n_conflicts.EN) == set(i18n_conflicts.JA) == set(i18n_conflicts.ZH)


def test_the_study_page_is_named_trial_record_differences() -> None:
    names = {i18n_data.EN["dc.conflicts.title"], i18n_data.JA["dc.conflicts.title"], i18n_data.ZH["dc.conflicts.title"]}
    assert names == {"Trial-record differences", "試験記録の相違", "試驗紀錄差異"}
    assert not names & {i18n_conflicts.EN["conflicts.title"], i18n_conflicts.JA["conflicts.title"],
                        i18n_conflicts.ZH["conflicts.title"]}  # fmt: skip
