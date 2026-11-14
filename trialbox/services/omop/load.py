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
  its ``tb_record`` becomes ``tombstoned`` (before-image kept); sent again, it is restored with the same id. A record
  the source itself deleted (the snapshot's ``tombstones.json``: a delta night's SS-MIX2 flag, FHIR ``deleted[]`` or
  CSV ``deleted`` row; passed as ``deleted``) has the reason ``deleted at the source`` on its tombstone event
  (T-305b, D-149); any other is ``left the feed``.
* **Withheld persons** (D-441). A patient the opt-out worker withholds (``tb_withheld``) is kept out of every load:
  their records are left out of the batch, so a live one is tombstoned with the reason ``opted out`` and none is
  restored while the row stands (:func:`withhold` is the worker's call; it tombstones at once).
* **Status and provenance** per record in ``tb_record`` (batch, file, row; first and last batch). A proposed fact is
  loaded (its type concept says so) but never reaches a coded lake table; a refuted diagnosis is ``rejected``.
* **Conflicts.** Two sources that give a patient different birth dates, sexes or dates of death open a
  ``tb_conflict``; the lake reads the item as unknown until a person resolves it (``resolve_conflict``).
* **Routed by domain** (T-106b, STD-031). A condition, measurement or procedure whose concept's domain is
  ``Observation`` (the standard concept's, else the Athena source concept's: an ICD-10 Z code, a LOINC survey item)
  is written to OBSERVATION; with no vocabulary loaded the resource type decides, as before. The lake reads it back
  by its resource type, so the lake does not change. A domain the loader cannot move a row to is counted.
* **Visits end** (STD-018): ``visit_end_datetime`` is the encounter's ``period.end``; ``visit_end_date`` is its day
  (the start day while the patient is still in). **Value concepts** are standard (``value_as_concept_id``: the
  standard Meas Value concept of the answer code, else 0); the answer code itself is kept with the record.
* **Row provenance** (DATA-010): the resource's source table, row hash, ingest night and mapping version are kept
  with the record (``tb_record.extra``, not part of its content: a new night alone is not an update).

The whole batch is one transaction under an advisory lock: a load is all or nothing and two loads never interleave.
The large clinical tables are partitioned by year (``omop.partitions``, T-106): a year's partition is made inside the
same transaction, before the first row of that year is written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from lake.flatten import (
    ATC_SYSTEM,
    DEMOGRAPHIC,
    EARLIEST_YEAR,
    NOT_PRESENT,
    PROVENANCE_COLS,
    SUSPECTED,
    Flattener,
    NotWesternYear,
    basis_of,
    is_atc_system,
    verification_of,
    void,
)
from tb_common import feedguard
from tb_common.config import site_tz
from tb_common.db import Database

from omop import vocab
from omop.partitions import PARTITIONED, ensure_years, years_of
from omop.schema import LOCAL_MIN, STATUSES, TRANSITIONS, OmopError
from omop.vocab import Code, Concepts, standard_vocabulary

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
# T-106b (STD-031): the table each OMOP domain asks for, and the tables a record may leave for OBSERVATION
DOMAIN_TABLE = {
    "Condition": "condition_occurrence",
    "Measurement": "measurement",
    "Observation": "observation",
    "Procedure": "procedure_occurrence",
    "Drug": "drug_exposure",
}
ROUTABLE = ("condition_occurrence", "measurement", "procedure_occurrence")
# a row's columns by role, for the tables a record is routed between (a role the target lacks is not carried)
ROLE: dict[str, dict[str, str]] = {
    "condition_occurrence": {
        "concept": "condition_concept_id",
        "datetime": "condition_start_datetime",
        "date": "condition_start_date",
        "type": "condition_type_concept_id",
        "source_value": "condition_source_value",
        "source_concept": "condition_source_concept_id",
        "qualifier_concept": "condition_status_concept_id",
        "qualifier_source": "condition_status_source_value",
    },
    "measurement": {
        "concept": "measurement_concept_id",
        "datetime": "measurement_datetime",
        "date": "measurement_date",
        "type": "measurement_type_concept_id",
        "source_value": "measurement_source_value",
        "source_concept": "measurement_source_concept_id",
    },
    "procedure_occurrence": {
        "concept": "procedure_concept_id",
        "datetime": "procedure_datetime",
        "date": "procedure_date",
        "type": "procedure_type_concept_id",
        "source_value": "procedure_source_value",
        "source_concept": "procedure_source_concept_id",
    },
    "observation": {
        "concept": "observation_concept_id",
        "datetime": "observation_datetime",
        "date": "observation_date",
        "type": "observation_type_concept_id",
        "source_value": "observation_source_value",
        "source_concept": "observation_source_concept_id",
        "qualifier_concept": "qualifier_concept_id",
        "qualifier_source": "qualifier_source_value",
    },
}
# columns of the same name in a home table and OBSERVATION
SAME_NAME = (
    "visit_occurrence_id",
    "provider_id",
    "value_as_number",
    "value_as_concept_id",
    "unit_concept_id",
    "unit_source_value",
    "value_source_value",
)


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
    # D-597: the code whose domain routes the record when it is not the source code (a mapped diagnosis)
    route: tuple[str | None, str] | None = None
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
        self.fl = Flattener(tz, earliest_year=EARLIEST_YEAR)  # NEW-B-2 (D-521): no year of another calendar
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
            out.extra = {k: _iso(p[k]) for k in ("birth_date", "sex", "deceased_date", "deceased")}
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
                "visit_end_datetime": e["end"],
                "visit_type_concept_id": self.type_concept(status),
                "visit_source_concept_id": None,
            }
            self._text(out, "visit_source_value", e["class"], "class")
            if e["status"] is not None:
                out.extra["status"] = e["status"]
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
        if rtype in ("MedicationRequest", "MedicationStatement"):
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
        system, code = c["system"], c["code"]
        own = _own_coding(r.get("code"), code)
        if own is not None:
            # D-597: a mapped diagnosis (D-593). The source value and its concept are the hospital's own code; the
            # standard concept is found through the mapped code, which the lake reads (kept in ``extra``, as the
            # lake built from the feed reads the first coding)
            self._code(out, "condition_source_value", own[0], own[1], self._display(r.get("code"), own[1]), "Condition")
            out.extra["code"], out.extra["system"] = code, system
            out.route = (system, code)  # the mapped code's domain routes the record, as a recorded one's does
        else:
            self._code(out, "condition_source_value", system, code, self._display(r.get("code"), code), "Condition")
        out.row["_std"] = (system, code)
        self._text(out, "condition_status_source_value", c["status"], "status")
        if c["eid"] is not None:
            out.refs["visit_occurrence_id"] = ("visit", c["eid"])
        return out

    def medication(self, r: Resource, out: Rec) -> Rec:
        m = self.fl.medication(r)
        out.table, out.pid = "drug_exposure", m["pid"]
        cc = self.fl.medication_concept(r)  # T-616: a medicationReference resolved as the lake resolves it
        nhi = atc = nhi_sys = atc_sys = None
        for c in cc.get("coding") or []:  # the flattener's own reading (``Flattener.medication``), systems kept
            if is_atc_system(c.get("system")):  # D-536: the flattener's own test, so the two readings agree
                # the system by its one name, so the vocabulary finds it whichever accepted spelling was sent
                atc, atc_sys = c.get("code"), ATC_SYSTEM
            elif nhi is None:
                nhi, nhi_sys = c.get("code"), c.get("system")
        if (nhi, atc) != (m["nhi_code"], m["atc"]):  # the two readings must agree
            # D-681: the resource type and the feed line, not the record's id nor a code of the row
            raise OmopError(
                f"{out.rtype} line {out.source_row}: the medication's codes read differently from the lake's flattener"
            )
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
            if o["value_code"] is not None:  # STD-031: the row holds the standard answer concept; the code is kept
                out.extra["value_code"] = o["value_code"]
                out.std_only.append((vsys, o["value_code"]))
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
    by_type: Mapping[str, Iterable[Resource]],
    files: Mapping[str, str] | None = None,
    tz: str | None = None,
    site_name: str = "",
    deleted: Mapping[str, Iterable[str]] | None = None,
) -> LoadReport:
    """Load one complete batch of ``kind``; return what changed. See the module docstring. ``deleted``: resource
    type -> source ids the source deleted in this batch (``tombstones.json``), for the tombstone's reason.

    NEW-B-37 (D-678): the values of ``by_type`` may be streams (``adapter.ndjson.readers``); the batch is taken a
    chunk of :func:`load_chunk` records at a time. ``Medication`` and ``ClaimResponse`` are read twice (the index the
    other records name them by, then as records), so their values must be re-readable."""
    if kind not in KINDS:
        raise OmopError(f"unknown source kind {kind!r}")
    t0 = time.perf_counter()
    rep = LoadReport(kind, batch)
    stats: dict[str, int] = {}
    files = files or {}
    tz = site_tz(tz)  # the site's zone; TB_TZ when not given, never a default (D-315)
    b = _Builder(tz, kind, stats)
    # T-616 (STD-014): a medicationReference to a Medication of the batch (the flattener's own index)
    b.fl.medications = {str(m["id"]): m for m in by_type.get("Medication", []) if m.get("id")}
    responses = {}
    for cr in by_type.get("ClaimResponse", []):  # the flattener's join: the last response to a claim wins
        req = ((cr.get("request") or {}).get("reference") or "").split("/")[-1]
        responses[req] = cr
    dead = {(str(t), str(i)) for t, ids in (deleted or {}).items() for i in ids}
    try:
        return _load(db, kind, batch, by_type, b, responses, files, site_name, stats, rep, t0, dead, load_chunk())
    except _NotWestern as w:
        # NEW-B-2 (D-521): one date of another calendar refuses the batch whole; the load's transaction is rolled
        # back with everything staged or written so far, and the refusal is kept (D-271)
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO tb_load (source_kind, batch, seconds, counts) VALUES (?, ?, 0, ?::jsonb)",
                (f"{kind}-refused", batch, json.dumps({"refused": str(w)})),
            )
        raise OmopError(
            f"{w}: refused, nothing loaded (the lake keeps its CURRENT snapshot). Correct the feed's "
            "dates to the western calendar and run the night again"
        ) from None
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


