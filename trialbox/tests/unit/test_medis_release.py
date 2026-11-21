"""Card 10B-2c (D-1257): the MEDIS ICD10対応標準病名マスター as MEDIS ships it.

The release itself is licensed and never in the repository. Every code, number and row below is INVENTED; only the
shapes are the release's (lane J read them off V5.18): tables without a header row, every field double-quoted,
Shift_JIS; the column titles in ``option/ttl_*.txt`` (the ICD-10 title written ＩＣＤ１０‐２０１３ with U+2010);
修飾語区分 a letter and seven digits; one 病名交換用コード shared by several rows; ICD-10 written undotted, with a
lower-case letter after it, or with a hyphen inside.

Each test fails on master ``d28f6c03`` unless it says it is a guard.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from adapter import licensed as lic
from adapter.sources.ssmix2 import source as reader
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_nights as nights
from tests import ssmix2_spec_kit as kit

P = kit.P1
# the release's own column titles (option/ttl_main.txt, ttl_mdfy.txt, ttl_idx.txt), as lane J read them
TTL_MAIN = [
    "変更区分",
    "病名管理番号",
    "病名表記",
    "病名表記カナ",
    "採択区分",
    "病名交換用コード",
    "ＩＣＤ１０‐２０１３",
    "ＩＣＤ１０‐２０１３複数分類コード",
    "予備１",
    "予備２",
    "レセ電算コード",
    "傷病名省略名称",
    "使用分野",
    "変更履歴番号",
    "更新日付",
    "移行先病名管理番号",
    "単独使用禁止区分",
    "保険請求外区分",
    "予備３",
    "予備４",
]
TTL_MDFY = [
    "変更区分",
    "修飾語管理番号",
    "修飾語表記",
    "修飾語表記カナ",
    "修飾語交換用コード",
    "接続位置区分",
    "修飾語区分",
    "排他グループコード",
    "レセ電算修飾語コード",
    "修飾語説明用ラベル",
]
TTL_IDX = [
    "索引用語",
    "対応用語コード",
    "病名修飾語区分",
    "かな漢字区分",
    "同義語区分",
    "異字体区分",
    "第１版採用表記区分",
    "言語区分（将来用予約）",
    "省略区分（将来用予約）",
]
README = "ICD10対応標準病名マスター　V9.87　2026年6月1日改訂\r\n（このファイルは試験用の作り物です）\r\n"


def _disease(change: str, no: str, name: str, adoption: str, exchange: str, icd: str, *, multi: str = "",
             receipt: str = "", successor: str = "") -> list[str]:  # fmt: skip
    row = [""] * 20
    row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7] = (
        change,
        no,
        name,
        "カナ",
        adoption,
        exchange,
        icd,
        multi,
    )
    row[10], row[12], row[15], row[16], row[17] = receipt, "01", successor, "00", "0"
    return row


#: invented rows in the release's shapes. YA01 is shared by a main name and its synonym; YA02 by a renamed entry (the
#: old 表記 deleted, the new one added); YA03 has only a deleted row, with a successor; YA04's ICD-10 carries a
#: lower-case letter; YA05's a hyphen; YA06 has none
DISEASES = [
    _disease("0", "80000001", "試験性肺炎", "1", "YA01", "J189", receipt="8800001"),
    _disease("0", "80000002", "試験性肺臓炎", "3", "YA01", "J189"),
    _disease("1", "80000003", "旧試験病", "1", "YA02", "K297"),
    _disease("3", "80000004", "新試験病", "1", "YA02", "K297", multi="K290"),
    _disease("1", "80000005", "廃止試験病", "1", "YA03", "M109", successor="80000004"),
    _disease("0", "80000006", "１型試験病", "1", "YA04", "E109a"),
    _disease("0", "80000007", "分類未定試験病", "1", "YA05", "A99-9"),
    _disease("5", "80000008", "無分類試験病", "2", "YA06", ""),
]
MODIFIERS = [
    ["0", "80010001", "左", "ヒダリ", "8101", "60", "A2000000", "", "", ""],
    ["0", "80010002", "下葉", "カヨウ", "8102", "50", "A1000000", "", "", ""],
    ["0", "80010003", "の疑い", "ノウタガイ", "8103", "1", "A8000000", "", "", ""],
    ["1", "80010004", "旧左", "キュウヒダリ", "8104", "95", "A2000001", "", "", ""],
]
INDEX = [
    ["試験性肺炎", "YA01", "1", "1", "0", "", "", "", ""],
    ["しけんせいはいえん", "YA01", "1", "2", "0", "", "", "", ""],
    ["試験肺炎", "YA01", "1", "1", "1", "", "", "", ""],
    ["左", "8101", "2", "1", "0", "", "", "", ""],
    ["試験", "YA01", "1", "1", "9", "", "", "", ""],
    ["試験", "YA02", "1", "1", "9", "", "", "", ""],
    ["廃語", "0000", "1", "1", "8", "", "", "", ""],
]


def _table(rows: list[list[str]]) -> bytes:
    """As the release writes a table: no header row, every field double-quoted, CRLF, Shift_JIS."""
    return "".join(",".join(f'"{c}"' for c in row) + "\r\n" for row in rows).encode("cp932")


def _release(version: str, released: str, diseases: list[list[str]] | None = None) -> dict[str, bytes]:
    """The invented release as another version: its readme's first line and the digits in its tables' names."""
    y, m, d = (int(x) for x in released.split("-"))
    readme = f"ICD10対応標準病名マスター　V{version}　{y}年{m}月{d}日改訂\r\n"
    digits = version.replace(".", "")
    return {name.replace("987", digits): data for name, data in _files(diseases, readme).items()}


def _files(diseases: list[list[str]] | None = None, readme: str = README) -> dict[str, bytes]:
    return {
        "byomei987/readme.txt": readme.encode("cp932"),
        "byomei987/main/nmain987.txt": _table(diseases or DISEASES),
        "byomei987/main/mdfy987.txt": _table(MODIFIERS),
        "byomei987/main/index987.txt": _table(INDEX),
        "byomei987/option/ttl_main.txt": _table([TTL_MAIN]),
        "byomei987/option/ttl_mdfy.txt": _table([TTL_MDFY]),
        "byomei987/option/ttl_idx.txt": _table([TTL_IDX]),
        "byomei987/dcmnts/spec.pdf": b"%PDF-1.4 not read",
    }


def _folder(tmp_path: Path, files: dict[str, bytes] | None = None) -> Path:
    for name, data in (files or _files()).items():
        f = tmp_path / "release" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return tmp_path / "release" / "byomei987"


def _zip(tmp_path: Path, files: dict[str, bytes] | None = None, name: str = "byomei987.zip") -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for member, data in (files or _files()).items():
            zf.writestr(member, data)
    (tmp_path / name).write_bytes(buf.getvalue())
    return tmp_path / name


def _tables(diseases: list[list[str]] | None = None) -> dict[str, dict[str, dict[str, str]]]:
    """What ``adapter.licensed.tables()`` gives a site that loaded the release above."""
    out: dict[str, dict[str, dict[str, str]]] = {"jlac10": {}, "yj": {}}
    for kind, data, titles in (("medis", _table(diseases or DISEASES), TTL_MAIN), ("medis_modifier", _table(MODIFIERS), TTL_MDFY)):  # fmt: skip
        parsed = lic.parse(kind, data, titles)
        out[kind] = {c["code"]: {k: c[k] for k in ("display", "target_system", "target_code", "extra")}
                     for c in parsed.concepts}  # fmt: skip
    return out


def _diagnosis(tmp_path: Path, code: str, name: str, zprs: list[str], tables: Any = None, icd: str = "") -> Any:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    prb = nights.prb("DX01", code=code, name=name, f10=f"{icd}^^I10" if icd else "")
    nights.snapshot(st, f"{nights.D1}090000000", [prb, *zprs])
    src = Ssmix2Source(st.root, licensed=tables or _tables(), today="20261231")
    (row,) = list(src.rows("diagnosis", "diagnosis", None, None))
    return row


# ------------------------------------------------------------------ R4: the release's own titles
def test_the_releases_own_titles_place_the_icd10_and_the_receipt_code() -> None:
    """ＩＣＤ１０‐２０１３ is written with U+2010, which NFKC leaves: on master the ICD-10 column was lost."""
    parsed = lic.parse("medis", _table(DISEASES), TTL_MAIN)
    by = {c["code"]: c for c in parsed.concepts}
    assert (by["YA01"]["target_code"], by["YA01"]["target_system"]) == ("J189", lic.ICD10_WHO)
    extra = json.loads(by["YA01"]["extra"])
    assert extra["receipt_code"] == "8800001" and extra["adoption"] == "1" and extra["no_solo"] == "00"
    assert json.loads(by["YA02"]["extra"])["multi_class"] == "K290"  # its own column, never taken for the ICD-10


def test_a_title_hyphen_is_normalised_and_a_value_never_is() -> None:
    assert lic._key("ＩＣＤ１０‐２０１３") == lic._key("ICD10-2013") == lic._key("ICD10−2013")
    by = {c["code"]: c for c in lic.parse("medis", _table(DISEASES), TTL_MAIN).concepts}
    assert by["YA05"]["target_code"] == "A99-9" and by["YA04"]["target_code"] == "E109a"  # kept as the release has it


# ------------------------------------------------------------------ R2: rows and concepts
def test_every_row_of_the_disease_table_is_kept_and_an_exchange_code_is_a_concept() -> None:
    """On master a 病名交換用コード on two different rows was "given twice with different content" and neither row
    was read. It is the release's design: the rows are told apart by their 病名管理番号."""
    parsed = lic.parse("medis", _table(DISEASES), TTL_MAIN)
    assert (parsed.rows, parsed.current, parsed.skipped) == (8, 6, [])
    by = {c["code"]: c for c in parsed.concepts}
    assert sorted(by) == ["YA01", "YA02", "YA03", "YA04", "YA05", "YA06"]
    assert by["YA01"]["display"] == "試験性肺炎"  # 採択区分 1 owns the code; 3 is a synonym that borrows it
    assert [r["no"] for r in json.loads(by["YA01"]["extra"])["rows"]] == ["80000001", "80000002"]
    renamed = json.loads(by["YA02"]["extra"])
    assert (by["YA02"]["display"], renamed["management_no"], renamed["change"]) == ("新試験病", "80000004", "3")
    gone = json.loads(by["YA03"]["extra"])
    assert (gone["change"], gone["successor"]) == ("1", "80000004")  # stored and marked, never skipped
    rows = lic.medis_rows({c["code"]: c for c in parsed.concepts})
    assert len(rows) == 8 and rows["80000002"]["exchange"] == "YA01" and rows["80000003"]["change"] == "1"


