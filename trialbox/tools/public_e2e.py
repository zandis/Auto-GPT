"""End-to-end run of the whole platform on the public-data site (``tools.public_site``): real notes, stub model.

    python -m tools.public_e2e --dir /tmp/tb-public --lang en          # run once, print the stage table
    python -m tools.public_e2e --dir /tmp/tb-public --serve            # then keep the console up for a browser walk

The same path as ``tools.e2e_simple`` (criteria -> report -> approval -> list -> marks -> mail -> REDCap -> log),
driven through the console's own routes, on two test protocols written for the public notes (``eval/public_site``):
the PUB-ONC trial (adults with a malignant tumour, ECOG 0-1 from the notes; pregnancy, active TB, ILD out) and the
PUB-CA cancer registry. Every count the box reports is recounted from the landing CSVs; every mail is searched for
chart numbers. The real-vs-derived statement is ``<dir>/hospital/PROVENANCE.md``.
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import os
import re
import secrets
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402
from tools import list_demo as ld  # noqa: E402
from tools import public_site as ps  # noqa: E402

TRIAL, COHORT = "PUB-ONC", "PUB-CA"
# D-120: the console says the records are public data, and its request menu lists this site's own studies only
SITE_ENV = {"TB_CONSOLE_DATA_SOURCE": "public", "TB_CONSOLE_STUDIES": f"{TRIAL},{COHORT}"}
# D-120: the site's short labels for the trial's criteria, given at approval (the study's own words stay beside them)
SITE_LABELS = {
    "ja": {
        "PUB-ONC-INC-01": "18歳以上",
        "PUB-ONC-INC-02": "悪性腫瘍",
        "PUB-ONC-INC-03": "ECOG 0〜1",
        "PUB-ONC-EXC-01": "妊娠中・授乳中",
        "PUB-ONC-EXC-02": "活動性結核",
        "PUB-ONC-EXC-03": "間質性肺疾患・肺臓炎",
        "PUB-ONC-EXC-04": "30日以内の他の治験参加",
    },
    "zh-TW": {
        "PUB-ONC-INC-01": "18歲以上",
        "PUB-ONC-INC-02": "惡性腫瘤",
        "PUB-ONC-INC-03": "ECOG 0–1",
        "PUB-ONC-EXC-01": "懷孕或哺乳中",
        "PUB-ONC-EXC-02": "活動性結核",
        "PUB-ONC-EXC-03": "間質性肺病或肺炎",
        "PUB-ONC-EXC-04": "30天內參加其他介入性試驗",
    },
}
PROFILES = ROOT / "eval" / "public_site" / "profiles"
CASSETTES = ROOT / "services" / "llm_stub" / "cassettes" / "ir_extract"
SIM_URL = "inproc://rc-sim"
TERM_DIR = ROOT / "services" / "criteria_compiler" / "terminology"
# curated demo rows + the full ICD-10-CM list the prefix groupers expand over (D-122)
TERMINOLOGY = [TERM_DIR / f"{name}.parquet" for name in ("icd10cm_tw", "icd10cm_full")]
MALIGNANT = ("C0", "C1", "C2", "C3", "C40", "C41", "C43", "C45", "C46", "C47", "C48", "C49", "C5", "C6", "C7", "C8")


@dataclass
class Stage:
    name: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    seconds: float = 0.0

    def check(self, what: str, ok: Any, detail: Any = "") -> bool:
        self.checks.append((what, bool(ok), str(detail)[:300]))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.checks)


def criteria(ruleset: str) -> str:
    """The pasted text: the test protocol's criteria under English headings (the cassette holds the same lines)."""
    crit = json.loads((CASSETTES / f"{ruleset}.json").read_text(encoding="utf-8"))["criteria"]
    inc = [c["text"] for c in crit if c["kind"] == "inclusion"]
    exc = [c["text"] for c in crit if c["kind"] == "exclusion"]
    lines = ["Inclusion criteria", *[f"{i}. {t}" for i, t in enumerate(inc, 1)]]
    if exc:
        lines += ["", "Exclusion criteria", *[f"{i}. {t}" for i, t in enumerate(exc, 1)]]
    return "\n".join(lines) + "\n"


def build(work: Path, llm: Any = None, verifier: Any = None) -> tuple[Any, Any, Path, dict[str, Any]]:
    """Public site -> ingest -> in-process box (stub model unless ``llm`` is given)."""
    from orchestrator import app as orch_app

    from tests.inproc_box import ingest_site, make_box
    from tools.role_demo import orch_client

    hospital = work / "hospital"
    site = ps.build(hospital)
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(fd.KEY)
    shutil.rmtree(work / "lake", ignore_errors=True)
    rep = ingest_site(hospital, work / "lake", sec, (ps.REF - timedelta(days=1)).isoformat())
    site["ingest"] = {"passed": rep.passed, "counts": rep.counts, "missing_required": rep.missing_required}
    shutil.rmtree(work / "box", ignore_errors=True)
    box = make_box(work / "box", work / "lake", sec, ps.REF + timedelta(days=1), extra_profiles=PROFILES)
    if llm is not None:
        site["canary"] = attach_models(box, llm, verifier)
    orch_app._orch = box.orch
    return box, orch_client(orch_app.app), work / "box" / "repo", site


def attach_models(box: Any, llm: Any, verifier: Any) -> dict[str, Any] | None:
    """Real-model runs: the judge (and the verifier) read the notes; the compiler stays on the stub. Returns the
    pair canary's status when the gate is on (D-117: as at box start, the canary runs first and gates exclusions)."""
    for c in (llm, verifier):
        if c is not None:
            c.audit = box.orch.audit  # every real model call is an llm.call audit record, as in the box
    box.orch.services.llm = llm
    box.orch.services.verifier = verifier
    from orchestrator import canary_gate

    if not canary_gate.gate_on():
        return None
    canary_gate.run_canary(box.orch)
    status: dict[str, Any] = canary_gate.status()
    return status


def _rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _age(birth: str, ref: date) -> int | None:
    if not birth:
        return None
    b = date.fromisoformat(birth)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def _json_out(box: Any, job: Any, prefix: str, suffix: str = ".json") -> dict[str, Any]:
    out = next(o for o in job.outputs or [] if o.filename.startswith(prefix) and o.filename.endswith(suffix))
    data: dict[str, Any] = json.loads(box.store.get(out.minio_key))
    return data


