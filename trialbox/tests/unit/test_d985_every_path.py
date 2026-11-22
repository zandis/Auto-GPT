"""D-985 on every path (R22-16): a note exclusion answered "condition present" stands only on a quote that STATES the
condition. A relative's, a rule-out or a suspected condition is the models' inference: the patient goes to review,
never off a list, whichever path screened them.

The rule is :func:`tb_common.pair.inferred_exclusion` (on :func:`matching.inferred.inferred`). Before R22-16 only
the cascade asked it (``engine._map``); the v1 evaluator, which MICROBATCH, NAV, CASE and SCREEN on v1 run, did not.
Three places read it now, and each is checked where only it can be seen:

* the cascade's ``_map`` (its outcome: SCREEN on the cascade, MICROBATCH's screen of new patients);
* the v1 ``note_verdict`` (the published verdict is ``unknown``, not a ``fail`` the status rule later holds back:
  SCREEN on v1, NAV, CASE, MICROBATCH on v1);
* the status rule's backstop, :func:`matching.decision.answer_of`, over a row stored before the fix (the pool row a
  MICROBATCH re-check re-tiers).

The five inputs: both models of the pair agree, confidence 0.9, the quote verbatim in the record. A control per
criterion (a quote that states the condition) still excludes on every path, so no check passes by never excluding.

One small lake and every path that decides a patient's status, driven in process on one box (``tests/inproc_box.py``)
with a scripted pair that reads the text it is shown (``tests/judge_kit.py``), as ``test_path_independence.py`` does.
Synthetic data only.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import pickle
import shutil
from dataclasses import dataclass, field
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
from matching.cascade.judge import JudgeReply
from orchestrator.scenarios.evaluate import NoteResult, note_verdict
from tb_common.crypto import pid_for_mrn
from tb_common.pair import INFERRED_REASON, inferred_exclusion
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
#: the reason code a published verdict carries for an inferred exclusion (the cascade's, ``verdict_of``)
INFERRED_CODE = code_of(INFERRED_REASON, "unknown", True)

# ------------------------------------------------------------------------------------------------ the criteria
HIV, MI, HCV, HIVJ = "D9-EXC-01", "D9-EXC-02", "D9-EXC-03", "D9-EXC-04"
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
# what a note says when the condition is absent (a reader needs a sentence to answer "not present")
ABSENT = {
    HIV: "No HIV infection.",
    MI: "No myocardial infarction.",
    HCV: "No hepatitis C.",
    HIVJ: "HIV感染症の既往なし。",
}
# The box's cascade finds a note by the shipped terms table (S2) and, with no embed service, by nothing else: a
# criterion none of whose words the table knows reads "not evaluated". The note questions name a word it knows
# ("heart attack", "infection") and every note holds one, so the cascade judges every criterion on every note
FILLER = "Routine follow-up after a gout attack; no new infection; vitals stable."

PAIR = 0.9  # both models agree at this confidence
ORACLE = {  # the oracle's key is a substring of the criterion's text (the first sentence shown decides)
    "known hiv": [Decisive(FAMILY, confidence=PAIR), Decisive(HAS_HIV, confidence=PAIR),
                  Decisive(FAMILY_JA, confidence=PAIR), Decisive(HAS_HIV_JA, confidence=PAIR),
                  Decisive(ABSENT[HIV], "fail")],
    "myocardial": [Decisive(RULE_OUT, confidence=PAIR), Decisive(HAD_MI, confidence=PAIR), Decisive(ABSENT[MI], "fail")],
    "hepatitis c": [Decisive(SUSPECTED, confidence=PAIR), Decisive(HAS_HCV, confidence=PAIR),
                    Decisive(ABSENT[HCV], "fail")],
    "hiv感染症の既往": [Decisive(FAMILY_JA, confidence=PAIR), Decisive(HAS_HIV_JA, confidence=PAIR),
                   Decisive(ABSENT[HIVJ], "fail")],
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
    "HIV_STATED": {"number": "20000011", "note": _note(HAS_HIV, (HIV,))},
    "MI_STATED": {"number": "20000012", "note": _note(HAD_MI, (MI,))},
    "HCV_STATED": {"number": "20000013", "note": _note(HAS_HCV, (HCV,))},
    "HIV_STATED_JA": {"number": "20000014", "note": _note(HAS_HIV_JA, (HIV, HIVJ))},
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
]
CONTROLS = [
    Input("stated-en-hiv", HIV, "HIV_STATED", HAS_HIV),
    Input("stated-en-mi", MI, "MI_STATED", HAD_MI),
    Input("stated-en-hcv", HCV, "HCV_STATED", HAS_HCV),
    Input("stated-ja-quote", HIV, "HIV_STATED_JA", HAS_HIV_JA),
    Input("stated-ja", HIVJ, "HIV_STATED_JA", HAS_HIV_JA),
]


def test_the_inputs_are_inferences_and_the_controls_are_not() -> None:
    """The premise: the shared rule calls every input an inference and no control one."""
    for i in INPUTS:
        assert inferred_exclusion("exclusion", True, i.quote, BY_ID[i.cid].text), i.name
        assert i.quote in PATIENTS[i.patient]["note"]
    for i in CONTROLS:
        assert not inferred_exclusion("exclusion", True, i.quote, BY_ID[i.cid].text), i.name


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
    mp.setenv("TB_DB_URL", f"{pg_cluster_url}{sep}tb_prefix=d985{os.getpid()}_")
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


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    """Every path run once on one box, shared by the run's xdist workers (the first builds it under a lock)."""
    if worker_id == "master":
        return build_world(tmp_path_factory.mktemp("d985"), pg_cluster_url)
    root = tmp_path_factory.getbasetemp().parent / "d985-every-path"
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
    )


AGE_MET = CriterionVerdict(id="D9-INC-01", verdict="pass", evidence=Evidence(resource_refs=[], reason="coded"),
                           basis="coded", prov=[])  # fmt: skip


@pytest.mark.parametrize("case", [pytest.param(i, id=f"pool.stored_row-{i.name}") for i in INPUTS])
def test_a_stored_row_on_an_inferred_quote_is_reviewed_by_the_status_rule(case: Input) -> None:
    """The backstop (``decision.answer_of``): the pool row a MICROBATCH re-check re-tiers, stored before the fix."""
    v = _stored(case)
    assert decision.answer_of(BY_ID[case.cid], v, POLICY) == "unknown"
    assert decision.status_of(BY_ID, [AGE_MET, v], POLICY).tier == "review"


@pytest.mark.parametrize("case", [pytest.param(i, id=f"pool.stored_row-{i.name}") for i in CONTROLS])
def test_a_stored_row_on_a_stated_quote_still_excludes(case: Input) -> None:
    v = _stored(case)
    assert decision.answer_of(BY_ID[case.cid], v, POLICY) == "no"
    assert decision.status_of(BY_ID, [AGE_MET, v], POLICY).tier == "excluded"


def _note_result(i: Input) -> NoteResult:
    return NoteResult("pass", PAIR, i.quote, "2026-09-20", "note", dids=["d1"], calls=["c-judge", "c-verifier"])


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
    return _run_for_map(True)._map(BY_ID[i.cid], reply, {**SPAN, "quote": i.quote}, "S3")


@pytest.mark.parametrize("case", [pytest.param(i, id=f"cascade.map-{i.name}") for i in INPUTS])
def test_the_cascade_outcome_of_an_inferred_quote_is_unknown(case: Input) -> None:
    o = _cascade(case)
    assert (o.status, o.hard, o.reason) == ("unknown", False, INFERRED_REASON)


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
