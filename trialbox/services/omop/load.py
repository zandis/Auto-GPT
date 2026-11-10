"""Load the normalized feed (FHIR R4 NDJSON, as the adapter writes it, and the site's own inputs) into OMOP (D-151).

    report = load_batch(db, "feed", "2026-10-31", by_type, files={"Condition": "ndjson/2026-10-31/Condition.ndjson"})

One batch is one source kind's complete set of records: ``feed`` (a snapshot's NDJSON, which the adapter writes as
the whole hospital, deltas merged) or ``site`` (the site's published inputs, ``lake/site/*.ndjson``, D-135).

* **Pseudonymised ids.** Only pseudonyms arrive (the adapter keys every resource with the site key). The patient
  pseudonym is ``person_source_value``; ``person_id`` is an integer minted once per pseudonym (``tb_id_map``), never
  derived from a chart number. Staff ids and department codes get their provider and care-site ids the same way.
* **Source values and concepts.** Every code is kept verbatim in ``*_source_value`` (ICD-10, LOINC, ATC, NHI, ...)
  with its local source concept (``omop.vocab``: minted once per code system and code, >= 2,000,000,000);
  ``*_concept_id`` is the standard concept where the vocabulary has one, else 0.
* **Idempotent.** A record is keyed by (kind, resource type, source id, part). A re-load of the same batch changes
  nothing (every record ``same``); a changed record is replaced in place (same OMOP id) with its before-image in
  ``tb_record_event``.
* **Tombstones.** A record of this kind that the batch no longer carries is deleted from the standard table and
  its ``tb_record`` becomes ``tombstoned`` (before-image kept); sent again, it is restored with the same id.
* **Status and provenance** per record in ``tb_record`` (batch, file, row; first and last batch). A proposed fact is
  loaded (its type concept says so) but never reaches a coded lake table; a refuted diagnosis is ``rejected``.
* **Conflicts.** Two sources that give a patient different birth dates, sexes or dates of death open a
  ``tb_conflict``; the lake reads the item as unknown until a person resolves it (``resolve_conflict``).

The whole batch is one transaction under an advisory lock: a load is all or nothing and two loads never interleave.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from lake.flatten import DEMOGRAPHIC, NOT_PRESENT, SUSPECTED, Flattener, basis_of, verification_of, void
from tb_common import feedguard
from tb_common.config import site_tz
from tb_common.db import Database

from omop import vocab
from omop.schema import STATUSES, TRANSITIONS, OmopError
from omop.vocab import Code, Concepts

Resource = dict[str, Any]
KINDS = ("feed", "site")
# the OMOP id column of each table the loader writes
ID_COL = {
    "visit_occurrence": "visit_occurrence_id",
    "condition_occurrence": "condition_occurrence_id",
    "drug_exposure": "drug_exposure_id",
    "procedure_occurrence": "procedure_occurrence_id",
    "measurement": "measurement_id",
    "observation": "observation_id",
    "note": "note_id",
    "tb_appointment": "appointment_id",
    "tb_claim": "claim_id",
    "tb_consent": "consent_id",
}
# the required date column of each table and the TIMESTAMP column it is taken from (NULL source -> imputed)
REQUIRED_DATE = {
    "visit_occurrence": "visit_start_date",
    "condition_occurrence": "condition_start_date",
    "drug_exposure": "drug_exposure_start_date",
    "procedure_occurrence": "procedure_date",
    "measurement": "measurement_date",
    "observation": "observation_date",
    "note": "note_date",
}
# varchar widths of the official DDL for the columns the loader fills from source text
WIDTH = {
    "condition_source_value": 50,
    "condition_status_source_value": 50,
    "measurement_source_value": 50,
    "unit_source_value": 50,
    "value_source_value": 50,
    "value_as_string": 60,
    "drug_source_value": 50,
    "procedure_source_value": 50,
    "note_source_value": 50,
    "note_title": 250,
    "visit_source_value": 50,
    "observation_source_value": 50,
}


def status_for(basis: str | None) -> str:
    """The record status a source's basis tag gives (D-135 tags; none: the hospital's coded record)."""
    if basis in ("proposed", "confirmed", "signed", "derived"):
        return str(basis)
    return "coded"


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date | datetime) else v


def _num(v: float | None) -> Decimal | None:
    """Floats into NUMERIC through their shortest repr: the value reads back as the same float."""
    return None if v is None else Decimal(repr(float(v)))


def _clean(s: str | None, stats: dict[str, int]) -> str | None:
    """PostgreSQL text cannot hold NUL: stripped, and counted in the load report."""
    if s is None or "\x00" not in s:
        return s
    stats["nul_stripped"] = stats.get("nul_stripped", 0) + 1
    return s.replace("\x00", "")


def _as_dt(d: date | datetime | None) -> datetime | None:
    if d is None or isinstance(d, datetime):
        return d
    return datetime(d.year, d.month, d.day)


@dataclass
class Rec:
    rtype: str
    srcid: str
    part: int
    table: str | None
    pid: str | None
    basis: str | None
    status: str
    source_row: int
    row: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, tuple[str, str]] = field(default_factory=dict)  # column -> (id kind, source id)
    extra: dict[str, Any] = field(default_factory=dict)
    codes: list[Code] = field(default_factory=list)
    std_only: list[tuple[str | None, str]] = field(default_factory=list)  # standard lookup only (units, note class)
    # set while resolving
    record_id: int | None = None
    person_id: int | None = None
    imputed: bool = False

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.rtype, self.srcid, self.part)


@dataclass
class LoadReport:
    kind: str
    batch: str
    inserted: int = 0
    updated: int = 0
    same: int = 0
    tombstoned: int = 0
    restored: int = 0
    concepts_minted: int = 0
    conflicts_open: int = 0
    by_table: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    override: str = ""  # D-271: why a mass tombstone was let through (TB_FEED_DROP_OVERRIDE for this batch)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class _Builder:
    """FHIR resources -> records. Field values come from the lake's own flattener (one reading of FHIR for both
    paths: dates in the hospital zone, censored values, the suspected flag), so the two lakes cannot drift."""

    def __init__(self, tz: str, kind: str, stats: dict[str, int]) -> None:
        self.fl = Flattener(tz)
        self.kind = kind
        self.stats = stats

    def type_concept(self, status: str) -> int:
        if status == "proposed":
            return vocab.PROPOSED_FACT
        return vocab.SITE_INPUT if self.kind == "site" else vocab.EHR

    def _code(
        self,
        rec: Rec,
        col: str,
        system: str | None,
        code: str | None,
        display: str | None,
        domain: str,
        lake_code: str = "code",
        lake_system: str | None = "system",
    ) -> None:
        """``col`` gets the verbatim code; its source concept is minted. A code that cannot be a concept (none, or
        longer than 50 characters) keeps its system (and code) in ``extra`` so the lake reads them back."""
        width = WIDTH.get(col, 50)
        rec.row[col] = code[:width] if code else code
        if code and len(code) <= 50:
            rec.codes.append(Code(system, code, display, domain))
        else:
            if code and len(code) > width:
                rec.extra[lake_code] = code
            if lake_system and system is not None:
                rec.extra[lake_system] = system

    def _text(self, rec: Rec, col: str, value: str | None, lake_col: str) -> None:
        value = _clean(value, self.stats)
        width = WIDTH[col]
        if value is not None and len(value) > width:
            rec.row[col] = value[:width]
            rec.extra[lake_col] = value
        else:
            rec.row[col] = value

    def build(self, rtype: str, r: Resource, line: int, responses: Mapping[str, Resource]) -> list[Rec]:
        basis = basis_of(r)
        status = status_for(basis)
        if void(rtype, r):  # D-275 (review S-4): entered in error, cancelled, never done: kept, never a fact
            status = "rejected"

        def rec(table: str | None, pid: str | None, part: int = 0, srcid: str | None = None) -> Rec:
            return Rec(rtype, srcid or str(r["id"]), part, table, pid, basis, status, line)

        fl = self.fl
        if rtype == "Patient":
            p = fl.patient(r)
            out = rec("person", p["pid"])
            out.extra = {k: _iso(p[k]) for k in ("birth_date", "sex", "deceased_date")}
            return [out]
        if rtype == "Practitioner":
            p = fl.practitioner(r)
            out = rec("provider", None)
            out.refs["provider_id"] = ("provider", str(p["practitioner_id"]))
            out.extra = {"staff_id": p["staff_id"], "name": _clean(p["name"], self.stats)}
            return [out]
        if rtype == "Encounter":
            e = fl.encounter(r)
            out = rec("visit_occurrence", e["pid"])
            out.row = {
                "visit_concept_id": vocab.VISIT.get(e["class"] or "", 0),
                "visit_start_datetime": e["start"],
                "visit_end_datetime": None,
                "visit_type_concept_id": self.type_concept(status),
                "visit_source_concept_id": None,
            }
            self._text(out, "visit_source_value", e["class"], "class")
            if e["practitioner_id"] is not None:
                out.refs["provider_id"] = ("provider", e["practitioner_id"])
            if e["dept"] is not None:
                out.refs["care_site_id"] = ("care_site", e["dept"])
            return [out]
        if rtype == "Appointment":
            a = fl.appointment(r)
            out = rec("tb_appointment", a["pid"])
            out.row = {"appointment_datetime": a["start"], "status": a["status"]}
            if a["practitioner_id"] is not None:
                out.refs["provider_id"] = ("provider", a["practitioner_id"])
            if a["dept"] is not None:
                out.refs["care_site_id"] = ("care_site", a["dept"])
            return [out]
        if rtype == "Condition":
            return [self.condition(r, rec(None, None))]
        if rtype == "Observation":
            return self.observation(r, rec)
        if rtype == "MedicationRequest":
            return [self.medication(r, rec(None, None))]
        if rtype == "Procedure":
            p = fl.procedure(r)
            out = rec("procedure_occurrence", p["pid"])
            out.row = {
                "procedure_datetime": _as_dt(p["performed"]),
                "procedure_type_concept_id": self.type_concept(status),
            }
            system = fl.coding(r.get("code"))[1]
            self._code(
                out, "procedure_source_value", system, p["code"], self._display(r.get("code"), p["code"]), "Procedure"
            )
            out.row["_std"] = (system, p["code"])
            return [out]
        if rtype == "DiagnosticReport":
            p = fl.report(r)
            out = rec("note", p["pid"])
            out.row = {
                "note_datetime": _as_dt(p["effective"]),
                "note_type_concept_id": self.type_concept(status),
                "note_title": None,
                "note_text": _clean(p["conclusion"], self.stats) or "",
                "encoding_concept_id": vocab.UTF8,
                "language_concept_id": 0,
            }
            if p["conclusion"] is None:
                out.extra["conclusion"] = None
            out.extra["system"] = p["system"]
            self._text(out, "note_source_value", p["code"], "code")
            out.row["_class"] = (p["system"], p["code"])  # note_class_concept_id: the standard concept, if any
            if p["code"]:
                out.std_only.append((p["system"], p["code"]))
            return [out]
        if rtype == "DocumentReference":
            p = fl.document(r)
            out = rec("note", p["pid"])
            out.row = {
                "note_datetime": p["date"],
                "note_type_concept_id": self.type_concept(status),
                "note_class_concept_id": 0,
                "note_text": _clean(p["text"], self.stats) or "",
                "encoding_concept_id": vocab.UTF8,
                "language_concept_id": 0,
                "note_source_value": None,
            }
            self._text(out, "note_title", p["type"], "type")
            if p["eid"] is not None:
                out.refs["visit_occurrence_id"] = ("visit", p["eid"])
            return [out]
        if rtype == "Consent":
            c = fl.consent(r)
            out = rec("tb_consent", c["pid"])
            out.row = {"status": c["status"], "contact_ok": c["contact_ok"], "consent_date": c["date"]}
            return [out]
        if rtype == "Claim":
            c = fl.claims([r], [x for x in [responses.get(str(r["id"]))] if x])[0]
            out = rec("tb_claim", c["pid"])
            out.row = {k: c[k] for k in ("created", "product", "outcome", "approval_start", "approval_end")}
            return [out]
        # ClaimResponse (read with its Claim), Coverage, Organization, ...: provenance only, no OMOP row
        self.stats[f"provenance_only:{rtype}"] = self.stats.get(f"provenance_only:{rtype}", 0) + 1
        return [rec(None, None)]

    @staticmethod
    def _display(cc: dict[str, Any] | None, code: str | None) -> str | None:
        for c in (cc or {}).get("coding") or []:
            if c.get("code") == code and c.get("display"):
                return str(c["display"])
        return (cc or {}).get("text")

    def condition(self, r: Resource, out: Rec) -> Rec:
        c = self.fl.condition(r)
        vs = verification_of(r)
        out.table, out.pid = "condition_occurrence", c["pid"]
        if vs in NOT_PRESENT:  # refuted or entered in error: kept, never a diagnosis
            out.status = "rejected"
        out.row = {
            "condition_start_datetime": _as_dt(c["onset"]),
            "_fallback_date": c["recorded"],
            "condition_type_concept_id": self.type_concept(out.status),
            "condition_status_concept_id": vocab.SUSPECTED if vs in SUSPECTED else None,
        }
        if c["recorded"] != c["onset"]:
            out.extra["recorded"] = _iso(c["recorded"])
        system = c["system"]
        self._code(
            out, "condition_source_value", system, c["code"], self._display(r.get("code"), c["code"]), "Condition"
        )
        out.row["_std"] = (system, c["code"])
        self._text(out, "condition_status_source_value", c["status"], "status")
        if c["eid"] is not None:
            out.refs["visit_occurrence_id"] = ("visit", c["eid"])
        return out

    def medication(self, r: Resource, out: Rec) -> Rec:
        m = self.fl.medication(r)
        out.table, out.pid = "drug_exposure", m["pid"]
        cc = r.get("medicationCodeableConcept") or {}
        nhi = atc = nhi_sys = atc_sys = None
        for c in cc.get("coding") or []:  # the flattener's own reading (``Flattener.medication``), systems kept
            if "atc" in (c.get("system") or ""):
                atc, atc_sys = c.get("code"), c.get("system")
            elif nhi is None:
                nhi, nhi_sys = c.get("code"), c.get("system")
        if (nhi, atc) != (m["nhi_code"], m["atc"]):  # the two readings must agree
            raise OmopError(f"medication {r.get('id')}: codes read differently from the lake's flattener")
        is_atc = m["atc"] is not None
        code, system = (m["atc"], atc_sys) if is_atc else (m["nhi_code"], nhi_sys)
        out.row = {
            "drug_exposure_start_datetime": _as_dt(m["start"]),
            "_end": m["end"],
            "verbatim_end_date": m["end"],
            "drug_type_concept_id": self.type_concept(out.status),
            "sig": _clean(m["dose"], self.stats),
        }
        self._code(
            out,
            "drug_source_value",
            system,
            code,
            self._display(cc, code),
            "Drug",
            lake_code="atc" if is_atc else "nhi_code",
            lake_system=None,
        )
        out.row["_std"] = (system, code)
        if is_atc:
            out.extra["atc_src"] = True
            if m["nhi_code"] is not None:
                out.extra["nhi_code"] = m["nhi_code"]
        if m["authored"] != m["start"]:
            out.extra["authored"] = _iso(m["authored"])
        if m["status"] is not None:
            out.extra["status"] = m["status"]
        if m["name"] is not None:
            out.extra["name"] = _clean(m["name"], self.stats)
        return out

    def observation(self, r: Resource, rec: Any) -> list[Rec]:
        demographic = any(c.get("system") == DEMOGRAPHIC for c in (r.get("code") or {}).get("coding") or [])
        text = r.get("valueString") or r.get("valueDateTime") or (r.get("valueCodeableConcept") or {}).get("text")
        text = _clean(text, self.stats)
        if demographic:  # a demographic fact read from a chart or a sheet (D-135): OMOP OBSERVATION, never coded
            o = self.fl.observation(r)
            out: Rec = rec("observation", o["pid"])
            out.row = {
                "observation_datetime": o["effective"],
                "observation_type_concept_id": self.type_concept(out.status),
                "value_as_number": _num(o["value_num"]),
                "value_as_string": text[:60] if text else text,
            }
            self._code(out, "observation_source_value", o["system"], o["code"], None, "Observation")
            self._text(out, "unit_source_value", o["unit"], "unit")
            self._text(out, "value_source_value", text, "value_text")
            out.extra["demographic"] = True
            return [out]
        rows = self.fl.observations(r)
        comps = r.get("component") or []
        recs = []
        for part, o in enumerate(rows):
            src = r if part == 0 else comps[part - 1]
            out = rec("measurement", o["pid"], part)
            vsys = self.fl.coding(src.get("valueCodeableConcept"))[1]
            q = src.get("valueQuantity") or {}
            out.row = {
                "measurement_datetime": o["effective"],
                "measurement_type_concept_id": self.type_concept(out.status),
                "operator_concept_id": vocab.OPERATOR.get(o["value_cmp"] or ""),
                "value_as_number": _num(o["value_num"]),
                "_value": (vsys, o["value_code"]),
                "_unit": (q.get("system"), o["unit"]),
            }
            if o["unit"]:
                out.std_only.append((q.get("system"), o["unit"]))
            if o["value_code"] and len(o["value_code"]) <= 50:
                out.codes.append(Code(vsys, o["value_code"], None, "Meas Value"))
            elif o["value_code"] is not None:
                out.extra["value_code"] = o["value_code"]
            codes = (src.get("code") or {}).get("coding") or []
            system = o["system"]
            display = next((c.get("display") for c in codes if c.get("code") == o["code"]), None)
            self._code(out, "measurement_source_value", system, o["code"], display, "Measurement")
            out.row["_std"] = (system, o["code"])
            self._text(out, "unit_source_value", o["unit"], "unit")
            self._text(out, "value_source_value", text if part == 0 else None, "value_text")
            if o["category"] is not None:
                out.extra["category"] = o["category"]
            if o["local_code"] is not None:
                out.extra["local_code"] = o["local_code"]
            recs.append(out)
        return recs


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _batch_date(batch: str) -> date:
    try:
        return date.fromisoformat(batch.rsplit("@", 1)[-1][:10])
    except ValueError:
        return date.today()


def _map_ids(tx: Any, kind: str, ids: Iterable[str], seq: str) -> dict[str, int]:
    want = sorted(set(ids))
    if not want:
        return {}
    have = dict(
        tx.fetchall("SELECT source_id, omop_id FROM tb_id_map WHERE id_kind = ? AND source_id = ANY(?)", (kind, want))
    )
    new = [s for s in want if s not in have]
    if new:
        nums = [int(r[0]) for r in tx.fetchall(f"SELECT nextval('{seq}') FROM generate_series(1, ?)", (len(new),))]
        tx.copy_rows(
            "tb_id_map", ["id_kind", "source_id", "omop_id"], [(kind, s, n) for s, n in zip(new, nums, strict=True)]
        )
        have.update(zip(new, nums, strict=True))
    return {str(k): int(v) for k, v in have.items()}


TB_RECORD_COLS = [
    "source_kind",
    "resource_type",
    "source_record_id",
    "part",
    "cdm_table",
    "record_id",
    "person_id",
    "status",
    "basis",
    "source_batch",
    "source_file",
    "source_row",
    "content_sha",
    "extra",
    "date_imputed",
    "first_batch",
    "last_batch",
]


def load_batch(
    db: Database,
    kind: str,
    batch: str,
    by_type: Mapping[str, list[Resource]],
    files: Mapping[str, str] | None = None,
    tz: str | None = None,
    site_name: str = "",
) -> LoadReport:
    """Load one complete batch of ``kind``; return what changed. See the module docstring."""
    if kind not in KINDS:
        raise OmopError(f"unknown source kind {kind!r}")
    t0 = time.perf_counter()
    rep = LoadReport(kind, batch)
    stats: dict[str, int] = {}
    files = files or {}
    tz = site_tz(tz)  # the site's zone; TB_TZ when not given, never a default (D-315)
    b = _Builder(tz, kind, stats)
    responses = {}
    for cr in by_type.get("ClaimResponse", []):  # the flattener's join: the last response to a claim wins
        req = ((cr.get("request") or {}).get("reference") or "").split("/")[-1]
        responses[req] = cr
    keyed: dict[tuple[str, str, int], Rec] = {}
    for rtype in sorted(by_type):
        for line, r in enumerate(by_type[rtype], start=1):
            for rec in b.build(rtype, r, line, responses):
                if rec.key in keyed:  # one id twice in a file: the last line wins, as the NDJSON merge does
                    stats["duplicate_id"] = stats.get("duplicate_id", 0) + 1
                    del keyed[rec.key]
                keyed[rec.key] = rec
    recs = list(keyed.values())
    try:
        return _load(db, kind, batch, recs, files, tz, site_name, stats, rep, t0)
    except _Refused as r:  # rolled back; the refusal itself is kept (D-271)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO tb_load (source_kind, batch, seconds, counts) VALUES (?, ?, 0, ?::jsonb)",
                (f"{kind}-refused", batch, json.dumps({"refused": str(r)})),
            )
        raise OmopError(
            f"{r}: refused, nothing loaded (the lake keeps its CURRENT snapshot). Check the feed; to load it anyway "
            f"set {feedguard.OVERRIDE_ENV}='{batch}: <reason>' (this batch only; the reason is recorded with the load)"
        ) from None


class _Refused(Exception):
    """A feed batch that would tombstone (nearly) every live person (D-271)."""


def _load(
    db: Database,
    kind: str,
    batch: str,
    recs: list[Rec],
    files: Mapping[str, str],
    tz: str,
    site_name: str,
    stats: dict[str, int],
    rep: LoadReport,
    t0: float,
) -> LoadReport:
    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('trialbox-omop-load'))")
        last = tx.fetchval("SELECT max(batch) FROM tb_load WHERE source_kind = ?", (kind,))
        if last is not None and batch < str(last):
            raise OmopError(
                f"OMOP holds {kind} batch {last}; refusing the older batch {batch} (a store of record "
                "moves forward; an older snapshot's lake is kept as it was built)"
            )
        dqd_before: dict[str, int] | None = None
        if kind == "feed":
            rep.override = _tombstone_guard(tx, batch, recs)
            from omop.dqd import relational_violations

            dqd_before = relational_violations(tx, person_only=True)
        concepts = Concepts(tx)
        concepts.prepare((c for r in recs for c in r.codes), (p for r in recs for p in r.std_only))
        _resolve(tx, kind, batch, recs, concepts, rep)
        affected_persons, affected_providers = _write(tx, kind, batch, recs, files, rep)
        _derive(tx, affected_persons, affected_providers, batch, rep, site_name)
        if dqd_before is not None:
            held = _dqd_hold(tx, batch, dqd_before)
            rep.override = "; ".join(x for x in (rep.override, held) if x)
        rep.concepts_minted = concepts.minted
        rep.skipped = dict(sorted({**stats, **rep.skipped}.items()))
        rep.seconds = round(time.perf_counter() - t0, 2)
        tx.execute(
            "INSERT INTO tb_load (source_kind, batch, seconds, counts) VALUES (?, ?, ?, ?::jsonb)",
            (kind, batch, rep.seconds, json.dumps(rep.as_dict())),
        )
    return rep


def _tombstone_guard(tx: Any, batch: str, recs: list[Rec]) -> str:
    """D-271: a feed batch that would tombstone every live record of a CDM table (persons, conditions, measurements,
    ...), or more than ``TB_FEED_MAX_DROP_PCT`` (default 20) % of them, is a missing or broken extract, not a hospital
    that lost its data overnight: refused (``_Refused``) unless ``TB_FEED_DROP_OVERRIDE`` names this batch with a
    reason, which is returned (kept in ``tb_load``)."""
    seen = {r.key for r in recs}
    live: dict[str, int] = defaultdict(int)
    gone: dict[str, int] = defaultdict(int)
    for t, s, p, table in tx.fetchall(
        "SELECT resource_type, source_record_id, part, cdm_table FROM tb_record WHERE source_kind = 'feed' "
        "AND status <> 'tombstoned'"
    ):
        live[str(table)] += 1
        if (str(t), str(s), int(p)) not in seen:
            gone[str(table)] += 1
    try:
        pct = feedguard.max_drop_pct()
    except feedguard.FeedGuardError as e:
        raise _Refused(str(e)) from None
    bad = feedguard.drops(live, gone, pct)
    if not bad:
        return ""
    what = f"OMOP feed batch {batch} would tombstone {'; '.join(bad)} live records (limit {pct:g} %)"
    reason = feedguard.override_for(batch)
    if not reason:
        raise _Refused(what)
    logging.getLogger("omop").warning("%s: loaded under %s: %s", what, feedguard.OVERRIDE_ENV, reason)
    return f"{what}; override: {reason}"


def _dqd_hold(tx: Any, batch: str, before: dict[str, int]) -> str:
    """T-611 (DATA-009): a feed batch after which the DQD ``isForeignKey`` check of a ``person_id`` (a fact whose person
    left the feed) fails on more rows than before it is held: refused (``_Refused``, the transaction rolls back,
    nothing is loaded and no record is tombstoned) unless ``TB_FEED_DROP_OVERRIDE`` names this batch with a reason,
    which is returned (kept in ``tb_load``). Other Relational checks are not held on: a hospital export may name a
    visit it does not send, which DQD reports and the box has always loaded."""
    from omop.dqd import relational_violations

    after = relational_violations(tx, person_only=True)
    worse = [f"{k}: {before.get(k, 0)} -> {v}" for k, v in sorted(after.items()) if v > before.get(k, 0)]
    if not worse:
        return ""
    what = f"OMOP feed batch {batch} makes the Data Quality checks fail: {'; '.join(worse[:6])}"
    reason = feedguard.override_for(batch)
    if not reason:
        raise _Refused(what)
    logging.getLogger("omop").warning("%s: loaded under %s: %s", what, feedguard.OVERRIDE_ENV, reason)
    return f"{what}; override: {reason}"


def _resolve(tx: Any, kind: str, batch: str, recs: list[Rec], concepts: Concepts, rep: LoadReport) -> None:
    """Ids for every record: the person, provider and care site behind each pseudonym, the visit a fact names,
    the record's own OMOP id (kept across loads), concept ids and the imputed required dates."""
    persons = _map_ids(tx, "person", (r.pid for r in recs if r.pid is not None), "tb_person_seq")
    refs: dict[str, set[str]] = defaultdict(set)
    for r in recs:
        for kind_, sid in r.refs.values():
            refs[kind_].add(sid)
    providers = _map_ids(tx, "provider", refs["provider"], "tb_provider_seq")
    sites = _map_ids(tx, "care_site", refs["care_site"], "tb_care_site_seq")
    existing = {
        (str(t), str(s), int(p)): (tab, rid, fb)
        for t, s, p, tab, rid, fb in tx.fetchall(
            "SELECT resource_type, source_record_id, part, cdm_table, record_id, first_batch FROM tb_record "
            "WHERE source_kind = ?",
            (kind,),
        )
    }

    def keeps_id(r: Rec) -> bool:
        old = existing.get(r.key)
        return old is not None and old[0] == r.table and old[1] is not None

    need = [r for r in recs if r.table in ID_COL and not keeps_id(r)]
    nums = [int(x[0]) for x in tx.fetchall("SELECT nextval('tb_row_seq') FROM generate_series(1, ?)", (len(need),))]
    fresh = dict(zip((id(r) for r in need), nums, strict=True))
    for r in recs:
        old = existing.get(r.key)
        if r.table in ID_COL:
            r.record_id = fresh.get(id(r)) or (old[1] if old else None)
        elif r.table == "person":
            r.record_id = persons[str(r.pid)]
        elif r.table == "provider":
            r.record_id = providers[r.refs["provider_id"][1]]
        r.person_id = persons.get(str(r.pid)) if r.pid is not None else None
        if (
            r.table is not None
            and r.table != "provider"
            and r.person_id is None
            and r.table not in ("tb_appointment", "tb_claim", "tb_consent")
        ):  # an OMOP clinical row needs a person; the record is kept for provenance only
            rep.skipped[f"no_patient:{r.rtype}"] = rep.skipped.get(f"no_patient:{r.rtype}", 0) + 1
            r.table, r.record_id = None, None
        r.row["_first_batch"] = old[2] if old else batch
    # the visit a fact names: this batch's encounters first, then any loaded encounter (another kind's)
    visits = {r.srcid: r.record_id for r in recs if r.table == "visit_occurrence" and r.part == 0}
    want = sorted({sid for r in recs for k, sid in r.refs.values() if k == "visit" and sid not in visits})
    if want:
        visits.update(
            {
                str(s): int(i)
                for s, i in tx.fetchall(
                    "SELECT source_record_id, record_id FROM tb_record WHERE resource_type = 'Encounter' AND part = 0 "
                    "AND record_id IS NOT NULL AND source_record_id = ANY(?) ORDER BY (source_kind = ?) ",
                    (want, kind),
                )
            }
        )
    for r in recs:
        first = _batch_date(str(r.row.pop("_first_batch")))
        for col, (k, sid) in r.refs.items():
            if r.table == "provider":
                continue  # a Practitioner record: its provider row is derived (``_derive``)
            if k == "visit":
                vid = visits.get(sid)
                r.row[col] = vid
                if vid is None:  # names an encounter not loaded: the lake keeps the reference as given
                    r.extra["eid"] = sid
            else:
                r.row[col] = (providers if k == "provider" else sites)[sid]
        if r.table is None:
            continue
        _concepts(r, concepts)
        req = REQUIRED_DATE.get(r.table)
        if req:
            ts_col = {
                "visit_occurrence": "visit_start_datetime",
                "condition_occurrence": "condition_start_datetime",
                "drug_exposure": "drug_exposure_start_datetime",
                "procedure_occurrence": "procedure_datetime",
                "measurement": "measurement_datetime",
                "observation": "observation_datetime",
                "note": "note_datetime",
            }[r.table]
            ts = r.row.get(ts_col)
            fallback = r.row.pop("_fallback_date", None)
            if ts is not None:
                r.row[req] = ts.date()
            elif fallback is not None:
                r.row[req] = fallback
            else:  # no date in the source: the date the record first reached TrialBox, flagged (DQD counts these)
                r.row[req], r.imputed = first, True
            if r.table == "visit_occurrence":
                r.row["visit_end_date"] = r.row[req]
            if r.table == "drug_exposure":
                end = r.row.pop("_end")
                r.row["drug_exposure_end_date"] = end if end is not None else r.row[req]
        r.row.pop("_fallback_date", None)


