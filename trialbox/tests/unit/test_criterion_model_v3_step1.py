"""Criterion model v3, step 1 (D-1263; plan 10 card 10A-5; review 15, B16-1): windows on a planned start, a
screening date and an event; the device and allergy domains; the flip date of a window or a washout.

Every expected answer below is written from the protocol sentence quoted beside it, with the calendar worked by hand,
not read off the engine. The day of the run is 2026-11-20. A window counts both of its end days, on the calendar date
of the record, as every v1 window does (D-17). All patients and records are synthetic.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import FILTERED, JUDGED, CompileError, class_split, compiled, kind
from criteria_compiler.terminology.mapper import FAMILY_EXT, Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from jsonschema import Draft202012Validator
from lake.client import LakeLocal
from matching import decision
from matching.cascade.engine import CascadeConfig, criterion_hashes, run_cascade, write_outputs
from matching.cascade.model import Outcome, PatientTrace
from orchestrator import answer_store
from orchestrator.scenarios.evaluate import SqlEngine, evaluate_patients, human_verdict
from orchestrator.scenarios.screen_cascade import verdict_of, verdicts_of
from pydantic import ValidationError
from tb_common.reasons import CODES, LABELS, Reason, code_of, label
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, validate
from tb_contracts.criterion_ir import (
    CriterionIRv3,
    NotStep1,
    canonical_hash,
    index_form,
    sourceless_domains,
    upgrade_v1,
    v1_face,
    valueset_content_hash,
)

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]
RUN = date(2026, 11, 20)
SNAPSHOT = "2026-11-20"
ATC = "http://www.whocc.no/atc"
LOINC = "http://loinc.org"
SCT = "http://snomed.info/sct"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"

# ----------------------------------------------------------------------------------------------- the criteria
#: "Exclusion 1: any chemotherapy in the 28 days before the planned start of study treatment (the day of the planned
#: start and each of the 28 days before it)."
WASHOUT: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-EXC-01", "ruleset": "M3", "kind": "exclusion", "class": "structured",
    "time_sensitive": True, "text": {"source": "Any chemotherapy in the 28 days before the planned start."},
    "logic": "a1",
    "atoms": [{"id": "a1", "domain": "medication", "valueset": "VS_CHEMO", "quantifier": "any",
               "window": {"from_days": -28, "to_days": 0, "anchor": "planned_start"}}],
}  # fmt: skip
#: "Inclusion 2: serum creatinine of 1.5 mg/dL or less, measured in the 14 days before the screening visit; the
#: latest result counts."
CREATININE: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-INC-02", "ruleset": "M3", "kind": "inclusion", "class": "structured",
    "text": {"source": "Creatinine <= 1.5 mg/dL in the 14 days before the screening visit."},
    "logic": "a1",
    "atoms": [{"id": "a1", "domain": "observation", "valueset": "VS_CREATININE", "quantifier": "latest",
               "value": {"op": "<=", "num": 1.5, "unit": "mg/dL"},
               "window": {"from_days": -14, "to_days": 0, "anchor": "screening"}}],
}  # fmt: skip
#: "Exclusion 3: a surgical site infection recorded on the day of the patient's last operation or in the 30 days
#: after it."
INFECTION: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-EXC-03", "ruleset": "M3", "kind": "exclusion", "class": "structured",
    "text": {"source": "Surgical site infection within 30 days after the last operation."},
    "logic": "a1",
    "atoms": [{"id": "e1", "domain": "procedure", "valueset": "VS_SURGERY"},
              {"id": "a1", "domain": "condition", "valueset": "VS_SSI", "quantifier": "any",
               "window": {"from_days": 0, "to_days": 30, "anchor": "event", "event_atom": "e1",
                          "event_pick": "last"}}],
}  # fmt: skip
#: "Exclusion 4: an implanted cardiac pacemaker."
PACEMAKER: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-EXC-04", "ruleset": "M3", "kind": "exclusion", "class": "structured",
    "text": {"source": "An implanted cardiac pacemaker."}, "logic": "a1",
    "atoms": [{"id": "a1", "domain": "device", "valueset": "VS_PACEMAKER", "quantifier": "any"}],
}  # fmt: skip
#: "Exclusion 5: known hypersensitivity to platinum compounds."
ALLERGY: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-EXC-05", "ruleset": "M3", "kind": "exclusion", "class": "structured",
    "text": {"source": "Known hypersensitivity to platinum compounds."}, "logic": "a1",
    "atoms": [{"id": "a1", "domain": "allergy", "valueset": "VS_PLATINUM_ALLERGY", "quantifier": "any"}],
}  # fmt: skip
#: "Exclusion 6: any chemotherapy in the last 28 days (today and each of the 28 days before it)." The same washout
#: on the index date, which v1 can also write: the ruleset's own SQL answers it and model v3 adds the flip date.
WASHOUT_TODAY: dict[str, Any] = {
    "ir_version": "3.0.0", "id": "M3-EXC-06", "ruleset": "M3", "kind": "exclusion", "class": "structured",
    "time_sensitive": True, "text": {"source": "Any chemotherapy in the last 28 days."}, "logic": "a1",
    "atoms": [{"id": "a1", "domain": "medication", "valueset": "VS_CHEMO", "quantifier": "any",
               "window": {"from_days": -28, "to_days": 0, "anchor": "index"}}],
}  # fmt: skip
#: a v1 criterion in the same ruleset: "Inclusion 7: 18 years or older."
ADULT_V1: dict[str, Any] = {
    "id": "M3-INC-07", "ruleset": "M3", "kind": "inclusion", "class": "structured", "text": "18 years or older.",
    "logic": {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}},
}  # fmt: skip
CRITERIA: list[dict[str, Any]] = [WASHOUT, CREATININE, INFECTION, PACEMAKER, ALLERGY, WASHOUT_TODAY, ADULT_V1]
VALUESETS = {
    "VS_CHEMO": (ATC, ["L01XA01", "L01CD01"]),  # cisplatin, paclitaxel
    "VS_CREATININE": (LOINC, ["2160-0"]),
    "VS_SURGERY": (SCT, ["387713003"]),
    "VS_SSI": (ICD, ["T81.49XA"]),
    "VS_PACEMAKER": (SCT, ["14106009"]),
    "VS_PLATINUM_ALLERGY": (SCT, ["293617002"]),
}


# ----------------------------------------------------------------------------------------------- the patients
def _med(mid: str, pid: str, code: str, day: str | None) -> dict[str, Any]:
    r: dict[str, Any] = {
        "resourceType": "MedicationRequest", "id": mid, "status": "completed", "intent": "order",
        "subject": {"reference": f"Patient/{pid}"},
        "medicationCodeableConcept": {"coding": [{"system": ATC, "code": code}]},
    }  # fmt: skip
    if day:
        r["authoredOn"] = day
    return r


def _creatinine(oid: str, pid: str, value: float, day: str) -> dict[str, Any]:
    return {
        "resourceType": "Observation", "id": oid, "status": "final", "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": LOINC, "code": "2160-0"}]}, "effectiveDateTime": day,
        "valueQuantity": {"value": value, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL"},
    }  # fmt: skip


def _surgery(prid: str, pid: str, day: str | None) -> dict[str, Any]:
    r: dict[str, Any] = {
        "resourceType": "Procedure", "id": prid, "status": "completed", "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": SCT, "code": "387713003"}]},
    }  # fmt: skip
    if day:
        r["performedDateTime"] = day
    return r


def _infection(cid: str, pid: str, day: str) -> dict[str, Any]:
    return {
        "resourceType": "Condition", "id": cid, "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": [{"system": ICD, "code": "T81.49XA"}]}, "onsetDateTime": day,
    }  # fmt: skip


#: patient -> their records. An "other" medicine (metformin, A10BA02) keeps a patient from having no medication row
#: at all, which S1 reads on its own (D-914)
RECORDS: dict[str, list[dict[str, Any]]] = {
    # the washout, planned start today (2026-11-20)
    "W-D27": [_med("m-d27", "W-D27", "L01XA01", "2026-10-24")],  # 27 days before
    "W-D28": [_med("m-d28", "W-D28", "L01XA01", "2026-10-23")],  # 28 days before: the first day of the window
    "W-D29": [_med("m-d29", "W-D29", "L01XA01", "2026-10-22")],  # 29 days before: the day before the window
    "W-UNDATED": [_med("m-und", "W-UNDATED", "L01XA01", None)],  # a chemotherapy order with no date
    "W-TODAY": [_med("m-tod", "W-TODAY", "L01XA01", "2026-11-20")],  # on the day of the planned start
    "W-TWO": [_med("m-two-a", "W-TWO", "L01XA01", "2026-10-24"), _med("m-two-b", "W-TWO", "L01CD01", "2026-11-10")],
    "W-NOSTART": [_med("m-nos", "W-NOSTART", "L01XA01", "2026-11-10")],  # nobody gave a planned start
    "W-NONE": [_med("m-non", "W-NONE", "A10BA02", "2026-11-01")],  # no chemotherapy at all
    # a dose ten days ago, and another chemotherapy order with no date
    "W-MIXED": [_med("m-mix-a", "W-MIXED", "L01XA01", "2026-11-10"), _med("m-mix-b", "W-MIXED", "L01CD01", None)],
    # a dose ten days ago and an order dated after the day of the run (an entry error, or a plan)
    "W-AHEAD": [_med("m-ahd-a", "W-AHEAD", "L01XA01", "2026-11-10"), _med("m-ahd-b", "W-AHEAD", "L01CD01", "2026-12-05")],
    "W-AHEADONLY": [_med("m-aho", "W-AHEADONLY", "L01XA01", "2026-12-05")],
    # the planned start was 2026-11-01; a dose on 2026-10-10, 22 days before it
    "W-PAST": [_med("m-pst", "W-PAST", "L01XA01", "2026-10-10")],
    # 100 doses, every third day from 330 to 33 days before the run
    "W-MANY": [_med(f"m-many-{n}", "W-MANY", "L01XA01", (RUN - timedelta(days=33 + 3 * n)).isoformat())
               for n in range(100)],
    # a planned start in the future (2026-12-01)
    "F-DOSED": [_med("m-fut", "F-DOSED", "L01XA01", "2026-11-10")],  # 21 days before the start: stays inside
    "F-CLEAN": [_med("m-fcl", "F-CLEAN", "A10BA02", "2026-11-01")],  # none so far; 11 days are still to come
    # the creatinine window, screening visit today
    "S-OK": [_creatinine("o-ok", "S-OK", 1.0, "2026-11-10")],  # 10 days before
    "S-OLD": [_creatinine("o-old", "S-OLD", 1.0, "2026-11-01")],  # 19 days before: outside
    "S-HIGH": [_creatinine("o-high", "S-HIGH", 2.0, "2026-11-15")],
    "S-NOVISIT": [_creatinine("o-nov", "S-NOVISIT", 1.0, "2026-11-10")],  # nobody gave a screening date
    "S-FUTURE": [_creatinine("o-fut", "S-FUTURE", 1.0, "2026-11-18")],  # the screening visit is on 2026-11-25
    # the infection after the last operation
    "E-INF": [_surgery("p-inf", "E-INF", "2026-09-01"), _infection("c-inf", "E-INF", "2026-09-20")],  # day 19
    "E-LATE": [_surgery("p-late", "E-LATE", "2026-09-01"), _infection("c-late", "E-LATE", "2026-10-15")],  # day 44
    "E-TWO": [_surgery("p-two-a", "E-TWO", "2026-06-01"), _surgery("p-two-b", "E-TWO", "2026-09-01"),
              _infection("c-two", "E-TWO", "2026-06-10")],  # after the first operation, before the last
    "E-NOSURG": [_infection("c-nos", "E-NOSURG", "2026-09-20")],
    "E-UNDATED": [_surgery("p-und-a", "E-UNDATED", "2026-09-01"), _surgery("p-und-b", "E-UNDATED", None),
                  _infection("c-und", "E-UNDATED", "2026-09-20")],  # one operation has no date: which is last?
    "E-RECENT": [_surgery("p-rec", "E-RECENT", "2026-11-10"), _infection("c-rec", "E-RECENT", "2026-01-05")],
}  # fmt: skip
ANCHORS = {
    **{p: {"planned_start": RUN} for p in RECORDS if p.startswith("W-") and p != "W-NOSTART"},
    "W-PAST": {"planned_start": date(2026, 11, 1)},
    "F-DOSED": {"planned_start": date(2026, 12, 1)},
    "F-CLEAN": {"planned_start": date(2026, 12, 1)},
    **{p: {"screening": RUN} for p in RECORDS if p.startswith("S-") and p != "S-NOVISIT"},
    "S-FUTURE": {"screening": date(2026, 11, 25)},
}


def _valueset(name: str) -> dict[str, Any]:
    system, codes = VALUESETS[name]
    return {
        "resourceType": "ValueSet", "id": f"m3-{name.lower().replace('_', '-')}", "version": "1.0.0",
        "url": f"https://trialbox.local/fhir/ValueSet/M3-{name}", "status": "active",
        "compose": {"include": [{"system": system, "concept": [{"code": c} for c in codes]}]},
    }  # fmt: skip


def _ruleset(criteria: list[dict[str, Any]] | None = None, family: str | None = None) -> Ruleset:
    """The ruleset as it is read from its files; its SQL holds the criteria v1 can express, as a compile gives.
    ``family``: that value set also stands for a code family (a grouper, D-113)."""
    criteria = CRITERIA if criteria is None else criteria
    base = yaml.safe_load((ROOT / "rulesets" / "GOUT-COH" / "manifest.yaml").read_text("utf-8"))
    manifest = {**base, "id": "M3", "criteria": [c["id"] for c in criteria]}
    manifest.pop("library", None)
    files = {"manifest.yaml": yaml.safe_dump(manifest, allow_unicode=True).encode("utf-8")}
    for c in criteria:
        files[f"ir/{c['id']}.json"] = json.dumps(c).encode("utf-8")
    for name in VALUESETS:
        vs = _valueset(name)
        if name == family:
            vs["extension"] = [{"url": FAMILY_EXT, "valueString": f"{VALUESETS[name][0]}|3877"}]
        files[f"valuesets/{name}.json"] = json.dumps(vs).encode("utf-8")
    rs = Ruleset.from_files(files)
    coded = [c for c in rs.criteria if c.class_ == "structured"]
    rs.sql = SqlGenerator("M3", rs.version, ValueSets("M3", rs.valuesets, Terminology())).render(coded)
    return rs


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from lake.store import Lake

    tmp = tmp_path_factory.mktemp("model-v3")
    src = tmp / "src"
    src.mkdir()
    by_type: dict[str, list[dict[str, Any]]] = {
        "Patient": [
            {"resourceType": "Patient", "id": p, "birthDate": "1970-01-01", "gender": "female"} for p in RECORDS
        ]
    }
    for rows in RECORDS.values():
        for r in rows:
            by_type.setdefault(r["resourceType"], []).append(r)
    for rtype, rows in by_type.items():
        (src / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), src)
    lake = LakeLocal(tmp / "lake", HashEmbedder())
    rs = _ruleset()
    cfg = CascadeConfig(study_id="M3", run_date=RUN, index_mode="single", population=sorted(RECORDS), snapshot=None,
                        anchors=ANCHORS)  # fmt: skip
    return {"rs": rs, "lake": lake, "res": run_cascade(lake, rs, cfg), "tmp": tmp}


def _out(world: dict[str, Any], pid: str, cid: str) -> Outcome:
    t: PatientTrace = world["res"].traces[pid]
    assert t.in_scope, (pid, t.scope_reason)
    return t.outcomes[cid]


def _excluded(o: Outcome) -> bool:
    return o.status == "fail" and o.hard


def _met(o: Outcome) -> bool:
    return o.status == "pass" and o.unknown_kind is None


def _open(o: Outcome, reason: Reason | None = None) -> bool:
    """Left to a person: an inclusion unknown, an exclusion kept with its unknown stated."""
    return o.unknown_kind == "data_gap" and not o.hard and (reason is None or code_of(o.reason) == reason.value)


# ----------------------------------------------------------------------------------------------- the model
def test_the_schema_holds_the_new_anchor_and_domains_and_nothing_else_changed_its_version() -> None:
    schema = json.loads((ROOT / "schemas" / "v4" / "criterion_ir.schema.json").read_text("utf-8"))
    assert schema["$defs"]["Window"]["properties"]["anchor"]["anyOf"][0]["enum"] == [
        "index", "event", "screening", "randomization", "planned_start",
    ]  # fmt: skip
    domains = schema["$defs"]["Atom"]["properties"]["domain"]["enum"]
    assert domains[-2:] == ["device", "allergy"] and len(domains) == 14
    assert schema["properties"]["ir_version"]["const"] == "3.0.0"  # the hash of every stored criterion holds it
    check = Draft202012Validator(schema)
    for doc in (WASHOUT, CREATININE, INFECTION, PACEMAKER, ALLERGY, WASHOUT_TODAY):
        assert not list(check.iter_errors(doc)), doc["id"]
        CriterionIRv3.model_validate(doc)


@pytest.mark.parametrize("member", ["planned_start", "device", "allergy"])
def test_the_v1_schema_does_not_take_a_v3_member(member: str) -> None:
    """A v1 criterion file reads exactly as before: the anchor and the domains exist in model v3 only."""
    logic: dict[str, Any] = {"domain": "medication", "valueset": "VS_CHEMO"}
    if member == "planned_start":
        logic["window"] = {"from_days": -28, "to_days": 0, "anchor": member}
    else:
        logic["domain"] = member
    doc = {"id": "M3-EXC-09", "ruleset": "M3", "kind": "exclusion", "class": "structured", "text": "x", "logic": logic}
    with pytest.raises(ValidationError):
        CriterionIR.model_validate(doc)
    with pytest.raises(Exception, match=member):
        validate("criterion_ir", doc)
    with pytest.raises(ValidationError):  # and a ruleset file that does not declare version 3 is refused as before
        Ruleset.from_files({"manifest.yaml": b"{}", "ir/M3-EXC-09.json": json.dumps(doc).encode()})


def test_a_v3_file_is_kept_and_stands_as_a_v1_criterion_every_service_can_read() -> None:
    rs = _ruleset()
    assert sorted(rs.v3) == sorted(c["id"] for c in CRITERIA if "ir_version" in c)
    by = rs.by_id()
    # v1 can write the index washout: it is that v1 criterion, in the ruleset's SQL like any other
    assert by["M3-EXC-06"].class_ == "structured" and '"C_M3-EXC-06"' in rs.sql
    assert by["M3-EXC-06"].model_dump(mode="json", by_alias=True, exclude_none=True)["logic"] == {
        "domain": "medication", "valueset": "VS_CHEMO", "quantifier": "any",
        "window": {"from_days": -28, "to_days": 0, "anchor": "index"},
    }  # fmt: skip
    # v1 cannot write the others: a person decides them wherever model v3 is not evaluated, and no SQL holds them
    for cid in ("M3-EXC-01", "M3-INC-02", "M3-EXC-03", "M3-EXC-04", "M3-EXC-05"):
        face = by[cid]
        assert face.class_ == "human" and face.human_question and f'"C_{cid}"' not in rs.sql
        assert face.logic.model_dump(exclude_unset=True) == {"domain": "demographic", "valueset": "NONE"}
        assert face.kind == rs.v3[cid].kind and face.text == rs.v3[cid].text.source
    assert by["M3-EXC-01"].time_sensitive is True
    assert v1_face(CriterionIRv3.model_validate(WASHOUT))["human_question"].endswith(WASHOUT["text"]["source"])


def test_a_v3_criterion_is_hashed_as_written() -> None:
    rs = _ruleset()
    vs = {name: valueset_content_hash(v) for name, v in rs.valuesets.items()}
    got = criterion_hashes(rs)
    assert got["M3-EXC-01"] == canonical_hash(rs.v3["M3-EXC-01"], vs)
    assert got["M3-EXC-04"] != got["M3-EXC-05"] != got["M3-EXC-01"]  # not the one neutral v1 form they share
    assert got["M3-INC-07"] == canonical_hash(upgrade_v1(ADULT_V1), vs)  # a v1 criterion: as before


def test_the_index_form_names_one_anchor_and_refuses_what_step_1_does_not_run() -> None:
    doc, (anchor, event, pick) = index_form(CriterionIRv3.model_validate(WASHOUT))
    assert anchor == "planned_start" and event is None and pick is None
    assert doc["logic"]["window"] == {"from_days": -28, "to_days": 0}
    doc, (anchor, event, pick) = index_form(CriterionIRv3.model_validate(INFECTION))
    assert (anchor, pick) == ("event", "last") and event is not None and event.valueset == "VS_SURGERY"
    assert doc["logic"] == {"domain": "condition", "valueset": "VS_SSI", "quantifier": "any",
                            "window": {"from_days": 0, "to_days": 30}}  # fmt: skip
    assert sourceless_domains(CriterionIRv3.model_validate(PACEMAKER)) == ["device"]

    def changed(base: dict[str, Any], **window: Any) -> CriterionIRv3:
        d = json.loads(json.dumps(base))
        d["atoms"][-1]["window"].update(window)
        return CriterionIRv3.model_validate(d)

    with pytest.raises(NotStep1, match="randomization"):
        index_form(changed(WASHOUT, anchor="randomization"))
    with pytest.raises(NotStep1, match="first or the last"):
        index_form(changed(INFECTION, event_pick="each"))
    two = json.loads(json.dumps(WASHOUT))
    two["atoms"].append({**CREATININE["atoms"][0], "id": "a2"})
    two["logic"] = {"op": "and", "args": ["a1", "a2"]}
    with pytest.raises(NotStep1, match="more than one anchor"):
        index_form(CriterionIRv3.model_validate(two))
    with pytest.raises(NotStep1, match="class note"):
        index_form(CriterionIRv3.model_validate({**WASHOUT, "class": "note"}))


# ----------------------------------------------------------------------------------------------- the washout
@pytest.mark.parametrize(
    ("pid", "excluded", "flip"),
    [
        # last dose 2026-10-24, 27 days before the start: inside. It is 29 days back on 2026-11-22
        ("W-D27", True, "2026-11-22"),
        # last dose 2026-10-23, the 28th day before the start, which the sentence counts. Out on 2026-11-21
        ("W-D28", True, "2026-11-21"),
        # last dose 2026-10-22, 29 days before: the washout is over on the day of the start; nothing will change
        ("W-D29", False, None),
        # a dose on the day of the planned start itself: inside until 2026-12-18, out on 2026-12-19
        ("W-TODAY", True, "2026-12-19"),
        # two drugs: the later last dose (2026-11-10) decides, 2026-11-10 + 29 days
        ("W-TWO", True, "2026-12-09"),
        ("W-NONE", False, None),
    ],
)
def test_the_28_day_washout_before_the_planned_start(
    world: dict[str, Any], pid: str, excluded: bool, flip: str | None
) -> None:
    o = _out(world, pid, "M3-EXC-01")
    assert (_excluded(o), _met(o)) == (excluded, not excluded), (o.status, o.reason)
    assert o.flip_date == flip
    assert o.anchor == {"kind": "planned_start", "date": "2026-11-20"} and o.stage == "S1"


def test_a_last_dose_with_no_date_gives_no_answer_and_no_flip_date(world: dict[str, Any]) -> None:
    o = _out(world, "W-UNDATED", "M3-EXC-01")
    assert _open(o) and o.status == "pass" and o.flip_date is None  # kept for a person, never a date from no date
    assert [e["record"] for e in o.evidence] == ["m-und"] and o.evidence[0]["date"] in (None, "")


def test_a_dated_dose_beside_an_undated_one_excludes_and_has_no_flip_date(world: dict[str, Any]) -> None:
    # the dose of 2026-11-10 is inside the 28 days: excluded. It leaves on 2026-12-09, but the order with no date
    # may be later still: the day the washout is over cannot be told, so no date is given
    for cid in ("M3-EXC-01", "M3-EXC-06"):
        o = _out(world, "W-MIXED", cid)
        assert _excluded(o) and o.flip_date is None, cid


def test_a_record_dated_after_the_day_of_the_run_gives_no_flip_date(world: dict[str, Any]) -> None:
    # the dose of 2026-11-10 excludes today. An order dated 2026-12-05 is not a dose yet: no day is computed with it
    for cid in ("M3-EXC-01", "M3-EXC-06"):
        o = _out(world, "W-AHEAD", cid)
        assert _excluded(o) and o.flip_date is None, cid
        # only the order dated ahead: nothing in the 28 days before today, and never "excluded from 2026-12-05"
        o = _out(world, "W-AHEADONLY", cid)
        assert _met(o) and o.flip_date is None, cid


def test_a_change_that_is_already_past_is_not_stored_as_one_to_come(world: dict[str, Any]) -> None:
    # planned start 2026-11-01, dose 2026-10-10 (22 days before): excluded for that start. The washout was over for
    # a start from 2026-11-08, which is before today: not a day to wait for, so no flip date
    o = _out(world, "W-PAST", "M3-EXC-01")
    assert _excluded(o) and o.flip_date is None and o.anchor == {"kind": "planned_start", "date": "2026-11-01"}
    assert _met(_out(world, "W-PAST", "M3-EXC-06"))  # 41 days ago by today's washout


def test_the_flip_date_search_is_bounded(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Any chemotherapy in the last 365 days": 100 dated doses give 100 days on which a dose leaves the window.
    At most MAX_DAYS of them are tried, soonest first, in one query per distinct day; here the answer does not
    change within those (later doses are still inside), so no date is given rather than a wrong one."""
    from matching.cascade import v3

    wide = json.loads(json.dumps(WASHOUT_TODAY))
    wide["atoms"][0]["window"]["from_days"] = -365
    asked: list[int] = []
    rows = v3.V3Stage._rows

    def counted(self: Any, crit: Any, need: Any) -> Any:
        asked.append(len(need))
        return rows(self, crit, need)

    monkeypatch.setattr(v3.V3Stage, "_rows", counted)
    cfg = CascadeConfig(study_id="M3", run_date=RUN, index_mode="single", population=["W-MANY", "W-D27"],
                        snapshot=None)  # fmt: skip
    res = run_cascade(world["lake"], _ruleset([wide, ADULT_V1]), cfg)
    many, d27 = res.traces["W-MANY"].outcomes["M3-EXC-06"], res.traces["W-D27"].outcomes["M3-EXC-06"]
    assert _excluded(many) and many.flip_date is None
    assert _excluded(d27) and d27.flip_date == "2027-10-25"  # one dose, 2026-10-24: 366 days later it is outside
    # the queries of the run: no event; none of its own answers (the ruleset's SQL gave them); the records' dates
    # on the day of the run; then the day of the run and at most MAX_DAYS days more for W-MANY, one more for W-D27
    assert asked[-2:] == [1, 1 + v3.MAX_DAYS + 1] and v3.MAX_DAYS == 64


