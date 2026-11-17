"""Card V-5: the planted-identifier harness (``tools.masking_leaks``) on a small fixed sample, one case per entry
point, language and kind (each form of the kind once at each place but a line break), plus one case per entry point
and language for a line break inside the value, and the check that the page's tables equal ``leaks.json``.

A case leaks when a planted value survives the real entry point (the module's leak rule). A leaking case is
``xfail(strict=True, raises=AssertionError)`` with its finding of
``docs/plan/measurements/masking-leaks-2026-11-17.md``: it turns red the day the masker covers the kind, and a
harness error (``PlantError``, a ``RuntimeError``) is never taken for the expected failure.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools import masking_leaks as ml

pytestmark = pytest.mark.nodb

# forms planted and reported but not held here: a bare 7-digit or letter-and-7-digit number with no label is a chart
# number only at a site whose chart pattern says so (the site pattern of deploy/settings.example.yaml is 8 digits)
NOT_HELD = {"bare_7", "letter_7"}
KINDS = ("name", "national_id", "chart", "phone", "address", "email", "dob")
XFAIL = {
    ("mask", "ja", "name"): "V5-01: Japanese names leak, after 氏名 too (kana, Hepburn, 殿, unlisted surnames)",
    ("mask", "en", "name"): "V5-02: English names leak (LAST, First; initials; Pinyin; First Last outside a title)",
    ("mask", "zh-TW", "name"): "V5-03: Chinese names leak (Pinyin after 姓名, unlisted surnames, no cue)",
    ("mask", "ja", "national_id"): "V5-04: the insurance card's 記号・番号 leaks after its label",
    ("mask", "en", "national_id"): "V5-09: an unlabelled US SSN is not masked",
    ("mask", "zh-TW", "email"): "V5-05: an e-mail with a full-width ＠ is not masked",
    ("mask", "ja", "email"): "V5-05: an e-mail with a full-width ＠ is not masked",
    ("mask", "en", "email"): "V5-05: an e-mail with a full-width ＠ is not masked",
    ("mask", "zh-TW", "phone"): "V5-06: unlabelled Taiwan landlines and full-width mobiles are not masked",
    ("mask", "ja", "phone"): "V5-06: an unlabelled full-width Japanese mobile is not masked",
    ("mask", "en", "phone"): "V5-06: unlabelled Taiwan landlines are not masked",
    ("mask", "zh-TW", "dob"): "V5-08: a compact ROC birth date before 出生 is not masked",
    ("mask", "en", "address"): "V5-12: an English address whose house number reads as a year is not masked",
}
# the cases the gateway tripwire (services/guard) passes on this sample; every other tripwire case leaks
TRIPWIRE_CLEAN = {
    ("zh-TW", "address"),
    ("zh-TW", "chart"),
    ("zh-TW", "national_id"),
    ("ja", "address"),
    ("ja", "chart"),
    ("ja", "dob"),
    ("en", "chart"),
    ("en", "dob"),
}
for _lang in ml.LANGS:
    XFAIL[("mask", _lang, "line_break")] = "V5-07: a line break inside a value defeats every recogniser"
    for _kind in (*KINDS, "line_break"):
        if (_lang, _kind) not in TRIPWIRE_CLEAN:
            XFAIL[("tripwire", _lang, _kind)] = "V5-10: the gateway tripwire misses what the masker misses"


@pytest.fixture(scope="module")
def eng() -> ml.Engines:
    return ml.engines()


def _cases() -> list[Any]:
    out = []
    for entry in ("mask", "tripwire"):
        for lang in ml.LANGS:
            kinds = sorted({k for k, _f, _g in ml.forms(lang)})
            for kind in (*kinds, "line_break"):
                reason = XFAIL.get((entry, lang, kind))
                marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)] if reason else []
                out.append(pytest.param(entry, lang, kind, marks=marks, id=f"{entry}-{lang}-{kind}"))
    return out


def _leaks(eng: ml.Engines, entry: str, lang: str, kind: str) -> tuple[int, list[str]]:
    n, bad = 0, []
    for k, form, pos, text, start, it in ml.cases(lang, len(ml.POSITIONS)):
        if form in NOT_HELD or (pos == "line_break") != (kind == "line_break"):
            continue
        if kind != "line_break" and k != kind:
            continue
        n += 1
        if entry == "mask":
            leaked = ml.judge(text, eng.mask(text), start, it, eng.mask_char) == "leaked"
        else:
            if it.surface[it.v[0] : it.v[1]] not in text:
                raise ml.PlantError("the value is not in the input")
            leaked = not eng.tripwire(text)
        if leaked:
            bad.append(f"{k}/{form}/{pos}")
    return n, bad


@pytest.mark.parametrize(("entry", "lang", "kind"), _cases())
def test_no_planted_identifier_survives(eng: ml.Engines, entry: str, lang: str, kind: str) -> None:
    n, bad = _leaks(eng, entry, lang, kind)
    if n == 0:
        raise ml.PlantError("no note was planted for this case")
    assert not bad, f"{len(bad)} of {n} planted values leaked: {bad[:6]}"


def test_unplanted_notes_give_no_mask_and_no_hit(eng: ml.Engines) -> None:
    """The control: the base notes alone hold nothing the masker or the tripwire takes for an identifier, so a
    clean case is clean because the planted value was masked."""
    data = ml.run(eng, per=len(ml.POSITIONS), langs=("zh-TW",))
    assert data["control_unplanted"]["zh-TW"] == {"notes": 200, "masked_chars": 0, "tripwire_hits": 0}


def test_compact_clinical_dates_are_kept(eng: ml.Engines) -> None:
    """An 8-digit clinical date (a date of diagnosis written 20240503) is not an identifier (D-745: a date with no
    birth label stays)."""
    text = "病人於20240503確診第二型糖尿病，持續原處方藥物。"
    assert eng.mask(text) == text


test_compact_clinical_dates_are_kept = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="V5-11: the site chart pattern masks 8-digit clinical dates"
)(test_compact_clinical_dates_are_kept)


def test_page_tables_match_the_json() -> None:
    assert ml.check() == []
