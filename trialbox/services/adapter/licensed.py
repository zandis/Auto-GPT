"""Licensed Japanese code lists a site buys and loads itself: MEDIS 標準病名, JLAC10 and YJ (TB-PLAN-04 step 7, D-137).

TrialBox never ships these files. A site loads its own release into the terminology store (schema ``terminology`` of
the trial database, D-126), with the version and the file it came from, and from then on:

* the SS-MIX2 reader resolves a 標準病名 code with no ICD-10 alternate through the MEDIS file (only to a code that is
  in the ICD-10-CM list; any other code stays unknown, D-130);
* site set-up suggests a standard code for a hospital code from the file's ICD-10 or from the name it gives
  (``sitesetup.mapping.suggest``, D-135);
* the JP Core check knows which JLAC10, YJ and 病名 codes are real (``adapter.validate.jpcore``).

Without a file the box says plainly which lists are not loaded (:func:`status`), and D-130 keeps codes that only such
a file could read ``unknown``.

Vendor files are CSV or tab-separated, Shift_JIS (CP932) or UTF-8 with or without a BOM; the encoding and the
separator are detected and recorded. Columns are found by their header names (the names the vendors print, matched
after NFKC, so full-width headers such as ``個別医薬品コード`` or ``ＪＡＮコード`` match). A release without a header
row is loaded with ``columns=`` giving the column names in file order, from the release's own specification.

The MEDIS master as MEDIS ships it (D-1257): a folder or a zip holding ``readme.txt``, the three tables without a
header row (``main/nmain*.txt`` 病名基本, ``main/mdfy*.txt`` 修飾語, ``main/index*.txt`` 索引) and their column titles
(``option/ttl_main.txt``, ``ttl_mdfy.txt``, ``ttl_idx.txt``). :func:`load_release` reads the titles and the version
from the release itself and loads the three tables in one transaction; :func:`check_release` reads the same way and
writes nothing.

    python -m adapter.licensed load --kind medis --file NMAIN.TXT --version 5.12 [--columns a,b,c]
    python -m adapter.licensed load-release --source byomei518.zip
    python -m adapter.licensed status
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tb_common import encoding
from tb_common.config import site_tz
from tb_common.db import ENV, Database, DatabaseError

# code systems: the JP Core 1.1.0 NamingSystems for JLAC10, YJ and HOT9; the MEDIS 病名交換用コード OID (JP Core 1.1.0
# has no NamingSystem for it; verify against the site's release)
MEDIS_BYOMEI = "urn:oid:1.2.392.200119.4.101.6"
# the 修飾語管理番号 as a code system: no OID is cited for it (D-1252); a URN of this box's own, never sent out
MEDIS_MODIFIER = "urn:trialbox:medis-modifier-management-number"
JLAC10 = "urn:oid:1.2.392.200119.4.504"
YJ = "urn:oid:1.2.392.100495.20.1.73"
HOT9 = "urn:oid:1.2.392.200119.4.403.1"
ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
ATC = "http://www.whocc.no/atc"

SCHEMA = """
CREATE TABLE IF NOT EXISTS release (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, kind TEXT NOT NULL,
  system TEXT NOT NULL, version TEXT NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL, encoding TEXT NOT NULL,
  rows INTEGER NOT NULL, skipped INTEGER NOT NULL DEFAULT 0, loaded_by TEXT NOT NULL, loaded_at TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS concept (release_id BIGINT NOT NULL, code TEXT NOT NULL, display TEXT NOT NULL DEFAULT '',
  target_system TEXT NOT NULL DEFAULT '', target_code TEXT NOT NULL DEFAULT '', extra TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (release_id, code))
"""


#: D-1257: what a release says of itself beside its codes (its date, how many rows of its table are current, the
#: sha256 of the whole release it came in), as JSON; and a term looked up by its text (the 索引テーブル)
SCHEMA_V2 = """
ALTER TABLE release ADD COLUMN IF NOT EXISTS meta TEXT NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS concept_display ON concept (release_id, display)
"""
#: deep review of #1238 (M5): one active release of a list, held by the database itself. Two loads at once left two
#: (``status`` showed one, ``tables`` served both); a store that already holds two keeps the newest
SCHEMA_V3 = """
UPDATE release SET active = FALSE
  WHERE active AND id NOT IN (SELECT max(id) FROM release WHERE active GROUP BY kind);
CREATE UNIQUE INDEX IF NOT EXISTS release_one_active ON release (kind) WHERE active
"""
MIGRATIONS = (SCHEMA, SCHEMA_V2, SCHEMA_V3)


@dataclass(frozen=True)
class Kind:
    """One licensed list: the code system, which columns hold what (header aliases, NFKC-normalised), and its use."""

    name: str
    label: str
    system: str
    code: tuple[str, ...]
    display: tuple[str, ...]
    target: tuple[str, ...] = ()  # the standard code the file itself gives (ICD-10 for 病名), if any
    target_system: str = ""
    parts: tuple[tuple[str, ...], ...] = ()  # a code split over several columns (JLAC10's five parts)
    extra: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shape: str = r".+"


KINDS: dict[str, Kind] = {
    "medis": Kind(
        "medis",
        "MEDIS 標準病名マスター",
        MEDIS_BYOMEI,
        code=("病名交換用コード", "交換用コード", "病名交換用code"),
        display=("病名表記", "病名", "病名表記(漢字)"),
        target=("ICD10-2013", "ICD-10-2013", "ICD10", "ICD-10", "ICD10コード"),
        target_system=ICD10_WHO,
        extra={
            "management_no": ("病名管理番号", "管理番号"),
            "change": ("変更区分",),  # D-1252: only a current row (0, 3, 5) confirms
            # レセ電算コード is the release's own title (option/ttl_main.txt, D-1257)
            "receipt_code": (
                "レセ電算コード",
                "レセプト電算処理システム傷病名コード",
                "レセプト電算コード",
                "傷病名コード",
            ),
            "kana": ("病名表記カナ", "病名カナ", "カナ"),
            "adoption": ("採択区分",),
            "multi_class": ("ICD10-2013複数分類コード", "複数分類コード"),
            "field": ("使用分野",),
            "successor": ("移行先病名管理番号",),
            "no_solo": ("単独使用禁止区分",),
            "no_claim": ("保険請求外区分",),
        },
        shape=r"^[0-9A-Z]{4}$",
    ),
    # D-1252: the 修飾語テーブル of the same release (ICD10対応標準病名マスター Ver.5.18 仕様書 (2), MEDIS-DC: the file
    # mdfy*.txt has no header row, so a site loads it with --columns 変更区分,修飾語管理番号,修飾語表記,修飾語表記カナ,
    # 修飾語交換用コード,接続位置区分,修飾語区分,排他グループコード,レセ電算修飾語コード,修飾語説明用ラベル)
    "medis_modifier": Kind(
        "medis_modifier",
        "MEDIS 標準病名マスター 修飾語テーブル",
        MEDIS_MODIFIER,
        code=("修飾語管理番号",),
        display=("修飾語表記", "修飾語"),
        extra={
            "change": ("変更区分",),
            "exchange_code": ("修飾語交換用コード", "交換用コード"),
            "position": ("接続位置区分",),
            "modifier_class": ("修飾語区分",),
            "receipt_code": ("レセ電算修飾語コード", "レセプト電算処理システム修飾語コード"),
            "exclusive_group": ("排他グループコード",),
            "kana": ("修飾語表記カナ",),
        },
        shape=r"^[0-9]{8}$",
    ),
    "jlac10": Kind(
        "jlac10",
        "JLAC10 臨床検査項目コード",
        JLAC10,
        code=("JLAC10", "JLAC10コード", "臨床検査項目分類コード"),
        display=("項目名", "検査項目名称", "検査項目名", "分析物名", "名称"),
        target=("LOINC", "LOINCコード"),
        target_system=LOINC,
        parts=(
            ("分析物コード", "分析物"),
            ("識別コード", "識別"),
            ("材料コード", "材料"),
            ("測定法コード", "測定法"),
            ("結果識別コード", "結果識別"),
        ),
        extra={"material": ("材料名", "材料名称"), "method": ("測定法名", "測定法名称")},
        shape=r"^[0-9A-Z]{15}([0-9A-Z]{2})?$",
    ),
    "yj": Kind(
        "yj",
        "YJ コード (医薬品 HOT コードマスター)",
        YJ,
        code=("個別医薬品コード", "YJコード", "YJ", "個別医薬品コード(YJコード)"),
        display=("販売名", "告示名称", "医薬品名", "レセプト電算処理システム医薬品名"),
        target=("ATC", "ATCコード"),
        target_system=ATC,
        extra={
            "hot13": ("基準番号(HOTコード)", "基準番号", "HOTコード", "HOT13"),
            "hot7": ("処方用番号(HOT7)", "処方用番号", "HOT7"),
            "price_code": ("薬価基準収載医薬品コード",),
            "receipt_code": ("レセプト電算処理システムコード(1)", "レセプト電算処理システムコード"),
            "maker": ("製造会社",),
        },
        shape=r"^[0-9A-Z]{12}$",
    ),
}


#: D-1257: the 索引テーブル of the MEDIS master (index*.txt): a term (索引用語) and the 対応用語コード it stands
#: for, the 病名交換用コード of a disease (病名修飾語区分 1) or the 修飾語交換用コード of a modifier (2); "0000" is
#: no current term. A term is not unique; the pair (term, code) is. It is not one of :data:`KINDS`:
#: :func:`tables` does not carry it (112,967 rows no reader reads) and :func:`status` lists it only when asked
#: (``all_lists``); it is looked
#: up with :meth:`TermStore.lookup_term`
INDEX = "medis_index"
INDEX_KIND = Kind(
    INDEX,
    "MEDIS 標準病名マスター 索引テーブル",
    "urn:trialbox:medis-index-term",  # this box's own name for the pair, never sent out
    code=("対応用語コード",),
    display=("索引用語",),
    extra={
        "target_kind": ("病名修飾語区分",),  # 1 a disease, 2 a modifier
        "kana_kanji": ("かな漢字区分",),  # 1 from the kanji form, 2 from the kana form, 9 other
        "synonym": ("同義語区分",),  # 0 the term itself, 1 near-synonym, 2 related, 8 advised against, 9 other
        "variant": ("異字体区分",),  # 1 from a misspelling or misreading, 2 a variant character form, 9 other
    },
    shape=r"^[0-9A-Z]{4}$",
)
ALL_KINDS: dict[str, Kind] = {**KINDS, INDEX: INDEX_KIND}
#: a 変更区分 of a current row (ICD10対応標準病名マスター 仕様書 (1)①: 0 unchanged, 3 added, 5 changed; 1 is deleted)
CURRENT = ("0", "3", "5")


def modifier_class(value: str) -> str:
    """The class of a 修飾語区分 (ICD10対応標準病名マスター 仕様書 (2)⑦: eight characters, "現在は、前から2桁目に次の
    意味": 1 部位, 2 位置, 3 病因, 4 経過表現, 5 状態表現, 6 患者帰属, 7 その他, 8 接尾語, 9 歯科): the second
    character when the value is exactly eight ASCII characters and the second is a digit 1 to 9, else empty. The
    release writes a letter first (``A1000000``); D-1252 read only eight digits, so no real modifier had a class
    (D-1257)."""
    v = unicodedata.normalize("NFKC", value or "").strip()
    return v[1] if len(v) == 8 and v.isascii() and v[1] in "123456789" else ""


#: the lists whose rows the SS-MIX2 reader reads only when current (D-1252): a release without the 変更区分 column, or
#: with it empty in every row, is refused at load, never read as every row retired one by one
CHANGE_REQUIRED = ("medis", "medis_modifier")


def extra_i_change(k: Kind, index: dict[str, int]) -> int | None:
    """The column of 変更区分 in a release's header, or None."""
    return _col(index, k.extra.get("change", ()))


class LicensedError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


#: the hyphens a column title may be written with (U+2010 to U+2015, the minus sign, the full-width hyphen-minus): the
#: release's own title of the ICD-10 column is ＩＣＤ１０‐２０１３ with U+2010, which NFKC leaves as it is (D-1257)
_TITLE_HYPHENS = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d"), "-")


def _key(text: str) -> str:
    """A header name for matching: NFKC (full-width letters, digits and brackets become half-width), no spaces, any
    hyphen written as ``-``. For titles only, never for a value."""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", text).translate(_TITLE_HYPHENS)).upper()


def detect_encoding(data: bytes) -> str:
    """``utf-8-sig``, ``utf-8`` or ``cp932`` (Shift_JIS with the Windows extensions the vendors' files use), by the
    shared detector (D-215): a file it cannot tell is refused, never guessed."""
    try:
        return encoding.detect(data, ("cp932",))[0]
    except encoding.EncodingRefused as exc:
        raise LicensedError("LIC-ENCODING", str(exc)) from exc


def _sniff(first: str) -> str:
    return "\t" if first.count("\t") > first.count(",") else ","


@dataclass
class Parsed:
    kind: str
    encoding: str
    delimiter: str
    concepts: list[dict[str, str]]
    skipped: list[tuple[int, str]]  # (line number, why)
    rows: int = 0  # rows of the table that were read (a MEDIS exchange code may stand for several, D-1257)
    current: int = 0  # of them, rows with a current 変更区分 (0, 3, 5); for a list without it, every row


def _col(index: dict[str, int], names: Sequence[str]) -> int | None:
    for n in names:
        i = index.get(_key(n))
        if i is not None:
            return i
    return None


#: the character set MEDIS publishes its release in (Shift_JIS, read with the Windows extensions)
RELEASE_ENCODING = "cp932"


_NOT_SHIFT_JIS = frozenset("\x80\xa0\uf8f0\uf8f1\uf8f2\uf8f3")


def _decode(data: bytes, declared: str | None) -> tuple[str, str]:
    """``(text, encoding)`` of a vendor file. With no declared character set the shared detector decides (D-215)
    and refuses what it cannot tell. With one (D-1257: a MEDIS release is Shift_JIS, its publisher says so) the
    file is read as that, strictly, and the detector is not asked: in a table of a hundred thousand Shift_JIS lines
    some line's bytes are also valid UTF-8, which the detector reads as two character sets mixed. A byte the declared
    set does not hold refuses the file with its line."""
    if declared is None:
        try:
            return encoding.decode(data, ("cp932",))
        except encoding.EncodingRefused as exc:
            raise LicensedError("LIC-ENCODING", str(exc)) from exc
    try:
        text = data.decode(declared)
        # Python's cp932 reads the lone bytes 0x80, 0xA0 and 0xFD to 0xFF as characters Shift_JIS does not have
        # and the user-defined area (lead bytes 0xF0 to 0xF9) as private-use characters, which no release's text is
        stray = -1
        if declared == "cp932":
            stray = next((i for i, ch in enumerate(text) if ch in _NOT_SHIFT_JIS or "\ue000" <= ch <= "\uf8ff"), -1)
        if stray >= 0:
            line = text.count("\n", 0, stray) + 1
            raise LicensedError("LIC-ENCODING", f"not {declared}: a byte that cannot be read (line {line})")
        return text, declared
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1
        raise LicensedError("LIC-ENCODING", f"not {declared}: a byte that cannot be read (line {line})") from exc
    except LookupError as exc:
        raise LicensedError("LIC-ENCODING", f"unknown character set {declared!r}") from exc


#: bounds on what one table may hold (deep review of #1238, M6, L4). The real tables: 27,877, 2,509 and 112,967 rows
MAX_ROWS = 400_000
MAX_SKIPPED = 1_000  # rows listed as not read; the rest are counted in one last entry
MAX_CELL = 1_000  # characters of a code or a display name (the store indexes them)


def _lines(text: str) -> Iterator[str]:
    """The lines of ``text``, each with its line end, one at a time (a ``StringIO`` would hold the text again, four
    bytes for each character)."""
    pos, size = 0, len(text)
    while pos < size:
        end = text.find("\n", pos)
        end = size if end < 0 else end + 1
        yield text[pos:end]
        pos = end


def _refuse_characters(text: str) -> None:
    """A NUL in the file: the database cannot hold it, so the file is refused where it is read, with its line."""
    at = text.find("\x00")
    if at >= 0:
        line = text.count("\n", 0, at) + 1
        raise LicensedError("LIC-CHARACTER", f"a NUL character (line {line}): not a text file of a code list")


def parse(
    kind: str,
    data: bytes,
    columns: Sequence[str] | None = None,
    declared_encoding: str | None = None,
    max_rows: int | None = None,
) -> Parsed:
    """Read one vendor file. A row whose code does not have the code system's shape is skipped and listed.

    The MEDIS 病名基本テーブル (D-1257): a row is identified by its 病名管理番号, and one 病名交換用コード names
    a concept that several rows may share by design (a renamed entry beside its old 表記, a main name and its
    synonym). Every row is kept; the list's code stays the exchange code, and each concept carries its rows
    (:func:`_medis_concepts`).
    A file with no 病名管理番号 column is read as before, one row for each exchange code."""
    k = ALL_KINDS.get(kind)
    if k is None:
        raise LicensedError("LIC-KIND", f"unknown list {kind!r}: one of {', '.join(ALL_KINDS)}")
    # the strict read: a file that already holds U+FFFD is refused with its line, as the sheet reader does;
    # ``declared_encoding`` names the character set when the publisher declares it (a table of a MEDIS release)
    text, enc = _decode(data, declared_encoding)
    _refuse_characters(text)
    first = text.split("\n", 1)[0]
    delim = _sniff(first)
    # read row by row: the table is never held as a list of rows beside its text (M6)
    body = csv.reader(_lines(text), delimiter=delim)
    if columns:
        header, start = list(columns), 1
    else:
        try:
            header, start = next(body, []), 2
        except csv.Error as exc:
            raise LicensedError("LIC-FORMAT", f"the first line cannot be read as a table ({exc})") from exc
    index = {_key(h): i for i, h in enumerate(header)}
    code_i = _col(index, k.code)
    part_i = [_col(index, p) for p in k.parts]
    if code_i is None and not (part_i and all(i is not None for i in part_i)):
        want = " / ".join(k.code)
        raise LicensedError(
            "LIC-COLUMNS", f"no code column ({want}) in the header; give the columns in file order with --columns"
        )
    if kind in CHANGE_REQUIRED and extra_i_change(k, index) is None:
        raise LicensedError(
            "LIC-COLUMNS",
            "no 変更区分 column: the SS-MIX2 reader reads only a current row (変更区分 0, 3 or 5) of the MEDIS master "
            "(D-1252); give the release's columns in file order with --columns",
        )
    disp_i = _col(index, k.display)
    targ_i = _col(index, k.target) if k.target else None
    extra_i = {name: _col(index, names) for name, names in k.extra.items()}
    shape = re.compile(k.shape)
    by_number = kind == "medis" and extra_i.get("management_no") is not None
    out: list[dict[str, str]] = []
    skipped: list[tuple[int, str]] = []
    seen: set[str] = set()
    first_row: dict[str, dict[str, str]] = {}
    conflicting: set[str] = set()
    lines: dict[str, int] = {}
    n_rows = 0
    not_listed = 0
    n = start - 1
    while True:
        try:
            row = next(body)
        except StopIteration:
            break
        except csv.Error as exc:
            raise LicensedError("LIC-FORMAT", f"line {n + 1} cannot be read as a row of a table ({exc})") from exc
        n += 1
        if not any(c.strip() for c in row):
            continue
        if max_rows is not None and n_rows + len(skipped) + not_listed >= max_rows:
            raise LicensedError("LIC-ROWS", f"more than {max_rows} rows: larger than this table can be")
        if len(skipped) > MAX_SKIPPED:  # listed up to a bound; counted beyond it
            not_listed += len(skipped) - MAX_SKIPPED
            del skipped[MAX_SKIPPED:]

        def cell(i: int | None, row: list[str] = row) -> str:
            return unicodedata.normalize("NFKC", row[i]).strip() if i is not None and i < len(row) else ""

        if code_i is not None:
            code = cell(code_i)
        else:
            code = "".join(cell(i) for i in part_i)
        code = code.upper()
        if len(code) > MAX_CELL or len(cell(disp_i)) > MAX_CELL:
            raise LicensedError("LIC-LONG", f"line {n}: a code or a name of more than {MAX_CELL} characters")
        if not shape.match(code):
            skipped.append((n, f"code {code!r} is not a {k.label} code"))
            continue
        target = cell(targ_i).replace(" ", "") if targ_i is not None else ""
        if kind != "medis":
            target = target.upper()  # the MEDIS ICD-10 is kept as the release writes it (``E109a``, D-1257)
        extra = {x: cell(i) for x, i in extra_i.items() if cell(i)}
        if kind == "medis_modifier" and modifier_class(extra.get("modifier_class", "")):
            extra["class"] = modifier_class(extra["modifier_class"])
        record = {
            "code": code,
            "display": cell(disp_i),
            "target_system": k.target_system if target else "",
            "target_code": target,
            "extra": json.dumps(extra, ensure_ascii=False),
        }
        # what identifies the row: the 病名管理番号 of a disease, the pair of an index row, else the code
        ident = code
        if by_number:
            ident = extra.get("management_no", "")
            if not ident:
                skipped.append((n, "a row with no 病名管理番号"))
                continue
        elif kind == INDEX:
            ident = f"{code}\t{record['display']}"
            if not record["display"]:
                skipped.append((n, "a row with no 索引用語"))
                continue
        n_rows += 1
        if ident in seen:
            if (kind in CHANGE_REQUIRED) and record != first_row[ident]:
                # D-1252: one MEDIS row key on two different rows: which is the master's cannot be told, so neither
                # is read (the reader then does not recognise the code); listed
                conflicting.add(ident)
                what = "病名管理番号" if by_number else "code"
                skipped.append((n, f"{what} {ident} appears twice with different content; neither row is read"))
            else:
                skipped.append((n, f"code {code} appears twice; the first row is kept"))
            n_rows -= 1
            continue
        seen.add(ident)
        first_row[ident] = record
        lines[ident] = n
        out.append(record)
    n_rows -= len(conflicting)
    if len(skipped) > MAX_SKIPPED:
        not_listed += len(skipped) - MAX_SKIPPED
        del skipped[MAX_SKIPPED:]
    if not_listed:
        skipped.append((0, f"{not_listed} more rows were not read (not listed)"))
    if by_number:
        kept = [r for r in out if json.loads(r["extra"])["management_no"] not in conflicting]
        out, more = _medis_concepts(kept, {r["code"]: lines[json.loads(r["extra"])["management_no"]] for r in kept})
        skipped += more
    elif kind == INDEX:
        # the store's key is the pair as written; the 対応用語コード is kept beside it. ``display`` is the term as it
        # is compared (:func:`index_key`), and the term as written is ``extra["term"]``
        for r in out:
            written = r["display"]
            r["target_code"], r["code"] = r["code"], f"{r['code']}\t{written}"
            r["extra"] = json.dumps({**json.loads(r["extra"]), "term": written}, ensure_ascii=False)
            r["display"] = index_key(written)
    else:
        out = [r for r in out if r["code"] not in conflicting]
    if not out:
        raise LicensedError("LIC-EMPTY", "no row with a code was found")
    changes = [json.loads(c["extra"]).get("change", "") for c in out]
    if by_number:
        changes = [r.get("change", "") for c in out for r in json.loads(c["extra"])["rows"]]
    if kind in CHANGE_REQUIRED and not any(changes):
        raise LicensedError("LIC-COLUMNS", "the 変更区分 column is empty in every row (D-1252): check the release")
    current = sum(c in CURRENT for c in changes) if kind in CHANGE_REQUIRED else n_rows
    return Parsed(kind, enc, "tab" if delim == "\t" else "comma", out, skipped, n_rows, current)


#: what each row of a MEDIS concept keeps (the keys of ``extra["rows"]``), beside ``no`` and ``name``
_ROW_FIELDS = ("kana", "change", "adoption", "multi_class", "field", "successor", "no_solo", "no_claim", "receipt_code")


def index_key(text: str) -> str:
    """An index term as it is stored and compared: NFKC, every blank removed (half- and full-width), upper case.
    ONE function for the stored key and for a query (:meth:`TermStore.lookup_term`), and for any name a caller
    compares with an index term: ``ｃｏｖｉｄ－１９ 肺炎`` and ``COVID-19肺炎`` are one term."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).upper()


def icd_comparable(value: str) -> str:
    """An ICD-10 code of the release as two rows' codes are compared: NFKC, blanks and the dot removed, and the one
    lower-case letter the release writes after some codes (``E109a``, a Japanese sub-classification) dropped. The
    store keeps what the release writes."""
    v = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).replace(".", "")
    m = re.fullmatch(r"([A-Z][0-9]{2,4})[a-z]", v)
    return m.group(1) if m else v


def _medis_concepts(
    rows: list[dict[str, str]], line: dict[str, int]
) -> tuple[list[dict[str, str]], list[tuple[int, str]]]:
    """The 病名基本テーブル as concepts, one for each 病名交換用コード (D-1257): ``rows`` are its table rows, each with
    its 病名管理番号 in ``extra``; every row is kept, a deleted one (変更区分 1) too, since a hospital's older records
    still carry it and its successor (移行先病名管理番号) must be found.

    A concept is ``code`` the exchange code; ``display`` and ``target_code`` (ICD-10, as the release writes it) of
    its preferred row: of the current rows (変更区分 0, 3, 5) the one with the lowest 採択区分 (1 or 2 owns the code, 3
    is a synonym that borrows it), else, when every row is deleted, of all rows. ``extra`` holds the preferred row's
    fields under the names the list always had (``management_no``, ``change``, ...) and ``rows``: every row as
    ``{no, name, icd, kana, change, adoption, multi_class, field, successor, no_solo, no_claim, receipt_code}``
    (empty fields left out), in 病名管理番号 order. Current rows of one code that disagree on ICD-10: the concept has
    no ICD-10, ``icd_conflict`` is set (the reader then reads the code as unknown) and it is listed."""
    groups: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        given = json.loads(r["extra"])
        row = {"no": given["management_no"], "name": r["display"], "icd": r["target_code"]}
        row.update({f: given[f] for f in _ROW_FIELDS if given.get(f)})
        groups.setdefault(r["code"], []).append(row)
    out: list[dict[str, str]] = []
    listed: list[tuple[int, str]] = []
    for code, members in groups.items():
        members.sort(key=lambda m: m["no"])
        current = [m for m in members if m.get("change", "") in CURRENT]

        def rank(m: dict[str, str]) -> tuple[int, str]:
            return (int(m["adoption"]) if m.get("adoption", "").isdigit() else 9, m["no"])

        best = min(current or members, key=rank)
        # compared as codes, not as text: ``E109`` and ``E109a`` are one ICD-10 code (deep review of #1238, L6)
        icds = {icd_comparable(m["icd"]) for m in current if m["icd"]}
        extra: dict[str, Any] = {"management_no": best["no"], **{f: best[f] for f in _ROW_FIELDS if best.get(f)}}
        extra["rows"] = [{k: v for k, v in m.items() if v} for m in members]
        icd = best["icd"]
        if len(icds) > 1:
            icd = ""
            extra["icd_conflict"] = "1"
            listed.append((line[code], f"code {code}: its current rows disagree on ICD-10; the code reads as unknown"))
        out.append(
            {
                "code": code,
                "display": best["name"],
                "target_system": ICD10_WHO if icd else "",
                "target_code": icd,
                "extra": json.dumps(extra, ensure_ascii=False),
            }
        )
    return out, listed


def medis_rows(medis: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Every row of a loaded 病名基本テーブル by its 病名管理番号, from the concepts :func:`tables` gives under
    ``medis``: ``{no, name, icd, exchange, change, adoption, ...}`` (the fields of ``extra["rows"]`` and the row's
    exchange code). A release loaded before D-1257 holds one row for each exchange code: that row."""
    out: dict[str, dict[str, str]] = {}
    for exchange, concept in medis.items():
        extra = concept.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except ValueError:
                extra = {}
        members = extra.get("rows")
        if not isinstance(members, list):
            members = [{"no": extra.get("management_no", ""), "name": concept.get("display", ""),
                        "icd": concept.get("target_code", "")}]  # fmt: skip
            if "change" in extra:
                members[0]["change"] = extra["change"]
        conflict = "1" if extra.get("icd_conflict") else ""
        for m in members:
            if m.get("no"):
                row = {**{k: str(v) for k, v in m.items()}, "exchange": str(exchange), "conflict": conflict}
                out[str(m["no"])] = row
    return out


class TermStore:
    """Schema ``terminology`` of the trial database: each loaded release and its codes."""

    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), "terminology")
        self._db.migrate(list(MIGRATIONS))

    @property
    def db(self) -> Database:
        return self._db

    def close(self) -> None:
        self._db.close()

    def load(
        self,
        kind: str,
        data: bytes,
        *,
        version: str,
        source: str,
        by: str,
        columns: Sequence[str] | None = None,
        audit_dir: Path | None = None,
        declared_encoding: str | None = None,
    ) -> dict[str, Any]:
        """Load one release; the earlier release of the same list stays in the store, inactive. With ``audit_dir``
        (or ``TB_AUDIT_DIR``) the load is in the hash-chained audit (``terminology.load``). ``declared_encoding``:
        the file's character set when its publisher declares it (``cp932`` for one table of a MEDIS release); the
        file is then read as that, strictly, and not by detection."""
        if not version.strip():
            raise LicensedError("LIC-VERSION", "say which release this is (the version printed on it)")
        p = parse(kind, data, columns, declared_encoding)
        sha = hashlib.sha256(data).hexdigest()
        (rid,) = self.load_parsed([(p, sha, source)], version=version, by=by, audit_dir=audit_dir)
        return {
            "kind": kind,
            "system": ALL_KINDS[kind].system,
            "version": version.strip(),
            "source": Path(source).name,
            "sha256": sha,
            "encoding": p.encoding,
            "delimiter": p.delimiter,
            "rows": len(p.concepts),
            "skipped": [{"line": n, "why": w} for n, w in p.skipped],
            "release_id": rid,
        }

    def load_parsed(
        self,
        parts: Sequence[tuple[Parsed, str, str]],
        *,
        version: str,
        by: str,
        meta: dict[str, str] | None = None,
        audit_dir: Path | None = None,
    ) -> list[int]:
        """Write the parsed lists ``(parsed, sha256 of its file, source name)`` in ONE transaction: all of them
        become the active release of their list, or none does (D-1257: the three tables of one MEDIS release).
        ``meta`` is what the release says of itself (``released``, ``release_sha256``); each list's row counts are
        added. Returns the release ids, in order.

        Deep review of #1238: one load at a time for a store (an advisory lock for the transaction, M5); the codes of
        every release older than the one this load replaces are removed (their ``release`` rows stay as the record of
        what was loaded, L7); and a failure in the database is a :class:`LicensedError` (``LIC-STORE``), with nothing
        loaded (L4)."""
        try:
            ids = self._write(parts, version, by, meta)
        except (LicensedError, DatabaseError):
            raise
        except Exception as exc:
            if not type(exc).__module__.startswith("psycopg"):
                raise
            raise LicensedError(
                "LIC-STORE", f"the terminology store refused the load ({type(exc).__name__}); nothing was loaded"
            ) from exc
        _CACHE.clear()
        self._audit(parts, version, by, audit_dir)
        return ids

    def _write(
        self, parts: Sequence[tuple[Parsed, str, str]], version: str, by: str, meta: dict[str, str] | None
    ) -> list[int]:
        at = datetime.now(UTC).isoformat(timespec="seconds")
        ids: list[int] = []
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext('terminology.load'), hashtext(current_schema()))")
            for p, sha, source in parts:
                k = ALL_KINDS[p.kind]
                about = {**(meta or {}), "table_rows": p.rows, "current_rows": p.current}
                was = tx.fetchone("SELECT id, sha256, meta FROM release WHERE kind = ? AND active", (p.kind,))
                tx.execute("UPDATE release SET active = FALSE WHERE kind = ?", (p.kind,))
                same = False
                if was is not None:  # the same release: by the sha256 of the whole release when both have one
                    try:
                        held = json.loads(was[2] or "{}").get("release_sha256", "")
                    except ValueError:
                        held = ""
                    mine = (meta or {}).get("release_sha256", "")
                    same = (held == mine) if (held or mine) else str(was[1]) == sha
                if was is not None and same:
                    # the same file loaded again: the copy it replaces holds nothing more, so that copy's codes go
                    # and the release before it stays the one kept
                    tx.execute("DELETE FROM concept WHERE release_id = ?", (was[0],))
                elif was is not None:  # the release this one replaces is kept; the codes of older ones go
                    tx.execute(
                        "DELETE FROM concept WHERE release_id IN (SELECT id FROM release WHERE kind = ? AND id < ?)",
                        (p.kind, was[0]),
                    )
                rid = tx.fetchval(
                    "INSERT INTO release (kind, system, version, source, sha256, encoding, rows, skipped, loaded_by, "
                    "loaded_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                    (
                        p.kind,
                        k.system,
                        version.strip(),
                        Path(source).name,
                        sha,
                        p.encoding,
                        len(p.concepts),
                        len(p.skipped),
                        by,
                        at,
                        json.dumps(about, ensure_ascii=False),
                    ),
                )
                tx.executemany(
                    "INSERT INTO concept (release_id, code, display, target_system, target_code, extra) "
                    "VALUES (?,?,?,?,?,?)",
                    [
                        (rid, c["code"], c["display"], c["target_system"], c["target_code"], c["extra"])
                        for c in p.concepts
                    ],
                )
                ids.append(int(rid))
        return ids

    def _audit(self, parts: Sequence[tuple[Parsed, str, str]], version: str, by: str, audit_dir: Path | None) -> None:
        adir = audit_dir or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
        if adir is not None:
            from tb_common.audit_writer import open_audit

            audit = open_audit(adir, site_tz())
            for p, sha, source in parts:
                audit.append(
                    "terminology.load",
                    actor=by,
                    output_sha=sha,
                    detail={
                        "kind": p.kind,
                        "version": version.strip(),
                        "source": Path(source).name,
                        "rows": len(p.concepts),
                        "skipped": len(p.skipped),
                    },
                )

    def releases(self, kind: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM release" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return self._db.fetchdicts(q, (kind,) if kind else ())

    def status(self, all_lists: bool = False) -> list[dict[str, Any]]:
        """Each list: ``loaded`` with its version, source, rows and date, or ``not loaded``. D-1257 adds, for a
        loaded list: ``released`` (the release's own date, when it says one), ``table_rows`` and ``current_rows``
        (rows of its table, and those with a current 変更区分; ``rows`` stays the number of codes), ``loaded_by`` and
        ``sha256`` (of the whole release when it came as one, else of the file). ``all_lists`` adds the lists that
        are not :data:`KINDS` (the MEDIS 索引テーブル)."""
        active = {r["kind"]: r for r in self._db.fetchdicts("SELECT * FROM release WHERE active ORDER BY id")}
        out = []
        for name, k in (ALL_KINDS if all_lists else KINDS).items():
            r = active.get(name)
            try:
                meta = json.loads(r["meta"]) if r and r.get("meta") else {}
            except ValueError:
                meta = {}
            out.append(
                {
                    "kind": name,
                    "label": k.label,
                    "system": k.system,
                    "state": "loaded" if r else "not_loaded",
                    "version": r["version"] if r else "",
                    "source": r["source"] if r else "",
                    "rows": int(r["rows"]) if r else 0,
                    "loaded_at": r["loaded_at"] if r else "",
                    "released": str(meta.get("released", "")),
                    "table_rows": int(meta.get("table_rows", r["rows"] if r else 0) or 0),
                    "current_rows": int(meta.get("current_rows", r["rows"] if r else 0) or 0),
                    "loaded_by": r["loaded_by"] if r else "",
                    "sha256": str(meta.get("release_sha256") or (r["sha256"] if r else "")),
                }
            )
        return out

    def snapshot(self, kinds: Sequence[str]) -> tuple[dict[str, dict[str, dict[str, str]]], str]:
        """The active releases' codes of ``kinds`` and the newest ``loaded_at`` among them, read in ONE statement:
        one view of the store, never one list from before a load and another from after it (deep review, L7)."""
        rows = self._db.fetchdicts(
            "SELECT r.kind, r.loaded_at, c.code, c.display, c.target_system, c.target_code, c.extra FROM release r "
            "LEFT JOIN concept c ON c.release_id = r.id WHERE r.active AND r.kind = ANY(?)",
            (list(kinds),),
        )
        out: dict[str, dict[str, dict[str, str]]] = {k: {} for k in kinds}
        loaded = ""
        for r in rows:
            loaded = max(loaded, str(r["loaded_at"] or ""))
            if r["code"] is not None:
                out[r["kind"]][r["code"]] = {k: r[k] for k in ("display", "target_system", "target_code", "extra")}
        return out, loaded

    def concepts(self, kind: str) -> dict[str, dict[str, str]]:
        """The active release's codes: ``code -> {display, target_system, target_code, extra}``."""
        rows = self._db.fetchdicts(
            "SELECT c.code, c.display, c.target_system, c.target_code, c.extra FROM concept c "
            "JOIN release r ON r.id = c.release_id WHERE r.kind = ? AND r.active",
            (kind,),
        )
        return {r["code"]: {k: r[k] for k in ("display", "target_system", "target_code", "extra")} for r in rows}

    def lookup_term(self, term: str) -> list[dict[str, str]]:
        """The rows of the loaded 索引テーブル for one 索引用語, compared by :func:`index_key` (the term is stored
        under that key at load): each ``{term, code, target_kind, kana_kanji, synonym, variant}``, ``term`` as the
        release writes it. ``code`` is the 対応用語コード: the 病名交換用コード of a disease (``target_kind`` 1) or the
        修飾語交換用コード of a modifier (2); ``0000`` names no current term and is given as it is, never resolved. A
        term may have several rows (D-1257)."""
        rows = self._db.fetchdicts(
            "SELECT c.code, c.display, c.target_code, c.extra FROM concept c JOIN release r ON r.id = c.release_id "
            "WHERE r.kind = ? AND r.active AND c.display = ? ORDER BY c.target_code, c.code",
            (INDEX, index_key(term)),
        )
        out = []
        for r in rows:
            extra = json.loads(r["extra"] or "{}")
            out.append({"term": extra.pop("term", r["display"]), "code": r["target_code"], **extra})
        return out


# ---------------------------------------------------------------------------------------------- a MEDIS release
#: the files of a MEDIS release by their base name, compared in lower case (D-1257): the three tables carry the
#: version's digits in their name (``nmain518.txt``)
_RELEASE_FILES = {
    "readme": re.compile(r"^readme\.txt$"),
    "medis": re.compile(r"^nmain\d*\.txt$"),
    "medis_modifier": re.compile(r"^mdfy\d*\.txt$"),
    INDEX: re.compile(r"^index\d*\.txt$"),
    "ttl:medis": re.compile(r"^ttl_main\.txt$"),
    "ttl:medis_modifier": re.compile(r"^ttl_mdfy\.txt$"),
    f"ttl:{INDEX}": re.compile(r"^ttl_idx\.txt$"),
}
RELEASE_TABLES = ("medis", "medis_modifier", INDEX)
#: bounds on a release archive (V5.18: a zip of 2.8 MB holding tables of 4.4, 6.4 and 0.2 MB)
RELEASE_MAX_ZIP = 32 * 1024 * 1024
RELEASE_MAX_MEMBERS = 500
RELEASE_MAX_FILE = 16 * 1024 * 1024  # deep review of #1238 (M6): the largest real table is 6.4 MB
#: readme.txt's first line: "ICD10対応標準病名マスター　V5.18　2026年6月1日改訂" (read after NFKC)
#: The line is that and nothing else (deep review of #1238, L5): a version inside a sentence is not the release's
_README = re.compile(
    r"^\s*(?:ICD\s*10\s*対応\s*)?標準病名マスター\s*V\s*(\d+(?:\.\d+)+)\s+"
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:改訂|改定|版|発行)?\s*$"
)


