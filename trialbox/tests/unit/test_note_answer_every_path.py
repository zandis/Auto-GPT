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
import json
import os
import pickle
import shutil
from collections.abc import Iterator
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
from matching.cascade.judge import AgreementJudge, JudgeReply, verify_span
from matching.inferred import inferred, sentence_of
from matching.note_answer import INFERRED_REASON, OTHER_KIND_REASON, note_answer_may
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, note_verdict
from tb_common.crypto import pid_for_mrn
from tb_common.reasons import code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, CriterionVerdict, Evidence, JobCreate

from tests.inproc_box import Box, make_box
from tests.judge_kit import Decisive, QuotingOracle, ScriptedModel, quoting_pair, says
from tests.unit.test_safety_properties import SPAN, _run_for_map

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)
SNAP = "2026-10-04"
TZ = "Asia/Taipei"
PRACT, PRACT2, DEPT = "P12345", "P23456", "RHEU"  # doctors of deploy/settings.example.yaml
POLICY = decision.Policy(0.75, True)  # the world's policy: the default threshold, a pair that may exclude
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
SCREENED = [k for k, v in PATIENTS.items() if v.get("pract", PRACT) == PRACT]


@dataclass(frozen=True)
class Input:
    """One case: the criterion, the patient whose record holds the quote, and the quote."""

    name: str
    cid: str
    patient: str
    quote: str


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
        may = note_answer_may("exclusion", True, i.quote, BY_ID[i.cid].text, _sentence(i), affirmed=True)
        assert may.effect == "review" and may.reason == INFERRED_REASON, i.name
    for i in CONTROLS:
        assert (
            note_answer_may("exclusion", True, i.quote, BY_ID[i.cid].text, _sentence(i), affirmed=True).effect
            == "excludes"
        ), i.name


def test_a_fragment_is_read_in_its_sentence() -> None:
    """The fragment alone states the condition; its sentence is a relative's (the guard read only the fragment)."""
    assert note_answer_may("exclusion", True, FRAGMENT, BY_ID[HIV].text, affirmed=True).effect == "excludes"
    assert sentence_of(FRAGMENT, PATIENTS["HIV_FRAGMENT"]["note"]) == FRAGMENT_SENTENCE


# ------------------------------------------------------------------------------------------------ the world
def _res(rtype: str, rid: str, **body: Any) -> dict[str, Any]:
    return {"resourceType": rtype, "id": rid, **body}


def build_lake(nd: Path, lake_dir: Path) -> None:
    types = ("Patient", "Practitioner", "Appointment", "Encounter", "DocumentReference", "Condition", "Consent")
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in types}
    for pr in (PRACT, PRACT2):
        out["Practitioner"].append(_res("Practitioner", pr, name=[{"text": f"Dr {pr} (synthetic)"}]))
    for key, p in PATIENTS.items():
        pid, ref, pract = PID[key], {"reference": f"Patient/{PID[key]}"}, p.get("pract", PRACT)
        out["Patient"].append(_res("Patient", pid, gender="female", birthDate="1960-01-01"))
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


def write_ruleset(root: Path, rid: str, base: str, **manifest: Any) -> Ruleset:
    """``CRITERIA`` as the approved ruleset ``rid`` under the manifest of the committed ruleset ``base``."""
    crits = [CriterionIR.model_validate({**c, "ruleset": rid}) for c in CRITERIA]
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


def nav_seen(box: Box, job: Any) -> Seen:
    """NAV: the list a patient is on (``-``: none) and the verdicts of the listed."""
    s = Seen({k: "-" for k in PATIENTS})
    for name, rows in _doc(box, job, "nav_lists_")["lists"].items():
        for r in rows:
            if name != "doc_gaps":
                s.status[WHO[r["pid"]]] = name
            s.rows[WHO[r["pid"]]] = _rows(r["criteria"])
    return s


SCR = {"practitioners": [PRACT, PRACT2], "appointment_window_days": 180, "recent_encounter_months": 12,
       "microbatch_window_days": 14}  # fmt: skip


def build_world(tmp: Path, pg_cluster_url: str) -> dict[str, Seen]:
    tmp.mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    sep = "&" if "?" in pg_cluster_url else "?"
    mp.setenv("TB_DB_URL", f"{pg_cluster_url}{sep}tb_prefix=noteans{os.getpid()}_")
    mp.setenv("TB_TZ", TZ)
    mp.setenv("TB_NOTE_BLOCK", "both_agree")  # the default policy: a note answer excludes when both models agree
    mp.setenv("TB_CANARY_GATE", "off")
    for name in ("TB_SCREEN_JUDGE", "TB_MODEL_SWAP", "TB_STUB_MODELS", "TB_SCREEN_PIPELINE"):
        mp.delenv(name, raising=False)
    try:
        sec = tmp / "sec"
        sec.mkdir()
        (sec / "site_hmac.key").write_bytes(KEY)
        build_lake(tmp / "nd", tmp / "lake")
        box = make_box(tmp / "box", tmp / "lake", sec, RUN)
        approved = tmp / "approved"
        box.orch.rulesets_dir = approved
        for rid in ("DX", "DV", "DM", "DMV"):
            write_ruleset(approved, rid, "GZQO", scopes={"screen": SCR})
        write_ruleset(approved, "DN", "RA-BIO")  # NAV needs an NHI ruleset: the same criteria
        svc = box.orch.services
        judge, verifier = quoting_pair(QuotingOracle(ORACLE))
        svc.llm, svc.verifier = cast(Any, judge), cast(Any, verifier)  # the scripted pair stands in for LlmClient

        seen: dict[str, Seen] = {}
        screen = f"pract={PRACT}"
        seen["screen.cascade"] = screen_seen(box, run_job(box, f"SCREEN DX {screen}"))
        run_job(box, "MICROBATCH DX incident=0")
        seen["microbatch.recheck.cascade"] = pool_seen(box, "DX")
        run_job(box, f"SCREEN DM pract={PRACT2}")
        seen["microbatch.new.cascade"] = new_patients_seen(box, run_job(box, "MICROBATCH DM"))
        seen["nav"] = nav_seen(box, run_job(box, "NAV DN dept=RHEU", sender="nurse-rheu@hospa.test"))
        case = Seen()
        for key in SCREENED:
            p = PATIENTS[key]
            j = run_job(box, f"CASE DX mrn={p['number']} lang=en", files=(("chart.txt", f"2026-09-20\n{p['note']}".encode()),))  # fmt: skip
            rec = json.loads(next(v for k, v in _outputs(box, j).items() if k.endswith(".json")))
            case.status[key] = "sheet"
            case.rows[key] = _rows(rec["criteria"])
        seen["case"] = case
        mp.setenv("TB_SCREEN_PIPELINE", "v1")
        seen["screen.v1"] = screen_seen(box, run_job(box, f"SCREEN DV {screen}"))
        run_job(box, "MICROBATCH DV incident=0")
        seen["microbatch.recheck.v1"] = pool_seen(box, "DV")
        run_job(box, f"SCREEN DMV pract={PRACT2}")
        seen["microbatch.new.v1"] = new_patients_seen(box, run_job(box, "MICROBATCH DMV"))
        return seen
    finally:
        mp.undo()


