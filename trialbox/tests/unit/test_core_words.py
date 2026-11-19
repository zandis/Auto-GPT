"""9k-16 (review 09 DS-16, D-1371): the twenty core words as data; a catalogue check refuses other spellings.

``services/console/core_words.yaml`` holds each word's one spelling in en, ja and zh-TW and the spellings refused for
it; ``tools.core_words`` reads every console catalogue string for a refused spelling and ``tools.text_keys`` (``make
lint``) reports what it finds. Proved by: zero refused spellings in the catalogues. These tests hold that count at
zero, check the file's shape, and show that the check finds a refused spelling, names key, language and the right
spelling, and does not fire on a refused spelling inside the right one or inside a phrase listed as allowed."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import pytest

from tools import core_words as cw
from tools import text_keys as tk

pytestmark = [pytest.mark.guard, pytest.mark.nodb]


@dataclass(frozen=True)
class Row:
    lang: str
    key: str
    text: str
    where: str = "services/console/i18n_x.py:1"


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    return cw.load()


def test_zero_refused_spellings_in_the_console_catalogues() -> None:
    defs = tk.definitions()
    assert len(defs) > 9000  # the check read the catalogues, not an empty list
    assert cw.problems(defs) == []


def test_text_keys_runs_the_check_on_every_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make lint` runs `python -m tools.text_keys`: what the core-word check finds is one of its problems, and the
    check is handed every definition the reader saw (the loser of an override included)."""
    seen: list[int] = []

    def fake(defs: list[tk.Definition]) -> list[str]:
        seen.append(len(defs))
        return ["refused spelling (stand-in)"]

    monkeypatch.setattr(cw, "problems", fake)
    assert tk.problems() == ["refused spelling (stand-in)"]
    assert seen and seen[0] > 9000


def test_the_file_holds_twenty_words_in_three_languages_none_read_yet(data: dict[str, Any]) -> None:
    assert cw.shape(data) == []
    assert len(data["words"]) == 20
    for w in data["words"]:
        # no native reader has read a row yet (decision 35, reopened): the file says so on every row
        assert w["read_by_native_reader"] is False, w["id"]
        if not any(w[lang]["refused"] for lang in cw.LANGS):
            assert w.get("note") or w["id"] in {"consent"}, f"{w['id']}: refuses nothing and says nothing why"


def test_decisions_37_and_38_are_in_the_file(data: dict[str, Any]) -> None:
    by = {w["id"]: w for w in data["words"]}
    # decision 37: the zh-TW coordinator word stays as it is until the owner chooses; no second word meanwhile
    assert by["coordinator"]["zh-TW"] == {"spelling": "研究護理師", "refused": ["研究協調員"]}
    # decision 38: "patient code" is the one word for the pseudonym on clinical pages
    assert [by["patient_code"][lang]["spelling"] for lang in cw.LANGS] == ["Patient code", "患者コード", "病人代碼"]


def test_a_refused_spelling_is_found_and_named_with_key_language_and_the_right_spelling() -> None:
    rows = [
        Row("zh-TW", "patient.title", "14 天內有門診的候選病人。"),
        Row("ja", "job.sponsor_pack", "スポンサー向けパック"),
        Row("en", "role.investigator", "investigator (PI / Sub-I)"),
        Row("en", "x.help", "Patients enroll here; see the enrollment page."),
    ]
    found = cw.refused(rows)
    assert [(r.lang, r.key, r.found, r.spelling) for r in found] == [
        ("zh-TW", "patient.title", "候選病人", "候選者"),
        ("ja", "job.sponsor_pack", "スポンサー", "治験依頼者"),
        ("en", "role.investigator", "Sub-I", "Sub-investigator"),
        ("en", "x.help", "enrollment", "Enrol"),
        ("en", "x.help", "enroll", "Enrol"),
    ]
    msg = str(found[0])
    assert "zh-TW" in msg and "patient.title" in msg and "'候選者'" in msg and "i18n_x.py:1" in msg


