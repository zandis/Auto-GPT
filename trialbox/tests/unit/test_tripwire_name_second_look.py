"""The tripwire's second look at a Chinese or Japanese NAME finding (NEW-LLM-3/4, D-647).

The sets under ``tests/fixtures/guard`` are the ones the decision's figures were measured on: synthetic by
construction (``ordinary_*``: a label word and ordinary clinical text of the repository that begins with a character
that is also a surname; ``names_*``: a label or an honorific with a synthetic full name). The figures here are
gates: a change of the rule, the word list or the dictionary that moves them is a re-measurement.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from guard import names
from guard.guard import Guard

SETS = Path(__file__).resolve().parents[1] / "fixtures" / "guard"
HAS_TOKENISER = importlib.util.find_spec("sudachipy") is not None
needs_tokeniser = pytest.mark.skipif(not HAS_TOKENISER, reason="SudachiPy is not in this environment")


def _rows(name: str) -> list[str]:
    return [x for x in (SETS / f"{name}.txt").read_text(encoding="utf-8").splitlines() if x]


def _refused(rows: list[str]) -> int:
    g = Guard(r"^\d{8}$")
    return sum(1 for x in rows if g.tripwire(x).hit)


class _Fake:
    """A tokeniser stand-in: ``tagged`` are the substrings it calls proper nouns; ``fail``: it raises."""

    def __init__(self, tagged: tuple[str, ...] = (), fail: bool = False, absent: bool = False) -> None:
        self.tagged, self.fail, self.absent, self.error, self.asked = tagged, fail, absent, "", 0

    def load(self) -> bool:
        self.error = "ModuleNotFoundError: No module named 'sudachipy'" if self.absent else ""
        return not self.absent

    def proper_noun(self, line: str, start: int, end: int) -> bool | None:
        self.asked += 1
        if self.absent or self.fail:
            self.error = self.error or "RuntimeError: tokeniser failed"
            return None
        return any(t in line and line.find(t) < end and line.find(t) + len(t) > start for t in self.tagged)


@pytest.fixture
def tagger(monkeypatch: pytest.MonkeyPatch) -> Any:
    def use(**kw: Any) -> _Fake:
        fake = _Fake(**kw)
        monkeypatch.setattr(names, "_TAGGER", fake)
        return fake

    return use


# ------------------------------------------------------------------------------------------------ Chinese
@pytest.mark.parametrize(
    "text", ["個案曾使用任何生物製劑。", "個案曾出現皮疹。", "病人高血壓控制不良", "患者許可後進行檢查"]
)
def test_ordinary_chinese_text_is_no_longer_refused(text: str) -> None:
    g = Guard()
    assert g.detect(text) and not g.tripwire(text).hit  # the pattern still matches; the second look takes it away


@pytest.mark.parametrize(
    "text",
    [
        "個案丁怡君由家屬陪同就診。",
        "何惠雯先生主訴胸痛三天。",
        "病人：陳美玲，女，54歲",
        "姓名 林志明",
        "患者曾志偉，男",
    ],
)
def test_a_chinese_name_still_stands(text: str) -> None:
    v = Guard().tripwire(text)
    assert v.hit and "NAME" in v.kinds


def test_the_chinese_sets_hold_the_measured_figures() -> None:
    ordinary, with_names = _rows("ordinary_zh"), _rows("names_zh")
    g = Guard(r"^\d{8}$")
    assert all(g.detect(x) for x in ordinary)  # before the second look: every sentence refused
    assert _refused(ordinary) <= 15  # 17.9 % of 84
    assert _refused(with_names) >= 187  # 97.9 % of 191


# ------------------------------------------------------------------------------------------------ Japanese
def test_japanese_text_is_decided_by_the_tokenisers_tag(tagger: Any) -> None:
    fake = tagger(tagged=("山田",))
    g = Guard()
    assert g.tripwire("患者 山田太郎さんに病状を説明した。").hit  # a proper noun inside the finding: it stands
    assert not g.tripwire("患者 高血圧の既往あり、内服を継続している。").hit  # none: ordinary text
    assert fake.asked >= 2


@pytest.mark.parametrize("how", [{"absent": True}, {"fail": True}])
def test_without_a_working_tokeniser_every_japanese_name_finding_stands(tagger: Any, how: dict[str, bool]) -> None:
    """Fail closed: as before this card. More ordinary text is refused; no name is let through."""
    tagger(**how)
    g = Guard()
    for text in ("患者 高血圧の既往あり、内服を継続している。", "患者 山田太郎さんに病状を説明した。"):
        assert g.tripwire(text).hit == bool(g.detect(text)) is True
    st = names.status()
    assert st["tokeniser"] is (not how.get("absent", False)) and (st["error"] or not how.get("absent"))


def test_a_line_too_long_for_the_tokeniser_is_not_asked_and_stands(tagger: Any) -> None:
    fake = tagger(tagged=())
    line = "患者 高血圧の既往あり。" + "あ" * names.MAX_LINE
    assert Guard().tripwire(line).hit and fake.asked == 0
    assert (
        not Guard().tripwire("患者 高血圧の既往あり。\n" + "あ" * names.MAX_LINE).hit
    )  # the long text is another line


def test_an_error_inside_the_second_look_leaves_the_finding_standing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any) -> bool:
        raise RuntimeError("word list unreadable")

    monkeypatch.setattr(names, "zh_stands", boom)
    assert Guard().tripwire("個案曾使用任何生物製劑。").hit
    monkeypatch.undo()
    monkeypatch.setattr(names, "WORDS", SETS / "no-such-file.csv")
    names._words.cache_clear()
    try:
        assert Guard().tripwire("個案曾使用任何生物製劑。").hit and names.status()["zh_error"]
    finally:
        names._words.cache_clear()


@needs_tokeniser
def test_the_japanese_sets_hold_the_measured_figures() -> None:
    ordinary, with_names = _rows("ordinary_ja"), _rows("names_ja")
    g = Guard(r"^\d{8}$")
    assert sum(1 for x in ordinary if g.detect(x)) == 96  # before: 72.7 % of 132
    assert _refused(ordinary) <= 4  # 3.0 %
    assert _refused(with_names) >= 81  # 97.6 % of 83
    assert names.status()["tokeniser"] and names.status()["effect"] == ""


# ------------------------------------------------------------------------------------------------ what it never does
def test_only_a_chinese_or_japanese_name_finding_is_looked_at_again(tagger: Any) -> None:
    tagger(tagged=())
    g = Guard(r"^\d{8}$")
    for text, kind in (
        ("Mr. Chen was seen today.", "NAME"),  # a name in Latin letters stands
        ("個案曾使用 0912-345-678", "PHONE"),
        ("患者 高血圧 A123456789", None),
        ("個案曾出現皮疹，病歷號 12345678", "MRN"),
    ):
        v = g.tripwire(text)
        assert v.hit and (kind is None or kind in v.kinds), text


def test_redaction_keeps_masking_every_match() -> None:
    """The trace store's redaction does not take the second look: masking too much costs readability only."""
    g = Guard()
    assert "[NAME]" in g.redact("個案曾使用任何生物製劑。") and not g.tripwire("個案曾使用任何生物製劑。").hit


