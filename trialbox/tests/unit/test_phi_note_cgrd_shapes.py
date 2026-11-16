"""NEW-B-50 (D-756): one definition per shape for the note masker and the guard: resident certificate numbers (both
formats), twelve-digit numbers, bed and room numbers, staff names beside a role word and names before an honorific
without a listed surname, and wider labelled values. Synthetic text only; the identifiers are built here, never
written whole in the file (the repository's own scan reads it)."""

from __future__ import annotations

import pytest
from guard import recognisers as rec
from guard.guard import Guard
from tb_common import phi_guard as pg
from tb_common.phi_guard import MASK_CHAR, NOTE_MASK_VERSION, mask_note

G = Guard("^\\d{8}$")
ARC_NEW = "A" + "8" + "00000014"  # the new format: a letter, 8 or 9, eight digits
ARC_OLD = "A" + "C" + "00000017"  # the old format: two letters, eight digits
CARD = " ".join(["0000", "1234", "5678"])
CARD_JOINED = "".join(["0000", "1234", "5679"])
PHONE_SPACED = "(02) " + "2712" + "." + "3456"
MOBILE_SPACED = " ".join(["0912", "345", "678"])
CHART_SPACED = " ".join(["1234", "5678"])
TIMES = " ".join(["0800", "1200", "1800"])  # a medication schedule


def _masked(text: str, value: str) -> bool:
    out = mask_note(text)
    s = text.index(value)
    return len(out) == len(text) and all(out[i] == MASK_CHAR or text[i].isspace() for i in range(s, s + len(value)))


def _untouched(text: str, value: str) -> bool:
    out = mask_note(text)
    s = text.index(value)
    return out[s : s + len(value)] == value


SHAPES = [
    (f"居留證 {ARC_NEW} 外籍看護", ARC_NEW),
    (f"外籍配偶，證號{ARC_OLD}。", ARC_OLD),
    (f"健保卡 {CARD} 已過卡", CARD),
    (f"卡號{CARD_JOINED}，", CARD_JOINED),
    ("床號：12A-05，生命徵象穩定", "12A-05"),
    ("今轉入5B-12床觀察", "5B-12"),
    ("病床No. 3 呼叫鈴", "3"),
    ("住病房 0712，家屬陪伴", "0712"),
    ("房號：7A-03", "7A-03"),
    ("主治醫師：王大明。", "王大明"),
    ("記錄者 林小華", "林小華"),
    ("護理師陳美，協助翻身", "陳美"),
    ("由王大明醫師說明病情", "王大明"),
    ("，李護理師協助抽血", "李"),
    ("王先生表示疼痛改善", "王"),
    ("，陳美華小姐陪同。", "陳美華"),
    ("家屬林阿嬤來院", "林"),
    ("病歷號：ab-1234-5678 住院", "ab-1234-5678"),
    (f"病歷號 {CHART_SPACED} 於門診", CHART_SPACED),
    (f"聯絡電話：{PHONE_SPACED} 轉 12", PHONE_SPACED + " 轉 12"),
    (f"手機 {MOBILE_SPACED}。", MOBILE_SPACED),
    ("身分證字號：a" + "123456789", "a" + "123456789"),
    # the review's cases (D-756)
    ("護理師：王大明、林小華", "王大明、林小華"),
    ("護理師王大明、林小華協助", "王大明、林小華"),
    ("住院醫師王大明說明病情", "王大明"),
    ("主治醫師王大明表示病情穩定", "王大明"),
    ("醫師(王大明)", "王大明"),
    ("醫師：歐陽大明", "歐陽大明"),
    ("王大明/護理師", "王大明"),
    ("王大明主治醫師", "王大明"),
    ("護理長林小華", "林小華"),
    ("社工師林小華", "林小華"),
    ("會同王大明醫師", "王大明"),
    ("告知王先生", "王"),
    ("，陳伯伯來院", "陳"),
    ("12號床", "12"),
    ("床：12", "12"),
    ("bed no. 12A", "12A"),
    ("病床號碼：12", "12"),
    ("住712病房", "712"),
    ("房間712", "712"),
    (f"居留證 A {ARC_NEW[1:]}", "A " + ARC_NEW[1:]),
    (f"健保卡 {CARD.replace(' ', '.')}", CARD.replace(" ", ".")),
    (f"健保卡 {TIMES}", TIMES),
    (f"病歷號：ab {CHART_SPACED}", "ab " + CHART_SPACED),
    ("病歷號：[" + "12345678]", "12345678"),
]


