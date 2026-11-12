"""Nightly ingest pipeline (SPEC §4.6): extract -> map -> NDJSON -> fhir-store + lake -> validate sample -> report."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import chartno, feedguard, labvalue
from tb_common.audit_writer import open_audit
from tb_common.crypto import SITE_KEY_FILE, KeyMissingError, key_fingerprint, load_key, pid_for_mrn, sha256_bytes
from tb_common.db import ENV as DB_URL_ENV
from tb_contracts import IngestReport, RebuildResult, ValidationSummary, dump
from tb_contracts.landing import Severity

from adapter import governance
from adapter.instants import to_site_offset
from adapter.mapping.engine import Mapper, Mapping, resource_id
from adapter.ndjson import Spool, is_deleted_flag, list_snapshots, snapshot_dir, tombstone_count, write_snapshot
from adapter.pidmap import PidMap
from adapter.sources.base import CHANGE_COLUMNS, Row, Source, has_table, quarantine_reason
from adapter.validate.validator import Hl7Validator, Sampler, StructuralValidator, missing_required

log = logging.getLogger("adapter")
Resource = dict[str, Any]


@dataclass
class AdapterConfig:
    lake_dir: Path
    secrets_dir: Path
    mapping_path: Path
    site_id: str
    tz: str = ""  # the site's zone; empty: TB_TZ, never a zone of the code's own (D-315)
    fhir_base_url: str | None = None
    audit_dir: Path | None = None
    validation_max_pct: float = 0.5
    sample_fraction: float = 0.01
    rebuild: Callable[[str, Path], RebuildResult] | None = None
    # T-723 (D-489): the lake in two steps, so a publish promotes last: ``build`` builds and judges a night without
    # serving it, ``promote`` makes it the served one (False: a newer night is served). Both None: ``rebuild`` alone
    build: Callable[[str, Path], RebuildResult] | None = None
    promote: Callable[[str], bool] | None = None
    # settings.registry_source: None = the data source's own ``registry`` table; ("none", "") = no registry;
    # ("csv", "/path/registry.csv") or ("sql", dsn) = a separate consent registry
    registry: tuple[str, str] | None = None
    keep_nightly: int = 3  # settings.retention.nightly_snapshots
    keep_month_end_months: int = 36  # settings.retention.month_end_snapshots_months
    db_url: str | None = None  # the trial database of the pid map (TB_DB_URL when None)
    profile_sample_per_type: int = 50  # D-137: resources per type checked against the mapping's profiles (JP Core)
    # T-611 (settings.feed_completeness): the completeness gate per source table
    table_max_drop_pct: float = 10.0
    required_tables: tuple[str, ...] = ()
    optional_tables: tuple[str, ...] = ()
    # NEW-DIN-8 (D-583): on the first night every table the mapping declares must be there with rows, unless it is
    # in ``optional_tables``. The product's entry (``adapter.cli``) always sets it; a tool or a test that builds a
    # night from a partial feed of its own making leaves it off
    first_night_all_tables: bool = False
    source_encoding: str | None = None  # T-615b: settings.data_source.encoding, the csv reader's first candidate
    # T-659b (D-370): the folder of data contracts (adapter/governance.py); None: no contract checks
    contracts_dir: Path | None = None
    # FIT-U09 (T-629): settings.mrn_regex, the site's chart-number pattern; a column whose all-digit values match it
    # only with leading zeros put back is refused (``tb_common.chartno.column_refusal``)
    mrn_regex: str | None = None

    def __post_init__(self) -> None:
        from tb_common.config import site_tz

        self.tz = site_tz(self.tz or None)  # ConfigError when neither the caller nor TB_TZ names a zone (D-315)

    def site_key(self) -> bytes:
        """The site's pseudonymisation key. Never made here (T-612): :class:`SiteKeyError` when it is missing."""
        path = self.secrets_dir / SITE_KEY_FILE
        try:
            return load_key(path)
        except KeyMissingError:
            raise SiteKeyError(
                f"the site key {path} is missing. It is made only by the install ceremony (deploy/install.sh runs "
                f"`python -m adapter.cli keys-init`); on a box that has run before, put the site's own key back from "
                f"the backup: a new key would give every patient a new pseudonym and lose their opt-outs"
            ) from None

    def pidmap(self) -> PidMap:
        return PidMap(self.secrets_dir / "pid_map.key", self.db_url)


class SiteKeyError(RuntimeError):
    """T-612 (DATA-004): the night is refused before anything is read or written, because the site key is missing or
    is not the key the box's pseudonyms were made with."""


SITE_KEY_RECORD = "site_key.json"  # in the lake folder: the fingerprint of the key its snapshots were written under


def check_site_key(cfg: AdapterConfig, key: bytes) -> str:
    """T-612: refuse a site key other than the one this box's data was made with; record it the first time.

    Compared with the fingerprint in ``<lake>/site_key.json`` and, when a trial database is configured, with the pid
    map's stored fingerprint and its rows (:meth:`PidMap.site_key_problem`). Returns the fingerprint."""
    fp = key_fingerprint(key)
    record = cfg.lake_dir / SITE_KEY_RECORD
    problems: list[str] = []
    seen: str | None = None
    try:
        seen = str(json.loads(record.read_text(encoding="utf-8"))["fingerprint"])
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(f"{record} cannot be read ({type(exc).__name__})")
    if seen is not None and seen != fp:
        problems.append(f"the lake's snapshots were written under key {seen}")
    if cfg.db_url or os.environ.get(DB_URL_ENV):
        pm = cfg.pidmap()
        try:
            why = pm.site_key_problem(cfg.site_id, key)
            if why:
                problems.append(f"the pid map: {why}")
            elif not problems:
                pm.record_site_key(cfg.site_id, key)
        finally:
            pm.close()
    if problems:
        raise SiteKeyError(
            f"the site key {cfg.secrets_dir / SITE_KEY_FILE} (fingerprint {fp}) is not the key this box's pseudonyms "
            f"were made with: {'; '.join(problems)}. Put the site's own key back from the backup; a new key would "
            f"give every patient a new pseudonym and lose their opt-outs"
        )
    if seen is None:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"fingerprint": fp, "site_id": cfg.site_id}) + "\n", encoding="utf-8")
    return fp


def make_source(kind: str, path: str, db_url: str | None = None, encoding: str | None = None) -> Source:
    if kind == "csv":
        from adapter.sources.csv.source import CsvSource

        return CsvSource(Path(path), encoding)
    if kind == "cgrd_sql":
        from adapter.sources.cgrd_sql.source import SqlSource

        return SqlSource(path)
    if kind == "ssmix2":
        from adapter import licensed
        from adapter.sources.ssmix2.source import Ssmix2Source

        # SS-MIX2 standardized and extended storage (D-122, D-137), with the site's licensed code lists
        return Ssmix2Source(Path(path), licensed=licensed.tables(db_url))
    raise ValueError(f"unknown source {kind!r}")


_REF_RE = re.compile(r"^([A-Z][A-Za-z]+)/(.+)$")


def bulk_id(key: bytes, rtype: str, rid: str) -> str:
    """The id a ``fhir_bulk`` resource gets in the box (the same rule for the resource, its references and its
    tombstone)."""
    if rtype == "Practitioner":
        return rid
    return pid_for_mrn(key, rid) if rtype == "Patient" else resource_id(key, rtype, rid)


def pseudonymise_bulk(resources: Iterator[Resource], key: bytes) -> Iterator[Resource]:
    """For ``fhir_bulk``: replace ids/references by pseudonyms and drop direct identifiers.

    One rule maps a resource's id and every reference to it, so a reference always finds its resource. A Practitioner
    keeps the hospital's staff id in both (as the CSV and SS-MIX2 mappings key it, ``{column: staff_id}``): a
    clinician is not a patient, and a study's clinic scope names its doctors by that id (D-120). Hashing only the
    references left every appointment without its practitioner and SCREEN with no one in scope (scenario run
    FHIR-01)."""

    def new_id(rtype: str, rid: str) -> str:
        return bulk_id(key, rtype, rid)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "reference" and isinstance(v, str) and (m := _REF_RE.match(v)):
                    out[k] = f"{m.group(1)}/{new_id(m.group(1), m.group(2))}"
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    for r in resources:
        r = walk(r)
        if r["resourceType"] == "Patient":
            for k in ("name", "telecom", "address", "photo", "contact", "identifier"):
                r.pop(k, None)
        r["id"] = new_id(r["resourceType"], r["id"])
        yield r


