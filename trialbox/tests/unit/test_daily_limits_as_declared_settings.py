"""D-507 (the owner's ruling of 2026-11-15, lane G's blocker 5): the daily limits are declared settings a VALIDATION box
can lift; PRODUCTION keeps today's values.

The limits are the heavy jobs a sender may start in a day (20; FEAS, SCREEN, COHORT, NAV, MICROBATCH, CALIBRATION,
D-146) and the mails one recipient gets in a day (200, T-108c). A box made by ``install.sh --answers`` reaches
declared ``TB_*`` variables (``env_extra``), not the site's ``settings.yaml``. So the jobs limit gets a declared
variable too, ``TB_JOBS_PER_SENDER_PER_DAY``, next to the mail's ``TB_MAIL_PER_RECIPIENT_PER_DAY``. 0 means no limit.

* on VALIDATION, TEST and DEV either variable may be set to any value, 0 included;
* on PRODUCTION (and a site box with ``TB_ENV`` unset) a setting may lower a limit, never lift it: 0 or a value above
  today's default is not applied, and today's value holds;
* unset, a box behaves as before (the site's ``settings.yaml``; the mail's built-in 200).

Synthetic values only."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from tb_common import daily_limits
from tb_common.authz import daily_limit
from tb_common.config import DECLARED


def _settings(**kw: Any) -> Any:
    """The two fields of the site's settings the limit reads (``tb_contracts.Settings``; defaults as there)."""
    return SimpleNamespace(**{"rate_limit_per_sender_per_day": 20, "rate_limits_per_day": None, **kw})


def test_both_limits_are_declared_variables() -> None:
    for name in ("TB_JOBS_PER_SENDER_PER_DAY", "TB_MAIL_PER_RECIPIENT_PER_DAY"):
        assert name in DECLARED and DECLARED[name].kind == "int", name
    assert "D-507" in DECLARED["TB_JOBS_PER_SENDER_PER_DAY"].doc


@pytest.mark.parametrize("env", ["VALIDATION", "TEST", "DEV"])
def test_a_validation_box_lifts_the_jobs_limit(env: str) -> None:
    s = _settings()
    assert daily_limit(s, "FEAS", {"TB_ENV": env, "TB_JOBS_PER_SENDER_PER_DAY": "0"}) is None  # no limit
    assert daily_limit(s, "SCREEN", {"TB_ENV": env, "TB_JOBS_PER_SENDER_PER_DAY": "500"}) == 500
    assert daily_limit(s, "CASE", {"TB_ENV": env, "TB_JOBS_PER_SENDER_PER_DAY": "500"}) is None  # never counted


def test_unset_the_site_settings_hold_as_before() -> None:
    assert daily_limit(_settings(), "FEAS", {"TB_ENV": "VALIDATION"}) == 20
    assert daily_limit(_settings(rate_limit_per_sender_per_day=7), "FEAS", {}) == 7
    assert daily_limit(_settings(rate_limits_per_day={"FEAS": 3}), "FEAS", {}) == 3


