"""Path independence (T-705, D-459; card AD-5 of ``docs/reviews/2026-11-12-architecture/decision.md``).

One small lake, one scripted pair that reads the text it is shown (``tests/judge_kit.py``: :class:`QuotingOracle`),
and every path that decides or counts patients, driven in process on the same snapshot through the real
orchestrator, mail gateway and job database (``tests/inproc_box.py``): SCREEN on the cascade and on v1, MICROBATCH
(the re-check of the pool and the screen of new patients), NAV, CASE with a chart number, FEAS and COHORT.

What must hold, per planted patient (``PATIENTS``):

* **the same status** on every path as on the reference path (SCREEN on the cascade, the default engine), read
  through the named table of the differences that are decisions (``INTENDED``);
* **the same verdict** for every criterion two paths both publish;
* **an opted-out patient is in no published bytes** of any path: lists, pool, workbooks, drafts, evidence files,
  the mail.

Today's unintended differences are strict expected failures (``KNOWN``), each naming its finding id of the review
(H1 to H4, M1 to M5) or of the critical-issues register. A card that fixes one removes its lines: a line whose
check starts to pass fails the run (``strict=True``), and so does a line no check uses. A card that adds a path that
decides or counts patients adds it here (plan v6.1 §5.1).

What cannot be driven as a path, and why, is said where the test stands in for it (the console's list, the COHORT
job's trial simulation).
"""

from __future__ import annotations

import base64
import fcntl
import io
import json
import multiprocessing
import os
import pickle
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching import decision
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, CriterionVerdict, JobCreate

from tests.inproc_box import Box, make_box
from tests.judge_kit import Decisive, QuotingOracle, ScriptedModel, quoting_pair

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
RUN = date(2026, 10, 5)  # a Monday
SNAP = "2026-10-04"
TZ = "Asia/Taipei"  # the zone of deploy/settings.example.yaml's site (D-315)
PRACT, PRACT2, DEPT = "P12345", "P23456", "RHEU"  # doctors of deploy/settings.example.yaml
ICD = "http://hl7.org/fhir/sid/icd-10-cm"

# ------------------------------------------------------------------------------------------------ the decisive text
FLARE = "Acute gout flare of the right toe."
SOFTFLARE = "Possible gout flare last spring."
NOFLARE = "No gout flare in the past year."
TB = "Active tuberculosis infection under treatment."
NO_TB = "Tuberculosis screening negative."
PREG = "Pregnancy test positive today."
NOT_PREG = "Pregnancy test negative."
FILLER = "Routine follow-up, vitals stable, no change in plan."
ASKED = "Gout clinic: did the patient have a gout flare in the past year? Notes of the past year to be reviewed."

ORACLE = {  # what a careful reader answers when shown the sentence (rule order: the first shown decides)
    "gout flare": [Decisive(FLARE), Decisive(SOFTFLARE, confidence=0.6), Decisive(NOFLARE, "fail")],
    "tuberculosis": [Decisive(TB), Decisive(NO_TB, "fail")],
    "pregnan": [Decisive(PREG), Decisive(NOT_PREG, "fail")],
}

# ------------------------------------------------------------------------------------------------ the ruleset
NOTE_LOGIC = {"domain": "condition", "valueset": "VS_NOTE"}


def _ir(cid: str, kind: str, class_: str, text: str, logic: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": cid, "kind": kind, "class": class_, "text": text, "label": text[:30], "logic": logic,
            "review": {"status": "approved", "by": "crc1@hospa.test", "at": "2026-10-01T09:00:00+08:00"}, **extra}  # fmt: skip


def _window(days: int) -> dict[str, Any]:
    return {"window": {"anchor": "index", "from_days": -days, "to_days": 0}}


