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
loader). Country modules add their items (``tb_common.refdata_tw``: the Taiwan maps and synonyms;
``tb_common.refdata_jp``: the Japan maps, CTCAE v5.0 and synonyms, D-173 to D-175); the box itself never downloads
anything: it reads the pack from the signed update bundle (offline media). An item's ``licence_reader`` reads its
licence at the source when the vendor fetches it (D-173).

:func:`verify` checks every file's size, sha256 and record count against the manifest. The update bundle's Ed25519
signature covers the tar, so the manifest itself is authentic when it arrives through ``apply_update``.

**Store**. :class:`RefStore` loads a pack into the schema ``refdata`` of the trial database (D-126). The box's backup
carries the ``pack`` and ``source`` rows and the hospital's own (``site-fetch``) rows; the vendor pack's rows are left
out and the restore loads the kept pack file again (D-187, ``tools/trialbox/backup.py``). A pack replaces the rows
of its own sources in one transaction; parts a hospital loads itself (``distribution: site-fetch``, e.g. UMIN-CTR,
whose terms forbid redistribution) live beside the vendor's pack and a vendor update does not touch them.
:meth:`RefStore.ctgov_search` answers what ``TB_CTGOV_MODE=live`` answers: by NCT id, by condition, by status and by
country (Japan or Taiwan sites); it returns the full API v2 record, which ``criteria_compiler.ctgov.to_study`` turns
into the eligibility text the criteria are drafted from.

    python -m tb_common.refdata verify PACK            # a directory or a .tar
    python -m tb_common.refdata load PACK [--by NAME]  # into TB_DB_URL's schema refdata
    python -m tb_common.refdata status
    python -m tb_common.refdata notice PACK            # print NOTICE.md from the manifest
    python -m tb_common.refdata withdraw ID --reason R # take one source out of the box (D-317)

**Withdrawing a source** (D-317). A pack replaces only its own sources, so a source a later pack leaves out keeps its
rows. A pack's manifest may list ``withdrawn: [{"id", "reason"}]``: loading it deletes those sources' rows (a vendor
pack never deletes the hospital's own site-fetch rows) and records each withdrawal in the table ``withdrawn``;
``withdraw`` does the same by hand. The status and NOTICE say what was withdrawn, when and why.

**Fetching** (D-317). Only ``tools/refdata_fetch.py fetch`` and the items' licence readers reach the network, all
through :func:`http_client`; a test replays a :class:`Cassette` (recorded answers, ``tests/fixtures/refdata/
cassettes``) in its place, so every item's fetch is tested with no network.
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
DDL_V3 = """
CREATE TABLE IF NOT EXISTS withdrawn (source_id TEXT NOT NULL, name TEXT NOT NULL, pack_id TEXT NOT NULL,
  reason TEXT NOT NULL, records BIGINT NOT NULL, withdrawn_at TEXT NOT NULL, withdrawn_by TEXT NOT NULL,
  PRIMARY KEY (source_id, withdrawn_at))
"""
MIGRATIONS = (DDL, DDL_V2, DDL_V3)  # D-317: version 3, the record of withdrawn sources
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
    URL); ``version`` is a fixed version when the source states one in the file (``version_of`` reads it from the
    file). ``licence_reader`` (D-173) is the item's own licence check, run at fetch time only (``tools/refdata_fetch.py
    fetch``; the generic fetch knows no portal, each country module brings its reader): it returns
    :class:`LicenceRead` evidence, or None when the source did not answer. The check fails closed: fetch stops when
    the source does not answer, the licence no longer reads as expected, or the file fetched is not shown to be a
    download of the licensed record (listed by it, or else pinned by ``sha256``); an item with a ``meta_url`` and no
    reader is refused, and a vendor build refuses an item with a reader whose ``fetch.json`` holds no check."""

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
    version: str = ""
    version_of: Callable[[Path], str] | None = None
    sha256: str = ""  # the expected sha256 of a version-pinned URL: fetch and build refuse another file
    licence_reader: LicenceReader | None = None  # D-173: reads the licence at the source when fetching


@dataclass(frozen=True)
class LicenceRead:
    """What a licence reader found at the source (kept in ``fetch.json`` as evidence): where it read, what it read,
    what it expected, whether that matches, the source's version when the same answer gives it, and the download
    URLs the licensed record lists (empty when the source lists none: the fetched file must then be pinned by
    ``Item.sha256``)."""

    url: str
    read: str
    expected: str
    ok: bool
    version: str = ""
    downloads: tuple[str, ...] = ()

    def evidence(self) -> dict[str, Any]:
        return {"url": self.url, "read": self.read, "expected": self.expected, "ok": self.ok,
                "version": self.version, "downloads": list(self.downloads)}  # fmt: skip


LicenceReader = Callable[[Item], LicenceRead | None]


def page_licence_reader(page: str, *markers: str) -> LicenceReader:
    """A reader for a licence stated as text on a web page: the page must contain every marker (the licence's own
    words, e.g. NCI's "free of copyright"). None when the page does not answer."""

    def read(item: Item) -> LicenceRead | None:
        try:
            with http_client() as c:
                r = c.get(page)
                r.raise_for_status()
        except Exception:
            return None
        text = r.text
        found = [m for m in markers if m in text]
        return LicenceRead(page, "; ".join(found) or "(none of the expected words)", "; ".join(markers),
                           len(found) == len(markers))  # fmt: skip

    return read


# ------------------------------------------------------------------------------------------------ fetching (D-317)
HTTP_TRANSPORT: Any = None  # None: the network (the vendor's fetch); a test sets a cassette's transport


def http_client(timeout: float = 60) -> Any:
    """The one HTTP client of the vendor's fetch and the licence readers (redirects followed). The box never calls
    it: it reads the pack. A test replays a :class:`Cassette` through it (``with replay(path):``)."""
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True, transport=HTTP_TRANSPORT)


