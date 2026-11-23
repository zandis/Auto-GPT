"""What a note answer may do, on every path (D-1069, D-985; R22-16): a note exclusion answered "condition present"
stands only on a quote that STATES the condition. A relative's, a rule-out, a suspected, a negated or a stated-absent
condition is the models' inference: the patient goes to review, never off a list, whichever path screened them.

The rule is one function, :func:`matching.note_answer.note_answer_may` (on :func:`matching.inferred.inferred`). Before
R22-16 only the cascade asked the guard (``engine._map``); the v1 evaluator, which MICROBATCH, NAV, CASE and SCREEN on
v1 run, did not. Three places read the function now, and each is checked where only it can be seen:

* the cascade's ``_map`` (its outcome: SCREEN on the cascade, MICROBATCH's screen of new patients);
* the v1 ``note_verdict`` (the published verdict is ``unknown``, not a ``fail`` the status rule later holds back:
  SCREEN on v1, NAV, CASE, MICROBATCH on v1);
* the status rule's backstop, :func:`matching.decision.answer_of`, over a row stored before the fix (the pool row a
  MICROBATCH re-check re-tiers).

The inputs: the review's four of section 6a and a Japanese criterion (#1327); its second round's absent and negated
forms (「本人のHIV検査は陰性。」, "DM(-)", 否認糖尿病, "Grandmother has HIV.") and a quote that is a clean fragment of a
relative's sentence (the guard read only the quoted fragment); and 32 report sentences of the MedTxt set tagged "only
suspected" or "stated absent", 8 per class and language (NTCIR-16 Real-MedNLP MedTxt-CR, Sociocom NAIST, CC BY 4.0;
picked by the bench, #639 7078754293, as the ones the judge read as present most often). Both models of the pair
agree, confidence 0.9, the quote verbatim in the record. A control per criterion (a quote that states the condition)
still excludes on every path, so no check passes by never excluding.

One small lake and every path that decides a patient's status, driven in process on one box (``tests/inproc_box.py``)
with a scripted pair that reads the text it is shown (``tests/judge_kit.py``), as ``test_path_independence.py`` does.
Synthetic data, and the public report sentences above.
"""

from __future__ import annotations

import base64
import fcntl
import itertools
import json
import os
import pickle
import shutil
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from lake.store import Lake
from matching import decision
from matching.cascade.judge import JudgeReply, verify_span
from matching.inferred import sentence_of
from matching.note_answer import INCLUSION_REASON, INFERRED_REASON, note_answer_may
from orchestrator.scenarios import nav
from orchestrator.scenarios.evaluate import NoteResult, PatientVerdicts, note_verdict
from tb_common.crypto import pid_for_mrn
from tb_common.reasons import code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, CriterionVerdict, Evidence, JobCreate

from tests.inproc_box import Box, make_box
from tests.judge_kit import Decisive, QuotingOracle, quoting_pair
from tests.unit.test_safety_properties import SPAN, _run_for_map

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)
SNAP = "2026-10-04"
TZ = "Asia/Taipei"
PRACT, PRACT2, DEPT = "P12345", "P23456", "RHEU"  # doctors of deploy/settings.example.yaml
POLICY = decision.Policy(0.75, True)  # the world's policy: the default threshold, a pair that may exclude
POLICIES = [decision.Policy(0.75, True), decision.Policy(0.75, False), decision.Policy(0.95, True)]
#: the reason code a published verdict carries for an inferred exclusion (the cascade's, ``verdict_of``)
INFERRED_CODE = code_of(INFERRED_REASON, "unknown", True)

# ------------------------------------------------------------------------------------------------ the criteria
HIV, MI, HCV, HIVJ, DM = "D9-EXC-01", "D9-EXC-02", "D9-EXC-03", "D9-EXC-04", "D9-EXC-05"
NOTE_LOGIC = {"domain": "condition", "valueset": "VS_NOTE", "window": {"anchor": "index", "from_days": -365,
                                                                       "to_days": 0}}  # fmt: skip


def _ir(cid: str, kind: str, class_: str, text: str, logic: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": cid, "kind": kind, "class": class_, "text": text, "label": text[:30], "logic": logic,
            "review": {"status": "approved", "by": "crc1@hospa.test", "at": "2026-10-01T09:00:00+08:00"}, **extra}  # fmt: skip


