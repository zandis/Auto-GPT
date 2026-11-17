"""Code systems loaded on the box at install (D-1028, D-1029; TERM-1, D-858).

A code system that may not be committed (LOINC, WHO ICD-10, ATC, a site's own lists: D-1028 as amended by D-1029) is
loaded onto each box at install and at update, by ``python -m tools.terminology_install``, into
``TB_TERMINOLOGY_DIR`` (default ``/data/terminology``). Every table written there has its line in ``manifest.json``:
the source, the version, the licence note, the file's sha256, its rows and when it was loaded. A table with no line,
or whose bytes do not match its line, is refused: it is not read, and ``trialbox doctor`` says so.

Loaders today:

* ``icd10cm_blocks`` and ``icd10cm_index``, from CMS's ICD-10-CM code-tables zip (the tabular list and the
  Alphabetic Index, US public domain): the blocks and chapters (``Ischemic heart diseases``, I20 to I25) and the
  index's main terms and first-level subterms (``Epilepsy``; ``Accident, cerebrovascular``). The FY2026 tables also
  ship in the repository (D-1029); a later release loaded here is read in their place, so a box takes the next
  year's names without a new image. Taiwan's NHI codes diagnoses in ICD-10-CM (its 2023 edition since 2025-01-01,
  D-171); the US release's blocks and index serve its names.

TERM-2 (D-1113 to D-1116), in the order the site's IT loads them (``docs/handover/OFFLINE-MEDIA.md``):

* ``site_<name>``: each of the site's own code lists (a local code or local name and the standard code it stands
  for). The primary source (D-1028 point 2): a name a site list knows resolves through it before every shipped or
  loaded table (D-1113). Never committed.
* ``nhi_drug_list`` (with its ATC column) and ``nhi_service_list``: the NHI open data (OGDL 1.0, with its
  attribution in the manifest line and ``docs/licences/nhi-open-data-attribution.md``).
* ``icd10pcs``: CMS's ICD-10-PCS order or codes file (US public domain, D-1029).
* ``loinc_table``, ``icd10_who``, ``atc_index``: from the site's own copy, after a named person accepted the
  licence. The manifest line names who and when; a licensed table whose line names nobody is refused (D-1114).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

DIR_ENV = "TB_TERMINOLOGY_DIR"
DEFAULT_DIR = "/data/terminology"
MANIFEST = "manifest.json"
ICD_BLOCKS, ICD_INDEX = "icd10cm_blocks", "icd10cm_index"
ICD_LICENCE = "US public domain (CMS, NCHS): ICD-10-CM; source credited"
_RANGE = re.compile(r"^([A-Z][0-9A-Z]{2})-([A-Z][0-9A-Z]{2})$")


class TerminologyRefused(RuntimeError):
    """A loaded table that cannot be trusted: no manifest line, or bytes that do not match it."""


def installed_dir(env: dict[str, str] | None = None) -> Path:
    return Path(((os.environ if env is None else env).get(DIR_ENV) or "").strip() or DEFAULT_DIR)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(directory: Path) -> dict[str, Any]:
    p = directory / MANIFEST
    if not p.is_file():
        return {"tables": {}}
    try:  # TERM-2 review (D-1116): a damaged manifest is a refusal, never a crash of the mapper or the doctor
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TerminologyRefused(f"{p}: not readable JSON ({type(exc).__name__}); load the tables again") from exc
    return data if isinstance(data, dict) and isinstance(data.get("tables"), dict) else {"tables": {}}


_PLAIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")


def _plain_name(name: str) -> bool:
    """A table name is a plain file name: no folder, no ``..`` (a manifest key ``../x`` names nothing here)."""
    return bool(_PLAIN.match(name)) and ".." not in name


def read_table(directory: Path, name: str) -> list[dict[str, Any]] | None:
    """The rows of a loaded table, or None when it is not loaded. Raises :class:`TerminologyRefused` for a table with
    no manifest line or whose sha256 differs from it (a hand-copied or changed file is never read)."""
    if not _plain_name(name):
        raise TerminologyRefused(f"{name!r}: not a plain table name; nothing outside {directory} is read")
    path = directory / f"{name}.parquet"
    if not path.is_file():
        return None
    line = manifest(directory)["tables"].get(name)
    if not line:
        raise TerminologyRefused(f"{path}: no line in {MANIFEST}; load it with tools.terminology_install")
    data = path.read_bytes()  # TERM-2 review: the bytes hashed are the bytes parsed (no swap between the two reads)
    if line.get("sha256") != hashlib.sha256(data).hexdigest():
        raise TerminologyRefused(f"{path}: its sha256 differs from {MANIFEST}; load it again")
    rows: list[dict[str, Any]] = pq.read_table(pa.BufferReader(data)).to_pylist()
    return rows


@dataclass(frozen=True)
class Loaded:
    name: str
    source: str
    version: str
    rows: int
    problem: str = ""


def status(directory: Path) -> list[Loaded]:
    """Each table under the directory and each manifest line: what is loaded, and what is refused and why."""
    try:
        lines, damaged = manifest(directory)["tables"], ""
    except TerminologyRefused as exc:
        lines, damaged = {}, str(exc)
    names = sorted({p.stem for p in directory.glob("*.parquet")} | set(lines)) if directory.is_dir() else []
    out = []
    for n in names:
        line = lines.get(n) or {}
        try:
            if damaged:
                raise TerminologyRefused(damaged)
            rows = read_loaded(directory, n)
            problem = "" if rows is not None else "in the manifest but its file is missing"
        except TerminologyRefused as exc:
            rows, problem = None, str(exc)
        out.append(Loaded(n, str(line.get("source") or ""), str(line.get("version") or ""), len(rows or []), problem))
    return out


# ------------------------------------------------------------------------------------------------ ICD-10-CM (CMS)
def zip_member(z: zipfile.ZipFile, suffix: str) -> bytes:
    names = [n for n in z.namelist() if n.lower().endswith(suffix)]
    if len(names) != 1:
        raise ValueError(f"the zip holds {len(names)} files ending {suffix!r}: not a CMS ICD-10-CM code-tables zip")
    return z.read(names[0])


def _xml(data: bytes) -> ET.Element:
    """A release's XML, refused when it declares a DTD or an entity: nothing for the parser to expand or fetch."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("the release's XML declares a DTD or an entity: refused, not a CMS ICD-10-CM file")
    return ET.fromstring(data)  # noqa: S314 - refused above when the document declares a DTD or an entity