def _wanted(name: str) -> str:
    """Which file of a release a member or file name is, by its base name alone (no folder of the name is used)."""
    base = re.split(r"[/\\]", name)[-1].lower()
    return next((what for what, pattern in _RELEASE_FILES.items() if pattern.match(base)), "")


def _release_files(source: Path | str) -> tuple[dict[str, bytes], dict[str, str], str]:
    """``(bytes by file, name by file, sha256)`` of a release given as a folder or a zip. Nothing is written
    anywhere: a zip's members are read in memory, only those whose base name is a release file, each bounded; a
    file the release must hold that is missing, or that is there twice, refuses the release."""
    src = Path(source)
    found: dict[str, bytes] = {}
    names: dict[str, str] = {}

    def take(what: str, name: str, read: Any) -> None:
        if what in found:
            raise LicensedError("LIC-RELEASE-TWICE", f"the release holds two files named like {names[what]}")
        found[what], names[what] = read(), re.split(r"[/\\]", name)[-1]

    if src.is_dir():
        for f in sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink()):
            what = _wanted(f.name)
            if what:
                if f.stat().st_size > RELEASE_MAX_FILE:
                    raise LicensedError("LIC-RELEASE-SIZE", f"{f.name} is larger than a release's file can be")
                take(what, f.name, f.read_bytes)
        digest = hashlib.sha256()
        for what in sorted(found):  # a folder's sha256: its release files, in a fixed order
            digest.update(what.encode() + b"\0" + hashlib.sha256(found[what]).digest())
        sha = digest.hexdigest()
    elif src.is_file():
        if src.stat().st_size > RELEASE_MAX_ZIP:
            raise LicensedError("LIC-RELEASE-SIZE", "the archive is larger than a release can be")
        raw = src.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = zf.infolist()
                if len(members) > RELEASE_MAX_MEMBERS:
                    raise LicensedError("LIC-RELEASE-SIZE", "the archive holds more files than a release does")
                for info in members:
                    what = "" if info.is_dir() else _wanted(info.filename)
                    if not what:
                        continue
                    if info.file_size > RELEASE_MAX_FILE:
                        raise LicensedError("LIC-RELEASE-SIZE", "a file of the archive is larger than a release's")

                    def read(info: zipfile.ZipInfo = info) -> bytes:
                        with zf.open(info) as fh:
                            data = fh.read(RELEASE_MAX_FILE + 1)
                        if len(data) > RELEASE_MAX_FILE:  # the size its header states was not its size
                            raise LicensedError("LIC-RELEASE-SIZE", "a file of the archive is larger than it says")
                        return data

                    take(what, info.filename, read)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error) as exc:
            raise LicensedError("LIC-RELEASE-ARCHIVE", f"the archive cannot be read ({type(exc).__name__})") from exc
    else:
        raise LicensedError("LIC-RELEASE-SOURCE", "the release is a folder or a zip file; neither was found")
    missing = [what for what in _RELEASE_FILES if what not in found]
    if missing:
        said = {"readme": "readme.txt", "medis": "nmain*.txt", "medis_modifier": "mdfy*.txt", INDEX: "index*.txt"}
        said.update({"ttl:medis": "ttl_main.txt", "ttl:medis_modifier": "ttl_mdfy.txt", f"ttl:{INDEX}": "ttl_idx.txt"})
        raise LicensedError("LIC-RELEASE-MISSING", "the release lacks " + ", ".join(said[m] for m in missing))
    return found, names, sha