def _done(box: Any, type_: str, ruleset: str) -> list[Any]:
    return [j for j in box.orch.db.find(type_=type_, ruleset=ruleset) if j.state == "done"]


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def real_models(judge_url: str, verifier_url: str, key: str) -> tuple[Any, Any]:
    """LlmClients for the GPU pair behind the VM's nginx (``/judge/v1``, ``/verifier/v1``), bearer key."""
    import httpx
    from tb_common.llm import LlmClient

    out = []
    for url, name in ((judge_url, "local/gemma-4-26b-a4b-nvfp4"), (verifier_url, "local/qwen3.5-9b-awq")):
        c = LlmClient(url, name, timeout=600.0)
        c.http = httpx.Client(timeout=600.0, headers={"Authorization": f"Bearer {key}"})
        out.append(c)
    return out[0], out[1]


def direct_swap(judge_url: str, verifier_url: str, key: str, llm: Any = None, verifier: Any = None) -> Any:
    """The gateway's own swap (:class:`gateway.swap.ModelSwap`, hold and release) driven straight at the VM's two
    servers, for a run with no tb-gateway in between: the orchestrator's :func:`orchestrator.twophase.two_phase`
    then holds the card, swaps judge -> verifier and releases it exactly as on the box (D-116). Every model call of
    ``llm`` / ``verifier`` first does what the gateway does on its request path: wake the model on demand when no
    run holds the card, refuse the call (``model_asleep``) when one does. (A call sent to a sleeping vLLM server
    directly waits for ever; through the gateway it never reaches one.)"""
    from gateway.swap import ModelSwap, SwapError
    from orchestrator import twophase
    from tb_common.llm import LlmError

    sw = ModelSwap({"serving": judge_url, "verifier": verifier_url}, headers={"Authorization": f"Bearer {key}"})

    class Direct:
        def use(self, endpoint: str) -> None:
            try:
                sw.activate(endpoint, hold=True)
            except SwapError as exc:
                raise LlmError(f"model swap to {endpoint} failed: {exc}") from exc

        def release(self) -> None:
            sw.release()  # the next call wakes what it needs (guarded below), as the gateway does

    for endpoint, client in (("serving", llm), ("verifier", verifier)):
        if client is None:
            continue
        inner = client.chat_json

        def guarded(*a: Any, _inner: Any = inner, _ep: str = endpoint, **kw: Any) -> Any:
            if not sw.ensure(_ep):
                raise LlmError(f"{_ep} is asleep (one-GPU swap); activate it first")
            return _inner(*a, **kw)

        client.chat_json = guarded
    os.environ["TB_MODEL_SWAP"] = "sleep"
    twophase.GatewaySwap.from_env = staticmethod(Direct)  # type: ignore[method-assign,assignment]
    return sw