@pytest.fixture(scope="module", autouse=True)
def _reimbursement_open() -> Iterator[None]:
    """Card 9e-9: NAV runs only on a test box with reimbursement switched on; this module's box is (as in
    ``tests/property/test_path_independence.py``)."""
    from orchestrator import reimbursement

    with pytest.MonkeyPatch.context() as m:
        m.setattr(reimbursement, "is_open", lambda *a, **k: True)
        yield


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    """Every path run once on one box, shared by the run's xdist workers (the first builds it under a lock)."""
    if worker_id == "master":
        return build_world(tmp_path_factory.mktemp("noteans"), pg_cluster_url)
    root = tmp_path_factory.getbasetemp().parent / "note-answer-every-path"
    root.mkdir(exist_ok=True)
    done = root / "world.pickle"
    with (root / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not done.exists():
                done.write_bytes(pickle.dumps(build_world(root / f"build-{os.getpid()}", pg_cluster_url)))
            loaded: dict[str, Seen] = pickle.loads(done.read_bytes())
            return loaded
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# ------------------------------------------------------------------------------------------------ the paths
#: path -> (what the inferred patient's status must be, what the control's must be). NAV's lists are not tiers:
#: a patient with an exclusion open is likely_eligible with a 確認 row; one excluded is on no list. A MICROBATCH
#: re-check re-tiers the pool, which holds no excluded patient. CASE prints a sheet for everyone.
PATHS: dict[str, tuple[tuple[str | None, ...], tuple[str | None, ...]]] = {
    "screen.cascade": (("review",), ("excluded",)),
    "screen.v1": (("review",), ("excluded",)),
    "microbatch.recheck.cascade": (("review",), (None, "excluded")),
    "microbatch.recheck.v1": (("review",), (None, "excluded")),
    "microbatch.new.cascade": (("review",), ("excluded",)),
    "microbatch.new.v1": (("review",), ("excluded",)),
    "nav": (("likely_eligible",), ("-",)),
    "case": (("sheet",), ("sheet",)),
}
EVERY = [pytest.param(path, i, id=f"{path}-{i.name}") for path in PATHS for i in INPUTS]
EVERY_CONTROL = [pytest.param(path, i, id=f"{path}-{i.name}") for path in PATHS for i in CONTROLS]


@pytest.mark.parametrize(("path", "case"), EVERY)
def test_an_inferred_exclusion_sends_the_patient_to_review_on_every_path(
    world: dict[str, Seen], path: str, case: Input
) -> None:
    """The patient's status is review (never excluded), and the criterion's published verdict is ``unknown`` with
    the cascade's code for the reason and the quote kept: not a ``fail`` that excludes, nor one held back later."""
    s = world[path]
    assert s.status.get(case.patient) in PATHS[path][0], (path, case.name, s.status.get(case.patient))
    row = s.rows[case.patient][case.cid]
    assert row["verdict"] == "unknown", (path, case.name, row)
    ev = row.get("evidence") or {}
    if path != "case":  # CASE's sheet row is its own shape: the reason and quote at the top level
        assert ev.get("reason") == INFERRED_CODE, (path, case.name, row)
        assert ev.get("quote") == case.quote, (path, case.name, row)
        v = CriterionVerdict.model_validate(row)
        assert decision.answer_of(BY_ID[case.cid], v, POLICY) == "unknown"
    else:
        assert row.get("quote") == case.quote, (path, case.name, row)


@pytest.mark.parametrize(("path", "case"), EVERY_CONTROL)
def test_a_quote_that_states_the_condition_still_excludes_on_every_path(
    world: dict[str, Seen], path: str, case: Input
) -> None:
    s = world[path]
    assert s.status.get(case.patient) in PATHS[path][1], (path, case.name, s.status.get(case.patient))
    row = s.rows.get(case.patient, {}).get(case.cid)
    if row is not None:  # the excluded list and NAV's "on no list" carry no verdict of the control's criterion
        assert row["verdict"] == "fail", (path, case.name, row)


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
        affirmed=True,  # round 5: both models affirmed it (judge v6); a row that does not say is pinned below
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
        "pass",
        PAIR,
        i.quote,
        "2026-09-20",
        "note",
        dids=["d1"],
        calls=["c-judge", "c-verifier"],
        sentence=_sentence(i),
        affirmed=True,
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
    reply = JudgeReply(
        "pass", PAIR, i.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True
    )
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
    reply = JudgeReply(
        "pass", PAIR, case.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True
    )
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
        c, JudgeReply("pass", PAIR, i.quote, None, "both agree", call_id="c1", prompt="judge@test", affirmed=True),
        {**SPAN, "quote": i.quote}, "S3",
    )  # fmt: skip
    if kind == "inclusion":
        assert (v.verdict, o.status) == ("pass", "pass")
    else:
        assert (v.verdict, o.status) == ("unknown", "unknown")


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
    may = note_answer_may("exclusion", True, q, c.text, q, affirmed=True)
    assert (may.effect, may.reason) == ("review", INFERRED_REASON)
    v = note_verdict(
        c, NoteResult("pass", PAIR, q, "2026-09-20", "note", dids=["d1"], sentence=q, affirmed=True), pair=True
    )
    assert (v.verdict, v.basis) == ("unknown", None)
    reply = JudgeReply("pass", PAIR, q, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True)
    o = _run_for_map(True)._map(c, reply, {**SPAN, "quote": q, "sentence": q}, "S3")
    assert (o.status, o.hard) == ("unknown", False)
    stored = CriterionVerdict(id=c.id, verdict="fail", basis="pair", final=True, prov=["c-judge", "c-verifier"], affirmed=True,
                              evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=q, confidence=PAIR,
                                                reason="note"))  # fmt: skip
    assert decision.answer_of(c, stored, POLICY) == "unknown"


# ------------------------------------------------------------------------------------------------ the review's forms
# The independent review of round 2 (#1334, H1 to H3, M1, M2) and the walk's probes of the real judge (#639
# 7100765762): forms a pair could read as "present" that do not state the condition. Fail safe: each goes to review on
# every builder. (criterion, quote, sentence of the record the quote lies in: "" when the quote is the sentence)
DM_EN, DM_JA, DM_ZH = "Known diabetes mellitus", "糖尿病の既往", "糖尿病"
TB = "Active tuberculosis requiring treatment"
REVIEW_FORMS: list[tuple[str, str, str]] = [
    # H1: a question
    (DM_EN, "Diabetes?", "Diabetes? Will check HbA1c."),
    (DM_EN, "DM?", "DM? Will check HbA1c."),
    (DM_JA, "糖尿病？", "糖尿病？HbA1c確認予定。"),
    # H2: negated, a relative's, uncertain, in en, ja and zh-TW
    (DM_EN, "Pt w/o diabetes.", ""),
    (DM_EN, "denying diabetes", ""),
    (DM_EN, "diabetes ruled-out", ""),
    (DM_EN, "diabetes, rule-out", ""),
    (DM_EN, "Mom has diabetes", ""),
    (DM_EN, "FHx: DM", ""),
    (DM_EN, "Diabetes: uncertain", ""),
    (DM_EN, "equivocal for diabetes", ""),
    (DM_EN, "borderline diabetes", ""),
    (DM_EN, "pre-diabetes", ""),
    (DM_JA, "糖尿病は指摘されず", ""),
    (DM_JA, "糖尿病は見られず", ""),
    (DM_JA, "糖尿病の恐れ", ""),
    (DM_ZH, "非糖尿病", ""),
    (DM_ZH, "不是糖尿病", ""),
    (DM_ZH, "糖尿病：否", ""),
    (DM_ZH, "媽媽有糖尿病", ""),
    (DM_ZH, "哥哥有糖尿病", ""),
    (DM_ZH, "姐姐有糖尿病", ""),
    (DM_ZH, "家人有糖尿病", ""),
    # H3: a criterion that names a drug, a treatment or a value is not exempt
    ("Known allergy to study drug", "No known drug allergies.", ""),
    (TB, "No tuberculosis", ""),
    (TB, "Mother has tuberculosis", ""),
    ("Asthma requiring inhaled steroids", "denies asthma", ""),
    # M1: a period after an abbreviation ends no sentence; M2: every mention must be stated
    (DM_EN, "hx. of diabetes", "Mother: hx. of diabetes."),
    ("History of heart failure", "No heart failure, but renal failure.", ""),
    ("Active hepatitis B infection", "Hepatitis B negative, but recent urinary tract infection", ""),
]
#: the same criteria on quotes that state the condition: they still exclude
REVIEW_CONTROLS: list[tuple[str, str]] = [
    (DM_EN, "Type 2 diabetes mellitus since 2015."),
    (DM_JA, "2型糖尿病あり。"),
    (DM_ZH, "有糖尿病。"),
    ("History of heart failure", "Heart failure, EF 25%."),
    (TB, "Active pulmonary tuberculosis on treatment."),
    ("Known allergy to study drug", "Known allergy to the study drug (rash)."),
]


