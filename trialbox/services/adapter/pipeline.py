"""Nightly ingest pipeline (SPEC §4.6): extract -> map -> NDJSON -> fhir-store + lake -> validate sample -> report."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common.audit import AuditLog
from tb_common.crypto import load_or_create_key, pid_for_mrn, sha256_bytes
from tb_contracts import IngestReport, RebuildResult, ValidationSummary, dump

from adapter.load_fhir import sync_snapshot
from adapter.mapping.engine import Mapper, Mapping, resource_id
from adapter.ndjson import list_snapshots, snapshot_dir, write_snapshot
from adapter.pidmap import PidMap
from adapter.sources.base import Source
from adapter.validate.validator import Hl7Validator, StructuralValidator, missing_required, sample

log = logging.getLogger("adapter")
Resource = dict[str, Any]


@dataclass
class AdapterConfig:
    lake_dir: Path
    secrets_dir: Path
    mapping_path: Path
    site_id: str
    tz: str = "Asia/Taipei"
    fhir_base_url: str | None = None
    audit_dir: Path | None = None
    validation_max_pct: float = 0.5
    sample_fraction: float = 0.01
    rebuild: Callable[[str, Path], RebuildResult] | None = None
    # settings.registry_source: None = the data source's own ``registry`` table; ("none", "") = no registry;
    # ("csv", "/path/registry.csv") or ("sql", dsn) = a separate consent registry
    registry: tuple[str, str] | None = None
    keep_nightly: int = 3  # settings.retention.nightly_snapshots
    keep_month_end_months: int = 36  # settings.retention.month_end_snapshots_months
    db_url: str | None = None  # the trial database of the pid map (TB_DB_URL when None)
    profile_sample_per_type: int = 50  # D-137: resources per type checked against the mapping's profiles (JP Core)

    def site_key(self) -> bytes:
        return load_or_create_key(self.secrets_dir / "site_hmac.key")

    def pidmap(self) -> PidMap:
        return PidMap(self.secrets_dir / "pid_map.key", self.db_url)


def make_source(kind: str, path: str, db_url: str | None = None) -> Source:
    if kind == "csv":
        from adapter.sources.csv.source import CsvSource

        return CsvSource(Path(path))
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


def pseudonymise_bulk(resources: Iterator[Resource], key: bytes) -> Iterator[Resource]:
    """For ``fhir_bulk``: replace ids/references by pseudonyms and drop direct identifiers."""

    def new_id(rtype: str, rid: str) -> str:
        return pid_for_mrn(key, rid) if rtype == "Patient" else resource_id(key, rtype, rid)

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
        if r["resourceType"] != "Practitioner":
            r["id"] = new_id(r["resourceType"], r["id"])
        yield r


def _undated_order(r: dict[str, Any]) -> bool:
    period = (r.get("dispenseRequest") or {}).get("validityPeriod") or {}
    return not r.get("authoredOn") and not period.get("start")


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
    zone = ZoneInfo(cfg.tz)
    started = datetime.now(zone)
    snap = snapshot or started.date().isoformat()
    key = cfg.site_key()
    errors: list[str] = []
    by_type: dict[str, list[Resource]] = {}
    patient_pairs: list[tuple[str, str]] = []
    identities: list[tuple[str, dict[str, str]]] = []
    fhir_profiles = ""
    source: Source | None = None
    if source_kind == "fhir_bulk":
        from adapter.sources.fhir_bulk.source import FhirBulkSource

        for r in pseudonymise_bulk(FhirBulkSource(Path(source_path)).resources(), key):
            by_type.setdefault(r["resourceType"], []).append(r)
    else:
        mapping = Mapping.load(cfg.mapping_path)
        mapper = Mapper(mapping, key, cfg.site_id)
        fhir_profiles = mapping.fhir_profiles
        source = make_source(source_kind, source_path, cfg.db_url)
        for res in mapper.static_resources():
            by_type.setdefault(res["resourceType"], []).append(res)
        for table, tspec in mapping.tables.items():
            src, src_name = source, tspec["source"]
            if table == "registry" and cfg.registry is not None:
                kind, where = cfg.registry
                if kind == "none" or not where:
                    continue
                if kind == "csv":
                    src, src_name = make_source("csv", str(Path(where).parent)), Path(where).stem
                else:
                    src = make_source("cgrd_sql", where)
            delta = mapping.source_column(table, tspec.get("delta"))
            rows = [mapping.normalize(table, r) for r in src.rows(table, src_name, delta, since)]
            if table == "patient":
                patient_pairs = [(pid_for_mrn(key, str(r[tspec["key"]])), str(r[tspec["key"]])) for r in rows]
                ident = tspec.get("identity") or {}
                if ident:  # e.g. {name: name, national_id: id_no}: kept encrypted in the pid map only
                    identities = [
                        (pid, {k: str(r.get(col) or "") for k, col in ident.items()})
                        for (pid, _), r in zip(patient_pairs, rows, strict=True)
                    ]
            try:
                for res in mapper.map_table(table, iter(rows)):
                    by_type.setdefault(res["resourceType"], []).append(res)
            except ValueError as exc:
                errors.append(f"{table}: {exc}")
    undated = [r for r in by_type.get("MedicationRequest", []) if _undated_order(r)]
    if undated:  # no authoredOn and no validity start: CQL Max/Min and SQL greatest/least would treat it as exposure
        by_type["MedicationRequest"] = [r for r in by_type["MedicationRequest"] if not _undated_order(r)]
    counts = {t: len(v) for t, v in sorted(by_type.items())}
    missing: Counter[str] = Counter()
    if undated:
        missing["MedicationRequest.authoredOn (no date at all: dropped)"] = len(undated)
    for rtype, items in by_type.items():
        for r in items:
            for p in missing_required(r):
                missing[f"{rtype}.{p}"] += 1
    if patient_pairs:
        pm = cfg.pidmap()
        pm.upsert_many(patient_pairs)
        if identities:
            pm.upsert_identity(identities)
        pm.close()
    # NDJSON snapshot (delta runs merge over the previous snapshot)
    out_dir = snapshot_dir(cfg.lake_dir, snap)
    prev = [s for s in list_snapshots(cfg.lake_dir) if s < snap]
    base = snapshot_dir(cfg.lake_dir, prev[-1]) if (since and prev) else None
    full_counts = write_snapshot(out_dir, by_type, base)
    fhir_loaded = fhir_deleted = 0
    if load_fhir and cfg.fhir_base_url:
        try:
            older = [s for s in list_snapshots(cfg.lake_dir) if s < snap]
            fhir_loaded, fhir_deleted = sync_snapshot(
                cfg.fhir_base_url,
                out_dir,
                cfg.lake_dir / "fhir_ledger",
                snapshot_dir(cfg.lake_dir, older[-1]) if older else None,
            )
        except Exception as exc:
            errors.append(f"fhir-store load failed: {exc}")
    lake_result: RebuildResult | None = None
    if rebuild_lake and cfg.rebuild is not None:
        try:
            lake_result = cfg.rebuild(snap, out_dir)
        except Exception as exc:
            errors.append(f"lake rebuild failed: {exc}")
    vsum = ValidationSummary(sampled=0, errors=0, error_pct=0.0, validator="skipped", messages=[])
    if validate:
        chosen = validator or Hl7Validator.from_env() or StructuralValidator()
        picked = sample((r for items in by_type.values() for r in items), cfg.sample_fraction)
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
            psum = jp_core_check(cfg, by_type, out_dir)
        except Exception as exc:
            errors.append(f"JP Core validation failed to run: {exc}")
    if source is not None and hasattr(source, "stats"):
        from adapter.sources.ssmix2.source import reader_summary

        (out_dir / "reader.json").write_text(
            json.dumps(reader_summary(source), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
    passed = not errors and vsum.error_pct <= cfg.validation_max_pct
    if vsum.error_pct > cfg.validation_max_pct:
        errors.append(f"validation error rate {vsum.error_pct:.2f}% exceeds {cfg.validation_max_pct}%")
    if psum is not None and psum.error_pct > cfg.validation_max_pct:
        passed = False
        first = f": {psum.messages[0]}" if psum.messages else ""
        errors.append(
            f"JP Core: {psum.errors} of {psum.sampled} sampled resources fail ({psum.error_pct:.2f}%, over "
            f"{cfg.validation_max_pct}%; every failure is in jp_core_validation.json){first}"
        )
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
    )
    body = json.dumps(dump(report), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    (out_dir / "ingest_report.json").write_bytes(body)
    pruned = prune_snapshots(cfg, date.fromisoformat(snap)) if passed and rebuild_lake else []
    if cfg.audit_dir:
        AuditLog(cfg.audit_dir, cfg.tz).append(
            "ingest.done" if passed else "ingest.failed",
            snapshot=snap,
            output_sha=sha256_bytes(body),
            actor="adapter",
            detail={
                "source": source_kind,
                "counts": counts,
                "validation_error_pct": vsum.error_pct,
                "jp_core": {"sampled": psum.sampled, "failed": psum.errors} if psum is not None else None,
                "snapshots_pruned": pruned,
            },
        )
    log.info("ingest finished", extra={"snapshot": snap, "passed": passed, "resources": sum(counts.values())})
    return report


def jp_core_check(cfg: AdapterConfig, by_type: dict[str, list[Resource]], out_dir: Path) -> ValidationSummary:
    """D-137: check ``profile_sample_per_type`` resources of each type against JP Core; write every outcome to
    ``jp_core_validation.json`` beside the snapshot; return the summary for the ingest report. Nothing is dropped."""
    from adapter import licensed
    from adapter.validate.jpcore import JpCoreValidator, sample_per_type

    picked = sample_per_type((r for items in by_type.values() for r in items), cfg.profile_sample_per_type)
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


def prune_snapshots(cfg: AdapterConfig, today: date) -> list[str]:
    """SPEC §10.3: keep the last N nightly snapshots and each month's last snapshot for M months (NDJSON, parquet,
    DuckDB); the current snapshot is always kept."""
    import shutil

    from tb_common.retention import snapshots_to_keep

    current = (cfg.lake_dir / "CURRENT").read_text().strip() if (cfg.lake_dir / "CURRENT").exists() else None
    snaps = set(list_snapshots(cfg.lake_dir)) | {p.stem for p in (cfg.lake_dir / "db").glob("*.duckdb")}
    keep = snapshots_to_keep(snaps, today, cfg.keep_nightly, cfg.keep_month_end_months) | {current or ""}
    gone = sorted(s for s in snaps if s not in keep)
    for s in gone:
        shutil.rmtree(cfg.lake_dir / "ndjson" / s, ignore_errors=True)
        shutil.rmtree(cfg.lake_dir / "parquet" / f"snapshot={s}", ignore_errors=True)
        for f in (cfg.lake_dir / "db").glob(f"{s}.duckdb*"):
            f.unlink(missing_ok=True)
    return gone
