"""BOX-VALIDATION (D-822), the owner's blockers 8 and 10 of 2026-11-15: the box form installs a VALIDATION box.

A box made by ``box-install.sh`` was always PRODUCTION: the owner's answers had no environment and the box plan
(``tools/box/plan.py``) never wrote ``TB_ENV``. The answers now take ``environment``, PRODUCTION (the default) or
VALIDATION (public or synthetic data, D-127); DEV and TEST are not a box's (a rehearsal box is TEST by its own
argument, D-726). The plan writes it as ``TB_ENV``. ``TB_ENV``'s declared help names VALIDATION."""

from __future__ import annotations

from typing import Any

import pytest
from tb_common import box_answers as ba
from tb_common.config import DECLARED

from tests.unit.test_box_plan import _hw
from tools.box import plan as bp

pytestmark = pytest.mark.nodb


def _raw(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {"site_name": "Hospital A", "tz": "Asia/Taipei", "language": "en",
                           "owner": {"full_name": "Owner", "username": "owner", "email": "owner@hospa.test"},
                           "box_name": "box1", "backup": {"kind": "later"}, "source": "later"}  # fmt: skip
    raw.update(over)
    return raw


def test_unanswered_is_production_and_the_plan_says_so() -> None:
    a, problems = ba.parse(_raw())
    assert problems == [] and a is not None and a.environment == "PRODUCTION"
    assert bp.plan(a, _hw()).env_extra["TB_ENV"] == "PRODUCTION"


@pytest.mark.parametrize("given", ["VALIDATION", "validation", " Validation "])
def test_validation_is_written_as_tb_env(given: str) -> None:
    a, problems = ba.parse(_raw(environment=given))
    assert problems == [] and a is not None and a.environment == "VALIDATION"
    assert bp.plan(a, _hw()).env_extra["TB_ENV"] == "VALIDATION"
    assert a.to_json()["environment"] == "VALIDATION"


@pytest.mark.parametrize("given", ["DEV", "TEST", "STAGING", "prod"])
def test_any_other_environment_is_a_problem_of_the_form(given: str) -> None:
    a, problems = ba.parse(_raw(environment=given))
    assert a is None and [(p.field, p.code) for p in problems] == [("environment", "environment")]


def test_the_provisional_answers_stay_production() -> None:
    assert bp.provisional(_hw()).environment == "PRODUCTION"


def test_tb_env_help_names_every_environment() -> None:
    help_text = DECLARED["TB_ENV"].doc
    assert all(e in help_text for e in ("DEV", "TEST", "VALIDATION", "PRODUCTION"))
