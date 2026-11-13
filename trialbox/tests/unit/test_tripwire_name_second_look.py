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

    def __init__(
        self, tagged: tuple[str, ...] = (), fail: bool = False, absent: bool = False, words: tuple[str, ...] = ()
    ) -> None:
        self.tagged, self.words, self.fail, self.absent = tagged, words, fail, absent
        self.error, self.asked, self.failed = "", 0, False

    def load(self) -> bool:
        self.error = "ModuleNotFoundError: No module named 'sudachipy'" if self.absent else self.error
        return not self.absent

    def tokens(self, line: str) -> list[tuple[int, int, str]] | None:
        """Every character a token of its own, but the tagged substrings: one token each, a proper noun; and the
        ``words``: one token each, ordinary."""
        self.asked += 1
        if self.absent or self.fail:
            self.error, self.failed = self.error or "RuntimeError: tokeniser failed", True
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


def _let_through(template: str, some_names: Any) -> tuple[int, int]:
    """(names the patterns find, names the tripwire then lets through) for one shape."""
    g = Guard(r"^\d{8}$")
    found = lost = 0
    for n in some_names:
        text = template.format(n=n)
        if any(f.kind == "NAME" for f in g.detect(text)):
            found += 1
            lost += not g.tripwire(text).hit
    return found, lost


# The standing gate of the tripwire (the integrator's rule after this card's first review): a ceiling PER SHAPE on
# the hard synthetic sets, so that no change passes on an average or on an easy set. A ceiling is what was
# measured for D-647; raising one is the owner's decision. (shapes, names, names found per shape, ceiling)
_ZH = list(guard_sets.zh_names())
_ZH_ONE = list(guard_sets.zh_names(guard_sets.ZH_GIVEN_ONE))
_JA = list(guard_sets.ja_names())
_PLAIN = [s + x for s in "于何余古嚴尤戴曾涂游白許謝高黃黄" for x in guard_sets.ZH_GIVEN]
_TOP10 = [s + x for s in "陳林黃張李王吳劉蔡楊" for x in guard_sets.ZH_GIVEN]
CEILINGS: list[tuple[str, dict[str, str], list[str], int, int]] = [
    ("a cue or a boundary", guard_sets.ZH_CUED, _ZH, 5750, 0),
    ("kana on the line, cue or boundary", guard_sets.ZH_WITH_KANA, _ZH, 5750, 0),
    ("the middle dot", {"dot": guard_sets.ZH_DOTS["middle dot"]}, _ZH, 5750, 0),
    ("run into text", guard_sets.ZH_RUNNING, _ZH, 5750, 188),  # 3.3 %
    ("run into text, the sixteen ordinary-word surnames", {"x": "病人{n}今日回診"}, _PLAIN, 800, 103),  # 12.9 %
    ("run into text, the ten most frequent surnames", {"x": "病人{n}今日回診"}, _TOP10, 500, 13),  # 2.6 %
    ("run into text, one-character given name", guard_sets.ZH_RUNNING, _ZH_ONE, 1380, 23),  # 1.7 %
    ("run into text on a line with kana", guard_sets.ZH_RUNNING_WITH_KANA, _ZH, 5750, 144),  # 2.5 %
    ("a subject line of a protocol", guard_sets.ZH_SUBJECT, _ZH, 5750, 188),  # 3.3 %
    ("Japanese, no kana on the line", guard_sets.JA_NO_KANA, _JA, 928, 0),
    ("Japanese, kana on the line", guard_sets.JA_KANA, _JA, 928, 1),  # 林学 after a label
]


@pytest.mark.parametrize(("what", "shapes", "some_names", "found", "ceiling"), CEILINGS, ids=[c[0] for c in CEILINGS])
def test_no_shape_lets_more_names_through_than_was_measured(
    what: str, shapes: dict[str, str], some_names: list[str], found: int, ceiling: int
) -> None:
    for shape, template in shapes.items():
        if shape == "sex and age, no space" and found == 5750:
            continue  # "N女72歲": 女 after the name is the sex cue; held with the cued shapes' rule, not found as text
        got, lost = _let_through(template, some_names)
        assert got == found, (what, shape, got)
        assert lost <= ceiling, (what, shape, lost)


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
        "病人王家豪・主訴頭痛",  # the middle dot is punctuation
        "山口一郎様来院",  # a Japanese name on a line without kana
        "中村健一氏同意取得済",
        "病人高建國於門診追蹤",  # the surname is an ordinary word, the given name a common word: 建 and 國 are name characters
        "病人林怡君今日回診，服用ロキソニン後改善",  # run into text beside kana: the tokeniser has no word for it
    ],
)
def test_the_reviews_names_stand(text: str) -> None:
    v = Guard().tripwire(text)
    assert v.hit and "NAME" in v.kinds


def test_the_stated_limit_a_name_that_reads_as_words_and_runs_into_text_is_let_through() -> None:
    """What the owner's trade costs, written down as a test so it is seen when it changes: the surname is an
    ordinary one-character word (黃 "yellow"), the given name is a common word (志豪) whose characters are not
    both among the ones names are most often made of, and text follows with no boundary. With a boundary or a
    cue the same name stands."""
    g = Guard()
    for text in (
        "個案黃志豪主訴頭痛",
        "病人王家豪今日回診",
        "受試者王家豪簽名",
    ):  # 王家 is a word; 豪 is no name character
        assert g.detect(text) and not g.tripwire(text).hit, text
    assert g.tripwire("個案黃志豪，主訴頭痛").hit and g.tripwire("黃志豪先生主訴頭痛").hit


def test_the_document_parsers_mask_keeps_every_pattern_match() -> None:
    """A protocol's contact and subject lines are masked as before this card: the mask does not take the look."""
    from doc_parser.parser import mask_contacts

    g = Guard()
    for line in ("受試者王家豪簽名", "受試者黃志豪已簽署同意書", "聯絡人黃志豪先生將與您聯繫", "患者林愛は同意した"):
        masked, kinds = mask_contacts(line, g)
        assert "[NAME]" in masked or masked == "[CONTACT]", line
        assert kinds
    assert not g.tripwire("受試者王家豪簽名").hit  # the gateway's tripwire is the one that takes the look


# ------------------------------------------------------------------------------------------------ Japanese
def test_japanese_text_is_decided_by_the_tokenisers_tag(tagger: Any) -> None:
    fake = tagger(tagged=("山田",), words=("高血圧",))
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
    fake = tagger(tagged=(), words=("高血圧",))
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
    assert _refused(ordinary) <= 7  # 5.3 % (4 of the 7 are lines that hold a name)
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