def icd10cm_blocks(tabular: bytes) -> list[dict[str, str]]:
    """Every block and chapter of the tabular list: ``name, first, last``."""
    root = _xml(tabular)
    out: list[dict[str, str]] = []
    for ch in root.iter("chapter"):
        ranges = []
        for sec in ch.findall("section"):
            m = _RANGE.match(sec.get("id") or "")
            if m:
                name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (sec.findtext("desc") or "").strip())
                out.append({"name": name, "first": m.group(1), "last": m.group(2)})
                ranges.append((m.group(1), m.group(2)))
        if ranges:
            name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (ch.findtext("desc") or "").strip())
            out.append({"name": name, "first": ranges[0][0], "last": ranges[-1][1]})
    return out


def icd10cm_index(index: bytes) -> list[dict[str, str]]:
    """Every main term and first-level subterm of the Alphabetic Index that leads to a code or to another term."""
    root = _xml(index)
    out: list[dict[str, str]] = []
    for mt in root.iter("mainTerm"):
        title = " ".join((mt.findtext("title") or "").split())
        code, see = (mt.findtext("code") or "").strip(), " ".join((mt.findtext("see") or "").split())
        if title and (code or see):
            out.append({"term": title, "code": code, "see": "" if code else see})
        for sub in mt.findall("term"):
            st, sc = " ".join((sub.findtext("title") or "").split()), (sub.findtext("code") or "").strip()
            if title and st and sc:
                out.append({"term": f"{title}, {st}", "code": sc, "see": ""})
    return out


def _write(directory: Path, name: str, rows: list[dict[str, str]], cols: tuple[str, ...], line: dict[str, Any]) -> None:
    import fcntl

    path = directory / f"{name}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    # TERM-2 review (D-1116): one loader at a time (a lock around the table's replace and its manifest line), and the
    # manifest is written whole or not at all (a temporary file, fsync, then rename)
    with (directory / ".manifest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pq.write_table(pa.table({c: pa.array([r[c] for r in rows], pa.string()) for c in cols}), tmp,
                       compression="zstd")  # fmt: skip
        tmp.replace(path)
        data = manifest(directory)
        data["tables"][name] = {**line, "sha256": _sha(path), "rows": len(rows)}
        mtmp = directory / f".{MANIFEST}.tmp"
        with mtmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(mtmp, directory / MANIFEST)