#: NEW-B-37 (D-678): the records one chunk of a load holds. Measured before the change: about 9.5 KB of memory a
#: resource while the whole batch was held (1,000 dense patients: 559,056 resources, 5.4 GiB). Unset: a sixteenth of
#: the process's memory cap at that size, as the ingest's sort runs take theirs (D-473)
CHUNK_ENV = "TB_OMOP_LOAD_CHUNK"
RECORD_BYTES = 9_500  # the measured memory of one resource with its records in the load (D-678)
CAP_SHARE = 16  # the share of the cap one chunk may take, the ingest sort's (adapter.ndjson.sort_run_bytes)


def load_chunk() -> int:
    """How many records one chunk of a load holds: ``TB_OMOP_LOAD_CHUNK``, else derived from the memory cap."""
    raw = os.environ.get(CHUNK_ENV, "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            raise OmopError(f"{CHUNK_ENV} must be a whole number of records") from None
        if n < 1:
            raise OmopError(f"{CHUNK_ENV} must be a whole number of records") from None
        return n
    from adapter.ndjson import _memory_cap

    return max(1, _memory_cap() // CAP_SHARE // RECORD_BYTES)


class _NotWestern(Exception):
    """A date of another calendar in the batch (NEW-B-2, D-521): the whole batch is refused."""


class _Refused(Exception):
    """A feed batch that would tombstone (nearly) every live person (D-271)."""


def _load(
    db: Database,
    kind: str,
    batch: str,
    by_type: Mapping[str, Iterable[Resource]],
    b: _Builder,
    responses: Mapping[str, Resource],
    files: Mapping[str, str],
    site_name: str,
    stats: dict[str, int],
    rep: LoadReport,
    t0: float,
    dead: set[tuple[str, str]],
    chunk: int,
) -> LoadReport:
    """The batch in one transaction, a chunk of records at a time (NEW-B-37, D-678): the records are built and
    staged in a temporary table of the transaction (the last line of a key wins there), then every step reads them
    back in chunks: the guard, the ids, the concepts, the routing, the diff with ``tb_record`` and the writes; what
    the batch no longer carries is found in the database. Nothing of the batch is held whole."""
    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('trialbox-omop-load'))")
        last = tx.fetchval("SELECT max(batch) FROM tb_load WHERE source_kind = ?", (kind,))
        if last is not None and batch < str(last):
            raise OmopError(
                f"OMOP holds {kind} batch {last}; refusing the older batch {batch} (a store of record "
                "moves forward; an older snapshot's lake is kept as it was built)"
            )
        held = {str(r[0]) for r in tx.fetchall("SELECT pid FROM tb_withheld")}  # D-441
        _stage(tx, b, by_type, responses, stats, held, chunk)
        dqd_before: dict[str, int] | None = None
        if kind == "feed":
            rep.override = _tombstone_guard(tx, batch)
            from omop.dqd import relational_violations

            dqd_before = relational_violations(tx, person_only=True)
        concepts = Concepts(tx)
        persons, providers, sites = _ids_of(tx)
        _assign(tx, kind, batch, persons, providers, rep, chunk)
        affected_persons: set[int] = set()
        affected_providers: set[int] = set()
        # every code's local concept minted before any record is resolved, as for the batch whole: one stream of the
        # batch's codes (the concepts keep only the distinct ones), its standard-only lookups gathered first
        std_only = dict.fromkeys(_staged_codes(tx, chunk, "std"))
        concepts.prepare(_staged_codes(tx, chunk, "codes"), list(std_only))
        for recs in _staged(tx, chunk):
            _resolve(tx, kind, recs, concepts, providers, sites, rep)
            ap, aq = _write(tx, kind, batch, recs, files, rep)
            affected_persons |= ap
            affected_providers |= aq
        ap, aq = _tombstone(tx, kind, batch, rep, dead, chunk)
        affected_persons |= ap
        affected_providers |= aq
        _derive(tx, affected_persons, affected_providers, batch, rep, site_name)
        if kind == "site":
            _note_nlp(tx, kind, batch)
        if dqd_before is not None:
            held_msg = _dqd_hold(tx, batch, dqd_before)
            rep.override = "; ".join(x for x in (rep.override, held_msg) if x)
        rep.concepts_minted = concepts.minted
        rep.skipped = dict(sorted({**stats, **rep.skipped}.items()))
        rep.seconds = round(time.perf_counter() - t0, 2)
        tx.execute(
            "INSERT INTO tb_load (source_kind, batch, seconds, counts) VALUES (?, ?, ?, ?::jsonb)",
            (kind, batch, rep.seconds, json.dumps(rep.as_dict())),
        )
    return rep


# ------------------------------------------------------------------------------------- the staged batch (D-678)
_KEY = "(resource_type, source_record_id, part)"
_STAGE_COLS = [
    "seq", "resource_type", "source_record_id", "part", "held", "pid", "providers", "sites", "cdm_table",
    "provider_id", "codes", "std", "rec",
]  # fmt: skip


def _stage(
    tx: Any,
    b: _Builder,
    by_type: Mapping[str, Iterable[Resource]],
    responses: Mapping[str, Resource],
    stats: dict[str, int],
    held: set[str],
    chunk: int,
) -> None:
    """Build every record of the batch, in the batch's order (types sorted, then line by line), and keep it in the
    transaction's ``tb_load_stage``: one row per key, the last line of a key winning (as the NDJSON merge does)
    with the position of that line. A record of a withheld patient is kept marked ``held`` (D-441): it counts as
    sent for the guard, and is tombstoned as opted out."""
    tx.execute(
        "CREATE TEMP TABLE tb_load_stage (seq BIGINT NOT NULL, resource_type TEXT NOT NULL, source_record_id TEXT "
        "NOT NULL, part INTEGER NOT NULL, held BOOLEAN NOT NULL, pid TEXT, providers TEXT[], sites TEXT[], "
        "cdm_table TEXT, provider_id TEXT, codes TEXT, std TEXT, rec TEXT NOT NULL, record_id BIGINT, "
        "person_id BIGINT, first_batch TEXT, PRIMARY KEY (resource_type, source_record_id, part)) "
        "ON COMMIT DROP"
    )
    tx.execute("CREATE INDEX ON tb_load_stage (seq)")
    pending: dict[tuple[str, str, int], tuple[Any, ...]] = {}
    seq = 0

    def flush() -> None:
        if not pending:
            return
        tx.execute("DROP TABLE IF EXISTS tb_load_in")
        tx.execute("CREATE TEMP TABLE tb_load_in (LIKE tb_load_stage) ON COMMIT DROP")
        tx.copy_rows("tb_load_in", _STAGE_COLS, pending.values())
        again = int(tx.fetchval(f"SELECT count(*) FROM tb_load_in i JOIN tb_load_stage s USING {_KEY}") or 0)
        if again:  # one id twice in a file: the last line wins, as the NDJSON merge does
            stats["duplicate_id"] = stats.get("duplicate_id", 0) + again
        cols = ", ".join(_STAGE_COLS)
        tx.execute(
            f"INSERT INTO tb_load_stage ({cols}) SELECT {cols} FROM tb_load_in ON CONFLICT {_KEY} DO UPDATE SET "
            + ", ".join(
                f"{c} = EXCLUDED.{c}" for c in _STAGE_COLS if c not in ("resource_type", "source_record_id", "part")
            )
        )
        pending.clear()

    for rtype in sorted(by_type):
        for line, r in enumerate(by_type[rtype], start=1):
            prov = {k: _iso(v) for k, v in b.fl.provenance(r).items() if v is not None}
            from_note = note_source(r)
            try:
                built = b.build(rtype, r, line, responses)
            except NotWesternYear as exc:
                raise _NotWestern(f"{rtype} line {line}: {exc}") from None
            for rec in built:
                rec.extra.update(prov)  # DATA-010: kept with the record, outside its content sha
                if from_note and rec.part == 0:  # T-202: a fact read from a chart, for NOTE_NLP
                    rec.extra["from_note"], rec.extra["from_note_term"] = from_note
                seq += 1
                if rec.key in pending:
                    stats["duplicate_id"] = stats.get("duplicate_id", 0) + 1
                    del pending[rec.key]
                out = rec.pid in held and rec.table not in KEEP_WITHHELD
                pending[rec.key] = (
                    seq, rec.rtype, rec.srcid, rec.part, out, rec.pid,
                    sorted({sid for k, sid in rec.refs.values() if k == "provider"}),
                    sorted({sid for k, sid in rec.refs.values() if k == "care_site"}),
                    rec.table,
                    rec.refs["provider_id"][1] if "provider_id" in rec.refs else None,
                    json.dumps([[c.system, c.code, c.display, c.domain] for c in rec.codes], ensure_ascii=False),
                    json.dumps(rec.std_only, ensure_ascii=False),
                    _pack(rec),
                )  # fmt: skip
                if len(pending) >= chunk:
                    flush()
    flush()


def _staged(tx: Any, chunk: int) -> Iterable[list[Rec]]:
    """The staged records of patients who are not withheld, in the batch's order, a chunk at a time, with the ids
    :func:`_assign` gave them."""
    after = -1
    while True:
        rows = tx.fetchall(
            "SELECT seq, rec, cdm_table, record_id, person_id, first_batch FROM tb_load_stage WHERE NOT held "
            "AND seq > ? ORDER BY seq LIMIT ?",
            (after, chunk),
        )
        if not rows:
            return
        after = int(rows[-1][0])
        out = []
        for _, text, table, record_id, person_id, first in rows:
            r = _unpack(text)
            r.table, r.record_id, r.person_id = table, record_id, person_id
            r.row["_first_batch"] = first
            out.append(r)
        yield out


def _staged_codes(tx: Any, chunk: int, column: str) -> Iterator[Any]:
    """The staged records' codes (``codes``) or standard-only lookups (``std``), one at a time in the batch's order."""
    after = -1
    while True:
        rows = tx.fetchall(
            f"SELECT seq, {column} FROM tb_load_stage WHERE NOT held AND seq > ? ORDER BY seq LIMIT ?", (after, chunk)
        )
        if not rows:
            return
        after = int(rows[-1][0])
        for _, text in rows:
            for x in json.loads(text):
                yield Code(*x) if column == "codes" else tuple(x)


def _encoded(v: Any) -> Any:
    if isinstance(v, datetime):  # before date: a datetime is a date
        return {"~dt": v.isoformat()}
    if isinstance(v, date):
        return {"~d": v.isoformat()}
    if isinstance(v, Decimal):
        return {"~n": str(v)}
    if isinstance(v, Code):
        return {"~c": [v.system, v.code, v.display, v.domain]}
    raise TypeError(f"a staged record holds a {type(v).__name__}")


def _decoded(d: dict[str, Any]) -> Any:
    if len(d) == 1:
        ((k, x),) = d.items()
        if k == "~dt":
            return datetime.fromisoformat(x)
        if k == "~d":
            return date.fromisoformat(x)
        if k == "~n":
            return Decimal(x)
        if k == "~c":
            return Code(*x)
    return d


def _pack(r: Rec) -> str:
    """A staged record as text, each value with its type (a date, a datetime, a decimal, a code), so that it reads
    back as it was built and its content sha is the same (D-678). The ids are kept beside it (:func:`_assign`)."""
    return json.dumps(
        {f: getattr(r, f) for f in Rec.__dataclass_fields__ if f not in ("record_id", "person_id")},
        default=_encoded,
        ensure_ascii=False,
    )


def _unpack(text: str) -> Rec:
    d = json.loads(text, object_hook=_decoded)
    d["refs"] = {k: tuple(v) for k, v in d["refs"].items()}
    d["std_only"] = [tuple(x) for x in d["std_only"]]
    d["route"] = tuple(d["route"]) if d["route"] is not None else None
    return Rec(**d)


def _keys_table(tx: Any, recs: Iterable[Rec]) -> None:
    """The keys of one chunk, for a join with ``tb_record``."""
    tx.execute("DROP TABLE IF EXISTS tb_load_keys")
    tx.execute(
        "CREATE TEMP TABLE tb_load_keys (resource_type TEXT, source_record_id TEXT, part INTEGER) ON COMMIT DROP"
    )
    tx.copy_rows(
        "tb_load_keys", ["resource_type", "source_record_id", "part"], ((r.rtype, r.srcid, r.part) for r in recs)
    )


def _ids_of(tx: Any) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """The person, provider and care site ids of every pseudonym the batch names (minted once, ``tb_id_map``):
    one map each, as large as the patients, staff and departments, not the records."""
    pids = [str(x[0]) for x in tx.fetchall("SELECT DISTINCT pid FROM tb_load_stage WHERE NOT held AND pid IS NOT NULL")]
    provs = [str(x[0]) for x in tx.fetchall("SELECT DISTINCT unnest(providers) FROM tb_load_stage WHERE NOT held")]
    sites = [str(x[0]) for x in tx.fetchall("SELECT DISTINCT unnest(sites) FROM tb_load_stage WHERE NOT held")]
    return (
        _map_ids(tx, "person", pids, "tb_person_seq"),
        _map_ids(tx, "provider", provs, "tb_provider_seq"),
        _map_ids(tx, "care_site", sites, "tb_care_site_seq"),
    )


#: the extension a site fact read from a chart carries (``sitesetup.publish``): the chart's DocumentReference id
NOTE_SOURCE = "urn:trialbox:note-source"


def note_source(r: Resource) -> tuple[str, str] | None:
    """``(DocumentReference id, the term as read)`` of a resource read from a chart (:data:`NOTE_SOURCE`), else None."""
    for ext in r.get("extension") or []:
        if ext.get("url") == NOTE_SOURCE:
            ref = ext.get("valueReference") or {}
            rid = str(ref.get("reference") or "")
            if rid.startswith("DocumentReference/") and rid.split("/", 1)[1]:
                return rid.split("/", 1)[1], str(ref.get("display") or "")
    return None


def _note_nlp(tx: Any, kind: str, batch: str) -> None:
    """NOTE_NLP from the site's facts (T-202): one row per live fact of ``kind`` read from a chart that is itself a
    live NOTE of the same kind; rewritten whole at every load of the kind. The term is the fact's own text (the chart
    text the lake holds is redacted; the fact's quote never leaves site setup); ``term_modifiers`` keeps its status
    (proposed, confirmed, ...), so a person's decision shows. The id is the fact's own OMOP row id."""
    tx.execute(
        "DELETE FROM note_nlp WHERE note_id IN (SELECT record_id FROM tb_record WHERE source_kind = ? "
        "AND cdm_table = 'note' AND record_id IS NOT NULL)",
        (kind,),
    )
    tx.execute(
        "INSERT INTO note_nlp (note_nlp_id, note_id, lexical_variant, note_nlp_concept_id, note_nlp_source_concept_id, "
        "nlp_system, nlp_date, term_exists, term_modifiers) SELECT f.record_id, n.record_id, "
        "left(coalesce(nullif(f.extra->>'from_note_term', ''), f.resource_type), 250), 0, 0, 'TrialBox site setup', "
        "coalesce(nt.note_date, ?), 'Y', 'status=' || f.status FROM tb_record f JOIN tb_record n "
        "ON n.source_kind = f.source_kind AND n.resource_type = 'DocumentReference' "
        "AND n.source_record_id = f.extra->>'from_note' AND n.part = 0 JOIN note nt ON nt.note_id = n.record_id "
        "WHERE f.source_kind = ? AND f.part = 0 AND f.record_id IS NOT NULL "
        "AND f.status NOT IN ('tombstoned', 'superseded') AND n.status NOT IN ('tombstoned', 'superseded')",
        (_batch_date(batch), kind),
    )


def _tombstone_guard(tx: Any, batch: str) -> str:
    """D-271: a feed batch that would tombstone every live record of a CDM table (persons, conditions, measurements,
    ...), or more than ``TB_FEED_MAX_DROP_PCT`` (default 20) % of them, is a missing or broken extract, not a hospital
    that lost its data overnight: refused (``_Refused``) unless ``TB_FEED_DROP_OVERRIDE`` names this batch with a
    reason, which is returned (kept in ``tb_load``). The records the batch sends are the staged ones, a withheld
    patient's too (D-678: counted in the database, not in memory)."""
    live: dict[str, int] = defaultdict(int)
    gone: dict[str, int] = defaultdict(int)
    for table, n, missing in tx.fetchall(
        "SELECT r.cdm_table, count(*), count(*) FILTER (WHERE s.seq IS NULL) FROM tb_record r LEFT JOIN "
        "tb_load_stage s ON (s.resource_type, s.source_record_id, s.part) = "
        "(r.resource_type, r.source_record_id, r.part) WHERE r.source_kind = 'feed' AND r.status <> 'tombstoned' "
        "GROUP BY r.cdm_table"
    ):
        live[str(table)] += int(n)
        if missing:
            gone[str(table)] += int(missing)
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


def _assign(
    tx: Any,
    kind: str,
    batch: str,
    persons: Mapping[str, int],
    providers: Mapping[str, int],
    rep: LoadReport,
    chunk: int,
) -> None:
    """The ids of every staged record, in the batch's order, a chunk at a time: the person behind its pseudonym, the
    record's own OMOP id (kept across loads, else the next of ``tb_row_seq``) and the batch it first came in. A
    clinical record without a person is kept for provenance only. Before any record is resolved further, so that a
    fact can name the visit of an encounter later in the batch (D-678). Kept beside the staged record."""
    after = -1
    while True:
        rows = tx.fetchall(
            "SELECT seq, resource_type, source_record_id, part, cdm_table, pid, provider_id FROM tb_load_stage "
            "WHERE NOT held AND seq > ? ORDER BY seq LIMIT ?",
            (after, chunk),
        )
        if not rows:
            return
        after = int(rows[-1][0])
        tx.execute("DROP TABLE IF EXISTS tb_load_keys")
        tx.execute(
            "CREATE TEMP TABLE tb_load_keys (resource_type TEXT, source_record_id TEXT, part INTEGER) ON COMMIT DROP"
        )
        tx.copy_rows("tb_load_keys", ["resource_type", "source_record_id", "part"], (r[1:4] for r in rows))
        existing = {
            (str(t), str(s_), int(p_)): (tab, rid, fb)
            for t, s_, p_, tab, rid, fb in tx.fetchall(
                "SELECT r.resource_type, r.source_record_id, r.part, r.cdm_table, r.record_id, r.first_batch FROM "
                "tb_record r JOIN tb_load_keys k ON (r.resource_type, r.source_record_id, r.part) = "
                "(k.resource_type, k.source_record_id, k.part) WHERE r.source_kind = ?",
                (kind,),
            )
        }

        def keeps_id(
            key: tuple[str, str, int], table: str | None, existing: dict[tuple[str, str, int], Any] = existing
        ) -> bool:
            old = existing.get(key)
            if old is None or old[1] is None:
                return False
            # a record routed to OBSERVATION by its domain (``_route``, after this) keeps its id there too
            return old[0] == table or (table in ROUTABLE and old[0] == "observation")

        keyed = [((str(t), str(s_), int(p_)), tab, pid, prov) for _, t, s_, p_, tab, pid, prov in rows]
        need = sum(1 for key, tab, _, _ in keyed if tab in ID_COL and not keeps_id(key, tab))
        nums = iter(int(x[0]) for x in tx.fetchall("SELECT nextval('tb_row_seq') FROM generate_series(1, ?)", (need,)))
        back = []
        for key, table, pid, prov in keyed:
            old = existing.get(key)
            record_id: int | None = None
            if table in ID_COL:
                record_id = next(nums) if not keeps_id(key, table) else (old[1] if old else None)
            elif table == "person":
                record_id = persons[str(pid)]
            elif table == "provider":
                record_id = providers[str(prov)]
            person_id = persons.get(str(pid)) if pid is not None else None
            if (
                table is not None
                and table != "provider"
                and person_id is None
                and table not in ("tb_appointment", "tb_claim", "tb_consent")
            ):  # an OMOP clinical row needs a person; the record is kept for provenance only
                rep.skipped[f"no_patient:{key[0]}"] = rep.skipped.get(f"no_patient:{key[0]}", 0) + 1
                table, record_id = None, None
            back.append((*key, table, record_id, person_id, old[2] if old else batch))
        tx.execute("DROP TABLE IF EXISTS tb_load_back")
        tx.execute(
            "CREATE TEMP TABLE tb_load_back (resource_type TEXT, source_record_id TEXT, part INTEGER, cdm_table TEXT, "
            "record_id BIGINT, person_id BIGINT, first_batch TEXT) ON COMMIT DROP"
        )
        tx.copy_rows(
            "tb_load_back",
            ["resource_type", "source_record_id", "part", "cdm_table", "record_id", "person_id", "first_batch"],
            back,
        )
        tx.execute(
            "UPDATE tb_load_stage s SET cdm_table = k.cdm_table, record_id = k.record_id, person_id = k.person_id, "
            "first_batch = k.first_batch FROM tb_load_back k WHERE (s.resource_type, s.source_record_id, s.part) = "
            "(k.resource_type, k.source_record_id, k.part)"
        )


def _resolve(
    tx: Any,
    kind: str,
    recs: list[Rec],
    concepts: Concepts,
    providers: Mapping[str, int],
    sites: Mapping[str, int],
    rep: LoadReport,
) -> None:
    """The rest of one chunk's ids (the visit a fact names, providers, care sites), its concepts, the imputed
    required dates and the table of its concept's domain."""
    # the visit a fact names: this batch's encounters first (staged, any chunk), then any loaded encounter (another
    # kind's)
    named = sorted({sid for r in recs for k, sid in r.refs.values() if k == "visit"})
    visits: dict[str, Any] = {}
    if named:
        for sid, rid in tx.fetchall(
            "SELECT source_record_id, record_id FROM tb_load_stage WHERE NOT held AND cdm_table = 'visit_occurrence' "
            "AND part = 0 AND source_record_id = ANY(?) ORDER BY seq",
            (named,),
        ):
            visits[str(sid)] = rid
    want = sorted(sid for sid in named if sid not in visits)
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
            if r.table == "visit_occurrence":  # STD-018: the end's day; the start's while the patient is in
                end = r.row.get("visit_end_datetime")
                r.row["visit_end_date"] = max(end.date(), r.row[req]) if end is not None else r.row[req]
            if r.table == "drug_exposure":
                end = r.row.pop("_end")
                r.row["drug_exposure_end_date"] = end if end is not None else r.row[req]
        r.row.pop("_fallback_date", None)
    _route(tx, recs, rep)


def _route(tx: Any, recs: list[Rec], rep: LoadReport) -> None:
    """STD-031: a record goes to the table of its concept's domain. The domain is the standard concept's; with none
    (0), the OHDSI source concept's for the same code (an ICD-10-CM Z code is ``Observation`` in Athena); with no
    vocabulary loaded neither exists and the resource type decides. A condition, measurement or procedure of the
    ``Observation`` domain moves to OBSERVATION; another domain than its table's is counted
    (``domain_kept:<table>:<domain>``), not moved."""
    cands = [r for r in recs if r.table in ROUTABLE]
    if not cands:
        return
    std_ids = sorted({int(r.row.get(ROLE[str(r.table)]["concept"]) or 0) for r in cands} - {0})
    std_dom: dict[int, str] = {}
    if std_ids:
        rows = tx.fetchall("SELECT concept_id, domain_id FROM concept WHERE concept_id = ANY(?)", (std_ids,))
        std_dom = {int(c): str(d) for c, d in rows}
    src_of: dict[int, tuple[str, str]] = {}
    want: dict[str, set[str]] = defaultdict(set)
    for r in cands:
        code = next((c for c in r.codes if c.domain != "Meas Value"), None)
        by = r.route or ((code.system, code.code) if code else None)
        sv = standard_vocabulary(by[0]) if by else None
        if by and sv:
            src_of[id(r)] = (sv, by[1])
            want[sv].add(by[1])
    src_dom: dict[tuple[str, str], str] = {}
    for sv, codes in want.items():
        for code, dom in tx.fetchall(
            "SELECT concept_code, domain_id FROM concept WHERE vocabulary_id = ? AND concept_code = ANY(?) "
            "AND concept_id > 0 AND concept_id < ? ORDER BY concept_id",
            (sv, sorted(codes), LOCAL_MIN),
        ):
            src_dom.setdefault((sv, str(code)), str(dom))
    for r in cands:
        home = str(r.table)
        std = int(r.row.get(ROLE[home]["concept"]) or 0)
        domain = std_dom.get(std) if std else src_dom.get(src_of.get(id(r), ("", "")))
        target = DOMAIN_TABLE.get(domain or "")
        if target is None or target == home:
            continue
        if target != "observation":
            key = f"domain_kept:{home}:{domain}"
            rep.skipped[key] = rep.skipped.get(key, 0) + 1
            continue
        _to_observation(r)
        rep.skipped[f"routed:{home}:observation"] = rep.skipped.get(f"routed:{home}:observation", 0) + 1


def _to_observation(r: Rec) -> None:
    """The record's row, written as an OBSERVATION row: each column by its role; the measurement operator, which
    OBSERVATION has no column for, is kept with the record (read back as the lake's ``value_cmp``)."""
    home_table = str(r.table)
    home, to = ROLE[home_table], ROLE["observation"]
    row: dict[str, Any] = {}
    for role, col in home.items():
        if col in r.row:
            row[to[role]] = r.row.pop(col)
    for col in SAME_NAME:
        if col in r.row:
            row[col] = r.row.pop(col)
    op = r.row.pop("operator_concept_id", None)
    if op:
        r.extra["value_cmp"] = vocab.OPERATOR_CODE.get(op)
    if r.row:
        # D-681: column names are the schema's; the record's id and the values under them stay out of the text
        raise OmopError(
            f"{r.rtype} line {r.source_row} ({home_table}): no OBSERVATION column for {', '.join(sorted(r.row))}"
        )
    r.row, r.table = row, "observation"


_ICD10CM, _ICD9CM = "http://hl7.org/fhir/sid/icd-10-cm", "http://hl7.org/fhir/sid/icd-9-cm"  # the pair of D-593


def _own_coding(cc: dict[str, Any] | None, read: str | None) -> tuple[str | None, str] | None:
    """``(system, code)`` of the hospital's own coding when the code the flattener read (``read``, the first
    coding) is the one the map gave (D-593): the first coding is ICD-10-CM marked ``userSelected: false`` and a
    later one is the hospital's ICD-9-CM code. Any other shape is None and the record loads as before: a first
    coding another source flags for its own reasons, a mapped coding alone, a hospital code too long to be a
    source concept."""
    codings = [c for c in (cc or {}).get("coding") or [] if c.get("code")]
    if not codings or codings[0].get("code") != read or codings[0].get("userSelected") is not False:
        return None
    if codings[0].get("system") != _ICD10CM:
        return None
    own = next((c for c in codings[1:] if c.get("system") == _ICD9CM and c.get("userSelected") is not False), None)
    if own is None or len(str(own["code"])) > 50:
        return None
    return (own.get("system"), str(own["code"]))


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
    if "_value" in r.row:  # STD-031: the standard answer concept (0: none in the vocabulary); the code is in extra
        vsys, vcode = r.row.pop("_value")
        r.row["value_as_concept_id"] = concepts.standard_id(vsys, vcode) if vcode else None
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


#: the reasons on a tombstone event (T-305b): the source said so, or the record is simply not in the batch any more
DELETED_AT_SOURCE = "deleted at the source"
LEFT_THE_FEED = "left the feed"
#: D-441: the patient is withheld by the opt-out worker (``tb_withheld``)
OPTED_OUT = "opted out"


def _write(
    tx: Any,
    kind: str,
    batch: str,
    recs: list[Rec],
    files: Mapping[str, str],
    rep: LoadReport,
) -> tuple[set[int], set[int]]:
    """Diff one chunk of the batch against ``tb_record`` (the chunk's own keys, read by a join: D-678) and write its
    inserts, updates and restores. What the batch no longer carries is :func:`_tombstone`'s."""
    _keys_table(tx, recs)
    old = {
        (str(t), str(s), int(p)): (int(k), tab, rid, sha, st, pid)
        for k, t, s, p, tab, rid, sha, st, pid in tx.fetchall(
            "SELECT r.record_key, r.resource_type, r.source_record_id, r.part, r.cdm_table, r.record_id, "
            "r.content_sha, r.status, r.person_id FROM tb_record r JOIN tb_load_keys k ON (r.resource_type, "
            "r.source_record_id, r.part) = (k.resource_type, k.source_record_id, k.part) WHERE r.source_kind = ?",
            (kind,),
        )
    }
    staged: list[tuple[Any, ...]] = []
    inserts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    deletes: dict[str, list[int]] = defaultdict(list)
    events: list[tuple[Any, ...]] = []  # (key tuple, event, from, to, before_sha)
    persons: set[int] = set()
    providers: set[int] = set()
    for r in recs:
        row = _omop_row(r)
        content = {k: v for k, v in r.extra.items() if k not in PROVENANCE_COLS}  # a new night alone is no update
        sha = _sha([r.table, row, r.basis, content, r.imputed, r.status if r.status == "rejected" else None])
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
    # T-202 (D-384): the record's own before-image, for the lake exported as of an earlier time (omop.export)
    changed = [old[e[0]][0] for e in events if e[0] in old]
    rec_before: dict[int, str] = {}
    if changed:
        for k, js in tx.fetchall(
            "SELECT record_key, row_to_json(r)::text FROM tb_record r WHERE record_key = ANY(?)", (changed,)
        ):
            rec_before[int(k)] = js
    # before-images of every OMOP row that is replaced or deleted
    before = _drop_rows(tx, deletes)
    for table, rows in inserts.items():
        if table in PARTITIONED:  # T-106: each year's partition exists before its rows are written
            ensure_years(tx, table, years_of(rows, PARTITIONED[table][1]))
        cols = sorted(set().union(*rows))
        tx.copy_rows(table, cols, ([row.get(c) for c in cols] for row in rows))
        rep.by_table[table] = rep.by_table.get(table, 0) + len(rows)
    tx.execute("DROP TABLE IF EXISTS tb_in_tmp")
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
        "i.source_file, source_row = i.source_row, extra = i.extra FROM tb_in_tmp i WHERE i.action = 'same' "
        "AND (r.source_kind, "
        "r.resource_type, r.source_record_id, r.part) = (i.source_kind, i.resource_type, i.source_record_id, i.part)"
    )
    all_cols = ", ".join(TB_RECORD_COLS)
    tx.execute(f"INSERT INTO tb_record ({all_cols}) SELECT {all_cols} FROM tb_in_tmp WHERE action = 'insert'")
    ev_rows: list[tuple[Any, ...]] = []
    keys = {k: v[0] for k, v in old.items()}
    new_keys = [e[0] for e in events if e[0] not in keys]
    if new_keys:
        tx.execute("DROP TABLE IF EXISTS tb_keys_tmp")
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
        ev_rows.append((keys[key], batch, action, frm, to, bsha, bjs, rec_before.get(keys[key]), None))
    _events(tx, ev_rows)
    return persons, providers