def test_a_planned_start_nobody_gave_gives_unknown_never_a_guess(world: dict[str, Any]) -> None:
    o = _out(world, "W-NOSTART", "M3-EXC-01")  # a dose ten days ago, and still no answer: no start, no window
    assert _open(o, Reason.ANCHOR_DATE_UNKNOWN) and o.flip_date is None and o.anchor is None
    assert verdict_of(o).verdict == "unknown" and verdict_of(o).evidence.reason == "anchor_date_unknown"  # type: ignore[union-attr]


def test_a_planned_start_in_the_future(world: dict[str, Any]) -> None:
    # start 2026-12-01; a dose on 2026-11-10 is 21 days before it and stays inside: excluded today. The washout
    # would be over for a start on 2026-12-09
    o = _out(world, "F-DOSED", "M3-EXC-01")
    assert _excluded(o) and o.flip_date == "2026-12-09" and o.anchor == {"kind": "planned_start", "date": "2026-12-01"}
    # no chemotherapy so far, but 11 days of the window are still to come: not "no chemotherapy", a person confirms
    o = _out(world, "F-CLEAN", "M3-EXC-01")
    assert _open(o, Reason.VERIFY_AT_ANCHOR) and o.status == "pass" and o.flip_date is None


def test_the_same_washout_on_the_index_date_gets_its_flip_date_from_model_v3(world: dict[str, Any]) -> None:
    """The ruleset's own SQL answers it (v1 can write it); the flip date is added because the file declares v3."""
    assert "M3-EXC-06" in world["res"].applied
    want = {"W-D27": "2026-11-22", "W-D28": "2026-11-21", "W-D29": None, "W-TODAY": "2026-12-19",
            "W-TWO": "2026-12-09", "W-NOSTART": "2026-12-09", "F-DOSED": "2026-12-09", "W-NONE": None}  # fmt: skip
    for pid, flip in want.items():
        o = _out(world, pid, "M3-EXC-06")
        assert _excluded(o) is (flip is not None) and o.flip_date == flip and o.anchor is None, pid
    assert _open(_out(world, "W-UNDATED", "M3-EXC-06")) and _out(world, "W-UNDATED", "M3-EXC-06").flip_date is None