# ------------------------------------------------------------------------------------------------ round 5 (#639 7115208555)
# The re-review of round 4 (#1334 7115208182) put 96 forms through the four builders; 27 still excluded: negated,
# another person's, unknown or pending, and outside the rule (an exposure, a prevention, cured, borderline). The guard
# is now the second net, widened by pattern family (``matching.inferred``: negated, another person, uncertain,
# pending, not now). The forms below are those 27, lane J's five rows (#1327 7094287787), and variants of each
# family in en, ja, zh-TW and zh-CN; with the review's 30 above they are one table through all four builders.
R5_HIV, R5_HCV = "Known HIV infection", "Active hepatitis C"
ROUND5_FORMS: list[tuple[str, str, str]] = [
    # the re-review's 27
    (R5_HIV, "HIV-ve", ""),
    (R5_HIV, "HIV -", ""),
    (R5_HIV, "HIV antibody non-reactive", ""),
    (R5_HIV, "HIV nonreactive", ""),
    (DM_EN, "Non-diabetic", ""),
    (R5_HIV, "HIV（ー）", ""),
    (R5_HIV, "HIV(―)", ""),
    (DM_ZH, "无糖尿病", ""),
    (R5_HIV, "HIV阴性", ""),
    (R5_HIV, "Partner is HIV positive.", ""),
    (R5_HIV, "Boyfriend has HIV.", ""),
    (DM_JA, "パートナーが糖尿病", ""),
    (DM_JA, "おばが糖尿病", ""),
    (DM_ZH, "外公有糖尿病", ""),
    (DM_ZH, "女兒有糖尿病", ""),
    (DM_ZH, "兒子有糖尿病", ""),
    (DM_ZH, "太太有糖尿病", ""),
    (R5_HIV, "HIV status unknown", ""),
    (R5_HIV, "HIV status: unknown.", ""),
    (R5_HIV, "HIV test ordered", ""),
    (R5_HIV, "HIV検査予定", ""),
    (R5_HIV, "On PrEP for HIV prevention", ""),
    (R5_HIV, "HIV exposure in 2019", ""),
    (R5_HCV, "Hepatitis C, cured with DAA in 2018", ""),
    (R5_HCV, "history of hepatitis C, treated, SVR", ""),
    (DM_JA, "糖尿病境界型", ""),
    (DM_JA, "糖尿病予備群", ""),
    # lane J's five rows: the quote's record
    (R5_HIV, "Mother has HIV.", ""),
    ("History of myocardial infarction", "Rule out myocardial infarction; troponin pending.", ""),
    (R5_HCV, "Suspected hepatitis C, awaiting PCR.", ""),
    ("HIV感染が既知の患者", "母親にHIV感染あり。", "母親にHIV感染あり。患者本人のHIV検査は陰性。"),
    (R5_HIV, "母親にHIV感染あり。", "母親にHIV感染あり。患者本人のHIV検査は陰性。"),
    # each family's variants
    (R5_HCV, "HCV-ve", ""),
    (R5_HIV, "HIV: neg", ""),
    (R5_HIV, "HIV Ab (-ve)", ""),
    (R5_HIV, "non-reactive HIV serology", ""),
    (R5_HIV, "HIV (−)", ""),
    (R5_HIV, "HIV（－）", ""),
    (DM_ZH, "無糖尿病", ""),
    (DM_ZH, "否认糖尿病", ""),
    (DM_ZH, "糖尿病：无", ""),
    (R5_HIV, "HIV陰性", ""),
    (R5_HIV, "HIV抗体陰性", ""),
    (DM_EN, "nondiabetic", ""),
    (R5_HIV, "Girlfriend has HIV.", ""),
    (R5_HIV, "Husband is HIV positive.", ""),
    (DM_EN, "Her son has diabetes.", ""),
    (DM_EN, "Grandson has diabetes", ""),
    (DM_EN, "Niece: diabetes", ""),
    (R5_HIV, "Close contact with an HIV-positive person", ""),
    (DM_JA, "叔母が糖尿病", ""),
    (DM_JA, "祖父母が糖尿病", ""),
    (DM_JA, "孫が糖尿病", ""),
    (DM_JA, "夫が糖尿病", ""),
    (DM_ZH, "外婆有糖尿病", ""),
    (DM_ZH, "老公有糖尿病", ""),
    (DM_ZH, "女儿有糖尿病", ""),
    (DM_ZH, "儿子有糖尿病", ""),
    (DM_ZH, "爷爷有糖尿病", ""),
    (DM_ZH, "妈妈有糖尿病", ""),
    (R5_HIV, "HIV test pending", ""),
    (R5_HIV, "HIV screen scheduled", ""),
    (R5_HIV, "Will test for HIV", ""),
    (R5_HIV, "HIV serology sent", ""),
    (R5_HIV, "HIV status not known", ""),
    (R5_HIV, "HIV檢驗待報告", ""),
    (R5_HIV, "HIV检查预约", ""),
    (R5_HIV, "HIV検査結果待ち", ""),
    (R5_HIV, "HIV status: TBD", ""),
    (R5_HCV, "Hepatitis C, eradicated", ""),
    (R5_HCV, "HCV, s/p treatment, SVR12", ""),
    (R5_HCV, "C型肝炎は治癒", ""),
    (R5_HCV, "C型肝炎治療後SVR", ""),
    (R5_HCV, "C型肝炎已治愈", ""),
    (R5_HCV, "丙型肝炎痊癒", ""),
    (R5_HIV, "Needlestick HIV exposure, on PEP", ""),
    (R5_HIV, "HIV prophylaxis", ""),
    (R5_HIV, "HIV暴露後予防", ""),
    (R5_HIV, "HIV暴露", ""),
    (DM_ZH, "糖尿病前期", ""),
    (DM_JA, "境界型糖尿病", ""),
    (DM_JA, "糖尿病予備軍", ""),
    (DM_EN, "prediabetic", ""),
    # a drug criterion reads the quote's sentence too (the re-review's surviving mutant at ``inferred.inferred``)
    ("Known allergy to study drug", "drug allergies", "No known drug allergies."),
    # the external OCR run's forms (#639 7118897121), with variants: a stated mention elsewhere in the sentence, a
    # contrast set off by commas (an aside, not a split), a split on an abbreviation, and a question
    ("History of heart failure", "No heart failure, but renal failure.", ""),
    ("History of heart failure", "No heart failure; however, renal failure.", ""),
    ("Known metastatic disease", "No evidence, however, of metastasis.", ""),
    ("Known metastatic disease", "No sign, however, of metastatic disease.", ""),
    ("Known metastatic disease", "Metastasis, though, is not seen.", ""),
    ("Known metastatic disease", "転移は、しかし、認めない。", ""),
    (DM_EN, "Family hx. diabetes.", ""),
    (DM_EN, "Fam. hx. diabetes", ""),
    (DM_EN, "Fam hx: diabetes", ""),
    (DM_EN, "FHx. DM.", ""),
    ("Known hypertension", "Hypertension?", ""),
    ("Known hypertension", "HTN ?", ""),
    ("Known hypertension", "? hypertension", ""),
    ("高血圧症の既往", "高血圧症？", ""),
    (DM_ZH, "糖尿病?", ""),
    # the OCR deeper pass (#639 7119659794), with variants: a "non-" form, another person by abbreviation, a field
    # coded absent, a question mark before or after
    (DM_EN, "Non-diabetic", ""),
    ("Known hypertension", "Non-hypertensive", ""),
    ("Pregnancy", "Non-pregnant", ""),
    ("Current smoker", "Non-smoker", ""),
    ("Current smoker", "Nonsmoker", ""),
    (DM_EN, "FHx: diabetes", ""),
    (DM_EN, "FH diabetes", ""),
    ("Known hypertension", "Hypertension: N", ""),
    ("Known hypertension", "HTN: N", ""),
    ("Known hypertension", "Hypertension - N", ""),
    (DM_EN, "DM: nil", ""),
    (R5_HCV, "HCV = 0", ""),
    (DM_EN, "?Diabetes", ""),
    (DM_EN, "Diabetes (?)", ""),
    (DM_EN, "DM (?)", ""),
    # the OCR whole-repo sweep, M-ME-1 (#639 7120477377, routed 7120987904): its 26 forms, reproduced on master's guard,
    # and "no hypertension", the sweep's own control (not stated: review)
    ("History of hypertension", "Hypertension: N", ""),
    ("History of hypertension", "Hypertension: No", ""),
    ("History of hypertension", "HTN (-)", ""),
    ("History of hypertension", "Hypertension was excluded", ""),
    ("History of hypertension", "hypertension, denied", ""),
    ("History of hypertension", "HTN: negative", ""),
    ("History of hypertension", "Hypertension: none", ""),
    ("Known diabetes mellitus", "non-diabetic", ""),
    ("Known diabetes mellitus", "Grandmother had diabetes", ""),
    ("Known diabetes mellitus", "aunt with diabetes", ""),
    ("Known diabetes mellitus", "FHx: DM", ""),
    ("History of hypertension", "FH: HTN", ""),
    ("Pregnancy", "pregnancy test negative", ""),
    ("高血壓病史", "高血壓(-)", ""),
    ("高血壓病史", "病人否認高血壓", ""),
    ("高血壓病史", "無高血壓病史", ""),
    ("高血壓病史", "沒有高血壓", ""),
    ("高血壓病史", "未有高血壓", ""),
    ("糖尿病病史", "非糖尿病患者", ""),
    ("懷孕中", "未懷孕", ""),
    ("糖尿病病史", "排除糖尿病", ""),
    ("高血圧症の既往", "高血圧（－）", ""),
    ("妊娠中", "非妊娠", ""),
    ("糖尿病の既往", "糖尿病の既往はない", ""),
    ("糖尿病の既往", "糖尿病既往なし", ""),
    ("高血圧症の既往", "高血圧症は否定的", ""),
    ("History of hypertension", "no hypertension", ""),
    # the same reviewer's review of #1435, M3 (#639 7120989887): its 26 forms
    ("Active hepatitis C", "Hepatitis C ruled out", ""),
    ("Known HIV infection", "HIV: negative", ""),
    ("Known HIV infection", "HIV (-)", ""),
    ("Known HIV infection", "HIV antibody negative.", ""),
    ("Known HIV infection", "患者本人のHIV検査は陰性。", ""),
    ("Known HIV infection", "HIV抗體陰性", ""),
    ("History of hypertension", "無高血壓", ""),
    ("History of hypertension", "沒有高血壓病史", ""),
    ("History of hypertension", "否認高血壓", ""),
    ("History of hypertension", "高血圧(-)", ""),
    ("History of hypertension", "高血圧はありません", ""),
    ("Known diabetes mellitus", "DM: no", ""),
    ("History of myocardial infarction", "排除心肌梗塞", ""),
    ("History of myocardial infarction", "心肌梗塞待排", ""),
    ("History of myocardial infarction", "MI was excluded by troponin", ""),
    ("History of myocardial infarction", "MI unlikely", ""),
    ("History of myocardial infarction", "probable MI", ""),
    ("History of myocardial infarction", "Concern for MI", ""),
    ("History of myocardial infarction", "Evaluate for MI", ""),
    (
        "History of myocardial infarction",
        "Patient denies chest pain, shortness of breath, palpitations, syncope or myocardial infarction",
        "",
    ),
    ("Active hepatitis C", "hepatitis C?", ""),
    ("Known HIV infection", "Wife has HIV.", ""),
    ("Known HIV infection", "Husband is HIV positive.", ""),
    ("Known HIV infection", "Son with HIV", ""),
    ("Pregnancy", "pregnancy test negative", ""),
    ("妊娠中", "妊娠反応陰性", ""),
]
#: stated quotes the widened families must not catch: a prefix "non-" that names the condition, a past procedure
ROUND5_CONTROLS: list[tuple[str, str]] = [
    (R5_HIV, "Patient has HIV."),
    (R5_HIV, "HIV infection on ART since 2019."),
    (R5_HCV, "Active hepatitis C infection on treatment."),
    ("History of myocardial infarction", "NSTEMI (non-ST elevation myocardial infarction) in 2020."),
    ("Lymphoma", "Non-Hodgkin lymphoma, stage II."),
    ("Prior stem cell transplant", "s/p allogeneic HSCT 2019"),
    ("Known metastatic disease", "Metastatic disease to the liver."),  # the OCR forms' controls
    ("Known hypertension", "Hypertension on amlodipine."),
    ("Known hypertension", "HTN, but no diabetes."),  # a contrast between two clauses still splits
    ("Known hypertension", "Hypertension: Y"),  # the deeper pass's controls: a field coded present, a number
    ("Current smoker", "Current smoker, 20 pack-years."),
    ("Pregnancy", "Pregnant, 12 weeks."),
    (R5_HIV, "HIV-1 infection, viral load 0 copies/mL."),
    ("History of hypertension", "Hypertension on amlodipine."),
    ("高血壓病史", "高血壓，服藥中。"),
    ("高血圧症の既往", "高血圧症あり。"),
    ("Pregnancy", "Pregnant, 12 weeks."),
    ("妊娠中", "妊娠12週。"),
    ("糖尿病病史", "第二型糖尿病。"),  # the sweep's criteria, stated
]
#: the re-review's probe of round 4, as posted on #1334 (7115258420): its 96 forms (expected review) and 6 controls
#: (expected to exclude), verbatim. 27 of the 96 excluded on round 4's guard.
P_DM, P_HIV, P_HCV, P_MI = (
    "Known diabetes mellitus",
    "Known HIV infection",
    "Active hepatitis C",
    "History of myocardial infarction",
)
P_DMJ, P_DMZ, P_HIVJ = "糖尿病の既往", "糖尿病病史", "HIV感染症の既往"
PROBE_FORMS: list[tuple[str, str, str]] = [
    (P_DM, "Diabetes?", ""),
    (P_DM, "DM?", ""),
    (P_DM, "糖尿病？", ""),
    (P_DM, "w/o diabetes", ""),
    (P_DM, "denying diabetes", ""),
    (P_DM, "diabetes ruled-out", ""),
    (P_DM, "diabetes, rule-out", ""),
    (P_DM, "Mom has diabetes", ""),
    (P_DM, "FHx: DM", ""),
    (P_DM, "Diabetes: uncertain", ""),
    (P_DM, "equivocal for diabetes", ""),
    (P_DM, "borderline diabetes", ""),
    (P_DM, "pre-diabetes", ""),
    (P_DMJ, "糖尿病は指摘されず", ""),
    (P_DMJ, "糖尿病は見られず", ""),
    (P_DMJ, "糖尿病の恐れ", ""),
    (P_DMZ, "非糖尿病", ""),
    (P_DMZ, "不是糖尿病", ""),
    (P_DMZ, "糖尿病：否", ""),
    (P_DMZ, "媽媽有糖尿病", ""),
    (P_DMZ, "哥哥有糖尿病", ""),
    (P_DMZ, "姐姐有糖尿病", ""),
    (P_DMZ, "家人有糖尿病", ""),
    ("Known allergy to study drug", "No known drug allergies.", ""),
    ("Active tuberculosis requiring treatment", "No tuberculosis", ""),
    ("Active tuberculosis requiring treatment", "Mother has tuberculosis", ""),
    ("Asthma requiring inhaled steroids", "denies asthma", ""),
    (P_DM, "hx. of diabetes", "Mother: hx. of diabetes."),
    ("History of heart failure", "No heart failure, but renal failure.", ""),
    ("Active hepatitis B infection", "Hepatitis B negative, but recent urinary tract infection", ""),
    (P_HIV, "Mother has HIV.", ""),
    (P_MI, "Rule out myocardial infarction; troponin pending.", ""),
    (P_HCV, "Suspected hepatitis C, awaiting PCR.", ""),
    (P_HIVJ, "母親にHIV感染あり。", ""),
    (P_HIV, "母親にHIV感染あり。", ""),
    (P_HIV, "HIV status unknown", ""),
    (P_HIV, "HIV status: unknown.", ""),
    (P_HIV, "Partner is HIV positive.", ""),
    (P_HIV, "Boyfriend has HIV.", ""),
    (P_HIV, "HIV-ve", ""),
    (P_HIV, "HIV -", ""),
    (P_HIV, "HIV antibody non-reactive", ""),
    (P_HIV, "HIV nonreactive", ""),
    (P_HIV, "HIV test ordered", ""),
    (P_HIV, "On PrEP for HIV prevention", ""),
    (P_HIV, "HIV exposure in 2019", ""),
    (P_DM, "Non-diabetic", ""),
    (P_DM, "nondiabetic", ""),
    (P_DM, "No hx of DM", ""),
    (P_DM, "DDx: DM vs stress hyperglycaemia", ""),
    (P_DM, "DM cannot be excluded", ""),
    (P_DM, "?DM", ""),
    (P_DM, "Diabetes ?", ""),
    (P_DM, "Father's diabetes", ""),
    (P_DM, "DM in 1st-degree relative", ""),
    (P_HCV, "Hepatitis C, cured with DAA in 2018", ""),
    (P_HCV, "HCV Ab positive, RNA negative", ""),
    (P_HCV, "history of hepatitis C, treated, SVR", ""),
    (P_MI, "MI was excluded", ""),
    (P_MI, "possible MI", ""),
    (P_MI, "MI unlikely", ""),
    (P_HIV, "Grandmother has HIV.", ""),
    (P_HIV, "HIV in her son", ""),
    (P_HIV, "Patient's daughter has HIV.", ""),
    (P_HIV, "Mother has HIV", "Mother has HIV and hepatitis."),
    (P_HIV, "HIV", "Her aunt: HIV."),
    (P_HIV, "HIV", "HIV? will test."),
    (P_DMJ, "糖尿病境界型", ""),
    (P_DMJ, "糖尿病予備群", ""),
    (P_DMJ, "おばが糖尿病", ""),
    (P_DMJ, "糖尿病の既往なし", ""),
    (P_DMJ, "糖尿病（－）", ""),
    (P_DMJ, "糖尿病は否定的", ""),
    (P_DMJ, "糖尿病ではない", ""),
    (P_DMJ, "糖尿病でなかった", ""),
    (P_DMJ, "糖尿病を除外できない", ""),
    (P_DMJ, "糖尿病の診断には至らず", ""),
    (P_DMJ, "パートナーが糖尿病", ""),
    (P_HIVJ, "HIV（ー）", ""),
    (P_HIVJ, "HIV(―)", ""),
    (P_HIVJ, "HIV（−）", ""),
    (P_HIVJ, "HIV抗体陰性", ""),
    (P_HIVJ, "HIV検査予定", ""),
    (P_HIVJ, "HIV感染の既往はありません", ""),
    (P_DMZ, "外公有糖尿病", ""),
    (P_DMZ, "女兒有糖尿病", ""),
    (P_DMZ, "兒子有糖尿病", ""),
    (P_DMZ, "太太有糖尿病", ""),
    (P_DMZ, "疑似糖尿病", ""),
    (P_DMZ, "糖尿病待查", ""),
    (P_DMZ, "排除糖尿病", ""),
    (P_DMZ, "未患糖尿病", ""),
    (P_DMZ, "无糖尿病", ""),
    (P_DMZ, "否认糖尿病", ""),
    ("HIV感染", "HIV阴性", ""),
    ("HIV感染", "HIV陰性", ""),
]
PROBE_CONTROLS: list[tuple[str, str, str]] = [
    (P_HIV, "Patient has HIV.", ""),
    (P_MI, "History of myocardial infarction in 2019.", ""),
    (P_HCV, "Active hepatitis C infection on treatment.", ""),
    (P_HIV, "HIV感染症あり。", ""),
    (P_HIVJ, "HIV感染症あり。", ""),
    (P_DM, "Type 2 diabetes mellitus since 2015.", ""),
]
UNWRAP_CASES: list[tuple[str, str]] = [  # the probe's quote cases: (quote, text)
    ("「「HIV」」", "N"),
    ("「HIV」」", "N"),
    ("「「HIV」", "N"),
    ('"HIV”', "N"),
    ('“HIV"', "N"),
    ('「HIV"', "N"),
    ('"「HIV」"', "N"),
    ('「"HIV"」', "N"),
    ("＂HIV＂", "N"),
    ("｢HIV｣", "N"),
    ("『HIV』", "N"),
    ("「 HIV 」", "N"),
    ("「 母親 に HIV 感染 あり 。」", "N"),
    ("「胸が痛い」", "N"),
    ("「胸が痛い」と訴えた", "N"),
    ('"Patient has HIV."', "N"),
    ('"HIV" ', "N"),
    ("「」", "N"),
    ('""', "N"),
    ('"a"', "xyz"),
    ('"x"', "xyz"),
    ("「母」と「父」", "母と父"),
    ("「HIV」", "H I V"),
    ('"Mother has HIV.', "N"),
    ('Mother has HIV."', "N"),
    ("「Mother has HIV.」", "N"),
    ('"Mother has HIV"', "Mother has [HIV]"),
    ('"DM (-)"', "N"),
    ("「DM(-)」", "N"),
    ("「HIV感染」", "HIV\n[…]\n感染"),
]
UNWRAP_NOTE = '患者は「胸が痛い」と訴えた。Mother has HIV. 母親にHIV感染あり。Patient denies "HIV". DM ( - ).'
ALL_FORMS = list(dict.fromkeys(REVIEW_FORMS + PROBE_FORMS + ROUND5_FORMS))
ALL_CONTROLS = list(dict.fromkeys(REVIEW_CONTROLS + [(t, q) for t, q, _ in PROBE_CONTROLS] + ROUND5_CONTROLS))