CRITERIA: list[dict[str, Any]] = [
    _ir("D9-INC-01", "inclusion", "structured", "Age 18 or older",
        {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
    _ir(HIV, "exclusion", "note", "Known HIV infection", NOTE_LOGIC,
        note_question="Do the notes document known HIV infection?"),
    _ir(MI, "exclusion", "note", "History of myocardial infarction", NOTE_LOGIC,
        note_question="Do the notes document a history of myocardial infarction (heart attack)?"),
    _ir(HCV, "exclusion", "note", "Active hepatitis C", NOTE_LOGIC,
        note_question="Do the notes document active hepatitis C?"),
    _ir(HIVJ, "exclusion", "note", "HIV感染症の既往", NOTE_LOGIC,
        note_question="HIV感染症の既往がカルテに記載されていますか？（history of HIV infection）"),
    _ir(DM, "exclusion", "note", "Known diabetes mellitus", NOTE_LOGIC,
        note_question="Do the notes document diabetes mellitus (a risk of infection)?"),
]  # fmt: skip
BY_ID = {c["id"]: CriterionIR.model_validate({**c, "ruleset": "D9"}) for c in CRITERIA}
VALUESETS = {
    "VS_NOTE": {"resourceType": "ValueSet", "id": "VS_NOTE", "name": "VS_NOTE", "status": "active",
                "compose": {"include": [{"system": "http://hl7.org/fhir/sid/icd-10-cm",
                                         "concept": [{"code": "Z99.99", "display": "none"}]}]}},
}  # fmt: skip

# ------------------------------------------------------------------------------------------------ the text
FAMILY = "Mother has HIV."
RULE_OUT = "Rule out myocardial infarction; troponin pending."
SUSPECTED = "Suspected hepatitis C, awaiting PCR."
FAMILY_JA = "母親にHIV感染あり。"
# the controls: a quote that states the condition
HAS_HIV = "Patient has HIV."
HAD_MI = "History of myocardial infarction in 2019."
HAS_HCV = "Active hepatitis C infection on treatment."
HAS_HIV_JA = "HIV感染症あり。"
HAS_DM = "Type 2 diabetes mellitus since 2015."
# the review's second round (#639 7079162788): absent and negated forms, and a clean fragment of a relative's sentence
GRANDMOTHER = "Grandmother has HIV."
OWN_NEGATIVE_JA = "本人のHIV検査は陰性。"
DM_MINUS = "DM(-)"
DENIED_ZH = "否認糖尿病。"
FRAGMENT_SENTENCE = "Her grandmother: HIV infection documented in 2010."
FRAGMENT = "HIV infection documented in 2010"  # alone it states the condition; its sentence is a relative's
# what a note says when the condition is absent (a reader needs a sentence to answer "not present")
ABSENT = {
    HIV: "No HIV infection.",
    MI: "No myocardial infarction.",
    HCV: "No hepatitis C.",
    HIVJ: "HIV感染症の既往なし。",
    DM: "No diabetes mellitus.",
}
# The box's cascade finds a note by the shipped terms table (S2) and, with no embed service, by nothing else: a
# criterion none of whose words the table knows reads "not evaluated". The note questions name a word it knows
# ("heart attack", "infection") and every note holds one, so the cascade judges every criterion on every note
FILLER = "Routine follow-up after a gout attack; no new infection; vitals stable."

PAIR = 0.9  # both models agree at this confidence
ORACLE = {  # the oracle's key is a substring of the criterion's text (the first sentence shown decides)
    "known hiv": [Decisive(FAMILY, confidence=PAIR), Decisive(HAS_HIV, confidence=PAIR),
                  Decisive(FAMILY_JA, confidence=PAIR), Decisive(HAS_HIV_JA, confidence=PAIR),
                  Decisive(GRANDMOTHER, confidence=PAIR), Decisive(OWN_NEGATIVE_JA, confidence=PAIR),
                  Decisive(FRAGMENT, confidence=PAIR), Decisive(ABSENT[HIV], "fail")],
    "myocardial": [Decisive(RULE_OUT, confidence=PAIR), Decisive(HAD_MI, confidence=PAIR), Decisive(ABSENT[MI], "fail")],
    "hepatitis c": [Decisive(SUSPECTED, confidence=PAIR), Decisive(HAS_HCV, confidence=PAIR),
                    Decisive(ABSENT[HCV], "fail")],
    "hiv感染症の既往": [Decisive(FAMILY_JA, confidence=PAIR), Decisive(HAS_HIV_JA, confidence=PAIR),
                   Decisive(OWN_NEGATIVE_JA, confidence=PAIR), Decisive(ABSENT[HIVJ], "fail")],
    "diabetes mellitus": [Decisive(DM_MINUS, confidence=PAIR), Decisive(DENIED_ZH, confidence=PAIR),
                          Decisive(HAS_DM, confidence=PAIR), Decisive(ABSENT[DM], "fail")],
}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the patients
def _note(own: str, about: tuple[str, ...]) -> str:
    """The patient's note: ``own`` and, for every criterion it is not ``about``, the sentence that it is absent."""
    return " ".join([own, *(s for cid, s in ABSENT.items() if cid not in about), FILLER])


PATIENTS: dict[str, dict[str, Any]] = {  # adults born 1960, a booked RHEU visit with PRACT unless said otherwise
    "HIV_FAMILY": {"number": "20000001", "note": _note(f"{FAMILY} Patient tested negative for HIV.", (HIV,))},
    "MI_RULE_OUT": {"number": "20000002", "note": _note(RULE_OUT, (MI,))},
    "HCV_SUSPECTED": {"number": "20000003", "note": _note(SUSPECTED, (HCV,))},
    "HIV_FAMILY_JA": {"number": "20000004", "note": _note(f"{FAMILY_JA}本人のHIV検査は陰性。", (HIV, HIVJ))},
    "HIV_GRANDMOTHER": {"number": "20000005", "note": _note(GRANDMOTHER, (HIV,))},
    "HIV_OWN_NEGATIVE_JA": {"number": "20000006", "note": _note(OWN_NEGATIVE_JA, (HIV, HIVJ))},
    "DM_MINUS": {"number": "20000007", "note": _note(DM_MINUS, (DM,))},
    "DM_DENIED_ZH": {"number": "20000008", "note": _note(DENIED_ZH, (DM,))},
    "HIV_FRAGMENT": {"number": "20000009", "note": _note(FRAGMENT_SENTENCE, (HIV,))},
    "HIV_STATED": {"number": "20000011", "note": _note(HAS_HIV, (HIV,))},
    "MI_STATED": {"number": "20000012", "note": _note(HAD_MI, (MI,))},
    "HCV_STATED": {"number": "20000013", "note": _note(HAS_HCV, (HCV,))},
    "HIV_STATED_JA": {"number": "20000014", "note": _note(HAS_HIV_JA, (HIV, HIVJ))},
    "DM_STATED": {"number": "20000015", "note": _note(HAS_DM, (DM,))},
    # the other doctor's patient: screened first, so MICROBATCH finds everyone else new
    "OTHERDOC": {"number": "20000020", "pract": PRACT2, "note": _note(FILLER, ())},
}
PID = {k: pid_for_mrn(KEY, v["number"]) for k, v in PATIENTS.items()}
WHO = {v: k for k, v in PID.items()}


@dataclass(frozen=True)
class Input:
    """One case: the criterion, the patient whose record holds the quote, and the quote."""

    name: str
    cid: str
    patient: str
    quote: str
    world: str = "exclusions"  # the world whose patient it is: ``exclusions`` (D9) or ``inclusions`` (R7)


INPUTS = [
    Input("1-relative-en", HIV, "HIV_FAMILY", FAMILY),
    Input("2-rule-out-en", MI, "MI_RULE_OUT", RULE_OUT),
    Input("3-suspected-en", HCV, "HCV_SUSPECTED", SUSPECTED),
    Input("4-relative-ja-quote", HIV, "HIV_FAMILY_JA", FAMILY_JA),
    Input("5-relative-ja", HIVJ, "HIV_FAMILY_JA", FAMILY_JA),
    Input("6-grandmother-en", HIV, "HIV_GRANDMOTHER", GRANDMOTHER),
    Input("7-own-test-negative-ja-quote", HIV, "HIV_OWN_NEGATIVE_JA", OWN_NEGATIVE_JA),
    Input("8-own-test-negative-ja", HIVJ, "HIV_OWN_NEGATIVE_JA", OWN_NEGATIVE_JA),
    Input("9-dm-minus", DM, "DM_MINUS", DM_MINUS),
    Input("10-denied-zh", DM, "DM_DENIED_ZH", DENIED_ZH),
    Input("11-fragment-of-a-relatives-sentence", HIV, "HIV_FRAGMENT", FRAGMENT),
]
#: the inputs whose quote alone shows what it is: a stored row keeps the quote, not its sentence
QUOTE_ALONE = [i for i in INPUTS if i.quote != FRAGMENT]
CONTROLS = [
    Input("stated-en-hiv", HIV, "HIV_STATED", HAS_HIV),
    Input("stated-en-mi", MI, "MI_STATED", HAD_MI),
    Input("stated-en-hcv", HCV, "HCV_STATED", HAS_HCV),
    Input("stated-ja-quote", HIV, "HIV_STATED_JA", HAS_HIV_JA),
    Input("stated-ja", HIVJ, "HIV_STATED_JA", HAS_HIV_JA),
    Input("stated-en-dm", DM, "DM_STATED", HAS_DM),
]


def _sentence(i: Input) -> str:
    return sentence_of(i.quote, PATIENTS[i.patient]["note"])


def test_the_inputs_are_inferences_and_the_controls_are_not() -> None:
    """The premise: the one rule sends every input to review and lets every control exclude."""
    for i in INPUTS:
        assert i.quote in PATIENTS[i.patient]["note"]
        may = note_answer_may("exclusion", True, i.quote, BY_ID[i.cid].text, _sentence(i))
        assert may.effect == "review" and may.reason == INFERRED_REASON, i.name
    for i in CONTROLS:
        assert note_answer_may("exclusion", True, i.quote, BY_ID[i.cid].text, _sentence(i)).effect == "excludes", i.name


def test_a_fragment_is_read_in_its_sentence() -> None:
    """The fragment alone states the condition; its sentence is a relative's (the guard read only the fragment)."""
    assert note_answer_may("exclusion", True, FRAGMENT, BY_ID[HIV].text).effect == "excludes"
    assert sentence_of(FRAGMENT, PATIENTS["HIV_FRAGMENT"]["note"]) == FRAGMENT_SENTENCE


# ------------------------------------------------------------------------------------------------ the inclusions (R22-17)
# The second world: an inclusion answered "not met" from the notes (the review's R22-17 input), with its own ruleset
# and patients, so each world's notes say one coherent thing. The cascade finds a note by the shipped terms table (S2):
# the note questions name words it knows ("pain", "infection") and every note holds one.
I_AGE, INC, INCJ, I_HIV = "R7-INC-01", "R7-INC-02", "R7-INC-03", "R7-EXC-01"
I_CRITERIA: list[dict[str, Any]] = [
    _ir(I_AGE, "inclusion", "structured", "Age 18 or older",
        {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
    _ir(INC, "inclusion", "note", "Diagnosis of type 2 diabetes", NOTE_LOGIC,
        note_question="Do the notes document a diagnosis of type 2 diabetes (not a pain or an infection)?"),
    _ir(INCJ, "inclusion", "note", "2型糖尿病の診断", NOTE_LOGIC,
        note_question="2型糖尿病の診断がカルテに記載されていますか？（type 2 diabetes; not a pain or an infection）"),
    _ir(I_HIV, "exclusion", "note", "Known HIV infection", NOTE_LOGIC,
        note_question="Do the notes document known HIV infection?"),
]  # fmt: skip
I_BY_ID = {c["id"]: CriterionIR.model_validate({**c, "ruleset": "R7"}) for c in I_CRITERIA}
OFF_TOPIC = "Patient denies chest pain."
ON_TOPIC = "No history of diabetes. HbA1c 5.2%."
OFF_TOPIC_JA = "胸痛は否定。"
ON_TOPIC_JA = "糖尿病の既往なし。HbA1c 5.2%。"
MET = {INC: "Type 2 diabetes on metformin.", INCJ: "2型糖尿病で治療中。"}  # each inclusion met, when nothing else
NO_HIV = "No HIV infection."
I_FILLER = "Routine follow-up; no new infection; vitals stable."
I_ORACLE = {
    "2型糖尿病の診断": [Decisive(OFF_TOPIC_JA, "fail", PAIR), Decisive(ON_TOPIC_JA, "fail", PAIR), Decisive(MET[INCJ])],
    "type 2 diabetes": [Decisive(OFF_TOPIC, "fail", PAIR), Decisive(ON_TOPIC, "fail", PAIR), Decisive(MET[INC])],
    "known hiv": [Decisive(HAS_HIV, confidence=PAIR), Decisive(NO_HIV, "fail")],
}  # fmt: skip


def _i_note(own: str, cid: str | None = None, hiv: str = NO_HIV) -> str:
    """``own``, each inclusion other than ``cid`` met, the HIV sentence and the filler."""
    return " ".join([own, *(s for k, s in MET.items() if k != cid), hiv, I_FILLER])


I_PATIENTS: dict[str, dict[str, Any]] = {  # born 1960 unless said, a booked RHEU visit with PRACT unless said
    "OFF_TOPIC_EN": {"number": "20000101", "note": _i_note(f"{OFF_TOPIC} Vitals stable.", INC)},
    "ON_TOPIC_EN": {"number": "20000102", "note": _i_note(ON_TOPIC, INC)},
    "OFF_TOPIC_JA": {"number": "20000103", "note": _i_note(f"{OFF_TOPIC_JA}バイタル安定。", INCJ)},
    "ON_TOPIC_JA": {"number": "20000104", "note": _i_note(ON_TOPIC_JA, INCJ)},
    # the controls
    "CODED_FAIL": {"number": "20000111", "born": "2014-01-01", "note": _i_note("")},  # 12: the coded inclusion fails
    "I_HIV_STATED": {"number": "20000112", "note": _i_note("", hiv=HAS_HIV)},
    # the other doctor's patient: screened first, so MICROBATCH finds everyone else new
    "I_OTHERDOC": {"number": "20000120", "pract": PRACT2, "note": _i_note("")},
}
I_INPUTS = [
    Input("a-off-topic-en", INC, "OFF_TOPIC_EN", OFF_TOPIC, "inclusions"),
    Input("b-on-topic-en", INC, "ON_TOPIC_EN", ON_TOPIC, "inclusions"),
    Input("c-off-topic-ja", INCJ, "OFF_TOPIC_JA", OFF_TOPIC_JA, "inclusions"),
    Input("d-on-topic-ja", INCJ, "ON_TOPIC_JA", ON_TOPIC_JA, "inclusions"),
]
I_CONTROLS = [
    Input("coded-inclusion-fails", I_AGE, "CODED_FAIL", "", "inclusions"),
    Input("exclusion-stated", I_HIV, "I_HIV_STATED", HAS_HIV, "inclusions"),
]
#: every criterion of both worlds, by id (the ids differ)
ALL_BY_ID = {**BY_ID, **I_BY_ID}
I_PID = {k: pid_for_mrn(KEY, v["number"]) for k, v in I_PATIENTS.items()}
WHO.update({v: k for k, v in I_PID.items()})


def test_the_inclusion_inputs_are_in_their_patients_notes_and_go_to_review() -> None:
    for i in [*I_INPUTS, I_CONTROLS[1]]:
        assert i.quote in I_PATIENTS[i.patient]["note"], i.name
    for i in I_INPUTS:
        may = note_answer_may("inclusion", False, i.quote, I_BY_ID[i.cid].text, _i_sentence(i))
        assert (may.effect, may.reason, may.reading_stands) == ("review", INCLUSION_REASON, True), i.name


def _i_sentence(i: Input) -> str:
    return sentence_of(i.quote, I_PATIENTS[i.patient]["note"])


@dataclass(frozen=True)
class World:
    """One world: its criteria, patients, scripted pair and the letter of its rulesets (``<L>X``, ``<L>V``, ...)."""

    tag: str
    letter: str
    criteria: list[dict[str, Any]]
    patients: dict[str, dict[str, Any]]
    oracle: dict[str, list[Decisive]]


# ------------------------------------------------------------------------------------------------ the world
def _res(rtype: str, rid: str, **body: Any) -> dict[str, Any]:
    return {"resourceType": rtype, "id": rid, **body}


def build_lake(nd: Path, lake_dir: Path, patients: dict[str, dict[str, Any]]) -> None:
    types = ("Patient", "Practitioner", "Appointment", "Encounter", "DocumentReference", "Condition", "Consent")
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in types}
    for pr in (PRACT, PRACT2):
        out["Practitioner"].append(_res("Practitioner", pr, name=[{"text": f"Dr {pr} (synthetic)"}]))
    for p in patients.values():
        pid = pid_for_mrn(KEY, p["number"])
        ref, pract = {"reference": f"Patient/{pid}"}, p.get("pract", PRACT)
        out["Patient"].append(_res("Patient", pid, gender="female", birthDate=p.get("born", "1960-01-01")))
        out["Appointment"].append(_res(
            "Appointment", f"{pid}-a", status="booked", start="2026-10-08T09:00:00+08:00",
            serviceType=[{"coding": [{"code": DEPT}]}],
            participant=[{"actor": ref}, {"actor": {"reference": f"Practitioner/{pract}"}}]))  # fmt: skip
        out["Encounter"].append(_res(
            "Encounter", f"{pid}-e", status="finished", subject=ref, serviceType={"coding": [{"code": DEPT}]},
            participant=[{"individual": {"reference": f"Practitioner/{pract}"}}],
            period={"start": "2026-09-20T09:00:00+08:00", "end": "2026-09-20T09:30:00+08:00"}))  # fmt: skip
        out["DocumentReference"].append(_res(
            "DocumentReference", f"{pid}-d1", subject=ref, date="2026-09-20T09:00:00+08:00", type={"text": "progress"},
            content=[{"attachment": {"contentType": "text/plain",
                                     "data": base64.b64encode(p["note"].encode()).decode()}}]))  # fmt: skip
    nd.mkdir(parents=True)
    for t, rows in out.items():
        (nd / f"{t}.ndjson").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    Lake(lake_dir, TZ).rebuild(SNAP, HashEmbedder(), nd)


def write_ruleset(root: Path, rid: str, base: str, criteria: list[dict[str, Any]], **manifest: Any) -> Ruleset:
    """``criteria`` as the approved ruleset ``rid`` under the manifest of the committed ruleset ``base``."""
    crits = [CriterionIR.model_validate({**c, "ruleset": rid}) for c in criteria]
    sql = SqlGenerator(rid, "1.0.0", ValueSets(rid, VALUESETS, Terminology())).render(
        [c for c in crits if c.class_ == "structured"]
    )
    m = Ruleset.load(ROOT / "rulesets" / base).manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    m.update({"id": rid, "version": "1.0.0", "criteria": [c.id for c in crits], "trial_alias": rid, **manifest})
    for k in ("library", "equivalence", "variants", "source_documents"):
        m.pop(k, None)
    d = root / rid
    shutil.rmtree(d, ignore_errors=True)
    for sub in ("ir", "valuesets", "sql"):
        (d / sub).mkdir(parents=True)
    (d / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for c in crits:
        (d / "ir" / f"{c.id}.json").write_text(c.model_dump_json(by_alias=True, exclude_none=True), encoding="utf-8")
    for k, v in VALUESETS.items():
        (d / "valuesets" / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    (d / "sql" / f"{rid}.sql").write_text(sql, encoding="utf-8")
    return Ruleset.load(d)


@dataclass
class Seen:
    """What one path published about each patient: a status word (None: nothing published about the patient) and
    each published verdict row (as JSON)."""

    status: dict[str, str | None] = field(default_factory=dict)
    rows: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


def _outputs(box: Box, job: Any) -> dict[str, bytes]:
    return {o.filename: box.store.get(o.minio_key) for o in job.outputs or []}


def _doc(box: Box, job: Any, prefix: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(
        next(v for k, v in _outputs(box, job).items() if k.startswith(prefix) and k.endswith(".json"))
    )
    return out


def _rows(criteria: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {v["id"]: v for v in criteria}


def run_job(box: Box, subject: str, sender: str = "crc1@hospa.test", files: tuple[tuple[str, bytes], ...] = ()) -> Any:
    before = {j.job_id for j in box.orch.db.find(limit=1000)}
    words = subject.split()
    if words[0] == "MICROBATCH":
        opts = dict(w.split("=", 1) for w in words[2:])
        box.orch.create(JobCreate(type="MICROBATCH", ruleset=words[1], requested_by="scheduler", options=opts or None))
    else:
        assert box.mail(subject, files, sender=sender) == "Processed", subject
    box.orch.drain()
    (job,) = [j for j in box.orch.db.find(limit=1000) if j.job_id not in before]
    assert job.state == "done", (subject, job.error)
    return job


def screen_seen(box: Box, job: Any) -> Seen:
    s = Seen()
    for r in _doc(box, job, "candidate_list_")["rows"]:
        s.status[WHO[r["pid"]]] = r["tier"]
        s.rows[WHO[r["pid"]]] = _rows(r["criteria"])
    for r in _doc(box, job, "excluded_")["rows"]:
        s.status[WHO[r["pid"]]] = "excluded"
        s.rows[WHO[r["pid"]]] = {v["id"]: {"id": v["id"], "verdict": "fail"} for v in r["criteria"]}
    return s


def pool_seen(box: Box, rid: str) -> Seen:
    s = Seen()
    for p in box.orch.db.pool(rid):
        s.status[WHO[p["pid"]]] = p["tier"]
        s.rows[WHO[p["pid"]]] = _rows(p["verdicts"])
    return s


def new_patients_seen(box: Box, job: Any) -> Seen:
    screened = {WHO[p] for p in _doc(box, job, "new_screened_")["pids"]}
    rows = {WHO[r["pid"]]: r for r in _doc(box, job, "candidate_list_")["rows"]}
    s = Seen()
    for k in screened:
        s.status[k] = rows[k]["tier"] if k in rows else "excluded"
        if k in rows:
            s.rows[k] = _rows(rows[k]["criteria"])
    return s


def nav_seen(box: Box, job: Any, patients: dict[str, dict[str, Any]]) -> Seen:
    """NAV: the list a patient is on (``-``: none) and the verdicts of the listed."""
    s = Seen({k: "-" for k in patients})
    for name, rows in _doc(box, job, "nav_lists_")["lists"].items():
        for r in rows:
            if name != "doc_gaps":
                s.status[WHO[r["pid"]]] = name
            s.rows[WHO[r["pid"]]] = _rows(r["criteria"])
    return s


SCR = {"practitioners": [PRACT, PRACT2], "appointment_window_days": 180, "recent_encounter_months": 12,
       "microbatch_window_days": 14}  # fmt: skip


WORLDS = {
    "exclusions": World("exclusions", "D", CRITERIA, PATIENTS, ORACLE),
    "inclusions": World("inclusions", "R", I_CRITERIA, I_PATIENTS, I_ORACLE),
}


def build_world(w: World, tmp: Path, pg_cluster_url: str) -> dict[str, Seen]:
    tmp.mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    sep = "&" if "?" in pg_cluster_url else "?"
    mp.setenv("TB_DB_URL", f"{pg_cluster_url}{sep}tb_prefix=noteans{w.letter.lower()}{os.getpid()}_")
    mp.setenv("TB_TZ", TZ)
    mp.setenv("TB_NOTE_BLOCK", "both_agree")  # the default policy: a note answer excludes when both models agree
    mp.setenv("TB_CANARY_GATE", "off")
    for name in ("TB_SCREEN_JUDGE", "TB_MODEL_SWAP", "TB_STUB_MODELS", "TB_SCREEN_PIPELINE"):
        mp.delenv(name, raising=False)
    try:
        sec = tmp / "sec"
        sec.mkdir()
        (sec / "site_hmac.key").write_bytes(KEY)
        build_lake(tmp / "nd", tmp / "lake", w.patients)
        box = make_box(tmp / "box", tmp / "lake", sec, RUN)
        approved = tmp / "approved"
        box.orch.rulesets_dir = approved
        lt = w.letter
        for rid in ("X", "V", "M", "MV"):
            write_ruleset(approved, lt + rid, "GZQO", w.criteria, scopes={"screen": SCR})
        write_ruleset(approved, lt + "N", "RA-BIO", w.criteria)  # NAV needs an NHI ruleset: the same criteria
        svc = box.orch.services
        judge, verifier = quoting_pair(QuotingOracle(w.oracle))
        svc.llm, svc.verifier = cast(Any, judge), cast(Any, verifier)  # the scripted pair stands in for LlmClient

        seen: dict[str, Seen] = {}
        screen = f"pract={PRACT}"
        seen["screen.cascade"] = screen_seen(box, run_job(box, f"SCREEN {lt}X {screen}"))
        run_job(box, f"MICROBATCH {lt}X incident=0")
        seen["microbatch.recheck.cascade"] = pool_seen(box, f"{lt}X")
        run_job(box, f"SCREEN {lt}M pract={PRACT2}")
        seen["microbatch.new.cascade"] = new_patients_seen(box, run_job(box, f"MICROBATCH {lt}M"))
        seen["nav"] = nav_seen(box, run_job(box, f"NAV {lt}N dept=RHEU", sender="nurse-rheu@hospa.test"), w.patients)
        case = Seen()
        for key, p in w.patients.items():
            if p.get("pract", PRACT) != PRACT:
                continue
            j = run_job(box, f"CASE {lt}X mrn={p['number']} lang=en", files=(("chart.txt", f"2026-09-20\n{p['note']}".encode()),))  # fmt: skip
            rec = json.loads(next(v for k, v in _outputs(box, j).items() if k.endswith(".json")))
            case.status[key] = "sheet"
            case.rows[key] = _rows(rec["criteria"])
        seen["case"] = case
        mp.setenv("TB_SCREEN_PIPELINE", "v1")
        seen["screen.v1"] = screen_seen(box, run_job(box, f"SCREEN {lt}V {screen}"))
        run_job(box, f"MICROBATCH {lt}V incident=0")
        seen["microbatch.recheck.v1"] = pool_seen(box, f"{lt}V")
        run_job(box, f"SCREEN {lt}MV pract={PRACT2}")
        seen["microbatch.new.v1"] = new_patients_seen(box, run_job(box, f"MICROBATCH {lt}MV"))
        return seen
    finally:
        mp.undo()


def _shared(w: World, tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    """Every path run once on one box, shared by the run's xdist workers (the first builds it under a lock)."""
    if worker_id == "master":
        return build_world(w, tmp_path_factory.mktemp(f"noteans-{w.tag}"), pg_cluster_url)
    root = tmp_path_factory.getbasetemp().parent / f"note-answer-every-path-{w.tag}"
    root.mkdir(exist_ok=True)
    done = root / "world.pickle"
    with (root / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not done.exists():
                done.write_bytes(pickle.dumps(build_world(w, root / f"build-{os.getpid()}", pg_cluster_url)))
            loaded: dict[str, Seen] = pickle.loads(done.read_bytes())
            return loaded
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    return _shared(WORLDS["exclusions"], tmp_path_factory, pg_cluster_url, worker_id)


@pytest.fixture(scope="module")
def inclusion_world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    return _shared(WORLDS["inclusions"], tmp_path_factory, pg_cluster_url, worker_id)


# ------------------------------------------------------------------------------------------------ the paths
#: path -> (what an input patient's status must be, what a control's must be), per world. NAV's lists are not tiers:
#: a patient with an exclusion open is likely_eligible with a 確認 row; one excluded, and one with an inclusion that
#: is not "yes", is on no list (``-``; NAV's rule for the inclusion is checked at ``nav.classify`` below: open, ruled
#: acceptable for ring 0 on #639 7079180333 because rc1 refuses NAV on PRODUCTION). A MICROBATCH re-check re-tiers the
#: pool, which holds no excluded patient. CASE prints a sheet for everyone.
PATHS: dict[str, dict[str, tuple[tuple[str | None, ...], tuple[str | None, ...]]]] = {
    "exclusions": {
        "screen.cascade": (("review",), ("excluded",)),
        "screen.v1": (("review",), ("excluded",)),
        "microbatch.recheck.cascade": (("review",), (None, "excluded")),
        "microbatch.recheck.v1": (("review",), (None, "excluded")),
        "microbatch.new.cascade": (("review",), ("excluded",)),
        "microbatch.new.v1": (("review",), ("excluded",)),
        "nav": (("likely_eligible",), ("-",)),
        "case": (("sheet",), ("sheet",)),
    },
}
PATHS["inclusions"] = {**PATHS["exclusions"], "nav": (("-",), ("-",))}
LISTS = [p for p in PATHS["exclusions"] if p not in ("nav", "case")]  # the paths that publish a tier and the rows
EVERY = [pytest.param(path, i, id=f"{path}-{i.name}") for path in PATHS["exclusions"] for i in [*INPUTS, *I_INPUTS]]
EVERY_CONTROL = [
    pytest.param(path, i, id=f"{path}-{i.world}-{i.name}")
    for path in PATHS["exclusions"]
    for i in [*CONTROLS, *I_CONTROLS]
]


def _seen(request: pytest.FixtureRequest, case: Input) -> dict[str, Seen]:
    seen: dict[str, Seen] = request.getfixturevalue("world" if case.world == "exclusions" else "inclusion_world")
    return seen


@pytest.mark.parametrize(("path", "case"), EVERY)
def test_a_note_answer_never_excludes_on_any_path(request: pytest.FixtureRequest, path: str, case: Input) -> None:
    """The one test of rc1 line 2: every screening scenario, every input of the review, through the one rule. The
    patient's status is review, never excluded.

    * an inferred exclusion (R22-16): the criterion's published verdict is ``unknown`` with the cascade's code for the
      reason and the quote kept, not a ``fail`` that excludes, nor one held back later;
    * an inclusion "not met" from the notes (R22-17): the published row stays "not met" with the quote kept (a person
      reads what the notes said), and the status rule answers it ``unknown``. On the lists, the patient's other note
      criteria were judged: the cascade did not stop at the inclusion as at a hard fail (CAS-3)."""
    s = _seen(request, case)[path]
    want = PATHS[case.world][path][0]
    assert s.status.get(case.patient) in want, (path, case.name, s.status.get(case.patient))
    if case.world == "inclusions" and path == "nav":
        return  # on no list, so nothing published about the patient: NAV's rule is checked below
    row = s.rows[case.patient][case.cid]
    if case.world == "exclusions":
        assert row["verdict"] == "unknown", (path, case.name, row)
    else:
        assert row["verdict"] == "fail", (path, case.name, row)
    if path == "case":  # CASE's sheet row is its own shape: the reason and quote at the top level
        assert row.get("quote") == case.quote, (path, case.name, row)
        return
    ev = row.get("evidence") or {}
    assert ev.get("quote") == case.quote, (path, case.name, row)
    if case.world == "exclusions":
        assert ev.get("reason") == INFERRED_CODE, (path, case.name, row)
    assert decision.answer_of(ALL_BY_ID[case.cid], CriterionVerdict.model_validate(row), POLICY) == "unknown"
    if case.world == "inclusions":
        others = {cid: r["verdict"] for cid, r in s.rows[case.patient].items() if cid != case.cid}
        want_others = {I_AGE: "pass", I_HIV: "pass", (INCJ if case.cid == INC else INC): "pass"}
        assert others == want_others, (path, case.name, others)


@pytest.mark.parametrize(("path", "case"), EVERY_CONTROL)
def test_a_stated_exclusion_or_a_coded_inclusion_still_excludes_on_every_path(
    request: pytest.FixtureRequest, path: str, case: Input
) -> None:
    s = _seen(request, case)[path]
    assert s.status.get(case.patient) in PATHS[case.world][path][1], (path, case.name, s.status.get(case.patient))
    row = s.rows.get(case.patient, {}).get(case.cid)
    if row is not None:  # the excluded list and NAV's "on no list" carry no verdict of the control's criterion
        assert row["verdict"] == "fail", (path, case.name, row)


@pytest.mark.parametrize("tag", ["exclusions", "inclusions"])
def test_each_world_lists_every_input_on_each_list_path(request: pytest.FixtureRequest, tag: str) -> None:
    """The premise: every list path screened the inputs, and the controls are excluded where a list says so (a path
    that published nothing would pass the control check with None on a re-check)."""
    seen: dict[str, Seen] = request.getfixturevalue("world" if tag == "exclusions" else "inclusion_world")
    inputs = INPUTS if tag == "exclusions" else I_INPUTS
    controls = CONTROLS if tag == "exclusions" else I_CONTROLS
    for path in LISTS:
        missing = [i.patient for i in inputs if i.patient not in seen[path].status]
        assert not missing, (path, missing)
    for path in ("screen.cascade", "screen.v1", "microbatch.new.cascade", "microbatch.new.v1"):
        assert all(seen[path].status.get(i.patient) == "excluded" for i in controls), path


# ------------------------------------------------------------------------------------------------ each rule itself
def _stored(i: Input) -> CriterionVerdict:
    """The row a path stored before R22-16 for the input: a pair's final, sure "fail" resting on the quote."""
    return CriterionVerdict(
        id=i.cid,
        verdict="fail",
        evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=i.quote, confidence=PAIR, reason="note"),
        basis="pair",
        final=True,
        prov=["c-judge", "c-verifier"],
    )


AGE_MET = CriterionVerdict(id="D9-INC-01", verdict="pass", evidence=Evidence(resource_refs=[], reason="coded"),
                           basis="coded", prov=[])  # fmt: skip


@pytest.mark.parametrize("case", [pytest.param(i, id=f"pool.stored_row-{i.name}") for i in QUOTE_ALONE])
def test_a_stored_row_on_an_inferred_quote_is_reviewed_by_the_status_rule(case: Input) -> None:
    """The backstop (``decision.answer_of``): the pool row a MICROBATCH re-check re-tiers, stored before the fix. A
    stored row keeps the quote, not its sentence: the fragment input is read where the sentence is (the builders)."""
    v = _stored(case)
    assert decision.answer_of(BY_ID[case.cid], v, POLICY) == "unknown"
    assert decision.status_of(BY_ID, [AGE_MET, v], POLICY).tier == "review"


@pytest.mark.parametrize("case", [pytest.param(i, id=f"pool.stored_row-{i.name}") for i in CONTROLS])
def test_a_stored_row_on_a_stated_quote_still_excludes(case: Input) -> None:
    v = _stored(case)
    assert decision.answer_of(BY_ID[case.cid], v, POLICY) == "no"
    assert decision.status_of(BY_ID, [AGE_MET, v], POLICY).tier == "excluded"


def _note_result(i: Input) -> NoteResult:
    return NoteResult(
        "pass", PAIR, i.quote, "2026-09-20", "note", dids=["d1"], calls=["c-judge", "c-verifier"], sentence=_sentence(i)
    )


@pytest.mark.parametrize("case", [pytest.param(i, id=f"v1.note_verdict-{i.name}") for i in INPUTS])
def test_the_v1_verdict_of_an_inferred_quote_is_unknown(case: Input) -> None:
    """``note_verdict`` (SCREEN on v1, NAV, CASE, MICROBATCH on v1): ``unknown`` with the cascade's reason code,
    no basis, the quote and its note kept."""
    v = note_verdict(BY_ID[case.cid], _note_result(case), pair=True)
    assert (v.verdict, v.basis) == ("unknown", None)
    assert v.evidence is not None
    assert (v.evidence.reason, v.evidence.quote, v.evidence.resource_refs) == (INFERRED_CODE, case.quote, ["DocumentReference/d1"])  # fmt: skip
    assert v.prov == ["c-judge", "c-verifier"]


@pytest.mark.parametrize("case", [pytest.param(i, id=f"v1.note_verdict-{i.name}") for i in CONTROLS])
def test_the_v1_verdict_of_a_stated_quote_still_fails(case: Input) -> None:
    v = note_verdict(BY_ID[case.cid], _note_result(case), pair=True)
    assert (v.verdict, v.basis) == ("fail", "pair")


def _cascade(i: Input) -> Any:
    reply = JudgeReply("pass", PAIR, i.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    return _run_for_map(True)._map(BY_ID[i.cid], reply, {**SPAN, "quote": i.quote, "sentence": _sentence(i)}, "S3")


@pytest.mark.parametrize("case", [pytest.param(i, id=f"cascade.map-{i.name}") for i in INPUTS])
def test_the_cascade_outcome_of_an_inferred_quote_is_unknown(case: Input) -> None:
    o = _cascade(case)
    assert (o.status, o.hard, o.reason) == ("unknown", False, INFERRED_REASON)
    assert all("sentence" not in e for e in o.evidence)  # read by the rule, never published


#: the keys of the cascade's verified span on master: what is published
MASTER_SPAN_KEYS = {"did", "start", "end", "date", "sentence_hash", "quote"}


@pytest.mark.parametrize("case", [pytest.param(i, id=f"published-{i.name}") for i in [*QUOTE_ALONE, *CONTROLS]])
def test_the_sentence_is_read_and_never_published(case: Input) -> None:
    """The sentence the rule reads is carried where the quote is verified (the cascade's span, ``NoteResult``) and
    never published (#639 7087774227): the published evidence is byte-identical to what master's span and master's
    ``NoteResult`` give, for every input whose decision the sentence does not change (the fragment's it does)."""
    ex = [{"did": "d1", "date": "2026-09-20", "text": PATIENTS[case.patient]["note"]}]
    reply = JudgeReply("pass", PAIR, case.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    span = verify_span(reply, ex, date(2026, 1, 1), date(2026, 12, 31))
    assert span is not None and set(span) == MASTER_SPAN_KEYS | {"sentence"} and span["sentence"] == _sentence(case)
    master_span = {k: v for k, v in span.items() if k != "sentence"}
    with_sentence = _run_for_map(True)._map(BY_ID[case.cid], reply, span, "S3")
    as_master = _run_for_map(True)._map(BY_ID[case.cid], reply, master_span, "S3")
    assert json.dumps(with_sentence.evidence, sort_keys=True) == json.dumps(as_master.evidence, sort_keys=True)
    assert (with_sentence.status, with_sentence.hard, with_sentence.reason) == (as_master.status, as_master.hard,
                                                                              as_master.reason)  # fmt: skip
    r = _note_result(case)
    assert r.sentence
    published = note_verdict(BY_ID[case.cid], r, pair=True).model_dump_json()
    assert published == note_verdict(BY_ID[case.cid], replace(r, sentence=""), pair=True).model_dump_json()
    assert case.quote == "" or _sentence(case) not in published.replace(case.quote, "")


@pytest.mark.parametrize("case", [pytest.param(i, id=f"cascade.map-{i.name}") for i in CONTROLS])
def test_the_cascade_outcome_of_a_stated_quote_is_a_hard_fail(case: Input) -> None:
    o = _cascade(case)
    assert (o.status, o.hard) == ("fail", True)


@pytest.mark.parametrize("kind", ["inclusion", "exclusion"])
def test_an_inclusion_is_never_affected(kind: str) -> None:
    """The rule reads exclusions only: an inclusion "met" on the same quote keeps the patient in, on both builders."""
    i = INPUTS[0]
    c = BY_ID[i.cid].model_copy(update={"kind": kind})
    v = note_verdict(c, _note_result(i), pair=True)
    o = _run_for_map(True)._map(
        c, JudgeReply("pass", PAIR, i.quote, None, "both agree", call_id="c1", prompt="judge@test"),
        {**SPAN, "quote": i.quote}, "S3",
    )  # fmt: skip
    if kind == "inclusion":
        assert (v.verdict, o.status) == ("pass", "pass")
    else:
        assert (v.verdict, o.status) == ("unknown", "unknown")


# ------------------------------------------------------------------------------------------------ the inclusion rule itself (R22-17)
def _i_note_row(i: Input, *, basis: Any = "pair", final: bool | None = True, conf: float = PAIR) -> CriterionVerdict:
    """A note "not met" resting on the quote, as a path publishes or stores it."""
    return CriterionVerdict(
        id=i.cid,
        verdict="fail",
        evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=i.quote, confidence=conf, reason="note"),
        basis=basis,
        final=final,
        prov=["c-judge", "c-verifier"],
    )


def _i_met(cid: str) -> CriterionVerdict:
    if cid == I_AGE:
        return CriterionVerdict(id=cid, verdict="pass", evidence=Evidence(resource_refs=[], reason="coded"),
                                basis="coded", prov=[])  # fmt: skip
    return CriterionVerdict(id=cid, verdict="pass",
                            evidence=Evidence(resource_refs=["DocumentReference/d1"], quote="q", confidence=PAIR,
                                              reason="note"), basis="pair", prov=["c"])  # fmt: skip


def _i_patient(row: CriterionVerdict) -> list[CriterionVerdict]:
    return [row if row.id == cid else _i_met(cid) for cid in I_BY_ID]


I_ROWS = [
    pytest.param(i, basis, final, conf, id=f"{i.name}-{basis}-{final}-{conf}")
    for i, (basis, final), conf in itertools.product(
        I_INPUTS, [("pair", True), ("pair", False), ("single", False), (None, None)], (PAIR, 0.5)
    )
]


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: f"t{p.threshold}-block{p.note_block}")
@pytest.mark.parametrize(("case", "basis", "final", "conf"), I_ROWS)
def test_the_status_rule_answers_a_note_inclusion_not_met_unknown_under_every_policy(
    case: Input, basis: Any, final: bool | None, conf: float, policy: decision.Policy
) -> None:
    """``answer_of``: SCREEN on v1, MICROBATCH (a stored pool row too), NAV's answers and the cascade's published tier.
    Whatever the policy, the basis, ``final`` or the confidence: ``unknown``, and the patient's status review."""
    v = _i_note_row(case, basis=basis, final=final, conf=conf)
    assert decision.answer_of(I_BY_ID[case.cid], v, policy) == "unknown"
    assert decision.status_of(I_BY_ID, _i_patient(v), policy).tier == "review"


@pytest.mark.parametrize("case", [pytest.param(i, id=f"mixed-{i.name}") for i in I_INPUTS])
def test_a_mixed_inclusion_the_codes_did_not_settle_is_a_note_answer(case: Input) -> None:
    c = I_BY_ID[case.cid].model_copy(update={"class_": "mixed"})
    v = _i_note_row(case)
    assert decision.is_note_answer(c, v)
    assert decision.answer_of(c, v, POLICY) == "unknown"


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: f"t{p.threshold}-block{p.note_block}")
def test_the_records_answer_and_a_persons_still_exclude(policy: decision.Policy) -> None:
    """Controls of the status rule: a coded inclusion "not met" (structured, and a mixed one the codes settled: no
    model confidence), and a person's "not met" on the note inclusion, exclude under every policy."""
    coded = CriterionVerdict(id=I_AGE, verdict="fail", evidence=Evidence(resource_refs=[], reason="coded"),
                             basis="coded", prov=[])  # fmt: skip
    assert decision.answer_of(I_BY_ID[I_AGE], coded, policy) == "no"
    assert decision.status_of(I_BY_ID, _i_patient(coded), policy).tier == "excluded"
    settled = CriterionVerdict(id=INC, verdict="fail", evidence=Evidence(resource_refs=["Condition/c1"], reason="coded"),
                               basis="coded", prov=[])  # fmt: skip
    assert decision.answer_of(I_BY_ID[INC].model_copy(update={"class_": "mixed"}), settled, policy) == "no"
    person = CriterionVerdict(id=INC, verdict="fail", evidence=Evidence(resource_refs=[], reason="human"),
                              basis="person", prov=[])  # fmt: skip
    assert decision.answer_of(I_BY_ID[INC], person, policy) == "no"


def test_an_exclusion_whose_quote_states_the_condition_still_excludes() -> None:
    v = _i_note_row(I_CONTROLS[1])
    assert decision.answer_of(I_BY_ID[I_HIV], v, POLICY) == "no"
    assert decision.status_of(I_BY_ID, _i_patient(v), POLICY).tier == "excluded"


def _i_note_result(i: Input) -> NoteResult:
    return NoteResult(
        "fail",
        PAIR,
        i.quote,
        "2026-09-20",
        "note",
        dids=["d1"],
        calls=["c-judge", "c-verifier"],
        sentence=_i_sentence(i),
    )


@pytest.mark.parametrize("case", [pytest.param(i, id=f"v1.note_verdict-{i.name}") for i in I_INPUTS])
def test_the_v1_row_stays_not_met_and_the_status_is_review(case: Input) -> None:
    """``note_verdict`` (SCREEN on v1, NAV, CASE, MICROBATCH on v1): the row is the pair's "not met" with its quote;
    the status rule reads it as a person's check."""
    v = note_verdict(I_BY_ID[case.cid], _i_note_result(case), pair=True)
    assert (v.verdict, v.basis) == ("fail", "pair")
    assert v.evidence is not None and v.evidence.quote == case.quote
    assert decision.status_of(I_BY_ID, _i_patient(v), POLICY).tier == "review"


class _IRs:
    """The one thing ``nav.classify`` asks of a ruleset."""

    def by_id(self) -> dict[str, CriterionIR]:
        return I_BY_ID


@pytest.mark.parametrize("case", [pytest.param(i, id=f"nav.classify-{i.name}") for i in I_INPUTS])
def test_nav_reads_an_inclusion_not_met_from_the_notes_as_a_row_to_confirm(case: Input) -> None:
    """NAV (line 83: the status rule's answer per criterion): the inclusion is a 確認 row, not a "no". A patient with
    an inclusion not "yes" is on no NAV list (``nav.lists``), so the row is what NAV's rule changes."""
    v = note_verdict(I_BY_ID[case.cid], _i_note_result(case), pair=True)
    pv = PatientVerdicts("P1", _i_patient(v), "review", [], 0)
    name, missing = nav.classify(cast(Any, _IRs()), pv, None, None, RUN, 42, 90, 0.75, True)
    assert name is None and [m.criterion_id for m in missing] == [case.cid]


@pytest.mark.parametrize("case", [pytest.param(i, id=f"nav.classify-{i.name}") for i in I_CONTROLS])
def test_nav_reads_a_coded_inclusion_or_a_stated_exclusion_as_a_no(case: Input) -> None:
    if case.cid == I_AGE:
        v = CriterionVerdict(id=I_AGE, verdict="fail", evidence=Evidence(resource_refs=[], reason="coded"),
                             basis="coded", prov=[])  # fmt: skip
    else:
        v = _i_note_row(case)
    pv = PatientVerdicts("P1", _i_patient(v), "excluded", [], 0)
    assert nav.classify(cast(Any, _IRs()), pv, None, None, RUN, 42, 90, 0.75, True) == (None, [])


def _i_cascade(i: Input, note_block: bool, stage: str = "S3") -> Any:
    reply = JudgeReply("fail", PAIR, i.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    span = {**SPAN, "quote": i.quote, "sentence": _i_sentence(i)}
    return _run_for_map(note_block)._map(I_BY_ID[i.cid], reply, span, stage)


@pytest.mark.parametrize("note_block", [True, False], ids=["block", "no-block"])
@pytest.mark.parametrize("stage", ["S3", "S4"])
@pytest.mark.parametrize("case", [pytest.param(i, id=f"cascade.map-{i.name}") for i in I_INPUTS])
def test_the_cascade_outcome_of_an_inclusion_not_met_is_a_soft_fail(case: Input, stage: str, note_block: bool) -> None:
    """``engine._map`` (SCREEN on the cascade, MICROBATCH's screen of new patients): "not met", never hard (no CAS-3
    stop, no exclusion, no recall stratum), whatever the policy."""
    o = _i_cascade(case, note_block, stage)
    assert (o.status, o.hard, o.stratum) == ("fail", False, None)


def test_the_cascade_outcome_of_a_stated_exclusion_is_a_hard_fail() -> None:
    c = I_CONTROLS[1]
    reply = JudgeReply("pass", PAIR, c.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    o = _run_for_map(True)._map(I_BY_ID[c.cid], reply, {**SPAN, "quote": c.quote}, "S3")
    assert (o.status, o.hard) == ("fail", True)


# ------------------------------------------------------------------------------------------------ the report sentences
#: (id, lang, certainty, finding, sentence): MedTxt-CR (NTCIR-16 Real-MedNLP, Sociocom NAIST, CC BY 4.0), the bench's
#: 32 of #639 7078754293. ``sentence`` is the report's sentence that carries the tag, verbatim, cut at 199 characters.
MEDTXT: list[tuple[str, str, str, str, str]] = [
    (
        "CR:JP0217-104|3",
        "ja",
        "only suspected",
        "ＩＣＩｓによる肝障害",
        "その機序として，ＩＣＩｓによる自己免疫応答の顕在化，癌細胞のネオ抗原と自己抗原での交差反応の出現といった，従来のアレルギー性，代謝性等の薬物性肝障害とは異なる機序が推定されている，経過からはＩＣＩｓによる肝障害が疑われ，肝生検での病理所見から病態の検討を行った．",
    ),
    (
        "CR:JP0217-108|1",
        "ja",
        "only suspected",
        "腫瘍",
        "腫瘍が増悪する可能性も考慮されたが，肝機能異常が主体病変であり，同日よりステロイドパルス療法（５００ｍｇ／日）を開始した．",
    ),
    (
        "CR:JP0217-29|1",
        "ja",
        "only suspected",
        "急性肝炎",
        "直接型優位のＢｉｌ上昇， ＰＴ７４％と軽度低下し， ＣＴで急性肝炎を疑う所見",
    ),
    (
        "CR:JP0217-29|3",
        "ja",
        "only suspected",
        "薬疹",
        "もともとの類天庖瘡とは異なる皮疹であり，ＣＭＺによる薬疹が疑われ，９月１７口より抗菌薬を中止された．",
    ),
    (
        "CR:JP0217-41|2",
        "ja",
        "only suspected",
        "うっ血肝",
        "経動脈性門脈造影下ＣＴ検査では，肝右葉実質の濃染は不均一でありうっ血肝の状態と考えられた．",
    ),
    (
        "CR:JP0217-44|1",
        "ja",
        "only suspected",
        "食道静脈瘤破裂",
        "同日，食道静脈瘤破裂自然止血後を考慮し， ＥＩＳを施行した．",
    ),
    (
        "CR:JP0217-44|4",
        "ja",
        "only suspected",
        "びまん性出血による下部消化管出血",
        "また，直前ＣＴで指摘された門脈血栓が上腸間膜静脈にまで及んでおり，門脈圧亢進症性腸症で内圧上昇した静脈に更なる内圧上昇が加わり，びまん性出血による下部消化管出血を呈した可能性が示唆された．",
    ),
    (
        "CR:JP1220-166|0",
        "ja",
        "only suspected",
        "心外膜炎",
        "Ｅ内服で手指の腫脹は軽減したが，６月末より発熱，嚥下障害を認めるようになり，７月２日心外膜炎疑いで入院となった。",
    ),
    (
        "CR:JP0217-104|3",
        "en",
        "only suspected",
        "ICIs might be the cause of the liver damage",
        "From the progression of the illness it was suspected that ICIs might be the cause of the liver damage and the findings of the liver biopsy formed the basis of our evaluation.",
    ),
    (
        "CR:JP0217-108|1",
        "en",
        "only suspected",
        "tumor",
        "The possibility of tumor exacerbation was considered, but liver function abnormalities were the main findings, and so steroid pulse therapy (500 mg/day) was started the same day.",
    ),
    (
        "CR:JP0217-29|1",
        "en",
        "only suspected",
        "acute hepatitis",
        "The patient was admitted to our department as an emergency case because she presented elevated bilirubin levels with direct type predominance, a mildly decreased PT of 74%, and CT findings suggestive",
    ),
    (
        "CR:JP0217-29|3",
        "en",
        "only suspected",
        "skin eruption",
        "Her skin rash was different from the original pemphigus, and was suspected to be a skin eruption caused by the CMZ.",
    ),
    (
        "CR:JP0217-41|2",
        "en",
        "only suspected",
        "congestive hepatopathy",
        "Transarterial portal venography (CT) revealed heterogeneous staining of the right lobe of the liver, suggesting congestive hepatopathy.",
    ),
    (
        "CR:JP0217-44|4",
        "en",
        "only suspected",
        "lower gastrointestinal bleeding due to a diffuse hemorrhage",
        "The portal vein thrombus, found in the earlier CT scan, extended into the superior mesenteric vein, suggesting that the vein's internal pressure increased due to portal hypertensive enteropathy, whic",
    ),
    (
        "CR:JP1220-166|0",
        "en",
        "only suspected",
        "Epicarditis",
        "Epicarditis was suspected and the patient was hospitalized on July 2.",
    ),
    (
        "CR:JP1220-166|1",
        "en",
        "only suspected",
        "ectopic thyroid tissue",
        "According to search by needle biopsy, the most probable cause was either ectopic thyroid tissue in the mediastinum or a malignant tumor in the salivary gland tissue.",
    ),
    ("CR:JP0217-110|3", "ja", "stated absent", "脂肪肝，萎縮や腹水", "エコーでは脂肪肝，萎縮や腹水は認めず．"),
    ("CR:JP0217-32|1", "ja", "stated absent", "偶発症", "治療は問題なく終了し，術後大きな偶発症なく経過した．"),
    ("CR:JP0217-67|2", "ja", "stated absent", "器質的疾患", "肝臓内や胆管内に明らかな器質的疾患は認めなかった．"),
    (
        "CR:JP0217-97|2",
        "ja",
        "stated absent",
        "嘔吐",
        "食事再開後嘔吐はないが食事量低下による低アルブミン血症が進行し腹水が再増悪した．",
    ),
    (
        "CR:JP0218-11|0",
        "ja",
        "stated absent",
        "拡大，線維増生",
        "２７）では腫大した表面平滑な赤褐色肝で組織では小葉構造はまったく整で実質部に異常なく，グ鞘域では拡大，線維増生はなく小葉間小胆管の著減及び中等大胆管の異常を認めた。",
    ),
    (
        "CR:JP1220-191|1",
        "ja",
        "stated absent",
        "脂漏性湿疹と乾癬",
        "皮疹は臨床的・組織学的に脂漏性湿疹と乾癬のどちらの性格も有していた。",
    ),
    (
        "CR:JP1220-84|0",
        "ja",
        "stated absent",
        "Ｔ細胞レセプターβ鎖の再構成（Ｔｃβ）",
        "血液検査でＨＴＬＶ－Ｉ ｐｒｏｖｉｒｕｓ陽性，ＡＴＬ抗体価２５６倍以上，Ｔ細胞レセプターβ鎖の再構成（Ｔｃβ）陰性，ＩＬ－２レセプター値高値であったことからＨＴＬＶ－１キャリアーと診断。",
    ),
    ("CR:JP1221-44|2", "ja", "stated absent", "真菌", "頭部膿疱部の培養で表皮ブ菌（＋），黄色ブ菌（－），真菌（－）。"),
    (
        "CR:JP0217-104|1",
        "en",
        "stated absent",
        "primary vulvar tumor",
        "Subsequently, the lung metastases tended to shrink, and the primary vulvar tumor was resected in November, 1 year before 20XX.",
    ),
    (
        "CR:JP0217-32|1",
        "en",
        "stated absent",
        "complications",
        "The procedure was executed without any difficulty, and the patient recovered without any major post-operative complications.",
    ),
    (
        "CR:JP0217-67|2",
        "en",
        "stated absent",
        "evidence of organic disease",
        "There was no obvious evidence of organic disease in the liver or bile ducts.",
    ),
    (
        "CR:JP0217-97|2",
        "en",
        "stated absent",
        "vomited",
        "After resumption of food intake the patient no longer vomited, but due to a decreased level of food intake the hypoalbuminemia progressed and the ascites again worsened.",
    ),
    (
        "CR:JP0218-11|0",
        "en",
        "stated absent",
        "enlargement or fibrosis",
        "A laparoscopic liver biopsy (S.44.3.27 revealed a swollen reddish-brown liver with a smooth surface, a completely lobulated structure, no abnormalities in the parenchyma, no enlargement or fibrosis i",
    ),
    (
        "CR:JP1220-191|1",
        "en",
        "stated absent",
        "seborrheic eczema and psoriasis",
        "The skin rash had clinical and histological characteristics of both seborrheic eczema and psoriasis.",
    ),
    (
        "CR:JP1220-84|0",
        "en",
        "stated absent",
        "T-cell receptor beta chain reconstitution (Tc beta)",
        "HTLV-I provirus blood test was positive, ATL antibody titer was more than 256 times, T-cell receptor beta chain reconstitution (Tc beta) was negative, and IL-2 receptor level was high.",
    ),
    (
        "CR:JP1221-40|0",
        "en",
        "stated absent",
        "pustules",
        "Clinical Progress: With the application of a 3 week course of a topical steroid, the plethora and lichenification of the entire body resolved, and the pustules dropped off.",
    ),
]


def _report(row: tuple[str, str, str, str, str]) -> tuple[CriterionIR, str]:
    """The exclusion a report finding becomes (``tools/medtxt_eval.py``'s form: "Patients with <finding>."), and the
    sentence, which is the quote."""
    _id, _lang, _cert, finding, sentence = row
    c = CriterionIR.model_validate({**CRITERIA[1], "id": "D9-EXC-90", "ruleset": "D9", "text": f"Patients with {finding}.",
                                    "note_question": f"Do the notes document {finding}?"})  # fmt: skip
    return c, sentence


REPORT = [pytest.param(r, id=f"{r[1]}-{r[2].replace(' ', '-')}-{r[0]}") for r in MEDTXT]


def test_the_report_sentences_are_the_benchs_thirty_two() -> None:
    assert len(MEDTXT) == 32 and len({(r[0], r[1]) for r in MEDTXT}) == 32
    for lang in ("ja", "en"):
        for cert in ("only suspected", "stated absent"):
            assert sum(1 for r in MEDTXT if r[1:3] == (lang, cert)) == 8


@pytest.mark.parametrize("row", REPORT)
def test_a_suspected_or_absent_report_finding_never_excludes_on_any_builder(
    row: tuple[str, str, str, str, str],
) -> None:
    """The one rule, the v1 verdict, the cascade's outcome and a stored row: review, never an exclusion."""
    c, q = _report(row)
    may = note_answer_may("exclusion", True, q, c.text, q)
    assert (may.effect, may.reason) == ("review", INFERRED_REASON)
    v = note_verdict(c, NoteResult("pass", PAIR, q, "2026-09-20", "note", dids=["d1"], sentence=q), pair=True)
    assert (v.verdict, v.basis) == ("unknown", None)
    reply = JudgeReply("pass", PAIR, q, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    o = _run_for_map(True)._map(c, reply, {**SPAN, "quote": q, "sentence": q}, "S3")
    assert (o.status, o.hard) == ("unknown", False)
    stored = CriterionVerdict(id=c.id, verdict="fail", basis="pair", final=True, prov=["c-judge", "c-verifier"],
                              evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=q, confidence=PAIR,
                                                reason="note"))  # fmt: skip
    assert decision.answer_of(c, stored, POLICY) == "unknown"