# ----------------------------------------------------------------------------------------------- the window
def test_a_window_before_the_screening_visit(world: dict[str, Any]) -> None:
    # 1.0 mg/dL on 2026-11-10, ten days before the visit: met. 2026-11-24 is its 14th day; too old on 2026-11-25
    o = _out(world, "S-OK", "M3-INC-02")
    assert _met(o) and o.flip_date == "2026-11-25" and o.anchor == {"kind": "screening", "date": "2026-11-20"}
    # 1.0 mg/dL on 2026-11-01, 19 days before: no result in the window. Not "not met": nothing was measured
    o = _out(world, "S-OLD", "M3-INC-02")
    assert _open(o, Reason.DATA_GAP) and o.status == "unknown" and o.flip_date is None
    # 2.0 mg/dL on 2026-11-15: not met. From 2026-11-30 that result is out of the window and no longer decides
    o = _out(world, "S-HIGH", "M3-INC-02")
    assert _excluded(o) and o.flip_date == "2026-11-30"
    o = _out(world, "S-NOVISIT", "M3-INC-02")
    assert _open(o, Reason.ANCHOR_DATE_UNKNOWN) and o.status == "unknown" and o.flip_date is None
    # visit on 2026-11-25; 1.0 mg/dL on 2026-11-18 is inside its window, but "the latest result counts" and a week
    # is still to come: not yet met, and an answer nobody gave has no flip date
    o = _out(world, "S-FUTURE", "M3-INC-02")
    assert _open(o, Reason.VERIFY_AT_ANCHOR) and o.status == "unknown" and o.flip_date is None
    assert o.anchor == {"kind": "screening", "date": "2026-11-25"}


