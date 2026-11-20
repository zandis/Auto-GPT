"""Nightly ingest pipeline (SPEC §4.6): extract -> map -> NDJSON -> fhir-store + lake -> validate sample -> report."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import stat
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import chartno, feedguard, id_rule, labvalue, refdata
from tb_common.audit_writer import open_audit
from tb_common.crypto import SITE_KEY_FILE, KeyMissingError, key_fingerprint, load_key, pid_for_mrn, sha256_bytes
from tb_common.db import ENV as DB_URL_ENV
from tb_common.id_rule import IdRuleError
from tb_common.site_profile import Profile as SiteProfile
from tb_common.site_profile import ProfileError
from tb_common.unmapped import KINDS
from tb_contracts import ConnectorReport, IngestReport, RebuildResult, ValidationSummary, dump
from tb_contracts.landing import Severity

from adapter import governance
from adapter.instants import to_site_offset
from adapter.mapping.engine import Mapper, Mapping, pivot_rows, resource_id
from adapter.ndjson import (
    Spool,
    absent_links,
    alias_patient,
    alias_references,
    is_deleted_flag,
    list_snapshots,
    read_type,
    snapshot_dir,
    tombstone_count,
    write_snapshot,
)
from adapter.pidmap import PidMap
from adapter.sources.base import CHANGE_COLUMNS, Row, Source, has_table, quarantine_reason
from adapter.validate.validator import (
    Hl7Validator,
    Sampler,
    StructuralValidator,
    capped_types,
    missing_required,
    sample_cap,
    sample_size,
)

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
    # called as promote(night) or promote(night, generation) (D-531): a callable of either shape, so not typed
    # more closely than this
    promote: Callable[..., bool] | None = None
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
    # 10B-6 (D-1233): the site profile's folder (adapter.site_profile.find; None: no profile, the night reads as it
    # did before profiles). Its code tables replace the mapping's look-ups and the SS-MIX2 reader's tables it names
    site_profile: Path | None = None
    # 10B-6: settings.profiles (tw_core, twpas_version): a profile's standard versions must agree with them
    profile_standards: dict[str, str] = field(default_factory=dict)

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


def check_id_rule(cfg: AdapterConfig) -> None:
    """D-1253: refuse the night, before anything is read or written, when the lake or a store this role reads holds
    lake ids of an earlier rule (:mod:`tb_common.id_rule`): the lake's snapshots, the OMOP store of record and the
    derived store. :class:`tb_common.id_rule.IdRuleError` names what holds old ids.

    Review round 3: the adapter's role is meant to read the OMOP and the derived store, so a rule it cannot read
    there ("not readable": no privilege, or the probe failed) refuses the night as an old rule does. The stores the
    adapter's role is not meant to read (D-378: vec, the patient twin, the candidate pool, the EDC drafts) are never
    probed here: for them "not readable" is expected, and each refuses at its own first write
    (:func:`tb_common.id_rule.ensure`)."""
    from tb_common import id_rule

    old: list[str] = []
    newer: list[str] = []
    snaps = id_rule.old_snapshots(cfg.lake_dir / "ndjson")
    rules = {s: id_rule.snapshot_rule(cfg.lake_dir / "ndjson" / s) for s in snaps}
    ahead = [s for s in snaps if rules[s] > id_rule.RULE]
    unreadable = [f"the lake snapshot {s}" for s in snaps if rules[s] == 0]  # one instruction (D-1253 deep review)
    behind = [s for s in snaps if s not in ahead and rules[s] != 0]
    if behind:
        old.append(f"the lake ({len(behind)} snapshots, the last {behind[-1]})")
    if ahead:
        newer.append(f"the lake ({len(ahead)} snapshots, the last {ahead[-1]})")
    url = cfg.db_url or os.environ.get(DB_URL_ENV)
    omop_url = os.environ.get("TB_OMOP_DB_URL") or url
    if url or omop_url:
        from omop.schema import schema_for

        checks = [(omop_url, id_rule.OMOP, schema_for(cfg.lake_dir)), (url, id_rule.DERIVED, None)]
        for where, store, schema in checks:
            if not where:
                continue
            try:
                state = id_rule.probe(where, store, schema)
            except Exception as exc:  # D-1253 review G5: a rule that cannot be read refuses the night
                log.error("id rule of %s not read (%s)", store.name, type(exc).__name__)
                raise id_rule.IdRuleError(
                    [f"the {store.name} store (its id rule could not be read: {type(exc).__name__})"]
                ) from exc
            if state == id_rule.UNREAD:  # a store this role reads, whose rule it cannot read: never let through
                log.error("id rule of %s not readable by this role", store.name)
                old.append(f"the {store.name} store (its id rule is not readable by this role)")
            elif state == id_rule.OLD:
                old.append(f"the {store.name} store")
            elif state == id_rule.NEWER:
                newer.append(f"the {store.name} store")
    if old or newer or unreadable:
        raise id_rule.IdRuleError(old, newer=newer, unreadable=unreadable)


def load_site_profile(cfg: AdapterConfig, source_kind: str) -> tuple[SiteProfile | None, dict[str, Any]]:
    """10B-6 (D-1233): the profile the night reads with and what the night says of it
    (:func:`adapter.site_profile.for_night`): only the version a person loaded (``load --by``) is applied, checked
    again against the box (its site, door, mapping, country and standard versions). A loaded version that fails ends
    the night here."""
    from adapter import site_profile as sp

    folder_or_none = cfg.site_profile
    if folder_or_none is None and not (cfg.lake_dir / sp.RECORD).exists():
        return None, {}
    profile, note = sp.for_night(folder_or_none, cfg.lake_dir, site_id=cfg.site_id, audit_dir=cfg.audit_dir,
                                 tz=cfg.tz)  # fmt: skip
    for k, v in note.items():
        log.warning("site profile: %s: %s", k, v)
    if profile is None:
        return None, note
    from tb_common.derived import country_of

    if profile.site_id != cfg.site_id:
        raise ProfileError("profile.yaml", f"the loaded profile is for site {profile.site_id!r}, not {cfg.site_id!r}")
    if profile.door != source_kind:
        raise ProfileError(
            "profile.yaml", f"the loaded profile describes a {profile.door} source; the box reads {source_kind}"
        )
    if source_kind != "fhir_bulk":
        sp.check_mapping(profile, Mapping.load(cfg.mapping_path))
    sp.check_settings(profile, country=country_of(cfg.tz), standards=cfg.profile_standards)
    return profile, note


def make_source(
    kind: str,
    path: str,
    db_url: str | None = None,
    encoding: str | None = None,
    profile_files: dict[str, Path] | None = None,
) -> Source:
    if kind == "csv":
        from adapter.sources.csv.source import CsvSource

        return CsvSource(Path(path), encoding)
    if kind == "cgrd_sql":
        from adapter.sources.cgrd_sql.source import SqlSource

        return SqlSource(path)
    if kind == "ssmix2":
        from adapter import licensed
        from adapter.sources.ssmix2.source import Ssmix2Source

        # SS-MIX2 standardized and extended storage (D-122, D-137), with the site's licensed code lists; a site
        # profile's tables in place of the shipped samples (10B-6, D-1233)
        def table(use: str) -> Path | None:  # the profile's table as loaded (adapter.site_profile.write_tables)
            return (profile_files or {}).get(use)

        return Ssmix2Source(
            Path(path),
            licensed=licensed.tables(db_url),
            byomei_to_icd10=table("ssmix2.diagnosis"),
            yj_to_atc=table("ssmix2.drug"),
            lab_lookup=table("ssmix2.lab"),
        )
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
    except (SiteKeyError, IdRuleError):  # T-612, D-1253: audited with the reason where refused; one event per night
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
    try:  # D-529: before a row, a folder or a lake build exists for it
        refuse_future_night(snap, started.date())
    except FutureNight as exc:
        log.error("night refused: %s", exc)
        if cfg.audit_dir:  # as a refused site key: the reason is in the audit, not only in the caller's hands
            open_audit(cfg.audit_dir, cfg.tz).append(
                "ingest.failed",
                snapshot=snap,
                actor="adapter",
                detail={"source": source_kind, "refused": "future_night", "reason": str(exc)},
            )
        raise
    try:  # NEW-B-38 (D-679): before anything is read or written, the room for tonight's snapshot
        check_room(cfg, snap)
    except (NoRoomForNight, LakeBudgetError) as exc:
        log.error("night refused: %s", exc)
        if cfg.audit_dir:
            open_audit(cfg.audit_dir, cfg.tz).append(
                "ingest.failed",
                snapshot=snap,
                actor="adapter",
                detail={
                    "source": source_kind,
                    "refused": "disk" if isinstance(exc, NoRoomForNight) else "setting",
                    "reason": str(exc),
                },
            )
        raise
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
    try:  # D-1253: before anything is read or written, no lake id of another rule anywhere it would be added to
        check_id_rule(cfg)
    except IdRuleError as exc:
        log.error("night refused: %s", exc)
        if cfg.audit_dir:  # one event, which closes the night's batch row (opened above) as failed, with the reason
            night_event(cfg, "ingest.failed", snapshot=snap, source=source_kind, passed=False, held=False,
                        batch=at.get("batch"), actor="adapter",
                        detail={"source": source_kind, "refused": "id_rule", "reason": str(exc)})  # fmt: skip
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
    mapper: Mapper | None = None  # None for a fhir_bulk night (10B-6's coverage asks)
    mapping: Mapping | None = None
    tombstones: dict[str, set[str]] = {}  # type -> ids deleted at the source (dataflow review P0-1)
    left_out: dict[str, set[str]] = {}  # D-528: type -> ids a row of a delta night no longer gives
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
    at["step"] = "site profile"
    profile, profile_note = load_site_profile(cfg, source_kind)  # 10B-6 (D-1233)
    profile_files: dict[str, Path] | None = None
    if profile is not None:
        from adapter import site_profile as sp

        # the tables as loaded and checked, never the raw files; scratch on the lake volume, gone with the spool
        profile_files = sp.write_tables(profile, cfg.lake_dir / "tmp" / f"site-profile-{snap}")
        cleanup.callback(shutil.rmtree, cfg.lake_dir / "tmp" / f"site-profile-{snap}", True)
    profile_full = False
    if since:  # a delta night over a night read with another profile (or none) reads whole (10B-6)
        from adapter import site_profile as sp

        over = merge_base(cfg.lake_dir, snap)
        said = sp.night_profile(snapshot_dir(cfg.lake_dir, over)) if over else None
        if (said or {}).get("digest") != (profile.digest if profile is not None else None):
            log.warning("site profile changed since night %s: this night reads whole, not since %s", over, since)
            since, profile_full = None, True
    at["step"] = "read"
    from adapter.read_timing import ReadTimes

    read_times = ReadTimes()  # 10E-9 (review 13-10): the connector's own time per message, for the report
    if source_kind == "fhir_bulk":
        from adapter.sources.fhir_bulk.source import FhirBulkSource

        bulk = FhirBulkSource(Path(source_path))
        inputs += [p for p in Path(source_path).iterdir() if p.is_file()]
        timed = read_times.timed(lambda r: str(r.get("resourceType") or "?"), bulk.resources())
        for r in pseudonymise_bulk(timed, key):
            to_spool(r)
        for rtype, rid in bulk.deleted():
            if rtype != "Patient":  # removing a person is the opt-out path's job, never a feed delta's
                tombstones.setdefault(rtype, set()).add(bulk_id(key, rtype, rid))
    else:
        mapping = Mapping.load(
            cfg.mapping_path,
            {u.split(".", 1)[1]: p for u, p in (profile_files or {}).items() if u.startswith("mapping.")} or None,
        )
        if profile is not None:
            from adapter import site_profile as sp

            sp.mark_unverified(profile, mapping)
        if since:
            at["step"] = "delta check"
            check_delta(mapping, source_kind)
            at["step"] = "read"
        # T-106b (DATA-010): every resource carries its source row, mapping version and the night it was ingested
        # D-593 (lane E's hunk): the mapper may ask the box's reference data (ICD-9-CM to ICD-10-CM, D-592);
        # no pack loaded or no database answers nothing, and nothing is mapped
        check_lookup_factors(mapping)  # D-527: a factor typed wrongly ends the night here, not row by row
        mapper = Mapper(
            mapping, key, cfg.site_id, ingest_instant(snap, mapping.tz),
            concept_map=reference_maps(mapping, cfg.db_url),  # D-665: a map that is not loaded is "not asked"
            mrn_regex=cfg.mrn_regex,  # CGRD-A4 (D-816, lane E's hunk): a masked text uses the site's pattern
        )  # fmt: skip
        fhir_profiles = mapping.fhir_profiles
        mapper.review = id_rule.read_review(cfg.lake_dir)  # D-1253 ruling 1: decided records, marked for review
        if profile is not None:  # 10B-6 (D-1233): a fact from a row still to verify carries D-135's basis tag
            from adapter.site_profile import verify_rules

            mapper.verify_rules = verify_rules(profile)
        source = make_source(source_kind, source_path, cfg.db_url, cfg.source_encoding, profile_files)
        for res in mapper.static_resources():
            to_spool(res)
        whole: set[str] = set()
        if since:
            # NEW-B-18 (D-538): the tables the reference data did not answer for on the night this one merges over
            # are read whole tonight, so the rows that did not change get their codes (D-530 left it to a person)
            from adapter.publish import recover_all

            recover_all(cfg)  # as below, before the lake's folders are read: a killed re-run is put back first
            whole, said_by = reread_whole(cfg.lake_dir, merge_base(cfg.lake_dir, snap))
            whole &= set(mapping.tables)
            # F7 (D-806, lane E's hunk): a visit table a link by day looks up is read whole, every night
            for table in sorted(mapping.read_whole() - whole):
                log.info("%s: read whole on this delta night: rows link to its visits by day (D-806)", table)
            for table in sorted(whole):
                log.info(
                    "%s: read whole on this delta night: the reference data did not answer for it on %s (D-538)",
                    table, said_by,
                )  # fmt: skip
        for table, tspec in mapping.tables.items():
            at["table"] = table
            src, src_name = source, tspec["source"]
            since_t = None if table in whole or table in mapping.read_whole() else since
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
            got = read_times.timed(table, src.rows(table, src_name, delta, since_t))
            if contracts is not None:
                got = _kept(got, raw)
            others = [0]  # CGRD-A2 (D-813, lane E's hunk): rows of a shared source that are another table's

            def own(rows_in: Any, t: str = table, n: list[int] = others) -> Iterator[Row]:
                for r in rows_in:
                    canon = mapping.normalize(t, r)
                    if mapping.keeps(t, canon):
                        yield canon
                    else:
                        n[0] += 1

            stream: Iterator[Row] = own(got)
            pivoted: dict[str, int] = {}  # CGRD-A8 (D-846, lane E's hunk): one item per row turned into columns
            if (pv := tspec.get("pivot")) is not None:
                stream = pivot_rows(stream, pv, str(tspec.get("key") or ""), spool.root / f".pivot-{table}", pivoted)
            rows = _TableRows.write(spool.root / f".rows-{table}", stream)
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
            if others[0]:
                tables[table]["rows_of_other_tables"] = others[0]
            if pivoted:
                tables[table]["pivot"] = dict(sorted(pivoted.items()))
            undated = getattr(src, "change_time_not_a_date", None)  # F14 (D-810, lane E's hunk): counts only
            if since_t and callable(undated) and (n_undated := int(undated(src_name))):
                tables[table]["change_time_not_a_date"] = n_undated
                log.warning("%s: %d rows have a change time that is not a date: read on every night, never windowed "
                            "by it (D-810)", table, n_undated)  # fmt: skip
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
                dead += [mapping.normalize(table, r) for r in deleted_rows(table, src_name, delta, since_t)]
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
                mapped_or_none = map_or_reject(mapper, table, row, rejected)
                if mapped_or_none is None:
                    continue
                mapped = mapped_or_none
                for res in mapped:
                    to_spool(res)
                if since:
                    # NEW-B-7 (D-528): on a delta night the snapshot is the night before with tonight's records
                    # over it. A row the mapping now leaves out (a ``where`` it no longer passes: a booking whose
                    # status became a code the map does not know) wrote nothing and removed nothing, so its
                    # record of the night before stayed as it was. What the row gave before and does not give
                    # tonight is removed, a record an earlier row of this run gave included. Not a tombstone: the
                    # source did not delete it, so it is not in tombstones.json (OMOP says "left the feed")
                    made = {(str(res.get("resourceType")), str(res.get("id"))) for res in mapped}
                    for rtype, rid in made:  # the last row of a key decides (DATA-017): given again, it stays
                        if rtype in left_out:
                            left_out[rtype].discard(rid)
                    for rtype, rid in mapper.tombstones(table, iter([row]), deleted=False):
                        if (rtype, rid) not in made:
                            left_out.setdefault(rtype, set()).add(rid)
            if rejected:
                n_bad = sum(rejected.values())
                tables[table]["rejected"] = dict(sorted(rejected.items()))
                if no_one := sum(n for k, n in rejected.items() if ": no patient (" in k):  # D-1253: counts only
                    tables[table]["rejected_no_patient"] = no_one
                why = "; ".join(f"{k} ({v})" for k, v in sorted(rejected.items()))
                log.warning("%s: %d of %d rows rejected: %s", table, n_bad, len(rows), why)
                if n_bad * 100 > REJECT_MAX_PCT * len(rows):
                    errors.append(f"{table}: {n_bad} of {len(rows)} rows rejected (over {REJECT_MAX_PCT:g} %): {why}")
            rows.discard()
        # NEW-DIN-6 (D-580): rows with a value the mapping could not use, per table (codes and counts only)
        for table, by_lookup in mapper.unmapped_summary().items():
            tables[table]["unmapped"] = by_lookup
        for table, n in mapper.atc_disputed().items():  # CGRD-A2 (D-813, lane E's hunk): counts only
            tables[table]["atc_disputed"] = n
        for table, links in mapper.encounter_links().items():  # F7 (D-806, lane E's hunk): links by day, counts only
            tables[table]["encounter_by_day"] = links
        for table, cols in mapping.read_as_western().items():  # F8 (D-807, lane E's hunk): counts only
            tables[table]["read_as_western"] = cols
        for table, by_element in mapper.implausible_dates().items():  # F9 (D-811, lane E's hunk): counts only
            tables[table]["implausible_dates"] = by_element
        for table, by_map in mapper.mapped_summary().items():  # D-689: rows that gained a mapped code, by map
            tables[table]["mapped"] = by_map
        for table, n in mapper.tombstones_without_patient().items():  # D-1253: counts only
            tables[table]["deletes_without_patient"] = n
            log.warning("%s: %d deleted rows name no patient: they remove nothing", table, n)
        for table, n in sorted(mapper.for_review.items()):  # D-1253 ruling 1: counts only
            tables[table]["steward_review_needed"] = n
            log.warning("%s: %d records a steward decided before the id rebuild await review: not coded", table, n)
        unmapped_codes = mapper.unmapped_by_code(cfg.mrn_regex)  # codes only: never a chart number or a name
    at.update(step="snapshot", table=None)
    unit_defaults = mapping.unit_defaults if mapping is not None else _bulk_unit_defaults(cfg.mapping_path)
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
    if base is not None and source_kind == "ssmix2" and (keyed := id_rule.snapshot_keys(base).get("ssmix2_order")):
        from adapter.sources.ssmix2.source import order_id_form

        if keyed != order_id_form():  # D-1253 ruling 11: never orders of two keys in one snapshot
            errors.append(
                f"delta night over snapshot {last_good}, whose SS-MIX2 orders are keyed {keyed}; the reader keys them "
                f"{order_id_form()}: run the one rebuild ({id_rule.COMMAND}), then a full night"
            )
    if base is not None and (read_from := _source_of(base)) and read_from != source_kind:
        # D-1253 review ruling 7: one record from a mapped feed and from a FHIR bulk export has two ids; a site
        # changes its source only with a full night, never a delta merged over another source's snapshot
        errors.append(
            f"delta night from {source_kind} over snapshot {last_good}, which was read from {read_from}: a site "
            "changes its source only with a full night (run it without since)"
        )
    from adapter.publish import RECORD as PUBLISH_RECORD

    try:  # T-723: the step record of an earlier publish of this folder (kept only for the same content)
        prior_record: str | None = (out_dir / PUBLISH_RECORD).read_text(encoding="utf-8")
    except OSError:
        prior_record = None
    carried: set[str] = set()
    if not patient_pairs:
        # NEW-B-36 (D-677; review DATA-006): the merges are applied to every night, whether or not it sends a patient
        # row with a chart number (a FHIR bulk night never does), and on a delta night to what it carries over too.
        # Without them a merged chart would stand as its own patient: the night is held and says why
        try:
            pm = cfg.pidmap()
            try:
                aliases = pm.aliases()
            finally:
                pm.close()
        except Exception as exc:
            log.error("the chart merges could not be read: %s", type(exc).__name__)
            errors.append(f"the chart merges could not be read ({type(exc).__name__}); the night is held")
            aliases = {}
    if base is not None and aliases:
        survivors = set(aliases.values())
        carried = {str(r["id"]) for r in read_type(base, "Patient") if str(r["id"]) in survivors}
    cap = sample_cap(cfg.validation_max_pct)  # T-693 (D-457): the most resources of one type the sample takes
    night = _NightPass(
        zone,
        unit_defaults,
        source_kind == "fhir_bulk",
        _Aliases(aliases, patient_ids, carried),
        counts,
        cfg.sample_fraction if validate else None,
        cfg.profile_sample_per_type if validate and fhir_profiles == "jp-core" else None,
        cap,
    )
    removed: dict[str, int] = {}
    carried_moved: dict[str, int] = {}
    collisions: dict[str, int] = {}  # D-1253: two of tonight's rows, one id, other content
    full_counts = write_snapshot(
        out_dir, spool, base, tombstones, transform=night, left_out=left_out, removed=removed,
        aliases=aliases if base is not None else None, moved=carried_moved, collisions=collisions,
    )  # fmt: skip
    if source_kind == "ssmix2":  # D-1253 ruling 11: the order-number form the ids were made from
        from adapter.sources.ssmix2.source import order_id_form

        id_rule.record_keys(out_dir, {"ssmix2_order": order_id_form(getattr(source, "order_key", None))})
    # D-1253: order-free, over the merged snapshot, in bounded memory
    absent = absent_links(out_dir, site_wide=mapping.site_wide if mapping is not None else ())
    if absent:
        log.warning("links to a patient's record the lake does not hold (per table and type): %s", absent)
    if collisions:
        log.warning("records of tonight that had the id of another row of tonight, with other content (the last "
                    "row kept): %s", dict(sorted(collisions.items())))  # fmt: skip
    if carried_moved:
        log.info(
            "records carried over from snapshot %s written under the surviving patient of a chart merge: %s",
            last_good, dict(sorted(carried_moved.items())),
        )  # fmt: skip
    if removed:  # D-528: counts per record type only
        log.info("records the feed's rows no longer give were removed: %s", dict(sorted(removed.items())))
    (out_dir / PUBLISH_RECORD).unlink(missing_ok=True)
    defaulted, presence_read, shifted, aliased = (
        night.defaulted,
        night.presence_read,
        night.shifted,
        night.aliases.moved + carried_moved.get("Patient", 0),  # tonight's and those carried over (D-677)
    )
    missing = night.missing_counts()
    tombstoned = tombstone_count(out_dir)
    overrides: list[str] = []
    # T-611: the completeness gate. A missing or emptied table, a table that shrank past the band, or a patient who
    # left the feed while their records stayed holds the night; D-271's override for this night lets it through
    gaps, completeness = completeness_check(cfg, tables, out_dir, last_good, full=not since)
    if collisions:  # D-1253: counts per record type only
        completeness["id_collisions"] = dict(sorted(collisions.items()))
    if absent:  # D-1253: links to a patient's record the snapshot does not hold, per table and type
        completeness["links_to_absent_records"] = absent
    (out_dir / COMPLETENESS).write_text(
        json.dumps(completeness, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    if unmapped_codes:
        (out_dir / UNMAPPED_CODES).write_text(
            json.dumps(unmapped_codes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        for table, by_lookup in sorted(unmapped_codes.items()):
            for line in unmapped_lines(table, by_lookup, UNMAPPED_CODES):
                log.warning("%s", line)
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
        # T-693 (D-457): the sample is each type's share, at least 3 and at most a cap derived from the gate's own
        # limit (settable); the report names the cap and the types it cut. Taken from the stream (T-692)
        picked = night.sample.result() if night.sample is not None else []
        cut = capped_types(night.kept, cfg.sample_fraction, cap=cap)
        try:
            vres = chosen.validate(picked)
            vsum = ValidationSummary(
                sampled=vres.sampled,
                errors=vres.errors,
                error_pct=round(vres.error_pct, 3),
                validator=vres.validator,
                messages=vres.messages,
                sample_cap=cap,
                capped=cut or None,
            )
        except Exception as exc:
            from adapter import failure

            failure.log_failure(log, "validation failed to run", exc)
            errors.append(f"validation failed to run: {failure.words(exc)}")  # D-668
    psum: ValidationSummary | None = None
    if validate and fhir_profiles == "jp-core":
        try:
            psum = jp_core_check(cfg, night.jp_sample.result() if night.jp_sample is not None else [], out_dir)
        except Exception as exc:
            from adapter import failure

            failure.log_failure(log, "JP Core validation failed to run", exc)
            errors.append(f"JP Core validation failed to run: {failure.words(exc)}")  # D-668
    if source is not None and hasattr(source, "stats"):
        from adapter.sources.ssmix2.source import reader_summary

        (out_dir / "reader.json").write_text(
            json.dumps(reader_summary(source), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
    profile_said: dict[str, Any] | None = None
    if profile is not None or profile_note:  # 10B-6 (D-1233): which profile read this night, and its coverage lines
        from adapter import site_profile as sp

        cov = None
        if profile is not None:
            cov = sp.coverage(
                profile,
                out_dir,
                reads=sp.readable(profile, mapping.tables) if mapping is not None else None,
                from_verify=dict(mapper.from_verify) if mapper is not None else None,
            )
            cov["night_profile"] = profile.stamp()
            profile_said = {**sp.summary(cov), **({"pending": profile_note["pending"]["digest"]}
                                                  if "pending" in profile_note else {})}  # fmt: skip
            for line in sp.lines(cov):
                log.info("%s", line)
        record = {"profile": profile.stamp() if profile is not None else None, "coverage": cov,
                  "note": profile_note or None, "read_whole_because_the_profile_changed": profile_full}  # fmt: skip
        (out_dir / sp.RECORD).write_text(
            json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
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
    ended = datetime.now(zone)
    # NEW-B-20 (D-661): how long the night took, for the host's doctor (the Windows update window is placed outside
    # it). ``finished``: it ended published, the whole of a night; a held or failed night measures only its part
    from adapter import night_runs
    from adapter.publish import read_record

    night_runs.record(cfg.lake_dir, snap, started, ended, finished=passed and not held,
                      steps_at=read_record(out_dir).get("at"))  # fmt: skip
    report = IngestReport(
        snapshot=date.fromisoformat(snap),
        source=source_kind,
        since=since,
        started_at=started,
        finished_at=ended,
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
        connector=ConnectorReport.model_validate(read_times.summary(source_kind)),  # 10E-9: per message, per table
    )
    body = json.dumps(dump(report), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    (out_dir / "ingest_report.json").write_bytes(body)
    if held:  # T-611: the folder says so itself, for the steward and for any later publish
        (out_dir / HELD).write_text(json.dumps({"snapshot": snap, "errors": errors}) + "\n", encoding="utf-8")
    else:
        (out_dir / HELD).unlink(missing_ok=True)
    pruning: PruneResult | None = None
    budget_said: dict[str, Any] | None = None
    if passed and rebuild_lake:
        try:  # D-679: the night is published; its pruning failing is said, never the night's failure
            pruning = prune_lake(cfg, date.fromisoformat(snap))
            budget_said = pruning.as_dict()
        except Exception as exc:
            log.error("the lake's pruning did not end after the night (%s); it runs again after the next one",
                      type(exc).__name__)  # fmt: skip
            budget_said = {"error": type(exc).__name__}
    pruned = pruning.gone if pruning is not None else []
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
                # NEW-B-38 (D-679): the byte budget, the month-end NDJSON removed for it, and whether it was met
                "lake_budget": budget_said,
                "tombstoned": tombstoned,
                "held": held,
                "lake_busy": lake_busy or None,  # D-462: run again once the lake is free
                "publish": publish_steps,  # T-723: each publish step's state (None: the night was held at the gate)
                "unit_defaults_applied": defaulted,
                "site_profile": profile_said,  # 10B-6 (D-1233): id, version, digest and the coverage counts
                "presence_words_read": presence_read,
                "instants_to_site_offset": shifted,
                "drop_override": "; ".join(overrides) or None,
                # T-611: what the readiness page shows for a held night (tables only, never a row)
                "incomplete": completeness["problems"] or None,
                "duplicate_keys": {t: v["duplicate_keys"] for t, v in tables.items() if v["duplicate_keys"]} or None,
                # D-1253: two of tonight's rows with one id and other content (the last kept), per record type; links
                # to a patient's record the merged snapshot does not hold, per table; rows and deletes with no patient
                "id_collisions": dict(sorted(collisions.items())) or None,
                "links_to_absent_records": {t: sum(by.values()) for t, by in sorted(absent.items())} or None,
                "steward_review_needed": {  # D-1253 ruling 1: proposed (never coded) until a steward reviews them
                    t: v["steward_review_needed"] for t, v in sorted(tables.items()) if v.get("steward_review_needed")
                }
                or None,
                "rejected_no_patient": {
                    t: v["rejected_no_patient"] for t, v in sorted(tables.items()) if v.get("rejected_no_patient")
                }
                or None,
                "deletes_without_patient": {
                    t: v["deletes_without_patient"]
                    for t, v in sorted(tables.items())
                    if v.get("deletes_without_patient")
                }
                or None,
                "orphans": completeness["orphans"] or None,
                # NEW-DIN-6 (D-580): rows with a value the mapping could not use, per table (the codes: the file)
                "unmapped": {t: sum(sum(c.values()) for c in by.values()) for t, by in sorted(unmapped_codes.items())}
                or None,
                # NEW-B-39 (D-740): the same rows per source table split by kind (KINDS); their sum is the total above
                "unmapped_kinds": {t: unmapped_kinds(by) for t, by in sorted(unmapped_codes.items())} or None,
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

    def __init__(self, aliases: dict[str, str], patient_ids: list[str], carried: Iterable[str] = ()) -> None:
        self.aliases = aliases
        # NEW-B-36 (D-677): ``carried`` are the surviving patients a delta night carries over from the night before:
        # a merged chart's Patient sent tonight is left out for them too, as a full night leaves it out
        self.present = set(patient_ids) | set(carried) if aliases else set()
        self.moved = 0
        self.dropped = 0
        if aliases:  # how many Patients will be left out, known before the first is written (the sample's size)
            seen = set(patient_ids) | set(carried)
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
        self._walk(r)  # a Patient's own references (``link``) too: the same rule as for a record carried over
        if r.get("resourceType") != "Patient":
            return True
        new = self.aliases.get(str(r.get("id")))
        if new is None:
            return True
        self.moved += 1
        if new in self.present:
            return False
        alias_patient(r, new, self.aliases)
        self.present.add(new)
        return True

    def _walk(self, node: Any) -> None:
        alias_references(node, self.aliases)


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
        cap: int | None = None,
    ) -> None:
        from lake.flatten import Unread  # the inbound FHIR contract (T-616), the lake's own reading

        self.zone, self.unit_defaults, self.presence, self.aliases = zone, unit_defaults, presence, aliases
        self.defaulted = self.presence_read = self.shifted = self.undated = 0
        self.missing: Counter[str] = Counter()
        self.unread = Unread()
        kept = {**counts, "Patient": counts.get("Patient", 0) - aliases.dropped}
        self.kept = kept  # what the sample is taken from, by type (the report names the types the cap cut)
        self.sample = (
            Sampler("trialbox", lambda t: sample_size(kept.get(t, 0), fraction, 3, cap))
            if fraction is not None
            else None
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


#: NEW-B-39 (D-740): the kinds of D-580's counter (the owner's yes, 2026-11-13). ``code_unknown``: a code no look-up,
#: list of known codes or map gives a single answer for (the row is left out, or kept without the code);
#: ``unit_not_read``: a value whose unit is not the look-up's or that is implausible without one (D-590: the row is
#: kept without the value); ``reference_data_not_reached``: a code the reference data could not be asked for (D-593:
#: an outage, not a fault of the feed). Every place the mapping engine counts is named with its kind in a test
_UNIT_NOT_READ = ("unit_mismatch", "no_unit_implausible")


def unmapped_kind(name: str) -> str:
    """The kind of one name of D-580's counter (a look-up, ``column:<c>``, ``map:<from>-><to>``, a unit check, or
    ``<map>:unavailable``)."""
    if name.endswith(":unavailable"):
        return "reference_data_not_reached"
    if name in _UNIT_NOT_READ:
        return "unit_not_read"
    return "code_unknown"


def unmapped_kinds(by_name: dict[str, dict[str, int]]) -> dict[str, int]:
    """One table's rows per kind (every kind, zero included): counts only, their sum the table's total."""
    out = dict.fromkeys(KINDS, 0)
    for name, codes in by_name.items():
        out[unmapped_kind(name)] += sum(codes.values())
    return out


def unmapped_lines(table: str, by_kind: dict[str, dict[str, int]], file: str) -> list[str]:
    """What the night's log says about D-580's counter for one table (NEW-B-8, D-530): counts and the counter's
    own names, never a code. The counter holds rows left out (a code no look-up knows, D-580; an unknown status,
    D-587) and rows kept without the value (a unit not read, a value implausible without a unit: D-590), so the
    line calls none of them "dropped". Rows whose code the reference data could not be asked for (D-593:
    ``<map>:unavailable``) get a line of their own: an outage, not a fault of the feed, and not a held night."""
    rows = sum(sum(c.values()) for c in by_kind.values())
    distinct = sum(len(c) for c in by_kind.values())
    out = [
        f"{table}: {rows} rows hold a value the mapping could not use ({distinct} distinct values): the row is "
        f"left out or kept without that value, by the mapping's rule ({file})"
    ]
    down = {k.removesuffix(":unavailable"): sum(c.values()) for k, c in by_kind.items() if k.endswith(":unavailable")}
    if down:
        out.append(
            f"{table}: the reference data did not answer for {sum(down.values())} rows ({', '.join(sorted(down))}): "
            "their codes were not mapped tonight. The next delta night reads this table whole and maps what the "
            "source still holds (D-538). The night is not held for this (D-530)"
        )
    return out


class NoRoomForNight(RuntimeError):
    """Less free disk on the lake's volume than the last snapshot took (D-679): the night is refused before it
    reads or writes anything, as a night of the future is."""


def check_room(cfg: AdapterConfig, snap: str) -> None:
    """NEW-B-38 (D-679; review DATA-025): tonight's snapshot needs about the room the newest earlier snapshot took
    (its NDJSON, Parquet and DuckDB); a disk with less free space refuses the night, saying both numbers. The first
    night (no snapshot yet) has nothing to measure by."""
    lake_budget(cfg.lake_dir)  # a budget setting that cannot be read refuses the night here (LakeBudgetError)
    base = merge_base(cfg.lake_dir, snap)  # the newest earlier night that passed and still holds its NDJSON
    if base is None:
        return
    lake = cfg.lake_dir
    need = _bytes(
        [lake / "ndjson" / base, lake / "parquet" / f"snapshot={base}", *(lake / "db").glob(f"{base}.duckdb*")]
    )
    free = shutil.disk_usage(cfg.lake_dir).free
    if free < need:
        raise NoRoomForNight(
            f"not enough free disk for tonight's snapshot: about {need / 2**20:.1f} MB needed (snapshot {base} took "
            f"that), {free / 2**20:.1f} MB free on the lake's volume; free space or lower the kept snapshots (D-679)"
        )


class FutureNight(ValueError):
    """A night dated after the site's today (D-529): refused, nothing read or written."""