def _form_criterion(text: str) -> CriterionIR:
    c = {**CRITERIA[1], "id": "D9-EXC-91", "ruleset": "D9", "text": text, "note_question": f"Do the notes say: {text}?"}
    return CriterionIR.model_validate(c)


def _builders(text: str, quote: str, sentence: str) -> tuple[str, str, str, bool]:
    """(the one rule's effect, the v1 verdict, the cascade outcome's status, the cascade outcome is hard) for a pair's
    "present" at 0.9 on ``quote``."""
    c = _form_criterion(text)
    sent = sentence or quote
    may = note_answer_may("exclusion", True, quote, text, sent, affirmed=True)
    v = note_verdict(
        c, NoteResult("pass", PAIR, quote, "2026-09-20", "note", dids=["d1"], sentence=sent, affirmed=True), pair=True
    )
    reply = JudgeReply(
        "pass", PAIR, quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True
    )
    o = _run_for_map(True)._map(c, reply, {**SPAN, "quote": quote, "sentence": sent}, "S3")
    return may.effect, v.verdict, o.status, o.hard


@pytest.mark.parametrize(("text", "quote", "sentence"), ALL_FORMS, ids=[f[1] for f in ALL_FORMS])
def test_a_form_that_does_not_state_the_condition_goes_to_review_on_every_builder(
    text: str, quote: str, sentence: str
) -> None:
    """Given "present" by both models, each form goes to review: the one rule, the v1 verdict, the cascade's outcome,
    and (where the quote alone shows it) a stored row through the status rule."""
    assert _builders(text, quote, sentence) == ("review", "unknown", "unknown", False)
    if not sentence or (sentence.startswith(quote) and inferred(quote, text)):  # a stored row keeps only the quote
        stored = CriterionVerdict(id="D9-EXC-91", verdict="fail", basis="pair", final=True, prov=["c-judge", "c-verifier"], affirmed=True,
                                  evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=quote,
                                                    confidence=PAIR, reason="note"))  # fmt: skip
        assert decision.answer_of(_form_criterion(text), stored, POLICY) == "unknown"


