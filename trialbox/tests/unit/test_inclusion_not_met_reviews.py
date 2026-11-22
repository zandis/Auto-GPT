"""R22-17, the owner's ruling of 2026-11-22: a note answer never removes a patient silently. An INCLUSION answered
"not met" from the notes sends the patient to review on every path, whatever the policy, the basis or the quote.

The fault: inclusion "Diagnosis of type 2 diabetes", note "Patient denies chest pain. Vitals stable.", both models
answer "not met" quoting "Patient denies chest pain." (confidence 0.9, the quote verbatim): the patient was EXCLUDED
on the cascade and on v1.

"From the notes" is :func:`matching.decision.is_note_answer` (every verdict of a ``note`` criterion, and a ``mixed``
one the coded data did not settle); on the cascade, the outcome of a note stage (``engine._map``). Two places read
the rule, and each is checked where only it can be seen:

* the status rule, :func:`matching.decision.answer_of` (its answer is ``unknown``; the row stays ``fail``, so a
  person reads "not met, from the notes"): SCREEN on v1, MICROBATCH, NAV's 確認 rows, a stored pool row, and the
  published tier of the cascade;
* the cascade's ``_map`` (a soft fail, never a hard one): the cascade goes on to the patient's other criteria and its
  own tier is review, not excluded.

The four inputs: an off-topic quote and an on-topic one, in English and in Japanese. Two controls on each path: a
coded inclusion that fails (age) still excludes, and an exclusion whose quote states the condition still excludes,
so no check passes by never excluding.

The world is ``test_d985_every_path.py``'s: one small lake and every path that decides a patient's status, driven in
process on one box with a scripted pair that reads the text it is shown. Synthetic data only.
"""

from __future__ import annotations

import base64
import fcntl
import itertools
import json
import os
import pickle
import shutil
from dataclasses import dataclass
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
from orchestrator.scenarios import nav
from orchestrator.scenarios.evaluate import NoteResult, PatientVerdicts, note_verdict
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, CriterionVerdict, Evidence

from tests.inproc_box import make_box
from tests.judge_kit import Decisive, QuotingOracle, quoting_pair
from tests.unit.test_d985_every_path import SCR, Seen, _doc, _outputs, _res, _rows, run_job
from tests.unit.test_safety_properties import SPAN, _run_for_map

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)
SNAP = "2026-10-04"
TZ = "Asia/Taipei"
PRACT, PRACT2, DEPT = "P12345", "P23456", "RHEU"  # doctors of deploy/settings.example.yaml
POLICY = decision.Policy(0.75, True)  # the world's policy: the default threshold, a pair that may exclude
POLICIES = [decision.Policy(0.75, True), decision.Policy(0.75, False), decision.Policy(0.95, True)]

# ------------------------------------------------------------------------------------------------ the criteria
AGE, INC, INCJ, HIV = "R7-INC-01", "R7-INC-02", "R7-INC-03", "R7-EXC-01"
NOTE_LOGIC = {"domain": "condition", "valueset": "VS_NOTE", "window": {"anchor": "index", "from_days": -365,
                                                                       "to_days": 0}}  # fmt: skip


def _ir(cid: str, kind: str, class_: str, text: str, logic: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": cid, "kind": kind, "class": class_, "text": text, "label": text[:30], "logic": logic,
            "review": {"status": "approved", "by": "crc1@hospa.test", "at": "2026-10-01T09:00:00+08:00"}, **extra}  # fmt: skip