def _titles(data: bytes) -> list[str]:
    """The column titles of a ``ttl_*.txt``: the cells of its one line, or one title on each line."""
    text, _enc = _decode(data, RELEASE_ENCODING)
    rows = [
        r for r in csv.reader(io.StringIO(text), delimiter=_sniff(text.split("\n", 1)[0])) if any(c.strip() for c in r)
    ]
    if len(rows) == 1:
        return [c.strip() for c in rows[0]]
    if rows and all(len([c for c in r if c.strip()]) == 1 for r in rows):
        return [next(c.strip() for c in r if c.strip()) for r in rows]
    raise LicensedError("LIC-RELEASE-TITLES", "a title file is neither one line of titles nor one title on each line")


def _read_release(source: Path | str) -> tuple[dict[str, Any], list[tuple[Parsed, str, str]]]:
    files, names, sha = _release_files(source)
    try:
        readme, _enc = _decode(files["readme"], RELEASE_ENCODING)
    except LicensedError as exc:
        raise LicensedError(exc.code, f"{names['readme']}: {exc.message}") from exc
    first = unicodedata.normalize("NFKC", readme.lstrip("﻿").split("\n", 1)[0])
    _refuse_characters(readme)
    m = _README.match(first.strip())
    if not m:
        raise LicensedError(
            "LIC-RELEASE-README",
            "readme.txt's first line is not the release's own title with its version and date "
            "(ICD10対応標準病名マスター V5.18 2026年6月1日改訂)",
        )
    version = m.group(1)
    try:
        released = date(int(m.group(2)), int(m.group(3)), int(m.group(4))).isoformat()
    except ValueError as exc:
        raise LicensedError("LIC-RELEASE-README", "readme.txt's first line gives a date that is no date") from exc
    # the tables carry the version's digits in their names (``nmain518.txt`` of V5.18): a table of another release
    # in this one's folder is refused
    digits = version.replace(".", "")
    for table in RELEASE_TABLES:
        named = "".join(ch for ch in names[table].rsplit(".", 1)[0] if ch.isdigit())
        if named and named != digits:
            raise LicensedError(
                "LIC-RELEASE-VERSION", f"{names[table]} is not a table of version {version}, which readme.txt names"
            )
    parts: list[tuple[Parsed, str, str]] = []
    skipped: list[tuple[str, int, str]] = []
    for table in RELEASE_TABLES:
        try:
            parsed = parse(table, files[table], _titles(files[f"ttl:{table}"]), RELEASE_ENCODING, MAX_ROWS)
        except LicensedError as exc:
            raise LicensedError(exc.code, f"{names[table]}: {exc.message}") from exc
        parts.append((parsed, hashlib.sha256(files[table]).hexdigest(), names[table]))
        skipped += [(table, n, why) for n, why in parsed.skipped]
    by_kind = {p.kind: p for p, _sha, _name in parts}
    report = {
        "version": version,
        "released": released,
        "disease_rows": by_kind["medis"].rows,
        "disease_current": by_kind["medis"].current,
        "modifier_rows": by_kind["medis_modifier"].rows,
        "index_rows": by_kind[INDEX].rows,
        "skipped": skipped,
        "sha256": sha,
    }
    return report, parts


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version))


