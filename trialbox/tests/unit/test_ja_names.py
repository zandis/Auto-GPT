"""Card 10C-1b: the guard's Japanese name analyser (SudachiPy with SudachiDict-small, D-1235) and its rule.

The guard registers ``phi_guard.japanese_names`` by default; it loads the analyser lazily (no import when the guard
loads, none for a text without kana or 歳), one tokenizer per thread, and works with no network. The combination rule
(``tb_common.ja_names.name_spans``) is tested on a stub analyser whose tags are written here, so those tests need no
package; the measurement (``tools.ja_name_eval``) runs with the analyser of the lock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from guard.guard import Guard
from tb_common import ja_names, phi_guard
from tb_common.ja_names import Token
from tb_common.phi_guard import mask_note

from tools import ja_name_eval

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
SYNTH = ROOT / "eval" / "phi_synth"
LINES = json.loads((SYNTH / "ja_name_lines.json").read_text())
HELD = json.loads((SYNTH / "ja_name_lines_holdout.json").read_text())
SEI = ("名詞", "固有名詞", "人名", "姓")
MEI = ("名詞", "固有名詞", "人名", "名")
PERSON = ("名詞", "固有名詞", "人名", "一般")
NOUN = ("名詞", "普通名詞", "一般")
SUFFIX = ("接尾辞", "名詞的", "一般")
PARTICLE = ("助詞", "係助詞")


class Stub:
    """An analyser whose words and tags are given per text (the surfaces in order; spaces are skipped)."""

    label = "stub"

    def __init__(self, tags: dict[str, list[tuple[str, tuple[str, ...]]]]) -> None:
        self.tags = tags

    def tokens(self, text: str) -> list[Token]:
        return ja_names._offsets(text, self.tags.get(text, []))


def _spans(text: str, words: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    return [text[s:e] for s, e in ja_names.name_spans(text, Stub({text: words}))]


_ANALYSERS = ("sudachipy", "sudachidict_small", "fugashi", "MeCab", "janome", "unidic_lite", "ipadic", "spacy", "ginza")
_ENV = {
    "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT / 'services'}:{ROOT}",
    "PATH": "/usr/bin:/bin",
    # no network: a proxy that refuses every connection (the dictionary is a wheel, read from disk)
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "NO_PROXY": "",
}


def _fresh(code: str) -> str:
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=_ENV, check=True)
    return out.stdout.strip()


@pytest.mark.req("PRIV-29")
def test_the_analyser_is_registered_and_loaded_only_for_japanese_text() -> None:
    """Registered by default; importing the guard, the masker, this module and the harness loads no analyser, and
    neither does a Chinese or English note; the first Japanese one loads SudachiPy with SudachiDict-small, offline."""
    assert [phi_guard.japanese_names] == phi_guard.NAME_RECOGNISERS
    code = (
        "import sys; import tb_common.phi_guard as pg, guard.guard, tb_common.ja_names, tools.ja_name_eval; "
        f"loaded = lambda: [m for m in {_ANALYSERS!r} if m in sys.modules]; "
        "print(pg.NAME_RECOGNISERS == [pg.japanese_names], loaded()); "
        "print(pg.mask_note('這位病人在台北看診。Seen today, stable.'), loaded()); "
        "print(pg.mask_note('68歳男性 ミホン タロウ'), loaded())"
    )
    assert _fresh(code).splitlines() == [
        "True []",
        "這位病人在台北看診。Seen today, stable. []",
        "68歳男性 ○○○ ○○○ ['sudachipy', 'sudachidict_small']",
    ]


@pytest.mark.req("PRIV-29")
def test_one_tokenizer_per_thread() -> None:
    """Each thread loads its own analyser (a Sudachi tokenizer is not shared between threads), once."""
    code = (
        "import threading; import tb_common.phi_guard as pg; seen = []\n"
        "def run():\n"
        "    for _ in range(3): pg.mask_note('見本太郎さん 68歳'); seen.append(id(pg._JA_ANALYSER.an))\n"
        "ts = [threading.Thread(target=run) for _ in range(3)]\n"
        "[t.start() for t in ts]; [t.join() for t in ts]\n"
        "print(len(seen), len(set(seen)))"
    )
    assert _fresh(code) == "9 3"


@pytest.mark.req("PRIV-29")
def test_the_default_analyser_masks_a_name_with_no_label() -> None:
    guard = Guard(None)
    text = "68歳男性 ミホン タロウ"
    assert mask_note(text) == "68歳男性 ○○○ ○○○"
    assert guard.redact(text) == "68歳男性 [NAME]"
    assert phi_guard.scan(text).hit


@pytest.mark.req("PRIV-29")
def test_a_registered_recogniser_adds_names_to_the_masker_the_guard_and_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phi_guard, "NAME_RECOGNISERS", [])  # the rules alone, then one recogniser
    text = "見本太郎は本日来院"
    guard = Guard(None)
    before = (mask_note(text), guard.redact(text), phi_guard.scan(text).hit)
    assert before == (text, text, False)  # a known gap of the rules

    def recognise(t: str) -> list[tuple[int, int]]:
        return [(0, 4)] if t == text else []

    phi_guard.NAME_RECOGNISERS.append(recognise)
    try:
        assert mask_note(text) == "○○○○は本日来院"
        assert guard.redact(text) == "[NAME]は本日来院"
        assert phi_guard.scan(text).hit
    finally:
        phi_guard.NAME_RECOGNISERS.remove(recognise)
    assert (mask_note(text), guard.redact(text), phi_guard.scan(text).hit) == before


@pytest.mark.req("PRIV-29")
def test_enable_puts_another_analyser_in_place_and_disable_puts_the_default_back() -> None:
    stub = Stub({"見本太郎は来院": [("見本", NOUN), ("太郎", MEI), ("は", PARTICLE), ("来院", NOUN)]})
    ja_names.enable(stub)
    ja_names.enable(stub)  # once only
    try:
        assert len(phi_guard.NAME_RECOGNISERS) == 1
        assert [phi_guard.japanese_names] != phi_guard.NAME_RECOGNISERS
        assert mask_note("見本太郎は来院") == "○○○○は来院"
    finally:
        ja_names.disable()
    assert [phi_guard.japanese_names] == phi_guard.NAME_RECOGNISERS


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize(
    ("text", "words", "want"),
    [
        # step 1: the surname before a given name, a given name after a surname, katakana, a space between them
        ("見本太郎は来院", [("見本", NOUN), ("太郎", MEI), ("は", PARTICLE), ("来院", NOUN)], ["見本太郎"]),
        (
            "ミホン タロウは来院",
            [("ミホン", NOUN), ("タロウ", MEI), ("は", PARTICLE), ("来院", NOUN)],
            ["ミホン タロウ"],
        ),
        ("杉野 直人 52歳", [("杉野", SEI), ("直人", MEI), ("52", ("名詞", "数詞")), ("歳", SUFFIX)], ["杉野 直人"]),
        ("宮坂 ケイコの母", [("宮坂", SEI), ("ケイコ", NOUN), ("の", PARTICLE), ("母", NOUN)], ["宮坂 ケイコ"]),
        # step 2: never a surname alone, a katakana word alone or one character
        ("松本の病院へ転院", [("松本", SEI), ("の", PARTICLE), ("病院", NOUN), ("へ", PARTICLE), ("転院", NOUN)], []),
        ("ミヤBM 3錠", [("ミヤ", MEI), ("BM", NOUN), ("3", ("名詞", "数詞")), ("錠", SUFFIX)], []),
        ("翔が来院した", [("翔", MEI), ("が", PARTICLE), ("来院", NOUN), ("し", ("動詞",)), ("た", ("助動詞",))], []),
        # step 3: an eponym, a scale, a procedure, an institution, a compound
        (
            "既往に橋本病あり",
            [("既往", NOUN), ("に", PARTICLE), ("橋本", SEI), ("病", SUFFIX), ("あり", ("動詞",))],
            [],
        ),
        ("高安動脈炎で通院", [("高安", SEI), ("動脈炎", NOUN), ("で", PARTICLE), ("通院", NOUN)], []),
        ("パーキンソン病の方", [("パーキンソン", PERSON), ("病", SUFFIX), ("の", PARTICLE), ("方", NOUN)], []),
        ("福田分類 A1です", [("福田", SEI), ("分類", NOUN), ("A1", NOUN), ("です", ("助動詞",))], []),
        (
            "紹介先：松本 歯科です",
            [("紹介", NOUN), ("先", SUFFIX), ("：", ()), ("松本", SEI), ("歯科", NOUN), ("です", ("助動詞",))],
            [],
        ),
        (
            "ギラン・バレー症候群の",
            [("ギラン", PERSON), ("・", ()), ("バレー", NOUN), ("症候群", NOUN), ("の", PARTICLE)],
            [],
        ),
        (
            "見本太郎医院より紹介",
            [("見本", NOUN), ("太郎", MEI), ("医院", NOUN), ("より", PARTICLE), ("紹介", NOUN)],
            [],
        ),
        # the guard's given-name class: 佐藤錦 and 山田錦 are a cherry and a rice
        (
            "長女 山田錦の酒を持参",
            [
                ("長女", NOUN),
                ("山田", SEI),
                ("錦", MEI),
                ("の", PARTICLE),
                ("酒", NOUN),
                ("を", PARTICLE),
                ("持参", NOUN),
            ],
            [],
        ),
        # step 4: the guard's words for a role, a relative or the patient; after Dr.
        ("長女 花子が来院", [("長女", NOUN), ("花子", MEI), ("が", PARTICLE), ("来院", NOUN)], ["花子"]),
        ("患者：独歩で来院", [("患者", NOUN), ("：", ()), ("独歩", MEI), ("で", PARTICLE), ("来院", NOUN)], []),
        ("Dr. コールした", [("Dr", NOUN), (".", ()), ("コール", PERSON), ("し", ("動詞",)), ("た", ("助動詞",))], []),
        # a text with no kana and no 歳 is not Japanese: not read
        ("林小明在台北看診", [("林", SEI), ("小明", MEI), ("在", NOUN), ("台北", NOUN), ("看診", NOUN)], []),
    ],
)
def test_the_combination_rule(text: str, words: list[tuple[str, tuple[str, ...]]], want: list[str]) -> None:
    assert _spans(text, words) == want


@pytest.mark.req("PRIV-29")
def test_without_the_rule_every_tagged_word_is_proposed() -> None:
    text = "既往に橋本病あり"
    stub = Stub({text: [("既往", NOUN), ("に", PARTICLE), ("橋本", SEI), ("病", SUFFIX), ("あり", ("動詞",))]})
    assert ja_names.name_spans(text, stub, protect=False) == [(3, 5)]
    assert ja_names.name_spans(text, stub) == []


@pytest.mark.req("PRIV-29")
def test_a_long_note_is_read_in_pieces_with_its_offsets_kept() -> None:
    line = "本日は異常なし、" * 400  # 3,200 characters on one line
    text = line + "\n見本太郎は来院"
    words = {"見本太郎は来院": [("見本", NOUN), ("太郎", MEI), ("は", PARTICLE), ("来院", NOUN)]}
    pieces = list(ja_names._pieces(text))
    assert all(len(p) <= ja_names._LINE_MAX for _, p in pieces)
    assert "".join(p for _, p in pieces) == text.replace("\n", "")
    assert [text[s:e] for s, e in ja_names.name_spans(text, Stub(words))] == ["見本太郎"]


@pytest.mark.req("PRIV-29")
def test_the_card_lines_are_well_formed_and_the_ordinary_ones_pass_the_rules() -> None:
    assert (len(LINES["names"]), len(LINES["ordinary"]), len(HELD["names"]), len(HELD["ordinary"])) == (75, 75, 30, 30)
    for p in LINES["names"] + HELD["names"]:
        assert all(v in p["text"] for v in p["ids"]), p
    guard = Guard(None)
    assert [t for t in LINES["ordinary"] + HELD["ordinary"] if ja_name_eval.changed(t, guard)] == []


@pytest.mark.req("PRIV-29")
def test_the_harness_skips_cleanly_without_an_analyser(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ja_name_eval, "installed", lambda choice: False)
    assert ja_name_eval.main([]) == 0
    assert "skipped: no analyser installed" in capsys.readouterr().out


@pytest.mark.req("PRIV-29")
def test_the_recommended_analyser_as_measured() -> None:
    """The guard as it ships (D-1235, second round): the development figures of the pull request as ceilings."""
    assert ja_name_eval.installed("sudachi-small")
    res = ja_name_eval.run(["sudachi-small"])["guard"]
    assert res["probe_masked"]["missed"] == 0
    assert res["new_names"]["missed"] <= 11 and res["held_names"]["missed"] <= 2
    for key in ("probe_unchanged", "new_ordinary", "held_ordinary"):
        assert res[key]["changed"] == 0, res[key]["which"]


# ------------------------------------------------------------------------------------------------ second round
CLASSES = json.loads((SYNTH / "ja_name_classes.json").read_text())


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("probe", CLASSES["names"], ids=lambda p: f"{p['class']}:{p['text']}")
def test_a_name_of_every_class_is_masked(probe: dict[str, Any]) -> None:
    """Kanji with no kana, hiragana, beside a title or a label, katakana foreign names across a middle dot, a name
    kept whole, Latin letters: the masker and the guard both take every character of each name."""
    assert ja_name_eval.unmasked(probe["text"], probe["ids"], Guard(None)) == []


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize(
    "probe",
    [pytest.param(p, marks=pytest.mark.xfail(strict=True, reason="limit: " + p["class"])) for p in CLASSES["limit"]],
    ids=lambda p: f"{p['class']}:{p['text']}",
)
def test_the_limits_still_leak(probe: dict[str, Any]) -> None:
    """The stated limits (a kanji surname alone, a hiragana surname the analyser does not know, a romaji surname
    alone): strict expected failures, so one that starts to pass must move to ``names``."""
    assert ja_name_eval.unmasked(probe["text"], probe["ids"], Guard(None)) == []


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("text", CLASSES["ordinary"])
def test_the_counter_cases_pass_unchanged(text: str) -> None:
    """Eponyms, places, titles with no name, a medicine, family and staff words, a prefix, drugs before an age,
    English sentences and Chinese lines."""
    assert not ja_name_eval.changed(text, Guard(None)), mask_note(text)


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("line", CLASSES["pinned"], ids=lambda p: p["text"])
def test_the_name_is_masked_never_the_title_beside_it(line: dict[str, str]) -> None:
    assert mask_note(line["text"]) == line["mask"]


@pytest.mark.req("PRIV-29")
def test_the_language_comes_from_the_site_and_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """A kanji-only line is read when the site declares Japanese notes, or declares nothing and the line holds no
    character only Chinese writes; never when the site declares Chinese or English notes. Kana is Japanese at any
    site."""
    kanji, chinese, kana = "森本裕子", "這位病人是森本裕子", "森本裕子さんが来院"
    monkeypatch.setattr(phi_guard, "site_notes_language", lambda: None)
    assert [phi_guard.japanese_text(t) for t in (kanji, chinese, kana)] == [True, False, True]
    assert mask_note(kanji) == "○○○○"
    monkeypatch.setattr(phi_guard, "site_notes_language", lambda: "ja")
    assert [phi_guard.japanese_text(t) for t in (kanji, chinese, kana)] == [True, True, True]
    for lang in ("zh-TW", "en"):
        monkeypatch.setattr(phi_guard, "site_notes_language", lambda lang=lang: lang)
        assert [phi_guard.japanese_text(t) for t in (kanji, chinese, kana)] == [False, False, True]
        assert mask_note(kanji) == kanji


@pytest.mark.req("PRIV-29")
def test_the_site_language_is_the_declared_notes_language(monkeypatch: pytest.MonkeyPatch) -> None:
    import tb_common.config as config

    class Site:
        notes_language = "zh-TW"

    class Settings:
        site = Site()

    class Config:
        settings = Settings()

    monkeypatch.setattr(config, "get_config", Config)
    assert phi_guard.site_notes_language() == "zh-TW"
    Site.notes_language = "auto"
    assert phi_guard.site_notes_language() is None


@pytest.mark.req("PRIV-29")
def test_romaji_needs_a_surname_and_the_shape_of_a_name() -> None:
    """Two Hepburn words, one a listed surname by its reading (long vowels written or not), written as a name is."""
    names = ("Taro Yamada", "Satou Hanako", "Kenji KATOH", "ito yuki")
    assert [t for t in names if not ja_names.romaji_spans(t)] == []
    for text in ("Taro Smith", "Taking Sato", "the Yamada", "Yamada", "Mild Ono", "done Mori"):
        assert ja_names.romaji_spans(text) == [], text
    assert (ja_names._kana("Ohta"), ja_names._kana("Kenji"), ja_names._kana("Smith")) == ("オタ", "ケンジ", None)


@pytest.mark.req("PRIV-29")
def test_the_reading_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Memory: the analyser's dictionary is memory-mapped (its pages read in as used, at most its 110 MB file); the
    one cache of this module, surname readings, never holds more than its bound."""
    monkeypatch.setattr(ja_names, "_SEI_CACHE_MAX", 8)
    monkeypatch.setattr(ja_names, "_SEI_CACHE", {})
    an = Stub({})
    for i in range(50):
        ja_names._reading_is_sei(an, "カ" * (i + 2))
        assert len(ja_names._SEI_CACHE) <= 8