def install_icd10cm(zip_path: Path, directory: Path, year: str, now: datetime | None = None) -> dict[str, int]:
    """Load ICD-10-CM's blocks and Alphabetic Index from CMS's code-tables zip of ``year`` (read, never unpacked)."""
    with zipfile.ZipFile(zip_path) as z:
        tab, idx = zip_member(z, f"icd10cm_tabular_{year}.xml"), zip_member(z, f"icd10cm_index_{year}.xml")
    directory.mkdir(parents=True, exist_ok=True)
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    line = {"source": f"CMS ICD-10-CM {year} code tables ({zip_path.name}, sha256 {_sha(zip_path)[:16]})",
            "version": f"ICD-10-CM {year}", "licence": ICD_LICENCE, "loaded_at": when}  # fmt: skip
    blocks, index = icd10cm_blocks(tab), icd10cm_index(idx)
    _write(directory, ICD_BLOCKS, blocks, ("name", "first", "last"), line)
    _write(directory, ICD_INDEX, index, ("term", "code", "see"), line)
    return {ICD_BLOCKS: len(blocks), ICD_INDEX: len(index)}


# ------------------------------------------------------------------------------------- TERM-2 (D-1113 to D-1116)
# The other code systems of D-1028, loaded the same way: one table each (``site_<name>`` for each site list), each with
# its manifest line. In the order the site's IT loads them: the site's own lists (the primary source, D-1028 point 2;
# they win over every other table, D-1113), the NHI open data (OGDL, with its attribution, D-1028 point 3), ICD-10-PCS
# (US public domain, D-1029), then LOINC, WHO ICD-10 and ATC, whose licences a named person accepts (D-1114). None of
# these is committed (D-1116): the site's IT stages the files in ``deploy/site/terminology/`` (ignored by git and by
# the image) and the loader reads them from there.
SITE_PREFIX = "site_"
NHI_DRUGS, NHI_SERVICES, ICD_PCS = "nhi_drug_list", "nhi_service_list", "icd10pcs"
LOINC_TABLE, ICD10_WHO, ATC_INDEX = "loinc_table", "icd10_who", "atc_index"
SITE_LICENCE = "the site's own list (D-1028 point 2): stays on this box, never enters the repository or an image"
OGDL = "Open Government Data License, version 1.0 (Taiwan), https://data.gov.tw/license"
NHI_DRUG_ATTRIBUTION = ("健保用藥品項查詢項目檔, National Health Insurance Administration (衛生福利部中央健康保險署), "
                        "via data.gov.tw (dataset 23715), Open Government Data License 1.0")  # fmt: skip
NHI_SERVICE_ATTRIBUTION = ("全民健康保險醫療服務給付項目及支付標準, National Health Insurance Administration "
                           "(衛生福利部中央健康保險署), via data.gov.tw (dataset 174450), "
                           "Open Government Data License 1.0")  # fmt: skip
PCS_LICENCE = "US public domain (CMS): ICD-10-PCS; source credited"
# the systems whose licence a named person accepts before they are loaded (D-1114), and that licence
LICENSED: dict[str, str] = {
    LOINC_TABLE: "LOINC licence (Regenstrief Institute), https://loinc.org/license/; keep the LOINC notice",
    ICD10_WHO: "WHO ICD-10 (WHO copyright): the site's own licensed copy; never shipped",
    ATC_INDEX: "ATC index (WHOCC copyright, https://atcddd.fhi.no/copyright_disclaimer/): the site's own copy",
}
# what the doctor names when it is not loaded, in the order of the install step
AT_INSTALL: tuple[tuple[str, str], ...] = (
    ("site lists", SITE_PREFIX), ("NHI drug list", NHI_DRUGS), ("NHI service codes", NHI_SERVICES),
    ("ICD-10-PCS", ICD_PCS), ("LOINC", LOINC_TABLE), ("WHO ICD-10", ICD10_WHO), ("ATC", ATC_INDEX),
)  # fmt: skip
# the code systems a site list may map to (the keys of the mapper's systems)
SITE_SYSTEMS = ("icd10cm", "icd10pcs", "icd10_who", "loinc", "atc", "nhi_drug", "nhi_order",
                "department")  # fmt: skip
