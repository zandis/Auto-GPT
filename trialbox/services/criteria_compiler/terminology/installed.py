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

import codecs
import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.parsers import expat

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
    rows: list[dict[str, Any]] = pq.ParquetFile(pa.BufferReader(data)).read(use_threads=False).to_pylist()
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


#: byte order marks, longest first (a UTF-32 LE mark begins with the UTF-16 LE one)
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
#: the first four bytes of a document with no mark that starts with "<" (XML 1.0, appendix F)
_SNIFF = {
    b"\x00\x00\x00<": "utf-32-be",
    b"<\x00\x00\x00": "utf-32-le",
    b"\x00<\x00?": "utf-16-be",
    b"<\x00?\x00": "utf-16-le",
}
#: the encodings a release may be written in: the ones the XML parser itself reads (UTF-8 and UTF-16, ASCII and
#: Latin-1) and UTF-32; any other declared name is refused, never guessed
_FAMILY = {
    "utf-8": "utf-8", "utf8": "utf-8",
    "utf-16": "utf-16", "utf-16le": "utf-16", "utf-16be": "utf-16",
    "utf-32": "utf-32", "utf-32le": "utf-32", "utf-32be": "utf-32",
    "us-ascii": "ascii", "ascii": "ascii", "iso-8859-1": "latin-1", "latin1": "latin-1", "latin-1": "latin-1",
}  # fmt: skip
_DECL = re.compile(r"""<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""")


def _family(codec: str) -> str:
    return codec.removesuffix("-le").removesuffix("-be")


def xml_text(data: bytes, what: str = "the release's XML") -> str:
    """The document's text, its encoding decided first (H10G39-01): the byte order mark, else the first four bytes
    (XML 1.0 appendix F), else the XML declaration, else UTF-8. Refused when the bytes are not that encoding, or when
    the declaration names an encoding outside :data:`_FAMILY` or another one than the bytes are in. A guard that reads
    raw bytes misses ``<!DOCTYPE`` written in UTF-16 or UTF-32; the caller's guard reads this text instead."""
    codec, body = None, data
    for bom, c in _BOMS:
        if data.startswith(bom):
            codec, body = c, data[len(bom) :]
            break
    codec = codec or _SNIFF.get(data[:4])
    if codec is None:  # an ASCII-compatible start: the declaration, read byte for byte, names the encoding
        m = _DECL.match(data.decode("latin-1"))
        declared = m.group(1).strip().lower() if m else "utf-8"
        family = _FAMILY.get(declared)
        if family is None or family in ("utf-16", "utf-32"):
            raise ValueError(f"{what} declares the encoding {declared!r} and is not written in it: refused")
        codec = family
    try:
        text = body.decode(codec)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{what} is not {codec} text: refused") from exc
    if "\x00" in text:  # U+0000 is no XML character: UTF-16 or UTF-32 with neither a mark nor a declaration
        raise ValueError(f"{what} holds NUL characters as {codec}: its encoding cannot be decided, refused")
    m = _DECL.match(text)
    if m is not None and _FAMILY.get(m.group(1).strip().lower()) != _family(codec):
        raise ValueError(f"{what} declares {m.group(1)!r} and its bytes are {codec}: refused")
    return text


def declares_dtd(text: str) -> bool:
    """The guard, on the decoded text: a document type or an entity declaration anywhere."""
    return "<!DOCTYPE" in text or "<!ENTITY" in text


def _xml(data: bytes, what: str = "the release's XML") -> ET.Element:
    """A release's XML, refused when it declares a DTD or an entity: nothing for the parser to expand or fetch.

    H10G39-01: the encoding is decided first (:func:`xml_text`) and the guard reads the decoded text; the parser is
    then given that text as UTF-8 with the encoding fixed (the declaration's name no longer counts) and refuses a
    document type or an entity declaration itself, so the two can never read different characters."""
    text = xml_text(data, what)
    if declares_dtd(text):
        raise ValueError(f"{what} declares a DTD or an entity: refused, not a CMS ICD-10-CM file")
    builder = ET.TreeBuilder()
    p = expat.ParserCreate(encoding="UTF-8")
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def no_dtd(*_: Any) -> None:
        raise ValueError(f"{what} declares a DTD or an entity: refused, not a CMS ICD-10-CM file")

    p.StartDoctypeDeclHandler = no_dtd
    p.EntityDeclHandler = no_dtd
    p.UnparsedEntityDeclHandler = no_dtd
    p.ExternalEntityRefHandler = no_dtd  # type: ignore[assignment]
    p.StartElementHandler = builder.start
    p.EndElementHandler = builder.end
    p.CharacterDataHandler = builder.data
    try:
        p.Parse(text.encode("utf-8"), True)
    except expat.ExpatError as exc:
        raise ValueError(f"{what} is not well-formed XML (line {exc.lineno}): refused") from None
    return builder.close()


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