# ----------------------------------------------------------------------------------------------- the event
def test_a_window_after_the_last_operation(world: dict[str, Any]) -> None:
    # operated 2026-09-01, infection 2026-09-20 (day 19): excluded
    o = _out(world, "E-INF", "M3-EXC-03")
    assert _excluded(o) and o.anchor == {"kind": "event", "date": "2026-09-01"} and o.flip_date is None
    assert [e["record"] for e in o.evidence] == ["c-inf"]
    # infection 2026-10-15, day 44: after the 30 days
    assert _met(_out(world, "E-LATE", "M3-EXC-03"))
    # operated 2026-06-01 and 2026-09-01; the infection of 2026-06-10 followed the first, not the last
    o = _out(world, "E-TWO", "M3-EXC-03")
    assert _met(o) and o.anchor == {"kind": "event", "date": "2026-09-01"}
    # no operation on record: no day to count from
    assert _open(_out(world, "E-NOSURG", "M3-EXC-03"), Reason.ANCHOR_DATE_UNKNOWN)
    # one operation has no date: which one was last cannot be told, though an infection followed the dated one
    assert _open(_out(world, "E-UNDATED", "M3-EXC-03"), Reason.ANCHOR_DATE_UNKNOWN)
    # operated 2026-11-10, ten days ago: 20 of the 30 days are still to come
    o = _out(world, "E-RECENT", "M3-EXC-03")
    assert _open(o, Reason.VERIFY_AT_ANCHOR) and o.status == "pass"


