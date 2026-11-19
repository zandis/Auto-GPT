"""Card 10C-1b: the optional analyser recogniser of the privacy guard is inert by default; its rule does what it says.

Nothing in the product registers a name recogniser, and no analyser package is in the lock: the guard's outputs are
master's (``phi_guard.NAME_RECOGNISERS`` is empty, nothing imports SudachiPy, MeCab or Janome). The combination rule
(``tb_common.ja_names.name_spans``) is tested on a stub analyser whose tags are written here, so it needs no package.
The measurement (``tools.ja_name_eval``) runs only where an analyser is installed, and skips cleanly otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


@pytest.mark.req("PRIV-29")
def test_nothing_is_registered_and_no_analyser_is_imported() -> None:
    """Off and absent: importing the guard, the masker, this module and the harness loads no analyser package."""
    code = (
        "import sys; import tb_common.phi_guard as pg, guard.guard, tb_common.ja_names, tools.ja_name_eval; "
        "print(pg.NAME_RECOGNISERS == [], [m for m in ('sudachipy', 'fugashi', 'MeCab', 'janome', 'unidic_lite', "
        "'ipadic', 'spacy', 'ginza') if m in sys.modules])"
    )
    env = {"PYTHONPATH": f"{ROOT / 'libs'}:{ROOT / 'services'}:{ROOT}", "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    assert out.stdout.strip() == "True []"
    assert phi_guard.NAME_RECOGNISERS == []


@pytest.mark.req("PRIV-29")
def test_a_registered_recogniser_adds_names_to_the_masker_the_guard_and_the_scan() -> None:
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
def test_enable_and_disable_register_one_recogniser() -> None:
    stub = Stub({"見本太郎は来院": [("見本", NOUN), ("太郎", MEI), ("は", PARTICLE), ("来院", NOUN)]})
    ja_names.enable(stub)
    ja_names.enable(stub)  # once only
    try:
        assert len(phi_guard.NAME_RECOGNISERS) == 1
        assert mask_note("見本太郎は来院") == "○○○○は来院"
    finally:
        ja_names.disable()
    assert phi_guard.NAME_RECOGNISERS == []


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
def test_the_harness_skips_cleanly_without_an_analyser(capsys: pytest.CaptureFixture[str]) -> None:
    if any(ja_name_eval.installed(c) for c in ja_names.CHOICES):
        pytest.skip("an analyser is installed here: the measurement test below runs instead")
    assert ja_name_eval.main([]) == 0
    assert "skipped: no analyser installed" in capsys.readouterr().out


@pytest.mark.req("PRIV-29")
def test_the_recommended_analyser_as_measured() -> None:
    """Runs only where SudachiPy and SudachiDict-small are installed (never in the lock): the figures of the
    assessment (docs/research/2026-11-19-japanese-name-analyser.md) as ceilings."""
    if not ja_name_eval.installed("sudachi-small"):
        pytest.skip("sudachipy and sudachidict_small are not installed (not in the lock: decision D-1235)")
    res = ja_name_eval.run(["sudachi-small"])["sudachi-small"]
    assert res["probe_masked"]["missed"] == 0
    assert res["new_names"]["missed"] <= 17 and res["held_names"]["missed"] <= 4
    for key in ("probe_unchanged", "new_ordinary", "held_ordinary"):
        assert res[key]["changed"] == 0, res[key]["which"]