CRITERIA: list[dict[str, Any]] = [
    _ir("PI-INC-01", "inclusion", "structured", "Age 18 or older",
        {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
    _ir("PI-INC-02", "inclusion", "note", "Gout flare in the past year", {**NOTE_LOGIC, **_window(365)},
        note_question="Do the notes document a gout flare in the past year?"),
    _ir("PI-EXC-01", "exclusion", "note", "Active tuberculosis infection", {**NOTE_LOGIC, **_window(365)},
        note_question="Do the notes document active tuberculosis infection?"),
    _ir("PI-EXC-02", "exclusion", "note", "Currently pregnant", {**NOTE_LOGIC, **_window(30)},
        note_question="Do the notes document a current pregnancy?", time_sensitive=True),
    _ir("PI-EXC-03", "exclusion", "structured", "Malignancy within the past 5 years",
        {"domain": "condition", "quantifier": "any", "valueset": "VS_MALIG", **_window(1825)}),
]  # fmt: skip
AMENDMENT = _ir("PI-INC-03", "inclusion", "structured", "Age 70 or older",
                {"domain": "demographic", "valueset": "NONE", "age": {"min": 70}})  # fmt: skip
STRUCTURED = {c["id"] for c in CRITERIA if c["class"] == "structured"}
INCLUSIONS = {c["id"] for c in CRITERIA if c["kind"] == "inclusion"}
RECHECKED = {c["id"] for c in CRITERIA if c.get("time_sensitive")}  # what the weekly re-check asks again
VALUESETS = {
    "VS_MALIG": {"resourceType": "ValueSet", "id": "VS_MALIG", "name": "VS_MALIG", "status": "active",
                 "compose": {"include": [{"system": ICD, "concept": [{"code": "C50.9", "display": "breast"}]}]}},
    "VS_NOTE": {"resourceType": "ValueSet", "id": "VS_NOTE", "name": "VS_NOTE", "status": "active",
                "compose": {"include": [{"system": ICD, "concept": [{"code": "Z99.99", "display": "none"}]}]}},
}  # fmt: skip


def write_ruleset(root: Path, rid: str, base: str, version: str = "1.0.0",
                  extra: list[dict[str, Any]] | None = None, **manifest: Any) -> Ruleset:  # fmt: skip
    """``CRITERIA`` (+ ``extra``) as the approved ruleset ``rid``, under the manifest of the committed ruleset
    ``base`` (its kind, routing, scopes and judge prompt pin). The same criterion ids in every copy, so the paths'
    verdicts compare one to one. ``root`` is not a git repository, so no approval tag is asked for."""
    crits = [CriterionIR.model_validate({**c, "ruleset": rid}) for c in [*CRITERIA, *(extra or [])]]
    sql = SqlGenerator(rid, version, ValueSets(rid, VALUESETS, Terminology())).render(
        [c for c in crits if c.class_ == "structured"]
    )
    m = Ruleset.load(ROOT / "rulesets" / base).manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    m.update({"id": rid, "version": version, "criteria": [c.id for c in crits], "trial_alias": rid, **manifest})
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


# ------------------------------------------------------------------------------------------------ the patients
def _note(on: str, *sentences: str) -> tuple[str, str]:
    """A note that also says, in so many words, that there is no tuberculosis and no pregnancy (a reader needs a
    sentence to answer "not present"; the pair keeps no answer without a quote)."""
    return on, " ".join([*sentences, NO_TB, NOT_PREG, FILLER])


# Adults (born 1960) with a booked visit with PRACT on 2026-10-08 in RHEU, unless the entry says otherwise; "number"
# is the synthetic hospital's chart number (the pseudonym is made from it with the site key, as the adapter does).
PATIENTS: dict[str, dict[str, Any]] = {
    "ELIG": {"number": "10000001", "notes": [_note("2026-09-20", FLARE)]},
    "INF": {"number": "10000002", "notes": [_note("2026-09-20", FLARE), _note("2026-08-01", TB)]},
    "CODED": {"number": "10000003", "notes": [_note("2026-09-20", FLARE)], "malig": "2026-01-10"},
    "NOFLARE": {"number": "10000004", "notes": [_note("2026-09-20", NOFLARE)]},
    "SILENT": {"number": "10000005", "notes": [_note("2026-09-20")]},
    "CHILD": {"number": "10000006", "birth": "2015-03-01", "notes": [_note("2026-09-20", FLARE)]},
    "OPT": {"number": "10000007", "notes": [_note("2026-09-20", FLARE)], "optout": True},
    "REFUSED": {"number": "10000008", "notes": [_note("2026-09-20", FLARE)],
                "consent": [("rejected", "deny", "2026-05-01")]},
    "NOCONTACT": {"number": "10000009", "notes": [_note("2026-09-20", FLARE)],
                  "consent": [("active", "deny", "2026-05-01")]},
    "UNDATED": {"number": "10000010", "notes": [_note("2026-09-20", FLARE)],
                "consent": [("active", "permit", "2026-05-01"), ("rejected", "deny", None)]},
    "PERMIT": {"number": "10000011", "notes": [_note("2026-09-20", FLARE)],
               "consent": [("active", "permit", "2026-05-01")]},
    "LOWCONF": {"number": "10000012", "notes": [_note("2026-09-20", SOFTFLARE)]},
    "PREGNANT": {"number": "10000013", "notes": [_note("2026-09-20", FLARE), _note("2026-10-01", PREG)]},
    "NOAGE": {"number": "10000014", "birth": None, "notes": [_note("2026-09-20", FLARE)]},
    # the flare is in an old note; seven newer notes say there was none (which text a path shows decides)
    "CUT": {"number": "10000015", "notes": [_note("2026-01-15", FLARE)]
            + [_note(f"2026-09-{d:02d}", NOFLARE) for d in (1, 5, 9, 13, 17, 21, 25)]},
    # the flare is in an old note, the newer ones say nothing about it (an unknown first answer: the full record)
    "DEEP": {"number": "10000017", "notes": [_note("2026-01-15", FLARE)]
             + [_note(f"2026-09-{d:02d}", ASKED) for d in (1, 5, 9, 13, 17, 21, 25)]},
    "OTHERDOC": {"number": "10000016", "pract": PRACT2, "notes": [_note("2026-09-20", FLARE)]},
}  # fmt: skip
PID = {k: pid_for_mrn(KEY, v["number"]) for k, v in PATIENTS.items()}
WHO = {v: k for k, v in PID.items()}
SCREENED = [k for k, v in PATIENTS.items() if v.get("pract", PRACT) == PRACT]  # SCREEN's scope (pract=PRACT)


def _res(rtype: str, rid: str, **body: Any) -> dict[str, Any]:
    return {"resourceType": rtype, "id": rid, **body}


def build_lake(nd: Path, lake_dir: Path) -> None:
    """``PATIENTS`` as FHIR NDJSON, flattened into one lake snapshot by the lake's own rebuild (hash embedder)."""
    types = ("Patient", "Practitioner", "Appointment", "Encounter", "DocumentReference", "Condition", "Consent")
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in types}
    for pr in (PRACT, PRACT2):
        out["Practitioner"].append(_res("Practitioner", pr, name=[{"text": f"Dr {pr} (synthetic)"}]))
    for key, p in PATIENTS.items():
        pid, ref = PID[key], {"reference": f"Patient/{PID[key]}"}
        birth = p.get("birth", "1960-01-01")
        out["Patient"].append(_res("Patient", pid, gender="female", **({"birthDate": birth} if birth else {})))
        out["Appointment"].append(_res(
            "Appointment", f"{pid}-a", status="booked", start="2026-10-08T09:00:00+08:00",
            serviceType=[{"coding": [{"code": DEPT}]}],
            participant=[{"actor": ref}, {"actor": {"reference": f"Practitioner/{p.get('pract', PRACT)}"}}]))  # fmt: skip
        out["Encounter"].append(_res(
            "Encounter", f"{pid}-e", status="finished", subject=ref, serviceType={"coding": [{"code": DEPT}]},
            participant=[{"individual": {"reference": f"Practitioner/{p.get('pract', PRACT)}"}}],
            period={"start": "2026-09-20T09:00:00+08:00", "end": "2026-09-20T09:30:00+08:00"}))  # fmt: skip
        for i, (on, text) in enumerate(p["notes"], start=1):
            out["DocumentReference"].append(_res(
                "DocumentReference", f"{pid}-d{i}", subject=ref, date=f"{on}T09:00:00+08:00",
                type={"text": "progress"},
                content=[{"attachment": {"contentType": "text/plain",
                                         "data": base64.b64encode(text.encode()).decode()}}]))  # fmt: skip
        if p.get("malig"):
            out["Condition"].append(_res(
                "Condition", f"{pid}-c1", subject=ref, code={"coding": [{"system": ICD, "code": "C50.9"}]},
                recordedDate=p["malig"], onsetDateTime=p["malig"]))  # fmt: skip
        for i, (status, prov, on) in enumerate(p.get("consent", []), start=1):
            out["Consent"].append(_res(
                "Consent", f"{pid}-k{i}", patient=ref, status=status, provision={"type": prov},
                **({"dateTime": on} if on else {})))  # fmt: skip
    nd.mkdir(parents=True)
    for t, rows in out.items():
        (nd / f"{t}.ndjson").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    Lake(lake_dir, TZ).rebuild(SNAP, HashEmbedder(), nd)


def chart(key: str) -> bytes:
    """The patient's notes as the chart a PI attaches to CASE: one dated paragraph per note."""
    return "\n\n".join(f"{on}\n{text}" for on, text in PATIENTS[key]["notes"]).encode("utf-8")


# ------------------------------------------------------------------------------------------------ what a path says
@dataclass
class Seen:
    """What one path published about each patient: a status word (or None: the path published nothing about the
    patient) and the verdict of each criterion it published."""

    status: dict[str, str | None] = field(default_factory=dict)
    verdicts: dict[str, dict[str, str]] = field(default_factory=dict)
    covers: set[str] = field(default_factory=set)  # the patients this path was asked about
    why: dict[str, str] = field(default_factory=dict)  # an exclusion with no criterion: "refused" or "contact"
    # what each published verdict says for eligibility (yes / no / unknown) by the one status function (D-478)
    answers: dict[str, dict[str, str]] = field(default_factory=dict)
    # the criteria whose stored answer says it was not allowed to exclude (final: false, D-476)
    not_final: dict[str, set[str]] = field(default_factory=dict)


def _outputs(box: Box, job: Any) -> dict[str, bytes]:
    return {o.filename: box.store.get(o.minio_key) for o in job.outputs or []}


def _doc(box: Box, job: Any, prefix: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(
        next(v for k, v in _outputs(box, job).items() if k.startswith(prefix) and k.endswith(".json"))
    )
    return doc


def _verdicts(criteria: list[dict[str, Any]]) -> dict[str, str]:
    return {v["id"]: v["verdict"] for v in criteria}


def _answers(criteria: list[dict[str, Any]]) -> dict[str, str]:
    """What each published verdict says for eligibility, by the one status function (``matching.decision``) under
    the world's policy: the default threshold, a pair that may exclude."""
    policy = decision.Policy(0.75, True)
    by = {c["id"]: SimpleNamespace(class_=c["class"]) for c in CRITERIA}
    return {v["id"]: decision.answer_of(by[v["id"]], CriterionVerdict.model_validate(v), policy)
            for v in criteria if v["id"] in by}  # fmt: skip


def screen_seen(box: Box, job: Any, covers: list[str]) -> Seen:
    """SCREEN: the candidate list (high, review; every verdict) and the excluded list (the failing criteria)."""
    assert job.state == "done", job.error
    s = Seen(covers=set(covers))
    for r in _doc(box, job, "candidate_list_")["rows"]:
        s.status[WHO[r["pid"]]] = r["tier"]
        s.verdicts[WHO[r["pid"]]] = _verdicts(r["criteria"])
        s.answers[WHO[r["pid"]]] = _answers(r["criteria"])
    for r in _doc(box, job, "excluded_")["rows"]:
        s.status[WHO[r["pid"]]] = "excluded"
        s.verdicts[WHO[r["pid"]]] = {v["id"]: "fail" for v in r["criteria"]}
        acts = " ".join(r.get("actions") or [])
        if not r["criteria"] and acts:  # the cascade's S0: a consent statement, not a criterion
            s.why[WHO[r["pid"]]] = "contact" if "contact: deny" in acts else "refused"
    return s


def pool_seen(box: Box, rid: str, covers: set[str]) -> Seen:
    """MICROBATCH's re-check: the pool rows after the run (tier and every stored verdict)."""
    s = Seen(covers=covers)
    for p in box.orch.db.pool(rid):
        if WHO[p["pid"]] in covers:
            s.status[WHO[p["pid"]]] = p["tier"]
            s.verdicts[WHO[p["pid"]]] = _verdicts(p["verdicts"])
            s.not_final[WHO[p["pid"]]] = {v["id"] for v in p["verdicts"] if v.get("final") is False}
    return s


def new_patients_seen(box: Box, job: Any) -> Seen:
    """MICROBATCH's new patients: the ones its record says it screened; listed ones with their tier and verdicts,
    the others excluded (the run publishes no evidence file for them)."""
    assert job.state == "done", job.error
    screened = {WHO[p] for p in _doc(box, job, "new_screened_")["pids"]}
    s = Seen(covers=screened)
    rows = {WHO[r["pid"]]: r for r in _doc(box, job, "candidate_list_")["rows"]}
    for k in screened:
        s.status[k] = rows[k]["tier"] if k in rows else "excluded"
        if k in rows:
            s.verdicts[k] = _verdicts(rows[k]["criteria"])
    return s


def nav_seen(box: Box, job: Any) -> Seen:
    """NAV: the list a patient is on (``-``: on none); verdicts of the listed."""
    assert job.state == "done", job.error
    s = Seen(covers=set(PATIENTS))
    for k in PATIENTS:
        s.status[k] = "-"
    for name, rows in _doc(box, job, "nav_lists_")["lists"].items():
        for r in rows:
            if name != "doc_gaps":
                s.status[WHO[r["pid"]]] = name
            s.verdicts[WHO[r["pid"]]] = _verdicts(r["criteria"])
    return s


# ------------------------------------------------------------------------------------------------ the world
def run_job(box: Box, subject: str, sender: str = "crc1@hospa.test", files: tuple[tuple[str, bytes], ...] = ()) -> Any:
    """``subject`` as a mail to the box (the gateway makes the job), or, for MICROBATCH (a timer's job, never
    mailed), as the scheduler submits it."""
    before = {j.job_id for j in box.orch.db.find(limit=1000)}
    words = subject.split()
    if words[0] == "MICROBATCH":
        opts = dict(w.split("=", 1) for w in words[2:])
        box.orch.create(JobCreate(type="MICROBATCH", ruleset=words[1], requested_by="scheduler", options=opts or None))
    else:
        assert box.mail(subject, files, sender=sender) == "Processed", subject
    box.orch.drain()
    (job,) = [j for j in box.orch.db.find(limit=1000) if j.job_id not in before]
    return job


@dataclass
class JobView:
    """What a job left: its state, its error and every file it published (as stored, by file name)."""

    state: str
    error: str
    outputs: dict[str, bytes]


@dataclass
class World:
    """Everything the tests read, as plain data: built once per run and shared by the xdist workers."""

    seen: dict[str, Seen]
    jobs: dict[str, JobView]
    mails: list[str]  # subject and every text part of each mail the box sent
    pools: dict[str, list[str]]  # ruleset -> the pids of its candidate pool at the end
    cohort: dict[str, Any]
    asked: set[str]  # the oracle's keys the pair was asked about
    lake_dir: Path
    rulesets_dir: Path


SCR = {"practitioners": [PRACT, PRACT2], "appointment_window_days": 180, "recent_encounter_months": 12,
       "microbatch_window_days": 14}  # fmt: skip


@pytest.fixture(scope="module", autouse=True)
def _reimbursement_open() -> Iterator[None]:
    """Card 9e-9: NAV runs only on a test box with reimbursement switched on; this module's box is."""
    from orchestrator import reimbursement

    with pytest.MonkeyPatch.context() as m:
        m.setattr(reimbursement, "is_open", lambda *a, **k: True)
        yield


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str, worker_id: str) -> World:
    """Every path run once on one box, one lake, one snapshot (about 45 s), shared by the xdist workers of the run
    (the first builds it under a lock, the others read it), so ``-n auto`` does not build it once per worker.

    H-81: a build that fails is not built again. The fixture is module-scoped, so a worker that leaves the module and
    comes back (``--dist worksteal``) asks again; it used to rebuild into the same ``build-<pid>`` folder and fail on
    ``sec`` already being there, hiding the first error. Each build gets a folder of its own, and the first failure is
    written down and raised again, with its text, to every later request of the run."""
    if worker_id == "master":
        return build_world(tmp_path_factory.mktemp("paths"), pg_cluster_url)
    root = tmp_path_factory.getbasetemp().parent / "path-independence"  # one directory for the run's workers
    w: World = shared_build(root, lambda tmp: build_world(tmp, pg_cluster_url))
    return w


def shared_build(root: Path, build: Callable[[Path], Any]) -> Any:
    """``build`` run once for the run's workers under a file lock, each attempt in a folder of its own; the result
    pickled for the others; a failure written down and raised again, with its text, instead of a second build."""
    root.mkdir(parents=True, exist_ok=True)
    done = root / "world.pickle"
    failed = root / "world.failed"
    with (root / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if not done.exists():
                if failed.exists():
                    raise RuntimeError(f"the world of this run failed to build, not built again: {failed.read_text()}")
                try:
                    w = build(Path(tempfile.mkdtemp(prefix=f"build-{os.getpid()}-", dir=root)))
                except Exception as e:
                    failed.write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
                    raise
                done.write_bytes(pickle.dumps(w))
            return pickle.loads(done.read_bytes())  # this run's own file
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def build_world(tmp: Path, pg_cluster_url: str) -> World:
    """The site's week, in the order a site would see it. The world's own trial database (the per-test one of
    ``tests/conftest.py`` would not outlive the first test)."""
    tmp.mkdir(parents=True, exist_ok=True)
    mp = pytest.MonkeyPatch()
    sep = "&" if "?" in pg_cluster_url else "?"
    mp.setenv("TB_DB_URL", f"{pg_cluster_url}{sep}tb_prefix=pathind{os.getpid()}_")
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
        box.orch.rulesets_dir = approved  # the approved rulesets of this test (the box's repo holds the seed)
        rs = {
            "PIX": write_ruleset(approved, "PIX", "GZQO", scopes={"screen": SCR}),  # the reference
            "PIV": write_ruleset(approved, "PIV", "GZQO", scopes={"screen": SCR}),  # SCREEN on v1 (own pool)
            "PIM": write_ruleset(approved, "PIM", "GZQO", scopes={"screen": SCR}),  # MICROBATCH new patients
            "PIS": write_ruleset(approved, "PIS", "GZQO", scopes={"screen": SCR}),  # one model, then the pair (H1)
            "PIA": write_ruleset(approved, "PIA", "GZQO", scopes={"screen": SCR}),  # amended (H3)
            "PIXN": write_ruleset(approved, "PIXN", "RA-BIO"),  # NAV needs an NHI ruleset: same criteria
            "PISN": write_ruleset(approved, "PISN", "RA-BIO"),
        }
        oracle = QuotingOracle(ORACLE)
        svc = box.orch.services
        svc.llm, svc.verifier = quoting_pair(oracle)  # type: ignore[assignment]  # a scripted LlmClient
        from tb_common.optout import OptOutRegister

        reg = OptOutRegister()
        reg.add(PID["OPT"], "paper", "synthetic opt-out", "crc1@hospa.test", "2026-10-01T09:00:00+08:00")
        reg.close()

        jobs: dict[str, Any] = {}
        seen: dict[str, Seen] = {}
        screen = f"pract={PRACT}"
        # the reference: SCREEN on the cascade, then the weekly MICROBATCH re-check of its pool
        jobs["screen.cascade"] = run_job(box, f"SCREEN PIX {screen}")
        seen["screen.cascade"] = screen_seen(box, jobs["screen.cascade"], SCREENED)
        pooled = {WHO[p["pid"]] for p in box.orch.db.pool("PIX")}
        jobs["microbatch.recheck"] = run_job(box, "MICROBATCH PIX incident=0")
        seen["microbatch.recheck"] = pool_seen(box, "PIX", pooled)
        # SCREEN on the v1 evaluator
        mp.setenv("TB_SCREEN_PIPELINE", "v1")
        jobs["screen.v1"] = run_job(box, f"SCREEN PIV {screen}")
        seen["screen.v1"] = screen_seen(box, jobs["screen.v1"], SCREENED)
        mp.delenv("TB_SCREEN_PIPELINE")
        # MICROBATCH new patients: a SCREEN of the other doctor's patient only, then everyone else is new
        jobs["screen.other"] = run_job(box, f"SCREEN PIM pract={PRACT2}")
        jobs["microbatch.new"] = run_job(box, "MICROBATCH PIM")
        seen["microbatch.new"] = new_patients_seen(box, jobs["microbatch.new"])
        # NAV (the RHEU appointments of the week: every patient)
        jobs["nav"] = run_job(box, "NAV PIXN dept=RHEU", sender="nurse-rheu@hospa.test")
        seen["nav"] = nav_seen(box, jobs["nav"])
        # CASE with the chart number and the patient's notes as the chart
        case = Seen(covers=set(SCREENED))
        for key in SCREENED:
            jobs[f"case.{key}"] = j = run_job(box, f"CASE PIX mrn={PATIENTS[key]['number']} lang=en",
                                              files=(("chart.txt", chart(key)),))  # fmt: skip
            if j.state == "done":
                rec = json.loads(next(v for k, v in _outputs(box, j).items() if k.endswith(".json")))
                case.verdicts[key] = {r["id"]: r["verdict"] for r in rec["criteria"]}
                case.status[key] = "sheet"
            else:
                case.status[key] = None
        seen["case"] = case
        # FEAS: who the count holds at its latest month-end (``FeasRaw.prevalent_pids``, which the job keeps in
        # memory for its profile and publishes as counts only: read from the job's own call)
        from orchestrator.scenarios import feas, feas_compute

        raws: list[Any] = []

        def spy(*a: Any, **kw: Any) -> Any:
            res = real(*a, **kw)
            raws.append(res[1])
            return res

        real = feas_compute.compute
        mp.setattr(feas, "compute", spy)
        jobs["feas"] = run_job(box, "FEAS PIX")
        mp.setattr(feas, "compute", real)
        assert jobs["feas"].state == "done", jobs["feas"].error
        members = {WHO[p] for p in raws[0].prevalent_pids}
        seen["feas"] = Seen({k: "member" if k in members else "-" for k in PATIENTS}, {}, set(PATIENTS))
        # COHORT: its own count functions at the run date (cohort_counts)
        cohort = cohort_counts(box, rs["PIX"])
        by_kind = {c["id"]: c["kind"] for c in CRITERIA}
        seen["cohort"] = Seen(
            {k: "member" if PID[k] in cohort["population"] else "-" for k in PATIENTS},
            {k: {cid: ("pass" if by_kind[cid] == "inclusion" else "fail") if PID[k] in pids else "-"
                 for cid, pids in cohort["items"].items()} for k in PATIENTS if PID[k] in cohort["population"]},
            set(PATIENTS),
        )  # fmt: skip

        # one model (TB_SCREEN_JUDGE=single: no verifier, a note answer may not exclude): SCREEN and NAV
        mp.setenv("TB_SCREEN_JUDGE", "single")
        jobs["screen.single"] = run_job(box, f"SCREEN PIS {screen}")
        seen["screen.single"] = screen_seen(box, jobs["screen.single"], SCREENED)
        jobs["nav.single"] = run_job(box, "NAV PISN dept=RHEU", sender="nurse-rheu@hospa.test")
        seen["nav.single"] = nav_seen(box, jobs["nav.single"])
        mp.delenv("TB_SCREEN_JUDGE")
        # H1: the next week the pair is back, and its verifier reads the tuberculosis note the other way. MICROBATCH
        # re-tiers the pool SCREEN left; the reference is SCREEN with the same pair on the same snapshot.
        pooled = {WHO[p["pid"]] for p in box.orch.db.pool("PIS")}
        svc.verifier = reads_tb_the_other_way(oracle)  # type: ignore[assignment]
        jobs["microbatch.after_single"] = run_job(box, "MICROBATCH PIS incident=0")
        seen["microbatch.after_single"] = pool_seen(box, "PIS", pooled)
        jobs["screen.pair_disagrees"] = run_job(box, f"SCREEN PIS {screen}")
        seen["screen.pair_disagrees"] = screen_seen(box, jobs["screen.pair_disagrees"], SCREENED)
        svc.verifier = quoting_pair(oracle)[1]  # type: ignore[assignment]

        # H3: the pool of version 1.0.0, then version 1.1.0 approved with one more inclusion (age 70 or older)
        jobs["screen.before_amendment"] = run_job(box, f"SCREEN PIA {screen}")
        pooled = {WHO[p["pid"]] for p in box.orch.db.pool("PIA")}
        rs["PIA"] = write_ruleset(approved, "PIA", "GZQO", "1.1.0", [AMENDMENT], scopes={"screen": SCR})
        jobs["microbatch.amended"] = run_job(box, "MICROBATCH PIA incident=0")
        seen["microbatch.amended"] = pool_seen(box, "PIA", pooled)
        jobs["screen.amended"] = run_job(box, f"SCREEN PIA {screen}")
        seen["screen.amended"] = screen_seen(box, jobs["screen.amended"], SCREENED)

        views = {n: JobView(j.state, str(j.error or ""), _outputs(box, j)) for n, j in jobs.items()}
        mails = [m.subject + "\n" + "\n".join(p.get_content() for p in m.msg.walk()
                                               if p.get_content_maintype() == "text") for m in box.sent]  # fmt: skip
        pools = {rid: [str(p["pid"]) for p in box.orch.db.pool(rid)] for rid in rs}
        asked = {k for k, _, _ in oracle.asked if k}
        return World(seen, views, mails, pools, cohort, asked, tmp / "lake", approved)
    finally:
        mp.undo()


def reads_tb_the_other_way(oracle: QuotingOracle) -> ScriptedModel:
    """A verifier that agrees with the judge on everything but a note that documents tuberculosis, where it says the
    opposite: the pair disagrees on that patient only (H1)."""

    def answer(variables: dict[str, Any]) -> dict[str, Any]:
        key = oracle.key_of(str(variables.get("criterion_text") or ""), str(variables.get("note_question") or ""))
        ans = oracle.decide(key, list(variables.get("excerpts") or []))
        return {**ans, "verdict": "fail"} if key == "tuberculosis" and ans["verdict"] == "pass" else ans

    return ScriptedModel("verifier-b", answer)


def cohort_counts(box: Box, rs: Ruleset) -> dict[str, Any]:
    """COHORT's membership by its own functions (``cohort.items_at``, ``cohort.contactable_pids``) at the run date
    on the box's lake (one snapshot). The COHORT job itself is not run: its published bytes are suppressed counts (no
    patient id can be compared), and it compiles the trials of the ClinicalTrials.gov cassette, which this test
    does not need (``tests/integration/test_cohort_inproc.py`` runs the job)."""
    from orchestrator.scenarios import cohort

    ctx: Any = SimpleNamespace(services=SimpleNamespace(lake=box.orch.services.lake), cfg=box.orch.cfg)
    items = cohort.items_at(ctx, rs, RUN, SNAP)
    contact = cohort.contactable_pids(ctx, RUN, SNAP)
    return {"population": items[0].pids, "items": {it.criterion_id: it.pids for it in items},
            "contactable": contact or set()}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the decisions
@dataclass(frozen=True)
class Intended:
    """A difference between paths that is a decision, with its reason and where it is decided."""

    reason: str
    basis: str


INTENDED: dict[str, Intended] = {
    "nav.lists": Intended(
        "NAV's lists are not tiers: likely_eligible holds a patient whose every inclusion is met and no exclusion is "
        "known to apply; a patient SCREEN would send to review with an inclusion unknown is on no NAV list (its "
        "open items are the 確認 rows of a listed patient). So: SCREEN high or review with every inclusion met is "
        "likely_eligible, and one whose only open inclusions a note speaks against (D-1072); everything else is on no list. 'Met' is the one status function's yes (D-478): an "
        "inclusion answered below the confidence threshold is a person's check, not met.",
        "SPEC §8.4 (nav.py docstring), D-478",
    ),
    "nav.scope": Intended(
        "NAV scopes by the department's booked visits, SCREEN by the study's doctors: compared on the patients of "
        "both (every planted patient but OTHERDOC).",
        "SPEC §8.4, D-146",
    ),
    "case.chart": Intended(
        "CASE answers the note criteria from the chart the PI attaches, not from the lake's notes: the test "
        "attaches the patient's own notes, so the text is the same.",
        "D-91",
    ),
    "case.no_status": Intended(
        "CASE gives an answer per criterion and no status: the sheet is a reading aid and the PI decides. Its "
        "status here is whether a sheet is made at all.",
        "D-91 (case.py docstring)",
    ),
    "counts.notes": Intended(
        "FEAS and COHORT read no notes: a note criterion is not applied in a count, so a patient excluded by a "
        "note answer is still counted.",
        "D-101",
    ),
    "counts.contact": Intended(
        "A consent that denies contact is not an opt-out: it keeps a patient off every list but in the counts "
        "and on a CASE sheet.",
        "D-441 (the 'contact: deny' item)",
    ),
    "feas.unknown": Intended(
        "FEAS's funnel counts a patient as remaining only when every applied inclusion is true: an inclusion with "
        "no value drops the patient from the count, which reports that drop per step and always adds the "
        "'unknown as pass' variant; SCREEN keeps such a patient for review. A count is a lower bound with its "
        "sensitivity beside it, a list is who a person looks at (ENG-005: was finding M4 in KNOWN).",
        "D-18",
    ),
    "feas.population": Intended(
        "FEAS counts the patients seen in the lookback (an encounter) at month-ends; SCREEN the study's patients "
        "with a booked visit or a recent encounter at the run date. Every planted patient has both, and nothing in "
        "the lake changes between the last month-end and the run date.",
        "SPEC §8.1, D-18",
    ),
    "cohort.documented": Intended(
        "COHORT counts the patients whose record documents each criterion (C IS TRUE) at quarter ends, not who is "
        "eligible: an inclusion without a value is not counted; its membership is read from its count functions "
        "at the run date (its published bytes are suppressed counts).",
        "SPEC §8.3, D-72",
    ),
    "cohort.contactable": Intended(
        "n_contactable needs a recorded active consent; SCREEN lists a patient with no statement. Compared on the "
        "patients with a consent statement only.",
        "D-72, D-441",
    ),
    "microbatch.recheck": Intended(
        "The weekly re-check asks the models again only about the time-sensitive criteria of the pool's patients "
        "and keeps the stored answers of the rest: compared on the pool's patients.",
        "D-397",
    ),
    "microbatch.not_final": Intended(
        "A re-tier never upgrades an answer no pair gave: a 'not met' SCREEN stored under one model is final: false "
        "and keeps the patient at review, where SCREEN with the pair on the same snapshot may exclude. Only a full "
        "screen asks the pair. So: review at the one-model SCREEN and excluded at the reference is review here. "
        "A time-sensitive criterion is asked again by the weekly re-check, so the pair's answer on it excludes. "
        "The stored word stays one model's, and the row says so (final: false, basis: single; D-478): such a "
        "verdict is not compared with the pair's.",
        "D-476 (T-707), D-478 (T-709)",
    ),
    "microbatch.new": Intended(
        "MICROBATCH screens as new only the patients no run has seen since the last SCREEN: compared on the "
        "patients its record says it screened (it publishes no evidence file for those it excludes).",
        "D-397",
    ),
}


# ------------------------------------------------------------------------------------------------ what to expect
@dataclass(frozen=True)
class Rule:
    """A path, the path it must agree with, and the decisions (``INTENDED``) its expectation reads."""

    path: str
    reference: str
    family: str
    intended: tuple[str, ...] = ()


RULES: dict[str, Rule] = {r.path: r for r in [
    Rule("screen.v1", "screen.cascade", "screen"),
    Rule("microbatch.recheck", "screen.cascade", "screen", ("microbatch.recheck",)),
    Rule("microbatch.new", "screen.cascade", "screen", ("microbatch.new",)),
    Rule("nav", "screen.cascade", "nav", ("nav.lists", "nav.scope")),
    Rule("case", "screen.cascade", "case", ("case.chart", "case.no_status", "counts.contact")),
    Rule("feas", "screen.cascade", "feas", ("counts.notes", "counts.contact", "feas.population", "feas.unknown")),
    Rule("cohort", "screen.cascade", "cohort", ("counts.notes", "counts.contact", "cohort.documented",
                                                "cohort.contactable")),
    # one model on the box (no verifier): NAV against SCREEN on the same box
    Rule("nav.single", "screen.single", "nav", ("nav.lists", "nav.scope")),
    # the week after: MICROBATCH re-tiers what SCREEN stored with one model; SCREEN with the pair is the reference
    Rule("microbatch.after_single", "screen.pair_disagrees", "screen", ("microbatch.recheck",
                                                                         "microbatch.not_final")),
    # after an amendment: MICROBATCH screens the old pool again in full (D-476); SCREEN on the approved version
    Rule("microbatch.amended", "screen.amended", "screen", ("microbatch.recheck",)),
]}  # fmt: skip


def structured_truth(w: World, key: str, cid: str) -> str | None:
    """The verdict of a structured criterion as the SQL engine gave it on the screening paths (the first that
    published it); None when none did."""
    for p in ("screen.cascade", "screen.v1", "case"):
        v = w.seen[p].verdicts.get(key, {}).get(cid)
        if v is not None:
            return v
    return None


def out_of_lists(ref: Seen, key: str) -> str | None:
    """Why the reference keeps the patient off every list without a criterion: the register (it never screened
    them), a refusal, or a consent that denies contact."""
    if key in ref.covers and ref.status.get(key) is None:
        return "register"
    return ref.why.get(key)


def expected_status(w: World, rule: Rule, key: str) -> str | None:
    ref = w.seen[rule.reference]
    st = ref.status.get(key)
    why = out_of_lists(ref, key)
    if rule.family == "screen":
        if "microbatch.not_final" in rule.intended and st == "excluded":
            stored = w.seen["screen.single"].status.get(key)  # the row the re-tier started from
            asked_again = any(v == "fail" and c in RECHECKED for c, v in ref.verdicts.get(key, {}).items())
            return "review" if stored == "review" and not asked_again else st
        return st
    if rule.family == "nav":
        ans, said = ref.answers.get(key, {}), ref.verdicts.get(key, {})
        # D-1072: a note "not met" (a verdict of fail the status rule answers "unknown") keeps the patient on the sheet
        stays = {c for c in INCLUSIONS if ans.get(c) == "unknown" and said.get(c) == "fail"}
        if st in ("high", "review") and all(ans.get(c) == "yes" or c in stays for c in INCLUSIONS):
            return "likely_eligible"
        return "-"
    if rule.family == "case":
        return None if why in ("register", "refused") else "sheet"
    struct_fail = any(structured_truth(w, key, c) == "fail" for c in STRUCTURED)
    if rule.family == "feas":
        # D-18: an applied inclusion with no value drops the patient from the funnel (feas.unknown)
        unknown_inc = any(structured_truth(w, key, c) == "unknown" for c in STRUCTURED & INCLUSIONS)
        return "-" if why in ("register", "refused") or struct_fail or unknown_inc else "member"
    if rule.family == "cohort":
        documented = structured_truth(w, key, "PI-INC-01") == "pass"
        return "member" if documented and why not in ("register", "refused") else "-"
    raise AssertionError(rule.family)


def compared(rule: Rule) -> list[str]:
    """The patients a rule compares: those both paths were asked about (``nav.scope``, ``microbatch.*``)."""
    return [k for k in PATIENTS if k in _COVERS.get(rule.path, set(PATIENTS)) and k in _COVERS.get(rule.reference,
            set(PATIENTS))]  # fmt: skip


# who each path is asked about, known before the run (the parametrisation needs it at collection)
_COVERS: dict[str, set[str]] = {p: set(SCREENED) for p in (
    "screen.cascade", "screen.v1", "screen.single", "screen.pair_disagrees", "screen.amended", "case")}  # fmt: skip
_COVERS["microbatch.new"] = set(SCREENED) - {"OPT"}  # the register keeps OPT out of the new patients too
# the pool each re-check starts from: who its SCREEN listed (the world checks that the run agrees)
# UNDATED is on no list: an undated refusal keeps the patient out on every path (D-477, the ruling on its review)
# NOFLARE: its note inclusion "not met" sends it to review, so it is in the pool (R22-17, D-1069; ruled on #639
# 7079180333: the planted patient is expected in review and in the pool)
# INF, PREGNANT: a pair's stated note exclusion sends them to review since ring 0 (D-1072), so they are in the pool
POOL = {"ELIG", "SILENT", "PERMIT", "LOWCONF", "NOAGE", "CUT", "DEEP", "NOFLARE", "INF", "PREGNANT"}
_COVERS["microbatch.recheck"] = _COVERS["microbatch.amended"] = POOL
_COVERS["microbatch.after_single"] = POOL  # one model's "not met" is not final


# ------------------------------------------------------------------------------------------------ known differences
@dataclass(frozen=True)
class Known:
    finding: str
    why: str


# ENG-005: empty. M4 (FEAS drops an inclusion with no value) is D-18's rule, now read from INTENDED ("feas.unknown")
KNOWN: dict[tuple[str, str, str], Known] = {}


def _checks() -> list[Any]:
    out = []
    for rule in RULES.values():
        aspects = ["status"] + (["verdicts"] if rule.family in ("screen", "nav", "case", "cohort") else [])
        aspects += ["consent"] if rule.family == "cohort" else []
        for key in compared(rule):
            for aspect in aspects:
                if aspect == "consent" and not PATIENTS[key].get("consent"):
                    continue
                k = KNOWN.get((rule.path, key, aspect))
                marks = [pytest.mark.xfail(strict=True, reason=f"{k.finding}: {k.why}")] if k else []
                out.append(pytest.param(rule.path, key, aspect, marks=marks, id=f"{rule.path}-{key}-{aspect}"))
    return out


CHECKS = _checks()


# ------------------------------------------------------------------------------------------------ the tests
@pytest.mark.parametrize(("path", "key", "aspect"), CHECKS)
def test_the_same_patient_gets_the_same_answer_on_every_path(world: World, path: str, key: str, aspect: str) -> None:
    """One patient, one snapshot: the path's status (read through ``INTENDED``) and its verdicts are the
    reference's. An expected failure names its finding; when the finding is fixed this test fails until its line
    in ``KNOWN`` is removed."""
    rule = RULES[path]
    seen, ref = world.seen[path], world.seen[rule.reference]
    assert key in seen.covers and key in ref.covers, f"{path} or {rule.reference} was not asked about {key}"
    if aspect == "status":
        assert seen.status.get(key) == expected_status(world, rule, key), (
            f"{path} says {seen.status.get(key)!r} for {key}; {rule.reference} says {ref.status.get(key)!r}"
        )
    elif aspect == "verdicts":
        mine = seen.verdicts.get(key, {})
        if rule.family == "cohort":  # a count holds a patient or not: compared with the documented structured truth
            truth = {c: structured_truth(world, key, c) for c in mine}
            counted = {c: "pass" if c in INCLUSIONS else "fail" for c in mine}  # what being counted says
            diff = {c: (v, truth[c]) for c, v in mine.items()
                    if truth[c] in ("pass", "fail") and (v != "-") != (truth[c] == counted[c])}  # fmt: skip
        else:
            theirs = ref.verdicts.get(key, {})
            skip = seen.not_final.get(key, set()) if "microbatch.not_final" in rule.intended else set()
            diff = {c: (mine[c], theirs[c]) for c in (mine.keys() & theirs.keys()) - skip if mine[c] != theirs[c]}
        assert not diff, f"{path} vs {rule.reference} for {key}: {diff}"
    else:  # consent: COHORT's n_contactable against the reference's lists, for the patients with a statement
        contactable = PID[key] in world.cohort["contactable"]
        assert contactable == (ref.status.get(key) in ("high", "review")), (
            f"COHORT contactable={contactable} for {key}; {rule.reference} says {ref.status.get(key)!r}"
        )


def test_every_known_difference_and_every_decision_is_used() -> None:
    """A line of ``KNOWN`` that no check reads, or a decision of ``INTENDED`` no rule reads, is stale: remove it."""
    ids = {(p.values[0], p.values[1], p.values[2]) for p in CHECKS}
    assert not set(KNOWN) - ids, sorted(set(KNOWN) - ids)
    used = {i for r in RULES.values() for i in r.intended}
    assert used == set(INTENDED), sorted(set(INTENDED) ^ used)
    assert {k.finding for k in KNOWN.values()} <= {"H1", "H2", "H3", "H4", "M1", "M2", "M4", "CR-026"}


def test_the_world_is_not_vacuous(world: World) -> None:
    """Every status word occurs, every path ran, and the pair was asked: the comparisons above compare something."""
    ref = world.seen["screen.cascade"]
    assert {ref.status[k] for k in SCREENED if k in ref.status} == {"high", "review", "excluded"}
    assert {"refused", "contact"} <= set(ref.why.values())
    assert world.seen["nav"].status["ELIG"] == "likely_eligible"
    assert world.seen["feas"].status["ELIG"] == "member" and world.seen["cohort"].status["ELIG"] == "member"
    for p in ("microbatch.recheck", "microbatch.after_single", "microbatch.amended", "microbatch.new"):
        assert world.seen[p].covers == _COVERS[p], (p, sorted(world.seen[p].covers ^ _COVERS[p]))
    # the register, and since D-477 a registry refusal, an undated one included: no sheet is made
    refused = ("case.OPT", "case.REFUSED", "case.UNDATED")
    for n in refused:
        assert world.jobs[n].state == "failed" and "opted out" in world.jobs[n].error, n
    assert {"gout flare", "tuberculosis", "pregnan"} <= world.asked
    # the row MICROBATCH re-tiered from one model's SCREEN says which answer may not exclude (D-476, D-478)
    assert world.seen["microbatch.after_single"].not_final["INF"] == {"PI-EXC-01"}
    assert world.seen["screen.cascade"].answers["LOWCONF"]["PI-INC-02"] == "unknown"  # a met below the threshold
    assert world.seen["screen.cascade"].answers["ELIG"]["PI-INC-02"] == "yes"
    failed = {n: j.error for n, j in world.jobs.items() if j.state != "done" and n not in refused}
    assert not failed, failed


# ------------------------------------------------------------------------------------------------ the pair itself
@pytest.mark.parametrize(
    ("verifier", "expected"),
    [("agree", ("pass", "note")), ("disagree", ("unknown", "disagree")), ("unknown", ("unknown", "disagree")),
     ("down", ("unknown", "model_down"))],
)  # fmt: skip
def test_the_quoting_pair_answers_from_what_it_is_shown(verifier: str, expected: tuple[str, str]) -> None:
    """The kit's pair through the box's own pair rule (``NoteJudge.judge_excerpts``): the answer follows the decisive
    sentence when it is shown, and is unknown when it is not; the verifier's four behaviours reach the pair rule."""
    from orchestrator.scenarios.evaluate import NoteJudge

    oracle = QuotingOracle(ORACLE)
    shown = [{"date": "2026-09-20", "note_type": "progress", "text": f"{FLARE} {FILLER}", "did": "D1"}]
    hidden = [{"date": "2026-09-20", "note_type": "progress", "text": FILLER, "did": "D2"}]
    crit = next(c for c in CRITERIA if c["id"] == "PI-INC-02")
    llm, second = quoting_pair(oracle, verifier=verifier)
    nj = NoteJudge(None, llm, "judge", verifier=second)  # type: ignore[arg-type]
    r = nj.judge_excerpts(crit["text"], crit["note_question"], RUN, shown)
    assert (r.predicate, r.reason) == expected
    assert nj.judge_excerpts(crit["text"], crit["note_question"], RUN, hidden).predicate == "unknown"
    assert oracle.asked[0] == ("gout flare", crit["text"], [shown[0]["text"]])
    assert oracle.full("gout flare", [*hidden, *shown]) == "pass" and oracle.full(crit["text"], hidden) == "unknown"


# ------------------------------------------------------------------------------------------------ the opt-out
def _texts(name: str, data: bytes) -> str:
    """What a reader of the file can see: the members of a workbook or a document (zip), a PDF's text, else the
    bytes themselves."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
    if data[:5] == b"%PDF-":
        from pypdf import PdfReader

        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8", "replace")


def _marks(key: str) -> tuple[str, ...]:
    return PID[key], PID[key][:12], PATIENTS[key]["number"]


BYTES_PATHS = sorted({n.split(".")[0] if n.startswith("case.") else n for n in (
    "screen.cascade", "microbatch.recheck", "screen.v1", "screen.other", "microbatch.new", "nav", "case.x", "feas",
    "screen.single", "nav.single", "microbatch.after_single", "screen.pair_disagrees", "screen.before_amendment",
    "microbatch.amended", "screen.amended")})  # fmt: skip


@pytest.mark.parametrize("path", [*BYTES_PATHS, "pool", "mail"])
def test_an_opted_out_patient_is_in_no_published_bytes(world: World, path: str) -> None:
    """The register's patient (OPT) is in no file a path published (lists, workbooks, drafts, evidence files, the
    stored candidate lists), in no pool row and in no mail (subject, body, the job mails of every path)."""
    found: list[str] = []
    if path == "pool":
        found += [f"pool {rid}" for rid, pids in world.pools.items() if PID["OPT"] in pids]
    elif path == "mail":
        found += [m.splitlines()[0] for m in world.mails if any(mark in m for mark in _marks("OPT"))]
    else:
        jobs = {n: j for n, j in world.jobs.items() if n == path or n.startswith(f"{path}.")}
        assert jobs, path
        for n, j in jobs.items():
            for fn, data in j.outputs.items():
                text = _texts(fn, data)
                found += [f"{n}: {fn}" for mark in _marks("OPT") if mark in text or mark in fn]
    assert not found, found
    # control: the scan reads what it is given (ELIG is in the reference's files, the pool and a mail)
    if path == "screen.cascade":
        assert PID["ELIG"] in "".join(_texts(fn, d) for fn, d in world.jobs[path].outputs.items())
    if path == "pool":
        assert PID["ELIG"] in world.pools["PIX"]


# ------------------------------------------------------------------------------------------------ outside the box
def test_the_console_reads_the_register_as_the_jobs_do(tmp_path: Path) -> None:
    """The console's list is the stored candidate list filtered by the register (``console/home.py`` week bundle,
    ``screening_log.py``, the team and EDC pages): the console process is not driven here (it needs the console app
    and a session), but the read it makes is ``Helpers.gone()``. A chart number that opted out and was then merged
    into another chart: the jobs keep the surviving patient off every list, and so does the console's read. Before
    T-708 (D-477, review M3) the pages read ``OptOutRegister.active()``, which leaves the survivor out."""
    from adapter.pidmap import PidMap
    from console.home import Helpers
    from tb_common.optout import OptOutRegister, opted_out

    pm = PidMap(tmp_path / "pid_map.key")
    old, survivor = pm.merge(KEY, "20000001", "20000002", "duplicate chart", "TICKET-1")
    pm.close()
    reg = OptOutRegister()
    reg.add(old, "paper", "synthetic opt-out", "crc1@hospa.test", "2026-10-01T09:00:00+08:00")
    assert survivor in opted_out()  # the jobs' read (control)
    assert survivor not in reg.active()  # the read the pages made before: the survivor was shown
    blank: Any = None
    h = Helpers(need=blank, page=blank, problem=blank, csrf_ok=blank, actor=blank, bk=blank, au=blank, store=blank,
                users=blank, optout=reg)  # fmt: skip
    console = h.gone()  # the one register read of the console's pages
    reg.close()
    assert survivor in console and old in console
    pages = Path(__file__).resolve().parents[2] / "services" / "console"
    stray = [p.name for p in sorted(pages.glob("*.py")) if "optout.active()" in p.read_text(encoding="utf-8")]
    assert not stray, f"a console page reads the register without merged charts: {stray}"


def test_a_status_does_not_depend_on_how_many_patients_are_in_the_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEEP's five top chunks are notes that say nothing of a flare; another note of the window holds the flare.
    Evaluated alone and with one more candidate, on the same snapshot with the same pair, the status must be the
    same. Before T-710 (D-479, review M5) the full record was read only for an unknown first answer in a run of at
    most 100 candidates, so the same patient was ``high`` alone and ``review`` in a large run; now there is one
    read of the window, the same for a run of any size."""
    from orchestrator.scenarios import evaluate
    from orchestrator.scenarios.evaluate import NoteJudge, SqlEngine, evaluate_patients

    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    assert not hasattr(evaluate, "FULL_RECORD_MAX_CANDIDATES")  # the limit is gone, not raised
    rs = Ruleset.load(world.rulesets_dir / "PIX")
    lake = LakeLocal(world.lake_dir, HashEmbedder(), TZ)

    def tier(pids: list[str]) -> str:
        llm, verifier = quoting_pair(QuotingOracle(ORACLE))
        nj = NoteJudge(lake, llm, "judge", verifier=verifier)  # type: ignore[arg-type]
        res = evaluate_patients(rs, pids, RUN, SqlEngine(lake, SNAP), nj, 0.75)
        return res[PID["DEEP"]].tier

    alone = tier([PID["DEEP"]])
    assert alone == "high"  # control: the full record was read
    assert tier([PID["DEEP"], PID["ELIG"]]) == alone