def test_one_management_number_on_two_different_rows_is_read_for_neither() -> None:
    twice = [*DISEASES, _disease("0", "80000001", "別の表記", "1", "YA09", "J180")]
    parsed = lic.parse("medis", _table(twice), TTL_MAIN)
    assert "80000001" not in lic.medis_rows({c["code"]: c for c in parsed.concepts})
    assert any("病名管理番号 80000001 appears twice with different content" in why for _n, why in parsed.skipped)


def test_current_rows_of_one_code_that_disagree_on_icd10_make_the_code_unknown(tmp_path: Path) -> None:
    odd = [*DISEASES, _disease("0", "80000009", "別分類試験性肺炎", "3", "YA01", "J180")]
    parsed = lic.parse("medis", _table(odd), TTL_MAIN)
    concept = next(c for c in parsed.concepts if c["code"] == "YA01")
    assert concept["target_code"] == "" and json.loads(concept["extra"])["icd_conflict"] == "1"
    assert any("code YA01: its current rows disagree on ICD-10" in why for _n, why in parsed.skipped)
    assert _diagnosis(tmp_path, "YA01", "試験性肺炎", [], _tables(odd))["suspected"] == "U"


@pytest.mark.parametrize(
    ("code", "name", "want"),
    [
        ("YA01", "試験性肺炎", ""),  # the main name
        ("YA01", "試験性肺臓炎", ""),  # the synonym's own 表記: a current row of the code
        ("80000002", "試験性肺臓炎", ""),  # by its own 病名管理番号
        ("YA02", "新試験病", ""),  # the current row of a renamed entry
        ("YA02", "旧試験病", "U"),  # the old 表記: its row is deleted
        ("80000003", "旧試験病", "U"),
        ("YA03", "廃止試験病", "U"),  # every row of the code is deleted
        ("YA01", "新試験病", "U"),  # another code's name
    ],
)
def test_a_diagnosis_by_exchange_code_is_read_against_every_current_row_of_the_code(
    tmp_path: Path, code: str, name: str, want: str
) -> None:
    assert _diagnosis(tmp_path, code, name, [])["suspected"] == want