def test_a_spelling_is_refused_only_in_its_own_language() -> None:
    # 委託者 alone is refused in zh-TW (試驗委託者); the same characters in a Japanese text are not this check's
    assert cw.refused([Row("ja", "x", "委託者")]) == []
    assert [r.found for r in cw.refused([Row("zh-TW", "x", "主持人即委託者")])] == ["委託者"]


def test_english_matches_whole_words_only() -> None:
    rows = [
        Row("en", "a", "Enrolled on {date}"),  # British and American alike: not refused
        Row("en", "b", "Enrolment"),
        Row("en", "c", "sub-investigator"),  # sub-I is inside it, but not as a word
        Row("en", "d", "subindex"),
    ]
    assert cw.refused(rows) == []


def test_a_refused_spelling_inside_the_right_one_is_not_a_finding() -> None:
    # 授權紀錄 is refused, and is the start of the right spelling 授權紀錄表; 委託者 ends 試驗委託者
    rows = [Row("zh-TW", "a", "開啟授權紀錄表"), Row("zh-TW", "b", "試驗委託者版面變更")]
    assert cw.refused(rows) == []
    both = cw.refused([Row("zh-TW", "c", "授權紀錄表與授權紀錄")])
    assert [r.found for r in both] == ["授權紀錄"]


def test_an_allowed_phrase_is_stated_as_data_and_masks_its_refused_spelling(data: dict[str, Any]) -> None:
    # 預篩檢查 is 預篩 (pre-screen) + 檢查 (check): it holds 篩檢 but is not the refused 篩檢
    assert cw.refused([Row("zh-TW", "feas.b.help", "預篩檢查可以找回這些病人。")], data) == []
    assert [r.found for r in cw.refused([Row("zh-TW", "x", "篩檢")], data)] == ["篩檢"]
    without = copy.deepcopy(data)
    for w in without["words"]:
        w["zh-TW"].pop("allowed", None)
    assert [r.found for r in cw.refused([Row("zh-TW", "feas.b.help", "預篩檢查")], without)] == ["篩檢"]


def test_the_longest_refused_spelling_is_one_finding() -> None:
    found = cw.refused([Row("ja", "edc.x", "この試験の責任分担表に")])
    assert [r.found for r in found] == ["責任分担表"]


def test_the_shape_check_refuses_a_broken_file(data: dict[str, Any]) -> None:
    def broken(change: Any) -> list[str]:
        d = copy.deepcopy(data)
        change(d)
        return cw.shape(d)

    assert broken(lambda d: d["words"].pop())  # nineteen words
    assert broken(lambda d: d["words"][0].pop("ja"))  # a language missing
    assert broken(lambda d: d["words"][1].__setitem__("id", d["words"][0]["id"]))  # an id twice
    assert broken(lambda d: d["words"][1]["ja"].__setitem__("refused", ["候補者"]))  # refuses its own spelling
    assert broken(lambda d: d["words"][1].__setitem__("read_by_native_reader", "no"))
    assert broken(lambda d: d["words"][1]["ja"].__setitem__("synonym", "x"))  # 10F-5's layer is not here
    # an allowed phrase that holds none of the word's refused spellings says nothing: refused
    assert broken(lambda d: d["words"][13]["zh-TW"].__setitem__("allowed", ["預約"]))
    # one word refusing what another word spells would make every use of that word a finding
    assert broken(lambda d: d["words"][0]["zh-TW"].__setitem__("refused", ["試驗"]))


def test_the_command_exits_zero_on_the_catalogues() -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = os.pathsep.join(str(tk.ROOT / p) for p in ("libs", "services", "."))
    out = subprocess.run(
        [sys.executable, "-m", "tools.core_words"], capture_output=True, text=True, cwd=tk.ROOT, env=env, check=False
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "core_words: 0 problem(s)" in out.stderr