def remove_site_list(directory: Path, name: str) -> dict[str, Any]:
    """E-TERM-3 (D-1048): remove one of the site's own lists on purpose: its file and its manifest line, under the
    loader's lock. A list removed this way is no refusal; one whose file is gone while its line stays is. Returns the
    removed line (for the audit event); ValueError when there is no such list."""
    import fcntl

    if not re.fullmatch(r"[a-z0-9_]{1,60}", name):
        raise ValueError(f"--name {name!r}: lower-case letters, digits and _ only (it names the table site_<name>)")
    table = SITE_PREFIX + name
    with (directory / ".manifest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = manifest(directory)
        line = data["tables"].pop(table, None)
        path = directory / f"{table}.parquet"
        if line is None and not path.exists():
            raise ValueError(f"{table}: no such site list in {directory}")
        mtmp = directory / f".{MANIFEST}.tmp"
        with mtmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(mtmp, directory / MANIFEST)
        path.unlink(missing_ok=True)
    return {"table": table, **{k: str(v) for k, v in (line or {}).items() if k in ("version", "sha256", "rows")}}


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
# M2 (DB-C2): the imaging code list. Its source and licence are the owner's (JJ1017): until a hospital names who
# accepted its licence it is a licensed system, loaded only from the hospital's copy, never in the release or a backup
IMAGING_LIST = "imaging_list"
LICENSED[IMAGING_LIST] = (
    "imaging code list (source and licence owner-decided, JJ1017): the hospital's own copy; never shipped"
)
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


def refused_site_lists(directory: Path) -> list[dict[str, str]]:
    """E-TERM-3 (D-1048): each site list on the box that is not read now, ``{"table", "reason"}``: its bytes differ
    from its manifest line, the manifest is damaged, or its file is gone while its line stays. A list removed on
    purpose (``remove_site_list``) has neither file nor line and is not here."""
    return [{"table": t.name, "reason": t.problem} for t in status(directory)
            if t.problem and t.name.startswith(SITE_PREFIX)]  # fmt: skip


def not_loaded(directory: Path) -> list[str]:
    """The install-time systems (``AT_INSTALL``) with no table in the directory, in the order of the install step."""
    have = {p.stem for p in directory.glob("*.parquet")} if directory.is_dir() else set()
    # H-17 (D-1127): an NHI table that ships in the image counts as there
    have |= set(shipped_tables())  # class B review: only a shipped table that reads through its manifest check
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
        except ValueError as exc:  # the sentence is written here, not taken from the error (D-700)
            raise ValueError(f"{what}, line {i}: {r[code]!r} is not a {s} code") from exc
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
def install_nhi_drugs(path: Path, directory: Path, version: str = "", now: datetime | None = None,
                      columns: dict[str, str] | None = None) -> dict[str, int]:  # fmt: skip
    """The NHI drug list 健保用藥品項查詢項目檔 (data.gov.tw 23715, the CSV NHIA publishes; its columns as
    ``tb_common.refdata_tw`` reads them): one row per 藥品代號, the newest validity period, with its ATC代碼 (kept
    only when ATC-shaped) and its 成分 (ingredient). H-17 (D-1127): read by :func:`nhi_drug_rows` (UTF-8 or Big5, the
    header as published or renamed with ``columns``, a malformed row refused with its number)."""
    return _install_nhi(NHI_DRUGS, path.read_bytes(), path.name, directory, version, now, columns)


def install_nhi_services(path: Path, directory: Path, version: str = "", now: datetime | None = None,
                         columns: dict[str, str] | None = None) -> dict[str, int]:  # fmt: skip
    """The NHI medical service and order codes 醫療服務給付項目及支付標準 (data.gov.tw 174450, its CSV as
    ``tb_common.refdata_tw`` reads it): one row per 診療項目代碼, the newest period, Chinese and English names.
    H-17 (D-1127): read by :func:`nhi_service_rows`, as the drug list is."""
    return _install_nhi(NHI_SERVICES, path.read_bytes(), path.name, directory, version, now, columns)


def _install_nhi(table: str, data: bytes, name: str, directory: Path, version: str, now: datetime | None,
                 columns: dict[str, str] | None, **more: str) -> dict[str, int]:  # fmt: skip
    """One NHI table from the file's bytes, read once: the bytes hashed are the bytes parsed (TERM-2's rule)."""
    cols: tuple[str, ...]
    if table == NHI_DRUGS:
        rows, cols, what = nhi_drug_rows(data, name, columns), NHI_DRUG_TABLE, "NHI drug list (data.gov.tw 23715)"
    else:
        rows, cols = nhi_service_rows(data, name, columns), NHI_SERVICE_TABLE
        what = "NHI medical service items (data.gov.tw 174450)"
    directory.mkdir(parents=True, exist_ok=True)
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    line = {"source": f"{what} ({name}, sha256 {hashlib.sha256(data).hexdigest()[:16]})",
            "version": version or f"{name} as loaded", "licence": OGDL, "loaded_at": when,
            "attribution": SHIPPABLE[table], **more}  # fmt: skip
    _write(directory, table, rows, cols, line)
    return {table: len(rows)}


# ------------------------------------------------------------- H-17 (D-1127): the NHI files as NHIA publishes them
# The columns NHIA's CSVs carry (data.gov.tw 23715 and 174450, "主要欄位說明", read 2026-11-17), those the loader needs
# (as ``tb_common.refdata_tw`` requires them) and the table each loader writes (TERM-2's, plus ``kind`` after the
# class B review: 單方 or 複方, from the optional 單複方 column).
NHI_DRUG_REQUIRED = ("藥品代號", "藥品中文名稱", "有效起日", "有效迄日", "ATC代碼")
NHI_DRUG_OPTIONAL = ("藥品英文名稱", "成分", "單複方")
NHI_DRUG_TABLE = ("nhi_code", "name", "name_zh", "ingredient", "atc", "valid_to", "kind")
NHI_SERVICE_REQUIRED = ("診療項目代碼", "健保支付點數", "生效起日", "生效迄日", "中文項目名稱")
NHI_SERVICE_OPTIONAL = ("英文項目名稱",)
NHI_SERVICE_TABLE = ("code", "display", "display_en", "valid_to")
# NHI open data that may ship in the image (D-1028 point 3), built by ``tools.terminology_install nhi-build`` into
# ``SHIPPED_DIR`` with its own manifest. A table loaded at install is read in its place (as ICD-10-CM's blocks are).
SHIPPED_DIR = Path(__file__).resolve().parent / "shipped"
NHI_PUBLISHER = "衛生福利部中央健康保險署"
NHI_TITLES = {NHI_DRUGS: "健保用藥品項查詢項目檔", NHI_SERVICES: "醫療服務給付項目及支付標準"}
SHIPPABLE: dict[str, str] = {NHI_DRUGS: NHI_DRUG_ATTRIBUTION, NHI_SERVICES: NHI_SERVICE_ATTRIBUTION}
# the only files the shipped folder may hold (review: a broader folder would let any file pass as cleared)
SHIPPED_FILES = frozenset({MANIFEST, *(f"{t}.parquet" for t in SHIPPABLE)})


def header_key(text: str) -> str:
    """A column header as compared: NFKC (full-width ``ＡＴＣ代碼`` is ``ATC代碼``), no BOM, quotes or white space,
    Latin letters in upper case (``ATC 代碼``, `` atc代碼`` are ``ATC代碼``)."""
    import unicodedata

    t = unicodedata.normalize("NFKC", text or "").replace("﻿", "")
    return re.sub(r"[\s\"']+", "", t).upper()


def nhi_csv(data: bytes, what: str, required: tuple[str, ...], optional: tuple[str, ...],
            columns: dict[str, str] | None = None) -> list[tuple[int, int, dict[str, str]]]:  # fmt: skip
    """NHIA's CSV as ``(row number, line number, {column: value})``: UTF-8 (BOM or not) or Big5, its header compared
    by :func:`header_key`; ``columns`` names the header the publisher now uses for one of ours (``{"ATC代碼": "ATC
    CODE"}``). A missing column, a header twice, two of our columns on one header, or a row whose field count differs
    from the header's refuses the whole file, naming the row (never half-read)."""
    import csv
    import io

    text = _text(data, what).lstrip("﻿")
    reader = csv.reader(io.StringIO(text, newline=""))
    header: list[str] = []
    for rec in reader:
        if any(f.strip() for f in rec):
            header = rec
            break
    if not header:
        raise ValueError(f"{what}: empty, no header")
    for col in columns or {}:
        if col not in (*required, *optional):
            raise ValueError(f"{what}: --column {col}: not a column this loader reads ({', '.join(required)})")
    keys = [header_key(h) for h in header]
    where: dict[str, int] = {}
    for col in (*required, *optional):
        wanted = header_key((columns or {}).get(col) or col)
        hits = [i for i, k in enumerate(keys) if k == wanted]
        if len(hits) > 1:
            raise ValueError(f"{what}: the header has column {col} {len(hits)} times")
        if hits:
            other = next((c for c, i in where.items() if i == hits[0]), "")
            if other:  # class B review: two of ours on one published column (a --column that repeats or swaps)
                raise ValueError(f"{what}: {other} and {col} both read the header {header[hits[0]].strip()}")
            where[col] = hits[0]
        elif col in required:
            raise ValueError(f"{what}: no column {col} (the header has: {', '.join(h.strip() for h in header)}); if "
                             f"the publisher renamed it, give --column {col}=<its header>")  # fmt: skip
    out = []
    n = 1
    for rec in reader:
        n += 1
        if not any(f.strip() for f in rec):
            continue
        if len(rec) != len(header):
            raise ValueError(f"{what}, row {n} (line {reader.line_num}): {len(rec)} fields, the header has "
                             f"{len(header)}")  # fmt: skip
        out.append((n, reader.line_num, {c: rec[i].strip() for c, i in where.items()}))
    if not out:
        raise ValueError(f"{what}: no rows under the header")
    return out


def _nhi_date(value: str, what: str, n: int, line: int, col: str) -> str:
    """An NHIA date as ISO: 民國 ``YYYMMDD`` (`` 960901``, ``1030630``) or ``YYY.MM.DD`` as
    ``tb_common.refdata_tw.roc`` reads it, ``YYYYMMDD``, or ISO; empty stays empty. Anything else refuses the file,
    and so does a year before 1911 or an 8-digit value with a leading zero (a zero-padded 民國 date, ``01151231``,
    would otherwise read as the year 115: class B review)."""
    from tb_common.refdata_tw import roc

    v = (value or "").strip()
    if not v:
        return ""
    iso = f"{v[:4]}-{v[4:6]}-{v[6:]}" if re.fullmatch(r"[1-9]\d{7}", v) else roc(v)
    try:
        ok = datetime.strptime(iso, "%Y-%m-%d").year >= 1911 and not re.fullmatch(r"0\d{7}", v)
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"{what}, row {n} (line {line}): {col} {value!r} is not a date")
    return iso