def refuse_future_night(snap: str, today: date) -> None:
    """NEW-PERF-3 (D-529; PERF-009): a night dated after the site's today is refused. Once served, every later
    night is older than it and is never served ("the box never moves back in time"), and the lake's age check read
    a future night as 0 days old. A name that is not a date (a tool's, a test's) has no place in time: not judged."""
    try:
        night = date.fromisoformat(snap[:10])
    except ValueError:
        return
    if night > today:
        raise FutureNight(
            f"night {snap} is dated after today ({today.isoformat()} at the site): it is not ingested. Check the "
            "date given to the run and the box's clock"
        )


def map_or_reject(mapper: Mapper, table: str, row: dict[str, Any], rejected: Counter[str]) -> list[Resource] | None:
    """One source row mapped, or None when the mapping cannot read it: then it is counted in ``rejected`` under its
    reason (:func:`reject_key`). The night and the back-fill reject alike (D-1253 review F).

    NEW-B-6 (D-527): a number the mapper reads and cannot compute with (thirty digits: decimal.InvalidOperation) is a
    row it cannot read, as a ValueError is; it ended the night before."""
    try:
        return list(mapper.map_table(table, iter([row])))
    except (ValueError, ArithmeticError) as exc:
        rejected[reject_key(exc)] += 1
        return None