_NOT_A_NAME = frozenset({"-", "accept", "accepted", "admin", "administrator", "agree", "hospital", "i agree", "it",
                         "me", "n/a", "na", "none", "ok", "root", "site", "the site", "test", "unknown", "user", "y",
                         "yes"})  # fmt: skip
_WHO_CODE = re.compile(r"^[A-Z]\d{2}(\.\d+)?$")
_WHO_BLOCK = re.compile(r"^[A-Z]\d{2}-[A-Z]\d{2}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{0,39}$")
_PCS = re.compile(r"^[0-9A-HJ-NP-Z]{3,7}$")
_ATC = re.compile(r"^[A-Z](\d{2}([A-Z]([A-Z](\d{2})?)?)?)?$")
_LOINC = re.compile(r"^\d{1,7}-\d$")
# TERM-2 review (D-1113): the shape of a code in each system a site list may name (after NFKC and upper case)
SITE_CODE_SHAPES: dict[str, re.Pattern[str]] = {
    "icd10cm": re.compile(r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$"),  # written dotted (D-808)
    "icd10_who": re.compile(r"^[A-Z][0-9]{2}(\.[0-9]{1,2})?$"),
    "icd10pcs": re.compile(r"^[0-9A-HJ-NP-Z]{7}$"),
    "loinc": _LOINC,
    "atc": _ATC,
    "nhi_drug": re.compile(r"^[A-Z0-9]{10}$"),
    "nhi_order": re.compile(r"^[0-9A-Z]{2,12}$"),
    "department": re.compile(r"^[0-9A-Z][0-9A-Z._-]{0,19}$"),
}


def site_code(system: str, code: str) -> str:
    """A site list's code as the tables write it (NFKC: full-width ``Ｅ１１`` is E11; upper case), or ValueError when
    it is not shaped as a code of its system (``I109`` without its dot, a word)."""
    import unicodedata

    c = unicodedata.normalize("NFKC", code).strip().upper()
    if not SITE_CODE_SHAPES[system].match(c):
        raise ValueError(f"{code!r} is not a {system} code")
    return c


def is_licensed(name: str) -> bool:
    return name in LICENSED


def licence_line(name: str, accepted_by: str, accepted_on: str = "", now: datetime | None = None) -> dict[str, str]:
    """The manifest fields of a licensed system (D-1114): its licence, the named person who accepted it, and the day.
    Refuses a missing name or a word that names nobody (``yes``, ``admin``, ``IT``)."""
    who = " ".join((accepted_by or "").split())
    letters = [ch for ch in who if ch.isalpha()]
    cjk = any(not ch.isascii() for ch in letters)
    plausible = (cjk and len(letters) >= 2) or (len(who.split()) >= 2 and len(letters) >= 3)
    if not who or who.lower() in _NOT_A_NAME or not plausible:  # a full name: two words, or a CJK name
        raise ValueError(f"{name}: --accepted-by must name the person who accepted the licence ({LICENSED[name]}), "
                         f"not {accepted_by!r}")  # fmt: skip
    day = (accepted_on or "").strip() or (now or datetime.now(UTC)).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError(f"{name}: --accepted-on is a date YYYY-MM-DD, not {accepted_on!r}")
    return {"licence": LICENSED[name], "licence_accepted_by": who, "licence_accepted_on": day}


def _refused_licence(directory: Path, name: str, line: dict[str, Any]) -> str:
    if is_licensed(name) and not str(line.get("licence_accepted_by") or "").strip():
        return (f"{directory / (name + '.parquet')}: its manifest line names nobody who accepted its licence "
                "(D-1114); load it again with --accepted-by")  # fmt: skip
    return ""


def accepted(directory: Path, name: str) -> str:
    """``by <who> on <day>`` for a licensed table's manifest line; empty for every other table."""
    line = manifest(directory)["tables"].get(name) or {}
    if not is_licensed(name) or not line.get("licence_accepted_by"):
        return ""
    return f"licence accepted by {line['licence_accepted_by']} on {line.get('licence_accepted_on') or '?'}"


def read_loaded(directory: Path, name: str) -> list[dict[str, Any]] | None:
    """:func:`read_table`, and for a licensed system also refused when its line names nobody who accepted the
    licence (D-1114)."""
    rows = read_table(directory, name)
    if rows is not None:
        problem = _refused_licence(directory, name, manifest(directory)["tables"].get(name) or {})
        if problem:
            raise TerminologyRefused(problem)
    return rows


def not_loaded(directory: Path) -> list[str]:
    """The install-time systems (``AT_INSTALL``) with no table in the directory, in the order of the install step."""
    have = {p.stem for p in directory.glob("*.parquet")} if directory.is_dir() else set()
    return [label for label, t in AT_INSTALL if not any(h == t or (t == SITE_PREFIX and h.startswith(t)) for h in have)]


def _source(path: Path, suffixes: tuple[str, ...], what: str) -> tuple[bytes, str]:
    """The file's bytes, or, for a zip, those of its one member ending with the first of ``suffixes`` that one member
    ends with (read, never unpacked)."""
    if not zipfile.is_zipfile(path):
        return path.read_bytes(), path.name
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for suffix in suffixes:
            hits = [n for n in names if n.lower().endswith(suffix.lower())]
            if len(hits) == 1:
                return z.read(hits[0]), hits[0]
    raise ValueError(f"{path.name}: no single member ending {' or '.join(suffixes)}: not {what}")


def _text(data: bytes, what: str) -> str:
    """UTF-8 (BOM or not), else Big5 (cp950, as older Taiwan files are written)."""
    for enc in ("utf-8-sig", "cp950"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{what}: neither UTF-8 nor Big5 text")


def table_rows(text: str, what: str) -> list[dict[str, str]]:
    """A CSV or TSV (a tab in the header line makes it TSV) as stripped dicts; header names compared in lower case."""
    import csv
    import io

    lines = text.lstrip("﻿").splitlines()
    if not lines:
        raise ValueError(f"{what}: empty")
    delim = "\t" if "\t" in lines[0] else ","
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if k is not None}
            for r in csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)]  # fmt: skip
    rows = [r for r in rows if any(r.values())]
    if not rows:
        raise ValueError(f"{what}: no rows")
    return rows