def _newest(rows: list[tuple[str, str, int, int, dict[str, str]]], what: str, same: tuple[str, ...],
            cols: tuple[str, str]) -> list[dict[str, str]]:  # fmt: skip
    """One row per code: the one with the latest start (a later row wins a tie), as ``tb_common.refdata_tw`` keeps.
    Class B review: two rows of one code with one start that differ in ``same`` (names, ATC, end) refuse the file,
    naming both rows, as does a period that ends before it starts; a repeated identical row is one row."""
    best: dict[str, tuple[str, dict[str, str]]] = {}
    seen: dict[tuple[str, str], tuple[int, dict[str, str]]] = {}
    for code, start, n, line, r in rows:
        if start and r["valid_to"] and r["valid_to"] < start:
            raise ValueError(f"{what}, row {n} (line {line}): {cols[1]} {r['valid_to']} is before {cols[0]} {start}")
        had = seen.setdefault((code, start), (n, r))
        if had[1] is not r and any(had[1].get(k) != r.get(k) for k in same):
            raise ValueError(
                f"{what}, rows {had[0]} and {n}: code {code} has two periods with the same start "
                f"{start or '(none)'} that differ ({', '.join(k for k in same if had[1].get(k) != r.get(k))})"
            )
        if code not in best or start >= best[code][0]:
            best[code] = (start, r)
    return [best[c][1] for c in sorted(best)]


def nhi_drug_rows(data: bytes, what: str = "the NHI drug list", columns: dict[str, str] | None = None
                  ) -> list[dict[str, str]]:  # fmt: skip
    """The NHI drug list's rows as ``nhi_drug_list`` holds them. A 藥品代號 that is not a 10-character NHI drug code,
    or a date that is not one, refuses the file with its row number."""
    import unicodedata

    shape = SITE_CODE_SHAPES["nhi_drug"]
    got = []
    for n, line, r in nhi_csv(data, what, NHI_DRUG_REQUIRED, NHI_DRUG_OPTIONAL, columns):
        code = unicodedata.normalize("NFKC", r["藥品代號"]).strip().upper()
        if not shape.match(code):
            raise ValueError(f"{what}, row {n} (line {line}): 藥品代號 {r['藥品代號']!r} is not a 10-character NHI "
                             "drug code")  # fmt: skip
        start = _nhi_date(r["有效起日"], what, n, line, "有效起日")
        end = _nhi_date(r["有效迄日"], what, n, line, "有效迄日")
        atc = r["ATC代碼"].strip().upper()
        got.append((code, start, n, line, {"nhi_code": code, "name": r.get("藥品英文名稱", ""),
                                           "name_zh": r["藥品中文名稱"], "ingredient": r.get("成分", ""),
                                           "atc": atc if _ATC.match(atc) else "", "valid_to": end,
                                           "kind": r.get("單複方", "")}))  # fmt: skip
    return _newest(got, what, ("name", "name_zh", "atc", "valid_to"), ("有效起日", "有效迄日"))


