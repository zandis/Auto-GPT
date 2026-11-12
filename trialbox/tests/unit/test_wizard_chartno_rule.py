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


@pytest.mark.parametrize("rule", ["asis", "digits:8", "hex:8", "hex:8:lower"])
def test_an_answered_rule_is_written_as_the_normaliser_reads_it(rule: str) -> None:
    regex = {"hex:8": r"^[0-9A-F]{8}$", "hex:8:lower": r"^[0-9a-f]{8}$"}.get(rule, r"^\d{8}$")
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
        # review M2: the pattern accepts other lengths too, so padding or stripping would make two numbers one
        ("digits:8", r"^\d{8,10}$"),  # 0012345678 and 12345678
        ("digits:8", r"^\d{6,8}$"),
        ("digits", r"^\d{6,8}$"),  # 00123456 and 123456
        ("digits", r"^\d{8}$"),  # the rule would write 123456, which the pattern refuses
        # review H2: the services read the pattern with re.match; without the end anchor it accepts 012345678
        ("digits:8", r"^\d{8}"),
        ("digits:8", r"\d{8}"),
    ],
)
def test_a_rule_that_contradicts_the_mrn_pattern_is_refused(rule: str, regex: str) -> None:
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule .* mrn_regex"):
        _build(chartno_rule=rule, mrn_regex=regex)


def test_a_rule_without_a_width_needs_a_pattern_with_no_leading_zero() -> None:
    env, _ = _build(chartno_rule="digits", mrn_regex=r"^[1-9]\d{0,9}$")
    assert env["TB_CHARTNO_RULE"] == "digits"


@pytest.mark.parametrize("regex", [r"^\d{8}$", r"^[0-9]{10}$", r"\d{7}", r"^C\d{7}$", r"^\d{6,8}$", r"^\d+$"])
def test_review_no_answer_is_never_turned_into_a_rule(regex: str) -> None:
    """Review H1 to H3: a rule read from the pattern could make two patients one (a pattern without its end anchor,
    a feed with a number wider than the pattern says, the wizard's own default taken for an answer). No answer is
    asis, the rule every box ran on, and a warning names the question."""
    env, warnings = _build(mrn_regex=regex)
    assert env["TB_CHARTNO_RULE"] == "asis", regex
    assert any("chartno_rule" in w and "leading zeros" in w for w in warnings), warnings


def test_review_h1_pressing_enter_at_every_question_gives_asis() -> None:
    answers = settings_wizard.ask({}, prompt=lambda _q: "")
    assert answers["mrn_regex"] and not answers["chartno_rule"]
    errors: list[str] = []
    warnings: list[str] = []
    assert settings_wizard.chartno_rule(answers["chartno_rule"], answers["mrn_regex"], errors, warnings) == "asis"
    assert errors == [] and len(warnings) == 1


def test_review_l1_a_width_that_is_not_an_ascii_number_is_refused_not_a_crash() -> None:
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule"):
        _build(chartno_rule="digits:\u00b2")


def _env(tmp_path: Path, text: str) -> Path:
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    return env


@pytest.mark.parametrize(
    ("present", "new", "rows", "ok"),
    [
        ("TB_CHARTNO_RULE=asis\n", "digits:8", 0, True),  # the first answer after the plan, before any patient
        ("TB_TZ=Asia/Taipei\n", "digits:8", 0, True),  # a box from before the setting, still empty
        ("TB_CHARTNO_RULE=digits:8\n", "hex:8", 0, True),  # a wrong first answer put right before the first night
        ("TB_CHARTNO_RULE=digits:8\n", "digits:8", None, True),  # no change: the database is not asked
        ("TB_TZ=Asia/Taipei\n", "asis", None, True),  # no rule and asis are the same rule
        ("TB_CHARTNO_RULE=asis\n", "digits:8", 3, False),  # patients are loaded: their pseudonyms would change
        ("TB_CHARTNO_RULE=digits:8\n", "asis", 3, False),
        ("TB_CHARTNO_RULE=asis\n", "digits:8", None, False),  # the database cannot be asked: not changed
    ],
)
def test_lane_e_review_the_box_changes_the_rule_only_while_the_pid_map_is_empty(
    tmp_path: Path, present: str, new: str, rows: int | None, ok: bool
) -> None:
    """From the review of the normaliser's fix (#389): a rule set on a box that has loaded patients changes their
    pseudonyms, and the pid map then reports a wrong site key. The box's apply asks the database first."""
    from tools.box.__main__ import chartno_change
    from tools.box.plan import PlanError

    asked: list[int] = []

    def count() -> int | None:
        asked.append(1)
        return rows

    env = _env(tmp_path, present)
    if ok:
        chartno_change(env, new, count)
        assert bool(asked) == (rows is not None)
    else:
        with pytest.raises(PlanError, match="TB_CHARTNO_RULE"):
            chartno_change(env, new, count)