# ----------------------------------------------------------------------------------------------- device, allergy
@pytest.mark.parametrize("cid", ["M3-EXC-04", "M3-EXC-05"])
def test_a_device_or_an_allergy_criterion_says_the_source_does_not_hold_it(world: dict[str, Any], cid: str) -> None:
    """No lake table holds a device or an allergy for any source, so nobody has an answer and nobody is excluded."""
    for pid in RECORDS:
        o = _out(world, pid, cid)
        assert _open(o, Reason.NOT_IN_SOURCE) and o.status == "pass" and o.flip_date is None, pid
        v = verdict_of(o)
        assert v.verdict == "unknown" and v.evidence is not None and v.evidence.reason == "not_in_source"
    for lang in ("en", "ja", "zh-TW"):
        assert (
            LABELS["not_in_source"][lang] and LABELS["anchor_date_unknown"][lang] and LABELS["verify_at_anchor"][lang]
        )


# ----------------------------------------------------------------------------------------------- the run
def test_only_the_washouts_exclude_and_the_stage_log_counts_the_v3_criteria(world: dict[str, Any]) -> None:
    res = world["res"]
    out = {pid: t.exit_criterion for pid, t in res.traces.items() if t.exit_stage is not None}
    assert out == {
        "W-D27": "M3-EXC-06", "W-D28": "M3-EXC-06", "W-TODAY": "M3-EXC-06", "W-TWO": "M3-EXC-06",
        "W-NOSTART": "M3-EXC-06", "F-DOSED": "M3-EXC-06", "E-INF": "M3-EXC-03", "S-HIGH": "M3-INC-02",
        "W-MIXED": "M3-EXC-06", "W-AHEAD": "M3-EXC-06", "W-PAST": "M3-EXC-01",
    }  # fmt: skip
    # those out by the washouts alone are on the engine's watch-list (the criteria are marked time-sensitive); the
    # infection and the creatinine are not marked so, and exclude
    assert {pid: res.traces[pid].tier for pid in out} == {
        **dict.fromkeys(out, "watchlist"), "E-INF": "excluded", "S-HIGH": "excluded",
    }  # fmt: skip
    assert res.stage("S1").detail["model_v3"] == 5  # the five criteria the ruleset's SQL does not hold
    assert all(t.outcomes["M3-INC-07"].status == "pass" for t in res.traces.values())  # the v1 criterion beside them


