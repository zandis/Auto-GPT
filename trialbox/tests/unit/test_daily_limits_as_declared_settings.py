"""D-775 (D-507, cut to the build phase by D-511): the heavy-jobs daily limit is a declared setting.

``TB_JOBS_PER_SENDER_PER_DAY`` reaches a box made by ``install.sh --answers`` (``env_extra``): set, it is the limit of
every heavy job type and overrides ``settings.yaml``; 0 means no limit (lane G's VALIDATION box lifts it so). Unset or
not a whole number, a box behaves as before. A type not counted by default never takes it. Synthetic values only."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.authz import daily_limit
from tb_common.config import DECLARED


def _settings(**kw: Any) -> Any:
    """The two fields of the site's settings the limit reads (``tb_contracts.Settings``; defaults as there)."""
    return SimpleNamespace(**{"rate_limit_per_sender_per_day": 20, "rate_limits_per_day": None, **kw})


def test_the_jobs_limit_is_a_declared_variable() -> None:
    d = DECLARED["TB_JOBS_PER_SENDER_PER_DAY"]
    assert d.kind == "int" and "D-775" in d.doc


def test_a_validation_box_lifts_the_jobs_limit() -> None:
    e = {"TB_ENV": "VALIDATION"}
    assert daily_limit(_settings(), "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "0"}) is None  # no limit
    assert daily_limit(_settings(), "SCREEN", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "500"}) == 500
    low = _settings(rate_limits_per_day={"FEAS": 3}, rate_limit_per_sender_per_day=7)
    assert daily_limit(low, "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "50"}) == 50  # overrides settings.yaml


@pytest.mark.parametrize("raw", [None, "", "abc", "5.0"])
def test_unset_or_malformed_the_site_settings_hold_as_before(raw: str | None) -> None:
    e = {} if raw is None else {"TB_JOBS_PER_SENDER_PER_DAY": raw}
    assert daily_limit(_settings(), "FEAS", e) == 20
    assert daily_limit(_settings(rate_limit_per_sender_per_day=7), "FEAS", e) == 7
    assert daily_limit(_settings(rate_limits_per_day={"FEAS": 3}), "FEAS", e) == 3


def test_a_type_not_counted_by_default_never_takes_the_variable() -> None:
    e = {"TB_JOBS_PER_SENDER_PER_DAY": "500"}
    assert daily_limit(_settings(), "CASE", e) is None
    assert daily_limit(_settings(rate_limits_per_day={"CASE": 5}), "CASE", e) == 5