def _concepts(r: Rec, concepts: Concepts) -> None:
    std = r.row.pop("_std", None)
    src_col = {
        "condition_occurrence": ("condition_concept_id", "condition_source_value", "condition_source_concept_id"),
        "drug_exposure": ("drug_concept_id", "drug_source_value", "drug_source_concept_id"),
        "procedure_occurrence": ("procedure_concept_id", "procedure_source_value", "procedure_source_concept_id"),
        "measurement": ("measurement_concept_id", "measurement_source_value", "measurement_source_concept_id"),
        "observation": ("observation_concept_id", "observation_source_value", "observation_source_concept_id"),
    }.get(str(r.table))
    if src_col:
        concept_col, value_col, source_col = src_col
        code = next((c for c in r.codes if c.domain not in ("Meas Value",)), None)
        r.row[source_col] = concepts.source_id(code.system, code.code) if code else 0
        r.row[concept_col] = concepts.standard_id(*std) if std else 0
        del value_col
    if r.table == "procedure_occurrence" and "procedure_concept_id" not in r.row:
        r.row["procedure_concept_id"] = 0
    if "_value" in r.row:
        vsys, vcode = r.row.pop("_value")
        r.row["value_as_concept_id"] = concepts.source_id(vsys, vcode) or None if vcode else None
    if "_unit" in r.row:
        usys, unit = r.row.pop("_unit")
        r.row["unit_concept_id"] = concepts.standard_id(usys, unit) if unit else None
    if "_class" in r.row:
        csys, ccode = r.row.pop("_class")
        r.row["note_class_concept_id"] = concepts.standard_id(csys, ccode)