# ------------------------------------------------------------------ R1: 修飾語区分
@pytest.mark.parametrize(
    ("value", "cls"),
    [("A2000000", "2"), ("A9000000", "9"), ("22000000", "2"), ("Ａ２００００００", "2"), ("A0000000", ""),
     ("AA000000", ""), ("A200000", ""), ("A20000000", ""), ("", "")],
)  # fmt: skip
def test_the_class_is_the_second_of_eight_characters(value: str, cls: str) -> None:
    assert lic.modifier_class(value) == cls


def test_a_modifier_of_the_releases_shape_is_recognised(tmp_path: Path) -> None:
    """Every 修飾語区分 of the release is a letter and seven digits; master read only eight digits, so with the real
    master every diagnosis that carried a modifier read unknown."""
    zpr = "ZPR|80010001^左^MDCDX2|80000001^試験性肺炎^MDCDX2||8101^左^MDCDX2|YA01^試験性肺炎^MDCDX2"
    assert _diagnosis(tmp_path / "a", "80000001", "左試験性肺炎", [zpr])["suspected"] == ""
    doubt = "ZPR||80000001^試験性肺炎^MDCDX2|80010003^の疑い^MDCDX2"
    assert _diagnosis(tmp_path / "b", "80000001", "試験性肺炎の疑い", [doubt])["suspected"] == "Y"
    retired = "ZPR|80010004^旧左^MDCDX2|80000001^試験性肺炎^MDCDX2"
    assert _diagnosis(tmp_path / "c", "80000001", "旧左試験性肺炎", [retired])["suspected"] == "U"
    stored = json.loads(_tables()["medis_modifier"]["80010001"]["extra"])
    assert (stored["class"], stored["modifier_class"], stored["position"]) == ("2", "A2000000", "60")


# ------------------------------------------------------------------ the ICD-10 forms of the release
@pytest.mark.parametrize(
    ("value", "read"),
    [("J189", "J18.9"), ("A1500", "A15.00"), ("I10", "I10"), ("E109a", "E10.9"), ("A99-9", ""), ("", ""),
     ("A15.0", "A15.0"), ("e149", "E14.9")],
)  # fmt: skip
def test_the_masters_icd10_forms(value: str, read: str) -> None:
    """Lane J's ruling: a lower-case letter after the code is a Japanese sub-classification (compared without it,
    the store keeps the original); the form with a hyphen inside is not an ICD-10 code until someone shows what it
    means."""
    assert reader.medis_icd(value) == read


def test_the_icd10_of_a_diagnosis_comes_from_its_own_row_by_either_code(tmp_path: Path) -> None:
    by_exchange = _diagnosis(tmp_path / "a", "YA04", "１型試験病", [])
    by_number = _diagnosis(tmp_path / "b", "80000006", "１型試験病", [])
    assert (by_exchange["icd10"], by_number["icd10"]) == ("E10.9", "E10.9")
    hyphen = _diagnosis(tmp_path / "c", "YA05", "分類未定試験病", [])
    assert (hyphen["icd10"], hyphen["suspected"]) == ("", "U")  # the hyphen form: unknown
    assert _diagnosis(tmp_path / "d", "YA01", "試験性肺炎", [], icd="J189")["suspected"] == ""
    assert _diagnosis(tmp_path / "e", "YA01", "試験性肺炎", [], icd="J180")["suspected"] == "U"  # not the master's


# ------------------------------------------------------------------ the deep review of #1238: M2, M3, L6
def test_a_master_icd10_the_reader_cannot_read_never_confirms_the_hospitals_own(tmp_path: Path) -> None:
    """M2: the master writes ``A99-9`` for the disease and the message says ``B99``. Nothing was compared, so
    nothing is confirmed (before: the check was skipped and the diagnosis read confirmed B99)."""
    row = _diagnosis(tmp_path, "YA05", "分類未定試験病", [], icd="B99")
    assert row["suspected"] == "U"
    assert _diagnosis(tmp_path / "g", "YA05", "分類未定試験病", [])["suspected"] == "U"  # nor without one of its own


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("80000003", "旧試験病"),  # a deleted row, by its 病名管理番号
        ("YA03", "廃止試験病"),  # a code every row of which is deleted
        ("YA01", "試験性肺炎"),  # a code whose current rows disagree on ICD-10
        ("80000001", "試験性肺炎"),  # a row of that code, by its number
    ],
)
def test_with_the_disease_table_alone_only_a_current_agreeing_row_gives_an_icd10(
    tmp_path: Path, code: str, name: str
) -> None:
    """M3: the disease table alone is loaded (the ICD-10 look-up, D-137; no modifier table, so no master rule). A
    deleted number, an all-deleted code and a conflicting code each gave ('A', '', its ICD-10). The successor of a
    deleted row is not followed: unknown, and no ICD-10."""
    odd = [*DISEASES, _disease("0", "80000009", "別分類試験性肺炎", "3", "YA01", "J180")]
    tables = {**_tables(odd), "medis_modifier": {}}
    row = _diagnosis(tmp_path, code, name, [], tables)
    assert (row["suspected"], row["icd10"]) == ("U", "")