# The box's cascade finds a note by the shipped terms table (S2): a criterion none of whose words the table knows
# reads "not evaluated". The note questions name words it knows ("pain", "infection") and every note holds one, so
# the cascade judges every criterion on every note, as the v1 evaluator does
CRITERIA: list[dict[str, Any]] = [
    _ir(AGE, "inclusion", "structured", "Age 18 or older",
        {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
    _ir(INC, "inclusion", "note", "Diagnosis of type 2 diabetes", NOTE_LOGIC,
        note_question="Do the notes document a diagnosis of type 2 diabetes (not a pain or an infection)?"),
    _ir(INCJ, "inclusion", "note", "2型糖尿病の診断", NOTE_LOGIC,
        note_question="2型糖尿病の診断がカルテに記載されていますか？（type 2 diabetes; not a pain or an infection）"),
    _ir(HIV, "exclusion", "note", "Known HIV infection", NOTE_LOGIC,
        note_question="Do the notes document known HIV infection?"),
]  # fmt: skip
BY_ID = {c["id"]: CriterionIR.model_validate({**c, "ruleset": "R7"}) for c in CRITERIA}
VALUESETS = {
    "VS_NOTE": {"resourceType": "ValueSet", "id": "VS_NOTE", "name": "VS_NOTE", "status": "active",
                "compose": {"include": [{"system": "http://hl7.org/fhir/sid/icd-10-cm",
                                         "concept": [{"code": "Z99.99", "display": "none"}]}]}},
}  # fmt: skip

# ------------------------------------------------------------------------------------------------ the text
OFF_TOPIC = "Patient denies chest pain."
ON_TOPIC = "No history of diabetes. HbA1c 5.2%."
OFF_TOPIC_JA = "胸痛は否定。"
ON_TOPIC_JA = "糖尿病の既往なし。HbA1c 5.2%。"
MET = {INC: "Type 2 diabetes on metformin.", INCJ: "2型糖尿病で治療中。"}  # each inclusion met, when nothing else
NO_HIV = "No HIV infection."
HAS_HIV = "Patient has HIV."  # the control: a quote that states the exclusion's condition
FILLER = "Routine follow-up; no new infection; vitals stable."

PAIR = 0.9  # both models agree at this confidence
ORACLE = {  # the oracle's key is a substring of the criterion's text or question (the first sentence shown decides)
    "2型糖尿病の診断": [Decisive(OFF_TOPIC_JA, "fail", PAIR), Decisive(ON_TOPIC_JA, "fail", PAIR), Decisive(MET[INCJ])],
    "type 2 diabetes": [Decisive(OFF_TOPIC, "fail", PAIR), Decisive(ON_TOPIC, "fail", PAIR), Decisive(MET[INC])],
    "known hiv": [Decisive(HAS_HIV, confidence=PAIR), Decisive(NO_HIV, "fail")],
}  # fmt: skip


def _note(own: str, cid: str | None = None, hiv: str = NO_HIV) -> str:
    """``own``, each inclusion other than ``cid`` met, the HIV sentence and the filler."""
    return " ".join([own, *(s for k, s in MET.items() if k != cid), hiv, FILLER])


PATIENTS: dict[str, dict[str, Any]] = {  # born 1960 unless said, a booked RHEU visit with PRACT unless said
    "OFF_TOPIC_EN": {"number": "20000101", "note": _note(f"{OFF_TOPIC} Vitals stable.", INC)},
    "ON_TOPIC_EN": {"number": "20000102", "note": _note(ON_TOPIC, INC)},
    "OFF_TOPIC_JA": {"number": "20000103", "note": _note(f"{OFF_TOPIC_JA}バイタル安定。", INCJ)},
    "ON_TOPIC_JA": {"number": "20000104", "note": _note(ON_TOPIC_JA, INCJ)},
    # the controls
    "CODED_FAIL": {"number": "20000111", "born": "2014-01-01", "note": _note("")},  # 12: the coded inclusion fails
    "HIV_STATED": {"number": "20000112", "note": _note("", hiv=HAS_HIV)},
    # the other doctor's patient: screened first, so MICROBATCH finds everyone else new
    "OTHERDOC": {"number": "20000120", "pract": PRACT2, "note": _note("")},
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
    Input("a-off-topic-en", INC, "OFF_TOPIC_EN", OFF_TOPIC),
    Input("b-on-topic-en", INC, "ON_TOPIC_EN", ON_TOPIC),
    Input("c-off-topic-ja", INCJ, "OFF_TOPIC_JA", OFF_TOPIC_JA),
    Input("d-on-topic-ja", INCJ, "ON_TOPIC_JA", ON_TOPIC_JA),
]
CONTROLS = [
    Input("coded-inclusion-fails", AGE, "CODED_FAIL", ""),
    Input("exclusion-stated", HIV, "HIV_STATED", HAS_HIV),
]


def test_the_inputs_are_in_their_patients_notes() -> None:
    for i in [*INPUTS, CONTROLS[1]]:
        assert i.quote in PATIENTS[i.patient]["note"], i.name


# ------------------------------------------------------------------------------------------------ the world
def build_lake(nd: Path, lake_dir: Path) -> None:
    types = ("Patient", "Practitioner", "Appointment", "Encounter", "DocumentReference", "Condition", "Consent")
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in types}
    for pr in (PRACT, PRACT2):
        out["Practitioner"].append(_res("Practitioner", pr, name=[{"text": f"Dr {pr} (synthetic)"}]))
    for key, p in PATIENTS.items():
        pid, ref, pract = PID[key], {"reference": f"Patient/{PID[key]}"}, p.get("pract", PRACT)
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


def screen_seen(box: Any, job: Any) -> Seen:
    s = Seen()
    for r in _doc(box, job, "candidate_list_")["rows"]:
        s.status[WHO[r["pid"]]] = r["tier"]
        s.rows[WHO[r["pid"]]] = _rows(r["criteria"])
    for r in _doc(box, job, "excluded_")["rows"]:
        s.status[WHO[r["pid"]]] = "excluded"
        s.rows[WHO[r["pid"]]] = {v["id"]: {"id": v["id"], "verdict": "fail"} for v in r["criteria"]}
    return s


def pool_seen(box: Any, rid: str) -> Seen:
    s = Seen()
    for p in box.orch.db.pool(rid):
        s.status[WHO[p["pid"]]] = p["tier"]
        s.rows[WHO[p["pid"]]] = _rows(p["verdicts"])
    return s


def new_patients_seen(box: Any, job: Any) -> Seen:
    screened = {WHO[p] for p in _doc(box, job, "new_screened_")["pids"]}
    rows = {WHO[r["pid"]]: r for r in _doc(box, job, "candidate_list_")["rows"]}
    s = Seen()
    for k in screened:
        s.status[k] = rows[k]["tier"] if k in rows else "excluded"
        if k in rows:
            s.rows[k] = _rows(rows[k]["criteria"])
    return s


def nav_seen(box: Any, job: Any) -> Seen:
    """NAV: the list a patient is on (``-``: none) and the verdicts of the listed."""
    s = Seen({k: "-" for k in PATIENTS})
    for name, rows in _doc(box, job, "nav_lists_")["lists"].items():
        for r in rows:
            if name != "doc_gaps":
                s.status[WHO[r["pid"]]] = name
            s.rows[WHO[r["pid"]]] = _rows(r["criteria"])
    return s


def build_world(tmp: Path, pg_cluster_url: str) -> dict[str, Seen]:
    tmp.mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    sep = "&" if "?" in pg_cluster_url else "?"
    mp.setenv("TB_DB_URL", f"{pg_cluster_url}{sep}tb_prefix=r2217{os.getpid()}_")
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
        for rid in ("RX", "RV", "RM", "RMV"):
            write_ruleset(approved, rid, "GZQO", scopes={"screen": SCR})
        write_ruleset(approved, "RN", "RA-BIO")  # NAV needs an NHI ruleset: the same criteria
        svc = box.orch.services
        judge, verifier = quoting_pair(QuotingOracle(ORACLE))
        svc.llm, svc.verifier = cast(Any, judge), cast(Any, verifier)  # the scripted pair stands in for LlmClient

        seen: dict[str, Seen] = {}
        screen = f"pract={PRACT}"
        seen["screen.cascade"] = screen_seen(box, run_job(box, f"SCREEN RX {screen}"))
        run_job(box, "MICROBATCH RX incident=0")
        seen["microbatch.recheck.cascade"] = pool_seen(box, "RX")
        run_job(box, f"SCREEN RM pract={PRACT2}")
        seen["microbatch.new.cascade"] = new_patients_seen(box, run_job(box, "MICROBATCH RM"))
        seen["nav"] = nav_seen(box, run_job(box, "NAV RN dept=RHEU", sender="nurse-rheu@hospa.test"))
        case = Seen()
        for key in SCREENED:
            p = PATIENTS[key]
            j = run_job(box, f"CASE RX mrn={p['number']} lang=en", files=(("chart.txt", f"2026-09-20\n{p['note']}".encode()),))  # fmt: skip
            rec = json.loads(next(v for k, v in _outputs(box, j).items() if k.endswith(".json")))
            case.status[key] = "sheet"
            case.rows[key] = _rows(rec["criteria"])
        seen["case"] = case
        mp.setenv("TB_SCREEN_PIPELINE", "v1")
        seen["screen.v1"] = screen_seen(box, run_job(box, f"SCREEN RV {screen}"))
        run_job(box, "MICROBATCH RV incident=0")
        seen["microbatch.recheck.v1"] = pool_seen(box, "RV")
        run_job(box, f"SCREEN RMV pract={PRACT2}")
        seen["microbatch.new.v1"] = new_patients_seen(box, run_job(box, "MICROBATCH RMV"))
        return seen
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> dict[str, Seen]:
    """Every path run once on one box, shared by the run's xdist workers (the first builds it under a lock)."""
    if worker_id == "master":
        return build_world(tmp_path_factory.mktemp("r2217"), pg_cluster_url)
    root = tmp_path_factory.getbasetemp().parent / "r2217-every-path"
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
#: path -> (what the input patient's status must be, what a control's must be). NAV's lists are not tiers: a patient
#: with an inclusion that is not "yes" is on no list (``nav.lists`` in ``test_path_independence.py``), so NAV is
#: checked at its rule below (``nav.classify``: the inclusion is a 確認 row, not a "no"). A MICROBATCH re-check
#: re-tiers the pool, which holds no excluded patient. CASE prints a sheet for everyone.
PATHS: dict[str, tuple[tuple[str | None, ...], tuple[str | None, ...]]] = {
    "screen.cascade": (("review",), ("excluded",)),
    "screen.v1": (("review",), ("excluded",)),
    "microbatch.recheck.cascade": (("review",), (None, "excluded")),
    "microbatch.recheck.v1": (("review",), (None, "excluded")),
    "microbatch.new.cascade": (("review",), ("excluded",)),
    "microbatch.new.v1": (("review",), ("excluded",)),
    "nav": (("-",), ("-",)),
    "case": (("sheet",), ("sheet",)),
}
LISTS = [p for p in PATHS if p not in ("nav", "case")]  # the paths that publish a tier and the verdict rows
EVERY = [pytest.param(path, i, id=f"{path}-{i.name}") for path in PATHS for i in INPUTS]
EVERY_CONTROL = [pytest.param(path, i, id=f"{path}-{i.name}") for path in PATHS for i in CONTROLS]


@pytest.mark.parametrize(("path", "case"), EVERY)
def test_an_inclusion_not_met_from_the_notes_sends_the_patient_to_review_on_every_path(
    world: dict[str, Seen], path: str, case: Input
) -> None:
    """The patient's status is review (never excluded). The published row stays "not met" with the quote kept (a
    person reads what the notes said), and the status rule answers it ``unknown``. On the lists, the patient's other
    note criteria were judged: the cascade did not stop at the inclusion as at a hard fail (CAS-3)."""
    s = world[path]
    assert s.status.get(case.patient) in PATHS[path][0], (path, case.name, s.status.get(case.patient))
    if path == "nav":
        return  # on no list, so nothing published about the patient: NAV's rule is checked below
    row = s.rows[case.patient][case.cid]
    assert row["verdict"] == "fail", (path, case.name, row)
    if path == "case":  # CASE's sheet row is its own shape: the quote at the top level
        assert row.get("quote") == case.quote, (path, case.name, row)
        return
    assert (row.get("evidence") or {}).get("quote") == case.quote, (path, case.name, row)
    assert decision.answer_of(BY_ID[case.cid], CriterionVerdict.model_validate(row), POLICY) == "unknown"
    others = {cid: r["verdict"] for cid, r in s.rows[case.patient].items() if cid != case.cid}
    assert others == {AGE: "pass", HIV: "pass", (INCJ if case.cid == INC else INC): "pass"}, (path, case.name, others)


@pytest.mark.parametrize(("path", "case"), EVERY_CONTROL)
def test_a_coded_inclusion_or_a_stated_exclusion_still_excludes_on_every_path(
    world: dict[str, Seen], path: str, case: Input
) -> None:
    s = world[path]
    assert s.status.get(case.patient) in PATHS[path][1], (path, case.name, s.status.get(case.patient))
    row = s.rows.get(case.patient, {}).get(case.cid)
    if row is not None:  # the excluded list and NAV's "on no list" carry no verdict of the control's criterion
        assert row["verdict"] == "fail", (path, case.name, row)


def test_the_world_lists_someone_on_each_list_path(world: dict[str, Seen]) -> None:
    """The premise: every list path screened the inputs and the controls (a path that published nothing would pass
    the control check with None on a re-check)."""
    for path in LISTS:
        missing = [i.patient for i in INPUTS if i.patient not in world[path].status]
        assert not missing, (path, missing)
    for path in ("screen.cascade", "screen.v1", "microbatch.new.cascade", "microbatch.new.v1"):
        assert all(world[path].status.get(i.patient) == "excluded" for i in CONTROLS), path


# ------------------------------------------------------------------------------------------------ each rule itself
def _note_row(i: Input, *, basis: Any = "pair", final: bool | None = True, conf: float = PAIR) -> CriterionVerdict:
    """A note "not met" resting on the quote, as a path publishes or stores it."""
    return CriterionVerdict(
        id=i.cid,
        verdict="fail",
        evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=i.quote, confidence=conf, reason="note"),
        basis=basis,
        final=final,
        prov=["c-judge", "c-verifier"],
    )