def _refuse_older(store: TermStore, report: dict[str, Any]) -> None:
    """A release older than the one loaded is refused (deep review of #1238, L5): it would silently take codes
    away. Older by its version, or by its date when both say one."""
    for s in store.status():
        if s["kind"] != "medis" or s["state"] != "loaded":
            continue
        older = _version_key(report["version"]) < _version_key(str(s["version"]))
        if s["released"] and report["released"] < str(s["released"]):
            older = True
        if older:
            raise LicensedError(
                "LIC-RELEASE-OLDER",
                f"version {report['version']} ({report['released']}) is older than the loaded version "
                f"{s['version']}" + (f" ({s['released']})" if s["released"] else "") + "; not loaded",
            )


def _refuse_same(store: TermStore, report: dict[str, Any]) -> None:
    """The very release that is loaded (the same sha256) is not loaded again unasked."""
    for s in store.status():
        if s["kind"] == "medis" and s["state"] == "loaded" and s["sha256"] == report["sha256"]:
            raise LicensedError(
                "LIC-RELEASE-LOADED",
                f"this release is already loaded (version {s['version']}"
                + (f", {s['released']}" if s["released"] else "")
                + f", loaded {s['loaded_at']} by {s['loaded_by']}); not loaded again",
            )


def check_release(source: Path | str, store: TermStore | None = None) -> dict[str, Any]:
    """What :func:`load_release` would load from ``source``, read by the same code, with nothing written: the same
    keys. A person is shown this before approving the load. With ``store``, a release :func:`load_release` would
    refuse as older than the loaded one is refused here too."""
    report = _read_release(source)[0]
    if store is not None:
        _refuse_older(store, report)
    return report