def reject_key(exc: BaseException) -> str:
    """The key a rejected row is counted under (STD-025; D-520): the exception's type and its message **up to the
    first value**, never a feed value. The message is cut at its first quote mark (the mapper writes a value with
    ``repr``; everything from there on is ``<value>``, so a value that holds quote marks of both kinds cannot end
    the cut early and leave a fragment), and a run of digits before it is ``<n>`` (a number written without quote
    marks). An ``ArithmeticError`` has one fixed sentence (D-527). The key goes into ``completeness.json``, the
    night's error, the audit and the log."""
    if isinstance(exc, ArithmeticError):  # D-527: decimal's message is a list of signal classes, not a sentence
        return f"{type(exc).__name__}: a number the mapping cannot compute"
    text = str(exc)
    head = re.split("['\"\u2018\u2019\u201c\u201d`]", text, maxsplit=1)[0]
    cut = len(head) < len(text)
    head = re.sub(r"[0-9]+(?:[.,:/-][0-9]+)*", "<n>", head).strip()
    said = f"{head} <value>".strip() if cut else head
    return f"{type(exc).__name__}: {said}" if said else type(exc).__name__


def check_lookup_factors(mapping: Any) -> None:
    """Every ``factor`` of every look-up row is a finite number (empty: 1), or the load ends before its first row
    (D-527, review). The mapper parses the factor per row; with a row's ``ArithmeticError`` now a rejected row, a
    factor typed wrongly would reject every row of its code each night under a key that blames the feed."""
    for name, lookup in mapping.lookups.items():
        for code, row in lookup.rows.items():
            text = str(row.get("factor") or "1").strip()
            try:
                ok = Decimal(text).is_finite()
            except ArithmeticError:
                ok = False
            if not ok:
                raise ValueError(f"look-up {name}, row {code!r}: the factor {text!r} is not a number")


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
    # night, the first night after a first load made before D-535 (it wrote no completeness record), a table an override
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