def test_with_the_disease_table_alone_a_current_row_still_gives_its_icd10(tmp_path: Path) -> None:
    """Guard for M3."""
    tables = {**_tables(), "medis_modifier": {}}
    for n, (code, name) in enumerate([("YA01", "試験性肺炎"), ("80000004", "新試験病"), ("YA02", "新試験病")]):
        row = _diagnosis(tmp_path / str(n), code, name, [], tables)
        assert (row["suspected"], row["icd10"]) == ("", "J18.9" if code == "YA01" else "K29.7"), code


def test_the_masters_suffix_form_is_one_code_with_the_plain_form(tmp_path: Path) -> None:
    """L6: ``E109`` and ``E109a`` on two current rows of one code are no conflict, and a hospital that writes the
    master's own ``E109a`` in PRB-10 is not contradicting the master."""
    both = [*DISEASES, _disease("0", "80000010", "１型試験病（別表記）", "3", "YA04", "E109")]
    concept = next(c for c in lic.parse("medis", _table(both), TTL_MAIN).concepts if c["code"] == "YA04")
    assert "icd_conflict" not in json.loads(concept["extra"]) and concept["target_code"] == "E109a"
    row = _diagnosis(tmp_path, "YA04", "１型試験病", [], icd="E109a")
    assert (row["suspected"], row["icd10"]) == ("", "E10.9")
    assert lic.icd_comparable("E10.9") == lic.icd_comparable("E109a") == "E109"


# ------------------------------------------------------------------ the release as MEDIS ships it
WANT = {"version": "9.87", "released": "2026-06-01", "disease_rows": 8, "disease_current": 6, "modifier_rows": 4,
        "index_rows": 7, "skipped": []}  # fmt: skip


def test_check_release_reads_a_folder_and_a_zip_alike_and_writes_nothing(tmp_path: Path) -> None:
    folder, archive = lic.check_release(_folder(tmp_path)), lic.check_release(_zip(tmp_path))
    assert {k: v for k, v in folder.items() if k != "sha256"} == WANT
    assert {k: v for k, v in archive.items() if k != "sha256"} == WANT
    assert len(folder["sha256"]) == len(archive["sha256"]) == 64
    assert sorted(p.name for p in tmp_path.iterdir()) == ["byomei987.zip", "release"]  # nothing extracted


def test_a_title_file_with_one_title_on_each_line_is_read_too(tmp_path: Path) -> None:
    files = _files()
    files["byomei987/option/ttl_mdfy.txt"] = "".join(f'"{t}"\r\n' for t in TTL_MDFY).encode("cp932")
    assert lic.check_release(_zip(tmp_path, files))["modifier_rows"] == 4


def test_skipped_rows_name_their_table_line_and_reason(tmp_path: Path) -> None:
    bad = [*DISEASES, _disease("0", "80000020", "符号不正", "1", "ya", "J189")]
    got = lic.check_release(_zip(tmp_path, _files(bad)))
    assert got["disease_rows"] == 8 and [(t, n) for t, n, _why in got["skipped"]] == [("medis", 9)]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda f: f.pop("byomei987/main/mdfy987.txt"), "LIC-RELEASE-MISSING"),
        (lambda f: f.pop("byomei987/option/ttl_idx.txt"), "LIC-RELEASE-MISSING"),
        (lambda f: f.update({"other/NMAIN986.TXT": f["byomei987/main/nmain987.txt"]}), "LIC-RELEASE-TWICE"),
        (lambda f: f.update({"byomei987/readme.txt": "標準病名マスター 最新版\r\n".encode("cp932")}), "LIC-RELEASE-README"),
        (lambda f: f.update({"byomei987/option/ttl_main.txt": _table([TTL_MAIN[:3], TTL_MAIN[3:]])}),
         "LIC-RELEASE-TITLES"),
    ],
)  # fmt: skip
def test_a_release_that_is_not_whole_is_refused_with_its_reason(tmp_path: Path, change: Any, code: str) -> None:
    files = _files()
    change(files)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip(tmp_path, files))
    assert exc.value.code == code