def _met(cid: str) -> CriterionVerdict:
    if cid == AGE:
        return CriterionVerdict(id=cid, verdict="pass", evidence=Evidence(resource_refs=[], reason="coded"),
                                basis="coded", prov=[])  # fmt: skip
    return CriterionVerdict(id=cid, verdict="pass",
                            evidence=Evidence(resource_refs=["DocumentReference/d1"], quote="q", confidence=PAIR,
                                              reason="note"), basis="pair", prov=["c"])  # fmt: skip


def _patient(row: CriterionVerdict) -> list[CriterionVerdict]:
    return [row if row.id == cid else _met(cid) for cid in BY_ID]


ROWS = [
    pytest.param(i, basis, final, conf, id=f"{i.name}-{basis}-{final}-{conf}")
    for i, (basis, final), conf in itertools.product(
        INPUTS, [("pair", True), ("pair", False), ("single", False), (None, None)], (PAIR, 0.5)
    )
]


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: f"t{p.threshold}-block{p.note_block}")
@pytest.mark.parametrize(("case", "basis", "final", "conf"), ROWS)
def test_the_status_rule_answers_a_note_inclusion_not_met_unknown_under_every_policy(
    case: Input, basis: Any, final: bool | None, conf: float, policy: decision.Policy
) -> None:
    """``answer_of``: SCREEN on v1, MICROBATCH (a stored pool row too), NAV's answers and the cascade's published tier.
    Whatever the policy, the basis, ``final`` or the confidence: ``unknown``, and the patient's status review."""
    v = _note_row(case, basis=basis, final=final, conf=conf)
    assert decision.answer_of(BY_ID[case.cid], v, policy) == "unknown"
    assert decision.status_of(BY_ID, _patient(v), policy).tier == "review"