def reference_maps(mapping: Any, db_url: str | None) -> Callable[[str, str], list[dict[str, Any]] | None]:
    """What the mapper asks the box's reference data with (D-593), for a night and for a first load (NEW-B-24,
    D-665).

    A map that is **not loaded** answers "no entry" for every code, which is counted and published and never asked
    again; loaded later, nothing would map those rows. So the first time a map the mapping names
    (``Mapping.concept_maps``) answers "no entry", the reference data is asked whether that map is loaded at all.
    If it is not, the map is treated from then on as one that **could not be asked** (the answer is None, counted
    under ``<map>:unavailable``): a night reads the table whole on the next delta night (D-538), a first load is
    held (D-660). Only rows that need the map are counted: a site without such rows is never asked to load a pack
    it does not use. With no database configured there is nothing that could be loaded: answered as before.
    The mapper asks by source system, so a source with two maps, one loaded and one not, is "not asked" for both
    once a code has no entry at all (no mapping shipped has two maps of one source)."""
    targets: dict[str, list[str]] = {}
    for source, target in mapping.concept_maps():
        targets.setdefault(source, []).append(target)
    absent: dict[str, bool] = {}  # per source system, once it is known
    not_loaded: list[str] = []

    def ask(system: str, code: str) -> list[dict[str, Any]] | None:
        if absent.get(system):
            return None
        got = refdata.map_targets_or_none(system, code, db_url)
        if got == [] and system in targets and system not in absent and (db_url or os.environ.get(DB_URL_ENV)):
            loaded = [refdata.has_map_or_none(system, t, db_url) for t in targets[system]]
            if None in loaded:
                # the "no entry" cannot be checked just now (the database went between two questions). Taken for
                # an answer it would be published and never asked again: this row is "not asked", the next asks
                return None
            absent[system] = False in loaded
            if absent[system]:
                not_loaded.append(f"{system} to {', '.join(targets[system])}")
                log.warning(
                    "the reference map from %s to %s is not loaded: the rows that need it are counted as not asked "
                    "(a night reads the table whole on the next delta night, D-538; a first load is held, D-660). "
                    "Load the reference pack",
                    system, ", ".join(targets[system]),
                )  # fmt: skip
                return None
        return got

    ask.not_loaded = not_loaded  # type: ignore[attr-defined]  # the maps found not loaded in this run (a held reason)
    return ask


