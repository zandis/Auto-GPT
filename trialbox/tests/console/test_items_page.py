# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""``/data/items`` (T-107, D-353): the catalogue by specialty in three languages for the steward (D-380: the
matrix's ``items.view``; T-102a found it the administrator's), 403 for the administrator, a coordinator (CRC) and the
other roles, 503 when the catalogue cannot be read."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from console import i18n_items, items_page
from console.i18n import CATALOGUES
from tb_common import catalogue

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    box,
    login,
)
from tests.console.test_role_pages import PW, _user


def _denied(b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == "console.denied" and e["detail"].get("action") == "/data/items"]


@pytest.mark.parametrize(
    ("lang", "title", "name"),
    [("en", "Clinical items", "Systolic blood pressure"), ("ja", "臨床項目", "収縮期血圧"),
     ("zh-TW", "臨床項目", "收縮壓")],
)  # fmt: skip
def test_the_steward_sees_items_by_specialty_in_three_languages(
    box: dict[str, Any], lang: str, title: str, name: str
) -> None:
    _user(box, "stw", "steward")
    c, csrf = login(box["app"], "stw", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    r = c.get("/data/items")
    assert r.status_code == 200
    assert title in r.text and name in r.text
    specs = [s["id"] for s in catalogue.specialties()]
    shown = [p.split('"')[0] for p in r.text.split('data-specialty="')[1:]]
    assert shown == ["GEN", *specs]  # every specialty, the general items first
    assert r.text.count('data-testid="item"') == sum(len(i.specialties) for i in catalogue.items())
    assert 'data-item="neuro.mmse_total" data-storable="score"' in r.text
    assert "LOINC 8480-6" in r.text and "2000001004" in r.text


def test_one_specialty_and_an_unknown_one(box: dict[str, Any]) -> None:
    c = _user(box, "stw", "steward")
    r = c.get("/data/items?specialty=rheu")
    assert r.status_code == 200
    assert r.text.count('data-testid="items-specialty"') == 1 and 'data-specialty="RHEU"' in r.text
    assert r.text.count('data-testid="item"') == sum(1 for i in catalogue.items() if "RHEU" in i.specialties)
    assert c.get("/data/items?specialty=NOPE").status_code == 404


@pytest.mark.parametrize("role", ["admin", "coordinator", "investigator", "viewer", "cro", "privacy"])
def test_a_crc_and_every_other_role_gets_403(box: dict[str, Any], role: str) -> None:
    c = _user(box, f"u_{role}", role)
    r = c.get("/data/items")
    assert r.status_code == 403
    assert "Systolic blood pressure" not in r.text
    assert len(_denied(box)) == 1


def test_an_unreadable_catalogue_is_503(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TB_CATALOGUE_DIR", str(tmp_path / "missing"))
    c = _user(box, "stw", "steward")
    r = c.get("/data/items")
    assert r.status_code == 503 and "cannot be read" in r.text


def test_the_page_in_three_languages() -> None:
    assert items_page.GENERAL == "GEN"  # importing the page joins its strings to the catalogues
    assert set(i18n_items.EN) == set(i18n_items.JA) == set(i18n_items.ZH)
    for lang in ("en", "ja", "zh-TW"):
        assert set(i18n_items.EN) <= set(CATALOGUES[lang]), lang
    for s in catalogue.STORABLE:
        assert f"items.storable.{s}" in i18n_items.EN
    for fit in {i.code_fit for i in catalogue.items()}:
        assert f"items.fit.{fit}" in i18n_items.EN
