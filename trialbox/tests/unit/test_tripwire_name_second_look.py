"""The tripwire's second look at a Chinese or Japanese NAME finding (NEW-LLM-3/4, D-647).

The sets under ``tests/fixtures/guard`` are the ones the decision's figures were measured on: synthetic by
construction (``ordinary_*``: a label word and ordinary clinical text of the repository that begins with a character
that is also a surname; ``names_*``: a label or an honorific with a synthetic full name). The figures here are
gates: a change of the rule, the word list or the dictionary that moves them is a re-measurement.
"""

from __future__ import annotations

import hashlib
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
    """A tokeniser stand-in: ``tagged`` are the substrings it calls proper nouns; ``fail``: it raises."""

    def __init__(self, tagged: tuple[str, ...] = (), fail: bool = False, absent: bool = False) -> None:
        self.tagged, self.fail, self.absent, self.error, self.asked, self.failed = tagged, fail, absent, "", 0, False

    def load(self) -> bool:
        self.error = "ModuleNotFoundError: No module named 'sudachipy'" if self.absent else self.error
        return not self.absent

    def proper_nouns(self, line: str) -> list[tuple[int, int]] | None:
        self.asked += 1
        if self.absent or self.fail:
            self.error, self.failed = self.error or "RuntimeError: tokeniser failed", True
            return None
        return [(line.find(t), line.find(t) + len(t)) for t in self.tagged if t in line]


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
    assert _refused(with_names) >= 188  # 98.4 % of 191 (the card's first, easy set)


def _let_through(shapes: dict[str, str], some_names: Any) -> tuple[int, int]:
    """(names the patterns find, names the tripwire then lets through) over ``shapes`` x ``some_names``."""
    g = Guard(r"^\d{8}$")
    found = lost = 0
    for _shape, text in guard_sets.rows(shapes, some_names):
        if any(f.kind == "NAME" for f in g.detect(text)):
            found += 1
            lost += not g.tripwire(text).hit
    return found, lost


def test_the_hard_name_sets_hold_the_measured_figures() -> None:
    """The review's shapes (``tests/guard_sets.py``). A cue or a boundary always keeps a name; what is let through
    is a Chinese name run straight into text whose characters read as common words."""
    assert _let_through(guard_sets.ZH_CUED, guard_sets.zh_names()) == (74750, 0)
    assert _let_through(guard_sets.ZH_WITH_KANA, guard_sets.zh_names()) == (23000, 0)
    found, lost = _let_through(guard_sets.ZH_RUNNING, guard_sets.zh_names())
    assert found == 34500 and lost <= 940  # 2.72 %; 3.3 % in each shape with nothing but text after the name
    found, lost = _let_through(guard_sets.ZH_RUNNING, guard_sets.zh_names(guard_sets.ZH_GIVEN_ONE))
    assert found == 8280 and lost <= 82  # 0.99 %
    assert _let_through(guard_sets.JA_NO_KANA, guard_sets.ja_names()) == (5568, 0)
    found, lost = _let_through(guard_sets.JA_KANA, guard_sets.ja_names())
    assert found == 6496 and lost <= 5  # 0.08 %: 林愛, 林学 after a label


def test_the_stated_limit_a_name_that_reads_as_words_and_runs_into_text_is_let_through() -> None:
    """What the owner's trade costs, written down as a test so it is seen when it changes: the surname is an
    ordinary one-character word (黃 "yellow"), the given name is a common word (志豪) whose characters are not
    both among the ones names are most often made of, and text follows with no boundary. With a boundary or a
    cue the same name stands."""
    g = Guard()
    assert g.detect("個案黃志豪主訴頭痛") and not g.tripwire("個案黃志豪主訴頭痛").hit
    assert g.tripwire("個案黃志豪，主訴頭痛").hit and g.tripwire("黃志豪先生主訴頭痛").hit


@pytest.mark.parametrize(
    "text",
    [
        "王家豪，男，65歲，服用ロキソニン後改善",  # a Chinese name on a line with kana: the cue keeps it
        "病人林怡君，主訴のど痛三天",
        "林怡君さんは本日来院した。",
        "病人歐陽志明今日回診",  # a compound surname is no common word
        "王國華先生表示頭暈",  # an honorific inside the match
        "聯絡人黃志豪先生將與您聯繫",
        "病人王家豪\r\n主訴頭痛",  # a line end of any kind is a boundary
        "病人王家豪\u00a0主訴頭痛",
        "山口一郎様来院",  # a Japanese name on a line without kana
        "中村健一氏同意取得済",
        "病人高建國於門診追蹤",  # the surname is an ordinary word, the given name a common word: 建 and 國 are name characters
    ],
)
def test_the_reviews_names_stand(text: str) -> None:
    v = Guard().tripwire(text)
    assert v.hit and "NAME" in v.kinds


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
    st = names.status()  # doctor's source: a tokeniser that is absent, or has failed on a text, is not "there"
    assert st["tokeniser"] is False and st["error"] and "none is let through" in st["effect"]


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
    word, one, plain, given = names._words()
    assert (len(word), len(one), len(given)) == (159721, 531, 136)
    assert "".join(sorted(plain)) == "于何余古嚴尤戴曾涂游白許謝高黃黄"  # surnames that are ordinary words
    assert {"使用", "出現", "血壓", "高血壓"} <= word and "有" in one


def test_the_word_list_is_the_built_one_and_its_sources_are_in_no_lock() -> None:
    """D-647: the list is data, rebuilt by ``tools/zh_common_words.py`` from the named dictionary file; the
    packages it is built with are build-time tools and never reach a lock or an image."""
    assert hashlib.sha256(names.WORDS.read_bytes()).hexdigest() == (
        "7e25b2267894b3af247ed6e8d0f7eceee0305b11f8a1e195b0621dccb96654ec"
    )
    locks = [ROOT / "uv.lock", *sorted((ROOT / "deploy").glob("*.lock")), ROOT / "tools/supply_chain/pip-audit.lock"]
    assert len(locks) >= 3
    for lock in locks:
        text = lock.read_text(encoding="utf-8").lower()
        assert "jieba" not in text and "opencc" not in text, lock.name
    pinned = (ROOT / "deploy/requirements.lock").read_text(encoding="utf-8")
    assert "sudachipy==0.7.0" in pinned and "sudachidict-core==20261015" in pinned
    assert names.DICTIONARY == "sudachidict-core 20261015"