def _events(tx: Any, ev_rows: list[tuple[Any, ...]]) -> None:
    if ev_rows:
        tx.copy_rows(
            "tb_record_event",
            [
                "record_key",
                "batch",
                "event",
                "from_status",
                "to_status",
                "before_sha",
                "before",
                "record_before",
                "reason",
            ],
            ev_rows,
        )


def _tombstone(
    tx: Any, kind: str, batch: str, rep: LoadReport, dead: set[tuple[str, str]], chunk: int
) -> tuple[set[int], set[int]]:
    """Every live record of this kind the batch no longer carries (or carries for a withheld patient, D-441): its
    OMOP row deleted, ``tb_record`` tombstoned, the event with its reason (opted out, deleted at the source, left the
    feed). Found by an anti-join with the staged batch and taken a chunk at a time, by record key (D-678)."""
    persons: set[int] = set()
    providers: set[int] = set()
    after = -1
    while True:
        gone = [
            ((str(t), str(s_), int(p_)), (int(k), tab, rid, sha, st, held))
            for k, t, s_, p_, tab, rid, sha, st, held in tx.fetchall(
                "SELECT r.record_key, r.resource_type, r.source_record_id, r.part, r.cdm_table, r.record_id, "
                "r.content_sha, r.status, s.held FROM tb_record r LEFT JOIN tb_load_stage s ON (s.resource_type, "
                "s.source_record_id, s.part) = (r.resource_type, r.source_record_id, r.part) WHERE r.source_kind = ? "
                "AND r.status <> 'tombstoned' AND r.record_key > ? AND (s.seq IS NULL OR s.held) "
                "ORDER BY r.record_key LIMIT ?",
                (kind, after, chunk),
            )
        ]
        if not gone:
            return persons, providers
        after = gone[-1][1][0]
        deletes: dict[str, list[int]] = defaultdict(list)
        for _, v in gone:
            if v[1] in ID_COL and v[2] is not None:
                deletes[str(v[1])].append(int(v[2]))
            if v[1] == "person" and v[2] is not None:
                persons.add(int(v[2]))
            if v[1] == "provider" and v[2] is not None:
                providers.add(int(v[2]))
        rep.tombstoned += len(gone)
        rec_before = dict(
            (int(k), js)
            for k, js in tx.fetchall(
                "SELECT record_key, row_to_json(r)::text FROM tb_record r WHERE record_key = ANY(?)",
                ([v[0] for _, v in gone],),
            )
        )
        before = _drop_rows(tx, deletes)
        tx.execute("DROP TABLE IF EXISTS tb_gone_tmp")
        tx.execute("CREATE TEMP TABLE tb_gone_tmp (record_key BIGINT) ON COMMIT DROP")
        tx.copy_rows("tb_gone_tmp", ["record_key"], [(v[0],) for _, v in gone])
        tx.execute(
            "UPDATE tb_record r SET status = 'tombstoned', tombstoned_at = now(), changed_at = now(), last_batch = ? "
            "FROM tb_gone_tmp g WHERE r.record_key = g.record_key",
            (batch,),
        )
        ev_rows: list[tuple[Any, ...]] = []
        for k, v in gone:
            bjs = before.get((str(v[1]), int(v[2]))) if v[1] in ID_COL and v[2] is not None else None
            why = OPTED_OUT if v[5] else DELETED_AT_SOURCE if (k[0], k[1]) in dead else LEFT_THE_FEED
            ev_rows.append((v[0], batch, "tombstone", v[4], "tombstoned", v[3], bjs, rec_before.get(v[0]), why))
        _events(tx, ev_rows)