def load_release(
    store: TermStore,
    source: Path | str,
    *,
    by: str,
    audit_dir: Path | None = None,
    allow_older: bool = False,
    allow_reload: bool = False,
) -> dict[str, Any]:
    """Load a MEDIS ICD10対応標準病名マスター release as MEDIS ships it (D-1257). ``source`` is the release's folder or
    its zip (``readme.txt``, ``main/nmain*.txt`` 病名基本, ``main/mdfy*.txt`` 修飾語, ``main/index*.txt`` 索引,
    ``option/ttl_main.txt``, ``ttl_mdfy.txt``, ``ttl_idx.txt``; anything else in it is ignored). The column titles
    come from ``option/`` (the tables have no header row); the version and the release date from readme's first
    line, and a readme that does not give them refuses the load (no version is guessed). The three tables are
    written in one transaction: all or nothing.

    A release older than the loaded one is refused (``LIC-RELEASE-OLDER``) unless ``allow_older`` is given: a
    deliberate step back, never what a page does by default. The release that is already loaded (the same sha256)
    is refused (``LIC-RELEASE-LOADED``) unless ``allow_reload`` is given: a person's explicit "load again"; the copy
    it replaces is then not kept twice.

    Returns ``{"version", "released" (YYYY-MM-DD), "disease_rows", "disease_current", "modifier_rows",
    "index_rows", "skipped": [(table, line, reason)], "sha256"}``: ``sha256`` of the zip, or for a folder of its
    release files. Nothing of the release is kept outside the terminology store; the file itself is the site's and
    never part of TrialBox."""
    report, parts = _read_release(source)
    if not allow_older:
        _refuse_older(store, report)
    if not allow_reload:
        _refuse_same(store, report)
    store.load_parsed(
        parts,
        version=report["version"],
        by=by,
        meta={"released": report["released"], "release_sha256": report["sha256"]},
        audit_dir=audit_dir,
    )
    return report