def test_the_flip_date_reaches_the_answer_store_row_and_only_there(world: dict[str, Any]) -> None:
    rs, res = world["rs"], world["res"]
    pv = verdicts_of(rs, res.traces["W-D27"])
    assert pv.flips == {"M3-EXC-01": "2026-11-22", "M3-EXC-06": "2026-11-22"}
    rows = answer_store.rows_of("M3", rs.version, {"W-D27": pv}, RUN, SNAPSHOT, "job-1", "2026-11-20T00:00:00+00:00")
    from orchestrator.db import ANSWER_COLUMNS

    col = ANSWER_COLUMNS.index("flip_date")
    assert {r[3]: r[col] for r in rows if r[col]} == pv.flips
    assert verdicts_of(rs, res.traces["W-D29"]).flips == {}
    # the verdict a page or a list shows carries no flip date: showing it is the watch-list's card (10A-11)
    assert all("flip" not in json.dumps(v.model_dump(mode="json")) for v in pv.verdicts)


def test_the_trace_file_holds_the_new_keys_for_v3_outcomes_only(world: dict[str, Any]) -> None:
    paths = write_outputs(world["res"], world["tmp"] / "out")
    by = {json.loads(x)["pid"]: json.loads(x) for x in paths["traces"].read_text("utf-8").splitlines()}
    d27 = by["W-D27"]["outcomes"]
    assert d27["M3-EXC-01"]["flip_date"] == "2026-11-22" and d27["M3-EXC-01"]["anchor"]["kind"] == "planned_start"
    assert "flip_date" not in d27["M3-INC-07"] and "anchor" not in d27["M3-INC-07"]  # the v1 criterion: as before
    assert "flip_date" not in by["W-D29"]["outcomes"]["M3-EXC-01"]