UNIT_SOURCE = "urn:trialbox:unit-source"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


def apply_unit_defaults(observations: list[Resource], defaults: dict[str, str]) -> int:
    """D-149 (owner decision 2026-11-09): a hospital-feed result with a number and no unit takes the site's declared
    unit for that analyte (``unit_defaults`` in the site mapping, LOINC -> UCUM), marked with the tag
    ``urn:trialbox:unit-source|site-default`` so the profile and an audit can tell. Only the feed does this; a sheet
    or chart value without a unit stays without one (its score is unknown). Returns how many results were given one."""
    if not defaults:
        return 0
    n = 0
    for r in observations:
        q = r.get("valueQuantity")
        if not isinstance(q, dict) or "value" not in q or q.get("code") or q.get("unit"):
            continue
        code = next(
            (c.get("code") for c in (r.get("code") or {}).get("coding") or [] if c.get("system") == LOINC), None
        )
        unit = defaults.get(str(code)) if code else None
        if unit is None:
            continue
        q.update({"unit": unit, "code": unit, "system": UCUM})
        meta = r.setdefault("meta", {})
        meta.setdefault("tag", []).append({"system": UNIT_SOURCE, "code": "site-default"})
        n += 1
    return n


VALUE_SOURCE = "urn:trialbox:value-source"
# the LOINC answers of a presence test (answer list LL360-9), as the shipped lab lookups write them (D-334)
PRESENCE_ANSWERS = {labvalue.POSITIVE: ("LA6576-8", "Positive"), labvalue.NEGATIVE: ("LA6577-6", "Negative")}


def apply_presence_words(observations: list[Resource]) -> int:
    """D-418 (T-619c, DATA-016): a ``fhir_bulk`` feed has no mapping step, so a qualitative result it sends as text
    (``valueString`` 陰性, 陽性, 未檢出, Non-reactive, 2+) was never read: every criterion on it stayed unknown. The
    shared presence reader of the mapped sources (``tb_common.labvalue.presence``, D-334) now reads it into the LOINC
    answer the shipped lookups use (``LA6576-8`` Positive, ``LA6577-6`` Negative), keeps the text as written in
    ``valueCodeableConcept.text``, and tags the result ``urn:trialbox:value-source|presence-word``. Only a result
    coded in LOINC is read. A held or borderline word (判定保留, ±, equivocal) and any other text stay text, which the
    engines read as unknown. Returns how many results were read."""
    n = 0
    for r in observations:
        text = r.get("valueString")
        if not isinstance(text, str) or not any(
            c.get("system") == LOINC for c in (r.get("code") or {}).get("coding") or []
        ):
            continue
        answer = PRESENCE_ANSWERS.get(labvalue.presence(text) or "")
        if answer is None:
            continue
        del r["valueString"]
        r["valueCodeableConcept"] = {
            "coding": [{"system": LOINC, "code": answer[0], "display": answer[1]}],
            "text": text,
        }
        r.setdefault("meta", {}).setdefault("tag", []).append({"system": VALUE_SOURCE, "code": "presence-word"})
        n += 1
    return n


def _bulk_unit_defaults(mapping_path: Path) -> dict[str, str]:
    """A ``fhir_bulk`` feed has no mapping step; its declared units are the ``unit_defaults`` of the site mapping."""
    try:
        import yaml

        doc = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) if mapping_path.is_file() else None
    except (OSError, ValueError):
        return {}
    raw = (doc or {}).get("unit_defaults") if isinstance(doc, dict) else None
    return {str(k): str(v) for k, v in (raw or {}).items()}


def _undated_order(r: dict[str, Any]) -> bool:
    period = (r.get("dispenseRequest") or {}).get("validityPeriod") or {}
    bounds = ((((r.get("dosageInstruction") or [{}])[0] or {}).get("timing") or {}).get("repeat") or {}).get(
        "boundsPeriod"
    ) or {}  # T-616 (STD-012): the therapy period, read first
    return not r.get("authoredOn") and not period.get("start") and not bounds.get("start")


CHART_COLUMNS = ("mrn",)  # the canonical chart-number column of every table (mapping/templates/CANONICAL.md)


def chart_column_refused(
    mapping: Mapping, table: str, tspec: dict[str, Any], rows: Iterable[Row], mrn_regex: str | None
) -> str | None:
    """FIT-U09 (T-629, D-415): why this table's chart-number column is refused, naming the column as the export
    writes it, or None. The patient table's key and every table's ``mrn`` are checked: a column that Excel turned
    into numbers (``tb_common.chartno.column_refusal``) would give some patients a second pseudonym, so the whole
    table is set aside and the night is held; nothing is guessed back."""
    first = next(iter(rows), None)  # re-readable: a list or the table's rows on disk (T-692)
    if first is None:
        return None
    cols = list(CHART_COLUMNS)
    if table == "patient" and tspec.get("key") and tspec["key"] not in cols:
        cols.insert(0, str(tspec["key"]))
    for col in cols:
        if col not in first:
            continue
        why = chartno.column_refusal((str(r.get(col) or "") for r in rows), mrn_regex)
        if why:
            local = mapping.source_column(table, col) or col
            what = {
                "excel_number": "holds numbers written the way Excel writes them (123456.0, 1.2E+11)",
                "lost_zeros": "holds chart numbers that match the site's pattern only with leading zeros put back",
            }[why]
            return (f"chart-number column {local!r} refused ({why}): it {what}; the leading zeros are lost. Export "
                    "the column as text and run the night again")  # fmt: skip
    return None


def _kept(rows: Iterable[Row], into: list[Row]) -> Iterator[Row]:
    """``rows`` as they pass, each also kept in ``into`` (the data contracts read the raw rows)."""
    for r in rows:
        into.append(r)
        yield r


def _duplicates(keys: Iterable[str], work: Path) -> int:
    """How many keys repeat an earlier one (``len(keys) - len(set(keys))``), counted over the keys sorted in runs on
    disk (T-692): a table's keys are never held."""
    from adapter.ndjson import _sorted, sort_run_bytes

    n = 0
    prev: str | None = None
    try:
        for k, _, _ in _sorted(((k, i, "") for i, k in enumerate(keys)), sort_run_bytes(), work):
            n += k == prev
            prev = k
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return n


class _TableRows:
    """One source table's normalized rows on disk, read again for each pass (T-692, D-473): the table is never held.

    A row that a JSON line does not give back exactly (a key that is not text, a value that is neither text nor
    empty: a CSV row with more cells than its header) keeps the table in memory instead, as before. ``where`` gives
    a view: only the rows at the ``keep`` positions (the data contracts' accepted rows), and with ``live`` only the
    rows that are not marked deleted in that column."""

    def __init__(self, path: Path, held: list[Row] | None, keep: set[int] | None, live: str | None) -> None:
        self.path, self.held, self.keep, self.live = path, held, keep, live
        self._n: int | None = None

    @classmethod
    def write(cls, path: Path, rows: Iterable[Row]) -> _TableRows:
        held: list[Row] | None = None
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                if held is None and all(type(k) is str and (v is None or type(v) is str) for k, v in r.items()):
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    continue
                if held is None:
                    fh.flush()
                    held = list(cls(path, None, None, None))
                held.append(r)
        if held is not None:
            path.unlink(missing_ok=True)
        return cls(path, held, None, None)

    def where(self, keep: set[int] | None = None, live: str | None = None) -> _TableRows:
        if keep is not None and self.keep is not None:
            raise ValueError("one row filter by position per table")
        return _TableRows(self.path, self.held, keep if keep is not None else self.keep, live or self.live)

    def _all(self) -> Iterator[Row]:
        if self.held is not None:
            yield from self.held
            return
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)

    def __iter__(self) -> Iterator[Row]:
        col = self.live
        for i, r in enumerate(self._all()):
            if self.keep is not None and i not in self.keep:
                continue
            if col is not None and col in r and is_deleted_flag(r[col]):
                continue
            yield r

    def __len__(self) -> int:
        if self._n is None:
            self._n = sum(1 for _ in self)
        return self._n

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)


