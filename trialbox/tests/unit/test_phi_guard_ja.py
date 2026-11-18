"""Card 10C-1 (plan 10, criterion F3; review 11 JP-8): the privacy guard masks Japanese identifiers.

The probe set is synthetic and lives with the other synthetic PHI notes (``eval/phi_synth/ja_guard_probes.json``):
lines with a name in katakana (full- and half-width), kanji, kana or both, with and without an honorific or a title;
old-form kanji names (髙, 﨑, 齋, 邊) before さん or 様; the health-insurance 記号, 番号 and 枝番; 公費 and 受給者
numbers; chart and patient numbers; phone numbers and postal codes as Japanese records write them; dates of birth in
an era and in western form; addresses. Before the card the guard left an identifier in most of its lines. Every
identifier must be masked by both the note masker (what the lake indexes) and the guard (what may reach a model), and
ordinary clinical lines (drugs, diseases, anatomy, abbreviations, honorifics said of a role) must pass unchanged.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from guard.guard import Guard
from tb_common import phi_guard as pg
from tb_common.phi_guard import MASK_CHAR, mask_note, scan

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: no database, in `make guard` and `make test-pure`

PROBES = json.loads((Path(__file__).resolve().parents[2] / "eval" / "phi_synth" / "ja_guard_probes.json").read_text())
G = Guard(None)


def _unmasked(text: str, ids: list[str]) -> list[str]:
    """The identifiers of ``ids`` that the masker or the guard leaves a character of."""
    masked = mask_note(text)
    spans = [(f.start, f.end) for f in G.detect(text)]
    out = []
    for value in ids:
        i = text.index(value)
        for j in range(i, i + len(value)):
            if text[j].isspace():
                continue
            if masked[j] != MASK_CHAR or not any(s <= j < e for s, e in spans):
                out.append(value)
                break
    return out


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("probe", PROBES["masked"], ids=lambda p: p["text"])
def test_every_japanese_identifier_is_masked(probe: dict[str, Any]) -> None:
    text, ids = str(probe["text"]), [str(v) for v in probe["ids"]]
    assert _unmasked(text, ids) == [], (text, mask_note(text), G.redact(text))
    redacted = G.redact(text)
    assert all(v not in redacted for v in ids), redacted


@pytest.mark.req("PRIV-29")
def test_f3_no_line_of_the_probe_set_keeps_an_identifier() -> None:
    """Criterion F3: 0 of at least 50 synthetic Japanese lines left with an identifier, every kind covered."""
    lines = PROBES["masked"]
    assert len(lines) >= 50
    kinds = {p["kind"] for p in lines}
    assert {"kana_name", "kanji_name", "mixed_name", "insurance", "patient_number", "phone", "postal", "dob",
            "address"} <= kinds  # fmt: skip
    assert [p["text"] for p in lines if _unmasked(p["text"], p["ids"])] == []


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("text", PROBES["unchanged"])
def test_ordinary_clinical_lines_pass_unchanged(text: str) -> None:
    assert mask_note(text) == text
    assert G.detect(text) == []
    # the v1 scan trips on the bare label words (氏名, 生年月日) by design, before this card too: nothing else may
    assert set(G.tripwire(text).kinds) <= {"KEYWORD"}


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("line", PROBES["overmasked_before"]["lines"], ids=lambda x: x["text"])
def test_lines_over_masked_before_the_card_are_unchanged_by_it(line: dict[str, str]) -> None:
    assert G.redact(line["text"]) == line["redact"]
    assert mask_note(line["text"]) == line["mask"]


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("probe", PROBES["masked"], ids=lambda p: p["text"])
def test_the_check_before_a_model_call_sees_every_probe(probe: dict[str, Any]) -> None:
    """The v1 scan (the criteria compiler's and the model-call clearance's check) runs the Japanese rules too."""
    assert scan(str(probe["text"])).hit


@pytest.mark.req("PRIV-29")
@pytest.mark.parametrize("index", range(len(pg.JA_NOTE_PATTERNS)))
def test_every_japanese_rule_is_needed_by_a_probe(monkeypatch: pytest.MonkeyPatch, index: int) -> None:
    """Without any one of the 10C-1 rules, at least one probe line keeps an identifier: no rule is dead weight."""
    rx = pg.JA_NOTE_PATTERNS[index][1]
    keep = [i for i, (_k, r) in enumerate(pg._NOTE_PATTERNS) if r is not rx]
    monkeypatch.setattr(pg, "_NOTE_PATTERNS", tuple(pg._NOTE_PATTERNS[i] for i in keep))
    monkeypatch.setattr(pg, "_NOTE_GATES", tuple(pg._NOTE_GATES[i] for i in keep))
    missed = []
    for p in PROBES["masked"]:
        masked = mask_note(p["text"])
        for value in p["ids"]:
            i = p["text"].index(value)
            if any(masked[j] != MASK_CHAR and not p["text"][j].isspace() for j in range(i, i + len(value))):
                missed.append(p["text"])
    assert missed, rx.pattern[:80]


@pytest.mark.req("PRIV-29")
def test_the_japanese_rules_keep_a_long_line_fast() -> None:
    adverse = ("ア" * 30000, "アイ " * 10000, "髙橋" * 15000, "様" * 20000, "山さん" * 10000, "記号１" * 10000,
               "氏名：" * 10000, "０ー" * 15000, "ふりがな：あ " * 5000, "市1-" * 10000, "1ア号室" * 8000,
               "長女 佐藤" * 6000, "本日髙橋一郎さん来院、記号１２番号３４。" * 1500)  # fmt: skip
    # a label, then a run of white space 100 kB long (spaces, tabs, full-width spaces): a look with two unbounded
    # runs of the same characters took 7.5 s on 8,000 spaces
    labels = (
        "氏名",
        "ふりがな",
        "記号",
        "患者ＩＤ",
        "〒",
        "郵便番号",
        "枝番",
        "患者：",
        "主治医：",
        "キーパーソン",
        "長女",
    )
    runs = tuple(label + ws * 100_000 + "見本" for label in labels for ws in (" ", "\t", "\u3000"))
    for text in adverse + runs:
        for f in (mask_note, G.redact, scan):
            start = time.monotonic()
            f(text)
            assert time.monotonic() - start < 2.0, (f, text[:6])