def test_what_step_1_does_not_run_is_a_persons_in_the_cascade_too(world: dict[str, Any]) -> None:
    """Windows on two anchors in one criterion, and an event whose value set stands for a code family (a record of
    the family outside the list could be the last operation): the engine gives no answer, a person decides."""
    two = json.loads(json.dumps(WASHOUT))
    two["atoms"].append({**CREATININE["atoms"][0], "id": "a2"})
    two["logic"] = {"op": "and", "args": ["a1", "a2"]}
    for rs in (_ruleset([two, ADULT_V1]), _ruleset([INFECTION, ADULT_V1], family="VS_SURGERY")):
        cid = rs.manifest.criteria[0]
        cfg = CascadeConfig(study_id="M3", run_date=RUN, index_mode="single", population=["W-D27", "E-INF"],
                            snapshot=None, anchors=ANCHORS)  # fmt: skip
        res = run_cascade(world["lake"], rs, cfg)
        for t in res.traces.values():
            assert t.outcomes[cid].status == "pending_human" and t.exit_stage is None, (cid, t.pid)
            assert t.outcomes["M3-INC-07"].status == "pass"
        assert "model_v3" not in res.stage("S1").detail


def test_the_v1_evaluator_never_answers_a_v3_only_criterion(world: dict[str, Any]) -> None:
    """The path that does not evaluate model v3 (MICROBATCH's re-check, ``TB_SCREEN_PIPELINE=v1``): a criterion v1
    cannot write is a person's there, whatever the records say; the one v1 can write is answered as a v1 criterion."""
    rs = world["rs"]
    got = evaluate_patients(rs, sorted(RECORDS), RUN, SqlEngine(world["lake"], None), None, 0.75, note_block=False)
    for pid, pv in got.items():
        by = {v.id: v for v in pv.verdicts}
        for cid in ("M3-EXC-01", "M3-INC-02", "M3-EXC-03", "M3-EXC-04", "M3-EXC-05"):
            assert by[cid].verdict == "pending_human", (pid, cid)
        assert pv.flips == {}
    d27 = {v.id: v.verdict for v in got["W-D27"].verdicts}
    assert d27["M3-EXC-06"] == "fail" and got["W-D27"].tier == "excluded"  # the dose 27 days ago, by the v1 SQL
    assert {v.id: v.verdict for v in got["W-D29"].verdicts}["M3-EXC-06"] == "pass"