# H-81: the shared build, without the world. Several processes at once build one folder; a failed build is raised
# again with its own text, never rebuilt into a folder an earlier attempt left behind.
def _slow_build(tmp: Path) -> dict[str, int]:
    (tmp / "sec").mkdir()  # what the world's build makes first
    (tmp.parent / f"built-{os.getpid()}").touch()
    time.sleep(0.3)
    return {"pid": os.getpid()}


def _build_in_child(root: str, out: Any) -> None:
    out.put(shared_build(Path(root), _slow_build)["pid"])


def test_many_workers_at_once_build_one_folder(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")  # a fresh interpreter per worker, as xdist starts them
    out = ctx.Queue()
    procs = [ctx.Process(target=_build_in_child, args=(str(tmp_path / "shared"), out)) for _ in range(6)]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(60)
    assert [pr.exitcode for pr in procs] == [0] * 6
    pids = {out.get(timeout=5) for _ in procs}
    assert len(pids) == 1  # every worker reads the one build
    assert len(list((tmp_path / "shared").glob("built-*"))) == 1
    assert len(list((tmp_path / "shared").glob("build-*"))) == 1


def test_a_failed_build_is_raised_again_not_built_again(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fails(tmp: Path) -> None:
        calls.append(tmp)
        (tmp / "sec").mkdir()
        raise AssertionError("font NotoSansTC-Regular.ttf not found")

    with pytest.raises(AssertionError, match="font NotoSansTC"):
        shared_build(tmp_path, fails)
    for _ in range(2):  # the worker comes back to the module (worksteal): the first error, not FileExistsError
        with pytest.raises(RuntimeError, match="failed to build, not built again: AssertionError: font NotoSansTC"):
            shared_build(tmp_path, fails)
    assert len(calls) == 1