def nhi_service_rows(data: bytes, what: str = "the NHI service list", columns: dict[str, str] | None = None
                     ) -> list[dict[str, str]]:  # fmt: skip
    """The NHI service and order codes as ``nhi_service_list`` holds them. A 診療項目代碼 not shaped as an NHI order
    code, or a date that is not one, refuses the file with its row number."""
    import unicodedata

    shape = SITE_CODE_SHAPES["nhi_order"]
    got = []
    for n, line, r in nhi_csv(data, what, NHI_SERVICE_REQUIRED, NHI_SERVICE_OPTIONAL, columns):
        code = unicodedata.normalize("NFKC", r["診療項目代碼"]).strip().upper()
        if not shape.match(code):
            raise ValueError(f"{what}, row {n} (line {line}): 診療項目代碼 {r['診療項目代碼']!r} is not an NHI "
                             "service or order code")  # fmt: skip
        start = _nhi_date(r["生效起日"], what, n, line, "生效起日")
        end = _nhi_date(r["生效迄日"], what, n, line, "生效迄日")
        got.append((code, start, n, line, {"code": code, "display": r["中文項目名稱"],
                                           "display_en": r.get("英文項目名稱", ""), "valid_to": end}))  # fmt: skip
    return _newest(got, what, ("display", "display_en", "valid_to"), ("生效起日", "生效迄日"))


def ogdl_statement(table: str, version: str) -> str:
    """The OGDL 1.0 attribution (its annex 顯名聲明): the provider, the data set and its version, the release under the
    licence, and the link to the licence's full text."""
    return (f"{NHI_PUBLISHER} {NHI_TITLES[table]} {version}。此開放資料依政府資料開放授權條款 (Open Government Data "
            "License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款："
            "https://data.gov.tw/license")  # fmt: skip


def build_shipped(table: str, path: Path, version: str, fetched_on: str, sha256: str, directory: Path | None = None,
                  columns: dict[str, str] | None = None) -> dict[str, int]:  # fmt: skip
    """H-17 (D-1127): the NHI open data as it ships (D-1028 point 3). The publisher's file, fetched by the integrator,
    is read once; its sha256 must be ``sha256`` (the one recorded at the fetch), and the same bytes are parsed as at
    install and written into the shipped folder with their manifest line: the source and its whole sha256, the
    version, the day it was fetched (no clock: a rebuild of the same file writes the same bytes), the licence and both
    attribution texts. A folder that holds anything but the shipped files (a live install folder) is refused."""
    if table not in SHIPPABLE:
        raise ValueError(f"{table}: only {', '.join(SHIPPABLE)} ship (D-1028 point 3)")
    if not _is_day(fetched_on):
        raise ValueError(f"--fetched-on is the day the file was fetched, YYYY-MM-DD, not {fetched_on!r}")
    if not version.strip():
        raise ValueError("--version is the publisher's version of the file (the data set's update time)")
    where = directory or SHIPPED_DIR
    if where.resolve() == installed_dir().resolve():
        raise ValueError(f"{where} is the box's install folder ({DIR_ENV}): the shipped tables are built elsewhere")
    held = sorted(p.name for p in where.iterdir()) if where.is_dir() else []
    others = [n for n in held if n not in SHIPPED_FILES and not n.startswith(".")]
    if others:
        raise ValueError(f"{where} holds {', '.join(others)}: not a shipped folder, nothing is written")
    data = path.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", (sha256 or "").lower()) or got != sha256.lower():
        raise ValueError(f"{path.name}: its sha256 is {got}, not the {sha256!r} recorded at the fetch")
    when = datetime.fromisoformat(f"{fetched_on}T00:00:00+00:00")
    out = _install_nhi(table, data, path.name, where, version, when, columns, source_sha256=got,
                       fetched_on=fetched_on, shipped="D-1028 point 3",
                       ogdl_statement=ogdl_statement(table, version))  # fmt: skip
    # the folder held only shipped files (checked above): no other loader holds this lock, and it is not committed
    (where / ".manifest.lock").unlink(missing_ok=True)
    return out


def _is_day(text: str) -> bool:
    try:
        datetime.strptime(text or "", "%Y-%m-%d")
    except ValueError:
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))


def shipped_problems(directory: Path | None = None) -> list[str]:
    """What is wrong with the shipped NHI tables (none shipped: nothing): a file the folder may not hold, a table with
    no manifest line or other bytes, a line without its licence, attribution, OGDL statement, source sha256, version
    or day of fetch."""
    where = directory or SHIPPED_DIR
    if not where.is_dir():
        return []
    out = [f"{p.name}: not a file the shipped folder may hold" for p in sorted(where.iterdir())
           if p.name not in SHIPPED_FILES and not p.name.endswith(".parquet")]  # fmt: skip
    try:
        lines = manifest(where)["tables"]
    except TerminologyRefused as exc:
        return [*out, str(exc)]
    for name in sorted({p.stem for p in where.glob("*.parquet")} | set(lines)):
        if name not in SHIPPABLE:
            out.append(f"{name}: not NHI open data; only {', '.join(SHIPPABLE)} ship (D-1028 point 3)")
            continue
        try:
            rows = read_table(where, name)
        except TerminologyRefused as exc:
            out.append(str(exc))
            continue
        line = lines.get(name) or {}
        if rows is None:
            out.append(f"{name}: in the shipped manifest but its file is missing")
        if line.get("licence") != OGDL or line.get("attribution") != SHIPPABLE[name]:
            out.append(f"{name}: its manifest line lacks the OGDL licence or the provider's attribution")
        if not str(line.get("version") or "").strip():
            out.append(f"{name}: its manifest line names no version")
        elif line.get("ogdl_statement") != ogdl_statement(name, str(line.get("version"))):
            out.append(f"{name}: its manifest line lacks the OGDL statement for version {line.get('version')!r}")
        if not _is_day(str(line.get("fetched_on") or "")):
            out.append(f"{name}: its manifest line's fetched_on {line.get('fetched_on')!r} is not a day")
        if not re.fullmatch(r"[0-9a-f]{64}", str(line.get("source_sha256") or "")):
            out.append(f"{name}: its manifest line records no sha256 of the publisher's file")
    return out