def test_an_archive_is_read_by_base_names_only_and_within_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No path is taken from a member name: a member that tries to leave the folder is only its base name, anything
    that is not a release file is never opened, and nothing is written to disk."""
    files = {name.replace("byomei987/", "../../outside/"): data for name, data in _files().items()}
    files["../../outside/evil.sh"] = b"never read"
    assert {k: v for k, v in lic.check_release(_zip(tmp_path, files)).items() if k != "sha256"} == WANT
    assert not (tmp_path.parent / "outside").exists() and not (tmp_path / "outside").exists()
    (tmp_path / "not.zip").write_bytes(b"this is not an archive")
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(tmp_path / "not.zip")
    assert exc.value.code == "LIC-RELEASE-ARCHIVE"
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(tmp_path / "nowhere")
    assert exc.value.code == "LIC-RELEASE-SOURCE"
    monkeypatch.setattr(lic, "RELEASE_MAX_FILE", 100)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip(tmp_path))
    assert exc.value.code == "LIC-RELEASE-SIZE"
    monkeypatch.setattr(lic, "RELEASE_MAX_MEMBERS", 3)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip(tmp_path))
    assert exc.value.code == "LIC-RELEASE-SIZE"


def test_load_release_loads_the_three_tables_at_once_and_status_says_what_is_loaded(tmp_path: Path) -> None:
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        report = lic.load_release(st, _zip(tmp_path), by="steward", audit_dir=tmp_path / "audit")
        assert {k: v for k, v in report.items() if k != "sha256"} == WANT
        assert report == lic.check_release(tmp_path / "byomei987.zip")  # one code path
        status = {s["kind"]: s for s in st.status(all_lists=True)}
        assert [s["kind"] for s in st.status()] == list(lic.KINDS)  # the index is listed only when asked
        for kind, rows, table_rows, current in (("medis", 6, 8, 6), ("medis_modifier", 4, 4, 3), ("medis_index", 7, 7, 7)):  # fmt: skip
            s = status[kind]
            assert (s["state"], s["version"], s["released"], s["loaded_by"]) == (
                "loaded",
                "9.87",
                "2026-06-01",
                "steward",
            )
            assert (s["rows"], s["table_rows"], s["current_rows"], s["sha256"]) == (
                rows,
                table_rows,
                current,
                report["sha256"],
            )
            assert s["loaded_at"]
        # the index: a term to its 対応用語コード; a term is not unique, the pair is; "0000" is given, never resolved
        assert [(r["code"], r["target_kind"], r["synonym"]) for r in st.lookup_term("試験性肺炎")] == [
            ("YA01", "1", "0")
        ]
        assert [r["code"] for r in st.lookup_term("試験")] == ["YA01", "YA02"]
        assert [(r["code"], r["target_kind"]) for r in st.lookup_term("左")] == [("8101", "2")]
        assert [(r["code"], r["synonym"]) for r in st.lookup_term("廃語")] == [("0000", "8")]
        assert st.lookup_term("どこにもない") == []
    finally:
        st.close()
    given = lic.tables()
    assert sorted(given) == sorted(lic.KINDS) and len(given["medis"]) == 6  # the index is not carried to readers
    assert lic.loaded_at_of(given)
    row = _diagnosis(tmp_path, "YA01", "試験性肺臓炎", [], given)
    assert (row["suspected"], row["icd10"]) == ("", "J18.9")


def test_a_release_whose_third_table_fails_in_the_database_loads_nothing(tmp_path: Path) -> None:
    """All or nothing, where it matters: the three tables parse, the first two are written, and the database
    refuses a row of the third (a constraint added here for the test). Nothing of the release is loaded, and the
    failure is a ``LicensedError`` (deep review of #1238: the earlier test failed at parse time, before any write)."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        st.db.execute("ALTER TABLE concept ADD CONSTRAINT refuse_one_term CHECK (display <> '廃語')")
        with pytest.raises(lic.LicensedError) as exc:
            lic.load_release(st, _zip(tmp_path), by="steward")
        assert exc.value.code == "LIC-STORE"
        assert {s["state"] for s in st.status(all_lists=True)} == {"not_loaded"}
        assert st.db.fetchval("SELECT count(*) FROM concept") == 0 and st.releases() == []
    finally:
        st.close()


def test_a_release_with_a_table_that_cannot_be_read_loads_nothing(tmp_path: Path) -> None:
    """The modifier table has no row with a code: refused before anything is written."""
    lic._CACHE.clear()
    files = _files()
    files["byomei987/main/mdfy987.txt"] = _table([["0", "bad", "左", "ヒダリ", "8101", "60", "A2000000", "", "", ""]])
    st = lic.TermStore()
    try:
        with pytest.raises(lic.LicensedError) as exc:
            lic.load_release(st, _zip(tmp_path, files), by="steward")
        assert exc.value.code == "LIC-EMPTY" and "mdfy987.txt" in exc.value.message
        assert {s["state"] for s in st.status(all_lists=True)} == {"not_loaded"}
    finally:
        st.close()


def test_a_single_file_still_loads_as_before(tmp_path: Path) -> None:
    """Guard: ``load`` with ``--columns`` (how a site loaded a table before the release loader)."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        out = st.load("medis", _table(DISEASES), version="9.87", source="nmain987.txt", by="admin", columns=TTL_MAIN)
        assert (out["rows"], out["skipped"]) == (6, [])
        s = next(s for s in st.status() if s["kind"] == "medis")
        assert (s["table_rows"], s["current_rows"], s["released"]) == (8, 6, "")
    finally:
        st.close()


# ------------------------------------------------------------------ R5: the release's character set is declared
def _also_utf8() -> str:
    """Two kanji whose Shift_JIS bytes are also valid UTF-8: such a line is to be expected somewhere in a table of a
    hundred thousand lines, and the shared detector reads it as two character sets mixed."""
    for lead in range(0xE1, 0xEB):  # a Shift_JIS lead byte that opens a three-byte UTF-8 sequence
        for trail in range(0x80, 0xC0):
            for second in range(0x89, 0xA0):  # the second kanji's lead byte: a UTF-8 continuation byte too
                raw = bytes([lead, trail, second, 0x41])  # its trail byte is ASCII
                try:
                    text = raw.decode("cp932")
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if len(text) == 2 and text.encode("cp932") == raw:
                    return text
    raise AssertionError("no such pair")


def test_a_shift_jis_line_that_is_also_valid_utf8_does_not_refuse_the_release(tmp_path: Path) -> None:
    """Found by lane J on the real release: one line of the index table. The publisher declares Shift_JIS, so the
    release is read as that, strictly, and the detector is not asked."""
    from tb_common import encoding

    term = _also_utf8()
    files = _files()
    files["byomei987/main/index987.txt"] = _table([*INDEX, [term, "YA01", "1", "1", "0", "", "", "", ""]])
    with pytest.raises(encoding.EncodingRefused):  # what the detector says of this table (unchanged for others)
        encoding.decode(files["byomei987/main/index987.txt"], ("cp932",))
    assert lic.check_release(_zip(tmp_path, files))["index_rows"] == 8
    with pytest.raises(lic.LicensedError):  # a single file with no declared set still goes through the detector
        lic.parse("medis_index", files["byomei987/main/index987.txt"], TTL_IDX)
    assert lic.parse("medis_index", files["byomei987/main/index987.txt"], TTL_IDX, "cp932").rows == 8


def test_a_byte_shift_jis_does_not_hold_refuses_the_release_with_its_line(tmp_path: Path) -> None:
    files = _files()
    good = _table(INDEX)
    files["byomei987/main/index987.txt"] = good + b'"\xfd\xfe","YA01","1","1","0","","","",""\r\n'
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip(tmp_path, files))
    assert exc.value.code == "LIC-ENCODING" and "index987.txt" in exc.value.message
    assert f"(line {len(INDEX) + 1})" in exc.value.message


# ================================================================== the deep review of #1238: the store
def _active(st: lic.TermStore) -> dict[str, int]:
    rows = st.db.fetchdicts("SELECT kind, count(*) AS n FROM release WHERE active GROUP BY kind")
    return {r["kind"]: int(r["n"]) for r in rows}


def test_one_load_at_a_time_and_one_active_release_of_a_list(tmp_path: Path) -> None:
    """M5: two loads at once left two active releases of one list. A load takes the store's lock for its
    transaction: a second load waits for the first to finish; and the database itself holds one active release of
    a list (a unique partial index), whatever a writer does."""
    import threading

    lic._CACHE.clear()
    first, second = lic.TermStore(), lic.TermStore()
    done = threading.Event()
    try:
        lic.load_release(first, _zip(tmp_path, _release("9.86", "2026-01-01"), "a.zip"), by="one")

        def load() -> None:
            lic.load_release(second, _zip(tmp_path, _release("9.87", "2026-06-01"), "b.zip"), by="two")
            done.set()

        with first.db.transaction() as tx:  # a load in progress, as the store sees it
            tx.execute("SELECT pg_advisory_xact_lock(hashtext('terminology.load'), hashtext(current_schema()))")
            thread = threading.Thread(target=load)
            thread.start()
            assert not done.wait(1.0)  # the second load waits
        thread.join(30)
        assert done.is_set()
        assert _active(first) == {"medis": 1, "medis_modifier": 1, "medis_index": 1}
        assert {s["version"] for s in first.status(all_lists=True) if s["kind"].startswith("medis")} == {"9.87"}
        with pytest.raises(Exception, match="release_one_active"):
            first.db.execute("UPDATE release SET active = TRUE WHERE kind = 'medis'")
    finally:
        first.close()
        second.close()


def test_two_loads_at_once_leave_one_release(tmp_path: Path) -> None:
    """The reviewer's run: two stores, two threads, different releases. One release is active for each list, and
    the lists a reader is given are that release's and no other's."""
    import threading

    lic._CACHE.clear()
    only_b = [*DISEASES, _disease("0", "80000011", "追加試験病", "1", "YB01", "J180")]
    zips = [_zip(tmp_path, _release("9.86", "2026-01-01"), "a.zip"),
            _zip(tmp_path, _release("9.86", "2026-01-01", only_b), "b.zip")]  # fmt: skip
    stores = [lic.TermStore(), lic.TermStore()]
    try:
        for _round in range(3):
            threads = [
                threading.Thread(target=lic.load_release, args=(st, z), kwargs={"by": "x"})
                for st, z in zip(stores, zips, strict=True)
            ]
            for th in threads:
                th.start()
            for th in threads:
                th.join(60)
            assert _active(stores[0]) == {"medis": 1, "medis_modifier": 1, "medis_index": 1}
            lic._CACHE.clear()
            rows = next(s for s in stores[0].status() if s["kind"] == "medis")["rows"]
            assert len(lic.tables()["medis"]) == rows
    finally:
        for st in stores:
            st.close()


def test_loading_again_keeps_the_release_before_and_drops_the_codes_of_older_ones(tmp_path: Path) -> None:
    """L7: every load kept every earlier release's rows (about 140,000 for each load of the real release). The codes
    of the release a load replaces stay; those of older ones go. The record of what was loaded stays whole."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        for n, version in enumerate(("9.85", "9.86", "9.87")):
            lic.load_release(st, _zip(tmp_path, _release(version, f"2026-0{n + 1}-01"), f"{n}.zip"), by="steward")
        releases = st.releases("medis")
        assert [(r["version"], bool(r["active"])) for r in releases] == [
            ("9.85", False),
            ("9.86", False),
            ("9.87", True),
        ]
        held = {
            r["version"]: int(st.db.fetchval("SELECT count(*) FROM concept WHERE release_id = ?", (r["id"],)))
            for r in releases
        }
        assert held == {"9.85": 0, "9.86": 6, "9.87": 6}
    finally:
        st.close()


def test_an_older_release_is_refused_unless_asked_for(tmp_path: Path) -> None:
    """L5: an older release loaded over a newer one silently. Refused by the check and by the load; loaded only
    with ``allow_older`` (which no page passes)."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        lic.load_release(st, _zip(tmp_path, _release("9.87", "2026-06-01"), "new.zip"), by="steward")
        old = _zip(tmp_path, _release("9.86", "2026-01-01"), "old.zip")
        with pytest.raises(lic.LicensedError) as exc:
            lic.load_release(st, old, by="steward")
        assert exc.value.code == "LIC-RELEASE-OLDER" and "9.86" in exc.value.message
        with pytest.raises(lic.LicensedError) as exc:
            lic.check_release(old, st)
        assert exc.value.code == "LIC-RELEASE-OLDER"
        assert lic.check_release(old)["version"] == "9.86"  # without a store there is nothing to compare with
        assert next(s for s in st.status() if s["kind"] == "medis")["version"] == "9.87"
        lic.load_release(st, old, by="steward", allow_older=True)
        assert next(s for s in st.status() if s["kind"] == "medis")["version"] == "9.86"
        lic.check_release(_zip(tmp_path, _release("9.86", "2026-01-01"), "same.zip"), st)  # the same: not older
    finally:
        st.close()


@pytest.mark.parametrize(
    ("first", "code"),
    [
        ("これは ICD10対応標準病名マスター　V9.87　2026年6月1日改訂 ではありません", "LIC-RELEASE-README"),
        ("前の版は V9.87 2026年6月1日", "LIC-RELEASE-README"),
        ("ICD10対応標準病名マスター　V9.87　2026年13月40日改訂", "LIC-RELEASE-README"),
        ("ICD10対応標準病名マスター　V9.86　2026年6月1日改訂", "LIC-RELEASE-VERSION"),  # its tables are named 987
    ],
)
def test_the_readme_is_not_trusted_beyond_its_own_title_line(tmp_path: Path, first: str, code: str) -> None:
    """L5: the version is read only from a first line that is the release's title, and the digits in the tables'
    names must be that version's."""
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip(tmp_path, _files(readme=first + "\r\n")))
    assert exc.value.code == code