def test_a_date_near_an_unconfirmed_name_is_no_date_of_birth_finding() -> None:
    g = Guard()
    day = "，" + "2024年3月5日"
    assert not g.tripwire("個案曾使用任何生物製劑" + day + "停藥。").hit
    named = next(x for x in _rows("names_zh") if x.startswith("個案") and "陪同就診" in x)  # a synthetic name
    v = g.tripwire(named.rstrip("。") + day + "。")
    assert v.hit and "DOB_NEAR_NAME" in v.kinds


# ------------------------------------------------------------------------------------------------ doctor and the list
def test_doctor_says_when_the_second_look_cannot_check(tagger: Any) -> None:
    from tools.trialbox import doctor

    tagger(absent=True)
    c = doctor.check_tripwire_names(doctor.DoctorInputs())
    assert (c.name, c.status) == ("tripwire_names", "WARN")
    assert "sudachipy" in c.detail and "none is let through" in c.detail
    tagger(tagged=())
    c = doctor.check_tripwire_names(doctor.DoctorInputs())
    assert c.status == "PASS" and names.DICTIONARY in c.detail
    assert doctor.check_tripwire_names in doctor.CHECKS


def test_the_shipped_word_list_is_the_measured_one() -> None:
    word, one, plain = names._words()
    assert (len(word), len(one)) == (159721, 531)
    assert "".join(sorted(plain)) == "于何余古嚴尤戴曾涂游白許謝高黃黄"  # surnames that are ordinary words
    assert {"使用", "出現", "血壓", "高血壓"} <= word and "有" in one