@pytest.mark.parametrize(("text", "quote"), ALL_CONTROLS, ids=[f[1] for f in ALL_CONTROLS])
def test_the_same_criteria_on_a_stated_quote_still_exclude(text: str, quote: str) -> None:
    assert _builders(text, quote, "") == ("excludes", "fail", "fail", True)


# ------------------------------------------------------------------------------------------------ round 4 (#639 7107834329)
@pytest.mark.parametrize("kind", ["renewal", "documentation"])
def test_a_renewal_or_documentation_not_met_from_the_notes_is_review_on_every_builder(kind: str) -> None:
    """L2: such a criterion reads as an inclusion (``matching.verdict.kind_class``). A decided "not met" from the notes
    goes to review: the reading stands (the row says "not met"), the status rule says ``unknown``, and the cascade's
    outcome is a soft fail; "met" keeps the patient."""
    c = BY_ID[HIV].model_copy(update={"kind": kind})
    may = note_answer_may(kind, False, HAS_HIV, c.text, HAS_HIV)
    assert (may.effect, may.reason, may.reading_stands) == ("review", OTHER_KIND_REASON, True)
    assert note_answer_may(kind, True, HAS_HIV, c.text, HAS_HIV).effect == "keeps"
    r = NoteResult("fail", PAIR, HAS_HIV, "2026-09-20", "note", dids=["d1"], sentence=HAS_HIV, affirmed=True)
    v = note_verdict(c, r, pair=True)
    assert (v.verdict, v.basis) == ("fail", "pair") and decision.answer_of(c, v, POLICY) == "unknown"
    reply = JudgeReply(
        "fail", PAIR, HAS_HIV, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True
    )
    o = _run_for_map(True)._map(c, reply, {**SPAN, "quote": HAS_HIV, "sentence": HAS_HIV}, "S3")
    assert (o.status, o.hard, o.reason) == ("fail", False, OTHER_KIND_REASON)


