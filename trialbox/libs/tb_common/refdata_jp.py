"""Japan reference data items (D-173, D-174, D-175): the WHO ICD-10 <-> ICD-10-CM category bridge, the MEDIS
標準病名 -> ICD-10 loader, the YJ code -> ATC map, the JLAC10 -> LOINC loader, CTCAE v5.0 in English and the
loader for its Japanese translation (JCOG), and the Japanese clinical synonyms for the name matcher.

Each item is one :class:`tb_common.refdata.Item` in the registry (``tools/refdata_fetch.py`` adds :data:`ITEMS`), as
the Taiwan items are (``tb_common.refdata_tw``). The box never downloads them: the vendor runs
``tools/refdata_fetch.py fetch`` and ``build``; the pack reaches the box in the signed update bundle. An item whose
licence forbids shipping is ``site-fetch``: it has a loader, the hospital downloads the file itself and runs
``tools/refdata_fetch.py site-load``, and TrialBox ships no data of it.

Licences read at the source on 2026-11-10:

* **MEDIS 標準病名マスター** (https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html): anyone may download
  and use it, but use outside a medical institution or for distribution needs MEDIS's written permission
  (使用許諾申請書); 病名 and HOT are on that list. Not shipped: site-fetch loader only.
* **JLAC10 -> LOINC**: no public map exists (MHLW, JSLM, JLAC Center searched); JSLM's code page refuses automated
  reading and states no licence we could read. Not shipped: site-fetch loader for the hospital's own map file.
* **YJ code -> ATC**: no free public table (KEGG is paid; CAPS publishes YJ codes without ATC). TrialBox's own
  table: 7-character YJ stems (薬効分類 + ingredient + route) read from MHLW's 薬価基準収載品目リスト (PDL 1.0) ->
  ATC codes as identifiers only (no WHOCC text: its site says no commercial copying of the index).
* **CTCAE v5.0 (NCI)**: NCI text is "free of copyright" (cancer.gov/policies/copyright-reuse), credit NCI; JCOG's
  page also calls CTCAE v5.0 a public-domain document. Shipped in English: terms, SOC, grades, definitions; the
  MedDRA codes are dropped (MedDRA is licensed by subscription for industry).
* **CTCAE v5.0 日本語訳 JCOG版** (https://jcog.jp/doctor/tool/ctcaev5/): free for non-commercial trials; commercial
  use needs a contract; JCOG holds the translation's copyright. Not shipped: site-fetch loader.
* **WHO ICD-10 <-> ICD-10-CM bridge**: TrialBox's own work from code strings only (the ICD-10-CM categories, US public
  domain, and our list of categories checked to have the same scope); no WHO text.
* **Japanese clinical synonyms**: TrialBox's own list.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from tb_common.refdata import (
    RELATIONS,
    Item,
    csv_rows,
    curated_synonyms,
    in_set_via_map,
    map_targets_or_empty,
    own_file_version,
    page_licence_reader,
    require_columns,
    sha256_file,
)

log = logging.getLogger(__name__)

ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
MEDIS_BYOMEI = "urn:oid:1.2.392.200119.4.101.6"  # as adapter.licensed (D-137)
JLAC10 = "urn:oid:1.2.392.200119.4.504"
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"
YJ_STEM = "urn:trialbox:jp:yj-stem7"  # the first 7 characters of a YJ / 薬価基準 code: 薬効分類, ingredient, route
CTCAE5 = "urn:trialbox:ctcae:5.0"  # code = the CTCAE v5.0 English term (MedDRA codes are not shipped)

SRC = Path(__file__).resolve().parent / "refdata_src"
REPO_YJ_ATC = SRC / "jp_yj_atc.csv"
REPO_BRIDGE_CHECKED = SRC / "icd10_who_cm_checked.csv"
REPO_SYNONYMS = SRC / "ja_clinical_synonyms.csv"

_ATC5 = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")
_YJ = re.compile(r"^\d{7}[A-Z][0-9A-Z]{4}$")  # 12 characters: 7 digits, the 剤形 letter, 4 more
_JLAC10 = re.compile(r"^[0-9A-Z]{15}([0-9A-Z]{2})?$")
_LOINC = re.compile(r"^\d{1,6}-\d$")
_CATEGORY = re.compile(r"^[A-Z]\d[0-9A-Z]$")


# ------------------------------------------------------------------------------------------------ table reading
def _key(text: str) -> str:
    """A header for matching: NFKC (full width to half), no spaces or line breaks, upper case."""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", str(text or ""))).upper()


def _decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM) or Shift_JIS (CP932), as Japanese vendor files come."""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("the file is neither UTF-8 nor Shift_JIS text")


