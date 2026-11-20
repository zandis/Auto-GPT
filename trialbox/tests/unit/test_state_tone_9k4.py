"""9k-4 (D-1380; review 09 DS-4): one state badge, fed by one table of tones.

Read from the tree, no database (a guard):

* every state the code can produce has a tone in ``console.state_tone`` (the person's states of J-2, the life-cycle
  steps, the referral states, and every key of the page catalogue that names a state, a tier, a reading, a verdict, a
  mark or a job state), and a tone is one of the five;
* **no old class is found**: none of the 60 state classes (``ps-``, ``stt-``, ``mk-``, ``ref-``, ``tier-``, ``rd-``,
  ``vd-``, ``v-``, ``pc-``, ``life-``, ``s-``, ``st-``) paints a badge in the style sheet, a template or a Python
  module, and the class ``state`` is gone;
* every ``tone(...)`` in a template names a family of the table, every literal ``data-tone`` is one of the five, and
  the style sheet paints each of the five.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"
for p in (ROOT / "services", ROOT / "libs"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from console import i18n, lifecycle_pages, person_state, teamstore  # noqa: E402
from console.state_tone import STATE_TONES, TONES, tone  # noqa: E402

CSS = (CONSOLE / "static" / "console.css").read_text(encoding="utf-8")
TEMPLATES = {p.name: p.read_text(encoding="utf-8") for p in sorted((CONSOLE / "templates").glob("*.html"))}
OLD_FAMILIES = ("ps", "stt", "mk", "ref", "tier", "rd", "vd", "v", "pc", "life", "s", "st")


def _keys(prefix: str) -> set[str]:
    return {
        k[len(prefix) :] for k in i18n.CATALOGUES["en"] if k.startswith(prefix) and k.count(".") == prefix.count(".")
    }


def test_every_tone_is_one_of_the_five() -> None:
    assert TONES == ("ok", "warn", "bad", "info", "neutral")
    for family, states in STATE_TONES.items():
        for state, t in states.items():
            assert t in TONES, (family, state, t)
    assert tone("person", "no-such-state") == "neutral" and tone("no-such-family", "x") == "neutral"


def test_every_state_has_one_tone() -> None:
    need = {
        "person": set(person_state.STATES) | {"unknown"},
        "life": set(lifecycle_pages.STATES),
        "referral": set(teamstore.STATES),
        "tier": {"high", "review", "excluded"},
        "reading": {"go", "conditional", "nogo"},
        "verdict": {"pass", "fail", "unknown", "pending_human"},
        "mark": {"approach", "need_info", "not_suitable", "not_now"},
        "site_patient": _keys("site.pc."),
        "job": _keys("state."),
        "visit": _keys("life.vstate."),
    }
    for family, states in need.items():
        assert states, family
        missing = sorted(states - set(STATE_TONES[family]))
        assert not missing, (family, missing)
    assert set(STATE_TONES) >= set(need)


def test_the_person_states_keep_the_tones_of_the_old_classes() -> None:
    """The colours the 60 classes gave, value for value (D-1380): a green state stays green."""
    assert {s for s, t in STATE_TONES["person"].items() if t == "ok"} == {
        "consented",
        "enrolled",
        "on_study",
        "completed",
    }
    assert {s for s, t in STATE_TONES["person"].items() if t == "warn"} == {"need_info", "to_contact", "contacted"}
    assert {s for s, t in STATE_TONES["person"].items() if t == "bad"} == {
        "set_aside",
        "not_approached",
        "declined",
        "screen_fail",
        "withdrawn",
    }


def test_no_old_state_class_is_found() -> None:
    fam = "|".join(OLD_FAMILIES)
    rule = re.compile(r"\.pill\.(?:" + fam + r")-|^\s*\.s-|\.st-|\.stt-|\.state\b", re.M)
    assert not rule.findall(CSS), rule.findall(CSS)
    old = re.compile(r"""class="[^"]*\b(?:pill|state)\b[^"]*\b(?:""" + fam + r")-[a-z{]")
    flat = re.compile(r"""class="state\b|class="[^"{]* state\b""")
    for name, text in TEMPLATES.items():
        assert not old.findall(text), name
        assert not flat.findall(text), name
        assert not re.search(r"""\bst-\{\{|\bstt-""", text), name
    for py in sorted(CONSOLE.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        assert not re.search(r"""["'](?:pill|state) (?:""" + fam + r")-", text), py.name


def test_templates_name_a_family_and_a_tone_of_the_table() -> None:
    seen = 0
    for name, text in TEMPLATES.items():
        for m in re.finditer(r"""tone\('([a-z_]+)',""", text):
            seen += 1
            assert m.group(1) in STATE_TONES, (name, m.group(1))
        for m in re.finditer(r"""data-tone="([a-z]+)\"""", text):
            assert m.group(1) in TONES, (name, m.group(1))
    assert seen >= 25


def test_the_style_sheet_paints_each_of_the_five() -> None:
    for t in TONES:
        assert re.search(r'\.pill\[data-tone="' + t + r'"\]\s*\{[^}]*background', CSS), t
