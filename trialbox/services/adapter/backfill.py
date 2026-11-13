"""All-history back-fill (T-305b, D-403, CR-061 back-fill half; WS-03.7, MR-129, owner decision C-02 "all history").

The first load of a hospital is every year it has, not one night. ``run_ingest`` holds the whole night in memory
(0.33 GB per 1,000 patients, review DF §7.2), so ten years at 50,000 patients cannot run that way. The back-fill makes
the same NDJSON snapshot the nightly full load would make, byte for byte, in bounded memory:

    report = backfill(cfg, "csv", "/data/export", snapshot="2026-11-10", first_years=5)

1. **Spool** (one streaming pass over the source): every row is read, normalised, mapped and pseudonymised exactly as
   the nightly load does (static resources, deleted rows left out, rejected rows counted per table, site unit
   defaults, merged chart numbers), and written to ``<work>/spool/<bucket>/<Type>.ndjson``, where the bucket is the
   record's clinical year (``resource_year``) or ``base`` (patients, staff, sites and undated records). Patients are
   added to the pid map in batches as they are read. Only the Patient list is held in memory (one entry per patient).
2. **Years, newest first.** Each bucket (``base`` first, then the newest year down to the oldest) is sorted by
   resource id into ``<work>/runs/<bucket>/`` and gets its own Data Quality report (``dq.json``: records per type,
   missing required elements, undated orders). Sorting holds the ids and offsets of one year of one type, not the
   records. ``dq.json`` is written last: it marks the year done.
3. **Publish.** The done years are merged (a streaming k-way merge by id; the source's last row of an id wins, as in
   the nightly merge) into the snapshot's NDJSON folder, checked (a structural sample, the drop guard against the last
   good night), loaded into OMOP when the dual write is on, and handed to the lake rebuild. With ``first_years`` the
   snapshot is published once after ``base`` and the newest ``first_years`` years, so screening runs on recent years
   while older years load, and again when every year is in. Both publishes are the same snapshot id: a publish whose
   snapshot a running job holds is refused by the lake (``SnapshotHeld``) and is simply run again.

**Resumable.** A run killed at any point starts again where it stopped: the spool is kept when it finished for the same
source, mapping and snapshot (``spool/done.json``; else it is read again), a year with a ``dq.json`` is not sorted
again, and a publish is repeated whole. ``<work>/progress.json`` says where the run is.

Not done by the back-fill (the nightly runs do them): data contract row checks (``TB_DATA_CONTRACTS``), the
completeness gate against the last night's tables, the JP Core profile sample and the fhir-store load.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any
from zoneinfo import ZoneInfo

from tb_common import feedguard, refdata
from tb_common.audit_writer import open_audit
from tb_common.crypto import pid_for_mrn

from adapter.ndjson import is_deleted_flag, snapshot_dir
from adapter.pipeline import (
    COMPLETENESS,
    PASSED,
    REJECT_MAX_PCT,
    UNMAPPED_CODES,
    AdapterConfig,
    _current,
    _type_counts,
    _undated_order,
    apply_aliases,
    apply_unit_defaults,
    check_lookup_factors,
    check_site_key,
    completeness_check,
    ingest_instant,
    make_source,
    merge_base,
    refuse_future_night,
)
from adapter.sources.base import has_table
from adapter.validate.validator import Hl7Validator, StructuralValidator, missing_required

log = logging.getLogger("adapter")
BASE = "base"
SPOOL_DONE = "done.json"
DQ = "dq.json"
REPORT = "backfill.json"  # beside the published NDJSON: which years it holds (the lake reads only *.ndjson)
PID_BATCH = 5000
#: the elements that date a record, in the order they are read (the first one present gives the year)
DATE_PATHS: tuple[tuple[str, ...], ...] = (
    ("effectiveDateTime",),
    ("effectivePeriod", "start"),
    ("performedDateTime",),
    ("performedPeriod", "start"),
    ("period", "start"),
    ("onsetDateTime",),
    ("recordedDate",),
    ("authoredOn",),
    ("dispenseRequest", "validityPeriod", "start"),
    ("occurrenceDateTime",),
    ("issued",),
    ("dateTime",),
    ("date",),
    ("start",),
    ("created",),
    ("context", "period", "start"),
)
UNDATED_TYPES = frozenset({"Patient", "Practitioner", "PractitionerRole", "Organization", "Location", "Medication"})


class BackfillStop(Exception):
    """Raised by a ``on_bucket`` hook to stop the run after a year (a test's kill, an operator's pause)."""


@dataclass
class BackfillReport:
    snapshot: str
    state: str = "running"  # running | partial | published | held | failed
    years: list[str] = field(default_factory=list)  # every bucket of the source, base first, then newest first
    done: list[str] = field(default_factory=list)  # buckets sorted and checked
    published: list[list[str]] = field(default_factory=list)  # the buckets of each publish
    counts: dict[str, int] = field(default_factory=dict)  # records per type in the last publish
    rejected: dict[str, int] = field(default_factory=dict)  # source rows the mapping could not read, per table
    # D-535: rows with a value the mapping could not use, per table (the codes: unmapped_codes.json)
    unmapped: dict[str, int] = field(default_factory=dict)
    incomplete: list[str] = field(default_factory=list)  # the completeness gate's problems (the load is held)
    errors: list[str] = field(default_factory=list)
    spool_reused: bool = False
    seconds: float = 0.0
    lake: dict[str, Any] | None = None
    omop: dict[str, Any] | None = None
    # T-693 (D-457): the cap of the validation sample in force and the types it cut (None: not validated)
    validation_sample: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(r: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = r
    for k in path:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


def resource_year(r: dict[str, Any]) -> str:
    """The bucket of a resource: the year of its first dating element (``DATE_PATHS``), else ``base``."""
    if r.get("resourceType") in UNDATED_TYPES:
        return BASE
    for path in DATE_PATHS:
        v = _get(r, path)
        if isinstance(v, str) and len(v) >= 4 and v[:4].isdigit():
            return v[:4]
    return BASE


def _canon(r: dict[str, Any]) -> str:
    """One resource as ``write_snapshot`` writes it (canonical JSON, one line)."""
    return json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_json(path: Path, body: Any) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _fingerprint(cfg: AdapterConfig, source_kind: str, source_path: str, snap: str) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([source_kind, str(source_path), snap, cfg.site_id], sort_keys=True).encode())
    if cfg.mapping_path.is_file():
        h.update(cfg.mapping_path.read_bytes())
    return h.hexdigest()


class _Spool:
    """Append-only per-bucket, per-type spool files: ``<seq>\\t<canonical json>`` lines."""

    def __init__(self, root: Path, last_year: str) -> None:
        self.root = root
        self.last_year = last_year  # a later date (a booked appointment) is in the snapshot's own year
        self.files: dict[tuple[str, str], IO[str]] = {}
        self.seq = 0

    def put(self, r: dict[str, Any], bucket: str | None = None, seq: int | None = None) -> None:
        """Spool ``r`` in its year (or ``bucket``) under the next sequence number (or ``seq``: a held patient)."""
        b = bucket or resource_year(r)
        if b != BASE and b > self.last_year:
            b = self.last_year
        key = (b, str(r["resourceType"]))
        fh = self.files.get(key)
        if fh is None:
            d = self.root / b
            d.mkdir(parents=True, exist_ok=True)
            fh = self.files[key] = (d / f"{key[1]}.ndjson").open("a", encoding="utf-8")
        if seq is None:
            self.seq += 1
            seq = self.seq
        fh.write(f"{seq:012d}\t{_canon(r)}\n")

    def close(self) -> None:
        for fh in self.files.values():
            fh.close()
        self.files.clear()


def _spool(cfg: AdapterConfig, source_kind: str, source_path: str, snap: str, root: Path, key: bytes) -> dict[str, Any]:
    """Phase 1: the source read once, mapped exactly as ``run_ingest`` maps it, spooled by year. Returns the facts
    the report needs (rejects per table, rows per table)."""
    from adapter.mapping.engine import Mapper, Mapping
    from adapter.pipeline import _bulk_unit_defaults

    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    sp = _Spool(root, snap[:4])
    rejected: dict[str, int] = {}
    rows_by_table: dict[str, int] = {}
    tables: dict[str, dict[str, Any]] = {}  # D-535: per source table, what the night's completeness record holds
    unmapped_codes: dict[str, dict[str, dict[str, int]]] = {}
    pm = cfg.pidmap()
    try:
        aliases = pm.aliases()
        patients: list[tuple[int, dict[str, Any]]] = []

        def emit(r: dict[str, Any]) -> None:
            if r["resourceType"] == "Patient":  # held until the end: a merged chart number may drop one (D-370)
                sp.seq += 1
                patients.append((sp.seq, r))
                return
            if r["resourceType"] == "Observation":
                apply_unit_defaults([r], unit_defaults)
            if aliases:
                apply_aliases({r["resourceType"]: [r]}, aliases)
            sp.put(r)

        if source_kind == "fhir_bulk":
            from adapter.pipeline import pseudonymise_bulk
            from adapter.sources.fhir_bulk.source import FhirBulkSource

            unit_defaults = _bulk_unit_defaults(cfg.mapping_path)
            for r in pseudonymise_bulk(FhirBulkSource(Path(source_path)).resources(), key):
                emit(r)
        else:
            mapping = Mapping.load(cfg.mapping_path)
            unit_defaults = mapping.unit_defaults
            check_lookup_factors(mapping)  # D-527
            mapper = Mapper(
                mapping, key, cfg.site_id, ingest_instant(snap, mapping.tz),
                concept_map=lambda system, code: refdata.map_targets_or_none(system, code, cfg.db_url),  # D-593
            )  # fmt: skip
            source = make_source(source_kind, source_path, cfg.db_url, cfg.source_encoding)
            for res in mapper.static_resources():
                emit(res)
            for table, tspec in mapping.tables.items():
                src, src_name = source, tspec["source"]
                if table == "registry" and cfg.registry is not None:
                    kind, where = cfg.registry
                    if kind == "none" or not where:
                        continue
                    if kind == "csv":
                        src = make_source("csv", str(Path(where).parent), encoding=cfg.source_encoding)
                        src_name = Path(where).stem
                    else:
                        src = make_source("cgrd_sql", where)
                dcol = str(tspec.get("deleted") or "deleted")
                ident = tspec.get("identity") or {}
                pairs: list[tuple[str, str]] = []
                idents: list[tuple[str, dict[str, str]]] = []
                n_rows = 0
                n_read = 0
                bad: Counter[str] = Counter()
                for raw in src.rows(table, src_name, None, None):
                    row = mapping.normalize(table, raw)
                    n_read += 1
                    if dcol in row and is_deleted_flag(row[dcol]):
                        continue  # a deleted row is a tombstone on a delta night; in a first load it is no record
                    n_rows += 1
                    if table == "patient":
                        mrn = str(row[tspec["key"]])
                        pid = pid_for_mrn(key, mrn)
                        pairs.append((pid, mrn))
                        if ident:
                            idents.append((pid, {k: str(row.get(col) or "") for k, col in ident.items()}))
                        if len(pairs) >= PID_BATCH:
                            pm.upsert_many(pairs)
                            if idents:
                                pm.upsert_identity(idents)
                            pairs, idents = [], []
                    try:
                        mapped = list(mapper.map_table(table, iter([row])))
                    except (ValueError, ArithmeticError):  # D-527: as the night does
                        bad["rejected"] += 1
                        continue
                    for res in mapped:
                        emit(res)
                if pairs:
                    pm.upsert_many(pairs)
                    if idents:
                        pm.upsert_identity(idents)
                rows_by_table[table] = n_rows
                if bad:
                    rejected[table] = sum(bad.values())
                # D-535: the facts the night keeps per table (pipeline.completeness_check reads them). Duplicate keys
                # are not counted by the first load (the night does, in a pass of its own): said by the flag
                tables[table] = {
                    "present": has_table(src, src_name),
                    "rows": n_read,
                    "rows_live": n_rows,
                    "duplicate_keys": 0,
                    "duplicates_counted": False,
                }
                if bad:
                    tables[table]["rejected"] = {"rejected": sum(bad.values())}
            for table, by_lookup in mapper.unmapped_summary().items():  # NEW-DIN-6 (D-580), as the night
                if table in tables:  # only a table that was read has an entry (its rows, its presence)
                    tables[table]["unmapped"] = by_lookup
            unmapped_codes = mapper.unmapped_by_code(cfg.mrn_regex)  # codes only: never a chart number or a name
        if patients:
            held = {"Patient": [r for _, r in patients]}
            apply_aliases(held, aliases)
            kept = {id(r) for r in held["Patient"]}
            for seq, r in patients:
                if id(r) in kept:
                    sp.put(r, BASE, seq)
    finally:
        sp.close()
        pm.close()
    return {"rejected": rejected, "rows": rows_by_table, "tables": tables, "unmapped_codes": unmapped_codes}


def _sort_bucket(spool: Path, runs: Path, bucket: str) -> dict[str, Any]:
    """Phase 2 for one bucket: each type's spool sorted by (id, seq) into a run file, and the bucket's DQ report.
    Memory: the ids and offsets of one type of one year."""
    t0 = time.perf_counter()
    out = runs / bucket
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    counts: dict[str, int] = {}
    missing: Counter[str] = Counter()
    undated = 0
    for f in sorted((spool / bucket).glob("*.ndjson")):
        index: list[tuple[str, str, int, int]] = []
        with f.open("rb") as fh:
            off = 0
            for line in fh:
                seq, _, body = line.partition(b"\t")
                r = json.loads(body)
                index.append((str(r["id"]), seq.decode("ascii"), off, len(line)))
                for p in missing_required(r):
                    missing[f"{f.stem}.{p}"] += 1
                if f.stem == "MedicationRequest" and _undated_order(r):
                    undated += 1
                off += len(line)
        index.sort()
        ids: set[str] = set()
        with f.open("rb") as src, (out / f.name).open("wb") as dst:
            for rid, num, at, n in index:
                src.seek(at)
                dst.write(rid.encode("utf-8") + b"\t" + num.encode("ascii") + b"\t" + src.read(n).partition(b"\t")[2])
                ids.add(rid)
        counts[f.stem] = len(ids)
        del index, ids
    dq = {
        "bucket": bucket,
        "counts": dict(sorted(counts.items())),
        "missing_required": dict(sorted(missing.items())),
        "undated_orders": undated,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    _atomic_json(out / DQ, dq)  # last: the bucket is done
    return dq


def _merged(runs: Path, buckets: list[str], rtype: str) -> Iterator[str]:
    """Canonical JSON lines of ``rtype`` over ``buckets``, sorted by id, the last source row of an id winning."""
    files = [
        (runs / b / f"{rtype}.ndjson").open(encoding="utf-8")
        for b in buckets
        if (runs / b / f"{rtype}.ndjson").exists()
    ]
    try:
        prev_id: str | None = None
        prev_body = ""
        for line in heapq.merge(*files, key=lambda ln: (ln.split("\t", 1)[0], ln.split("\t", 2)[1])):
            rid, _, rest = line.partition("\t")
            body = rest.partition("\t")[2]
            if prev_id is not None and rid != prev_id:
                yield prev_body
            prev_id, prev_body = rid, body
        if prev_id is not None:
            yield prev_body
    finally:
        for fh in files:
            fh.close()


def _write_merged(runs: Path, buckets: list[str], out: Path) -> dict[str, int]:
    types = sorted({p.stem for b in buckets for p in (runs / b).glob("*.ndjson")})
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for rtype in types:
        tmp = out / f".{rtype}.ndjson.tmp"
        n = 0
        with tmp.open("w", encoding="utf-8") as fh:
            for body in _merged(runs, buckets, rtype):
                fh.write(body)
                n += 1
        tmp.replace(out / f"{rtype}.ndjson")
        counts[rtype] = n
    return counts


def _sample(
    folder: Path, counts: dict[str, int], fraction: float, minimum: int = 3, cap: int | None = None
) -> list[dict[str, Any]]:
    """``validator.sample`` over a folder without loading it: the same hash order, a bounded heap per type, the
    same size rule (T-693, D-457: the share, at least ``minimum``, at most ``cap``)."""
    from adapter.validate.validator import sample_size

    out: list[dict[str, Any]] = []
    for rtype in sorted(counts):
        k = sample_size(counts[rtype], fraction, minimum, cap)
        if k <= 0:
            continue
        heap: list[tuple[str, str]] = []  # max-heap by hash (negated via sorting key below)
        with (folder / f"{rtype}.ndjson").open(encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                h = hashlib.sha256(f"trialbox|{r['resourceType']}|{r['id']}".encode()).hexdigest()
                item = (_neg(h), line)
                if len(heap) < k:
                    heapq.heappush(heap, item)
                elif item > heap[0]:
                    heapq.heapreplace(heap, item)
        out.extend(json.loads(line) for _, line in sorted(heap, reverse=True))
    return out


def _neg(h: str) -> str:
    """A hex string whose order is the reverse of ``h``'s (for a bounded max-heap on ``heapq``'s min-heap)."""
    return h.translate(str.maketrans("0123456789abcdef", "fedcba9876543210"))


def _published(cfg: AdapterConfig, snap: str, buckets: list[str]) -> bool:
    """Whether an earlier run of this back-fill already published these buckets (a resumed run does not repeat the
    first publish)."""
    final_dir = snapshot_dir(cfg.lake_dir, snap)
    try:
        body = json.loads((final_dir / REPORT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (final_dir / PASSED).exists() and set(body.get("years") or []) >= {b for b in buckets if b != BASE}


def _progress(work: Path, rep: BackfillReport, step: str) -> None:
    _atomic_json(work / "progress.json", {"step": step, **rep.as_dict()})


def backfill(
    cfg: AdapterConfig,
    source_kind: str,
    source_path: str,
    *,
    snapshot: str | None = None,
    work_dir: Path | None = None,
    first_years: int = 0,
    validate: bool = True,
    validator: Hl7Validator | StructuralValidator | None = None,
    rebuild_lake: bool = True,
    on_bucket: Callable[[str], None] | None = None,
) -> BackfillReport:
    """Load the source's whole history as snapshot ``snapshot`` (today in the site's zone by default); see the module
    docstring. ``on_bucket`` is called after each year is sorted (a :class:`BackfillStop` from it ends the run there;
    the next run resumes)."""
    t0 = time.perf_counter()
    zone = ZoneInfo(cfg.tz)
    snap = snapshot or datetime.now(zone).date().isoformat()
    refuse_future_night(snap, datetime.now(zone).date())  # D-529
    key = cfg.site_key()
    check_site_key(cfg, key)
    work = work_dir or cfg.lake_dir / "backfill" / snap
    work.mkdir(parents=True, exist_ok=True)
    spool, runs = work / "spool", work / "runs"
    rep = BackfillReport(snapshot=snap)
    fp = _fingerprint(cfg, source_kind, source_path, snap)
    marker = spool / SPOOL_DONE
    done_spool = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None

    def read_source() -> dict[str, Any]:
        _progress(work, rep, "spool")
        shutil.rmtree(runs, ignore_errors=True)  # runs of another source are void
        got = {"fingerprint": fp, **_spool(cfg, source_kind, source_path, snap, spool, key)}
        _atomic_json(marker, got)
        return got

    def gate(got: dict[str, Any]) -> list[str]:
        # D-535: the first load is a hospital's first night. The night's completeness gate is asked of its tables
        # before a year is published (a required table missing or empty; with ``first_night_all_tables``, any
        # table of the mapping that is not optional). A source without tables (a FHIR bulk export) is asked with
        # none, as the night asks it
        tables = {str(t): dict(v) for t, v in (got.get("tables") or {}).items()}
        return completeness_check(cfg, tables, work / "none", None, full=True)[0]

    # a spool is reused when it is of the same source, mapping and snapshot AND holds the table facts (a spool
    # written before D-535 has none: the source is read again, or the gate and the baseline would be skipped)
    if done_spool and done_spool.get("fingerprint") == fp and "tables" in done_spool:
        rep.spool_reused = True
        facts = done_spool
        if gate(facts):
            # the load was held for its tables and is run again: the site may have supplied what was missing (the
            # fingerprint does not see a table added to the folder). Read the source again, once, before holding
            log.warning("back-fill %s: the kept spool's tables are incomplete; the source is read again", snap)
            rep.spool_reused = False
            facts = read_source()
    else:
        if done_spool and done_spool.get("fingerprint") == fp:
            log.warning("back-fill %s: the kept spool has no table facts (an older version's); read again", snap)
        facts = read_source()
    rep.rejected = dict(facts.get("rejected") or {})
    codes = facts.get("unmapped_codes") or {}
    rep.unmapped = {t: sum(sum(c.values()) for c in by.values()) for t, by in sorted(codes.items())}
    rep.incomplete = gate(facts)
    rep.errors += rep.incomplete
    for table, n in rep.unmapped.items():
        log.warning("%s: %d rows hold a value no look-up knows (%s)", table, n, UNMAPPED_CODES)
    for table, n_bad in sorted(rep.rejected.items()):
        n_rows = int((facts.get("rows") or {}).get(table) or 0)
        if n_bad * 100 > REJECT_MAX_PCT * max(1, n_rows):
            rep.errors.append(f"{table}: {n_bad} of {n_rows} rows rejected (over {REJECT_MAX_PCT:g} %)")
    years = sorted((p.name for p in spool.iterdir() if p.is_dir() and p.name != BASE), reverse=True)
    rep.years = ([BASE] if (spool / BASE).is_dir() else []) + years
    publish_at = len(rep.years) if first_years <= 0 else min(len(rep.years), 1 + first_years)
    try:
        for i, bucket in enumerate(rep.years, start=1):
            if not (runs / bucket / DQ).exists():
                _progress(work, rep, f"year {bucket}")
                dq = _sort_bucket(spool, runs, bucket)
                log.info("back-fill %s: %s sorted (%s)", snap, bucket, dq["counts"])
                if on_bucket is not None:
                    on_bucket(bucket)
            rep.done.append(bucket)
            if i == publish_at and i < len(rep.years) and not rep.errors and not _published(cfg, snap, rep.done):
                _publish(cfg, rep, work, runs, list(rep.done), validate, validator, rebuild_lake, final=False)
                if rep.state == "held":
                    break
    except BackfillStop:
        rep.state = "running"
        rep.seconds = round(time.perf_counter() - t0, 2)
        _progress(work, rep, "stopped")
        return rep
    if rep.errors and rep.state != "held":
        rep.state = "held"
    elif rep.state != "held":
        _publish(cfg, rep, work, runs, list(rep.done), validate, validator, rebuild_lake, final=True)
    rep.seconds = round(time.perf_counter() - t0, 2)
    _progress(work, rep, rep.state)
    _audit(cfg, rep)
    return rep


def _spool_facts(work: Path) -> dict[str, Any]:
    """What the spool phase recorded beside its spool (``spool/done.json``), or {} (a spool of an older version)."""
    try:
        got = json.loads((work / "spool" / "done.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _publish(
    cfg: AdapterConfig,
    rep: BackfillReport,
    work: Path,
    runs: Path,
    buckets: list[str],
    validate: bool,
    validator: Hl7Validator | StructuralValidator | None,
    rebuild_lake: bool,
    *,
    final: bool,
) -> None:
    """Phase 3: the done years as the snapshot's NDJSON, checked, loaded and rebuilt (see the module docstring)."""
    snap = rep.snapshot
    _progress(work, rep, f"publish {'all' if final else 'first'} years")
    stage = work / "publish"
    shutil.rmtree(stage, ignore_errors=True)
    counts = _write_merged(runs, buckets, stage)
    years = [b for b in buckets if b != BASE]
    _atomic_json(stage / REPORT, {"snapshot": snap, "years": years, "complete": final})
    # D-535: the snapshot's completeness record and its unknown codes, as a night's snapshot has them. The table
    # facts are the spool's (kept beside it: a run started again writes the same); the orphan counts are read from
    # the records of this publish
    facts = _spool_facts(work)
    tables = {str(t): dict(v) for t, v in (facts.get("tables") or {}).items()}
    if "tables" in facts:  # always, since the load reads its source again for a spool without them
        _, completeness = completeness_check(cfg, tables, stage, None, full=True)
        completeness["first_load"] = {"years": years, "complete": final}
        _atomic_json(stage / COMPLETENESS, completeness)
    if facts.get("unmapped_codes"):
        _atomic_json(stage / UNMAPPED_CODES, facts["unmapped_codes"])
    errors: list[str] = []
    if validate:
        chosen = validator or Hl7Validator.from_env() or StructuralValidator()
        try:
            from adapter.validate.validator import capped_types, sample_cap

            cap = sample_cap(cfg.validation_max_pct)  # T-693 (D-457)
            rep.validation_sample = {
                "sample_cap": cap,
                "capped": capped_types(counts, cfg.sample_fraction, cap=cap),
            }
            v = chosen.validate(_sample(stage, counts, cfg.sample_fraction, cap=cap))
            if v.error_pct > cfg.validation_max_pct:
                errors.append(f"validation error rate {v.error_pct:.2f}% exceeds {cfg.validation_max_pct}%")
        except Exception as exc:
            errors.append(f"validation failed to run: {exc}")
    last_good = merge_base(cfg.lake_dir, snap)
    if last_good is not None and last_good != snap:  # D-271: never (nearly) empty a kind of record
        try:
            pct = feedguard.max_drop_pct()
            before = _type_counts(snapshot_dir(cfg.lake_dir, last_good))
            bad = feedguard.drops(before, {t: n - counts.get(t, 0) for t, n in before.items()}, pct)
        except feedguard.FeedGuardError as exc:
            bad, pct = [str(exc)], 0.0
        if bad and not feedguard.override_for(snap):
            errors.append(f"the back-fill removes {'; '.join(bad)} records of snapshot {last_good} (limit {pct:g} %)")
    if errors:
        rep.errors += errors
        rep.state = "held"
        return
    final_dir = snapshot_dir(cfg.lake_dir, snap)
    old = work / "replaced"
    shutil.rmtree(old, ignore_errors=True)
    if final_dir.exists():
        final_dir.rename(old)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(stage), str(final_dir))  # a --work folder may be on another disk
    shutil.rmtree(old, ignore_errors=True)
    rep.counts = counts
    from adapter.dual_write import load_night

    omop = load_night(cfg, snap, final_dir)
    rep.omop = omop.model_dump(mode="json") if omop is not None else None
    if rebuild_lake and cfg.rebuild is not None:
        try:
            rep.lake = cfg.rebuild(snap, final_dir).model_dump(mode="json")
        except Exception as exc:
            rep.errors.append(f"lake rebuild failed: {type(exc).__name__}: {str(exc)[:300]}")
            rep.state = "held"
            return
    (final_dir / PASSED).write_text(json.dumps({"snapshot": snap}) + "\n", encoding="utf-8")
    rep.published.append(list(buckets))
    rep.state = "published" if final else "partial"
    log.info("back-fill %s: published %s (%s)", snap, "every year" if final else f"{len(years)} years", counts)


def _audit(cfg: AdapterConfig, rep: BackfillReport) -> None:
    if not cfg.audit_dir:
        return
    open_audit(cfg.audit_dir, cfg.tz).append(
        "ingest.backfill",
        snapshot=rep.snapshot,
        actor="adapter",
        detail={
            "state": rep.state,
            "years": [y for y in rep.years if y != BASE],
            "published": rep.published,
            "counts": rep.counts,
            "rejected": rep.rejected or None,
            "errors": rep.errors or None,
            "current": _current(cfg.lake_dir),
        },
    )