def test_the_v1_stand_in_of_a_v3_only_criterion_can_never_be_decided_by_a_v1_reader(world: dict[str, Any]) -> None:
    """What every reader of ``Ruleset.criteria`` sees for a criterion v1 cannot write: no coded logic to compile,
    no SQL column, a question for a person; so no v1 reader counts it met or failed, and it is never silent."""
    rs = world["rs"]
    only = [cid for cid, ir in rs.v3.items() if rs.by_id()[cid].class_ == "human"]
    assert sorted(only) == ["M3-EXC-01", "M3-EXC-03", "M3-EXC-04", "M3-EXC-05", "M3-INC-02"]
    gen = SqlGenerator("M3", rs.version, ValueSets("M3", rs.valuesets, Terminology()))
    for cid in only:
        face = rs.by_id()[cid]
        assert face.class_ not in FILTERED + JUDGED and face.note_question is None  # no SQL/CQL, no model
        assert compiled([face]) == [] and f"C_{cid}" not in gen.render([face]) and f"C_{cid}" not in rs.sql
        with pytest.raises(CompileError):  # even read as coded, its logic compiles to nothing
            kind(face.logic)
        assert class_split([face]) == {"structured": 0, "mixed": 0, "note": 0, "human": 1}
        v = human_verdict(face)  # what the v1 evaluator gives it
        assert v.verdict == "pending_human" and decision.basis_of(face, v, pair=True) == "person"
        st = decision.status_of(rs.by_id(), [v], decision.Policy(0.75, True))
        assert st.tier == "high" and st.excluded_by == [] and st.actions == [face.human_question]  # open, never silent
    # the cascade without its v3 stage (a reader that knows nothing of model v3): a person's, for every patient
    blind = Ruleset(manifest=rs.manifest, criteria=rs.criteria, valuesets=rs.valuesets, sql=rs.sql)
    cfg = CascadeConfig(study_id="M3", run_date=RUN, index_mode="single", population=sorted(RECORDS), snapshot=None)
    res = run_cascade(world["lake"], blind, cfg)
    assert set(only) <= set(res.human_criteria) and not set(only) & set(res.applied)
    for t in res.traces.values():
        for cid in only:
            assert t.outcomes[cid].status == "pending_human" and t.exit_criterion != cid, (t.pid, cid)
            assert t.outcomes[cid].flip_date is None


def test_the_new_reason_codes_are_worded_in_three_languages_and_no_v1_answer_can_carry_one() -> None:
    new = ("anchor_date_unknown", "verify_at_anchor", "not_in_source")
    for code in new:
        assert code in CODES and set(LABELS[code]) == {"en", "ja", "zh-TW"}
        for lang in ("en", "ja", "zh-TW"):
            text = label(code, lang)
            assert text and text == LABELS[code][lang] and code not in text and "_" not in text
        assert LABELS[code]["ja"] != LABELS[code]["en"] != LABELS[code]["zh-TW"]
    # no rule of ``code_of`` leads to one: only the code itself does, and only the v3 stage names them
    from tb_common import reasons

    assert not [r for keys, r in reasons._RULES if r.value in new]
    for text in [k for keys, _ in reasons._RULES for k in keys] + ["", "anything else", "matching record"]:
        for verdict in ("pass", "fail", "unknown", "pending_human", None):
            assert code_of(text, verdict) not in new
    users = sorted(
        p.relative_to(ROOT).as_posix()
        for base in ("services", "libs", "tools")
        for p in (ROOT / base).rglob("*.py")
        if any(f"Reason.{c.upper()}" in p.read_text("utf-8") for c in new)
    )
    assert users == ["services/matching/cascade/v3.py"]


# ----------------------------------------------------------------------------------------------- v1 unchanged
RULESET_DIRS = sorted(
    d
    for base in (ROOT / "rulesets", ROOT / "tests" / "fixtures" / "open_data" / "rulesets")
    for d in base.iterdir()
    if (d / "manifest.yaml").exists()
)


@pytest.mark.parametrize("rdir", RULESET_DIRS, ids=lambda d: d.name)
def test_every_stored_ruleset_is_read_exactly_as_before(rdir: Path) -> None:
    """No stored criterion declares version 3, so none is touched: the criteria are the files' own v1 documents,
    the hashes are the v1 ones, and the engine builds no v3 stage."""
    rs = Ruleset.load(rdir)
    assert rs.v3 == {}
    files = sorted((rdir / "ir").glob("*.json"))
    assert len(files) == len(rs.criteria) > 0
    for f, c in zip(files, rs.criteria, strict=True):
        raw = json.loads(f.read_text("utf-8"))
        assert "ir_version" not in raw
        assert c == CriterionIR.model_validate(raw)
    vs = {name: valueset_content_hash(v) for name, v in rs.valuesets.items()}
    assert criterion_hashes(rs) == {c.id: canonical_hash(upgrade_v1(c), vs) for c in rs.active()}


def test_a_v1_outcome_is_written_as_before() -> None:
    t = PatientTrace(pid="P", index_date=RUN, outcomes={"X-INC-01": Outcome("X-INC-01", "pass", "S1")})
    assert t.to_dict()["outcomes"]["X-INC-01"] == {
        "criterion_id": "X-INC-01", "status": "pass", "stage": "S1", "hard": False, "unknown_kind": None,
        "stratum": None, "evidence": [], "reason": "", "rescue": None,
    }  # fmt: skip