def read_table(path: Path, columns: list[str] | None = None) -> list[list[str]]:
    """Rows of a CSV, a tab-separated file or the first sheet of an ``.xlsx`` (cells NFKC'd and trimmed). With
    ``columns`` (a release without a header row) the names are put in front as the header."""
    if path.suffix.lower() == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            out = [["" if c is None else str(c) for c in row] for row in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    else:
        text = _decode(path.read_bytes())
        first = text.split("\n", 1)[0]
        delim = "\t" if first.count("\t") > first.count(",") else ","
        out = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [[unicodedata.normalize("NFKC", c).strip() for c in r] for r in out]
    return ([list(columns)] if columns else []) + rows


def columns_beside(path: Path) -> list[str] | None:
    """The column names a site gave for a file without a header row (``site-load --columns``, kept beside the file
    as ``columns.txt``), else None."""
    f = path.parent / "columns.txt"
    if not f.is_file():
        return None
    names = [c.strip() for c in f.read_text(encoding="utf-8").split(",") if c.strip()]
    return names or None


def find_header(rows: list[list[str]], wanted: dict[str, tuple[str, ...]], required: Iterable[str],
                what: str) -> tuple[int, dict[str, int]]:  # fmt: skip
    """The first row (of the first 20) holding every required column: its index and ``name -> column index``
    (first alias that matches). ValueError when no row does (a file that changed shape never loads half-read)."""
    for i, row in enumerate(rows[:20]):
        idx: dict[str, int] = {}
        keys = [_key(c) for c in row]
        for name, aliases in wanted.items():
            for a in aliases:
                if _key(a) in keys:
                    idx[name] = keys.index(_key(a))
                    break
        if all(r in idx for r in required):
            return i, idx
    raise ValueError(f"{what}: no header row with {', '.join(required)} (give the columns with --columns)")


def _cell(row: list[str], idx: dict[str, int], name: str) -> str:
    i = idx.get(name)
    return row[i] if i is not None and i < len(row) else ""


# ------------------------------------------------------------------------------------------------ D-173 MEDIS
MEDIS_COLS: dict[str, tuple[str, ...]] = {
    "code": ("病名交換用コード", "交換用コード", "病名交換用code"),
    "name": ("病名表記", "病名", "病名表記(漢字)"),
    "icd10": ("ICD10-2013", "ICD-10-2013", "ICD10", "ICD-10", "ICD10コード"),
    "management_no": ("病名管理番号", "管理番号"),
    "receipt_code": ("レセプト電算処理システム傷病名コード", "レセプト電算コード", "傷病名コード"),
}
_WHO_CODE = re.compile(r"^[A-Z]\d[0-9A-Z](\.?[0-9A-Z]{1,2})?$")


def parse_medis_byomei(path: Path) -> Iterator[dict[str, Any]]:
    """The hospital's own MEDIS 標準病名マスター download (site-fetch: never shipped) -> map rows 病名交換用コード ->
    the WHO ICD-10 code the master gives. The 病名 is narrower than its ICD-10 code, so the target is ``wider``. A
    row without an ICD-10 code, or with one that is not ICD-10-shaped, gives no row (unknown, never a guess)."""
    rows = read_table(path, columns_beside(path))
    head, idx = find_header(rows, MEDIS_COLS, ("code", "icd10"), "the MEDIS 病名 master")
    seen: set[str] = set()
    for r in rows[head + 1 :]:
        code, icd = _cell(r, idx, "code").upper(), _cell(r, idx, "icd10").upper().replace(" ", "")
        if not re.fullmatch(r"[0-9A-Z]{4}", code) or code in seen:
            continue
        if not _WHO_CODE.match(icd):
            continue
        seen.add(code)
        if "." not in icd and len(icd) > 3:
            icd = icd[:3] + "." + icd[3:]
        yield {"source_system": MEDIS_BYOMEI, "source_code": code, "source_display": _cell(r, idx, "name"),
               "target_system": ICD10_WHO, "target_code": icd, "target_display": "", "relation": "wider",
               "extra": {k: v for k in ("management_no", "receipt_code") if (v := _cell(r, idx, k))}}  # fmt: skip


# ------------------------------------------------------------------------------------------------ D-173 bridge
def icd10cm_categories(path: Path) -> list[str]:
    """The 3-character categories of the ICD-10-CM code list (the CDC zip ``icd10cm-codes-<year>.txt``)."""
    import zipfile

    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if re.search(r"icd10cm-codes-\d{4}\.txt$", n))
        text = z.read(name).decode("utf-8", errors="replace")
    cats = {m.group(1) for line in text.splitlines() if (m := re.match(r"^([A-Z]\d[0-9A-Z])", line.strip()))}
    if not cats:
        raise ValueError(f"{path.name}: no ICD-10-CM codes")
    return sorted(cats)