def test_a_note_exclusion_with_no_quote_never_excludes() -> None:
    """L1: what is not shown never excludes. A stored pair's final, sure "present" with no quote is review."""
    v = _stored(CONTROLS[0]).model_copy(update={"evidence": Evidence(resource_refs=["DocumentReference/d1"],
                                                                     confidence=PAIR, reason="note")})  # fmt: skip
    assert decision.answer_of(BY_ID[HIV], v, POLICY) == "unknown"
    assert decision.status_of(BY_ID, [AGE_MET, v], POLICY).tier == "review"
    # a criterion that is a value has no condition word for the guard to look for: still review with no quote
    alt = BY_ID[HIV].model_copy(update={"text": "ALT > 3x ULN"})
    assert decision.answer_of(alt, v, POLICY) == "unknown"


TWO_QUOTES = "Patient has HIV. Grandmother has HIV."


@pytest.mark.parametrize(("verifier_quote", "want"), [(GRANDMOTHER, "unknown"), (HAS_HIV, "fail")])
def test_the_v1_pair_reads_the_verifiers_quote_too(verifier_quote: str, want: str) -> None:
    """L3 on v1: the judge quotes a sentence that states HIV, the verifier a relative's. The pair agrees on
    "present", and the answer rests on both quotes, so it is review; when both state it, it excludes."""
    nj = NoteJudge(lake=None, llm=ScriptedModel("judge-a", says("pass", HAS_HIV)),  # type: ignore[arg-type]
                   verifier=ScriptedModel("verifier-b", says("pass", verifier_quote)))  # type: ignore[arg-type]  # fmt: skip
    r = nj.judge_excerpts(BY_ID[HIV].text, "Do the notes document known HIV infection?", RUN,
                          [{"did": "d1", "date": "2026-09-20", "text": TWO_QUOTES}])  # fmt: skip
    assert r.predicate == "pass" and r.quote == HAS_HIV
    assert note_verdict(BY_ID[HIV], r, pair=True).verdict == want
    assert verifier_quote not in note_verdict(BY_ID[HIV], r, pair=True).model_dump_json() or want == "fail"


class _Says:
    """A cascade ``JudgeClient`` that answers "present" quoting ``quote``."""

    def __init__(self, quote: str, prompt: str = "judge@test") -> None:
        self.quote, self.prompt = quote, prompt

    def judge(self, **kw: Any) -> JudgeReply:
        return JudgeReply("pass", PAIR, self.quote, "2026-09-20", "scripted", call_id=f"c-{self.quote[:4]}",
                          prompt=self.prompt, affirmed=True)  # fmt: skip


@pytest.mark.parametrize(("verifier_quote", "want"), [(GRANDMOTHER, ("unknown", False)), (HAS_HIV, ("fail", True))])
def test_the_cascade_pair_reads_the_verifiers_quote_too(verifier_quote: str, want: tuple[str, bool]) -> None:
    """L3 on the cascade: the pair's reply carries the verifier's sentence (``JudgeReply.sentence``, never
    published), which the one rule reads beside the judge's span."""
    ex = [{"did": "d1", "date": "2026-09-20", "text": TWO_QUOTES}]
    pair = AgreementJudge(_Says(HAS_HIV), _Says(verifier_quote))
    reply = pair.judge(role="judge", criterion_text=BY_ID[HIV].text, note_question="Q?", index_date=RUN, excerpts=ex,
                       study_id="D9", data_class="D3", step_id="t", purpose="screening")  # fmt: skip
    assert reply.verdict == "pass" and reply.quote == HAS_HIV and reply.sentence == verifier_quote
    span = verify_span(reply, ex, date(2026, 1, 1), date(2026, 12, 31))
    o = _run_for_map(True)._map(BY_ID[HIV], reply, span, "S3")
    assert (o.status, o.hard) == want
    assert verifier_quote not in json.dumps(o.evidence) or want[1]


# ------------------------------------------------------------------------------------ lane J's reproduction
# Lane J reproduced R22-16 on master with the two models faked as a real pair (#1327 7094287787): its four inputs were
# excluded on v1. They are this file's first four inputs; here they run as lane J ran them: a judge and a verifier
# that are two different models (each its own ``served_root``), v1 through ``NoteJudge`` -> ``note_verdict`` ->
# ``tier``/``status_of``, the cascade through ``OrchestratorJudge`` -> ``verify_span`` -> ``_map`` (#639 7113069462).
# Each input also runs with its quote wrapped in 「」 or "" as a model may write it, which lane J found matched no note
# (``quote_not_found``); one enclosing pair of marks is now dropped before the quote is matched. A stated quote, bare
# and wrapped, still excludes on both paths.
J_IDX = date(2026, 2, 1)
J_HIV, J_MI, J_HCV = "Known HIV infection", "History of myocardial infarction", "Active hepatitis C"
J_HIV_JA = "HIV感染が既知の患者"
J_RECORD_JA = "母親にHIV感染あり。患者本人のHIV検査は陰性。"
J_INPUTS = [  # (criterion, record, quote): the quote verbatim in the record
    (J_HIV, FAMILY, FAMILY),
    (J_MI, RULE_OUT, RULE_OUT),
    (J_HCV, SUSPECTED, SUSPECTED),
    (J_HIV_JA, J_RECORD_JA, FAMILY_JA),
    (J_HIV, J_RECORD_JA, FAMILY_JA),
]
J_STATED = [
    (J_HIV, "Patient has HIV. On ART since 2019.", HAS_HIV),
    (J_HIV_JA, "HIV感染症あり。抗HIV療法中。", HAS_HIV_JA),
]


def _wrapped(quote: str) -> str:
    return f"「{quote}」" if any(ord(ch) > 0x3000 for ch in quote) else f'"{quote}"'


class _PairModel:
    """One of two different models answering every judge call "present" at 0.9 with ``quote``."""

    made = 0

    def __init__(self, quote: str) -> None:
        _PairModel.made += 1
        self.model = self.served_root = f"pair-{_PairModel.made}"  # its own weights (D-276): a real pair
        self.quote = quote

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> Any:
        from tb_common.llm import LlmResult

        d = {"verdict": "pass", "reason": "r", "confidence": 0.9, "quote": self.quote, "quote_date": None,
             "certainty": "affirmed", "experiencer": "patient", "time": "current"}  # judge v6, both affirm  # fmt: skip
        return LlmResult(d, prompt_id, 4, self.model, "local", "i" * 64, "o" * 64, 100, 20, 1)


def _j_criterion(text: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": "J-EXC-01", "ruleset": "J", "text": text, "kind": "exclusion", "class": "note",
         "note_question": f"Do the notes document: {text}?", "logic": {"domain": "condition", "valueset": "VS_X"}}
    )  # fmt: skip


def _j_paths(criterion: str, record: str, quote: str) -> tuple[str, str, Any, Any]:
    """The v1 tier, the v1 status and the published v1 verdict, and the cascade's outcome, on a real pair."""
    from orchestrator.scenarios.evaluate import is_pair, tier
    from orchestrator.scenarios.screen_cascade import OrchestratorJudge

    from tests.unit.test_safety_properties import _run_for_map

    c = _j_criterion(criterion)
    excerpts = [{"date": "2026-01-10", "note_type": "progress", "text": record, "did": "D1"}]
    nj = NoteJudge(lake=None, llm=_PairModel(quote), verifier=_PairModel(quote))  # type: ignore[arg-type]
    assert is_pair(nj)
    v = note_verdict(c, nj.judge_excerpts(c.text, c.note_question or c.text, J_IDX, excerpts), pair=is_pair(nj))
    rs = cast(Ruleset, type("RS", (), {"by_id": staticmethod(lambda: {c.id: c})}))
    v1_tier = tier(rs, [v], 0.75, note_block=True)[0]
    status = decision.status_of({c.id: c}, [v], decision.Policy(0.75, True)).tier
    oj = OrchestratorJudge(None, _PairModel(quote), verifier=_PairModel(quote))  # type: ignore[arg-type]
    reply = oj.judge(role="judge", criterion_text=c.text, note_question=c.note_question or c.text, index_date=J_IDX,
                     excerpts=excerpts, study_id="J", data_class="D0", step_id="s", purpose="screen")  # fmt: skip
    span = verify_span(reply, excerpts, date(2025, 1, 1), J_IDX)
    assert span is not None, "the quote must verify against the record"
    return v1_tier, status, v, _run_for_map(True)._map(c, reply, span, "S3")