def status(url: str | None = None, all_lists: bool = False) -> list[dict[str, Any]]:
    """:meth:`TermStore.status`, or every list ``not loaded`` (with ``store: unavailable``) when there is no store."""
    try:
        st = TermStore(url)
    except DatabaseError:
        return [
            {
                "kind": n,
                "label": k.label,
                "system": k.system,
                "state": "not_loaded",
                "version": "",
                "source": "",
                "rows": 0,
                "loaded_at": "",
                "released": "",
                "table_rows": 0,
                "current_rows": 0,
                "loaded_by": "",
                "sha256": "",
                "store": "unavailable",
            }
            for n, k in (ALL_KINDS if all_lists else KINDS).items()
        ]
    try:
        return st.status(all_lists)
    finally:
        st.close()


_CACHE: dict[str, tuple[float, dict[str, dict[str, dict[str, str]]]]] = {}
CACHE_SECONDS = 30.0


def tables(url: str | None = None, *, cached: bool = False) -> dict[str, dict[str, dict[str, str]]]:
    """Every active release's codes by list (empty lists when nothing is loaded or there is no store). ``cached``
    keeps the answer for :data:`CACHE_SECONDS` (site set-up asks once per code); a load in this process clears it.

    The lists are one view of the store (:meth:`TermStore.snapshot`). When a store is configured and cannot be
    reached, the lists are empty and :func:`unavailable` says so of them (deep review of #1238, M4): empty because
    nothing is loaded and empty because the store is down are not the same night."""
    key = url or os.environ.get(ENV) or ""
    now = time.monotonic()
    hit = _CACHE.get(key)
    if cached and hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    out: dict[str, dict[str, dict[str, str]]]
    try:
        st = TermStore(url)
    except DatabaseError:
        out = {k: {} for k in KINDS}
        _remember(out, "", down=bool(key))
        return out
    try:
        out, loaded = st.snapshot(list(KINDS))
    except Exception as exc:
        if not (isinstance(exc, DatabaseError) or type(exc).__module__.startswith("psycopg")):
            raise
        out = {k: {} for k in KINDS}
        _remember(out, "", down=True)
        return out
    finally:
        st.close()
    _CACHE[key] = (now, out)
    _remember(out, loaded, down=False)
    return out


