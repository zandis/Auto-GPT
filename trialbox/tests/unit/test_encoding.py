"""One encoding detector (T-118, D-215; review R-33, MR-013, E-05): ``tb_common.encoding``.

The fixtures under ``tests/fixtures/encodings/`` are synthetic (made-up names and values); :data:`FIXTURES` holds the
text each one was written from and the codec of each part, and the first test checks the bytes still match.
"""

from __future__ import annotations

import csv
import io
import random
from pathlib import Path

import pytest
from sitesetup import charts, intake, messy
from tb_common import encoding

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "encodings"

BIG5_HEADER = "病歷號,姓名,性別,出生日期,診斷,尿酸值,日期\r\n"
FIXTURES: dict[str, list[tuple[str, str]]] = {
    # MR-013: the Chinese is only in the header; the first-that-decodes readers took it for CP932 (ｩmｦW for 姓名)
    "big5_header_only.csv": [
        (
            BIG5_HEADER
            + "A0001,Chen Da-Wen,M,1960-01-02,M10.9,8.1,2025-01-02\r\n"
            + "A0002,Lin Mei-Ling,F,1971-05-06,M10.9,7.4,2025-02-03\r\n",
            "big5",
        )
    ],
    "big5_sheet.csv": [
        (
            "病歷號,姓名,出生日期,性別,診斷,尿酸值,單位,就診日\r\n"
            "A0001,陳大文,民國49年1月2日,男,痛風,8.1,mg/dL,112年3月15日\r\n"
            "A0002,林美玲,民國60年5月6日,女,高血壓,6.2,mg/dL,民國112年4月1日\r\n",
            "big5",
        )
    ],
    "cp932_sheet.csv": [
        (
            "カルテ番号,氏名,カナ,生年月日,診断,尿酸値,単位,受診日\r\n"
            "001,山田太郎,ﾔﾏﾀﾞ ﾀﾛｳ,昭和40年5月6日,痛風,8.1,mg/dL,令和6年1月5日\r\n"
            "002,鈴木花子,ｽｽﾞｷ ﾊﾅｺ,平成2年3月4日,高尿酸血症,7.9,mg/dL,R6.2.1\r\n",
            "cp932",
        )
    ],
    "utf8_bom.csv": [("\ufeffID,氏名,尿酸値,単位\r\n1,山田,480,µmol/L\r\n", "utf-8")],
    "eucjp_note.txt": [("退院時サマリ：痛風発作は軽快した。尿酸値は６．８ｍｇ／ｄＬ。\n", "euc_jp")],
    # lines 1-3 UTF-8, line 4 saved in Shift_JIS by another program: refused at line 4, never half-read
    "mixed_utf8_cp932.csv": [
        ("ID,診断,受診日\n1,痛風,2025-01-02\n2,高血圧,2025-01-03\n", "utf-8"),
        ("3,糖尿病,2025-01-04\n", "cp932"),
    ],
    # two bytes B6 C5: Shift_JIS ｶﾅ or Big5 債; too little to tell, so refused
    "ambiguous_two_chars.csv": [("ID,kana\r\n1,ｶﾅ\r\n", "cp932")],
}


def _read(name: str) -> bytes:
    return (DIR / name).read_bytes()


def test_the_fixtures_are_the_texts_above() -> None:
    assert sorted(p.name for p in DIR.iterdir()) == sorted(FIXTURES)
    for name, parts in FIXTURES.items():
        assert _read(name) == b"".join(t.encode(enc) for t, enc in parts), name


# ------------------------------------------------------------------------------------------------ examples
@pytest.mark.parametrize(
    ("name", "codec"),
    [
        ("big5_header_only.csv", "big5"),
        ("big5_sheet.csv", "big5"),
        ("cp932_sheet.csv", "cp932"),
        ("utf8_bom.csv", "utf-8-sig"),
    ],
)
def test_detect_names_the_codec(name: str, codec: str) -> None:
    got, confidence = encoding.detect(_read(name))
    assert got == codec and confidence >= encoding.THRESHOLD
    text, used = encoding.decode(_read(name))
    assert used == codec and text == "".join(t for t, _ in FIXTURES[name]).lstrip("\ufeff")