def shipped_tables() -> dict[str, list[dict[str, Any]]]:
    """The shipped NHI tables that read through their manifest check (a refused one is left out: the doctor reports
    it through :func:`shipped_problems`)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name in SHIPPABLE:
        try:
            rows = read_table(SHIPPED_DIR, name)
        except TerminologyRefused:
            continue
        if rows is not None:
            out[name] = rows
    return out


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


_IMAGING_CODE = re.compile(r"^[0-9A-Z][0-9A-Z._-]{0,29}$")


def imaging_rows(text: str) -> list[dict[str, str]]:
    """The imaging list as a table: ``code``, ``display`` and the optional ``modality`` (CT, MR, XR, US...)."""
    rows = table_rows(text, "the imaging list")
    code = _col(rows, ("code", "imaging_code"), "the imaging list")
    name = _col(rows, ("display", "name"), "the imaging list")
    mod = _col(rows, ("modality",), "the imaging list", required=False)
    out, seen = [], set()
    for r in rows:
        c = r.get(code, "").upper()
        if not c or c in seen:
            continue
        if not _IMAGING_CODE.match(c):
            raise ValueError(f"the imaging list: {c!r} is not a code")
        seen.add(c)
        out.append({"code": c, "display": r.get(name, ""), "modality": r.get(mod, "") if mod else ""})
    return out


def install_imaging(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                    now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """The imaging code list from the hospital's own copy (CSV or TSV), after a named person accepted its licence
    (D-1114). A release names no list: the real one is the owner's (JJ1017)."""
    lic = licence_line(IMAGING_LIST, accepted_by, accepted_on, now)
    if not version:
        raise ValueError("imaging: give --version (the list's own version or year)")
    data, member = _source(path, (".csv", ".tsv", ".txt"), "an imaging code list")
    rows = imaging_rows(_text(data, member))
    directory.mkdir(parents=True, exist_ok=True)
    line = _line(f"imaging list ({member})", path, f"imaging {version}", lic.pop("licence"), now, **lic)
    _write(directory, IMAGING_LIST, rows, ("code", "display", "modality"), line)
    return {IMAGING_LIST: len(rows)}


# ----------------------------------------------------------------------------------------- V-18: the site's copies
# V-18 (D-1182; the owner's ruling, #639): SNOMED CT, the UMLS and the ATC/DDD index load from the hospital's own
# licensed copy, in the format its publisher ships, after a named person accepted the licence (D-1114). Nothing of
# them ships; the repository and the bundle never carry them. Each copy is verified by its own manifest (UMLS:
# MRFILES.RRF) or checksum file (SHA256SUMS beside it), else by a sha256 the person recorded (``sha256``), else only
# by its own headers; the manifest line says which ("verified").
SNOMED_CT, UMLS_CONCEPTS, UMLS_CODES = "snomed_ct", "umls_concepts", "umls_codes"
LICENSED.update({
    SNOMED_CT: "SNOMED CT (SNOMED International): the hospital's own RF2 copy under its licence; never shipped",
    UMLS_CONCEPTS: "UMLS Metathesaurus (NLM, UMLS licence and its source restrictions): the hospital's own subset",
    UMLS_CODES: "UMLS Metathesaurus (NLM, UMLS licence and its source restrictions): the hospital's own subset",
})  # fmt: skip
SNOMED_IS_A = "116680003"


class CopyRefused(ValueError):
    """A hospital's copy that is not what it says (a checksum, its own manifest, its format): the sentence is the
    loader's own, so it may be shown and recorded (never a general error's text, NEW-TRUST-6)."""


SNOMED_FSN = "900000000000003001"
SUMS = ("SHA256SUMS", "sha256sums.txt", "SHA256SUMS.txt")


def _files(path: Path) -> dict[str, bytes | Path]:
    """A release as ``{member path: bytes or file}``: a folder's files (read when asked) or a zip's members."""
    if path.is_dir():
        return {str(p.relative_to(path)): p for p in sorted(path.rglob("*")) if p.is_file()}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    raise CopyRefused(f"{path.name}: neither a folder nor a zip archive")


def _bytes(item: bytes | Path) -> bytes:
    return item if isinstance(item, bytes) else item.read_bytes()


def _copy_line(what: str, path: Path, files: dict[str, bytes | Path], version: str, licence: str,
               now: datetime | None, **more: str) -> dict[str, Any]:  # fmt: skip
    """:func:`_line` for a release that may be a folder: its sha256 is of the archive, or over its files' names and
    sha256s. Only the name and the hash are kept: the copy itself never leaves where the hospital put it."""
    if path.is_file():
        return _line(what, path, version, licence, now, **more)
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{name}\0{hashlib.sha256(_bytes(files[name])).hexdigest()}\n".encode())
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return {"source": f"{what} ({path.name}/, sha256 {h.hexdigest()[:16]})", "version": version, "licence": licence,
            "loaded_at": when, **more}  # fmt: skip


