"""NEW-LIFE-8 (D-766, the deep review's LIFE-008): the SAE clock by the event's class, and none until confirmed.

Three rule sets showed a wrong or noisy regulator clock:

* (a) in a 医師主導治験 (``jp_gcp_ii``) a known (expected) death or life-threatening reaction still has a 15-day PMDA
  report; the box showed none;
* (b) in a sponsor's trial at a Taiwan site the TFDA report is the sponsor's: ``tw_trial`` showed the site a TFDA
  clock that went overdue for ever; ``tw_trial_sponsor`` has none;
* (c) ``ae_related`` was never read: an unrelated SAE ran the regulator clock (a regulator report is for a suspected
  reaction; "unknown" counts as suspected).

And the clock is off until the study's rule set is chosen: a country default gives no deadline and an alert
(``unconfirmed``), never a clock nobody confirmed. Synthetic data only."""

from __future__ import annotations

from datetime import date

from datacore import lifecycle as lc

TODAY = date(2026, 11, 20)
BASE = {"ae_onset": "2026-11-09", "ae_aware": "2026-11-09", "ae_serious": "1"}
FATAL = {**BASE, "ae_outcome": "5", "ae_serious_why": "1"}


def _parties(rule_set: str, e: dict[str, str]) -> dict[str, int]:
    rules = lc.clock_rules(rule_set, "Asia/Tokyo" if rule_set.startswith("jp") else "Asia/Taipei")
    return {r["party"]: r["days"] for r in lc.report_clock(e, TODAY, rules["parties"])}


def test_an_expected_death_in_an_investigator_initiated_trial_has_its_15_day_pmda_report() -> None:
    got = _parties("jp_gcp_ii", {**FATAL, "ae_expected": "1", "ae_related": "1"})
    assert got.get("regulator") == 15
    assert _parties("jp_gcp_ii", {**FATAL, "ae_expected": "0", "ae_related": "1"}).get("regulator") == 7


def test_a_sponsor_trial_in_taiwan_has_no_site_regulator_clock() -> None:
    assert "tw_trial_sponsor" in lc.RULE_SETS
    got = _parties("tw_trial_sponsor", {**FATAL, "ae_expected": "0", "ae_related": "1"})
    assert "regulator" not in got and got["sponsor"] == lc.HOUR_RULE


def test_an_unrelated_sae_runs_no_regulator_clock_and_unknown_counts_as_suspected() -> None:
    e = {**FATAL, "ae_expected": "0"}
    assert "regulator" not in _parties("tw_trial", {**e, "ae_related": "0"})
    assert _parties("tw_trial", {**e, "ae_related": "9"}).get("regulator") == 7
    assert _parties("tw_trial", {**e, "ae_related": "1"}).get("regulator") == 7
    assert _parties("tw_trial", {**e, "ae_related": "0"}).get("sponsor") == lc.HOUR_RULE  # the sponsor is told all


def test_no_deadline_until_the_studys_rule_set_is_chosen() -> None:
    rules = lc.clock_rules("", "Asia/Taipei")
    assert rules["parties"] == {} and "unconfirmed" in rules["problems"] and "unconfirmed" in lc.RULE_ALERTS
    assert lc.report_clock(FATAL, TODAY, rules["parties"]) == []
    chosen = lc.clock_rules("tw_trial", "Asia/Taipei")
    assert chosen["parties"] and "unconfirmed" not in chosen["problems"]


# ---------------------------------------------------------------------------------------------- the review's cases
def test_the_sponsors_causality_makes_it_a_suspected_reaction() -> None:
    """The review of D-766 (1): ICH E2A: either the investigator's or the sponsor's judgment."""
    e = {**FATAL, "ae_expected": "0", "ae_related": "0"}
    assert _parties("jp_gcp_ii", {**e, "ae_sponsor_related": "1"}).get("regulator") == 7
    assert "regulator" not in _parties("jp_gcp_ii", {**e, "ae_sponsor_related": "0"})


def test_a_box_wide_set_runs_no_clock_and_names_the_regulator() -> None:
    """The review of D-766 (3): only the study's own set runs a clock (a box set put TFDA on every sponsor trial)."""
    rules = lc.clock_rules("", "Asia/Taipei", "", "tw")
    assert rules["parties"] == {} and "unconfirmed" in rules["problems"] and rules["regulator"] == "TFDA"


def test_an_override_off_turns_the_expected_row_off_and_a_bad_one_is_said_before_a_set() -> None:
    """The review of D-766 (5, 7)."""
    rules = lc.clock_rules("jp_gcp_ii", "Asia/Tokyo", "regulator=0")
    assert lc.EXPECTED_REGULATOR not in rules["parties"]
    assert "regulator" not in {r["party"] for r in lc.report_clock({**FATAL, "ae_expected": "1"}, TODAY,
                                                                   rules["parties"])}  # fmt: skip
    assert "bad_override" in lc.clock_rules("", "Asia/Taipei", "irb=x")["problems"]


def test_an_expected_pmda_row_has_no_made_up_follow_up_and_no_contradicting_flag() -> None:
    """The review of D-766 (4, 6): the 7 + 8 follow-up is for an unexpected reaction; ``expected_noreg`` says no
    regulator report, which is untrue when the set keeps one."""
    from console import saerecord as sr

    rules = lc.clock_rules("jp_gcp_ii", "Asia/Tokyo")
    ae = {**FATAL, "ae_expected": "1", "ae_related": "1", "record": "GZQO-0001", "event": "ae1"}
    ae["clock"] = lc.report_clock(ae, TODAY, rules["parties"])
    fu = sr.rule_followups(ae, TODAY, sr.followup_rules(""), {})
    assert not [f for f in fu if f["party"] == "regulator"]
    v = sr.case_view(ae, None, [], TODAY, sr.followup_rules(""), None, rules)
    assert "expected_noreg" not in v["flags"]