def _drop_rows(tx: Any, deletes: Mapping[str, list[int]]) -> dict[tuple[str, int], str]:
    """Delete OMOP rows by id (table -> ids, tables of :data:`ID_COL` only) and return their before-images."""
    before: dict[tuple[str, int], str] = {}
    for table, ids in deletes.items():
        col = ID_COL[table]
        for rid, js in tx.fetchall(f"SELECT {col}, row_to_json(t)::text FROM {table} t WHERE {col} = ANY(?)", (ids,)):
            before[(table, int(rid))] = js
        tx.execute(f"DELETE FROM {table} WHERE {col} = ANY(?)", (ids,))
    return before


def _batch_day(batch: str) -> date:
    """The night a batch holds (``2026-10-31``, ``site@2026-10-31``): the latest a death it reports can have been."""
    try:
        return date.fromisoformat(batch.rsplit("@", 1)[-1][:10])
    except ValueError:
        return date.today()


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
    # T-616 (STD-013): any source that says the patient died (a date or a flag) makes a death; never a conflict
    merged["deceased"] = bool(merged["deceased_date"]) or any(s.get("deceased") is True for s in sources)
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
            if not srcs.get(pid):  # no source sends the patient tonight: a recorded conflict stays (DATA-011)
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
            elif merged["deceased"]:  # STD-013: dead, no date: the batch's night, flagged as imputed (D-400)
                drow.append((pid, _batch_day(batch), vocab.DEATH_DATE_IMPUTED))
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
    # the active Athena release (T-105b: its row is vocabulary_id 'None', OMOP's convention); none loaded: local only
    vocab_version = tx.fetchval(
        "SELECT version FROM tb_vocab_release WHERE vocabulary_id = 'None' AND active ORDER BY loaded_at DESC LIMIT 1"
    )
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
            str(vocab_version)[:20] if vocab_version else "TB local, no Athena",
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
    withdraw a recorded one only when two or more sources give the item and agree again. A source that goes silent
    (a feed that lacks the patient tonight, a sheet row deleted) withdraws nothing: the remaining value never stands
    alone by default; the item stays unknown until a person resolves it (T-201, DATA-011, D-426)."""
    for item in ("birth_date", "sex", "deceased_date"):
        vals = clash.get(item)
        if not vals:
            if sum(1 for s in sources if s.get(item) is not None) < 2:
                continue  # one source or none: silence is not agreement
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
            # D-681: the caller holds the key it asked with; the text names the kind and the resource type only
            raise OmopError(f"no {key[0]} {key[1]} record of that id and part")
        rk, frm = int(row[0]), str(row[1])
        if to not in TRANSITIONS[frm]:
            raise OmopError(f"a {frm} record cannot become {to}")
        tx.execute(  # the event first: it keeps the record as it was (T-202, the export "as of")
            "INSERT INTO tb_record_event (record_key, event, from_status, to_status, actor, reason, record_before) "
            "SELECT ?, 'status', ?, ?, ?, ?, row_to_json(r)::jsonb FROM tb_record r WHERE r.record_key = ?",
            (rk, frm, to, by, reason, rk),
        )
        tx.execute("UPDATE tb_record SET status = ?, changed_at = now() WHERE record_key = ?", (to, rk))


# ------------------------------------------------------------------------------------------------ D-441 withheld
#: the tables a withheld patient keeps: the consent statements that say no (D-441)
KEEP_WITHHELD = ("tb_consent",)


EVENT_COLS = [
    "record_key",
    "event",
    "from_status",
    "to_status",
    "before_sha",
    "before",
    "record_before",
    "actor",
    "reason",
]


@dataclass
class WithholdReport:
    withheld: int = 0  # rows added to tb_withheld
    released: int = 0  # rows removed (a lift: the next load restores the records)
    tombstoned: int = 0  # live records tombstoned now

    def as_dict(self) -> dict[str, int]:
        return {"withheld": self.withheld, "released": self.released, "tombstoned": self.tombstoned}


def withhold(db: Database, pids: Iterable[str], actor: str = "optout-worker") -> WithholdReport:
    """D-441: make ``tb_withheld`` exactly ``pids`` (the patients opted out now) and tombstone, at once, every live
    record of a newly withheld patient with the reason ``opted out`` (before-images kept, as for any tombstone;
    erasing them is the retention run's, T-206b). A released patient (lifted) is only taken off the table: nothing
    is restored until the next load carries the records again. Under the loader's lock, so it never interleaves with
    a load. Returns counts only."""
    want = sorted(set(pids))
    rep = WithholdReport()
    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('trialbox-omop-load'))")
        have = {str(r[0]) for r in tx.fetchall("SELECT pid FROM tb_withheld")}
        gone = sorted(have - set(want))
        if gone:
            tx.execute("DELETE FROM tb_withheld WHERE pid = ANY(?)", (gone,))
            rep.released = len(gone)
        new = [p for p in want if p not in have]
        for p in new:
            tx.execute("INSERT INTO tb_withheld (pid, reason) VALUES (?, ?)", (p, OPTED_OUT))
        rep.withheld = len(new)
        if not want:
            return rep
        rep.tombstoned = withhold_persons(tx, want, actor)
    return rep


def withhold_persons(tx: Any, pids: Sequence[str], actor: str) -> int:
    """Tombstone every live record of the patients ``pids`` with the reason ``opted out`` (before-images kept), in
    the caller's transaction; the consent statements stay (:data:`KEEP_WITHHELD`). Returns the records tombstoned.
    The opt-out worker's :func:`withhold` and the export as of a time (T-728, D-493: a patient withheld now is
    never brought back by a wind-back) both end here."""
    persons = [
        int(r[0])
        for r in tx.fetchall(
            "SELECT omop_id FROM tb_id_map WHERE id_kind = 'person' AND source_id = ANY(?)", (list(pids),)
        )
    ]
    if not persons:
        return 0
    live = tx.fetchall(
        "SELECT record_key, cdm_table, record_id, status, content_sha FROM tb_record WHERE status <> 'tombstoned' "
        "AND (person_id = ANY(?) OR (cdm_table = 'person' AND record_id = ANY(?))) "
        "AND coalesce(cdm_table, '') <> ALL(?)",
        (persons, persons, list(KEEP_WITHHELD)),
    )
    if not live:
        return 0
    keys = [int(r[0]) for r in live]
    rec_before: dict[int, str] = dict(
        tx.fetchall("SELECT record_key, row_to_json(r)::text FROM tb_record r WHERE record_key = ANY(?)", (keys,))
    )
    by_table: dict[str, list[int]] = defaultdict(list)
    for _, table, rid, _, _ in live:
        if table in ID_COL and rid is not None:
            by_table[str(table)].append(int(rid))
    if by_table.get("note"):
        tx.execute("DELETE FROM note_nlp WHERE note_id = ANY(?)", (by_table["note"],))
    if by_table.get("measurement"):
        m = by_table["measurement"]
        tx.execute("DELETE FROM fact_relationship WHERE fact_id_1 = ANY(?) OR fact_id_2 = ANY(?)", (m, m))
    before = _drop_rows(tx, by_table)
    tx.execute("DELETE FROM observation_period WHERE person_id = ANY(?)", (persons,))
    tx.execute("DELETE FROM death WHERE person_id = ANY(?)", (persons,))
    tx.execute("DELETE FROM person WHERE person_id = ANY(?)", (persons,))
    tx.execute(
        "UPDATE tb_record SET status = 'tombstoned', tombstoned_at = now(), changed_at = now() "
        "WHERE record_key = ANY(?)",
        (keys,),
    )
    tx.copy_rows(
        "tb_record_event",
        EVENT_COLS,
        [
            (
                int(k),
                "tombstone",
                st,
                "tombstoned",
                sha,
                before.get((str(t), int(rid))) if t in ID_COL and rid is not None else None,
                rec_before.get(int(k)),
                actor,
                OPTED_OUT,
            )
            for k, t, rid, st, sha in live
        ],
    )
    return len(live)