def check_delta(mapping: Mapping, source_kind: str) -> None:
    """T-615b (DATA-008): on a csv or cgrd_sql delta night every ``delta:`` must name a change-time column
    (:data:`CHANGE_COLUMNS`), never a clinical date. Raises :class:`ValueError` naming the table."""
    if source_kind not in ("csv", "cgrd_sql"):
        return  # SS-MIX2 versions its files itself; a FHIR bulk export carries its own _since
    for table, tspec in mapping.tables.items():
        col = tspec.get("delta")
        if col and col not in CHANGE_COLUMNS:
            raise ValueError(
                f"delta night refused: table {table}'s delta column {col!r} is not a change time "
                f"({', '.join(CHANGE_COLUMNS)}); a corrected or late-entered record keeps its old clinical date and "
                "would be missed. Map the source's change-time column to updated_at, or run a full night"
            )


def run_ingest(
    cfg: AdapterConfig,
    source_kind: str,
    source_path: str,
    *,
    since: str | None = None,
    snapshot: str | None = None,
    load_fhir: bool = True,
    rebuild_lake: bool = True,
    validate: bool = True,
    validator: Hl7Validator | StructuralValidator | None = None,
) -> IngestReport:
    """One night's ingest. Any exception on the way (an unreadable source, a mapping error, a full disk) writes one
    ``ingest.failed`` audit event with the error's type, the step and the table, then propagates (T-615b, DATA-003).
    The event holds no message text: a parser's message can quote a cell."""
    at: dict[str, str | None] = {"step": "start", "table": None}
    try:
        with contextlib.ExitStack() as cleanup:  # T-692: the night's spool goes, whatever happens
            return _run_ingest(
                cfg,
                source_kind,
                source_path,
                at,
                since=since,
                snapshot=snapshot,
                load_fhir=load_fhir,
                rebuild_lake=rebuild_lake,
                validate=validate,
                validator=validator,
                cleanup=cleanup,
            )
    except SiteKeyError:  # T-612 audits its own refusal (with the reason); one event per night
        raise
    except Exception as exc:
        if cfg.audit_dir:
            try:
                night_event(
                    cfg,
                    "ingest.failed",
                    snapshot=snapshot or datetime.now(ZoneInfo(cfg.tz)).date().isoformat(),
                    source=source_kind,
                    passed=False,
                    held=False,
                    batch=at.get("batch"),
                    actor="adapter",
                    detail={
                        "source": source_kind,
                        "since": since,
                        "error": type(exc).__name__,
                        "step": at["step"],
                        "table": at["table"],
                    },
                )
            except Exception:  # the audit's own failure must not hide the ingest's
                log.exception("ingest.failed could not be audited")
        log.error("ingest failed", extra={"error": type(exc).__name__, "step": at["step"], "table": at["table"]})
        raise