def _omop_row(r: Rec) -> dict[str, Any]:
    row = dict(r.row)
    if r.table in ID_COL:
        row[ID_COL[str(r.table)]] = r.record_id
        row["person_id"] = r.person_id
    return row


def _write(
    tx: Any, kind: str, batch: str, recs: list[Rec], files: Mapping[str, str], rep: LoadReport
) -> tuple[set[int], set[int]]:
    """Diff the batch against ``tb_record`` and write inserts, updates, tombstones and restores."""
    old = {
        (str(t), str(s), int(p)): (int(k), tab, rid, sha, st, pid)
        for k, t, s, p, tab, rid, sha, st, pid in tx.fetchall(
            "SELECT record_key, resource_type, source_record_id, part, cdm_table, record_id, content_sha, status, "
            "person_id FROM tb_record WHERE source_kind = ?",
            (kind,),
        )
    }
    seen: set[tuple[str, str, int]] = set()
    staged: list[tuple[Any, ...]] = []
    inserts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deletes: dict[str, list[int]] = defaultdict(list)
    events: list[tuple[Any, ...]] = []  # (key tuple, event, from, to, before_sha)
    persons: set[int] = set()
    providers: set[int] = set()
    for r in recs:
        seen.add(r.key)
        row = _omop_row(r)
        sha = _sha([r.table, row, r.basis, r.extra, r.imputed, r.status if r.status == "rejected" else None])
        prev = old.get(r.key)
        status = r.status
        if prev is None:
            action = "insert"
        elif prev[4] == "tombstoned":
            action = "restore"
        elif prev[3] != sha or prev[1] != r.table or prev[2] != r.record_id:
            action = "update"
        else:
            action, status = "same", prev[4]  # a person's status change survives an unchanged re-load
        if action != "same":
            if prev is not None and prev[1] in ID_COL and prev[2] is not None:
                deletes[str(prev[1])].append(int(prev[2]))
            if r.table in ID_COL:
                inserts[str(r.table)].append(row)
            counter = {"insert": "inserted", "update": "updated", "restore": "restored"}[action]
            setattr(rep, counter, getattr(rep, counter) + 1)
            events.append((r.key, action, prev[4] if prev else None, status, prev[3] if prev else None))
            if r.table == "person" or (prev and prev[1] == "person"):
                persons.update(x for x in (r.record_id, prev[2] if prev else None) if x is not None)
            if r.table == "provider" or (prev and prev[1] == "provider"):
                providers.update(x for x in (r.record_id, prev[2] if prev else None) if x is not None)
        else:
            rep.same += 1
        staged.append(
            (
                kind,
                r.rtype,
                r.srcid,
                r.part,
                r.table,
                r.record_id,
                r.person_id,
                status,
                r.basis,
                batch,
                files.get(r.rtype, f"{r.rtype}.ndjson"),
                r.source_row,
                sha,
                json.dumps(r.extra, default=_iso, sort_keys=True, ensure_ascii=False),
                r.imputed,
                batch,
                batch,
                action,
            )
        )
    gone = [(k, v) for k, v in old.items() if k not in seen and v[4] != "tombstoned"]
    for _, v in gone:
        if v[1] in ID_COL and v[2] is not None:
            deletes[str(v[1])].append(int(v[2]))
        if v[1] == "person" and v[2] is not None:
            persons.add(int(v[2]))
        if v[1] == "provider" and v[2] is not None:
            providers.add(int(v[2]))
    rep.tombstoned = len(gone)
    # before-images of every OMOP row that is replaced or deleted
    before: dict[tuple[str, int], str] = {}
    for table, ids in deletes.items():
        col = ID_COL[table]
        for rid, js in tx.fetchall(f"SELECT {col}, row_to_json(t)::text FROM {table} t WHERE {col} = ANY(?)", (ids,)):
            before[(table, int(rid))] = js
        tx.execute(f"DELETE FROM {table} WHERE {col} = ANY(?)", (ids,))
    for table, rows in inserts.items():
        cols = sorted(set().union(*rows))
        tx.copy_rows(table, cols, ([row.get(c) for c in cols] for row in rows))
        rep.by_table[table] = rep.by_table.get(table, 0) + len(rows)
    tx.execute("CREATE TEMP TABLE tb_in_tmp (LIKE tb_record INCLUDING DEFAULTS, action TEXT) ON COMMIT DROP")
    tx.execute("ALTER TABLE tb_in_tmp DROP COLUMN record_key")
    tx.copy_rows("tb_in_tmp", [*TB_RECORD_COLS, "action"], staged)
    sets = ", ".join(
        f"{c} = i.{c}"
        for c in TB_RECORD_COLS
        if c not in ("source_kind", "resource_type", "source_record_id", "part", "first_batch")
    )
    tx.execute(
        f"UPDATE tb_record r SET {sets}, changed_at = now(), tombstoned_at = NULL FROM tb_in_tmp i "
        "WHERE i.action IN ('update', 'restore') AND (r.source_kind, r.resource_type, r.source_record_id, r.part) "
        "= (i.source_kind, i.resource_type, i.source_record_id, i.part)"
    )
    tx.execute(
        "UPDATE tb_record r SET last_batch = i.last_batch, source_batch = i.source_batch, source_file = "
        "i.source_file, source_row = i.source_row FROM tb_in_tmp i WHERE i.action = 'same' AND (r.source_kind, "
        "r.resource_type, r.source_record_id, r.part) = (i.source_kind, i.resource_type, i.source_record_id, i.part)"
    )
    all_cols = ", ".join(TB_RECORD_COLS)
    tx.execute(f"INSERT INTO tb_record ({all_cols}) SELECT {all_cols} FROM tb_in_tmp WHERE action = 'insert'")
    if gone:
        tx.execute(
            "CREATE TEMP TABLE tb_gone_tmp (resource_type TEXT, source_record_id TEXT, part INTEGER) ON COMMIT DROP"
        )
        tx.copy_rows("tb_gone_tmp", ["resource_type", "source_record_id", "part"], [k for k, _ in gone])
        tx.execute(
            "UPDATE tb_record r SET status = 'tombstoned', tombstoned_at = now(), changed_at = now(), last_batch = ? "
            "FROM tb_gone_tmp g WHERE r.source_kind = ? AND (r.resource_type, r.source_record_id, r.part) = "
            "(g.resource_type, g.source_record_id, g.part)",
            (batch, kind),
        )
    ev_rows = []
    keys = {k: v[0] for k, v in old.items()}
    new_keys = [e[0] for e in events if e[0] not in keys]
    if new_keys:
        tx.execute(
            "CREATE TEMP TABLE tb_keys_tmp (resource_type TEXT, source_record_id TEXT, part INTEGER) ON COMMIT DROP"
        )
        tx.copy_rows("tb_keys_tmp", ["resource_type", "source_record_id", "part"], new_keys)
        for k, t, s, p in tx.fetchall(
            "SELECT r.record_key, r.resource_type, r.source_record_id, r.part FROM tb_record r JOIN tb_keys_tmp k "
            "ON (r.resource_type, r.source_record_id, r.part) = (k.resource_type, k.source_record_id, k.part) "
            "WHERE r.source_kind = ?",
            (kind,),
        ):
            keys[(str(t), str(s), int(p))] = int(k)
    for key, action, frm, to, bsha in events:
        prev = old.get(key)
        bjs = before.get((str(prev[1]), int(prev[2]))) if prev and prev[1] in ID_COL and prev[2] else None
        ev_rows.append((keys[key], batch, action, frm, to, bsha, bjs))
    for _, v in gone:
        bjs = before.get((str(v[1]), int(v[2]))) if v[1] in ID_COL and v[2] is not None else None
        ev_rows.append((v[0], batch, "tombstone", v[4], "tombstoned", v[3], bjs))
    if ev_rows:
        tx.copy_rows(
            "tb_record_event",
            ["record_key", "batch", "event", "from_status", "to_status", "before_sha", "before"],
            ev_rows,
        )
    return persons, providers