def reread_whole(lake_dir: Path, base: str | None) -> tuple[set[str], str | None]:
    """The tables a delta night reads whole, and the night that says so (NEW-B-18, D-538): those for which the
    reference data did not answer on the night this one merges over (``base``; its ``unmapped_codes.json`` counts
    them under ``<map>:unavailable``, D-593). Their rows kept an unmapped code (D-530) and a delta night reads only
    rows that changed, so nothing would map them again. Nothing is kept for this: the night merged over says it,
    and a night that reads the table whole with the reference data answering says nothing for the next one. A
    file that cannot be read asks for nothing: the night goes on as a delta."""
    if base is None:
        return set(), None
    try:
        counted = json.loads((snapshot_dir(lake_dir, base) / UNMAPPED_CODES).read_text(encoding="utf-8"))
        tables = {
            str(t) for t, by in counted.items() if any(str(k).endswith(":unavailable") and c for k, c in by.items())
        }
    except (OSError, ValueError, AttributeError):
        tables = set()
    return tables, base


def _source_of(snapshot: Path) -> str | None:
    """The source kind a snapshot was read from (its ``ingest_report.json``); None when it does not say."""
    try:
        said = json.loads((snapshot / "ingest_report.json").read_text(encoding="utf-8")).get("source")
    except (OSError, ValueError, AttributeError):
        return None
    return str(said) if said else None