def test_the_rows_are_asked_of_the_boxs_database_and_a_box_that_never_ingested_has_none(tmp_path: Path) -> None:
    from tools.box.__main__ import pid_map_rows

    calls: list[list[str]] = []

    def run(answers: list[str]) -> Any:
        def _run(argv: list[str]) -> str:
            calls.append(argv)
            return answers[len(calls) - 1]

        return _run

    assert pid_map_rows(tmp_path, run(["f\n"])) == 0  # no pid map table yet: no patients
    assert len(calls) == 1 and "to_regclass('pidmap.pid_map')" in calls[0][-1]
    assert calls[0][:2] == ["docker", "compose"] and "trialbox_wf" in calls[0]
    calls.clear()
    assert pid_map_rows(tmp_path, run(["t\n", "42\n"])) == 42
    calls.clear()

    def down(_argv: list[str]) -> str:
        raise OSError("no docker")

    assert pid_map_rows(tmp_path, down) is None


def test_the_wizard_does_not_write_another_rule_over_a_box_that_is_installed(tmp_path: Path) -> None:
    """The wizard writes the whole .env and cannot ask the database. A box that has an .env keeps its rule: the
    same rule is written again, another is refused. A fresh box (no .env) takes the answer."""
    settings, env, _ = settings_wizard.build(
        _answers(chartno_rule="digits:8", mrn_regex=r"^\d{8}$"), [REHEARSAL / "mapping"]
    )
    out = tmp_path / "settings.yaml"
    settings_wizard.write(settings, env, out, tmp_path / ".env")  # fresh
    assert "TB_CHARTNO_RULE=digits:8" in (tmp_path / ".env").read_text(encoding="utf-8")
    settings_wizard.write(settings, env, out, tmp_path / ".env")  # the same rule again
    for present in ("TB_CHARTNO_RULE=asis\n", "TB_TZ=Asia/Taipei\n", "TB_CHARTNO_RULE=hex:8\n"):
        (tmp_path / ".env").write_text(present, encoding="utf-8")
        with pytest.raises(settings_wizard.WizardError, match="TB_CHARTNO_RULE"):
            settings_wizard.write(settings, env, out, tmp_path / ".env")
        assert (tmp_path / ".env").read_text(encoding="utf-8") == present  # nothing was written


def test_the_rule_reaches_every_service_that_hashes_a_chart_number() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("adapter", "orchestrator", "console", "lake"):  # yaml merges the anchor into each service
        assert compose["services"][name]["env_file"] == [".env"], name
    from tb_common.config import DECLARED

    assert "installation" in DECLARED["TB_CHARTNO_RULE"].doc or "wizard" in DECLARED["TB_CHARTNO_RULE"].doc


def test_the_box_plan_passes_the_owners_answer_when_the_first_run_page_has_one() -> None:
    text = (ROOT / "tools" / "box" / "plan.py").read_text(encoding="utf-8")
    assert '"chartno_rule": getattr(a, "chartno_rule", "")' in text


def test_the_install_runbook_names_the_question() -> None:
    page = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8")
    assert "chartno_rule" in page and "TB_CHARTNO_RULE" in page