def _run_ingest(
    cfg: AdapterConfig,
    source_kind: str,
    source_path: str,
    at: dict[str, str | None],
    *,
    since: str | None,
    snapshot: str | None,
    load_fhir: bool,
    rebuild_lake: bool,
    validate: bool,
    validator: Hl7Validator | StructuralValidator | None,
    cleanup: contextlib.ExitStack,
) -> IngestReport:
    zone = ZoneInfo(cfg.tz)
    started = datetime.now(zone)
    snap = snapshot or started.date().isoformat()
    at["batch"] = _open_night(cfg, source_kind, snap, started.isoformat())  # T-723 (D-489): the row, from the start
    try:  # T-612: before anything is read or written
        key = cfg.site_key()
        check_site_key(cfg, key)
    except SiteKeyError as exc:
        log.error("night refused: %s", exc)
        if cfg.audit_dir:
            open_audit(cfg.audit_dir, cfg.tz).append(
                "ingest.failed",
                snapshot=snap,
                actor="adapter",
                detail={"source": source_kind, "refused": "site_key", "reason": str(exc)},
            )
        raise
    errors: list[str] = []
    # T-692 (D-473): every mapped resource goes to disk as it is made; the night is never held in memory. The spool
    # is scratch on the lake volume (``lake:tmp``), removed when the night ends
    spool = cleanup.enter_context(contextlib.closing(Spool(cfg.lake_dir / "tmp" / f"ingest-{snap}")))
    patient_ids: list[str] = []  # in the order sent: the merged chart numbers drop by id alone

    def to_spool(r: Resource) -> None:
        spool.add(r)
        if r["resourceType"] == "Patient":
            patient_ids.append(str(r.get("id")))

    patient_pairs: list[tuple[str, str]] = []
    identities: list[tuple[str, dict[str, str]]] = []
    fhir_profiles = ""
    source: Source | None = None
    tombstones: dict[str, set[str]] = {}  # type -> ids deleted at the source (dataflow review P0-1)
    tables: dict[str, dict[str, Any]] = {}  # T-611: per source table, present / rows / duplicate keys
    unmapped_codes: dict[str, dict[str, dict[str, int]]] = {}  # NEW-DIN-6: table -> look-up -> code -> rows
    quarantined: dict[str, str] = {}  # T-615b: table -> why its file was quarantined
    current_before = _current(cfg.lake_dir)
    # T-659b (D-370): the controls moved from the retired data platform: contracts, row quarantine, control totals
    contracts = (
        governance.load_contracts(cfg.contracts_dir) if cfg.contracts_dir and source_kind != "fhir_bulk" else None
    )
    control_totals = (
        governance.read_control_totals(Path(source_path))
        if contracts is not None and source_kind == "csv" and not since
        else None
    )
    checks: list[governance.TableCheck] = []
    inputs: list[Path] = []
    gate_facts = governance.NightFacts(night=snap, current_before=current_before)
    completeness_msgs: list[str] = []
    validation_msgs: list[str] = []
    at["step"] = "read"
    if source_kind == "fhir_bulk":
        from adapter.sources.fhir_bulk.source import FhirBulkSource

        bulk = FhirBulkSource(Path(source_path))
        inputs += [p for p in Path(source_path).iterdir() if p.is_file()]
        for r in pseudonymise_bulk(bulk.resources(), key):
            to_spool(r)
        for rtype, rid in bulk.deleted():
            if rtype != "Patient":  # removing a person is the opt-out path's job, never a feed delta's
                tombstones.setdefault(rtype, set()).add(bulk_id(key, rtype, rid))
    else:
        mapping = Mapping.load(cfg.mapping_path)
        if since:
            at["step"] = "delta check"
            check_delta(mapping, source_kind)
            at["step"] = "read"
        # T-106b (DATA-010): every resource carries its source row, mapping version and the night it was ingested
        mapper = Mapper(mapping, key, cfg.site_id, ingest_instant(snap, mapping.tz))
        fhir_profiles = mapping.fhir_profiles
        source = make_source(source_kind, source_path, cfg.db_url, cfg.source_encoding)
        for res in mapper.static_resources():
            to_spool(res)
        for table, tspec in mapping.tables.items():
            at["table"] = table
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
            delta = mapping.source_column(table, tspec.get("delta"))
            # T-692 (D-473): the table's rows go to disk as they are read and are read back for each pass; only the
            # data contracts (off unless TB_DATA_CONTRACTS) still need the raw rows in memory
            raw: list[Row] = []
            got = src.rows(table, src_name, delta, since)
            if contracts is not None:
                got = _kept(got, raw)
            rows = _TableRows.write(spool.root / f".rows-{table}", (mapping.normalize(table, r) for r in got))
            if isinstance(where_dir := getattr(src, "directory", None), Path):
                inputs.append(where_dir / f"{src_name}.csv")
            why = quarantine_reason(src, src_name)
            if why:  # T-615b: the file is set aside, the night goes on with the other tables and is held
                quarantined[table] = why
                errors.append(f"{table}: {why}")
            kcol = tspec.get("key")
            tables[table] = {  # T-611 (DATA-017: a duplicate source key is counted; the last row wins)
                "present": has_table(src, src_name),
                "rows": len(rows),
                "duplicate_keys": _duplicates((str(r.get(kcol)) for r in rows), spool.root / ".keys") if kcol else 0,
            }
            if contracts is not None:  # T-659b: the contract's row checks; a failing row is set aside, never mapped
                chk = governance.check_table(
                    contracts.get(src_name) or contracts.get(table),
                    table,
                    raw,
                    today=date.fromisoformat(snap[:10]),
                    source_totals=(control_totals or {}).get(src_name),
                    hasher=governance.key_hasher(key),
                    present=has_table(src, src_name) is not False,
                )
                checks.append(chk)
                if chk.validation.quarantined:
                    keep = {id(r) for r in chk.accepted}
                    rows = rows.where(keep={i for i, r in enumerate(raw) if id(r) in keep})
            del raw
            refused = chart_column_refused(mapping, table, tspec, rows, cfg.mrn_regex)
            if refused:  # FIT-U09 (T-629, D-415): the table is set aside whole and the night is held
                quarantined[table] = refused
                errors.append(f"{table}: {refused}")
                rows = rows.where(keep=set())
            if table in quarantined:  # NEW-DIN-8: already an error of its own; not also "empty"
                tables[table]["set_aside"] = True
            # a row marked deleted (``deleted`` column, or the table's ``deleted:`` column) is a tombstone, never a
            # record; a source that keeps deletes apart (SS-MIX2 flag 0) gives them through ``deleted_rows``
            dcol = str(tspec.get("deleted") or "deleted")
            dead = [r for r in rows if dcol in r and is_deleted_flag(r[dcol])]
            if dead:
                rows = rows.where(live=dcol)
                tables[table]["rows_live"] = len(rows)  # NEW-DIN-8: a table of deleted rows only is empty
            deleted_rows = getattr(src, "deleted_rows", None)
            if deleted_rows is not None:
                dead += [mapping.normalize(table, r) for r in deleted_rows(table, src_name, delta, since)]
            for rtype, rid in mapper.tombstones(table, iter(dead)):
                tombstones.setdefault(rtype, set()).add(rid)
            if table == "patient":
                patient_pairs = [(pid_for_mrn(key, str(r[tspec["key"]])), str(r[tspec["key"]])) for r in rows]
                ident = tspec.get("identity") or {}
                if ident:  # e.g. {name: name, national_id: id_no}: kept encrypted in the pid map only
                    identities = [
                        (pid, {k: str(r.get(col) or "") for k, col in ident.items()})
                        for (pid, _), r in zip(patient_pairs, rows, strict=True)
                    ]
            # STD-025 (T-615a): a row the mapping cannot read is rejected and counted by reason (its values left out);
            # the table goes on, and the night is held only when rejects pass REJECT_MAX_PCT % of the table's rows
            rejected: Counter[str] = Counter()
            for row in rows:
                try:
                    mapped = list(mapper.map_table(table, iter([row])))
                except ValueError as exc:
                    rejected[reject_key(exc)] += 1
                    continue
                for res in mapped:
                    to_spool(res)
            if rejected:
                n_bad = sum(rejected.values())
                tables[table]["rejected"] = dict(sorted(rejected.items()))
                why = "; ".join(f"{k} ({v})" for k, v in sorted(rejected.items()))
                log.warning("%s: %d of %d rows rejected: %s", table, n_bad, len(rows), why)
                if n_bad * 100 > REJECT_MAX_PCT * len(rows):
                    errors.append(f"{table}: {n_bad} of {len(rows)} rows rejected (over {REJECT_MAX_PCT:g} %): {why}")
            rows.discard()
        # NEW-DIN-6 (D-580): rows dropped for a code the look-up does not know, per table (codes and counts only)
        for table, by_lookup in mapper.unmapped_summary().items():
            tables[table]["unmapped"] = by_lookup
        unmapped_codes = mapper.unmapped_by_code(cfg.mrn_regex)  # codes only: never a chart number or a name
    at.update(step="snapshot", table=None)
    unit_defaults = mapping.unit_defaults if source_kind != "fhir_bulk" else _bulk_unit_defaults(cfg.mapping_path)
    counts = spool.counts()
    crep: Any = None
    if contracts is not None:
        crep = governance.contract_report(cfg.site_id, snap, checks, datetime.now(zone))
        gate_facts.contracts = crep
        bad = [
            f"{t.table}: {f.reason.value} ({f.detail})"
            for t in crep.tables
            for f in t.findings
            if f.severity == Severity.BLOCKING
        ]
        bad += [
            f"{e.table}: {e.reason.value if e.reason else ''} ({e.name}: export {e.lhs}, read {e.rhs})"
            for e in crep.reconciliation.equations
            if e.verdict == "fail"
        ]
        if bad:
            errors.append(f"data contracts: {'; '.join(bad)}")
    aliases: dict[str, str] = {}
    from adapter.publish import finish_served

    finish_served(cfg)  # T-723 second review (H2): a served night whose pid map step did not end is finished first
    if patient_pairs:
        pm = cfg.pidmap()
        try:
            # T-723 (D-489, F-12): the night's chart numbers are staged, not written: they enter the pid map when
            # the night is published (adapter.publish), so a held night's never reach the reverse map. The staged
            # rows of nights that are no longer held (rejected, replaced) are dropped here; never the served
            # night's (its pid map step may still be owed: ``finish_served``)
            still_held = _held_nights(cfg)
            if still_held is not None:
                served_now = _current(cfg.lake_dir)
                pm.discard(still_held | {snap} | ({served_now} if served_now else set()))
            pm.stage(snap, patient_pairs, identities or [])
            aliases = pm.aliases()  # T-659b: a merged chart number's records, one pid (applied as they are written)
        finally:
            pm.close()
    night = _NightPass(
        zone,
        unit_defaults,
        source_kind == "fhir_bulk",
        _Aliases(aliases, patient_ids),
        counts,
        cfg.sample_fraction if validate else None,
        cfg.profile_sample_per_type if validate and fhir_profiles == "jp-core" else None,
    )
    # NDJSON snapshot (delta runs merge over the previous snapshot and drop what the source deleted)
    final_dir = out_dir = snapshot_dir(cfg.lake_dir, snap)
    # D-271: a re-run of a promoted night is written beside it and moved in only when it passes; a held re-run never
    # touches the NDJSON that CURRENT (or a later delta) was built from
    from adapter.publish import recover_all

    recover_all(cfg)  # T-723 review: a re-run that was killed in its lake step is put back before anything is read
    rerun = (final_dir / PASSED).exists() or _current(cfg.lake_dir) == snap
    if rerun:
        out_dir = cfg.lake_dir / RERUN_DIR / snap
        shutil.rmtree(out_dir, ignore_errors=True)
    prev = [s for s in list_snapshots(cfg.lake_dir) if s < snap]
    last_good = merge_base(cfg.lake_dir, snap)  # D-271: never a held night's NDJSON
    base = snapshot_dir(cfg.lake_dir, last_good) if (since and last_good) else None
    if since and last_good is None and (prev or _current(cfg.lake_dir) or cfg.first_night_all_tables):
        # NEW-DIN-8 (D-583): on a box a delta is never the first night: it has nothing to merge over and no
        # table of it can be judged complete
        errors.append("delta night: no earlier snapshot passed validation to merge over; run a full load")
    from adapter.publish import RECORD as PUBLISH_RECORD

    try:  # T-723: the step record of an earlier publish of this folder (kept only for the same content)
        prior_record: str | None = (out_dir / PUBLISH_RECORD).read_text(encoding="utf-8")
    except OSError:
        prior_record = None
    full_counts = write_snapshot(out_dir, spool, base, tombstones, transform=night)
    (out_dir / PUBLISH_RECORD).unlink(missing_ok=True)
    defaulted, presence_read, shifted, aliased = (
        night.defaulted,
        night.presence_read,
        night.shifted,
        night.aliases.moved,
    )
    missing = night.missing_counts()
    tombstoned = tombstone_count(out_dir)
    overrides: list[str] = []
    # T-611: the completeness gate. A missing or emptied table, a table that shrank past the band, or a patient who
    # left the feed while their records stayed holds the night; D-271's override for this night lets it through
    gaps, completeness = completeness_check(cfg, tables, out_dir, last_good, full=not since)
    (out_dir / COMPLETENESS).write_text(
        json.dumps(completeness, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    if unmapped_codes:
        (out_dir / UNMAPPED_CODES).write_text(
            json.dumps(unmapped_codes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        for table, by_lookup in sorted(unmapped_codes.items()):
            log.warning("%s: %d rows dropped: %d values have no look-up row with a code (%s)", table,
                        sum(sum(c.values()) for c in by_lookup.values()), sum(len(c) for c in by_lookup.values()),
                        UNMAPPED_CODES)  # fmt: skip
    else:  # an earlier attempt of this night may have left one
        (out_dir / UNMAPPED_CODES).unlink(missing_ok=True)
    if gaps:
        what = f"incomplete feed (against snapshot {last_good or 'none'}): {'; '.join(gaps)}"
        reason = feedguard.override_for(snap)
        if reason:
            log.warning("%s: loaded under %s: %s", what, feedguard.OVERRIDE_ENV, reason)
            overrides.append(f"{what}; override: {reason}")
        else:
            errors.append(
                f"{what}. A missing or broken extract? To load it anyway set "
                f"{feedguard.OVERRIDE_ENV}='{snap}: <reason>' (this night only; the reason is audited)"
            )
            completeness_msgs.append(errors[-1])
    if last_good is not None:  # D-271: a night may not remove (nearly) all records of a kind
        try:
            pct = feedguard.max_drop_pct()
            before = _type_counts(snapshot_dir(cfg.lake_dir, last_good))
            bad = feedguard.drops(before, {t: n - full_counts.get(t, 0) for t, n in before.items()}, pct)
        except feedguard.FeedGuardError as exc:
            bad, pct = [str(exc)], 0.0
        if bad:
            drop_override = feedguard.override_for(snap)
            what = f"this night removes {'; '.join(bad)} records of snapshot {last_good} (limit {pct:g} %)"
            if drop_override:
                log.warning("%s: loaded under %s: %s", what, feedguard.OVERRIDE_ENV, drop_override)
                overrides.append(f"{what}; override: {drop_override}")
            else:
                errors.append(
                    f"{what}: a missing or broken extract? To load it anyway set "
                    f"{feedguard.OVERRIDE_ENV}='{snap}: <reason>' (this night only; the reason is audited)"
                )
                completeness_msgs.append(errors[-1])
    # dataflow review P0-2 (WS-08.1): validate first. fhir-store and the lake are loaded, and CURRENT moves, only for
    # a night that passed; a failed night is *held*: its NDJSON stays for the steward to look at, the box keeps
    # serving the previous snapshot
    at["step"] = "validate"
    vsum = ValidationSummary(sampled=0, errors=0, error_pct=0.0, validator="skipped", messages=[])
    if validate:
        chosen = validator or Hl7Validator.from_env() or StructuralValidator()
        picked = night.sample.result() if night.sample is not None else []
        try:
            vres = chosen.validate(picked)
            vsum = ValidationSummary(
                sampled=vres.sampled,
                errors=vres.errors,
                error_pct=round(vres.error_pct, 3),
                validator=vres.validator,
                messages=vres.messages,
            )
        except Exception as exc:
            errors.append(f"validation failed to run: {exc}")
    psum: ValidationSummary | None = None
    if validate and fhir_profiles == "jp-core":
        try:
            psum = jp_core_check(cfg, night.jp_sample.result() if night.jp_sample is not None else [], out_dir)
        except Exception as exc:
            errors.append(f"JP Core validation failed to run: {exc}")
    if source is not None and hasattr(source, "stats"):
        from adapter.sources.ssmix2.source import reader_summary

        (out_dir / "reader.json").write_text(
            json.dumps(reader_summary(source), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
    if vsum.error_pct > cfg.validation_max_pct:
        errors.append(f"validation error rate {vsum.error_pct:.2f}% exceeds {cfg.validation_max_pct}%")
        validation_msgs.append(errors[-1])
    if psum is not None and psum.error_pct > cfg.validation_max_pct:
        first = f": {psum.messages[0]}" if psum.messages else ""
        errors.append(
            f"JP Core: {psum.errors} of {psum.sampled} sampled resources fail ({psum.error_pct:.2f}%, over "
            f"{cfg.validation_max_pct}%; every failure is in jp_core_validation.json){first}"
        )
        validation_msgs.append(errors[-1])
    held = bool(errors)
    omop_load = None
    fhir_loaded = fhir_deleted = 0
    lake_result: RebuildResult | None = None
    lake_busy = False
    publish_steps: dict[str, str] | None = None
    if held:
        errors.append("night held: fhir-store and the lake were not loaded; CURRENT still names the previous snapshot")
    else:
        # T-723 (D-489): the night passed the gate. One resumable function publishes it: pid map, OMOP, the FHIR
        # store, the lake (promote last). A step that fails stops it there; a re-run of the served night touches
        # nothing while a job holds the snapshot
        from adapter.publish import RECORD, publish_night

        def on_step(step: str, steps: dict[str, str]) -> None:
            at["step"] = f"publish:{step}"
            _note(cfg, at.get("batch"), step=at["step"], publish=steps)

        if prior_record is not None:  # the same night run again: the steps done for the same content are kept
            (out_dir / RECORD).write_text(prior_record, encoding="utf-8")
        pub = publish_night(
            cfg, snap, out_dir, last_good=last_good, load_fhir=load_fhir, rebuild_lake=rebuild_lake, on_step=on_step
        )
        out_dir, publish_steps = pub.out_dir, dict(pub.steps)
        errors += pub.errors
        held, lake_busy = pub.held, pub.lake_busy
        omop_load, fhir_loaded, fhir_deleted, lake_result = pub.omop, pub.fhir_loaded, pub.fhir_deleted, pub.lake
    at["step"] = "report"
    passed = not errors
    report = IngestReport(
        snapshot=date.fromisoformat(snap),
        source=source_kind,
        since=since,
        started_at=started,
        finished_at=datetime.now(zone),
        counts=counts if not since else full_counts,
        missing_required=dict(missing),
        validation=vsum,
        profile_validation=psum,
        fhir_loaded=fhir_loaded,
        fhir_deleted=fhir_deleted,
        lake=lake_result,
        passed=passed,
        errors=errors,
        tombstoned=tombstoned,
        held=held,
        omop=omop_load,
        fhir_unread=night.unread.result(),  # T-616: the inbound contract, what each resource carries unread
    )
    body = json.dumps(dump(report), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    (out_dir / "ingest_report.json").write_bytes(body)
    if held:  # T-611: the folder says so itself, for the steward and for any later publish
        (out_dir / HELD).write_text(json.dumps({"snapshot": snap, "errors": errors}) + "\n", encoding="utf-8")
    else:
        (out_dir / HELD).unlink(missing_ok=True)
    pruned = prune_snapshots(cfg, date.fromisoformat(snap)) if passed and rebuild_lake else []
    # T-659b (D-370): one gate record per night, the lineage and the contract checks beside the report
    sorted_out = {*completeness_msgs, *validation_msgs, *(e for e in errors if e.startswith("data contracts: "))}
    sorted_out |= {e for e in errors if e.startswith("night held: ")}
    sorted_out |= {f"{t}: {w}" for t, w in quarantined.items()}
    gate_facts.file_quarantine = quarantined
    gate_facts.completeness, gate_facts.validation, gate_facts.overrides = completeness_msgs, validation_msgs, overrides
    gate_facts.other = [e for e in errors if e not in sorted_out]
    gate_facts.current_after = _current(cfg.lake_dir)
    gate = governance.gate_record(gate_facts, datetime.now(zone))
    governance.write_gate(gate, out_dir, cfg.lake_dir)
    mapping_file = cfg.mapping_path if source_kind != "fhir_bulk" else None
    lineage_doc = governance.lineage(snap, source_kind, inputs, mapping_file, out_dir, gate)
    (out_dir / governance.LINEAGE).write_text(
        json.dumps(lineage_doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    if crep is not None:
        (out_dir / governance.CONTRACT_REPORT).write_text(
            json.dumps(crep.model_dump(mode="json"), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if cfg.audit_dir:
        night_event(
            cfg,
            "ingest.done" if passed else "ingest.held" if held else "ingest.failed",
            snapshot=snap,
            source=source_kind,
            passed=passed,
            held=held,
            started_at=started.isoformat(),
            batch=at.get("batch"),
            output_sha=sha256_bytes(body),
            actor="adapter",
            detail={
                "source": source_kind,
                "counts": counts,
                "validation_error_pct": vsum.error_pct,
                "jp_core": {"sampled": psum.sampled, "failed": psum.errors} if psum is not None else None,
                "snapshots_pruned": pruned,
                "tombstoned": tombstoned,
                "held": held,
                "lake_busy": lake_busy or None,  # D-462: run again once the lake is free
                "publish": publish_steps,  # T-723: each publish step's state (None: the night was held at the gate)
                "unit_defaults_applied": defaulted,
                "presence_words_read": presence_read,
                "instants_to_site_offset": shifted,
                "drop_override": "; ".join(overrides) or None,
                # T-611: what the readiness page shows for a held night (tables only, never a row)
                "incomplete": completeness["problems"] or None,
                "duplicate_keys": {t: v["duplicate_keys"] for t, v in tables.items() if v["duplicate_keys"]} or None,
                "orphans": completeness["orphans"] or None,
                # NEW-DIN-6 (D-580): rows dropped for a code no look-up knows, per table (the codes: the file)
                "unmapped": {t: sum(sum(c.values()) for c in by.values()) for t, by in sorted(unmapped_codes.items())}
                or None,
                # T-615b: the tables whose file was set aside (character set or CSV form; no cell text)
                "quarantined": quarantined or None,
                # T-659b: the night's one gate record, rows set aside by the contracts, merged chart numbers
                "gate": {
                    "gate_id": gate.gate_id,
                    "outcome": gate.outcome,
                    "reasons": [r.value for r in gate.blocking_reasons],
                },
                "rows_quarantined": (
                    {t.table: t.quarantine_by_reason for t in crep.tables if t.quarantined} or None
                    if crep is not None
                    else None
                ),
                "aliased": aliased or None,
                # T-106: the dual write into OMOP and the foreign-key checks after it (None: the flag is off)
                "omop": (
                    {
                        k: v
                        for k, v in dump(omop_load).items()
                        if k in ("state", "seconds", "counts", "relational_failed")
                    }
                    if omop_load is not None
                    else None
                ),
            },
        )
    log.info("ingest finished", extra={"snapshot": snap, "passed": passed, "resources": sum(counts.values())})
    return report


_REFERENCE = re.compile(r"^Patient/(.+)$")


def _ops(cfg: AdapterConfig) -> Any:
    from datacore.dataops import DataOps

    return DataOps(cfg.db_url or os.environ.get(DB_URL_ENV))


def _open_night(cfg: AdapterConfig, source: str, snapshot: str, started_at: str) -> str | None:
    """T-723 (D-489): the night's ``dataops.batch`` row, opened when the run starts (``LANDED``); the id as text, or
    None when there is no audit folder or the trial database cannot be reached (the night goes on, and its end
    writes the event without a row, as before)."""
    if not cfg.audit_dir:
        return None
    try:
        ops = _ops(cfg)
    except Exception as exc:
        log.error("the night's batch row was not opened", extra={"error": type(exc).__name__})
        return None
    try:
        row = ops.open_night(open_audit(cfg.audit_dir, cfg.tz), source=source, snapshot=snapshot, by="adapter",
                             at=started_at)  # fmt: skip
        return str(row.id)
    except Exception as exc:
        log.error("the night's batch row was not opened", extra={"error": type(exc).__name__})
        return None
    finally:
        ops.close()


def _note(cfg: AdapterConfig, batch: str | None, **detail: Any) -> None:
    """Write where the running night is into its row's detail (the step, the publish steps); never fails the run."""
    if not batch:
        return
    try:
        ops = _ops(cfg)
        try:
            ops.note(int(batch), **detail)
        finally:
            ops.close()
    except Exception as exc:
        log.warning("the night's batch row was not updated", extra={"error": type(exc).__name__})


def _held_nights(cfg: AdapterConfig) -> set[str] | None:
    """The nights a steward has still to decide (``HELD`` rows), or None when the store cannot be read."""
    try:
        ops = _ops(cfg)
        try:
            return {b.snapshot for b in ops.held()}
        finally:
            ops.close()
    except Exception:
        return None


def night_event(cfg: AdapterConfig, event: str, *, snapshot: str, source: str, passed: bool, held: bool,
                started_at: str = "", batch: str | None = None, **fields: Any) -> None:  # fmt: skip
    """The night's audit event and its ``dataops.batch`` row, in one transaction (T-112a, D-427): the one adapter
    hook of the data-operations schema. A trial database that cannot be reached does not hide the night's event: it
    is written without a row, says so (``detail.batch`` is ``None``) and the log names the error."""
    from datacore.dataops import DataOps

    audit = open_audit(cfg.audit_dir, cfg.tz)
    at = datetime.now(ZoneInfo(cfg.tz)).isoformat()
    try:
        ops = DataOps(cfg.db_url or os.environ.get(DB_URL_ENV))
    except Exception as exc:  # the store's own failure must not hide the night's event
        log.error("the night's batch row was not written", extra={"error": type(exc).__name__})
        fields["detail"] = {**(fields.get("detail") or {}), "batch": None}
        audit.append(event, snapshot=snapshot, **fields)
        return
    try:
        ops.record_night(audit, event, source=source, snapshot=snapshot, passed=passed, held=held, by="adapter",
                         at=at, started_at=started_at, batch_id=int(batch) if batch else None, **fields)  # fmt: skip
    finally:
        ops.close()


def apply_aliases(by_type: dict[str, list[Resource]], aliases: dict[str, str]) -> int:
    """T-659b (D-370): write a merged chart number's records under the surviving pid (``pidmap.pid_alias``). A Patient
    whose pid was merged takes the surviving pid, or is dropped when the surviving patient is in the feed too; every
    reference ``Patient/<old>`` becomes ``Patient/<surviving>``. Nothing stored is re-keyed. Returns the patients
    moved."""
    if not aliases:
        return 0
    one = _Aliases(aliases, [str(p.get("id")) for p in by_type.get("Patient", [])])
    if "Patient" in by_type:
        by_type["Patient"] = [p for p in by_type["Patient"] if one(p)]
    for rtype, items in by_type.items():
        if rtype != "Patient":
            for r in items:
                one(r)
    return one.moved


class _Aliases:
    """:func:`apply_aliases` one resource at a time, in the order the night sent them (T-692). ``patient_ids`` are the
    ids of every Patient of the night, in that order; ``__call__`` returns False for a Patient to leave out."""

    def __init__(self, aliases: dict[str, str], patient_ids: list[str]) -> None:
        self.aliases = aliases
        self.present = set(patient_ids) if aliases else set()
        self.moved = 0
        self.dropped = 0
        if aliases:  # how many Patients will be left out, known before the first is written (the sample's size)
            seen = set(patient_ids)
            for pid in patient_ids:
                new = aliases.get(pid)
                if new is not None:
                    if new in seen:
                        self.dropped += 1
                    else:
                        seen.add(new)

    def __call__(self, r: Resource) -> bool:
        if not self.aliases:
            return True
        if r.get("resourceType") != "Patient":
            self._walk(r)
            return True
        new = self.aliases.get(str(r.get("id")))
        if new is None:
            return True
        self.moved += 1
        if new in self.present:
            return False
        r["id"] = new
        for ident in r.get("identifier") or []:
            if isinstance(ident, dict) and str(ident.get("value")) in self.aliases:
                ident["value"] = new
        self.present.add(new)
        return True

    def _walk(self, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if (
                    k == "reference"
                    and isinstance(v, str)
                    and (m := _REFERENCE.match(v))
                    and m.group(1) in self.aliases
                ):
                    node[k] = f"Patient/{self.aliases[m.group(1)]}"
                else:
                    self._walk(v)
        elif isinstance(node, list):
            for x in node:
                self._walk(x)


class _NightPass:
    """T-692 (D-473): what the night did to each resource and counted over all of them, done once per resource as
    :func:`adapter.ndjson.write_snapshot` reads the spool back, in the order it was sent: the site's unit defaults
    (D-149), the presence words of a FHIR feed (D-418), the site's offset (T-619a), the missing-element counts and
    undated orders (D-275), the merged chart numbers (T-659b), the validation and JP Core samples and the unread
    elements (T-616). The same results as the passes over the whole night in memory it replaces."""

    def __init__(
        self,
        zone: Any,
        unit_defaults: dict[str, str],
        presence: bool,
        aliases: _Aliases,
        counts: dict[str, int],
        fraction: float | None,
        per_type: int | None,
    ) -> None:
        from lake.flatten import Unread  # the inbound FHIR contract (T-616), the lake's own reading

        self.zone, self.unit_defaults, self.presence, self.aliases = zone, unit_defaults, presence, aliases
        self.defaulted = self.presence_read = self.shifted = self.undated = 0
        self.missing: Counter[str] = Counter()
        self.unread = Unread()
        kept = {**counts, "Patient": counts.get("Patient", 0) - aliases.dropped}
        self.sample = (
            Sampler("trialbox", lambda t: max(3, round(kept.get(t, 0) * fraction))) if fraction is not None else None
        )
        self.jp_sample = Sampler("jp-core", lambda _t: per_type) if per_type is not None else None

    def __call__(self, r: Resource) -> bool:
        rtype = r["resourceType"]
        if rtype == "Observation":
            self.defaulted += apply_unit_defaults([r], self.unit_defaults)
            if self.presence:
                self.presence_read += apply_presence_words([r])
        self.shifted += to_site_offset((r,), self.zone)
        if rtype == "MedicationRequest" and _undated_order(r):
            self.undated += 1
        for p in missing_required(r):
            self.missing[f"{rtype}.{p}"] += 1
        if not self.aliases(r):
            return False
        if self.sample is not None:
            self.sample.add(r)
        if self.jp_sample is not None:
            self.jp_sample.add(r)
        self.unread.add(r)
        return True

    def missing_counts(self) -> Counter[str]:
        out: Counter[str] = Counter()
        if self.undated:
            out["MedicationRequest.authoredOn (no date at all: kept, read as unknown)"] = self.undated
        out.update(self.missing)
        return out


def jp_core_check(cfg: AdapterConfig, picked: list[Resource], out_dir: Path) -> ValidationSummary:
    """D-137: check the ``profile_sample_per_type`` resources of each type the night picked (``sample_per_type``, taken
    as the night is written: T-692) against JP Core; write every outcome to ``jp_core_validation.json`` beside the
    snapshot; return the summary for the ingest report. Nothing is dropped."""
    from adapter import licensed
    from adapter.validate.jpcore import JpCoreValidator

    rep = JpCoreValidator(licensed.tables(cfg.db_url)).validate(picked)
    (out_dir / "jp_core_validation.json").write_text(
        json.dumps(rep.as_json(), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    if rep.errors:
        log.warning("JP Core: %s of %s sampled resources fail", rep.errors, rep.sampled)
    return ValidationSummary(
        sampled=rep.sampled,
        errors=rep.errors,
        error_pct=round(rep.error_pct, 3),
        validator=rep.validator,
        messages=rep.messages(),
    )


PASSED = "passed.json"  # written in a snapshot's NDJSON folder when its night passed (D-271)
HELD = "held.json"  # written in a snapshot's NDJSON folder when its night was held, with why (T-611)


def reject_key(exc: BaseException) -> str:
    """The key a rejected row is counted under (STD-025; D-520): the exception's type and its message **up to the
    first value**, never a feed value. The message is cut at its first quote mark (the mapper writes a value with
    ``repr``; everything from there on is ``<value>``, so a value that holds quote marks of both kinds cannot end
    the cut early and leave a fragment), and a run of digits before it is ``<n>`` (a number written without quote
    marks). The key goes into ``completeness.json``, the night's error, the audit and the log."""
    text = str(exc)
    head = re.split("['\"\u2018\u2019\u201c\u201d`]", text, maxsplit=1)[0]
    cut = len(head) < len(text)
    head = re.sub(r"[0-9]+(?:[.,:/-][0-9]+)*", "<n>", head).strip()
    said = f"{head} <value>".strip() if cut else head
    return f"{type(exc).__name__}: {said}" if said else type(exc).__name__


REJECT_MAX_PCT = 1.0  # STD-025: a table whose rejected rows pass this share of its rows holds the night (T-615a)
UNMAPPED_CODES = "unmapped_codes.json"  # NEW-DIN-6 (D-580): every code no look-up knows, with its row count
COMPLETENESS = "completeness.json"  # per source table: present, rows, duplicate keys; the gate's findings (T-611)
_PATIENT_REF = re.compile(rb'"Patient/([^"]+)"')


def _patient_ids(directory: Path) -> set[str]:
    out: set[str] = set()
    path = directory / "Patient.ndjson"
    if path.is_file():
        with path.open("rb") as fh:
            for line in fh:
                if line.strip():
                    out.add(str(json.loads(line)["id"]))
    return out


def _referenced_patients(directory: Path) -> Counter[str]:
    """Records per referenced patient id, over every type but Patient (a regex on the raw line: no JSON parse)."""
    refs: Counter[str] = Counter()
    for f in directory.glob("*.ndjson"):
        if f.stem == "Patient":
            continue
        with f.open("rb") as fh:
            for line in fh:
                for pid in set(_PATIENT_REF.findall(line)):
                    refs[pid.decode("utf-8", "replace")] += 1
    return refs


def completeness_check(
    cfg: AdapterConfig, tables: dict[str, dict[str, Any]], out_dir: Path, last_good: str | None, *, full: bool
) -> tuple[list[str], dict[str, Any]]:
    """T-611 (DATA-001, DATA-009, DATA-017): the night's source tables against the last good night's.

    Holds (returned as problems): a required table missing or empty; a table the last good night had rows of that is
    missing now, or (full night) has no rows; a full night's table with more than ``table_max_drop_pct`` % fewer rows
    than the last good night (above ``feedguard.FLOOR`` rows); a patient of the last good night who left the feed
    while records of theirs stayed (orphans: the legacy lake would keep them with no patient row). Counted only:
    duplicate source keys per table, and records that point at a patient the snapshot does not hold."""
    base: dict[str, Any] = {}
    if last_good is not None:
        try:
            base = json.loads((snapshot_dir(cfg.lake_dir, last_good) / COMPLETENESS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            base = {}  # a folder from before the gate: only the resource-type guard (D-271) compares it
    # rows per table of the last full night (a delta night carries its base's forward: its own rows are a delta)
    before: dict[str, int] = {str(k): int(v) for k, v in (base.get("reference") or {}).items()}
    problems: list[str] = []
    optional = set(cfg.optional_tables)
    # NEW-DIN-8 (D-583): a table no earlier good night had rows of has no baseline to be compared with: the first
    # night, the first night after a first load (the back-fill writes no completeness record), a table an override
    # once let through empty. So on a full night such a table must be there with live rows, unless the site lists
    # it as optional; else a table missing on go-live night would never be asked for again.
    for t in sorted(set(tables) | set(cfg.required_tables)):
        now = tables.get(t)
        rows = int(now["rows"]) if now else 0
        present = now["present"] if now else None
        if t in cfg.required_tables and (present is False or (full and rows == 0) or now is None):
            problems.append(f"{t}: required table {'missing' if present is False or now is None else 'empty'}")
            continue
        live = int(now.get("rows_live", rows)) if now else 0
        if (cfg.first_night_all_tables and full and not before.get(t) and t not in optional and now is not None
                and not now.get("set_aside") and (present is False or live == 0)):  # fmt: skip
            problems.append(
                f"{t}: table {'missing' if present is False else 'empty'} and no earlier good night had it (every "
                "table of the mapping is required until one has; a table this site does not have goes under "
                "feed_completeness.optional_tables)"
            )
            continue
        old = before.get(t, 0)
        if not old or t in optional:
            continue
        if present is False:
            problems.append(f"{t}: table missing (last good night {old} rows)")
        elif full and rows == 0:
            problems.append(f"{t}: table empty (last good night {old} rows)")
        elif full and old - rows > feedguard.FLOOR and (old - rows) * 100 > cfg.table_max_drop_pct * old:
            problems.append(
                f"{t}: {rows} rows, {round(100 * (old - rows) / old, 1):g} % fewer than the last good night's {old} "
                f"(limit {cfg.table_max_drop_pct:g} %)"
            )
    now_ids = _patient_ids(out_dir)
    refs = _referenced_patients(out_dir)
    vanished = (_patient_ids(snapshot_dir(cfg.lake_dir, last_good)) - now_ids) if last_good else set()
    orphans = sum(n for pid, n in refs.items() if pid not in now_ids)
    of_vanished = sum(refs.get(pid, 0) for pid in vanished)
    if of_vanished:
        problems.append(
            f"Patient: {len(vanished)} patients of the last good night left the feed while {of_vanished} of their "
            "records stayed (orphans)"
        )
    report = {
        "full": full,
        "tables": {t: {**v, "rows_before": before.get(t)} for t, v in sorted(tables.items())},
        "reference": {t: int(v["rows"]) for t, v in tables.items()} if full else before,
        "baseline": last_good if before else None,
        "problems": problems,
        "patients_vanished": len(vanished),
        "orphans": orphans,
        "orphans_of_vanished": of_vanished,
    }
    return problems, report


RERUN_DIR = "ndjson-rerun"  # a re-run of a promoted night until it passes (D-271)
# exceptions by which the lake refuses a snapshot (lake.store.RebuildError, omop.schema.OmopError, the HTTP 409)
REFUSALS = ("RebuildError", "OmopError", "RebuildRefused")
#: D-462: the lake could not rebuild now (``lake.store.LakeBusy``: held by a job, or already building), in process or
#: over HTTP (409 with ``X-TB-Lake-Busy``): retried later, never a held night
BUSY = ("LakeBusy", "SnapshotHeld", "SnapshotBuilding")


class RebuildRefused(RuntimeError):
    """The lake service answered 409: it refused the snapshot (the detail says why)."""


def ingest_instant(snap: str, zone: Any) -> str:
    """The night ``snap`` as a FHIR instant (midnight in the source's zone): a row's ``meta.lastUpdated``. The same
    night ingested twice stamps the same instant, so its NDJSON stays byte for byte the same."""
    d = date.fromisoformat(snap[:10])
    return datetime(d.year, d.month, d.day, tzinfo=zone).isoformat()


def _current(lake_dir: Path) -> str | None:
    p = lake_dir / "CURRENT"
    return p.read_text().strip() or None if p.exists() else None


def _type_counts(directory: Path) -> dict[str, int]:
    """Records per resource type of a snapshot folder (lines, without parsing)."""
    out = {}
    for f in directory.glob("*.ndjson"):
        with f.open("rb") as fh:
            out[f.stem] = sum(1 for line in fh if line.strip())
    return out


def merge_base(lake_dir: Path, snap: str) -> str | None:
    """The snapshot a delta night ``snap`` merges over (D-271): the newest earlier one that passed (``passed.json``),
    or the lake's ``CURRENT`` (folders written before the marker existed). Never a held night's NDJSON: only the
    delta's own records are validated, so merging over a held folder would promote the records it was held for."""
    prev = [s for s in list_snapshots(lake_dir) if s < snap]
    good = [s for s in prev if (snapshot_dir(lake_dir, s) / PASSED).exists()]
    cur = _current(lake_dir)
    if cur in prev:
        good.append(str(cur))
    return max(good) if good else None


def _built_not_served(lake_dir: Path, snap: str) -> bool:
    """The night has a publish record (T-723) and its promotion did not end. A folder without a record (a night
    from before T-723, a lake rebuilt by hand) is not judged here."""
    from adapter.publish import ENDED, read_record

    steps = read_record(snapshot_dir(lake_dir, snap)).get("steps") or {}
    return bool(steps) and steps.get("lake") not in ENDED


def prune_snapshots(cfg: AdapterConfig, today: date) -> list[str]:
    """SPEC §10.3: keep the last N nightly snapshots and each month's last snapshot for M months (NDJSON, parquet,
    DuckDB); the current snapshot is always kept, and so is every snapshot a running job holds (T-305b, D-403: a
    long SCREEN, or one waiting for an approval, still reads its night after N newer ones arrived)."""
    import shutil

    from lake.store import SnapshotBuilding, building, drop_reader_links, held_snapshots, lake_lock
    from tb_common.retention import snapshots_to_keep

    current = (cfg.lake_dir / "CURRENT").read_text().strip() if (cfg.lake_dir / "CURRENT").exists() else None
    snaps = set(list_snapshots(cfg.lake_dir)) | {p.stem for p in (cfg.lake_dir / "db").glob("*.duckdb")}
    # T-611: only nights that passed count towards the N kept (a held night has no passed.json and no DuckDB; a
    # folder from before the marker that was promoted has its DuckDB)
    good = {s for s in snaps if (snapshot_dir(cfg.lake_dir, s) / PASSED).exists()}
    # T-723 second review (L3): the lake now builds a night before it serves it. A built night whose publish record
    # says the promotion did not end was never served: it is not a good night and takes no place among the N kept
    good |= {p.stem for p in (cfg.lake_dir / "db").glob("*.duckdb") if not _built_not_served(cfg.lake_dir, p.stem)}
    good |= {current} if current else set()
    keep = snapshots_to_keep(snaps, today, cfg.keep_nightly, cfg.keep_month_end_months, good) | {current or ""}
    gone: list[str] = []
    with lake_lock(cfg.lake_dir):  # D-462: no hold lands between reading the holds and the deletes
        keep |= set(held_snapshots(cfg.lake_dir).values())
        for s in sorted(s for s in snaps if s not in keep):
            try:
                # D-462: a snapshot that is being rebuilt is left alone (the build would bring it back at its swap)
                with building(cfg.lake_dir, s):
                    shutil.rmtree(cfg.lake_dir / "ndjson" / s, ignore_errors=True)
                    shutil.rmtree(cfg.lake_dir / "parquet" / f"snapshot={s}", ignore_errors=True)
                    for f in (cfg.lake_dir / "db").glob(f"{s}.duckdb*"):
                        f.unlink(missing_ok=True)
                    drop_reader_links(cfg.lake_dir, s)
            except SnapshotBuilding:
                log.info("lake snapshot %s is being rebuilt: not pruned this time", s)
                continue
            gone.append(s)
    return gone