@pytest.mark.parametrize(("text", "value"), SHAPES)
def test_the_masker_and_the_guard_both_find_the_shape(text: str, value: str) -> None:
    assert _masked(text, value), mask_note(text)
    assert value not in G.redact(text) or value.strip() == "", G.redact(text)


LEFT_ALONE = [
    ("病人臥床休息", "臥床"),
    ("轉入加護病房觀察", "加護病房觀察"),
    ("醫師說明病情。", "說明病情"),
    ("由主治醫師評估後", "主治醫師評估"),
    ("會診心臟科醫師", "心臟科醫師"),
    ("值班護理師交班", "值班護理師交班"),
    ("其先生陪同就醫", "其先生"),
    ("與先生同住", "與先生同住"),
    ("醫師 建議回診", "建議回診"),
    (f"Insulin at {TIMES} daily", TIMES),
    # the review's over-masking (D-756)
    ("醫師交代多喝水", "交代"),
    ("醫師認為可出院", "認為"),
    ("護理師換藥。", "換藥"),
    ("醫師及護理師", "醫師及"),
    ("詢問醫師後", "詢問"),
    ("麻醉醫師評估", "麻醉"),
    ("記錄者：同上", "同上"),
    ("這位先生", "這位"),
    ("一位老先生", "一位"),
    ("看護小姐協助", "看護"),
    ("本病房共40床", "40"),
    ("共有20床", "20"),
    ("2床被", "2"),
    ("病房 2 次", "2"),
    ("電話：2026-11-15 已聯絡家屬", "2026-11-15"),
    ("血壓 120/80 mmHg，心跳 88", "120/80"),
]


@pytest.mark.parametrize(("text", "value"), LEFT_ALONE)
def test_the_words_of_a_note_are_left_alone(text: str, value: str) -> None:
    assert _untouched(text, value), mask_note(text)


def test_the_guard_never_lets_through_twelve_digits_the_masker_leaves() -> None:
    text = f"マイナンバー {TIMES}"
    assert TIMES not in G.redact(text), G.redact(text)  # the guard takes every twelve digits


@pytest.mark.parametrize("text", [t for t, _ in SHAPES] + ["陳美華醫師", "記錄者 林小華", "告知王先生"])
def test_the_guard_finds_every_span_the_masker_finds(text: str) -> None:
    redacted = G.redact(text)
    for _kind, s, e in pg.note_spans(text):
        assert text[s:e] not in redacted, (text, text[s:e], redacted)


def test_a_note_written_as_one_long_line_is_masked_in_time() -> None:
    import time

    line = "病人今日生命徵象穩定，持續觀察，主訴頭痛改善。" * 1300  # about 30,000 characters, no line break
    for f in (mask_note, G.redact):
        start = time.monotonic()
        f(line)
        assert time.monotonic() - start < 2.0, f  # a look that ran to the line's end took 6.6 s
    for adverse in ("病房：" * 7000, "電話：" * 7000, "床" * 20000, "醫師" * 10000, "王" * 20000):
        start = time.monotonic()
        mask_note(adverse)
        assert time.monotonic() - start < 2.0, adverse[:3]


def test_the_guard_reads_the_masker_s_definitions() -> None:
    assert rec.TW_ARC is pg.TW_ARC and rec.MY_NUMBER is pg.TWELVE_DIGITS_ANY
    names = {n for n, _ in rec.recognisers()}
    assert {"bed", "bed_number", "room", "room_number", "phone_label", "name_staff_after", "name_staff_before",
            "name_honorific", "id_label", "note_spans"} <= names  # fmt: skip


def test_the_mask_version_says_the_masking_changed() -> None:
    assert NOTE_MASK_VERSION == "6"  # NEW-B-55 (D-923): English Taiwan charts