@pytest.mark.parametrize("case", [pytest.param(i, id=f"mixed-{i.name}") for i in INPUTS])
def test_a_mixed_inclusion_the_codes_did_not_settle_is_a_note_answer(case: Input) -> None:
    c = BY_ID[case.cid].model_copy(update={"class_": "mixed"})
    v = _note_row(case)
    assert decision.is_note_answer(c, v)
    assert decision.answer_of(c, v, POLICY) == "unknown"


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: f"t{p.threshold}-block{p.note_block}")
def test_the_records_answer_and_a_persons_still_exclude(policy: decision.Policy) -> None:
    """Controls of the status rule: a coded inclusion "not met" (structured, and a mixed one the codes settled: no
    model confidence), and a person's "not met" on the note inclusion, exclude under every policy."""
    coded = CriterionVerdict(id=AGE, verdict="fail", evidence=Evidence(resource_refs=[], reason="coded"),
                             basis="coded", prov=[])  # fmt: skip
    assert decision.answer_of(BY_ID[AGE], coded, policy) == "no"
    assert decision.status_of(BY_ID, _patient(coded), policy).tier == "excluded"
    settled = CriterionVerdict(id=INC, verdict="fail", evidence=Evidence(resource_refs=["Condition/c1"], reason="coded"),
                               basis="coded", prov=[])  # fmt: skip
    assert decision.answer_of(BY_ID[INC].model_copy(update={"class_": "mixed"}), settled, policy) == "no"
    person = CriterionVerdict(id=INC, verdict="fail", evidence=Evidence(resource_refs=[], reason="human"),
                              basis="person", prov=[])  # fmt: skip
    assert decision.answer_of(BY_ID[INC], person, policy) == "no"