def bridge_checked(path: Path | None = None) -> dict[str, str]:
    """TrialBox's list of WHO categories checked to sit wholly inside the ICD-10-CM category of the same code:
    ``category -> note``."""
    out: dict[str, str] = {}
    rows = csv_rows((path or REPO_BRIDGE_CHECKED).read_bytes())
    for r in require_columns(rows, ("category", "note"), "the checked bridge categories"):
        cat = r["category"].upper()
        if not _CATEGORY.match(cat):
            raise ValueError(f"the checked bridge categories: {cat!r} is not a 3-character category")
        out[cat] = r["note"]
    return out


def parse_icd10_who_cm_bridge(path: Path) -> Iterator[dict[str, Any]]:
    """WHO ICD-10 category -> the ICD-10-CM category of the same three characters (a family, D-113 style), for every
    category ICD-10-CM has. ``wider`` (the ICD-10-CM category holds all of the WHO category's meaning) only for the
    categories TrialBox checked (``refdata_src/icd10_who_cm_checked.csv``); every other row is ``inexact`` (a
    candidate that never decides): ICD-10-CM narrowed or moved parts of many categories (A09 unspecified -> K52.9,
    chronic gout M10 -> M1A, neuroendocrine tumours of C categories -> C7A, E13 -> E08 / E09). A WHO category that
    ICD-10-CM does not have (E14, B21) has no row: it stays unknown. Code strings only, no WHO text."""
    checked = bridge_checked()
    for cat in icd10cm_categories(path):
        ok = cat in checked
        yield {"source_system": ICD10_WHO, "source_code": cat, "source_display": "", "target_system": ICD10CM,
               "target_code": cat, "target_display": "", "relation": "wider" if ok else "inexact",
               "extra": {"level": "category", "checked": ok, "note": checked.get(cat, "")}}  # fmt: skip


def bridge_version(path: Path) -> str:
    year = re.search(r"(20\d{2})", path.name)
    return (f"ICD-10-CM {'FY' + year.group(1) if year else path.name} categories; TrialBox checked list sha256 "
            f"{sha256_file(REPO_BRIDGE_CHECKED)[:12]}")  # fmt: skip


def who_icd10_targets(code: str, url: str | None = None) -> list[dict[str, Any]]:
    """The ICD-10-CM families a WHO ICD-10 code (E11.9, from a MEDIS 病名 or an SS-MIX2 record) falls in, by its
    category; [] when nothing is loaded."""
    c = code.strip().upper()
    return map_targets_or_empty(ICD10_WHO, c[:3], url) if _CATEGORY.match(c[:3]) else []


def who_icd10_in_list(code: str, wanted: set[tuple[str, str]], families: Iterable[tuple[str, str]] = (),
                      url: str | None = None) -> str:  # fmt: skip
    """``yes`` / ``unknown`` for a WHO ICD-10 code against an ICD-10-CM list (exact codes and prefix families),
    through the bridge. The bridge never says ``no`` (its rows are ``wider`` or ``inexact``), so a WHO-only code
    never excludes."""
    return in_set_via_map(who_icd10_targets(code, url), wanted, families)


# ------------------------------------------------------------------------------------------------ D-174 YJ -> ATC
YJ_COLS = ("yj_stem7", "ingredient_ja", "route", "atc", "name_en")