def run(work: Path, password: str, lang: str = "en", llm: Any = None, verifier: Any = None) -> dict[str, Any]:
    from console import notify
    from console.i18n import CATALOGUES
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook
    from rc_sim.app import create_app as sim_app
    from rc_sim.app import load_projects, register_inproc
    from tb_common.audit import verify

    stages: list[Stage] = []
    t0 = time.perf_counter()
    box, client, repo, site = build(work, llm, verifier)
    clock = ld.Clock(box.today[0])
    # D-178: the operations screens run their actions in this process (no host runner in the in-process box)
    ops_env = {"TB_OPS_DIR": str(work / "ops"), "TB_OPS_RUNNER": "inline", "TB_OPS_DEPLOY": str(work / "ops-deploy")}
    shutil.rmtree(work / "ops", ignore_errors=True)
    app = ld.console(work, box, client, repo, password, clock, extra_env={**SITE_ENV, **ops_env})
    h = app.state.helpers
    cat = CATALOGUES[lang]
    hosp = work / "hospital"
    patients = _rows(hosp / "patient.csv")
    mrns = {p["mrn"] for p in patients}
    dx = _rows(hosp / "diagnosis.csv")
    lake = box.orch.services.lake

    def q(sql: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = lake.query(sql).to_pylist()
        return rows

    # ------------------------------------------------------------------ 0 data in
    s = Stage("0 public data in")
    t = time.perf_counter()
    summ = site["summary"]
    s.check(
        "every source document is one patient (SIGIR 53, MedTxt-CR 123, MedTxt-RR 92)",
        summ["by_source"] == {"SIGIR": 53, "MedTxt-CR": 123, "MedTxt-RR": 92},
        summ["by_source"],
    )
    s.check("ingest passed", site["ingest"]["passed"], site["ingest"])
    got = {
        k: int(q(f"SELECT count(*) AS n FROM {tb}")[0]["n"])
        for k, tb in (("patient", "patient"), ("note", "document"), ("dx", "condition"))
    }
    want = {"patient": len(patients), "note": len(_rows(hosp / "note.csv")), "dx": len(dx)}
    s.check("lake counts = CSV counts (patients, notes, diagnoses)", got == want, f"lake {got} csv {want}")
    texts = {r["text"] for r in _rows(hosp / "note.csv")}
    lake_text = (
        {r["text"] for r in q("SELECT text FROM document")}
        if "text" in lake.query("SELECT * FROM document LIMIT 1").column_names
        else set()
    )
    s.check(
        "note text reaches the lake verbatim",
        not lake_text or len(texts & lake_text) == len(texts),
        len(texts & lake_text),
    )
    cols = {
        tb: set(lake.query(f"SELECT * FROM {tb} LIMIT 1").column_names)
        for tb in ("patient", "encounter", "document", "condition")
    }
    s.check("no chart number column in the lake", not any(c & {"mrn", "id_no", "phone"} for c in cols.values()), cols)
    pids = {r["pid"] for r in q("SELECT pid FROM patient")}
    s.check("lake keys are pseudonyms", not pids & mrns, len(pids & mrns))
    s.check(
        "missing birth dates reported, not invented",
        site["ingest"]["missing_required"].get("Patient.birthDate") == summ["age_missing"],
        site["ingest"]["missing_required"],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    crc = ld.sign_in(app, "crc", password, lang)
    pi = ld.sign_in(app, "pi", password, lang)
    admin = ld.sign_in(app, "admin", password, lang)

    # ------------------------------------------------------------------ 1 S2 paste -> S20 approval -> FEAS
    s = Stage("1 criteria, approval and feasibility")
    t = time.perf_counter()
    jobs = {}
    for rs in (COHORT, TRIAL):
        form = crc.get("/pilot/protocol")
        r = crc.post("/pilot/protocol", data={"csrf": fd._csrf(form.text), "ruleset": rs, "criteria": criteria(rs)})
        job = box.orch.db.get(r.url.path.rsplit("/", 1)[-1])
        s.check(
            f"S2 paste {rs} -> draft waiting for approval",
            r.status_code == 200 and job is not None and job.state == "awaiting_approval",
            (r.status_code, job and job.state),
        )
        jobs[rs] = job
    s20 = crc.get(f"/pilot/jobs/{jobs[TRIAL].job_id}/approval")
    s.check("S20 says who ticks and approves; the coordinator has no tick", 'data-testid="s20-who"' in s20.text
            and 'data-testid="tick-btn-' not in s20.text, "")  # fmt: skip
    # D-146 (review J-27): the investigator ticks a criterion's codes, as only the investigator approves
    p20 = pi.get(f"/pilot/jobs/{jobs[TRIAL].job_id}/approval")
    first = re.search(r'data-testid="tick-btn-([A-Z0-9-]+)"', p20.text)
    r = pi.post(
        f"/pilot/jobs/{jobs[TRIAL].job_id}/approval/tick",
        data={"csrf": fd._csrf(p20.text), "crit": first.group(1) if first else "-"},
    )
    s.check("investigator ticks a criterion's codes on S20", bool(first) and r.status_code == 200, r.status_code)
    r = crc.post(f"/pilot/jobs/{jobs[TRIAL].job_id}/approve", data={"csrf": fd._csrf(s20.text)}, follow_redirects=False)
    s.check("coordinator's approve refused (403)", r.status_code == 403, r.status_code)
    # D-120: at approval the coordinator gives each criterion a short label in the site's languages; the pages show
    # it with the study's own words beside it
    saved = 0
    for lg, words in SITE_LABELS.items():
        page = crc.get(f"/pilot/jobs/{jobs[TRIAL].job_id}/approval")
        crc.post("/lang", data={"csrf": fd._csrf(page.text), "lang": lg, "back": "/home"})
        for cid, text in words.items():
            r = crc.post(
                f"/pilot/jobs/{jobs[TRIAL].job_id}/approval/label",
                data={"csrf": fd._csrf(page.text), "crit": cid, "text": text},
                follow_redirects=False,
            )
            saved += r.status_code == 303
    crc.post("/lang", data={"csrf": fd._csrf(page.text), "lang": lang, "back": "/home"})
    n_labels = sum(len(w) for w in SITE_LABELS.values())
    s.check("S20: criterion labels in Japanese and Chinese saved", saved == n_labels, f"{saved}/{n_labels}")
    for rs, job in jobs.items():
        page = pi.get(f"/pilot/jobs/{job.job_id}/approval")
        for cid in re.findall(r'data-testid="open-([A-Z0-9-]+)"', page.text):
            page = pi.get(f"/pilot/jobs/{job.job_id}/approval?open={cid}")
        r = pi.post(
            f"/pilot/jobs/{job.job_id}/approve",
            data={"csrf": fd._csrf(page.text), "confirm": "yes"},
            follow_redirects=False,
        )
        after = box.orch.db.get(job.job_id)
        s.check(
            f"investigator approves {rs}; FEAS finishes",
            r.status_code == 303 and after is not None and after.state == "done",
            (r.status_code, after and after.state, after and after.error),
        )
    fj = _done(box, "FEAS", TRIAL)[0]
    names = sorted(o.filename for o in fj.outputs or [])
    s.check(
        "FEAS PDF, XLSX and JSON", all(any(n.endswith(x) for n in names) for x in (".pdf", ".xlsx", ".json")), names
    )
    rep = _json_out(box, fj, "feasibility_")
    raw = _json_out(box, fj, "feasibility_", ".raw.json")
    ref = date.fromisoformat(rep["snapshot"])
    adults = {p["mrn"] for p in patients if (a := _age(p["birth_date"], ref)) is not None and a >= 18}
    import pyarrow.parquet as pq

    known = {r["code"] for t in TERMINOLOGY for r in pq.read_table(t, columns=["code"]).to_pylist()}
    vs = {c for c in known if c.startswith(MALIGNANT)}  # the "malignancy" grouper expands over the terminology
    # clinical truth, independent of the terminology: any code in the malignancy families (D-113)
    cancer = {d["mrn"] for d in dx if d["icd10"].startswith(MALIGNANT)}
    term = sorted({d["icd10"] for d in dx if d["icd10"].startswith(MALIGNANT) and d["icd10"] not in vs})
    inc = {k: v for k, v in raw["remaining"].items()}
    s.check("start = every patient", raw["start_n"] == len(patients), raw["start_n"])
    s.check(
        "age >= 18 = recount from patient.csv",
        inc.get(f"{TRIAL}-INC-01") == len(adults),
        (inc.get(f"{TRIAL}-INC-01"), len(adults)),
    )
    s.check(
        "malignancy = every adult with a cancer code in diagnosis.csv (recount by ICD-10 family, not by the list)",
        inc.get(f"{TRIAL}-INC-02") == len(adults & cancer),
        (inc.get(f"{TRIAL}-INC-02"), len(adults & cancer)),
    )
    listed = {d["mrn"] for d in dx if d["icd10"] in vs}
    missed = cancer - listed  # patients whose only cancer codes are outside the list (kept as unknown, D-113)
    s.check(
        "every cancer code in the data is in the malignancy value set",
        term == [] and not missed,
        f"not listed: {term}, {len(missed)} patients",
    )
    rem = [row["remaining"] for row in rep["funnel"]]
    s.check("funnel never grows", all(a >= b for a, b in itertools.pairwise(rem)), rem)
    s.check("FEAS ran without a model", (rep.get("provenance") or {}).get("models") == [], rep.get("provenance"))
    s3 = crc.get(f"/studies/{TRIAL}/feasibility")
    s.check("S3 feasibility page", s3.status_code == 200 and "funnel" in s3.text.lower(), s3.status_code)
    r = crc.post(f"/studies/{TRIAL}/feasibility/refresh", data={"csrf": fd._csrf(s3.text)}, follow_redirects=False)
    s.check(
        "S3 Refresh re-runs FEAS",
        r.status_code in (200, 303) and len(box.orch.db.find(type_="FEAS", ruleset=TRIAL)) >= 2,
        (r.status_code, len(box.orch.db.find(type_="FEAS", ruleset=TRIAL))),
    )
    out: dict[str, Any] = {
        "feas": {"start": raw["start_n"], "remaining": raw["remaining"], "funnel": rep["funnel"]},
        "terminology_missed": {"codes": term, "patients": len(missed)},
    }
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 2 SCREEN on real notes
    s = Stage("2 screening (patient list) on real notes")
    t = time.perf_counter()
    screen_secs: dict[str, float] = {}
    for rs, pract in ((TRIAL, ""), (COHORT, "P12345,P23456")):
        t_req = time.perf_counter()
        form = crc.get(f"/pilot/request?ruleset={rs}")
        r = crc.post(
            "/pilot/request",
            data={"csrf": fd._csrf(form.text), "kind": "SCREEN", "ruleset": rs, "pract": pract},
            follow_redirects=False,
        )
        sj = box.orch.db.get(r.headers.get("location", "/").rsplit("/", 1)[-1]) if r.status_code == 303 else None
        screen_secs[rs] = round(time.perf_counter() - t_req, 1)
        s.check(
            f"SCREEN {rs} done",
            sj is not None and sj.state == "done",
            (r.status_code, sj and sj.state, sj and sj.error),
        )
    sj = _done(box, "SCREEN", TRIAL)[0]
    scr = _json_out(box, sj, "screen_")
    fun = dict((k, v) for k, v in scr["funnel"])
    s.check("screen funnel S0 >= S1 >= S3 >= S4", fun["S0"] >= fun["S1"] >= fun["S3"] >= fun["S4"], fun)
    s.check("listed = high + review", scr["listed"] == scr["tiers"]["high"] + scr["tiers"]["review"], scr["tiers"])
    want_block = "both_agree" if verifier is not None else "never"
    s.check(
        "note-based exclusion only when two models agree",
        scr["judging"]["note_block"] == want_block and (verifier is not None or not scr["judging"]["may_block"]),
        scr["judging"],
    )

    # P-04 (D-143): every patient the run excluded is on "Excluded patients and why", with criterion and source
    ex = pi.get(f"/studies/{TRIAL}/excluded").text
    m = re.search(r'data-testid="ex-run">([^<]*)<', ex)
    s.check("the excluded patients and why: every excluded patient, with criterion and source",
            m is not None and str(scr["tiers"]["excluded"]) in m.group(1) and 'data-testid="ex-source-' in ex,
            m.group(1) if m else _text(ex)[-200:])  # fmt: skip
    out["screen"] = {
        "funnel": fun,
        "tiers": scr["tiers"],
        "listed": scr["listed"],
        "judging": scr["judging"],
        "request_seconds": screen_secs,
        "stage_seconds": round(time.perf_counter() - t, 1),
    }
    cohort = crc.get(f"/studies/{COHORT}/cohort")
    members = len(re.findall(r'data-testid="member-', cohort.text))
    s.check(
        "cohort list PUB-CA has members, no contact step",
        cohort.status_code == 200 and members > 0 and 'data-testid="mark-' not in cohort.text,
        members,
    )
    out["cohort_members"] = members
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 3 list, S5, marks (replace, withdraw), outcomes
    s = Stage("3 list, S5 and marks")
    t = time.perf_counter()
    week = h.week_bundle(None, TRIAL)
    rows = week["rows"]
    s.check("the list has at least three patients", len(rows) >= 3, len(rows))
    days = sorted(d for d in notify.clinic_days(rows, ld.PI_PRACTITIONER) if d.weekday() < 5)
    day = days[0] if days else clock.now.date()
    clock.set(day)
    picks = rows[:3]
    lst = pi.get(f"/studies/{TRIAL}/week?list=all")
    s.check("PI list page", lst.status_code == 200 and all(p["pid"][:8] in lst.text for p in picks), lst.status_code)
    marks = [
        ("approach", {}),
        ("need_info", {"note": "ECOG not recorded"}),
        ("not_now", {"recheck": (day + timedelta(days=28)).isoformat()}),
    ]
    for row, (mark, extra) in zip(picks, marks, strict=False):
        page = pi.get(f"/studies/{TRIAL}/week?list=all&pid={row['pid']}")
        r = pi.post(
            f"/studies/{TRIAL}/patients/{row['pid']}/mark",
            data={"csrf": fd._csrf(page.text), "mark": mark, "back": "list:all", **extra},
            follow_redirects=False,
        )
        s.check(f"mark {mark}", r.status_code == 303, r.status_code)
    if len(picks) >= 3:
        third = picks[2]["pid"]
        page = pi.get(f"/studies/{TRIAL}/week?list=all&pid={third}")
        r = pi.post(
            f"/studies/{TRIAL}/patients/{third}/mark",
            data={"csrf": fd._csrf(page.text), "mark": "approach", "back": "list:all"},
            follow_redirects=False,
        )
        hist = [m.mark for m in h.store.mark_history(TRIAL, third)]
        s.check(
            "replace a mark: history keeps both", r.status_code == 303 and hist[-2:] == ["not_now", "approach"], hist
        )
        r = pi.post(
            f"/studies/{TRIAL}/patients/{third}/mark",
            data={"csrf": fd._csrf(page.text), "mark": "withdraw", "back": "list:all"},
            follow_redirects=False,
        )
        hist = [m.mark for m in h.store.mark_history(TRIAL, third)]
        s.check("withdraw a mark", r.status_code == 303, (r.status_code, hist, _text(r.text)[-200:]))
        out["withdraw_hist"] = hist
    approached = picks[0]["pid"] if picks else ""
    p5 = pi.get(f"/studies/{TRIAL}/patients/{approached}")
    s.check("S5 patient page", p5.status_code == 200, p5.status_code)
    page = crc.get(f"/studies/{TRIAL}/patients/{approached}")
    r = crc.post(
        f"/studies/{TRIAL}/patients/{approached}/outcome",
        data={"csrf": fd._csrf(page.text), "outcome": "not_reached", "back": "patient"},
        follow_redirects=False,
    )
    s.check("coordinator records a contact outcome", r.status_code == 303, r.status_code)
    no = h.store.screening_no(TRIAL, approached)
    s.check("Approach gives a screening number", bool(no) and no.startswith(TRIAL), no)
    log = crc.get(f"/studies/{TRIAL}/screening-log")
    s.check("screening log lists the approached patient", log.status_code == 200 and no in log.text, log.status_code)
    x = crc.get(f"/studies/{TRIAL}/screening-log.xlsx")
    wb = load_workbook(io.BytesIO(x.content)) if x.status_code == 200 else None
    s.check(
        "screening log XLSX opens",
        wb is not None and any(no in str(c.value) for ws in wb.worksheets for r_ in ws.iter_rows() for c in r_),
        x.status_code,
    )
    out["picks"] = [p["pid"][:8] for p in picks]
    out["screening_no"] = no
    # TB-PLAN-04 step 4 (D-129): the built-in forms, so the walk can open Entry and History and save on the phone
    page = crc.get(f"/studies/{TRIAL}/forms")
    r = crc.post(f"/studies/{TRIAL}/forms/builtin", data={"csrf": fd._csrf(page.text)})
    s.check("the coordinator adds the built-in forms", 'data-testid="dc-builtin-added"' in r.text, r.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 4 mail
    s = Stage("4 N1 / N2 mail")
    t = time.perf_counter()
    before = len(box.sent)
    notify.send_all(h, day)
    mails = box.sent[before:]
    s.check("N1 and N2 sent", len(mails) >= 2, [m.subject for m in mails])
    body = "\n".join(m.text() for m in mails)
    leaked = sorted(m for m in mrns if re.search(rf"(?<!\d){m}(?!\d)", body))
    s.check("mail carries no chart number", not leaked, leaked[:3])
    numbered = [(p[:8], n) for p, n in h.store.screening_nos(TRIAL).items() if f"({n})" in body]
    s.check("mail shows the screening number beside the pseudonym (D-136)",
            bool(numbered) and all(f"{p} ({n})" in body for p, n in numbered), numbered[:3])  # fmt: skip
    out["mails"] = [{"to": m.to, "subject": m.subject} for m in mails]
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 5 REDCap (S36, S21, read-back)
    s = Stage("5 REDCap simulator read-back")
    t = time.perf_counter()
    sim = sim_app()
    register_inproc(sim)
    token = next(tk for tk, p in load_projects().items() if p["project"]["project_id"] == 101)
    page = admin.get("/admin/redcap")
    admin.post(
        "/admin/redcap", data={"csrf": fd._csrf(page.text), "token_ref": "pubonc", "url": SIM_URL, "token": token}
    )
    r = admin.post("/admin/redcap/pubonc/test", data={"csrf": fd._csrf(page.text)})
    s.check(
        "S36 Test connection (version shown, token never shown)",
        r.status_code == 200 and "16.0.10" in r.text and token not in r.text,
        r.status_code,
    )
    page = crc.get(f"/studies/{TRIAL}/setup")
    form = {
        **{
            "token_ref": "pubonc",
            "project_id": "101",
            "link_field": "tb_screening_no",
            "consent_field": "consent_date",
            "enrol_field": "enrolled",
            "enrol_value": "1",
            "screenfail_field": "sf_reason",
            "screenfail_choice_map": "1=inclusion, 2=exclusion, 3=consent_withdrawn, 9=other",
            "subject_no_field": "subject_no",
        }
    }
    r = crc.post(f"/studies/{TRIAL}/setup/redcap", data={"csrf": fd._csrf(page.text), **form})
    s.check(
        "S21 project link checked against the data dictionary", 'data-testid="link-on"' in r.text, _text(r.text)[-300:]
    )
    sc = TestClient(sim)
    sc.post(
        "/sim/records",
        json={
            "project_id": 101,
            "records": [{"record_id": "3", "tb_screening_no": no, "consent_date": day.isoformat()}],
        },
    )
    log = crc.get(f"/studies/{TRIAL}/screening-log")
    r = crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(log.text), "back": "log"})
    from tools.rc_demo import status_of

    s.check(
        "Run now: consented", status_of(r.text, no).startswith(cat["registry.status.consented"]), status_of(r.text, no)
    )
    sc.post(
        "/sim/records",
        json={"project_id": 101, "records": [{"record_id": "3", "enrolled": "1", "subject_no": "S-0003"}]},
    )
    r = crc.post(f"/studies/{TRIAL}/redcap-read", data={"csrf": fd._csrf(r.text), "back": "log"})
    s.check(
        "Run now: enrolled, subject number shown",
        status_of(r.text, no).startswith(cat["registry.status.enrolled"]) and "S-0003" in r.text,
        status_of(r.text, no),
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 5b the trial lifecycle (TB-PLAN-04 step 5)
    s = Stage("5b trial lifecycle (D-134)")
    t = time.perf_counter()
    from console.timefmt import local_today, site_zone

    today = local_today(h.clock(), site_zone(h.bk))
    have = set(h.store.screening_nos(TRIAL))
    # the last listed patient without a number (the walk's own patient, the first one not marked, stays untouched)
    life_pid = next(r["pid"] for r in reversed(h.week_bundle(None, TRIAL)["rows"]) if r["pid"] not in have)
    life_no = h.store.assign_screening_no(TRIAL, life_pid, h.settings_of(TRIAL), h.clock().isoformat())
    page = crc.get(f"/studies/{TRIAL}/schedule")
    r = crc.post(f"/studies/{TRIAL}/schedule", data={
        "csrf": fd._csrf(page.text), "action": "save", "visit": ["v1", "v2"], "label": ["", ""], "day": ["7", "28"],
        "before": ["2", "3"], "after": ["2", "3"], "anchor": ["enrolment", "enrolment"]})  # fmt: skip
    s.check("the visit schedule is saved", 'data-testid="schedule-saved"' in r.text, r.status_code)
    page = crc.get(f"/studies/{TRIAL}/subjects")
    s.check("both screening numbers are participants", life_no in page.text and no in page.text, page.status_code)
    csrf = fd._csrf(page.text)
    enrol = today - timedelta(days=7)  # v1 is due today
    crc.post(
        f"/studies/{TRIAL}/subjects/{life_no}/step",
        data={"csrf": csrf, "to": "approached", "on_day": (enrol - timedelta(days=2)).isoformat()},
    )

    def save(form: str, values: dict[str, str], event: str = "") -> Any:
        data = {"csrf": csrf, "record": life_no, "event": event, "form": form, "back": "subject",
                **{f"f_{k}": v for k, v in values.items()}}  # fmt: skip
        return crc.post(f"/studies/{TRIAL}/entry", data=data)

    save("tb_consent", {"ic_date": (enrol - timedelta(days=1)).isoformat(), "ic_version": "v1", "ic_copy": "1"})
    r = save("tb_enrolment", {"en_date": enrol.isoformat(), "en_eligible": "1"})
    s.check("enrolled through the forms", 'data-state="enrolled"' in r.text, r.status_code)
    r = save("tb_adverse_event", {"ae_term": "肺炎", "ae_onset": today.isoformat(), "ae_serious": "1",
                                  "ae_serious_why": "3", "ae_severity": "2", "ae_related": "9"}, "ae1")  # fmt: skip
    s.check("a serious AE on ae1", 'data-testid="ae-ae1"' in r.text, r.status_code)
    page = crc.get(f"/studies/{TRIAL}/visits").text
    s.check("today's visit is on the coordinator's list", f'data-testid="done-{life_no}-v1"' in page)
    s.check("the serious AE is on the investigator's home page", 'data-testid="sae-banner"' in pi.get("/week").text)
    rep = crc.get(f"/studies/{TRIAL}/enrolment")
    s.check("the enrolment report", rep.status_code == 200 and 'data-testid="report-states"' in rep.text)
    out["life_record"] = life_no
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 5c site set-up (TB-PLAN-04 step 5b, D-135)
    s = Stage("5c site set-up and data harmonization (D-135)")
    t = time.perf_counter()
    page = crc.get(f"/site/help?study={TRIAL}")
    r = crc.post("/site/practice", data={"csrf": fd._csrf(page.text), "action": "load", "study": TRIAL})
    s.check("the practice site loads in one tap", r.status_code == 200 and "ws=practice" in str(r.url), r.status_code)
    sq = f"ws=practice&study={TRIAL}"
    page = crc.get(f"/site?{sq}").text
    s.check("its readiness lists what is missing", 'data-testid="miss-proposed"' in page
            and 'data-testid="miss-unmapped"' in page and 'data-testid="miss-checks"' in page)  # fmt: skip
    facts = crc.get(f"/site/facts?{sq}").text
    ids = re.findall(r'data-testid="confirm-(\d+)"', facts)
    s.check("proposed facts beside their quotes", len(ids) >= 7 and facts.count('data-testid="quote-') >= 7, len(ids))
    r = crc.post(f"/site/facts/{ids[0]}", data={"csrf": fd._csrf(facts), "ws": "practice", "study": TRIAL,
                                                  "action": "confirm"})  # fmt: skip
    s.check("one tap confirms a fact", 'data-testid="fact-done"' in r.text, r.status_code)
    s.check("the hospital's own data is untouched by the practice site",
            'data-testid="miss-proposed"' not in crc.get(f"/site?study={TRIAL}").text)  # fmt: skip
    ask = crc.get("/ask", params={"q": "What do I do next?", "ws": "practice", "study": TRIAL})
    s.check("Ask TrialBox answers what to do next", 'data-kind="next"' in ask.text, ask.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 6 the other screens, every role
    s = Stage("6 other screens")
    t = time.perf_counter()
    for who, c in (("crc", crc), ("pi", pi), ("admin", admin)):
        for path in ("/home", "/week", "/account", "/help", "/notices/received", "/reports", "/settings/notices"):
            r = c.get(path)
            s.check(f"{who} {path}", r.status_code == 200, r.status_code)
    # D-120: a public-data site says so (not "synthetic"), lists its own studies only, and names its clinicians
    # from the records
    home = crc.get("/home").text
    s.check("banner says public data", 'data-testid="banner"' in home and "synthetic" not in home.lower(), "")
    menu = re.findall(r'<option value="([A-Z0-9-]+)"', crc.get("/pilot/request").text)
    s.check("request menu: this site's studies only", bool(menu) and set(menu) <= {TRIAL, COHORT}, menu)
    wk = pi.get(f"/studies/{TRIAL}/week?list=all").text
    s.check("clinician names from the records", "public-data site" in wk and "(synthetic)" not in wk, "")
    r = crc.get("/reports/research-office")
    s.check("research-office counts", r.status_code == 200, r.status_code)
    r = crc.get("/reports/research-office.xlsx")
    s.check("research-office XLSX", r.status_code == 200 and r.content[:2] == b"PK", r.status_code)
    for qtext in (TRIAL, approached[:8], "help"):
        r = crc.get(f"/cmd?q={qtext}")
        s.check(f"command field: {qtext!r}", r.status_code in (200, 303), r.status_code)
    for path in (
        "/admin",
        "/admin?tab=health",
        "/admin?tab=jobs",
        "/admin?tab=sources",
        "/ops/users",
        "/audit",
        "/jobs",
        *(f"/admin/ops?tab={tab}" for tab in ("overview", "backups", "update", "logs", "secrets", "network")),
    ):
        r = admin.get(path)
        s.check(f"admin {path}", r.status_code == 200, r.status_code)
    r = pi.get("/admin")
    s.check("investigator cannot open admin", r.status_code in (403, 303, 404), r.status_code)
    # D-178 (review J-09): the network sheet from the console, after a confirmation that names the consequence
    page = admin.get("/admin/ops?tab=network")
    r = admin.post("/admin/ops/network_sheet", data={"csrf": fd._csrf(page.text)})
    s.check("operations: the action asks first", 'data-testid="confirm-text"' in r.text, r.status_code)
    r = admin.post("/admin/ops/network_sheet", data={"csrf": fd._csrf(page.text), "confirm": "yes"})
    s.check("operations: network sheet written", 'data-state="done"' in r.text and "network-sheet." in r.text, "")
    s.check("operations: refused to the investigator", pi.get("/admin/ops").status_code == 403, "")
    r = crc.get("/no-such-page")
    s.check("404 page", r.status_code == 404, r.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 7 exports, CASE, consent, jobs Cancel / Retry
    s = Stage("7 exports, CASE, consent explainer, Cancel / Retry")
    t = time.perf_counter()
    for o in fj.outputs or []:
        if o.filename.endswith((".pdf", ".xlsx")):
            r = crc.get(f"/pilot/jobs/{fj.job_id}/files/{o.filename}")
            magic = b"%PDF" if o.filename.endswith(".pdf") else b"PK"
            s.check(
                f"download {o.filename.rsplit('.', 1)[-1].upper()} feasibility report",
                r.status_code == 200 and r.content.startswith(magic),
                r.status_code,
            )
    r = crc.get(f"/pilot/registry/{COHORT}/export.xlsx")
    s.check("cohort registry export XLSX", r.status_code == 200 and r.content[:2] == b"PK", r.status_code)
    # CASE: one real MedTxt case report, uploaded as the chart of its own patient
    case_p = next(p for p in site["patients"] if p["source"] == "MedTxt-CR" and p["dx"] and p["age"])
    note = next(n for n in _rows(hosp / "note.csv") if n["mrn"] == case_p["mrn"])
    form = crc.get("/pilot/case")
    r = crc.post(
        "/pilot/case",
        data={"csrf": fd._csrf(form.text), "ruleset": TRIAL, "mrn": case_p["mrn"], "lang": lang},
        files={"charts": ("case.txt", note["text"].encode("utf-8"), "text/plain")},
        follow_redirects=False,
    )
    cj = box.orch.db.get(r.headers.get("location", "/").rsplit("/", 1)[-1]) if r.status_code == 303 else None
    s.check(
        "CASE on a real case report finishes",
        cj is not None and cj.state in ("done", "awaiting_release"),
        (r.status_code, cj and cj.state, cj and cj.error, _text(r.text)[-200:]),
    )
    form = crc.get("/pilot/consent")
    icf = next(ROOT.glob("tests/fixtures/**/GZQO_ICF_v2.md")).read_bytes()  # a synthetic ICF: no public one exists
    r = crc.post(
        "/pilot/consent",
        data={"csrf": fd._csrf(form.text), "study": TRIAL, "langs": ["en", "ja"]},
        files={"icf": ("icf.md", icf, "text/markdown")},
        follow_redirects=False,
    )
    kj = box.orch.db.get(r.headers.get("location", "/").rsplit("/", 1)[-1]) if r.status_code == 303 else None
    s.check(
        "consent explainer draft (ICF upload, EN + JA)",
        kj is not None and kj.state == "done",
        (r.status_code, kj and kj.state, kj and kj.error, _text(r.text)[-200:]),
    )
    form = crc.get("/pilot/protocol")
    r = crc.post(
        "/pilot/protocol",
        data={"csrf": fd._csrf(form.text), "ruleset": TRIAL, "criteria": criteria(TRIAL) + "5. Known HIV infection.\n"},
    )
    draft = box.orch.db.get(r.url.path.rsplit("/", 1)[-1])
    page = admin.get("/admin?tab=jobs")
    r = admin.post(f"/admin/jobs/{draft.job_id}/cancel", data={"csrf": fd._csrf(page.text)})
    s.check("Cancel asks to confirm", r.status_code == 200 and "confirm" in r.text, r.status_code)
    r = admin.post(
        f"/admin/jobs/{draft.job_id}/cancel",
        data={"csrf": fd._csrf(page.text), "confirm": "yes"},
        follow_redirects=False,
    )
    gone = box.orch.db.get(draft.job_id)
    s.check(
        "Cancel a waiting job (failed, step cancelled)",
        r.status_code == 303
        and gone is not None
        and gone.state == "failed"
        and gone.error is not None
        and gone.error.step == "cancelled",
        (r.status_code, gone and gone.state, gone and gone.error),
    )
    # Retry needs a failed job: mark a finished SCREEN failed (simulated failure), then retry it
    from tb_contracts import JobError

    failed = sj.model_copy(
        update={"state": "failed", "error": JobError(step="screen", message="simulated failure (public-data e2e)")}
    )
    box.orch.db.put(failed)
    n_before = len(box.orch.db.find(type_="SCREEN", ruleset=TRIAL))
    r = admin.post(
        f"/admin/jobs/{sj.job_id}/retry", data={"csrf": fd._csrf(page.text), "confirm": "yes"}, follow_redirects=False
    )
    s.check(
        "Retry a failed job creates a new one",
        r.status_code == 303 and len(box.orch.db.find(type_="SCREEN", ruleset=TRIAL)) == n_before + 1,
        (r.status_code, _text(r.text)[-200:]),
    )
    r = admin.post(f"/admin/jobs/{fj.job_id}/retry", data={"csrf": fd._csrf(page.text), "confirm": "yes"})
    s.check("Retry of a finished job is refused (409)", r.status_code == 409, r.status_code)
    r = admin.post(f"/admin/jobs/{fj.job_id}/cancel", data={"csrf": fd._csrf(page.text), "confirm": "yes"})
    s.check("Cancel of a finished job is refused (409)", r.status_code == 409, r.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 7b identifiers by role (P-01, P-32, D-143)
    s = Stage("7b chart numbers and names by role")
    t = time.perf_counter()
    walk = {"trial": TRIAL, "cohort": COHORT, "pid_marked": picks[1]["pid"] if len(picks) > 1 else picks[0]["pid"],
            "feas_job": fj.job_id, "approval_job": jobs[TRIAL].job_id, "case_job": cj.job_id if cj else "",
            "consent_job": kj.job_id if kj else "", "screen_job": sj.job_id, "record": out.get("screening_no") or "",
            "life_record": out.get("life_record") or "", "site_ws": "practice"}  # fmt: skip
    ident = mrns | {p[k] for p in patients for k in ("name", "id_no", "phone") if p.get(k)}
    swept = identifier_sweep(app, password, lang, walk_pages(walk), ident)
    for who, seen in swept.items():
        s.check(f"{who}: no chart number or name on any page of the walk ({len(seen['pages'])} pages)",
                not seen["leaks"], seen["leaks"][:3])  # fmt: skip
        # D-146 (review J-03 to J-05): no patient-level page or API, no registry, audit trail or set-up for them
        shut = [
            p
            for p, code in seen["pages"]
            if code == 200
            and (
                p == f"/pilot/jobs/{walk.get('case_job')}"
                or re.match(
                    r"^/(?:jobs|audit|pilot/registry|admin/redcap|studies/[^/]+/(?:setup|sources|forms|screening-log|week))",
                    p,
                )
            )
        ]
        s.check(f"{who}: runs, registry, audit trail and study set-up refused (403)", not shut, shut[:3])  # fmt: skip
    if cj is not None:  # the study's investigator has identifier authority: the CASE request row in clear, audited
        page = pi.get(f"/pilot/jobs/{cj.job_id}").text
        s.check("the study's investigator sees the CASE request's chart number (D-143)",
                f"mrn={case_p['mrn']}" in page, "")  # fmt: skip
        s.check("and that view is audited", any(r.event == "console.view_id" and r.actor == "console:pi"
                                                for r in h.bk.audit(cj.job_id)))  # fmt: skip
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ------------------------------------------------------------------ 8 audit chain
    s = Stage("8 audit chain")
    t = time.perf_counter()
    res = verify(box.audit_dir)
    s.check("audit chain verifies", getattr(res, "ok", res) in (True,) or bool(getattr(res, "ok", False)), res)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    rows_now = h.week_bundle(None, TRIAL)["rows"]
    fresh = next((r["pid"] for r in rows_now if r["pid"][:8] not in out["picks"] and r["pid"] != life_pid),
                 rows_now[-1]["pid"])  # fmt: skip
    out["walk"] = {
        "trial": TRIAL,
        "cohort": COHORT,
        "pid_marked": picks[1]["pid"] if len(picks) > 1 else picks[0]["pid"],
        "pid_fresh": fresh,
        "feas_job": fj.job_id,
        "approval_job": jobs[TRIAL].job_id,
        "case_job": cj.job_id if cj else "",
        "consent_job": kj.job_id if kj else "",
        "record": out.get("screening_no") or "",  # a screening number: the walk's Entry and History record
        "life_record": out.get("life_record") or "",  # D-134: a participant with today's visit and a serious AE
        "site_ws": "practice",  # D-135: the practice site, loaded in stage 5c (proposed facts, codes, checks)
        # the study's own words (criterion labels, texts, actions) and the staff names from the data: shown as
        # written, so the walk's language check (D-119) does not count them as untranslated page text
        "authored": authored_strings(box, [TRIAL, COHORT]),
    }
    out.update(
        {
            "stages": stages,
            "seconds": time.perf_counter() - t0,
            "site": site["summary"],
            "canary": site.get("canary"),
            "app": app,
            "box": box,
            "day": day,
            "crc": crc,
            "pi": pi,
            "admin": admin,
        }
    )
    return out


# roles that hold no identifier authority (D-143): they must never see a chart number or a patient's name
NO_ID_ROLES = ("viewer", "cra")


def walk_pages(w: dict[str, Any]) -> list[str]:
    """Every page ``tools/public_walk.js`` opens for any role (its PAGES and FORBIDDEN lists), plus the job pages,
    so that the identifier sweep covers what the walk shows."""
    t, c, lr = w["trial"], w["cohort"], w["life_record"]
    sq = f"ws={w['site_ws']}&study={t}"
    site = [f"/site?{sq}", f"/site/start?{sq}&step=2", f"/site/charts?{sq}", f"/site/facts?{sq}", f"/site/codes?{sq}",
            f"/site/checks?{sq}", f"/site/sheets?{sq}", f"/site/people?{sq}", f"/site/patients?{sq}",
            f"/site/help?{sq}"]  # fmt: skip
    life = [f"/studies/{t}/subjects", f"/studies/{t}/subjects/{lr}", f"/studies/{t}/visits",
            f"/studies/{t}/schedule", f"/studies/{t}/enrolment"]  # fmt: skip
    pages = ["/home", "/help", "/account", "/notices/received", "/settings/notices", f"/ask?q=next&{sq}", "/week",
             f"/studies/{t}/week?list=all", f"/studies/{t}/patients/{w['pid_marked']}", f"/studies/{c}/cohort",
             f"/studies/{t}/feasibility", f"/studies/{t}/screening-log", f"/studies/{t}/setup",
             f"/studies/{t}/sources", f"/studies/{t}/conflicts?all=1", f"/studies/{t}/forms",
             f"/studies/{t}/excluded", f"/studies/{t}/entry?record={w['record']}&form=tb_consent",
             f"/studies/{t}/history?record={w['record']}", *life, *site, "/pilot/protocol", "/pilot/request",
             "/pilot/case", "/pilot/consent", f"/pilot/registry/{c}", "/reports", "/reports/research-office",
             "/jobs", "/audit", "/admin?tab=health", "/admin?tab=jobs", "/ops/users"]  # fmt: skip
    for k in ("feas_job", "case_job", "consent_job", "screen_job"):
        if w.get(k):
            pages.append(f"/pilot/jobs/{w[k]}")
    if w.get("approval_job"):
        pages.append(f"/pilot/jobs/{w['approval_job']}/approval")
    return pages


def identifier_sweep(app: Any, password: str, lang: str, pages: list[str], ids: set[str]) -> dict[str, Any]:
    """Every page of the walk, as each role without identifier authority, searched for every chart number and name
    of the site (review 2026-11-09 P-01/P-32: the CASE job page printed ``mrn=`` to the viewer; only the mail was
    swept)."""
    pats = [re.compile(rf"(?<![0-9A-Za-z]){re.escape(x)}(?![0-9A-Za-z])") for x in sorted(ids) if len(x) >= 4]
    out: dict[str, Any] = {}
    for who in NO_ID_ROLES:
        c = ld.sign_in(app, who, password, lang)
        seen: dict[str, Any] = {"pages": [], "leaks": []}
        for path in pages:
            r = c.get(path)
            seen["pages"].append((path, r.status_code))
            seen["leaks"] += [(path, m.pattern[-24:]) for m in pats if m.search(r.text)]
        out[who] = seen
    return out


def authored_strings(box: Any, rulesets: list[str]) -> list[str]:
    from tb_common.ruleset import RulesetNotApproved, load_approved

    out: set[str] = set()
    for rid in rulesets:
        try:
            r = load_approved(box.orch.rulesets_dir, rid)
        except (FileNotFoundError, RulesetNotApproved):
            continue
        for c in r.criteria:
            out.update(x for x in (c.label, c.text, c.action, c.note_question, c.human_question) if x)
    for p in (box.orch.cfg.settings.practitioners or {}).values():
        if p.name:
            out.add(p.name)
    out.update(name for _, name, _ in ps.STAFF)  # the clinicians' names as the records hold them (D-120)
    return sorted(out, key=len, reverse=True)


def table(stages: list[Stage]) -> str:
    lines = ["| stage | check | result | detail |", "| --- | --- | --- | --- |"]
    for st in stages:
        for what, ok, detail in st.checks:
            why = "" if ok else detail.replace("|", "/")[:160]
            lines.append(f"| {st.name} | {what} | {'pass' if ok else 'FAIL'} | {why} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_PUBLIC_DIR", "/tmp/tb-public")))
    ap.add_argument("--lang", default="en", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--judge-url", default="", help="real judge, e.g. http://<vm>/judge/v1 (key in TB_GPU_KEY)")
    ap.add_argument("--verifier-url", default="")
    ap.add_argument("--single", action="store_true", help="judge only, no verifier")
    ap.add_argument(
        "--swap",
        action="store_true",
        help="one GPU, one model awake (TB_MODEL_SWAP=sleep): the run swaps the VM's servers as the gateway would",
    )
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    a.dir.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    llm = verifier = None
    if a.judge_url:  # the key comes from the environment only (never a flag, never printed)
        llm, verifier = real_models(a.judge_url, a.verifier_url, os.environ["TB_GPU_KEY"])
        if a.single:
            verifier = None
    swap = None
    if a.swap:
        swap = direct_swap(a.judge_url, a.verifier_url, os.environ["TB_GPU_KEY"], llm, verifier)
    res = run(a.dir, password, a.lang, llm, verifier)
    if swap is not None:
        res["swap"] = swap.status()
        print(f"swap: {json.dumps(res['swap'])}")
    print(table(res["stages"]))
    n = sum(len(st.checks) for st in res["stages"])
    bad = sum(1 for st in res["stages"] for c in st.checks if not c[1])
    print(f"\n{n - bad}/{n} checks pass in {res['seconds']:.1f} s; feasibility {json.dumps(res['feas']['remaining'])}")
    print(f"screen {json.dumps(res['screen'], default=str)}; cohort members {res['cohort_members']}")
    (a.dir / "walk.json").write_text(json.dumps(res["walk"]), encoding="utf-8")
    (a.dir / "stages.md").write_text(table(res["stages"]), encoding="utf-8")
    (a.dir / "result.json").write_text(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "feas",
                    "screen",
                    "cohort_members",
                    "seconds",
                    "site",
                    "terminology_missed",
                    "swap",
                    "judging",
                    "canary",
                )
                if k in res
            },
            default=str,
            indent=1,
        ),
        encoding="utf-8",
    )
    if a.serve:
        import uvicorn

        if not os.environ.get("TB_DEMO_PASSWORD"):
            print(f"password (all accounts): {password}")
        uvicorn.run(res["app"], host=a.host, port=a.port, log_level="warning")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