def test_an_exclusion_whose_quote_states_the_condition_still_excludes() -> None:
    v = _note_row(CONTROLS[1])
    assert decision.answer_of(BY_ID[HIV], v, POLICY) == "no"
    assert decision.status_of(BY_ID, _patient(v), POLICY).tier == "excluded"


def _note_result(i: Input) -> NoteResult:
    return NoteResult("fail", PAIR, i.quote, "2026-09-20", "note", dids=["d1"], calls=["c-judge", "c-verifier"])


@pytest.mark.parametrize("case", [pytest.param(i, id=f"v1.note_verdict-{i.name}") for i in INPUTS])
def test_the_v1_row_stays_not_met_and_the_status_is_review(case: Input) -> None:
    """``note_verdict`` (SCREEN on v1, NAV, CASE, MICROBATCH on v1): the row is the pair's "not met" with its quote;
    the status rule reads it as a person's check."""
    v = note_verdict(BY_ID[case.cid], _note_result(case), pair=True)
    assert (v.verdict, v.basis) == ("fail", "pair")
    assert v.evidence is not None and v.evidence.quote == case.quote
    assert decision.status_of(BY_ID, _patient(v), POLICY).tier == "review"


class _Rs:
    """The one thing ``nav.classify`` asks of a ruleset."""

    def by_id(self) -> dict[str, CriterionIR]:
        return BY_ID


