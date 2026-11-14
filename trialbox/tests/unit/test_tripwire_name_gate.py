"""The standing gate of the tripwire's name patterns (NEW-LLM-3/4, D-647; the owner's choice "C").

The tripwire refuses a text in which a Chinese or Japanese name pattern matches. It refuses much ordinary Japanese
text too. Two attempts to take such findings away with a tokeniser were measured on easy sets and passed, and
each review then found shapes of real names that were let through. The owner's decision for go-live: the tripwire
stays as it is, and this file is what any later attempt must pass.

* the synthetic names of ``tests/guard_sets.py`` in every shape, with a ceiling **per shape** on how many the
  tripwire lets through. Every ceiling is 0. Raising one is the owner's decision;
* what the tripwire costs today, so that it is seen when it changes: how much ordinary text it refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from guard.guard import Guard

from tests import guard_sets

SETS = Path(__file__).resolve().parents[1] / "fixtures" / "guard"


def _rows(name: str) -> list[str]:
    return [x for x in (SETS / f"{name}.txt").read_text(encoding="utf-8").splitlines() if x]


def _refused(rows: list[str]) -> int:
    g = Guard(r"^\d{8}$")
    return sum(1 for x in rows if g.tripwire(x).hit)


def test_every_sentence_with_a_name_is_refused_and_what_ordinary_text_costs_is_as_measured() -> None:
    names_ja, names_zh = _rows("names_ja"), _rows("names_zh")
    assert _refused(names_ja) == len(names_ja) == 83
    assert _refused(names_zh) == len(names_zh) == 191
    # the cost, measured for D-647: ordinary clinical sentences without any name that the tripwire refuses.
    # A change that lowers these must keep every ceiling below at 0
    ordinary_ja, ordinary_zh = _rows("ordinary_ja"), _rows("ordinary_zh")
    assert (len(ordinary_ja), _refused(ordinary_ja)) == (132, 96)  # Japanese: 72.7 %
    assert (len(ordinary_zh), _refused(ordinary_zh)) == (84, 84)  # Chinese: the set holds only refused sentences


def _let_through(template: str, some_names: list[str]) -> tuple[int, int]:
    """(names the patterns find, names the tripwire then lets through) for one shape."""
    g = Guard(r"^\d{8}$")
    found = lost = 0
    for n in some_names:
        text = template.format(n=n)
        if any(f.kind == "NAME" for f in g.detect(text)):
            found += 1
            lost += not g.tripwire(text).hit
    return found, lost


_ZH = list(guard_sets.zh_names())
_ZH_ONE = list(guard_sets.zh_names(guard_sets.ZH_GIVEN_ONE))
_JA = list(guard_sets.ja_names())
_JA_UNLISTED = [s + x for s in "森林" for x in guard_sets.JA_GIVEN_UNLISTED]
_JA_KANA_GIVEN = [s + x for s in "森林" for x in guard_sets.JA_GIVEN_KANA]
# (what, shapes, names): the shapes the three reviews of D-647 found names let through in
SHAPES: list[tuple[str, dict[str, str], list[str]]] = [
    ("Chinese, a cue or a boundary", guard_sets.ZH_CUED, _ZH),
    ("Chinese, run into text", guard_sets.ZH_RUNNING, _ZH),
    ("Chinese, run into text, one-character given name", guard_sets.ZH_RUNNING, _ZH_ONE),
    ("Chinese, kana on the line, cue or boundary", guard_sets.ZH_WITH_KANA, _ZH),
    ("Chinese, run into text on a line with kana", guard_sets.ZH_RUNNING_WITH_KANA, _ZH),
    ("Chinese, the middle dot and the long vowel mark", guard_sets.ZH_DOTS, _ZH),
    ("Chinese, a subject line of a protocol", guard_sets.ZH_SUBJECT, _ZH),
    ("Chinese, one-character given name, cue or boundary on a line with kana", guard_sets.ZH_WITH_KANA, _ZH_ONE),
    # option B let 12 of 1,380 through here: a two-character name that is a Japanese dictionary word (白雪, 黎明)
    ("Chinese, one-character given name, no cue, on a line with kana", guard_sets.ZH_ONE_WITH_KANA, _ZH_ONE),
    ("Japanese, no kana on the line", guard_sets.JA_NO_KANA, _JA),
    ("Japanese, kana on the line", guard_sets.JA_KANA, _JA),
    ("Japanese, after a label, before a particle", guard_sets.JA_PARTICLE, _JA),
    ("Japanese, 森 and 林 with given names the dictionary does not hold", guard_sets.JA_PARTICLE, _JA_UNLISTED),
    ("Japanese, 森 and 林 with given names in kana", guard_sets.JA_PARTICLE, _JA_KANA_GIVEN),
]
CEILING = 0  # per shape; the owner's decision to raise


@pytest.mark.parametrize(("what", "shapes", "some_names"), SHAPES, ids=[c[0] for c in SHAPES])
def test_no_shape_lets_a_name_the_patterns_find_through(
    what: str, shapes: dict[str, str], some_names: list[str]
) -> None:
    for shape, template in shapes.items():
        found, lost = _let_through(template, some_names)
        assert found > 0, (what, shape)
        assert lost <= CEILING, (what, shape, lost, found)


def test_the_names_that_were_let_through_by_the_attempt_not_taken_are_refused() -> None:
    g = Guard()
    for name in ("白雪", "黎明", "王軍"):
        assert g.tripwire(f"患者{name}は発熱のため受診した。").hit, name
