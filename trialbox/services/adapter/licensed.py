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

    python -m adapter.licensed load --kind medis --file NMAIN.TXT --version 5.12 [--columns a,b,c]
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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
            "receipt_code": ("レセプト電算処理システム傷病名コード", "レセプト電算コード", "傷病名コード"),
            "kana": ("病名表記カナ", "病名カナ", "カナ"),
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


def _key(text: str) -> str:
    """A header name for matching: NFKC (full-width letters, digits and brackets become half-width), no spaces."""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", text)).upper()


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


def _col(index: dict[str, int], names: Sequence[str]) -> int | None:
    for n in names:
        i = index.get(_key(n))
        if i is not None:
            return i
    return None


def parse(kind: str, data: bytes, columns: Sequence[str] | None = None) -> Parsed:
    """Read one vendor file. A row whose code does not have the code system's shape is skipped and listed."""
    k = KINDS.get(kind)
    if k is None:
        raise LicensedError("LIC-KIND", f"unknown list {kind!r}: one of {', '.join(KINDS)}")
    try:  # the strict read: a file that already holds U+FFFD is refused with its line, as the sheet reader does
        text, enc = encoding.decode(data, ("cp932",))
    except encoding.EncodingRefused as exc:
        raise LicensedError("LIC-ENCODING", str(exc)) from exc
    first = text.split("\n", 1)[0]
    delim = _sniff(first)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if columns:
        header, body, start = list(columns), rows, 1
    else:
        header, body, start = (rows[0] if rows else []), rows[1:], 2
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
    out: list[dict[str, str]] = []
    skipped: list[tuple[int, str]] = []
    seen: set[str] = set()
    first_row: dict[str, dict[str, str]] = {}
    conflicting: set[str] = set()
    for n, row in enumerate(body, start=start):
        if not any(c.strip() for c in row):
            continue

        def cell(i: int | None, row: list[str] = row) -> str:
            return unicodedata.normalize("NFKC", row[i]).strip() if i is not None and i < len(row) else ""

        if code_i is not None:
            code = cell(code_i)
        else:
            code = "".join(cell(i) for i in part_i)
        code = code.upper()
        if not shape.match(code):
            skipped.append((n, f"code {code!r} is not a {k.label} code"))
            continue
        target = cell(targ_i).upper().replace(" ", "") if targ_i is not None else ""
        record = {
            "code": code,
            "display": cell(disp_i),
            "target_system": k.target_system if target else "",
            "target_code": target,
            "extra": json.dumps({x: cell(i) for x, i in extra_i.items() if cell(i)}, ensure_ascii=False),
        }
        if code in seen:
            if kind in CHANGE_REQUIRED and record != first_row[code]:
                # D-1252: one MEDIS code on two different rows: which is the master's cannot be told, so neither is
                # read (the reader then does not recognise the code); listed
                conflicting.add(code)
                skipped.append((n, f"code {code} appears twice with different content; neither row is read"))
            else:
                skipped.append((n, f"code {code} appears twice; the first row is kept"))
            continue
        seen.add(code)
        first_row[code] = record
        out.append(record)
    out = [r for r in out if r["code"] not in conflicting]
    if not out:
        raise LicensedError("LIC-EMPTY", "no row with a code was found")
    if kind in CHANGE_REQUIRED and not any(json.loads(c["extra"]).get("change") for c in out):
        raise LicensedError("LIC-COLUMNS", "the 変更区分 column is empty in every row (D-1252): check the release")
    return Parsed(kind, enc, "tab" if delim == "\t" else "comma", out, skipped)