def test_a_big5_header_is_not_read_as_cp932() -> None:
    """MR-013: before D-215 every sheet reader tried CP932 before Big5 and took the first that did not fail."""
    data = _read("big5_header_only.csv")
    assert data.decode("cp932").startswith("ｯfｾ弴ｹ,ｩmｦW")  # the old reading: no error, and no 姓名 for the guard
    assert encoding.decode(data) == ("".join(t for t, _ in FIXTURES["big5_header_only.csv"]), "big5")


def test_a_big5_sheet_with_a_name_column_drops_the_column() -> None:
    """Acceptance (2): the name column is recognised and dropped, because the header is read as Big5."""
    grid, merged = intake.read_grid("candidates.csv", _read("big5_header_only.csv"))
    assert grid[0][:2] == ["病歷號", "姓名"]
    cleaned = messy.clean(grid, merged)
    assert cleaned.dropped == ["姓名"]
    assert all("Chen" not in str(v) and "Lin" not in str(v) for r in cleaned.records for v in r.values.values())


def test_the_ssmix2_note_reads_as_euc_jp() -> None:
    from adapter.sources.ssmix2.source import document_text

    text, how = document_text("note.txt", _read("eucjp_note.txt"))
    assert how == "text" and text.startswith("退院時サマリ")


def test_licensed_files_keep_their_codec_names() -> None:
    from adapter.licensed import LicensedError, detect_encoding

    assert detect_encoding(_read("utf8_bom.csv")) == "utf-8-sig"
    assert detect_encoding(_read("cp932_sheet.csv")) == "cp932"
    assert detect_encoding(b"code,name\r\n1,a\r\n") == "utf-8"
    with pytest.raises(LicensedError) as exc:
        detect_encoding(_read("big5_sheet.csv"))  # a vendor list is UTF-8 or Shift_JIS: Big5 is not read as either
    assert exc.value.code == "LIC-ENCODING" and "FORM-ENCODING" in exc.value.message


# ------------------------------------------------------------------------------------------------ refusals
def test_a_mixed_encoding_file_is_refused_with_the_line() -> None:
    with pytest.raises(encoding.EncodingRefused) as exc:
        encoding.decode(_read("mixed_utf8_cp932.csv"))
    assert exc.value.code == "FORM-ENCODING" and exc.value.line == 4
    assert str(exc.value).startswith("FORM-ENCODING:") and "(line 4)" in str(exc.value)


def test_mixed_the_other_way_round_names_the_first_utf8_line() -> None:
    data = "ID,診断\n1,痛風\n".encode("cp932") + "2,高血圧\n".encode()
    with pytest.raises(encoding.EncodingRefused) as exc:
        encoding.detect(data)
    assert exc.value.line == 3


def test_too_little_to_tell_is_refused() -> None:
    with pytest.raises(encoding.EncodingRefused) as exc:
        encoding.detect(_read("ambiguous_two_chars.csv"))
    assert exc.value.code == "FORM-ENCODING" and "cannot be told" in exc.value.message


def test_bytes_no_codec_reads_are_refused_with_the_line() -> None:
    data = b"ID,x\n1,ok\n2,\x82\xa0\x88\n3,ok\n"  # line 3: a Shift_JIS lead byte with no trail, invalid in Big5 too
    with pytest.raises(encoding.EncodingRefused) as exc:
        encoding.detect(data)
    assert exc.value.line == 3


def test_a_replacement_character_is_refused_never_passed_on() -> None:
    data = "ID,診断\n1,痛風\n2,\ufffd\ufffd\n".encode()
    with pytest.raises(encoding.EncodingRefused) as exc:
        encoding.decode(data)
    assert exc.value.line == 3 and "U+FFFD" in exc.value.message


def test_a_bom_followed_by_other_bytes_is_refused() -> None:
    with pytest.raises(encoding.EncodingRefused):
        encoding.detect(b"\xef\xbb\xbfID\n" + "痛風\n".encode("cp932"))


def test_the_readers_refuse_instead_of_guessing() -> None:
    with pytest.raises(intake.IntakeError) as sheet:
        intake.read_grid("a.csv", _read("mixed_utf8_cp932.csv"))
    assert sheet.value.code == "SHEET-READ" and "FORM-ENCODING" in sheet.value.message
    assert "line 4" in sheet.value.message
    with pytest.raises(charts.ChartError) as chart:
        charts._decode(_read("ambiguous_two_chars.csv"))
    assert chart.value.code == "CHART-TEXT" and "FORM-ENCODING" in chart.value.message