def parse_jp_yj_atc(path: Path) -> Iterator[dict[str, Any]]:
    """TrialBox's own table: a 7-character YJ stem (薬効分類 4 + ingredient and route 3; every YJ and 薬価基準 code of
    the ingredient and route starts with it) -> its ATC code. The product is narrower than its ATC class:
    ``wider``. Stems were read from MHLW's 薬価基準収載品目リスト (2026-11 lists) and each holds one ingredient."""
    for r in require_columns(csv_rows(path.read_bytes()), YJ_COLS, "the YJ -> ATC table"):
        stem, atc = r["yj_stem7"], r["atc"].upper()
        if not re.fullmatch(r"\d{7}", stem) or not _ATC5.match(atc):
            raise ValueError(f"the YJ -> ATC table: bad row {stem!r} -> {atc!r}")
        yield {"source_system": YJ_STEM, "source_code": stem, "source_display": r["ingredient_ja"],
               "target_system": ATC, "target_code": atc, "target_display": "", "relation": "wider",
               "extra": {"route": r["route"], "name_en": r["name_en"], "atc_level": 5}}  # fmt: skip


def yj_version(path: Path) -> str:
    return own_file_version("TrialBox YJ stem to ATC", path, sum(1 for _ in parse_jp_yj_atc(path)))


def yj_atc_targets(code: str, url: str | None = None) -> list[dict[str, Any]]:
    """The ATC rows for a 12-character YJ (or 薬価基準) code, by its 7-character stem; [] for another shape or when
    nothing is loaded."""
    c = code.strip().upper()
    return map_targets_or_empty(YJ_STEM, c[:7], url) if _YJ.match(c) else []


# ------------------------------------------------------------------------------------------------ D-174 JLAC10
JLAC_COLS: dict[str, tuple[str, ...]] = {
    "code": ("JLAC10", "JLAC10コード", "臨床検査項目分類コード"),
    "loinc": ("LOINC", "LOINCコード", "LOINC_NUM", "LOINC code"),
    "name": ("項目名", "検査項目名称", "検査項目名", "名称", "name"),
    "relation": ("relation", "equivalence", "対応関係"),
    "analyte": ("分析物コード", "分析物"),
    "identification": ("識別コード", "識別"),
    "material": ("材料コード", "材料"),
    "method": ("測定法コード", "測定法"),
    "result": ("結果識別コード", "結果識別"),
}
_JLAC_PARTS = ("analyte", "identification", "material", "method", "result")


def parse_jlac10_loinc(path: Path) -> Iterator[dict[str, Any]]:
    """The hospital's own JLAC10 -> LOINC file (site-fetch: no public map exists and nothing is shipped): a CSV, TSV
    or XLSX with a JLAC10 column (or its five part columns) and a LOINC column. The relation is the file's own
    (an R4 equivalence) when it has one, else ``relatedto`` (a candidate: site set-up offers it, a person
    confirms). Rows whose codes are not JLAC10- or LOINC-shaped are left out."""
    rows = read_table(path, columns_beside(path))
    try:
        head, idx = find_header(rows, JLAC_COLS, ("code", "loinc"), "a JLAC10 -> LOINC file")
    except ValueError:
        head, idx = find_header(rows, JLAC_COLS, ("loinc", *_JLAC_PARTS), "a JLAC10 -> LOINC file")
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for r in rows[head + 1 :]:
        if not any(c.strip() for c in r):
            continue
        code = _cell(r, idx, "code") if "code" in idx else "".join(_cell(r, idx, p) for p in _JLAC_PARTS)
        code = re.sub(r"[\s\-‐－]", "", code.upper())  # 3C015-0000-023-271-01 as printed in many masters
        loinc = _cell(r, idx, "loinc").replace(" ", "")
        if (code, loinc) in seen:
            continue
        if not _JLAC10.match(code) or not _LOINC.match(loinc):
            skipped += 1
            continue
        seen.add((code, loinc))
        rel = _cell(r, idx, "relation").lower() or "relatedto"
        if rel not in RELATIONS:
            raise ValueError(f"{path.name}: {code} -> {loinc}: relation {rel!r} is not an R4 equivalence")
        yield {"source_system": JLAC10, "source_code": code, "source_display": _cell(r, idx, "name"),
               "target_system": LOINC, "target_code": loinc, "target_display": "", "relation": rel,
               "extra": {}}  # fmt: skip
    if skipped:
        log.warning("%s: %d rows left out (not a JLAC10 or LOINC code)", path.name, skipped)


def jlac10_loinc_targets(code: str, url: str | None = None) -> list[dict[str, Any]]:
    c = code.strip().upper()
    return map_targets_or_empty(JLAC10, c, url) if _JLAC10.match(c) else []


