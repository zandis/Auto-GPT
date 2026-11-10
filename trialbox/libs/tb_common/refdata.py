"""The offline reference data pack (TB-PLAN-04, D-140): public registry and terminology data the box reads with no
outbound access.

**Format** (``trialbox-refdata/1``). A pack is a directory ``trialbox-refdata-<YYYYMMDD>/`` (shipped as one ``.tar``
inside the signed update bundle, payload kind ``refdata``)::

    manifest.json        format, pack_id, data_as_of, created_at, sample, and one entry per source:
                         id, name, kind (ctgov | trial | term | map | synonym), url, downloaded_at,
                         download_sha256, version, records, licence, licence_url, terms, attribution, refresh,
                         distribution (ship | site-fetch), files [{path, sha256, bytes, records}]
    NOTICE.md            the attribution and licence text of every source, generated from the manifest
    <source>/<file>.jsonl.gz   one JSON object per line:
        ctgov:  {"nct_id", "study": <ClinicalTrials.gov API v2 study record, unchanged>}
        trial:  {"registry", "trial_id", "title", "status", "phase", "sponsor", "conditions": [], "countries": [],
                 "inclusion", "exclusion", "start", "end", "updated", "codes": [], "record": {<source row>}}
        term:   {"system", "code", "display", "extra": {}}
        map:    {"source_system", "source_code", "source_display", "target_system", "target_code", "target_display",
                 "relation" (FHIR R4 ConceptMap equivalence, see RELATIONS), "extra": {}}       (D-170)
                 an ``unmatched`` row may have an empty target_code (a source code with no target at all)
        synonym: {"term", "lang", "canonical", "canonical_lang", "domain", "system", "code", "curated", "extra": {}}
                 one surface form (zh-TW, an abbreviation) -> the name the matcher knows (D-172)

``version`` (D-170) is the source's own version or edition (an IG version, a dataset's modified date, the download
date for a daily list). Packs built before D-170 have no ``version``; it is required for the kinds map and synonym.
Each source's licence was read at the source; a source whose licence forbids redistribution is ``site-fetch``: the
vendor never ships it and the hospital loads its own download (``tools/refdata_fetch.py site-load``).

**Items** (D-170). Every source is one :class:`Item` in one registry (``tools/refdata_fetch.py`` ``SOURCES``):
where it comes from, its licence and terms, its attribution, how to read its version, and its own parser (its
loader). Country modules add their items (``tb_common.refdata_tw``: the Taiwan maps and synonyms); the box itself
never downloads anything: it reads the pack from the signed update bundle (offline media).

:func:`verify` checks every file's size, sha256 and record count against the manifest. The update bundle's Ed25519
signature covers the tar, so the manifest itself is authentic when it arrives through ``apply_update``.

**Store**. :class:`RefStore` loads a pack into the schema ``refdata`` of the trial database (D-126), so the box's
backup carries it. A pack replaces the rows of its own sources in one transaction; parts a hospital loads itself
(``distribution: site-fetch``, e.g. UMIN-CTR, whose terms forbid redistribution) live beside the vendor's pack and a
vendor update does not touch them. :meth:`RefStore.ctgov_search` answers what ``TB_CTGOV_MODE=live`` answers: by NCT
id, by condition, by status and by country (Japan or Taiwan sites); it returns the full API v2 record, which
``criteria_compiler.ctgov.to_study`` turns into the eligibility text the criteria are drafted from.

    python -m tb_common.refdata verify PACK            # a directory or a .tar
    python -m tb_common.refdata load PACK [--by NAME]  # into TB_DB_URL's schema refdata
    python -m tb_common.refdata status
    python -m tb_common.refdata notice PACK            # print NOTICE.md from the manifest
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FORMAT = "trialbox-refdata/1"
KINDS = ("ctgov", "trial", "term", "map", "synonym")
VERSIONED = ("map", "synonym")  # kinds added by D-170: their sources must state a version
# FHIR R4 ConceptMap equivalence: how the target's meaning relates to the source's
RELATIONS = ("equivalent", "equal", "wider", "subsumes", "narrower", "specializes", "inexact", "relatedto",
             "unmatched")  # fmt: skip
REQUIRED = ("id", "name", "kind", "url", "downloaded_at", "download_sha256", "records", "licence", "terms",
            "attribution", "distribution", "files")  # fmt: skip
PACK_ID = re.compile(r"^trialbox-refdata-\d{8}(-[a-z0-9-]+)?$")
SCHEMA = "refdata"
TRIAL_COLS = ("registry", "trial_id", "title", "status", "conditions", "countries", "record", "source_id")

DDL = """
CREATE TABLE IF NOT EXISTS pack (pack_id TEXT PRIMARY KEY, data_as_of TEXT NOT NULL, origin TEXT NOT NULL,
  sample BOOLEAN NOT NULL DEFAULT FALSE, manifest JSONB NOT NULL, loaded_at TEXT NOT NULL, loaded_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source (source_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, name TEXT NOT NULL,
  kind TEXT NOT NULL, distribution TEXT NOT NULL, records BIGINT NOT NULL, url TEXT NOT NULL,
  downloaded_at TEXT NOT NULL, licence TEXT NOT NULL, attribution TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ctgov_study (nct_id TEXT PRIMARY KEY, title TEXT NOT NULL, overall_status TEXT NOT NULL,
  conditions TEXT NOT NULL, countries TEXT NOT NULL, last_update TEXT NOT NULL, study JSONB NOT NULL,
  source_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ctgov_study_status ON ctgov_study (overall_status);
CREATE TABLE IF NOT EXISTS trial (registry TEXT NOT NULL, trial_id TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL, conditions TEXT NOT NULL, countries TEXT NOT NULL, record JSONB NOT NULL,
  source_id TEXT NOT NULL, PRIMARY KEY (registry, trial_id));
CREATE TABLE IF NOT EXISTS term (system TEXT NOT NULL, code TEXT NOT NULL, display TEXT NOT NULL,
  extra JSONB NOT NULL, source_id TEXT NOT NULL, PRIMARY KEY (system, code))
"""
DDL_V2 = """
ALTER TABLE source ADD COLUMN IF NOT EXISTS version TEXT NOT NULL DEFAULT '';
ALTER TABLE source ADD COLUMN IF NOT EXISTS download_sha256 TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS concept_map (source_system TEXT NOT NULL, source_code TEXT NOT NULL,
  target_system TEXT NOT NULL, target_code TEXT NOT NULL, relation TEXT NOT NULL, source_display TEXT NOT NULL,
  target_display TEXT NOT NULL, extra JSONB NOT NULL, source_id TEXT NOT NULL,
  PRIMARY KEY (source_id, source_system, source_code, target_system, target_code));
CREATE INDEX IF NOT EXISTS concept_map_source ON concept_map (source_system, source_code);
CREATE INDEX IF NOT EXISTS concept_map_target ON concept_map (target_system, target_code);
CREATE TABLE IF NOT EXISTS synonym (term_norm TEXT NOT NULL, term TEXT NOT NULL, lang TEXT NOT NULL,
  canonical TEXT NOT NULL, canonical_lang TEXT NOT NULL, domain TEXT NOT NULL, system TEXT NOT NULL,
  code TEXT NOT NULL, curated BOOLEAN NOT NULL, extra JSONB NOT NULL, source_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS synonym_term ON synonym (term_norm)
"""
TABLES = ("ctgov_study", "trial", "term", "concept_map", "synonym")
MAP_COLS = ("source_system", "source_code", "target_system", "target_code", "relation", "source_display",
            "target_display", "extra", "source_id")  # fmt: skip
SYN_COLS = ("term_norm", "term", "lang", "canonical", "canonical_lang", "domain", "system", "code", "curated",
            "extra", "source_id")  # fmt: skip


class PackError(ValueError):
    """The pack is malformed, or a file does not match the manifest."""


Parser = Callable[[Path], Iterator[dict[str, Any]]]


@dataclass(frozen=True)
class Item:
    """One reference data source in the registry (D-140, D-170): where it comes from, its licence, its terms, the
    credit it asks for, and its loader.

    ``distribution``: ship (the vendor builds it into the pack), site-fetch (the licence forbids redistribution or
    the download needs the hospital's account: the hospital loads its own copy) or not usable. ``parse`` reads the
    fetched file into the pack's records (built-in parsers of ``tools/refdata_fetch.py`` when None). ``extra_files``
    are further ``(file name, URL)`` downloads of the same item; ``derived_from`` names the item whose download this
    one reads (no second download). ``meta_url`` is the source's own dataset record (e.g. a data.gov.tw dataset API
    URL), read at fetch time by the item's ``read_meta`` for the dataset's version and its licence field; the fetch
    stops when the record cannot be read or its licence is not ``licence_id`` (each country module brings its own
    reader: the generic fetch knows no portal). ``version`` is a fixed version when the source states one in the
    file (``version_of`` reads it from the file)."""

    id: str
    name: str
    kind: str  # ctgov | trial | term | map | synonym
    distribution: str  # ship | site-fetch | not usable
    url: str
    licence: str
    licence_url: str
    terms: str
    attribution: str
    refresh: str
    size: str
    note: str = ""
    filename: str = ""
    fetch: bool = True  # False: the file comes from an account download (--file) or the hospital
    country: str = ""
    decision: str = ""
    parse: Parser | None = None
    extra_files: tuple[tuple[str, str], ...] = ()
    derived_from: str = ""
    meta_url: str = ""
    read_meta: Callable[[str], dict[str, Any]] | None = None  # meta_url -> {version, license, downloads}; {}: none
    licence_id: str = ""  # the licence field read_meta must return (the licence read at the source)
    version: str = ""
    version_of: Callable[[Path], str] | None = None
    sha256: str = ""  # the expected sha256 of a version-pinned URL: fetch and build refuse another file


def norm_name(text: str) -> str:
    """The matcher's normal form (``criteria_compiler.terminology.mapper.norm``): NFKC, trimmed, lower case."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").strip().lower())


def require_columns(rows: list[dict[str, str]], cols: Iterable[str], what: str) -> list[dict[str, str]]:
    """The rows, when there are any and they have every column; otherwise ValueError (a source that changed shape,
    or an error page, never builds into an empty or half-read item)."""
    if not rows:
        raise ValueError(f"{what}: no rows")
    missing = [c for c in cols if c not in rows[0]]
    if missing:
        raise ValueError(f"{what}: columns {', '.join(missing)} are missing (the source changed shape?)")
    return rows


def csv_rows(data: bytes) -> list[dict[str, str]]:
    """A UTF-8 CSV (BOM or not) as stripped dicts."""
    text = data.decode("utf-8-sig")
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


# ------------------------------------------------------------------------------------------------ writing a pack
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl_gz(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Deterministic gzip (no name, mtime 0), so the same rows give the same sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        for r in rows:
            gz.write(json.dumps(r, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
            n += 1
    return n


def file_entry(pack: Path, rel: str, records: int) -> dict[str, Any]:
    p = pack / rel
    return {"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size, "records": records}


def write_manifest(pack: Path, data_as_of: str, sources: list[dict[str, Any]], sample: bool = False) -> dict[str, Any]:
    m = {
        "format": FORMAT,
        "pack_id": pack.name,
        "data_as_of": data_as_of,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sample": sample,
        "sources": sources,
    }
    check_manifest(m)
    (pack / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (pack / "NOTICE.md").write_text(notice(m), encoding="utf-8")
    return m


def notice(m: dict[str, Any]) -> str:
    """The pack's attribution page: what each source is, where it came from, its licence and its terms."""
    out = [f"# {m['pack_id']}: sources, licences and attribution", "",
           f"Data as of {m['data_as_of']}." + (" SAMPLE pack for tests; not for use." if m.get("sample") else ""),
           ""]  # fmt: skip
    for s in m["sources"]:
        out += [
            f"## {s['name']} (`{s['id']}`)",
            "",
            f"* Source: {s['url']}",
            f"* Downloaded: {s['downloaded_at']}; {s['records']:,} records; sha256 of the download "
            f"`{s['download_sha256']}`" + (" (over the parts' sha256s, in order)" if _multi(s) else ""),
            *([f"* Version: {s['version']}"] if s.get("version") else []),
            *(f"  * part {p['file']}: sha256 `{p['sha256']}` ({p['url']})" for p in _multi(s)),
            f"* Licence: {s['licence']}" + (f" ({s['licence_url']})" if s.get("licence_url") else ""),
            f"* Terms: {s['terms']}",
            f"* Attribution: {s['attribution']}",
            "",
        ]
    return "\n".join(out)


def _multi(s: dict[str, Any]) -> list[dict[str, Any]]:
    """The parts of a download of several files (each with its own sha256); none for a single file, whose sha256
    is the download's."""
    parts = s.get("parts") or []
    return list(parts) if len(parts) > 1 else []


# ------------------------------------------------------------------------------------------------ reading a pack
def check_manifest(m: dict[str, Any]) -> None:
    if m.get("format") != FORMAT:
        raise PackError(f"not a {FORMAT} manifest (format {m.get('format')!r})")
    if not PACK_ID.match(str(m.get("pack_id", ""))):
        raise PackError(f"bad pack id {m.get('pack_id')!r} (trialbox-refdata-YYYYMMDD)")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(m.get("data_as_of", ""))):
        raise PackError("data_as_of must be YYYY-MM-DD")
    ids = set()
    for s in m.get("sources") or []:
        missing = [k for k in REQUIRED if s.get(k) in (None, "")]
        if missing:
            raise PackError(f"source {s.get('id')!r}: missing {', '.join(missing)}")
        if s["kind"] not in KINDS:
            raise PackError(f"source {s['id']}: kind {s['kind']!r} is not one of {', '.join(KINDS)}")
        if s["kind"] in VERSIONED and not s.get("version"):
            raise PackError(f"source {s['id']}: a {s['kind']} source must state its version")
        if s["distribution"] not in ("ship", "site-fetch"):
            raise PackError(f"source {s['id']}: distribution must be ship or site-fetch")
        if s["id"] in ids:
            raise PackError(f"source {s['id']} twice")
        ids.add(s["id"])
        if sum(int(f["records"]) for f in s["files"]) != int(s["records"]):
            raise PackError(f"source {s['id']}: the files' records do not add up to {s['records']}")
    if not ids:
        raise PackError("the pack has no source")


@contextmanager
def opened(path: Path) -> Iterator[Path]:
    """A pack directory as is, or a ``.tar`` unpacked into a temporary directory (members checked first)."""
    if path.is_dir():
        yield path
        return
    tmp = Path(tempfile.mkdtemp(prefix="tb-refdata-"))
    try:
        with tarfile.open(path, "r:*") as tf:
            for mem in tf.getmembers():
                name = Path(mem.name)
                if name.is_absolute() or ".." in name.parts or not (mem.isfile() or mem.isdir()):
                    raise PackError(f"unsafe member in {path.name}: {mem.name}")
            tf.extractall(tmp, filter="data")
        tops = [p for p in tmp.iterdir() if p.is_dir()]
        if len(tops) != 1:
            raise PackError(f"{path.name}: expected one top directory trialbox-refdata-<date>/")
        yield tops[0]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_manifest(pack: Path) -> dict[str, Any]:
    try:
        m: dict[str, Any] = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"{pack}: no readable manifest.json ({exc})") from exc
    check_manifest(m)
    if m["pack_id"] != pack.name:
        raise PackError(f"the directory {pack.name} does not match the pack id {m['pack_id']}")
    return m


def rows(pack: Path, rel: str) -> Iterator[dict[str, Any]]:
    with gzip.open(pack / rel, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def verify(pack: Path) -> dict[str, Any]:
    """Every file present, of its size and sha256, with its record count. Returns the manifest."""
    m = read_manifest(pack)
    for s in m["sources"]:
        for f in s["files"]:
            p = pack / f["path"]
            if Path(f["path"]).is_absolute() or ".." in Path(f["path"]).parts or not p.is_file():
                raise PackError(f"{s['id']}: file {f['path']} is missing")
            if p.stat().st_size != int(f["bytes"]) or sha256_file(p) != f["sha256"]:
                raise PackError(f"{s['id']}: {f['path']} does not match its sha256 (a damaged or changed pack)")
            n = sum(1 for _ in check_records(s, rows(pack, f["path"])))
            if n != int(f["records"]):
                raise PackError(f"{s['id']}: {f['path']} has {n} records, the manifest says {f['records']}")
    return m


def check_records(source: dict[str, Any], recs: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Each record checked as the box's load checks it (a relation outside RELATIONS, a synonym without its term),
    so a pack that would fail at the hospital fails at the vendor's build and verify instead."""
    check = {"map": map_row, "synonym": synonym_row}.get(str(source.get("kind")))
    for r in recs:
        if check is not None:
            check(r, str(source.get("id")))
        yield r


def pack_tar(pack: Path, out: Path) -> Path:
    """The pack directory as one deterministic tar (sorted names, no owners, mtime 0)."""
    out.parent.mkdir(parents=True, exist_ok=True)

    def norm(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        ti.mtime = 0
        return ti

    with tarfile.open(out, "w") as tf:
        for p in [pack, *sorted(pack.rglob("*"))]:
            tf.add(p, arcname=p.relative_to(pack.parent).as_posix(), recursive=False, filter=norm)
    return out


# ------------------------------------------------------------------------------------------------ the store
def _bar(values: Iterable[str]) -> str:
    """``|a|b|`` lower case: a column searched with LIKE for whole values (countries) or parts (conditions)."""
    vals = [v.strip().lower() for v in values if v and v.strip()]
    return "|" + "|".join(vals) + "|" if vals else ""


def ctgov_row(rec: dict[str, Any], source_id: str) -> tuple[str, ...]:
    study = rec["study"]
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    status = ps.get("statusModule") or {}
    locs = (ps.get("contactsLocationsModule") or {}).get("locations") or []
    nct = str(rec.get("nct_id") or ident.get("nctId") or "")
    if not nct.startswith("NCT"):
        raise PackError(f"a ClinicalTrials.gov record without an NCT id: {nct!r}")
    conds = list((ps.get("conditionsModule") or {}).get("conditions") or [])
    conds += list((ps.get("conditionsModule") or {}).get("keywords") or [])
    return (
        nct,
        str(ident.get("briefTitle") or ident.get("officialTitle") or nct),
        str(status.get("overallStatus") or "").upper(),
        _bar(conds),
        _bar(str(x.get("country") or "") for x in locs),
        str((status.get("lastUpdatePostDateStruct") or {}).get("date") or ""),
        json.dumps(study, ensure_ascii=False),
        source_id,
    )


def map_row(rec: dict[str, Any], source_id: str) -> tuple[Any, ...]:
    rel = str(rec.get("relation") or "")
    if rel not in RELATIONS:
        raise PackError(f"{source_id}: relation {rel!r} is not one of {', '.join(RELATIONS)}")
    vals = [str(rec.get(k) or "").strip() for k in ("source_system", "source_code", "target_system", "target_code")]
    if not all(vals[:3]) or not (vals[3] or rel == "unmatched"):  # an unmatched row may have no target (D-171)
        raise PackError(f"{source_id}: a map row needs source and target system and code: {rec!r}")
    return (*vals, rel, str(rec.get("source_display") or ""), str(rec.get("target_display") or ""),
            json.dumps(rec.get("extra") or {}, ensure_ascii=False), source_id)  # fmt: skip


def synonym_row(rec: dict[str, Any], source_id: str) -> tuple[Any, ...]:
    term, canonical = str(rec.get("term") or "").strip(), str(rec.get("canonical") or "").strip()
    if not term or not canonical or not rec.get("lang"):
        raise PackError(f"{source_id}: a synonym row needs term, lang and canonical: {rec!r}")
    return (norm_name(term), term, str(rec["lang"]), canonical, str(rec.get("canonical_lang") or ""),
            str(rec.get("domain") or ""), str(rec.get("system") or ""), str(rec.get("code") or ""),
            bool(rec.get("curated")), json.dumps(rec.get("extra") or {}, ensure_ascii=False), source_id)  # fmt: skip


@dataclass(frozen=True)
class LoadResult:
    pack_id: str
    data_as_of: str
    counts: dict[str, int]


class RefStore:
    """The ``refdata`` schema of the trial database."""

    def __init__(self, url: str | None = None) -> None:
        from tb_common.db import ENV, Database

        self.db = Database.connect(url or os.environ.get(ENV), SCHEMA)
        self.db.migrate([DDL, DDL_V2])

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> RefStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def load(self, pack: Path, by: str = "operator", origin: str | None = None) -> LoadResult:
        """Verify, then replace the rows of the pack's sources in one transaction."""
        m = verify(pack)
        origin = origin or ("site" if all(s["distribution"] == "site-fetch" for s in m["sources"]) else "vendor")
        counts: dict[str, int] = {}
        with self.db.transaction() as tx:
            for s in m["sources"]:
                sid = s["id"]
                for table in TABLES:
                    tx.execute(f"DELETE FROM {table} WHERE source_id = ?", (sid,))
                tx.execute("DELETE FROM source WHERE source_id = ?", (sid,))
                n = 0
                for f in s["files"]:
                    recs = rows(pack, f["path"])
                    if s["kind"] == "ctgov":
                        n += tx.copy_rows("ctgov_study", ("nct_id", "title", "overall_status", "conditions",
                                                          "countries", "last_update", "study", "source_id"),
                                          (ctgov_row(r, sid) for r in recs))  # fmt: skip
                    elif s["kind"] == "trial":
                        n += tx.copy_rows(
                            "trial",
                            TRIAL_COLS,
                            ((str(r["registry"]), str(r["trial_id"]), str(r.get("title") or ""),
                              str(r.get("status") or ""), _bar(r.get("conditions") or []),
                              _bar(r.get("countries") or []), json.dumps(r, ensure_ascii=False), sid)
                             for r in recs),
                        )  # fmt: skip
                    elif s["kind"] == "map":
                        n += tx.copy_rows("concept_map", MAP_COLS, (map_row(r, sid) for r in recs))
                    elif s["kind"] == "synonym":
                        n += tx.copy_rows("synonym", SYN_COLS, (synonym_row(r, sid) for r in recs))
                    else:
                        n += tx.copy_rows(
                            "term",
                            ("system", "code", "display", "extra", "source_id"),
                            ((str(r["system"]), str(r["code"]), str(r.get("display") or ""),
                              json.dumps(r.get("extra") or {}, ensure_ascii=False), sid) for r in recs),
                        )  # fmt: skip
                tx.execute(
                    "INSERT INTO source (source_id, pack_id, name, kind, distribution, records, url, downloaded_at, "
                    "licence, attribution, version, download_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sid, m["pack_id"], s["name"], s["kind"], s["distribution"], n, s["url"], s["downloaded_at"],
                     s["licence"], s["attribution"], str(s.get("version") or ""), s["download_sha256"]),
                )  # fmt: skip
                counts[sid] = n
            tx.execute("DELETE FROM pack WHERE pack_id = ?", (m["pack_id"],))
            tx.execute(
                "INSERT INTO pack (pack_id, data_as_of, origin, sample, manifest, loaded_at, loaded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (m["pack_id"], m["data_as_of"], origin, bool(m.get("sample")), json.dumps(m, ensure_ascii=False),
                 datetime.now(UTC).isoformat(timespec="seconds"), by),
            )  # fmt: skip
            tx.execute("DELETE FROM pack WHERE pack_id NOT IN (SELECT DISTINCT pack_id FROM source)")  # replaced
        return LoadResult(m["pack_id"], m["data_as_of"], counts)

    # -------------------------------------------------------------------- queries
    def ctgov_study(self, nct_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT study FROM ctgov_study WHERE nct_id = ?", (nct_id.strip().upper(),))
        return _json(row[0]) if row else None

    def ctgov_search(
        self,
        condition: str = "",
        locations: Iterable[str] = (),
        status: str | None = "RECRUITING",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Full API v2 records: condition (part of a condition or keyword, any case), any of the countries, the
        overall status; newest update first."""
        where, args = [], []
        if condition.strip():
            where.append("(conditions LIKE ? OR lower(title) LIKE ?)")
            like = f"%{_esc(condition.strip().lower())}%"
            args += [like, like]
        locs = [c.strip().lower() for c in locations if c.strip()]
        if locs:
            where.append("(" + " OR ".join("countries LIKE ?" for _ in locs) + ")")
            args += [f"%|{_esc(c)}|%" for c in locs]
        if status:
            where.append("overall_status = ?")
            args.append(status.upper())
        sql = "SELECT study FROM ctgov_study" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY last_update DESC, nct_id LIMIT ?"
        return [_json(r[0]) for r in self.db.fetchall(sql, (*args, int(limit)))]

    def trials(self, registry: str = "", condition: str = "", limit: int = 50) -> list[dict[str, Any]]:
        where, args = [], []
        if registry:
            where.append("registry = ?")
            args.append(registry)
        if condition.strip():
            where.append("(conditions LIKE ? OR lower(title) LIKE ?)")
            like = f"%{_esc(condition.strip().lower())}%"
            args += [like, like]
        sql = "SELECT record FROM trial" + (" WHERE " + " AND ".join(where) if where else "")
        return [_json(r[0]) for r in self.db.fetchall(sql + " ORDER BY trial_id LIMIT ?", (*args, int(limit)))]

    def term(self, system: str, code: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT display, extra FROM term WHERE system = ? AND code = ?", (system, code))
        return {"system": system, "code": code, "display": row[0], "extra": _json(row[1])} if row else None

    def map_targets(self, source_system: str, code: str) -> list[dict[str, Any]]:
        """What one code maps to (every loaded map from ``source_system``), e.g. an NHI lab code -> LOINC."""
        return self._map("source_system = ? AND source_code = ?", (source_system, code.strip()))

    def map_sources(self, target_system: str, code: str) -> list[dict[str, Any]]:
        """The reverse: which codes map to this one (e.g. the 2014 codes behind a 2023 TW ICD-10-CM code)."""
        return self._map("target_system = ? AND target_code = ?", (target_system, code.strip()))

    def _map(self, where: str, args: tuple[str, str]) -> list[dict[str, Any]]:
        rows = self.db.fetchdicts(
            "SELECT source_system, source_code, source_display, target_system, target_code, target_display, relation, "
            f"extra, source_id FROM concept_map WHERE {where} ORDER BY source_code, target_code",
            args,
        )
        return [r | {"extra": _json(r["extra"])} for r in rows]

    def synonyms(self, term: str, domain: str = "") -> list[dict[str, Any]]:
        """The dictionary entries of one surface form (matched in the matcher's normal form). An entry without a
        domain answers every domain."""
        rows = self.db.fetchdicts(
            "SELECT term, lang, canonical, canonical_lang, domain, system, code, curated, source_id FROM synonym "
            "WHERE term_norm = ? AND (domain = '' OR ? = '' OR domain = ?) ORDER BY curated DESC, source_id, canonical",
            (norm_name(term), domain, domain),
        )
        return [r | {"curated": bool(r["curated"])} for r in rows]

    def status(self) -> dict[str, Any] | None:
        """What the admin page shows: the vendor pack's date ("data as of"), every source with its records and
        licence, and the parts the hospital loaded itself. None when nothing is loaded."""
        packs = self.db.fetchdicts("SELECT pack_id, data_as_of, origin, sample, loaded_at, loaded_by FROM pack "
                                   "ORDER BY loaded_at DESC, data_as_of DESC")  # fmt: skip
        if not packs:
            return None
        srcs = self.db.fetchdicts("SELECT source_id, pack_id, name, kind, distribution, records, downloaded_at, "
                                  "licence, attribution, version, download_sha256 FROM source "
                                  "ORDER BY source_id")  # fmt: skip
        vendor = next((p for p in packs if p["origin"] == "vendor"), packs[0])
        return {
            "pack_id": vendor["pack_id"],
            "data_as_of": vendor["data_as_of"],
            "loaded_at": vendor["loaded_at"],
            "sample": bool(vendor["sample"]),
            "packs": packs,
            "sources": srcs,
        }

    def notices(self) -> list[dict[str, Any]]:
        """Every loaded source as its manifest states it (licence, terms, attribution): the NOTICE page."""
        out = []
        for (m,) in self.db.fetchall("SELECT manifest FROM pack ORDER BY origin DESC, pack_id"):
            man = _json(m)
            for s in man.get("sources") or []:
                out.append({k: s.get(k, "") for k in ("id", "name", "kind", "url", "downloaded_at", "records",
                                                      "version", "download_sha256", "licence", "licence_url", "terms",
                                                      "attribution", "distribution")}
                           | {"parts": _multi(s)}
                           | {"pack_id": man.get("pack_id", "")})  # fmt: skip
        return out


def notices_or_empty(url: str | None = None) -> list[dict[str, Any]]:
    try:
        with RefStore(url) as st:
            return st.notices()
    except Exception:
        return []


_SHARED: dict[str, RefStore] = {}  # at most one: the database the process uses
_FAILED: dict[str, float] = {}


def _url(url: str | None) -> str | None:
    from tb_common.db import ENV

    return url or os.environ.get(ENV)


def shared(url: str | None = None) -> RefStore | None:
    """One open store for lookups made often (the name matcher, site set-up suggestions); None when no database is
    configured or it cannot be reached. Another URL closes the previous store (one connection per process). Never
    touches the network beyond the trial database."""
    url = _url(url)
    if not url:
        return None
    st = _SHARED.get(url)
    if st is None:
        if time.monotonic() - _FAILED.get(url, -1e9) < 60:
            return None  # not reachable a moment ago: do not wait on it for every name
        for old in _SHARED.values():
            with suppress(Exception):
                old.close()
        _SHARED.clear()
        try:
            st = RefStore(url)
        except Exception:
            _FAILED[url] = time.monotonic()
            return None
        _SHARED[url] = st
    return st


def _drop_shared(st: RefStore) -> None:
    """A shared store whose query failed (the database restarted, the connection dropped): close it and forget it,
    so the next lookup after the 60 s pause opens a new one instead of failing for the life of the process."""
    for url, cur in list(_SHARED.items()):
        if cur is st:
            _SHARED.pop(url, None)
            _FAILED[url] = time.monotonic()
            log.warning("reference data store query failed; reconnecting later")
    with suppress(Exception):
        st.close()


def map_targets_or_empty(source_system: str, code: str, url: str | None = None) -> list[dict[str, Any]]:
    """:meth:`RefStore.map_targets`, or [] when nothing is loaded or the database is not reachable."""
    st = shared(url)
    if st is None:
        return []
    try:
        return st.map_targets(source_system, code)
    except Exception:
        _drop_shared(st)
        return []


def synonyms_or_empty(term: str, domain: str = "", url: str | None = None) -> list[dict[str, Any]]:
    st = shared(url)
    if st is None:
        return []
    try:
        return st.synonyms(term, domain)
    except Exception:
        _drop_shared(st)
        return []


def synonym_lookup(url: str | None = None) -> Callable[[str, str], list[dict[str, Any]]]:
    """The name matcher's dictionary (``Terminology(name_synonyms=...)``, D-172): the loaded synonym sources."""

    def lookup(term: str, domain: str = "") -> list[dict[str, Any]]:
        return synonyms_or_empty(term, domain, url)

    return lookup


YES_RELATIONS = ("equivalent", "equal", "wider", "subsumes")  # the target holds all of the source's meaning
NO_RELATIONS = ("equivalent", "equal", "narrower", "specializes")  # the targets together hold all of it


def in_set_via_map(
    targets: Iterable[dict[str, Any]],
    wanted: set[tuple[str, str]],
    families: Iterable[tuple[str, str]] = (),
) -> str:
    """Whether a code read through a map (e.g. a TW 2014 ICD-10-CM code from an old record) is in a code list of
    exact ``(system, code)`` pairs (a prefix family is not expanded here). Unknown never excludes:

    * ``unknown`` when the list holds no code or family of a target's system (an HL7 ICD-10-CM list against the TW
      2023 system, say): the map cannot speak about a list it does not share a system with;
    * ``yes`` only when a target that holds the whole meaning (equivalent, equal, wider, subsumes) is in the list,
      or every target of a split (narrower, specializes) is;
    * ``no`` only when every target is equivalent, equal, narrower or specializes (together they cover the source)
      and none is in the list;
    * ``unknown`` otherwise: some targets in and some out (a split), an inexact or relatedto row (candidates, not
      meanings), or no row at all. ``unmatched`` rows are dropped first.

    ``families`` are the list's ``(system, code prefix)`` groupers (``MappingResult.families``): a target under one
    is inside. A list in another code system than every target (the HL7 ICD-10-CM URI against the TW 2023 system)
    cannot say "no": the answer is then ``yes`` or ``unknown``, never ``no``."""
    rows = [t for t in targets if t.get("relation") != "unmatched"]
    if not rows:
        return "unknown"
    fams = [(sy, pre) for sy, pre in families if pre]

    def is_in(t: dict[str, Any]) -> bool:
        sy, code = t["target_system"], t["target_code"]
        return (sy, code) in wanted or any(sy == fs and code.startswith(pre) for fs, pre in fams)

    inside = [is_in(t) for t in rows]
    systems = {sy for sy, _ in wanted} | {sy for sy, _ in fams}
    if any(i and t.get("relation") in YES_RELATIONS for i, t in zip(inside, rows, strict=True)):
        return "yes"
    if all(inside) and all(t.get("relation") in NO_RELATIONS for t in rows):
        return "yes"  # a split whose every part is in the list (2014 I10 against I10 and I16.0 / .1 / .9)
    if (
        not any(inside)
        and all(t.get("relation") in NO_RELATIONS for t in rows)
        and all(t["target_system"] in systems for t in rows)
    ):
        return "no"  # only when the list speaks the targets' code system
    return "unknown"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str | bytes) else v


def status_or_none(url: str | None = None) -> dict[str, Any] | None:
    """:meth:`RefStore.status`, or None when the database is not configured or not reachable (a page never fails
    because of it)."""
    try:
        with RefStore(url) as st:
            return st.status()
    except Exception:
        return None


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tb_common.refdata", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "load", "notice"):
        p = sub.add_parser(name)
        p.add_argument("pack", type=Path)
        if name == "load":
            p.add_argument("--by", default="operator")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            st = status_or_none()
            print(json.dumps(st, ensure_ascii=False, indent=1, default=str) if st else "no reference data loaded")
            return 0
        with opened(a.pack) as pack:
            if a.cmd == "verify":
                m = verify(pack)
                print(f"OK {m['pack_id']}: data as of {m['data_as_of']}, "
                      + ", ".join(f"{s['id']} {s['records']}" for s in m["sources"]))  # fmt: skip
            elif a.cmd == "notice":
                print(notice(read_manifest(pack)))
            else:
                with RefStore() as store:
                    res = store.load(pack, by=a.by)
                print(f"loaded {res.pack_id} (data as of {res.data_as_of}): "
                      + ", ".join(f"{k} {v}" for k, v in res.counts.items()))  # fmt: skip
    except (PackError, OSError, tarfile.TarError) as exc:
        print(f"refdata: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