class TermStore:
    """Schema ``terminology`` of the trial database: each loaded release and its codes."""

    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), "terminology")
        self._db.migrate([SCHEMA])

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
    ) -> dict[str, Any]:
        """Load one release; the earlier release of the same list stays in the store, inactive. With ``audit_dir``
        (or ``TB_AUDIT_DIR``) the load is in the hash-chained audit (``terminology.load``)."""
        if not version.strip():
            raise LicensedError("LIC-VERSION", "say which release this is (the version printed on it)")
        p = parse(kind, data, columns)
        k = KINDS[kind]
        sha = hashlib.sha256(data).hexdigest()
        at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            tx.execute("UPDATE release SET active = FALSE WHERE kind = ?", (kind,))
            rid = tx.fetchval(
                "INSERT INTO release (kind, system, version, source, sha256, encoding, rows, skipped, loaded_by, "
                "loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (
                    kind,
                    k.system,
                    version.strip(),
                    Path(source).name,
                    sha,
                    p.encoding,
                    len(p.concepts),
                    len(p.skipped),
                    by,
                    at,
                ),
            )
            tx.executemany(
                "INSERT INTO concept (release_id, code, display, target_system, target_code, extra) "
                "VALUES (?,?,?,?,?,?)",
                [(rid, c["code"], c["display"], c["target_system"], c["target_code"], c["extra"]) for c in p.concepts],
            )
        _CACHE.clear()
        adir = audit_dir or (Path(os.environ["TB_AUDIT_DIR"]) if os.environ.get("TB_AUDIT_DIR") else None)
        if adir is not None:
            from tb_common.audit_writer import open_audit

            open_audit(adir, site_tz()).append(
                "terminology.load",
                actor=by,
                output_sha=sha,
                detail={
                    "kind": kind,
                    "version": version.strip(),
                    "source": Path(source).name,
                    "rows": len(p.concepts),
                    "skipped": len(p.skipped),
                },
            )
        return {
            "kind": kind,
            "system": k.system,
            "version": version.strip(),
            "source": Path(source).name,
            "sha256": sha,
            "encoding": p.encoding,
            "delimiter": p.delimiter,
            "rows": len(p.concepts),
            "skipped": [{"line": n, "why": w} for n, w in p.skipped],
            "release_id": int(rid),
        }

    def releases(self, kind: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM release" + (" WHERE kind = ?" if kind else "") + " ORDER BY id"
        return self._db.fetchdicts(q, (kind,) if kind else ())

    def status(self) -> list[dict[str, Any]]:
        """Each list: ``loaded`` with its version, source, rows and date, or ``not loaded``."""
        active = {r["kind"]: r for r in self._db.fetchdicts("SELECT * FROM release WHERE active ORDER BY id")}
        out = []
        for name, k in KINDS.items():
            r = active.get(name)
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
                }
            )
        return out

    def concepts(self, kind: str) -> dict[str, dict[str, str]]:
        """The active release's codes: ``code -> {display, target_system, target_code, extra}``."""
        rows = self._db.fetchdicts(
            "SELECT c.code, c.display, c.target_system, c.target_code, c.extra FROM concept c "
            "JOIN release r ON r.id = c.release_id WHERE r.kind = ? AND r.active",
            (kind,),
        )
        return {r["code"]: {k: r[k] for k in ("display", "target_system", "target_code", "extra")} for r in rows}


def status(url: str | None = None) -> list[dict[str, Any]]:
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
                "store": "unavailable",
            }
            for n, k in KINDS.items()
        ]
    try:
        return st.status()
    finally:
        st.close()


_CACHE: dict[str, tuple[float, dict[str, dict[str, dict[str, str]]]]] = {}
CACHE_SECONDS = 30.0


def tables(url: str | None = None, *, cached: bool = False) -> dict[str, dict[str, dict[str, str]]]:
    """Every active release's codes by list (empty lists when nothing is loaded or there is no store). ``cached``
    keeps the answer for :data:`CACHE_SECONDS` (site set-up asks once per code); a load in this process clears it."""
    key = url or os.environ.get(ENV) or ""
    now = time.monotonic()
    hit = _CACHE.get(key)
    if cached and hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        st = TermStore(url)
    except DatabaseError:
        return {k: {} for k in KINDS}
    try:
        out = {k: st.concepts(k) for k in KINDS}
        loaded = max((str(r["loaded_at"]) for r in st.status() if r["state"] == "loaded"), default="")
    finally:
        st.close()
    _CACHE[key] = (now, out)
    _GIVEN[id(out)] = (out, loaded)
    while len(_GIVEN) > _GIVEN_MAX:
        _GIVEN.pop(next(iter(_GIVEN)))
    return out


#: what :func:`tables` gave lately, each with the load time of the newest active release behind it (D-1257). The
#: tables themselves are kept, so an identity is never mistaken for another dictionary's
_GIVEN: dict[int, tuple[dict[str, dict[str, dict[str, str]]], str]] = {}
_GIVEN_MAX = 8


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
    ld.add_argument("--kind", required=True, choices=sorted(KINDS))
    ld.add_argument("--file", required=True, type=Path)
    ld.add_argument("--version", required=True, help="the release's version as printed on it")
    ld.add_argument("--columns", help="column names in file order, for a release without a header row")
    ld.add_argument("--by", default=os.environ.get("USER", "admin"))
    sub.add_parser("status", help="which lists are loaded")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        for s in status():
            line = f"{s['kind']:7} {s['label']}: "
            line += (
                f"loaded, version {s['version']}, {s['rows']} codes, {s['source']}, {s['loaded_at']}"
                if s["state"] == "loaded"
                else "not loaded (its codes stay unknown)"
            )
            print(line)
        return 0
    st = TermStore()
    try:
        cols = [c.strip() for c in a.columns.split(",")] if a.columns else None
        out = st.load(a.kind, a.file.read_bytes(), version=a.version, source=str(a.file), by=a.by, columns=cols)
    except LicensedError as exc:
        print(f"not loaded: {exc.message}", file=sys.stderr)
        return 1
    finally:
        st.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