# ------------------------------------------------------------------------------------------------ D-174 CTCAE
CTCAE_EN_COLS: dict[str, tuple[str, ...]] = {
    "meddra": ("MedDRA v20.1 Code", "MedDRA Code"),
    "soc": ("MedDRA v20.1 SOC", "MedDRA SOC"),
    "term": ("CTCAE Term/MedDRA LLT v20.1", "CTCAE Term"),
    **{f"g{i}": (f"Grade {i}",) for i in range(1, 6)},
    "definition": ("Definition",),
    "note": ("Navigational Note",),
}


def _nd(text: str) -> str:
    """A grade cell: NCI writes "-" (or " -") for a grade that does not apply."""
    t = (text or "").strip()
    return "" if t in ("-", "－", "‐") else t


def _xlsx_rows(path: Path, sheet_hint: str = "") -> list[list[str]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = next((w for w in wb.worksheets if sheet_hint and sheet_hint in w.title), wb.worksheets[0])
        return [[unicodedata.normalize("NFKC", "" if c is None else str(c)).strip() for c in row]
                for row in ws.iter_rows(values_only=True)]  # fmt: skip
    finally:
        wb.close()


def parse_ctcae_v5_en(path: Path) -> Iterator[dict[str, Any]]:
    """NCI's CTCAE v5.0 workbook (sheet "CTCAE v5.0 Clean Copy"): one term per CTCAE term with its SOC, the five
    grade texts and the definition. The MedDRA code column is not copied (MedDRA is licensed separately); the
    term itself is the code."""
    rows = _xlsx_rows(path, "Clean Copy")
    head, idx = find_header(rows, CTCAE_EN_COLS, ("term", "soc", "g1"), "the CTCAE v5.0 workbook")
    seen: set[str] = set()
    for r in rows[head + 1 :]:
        term = _cell(r, idx, "term")
        if not term or term in seen:
            continue
        seen.add(term)
        yield {"system": CTCAE5, "code": term, "display": term,
               "extra": {"lang": "en", "soc": _cell(r, idx, "soc"),
                         "grades": {str(i): _nd(_cell(r, idx, f"g{i}")) for i in range(1, 6)},
                         "definition": _nd(_cell(r, idx, "definition")),
                         "navigational_note": _nd(_cell(r, idx, "note"))}}  # fmt: skip


def ctcae_en_version(path: Path) -> str:
    rows = _xlsx_rows(path, "Clean Copy")
    meddra = next((m.group(0) for c in (rows[0] if rows else []) if (m := re.search(r"MedDRA v[\d.]+", c))), "")
    return "CTCAE v5.0 (NCI, 2017-11-27)" + (f", terms of {meddra}" if meddra else "")


CTCAE_JA_COLS: dict[str, tuple[str, ...]] = {
    "term": ("CTCAE v5.0 Term",),
    "term_ja": ("CTCAE v5.0 Term 日本語",),
    "soc_ja": ("CTCAE v5.0 SOC 日本語",),
    "note_ja": ("検索上の注意",),
}


def parse_ctcae_v5_ja(path: Path) -> Iterator[dict[str, Any]]:
    """The hospital's own download of the JCOG Japanese translation (site-fetch: JCOG holds its copyright and
    commercial use needs a contract) -> synonym rows: the Japanese term -> the CTCAE v5.0 English term (domain
    ``adverse_event``, system CTCAE, code the English term), with the Japanese grade texts and definition. In the
    JCOG workbook each grade has an English column (``原文``) followed by its Japanese column; the second
    ``Definition`` column is the Japanese one."""
    rows = _xlsx_rows(path) if path.suffix.lower() == ".xlsx" else read_table(path)
    head, idx = find_header(rows, CTCAE_JA_COLS, ("term", "term_ja"), "the JCOG CTCAE v5.0 workbook")
    keys = [_key(c) for c in rows[head]]
    grade = {i: next((j for j, k in enumerate(keys) if k == f"GRADE{i}"), None) for i in range(1, 6)}
    defs = [j for j, k in enumerate(keys) if "DEFINITION" in k]
    seen: set[str] = set()
    for r in rows[head + 1 :]:
        en, ja = _cell(r, idx, "term"), _cell(r, idx, "term_ja")
        if not en or not ja or ja in seen:
            continue
        seen.add(ja)

        def at(j: int | None, r: list[str] = r) -> str:
            return _nd(r[j]) if j is not None and j < len(r) else ""

        yield {"term": ja, "lang": "ja", "canonical": en, "canonical_lang": "en", "domain": "adverse_event",
               "system": CTCAE5, "code": en, "curated": True,
               "extra": {"soc_ja": _cell(r, idx, "soc_ja"), "grades_ja": {str(i): at(grade[i]) for i in grade},
                         "definition_ja": at(defs[-1]) if len(defs) > 1 else "",
                         "note_ja": _nd(_cell(r, idx, "note_ja"))}}  # fmt: skip


def ctcae_ja_version(path: Path) -> str:
    m = re.search(r"(\d{8})", path.name)
    return f"CTCAE v5.0 日本語訳JCOG版 {m.group(1) if m else '(the site gives the edition)'}"


# ------------------------------------------------------------------------------------------------ D-175 synonyms
def parse_ja_synonyms(path: Path) -> Iterator[dict[str, Any]]:
    """TrialBox's own list: Japanese clinical words and the abbreviations of Japanese notes -> the name the matcher
    knows, per domain; rows marked ``review`` (PSL, MTX, RA) are not trusted."""
    return curated_synonyms(path, "ja", "the curated Japanese synonyms")


def ja_synonyms_version(path: Path) -> str:
    return own_file_version("TrialBox ja synonyms", path, sum(1 for _ in parse_ja_synonyms(path)))


# ------------------------------------------------------------------------------------------------ D-317 jRCT
# The columns of the CSV that jRCT's search page downloads (「CSVダウンロード」, after 利用規約を確認しました), in
# Japanese or English; matched by alias. Check them against the hospital's first real download.
JRCT_COLS: dict[str, tuple[str, ...]] = {
    "id": (
        "臨床研究実施計画番号",
        "臨床研究実施計画・研究概要公開システム番号",
        "jRCT番号",
        "jRCT No.",
        "Trial ID",
        "jRCT ID",
    ),
    "title": ("研究の名称", "平易な研究名称", "Scientific Title", "Public Title", "Title"),
    "condition": ("対象疾患名", "Health Condition(s) or Problem(s) Studied", "Condition"),
    "status": ("研究の進捗状況", "Recruitment Status", "Status"),
    "updated": ("最終公表日", "最終更新日", "公表日", "Last Update", "Date of Last Update"),
    "inclusion": ("選択基準", "Inclusion Criteria"),
    "exclusion": ("除外基準", "Exclusion Criteria"),
    "phase": ("試験のフェーズ", "Phase"),
}
_JRCT_ID = re.compile(r"^jRCT[0-9a-z]?\d{6,12}$", re.IGNORECASE)


def parse_jrct(path: Path) -> Iterator[dict[str, Any]]:
    """The hospital's own jRCT search download (CSV, UTF-8 or Shift_JIS, or XLSX) -> trial rows (registry jRCT). A
    row without a jRCT-shaped id is left out and counted in the log; a file without the id and title columns is
    refused. TrialBox never fetches jRCT: bulk use needs the help desk's permission (D-140, D-317)."""
    rows = read_table(path)
    head, idx = find_header(rows, JRCT_COLS, ("id", "title"), "a jRCT search download")
    seen: set[str] = set()
    skipped = 0
    for row in rows[head + 1 :]:
        tid = _cell(row, idx, "id").strip()
        if not _JRCT_ID.match(tid) or tid in seen:
            skipped += bool(any(row))
            continue
        seen.add(tid)
        cond = _cell(row, idx, "condition")
        yield {"registry": "jRCT", "trial_id": tid, "title": _cell(row, idx, "title"),
               "status": _cell(row, idx, "status"), "phase": _cell(row, idx, "phase"),
               "conditions": [c.strip() for c in re.split(r"[、;；\n]", cond) if c.strip()],
               "countries": ["Japan"], "inclusion": _cell(row, idx, "inclusion"),
               "exclusion": _cell(row, idx, "exclusion"), "updated": _cell(row, idx, "updated"), "codes": [],
               "record": {k: v for k, v in zip(rows[head], row, strict=False) if k}}  # fmt: skip
    if skipped:
        log.info("jRCT download: %d rows without a jRCT id left out", skipped)


# ------------------------------------------------------------------------------------------------ the items
OWN = "TrialBox (own work)"
OWN_TERMS = "Written by the TrialBox team; shipped with the product."
NCI_REUSE = "https://www.cancer.gov/policies/copyright-reuse"
MEDIS_TERMS_URL = "https://www.medis.or.jp/4_hyojyun/medis-master/riyou/index.html"
JCOG_URL = "https://jcog.jp/doctor/tool/ctcaev5/"

ITEMS: tuple[Item, ...] = (
    Item(
        "icd10_who_cm_bridge", "WHO ICD-10 <-> ICD-10-CM category bridge (TrialBox, from the ICD-10-CM code list)",
        "map", "ship",
        "https://ftp.cdc.gov/pub/Health_Statistics/NCHS/Publications/ICD10CM/2027/icd10cm-code-descriptions-2027.zip",
        OWN, "",
        "TrialBox's own work from code strings only: the ICD-10-CM categories (U.S. public domain, CDC NCHS) and "
        "TrialBox's list of categories checked to have the same scope. No WHO ICD-10 text is shipped.",
        "TrialBox WHO ICD-10 <-> ICD-10-CM bridge, Aimedics; ICD-10-CM category codes from the National Center for "
        "Health Statistics, CDC. ICD-10 is a classification of the World Health Organization.",
        "with each ICD-10-CM release", "about 1,900 category rows",
        "A WHO code in a checked category falls in its ICD-10-CM family (yes); any other is unknown; never no.",
        country="JP", decision="D-173", derived_from="icd10cm", parse=parse_icd10_who_cm_bridge,
        version_of=bridge_version,
    ),
    Item(
        "medis_byomei_icd10", "MEDIS 標準病名マスター -> ICD-10 (the hospital's own download)", "map", "site-fetch",
        "https://www2.medis.or.jp/stdcd/byomei/", "MEDIS-DC standard master terms of use", MEDIS_TERMS_URL,
        "Anyone may download and use it; use outside a medical institution or for distribution needs MEDIS-DC's "
        "written permission (使用許諾申請書), so TrialBox does not ship it. The hospital downloads its release and "
        "loads it with site-load (give --columns for a file without a header row). A modified copy must say it "
        "uses the MEDIS-DC standard master.",
        "標準病名マスター, 一般財団法人医療情報システム開発センター (MEDIS-DC), downloaded and loaded by the hospital.",
        "several releases a year", "about 27,000 病名",
        "Site-fetch until MEDIS-DC grants TrialBox a distribution permission (asked separately).",
        country="JP", decision="D-173", fetch=False, parse=parse_medis_byomei,
    ),
    Item(
        "jp_yj_atc", "YJ code (7-character stem) -> ATC (TrialBox, stems from the MHLW 薬価基準収載品目リスト)",
        "map", "ship", "repo:libs/tb_common/refdata_src/jp_yj_atc.csv", OWN, "",
        "TrialBox's own table. The YJ stems were read from MHLW's 薬価基準収載品目リスト (PDL 1.0, 出典：厚生労働省). "
        "ATC codes are used as identifiers only: no WHOCC ATC/DDD index text is shipped.",
        "TrialBox YJ -> ATC table, Aimedics. YJ stems from 出典：厚生労働省「薬価基準収載品目リスト」(加工して作成). "
        "ATC codes: WHO Collaborating Centre for Drug Statistics Methodology.",
        "with releases", "56 stems",
        "No free public YJ -> ATC table exists (KEGG is paid); a stem is one ingredient and route.",
        "jp_yj_atc.csv", country="JP", decision="D-174", parse=parse_jp_yj_atc, version_of=yj_version,
    ),
    Item(
        "jlac10_loinc", "JLAC10 -> LOINC (the hospital's own map file)", "map", "site-fetch",
        "https://www.jslm.org/committees/code/", "No public map; the hospital's own file", "",
        "No public JLAC10 -> LOINC map exists (MHLW, JSLM and JLAC Center searched on 2026-11-10) and JSLM states no "
        "redistribution terms, so TrialBox ships none. The hospital loads its own map (a JLAC10 and a LOINC "
        "column) with site-load; rows without a stated equivalence are candidates (relatedto).",
        "The hospital's own JLAC10 -> LOINC map. LOINC is copyright Regenstrief Institute, Inc. and the LOINC "
        "Committee, available at no cost under the license at http://loinc.org/license.",
        "when the hospital changes it", "the hospital's lab items",
        "Site set-up suggests a LOINC code for a JLAC10 code with one target.",
        country="JP", decision="D-174", fetch=False, parse=parse_jlac10_loinc,
    ),
    Item(
        "ctcae_v5_en", "CTCAE v5.0 terms and grades, English (NCI)", "term", "ship",
        "https://dctd.cancer.gov/research/ctep-trials/trial-development/ctcae-v5.0.xlsx",
        "U.S. public domain (NCI: free of copyright, credit NCI)", NCI_REUSE,
        "NCI text is free of copyright and may be reused without permission; credit the National Cancer Institute. "
        "The MedDRA codes in the workbook are not shipped (MedDRA is licensed separately); the terms, SOCs, grades "
        "and definitions are.",
        "Common Terminology Criteria for Adverse Events (CTCAE) v5.0, U.S. National Cancer Institute, Cancer "
        "Therapy Evaluation Program. Source: National Cancer Institute.",
        "static (v6.0 exists; v5.0 kept for trials that use it)", "837 terms, 0.5 MB xlsx",
        "For AE entry; grading stays with a person (D-129).",
        "ctcae-v5.0.xlsx", country="JP", decision="D-174", parse=parse_ctcae_v5_en, version_of=ctcae_en_version,
        sha256="2036d4933ee2b768a8d9955ea939439b8a4b9dd432053b244d7529f9826ea047",  # read 2026-11-10
        licence_reader=page_licence_reader(NCI_REUSE, "free of copyright"),
    ),
    Item(
        "ctcae_v5_ja_jcog", "CTCAE v5.0 日本語訳JCOG版 (the hospital's own download)", "synonym", "site-fetch",
        JCOG_URL, "JCOG terms (secondary copyright JCOG; non-commercial trial use)", JCOG_URL,
        "Free to download and use for non-commercial clinical trials without permission, citing it as "
        "「有害事象共通用語規準 v5.0 日本語訳JCOG版より引用」; commercial use needs a contract with JCOG, so TrialBox "
        "does not ship it. The hospital downloads the body-only workbook and loads it with site-load.",
        "引用：有害事象共通用語規準 v5.0 日本語訳JCOG版より引用 (Japan Clinical Oncology Group), loaded by the "
        "hospital.",
        "with JCOG editions (2025-09-01 edition, MedDRA/J v28.1)", "837 terms",
        "All 837 English terms and MedDRA codes of the 2025-09-01 edition match NCI's v5.0 workbook (checked "
        "2026-11-10).",
        country="JP", decision="D-174", fetch=False, parse=parse_ctcae_v5_ja, version_of=ctcae_ja_version,
    ),
    Item(
        "ja_synonyms", "TrialBox Japanese clinical synonyms and note abbreviations (curated)", "synonym", "ship",
        "repo:libs/tb_common/refdata_src/ja_clinical_synonyms.csv", OWN, "", OWN_TERMS,
        "TrialBox Japanese clinical synonyms, Aimedics.", "with releases", "about 70 entries",
        "Japanese disease, drug and test names and note abbreviations -> the matcher's names.",
        "ja_clinical_synonyms.csv", country="JP", decision="D-175", parse=parse_ja_synonyms,
        version_of=ja_synonyms_version,
    ),
    Item(
        "jrct", "jRCT (Japan Registry of Clinical Trials), the hospital's own search download", "trial", "site-fetch",
        "https://jrct.mhlw.go.jp/search", "jRCT terms of use (MHLW)", "https://jrct.mhlw.go.jp/",
        "No public API. The search page's CSV download asks the user to accept the terms; bulk or comprehensive "
        "use and crawling need the jRCT help desk's permission (asked, pending). TrialBox never fetches or ships "
        "jRCT data: the hospital downloads its own search (for example its conditions, or its own institution) "
        "and loads it with site-load.",
        "jRCT (Japan Registry of Clinical Trials), Ministry of Health, Labour and Welfare; downloaded by the "
        "hospital.",
        "when the hospital downloads again", "the hospital's search",
        "JAPIC-CTI and JMACCT were merged into jRCT on 2023-03-06. Column names matched by alias: check them "
        "against the first real download.",
        country="JP", decision="D-317", fetch=False, parse=parse_jrct,
    ),
)  # fmt: skip
