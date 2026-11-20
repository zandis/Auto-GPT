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
    assert _diagnosis(tmp_path / "c", "YA05", "分類未定試験病", [])["icd10"] == ""  # the hyphen form: unknown
    assert _diagnosis(tmp_path / "d", "YA01", "試験性肺炎", [], icd="J189")["suspected"] == ""
    assert _diagnosis(tmp_path / "e", "YA01", "試験性肺炎", [], icd="J180")["suspected"] == "U"  # not the master's


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


def test_a_release_with_a_table_that_cannot_be_loaded_loads_nothing(tmp_path: Path) -> None:
    """All or nothing: the modifier table has no row with a code, so the disease table is not loaded either."""
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