@pytest.mark.parametrize("wrap", [False, True], ids=["bare", "wrapped"])
@pytest.mark.parametrize(
    ("criterion", "record", "quote"), J_INPUTS, ids=["mother", "rule_out", "suspected", "ja", "ja_en"]
)
def test_no_path_excludes_on_a_negated_family_history_rule_out_or_suspected_quote(
    criterion: str, record: str, quote: str, wrap: bool
) -> None:
    """Lane J's four inputs (the Japanese line under the Japanese and the English criterion): review on every path."""
    v1_tier, status, v, o = _j_paths(criterion, record, _wrapped(quote) if wrap else quote)
    assert (v1_tier, status) == ("review", "review"), (v1_tier, status)
    assert v.verdict == "unknown" and v.evidence is not None and v.evidence.quote == quote  # read as the note holds it
    assert v.evidence.reason == code_of(INFERRED_REASON, "unknown")
    assert o.status == "unknown" and not o.hard and o.reason == INFERRED_REASON


@pytest.mark.parametrize("wrap", [False, True], ids=["bare", "wrapped"])
@pytest.mark.parametrize(("criterion", "record", "quote"), J_STATED, ids=["en", "ja"])
def test_lane_js_control_a_stated_quote_still_excludes_bare_or_in_marks(
    criterion: str, record: str, quote: str, wrap: bool
) -> None:
    """Red before the marks were dropped (wrapped): the quote matched no note, so nothing could ever exclude on it."""
    v1_tier, status, v, o = _j_paths(criterion, record, _wrapped(quote) if wrap else quote)
    assert (v1_tier, status) == ("excluded", "excluded"), (v1_tier, status)
    assert v.verdict == "fail" and v.evidence is not None and v.evidence.quote == quote
    assert o.status == "fail" and o.hard


@pytest.mark.parametrize(
    ("quote", "bare"),
    [
        ("「母親にHIV感染あり。」", "母親にHIV感染あり。"),
        ('"Mother has HIV."', "Mother has HIV."),
        ("“Mother has HIV.”", "Mother has HIV."),
        (" 「HIV感染症あり。」 ", "HIV感染症あり。"),
        ("「母」と「父」", "「母」と「父」"),  # not one quote in marks
        ('"a" and "b"', '"a" and "b"'),
        ("「unclosed", "「unclosed"),
        ("「」", "「」"),
        ("Mother has HIV.", "Mother has HIV."),
    ],
)
def test_one_enclosing_pair_of_marks_is_dropped_and_nothing_else(quote: str, bare: str) -> None:
    from tb_common.quotes import as_in, unwrap

    assert unwrap(quote) == bare
    note = "「母」と「父」 a note. Mother has HIV. HIV感染症あり。"
    assert as_in(quote, note) == (bare if bare in note else None)


def test_a_note_that_holds_the_marks_itself_is_matched_as_written() -> None:
    from tb_common.quotes import as_in

    note = "患者は「胸が痛い」と訴えた。"
    assert as_in("「胸が痛い」", note) == "「胸が痛い」"  # the marks are the note's: kept
    assert sentence_of("「母親にHIV感染あり。」", J_RECORD_JA) == "母親にHIV感染あり。"


class _Answers:
    """A cascade ``JudgeClient`` that answers "present" quoting ``quote`` (which may be None)."""

    def __init__(self, quote: str | None) -> None:
        self.quote = quote

    def judge(self, **kw: Any) -> JudgeReply:
        return JudgeReply(
            "pass", PAIR, self.quote, "2026-09-20", "scripted", call_id="c-x", prompt="judge@test", affirmed=True
        )


#: M1: (the verifier's quote, the pair's verdict). The judge's own quote states HIV and is in the record.
VERIFIER_QUOTES = [
    (None, "unknown"),  # no quote: nothing shown
    ("Patient has HIV and is on ART.", "unknown"),  # not in the record
    ("「Patient has HIV.」", "pass"),  # in the record, in marks
    (HAS_HIV, "pass"),
]


@pytest.mark.parametrize(("verifier_quote", "want"), VERIFIER_QUOTES)
def test_the_cascade_checks_the_verifiers_quote_against_the_record_as_v1_does(
    verifier_quote: str | None, want: str
) -> None:
    """Round 5, M1 (#639 7115208555): on the cascade's ``AgreementJudge`` a decided verifier answer whose quote is not
    in the record (or is missing) is the verifier's "unknown", so the pair disagrees and the patient goes to review,
    as on v1, where ``postprocess`` gives that answer ``unknown``. Both paths agree on every row."""
    ex = [{"did": "d1", "date": "2026-09-20", "text": HAS_HIV + " On ART since 2019."}]
    pair = AgreementJudge(_Answers(HAS_HIV), _Answers(verifier_quote))
    reply = pair.judge(role="judge", criterion_text=BY_ID[HIV].text, note_question="Q?", index_date=RUN, excerpts=ex,
                       study_id="D9", data_class="D3", step_id="t", purpose="screening")  # fmt: skip
    assert reply.verdict == want
    assert pair.disagreements == (want == "unknown")
    o = _run_for_map(True)._map(BY_ID[HIV], reply, verify_span(reply, ex, date(2026, 1, 1), date(2026, 12, 31)), "S3")
    assert (o.status, o.hard) == (("fail", True) if want == "pass" else ("unknown", False))
    # v1 on the same pair
    nj = NoteJudge(lake=None, llm=ScriptedModel("judge-a", says("pass", HAS_HIV)),  # type: ignore[arg-type]
                   verifier=ScriptedModel("verifier-b", says("pass", verifier_quote)))  # type: ignore[arg-type]  # fmt: skip
    r = nj.judge_excerpts(BY_ID[HIV].text, "Do the notes document known HIV infection?", RUN, ex)
    assert note_verdict(BY_ID[HIV], r, pair=True).verdict == ("fail" if want == "pass" else "unknown")


def test_the_cascade_reads_the_judges_sentence_beside_the_verifiers() -> None:
    """Round 5, the re-review's surviving mutant at ``engine._map``: the judge's span sentence is a relative's, the
    verifier's sentence states HIV. The rule reads both, so the patient goes to review; reading only the verifier's
    would exclude."""
    reply = replace(JudgeReply("pass", PAIR, FRAGMENT, "2026-09-20", "both agree", call_id="c1", prompt="judge@test", affirmed=True),
                    sentence=HAS_HIV)  # fmt: skip
    o = _run_for_map(True)._map(BY_ID[HIV], reply, {**SPAN, "quote": FRAGMENT, "sentence": FRAGMENT_SENTENCE}, "S3")
    assert (o.status, o.hard, o.reason) == ("unknown", False, INFERRED_REASON)
    both_stated = replace(reply, quote=HAS_HIV)
    o = _run_for_map(True)._map(BY_ID[HIV], both_stated, {**SPAN, "quote": HAS_HIV, "sentence": HAS_HIV}, "S3")
    assert (o.status, o.hard) == ("fail", True)  # the control: both state it


@pytest.mark.parametrize(("quote", "text"), UNWRAP_CASES)
def test_a_quote_matched_without_its_marks_is_always_in_the_text(quote: str, text: str) -> None:
    """The re-review's 30 quote cases: ``as_in`` never yields a quote that is not in the text (nested, unbalanced,
    mixed, full-width marks; a quote across a cut)."""
    from tb_common.quotes import as_in, quote_in

    t = UNWRAP_NOTE if text == "N" else text
    got = as_in(quote, t)
    assert got is None or quote_in(got, t)