#: what :func:`tables` gave lately, each with the load time of the newest active release behind it (D-1257) and
#: whether the store could not be reached. The tables themselves are kept, so an identity is never mistaken for
#: another dictionary's
_GIVEN: dict[int, tuple[dict[str, dict[str, dict[str, str]]], str, bool]] = {}
_GIVEN_MAX = 8


def _remember(out: dict[str, dict[str, dict[str, str]]], loaded: str, *, down: bool) -> None:
    _GIVEN[id(out)] = (out, loaded, down)
    while len(_GIVEN) > _GIVEN_MAX:
        _GIVEN.pop(next(iter(_GIVEN)))


def unavailable(given: object) -> bool:
    """Whether ``given`` (a result of :func:`tables`) is empty because a configured terminology store could not be
    reached. A reader whose rows depend on the licensed lists does not read then: a night read without the master
    stores diagnoses as a site without one has them, and no later night sends them again (deep review, M4)."""
    hit = _GIVEN.get(id(given))
    return hit is not None and hit[0] is given and hit[2]


def loaded_at_of(given: object) -> str | None:
    """When the newest active release behind ``given`` (a result of :func:`tables`) was loaded: ISO, UTC, as
    ``release.loaded_at``; empty when no release is loaded. None when ``given`` did not come from :func:`tables` (a
    caller's own dictionary), so the time cannot be known. A reader whose rows depend on the licensed lists uses it
    as part of their change time (D-1257): a release loaded after the delta window opened changes rows whose
    hospital files did not change."""
    hit = _GIVEN.get(id(given))
    return hit[1] if hit is not None and hit[0] is given else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="adapter.licensed", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load", help="load one licensed release into the terminology store")
    ld.add_argument("--kind", required=True, choices=sorted(ALL_KINDS))
    ld.add_argument("--file", required=True, type=Path)
    ld.add_argument("--version", required=True, help="the release's version as printed on it")
    ld.add_argument("--columns", help="column names in file order, for a release without a header row")
    ld.add_argument("--encoding", help="the file's character set when its publisher declares it (cp932 for MEDIS)")
    ld.add_argument("--by", default=os.environ.get("USER", "admin"))
    lr = sub.add_parser("load-release", help="load a MEDIS release as MEDIS ships it (its folder or its zip)")
    lr.add_argument("--source", required=True, type=Path)
    lr.add_argument("--check", action="store_true", help="read it and say what would be loaded; write nothing")
    lr.add_argument("--allow-older", action="store_true", help="load a release older than the loaded one")
    lr.add_argument("--again", action="store_true", help="load the release that is already loaded once more")
    lr.add_argument("--by", default=os.environ.get("USER", "admin"))
    sub.add_parser("status", help="which lists are loaded")
    a = ap.parse_args(argv)
    if a.cmd == "load-release":
        try:
            if a.check:
                out = check_release(a.source)
            else:
                st = TermStore()
                try:
                    out = load_release(st, a.source, by=a.by, allow_older=a.allow_older, allow_reload=a.again)
                finally:
                    st.close()
        except LicensedError as exc:
            print(f"not loaded: {exc.message}", file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "status":
        for s in status(all_lists=True):
            line = f"{s['kind']:14} {s['label']}: "
            line += (
                f"loaded, version {s['version']}"
                + (f" ({s['released']})" if s["released"] else "")
                + f", {s['rows']} codes, {s['table_rows']} rows ({s['current_rows']} current), {s['source']}, "
                f"{s['loaded_at']} by {s['loaded_by']}"
                if s["state"] == "loaded"
                else "not loaded (its codes stay unknown)"
            )
            print(line)
        return 0
    st = TermStore()
    try:
        cols = [c.strip() for c in a.columns.split(",")] if a.columns else None
        out = st.load(
            a.kind,
            a.file.read_bytes(),
            version=a.version,
            source=str(a.file),
            by=a.by,
            columns=cols,
            declared_encoding=a.encoding,
        )
    except LicensedError as exc:
        print(f"not loaded: {exc.message}", file=sys.stderr)
        return 1
    finally:
        st.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
