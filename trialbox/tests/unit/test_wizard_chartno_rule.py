"""NEW-DIN-3, the installer's half (D-579; DIN-003): the settings wizard asks the site's chart-number format once
and writes ``TB_CHARTNO_RULE`` to ``deploy/.env``. Before, nothing set it: every box ran on ``asis``, where a chart
number that lost its leading zeros in a sheet is a second patient."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import chartno

from tools import settings_wizard

ROOT = Path(__file__).resolve().parents[2]
REHEARSAL = ROOT / "tools" / "rehearse_box"

pytestmark = pytest.mark.nodb


def _answers(**over: Any) -> dict[str, Any]:
    a: dict[str, Any] = yaml.safe_load((REHEARSAL / "site_answers.yaml").read_text(encoding="utf-8"))
    a.pop("chartno_rule", None)
    a.update({"llm_mode": "stub", **over})
    return {k: v for k, v in a.items() if v is not None}


def _build(**over: Any) -> tuple[dict[str, str], list[str]]:
    _settings, env, warnings = settings_wizard.build(_answers(**over), [REHEARSAL / "mapping"])
    return env, warnings


def test_the_wizard_has_the_question_after_the_mrn_pattern() -> None:
    keys = [q[0] for q in settings_wizard.QUESTIONS]
    assert keys.index("chartno_rule") == keys.index("mrn_regex") + 1


@pytest.mark.parametrize("rule", ["asis", "digits", "digits:8", "hex:8", "hex:8:lower"])
def test_an_answered_rule_is_written_as_the_normaliser_reads_it(rule: str) -> None:
    regex = r"^\d{8}$" if rule.startswith("digits") or rule == "asis" else r"^[0-9A-Fa-f]{8}$"
    env, _ = _build(chartno_rule=rule, mrn_regex=regex)
    assert env["TB_CHARTNO_RULE"] == rule
    assert str(chartno.parse_rule(env["TB_CHARTNO_RULE"])) == rule


def test_the_written_rule_joins_the_spelling_a_sheet_made() -> None:
    """The point of the card: with the rule in .env, ``123456`` and ``00123456`` are one chart number."""
    env, _ = _build(chartno_rule="digits:8", mrn_regex=r"^\d{8}$")
    rule = env["TB_CHARTNO_RULE"]
    assert chartno.normalise(rule, "123456") == chartno.normalise(rule, "00123456") == "00123456"


@pytest.mark.parametrize(
    ("rule", "needle"),
    [
        ("digit", "chartno_rule"),  # not a rule
        ("digits:0", "chartno_rule"),
        ("asis:8", "chartno_rule"),
        ("digits:8\nTB_ENV=DEV", "chartno_rule"),  # a line break never reaches .env
    ],
)
def test_a_rule_the_normaliser_cannot_read_is_refused(rule: str, needle: str) -> None:
    with pytest.raises(settings_wizard.WizardError, match=needle):
        _build(chartno_rule=rule)


@pytest.mark.parametrize(
    ("rule", "regex"),
    [
        ("digits:10", r"^\d{8}$"),  # the pattern says eight digits, the rule pads to ten: every number would be refused
        ("digits:6", r"^\d{8}$"),
        ("hex:8", r"^\d{8}$"),  # a hex rule on an all-digit pattern
        ("digits:8", r"^C\d{7}$"),  # a digit rule on a pattern with a letter: it would never apply
    ],
)
def test_a_rule_that_contradicts_the_mrn_pattern_is_refused(rule: str, regex: str) -> None:
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule .* mrn_regex"):
        _build(chartno_rule=rule, mrn_regex=regex)


def test_no_answer_and_an_answered_pattern_of_fixed_digits_gives_the_rule() -> None:
    for regex, want in ((r"^\d{8}$", "digits:8"), (r"^[0-9]{10}$", "digits:10"), (r"\d{7}", "digits:7")):
        env, warnings = _build(mrn_regex=regex)
        assert env["TB_CHARTNO_RULE"] == want, regex
        assert any("chartno_rule" in w and want in w for w in warnings), warnings  # said, not silent


def test_no_answer_and_any_other_pattern_stays_asis_and_says_so() -> None:
    for regex in (r"^C\d{7}$", r"^\d{6,8}$", r"^\d+$"):
        env, warnings = _build(mrn_regex=regex)
        assert env["TB_CHARTNO_RULE"] == "asis", regex
        assert any("chartno_rule" in w and "leading zeros" in w for w in warnings), warnings


def test_a_pattern_nobody_answered_is_never_read_as_the_hospitals_format() -> None:
    """The wizard's own default pattern is a placeholder: no rule is guessed from it."""
    a = _answers()
    a.pop("mrn_regex")
    _settings, env, warnings = settings_wizard.build(a, [REHEARSAL / "mapping"])
    assert env["TB_CHARTNO_RULE"] == "asis"
    assert any("chartno_rule" in w for w in warnings)


def test_the_rule_reaches_every_service_through_the_env_file() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    anchor = next(v for k, v in compose.items() if k.startswith("x-") and isinstance(v, dict) and "env_file" in v)
    assert anchor["env_file"] == [".env"]
    from tb_common.config import DECLARED

    assert "installation" in DECLARED["TB_CHARTNO_RULE"].doc or "wizard" in DECLARED["TB_CHARTNO_RULE"].doc


def test_the_box_plan_passes_the_owners_answer_when_the_first_run_page_has_one() -> None:
    text = (ROOT / "tools" / "box" / "plan.py").read_text(encoding="utf-8")
    assert '"chartno_rule": getattr(a, "chartno_rule", "")' in text


def test_the_install_runbook_names_the_question() -> None:
    page = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8")
    assert "chartno_rule" in page and "TB_CHARTNO_RULE" in page
