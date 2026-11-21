"""9k-10 (D-1385; review 09 DS-10): the phase strip.

Read from the template and the style sheet, no database: ``templates/_steps.html`` holds ``phase_strip``. Each item
has one of four states (done, current, todo, off); the state is said in words for a screen reader, the current item
carries ``aria-current="step"``, the old ``.steps`` markup is gone, and the words exist in the three languages.
"""

from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest
from console.i18n import CATALOGUES
from console.state_tone import PHASE_STATES, STATE_TONES, tone

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "services" / "console" / "templates"
CSS = ROOT / "services" / "console" / "static" / "console.css"
STATES = ("done", "current", "todo", "off")
# what a screen reader must hear per state and language, written out here (not read from the catalogue the page reads)
WORDS = {
    "en": {"done": "done", "current": "current step", "todo": "not done yet", "off": "not used in this study"},
    "ja": {"done": "完了", "current": "現在の手順", "todo": "未完了", "off": "この試験では使いません"},
    "zh-TW": {"done": "已完成", "current": "目前步驟", "todo": "尚未完成", "off": "本試驗不使用"},
}


def _env(lang: str) -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True)
    cat = CATALOGUES[lang]
    env.globals["tone"] = tone
    env.globals["t"] = lambda key, **kw: cat[key].format(**kw) if kw else cat[key]
    return env


def _strip(lang: str, items: list[dict[str, str]]) -> str:
    src = '{% from "_steps.html" import phase_strip with context %}{{ phase_strip(items, "Procedure", "strip") }}'
    return _env(lang).from_string(src).render(items=items)


@pytest.mark.parametrize("lang", ("en", "ja", "zh-TW"))
def test_every_state_is_said_in_words_and_only_the_current_one_is_marked(lang: str) -> None:
    items = [{"name": f"P{i}", "who": "", "state": s} for i, s in enumerate(STATES)]
    out = _strip(lang, items)
    cat = CATALOGUES[lang]
    assert out.count("<li ") == 4 and out.count('aria-current="step"') == 1
    for s in STATES:
        assert cat["ps." + s] == WORDS[lang][s]
        assert re.search(
            rf'<li data-state="{s}"[^>]*><b>\d&nbsp;· P\d<span class="sr"> \({WORDS[lang][s]}\)</span>', out
        ), s
        assert f'<li data-state="{s}" data-tone="{tone("phase", s)}"' in out
    assert re.search(r'<li data-state="current" data-tone="info" aria-current="step"><b>2&nbsp;· P1', out)
    assert len({cat["ps." + s] for s in STATES}) == 4  # four different words


def test_markup_is_one_ordered_list_with_a_label_and_a_test_id() -> None:
    out = _strip("en", [{"name": "A", "who": "coordinator", "state": "todo"}])
    assert out.count("<ol ") == 1 and '<ol class="ps" aria-label="Procedure" data-testid="strip">' in out
    assert '<span class="who">coordinator</span>' in out
    assert '<span class="who">' not in _strip("en", [{"name": "A", "who": "", "state": "todo"}])


def test_the_six_step_call_maps_the_step_to_done_current_todo() -> None:
    src = '{% from "_steps.html" import steps_bar with context %}{{ steps_bar(steps, 2) }}'
    out = (
        _env("en")
        .from_string(src)
        .render(steps=["protocol", "criteria", "feasibility", "weekly", "contact", "enrolled"])
    )
    assert re.findall(r'data-state="(\w+)"', out) == ["done", "done", "current", "todo", "todo", "todo"]
    assert 'data-testid="steps"' in out


def test_no_template_or_rule_uses_the_old_steps_strip() -> None:
    for page in TEMPLATES.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert not re.search(r'<ol class="steps"[ >]', text), page.name
    css = CSS.read_text(encoding="utf-8")
    assert not re.search(r"(^|[\s,}])\.steps\b(?!-)", css, re.M)
    assert '.ps li[data-state="current"]' in css and "@media (max-width: 760px) { .ps {" in css


def test_the_states_of_the_macro_are_the_states_of_the_table_and_have_words() -> None:
    assert PHASE_STATES == STATES and set(STATE_TONES["phase"]) == set(STATES)
    used: set[str] = set()
    for name in ("_steps.html", "site_wizard.html"):
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for m in re.finditer(r"'state': ([^}]*)\}", text):
            used |= set(re.findall(r"'(\w+)'", m.group(1)))
    assert used and used <= set(PHASE_STATES), used
    for lang in CATALOGUES:
        if lang in WORDS:
            assert all(f"ps.{s}" in CATALOGUES[lang] for s in PHASE_STATES)


def test_the_wizard_strip_has_its_own_name_not_the_study_procedure() -> None:
    text = (TEMPLATES / "site_wizard.html").read_text(encoding="utf-8")
    assert "phase_strip(ns.l, t('site.start.title'), 'wizard-steps')" in text
    for lang in WORDS:
        assert CATALOGUES[lang]["site.start.title"] != CATALOGUES[lang]["steps.label"]


def test_the_style_marks_the_current_and_the_done_item_differently_and_never_cuts_a_label() -> None:
    css = CSS.read_text(encoding="utf-8").split("9k-10 (D-1385)")[1]
    assert re.search(r'li\[data-state="done"\] b::before \{[^}]*content: "✓ " / ""', css)  # the tick is not read aloud
    assert re.search(r'li\[data-state="current"\] \{[^}]*inset 0 -3px 0 var\(--accent\)', css)
    assert "forced-colors: active" in css and "Highlight" in css
    assert "overflow-wrap: anywhere" in css and "text-overflow" not in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css  # two columns on a phone