@pytest.mark.parametrize("case", [pytest.param(i, id=f"nav.classify-{i.name}") for i in INPUTS])
def test_nav_reads_an_inclusion_not_met_from_the_notes_as_a_row_to_confirm(case: Input) -> None:
    """NAV (line 83: the status rule's answer per criterion): the inclusion is a 確認 row, not a "no". A patient with
    an inclusion not "yes" is on no NAV list (``nav.lists``), so the row is what NAV's rule changes."""
    v = note_verdict(BY_ID[case.cid], _note_result(case), pair=True)
    pv = PatientVerdicts("P1", _patient(v), "review", [], 0)
    name, missing = nav.classify(cast(Any, _Rs()), pv, None, None, RUN, 42, 90, 0.75, True)
    assert name is None and [m.criterion_id for m in missing] == [case.cid]


@pytest.mark.parametrize("case", [pytest.param(i, id=f"nav.classify-{i.name}") for i in CONTROLS])
def test_nav_reads_a_coded_inclusion_or_a_stated_exclusion_as_a_no(case: Input) -> None:
    if case.cid == AGE:
        v = CriterionVerdict(id=AGE, verdict="fail", evidence=Evidence(resource_refs=[], reason="coded"),
                             basis="coded", prov=[])  # fmt: skip
    else:
        v = _note_row(case)
    pv = PatientVerdicts("P1", _patient(v), "excluded", [], 0)
    assert nav.classify(cast(Any, _Rs()), pv, None, None, RUN, 42, 90, 0.75, True) == (None, [])


def _cascade(i: Input, note_block: bool, stage: str = "S3") -> Any:
    reply = JudgeReply("fail", PAIR, i.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    return _run_for_map(note_block)._map(BY_ID[i.cid], reply, {**SPAN, "quote": i.quote}, stage)


@pytest.mark.parametrize("note_block", [True, False], ids=["block", "no-block"])
@pytest.mark.parametrize("stage", ["S3", "S4"])
@pytest.mark.parametrize("case", [pytest.param(i, id=f"cascade.map-{i.name}") for i in INPUTS])
def test_the_cascade_outcome_of_an_inclusion_not_met_is_a_soft_fail(case: Input, stage: str, note_block: bool) -> None:
    """``engine._map`` (SCREEN on the cascade, MICROBATCH's screen of new patients): "not met", never hard (no CAS-3
    stop, no exclusion, no recall stratum), whatever the policy."""
    o = _cascade(case, note_block, stage)
    assert (o.status, o.hard, o.stratum) == ("fail", False, None)


def test_the_cascade_outcome_of_a_stated_exclusion_is_a_hard_fail() -> None:
    c = CONTROLS[1]
    reply = JudgeReply("pass", PAIR, c.quote, "2026-09-20", "both agree", call_id="c1", prompt="judge@test")
    o = _run_for_map(True)._map(BY_ID[c.cid], reply, {**SPAN, "quote": c.quote}, "S3")
    assert (o.status, o.hard) == ("fail", True)