class CassetteMiss(RuntimeError):
    """A request the cassette did not record: the test would have reached the network."""


class Cassette:
    """Recorded HTTP answers, replayed in place of the network (D-317). A cassette is a JSON file::

        {"note": "...", "interactions": [{"method": "GET", "url": "...", "status": 200, "headers": {...},
                                          "body": <one of the forms below>, "repeat": false}, ...]}

    Body forms: ``{"text": "..."}``, ``{"json": {...}}``, ``{"file": "<path beside the cassette>"}``,
    ``{"xlsx_from_csv": "<csv beside the cassette>"}`` (a one-sheet workbook, built at replay time so no binary is
    committed), ``{"zip": {"<member>": "<file>"}}`` and ``{"tgz": {"<member>": "<file>"}}``. ``"cut_at": n`` sends
    only the first ``n`` bytes while the ``content-length`` header still names the whole body (a cut-off
    transfer). Each interaction answers once, in order, unless ``repeat`` is true; a request not recorded raises
    :class:`CassetteMiss` (kept in ``misses``) and never reaches the network."""

    def __init__(self, path: Path) -> None:
        self.path = path
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.interactions: list[dict[str, Any]] = list(doc["interactions"])
        self.used: list[int] = []
        self.misses: list[str] = []
        self._built: dict[int, bytes] = {}

    def body(self, spec: dict[str, Any]) -> bytes:
        base = self.path.parent
        if "text" in spec:
            return str(spec["text"]).encode("utf-8")
        if "json" in spec:
            return json.dumps(spec["json"], ensure_ascii=False).encode("utf-8")
        if "file" in spec:
            return (base / str(spec["file"])).read_bytes()
        if "xlsx_from_csv" in spec:
            import openpyxl

            wb = openpyxl.Workbook()
            ws = wb.worksheets[0]
            if spec.get("sheet"):
                ws.title = str(spec["sheet"])
            text = (base / spec["xlsx_from_csv"]).read_text(encoding="utf-8")
            for row in csv.reader(io.StringIO(text)):
                ws.append([c or None for c in row])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        if "zip" in spec:
            import zipfile

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for member, f in sorted(spec["zip"].items()):
                    z.writestr(member, (base / f).read_bytes())
            return buf.getvalue()
        if "tgz" in spec:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                for member, f in sorted(spec["tgz"].items()):
                    data = (base / f).read_bytes()
                    ti = tarfile.TarInfo(member)
                    ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
            return buf.getvalue()
        raise ValueError(f"{self.path.name}: unknown body form {sorted(spec)}")

    def handle(self, request: Any) -> Any:
        import httpx

        url = str(request.url)
        for i, it in enumerate(self.interactions):
            if i in self.used and not it.get("repeat"):
                continue
            if it.get("method", "GET") == request.method and it["url"] == url:
                if not it.get("repeat"):
                    self.used.append(i)
                data = self.payload_at(i)
                headers = {"content-length": str(len(data)), **(it.get("headers") or {})}
                if it.get("cut_at") is not None:
                    data = data[: int(it["cut_at"])]
                return httpx.Response(int(it.get("status", 200)), headers=headers, content=data, request=request)
        self.misses.append(f"{request.method} {url}")
        raise CassetteMiss(f"{request.method} {url} is not in the cassette {self.path.name}")

    def payload_at(self, i: int) -> bytes:
        """Interaction ``i``'s whole body, built once per cassette (a workbook or archive built at replay time has
        the same bytes on every answer, so a test can pin its sha256)."""
        if i not in self._built:
            self._built[i] = self.body(self.interactions[i].get("body") or {"text": ""})
        return self._built[i]

    def payload(self, url: str) -> bytes:
        """The whole body recorded for the first interaction with ``url``."""
        return self.payload_at(next(i for i, it in enumerate(self.interactions) if it["url"] == url))

    def unused(self) -> list[str]:
        return [it["url"] for i, it in enumerate(self.interactions) if i not in self.used and not it.get("repeat")]