def test_utf8_with_unit_symbols_stays_utf8() -> None:
    """µ (C2 B5) and ° (C2 B0) are valid Big5 bytes too; a UTF-8 lab sheet must not be read as Big5."""
    for text in ("尿酸,480,µmol/L\n", "体温,37.5,°C\n", "x,1,µ\n", "name\nJosé Müller résumé\n"):
        assert encoding.detect(text.encode()) == ("utf-8", 1.0), text


def test_ascii_is_utf8() -> None:
    assert encoding.detect(b"id,value\r\n1,2\r\n") == ("utf-8", 1.0) and encoding.detect(b"") == ("utf-8", 1.0)


# ------------------------------------------------------------------------------------------------ round trips
_JA = (
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞ"
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモラリルレロンー"
    "患者氏名生年月日性別男女診断痛風高血圧糖尿病尿酸値単位受診日検査結果薬処方病院医師内科外科入院退院治療経過血液"
)
_ZH = (
    "的一是不了人我在有他這中大來上國個到說們為子和你地出道也時年得就那要下以生會自著去之過家學對可她裡後小麼心多天"
    "病歷號姓名出生日期性別診斷尿酸值單位就診醫院檢驗藥血男女患者科師痛風高壓糖腎臟肝臟心臟肺炎症狀發燒咳嗽頭"
)
_HW = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ"
_HW_FIRST = "".join(c for c in _HW if c not in "ｦｧｨｩｪｫｬｭｮｯｰﾞﾟﾝ")


def _sheet(rnd: random.Random, cell: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["id", "text", "n"])
    for i in range(rnd.randint(1, 4)):
        w.writerow([f"P{i:04d}", cell if i == 0 else "", rnd.randint(1, 999)])
    return buf.getvalue()


def _never_wrong(text: str, codec: str) -> bool:
    """The property: the detector reads ``text`` back exactly, or refuses; it never returns other text. True when
    it read it back."""
    try:
        got, _ = encoding.decode(text.encode(codec))
    except encoding.EncodingRefused:
        return False
    assert got == text
    return True


@pytest.mark.parametrize(("alphabet", "codec", "lo", "most_refused"), [(_JA, "cp932", 1, 0.0), (_ZH, "big5", 2, 0.05)])
def test_round_trip_sweep(alphabet: str, codec: str, lo: int, most_refused: float) -> None:
    """A seeded sweep of sheets of common Japanese (CP932) and Traditional Chinese (Big5) text: every one is read back
    exactly or refused, and refusals are rare."""
    rnd = random.Random(20261109)
    n = 1500
    read = sum(
        _never_wrong(_sheet(rnd, "".join(rnd.choice(alphabet) for _ in range(rnd.randint(lo, 10)))), codec)
        for _ in range(n)
    )
    assert read >= n * (1 - most_refused)


def test_half_width_kana_names_round_trip_or_are_refused() -> None:
    rnd = random.Random(7)

    def name() -> str:
        return rnd.choice(_HW_FIRST) + "".join(rnd.choice(_HW) for _ in range(rnd.randint(2, 5)))

    n = 1500
    read = sum(_never_wrong(_sheet(rnd, f"{name()} {name()}"), "cp932") for _ in range(n))
    assert read >= n * 0.85  # one short name in a sheet is often too little to tell from Big5: refused, not guessed


def test_round_trip_property() -> None:
    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is not a dev dependency yet (T-118 remains)")
    st = pytest.importorskip("hypothesis.strategies")

    def prop(case: tuple[str, str]) -> None:
        text, codec = case
        _never_wrong(f"id,text\r\n1,{text}\r\n", codec)

    hypothesis.settings(max_examples=500, deadline=None)(
        hypothesis.given(
            st.sampled_from([(_JA, "cp932"), (_ZH, "big5"), (_JA + _ZH, "utf-8")]).flatmap(
                lambda ac: st.tuples(st.text(st.sampled_from(list(ac[0])), min_size=1, max_size=40), st.just(ac[1]))
            )
        )(prop)
    )()


def test_detect_never_raises_anything_but_a_refusal_property() -> None:
    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is not a dev dependency yet (T-118 remains)")
    st = pytest.importorskip("hypothesis.strategies")

    def prop(data: bytes) -> None:
        try:
            text, codec = encoding.decode(data)
        except encoding.EncodingRefused:
            return
        assert "\ufffd" not in text and data.decode(codec) == text

    hypothesis.settings(max_examples=500, deadline=None)(hypothesis.given(st.binary(max_size=200))(prop))()
