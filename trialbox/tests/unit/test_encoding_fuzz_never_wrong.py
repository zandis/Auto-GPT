"""D-680: "never wrong text", measured. Short text in a character set the box does not read (EUC-JP, GB18030, EUC-KR,
Windows-1252) was read as Shift_JIS or Big5 text when the two readings tied: 20 to 50 % of two to four characters.
Each shape below is fuzzed with a fixed seed and its ceiling is ZERO wrong readings, for the sheet reader
(``decode``) and the upload reader (``decode_upload``) alike. The other side is measured too: realistic Shift_JIS,
Big5 and UTF-8 sheets are still read. All text is synthetic (clinic words, no names)."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator

import pytest
from tb_common import encoding

JA = ["辞退", "家族反対", "尿酸値", "高血圧", "糖尿病", "同意取得", "検査", "入院", "退院", "来院", "服薬", "中止", "痛風", "発作", "腎機能", "血清", "患者", "診断", "治験", "既往歴", "体重", "身長", "年齢", "性別", "転院", "死亡", "拒否", "連絡不能", "経過観察", "カルテ", "テスト", "データ", "あり", "なし", "です", "した"]  # fmt: skip
ZHS = ["已转院了", "拒绝", "高血压", "糖尿病", "同意", "检查", "住院", "出院", "服药", "停药", "痛风", "发作", "肾功能", "血清", "患者", "诊断", "试验", "既往史", "体重", "身高", "年龄", "性别", "转院", "死亡", "失访", "随访", "病历", "数据", "没有", "已经"]  # fmt: skip
ZHT = ["已轉院", "拒絕", "高血壓", "糖尿病", "同意", "檢查", "住院", "出院", "服藥", "停藥", "痛風", "發作", "腎功能", "血清", "病人", "診斷", "試驗", "過去病史", "體重", "身高", "年齡", "性別", "轉院", "死亡", "失聯", "追蹤", "病歷", "數據", "沒有", "已經"]  # fmt: skip
KO = [
    "체중",
    "신장",
    "성별",
    "연령",
    "과거력",
    "용량",
    "비고",
    "진단",
    "검사",
    "입원",
    "퇴원",
    "환자",
    "동의",
    "거부",
    "전원",
    "사망",
    "통풍",
    "고혈압",
    "당뇨병",
]
WEST = ["ATENÇÃO", "ÄÖÜ", "PÉREZ", "MÜLLER", "SÃO", "ÉCOLE", "NÃO", "AÇÃO", "GONZÁLEZ", "ÅSE", "ØRSTED", "señor", "café", "naïve", "résumé", "Zürich", "Ångström"]  # fmt: skip
KANA = ["ｶﾙﾃ ﾊﾞﾝｺﾞｳ", "ｹﾝｻ ｹｯｶ", "ﾂｳﾌｳ ﾎｯｻ", "ﾃｽﾄ ﾃﾞｰﾀ", "ｼﾝﾀﾞﾝ ﾒｲ", "ﾄｳﾆｮｳ ﾋﾞｮｳ", "ｺｳｹﾂｱﾂ", "ｼﾞﾝｷﾉｳ", "ﾆｭｳｲﾝ ﾋﾞ",
        "ﾀｲｲﾝ ﾋﾞ"]  # fmt: skip
WRAPS = ("{}", "Dx: {}", "ID,note\n1,{}\n")
READERS: dict[str, Callable[[bytes], tuple[str, str]]] = {"decode": encoding.decode, "upload": encoding.decode_upload}
ROUNDS = 150


def _cut(words: list[str], n: int, rng: random.Random) -> str:
    out = ""
    while len(out) < n:
        out += rng.choice(words)
    return out[:n]


def _foreign(rng: random.Random) -> Iterator[tuple[str, str, str]]:
    """(shape, text, the character set it is truly in): short text in sets that are not candidates, and in the two
    that are."""
    for n in (2, 3, 4, 12, 40):
        for name, words, codec in (
            ("euc_jp", JA, "euc_jp"), ("gb18030", ZHS, "gb18030"), ("euc_kr", KO, "euc_kr"),
            ("big5", ZHT, "big5"), ("cp932", JA, "cp932"),  # the box's own sets: read right or refused, as the others
        ):  # fmt: skip
            for wrap in WRAPS:
                yield f"{name}/{n}/{wrap[:3]}", wrap.format(_cut(words, n, rng)), codec
    for wrap in ("{}", "Nome: {}\n", "id,name\n1,{}\n"):
        line = " ".join(rng.choice(WEST) for _ in range(rng.randint(1, 4)))
        yield f"cp1252/{wrap[:3]}", wrap.format(line), "cp1252"
    for name, words, codec in (("big5", ZHT, "big5"), ("euc_jp", JA, "euc_jp"), ("cp932", JA, "cp932")):
        yield f"{name}/2/sheet", f"ID,x\n1,{_cut(words, 2, rng)}\n", codec


@pytest.mark.parametrize("reader", sorted(READERS))
def test_short_text_in_any_character_set_is_read_right_or_refused(reader: str) -> None:
    rng = random.Random(11)
    wrong: dict[str, tuple[str, str]] = {}
    seen = 0
    for _ in range(ROUNDS):
        for shape, truth, codec in _foreign(rng):
            seen += 1
            try:
                got = READERS[reader](truth.encode(codec))[0]
            except encoding.EncodingRefused:
                continue
            if got != truth:
                wrong.setdefault(shape, (truth, got))
    assert seen > 10_000
    assert wrong == {}, f"{len(wrong)} shape(s) read as wrong text, e.g. {next(iter(wrong.items()))}"


def _sheet(kind: str, rng: random.Random) -> str:
    rows = []
    for k in range(rng.randint(1, 8)):
        cell = {
            "kana": lambda: rng.choice(KANA),
            "kana+kanji": lambda: f"{rng.choice(KANA)},{rng.choice(JA)}",
            "kanji": lambda: f"{rng.choice(JA)},{rng.choice(JA)}",
            "hanzi": lambda: f"{rng.choice(ZHT)},{rng.choice(ZHT)}",
            "hanzi, one cell": lambda: rng.choice(ZHT),
        }[kind]()
        rows.append(f"{k + 1},{cell},{rng.randint(20, 80)}")
    return "ID,name,x\n" + "\n".join(rows) + "\n"


@pytest.mark.parametrize(("kind", "codec", "floor"), [
    ("kana", "cp932", 0.9), ("kana+kanji", "cp932", 0.97), ("kanji", "cp932", 0.99), ("hanzi", "big5", 0.95),
    ("hanzi, one cell", "big5", 0.85), ("kanji", "utf-8", 1.0), ("hanzi", "utf-8", 1.0),
])  # fmt: skip
def test_a_real_sheet_is_still_read_and_never_wrong(kind: str, codec: str, floor: float) -> None:
    """The price of the rule, held: of small real sheets (one to eight rows) at least ``floor`` are read; the rest
    are refused (the smallest ones), none is read wrong."""
    rng = random.Random(5)
    read = 0
    for _ in range(200):
        truth = _sheet(kind, rng)
        try:
            got = encoding.decode(truth.encode(codec))[0]
        except encoding.EncodingRefused:
            continue
        assert got == truth
        read += 1
    assert read >= floor * 200, read


def test_a_vendor_master_named_as_shift_jis_is_still_read_where_a_rival_ties() -> None:
    """A caller that names one character set has said what the file is: kana glued to ASCII reads as Big5 as well
    as it does as Shift_JIS, and is read (D-215's licensed masters); for a sheet of unknown origin it is refused."""
    data = "ｶﾙﾃNo,WBC\n1,5.1\n".encode("cp932")
    assert encoding.detect(data, ("cp932",))[0] == "cp932"
    with pytest.raises(encoding.EncodingRefused):
        encoding.detect(data)


# ------------------------------------------------------------------------------------------------ the review
FR = [
    "sévère",
    "décès",
    "œdème",
    "fièvre",
    "nausée",
    "état",
    "général",
    "éruption",
    "cutanée",
    "hémorragie",
    "diarrhée",
]
DE = ["Müdigkeit", "Übelkeit", "Schwäche", "Größe", "Blutdruck", "erhöht", "Kopfschmerzen", "Rötung", "Ödem"]
PT = ["ATENÇÃO", "NÃO", "infecção", "reação", "pressão", "coração", "náusea", "DOR", "AÇÃO", "febre"]
PL = ["GORĄCZKA", "nudności", "ból", "głowy", "zmęczenie", "ŻÓŁTACZKA", "wysypka", "duszność"]
RU = ["рвота", "тошнота", "боль", "головная", "слабость", "сыпь", "давление", "лихорадка"]
HK = ["食咗藥", "冇發燒", "唔舒服", "睇醫生", "嘔吐", "頭痛"]
SYMBOLS = ["ID,temp\n1,37.2 °C\n2,38.1 °C\n", "ID,dose\n1,½ tablet\n2,1 tablet\n", "ID,r\n1,5 ± 2\n",
           "ID,AE\n1,ŒDÈME\n", "Dose: 5 µg\n", "Area 1.73 m²\n", "ID,x\n1,¼ dose\n"]  # fmt: skip


def _western(rng: random.Random) -> Iterator[tuple[str, str, str]]:
    sets = ((FR, ("cp1252", "mac_roman", "cp437"), "fr"), (DE, ("cp1252", "mac_roman", "cp437"), "de"),
            (PT, ("cp1252", "mac_roman"), "pt"), (PL, ("cp1250",), "pl"), (RU, ("koi8_r", "cp1251"), "ru"),
            (HK, ("big5hkscs",), "hk"))  # fmt: skip
    for words, codecs, name in sets:
        for codec in codecs:
            for _ in range(40):
                line = " ".join(rng.choice(words) for _ in range(rng.randint(1, 3)))
                yield f"{name}/{codec}", line, codec
                yield f"{name}/{codec}", f"AE: {line}\n", codec
                yield f"{name}/{codec}", f"ID,AE\n1,{line}\n2,{rng.choice(words)}\n", codec
    for text in SYMBOLS:
        yield "symbols/cp1252", text, "cp1252"
    for text in ("ID,note\n1,ok\n", "Dx: gout\n"):
        yield "utf-16 without a mark", text, "utf-16-le"
        yield "utf-16 without a mark", text, "utf-16-be"
    # two lowercase letters and one character whose legacy bytes are C3 A0 to C3 BF, a western letter in UTF-8:
    # `icf簽` in Big5 was read as `icfñ` by a first version of this card
    for codec in ("big5", "gb18030", "euc_jp", "euc_kr"):
        for low in range(0xA0, 0xC0):
            try:
                ch = bytes((0xC3, low)).decode(codec)
            except UnicodeDecodeError:
                continue
            for wrap in ("ID,note\n1,icf{}\n", "consent{}", "Dx: gout{}\n", "ID,x\n1,ok{}\n"):
                yield f"a word and one character/{codec}", wrap.format(ch), codec


@pytest.mark.parametrize("reader", sorted(READERS))
def test_western_cyrillic_and_cantonese_text_is_read_right_or_refused(reader: str) -> None:
    """French, German, Portuguese and Polish in the single-byte sets a western file may be in, Russian, Cantonese
    in Big5-HKSCS (read: it is of the Big5 family), sheets of symbols, UTF-16 without its mark. Not in the ceiling,
    and said so in D-680: Thai (TIS-620), whose words are the same bytes as runs of half-width kana."""
    rng = random.Random(3)
    wrong: dict[str, tuple[str, str]] = {}
    seen = 0
    for shape, truth, codec in _western(rng):
        try:
            data = truth.encode(codec)
        except UnicodeEncodeError:
            continue
        seen += 1
        try:
            got = READERS[reader](data)[0]
        except encoding.EncodingRefused:
            continue
        if got != truth:
            wrong.setdefault(shape, (truth, got))
    assert seen > 1_500
    assert wrong == {}, f"{len(wrong)} shape(s) read as wrong text, e.g. {next(iter(wrong.items()))}"


def test_a_japanese_note_is_read_in_either_of_its_two_sets() -> None:
    """The SS-MIX2 notes: the caller names Shift_JIS and EUC-JP, both Japanese. A rival of another language must
    read the note better to refuse it, as before (the first version of this card refused 57 % of EUC-JP notes)."""
    rng = random.Random(9)
    read = {"cp932": 0, "euc_jp": 0}
    for _ in range(200):
        lines = ["".join(rng.choice(JA) for _ in range(rng.randint(2, 6))) + "。" for _ in range(rng.randint(1, 20))]
        note = "\n".join(lines) + "\n"
        for codec in read:
            try:
                got = encoding.decode(note.encode(codec), ("cp932", "euc_jp"))[0]
            except encoding.EncodingRefused:
                continue
            assert got == note
            read[codec] += 1
    assert read["cp932"] >= 196 and read["euc_jp"] >= 190, read
