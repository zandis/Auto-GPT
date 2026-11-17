"""D-987 (the integrator's side finding on D-983, #639): FEAS in the product counts in SQL and builds no cascade; the
cascade's feasibility runs are the measurement tools (``scale_gate``, ``cascade_e2e``, ``vec_parity``), which never
set the cascade's language and so read every note against the engine's default, zh-TW, whatever the notes were. Each
tool now takes ``--language`` (auto by default: read per patient, the tool's data's own locale the fallback), and no
``CascadeConfig(...)`` outside the tests may leave its language to the default."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from matching.notelang import LANGS, cascade_languages

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("services", "libs", "tools", "eval")


def _calls(text: str) -> list[tuple[int, str]]:
    """Every ``CascadeConfig(...)`` call in ``text`` (also inside a child script held in a string), with its line."""
    out = []
    for m in re.finditer(r"(?<![\w.])CascadeConfig\(", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        out.append((text.count("\n", 0, m.start()) + 1, text[m.end() : i - 1]))
    return out


def test_no_cascade_outside_the_tests_leaves_its_language_to_the_default() -> None:
    bad = []
    for d in SCANNED:
        for f in sorted((ROOT / d).rglob("*.py")):
            if ".venv" in f.parts or "__pycache__" in f.parts:
                continue
            for line, args in _calls(f.read_text(encoding="utf-8")):
                if not re.search(r"(?<![\w.])language\s*=", args):
                    bad.append(f"{f.relative_to(ROOT)}:{line}")
    assert not bad, "pass language= (the notes' fallback language) to every CascadeConfig (D-987):\n  " + "\n  ".join(
        bad
    )


def test_the_guard_sees_a_call_in_a_child_script_and_one_without_language() -> None:
    src = 'CHILD = r"""\ncfg = CascadeConfig(study_id=t, run_date=d)\n"""\nok = CascadeConfig(study_id=t, language="en")\n'
    calls = _calls(src)
    assert [line for line, _ in calls] == [2, 4]
    assert [bool(re.search(r"(?<![\w.])language\s*=", a)) for _, a in calls] == [False, True]


def test_auto_reads_the_notes_with_the_datas_own_locale_as_the_fallback() -> None:
    assert cascade_languages("auto", "zh-TW") == ("zh-TW", "auto")


@pytest.mark.parametrize("lang", LANGS)
def test_a_named_language_is_the_notes_and_the_fallbacks(lang: str) -> None:
    assert cascade_languages(lang, "zh-TW") == (lang, lang)


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="auto or one of"):
        cascade_languages("fr", "zh-TW")