@contextmanager
def replay(path: Path) -> Iterator[Cassette]:
    """Every :func:`http_client` inside the block answers from the cassette at ``path``."""
    import httpx

    global HTTP_TRANSPORT
    cas = Cassette(path)
    before = HTTP_TRANSPORT
    HTTP_TRANSPORT = httpx.MockTransport(cas.handle)
    try:
        yield cas
    finally:
        HTTP_TRANSPORT = before


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


CURATED_COLS = ("term", "lang", "canonical", "domain", "review")


def curated_synonyms(path: Path, lang: str, what: str) -> Iterator[dict[str, Any]]:
    """TrialBox's own curated synonym list (``refdata_src/*_clinical_synonyms.csv``, D-172, D-175): one surface form
    -> the name the matcher knows, per domain. A row is trusted (``curated``) unless its ``review`` column says yes
    (an abbreviation with another meaning in some specialty)."""
    for r in require_columns(csv_rows(path.read_bytes()), CURATED_COLS, what):
        if r.get("term") and r.get("canonical"):
            review = r.get("review", "").lower() in ("yes", "y", "true", "1")
            yield {"term": r["term"], "lang": r.get("lang") or lang, "canonical": r["canonical"],
                   "canonical_lang": r.get("canonical_lang") or "en", "domain": r.get("domain", ""), "system": "",
                   "code": "", "curated": not review,
                   "extra": {"note": r.get("note", ""), "review": review}}  # fmt: skip


def own_file_version(label: str, path: Path, count: int) -> str:
    """The version of a file TrialBox writes itself: its name, its size in entries and its sha256 (first 12)."""
    return f"{label}, {count} entries, sha256 {sha256_file(path)[:12]}"


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