def _merge_person(sources: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """The lake's own merge (``flatten.merge_patients``): a field the sources agree on is kept; a field they give
    different values for is a conflict (the value of the first source, the hospital's, is what OMOP holds)."""
    merged: dict[str, Any] = {}
    clash: dict[str, list[Any]] = {}
    for item in ("birth_date", "sex", "deceased_date"):
        vals = [s.get(item) for s in sources if s.get(item) is not None]
        merged[item] = vals[0] if vals else None
        distinct = list(dict.fromkeys(vals))
        if len(distinct) > 1:
            clash[item] = distinct
    return merged, clash


def _derive(tx: Any, persons: set[int], providers: set[int], batch: str, rep: LoadReport, site_name: str) -> None:
    """Rows built from several records: person and death (merged sources, conflicts), provider and care site,
    observation periods, panel relationships and the CDM_SOURCE row."""
    if persons:
        ids = sorted(persons)
        srcs: dict[int, list[dict[str, Any]]] = defaultdict(list)
        claims: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
        for pid, kind, rtype, sid, extra in tx.fetchall(
            "SELECT person_id, source_kind, resource_type, source_record_id, extra FROM tb_record "
            "WHERE cdm_table = 'person' AND status <> 'tombstoned' AND record_id = ANY(?) "
            "ORDER BY record_id, (source_kind = 'site'), source_row",
            (ids,),
        ):
            srcs[int(pid)].append(dict(extra))
            claims[int(pid)].append((str(kind), str(rtype), str(sid)))
        tx.execute("DELETE FROM death WHERE person_id = ANY(?)", (ids,))
        tx.execute("DELETE FROM person WHERE person_id = ANY(?)", (ids,))
        pids = dict(
            tx.fetchall(
                "SELECT omop_id, source_id FROM tb_id_map WHERE id_kind = 'person' AND omop_id = ANY(?)", (ids,)
            )
        )
        prow, drow = [], []
        for pid in ids:
            if not srcs.get(pid):
                _conflicts(tx, pid, {}, [], [], batch)
                continue
            merged, clash = _merge_person(srcs[pid])
            birth = date.fromisoformat(merged["birth_date"]) if merged["birth_date"] else None
            sex = merged["sex"]
            prow.append(
                (
                    pid,
                    vocab.GENDER.get(sex or "", 0),
                    birth.year if birth else 0,
                    birth.month if birth else None,
                    birth.day if birth else None,
                    _as_dt(birth),
                    0,
                    0,
                    str(pids[pid])[:50],
                    sex[:50] if sex else sex,
                )
            )
            if merged["deceased_date"]:
                drow.append((pid, date.fromisoformat(merged["deceased_date"]), vocab.EHR))
            _conflicts(tx, pid, clash, srcs[pid], claims[pid], batch)
        tx.copy_rows(
            "person",
            [
                "person_id",
                "gender_concept_id",
                "year_of_birth",
                "month_of_birth",
                "day_of_birth",
                "birth_datetime",
                "race_concept_id",
                "ethnicity_concept_id",
                "person_source_value",
                "gender_source_value",
            ],
            prow,
        )
        tx.copy_rows("death", ["person_id", "death_date", "death_type_concept_id"], drow)
    if providers:
        ids = sorted(providers)
        tx.execute("DELETE FROM provider WHERE provider_id = ANY(?)", (ids,))
    # every provider and care site a record names has its row (name from the first live Practitioner record)
    tx.execute(
        "INSERT INTO provider (provider_id, provider_name, provider_source_value) "
        "SELECT m.omop_id, (SELECT left(r.extra->>'name', 255) FROM tb_record r WHERE r.cdm_table = 'provider' "
        "AND r.record_id = m.omop_id AND r.status <> 'tombstoned' ORDER BY (r.source_kind = 'site'), r.source_row "
        "LIMIT 1), left(m.source_id, 50) FROM tb_id_map m WHERE m.id_kind = 'provider' "
        "AND NOT EXISTS (SELECT 1 FROM provider p WHERE p.provider_id = m.omop_id)"
    )
    tx.execute(
        "INSERT INTO care_site (care_site_id, care_site_name, care_site_source_value) SELECT m.omop_id, "
        "left(m.source_id, 255), left(m.source_id, 50) FROM tb_id_map m WHERE m.id_kind = 'care_site' "
        "AND NOT EXISTS (SELECT 1 FROM care_site c WHERE c.care_site_id = m.omop_id)"
    )
    tx.execute("DELETE FROM observation_period")
    tx.execute(
        "INSERT INTO observation_period (observation_period_id, person_id, observation_period_start_date, "
        "observation_period_end_date, period_type_concept_id) SELECT x.person_id, x.person_id, min(x.d0), max(x.d1), "
        f"{vocab.EHR} FROM ("
        "SELECT person_id, visit_start_date d0, visit_end_date d1 FROM visit_occurrence UNION ALL "
        "SELECT person_id, condition_start_date, condition_start_date FROM condition_occurrence UNION ALL "
        "SELECT person_id, drug_exposure_start_date, drug_exposure_end_date FROM drug_exposure UNION ALL "
        "SELECT person_id, procedure_date, procedure_date FROM procedure_occurrence UNION ALL "
        "SELECT person_id, measurement_date, measurement_date FROM measurement UNION ALL "
        "SELECT person_id, observation_date, observation_date FROM observation UNION ALL "
        "SELECT person_id, note_date, note_date FROM note) x "
        "WHERE x.person_id IN (SELECT person_id FROM person) GROUP BY x.person_id"
    )
    tx.execute(
        "DELETE FROM fact_relationship WHERE relationship_concept_id IN (?, ?)",
        (vocab.HAS_COMPONENT, vocab.COMPONENT_OF),
    )
    for rel, a, b in ((vocab.HAS_COMPONENT, "p", "c"), (vocab.COMPONENT_OF, "c", "p")):
        tx.execute(
            "INSERT INTO fact_relationship (domain_concept_id_1, fact_id_1, domain_concept_id_2, fact_id_2, "
            f"relationship_concept_id) SELECT ?, {a}.record_id, ?, {b}.record_id, ? FROM tb_record c JOIN tb_record p "
            "ON (p.source_kind, p.resource_type, p.source_record_id, p.part) = "
            "(c.source_kind, c.resource_type, c.source_record_id, 0) WHERE c.part > 0 AND c.cdm_table = 'measurement' "
            "AND p.cdm_table = 'measurement' AND c.status <> 'tombstoned' AND p.status <> 'tombstoned'",
            (vocab.DOMAIN_MEASUREMENT, vocab.DOMAIN_MEASUREMENT, rel),
        )
    rep.conflicts_open = int(tx.fetchval("SELECT count(*) FROM tb_conflict WHERE state = 'open'"))
    tx.execute("DELETE FROM cdm_source")
    tx.execute(
        "INSERT INTO cdm_source (cdm_source_name, cdm_source_abbreviation, cdm_holder, source_description, "
        "source_documentation_reference, cdm_etl_reference, source_release_date, cdm_release_date, cdm_version, "
        "cdm_version_concept_id, vocabulary_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '5.4', 0, ?)",
        (
            f"TrialBox {site_name}".strip()[:255],
            (site_name or "TrialBox")[:25],
            "the hospital (data steward); TrialBox holds it on the site's box",
            "The hospital feed and the site's own inputs, pseudonymised at the door (D-144, D-151).",
            "trialbox/docs/DATA.md",
            "trialbox/services/omop/load.py",
            _batch_date(batch),
            date.today(),
            "TB local, no Athena",
        ),
    )


def _conflicts(
    tx: Any,
    pid: int,
    clash: dict[str, list[Any]],
    sources: list[dict[str, Any]],
    claims: list[tuple[str, str, str]],
    batch: str,
) -> None:
    """Open a conflict per disagreeing item (unless the same disagreement is already recorded, open or resolved);
    withdraw a recorded one the sources no longer give."""
    for item in ("birth_date", "sex", "deceased_date"):
        vals = clash.get(item)
        if not vals:
            tx.execute(
                "UPDATE tb_conflict SET state = 'withdrawn', closed_batch = ? WHERE person_id = ? AND item = ? "
                "AND kind = 'source_vs_source' AND state <> 'withdrawn'",
                (batch, pid, item),
            )
            continue
        vsha = _sha(sorted(str(v) for v in vals))
        tx.execute(
            "UPDATE tb_conflict SET state = 'withdrawn', closed_batch = ? WHERE person_id = ? AND item = ? "
            "AND kind = 'source_vs_source' AND state <> 'withdrawn' AND values_sha <> ?",
            (batch, pid, item, vsha),
        )
        body = [
            {"value": s.get(item), "source": list(c)}
            for s, c in zip(sources, claims, strict=True)
            if s.get(item) is not None
        ]
        tx.execute(
            "INSERT INTO tb_conflict (person_id, kind, item, values_sha, claims, state, detected_batch) "
            "SELECT ?, 'source_vs_source', ?, ?, ?::jsonb, 'open', ? WHERE NOT EXISTS (SELECT 1 FROM tb_conflict "
            "WHERE person_id = ? AND item = ? AND values_sha = ? AND state <> 'withdrawn')",
            (pid, item, vsha, json.dumps(body, ensure_ascii=False), batch, pid, item, vsha),
        )


def resolve_conflict(
    db: Database, conflict_id: int, value: str | None, by: str, reason: str, authority: str = "steward"
) -> None:
    """A person settles a conflict: ``value`` is what the lake reads from now on (None: the item stays unknown).
    A reason is required; nothing is deleted (D-144: the steward for the whole database, a PI for their study)."""
    if not reason.strip():
        raise OmopError("a conflict is resolved with a reason")
    if authority not in ("steward", "pi_clinical_judgement", "hospital_record", "source_owner"):
        raise OmopError(f"unknown authority {authority!r}")
    with db.transaction() as tx:
        n = tx.execute(
            "UPDATE tb_conflict SET state = 'resolved', resolved_value = ?, resolution = ?, reason = ?, "
            "authority = ?, resolved_by = ?, resolved_at = now() WHERE conflict_id = ? AND state = 'open'",
            (value, "value" if value is not None else "unknown", reason, authority, by, conflict_id),
        )
    if n != 1:
        raise OmopError(f"no open conflict {conflict_id}")


def set_status(db: Database, key: tuple[str, str, str, int], to: str, by: str, reason: str) -> None:
    """A person changes a record's status (confirm, sign, reject, supersede), within :data:`TRANSITIONS`; the
    change is an event with actor and reason. ``key``: (kind, resource type, source id, part)."""
    if to not in STATUSES:
        raise OmopError(f"unknown status {to!r}")
    if not reason.strip():
        raise OmopError("a status change needs a reason")
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT record_key, status FROM tb_record WHERE (source_kind, resource_type, source_record_id, part) = "
            "(?, ?, ?, ?) FOR UPDATE",
            key,
        )
        if row is None:
            raise OmopError(f"no record {key}")
        rk, frm = int(row[0]), str(row[1])
        if to not in TRANSITIONS[frm]:
            raise OmopError(f"a {frm} record cannot become {to}")
        tx.execute("UPDATE tb_record SET status = ?, changed_at = now() WHERE record_key = ?", (to, rk))
        tx.execute(
            "INSERT INTO tb_record_event (record_key, event, from_status, to_status, actor, reason) "
            "VALUES (?, 'status', ?, ?, ?, ?)",
            (rk, frm, to, by, reason),
        )