def _col(rows: list[dict[str, str]], names: tuple[str, ...], what: str, required: bool = True) -> str:
    for n in names:
        if n.lower() in rows[0]:
            return n.lower()
    if required:
        raise ValueError(f"{what}: no column {' or '.join(names)} (columns: {', '.join(rows[0])})")
    return ""


def _line(what: str, path: Path, version: str, licence: str, now: datetime | None, **more: str) -> dict[str, Any]:
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return {"source": f"{what} ({path.name}, sha256 {_sha(path)[:16]})", "version": version, "licence": licence,
            "loaded_at": when, **more}  # fmt: skip


# ------------------------------------------------------------------------------------------- the site's own lists
def site_list_rows(text: str, system: str = "", what: str = "the site list") -> list[dict[str, str]]:
    """A site list (D-1113): one row per local code or local name and the standard code it stands for. Columns
    ``local_code`` and/or ``local_name``, ``code``, ``system`` (or one ``system`` for the whole file) and an optional
    ``display``. A row the loader cannot place refuses the whole file (never half-read)."""
    rows = table_rows(text, what)
    lc = _col(rows, ("local_code",), what, required=False)
    ln = _col(rows, ("local_name",), what, required=False)
    if not lc and not ln:
        raise ValueError(f"{what}: no column local_code or local_name")
    code, sy = _col(rows, ("code",), what), _col(rows, ("system",), what, required=not system)
    disp = _col(rows, ("display",), what, required=False)
    out = []
    seen: dict[tuple[str, str, str], tuple[str, int]] = {}  # (system, local code or name) -> (code, line)
    for i, r in enumerate(rows, start=2):
        s = (r.get(sy, "") if sy else "") or system
        if s not in SITE_SYSTEMS:
            raise ValueError(f"{what}, line {i}: system {s!r} is not one of {', '.join(SITE_SYSTEMS)}")
        if not r.get(code) or not (r.get(lc, "") or r.get(ln, "")):
            raise ValueError(f"{what}, line {i}: a row needs a code and a local code or a local name")
        try:
            c = site_code(s, r[code])
        except ValueError as exc:
            raise ValueError(f"{what}, line {i}: {exc}") from exc
        local = {"local_code": r.get(lc, "") if lc else "", "local_name": r.get(ln, "") if ln else ""}
        for kind, value in local.items():  # one local code or name, two standard codes: the list contradicts itself
            key = (s, kind, " ".join(value.lower().split()))
            if value and key in seen and seen[key][0] != c:
                raise ValueError(f"{what}, line {i}: {kind} {value!r} is {c} here and {seen[key][0]} on line "
                                 f"{seen[key][1]}")  # fmt: skip
            if value:
                seen.setdefault(key, (c, i))
        out.append({**local, "system": s, "code": c, "display": r.get(disp, "") if disp else ""})
    return out