def write_manifest(pack: Path, data_as_of: str, sources: list[dict[str, Any]], sample: bool = False,
                   withdrawn: list[dict[str, str]] | None = None) -> dict[str, Any]:  # fmt: skip
    m: dict[str, Any] = {
        "format": FORMAT,
        "pack_id": pack.name,
        "data_as_of": data_as_of,
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),  # D-317: ordered against withdrawals
        "sample": sample,
        "sources": sources,
    }
    if withdrawn:
        m["withdrawn"] = withdrawn  # D-317: sources this pack takes out of the box
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
    if m.get("withdrawn"):
        out += ["## Withdrawn by this pack", ""]
        out += [f"* `{w['id']}`: {w['reason']}" for w in m["withdrawn"]]
        out.append("")
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
    gone = set()
    for w in m.get("withdrawn") or []:
        wid, why = str(w.get("id") or "").strip(), str(w.get("reason") or "").strip()
        if not wid or not why:
            raise PackError(f"a withdrawn source needs an id and a reason: {w!r}")
        if wid in ids or wid in gone:
            raise PackError(f"source {wid} is both shipped and withdrawn, or withdrawn twice")
        gone.add(wid)
    if not ids and not gone:
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
    pairs: set[tuple[str, ...]] = set()  # D-592: the box's concept_map holds one row per source and target
    for r in recs:
        if check is not None:
            check(r, str(source.get("id")))
        if source.get("kind") == "map":
            key = tuple(str(r.get(k)) for k in ("source_system", "source_code", "target_system", "target_code"))
            if key in pairs:
                raise PackError(f"{source.get('id')}: the map names {key[1]} -> {key[3]} twice")
            pairs.add(key)
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
        self.db.migrate(list(MIGRATIONS))

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> RefStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def load(self, pack: Path, by: str = "operator", origin: str | None = None) -> LoadResult:
        """Verify, then replace the rows of the pack's sources in one transaction."""
        m = verify(pack)
        site = bool(m["sources"]) and all(s["distribution"] == "site-fetch" for s in m["sources"])
        origin = origin or ("site" if site else "vendor")  # a pack that only withdraws is the vendor's
        counts: dict[str, int] = {}
        with self.db.transaction() as tx:
            for s in m["sources"]:
                sid = s["id"]
                if self._withdrawn_after(tx, sid, str(m.get("created_at") or "")):
                    log.warning("refdata: %s skipped: withdrawn after pack %s was made", sid, m["pack_id"])
                    continue  # an older pack loaded again (a restore) never brings a withdrawn source back
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
            for w in m.get("withdrawn") or []:
                self._withdraw(tx, str(w["id"]), str(w["reason"]), by, m["pack_id"], vendor=origin == "vendor")
            tx.execute("DELETE FROM pack WHERE pack_id = ?", (m["pack_id"],))
            tx.execute(
                "INSERT INTO pack (pack_id, data_as_of, origin, sample, manifest, loaded_at, loaded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (m["pack_id"], m["data_as_of"], origin, bool(m.get("sample")), json.dumps(m, ensure_ascii=False),
                 datetime.now(UTC).isoformat(timespec="seconds"), by),
            )  # fmt: skip
            tx.execute("DELETE FROM pack WHERE pack_id NOT IN (SELECT DISTINCT pack_id FROM source)")  # replaced
        return LoadResult(m["pack_id"], m["data_as_of"], counts)

    def withdraw(self, source_id: str, reason: str, by: str = "operator") -> int:
        """Take one loaded source out of the box by hand (D-317): its rows go, the withdrawal is recorded. Returns
        the rows removed. Refused for a source that is not loaded or without a reason."""
        if not reason.strip():
            raise PackError("a withdrawal needs a reason")
        with self.db.transaction() as tx:
            n = self._withdraw(tx, source_id.strip(), reason.strip(), by, "manual", vendor=False)
            tx.execute("DELETE FROM pack WHERE pack_id NOT IN (SELECT DISTINCT pack_id FROM source)")
        if n is None:
            raise PackError(f"source {source_id!r} is not loaded")
        return n

    @staticmethod
    def _withdrawn_after(tx: Any, sid: str, created_at: str) -> bool:
        """Whether ``sid`` was withdrawn after a pack made at ``created_at``. Packs made before D-317 carry seconds
        only; a pack whose time cannot be read is not held back (it loads as before)."""
        try:
            made = datetime.fromisoformat(created_at)
        except ValueError:
            return False
        rows = tx.fetchall("SELECT withdrawn_at FROM withdrawn WHERE source_id = ?", (sid,))
        return any(datetime.fromisoformat(str(at)) > made for (at,) in rows)

    @staticmethod
    def _withdraw(tx: Any, sid: str, reason: str, by: str, pack_id: str, vendor: bool) -> int | None:
        """Delete one source's rows and record why. A vendor pack never withdraws the hospital's own (site-fetch)
        rows; a source that is not loaded is skipped (None): a pack may withdraw what a box never had."""
        row = tx.fetchone("SELECT name, distribution FROM source WHERE source_id = ?", (sid,))
        if row is None or (vendor and row[1] == "site-fetch"):
            return None
        n = int(sum(tx.execute(f"DELETE FROM {table} WHERE source_id = ?", (sid,)) for table in TABLES))
        tx.execute("DELETE FROM source WHERE source_id = ?", (sid,))
        tx.execute(
            "INSERT INTO withdrawn (source_id, name, pack_id, reason, records, withdrawn_at, withdrawn_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, str(row[0]), pack_id, reason, n, datetime.now(UTC).isoformat(timespec="microseconds"), by),
        )
        return n

    def withdrawn(self) -> list[dict[str, Any]]:
        """Every withdrawal, newest first."""
        return self.db.fetchdicts("SELECT source_id, name, pack_id, reason, records, withdrawn_at, withdrawn_by "
                                  "FROM withdrawn ORDER BY withdrawn_at DESC, source_id")  # fmt: skip

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
            "withdrawn": self.withdrawn(),
        }

    def notices(self) -> list[dict[str, Any]]:
        """Every loaded source as its manifest states it (licence, terms, attribution): the NOTICE page."""
        out = []
        live = {(str(r[0]), str(r[1])) for r in self.db.fetchall("SELECT source_id, pack_id FROM source")}
        for (m,) in self.db.fetchall("SELECT manifest FROM pack ORDER BY origin DESC, pack_id"):
            man = _json(m)
            for s in man.get("sources") or []:
                if (str(s.get("id")), str(man.get("pack_id"))) not in live:
                    continue  # replaced by a later pack, or withdrawn (D-317): its rows are not in the box

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


def map_targets_or_none(source_system: str, code: str, url: str | None = None) -> list[dict[str, Any]] | None:
    """:meth:`RefStore.map_targets` for a caller that must tell "no entry" from "could not ask" (D-593): [] when no
    database is configured (there is nothing to ask), None when one is configured and it cannot be reached or the
    question fails."""
    if not _url(url):
        return []
    st = shared(url)
    if st is None:
        return None
    try:
        return st.map_targets(source_system, code)
    except Exception:
        _drop_shared(st)
        return None


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
    w = sub.add_parser("withdraw", help="delete one loaded source's rows and record why (D-317)")
    w.add_argument("source_id")
    w.add_argument("--reason", required=True)
    w.add_argument("--by", default="operator")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "withdraw":
            with RefStore() as store:
                n = store.withdraw(a.source_id, a.reason, a.by)
            print(f"withdrew {a.source_id}: {n} rows removed")
            return 0
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