# ------------------------------------------------------------------------------------------------ round 5: affirmed
# Point 1 of the ruling (#639 7115208555, 7115258794): the guard is inverted. A note exclusion stands only when both
# models say the quote affirms the condition, in this patient, now: judge v6's ``certainty``, ``experiencer`` and
# ``time`` (schema ``llm_judge_output_v2``, 1.2.0). Any other value, or a missing or null field, is review; so an
# answer of a judge before v6, which gives none, never excludes. The deterministic guard stays as the second net.
NOT_AFFIRMED = [
    ("negated", "patient", "current"),
    ("possible", "patient", "current"),
    ("unknown", "patient", "current"),
    ("affirmed", "other", "current"),
    ("affirmed", "patient", "past_resolved"),
    ("affirmed", "patient", "planned"),
    (None, "patient", "current"),
    ("affirmed", None, "current"),
    ("affirmed", "patient", None),
]


def _fields(t: tuple[str | None, ...]) -> dict[str, str | None]:
    return dict(zip(("certainty", "experiencer", "time"), t, strict=True))


def test_only_affirmed_patient_current_affirms() -> None:
    from matching.note_answer import affirms

    assert affirms(_fields(("affirmed", "patient", "current")))
    assert not any(affirms(_fields(t)) for t in NOT_AFFIRMED)
    assert not affirms({"verdict": "pass", "quote": HAS_HIV})  # a judge before v6: nothing said


def test_a_stated_exclusion_excludes_only_when_both_models_affirmed_it() -> None:
    from matching.note_answer import NOT_AFFIRMED_REASON

    assert note_answer_may("exclusion", True, HAS_HIV, BY_ID[HIV].text, HAS_HIV, affirmed=True).effect == "excludes"
    for affirmed in (None, False):
        may = note_answer_may("exclusion", True, HAS_HIV, BY_ID[HIV].text, HAS_HIV, affirmed=affirmed)
        assert (may.effect, may.reason) == ("review", NOT_AFFIRMED_REASON)
    # the second net: the guard's review stands whatever the models said
    may = note_answer_may("exclusion", True, GRANDMOTHER, BY_ID[HIV].text, GRANDMOTHER, affirmed=True)
    assert (may.effect, may.reason) == ("review", INFERRED_REASON)
    # an answer that keeps the patient needs no affirmation
    assert note_answer_may("exclusion", False, ABSENT[HIV], BY_ID[HIV].text, affirmed=None).effect == "keeps"


@pytest.mark.parametrize("other", NOT_AFFIRMED, ids=[str(t) for t in NOT_AFFIRMED])
def test_a_v1_pair_excludes_only_when_both_models_affirm(other: tuple[str | None, ...]) -> None:
    """v1: the judge affirms; the verifier agrees on "present" with the same stated quote but reads it otherwise (or
    says nothing of it). Review; when both affirm, the patient is excluded."""
    ex = [{"did": "d1", "date": "2026-09-20", "text": HAS_HIV + " On ART since 2019."}]

    def answer(fields: tuple[str | None, ...]) -> Any:
        return lambda v: {**says("pass", HAS_HIV)(v), **_fields(fields)}

    for second, want in ((other, "unknown"), (("affirmed", "patient", "current"), "fail")):
        nj = NoteJudge(lake=None, llm=ScriptedModel("judge-a", answer(("affirmed", "patient", "current"))),  # type: ignore[arg-type]
                       verifier=ScriptedModel("verifier-b", answer(second)))  # type: ignore[arg-type]  # fmt: skip
        r = nj.judge_excerpts(BY_ID[HIV].text, "Do the notes document known HIV infection?", RUN, ex)
        v = note_verdict(BY_ID[HIV], r, pair=True)
        assert v.verdict == want
        assert v.affirmed is (True if want == "fail" else None)
        assert decision.answer_of(BY_ID[HIV], v, POLICY) == ("no" if want == "fail" else "unknown")


@pytest.mark.parametrize("other", NOT_AFFIRMED, ids=[str(t) for t in NOT_AFFIRMED])
def test_a_cascade_pair_excludes_only_when_both_models_affirm(other: tuple[str | None, ...]) -> None:
    """The cascade: the gateway judge parses each model's fields, ``AgreementJudge`` needs both, ``_map`` reads it,
    and the stored verdict says it (``verdict_of``)."""
    from orchestrator.scenarios.screen_cascade import verdict_of

    ex = [{"did": "d1", "date": "2026-09-20", "text": HAS_HIV + " On ART since 2019."}]

    class _Model:
        def __init__(self, fields: tuple[str | None, ...]) -> None:
            self.fields = fields

        def judge(self, **kw: Any) -> JudgeReply:
            return JudgeReply("pass", PAIR, HAS_HIV, "2026-09-20", "scripted", call_id="c-x", prompt="judge@test",
                              affirmed=_fields(self.fields) == _fields(("affirmed", "patient", "current")))  # fmt: skip

    for second, want in ((other, ("unknown", False)), (("affirmed", "patient", "current"), ("fail", True))):
        pair = AgreementJudge(_Model(("affirmed", "patient", "current")), _Model(second))
        reply = pair.judge(role="judge", criterion_text=BY_ID[HIV].text, note_question="Q?", index_date=RUN,
                           excerpts=ex, study_id="D9", data_class="D3", step_id="t", purpose="screening")  # fmt: skip
        o = _run_for_map(True)._map(BY_ID[HIV], reply, verify_span(reply, ex, date(2026, 1, 1), date(2026, 12, 31)),
                                    "S3")  # fmt: skip
        assert (o.status, o.hard) == want
        v = verdict_of(o, pair=True)
        assert v.affirmed is (True if want[1] else None)
        assert decision.answer_of(BY_ID[HIV], v, POLICY) == ("no" if want[1] else "unknown")


def test_the_gateway_judge_reads_the_three_fields() -> None:
    """The cascade's parse of one model's answer: affirmed only on the three values, never on a v5 answer."""
    from matching.note_answer import affirms

    base = {"verdict": "pass", "reason": "r", "quote": HAS_HIV, "quote_date": None, "confidence": 0.9}
    assert affirms({**base, **_fields(("affirmed", "patient", "current"))})
    assert not affirms(base)


def test_a_stored_row_that_does_not_say_affirmed_never_excludes() -> None:
    """The status rule over a stored row: a pair's final, sure "present" on a stated quote excludes only when the row
    says both models affirmed it; a row stored before the field (or by a judge before v6) is review."""
    v = _stored(CONTROLS[0])
    assert decision.answer_of(BY_ID[HIV], v.model_copy(update={"affirmed": True}), POLICY) == "no"
    for flag in (None, False):
        assert decision.answer_of(BY_ID[HIV], v.model_copy(update={"affirmed": flag}), POLICY) == "unknown"


def test_the_stub_answers_the_three_fields_only_when_the_schema_asks() -> None:
    from llm_stub.handlers import assertion_fields
    from tb_contracts import inline_schema

    answer = {"verdict": "pass", "quote": HAS_HIV, "quote_date": None, "confidence": 0.9, "reason": "r"}
    v2 = {"response_format": {"json_schema": {"schema": inline_schema("llm_judge_output_v2")}}}
    v1 = {"response_format": {"json_schema": {"schema": inline_schema("llm_judge_output")}}}
    assert assertion_fields(v1, answer) == answer  # 1.1.0 forbids other keys
    got = assertion_fields(v2, answer)
    assert (got["certainty"], got["experiencer"], got["time"]) == ("affirmed", "patient", "current")
    none = assertion_fields(v2, {**answer, "verdict": "unknown", "quote": None})
    assert (none["certainty"], none["experiencer"], none["time"]) == (None, None, None)


def test_judge_v6_asks_for_the_three_fields_and_is_not_qualified() -> None:
    """Judge v6 is registered on schema 1.2.0 with no qualification: PRODUCTION serves the newest qualified judge,
    whose answers say nothing of the three fields, so no note exclusion stands there until v6 qualifies."""
    from tb_llm.prompt_registry import default_registry

    reg = default_registry()
    v6 = next(e for e in reg.entries() if e.id == "judge" and e.version == 6)
    assert v6.schema == "llm_judge_output_v2" and v6.qualification is None
    v5 = next(e for e in reg.entries() if e.id == "judge" and e.version == 5)
    assert v5.schema == "llm_judge_output"  # the 1.1.0 schema stays for judge 3 to 5 and their pins
    text = (ROOT / "libs" / "tb_llm" / "prompts" / "judge_v6.md").read_text(encoding="utf-8")
    assert all(f"`{k}`" in text for k in ("certainty", "experiencer", "time"))