def merge_base(lake_dir: Path, snap: str) -> str | None:
    """The snapshot a delta night ``snap`` merges over (D-271): the newest earlier one that passed (``passed.json``),
    or the lake's ``CURRENT`` (folders written before the marker existed). Never a held night's NDJSON: only the
    delta's own records are validated, so merging over a held folder would promote the records it was held for."""
    prev = [s for s in list_snapshots(lake_dir) if s < snap]
    good = [s for s in prev if (snapshot_dir(lake_dir, s) / PASSED).exists()]
    cur = _current(lake_dir)
    if cur in prev:
        good.append(str(cur))
    # D-679: a month-end snapshot whose NDJSON the byte budget removed holds nothing to merge over
    good = [s for s in good if not (snapshot_dir(lake_dir, s) / NDJSON_REMOVED).exists()]
    return max(good) if good else None


def _built_not_served(lake_dir: Path, snap: str) -> bool:
    """The night has a publish record (T-723) and its promotion did not end. A folder without a record (a night
    from before T-723, a lake rebuilt by hand) is not judged here."""
    from adapter.publish import ENDED, read_record

    steps = read_record(snapshot_dir(lake_dir, snap)).get("steps") or {}
    return bool(steps) and steps.get("lake") not in ENDED


def prune_snapshots(cfg: AdapterConfig, today: date) -> list[str]:
    """The snapshots :func:`prune_lake` removed whole."""
    return prune_lake(cfg, today).gone