def _zip_with(tmp_path: Path, name: str, data: bytes) -> Path:
    files = _files()
    files[name] = data
    return _zip(tmp_path, files)


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (["0", "80000012", "試験\x00病", "カナ", "1", "YC01", "J189"] + [""] * 13, "LIC-CHARACTER"),  # a NUL
        (["0", "80000012", "長" * 4000, "カナ", "1", "YC01", "J189"] + [""] * 13, "LIC-LONG"),  # breaks the index
    ],
)
def test_what_the_database_would_refuse_is_refused_by_the_check(tmp_path: Path, row: list[str], code: str) -> None:
    """L4: a NUL in a term passed ``check_release`` and ``load_release`` raised a database error; a term of 4,000
    characters broke the index. Both are refused where the table is read, by the check and the load alike."""
    source = _zip_with(tmp_path, "byomei987/main/nmain987.txt", _table([*DISEASES, row]))
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(source)
    assert exc.value.code == code and "nmain987.txt" in exc.value.message
    st = lic.TermStore()
    try:
        with pytest.raises(lic.LicensedError) as exc:
            lic.load_release(st, source, by="steward")
        assert exc.value.code == code
    finally:
        st.close()


def test_a_corrupt_member_of_the_archive_is_a_refusal_with_a_code(tmp_path: Path) -> None:
    """L4: a corrupt deflate stream raised ``zlib.error``."""
    source = _zip(tmp_path)
    raw = bytearray(source.read_bytes())
    with zipfile.ZipFile(source) as zf:
        info = zf.getinfo("byomei987/main/nmain987.txt")
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    for i in range(start, start + min(40, info.compress_size)):
        raw[i] ^= 0xFF
    source.write_bytes(bytes(raw))
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(source)
    assert exc.value.code == "LIC-RELEASE-ARCHIVE"