def _verify_sums(files: dict[str, bytes | Path], path: Path, sha256: str = "") -> str:
    """How the copy was verified. A ``SHA256SUMS`` beside it: every file it lists must match (a mismatch refuses the
    copy). Else the person's ``sha256`` of the archive. Else its headers only (said in the manifest line)."""
    sums = next((k for k in files if k.rsplit("/", 1)[-1] in SUMS), "")
    if sums:
        by_name = {k.rsplit("/", 1)[-1]: k for k in files}
        n = 0
        for line in _bytes(files[sums]).decode("utf-8").splitlines():
            if not line.strip():
                continue
            want, name = line.split(maxsplit=1)
            key = by_name.get(name.strip().lstrip("*").rsplit("/", 1)[-1])
            if key is None:
                raise CopyRefused(f"{path.name}: {sums} lists {name.strip()}, which the copy does not hold")
            if hashlib.sha256(_bytes(files[key])).hexdigest() != want.lower():
                raise CopyRefused(f"{path.name}: {key} does not match its sha256 in {sums}")
            n += 1
        return f"{sums}: {n} files match"
    if sha256:
        if path.is_dir():
            raise CopyRefused(f"{path.name}: a sha256 is checked against an archive, not a folder (or add SHA256SUMS)")
        if _sha(path) != sha256.strip().lower():
            raise CopyRefused(f"{path.name}: its sha256 is not the one recorded ({sha256.strip()[:16]}...)")
        return "the sha256 the person recorded"
    return "its own headers only (no SHA256SUMS and no recorded sha256)"


def _tsv(data: bytes, want: tuple[str, ...], what: str) -> list[list[str]]:
    lines = data.decode("utf-8-sig").splitlines()
    if not lines or tuple(lines[0].split("\t")[: len(want)]) != want:
        raise CopyRefused(f"{what}: not an RF2 file (its header is not {' '.join(want)})")
    return [ln.split("\t") for ln in lines[1:] if ln]


def _one(files: dict[str, bytes | Path], pattern: str, what: str, many: bool = False) -> list[str]:
    hits = sorted(k for k in files if re.search(pattern, k.rsplit("/", 1)[-1]))
    if not hits or (len(hits) > 1 and not many):
        raise CopyRefused(f"{what}: {'no' if not hits else 'more than one'} file named like {pattern}")
    return hits


def snomed_rows(
    files: dict[str, bytes | Path], what: str = "the SNOMED CT release"
) -> tuple[list[dict[str, str]], str]:
    """An RF2 Snapshot: each active concept, its fully specified name (the active FSN of its descriptions) and its
    active is-a parents. ``(rows, effective time)``."""
    (concept,) = _one(files, r"^sct2_Concept_Snapshot_.*\.txt$", what)
    descs = _one(files, r"^sct2_Description_Snapshot.*\.txt$", what, many=True)
    (rel,) = _one(files, r"^sct2_Relationship_Snapshot_.*\.txt$", what)
    active = {r[0]: r[1] for r in _tsv(_bytes(files[concept]), ("id", "effectiveTime", "active"), what) if r[2] == "1"}
    fsn: dict[str, str] = {}
    for d in descs:
        head = ("id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term")
        for r in _tsv(_bytes(files[d]), head, what):
            if r[2] == "1" and r[6] == SNOMED_FSN and r[4] in active:
                fsn.setdefault(r[4], r[7])
    parents: dict[str, set[str]] = {}
    head = ("id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId")
    for r in _tsv(_bytes(files[rel]), head, what):
        if r[2] == "1" and r[7] == SNOMED_IS_A and r[4] in active:
            parents.setdefault(r[4], set()).add(r[5])
    stamp = re.search(r"_(\d{8})\.txt$", concept)
    rows = [{"code": c, "display": fsn.get(c, ""), "parents": " ".join(sorted(parents.get(c, ())))}
            for c in sorted(active, key=int)]  # fmt: skip
    return rows, stamp.group(1) if stamp else max(active.values(), default="")