@pytest.mark.parametrize("env", ["PRODUCTION", ""])
def test_production_may_lower_but_not_lift(env: str) -> None:
    e = {"TB_ENV": env} if env else {}
    s = _settings()
    assert daily_limit(s, "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "5"}) == 5  # lower: applied
    assert daily_limit(s, "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "0"}) == 20  # no limit: today's value holds
    assert daily_limit(s, "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "500"}) == 20  # above: today's value holds
    assert daily_limit(_settings(rate_limit_per_sender_per_day=0), "FEAS", e) == 20  # the site file cannot lift either
    assert daily_limit(_settings(rate_limits_per_day={"SCREEN": 90}), "SCREEN", e) == 20


def test_the_mail_limit_follows_the_same_rule() -> None:
    assert daily_limits.mail_per_recipient({"TB_ENV": "VALIDATION", "TB_MAIL_PER_RECIPIENT_PER_DAY": "0"}) == 0
    assert daily_limits.mail_per_recipient({"TB_ENV": "VALIDATION", "TB_MAIL_PER_RECIPIENT_PER_DAY": "5000"}) == 5000
    assert daily_limits.mail_per_recipient({"TB_ENV": "PRODUCTION", "TB_MAIL_PER_RECIPIENT_PER_DAY": "0"}) == 200
    assert daily_limits.mail_per_recipient({"TB_ENV": "PRODUCTION", "TB_MAIL_PER_RECIPIENT_PER_DAY": "50"}) == 50
    assert daily_limits.mail_per_recipient({}) == 200


def test_a_refused_lift_is_said() -> None:
    """``doctor`` and the services name a lift a PRODUCTION box does not apply."""
    got = daily_limits.refused_lifts({"TB_ENV": "PRODUCTION", "TB_JOBS_PER_SENDER_PER_DAY": "0",
                                      "TB_MAIL_PER_RECIPIENT_PER_DAY": "900"}, _settings())  # fmt: skip
    assert {x.split(":")[0] for x in got} == {"TB_JOBS_PER_SENDER_PER_DAY", "TB_MAIL_PER_RECIPIENT_PER_DAY"}
    assert daily_limits.refused_lifts({"TB_ENV": "VALIDATION", "TB_JOBS_PER_SENDER_PER_DAY": "0"}, _settings()) == []


def test_doctor_fails_a_refused_lift_and_names_it() -> None:
    from tools.trialbox.doctor import CHECKS, DoctorInputs, check_daily_limits

    assert check_daily_limits in CHECKS
    bad = check_daily_limits(DoctorInputs(env={"TB_ENV": "PRODUCTION"}, settings={"rate_limit_per_sender_per_day": 0}))
    assert bad.status == "FAIL" and "rate_limit_per_sender_per_day" in bad.detail, bad
    ok = check_daily_limits(DoctorInputs(env={"TB_ENV": "VALIDATION", "TB_MAIL_PER_RECIPIENT_PER_DAY": "0"}))
    assert ok.status == "PASS" and "mail a recipient a day: no limit" in ok.detail, ok
    assert check_daily_limits(DoctorInputs(env={"TB_ENV": "PRODUCTION"})).status == "PASS"  # unset: today's values


# ---------------------------------------------------------------------------------------------- the review's cases
@pytest.mark.parametrize("env", ["PRODUCTION", ""])
def test_on_production_the_variable_only_lowers_the_sites_own_limit(env: str) -> None:
    """The review of D-775 (1): a site that lowered FEAS to 3 keeps 3 whatever the variable says; doctor names it."""
    e = {"TB_ENV": env} if env else {}
    low = _settings(rate_limits_per_day={"FEAS": 3}, rate_limit_per_sender_per_day=7)
    assert daily_limit(low, "FEAS", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "20"}) == 3
    assert daily_limit(low, "SCREEN", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "10"}) == 7
    assert daily_limit(low, "SCREEN", {**e, "TB_JOBS_PER_SENDER_PER_DAY": "5"}) == 5  # lowering is applied
    got = daily_limits.refused_lifts({**e, "TB_JOBS_PER_SENDER_PER_DAY": "20"}, low)
    assert any(x.startswith("TB_JOBS_PER_SENDER_PER_DAY: 20") and "FEAS" in x for x in got), got
    assert daily_limit(low, "FEAS", {"TB_ENV": "VALIDATION", "TB_JOBS_PER_SENDER_PER_DAY": "20"}) == 20  # lifts there


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_a_type_not_counted_by_default_keeps_the_sites_value_and_ignores_the_variable(env: str) -> None:
    """The review of D-775 (2): CASE, CONSENT and STATUS have no limit by default; a site's value is a new limit, never
    a lift, and the variable never reaches them."""
    e = {"TB_ENV": env, "TB_JOBS_PER_SENDER_PER_DAY": "500"}
    assert daily_limit(_settings(rate_limits_per_day={"CASE": 25}), "CASE", e) == 25
    assert daily_limit(_settings(rate_limits_per_day={"CASE": 0}), "CASE", e) is None
    assert daily_limit(_settings(rate_limits_per_day={"CASE": 5}), "CASE", e) == 5
    assert daily_limit(_settings(), "CASE", e) is None
    assert not [x for x in daily_limits.refused_lifts({"TB_ENV": env}, _settings(rate_limits_per_day={"CASE": 25}))
                if "CASE" in x]  # fmt: skip


@pytest.mark.parametrize("raw", ["abc", "1e3", "1,000", "5.0"])
def test_a_malformed_variable_is_ignored_and_said(raw: str) -> None:
    """The review of D-775 (3): the site's value and the defaults hold, and doctor FAILs naming it, on any box."""
    for env in ("PRODUCTION", "VALIDATION"):
        e = {"TB_ENV": env, "TB_JOBS_PER_SENDER_PER_DAY": raw, "TB_MAIL_PER_RECIPIENT_PER_DAY": raw}
        assert daily_limit(_settings(), "FEAS", e) == 20 and daily_limits.mail_per_recipient(e) == 200
        got = daily_limits.refused_lifts(e, _settings())
        assert {x.split(":")[0] for x in got if "whole number" in x} == {"TB_JOBS_PER_SENDER_PER_DAY",
                                                                          "TB_MAIL_PER_RECIPIENT_PER_DAY"}  # fmt: skip


@pytest.mark.parametrize(("raw", "lifts"), [(" validation ", True), ("test", True), ("  ", False), ("staging", False)])
def test_tb_env_is_read_by_the_one_rule(raw: str, lifts: bool) -> None:
    assert daily_limits.may_lift({"TB_ENV": raw}) is lifts