def test_user_defined_shift_jis_bytes_refuse_the_release(tmp_path: Path) -> None:
    """L7: the bytes F0 40 are the user-defined area: Python reads them as a private-use character, which no
    release's text is."""
    table = _table(DISEASES).replace("試験性肺炎".encode("cp932"), b"\xf0\x40", 1)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(_zip_with(tmp_path, "byomei987/main/nmain987.txt", table))
    assert exc.value.code == "LIC-ENCODING" and "line 1" in exc.value.message


def test_a_table_of_too_many_rows_is_refused_within_bounded_memory(tmp_path: Path) -> None:
    """M6: a table of 16 MB of short rows (some tens of KB as a zip) was read into about forty times its size.
    A member is at most 16 MB, a table at most 400,000 rows, read row by row; the rows not read are listed up to a
    bound. The peak memory of the refusal is measured."""
    import tracemalloc

    assert (lic.RELEASE_MAX_FILE, lic.MAX_ROWS) == (16 * 1024 * 1024, 400_000)
    line = b'"x"\r\n'
    hostile = line * (lic.RELEASE_MAX_FILE // len(line))
    source = _zip_with(tmp_path, "byomei987/main/nmain987.txt", hostile)
    assert source.stat().st_size < 200_000
    tracemalloc.start()
    try:
        with pytest.raises(lic.LicensedError) as exc:
            lic.check_release(source)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert exc.value.code == "LIC-ROWS"
    assert peak < 4 * len(hostile), peak  # the zip, the table's bytes, its text; never a list of its rows
    over = _zip_with(tmp_path, "byomei987/main/nmain987.txt", hostile + line)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(over)
    assert exc.value.code == "LIC-RELEASE-SIZE"


def test_rows_not_read_are_listed_up_to_a_bound(tmp_path: Path) -> None:
    bad = [["0", f"8{n:07d}", "名", "カナ", "1", "", "J189"] + [""] * 13 for n in range(lic.MAX_SKIPPED + 500)]
    parsed = lic.parse("medis", _table([*DISEASES, *bad]), TTL_MAIN, "cp932")
    assert len(parsed.skipped) == lic.MAX_SKIPPED + 1
    assert parsed.skipped[-1] == (0, "500 more rows were not read (not listed)")


def test_a_symlink_in_a_release_folder_is_never_followed(tmp_path: Path) -> None:
    """A file or a folder of the release that is a link to somewhere else is not read: the release then lacks it."""
    folder = _folder(tmp_path)
    table = folder / "main" / "nmain987.txt"
    outside = tmp_path / "elsewhere.txt"
    outside.write_bytes(table.read_bytes())
    table.unlink()
    table.symlink_to(outside)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(folder)
    assert exc.value.code == "LIC-RELEASE-MISSING" and "nmain" in exc.value.message
    table.unlink()
    (tmp_path / "away").mkdir()
    (tmp_path / "away" / "nmain987.txt").write_bytes(outside.read_bytes())
    (folder / "linked").symlink_to(tmp_path / "away", target_is_directory=True)
    with pytest.raises(lic.LicensedError) as exc:
        lic.check_release(folder)
    assert exc.value.code == "LIC-RELEASE-MISSING"


def test_a_store_that_cannot_be_reached_is_not_a_store_with_nothing_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: ``tables()`` gave empty lists when the store was down, so a night read the diagnoses without the master
    and no later night sent them again. The lists say when they are empty for that reason, and the SS-MIX2 reader
    does not read then (the night is held). No store configured at all is a site that loaded nothing: read."""
    from tb_common.db import DatabaseError

    class Down:
        def __init__(self, url: str | None = None) -> None:
            raise DatabaseError("cannot reach the trial database: OperationalError")

    lic._CACHE.clear()
    monkeypatch.setattr(lic, "TermStore", Down)
    given = lic.tables("postgresql://configured.invalid/trialbox")
    assert given == {k: {} for k in lic.KINDS} and lic.unavailable(given)
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    nights.snapshot(st, f"{nights.D1}090000000", [nights.prb("DX01")])
    with pytest.raises(lic.LicensedError) as exc:
        Ssmix2Source(st.root, licensed=given, today="20261231")
    assert exc.value.code == "LIC-STORE-DOWN"
    monkeypatch.delenv("TB_DB_URL")
    none = lic.tables()
    assert not lic.unavailable(none) and not lic.unavailable(dict(given))
    assert (
        len(list(Ssmix2Source(st.root, licensed=none, today="20261231").rows("diagnosis", "diagnosis", None, None)))
        == 1
    )


def test_the_lists_a_reader_is_given_are_one_view_of_the_store(tmp_path: Path) -> None:
    """L7: the four lists and the load time came from separate statements. They are one statement's answer, and it
    is what the store's own methods say."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        lic.load_release(st, _zip(tmp_path), by="steward")
        given = lic.tables()
        assert given == {k: st.concepts(k) for k in lic.KINDS}
        assert lic.loaded_at_of(given) == max(s["loaded_at"] for s in st.status())
        assert st.snapshot(["medis_index"])[0]["medis_index"] == st.concepts("medis_index")
    finally:
        st.close()


def test_the_release_that_is_loaded_is_not_loaded_again_unasked(tmp_path: Path) -> None:
    """A second load of the same release was accepted silently and kept a whole inactive copy. It is refused by its
    sha256, which ``status`` gives; asked for explicitly, it loads and the copy it replaces is not kept."""
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        first = lic.load_release(st, _zip(tmp_path, _release("9.86", "2026-01-01"), "a.zip"), by="steward")
        source = _zip(tmp_path, _release("9.87", "2026-06-01"), "b.zip")
        report = lic.load_release(st, source, by="steward")
        assert next(s for s in st.status() if s["kind"] == "medis")["sha256"] == report["sha256"] != first["sha256"]
        with pytest.raises(lic.LicensedError) as exc:
            lic.load_release(st, source, by="steward")
        assert exc.value.code == "LIC-RELEASE-LOADED" and "9.87" in exc.value.message
        lic.load_release(st, source, by="steward", allow_reload=True)
        held = [
            (r["version"], int(st.db.fetchval("SELECT count(*) FROM concept WHERE release_id = ?", (r["id"],))))
            for r in st.releases("medis")
        ]
        assert held == [("9.86", 6), ("9.87", 0), ("9.87", 6)]  # the release before is still the one kept
    finally:
        st.close()


def test_an_index_term_is_stored_and_asked_for_under_one_key(tmp_path: Path) -> None:
    """One function, ``index_key``, for the stored term and the query: NFKC, every blank removed, upper case. A term
    with lower-case Latin letters was never found by a caller that asked in upper case. The term comes back as the
    release writes it; two writings of one term for one code are both kept."""
    assert lic.index_key(" ｃｏｖｉｄ－１９　肺炎 ") == lic.index_key("COVID-19肺炎") == "COVID-19肺炎"
    assert lic.index_key("") == ""
    files = _files()
    files["byomei987/main/index987.txt"] = _table(
        [*INDEX, ["ｃｏｖｉｄ試験 肺炎", "YA01", "1", "1", "1", "", "", "", ""],
         ["Covid試験肺炎", "YA01", "1", "1", "1", "", "", "", ""], ["IgA試験症", "YA02", "1", "1", "1", "", "", "", ""]]
    )  # fmt: skip
    lic._CACHE.clear()
    st = lic.TermStore()
    try:
        assert lic.load_release(st, _zip(tmp_path, files), by="steward")["index_rows"] == 10
        for asked in ("covid試験肺炎", "COVID試験肺炎", "ＣＯＶＩＤ試験　肺炎", "Covid試験 肺炎"):
            assert [(r["term"], r["code"]) for r in st.lookup_term(asked)] == [
                ("Covid試験肺炎", "YA01"),
                ("covid試験 肺炎", "YA01"),
            ], asked
        assert [(r["term"], r["code"]) for r in st.lookup_term("iga試験症")] == [("IgA試験症", "YA02")]
        assert [r["term"] for r in st.lookup_term("試験性肺炎")] == ["試験性肺炎"]
    finally:
        st.close()
