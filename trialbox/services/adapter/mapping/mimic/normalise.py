"""Normalise the MIMIC-IV Clinical Database Demo on FHIR (v2.1.0) to the TrialBox FHIR minimal profile (SPEC §3.1).

MIMIC-on-FHIR is already FHIR R4, but it uses MIMIC code systems and a per-patient date shift that the lake and the
criteria compiler cannot use as they are. This step runs before the ``fhir_bulk`` adapter source and is
table-driven (``tables/*.csv``; every table is documented in docs/OPEN_DATA.md):

* **Diagnoses.** ``mimic-diagnosis-icd10`` codes (no dot, e.g. ``I5023``) become ICD-10-CM (``I50.23``).
  ``mimic-diagnosis-icd9`` codes are cross-walked to ICD-10-CM with ``icd9_to_icd10cm.csv``: a small explicit table
  (CMS General Equivalence Mappings, forward direction) for the concepts the open-data rulesets use, not a full GEM.
  Unmapped ICD-9 codes stay ICD-9-CM. ``recordedDate`` is the start of the referenced encounter (MIMIC diagnoses carry
  no date of their own).
* **Labs.** ``mimic-d-labitems`` item ids get a LOINC coding (first) from ``labitem_to_loinc.csv``; the MIMIC coding is
  kept second (the lake's ``local_code``). The demo carries no LOINC codes of its own. Units are rewritten to UCUM.
* **Medications.** ``medicationReference`` -> ``Medication`` (or a medication mix, by its ingredient names) is
  resolved into ``medicationCodeableConcept`` (drug name as text, NDC coding when present); drug names are matched
  to ATC with ``drug_to_atc.csv`` (whole-word, case-insensitive generic names).
* **Procedures.** ICD-9 / ICD-10 procedure systems become ICD-9-CM / ICD-10-PCS; ICU charted procedures
  (``mimic-d-items``) get a SNOMED CT coding from ``icu_item_to_snomed.csv`` and ``performedDateTime`` from
  ``performedPeriod.start``.
* **Encounters.** The MIMIC service (``MED``, ``CMED`` …) becomes the department code; ICU stays get department
  ``ICU``.
* **Dates.** MIMIC shifts every patient into 2100–2200, each by a different offset, so no single run date sees the
  cohort. Each patient's timeline is moved by a whole number of days so that the start of the patient's last
  encounter falls inside the FEAS lookback before ``run_date`` (deterministic position from a hash of the MIMIC
  patient id). Intervals within a patient — and ages, since ``birthDate`` moves too — are preserved.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

Resource = dict[str, Any]

TABLES = Path(__file__).resolve().parent / "tables"
MIMIC_CS = "http://mimic.mit.edu/fhir/mimic/CodeSystem/"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD9CM = "http://hl7.org/fhir/sid/icd-9-cm"
ICD10PCS = "http://www.cms.gov/Medicare/Coding/ICD10"
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
ATC = "http://www.whocc.no/atc"
NDC = "http://hl7.org/fhir/sid/ndc"
DEPARTMENT = "https://trialbox.local/fhir/CodeSystem/department"
ICU_DEPARTMENT = "ICU"

# keys whose string value is a FHIR date/dateTime/instant moved by the per-patient shift
DATE_KEYS = frozenset(
    {
        "birthDate",
        "deceasedDateTime",
        "start",
        "end",
        "authoredOn",
        "effectiveDateTime",
        "issued",
        "performedDateTime",
        "recordedDate",
        "onsetDateTime",
    }
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class LabMap:
    loinc: str
    display: str
    ucum: str


@dataclass(frozen=True)
class MimicTables:
    icd9: dict[str, tuple[str, str]]  # ICD-9 (MIMIC form, no dot) -> (ICD-10-CM, display)
    labs: dict[str, LabMap]  # MIMIC lab itemid -> LOINC
    drugs: list[tuple[re.Pattern[str], str, str]]  # (whole-word generic name, ATC, display)
    icu_items: dict[str, tuple[str, str]]  # MIMIC ICU itemid -> (SNOMED CT, display)

    @classmethod
    def load(cls, directory: Path = TABLES) -> MimicTables:
        def rows(name: str) -> list[dict[str, str]]:
            with (directory / name).open(encoding="utf-8", newline="") as fh:
                return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]

        icd9: dict[str, tuple[str, str]] = {}
        for r in rows("icd9_to_icd10cm.csv"):
            if r["icd9"] in icd9:
                raise ValueError(f"icd9_to_icd10cm.csv: duplicate ICD-9 code {r['icd9']}")
            icd9[r["icd9"]] = (r["icd10cm"], r["display"])
        labs = {r["itemid"]: LabMap(r["loinc"], r["display"], r["ucum"]) for r in rows("labitem_to_loinc.csv")}
        drugs = [
            (re.compile(rf"\b{re.escape(r['pattern'].lower())}\b"), r["atc"], r["display"])
            for r in rows("drug_to_atc.csv")
        ]
        icu = {r["itemid"]: (r["snomed"], r["display"]) for r in rows("icu_item_to_snomed.csv")}
        return cls(icd9, labs, drugs, icu)

    def atc_for(self, drug_name: str) -> tuple[str, str] | None:
        name = drug_name.lower()
        for pattern, atc, display in self.drugs:
            if pattern.search(name):
                return atc, display
        return None


def icd10_dotted(code: str) -> str:
    """MIMIC ICD-10 (``I5023``) -> ICD-10-CM (``I50.23``); 3-character categories have no dot."""
    code = code.strip().upper().replace(".", "")
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"


def icd9_dotted(code: str, procedure: bool = False) -> str:
    """MIMIC ICD-9 without dot -> ICD-9-CM display form (``4280`` -> ``428.0``, ``V4511`` -> ``V45.11``,
    ``E8889`` -> ``E888.9``; procedures ``3995`` -> ``39.95``)."""
    code = code.strip().upper().replace(".", "")
    head = 2 if procedure else (4 if code.startswith("E") else 3)
    return code if len(code) <= head else f"{code[:head]}.{code[head:]}"


def read_ndjson_gz(path: Path) -> Iterator[Resource]:
    for line in _lines(path):
        yield json.loads(line)


def _lines(path: Path) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield line


def release_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("Mimic*.ndjson.gz")) + sorted(directory.glob("Mimic*.ndjson"))


def read_release(directory: Path, keep: Callable[[Resource], bool] | None = None) -> dict[str, list[Resource]]:
    """All ``Mimic*.ndjson[.gz]`` files of a release directory in memory, grouped by resourceType (small inputs and
    tests; ``MimicNormaliser.run`` streams instead)."""
    by_type: dict[str, list[Resource]] = {}
    for path in release_files(directory):
        for r in read_ndjson_gz(path):
            if keep is None or keep(r):
                by_type.setdefault(r["resourceType"], []).append(r)
    return by_type


def _ref(ref: dict[str, Any] | None, rtype: str) -> str | None:
    value = (ref or {}).get("reference") or ""
    prefix = f"{rtype}/"
    return value[len(prefix) :] if value.startswith(prefix) else None


def shift_value(value: str, days: int) -> str:
    if len(value) == 10:
        return (date.fromisoformat(value) + timedelta(days=days)).isoformat()
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(days=days)).isoformat()


def shift_dates(node: Any, days: int) -> Any:
    """Copy of ``node`` with every date-valued key in DATE_KEYS moved by ``days``."""
    if isinstance(node, dict):
        return {
            k: (
                shift_value(v, days)
                if k in DATE_KEYS and isinstance(v, str) and _DATE_RE.match(v)
                else shift_dates(v, days)
            )
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [shift_dates(x, days) for x in node]
    return node


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value and _DATE_RE.match(value) else None


# elements kept per resource type: the SPEC §3.1 minimal profile plus status/category/encounter links (MIMIC's
# identifiers, meta, extensions, reference ranges, specimens and locations are not used downstream)
KEEP: dict[str, frozenset[str]] = {
    "Patient": frozenset({"resourceType", "id", "gender", "birthDate", "deceasedDateTime", "deceasedBoolean"}),
    "Encounter": frozenset(
        {"resourceType", "id", "subject", "class", "period", "serviceType", "status", "partOf", "identifier"}
    ),
    "Condition": frozenset(
        {"resourceType", "id", "subject", "code", "category", "encounter", "recordedDate", "onsetDateTime"}
    ),
    "Observation": frozenset(
        {
            "resourceType",
            "id",
            "subject",
            "code",
            "category",
            "status",
            "encounter",
            "effectiveDateTime",
            "valueQuantity",
            "valueCodeableConcept",
            "valueString",
        }
    ),
    "MedicationRequest": frozenset(
        {
            "resourceType",
            "id",
            "subject",
            "status",
            "intent",
            "encounter",
            "authoredOn",
            "dispenseRequest",
            "dosageInstruction",
            "medicationCodeableConcept",
            "medicationReference",
        }
    ),
    "Procedure": frozenset(
        {"resourceType", "id", "subject", "code", "status", "encounter", "performedDateTime", "performedPeriod"}
    ),
}
INDEX_TYPES = frozenset({"Patient", "Encounter", "Medication"})
# cheap pre-parse test for lab lines whose item has no LOINC mapping (falls back to parsing when the layout differs)
_LAB_LINE = re.compile(r'"code": "(\d+)", "system": "http://mimic\.mit\.edu/fhir/mimic/CodeSystem/mimic-d-labitems"')


@dataclass
class NormaliseReport:
    counts: Counter[str] = field(default_factory=Counter)
    unmapped_icd9: Counter[str] = field(default_factory=Counter)
    shifts: dict[str, int] = field(default_factory=dict)  # MIMIC patient id -> days

    def as_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "unmapped_icd9_top": [{"code": c, "n": n} for c, n in self.unmapped_icd9.most_common(15)],
            "patients_shifted": len(self.shifts),
        }


class MimicNormaliser:
    def __init__(self, tables: MimicTables, window_start: date, window_end: date) -> None:
        """The start of each patient's last encounter is moved into ``[window_start, window_end]``."""
        if window_end <= window_start:
            raise ValueError("empty anchoring window")
        self.t = tables
        self.window_start = window_start
        self.window_end = window_end
        self.report = NormaliseReport()
        self.enc_start: dict[str, str] = {}
        self.meds: dict[str, tuple[str | None, str | None]] = {}  # Medication id -> (name, NDC)
        self._patients: list[str] = []
        self._last_enc: dict[str, date] = {}

    def keep_raw(self, r: Resource) -> bool:
        """Read filter: lab events whose item has no LOINC mapping are not loaded (counted in the report)."""
        if r.get("resourceType") != "Observation":
            return True
        c = ((r.get("code") or {}).get("coding") or [{}])[0]
        if c.get("system") == f"{MIMIC_CS}mimic-d-labitems" and str(c.get("code")) not in self.t.labs:
            self.report.counts["observation.skipped_unmapped_lab"] += 1
            return False
        return True

    # ------------------------------------------------------------------ pass 1: index + dates
    def index(self, r: Resource) -> None:
        rtype = r.get("resourceType")
        if rtype == "Patient":
            self._patients.append(r["id"])
        elif rtype == "Encounter":
            start = (r.get("period") or {}).get("start")
            pid = _ref(r.get("subject"), "Patient")
            if start:
                self.enc_start[r["id"]] = start
                d = _day(start)
                if pid is not None and d is not None:
                    self._last_enc[pid] = max(self._last_enc.get(pid, d), d)
        elif rtype == "Medication":
            name = ndc = None
            for ident in r.get("identifier") or []:
                sys_ = str(ident.get("system") or "")
                if sys_.endswith("mimic-medication-name"):
                    name = ident.get("value")
                elif sys_.endswith("mimic-medication-ndc"):
                    ndc = ident.get("value")
                elif sys_.endswith("medication-mix") and ident.get("value"):
                    # mixes: "<name>--<formulary>--<ndc>_<name>--<formulary>--<ndc>..." -> "<name> + <name>"
                    name = " + ".join(part.split("--")[0] for part in str(ident["value"]).split("_"))
            self.meds[r["id"]] = (name, ndc)

    def _anchor(self, pid: str) -> date:
        span = (self.window_end - self.window_start).days
        h = int(hashlib.sha256(f"mimic-anchor|{pid}".encode()).hexdigest()[:12], 16)
        return self.window_start + timedelta(days=h % (span + 1))

    def finish_index(self) -> dict[str, int]:
        """Per-patient day shift: the start of the last encounter goes to the patient's anchor date. Patients
        without any encounter have no timeline and are dropped (counted)."""
        shifts: dict[str, int] = {}
        for pid in self._patients:
            last = self._last_enc.get(pid)
            if last is None:
                self.report.counts["patient.dropped_no_encounter"] += 1
                continue
            shifts[pid] = (self._anchor(pid) - last).days
        self.report.shifts = shifts
        return shifts

    # ------------------------------------------------------------------ per resource type
    def condition(self, r: Resource, enc_start: dict[str, str]) -> Resource:
        r = dict(r)
        codings = list((r.get("code") or {}).get("coding") or [])
        c = codings[0] if codings else {}
        system, code = str(c.get("system") or ""), str(c.get("code") or "")
        self.report.counts["condition.total"] += 1
        if system == f"{MIMIC_CS}mimic-diagnosis-icd10":
            new = [{"system": ICD10CM, "code": icd10_dotted(code), "display": c.get("display")}]
            self.report.counts["condition.icd10"] += 1
        elif system == f"{MIMIC_CS}mimic-diagnosis-icd9":
            icd9 = {"system": ICD9CM, "code": icd9_dotted(code), "display": c.get("display")}
            hit = self.t.icd9.get(code.replace(".", "").upper())
            if hit:
                new = [{"system": ICD10CM, "code": hit[0], "display": hit[1]}, icd9]
                self.report.counts["condition.icd9_mapped"] += 1
            else:
                new = [icd9]
                self.report.counts["condition.icd9_unmapped"] += 1
                self.report.unmapped_icd9[code] += 1
        else:
            new = []
            self.report.counts["condition.other_system"] += 1
        r["code"] = {**(r.get("code") or {}), "coding": [{k: v for k, v in x.items() if v} for x in new] + codings}
        if not r.get("onsetDateTime") and not r.get("recordedDate"):
            start = enc_start.get(_ref(r.get("encounter"), "Encounter") or "")
            if start:
                r["recordedDate"] = start
            else:
                self.report.counts["condition.undated"] += 1
        return r

    def observation(self, r: Resource) -> Resource:
        r = dict(r)
        codings = list((r.get("code") or {}).get("coding") or [])
        self.report.counts["observation.total"] += 1
        c = codings[0] if codings else {}
        lab = self.t.labs.get(str(c.get("code"))) if c.get("system") == f"{MIMIC_CS}mimic-d-labitems" else None
        if lab is None:
            return r
        self.report.counts["observation.loinc"] += 1
        r["code"] = {
            **(r.get("code") or {}),
            "coding": [{"system": LOINC, "code": lab.loinc, "display": lab.display}, *codings],
        }
        q = r.get("valueQuantity")
        if isinstance(q, dict) and "value" in q:
            r["valueQuantity"] = {"value": q["value"], "unit": lab.ucum, "system": UCUM, "code": lab.ucum}
        return r

    def medication_request(self, r: Resource) -> Resource:
        r = dict(r)
        self.report.counts["medication_request.total"] += 1
        name: str | None = None
        ndc: str | None = None
        mid = _ref(r.get("medicationReference"), "Medication")
        if mid is not None:
            if mid in self.meds:
                name, ndc = self.meds[mid]
            else:
                self.report.counts["medication_request.unresolved"] += 1
        for c in (r.get("medicationCodeableConcept") or {}).get("coding") or []:
            if str(c.get("system") or "").endswith("mimic-medication-name"):
                name = name or c.get("code")
        codings: list[dict[str, Any]] = []
        hit = self.t.atc_for(name) if name else None
        if hit:
            codings.append({"system": ATC, "code": hit[0], "display": hit[1]})
            self.report.counts["medication_request.atc"] += 1
        if ndc and ndc != "0":
            codings.append({"system": NDC, "code": ndc})
        if name:
            codings.append({"system": f"{MIMIC_CS}mimic-medication-name", "code": name})
        r.pop("medicationReference", None)
        r["medicationCodeableConcept"] = {"coding": codings, **({"text": name} if name else {})}
        return r

    def procedure(self, r: Resource) -> Resource:
        r = dict(r)
        codings = list((r.get("code") or {}).get("coding") or [])
        c = codings[0] if codings else {}
        system, code = str(c.get("system") or ""), str(c.get("code") or "")
        self.report.counts["procedure.total"] += 1
        new: list[dict[str, Any]] = []
        if system == f"{MIMIC_CS}mimic-procedure-icd9":
            new = [{"system": ICD9CM, "code": icd9_dotted(code, procedure=True), "display": c.get("display")}]
        elif system == f"{MIMIC_CS}mimic-procedure-icd10":
            new = [{"system": ICD10PCS, "code": code.upper(), "display": c.get("display")}]
        elif system == f"{MIMIC_CS}mimic-d-items" and code in self.t.icu_items:
            snomed, display = self.t.icu_items[code]
            new = [{"system": SNOMED, "code": snomed, "display": display}]
            self.report.counts["procedure.icu_snomed"] += 1
        if new:
            r["code"] = {**(r.get("code") or {}), "coding": [{k: v for k, v in x.items() if v} for x in new] + codings}
        if not r.get("performedDateTime") and (r.get("performedPeriod") or {}).get("start"):
            r["performedDateTime"] = r["performedPeriod"]["start"]
        return r

    def encounter(self, r: Resource) -> Resource:
        r = dict(r)
        self.report.counts["encounter.total"] += 1
        icu = any(str(i.get("system") or "").endswith("encounter-icu") for i in r.pop("identifier", None) or [])
        if icu:
            self.report.counts["encounter.icu"] += 1
            r["serviceType"] = {"coding": [{"system": DEPARTMENT, "code": ICU_DEPARTMENT, "display": "ICU stay"}]}
        else:
            svc = ((r.get("serviceType") or {}).get("coding") or [{}])[0].get("code")
            if svc:
                r["serviceType"] = {"coding": [{"system": DEPARTMENT, "code": str(svc)}]}
        return r

    # ------------------------------------------------------------------ pass 2: one resource
    def one(self, r: Resource) -> Resource | None:
        """Normalised, trimmed and date-shifted copy of one MIMIC resource (None: not loaded)."""
        rtype = str(r.get("resourceType"))
        keep = KEEP.get(rtype)
        if keep is None or not self.keep_raw(r):
            return None
        pid = r["id"] if rtype == "Patient" else _ref(r.get("subject"), "Patient")
        if pid is None or pid not in self.report.shifts:
            self.report.counts[f"{rtype[0].lower()}{rtype[1:]}.dropped_no_patient_timeline"] += 1
            return None
        r = {k: v for k, v in r.items() if k in keep}
        match rtype:
            case "Encounter":
                r = self.encounter(r)
            case "Condition":
                r = self.condition(r, self.enc_start)
            case "Observation":
                r = self.observation(r)
            case "MedicationRequest":
                r = self.medication_request(r)
            case "Procedure":
                r = self.procedure(r)
        out: Resource = shift_dates(r, self.report.shifts[pid])
        return out

    def normalise(self, by_type: dict[str, list[Resource]]) -> dict[str, list[Resource]]:
        """In-memory variant of ``run`` (same per-resource steps)."""
        for rtype in ("Patient", "Encounter", "Medication"):
            for r in by_type.get(rtype, []):
                self.index(r)
        self.finish_index()
        out: dict[str, list[Resource]] = {}
        for rtype in KEEP:
            items = [x for r in by_type.get(rtype, []) if (x := self.one(r)) is not None]
            out[rtype] = items
        return out

    def run(self, release_dir: Path, out_dir: Path) -> dict[str, int]:
        """Stream a release directory into ``<out_dir>/<Type>.ndjson`` (the ``fhir_bulk`` source layout) without
        holding it in memory: pass 1 indexes patients, encounters and medications, pass 2 normalises line by line."""
        files = release_files(release_dir)
        first_type: dict[Path, str] = {}
        for path in files:
            first = next(_lines(path), None)
            if first is not None:
                first_type[path] = str(json.loads(first).get("resourceType"))
        for path, rtype in first_type.items():
            if rtype in INDEX_TYPES:
                for r in read_ndjson_gz(path):
                    self.index(r)
        self.finish_index()
        out_dir.mkdir(parents=True, exist_ok=True)
        counts: Counter[str] = Counter()
        handles: dict[str, Any] = {}
        try:
            for path, rtype in first_type.items():
                if rtype not in KEEP:
                    continue
                for line in _lines(path):
                    m = _LAB_LINE.search(line) if rtype == "Observation" else None
                    if m is not None and m.group(1) not in self.t.labs:
                        self.report.counts["observation.skipped_unmapped_lab"] += 1
                        continue
                    res = self.one(json.loads(line))
                    if res is None:
                        continue
                    t = res["resourceType"]
                    if t not in handles:
                        handles[t] = (out_dir / f"{t}.ndjson").open("w", encoding="utf-8")
                    handles[t].write(json.dumps(res, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                    counts[t] += 1
        finally:
            for fh in handles.values():
                fh.close()
        return dict(sorted(counts.items()))


def write_bulk(directory: Path, by_type: dict[str, list[Resource]]) -> dict[str, int]:
    """``<Type>.ndjson`` files for the ``fhir_bulk`` adapter source (sorted by id, canonical JSON)."""
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for rtype, items in sorted(by_type.items()):
        with (directory / f"{rtype}.ndjson").open("w", encoding="utf-8") as fh:
            for r in sorted(items, key=lambda x: str(x["id"])):
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        counts[rtype] = len(items)
    return counts
