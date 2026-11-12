# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/ops/flags`` (T-008, D-207, MR-090): administrators only, a reason and one confirmation for a change, the audit
event with actor and reason, 400 for an undeclared flag or a bad value, the first-start seed at ``create_app``."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console import i18n_flags
from console.i18n import CATALOGUES
from tb_common import flags as fl

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    box,
    login,
)
from tests.console.test_role_pages import _csrf, _user


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    yield
    fl.clear_cache()


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == name]


def test_admin_sees_the_flags_seeded_at_start(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])
    r = c.get("/ops/flags")
    assert r.status_code == 200
    assert 'data-flag="lake.source"' in r.text and 'data-value="legacy"' in r.text
    assert 'data-kind="seed"' in r.text  # the first value is in the history
    assert len(_events(box, "flag.seed")) == len(fl.DECLARED)  # each declared flag seeded once


def test_a_change_needs_a_reason_and_a_confirmation_and_is_audited(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])
    csrf = _csrf(c.get("/ops/flags").text)
    form = {"csrf": csrf, "name": "lake.source", "value": "omop", "reason": "D-207 test: the goldens held"}
    r = c.post("/ops/flags", data={**form, "reason": "  "}, follow_redirects=False)
    assert r.status_code == 400
    r = c.post("/ops/flags", data=form, follow_redirects=False)
    assert r.status_code == 200 and 'data-testid="confirm"' in r.text
    assert "lake.source" in r.text and "legacy" in r.text and "omop" in r.text and "the goldens held" in r.text
    assert fl.Flags().row("lake.source") == "legacy"  # nothing changed before Yes
    assert 'name="old" value="legacy"' in r.text  # the sheet carries the value it showed
    r = c.post("/ops/flags", data={**form, "confirm": "yes", "old": "legacy"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ops/flags#flag-lake.source"
    assert fl.Flags().row("lake.source") == "omop"
    (ev,) = _events(box, "flag.set")
    assert ev["actor"] == "console:admin"
    assert {k: ev["detail"][k] for k in ("flag", "old", "new", "reason")} == {
        "flag": "lake.source", "old": "legacy", "new": "omop", "reason": "D-207 test: the goldens held"}  # fmt: skip
    page = c.get("/ops/flags").text
    assert 'data-value="omop"' in page and 'data-kind="set"' in page and "the goldens held" in page
    r = c.post("/ops/flags", data={**form, "confirm": "yes", "old": "omop"}, follow_redirects=False)
    assert r.status_code == 400  # already omop: not a second event
    assert len(_events(box, "flag.set")) == 1


@pytest.mark.parametrize(
    ("name", "value"), [("lake.sauce", "omop"), ("", "omop"), ("lake.source", "fhir"), ("lake.source", "")]
)
def test_an_undeclared_flag_or_a_bad_value_is_400(box: dict[str, Any], name: str, value: str) -> None:
    c, _ = login(box["app"])
    csrf = _csrf(c.get("/ops/flags").text)
    for confirm in ("", "yes"):
        r = c.post("/ops/flags", data={"csrf": csrf, "name": name, "value": value, "reason": "x", "confirm": confirm},
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 400
    assert fl.Flags().row("lake.source") == "legacy" and not _events(box, "flag.set")


def test_a_bad_csrf_is_400(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])
    r = c.post("/ops/flags", data={"csrf": "x", "name": "lake.source", "value": "omop", "reason": "r",
                                   "confirm": "yes"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 400 and fl.Flags().row("lake.source") == "legacy"


@pytest.mark.parametrize("role", ["viewer", "coordinator", "investigator", "cro"])
def test_anyone_but_an_administrator_gets_403(box: dict[str, Any], role: str) -> None:
    c = _user(box, f"u{role[:6]}", role)
    assert c.get("/ops/flags").status_code == 403
    csrf = _csrf(c.get("/").text)
    r = c.post("/ops/flags", data={"csrf": csrf, "name": "lake.source", "value": "omop", "reason": "r",
                                   "confirm": "yes"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 403
    assert fl.Flags().row("lake.source") == "legacy" and not _events(box, "flag.set")
    assert any(e["detail"]["action"] == "/ops/flags" for e in _events(box, "console.denied"))


def test_the_seed_at_start_comes_from_the_variable_once(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The box fixture's create_app already seeded ``legacy`` (no variable); a later start with
    ``TB_LAKE_SOURCE=omop`` changes nothing, and doctor would say so."""
    from console.admin_flags import seed_at_start

    monkeypatch.setenv("TB_LAKE_SOURCE", "omop")
    assert seed_at_start(box["app"].state.helpers) == []
    assert fl.Flags().row("lake.source") == "legacy"
    assert fl.env_drift({"TB_LAKE_SOURCE": "omop"})
    monkeypatch.delenv("TB_DB_URL")
    assert seed_at_start(box["app"].state.helpers) == []  # no trial database: the console starts all the same


def test_the_page_in_three_languages() -> None:
    assert set(i18n_flags.EN) == set(i18n_flags.JA) == set(i18n_flags.ZH)
    for lang in ("en", "ja", "zh-TW"):
        assert set(i18n_flags.EN) <= set(CATALOGUES[lang]), lang
    assert all(f"flags.desc.{n}" in i18n_flags.EN for n in fl.DECLARED)


def test_a_stale_confirmation_or_a_long_reason_is_refused(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])
    csrf = _csrf(c.get("/ops/flags").text)
    form = {"csrf": csrf, "name": "lake.source", "value": "omop", "reason": "r", "confirm": "yes"}
    r = c.post("/ops/flags", data={**form, "old": "omop"}, follow_redirects=False)  # the sheet showed another value
    assert r.status_code == 400 and "changed by someone else meanwhile" in r.text
    r = c.post("/ops/flags", data={**form, "old": "legacy", "reason": "x" * (fl.MAX_REASON + 1)},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 400
    assert fl.Flags().row("lake.source") == "legacy" and not _events(box, "flag.set")


def test_a_flag_store_that_does_not_answer_is_a_503_page(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """T-655 (PR #71 review): the trial database is down: the list, the sheet and a Yes are a 503 page, never a 500 or
    a 400, and nothing is changed or audited."""
    import os

    c, _ = login(box["app"])
    csrf = _csrf(c.get("/ops/flags").text)
    url = os.environ["TB_DB_URL"]
    monkeypatch.setenv("TB_DB_URL", "postgresql://nobody@/nowhere?host=/nonexistent")
    fl.clear_cache()
    r = c.get("/ops/flags")
    assert r.status_code == 503 and "cannot be read just now" in r.text
    form = {"csrf": csrf, "name": "lake.source", "value": "omop", "reason": "D-207 test: store down"}
    assert c.post("/ops/flags", data=form, follow_redirects=False).status_code == 503
    r = c.post("/ops/flags", data={**form, "confirm": "yes", "old": "legacy"}, follow_redirects=False)
    assert r.status_code == 503
    monkeypatch.setenv("TB_DB_URL", url)
    assert fl.Flags().row("lake.source") == "legacy" and not _events(box, "flag.set")