#: NEW-B-38 (D-679): the lake's byte budget, in MB (declared); unset, this share of the disk the lake is on. The rest
#: of that disk is for what shares it on a box (the database, the backup's staging, the logs) and for a night's build
#: while the last one is still kept
BUDGET_ENV = "TB_LAKE_BUDGET_MB"
LAKE_DISK_SHARE = 0.5
#: written in a month-end snapshot's folder when its NDJSON was removed for the budget: the folder, its reports and
#: its ``passed.json`` stay; no night merges over it (it holds nothing to merge)
NDJSON_REMOVED = "ndjson_removed.json"


class LakeBudgetError(ValueError):
    """``TB_LAKE_BUDGET_MB`` is not a whole number of megabytes above 0 (D-679): the night is refused before it reads,
    so that a typo is found by the first night, not at the end of one."""


@dataclass
class PruneResult:
    """What a night's pruning did (NEW-B-38, D-679): the snapshots removed whole, the month-end snapshots whose
    NDJSON was removed (the lake still serves them; they can no longer be rebuilt from it), the lake's size and its
    budget after, and whether the budget could be met (``said``: why not)."""

    gone: list[str]
    ndjson_dropped: list[str]
    used_bytes: int
    budget_bytes: int
    unmet: bool = False
    said: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"snapshots_gone": self.gone, "ndjson_dropped": self.ndjson_dropped, "used_bytes": self.used_bytes,
                "budget_bytes": self.budget_bytes, "unmet": self.unmet, "said": self.said or None}  # fmt: skip


def lake_budget(lake_dir: Path) -> int:
    """The lake's byte budget: ``TB_LAKE_BUDGET_MB``, else :data:`LAKE_DISK_SHARE` of the disk it is on."""
    raw = os.environ.get(BUDGET_ENV, "").strip()
    if raw:
        try:
            mb = int(raw)
        except ValueError:
            raise LakeBudgetError(f"{BUDGET_ENV} must be a whole number of megabytes above 0") from None
        if mb < 1:
            raise LakeBudgetError(f"{BUDGET_ENV} must be a whole number of megabytes above 0")
        return mb * 1024 * 1024
    probe = lake_dir if lake_dir.exists() else lake_dir.parent
    return int(shutil.disk_usage(probe).total * LAKE_DISK_SHARE)


def _bytes(paths: Iterable[Path], seen: set[tuple[int, int]] | None = None) -> int:
    """The bytes the files under ``paths`` take, a file with several names (the lake's reader links) once and a
    symbolic link not followed. A file or folder that goes while it is counted (a rebuild's spill, a reader's link)
    is left out, never an error: the count runs after a night was published."""
    seen = set() if seen is None else seen
    n = 0

    def one(path: str) -> int:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return 0
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) in seen:
            return 0
        seen.add((st.st_dev, st.st_ino))
        return st.st_size

    for root in paths:
        n += one(str(root))
        for folder, _dirs, names in os.walk(root):  # os.walk leaves out a folder it cannot list (gone)
            n += sum(one(os.path.join(folder, name)) for name in names)
    return n


def _snapshot_paths(lake_dir: Path, s: str) -> list[Path]:
    """Every file of snapshot ``s``: its NDJSON, Parquet, DuckDB (and side files) and generations."""
    return [
        lake_dir / "ndjson" / s,
        lake_dir / "parquet" / f"snapshot={s}",
        *(lake_dir / "db").glob(f"{s}.duckdb*"),
        *(lake_dir / "db" / "gen").glob(f"{s}.g*"),
    ]


def snapshot_bytes(lake_dir: Path, s: str) -> int:
    """How many bytes snapshot ``s`` takes (D-679: the free space a night must find before it writes its own)."""
    return _bytes(_snapshot_paths(lake_dir, s))


