"""The tripwire's second look at a NAME finding on a Japanese line (NEW-LLM-4, D-647; the owner's choice "B").

Only a finding on a line with kana can be taken away, and only when the tokeniser tags no proper noun in it, no
cue stands beside it, and one dictionary word covers it (or the match itself holds kana). Chinese text is judged
exactly as before the card.

**The standing gate of the tripwire** (the integrator's rule, after two reviews each found shapes an easy set did
not hold): the synthetic names of ``tests/guard_sets.py`` in every shape, with a ceiling **per shape** on how many
the tripwire lets through. Chinese shapes: 0, by construction. Japanese shapes: what was measured for D-647.
Raising a ceiling is the owner's decision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from guard import names
from guard.guard import Guard

from tests import guard_sets

SETS = Path(__file__).resolve().parents[1] / "fixtures" / "guard"
ROOT = Path(__file__).resolve().parents[2]


def _rows(name: str) -> list[str]:
    return [x for x in (SETS / f"{name}.txt").read_text(encoding="utf-8").splitlines() if x]


def _refused(rows: list[str]) -> int:
    g = Guard(r"^\d{8}$")
    return sum(1 for x in rows if g.tripwire(x).hit)


class _Fake:
    """A tokeniser stand-in. ``tagged``: substrings it calls proper nouns; ``words``: substrings that are one
    ordinary word of its dictionary; every other character is a token of its own, unknown. ``fail``: it cannot
    tell; ``absent``: it is not installed."""

    def __init__(
        self, tagged: tuple[str, ...] = (), fail: bool = False, absent: bool = False, words: tuple[str, ...] = ()
    ) -> None:
        self.tagged, self.words, self.fail, self.absent = tagged, words, fail, absent
        self.error, self.asked, self.failed = "", 0, False

    def load(self) -> bool:
        self.error = "ModuleNotFoundError: No module named 'sudachipy'" if self.absent else self.error
        return not self.absent

    def tokens(self, line: str) -> list[tuple[int, int, str]] | None:
        self.asked += 1
        if self.absent or self.fail:
            self.error, self.failed = self.error or "RuntimeError while tokenising a line", True
            return None
        out: list[tuple[int, int, str]] = []
        at = 0
        while at < len(line):
            hit = next(((t, "proper") for t in self.tagged if line.startswith(t, at)), None) or next(
                ((t, "word") for t in self.words if line.startswith(t, at)), None
            )
            n = len(hit[0]) if hit else 1
            out.append((at, at + n, hit[1] if hit else "unknown"))
            at += n
        return out


@pytest.fixture
def tagger(monkeypatch: pytest.MonkeyPatch) -> Any:
    def use(**kw: Any) -> _Fake:
        fake = _Fake(**kw)
        monkeypatch.setattr(names, "_TAGGER", fake)
        return fake

    return use


# ------------------------------------------------------------------------------------------------ the rule
def test_japanese_text_one_dictionary_word_covers_is_no_longer_refused(tagger: Any) -> None:
    fake = tagger(words=("高血圧", "連絡"))
    g = Guard()
    for text in ("患者 高血圧の既往あり、内服を継続している。", "患者連絡のうえ同意を取得した。"):
        assert g.detect(text) and not g.tripwire(text).hit, text  # the pattern still matches; the look takes it away
    assert fake.asked == 2


def test_everything_else_on_a_japanese_line_stands(tagger: Any) -> None:
    tagger(tagged=("山田",), words=("丁子", "血圧"))
    g = Guard()
    for text in (
        "患者 山田太郎は発熱のため受診した。",  # tagged a proper noun
        "患者 高橋恵は発熱のため受診した。",  # a surname of more than one character: a cue, whatever the tags
        "患者 林某さんに説明した。",  # an honorific after it
        "病人丁子涵今日回診，服用ロキソニン後改善",  # a Chinese name beside kana: 丁子 is a word, it does not cover the name
        "患者 高血圧症を合併している。",  # the tokeniser splits it (高血圧｜症 here): no one word covers the match
        "患者 林某乙が来院した。",  # nothing the dictionary knows, no kana in the match
    ):
        v = g.tripwire(text)
        assert v.hit and "NAME" in v.kinds, text


@pytest.mark.parametrize(
    "text",
    [
        "個案曾使用任何生物製劑。",  # ordinary Chinese that matches a name pattern: refused, as before this card
        "病人高血壓控制不良",
        "個案丁怡君由家屬陪同就診。",
        "病人王家豪今日回診",
        "山口一郎様来院",  # a Japanese name on a line without kana
    ],
)
def test_a_line_without_kana_is_judged_exactly_as_before(text: str, tagger: Any) -> None:
    fake = tagger(words=("高血壓", "曾使用", "王家豪", "山口一郎"))  # whatever a tokeniser would say: it is not asked
    g = Guard()
    assert g.tripwire(text).hit and g.detect(text) and fake.asked == 0


@pytest.mark.parametrize("how", [{"absent": True}, {"fail": True}])
def test_without_a_working_tokeniser_every_finding_stands(tagger: Any, how: dict[str, bool]) -> None:
    """Fail closed: as before this card. More ordinary text is refused; no name is let through."""
    tagger(**how)
    g = Guard()
    for text in ("患者 高血圧の既往あり、内服を継続している。", "患者 山田太郎さんに病状を説明した。"):
        assert g.tripwire(text).hit == bool(g.detect(text)) is True
    st = names.status()  # doctor's source: a tokeniser that is absent, or has failed on a text, is not "there"
    assert st["tokeniser"] is False and st["error"] and "none is let through" in st["effect"]
    assert "患者" not in st["error"]  # the reason never quotes the text


def test_a_line_too_long_for_the_tokeniser_is_not_asked_and_stands(tagger: Any) -> None:
    fake = tagger(words=("高血圧",))
    line = "患者 高血圧の既往あり。" + "あ" * names.MAX_LINE
    assert Guard().tripwire(line).hit and fake.asked == 0
    assert (
        not Guard().tripwire("患者 高血圧の既往あり。\n" + "あ" * names.MAX_LINE).hit
    )  # the long text is another line


def test_an_error_inside_the_second_look_leaves_the_finding_standing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any) -> bool:
        raise RuntimeError("anything")

    monkeypatch.setattr(names, "_cue", boom)
    monkeypatch.setattr(names, "_TAGGER", _Fake(words=("林学",)))
    assert Guard().tripwire("患者林学は発熱のため受診した。").hit


def test_only_a_japanese_name_finding_is_looked_at_again(tagger: Any) -> None:
    tagger(words=("高血圧",))
    g = Guard(r"^\d{8}$")
    for text, kind in (
        ("Mr. Chen was seen today. 発熱なし。", "NAME"),  # a name in Latin letters stands
        ("患者 高血圧の既往あり 0912-345-678", "PHONE"),
        ("患者 高血圧の既往あり A123456789", None),
        ("患者 高血圧の既往あり、カルテ番号 12345678", "MRN"),
    ):
        v = g.tripwire(text)
        assert v.hit and (kind is None or kind in v.kinds), text


def test_redaction_and_the_document_parsers_mask_keep_every_pattern_match(tagger: Any) -> None:
    """The trace store's redaction and the mask of a protocol's contact and subject lines do not take the look:
    masking too much costs readability only."""
    from doc_parser.parser import mask_contacts

    tagger(words=("高血圧",))
    g = Guard()
    line = "患者 高血圧の既往あり、内服を継続している。"
    assert not g.tripwire(line).hit and "[NAME]" in g.redact(line)
    masked, kinds = mask_contacts(line, g)
    assert "[NAME]" in masked and kinds
    assert g.tripwire(line, second_look=False).hit


def test_a_date_near_an_unconfirmed_name_is_no_date_of_birth_finding(tagger: Any) -> None:
    tagger(words=("高血圧",), tagged=("山田",))
    g = Guard()
    day = "2024年3月5日"
    assert not g.tripwire("患者 高血圧の既往あり、" + day + "に内服を開始した。").hit
    v = g.tripwire("山田太郎さんは" + day + "に来院した。")
    assert v.hit and "DOB_NEAR_NAME" in v.kinds


# ------------------------------------------------------------------------------------------------ measured figures
def test_the_first_sets_hold_the_measured_figures() -> None:
    g = Guard(r"^\d{8}$")
    ordinary_ja, names_ja = _rows("ordinary_ja"), _rows("names_ja")
    assert sum(1 for x in ordinary_ja if g.detect(x)) == 96  # before: 72.7 % of 132
    assert _refused(ordinary_ja) <= 29  # 22.0 %
    assert _refused(names_ja) >= 81  # 2 of 83 are let through: names that are dictionary words
    ordinary_zh, names_zh = _rows("ordinary_zh"), _rows("names_zh")
    assert _refused(ordinary_zh) == len(ordinary_zh) == 84  # Chinese: as before, every sentence refused
    assert _refused(names_zh) == len(names_zh) == 191
    assert names.status()["tokeniser"] and names.status()["effect"] == ""


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
# (what, shapes, names, ceiling per shape)
CEILINGS: list[tuple[str, dict[str, str], list[str], int]] = [
    ("Chinese, a cue or a boundary", guard_sets.ZH_CUED, _ZH, 0),
    ("Chinese, run into text", guard_sets.ZH_RUNNING, _ZH, 0),
    ("Chinese, run into text, one-character given name", guard_sets.ZH_RUNNING, _ZH_ONE, 0),
    ("Chinese, kana on the line, cue or boundary", guard_sets.ZH_WITH_KANA, _ZH, 0),
    ("Chinese, run into text on a line with kana", guard_sets.ZH_RUNNING_WITH_KANA, _ZH, 0),
    ("Chinese, the middle dot and the long vowel mark", guard_sets.ZH_DOTS, _ZH, 0),
    ("Chinese, a subject line of a protocol", guard_sets.ZH_SUBJECT, _ZH, 0),
    ("Japanese, no kana on the line", guard_sets.JA_NO_KANA, _JA, 0),
    ("Japanese, kana on the line", guard_sets.JA_KANA, _JA, 1),  # 林学 ("forestry") after a label
]


@pytest.mark.parametrize(("what", "shapes", "some_names", "ceiling"), CEILINGS, ids=[c[0] for c in CEILINGS])
def test_no_shape_lets_more_names_through_than_was_measured(
    what: str, shapes: dict[str, str], some_names: list[str], ceiling: int
) -> None:
    for shape, template in shapes.items():
        found, lost = _let_through(template, some_names)
        assert found > 0, (what, shape)
        assert lost <= ceiling, (what, shape, lost, found)


def test_the_stated_limit_a_name_that_is_itself_a_dictionary_word_is_let_through() -> None:
    """What the owner's choice costs, written down as a test so it is seen when it changes: 林 with the given name
    学 is the word 林学 (forestry) to the tokeniser; after a label and before a particle it is let through. With
    an honorific after it, it stands."""
    g = Guard()
    assert g.detect("患者林学は発熱のため受診した。") and not g.tripwire("患者林学は発熱のため受診した。").hit
    assert g.tripwire("林学さんは発熱のため受診した。").hit


# ------------------------------------------------------------------------------------------------ doctor, the lock
def test_doctor_says_when_the_second_look_cannot_check(tagger: Any) -> None:
    from tools.trialbox import doctor

    tagger(absent=True)
    c = doctor.check_tripwire_names(doctor.DoctorInputs())
    assert (c.name, c.status) == ("tripwire_names", "WARN")
    assert "sudachipy" in c.detail and "none is let through" in c.detail
    tagger()
    c = doctor.check_tripwire_names(doctor.DoctorInputs())
    assert c.status == "PASS" and names.DICTIONARY in c.detail
    assert doctor.check_tripwire_names in doctor.CHECKS


def test_the_tokeniser_and_its_dictionary_are_pinned_and_nothing_else_came_with_the_card() -> None:
    locks = [ROOT / "uv.lock", *sorted((ROOT / "deploy").glob("*.lock")), ROOT / "tools/supply_chain/pip-audit.lock"]
    assert len(locks) >= 3
    for lock in locks:
        text = lock.read_text(encoding="utf-8").lower()
        assert "jieba" not in text and "opencc" not in text, lock.name
    pinned = (ROOT / "deploy/requirements.lock").read_text(encoding="utf-8")
    assert "sudachipy==0.7.0" in pinned and "sudachidict-core==20261015" in pinned
    assert names.DICTIONARY == "sudachidict-core 20261015"
    assert not (ROOT / "services/guard/data").exists()  # the Chinese word list of the form not taken is gone