def install_snomed(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                   sha256: str = "", now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """SNOMED CT from the hospital's own RF2 Snapshot (a folder or the release zip), after a named person accepted
    the licence (D-1114; the owner's ruling on #639). Never shipped; the copy is read, never kept beside the table."""
    lic = licence_line(SNOMED_CT, accepted_by, accepted_on, now)
    files = _files(path)
    verified = _verify_sums(files, path, sha256)
    rows, effective = snomed_rows(files)
    if not rows:
        raise CopyRefused(f"{path.name}: no active SNOMED CT concept")
    directory.mkdir(parents=True, exist_ok=True)
    line = _copy_line("SNOMED CT RF2 Snapshot", path, files, f"SNOMED CT {version or effective}", lic.pop("licence"),
                      now, verified=verified, **lic)  # fmt: skip
    _write(directory, SNOMED_CT, rows, ("code", "display", "parents"), line)
    return {SNOMED_CT: len(rows)}


def _rrf(data: bytes, cols: int, what: str) -> list[list[str]]:
    out = []
    for n, ln in enumerate(data.decode("utf-8").splitlines(), 1):
        if not ln:
            continue
        f = ln.split("|")
        if len(f) < cols:
            raise CopyRefused(f"{what}: line {n} has {len(f)} fields, not {cols}")
        out.append(f)
    return out


def _verify_mrfiles(files: dict[str, bytes | Path], what: str) -> str:
    """MetamorphoSys's own manifest: each file MRFILES.RRF names has its rows and bytes."""
    by_name = {k.rsplit("/", 1)[-1]: k for k in files}
    key = by_name.get("MRFILES.RRF")
    if key is None:
        return ""
    n = 0
    for f in _rrf(_bytes(files[key]), 6, what):
        name, rows, size = f[0].rsplit("/", 1)[-1], f[4], f[5]
        if name not in ("MRCONSO.RRF", "MRREL.RRF") or name not in by_name:
            continue
        data = _bytes(files[by_name[name]])
        if str(len(data)) != size or str(data.count(b"\n")) != rows:
            raise CopyRefused(f"{what}: {name} does not match MRFILES.RRF ({rows} rows, {size} bytes)")
        n += 1
    return f"MRFILES.RRF: {n} files match" if n else ""


Rows = list[dict[str, str]]


def umls_rows(files: dict[str, bytes | Path], what: str = "the UMLS subset") -> tuple[Rows, Rows, str]:
    """A MetamorphoSys RRF subset: each concept (CUI) with its preferred English name, its parents (MRREL ``PAR``)
    and the sources it holds; and each source code with its CUI. ``(concepts, codes, release)``."""
    by_name = {k.rsplit("/", 1)[-1]: k for k in files}
    if "MRCONSO.RRF" not in by_name:
        raise CopyRefused(f"{what}: no MRCONSO.RRF")
    names: dict[str, tuple[int, str]] = {}
    sabs: dict[str, set[str]] = {}
    codes: dict[tuple[str, str, str], str] = {}
    for f in _rrf(_bytes(files[by_name["MRCONSO.RRF"]]), 18, what):
        cui, lat, ts, stt, ispref, sab, code, text, suppress = f[0], f[1], f[2], f[4], f[6], f[11], f[13], f[14], f[16]
        if suppress in ("O", "E", "Y"):
            continue
        rank = (lat == "ENG") * 8 + (ts == "P") * 4 + (stt == "PF") * 2 + (ispref == "Y")
        if cui not in names or rank > names[cui][0]:
            names[cui] = (rank, text)
        sabs.setdefault(cui, set()).add(sab)
        codes.setdefault((sab, code, cui), text)
    parents: dict[str, set[str]] = {}
    if "MRREL.RRF" in by_name:
        for f in _rrf(_bytes(files[by_name["MRREL.RRF"]]), 16, what):
            if f[3] == "PAR" and f[0] in names and f[4] in names:
                parents.setdefault(f[0], set()).add(f[4])
    release = ""
    if "release.dat" in by_name:
        m = re.search(r"umls\.release\.name=(\S+)", _bytes(files[by_name["release.dat"]]).decode("utf-8", "replace"))
        release = m.group(1) if m else ""
    concepts = [{"code": c, "display": names[c][1], "parents": " ".join(sorted(parents.get(c, ()))),
                 "sources": " ".join(sorted(sabs[c]))} for c in sorted(names)]  # fmt: skip
    rows = [{"sab": s, "code": k, "cui": c, "display": t} for (s, k, c), t in sorted(codes.items())]
    return concepts, rows, release


def install_umls(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                 sha256: str = "", now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """The UMLS from the hospital's own MetamorphoSys RRF subset (MRCONSO, MRREL; a folder or zip), after a named
    person accepted the UMLS licence (D-1114). Verified by its MRFILES.RRF, else as :func:`_verify_sums`."""
    lic = licence_line(UMLS_CONCEPTS, accepted_by, accepted_on, now)
    files = _files(path)
    verified = _verify_mrfiles(files, "the UMLS subset") or _verify_sums(files, path, sha256)
    concepts, codes, release = umls_rows(files)
    if not concepts:
        raise CopyRefused(f"{path.name}: no concept in MRCONSO.RRF")
    if not (version or release):
        raise CopyRefused("umls: no release.dat in the subset: give --version (the UMLS release, e.g. 2025AB)")
    directory.mkdir(parents=True, exist_ok=True)
    label = f"UMLS {version or release}"
    for table, rows, cols in ((UMLS_CONCEPTS, concepts, ("code", "display", "parents", "sources")),
                              (UMLS_CODES, codes, ("sab", "code", "cui", "display"))):  # fmt: skip
        more = dict(lic)
        line = _copy_line("UMLS Metathesaurus subset (RRF)", path, files, label, more.pop("licence"), now,
                          verified=verified, **more)  # fmt: skip
        _write(directory, table, rows, cols, line)
    return {UMLS_CONCEPTS: len(concepts), UMLS_CODES: len(codes)}


def atc_xlsx_text(data: bytes) -> str:
    """The WHOCC's ATC/DDD index as an Excel workbook (its first sheet), as the CSV text :func:`atc_rows` reads."""
    import csv
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = io.StringIO()
    w = csv.writer(out)
    for row in wb.worksheets[0].iter_rows(values_only=True):
        if any(v not in (None, "") for v in row):
            w.writerow(["" if v is None else str(v) for v in row])
    return out.getvalue()


def install_atc_index(path: Path, directory: Path, accepted_by: str, accepted_on: str = "", version: str = "",
                      sha256: str = "", now: datetime | None = None) -> dict[str, int]:  # fmt: skip
    """The ATC/DDD index from the hospital's own copy as the WHOCC sells it: an Excel workbook, or a CSV or TSV
    (:func:`install_atc`), after a named person accepted the WHOCC's terms (D-1114)."""
    if not (path.suffix.lower() == ".xlsx" or (path.is_dir() and any(path.glob("*.xlsx")))):
        src = next(iter(sorted(path.glob("*.[ct]sv"))), path) if path.is_dir() else path
        return install_atc(src, directory, accepted_by, accepted_on, version, now)
    lic = licence_line(ATC_INDEX, accepted_by, accepted_on, now)
    if not version:
        raise CopyRefused("atc: give --version (the ATC index's year, e.g. 2026)")
    src = path if path.is_file() else sorted(path.glob("*.xlsx"))[0]
    verified = _verify_sums(_files(path), path, sha256) if path.is_dir() else _verify_sums({}, src, sha256)
    rows = atc_rows(atc_xlsx_text(src.read_bytes()))
    directory.mkdir(parents=True, exist_ok=True)
    line = _line(
        f"ATC/DDD index ({src.name})", src, f"ATC {version}", lic.pop("licence"), now, verified=verified, **lic
    )
    _write(directory, ATC_INDEX, rows, ("code", "display"), line)
    return {ATC_INDEX: len(rows)}


# The folder the hospital points to (V-18; README of docs/handover/terminology-folder.md): one subfolder per system,
# and acceptance.json, the named person who accepted the licences (written by the install question, D-1114)
ACCEPTANCE = "acceptance.json"
FOLDER_SYSTEMS: tuple[tuple[str, str, str], ...] = (
    # (subfolder, label, table it loads)
    ("snomed", "SNOMED CT", SNOMED_CT),
    ("umls", "UMLS", UMLS_CONCEPTS),
    ("atc", "ATC", ATC_INDEX),
    ("loinc", "LOINC", LOINC_TABLE),
    ("icd10-who", "WHO ICD-10", ICD10_WHO),
)


def _version_file(folder: Path) -> str:
    v = folder / "VERSION"
    return v.read_text("utf-8").strip() if v.is_file() else ""


def _sha_file(folder: Path) -> str:
    v = folder / "SHA256"
    return v.read_text("utf-8").split()[0] if v.is_file() and v.read_text("utf-8").strip() else ""


def _release(folder: Path) -> Path:
    """The release in a system's subfolder: its one archive (zip), else the folder itself (unpacked files)."""
    zips = sorted(folder.glob("*.zip"))
    return zips[0] if len(zips) == 1 else folder


def install_folder(folder: Path, directory: Path, accepted_by: str = "", accepted_on: str = "",
                   now: datetime | None = None) -> dict[str, tuple[str, str]]:  # fmt: skip
    """Each system the hospital's folder holds, loaded from its subfolder (``FOLDER_SYSTEMS``). Never a stop: each
    system says ``("loaded", what)``, ``("missing", why)`` or ``("refused", why)``. The person who accepted the
    licences is ``accepted_by``, else the folder's ``acceptance.json``; with neither, nothing licensed is loaded."""
    if not accepted_by and (folder / ACCEPTANCE).is_file():
        acc = json.loads((folder / ACCEPTANCE).read_text("utf-8"))
        accepted_by, accepted_on = str(acc.get("accepted_by") or ""), accepted_on or str(acc.get("accepted_on") or "")
    loaders = {"snomed": install_snomed, "umls": install_umls, "atc": install_atc_index}
    out: dict[str, tuple[str, str]] = {}
    for sub, label, _table in FOLDER_SYSTEMS:
        where = folder / sub
        if not where.is_dir() or not any(where.iterdir()):
            out[label] = ("missing", f"no {sub}/ in the hospital's folder")
            continue
        if not accepted_by:
            out[label] = ("missing", "nobody named accepted its licence (acceptance.json or --accepted-by, D-1114)")
            continue
        src, version, sha = _release(where), _version_file(where), _sha_file(where)
        try:
            if sub in loaders:
                got = loaders[sub](src, directory, accepted_by, accepted_on, version, sha, now)
            elif sub == "loinc":
                got = install_loinc(src if src.is_file() else next(iter(sorted(where.glob("*.csv"))), src), directory,
                                    accepted_by, accepted_on, version, now)  # fmt: skip
            else:
                got = install_icd10_who(src if src.is_file() else next(iter(sorted(where.glob("*.*ml"))), src),
                                        directory, accepted_by, accepted_on, version, now)  # fmt: skip
        except CopyRefused as exc:  # the loader's own sentence
            out[label] = ("refused", str(exc)[:300])
            continue
        except (ValueError, OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:  # its type, never its text
            cmd = {"icd10-who": "icd10who"}.get(sub, sub)
            out[label] = ("refused", f"{type(exc).__name__}: deploy/terminology.sh {cmd} /stage/{sub} says why")
            continue
        out[label] = ("loaded", ", ".join(f"{t} {n} rows" for t, n in got.items()))
    return out


# V-18 (D-1182): an update's terminology payload can be rolled back. Before it loads, the volume's tables that were
# not built from a licensed copy are kept aside with their manifest lines (a licensed table never leaves the volume,
# and an update never carries one); a rollback puts them back and takes away what the update added
SAVED = "saved.json"


def save_tables(directory: Path, dest: Path) -> list[str]:
    """Copy each table not built from a licensed copy, with its manifest line, into ``dest``; record every table name
    the volume had. Returns the tables kept."""
    import fcntl

    dest.mkdir(parents=True, exist_ok=True)
    kept: dict[str, Any] = {}
    with (directory / ".manifest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        tables = manifest(directory).get("tables") or {}
        for name, line in sorted(tables.items()):
            if str((line or {}).get("licence_accepted_by") or "").strip() or not _plain_name(name):
                continue
            src = directory / f"{name}.parquet"
            if src.is_file():
                shutil.copy2(src, dest / src.name)
                kept[name] = line
    (dest / SAVED).write_text(json.dumps({"tables": kept, "had": sorted(tables)}, indent=1, sort_keys=True) + "\n",
                              encoding="utf-8")  # fmt: skip
    return sorted(kept)


def restore_tables(directory: Path, saved: Path) -> list[str]:
    """Put back what :func:`save_tables` kept, and take away each table the volume did not have then that is not
    built from a licensed copy (an update's new system). A licensed table is never touched. Returns what changed."""
    import fcntl

    record = json.loads((saved / SAVED).read_text("utf-8"))
    kept, had = record.get("tables") or {}, set(record.get("had") or [])
    changed: list[str] = []
    with (directory / ".manifest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = manifest(directory)
        for name, line in sorted(kept.items()):
            src = saved / f"{name}.parquet"
            if not _plain_name(name) or not src.is_file() or _sha(src) != line.get("sha256"):
                raise ValueError(f"{saved}: {name} is not the table it kept; nothing was restored")
        for name, line in sorted(kept.items()):
            tmp = directory / f"{name}.parquet.tmp"
            shutil.copy2(saved / f"{name}.parquet", tmp)
            tmp.replace(directory / f"{name}.parquet")
            data["tables"][name] = line
            changed.append(name)
        for name in sorted(set(data["tables"]) - had):
            line = data["tables"][name] or {}
            if str(line.get("licence_accepted_by") or "").strip() or not _plain_name(name):
                continue
            data["tables"].pop(name)
            (directory / f"{name}.parquet").unlink(missing_ok=True)
            changed.append(name)
        mtmp = directory / f".{MANIFEST}.tmp"
        with mtmp.open("w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(mtmp, directory / MANIFEST)
    return changed