# ------------------------------------------------------------------------------------------------ third round
@pytest.mark.req("PRIV-29")
def test_the_cue_words_are_data() -> None:
    """The titles, roles and words in a name's place come from ``libs/tb_common/ja_name_cues.json`` (data, not code):
    every title before a name is a cue the rule reads, every title after a name ends one, every word of
    ``not_a_name_value`` is refused in a name's place."""
    cues = json.loads((ROOT / "libs" / "tb_common" / "ja_name_cues.json").read_text())
    assert cues["format"] == "tb-ja-name-cues/1"
    assert cues == ja_names.CUES
    for w in cues["titles_before_name"]:
        m = ja_names._CUE_BEFORE.match(w + " 宮田")
        assert m is not None and m.end() == len(w) + 1, w
    for w in cues["titles_after_name"]:
        assert any(m.start() == 2 for m in ja_names._TITLE.finditer("宮田" + w)), w
    assert all(ja_names.not_a_name(w) for w in cues["not_a_name_value"])


@pytest.mark.req("PRIV-29")
def test_a_name_masked_once_is_masked_wherever_it_stands_alone() -> None:
    """The other bare occurrences of a masked name in the same note, never inside a longer word or before a term."""
    assert mask_note("菅野さんへ電話。菅野は外出中。菅野病院とは別。") == "○○さんへ電話。○○は外出中。菅野病院とは別。"
    assert mask_note("河合さん来院。河合町の住所。") == "○○さん来院。河合町の住所。"
    assert ja_names.repeat_spans("長女と面会。長女は帰宅。", ["長女"]) == []
