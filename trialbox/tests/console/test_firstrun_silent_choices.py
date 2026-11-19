"""10K-21 (D-1365; review 18, SO-21): the box's first-run page does not leave three choices silent.

On a PRODUCTION box the page refuses to finish without a chart-number rule (``kept as written`` chosen is an
answer; ``Not answered`` is not) and without the name of the person who opens the health page every working day (a
box's backup alert route is the health page, D-735). Who in hospital IT confirmed the box's root certificate is on
the team's computers is asked too; it may stay empty (the box makes its root at its first start), and it is recorded
with the day it was given. Outside PRODUCTION the page reads the answers as before. The texts are in en, ja and
zh-TW."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from console import firstrun as page
from console.i18n_firstrun import EN, JA, ZH
from tb_common import box_answers, firstrun

from tests.console.test_firstrun import _answers, _box, _with_code

NEW_KEYS = (
    "firstrun.chartno.help.production",
    "firstrun.err.chartno_required",
    "firstrun.health_page_person",
    "firstrun.health_page_person.help",
    "firstrun.err.health_page_person_required",
    "firstrun.tls_root",
    "firstrun.tls_root.help",
    "firstrun.err.person_name",
    "firstrun.err.confirmed_on",
)


@pytest.fixture(autouse=True)
def _no_patients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page, "box_holds_patients", lambda: False)  # the page asks the chart-number rule


def _written(b: dict[str, Any]) -> dict[str, Any]:
    got: dict[str, Any] = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    return got


def test_production_refuses_a_silent_chart_number_rule_and_an_unnamed_health_page(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    c = _with_code(b)
    shown = c.get("/login/first-run/answers").text
    assert "This box is in use, so this must be answered" in shown and 'name="health_page_person"' in shown
    r, _ = _answers(c)
    assert r.status_code == 422 and b["users"].count() == 0
    assert 'data-testid="err-chartno_rule"' in r.text and "choose kept as written" in r.text
    assert 'data-testid="err-health_page_person"' in r.text
    assert not (tmp_path / "firstrun" / firstrun.ANSWERS).exists()


def test_production_takes_kept_as_written_chosen_and_a_named_person(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    c = _with_code(b)
    r, _ = _answers(c, chartno_kind="asis", health_page_person="山田 花子")
    assert r.status_code == 200 and 'data-testid="firstrun-done"' in r.text, r.text[-600:]
    got = _written(b)
    assert got["chartno_rule"] == "asis" and got["health_page_person"] == "山田 花子"
    assert "tls_root_confirmed_by" not in got  # not answered: not written (doctor reports it)


def test_it_s_confirmation_is_recorded_with_who_and_the_day(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    c = _with_code(b)
    r, _ = _answers(c, chartno_kind="digits", chartno_width="8", health_page_person="Dr Owner",
                    tls_root_confirmed_by="Lin, IT desk")  # fmt: skip
    assert r.status_code == 200, r.text[-600:]
    got = _written(b)
    assert got["tls_root_confirmed_by"] == "Lin, IT desk" and got["tls_root_confirmed_on"] == date.today().isoformat()


@pytest.mark.parametrize("field", ["health_page_person", "tls_root_confirmed_by"])
def test_a_name_that_is_not_one_plain_value_is_refused(tmp_path: Path, field: str) -> None:
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    c = _with_code(b)
    over = {"chartno_kind": "asis", "health_page_person": "Dr Owner", field: "A $(id) #x"}
    r, _ = _answers(c, **over)
    assert r.status_code == 422 and f'data-testid="err-{field}"' in r.text and "one name on one line" in r.text


def test_outside_production_the_page_reads_the_answers_as_before(tmp_path: Path) -> None:
    b = _box(tmp_path)  # the suite's TEST box
    c = _with_code(b)
    assert "If you are not sure, leave this unanswered" in c.get("/login/first-run/answers").text
    r, _ = _answers(c)
    assert r.status_code == 200, r.text[-600:]
    got = _written(b)
    assert got["chartno_rule"] == "" and "health_page_person" not in got


def test_a_box_that_holds_patients_is_not_asked_the_rule_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(page, "box_holds_patients", lambda: True)
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    c = _with_code(b)
    r, _ = _answers(c, health_page_person="Dr Owner")
    assert r.status_code == 200, r.text[-600:]  # the box's rule stays; no refusal for a question not asked


@pytest.mark.nodb
def test_the_gaps_are_the_schema_s_one_rule() -> None:
    base = {"site_name": "Site A (synthetic)", "tz": "Asia/Tokyo", "owner_full_name": "Dr Owner",
            "owner_username": "owner", "owner_email": "owner@hospa.test", "backup_kind": "later"}  # fmt: skip
    a, problems = box_answers.parse(base)
    assert a is not None, problems
    assert [p.code for p in box_answers.production_gaps(a)] == ["chartno_required", "health_page_person_required"]
    assert [p.code for p in box_answers.production_gaps(a, chartno_asked=False)] == ["health_page_person_required"]
    a, _ = box_answers.parse({**base, "chartno_rule": "asis", "health_page_person": "Dr Owner"})
    assert a is not None and box_answers.production_gaps(a) == []
    _, problems = box_answers.parse({**base, "tls_root_confirmed_by": "Lin", "tls_root_confirmed_on": "2999-01-01"})
    assert [p.code for p in problems] == ["confirmed_on"]  # a day to come is not a confirmation


@pytest.mark.nodb
def test_the_new_texts_are_in_the_three_languages() -> None:
    for cat in (EN, JA, ZH):
        missing = [k for k in NEW_KEYS if not cat.get(k, "").strip()]
        assert not missing, missing
    assert "書かれたとおりに扱う" in JA["firstrun.err.chartno_required"]  # the option's own words
    assert "依原樣處理" in ZH["firstrun.err.chartno_required"]