# ---------------------------------------------------------------------------------------------- packet 2 (D-756)
DISCHARGE = """出院病摘
病歷號：{chart}　床號：{bed}
入院日期：2026/11/02　出院日期：2026/11/09
出院診斷：第二型糖尿病，痛風
住院經過：主治醫師：{doctor}查房後評估，{nurse}護理師協助衛教。家屬{family}先生陪同。
出院醫囑：門診追蹤。聯絡電話：{phone}。地址：{address}
外籍看護居留證 {arc}，健保卡 {card}。
"""
ADMISSION = """入院紀錄
主訴：多尿三個月。
現病史：病人自述三個月前開始多尿，於門診由{doctor}醫師安排住院，住{room}病房，{bed}床。
過去病史：高血壓。家族史：無。
理學檢查：BP 132/84 mmHg，HR 88。
記錄者：{nurse}
聯絡人：{family}小姐，電話 {phone}。住址：{address}。
"""
FILL = {
    "chart": " ".join(["1234", "5678"]),
    "bed": "12A-05",
    "doctor": "王大明",
    "nurse": "林小華",
    "family": "陳",
    "phone": MOBILE_SPACED,
    "address": "宜蘭縣羅東鎮公正路 " + "88 號",
    "arc": ARC_OLD,
    "card": CARD,
    "room": "712",
}


@pytest.mark.parametrize("layout", [DISCHARGE, ADMISSION], ids=["discharge-summary", "admission-note"])
def test_every_shape_is_masked_in_both_note_layouts(layout: str) -> None:
    text = layout.format(**FILL)
    for key, value in FILL.items():
        if "{" + key + "}" in layout:
            assert _masked(text, value), (key, value, mask_note(text))
            assert value not in G.redact(text), (key, G.redact(text))


@pytest.mark.parametrize(
    "address",
    [
        "宜蘭縣羅東鎮公正路 88 號",
        "台北市大安區復興南路一段 390 號 5F",
        "新竹市東區光復路二段101號　3樓",
        "臺中市西屯區台灣大道三段99號12樓之1",
    ],
)
def test_a_full_address_with_spaces_between_its_parts_is_masked(address: str) -> None:
    assert _masked(f"住址：{address}，", address.split("號", maxsplit=1)[0] + "號"), mask_note(address)
    assert _masked(f"家住{address}", address.split("號", maxsplit=1)[0] + "號"), mask_note(address)


def _corpus() -> list[str]:
    """Synthetic texts for the equivalence check: this file's cases, both layouts, and generated notes."""
    import random

    rnd = random.Random(11)
    words = ["主訴", "醫師", "護理師", "先生", "小姐", "床", "病房", "電話", "住址", "病歷號", "出生", "號", "路", "生命徵象",
             "BP", "pH 7.4", "Tel", "home", "1234", "0800", "2026/11/02", "：", "，", "。", " ", "\n", "王", "林", "大明",
             "12", "A3", "號床", "5B-12", ARC_NEW, CARD, MOBILE_SPACED, "Dr. Smith", "さん", "様",
             "民國四十五年三月十四日", "出生日期", "生", "生日：", "1956年3月14日", "昭和三十一年", "生まれ"]  # fmt: skip
    gen = ["".join(rnd.choice(words) for _ in range(rnd.randint(20, 400))) for _ in range(300)]
    cases = [t for t, _ in SHAPES] + [t for t, _ in LEFT_ALONE] + [DISCHARGE.format(**FILL), ADMISSION.format(**FILL)]
    return cases + gen


def test_the_gates_and_windows_find_what_the_whole_note_gives(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-756 (speed): a pattern is skipped when the note lacks what it needs, and an anchored pattern runs only around
    its anchor; neither may change a span."""
    corpus = _corpus()
    fast = [pg.note_spans(t, "^\\d{8}$") for t in corpus]
    monkeypatch.setattr(pg, "_NOTE_GATES", tuple(lambda f: True for _ in pg._NOTE_GATES))
    monkeypatch.setattr(pg, "_NOTE_WINDOWS", {})
    whole = [pg.note_spans(t, "^\\d{8}$") for t in corpus]
    assert [(t, a) for t, a, b in zip(corpus, fast, whole, strict=True) if a != b] == []