def install_site_list(path: Path, directory: Path, name: str, system: str = "", version: str = "",
                      now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """Load one of the site's own code lists as ``site_<name>`` (CSV or TSV, UTF-8 or Big5). It stays on the box."""
    if not _SLUG.match(name):
        raise ValueError(f"--name {name!r}: lower-case letters, digits and _ only (it names the table site_<name>)")
    if system and system not in SITE_SYSTEMS:
        raise ValueError(f"--system {system!r} is not one of {', '.join(SITE_SYSTEMS)}")
    rows = site_list_rows(_text(path.read_bytes(), str(path.name)), system, f"site list {path.name}")
    directory.mkdir(parents=True, exist_ok=True)
    table = SITE_PREFIX + name
    line = _line(f"site list {name}", path, version or f"{path.name} as loaded", SITE_LICENCE, now)
    _write(directory, table, rows, ("local_code", "local_name", "system", "code", "display"), line)
    return {table: len(rows)}


# ------------------------------------------------------------------------------------------------- NHI open data
def install_nhi_drugs(path: Path, directory: Path, version: str = "", now: datetime | None = None) -> dict[str, int]:
    """The NHI drug list 健保用藥品項查詢項目檔 (data.gov.tw 23715, the CSV NHIA publishes; its columns as
    ``tb_common.refdata_tw`` reads them): one row per 藥品代號, the newest validity period, with its ATC代碼 (kept
    only when ATC-shaped) and its 成分 (ingredient)."""
    from tb_common.refdata_tw import latest_nhi_rows

    rows = []
    for code, r in sorted(latest_nhi_rows(path).items()):
        atc = r.get("ATC代碼", "").strip().upper()
        rows.append({"nhi_code": code, "name": r.get("藥品英文名稱", ""), "name_zh": r.get("藥品中文名稱", ""),
                     "ingredient": r.get("成分", ""), "atc": atc if _ATC.match(atc) else "",
                     "valid_to": r.get("有效迄日", "")})  # fmt: skip
    directory.mkdir(parents=True, exist_ok=True)
    line = _line("NHI drug list (data.gov.tw 23715)", path, version or f"{path.name} as loaded", OGDL, now,
                 attribution=NHI_DRUG_ATTRIBUTION)  # fmt: skip
    _write(directory, NHI_DRUGS, rows, ("nhi_code", "name", "name_zh", "ingredient", "atc", "valid_to"), line)
    return {NHI_DRUGS: len(rows)}


def install_nhi_services(path: Path, directory: Path, version: str = "", now: datetime | None = None) -> dict[str, int]:
    """The NHI medical service and order codes 醫療服務給付項目及支付標準 (data.gov.tw 174450, its CSV as
    ``tb_common.refdata_tw`` reads it): one row per 診療項目代碼, the newest period, Chinese and English names."""
    from tb_common.refdata_tw import parse_nhi_services

    rows = [{"code": t["code"], "display": t["display"], "display_en": t["extra"]["en"],
             "valid_to": t["extra"]["valid_to"]} for t in parse_nhi_services(path)]  # fmt: skip
    directory.mkdir(parents=True, exist_ok=True)
    line = _line("NHI medical service items (data.gov.tw 174450)", path, version or f"{path.name} as loaded", OGDL,
                 now, attribution=NHI_SERVICE_ATTRIBUTION)  # fmt: skip
    _write(directory, NHI_SERVICES, rows, ("code", "display", "display_en", "valid_to"), line)
    return {NHI_SERVICES: len(rows)}


# ----------------------------------------------------------------------------------------------- ICD-10-PCS (CMS)
def icd10pcs_rows(text: str) -> list[dict[str, str]]:
    """CMS's ICD-10-PCS order file (``icd10pcs_order_<year>.txt``: order number, code, header flag, short and long
    description in fixed columns) or codes file (``icd10pcs_codes_<year>.txt``: code, then the long description)."""
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if len(line) > 6 and line[:5].isdigit() and line[5] == " ":  # the order file: always its fixed columns
            code, valid, short, long = line[6:13].strip(), line[14:15], line[16:76].strip(), line[77:].strip()
        else:
            parts = line.split(None, 1)
            code, valid, short, long = parts[0], "1", "", (parts[1].strip() if len(parts) > 1 else "")
        if not _PCS.match(code) or not long or valid not in ("0", "1"):
            raise ValueError(f"line {i}: not a line of CMS's ICD-10-PCS order or codes file")
        out.append({"code": code, "display": long, "short": short, "valid": valid})
    if not out:
        raise ValueError("no ICD-10-PCS codes")
    return out


def install_icd10pcs(path: Path, directory: Path, year: str, now: datetime | None = None) -> dict[str, int]:
    """ICD-10-PCS from CMS's code-files zip (or its order or codes text file) of ``year``."""
    data, member = _source(path, (f"icd10pcs_order_{year}.txt", f"icd10pcs_codes_{year}.txt"),
                           "a CMS ICD-10-PCS code-files zip")  # fmt: skip
    rows = icd10pcs_rows(_text(data, member))
    directory.mkdir(parents=True, exist_ok=True)
    _write(directory, ICD_PCS, rows, ("code", "display", "short", "valid"),
           _line(f"CMS ICD-10-PCS {year} ({member})", path, f"ICD-10-PCS {year}", PCS_LICENCE, now))  # fmt: skip
    return {ICD_PCS: len(rows)}


# --------------------------------------------------------------------------- LOINC, WHO ICD-10, ATC (licensed)
def loinc_rows(text: str) -> list[dict[str, str]]:
    """LOINC's table (``LoincTable/Loinc.csv`` of Regenstrief's download): code, long common name, short name,
    component, specimen (``SYSTEM``), class and status."""
    rows = table_rows(text, "Loinc.csv")
    for c in ("loinc_num", "component", "system", "status", "long_common_name"):
        _col(rows, (c,), "Loinc.csv")
    out = []
    for r in rows:
        if not _LOINC.match(r["loinc_num"]):
            raise ValueError(f"Loinc.csv: {r['loinc_num']!r} is not a LOINC code")
        out.append({"code": r["loinc_num"], "display": r["long_common_name"], "shortname": r.get("shortname", ""),
                    "component": r["component"], "specimen": r["system"], "class": r.get("class", ""),
                    "status": r["status"]})  # fmt: skip
    return out


def install_loinc(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                  now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """LOINC from the site's own download (Regenstrief's zip, or its ``Loinc.csv``), after a named person accepted
    Regenstrief's licence (D-1114)."""
    lic = licence_line(LOINC_TABLE, accepted_by, accepted_on, now)
    data, member = _source(path, ("loinctable/loinc.csv", "/loinc.csv"), "Regenstrief's LOINC zip")
    m = re.search(r"(?i)loinc_?(\d+\.\d+)", path.name)
    ver = version or (f"LOINC {m.group(1)}" if m else "")
    if not ver:
        raise ValueError("loinc: give --version (the LOINC release, e.g. 2.81): the file's name does not say it")
    rows = loinc_rows(_text(data, member))
    directory.mkdir(parents=True, exist_ok=True)
    line = _line(f"LOINC ({member})", path, ver, lic.pop("licence"), now, **lic)
    _write(directory, LOINC_TABLE, rows, ("code", "display", "shortname", "component", "specimen", "class", "status"),
           line)  # fmt: skip
    return {LOINC_TABLE: len(rows)}


def icd10_who_rows(data: bytes) -> tuple[list[dict[str, str]], str]:
    """WHO ICD-10 from its ClaML file (``Class`` code, kind and preferred label; the ``Title`` version), or a CSV or
    TSV with ``code`` and ``title`` columns. A ClaML that declares an entity or an internal DTD is refused; an
    external DTD reference (``<!DOCTYPE ClaML SYSTEM "ClaML.dtd">``) is dropped, never fetched."""
    if data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
        if b"<!ENTITY" in data:
            raise ValueError("the ClaML file declares an entity: refused")
        data = re.sub(rb"<!DOCTYPE[^\[>]*>", b"", data, count=1)
        if b"<!DOCTYPE" in data:
            raise ValueError("the ClaML file declares an internal DTD: refused")
        root = _xml(data)  # TERM-1's parser: it refuses a DTD or an entity, and none is left here
        if root.tag != "ClaML":
            raise ValueError("not a ClaML file")
        title = root.find("Title")
        ver = f"WHO ICD-10 {title.get('version')}" if title is not None and title.get("version") else ""
        out = []
        for cls in root.iter("Class"):
            label = next((" ".join("".join(lb.itertext()).split()) for rb in cls.findall("Rubric")
                          if rb.get("kind") == "preferred" for lb in rb.findall("Label")), "")  # fmt: skip
            code, kind = str(cls.get("code") or ""), str(cls.get("kind") or "")
            # TERM-2 review: a chapter (``I``, ``XXII``) is no code; a block (``A00-A09``) is kept as a block
            if label and (_WHO_CODE.match(code) or (kind == "block" and _WHO_BLOCK.match(code))):
                out.append({"code": code, "display": label, "kind": "block" if "-" in code else "category"})
        return out, ver
    rows = table_rows(_text(data, "WHO ICD-10"), "WHO ICD-10")
    code, label = _col(rows, ("code",), "WHO ICD-10"), _col(rows, ("title", "display"), "WHO ICD-10")
    return [{"code": r[code], "display": r[label], "kind": "category" if "-" not in r[code] else "block"}
            for r in rows if r.get(label) and (_WHO_CODE.match(r.get(code, "")) or _WHO_BLOCK.match(r.get(code, "")))
            ], ""  # fmt: skip


def install_icd10_who(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                      now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """WHO ICD-10 from the site's own licensed copy (ClaML, or a code and title table), after a named person accepted
    its licence (D-1114)."""
    lic = licence_line(ICD10_WHO, accepted_by, accepted_on, now)
    data, member = _source(path, (".xml", ".csv", ".tsv", ".txt"), "WHO ICD-10 (ClaML or a code table)")
    rows, ver = icd10_who_rows(data)
    if not rows:
        raise ValueError(f"{member}: no ICD-10 classes")
    ver = version or ver
    if not ver:
        raise ValueError("icd10who: give --version (the WHO ICD-10 edition): the file does not say it")
    directory.mkdir(parents=True, exist_ok=True)
    line = _line(f"WHO ICD-10 ({member})", path, ver, lic.pop("licence"), now, **lic)
    _write(directory, ICD10_WHO, rows, ("code", "display", "kind"), line)
    return {ICD10_WHO: len(rows)}


def atc_rows(text: str) -> list[dict[str, str]]:
    """The ATC index as a table: the WHOCC's ``ATC code`` and ``ATC level name`` columns (or ``code`` and ``name``)."""
    rows = table_rows(text, "the ATC index")
    code = _col(rows, ("atc code", "atc_code", "code"), "the ATC index")
    name = _col(rows, ("atc level name", "atc_name", "name", "display"), "the ATC index")
    out, seen = [], set()
    for r in rows:
        c = r.get(code, "").upper()
        if not c:
            continue
        if not _ATC.match(c):
            raise ValueError(f"the ATC index: {c!r} is not an ATC code")
        if c not in seen and r.get(name):
            seen.add(c)
            out.append({"code": c, "display": r[name]})
    return out


def install_atc(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """The ATC index from the site's own copy (a CSV or TSV export), after a named person accepted the WHOCC's terms
    (D-1114)."""
    lic = licence_line(ATC_INDEX, accepted_by, accepted_on, now)
    if not version:
        raise ValueError("atc: give --version (the ATC index's year, e.g. 2026)")
    data, member = _source(path, (".csv", ".tsv", ".txt"), "an ATC index table")
    rows = atc_rows(_text(data, member))
    directory.mkdir(parents=True, exist_ok=True)
    line = _line(f"ATC index ({member})", path, f"ATC {version}", lic.pop("licence"), now, **lic)
    _write(directory, ATC_INDEX, rows, ("code", "display"), line)
    return {ATC_INDEX: len(rows)}