#: D-1253: the earlier id rule's month-end snapshots the one rebuild kept aside (``tools/id_rule_rebuild.py``)
ID_RULE_ASIDE = "id_rule_1"


def _prune_aside(lake_dir: Path, today: date, months: int) -> list[str]:
    """D-1253: a month-end of the earlier id rule, kept aside by the one rebuild and never read, goes when retention
    no longer keeps it, as any month-end does. Returns the snapshots that went."""
    from tb_common.id_rule import snapshot_names
    from tb_common.retention import snapshots_to_keep

    aside = lake_dir / "id_rule_1"  # ID_RULE_ASIDE, spelt out: the erasure registry's scan reads the name here
    snaps = sorted(snapshot_names(aside))  # every place: a month-end may be kept aside without its NDJSON
    keep = snapshots_to_keep(snaps, today, 0, months)
    gone = []
    for s in snaps:
        if s in keep:
            continue
        shutil.rmtree(aside / "ndjson" / s, ignore_errors=True)
        shutil.rmtree(aside / "parquet" / f"snapshot={s}", ignore_errors=True)
        for f in [*(aside / "db").glob(f"{s}.duckdb*"), *(aside / "db" / "gen").glob(f"{s}.g*")]:
            f.unlink(missing_ok=True)
        gone.append(s)
    return gone


def good_snapshots(lake_dir: Path, snaps: Iterable[str], current: str | None = None) -> set[str]:
    """The nights retention counts (the one definition, used by :func:`prune_lake` and by the D-1253 rebuild's choice
    of month-ends). T-611: only nights that passed (a held night has no passed.json and no DuckDB; a folder from
    before the marker that was promoted has its DuckDB). T-723 second review (L3): a built night whose publish record
    says the promotion did not end was never served: it is not a good night. The served night always is."""
    snaps = set(snaps)
    good = {s for s in snaps if (snapshot_dir(lake_dir, s) / PASSED).exists()}
    good |= {p.stem for p in (lake_dir / "db").glob("*.duckdb") if not _built_not_served(lake_dir, p.stem)}
    good |= {current} if current else set()
    return good & snaps | ({current} if current else set())


def prune_lake(cfg: AdapterConfig, today: date) -> PruneResult:
    """SPEC §10.3: keep the last N nightly snapshots and each month's last snapshot for M months (NDJSON, parquet,
    DuckDB); the current snapshot is always kept, and so is every snapshot a running job holds (T-305b, D-403: a
    long SCREEN, or one waiting for an approval, still reads its night after N newer ones arrived).

    NEW-B-38 (D-679; review DATA-025): then the lake is kept within its byte budget (:func:`lake_budget`). While it
    is over, the NDJSON of the oldest month-end snapshot goes (its DuckDB and Parquet stay: the lake still serves
    it), then, when every month-end NDJSON is gone, the oldest month-end snapshot whole. The served snapshot, the N
    nightly ones (the delta's merge base among them) and a snapshot a job holds never go. A budget that cannot be met
    is logged and returned (``unmet``, ``said``): the night is not held for it."""
    from lake.store import SnapshotBuilding, building, drop_reader_links, held_snapshots, lake_lock
    from tb_common.retention import snapshots_to_keep

    current = (cfg.lake_dir / "CURRENT").read_text().strip() if (cfg.lake_dir / "CURRENT").exists() else None
    snaps = set(list_snapshots(cfg.lake_dir)) | {p.stem for p in (cfg.lake_dir / "db").glob("*.duckdb")}
    good = good_snapshots(cfg.lake_dir, snaps, current)
    keep = snapshots_to_keep(snaps, today, cfg.keep_nightly, cfg.keep_month_end_months, good) | {current or ""}
    nightly = snapshots_to_keep(snaps, today, cfg.keep_nightly, 0, good) | {current or ""}
    budget = lake_budget(cfg.lake_dir)
    gone: list[str] = []
    ndjson_dropped: list[str] = []

    def drop(s: str, whole: bool) -> bool:
        try:
            # D-462: a snapshot that is being rebuilt is left alone (the build would bring it back at its swap)
            with building(cfg.lake_dir, s):
                if whole:
                    shutil.rmtree(cfg.lake_dir / "ndjson" / s, ignore_errors=True)
                else:  # the records go; the night's folder, its reports and its passed.json stay (D-679)
                    nd = cfg.lake_dir / "ndjson" / s
                    for f in nd.glob("*.ndjson"):
                        f.unlink(missing_ok=True)
                    (nd / NDJSON_REMOVED).write_text(
                        json.dumps({"snapshot": s, "why": "the lake's byte budget (D-679)"}) + "\n", encoding="utf-8"
                    )
                if whole:
                    shutil.rmtree(cfg.lake_dir / "parquet" / f"snapshot={s}", ignore_errors=True)
                    for f in (cfg.lake_dir / "db").glob(f"{s}.duckdb*"):
                        f.unlink(missing_ok=True)
                    for f in (cfg.lake_dir / "db" / "gen").glob(f"{s}.g*"):  # T-724 (D-490): its generations
                        f.unlink(missing_ok=True)
                    drop_reader_links(cfg.lake_dir, s)
        except SnapshotBuilding:
            log.info("lake snapshot %s is being rebuilt: not pruned this time", s)
            return False
        return True

    with lake_lock(cfg.lake_dir):  # D-462: no hold lands between reading the holds and the deletes
        held = set(held_snapshots(cfg.lake_dir).values())
        keep |= held
        for s in sorted(s for s in snaps if s not in keep):
            if drop(s, whole=True):
                gone.append(s)
        used = _bytes([cfg.lake_dir])
        # the month-end snapshots the count keeps, oldest first; never the served one, a nightly one or a held one
        month_ends = sorted(s for s in keep if s and s not in nightly and s not in held and s in snaps)
        for s in month_ends:
            if used <= budget:
                break
            nd = cfg.lake_dir / "ndjson" / s
            if any(nd.glob("*.ndjson")):
                size = _bytes(nd.glob("*.ndjson"))
                if drop(s, whole=False):
                    ndjson_dropped.append(s)
                    used -= size
        for s in month_ends:
            if used <= budget:
                break
            size = snapshot_bytes(cfg.lake_dir, s)
            if drop(s, whole=True):
                gone.append(s)
                used -= size
        gone += _prune_aside(cfg.lake_dir, today, cfg.keep_month_end_months)
        used = _bytes([cfg.lake_dir])
    res = PruneResult(sorted(gone), ndjson_dropped, used, budget)
    if used > budget:
        res.unmet = True
        res.said = (
            f"the lake's byte budget cannot be met: {used // 2**20} MB used, {budget // 2**20} MB budget; what is "
            f"left is the served snapshot, the {cfg.keep_nightly} nightly ones and those a job holds ({BUDGET_ENV})"
        )
        log.error("%s", res.said)
    if ndjson_dropped:
        log.warning(
            "lake over its byte budget: the NDJSON of month-end snapshots %s was removed; the lake still serves them, "
            "they can no longer be rebuilt from it (D-679)", ", ".join(ndjson_dropped),
        )  # fmt: skip
    return res
