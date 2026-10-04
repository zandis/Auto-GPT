"""TWPAS prior-authorisation Bundle (SPEC §9.5) per IG ``tw.gov.mohw.nhi.pas`` (1.2.0 offline, DECISIONS D-63):
``Bundle(type=collection)`` with Claim (prior-auth request), Patient, Practitioner, Organization (hospital, NHI),
Coverage, Encounter, the applied MedicationRequest and supporting Observations (gene test with its Specimen and
laboratory, ECOG patient assessment) as the data allow. The bundle carries PHI (identity resolved in-box) and is only
ever stored, validated, pre-checked and — on an explicit ``SUBMIT`` by a physician — posted to the NHI endpoint.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

PAS = "https://nhicore.nhi.gov.tw/pas"
SD = f"{PAS}/StructureDefinition"
CS = f"{PAS}/CodeSystem"
TWCS = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem"
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
UCUM = "http://unitsofmeasure.org"
LOINC = "http://loinc.org"
SCT = "http://snomed.info/sct"
# department code (site) -> NHI consultation department code (TW Core medical-consultation-department-nhi-tw)
NHI_DEPARTMENT = {
    "ONC": "AF",
    "RHEU": "AE",
    "META": "AG",
    "NEPH": "AD",
    "CARD": "AB",
    "FM": "01",
    "ORTH": "06",
    "CHEST": "AC",
}
DAVINCI_RECORDED_DATE = "http://hl7.org/fhir/us/davinci-pas/StructureDefinition/extension-diagnosisRecordedDate"
GENE_LAB_DEFAULT = ("https://dep.mohw.gov.tw", "2023LDTB0002")  # the IG's example LDT laboratory id


class BundleDataMissing(ValueError):
    """Mandatory TWPAS content is not available from the record (reported as a precheck issue)."""


@dataclass
class TwpasInput:
    pid: str
    mrn: str
    name: str
    national_id: str
    gender: str  # male | female | other | unknown
    birth_date: str
    practitioner_id: str
    practitioner_license: str
    org_id: str
    org_name: str
    department: str
    run_date: date
    diagnosis_code: str
    diagnosis_date: str | None
    weight_kg: float | None
    height_cm: float | None
    drug_code: str
    daily_dose_mg: float = 80.0
    days: int = 28
    apply_type: str = "1"  # nhi-apply-type: 1 送核
    continuation: str = "1"  # nhi-continuation-status: 1 初次使用, 2 續用
    line_of_therapy: str = "1"
    program_text: str = ""
    egfr_positive: bool | None = None
    egfr_date: str | None = None
    ecog: int | None = None
    ecog_date: str | None = None
    hospital_mrn_system: str = "https://hospital.trialbox.local/mrn"
    summary: str = ""  # 簡要病摘 (Claim.diagnosis.type.text)
    extra: dict[str, Any] = field(default_factory=dict)


def _id(pid: str, kind: str) -> str:
    return f"{kind}-{hashlib.sha256((pid + kind).encode()).hexdigest()[:16]}"


def _meta(profile: str) -> dict[str, Any]:
    return {"profile": [profile if profile.startswith("http") else f"{SD}/{profile}"]}


def build(inp: TwpasInput, base: str = f"{PAS}") -> dict[str, Any]:
    missing = [
        k
        for k, v in (
            ("weight", inp.weight_kg),
            ("height", inp.height_cm),
            ("name", inp.name),
            ("national_id", inp.national_id),
            ("practitioner_license", inp.practitioner_license),
            ("diagnosis_code", inp.diagnosis_code),
        )
        if not v
    ]
    if inp.egfr_positive is None or not inp.egfr_date:
        missing.append("gene test (Claim invariant: examination, imaging or gene report required)")
    if missing:
        raise BundleDataMissing("missing for TWPAS: " + ", ".join(missing))
    ids = {
        k: _id(inp.pid, k)
        for k in (
            "claim",
            "encounter",
            "patient",
            "practitioner",
            "org",
            "nhi",
            "coverage",
            "medapply",
            "gene",
            "specimen",
            "genelab",
            "ecog",
        )
    }
    ref = {
        k: f"{t}/{ids[k]}"
        for k, t in (
            ("claim", "Claim"),
            ("encounter", "Encounter"),
            ("patient", "Patient"),
            ("practitioner", "Practitioner"),
            ("org", "Organization"),
            ("nhi", "Organization"),
            ("coverage", "Coverage"),
            ("medapply", "MedicationRequest"),
            ("gene", "Observation"),
            ("specimen", "Specimen"),
            ("genelab", "Organization"),
            ("ecog", "Observation"),
        )
    }
    patient = {
        "resourceType": "Patient",
        "id": ids["patient"],
        "meta": _meta("Patient-twpas"),
        "identifier": [
            {
                "use": "official",
                "type": {"coding": [{"system": V2_0203, "code": "NNxxx"}]},
                "system": "http://www.moi.gov.tw",
                "value": inp.national_id,
            },
            {
                "use": "official",
                "type": {"coding": [{"system": V2_0203, "code": "MR"}]},
                "system": inp.hospital_mrn_system,
                "value": inp.mrn,
            },
        ],
        "name": [{"use": "usual", "text": inp.name}],
        "gender": inp.gender,
        "birthDate": inp.birth_date,
    }
    practitioner = {
        "resourceType": "Practitioner",
        "id": ids["practitioner"],
        "meta": _meta("Practitioner-twpas"),
        "identifier": [
            {
                "type": {"coding": [{"system": V2_0203, "code": "MD"}]},
                "system": "https://dep.mohw.gov.tw/DOMA",
                "value": inp.practitioner_license,
            }
        ],
    }
    org = {
        "resourceType": "Organization",
        "id": ids["org"],
        "meta": _meta("Organization-twpas"),
        "identifier": [
            {
                "use": "official",
                "type": {"coding": [{"system": V2_0203, "code": "PRN"}]},
                "system": f"{CS}/organization-identifier-tw",
                "value": inp.org_id,
            }
        ],
        "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/organization-type", "code": "prov"}]}],
        "name": inp.org_name,
    }
    nhi = {
        "resourceType": "Organization",
        "id": ids["nhi"],
        "meta": _meta("https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/Organization-govt-twcore"),
        "identifier": [
            {
                "use": "official",
                "type": {"coding": [{"system": f"{TWCS}/v2-0203", "code": "GOI"}]},
                "system": "https://oid.nat.gov.tw/",
                "value": "A21030000I",
            }
        ],
        "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/organization-type", "code": "govt"}]}],
        "name": "衛生福利部中央健康保險署",
    }
    coverage = {
        "resourceType": "Coverage",
        "id": ids["coverage"],
        "meta": _meta("Coverage-twpas"),
        "status": "active",
        "beneficiary": {"reference": ref["patient"]},
        "payor": [{"reference": ref["nhi"]}],
    }
    encounter = {
        "resourceType": "Encounter",
        "id": ids["encounter"],
        "meta": _meta("Encounter-twpas"),
        "status": "planned",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        "serviceType": {
            "coding": [
                {
                    "system": f"{TWCS}/medical-consultation-department-nhi-tw",
                    "code": NHI_DEPARTMENT.get(inp.department, "02"),
                }
            ]
        },
    }
    start = inp.run_date + timedelta(days=7)
    end = start + timedelta(days=inp.days - 1)
    medapply = {
        "resourceType": "MedicationRequest",
        "id": ids["medapply"],
        "meta": _meta("MedicationRequest-apply-twpas"),
        "status": "on-hold",
        "intent": "plan",
        "medicationCodeableConcept": {"coding": [{"system": f"{CS}/nhi-medication", "code": inp.drug_code}]},
        "subject": {"reference": ref["patient"]},
        "dosageInstruction": [
            {
                "timing": {
                    "repeat": {"boundsPeriod": {"start": start.isoformat(), "end": end.isoformat()}, "count": inp.days},
                    "code": {
                        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-GTSAbbreviation", "code": "QD"}]
                    },
                },
                "route": {"coding": [{"system": SCT, "code": "26643006"}]},
                "doseAndRate": [{"doseQuantity": {"value": inp.daily_dose_mg, "system": UCUM, "code": "mg"}}],
            }
        ],
    }
    sinfo: list[dict[str, Any]] = []

    def info(code: str, **value: Any) -> None:
        sinfo.append(
            {
                "sequence": len(sinfo) + 1,
                "category": {"coding": [{"system": f"{CS}/nhi-supporting-info-type", "code": code}]},
                **value,
            }
        )

    # whole kg / cm: the HL7 validator evaluates the IG's HTWT invariant ((v*100).round() = v*100) with BigDecimal
    # scale semantics that reject one-decimal values such as 60.5 (DECISIONS D-65)
    info("weight", valueQuantity={"value": round(float(inp.weight_kg or 0)), "system": UCUM, "code": "kg"})
    info("height", valueQuantity={"value": round(float(inp.height_cm or 0)), "system": UCUM, "code": "cm"})
    extra: list[dict[str, Any]] = []
    if inp.egfr_positive is not None and inp.egfr_date:
        interp = "POS" if inp.egfr_positive else "NEG"
        answer = ("LA9633-4", "Present") if inp.egfr_positive else ("LA9634-2", "Absent")
        extra += [
            {
                "resourceType": "Organization",
                "id": ids["genelab"],
                "meta": _meta("Organization-genetic-testing-twpas"),
                "identifier": [{"system": GENE_LAB_DEFAULT[0], "value": GENE_LAB_DEFAULT[1]}],
            },
            {
                "resourceType": "Specimen",
                "id": ids["specimen"],
                "meta": _meta("Specimen-twpas"),
                "type": {"coding": [{"system": LOINC, "code": "LP7057-5"}]},
                "subject": {"reference": ref["patient"]},
                "receivedTime": f"{inp.egfr_date}T09:00:00+08:00",
            },
            {
                "resourceType": "Observation",
                "id": ids["gene"],
                "meta": _meta("Observation-diagnostic-twpas"),
                "status": "final",
                "category": [{"coding": [{"system": f"{CS}/nhi-supporting-info-type", "code": "geneInfo"}]}],
                "code": {"coding": [{"system": LOINC, "code": "69548-6"}]},
                "subject": {"reference": ref["patient"]},
                "effectiveDateTime": inp.egfr_date,
                "performer": [{"reference": ref["genelab"]}],
                "valueString": f"EGFR mutation (exon 19 deletion / L858R): {answer[1]}",
                "interpretation": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                                "code": interp,
                            }
                        ]
                    }
                ],
                "method": {"coding": [{"system": LOINC, "code": "LA26418-6"}]},
                "specimen": {"reference": ref["specimen"]},
                "component": [
                    {
                        "code": {"coding": [{"system": LOINC, "code": "21665-5"}]},
                        "valueString": f"EGFR: {answer[1]}",
                        "interpretation": [
                            {"coding": [{"system": LOINC, "code": answer[0], "display": answer[1]}], "text": answer[1]}
                        ],
                    }
                ],
            },
        ]
        info("geneInfo", valueReference={"reference": ref["gene"]})
    if inp.ecog is not None and inp.ecog_date:
        extra.append(
            {
                "resourceType": "Observation",
                "id": ids["ecog"],
                "meta": _meta("Observation-pat-assessment-twpas"),
                "status": "final",
                "category": [{"coding": [{"system": f"{CS}/nhi-supporting-info-type", "code": "patientAssessment"}]}],
                "code": {"coding": [{"system": LOINC, "code": "89247-1"}]},
                "subject": {"reference": ref["patient"]},
                "effectiveDateTime": inp.ecog_date,
                "performer": [{"reference": ref["practitioner"]}],
                "valueInteger": int(inp.ecog),
            }
        )
        info("patientAssessment", valueReference={"reference": ref["ecog"]})
    diagnosis: dict[str, Any] = {
        "extension": [{"url": DAVINCI_RECORDED_DATE, "valueDate": inp.diagnosis_date or inp.run_date.isoformat()}],
        "sequence": 1,
        "diagnosisCodeableConcept": {"coding": [{"system": f"{TWCS}/icd-10-cm-2023-tw", "code": inp.diagnosis_code}]},
        "type": [{"text": inp.summary or inp.program_text or "申請事前審查"}],
    }
    claim = {
        "resourceType": "Claim",
        "id": ids["claim"],
        "meta": _meta("Claim-twpas"),
        "extension": [{"url": f"{SD}/extension-claim-encounter", "valueReference": {"reference": ref["encounter"]}}],
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "institutional"}]},
        "subType": {"coding": [{"system": f"{CS}/nhi-apply-type", "code": inp.apply_type}]},
        "use": "preauthorization",
        "patient": {"reference": ref["patient"]},
        "created": inp.run_date.isoformat(),
        "enterer": {"reference": ref["practitioner"]},
        "provider": {"reference": ref["org"]},
        "priority": {"coding": [{"system": f"{CS}/nhi-tmhb-type", "code": "1"}]},
        "supportingInfo": sinfo,
        "diagnosis": [diagnosis],
        "insurance": [{"sequence": 1, "focal": True, "coverage": {"reference": ref["coverage"]}}],
        "item": [
            {
                "extension": [
                    {"url": f"{SD}/extension-requestedService", "valueReference": {"reference": ref["medapply"]}}
                ],
                "sequence": 1,
                "productOrService": {"coding": [{"system": f"{CS}/nhi-order-type", "code": "1"}]},
                "modifier": [
                    {"coding": [{"system": f"{CS}/nhi-continuation-status", "code": inp.continuation}]},
                    {"coding": [{"system": f"{CS}/nhi-line-of-therapy", "code": inp.line_of_therapy}]},
                ],
                "programCode": [{"text": inp.program_text or "非小細胞肺癌第一線治療"}],
                "quantity": {"value": inp.days, "system": UCUM, "code": "{tbl}"},
            }
        ],
    }
    resources: list[dict[str, Any]] = [claim, encounter, patient, practitioner, org, medapply, coverage, nhi, *extra]
    return {
        "resourceType": "Bundle",
        "id": _id(inp.pid, "bundle"),
        "meta": _meta("Bundle-twpas"),
        "type": "collection",
        "timestamp": f"{inp.run_date.isoformat()}T00:00:00+08:00",
        "entry": [{"fullUrl": f"{base}/{r['resourceType']}/{r['id']}", "resource": r} for r in resources],
    }


def structural_errors(bundle: dict[str, Any]) -> list[str]:
    """R4B model parse of every entry (D-11): catches malformed resources before the HL7 validator runs."""
    from fhir.resources.R4B import get_fhir_model_class

    errors = []
    for e in bundle.get("entry", []):
        r = e["resource"]
        try:
            get_fhir_model_class(r["resourceType"]).model_validate(r)
        except Exception as exc:
            errors.append(f"{r['resourceType']}/{r.get('id')}: {str(exc).splitlines()[0][:200]}")
    return errors
