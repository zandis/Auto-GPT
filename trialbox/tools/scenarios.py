"""The scenario matrix of the complete run (TB-PLAN-04 step 9, D-141): every way a site gives TrialBox data, each
through its own path, screened, and counted against an independent recount from the generator.

    db-csv        the hospital database feed (CGRD-style CSV export) at ``--patients``: this is the ``hospital:<lang>``
                  part of ``tools.complete_run`` (``e2e_simple`` stages 0-7); its section is built from those parts
    emr-ssmix2    SS-MIX2 standardized and extended storage (HL7 v2 with ADT, OMP and 疑い diagnoses), JP Core
                  ``$validate`` on the sample, SCREEN with the run's model
    emr-fhir      a FHIR Bulk ``$export`` (NDJSON, chart numbers and names in it), SCREEN with the run's model
    site-excel    a PI's messy Excel list, a Shift_JIS CSV and a Big5 CSV, joined to the feed by pseudonym in the
                  hospital's own space; the scripted coordinator answers the checks and maps the codes; SCREEN
    chart-paste   EMR screen text in ja and zh-TW: the model proposes facts, the coordinator confirms or rejects each,
                  then the patient check counts (D-135); extraction precision and recall against the charts' facts
    chart-files   the same charts as Word, a PDF with a text layer, and scans (PNG and image-only PDF) through OCR
    redcap        a two-way REDCap project (``rc_sim``) and the built-in forms, records keyed by screening number
    it-dump       an IT department's dump in Shift_JIS with the hospital's own codes, mapped once for the site
    registry      the offline trial registry from the reference data pack sample (D-140), no network
    gateway       a probe: one judge and one chart-reading call through the gateway built as an installed box
                  builds it (``TB_ENV=PRODUCTION``, no ``TB_DATA_CLASS``, the pair pinned as install pins it);
                  both calls must be answered (A-01 and GW-02, fixed in D-142)

Each scenario returns its stages (checks), a ``scenario`` block (input, counts, expected, got, model calls, model
exclusions against the generator's note truth, extraction scores) and the console pages to photograph. Known
findings that the run reports but does not fix are listed under ``findings`` and do not fail the run; every other
check does. The review's A-01, GW-02, P-04 and B-03 (fixed in D-142) are checks now.

Sizes follow ``--patients`` (:func:`sizes`): on the card 50,000 gives SS-MIX2 and FHIR 5,000 patients each, the
Excel list 1,000 rows, 200 pasted charts and 60 chart files; a laptop run at 5,000 gives a tenth.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import random
import re
import shutil
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tools import feas_demo as fd
from tools import list_demo as ld
from tools import synth_charts as sc
from tools.e2e_simple import Stage

ROOT = Path(__file__).resolve().parents[1]
SNAP = (fd.REF - timedelta(days=1)).isoformat()  # the feed's snapshot day
TODAY = fd.REF + timedelta(days=1)  # the box's day
GOUT = ("M10", "M1A")
TRIAL = "GZQO"
SITE_RS = "SITE5B"
NOTE_CRITERIA = ("GZQO-INC-05", "GZQO-EXC-11")
# the generator's note truth that makes a note criterion block the patient (EXC-11 flare now; INC-05 < 2 flares)
BLOCKING_TRUTH = {"GZQO-EXC-11": "yes", "GZQO-INC-05": "no"}
SCENARIOS = (
    "emr-ssmix2",
    "emr-fhir",
    "site-excel",
    "chart-paste",
    "chart-files",
    "redcap",
    "it-dump",
    "registry",
    "public-mimic",
    "public-medtxt",
    "public-trec",
    "gateway",
)
TITLES = {
    "db-csv": "Hospital database feed (CGRD-style CSV)",
    "emr-ssmix2": "EMR: SS-MIX2 storage",
    "emr-fhir": "EMR: FHIR bulk export",
    "site-excel": "The site's own Excel and CSV lists",
    "chart-paste": "A single chart, pasted EMR text",
    "chart-files": "Chart files: Word, PDF, scans (OCR)",
    "redcap": "REDCap two-way and built-in forms",
    "it-dump": "IT dump with local codes",
    "registry": "Offline trial registry (reference data pack)",
    "public-mimic": "Real data: MIMIC-IV demo on FHIR (ODbL)",
    "public-medtxt": "Real data: MedTxt-CR Japanese case reports as pasted charts (CC BY 4.0)",
    "public-trec": "Real data: TREC Clinical Trials topics, trials and qrels (NIST, NCBI)",
    "gateway": "Probe: the installed box's model gateway",
}
# public datasets of eval/DATASETS.yaml not run as scenarios, and why (the report lists them)
NOT_RUN = {
    "chia": "real eligibility criteria (CC BY 4.0): not in .cache on this machine (tools/chia_routes.py fetches it)",
    "synthea": "no Synthea mapping in this build (TB-DS-21 §4); tools/synthea_ad_cohort.py is a separate study",
    "open_cohorts": "SIGIR 2016 and TREC 2023 files are not in .cache on this machine",
    "public_site": "the SIGIR notes and MedTxt site: run as the public:<lang> parts of this run",
    "refdata (full pack)": "the registry scenario uses the pack's sample; the full 2026-11-09 pack is loaded by "
    "tools/refdata_fetch.py on a box, not in this run",
    "jp_core": "the JP Core 1.1.0 package is what the SS-MIX2 scenario's $validate checks against",
}
# per-scenario floors for chart reading: precision guards against invented facts (they would mislead a coordinator)
FLOORS = {"precision": 0.90, "recall": 0.70}
# model-call estimate inputs (tools.complete_run --estimate): seconds per call on the card, from VALIDATION §3
SECONDS_PER_NOTE_PATIENT = 6.3


def sizes(patients: int) -> dict[str, int]:
    """Scenario sample sizes for a run of ``patients`` (the bulk feed)."""
    return {
        "db-csv": patients,
        "emr-ssmix2": max(200, min(5000, patients // 10)),
        "emr-fhir": max(200, min(5000, patients // 10)),
        "site-excel": max(40, min(1000, patients // 50)),
        "site-feed": max(300, min(5000, patients // 10)),
        "chart-paste": max(20, min(200, patients // 250)),
        "chart-files": max(12, min(60, patients // 800)),
        "redcap": max(20, min(500, patients // 100)),
        "it-dump": max(50, min(2000, patients // 25)),
        "registry": 6,
        "public-mimic": 100,
        "public-medtxt": max(10, min(148, patients // 300)),
        "public-trec": max(4, min(50, patients // 1000)),
        "gateway": 2,
    }


@dataclass
class Result:
    name: str
    stages: list[Stage] = field(default_factory=list)
    block: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    pages: list[tuple[str, str]] = field(default_factory=list)  # (user, path) on the console
    app: Any = None

    def finding(self, fid: str, what: str, expected: Any, got: Any, holds: bool) -> None:
        """A known finding of the review: reported with what was seen, never a failed check of this run."""
        self.findings.append({"id": fid, "what": what, "expected": expected, "got": got, "holds": bool(holds)})


# ------------------------------------------------------------------------------------------------ models
def gateway_client(env: dict[str, str], upstream: Any = None) -> Any:
    """``tb_llm.GatewayClient`` to an in-process tb-gateway built exactly as an installed box builds it
    (:func:`gateway.app.from_env` over ``env``: ``TB_ENV``, ``TB_PROFILE``, ``TB_EP_*_URL``, the registry with its
    site pins). ``upstream``: the HTTP client to the model servers (the stub in process; None = the network)."""
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from gateway.core import Gateway, GatewayConfig
    from gateway.policy import RoutingPolicy
    from guard.guard import Guard
    from registry.registry import Registry
    from tb_common.audit import AuditLog
    from tb_llm import GatewayClient

    gw = Gateway(
        RoutingPolicy.load(),
        Registry.from_env(env),
        AuditLog(Path(env["TB_AUDIT_DIR"])),
        GatewayConfig.from_env(env),
        http=upstream,
        guard=Guard.from_settings(),
        env=env,
    )
    return GatewayClient("http://tb-gateway/v1", "orchestrator", http=TestClient(create_app(gw)))


def installed_registry(work: Path) -> Path:
    """The pins ``install.sh`` makes (``tools/pin_model.py --install rtxpro6000``, D-142 review R-01): the profile's
    pair as champion, from the site's weights in ``deploy/models`` when they are there, else from synthetic weights in
    ``work`` (the laptop and the stub have none). Written under ``work``, never into the repository."""
    from tools import pin_model

    out = work / "site" / "registry.site.yaml"
    if out.exists():
        return out
    root = ROOT / "deploy" / "models"
    dirs = [p[3] for p in pin_model.PROFILE_PAIRS["rtxpro6000"]]
    if not all((root / d).is_dir() for d in dirs):
        root = work / "models"
        for d in dirs:
            (root / d).mkdir(parents=True, exist_ok=True)
            (root / d / "model.safetensors").write_bytes(f"synthetic {d}".encode())
    ok, lines = pin_model.install_pins("rtxpro6000", root, out, {})
    if not ok:
        raise RuntimeError("; ".join(lines))
    return out


def installed_env(audit_dir: Path, judge_url: str = "", verifier_url: str = "") -> dict[str, str]:
    """The gateway's environment on an installed RTX PRO 6000 box (``deploy/docker-compose.yml`` and
    ``docker-compose.rtxpro6000.yml`` defaults; ``install.sh`` writes TB_ENV=PRODUCTION and no TB_DATA_CLASS, and
    pins the profile's pair: :func:`installed_registry`)."""
    env = {
        "TB_ENV": "PRODUCTION",
        "TB_TOPOLOGY": "A",
        "TB_PROFILE": "P-PRO6000",
        "TB_AUDIT_DIR": str(audit_dir),
        "TB_REGISTRY_OVERRIDE": str(installed_registry(audit_dir.parent)),
    }
    if judge_url:
        env["TB_EP_SERVING_URL"] = judge_url
    if verifier_url:
        env["TB_EP_VERIFIER_URL"] = verifier_url
    return env


def models(a: Any, audit_dir: Path) -> tuple[Any, Any]:
    """The run's judge and verifier clients: None on the stub (the box keeps its own); with ``--model pair``
    either straight to the card (``--direct``) or, by default, through the gateway as an installed box routes."""
    if getattr(a, "model", "stub") != "pair":
        return None, None
    os.environ["TB_CANARY_GATE"] = "on"  # plan v4 §5: screening with the pair and the canary gate
    if getattr(a, "direct", False):
        from tools.public_e2e import real_models

        return real_models(a.judge_url, a.verifier_url, os.environ["TB_GPU_KEY"])
    from tb_common.llm import LlmClient

    os.environ.pop("TB_DATA_CLASS", None)  # as install leaves it
    env = installed_env(audit_dir, a.judge_url, a.verifier_url)
    out = []
    for alias in ("", "v-verifier"):
        c = LlmClient("http://unused/v1", "", gateway=gateway_client(env))
        if alias:
            c.gateway.model = alias
        out.append(c)
    return out[0], out[1]


def llm_calls(box: Any, prompt: str = "") -> int:
    n = 0
    for p in sorted(Path(box.audit_dir).glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if '"llm.call"' in line and (not prompt or f'"{prompt}_v' in line):
                n += 1
    return n


# ------------------------------------------------------------------------------------------------ SCREEN capture
CAPTURED: list[dict[str, Any]] = []


def capture_screens() -> None:
    """Keep every SCREEN run's per-patient verdicts (the cascade's rows) for the exclusion check; once per process."""
    from orchestrator.scenarios import screen

    if getattr(screen, "_tb_captured", False):
        return
    inner = screen.screen_with_cascade  # type: ignore[attr-defined]

    def wrapped(ctx: Any, rs: Any, *args: Any, **kw: Any) -> Any:
        out = inner(ctx, rs, *args, **kw)
        CAPTURED.append({"ruleset": rs.id, "results": out.results, "judging": out.judging, "summary": out.summary})
        return out

    screen.screen_with_cascade = wrapped  # type: ignore[attr-defined]
    screen._tb_captured = True  # type: ignore[attr-defined]


def cap_duckdb_temp(limit: str = "2GB") -> None:
    """Every DuckDB connection of this process may spill at most ``limit`` to disk: a runaway query then fails with
    an error instead of filling the machine's disk (seen on 2026-11-09: SCREEN on the hospital's own space after a
    site sheet was published, finding XL-02)."""
    import duckdb

    os.environ.setdefault("TB_LAKE_MAX_TEMP", limit)  # the lake's own cap (D-142, XL-02) is the same guard
    if getattr(duckdb, "_tb_capped", False):
        return
    real = duckdb.connect

    def connect(*args: Any, **kw: Any) -> Any:
        con = real(*args, **kw)
        with contextlib.suppress(Exception):  # an old DuckDB without the setting: the harness still runs
            con.execute(f"SET max_temp_directory_size = '{limit}'")
        return con

    duckdb.connect = connect
    duckdb._tb_capped = True  # type: ignore[attr-defined]


def note_truth(site_dirs: list[Path], key: bytes) -> dict[str, dict[str, str]]:
    from tb_common.crypto import pid_for_mrn

    out: dict[str, dict[str, str]] = {}
    for d in site_dirs:
        f = d / "note_truth.json"
        if f.exists():
            for mrn, v in json.loads(f.read_text(encoding="utf-8")).items():
                out[pid_for_mrn(key, mrn)] = v
    return out


def model_exclusions(results: dict[str, Any], truth: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Patients the models excluded (a note criterion failed and no coded criterion did), each checked against the
    generator's note truth: a true exclusion when the truth blocks on that criterion, else a false one. Also the
    true exclusions the run reached but did not make (the patient still listed)."""
    rows, true_x, false_x, missed = [], 0, 0, 0
    for pid, pv in sorted(results.items()):
        fails = [v.id for v in pv.verdicts if v.verdict == "fail"]
        notes = [c for c in fails if c in NOTE_CRITERIA]
        coded = [c for c in fails if c not in NOTE_CRITERIA]
        blocks = [c for c, v in BLOCKING_TRUTH.items() if truth.get(pid, {}).get(c) == v]
        other = any("contact" in x or "scope" in x for x in pv.actions)  # out for consent or scope, not a model
        if pv.tier == "excluded" and notes and not coded and not other:
            ok = all(c in blocks for c in notes)
            true_x += ok
            false_x += not ok
            rows.append(
                {
                    "pid": pid[:10],
                    "criteria": notes,
                    "truth": {c: truth.get(pid, {}).get(c) for c in notes},
                    "correct": ok,
                }
            )
        elif pv.tier in ("high", "review") and blocks:
            missed += 1
    return {
        "excluded_by_models": len(rows),
        "true": true_x,
        "false": false_x,
        "missed_true": missed,
        "patients": rows[:50],
    }


def screen_once(box: Any, ruleset: str = TRIAL) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """SCREEN the ruleset by mail (as a coordinator asks for it), drained; ``(job, screen json, captured rows)``."""
    from tools.e2e_simple import _json_output

    before = len(CAPTURED)
    box.mail(f"SCREEN {ruleset} version=1.0.0")
    box.orch.drain()
    jobs = [j for j in box.orch.db.find(type_="SCREEN", ruleset=ruleset, limit=20)]
    job = jobs[0] if jobs else None
    if job is None or job.state != "done":
        return job, {}, {}
    cap = CAPTURED[before] if len(CAPTURED) > before else {}
    return job, _json_output(box, job, "screen_"), cap


# ------------------------------------------------------------------------------------------------ feed and box
def synth(work: Path, sites: str) -> tuple[list[Path], Path, dict[str, Any]]:
    """A synthetic hospital (``tools.synth_hospital``) merged into one feed folder: (site dirs, feed dir, summary)."""
    from tools.synth_hospital import run as synth_run

    out = work / "synth"
    if not (out / "summary.json").exists():
        res = synth_run(out, profile="ci", sites=sites, ref_date=fd.REF)
        if not res.passed:
            raise RuntimeError("synthetic hospital checks failed: " + "; ".join(res.failures[:3]))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    dirs = [out / s["dir"] for s in summary["sites"]]
    feed = work / "hospital"
    if not (feed / "patient.csv").exists():
        fd.merge_sites(dirs, feed)
    return dirs, feed, summary


def secrets_dir(work: Path) -> Path:
    sec = work / "sec"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(fd.KEY)
    return sec


def csv_lake(feed: Path, lake: Path, sec: Path) -> Any:
    from tests.inproc_box import ingest_site

    return ingest_site(feed, lake, sec, SNAP)


@dataclass
class World:
    box: Any
    app: Any
    h: Any
    svc: Any
    crc: Any
    admin: Any
    password: str


def world(work: Path, lake: Path, sec: Path, a: Any, ocr: Any = None) -> World:
    """The in-process box over ``lake`` with the run's models, its console (accounts of ``tools.feas_demo``) and its
    site set-up service (the same object the console's ``/site`` pages use)."""
    from orchestrator import app as orch_app
    from orchestrator.app import setup_of

    from tests.inproc_box import make_box
    from tools.public_e2e import attach_models
    from tools.role_demo import orch_client

    cap_duckdb_temp()
    shutil.rmtree(work / "box", ignore_errors=True)
    box = make_box(work / "box", lake, sec, TODAY)
    orch_app._orch = box.orch
    llm, verifier = models(a, work / "gw-audit")
    if llm is not None:
        attach_models(box, llm, verifier)
    capture_screens()
    clock = ld.Clock(box.today[0])
    app = ld.console(work, box, orch_client(orch_app.app), work / "box" / "repo", a.password, clock)
    svc = setup_of(box.orch)
    if ocr is not None:
        svc.ocr = ocr
    crc = ld.sign_in(app, "crc", a.password, a.lang)
    admin = ld.sign_in(app, "admin", a.password, a.lang)
    return World(box, app, app.state.helpers, svc, crc, admin, a.password)


# ------------------------------------------------------------------------------------------------ recounts
def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _age(birth: str, ref: date) -> int:
    b = date.fromisoformat(birth)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def recount_feas(feed: Path) -> dict[str, int]:
    """GZQO's first FEAS steps recounted from the generator's CSVs (as ``e2e_simple`` stage 1 does)."""
    ref = date.fromisoformat(SNAP)
    pts = _rows(feed / "patient.csv")
    adults = {p["mrn"] for p in pts if _age(p["birth_date"], ref) >= 18}
    gout = {r["mrn"] for r in _rows(feed / "diagnosis.csv") if r["icd10"].startswith(GOUT)}
    return {"start": len(pts), "GZQO-INC-01": len(adults), "GZQO-INC-02": len(adults & gout)}


def feas(lake_dir: Path, ruleset: str = TRIAL) -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios.feas_compute import FeasParams, compute
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / ruleset)
    _, raw = compute(
        LakeLocal(lake_dir, HashEmbedder()), rs, FeasParams(run_date=fd.REF, snapshot=SNAP, lookback_months=36)
    )
    return {"start": raw.start_n, **raw.remaining}


def lake_count(lake_dir: Path, table: str) -> int:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    return int(LakeLocal(lake_dir, HashEmbedder()).query(f"SELECT count(*) AS n FROM {table}").to_pylist()[0]["n"])


def site_ruleset() -> Any:
    """SITE5B: age 18+, gout, latest serum urate in the last year >= 7.0 mg/dL, no malignancy (the structured study
    of D-135's site set-up; built here as ``tests/unit/test_site_setup.py`` builds it)."""
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
    from tb_common.ruleset import Ruleset
    from tb_contracts import CriterionIR

    def crit(cid: str, kind: str, text: str, logic: dict[str, Any]) -> Any:
        return CriterionIR.model_validate(
            {"id": cid, "ruleset": SITE_RS, "kind": kind, "class": "structured", "text": text, "logic": logic}
        )

    cs = [
        crit("SITE5B-INC-01", "inclusion", "18+", {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
        crit("SITE5B-INC-02", "inclusion", "gout", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"}),
        crit(
            "SITE5B-INC-03",
            "inclusion",
            "urate >= 7",
            {
                "domain": "observation",
                "quantifier": "latest",
                "valueset": "VS_SERUM_URATE",
                "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"},
                "window": {"anchor": "index", "from_days": -365, "to_days": 0},
            },
        ),
        crit(
            "SITE5B-EXC-01",
            "exclusion",
            "malignancy",
            {"domain": "condition", "quantifier": "any", "valueset": "VS_MALIGNANCY"},
        ),
    ]
    term = Terminology()
    vs = {}
    for name, domain, concept in (
        ("VS_GOUT", "condition", "gout"),
        ("VS_SERUM_URATE", "observation", "serum urate"),
        ("VS_MALIGNANCY", "condition", "malignancy"),
    ):
        res = term.map(domain, concept)
        vs[name] = valueset(SITE_RS, name, concept, res.concepts, "1.0.0", families=res.families)
    sql = SqlGenerator(SITE_RS, "1.0.0", ValueSets(SITE_RS, vs, term)).render(cs)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": SITE_RS, "library": None, "criteria": [c.id for c in cs]})
    return Ruleset(manifest=manifest, criteria=cs, valuesets=vs, sql=sql)


@dataclass
class Truth:
    """What the generator knows about one patient, for the SITE5B recount."""

    birth: str = ""
    dx: set[str] = field(default_factory=set)
    urate: list[tuple[str, float]] = field(default_factory=list)  # (day, mg/dL)


def expected_state(t: Truth, today: date = TODAY) -> str:
    """SITE5B by hand: not eligible when a criterion fails, needs information when one is unknown, else ready."""
    verdicts = []
    verdicts.append(None if not t.birth else _age(t.birth, today) >= 18)
    verdicts.append(any(c.startswith(GOUT) for c in t.dx))
    win = [(d, v) for d, v in t.urate if today - timedelta(days=365) <= date.fromisoformat(d) <= today]
    verdicts.append(None if not win else max(win)[1] >= 7.0)
    # malignancy: ICD-10 C00-C96 except C44 (non-melanoma skin cancer, as the curated value set leaves it out)
    excluded = any(c[:1] == "C" and c[1:3].isdigit() and int(c[1:3]) <= 96 and c[1:3] != "44" for c in t.dx)
    if excluded or any(v is False for v in verdicts):
        return "not_eligible"
    return "needs" if any(v is None for v in verdicts) else "ready"


def compare_states(got: dict[str, str], want: dict[str, str]) -> dict[str, Any]:
    diff = {p[:10]: (want.get(p), got.get(p)) for p in sorted(set(got) | set(want)) if got.get(p) != want.get(p)}
    return {
        "expected": dict(Counter(want.values())),
        "got": dict(Counter(got.values())),
        "differ": len(diff),
        "examples": dict(list(diff.items())[:8]),
    }


def patient_states(svc: Any, ws: str, rs: Any) -> dict[str, str]:
    from sitesetup import readiness

    return {p["pid"]: p["state"] for p in readiness.patient_check(svc, ws, rs, TODAY)}


def screen_stage(s: Stage, box: Any, truth: dict[str, dict[str, str]], blk: dict[str, Any], a: Any) -> None:
    """SCREEN GZQO on the scenario's lake with the run's model; the funnel, the model calls and the model-driven
    exclusions checked against the generator's note truth (false exclusions must be 0)."""
    calls0 = llm_calls(box)
    t = time.perf_counter()
    job, scr, cap = screen_once(box)
    s.check(
        "SCREEN GZQO ran on this path's data", job is not None and job.state == "done", job and (job.state, job.error)
    )
    if not scr:
        return
    fun = dict(scr["funnel"])
    s.check("SCREEN funnel never grows", fun["S0"] >= fun["S1"] >= fun["S3"], fun)
    j = scr.get("judging") or {}
    ex = model_exclusions(cap.get("results") or {}, truth)
    s.check("no false model exclusion against the generator's note truth", ex["false"] == 0, ex["patients"][:5])
    if a.model == "pair":
        s.check(
            "the pair judged: judge and verifier both named, notes may exclude",
            j.get("verifier_model") and j.get("may_block"),
            j,
        )
    blk["screen"] = {
        "funnel": fun,
        "tiers": scr.get("tiers"),
        "listed": scr.get("listed"),
        "judging": j,
        "seconds": round(time.perf_counter() - t, 1),
    }
    blk["model_calls"] = blk.get("model_calls", 0) + llm_calls(box) - calls0
    blk["model_exclusions"] = ex


# ------------------------------------------------------------------------------------------------ EMR: SS-MIX2
SUSPECT = ("C16.9", "胃癌の疑い")


def _suspected(storage: Path, mrns: list[str]) -> int:
    """PPR-01 messages for 疑い diagnoses (a suspected malignancy, never confirmed): the 標準病名 text ends in の疑い
    and PRB-13 (confirmation status) says suspected. The review (P-04) says the reader ignores the flag."""
    from adapter.sources.ssmix2 import hl7

    from tools.ssmix2_export import _msh, _write

    for i, mrn in enumerate(mrns):
        no = f"DQ{i:06d}"
        prb = ["PRB", "AD", hl7.hl7_ts("2026-06-01"), f"^{SUSPECT[1]}^^{SUSPECT[0]}^{SUSPECT[1]}^I10", no] + [""] * 12
        prb[13] = "S^疑い^HL70?"
        prb[14] = "A"
        prb[16] = hl7.hl7_ts("2026-06-01")
        _write(storage, mrn, "20260601", "PPR-01", no, "-", [_msh("PPR^ZD1", no), "PV1||O", "|".join(prb)])
    return len(mrns)


def flag_labs(files: list[Path], mrns: list[str]) -> dict[str, tuple[str, float]]:
    """Non-numeric lab results as hospitals send them (review B-01): the latest serum urate of each patient becomes
    "8.2 H", ">8.2", "8.2H" or "<5.0" (the true number is kept as truth). Written into every ``lab.csv`` given (the
    site folder the SS-MIX2 storage is made from and the merged feed), so both paths read the same text."""
    variants = ("{v} H", ">{v}", "{v}H", "<{v}")
    out: dict[str, tuple[str, float]] = {}
    for f in files:
        rows = _rows(f)
        if not rows:
            continue
        latest: dict[str, int] = {}
        for i, r in enumerate(rows):
            if r["mrn"] in mrns and r["local_code"] == "UA" and r["result_value"]:
                j = latest.get(r["mrn"])
                if j is None or rows[j]["sample_datetime"] < r["sample_datetime"]:
                    latest[r["mrn"]] = i
        for k, (mrn, i) in enumerate(sorted(latest.items())):
            form = variants[k % len(variants)]
            v = 5.0 if form.startswith("<") else max(7.2, float(rows[i]["result_value"]))
            raw = form.format(v=f"{v:.1f}")
            rows[i]["result_value"] = raw
            out[mrn] = (raw, v)
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return out


def flagged_verdicts(lake_dir: Path, flagged: dict[str, tuple[str, float]]) -> dict[str, Any]:
    """GZQO-INC-04 (serum urate >= 6.8) for the flagged patients, against the true number: a value the truth puts
    at or over 6.8 read as FALSE is a wrong hard exclusion."""
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios.evaluate import SqlEngine
    from tb_common.crypto import pid_for_mrn
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / TRIAL)
    pid = {pid_for_mrn(fd.KEY, m): m for m in flagged}
    ev = SqlEngine(LakeLocal(lake_dir, HashEmbedder())).evaluate(rs, list(pid), TODAY, ["GZQO-INC-04"])
    rows: list[dict[str, Any]] = []
    wrong = 0
    for p, m in sorted(pid.items()):
        got = ev[p].results.get("GZQO-INC-04") if ev.get(p) else None
        raw, v = flagged[m]
        bad = v >= 6.8 and got is False
        wrong += bad
        rows.append({"value": raw, "truth": v, "verdict": got, "wrong_exclusion": bad})
    forms = Counter(f"{re.sub(r'[0-9.]+', 'x', str(r['value']))} -> {r['verdict']}" for r in rows)
    return {"patients": len(rows), "wrong_exclusions": wrong, "by_form": dict(forms)}


def _ingest(kind: str, path: Path, lake: Path, sec: Path, mapping: str, work: Path) -> Any:
    from adapter.pipeline import AdapterConfig, run_ingest
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake
    from tb_contracts import RebuildResult

    def rebuild(sn: str, nd: Path) -> RebuildResult:
        r = Lake(lake, "Asia/Tokyo").rebuild(sn, HashEmbedder(), nd)
        return RebuildResult(
            snapshot=r.snapshot, tables=r.tables, chunks=r.chunks, embedded_new=r.embedded_new, seconds=r.seconds
        )

    cfg = AdapterConfig(
        lake_dir=lake,
        secrets_dir=sec,
        site_id="SCN",
        tz="Asia/Tokyo",
        mapping_path=ROOT / "services/adapter/mapping" / mapping,
        rebuild=rebuild,
        audit_dir=work / "adapter-audit",
    )
    return run_ingest(cfg, kind, str(path), snapshot=SNAP, load_fhir=False)


def sc_ssmix2(a: Any, work: Path) -> Result:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.scenarios.evaluate import SqlEngine
    from tb_common.crypto import pid_for_mrn
    from tb_common.ruleset import Ruleset

    from tools.ssmix2_export import export

    res = Result("emr-ssmix2")
    n = sizes(a.patients)["emr-ssmix2"]
    s = Stage("SS-MIX2: storage in, JP Core, the funnel, 疑い diagnoses")
    t = time.perf_counter()
    dirs, feed, _ = synth(work, f"ss:JP:{n}")
    sec = secrets_dir(work)
    storage = work / "ssmix2"
    pts = _rows(feed / "patient.csv")
    ref = date.fromisoformat(SNAP)
    gout = {r["mrn"] for r in _rows(feed / "diagnosis.csv") if r["icd10"].startswith(GOUT)}
    cancer = {r["mrn"] for r in _rows(feed / "diagnosis.csv") if r["icd10"].startswith("C")}
    cand = sorted(m for m in gout - cancer if _age(next(p["birth_date"] for p in pts if p["mrn"] == m), ref) >= 18)
    suspects = cand[: max(3, n // 100)]
    flagged = flag_labs([dirs[0] / "lab.csv", feed / "lab.csv"], cand[len(suspects) : len(suspects) + max(4, n // 100)])
    sent = export(dirs[0], storage)
    n_sus = _suspected(storage, suspects)
    s.check(
        "the storage has ADT-52, OMP-02/11/12, extended-storage documents and 疑い diagnoses",
        all(sent[k] > 0 for k in ("ADT-52", "OMP-02", "OMP-11", "OMP-12", "document")) and n_sus > 0,
        {**sent, "suspected": n_sus},
    )
    rep_csv = _ingest("csv", feed, work / "lake-csv", sec, "tw_core/demo_his.yaml", work)
    rep = _ingest("ssmix2", storage, work / "lake-ss", sec, "jp_core/ssmix2_site.yaml", work)
    same = {
        k: (rep_csv.counts.get(k), rep.counts.get(k))
        for k in ("Patient", "Encounter", "MedicationRequest", "Observation")
    }
    s.check(
        "the storage gives the CSV's patients, visits, medicines and results",
        all(x == y and x for x, y in same.values()),
        same,
    )
    cond = (rep_csv.counts.get("Condition", 0), rep.counts.get("Condition", 0))
    s.check("diagnoses: the CSV's plus the 疑い ones", cond[1] == cond[0] + n_sus, cond)
    pv = rep.profile_validation
    s.check(
        "JP Core $validate passes on the sample (50 per type)",
        rep.passed and pv is not None and pv.errors == 0,
        pv and (pv.sampled, pv.errors, (pv.messages or [])[:2]),
    )
    want = recount_feas(feed)
    f_ss, f_csv = feas(work / "lake-ss"), feas(work / "lake-csv")
    got = {k: f_ss.get(k) for k in want}
    s.check("FEAS start, age and gout steps = the generator's recount", got == want, {"want": want, "got": got})
    inc = {k: (f_csv[k], f_ss[k]) for k in f_csv if k == "start" or "-INC-" in k}
    s.check("every inclusion step of the funnel equals the CSV path's", all(x == y for x, y in inc.values()), inc)
    rs = Ruleset.load(ROOT / "rulesets" / TRIAL)
    pids = [pid_for_mrn(fd.KEY, m) for m in suspects]
    ev = SqlEngine(LakeLocal(work / "lake-ss", HashEmbedder())).evaluate(rs, pids, TODAY, ["GZQO-EXC-07"])
    excluded = sum(1 for p in pids if ev.get(p) and ev[p].results.get("GZQO-EXC-07") is True)
    for kind in ("csv", "ss"):
        fv = flagged_verdicts(work / f"lake-{kind}", flagged)
        res.finding(
            "B-01",
            f"lab values with a flag or a bound ('8.2 H', '>8.2', '<5.0'), {
                'the CSV feed' if kind == 'csv' else 'SS-MIX2 OBX-5'
            }: true urate >= 6.8 read as FALSE (a hard exclusion)",
            f"0 of {fv['patients']}",
            f"{fv['wrong_exclusions']} of {fv['patients']}; {fv['by_form']}",
            fv["wrong_exclusions"] == 0,
        )
    lk = LakeLocal(work / "lake-ss", HashEmbedder())
    plist = ",".join(f"'{p}'" for p in pids)
    in_lake = lk.query(
        f"SELECT count(DISTINCT pid) AS n FROM condition WHERE code = '{SUSPECT[0]}' AND pid IN ({plist})"
    )
    verdicts = Counter(str(ev[p].results.get("GZQO-EXC-07")) if ev.get(p) else "-" for p in pids)
    listed = lk.query(
        f"SELECT count(DISTINCT pid) AS n FROM site_fact WHERE basis = 'suspected' AND pid IN ({plist})"
    )
    s.check(
        "P-04 (D-142): a patient whose only malignancy is a 疑い diagnosis is not excluded by GZQO-EXC-07; the "
        "diagnosis is listed as suspected, never coded",
        excluded == 0 and in_lake.to_pylist()[0]["n"] == 0 and listed.to_pylist()[0]["n"] == len(pids),
        {
            "excluded": f"{excluded} of {len(pids)}",
            "coded": in_lake.to_pylist()[0]["n"],
            "listed_suspected": listed.to_pylist()[0]["n"],
            "EXC-07": dict(verdicts),
        },
    )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    s2 = Stage("SS-MIX2: screening with the run's model")
    t = time.perf_counter()
    w = world(work, work / "lake-ss", sec, a)
    res.block = {
        "input": f"SS-MIX2 storage of {n:,} patients ({sum(sent.values()):,} messages, {n_sus} 疑い)",
        "counts": {**rep.counts},
        "expected": want,
        "got": got,
        "model_calls": 0,
    }
    screen_stage(s2, w.box, note_truth(dirs, fd.KEY), res.block, a)
    cap = CAPTURED[-1]["results"] if CAPTURED else {}
    fl = {pid_for_mrn(fd.KEY, m): v for m, (_raw, v) in flagged.items()}
    seen = [p for p in fl if p in cap]
    wrong = [
        p for p in seen if fl[p] >= 6.8 and any(v.id == "GZQO-INC-04" and v.verdict == "fail" for v in cap[p].verdicts)
    ]
    res.finding(
        "B-01",
        "flagged urate values in the SCREEN cascade (S1): true urate >= 6.8 failing GZQO-INC-04",
        f"0 of {len(seen)} in scope",
        f"{len(wrong)} of {len(seen)} in scope",
        not wrong,
    )
    s2.seconds = time.perf_counter() - t
    res.stages.append(s2)
    res.app, res.pages = w.app, [("pi", f"/studies/{TRIAL}/week?list=all")]
    return res


# ------------------------------------------------------------------------------------------------ EMR: FHIR export
def fhir_export(lake_csv: Path, feed: Path, out: Path) -> dict[str, int]:
    """The EMR's FHIR Bulk export of the same hospital: the CSV path's resources with the chart number back as
    Patient.id, and the identifiers and names an EMR export carries (TrialBox must drop them)."""
    from adapter.ndjson import read_all
    from tb_common.crypto import pid_for_mrn

    pts = {p["mrn"]: p for p in _rows(feed / "patient.csv")}
    back = {pid_for_mrn(fd.KEY, m): m for m in pts}
    by_type = read_all(lake_csv / "ndjson" / SNAP)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (
                    f"Patient/{back[v[8:]]}"
                    if k == "reference" and isinstance(v, str) and v.startswith("Patient/") and v[8:] in back
                    else walk(v)
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    for rtype, items in sorted(by_type.items()):
        with (out / f"{rtype}.ndjson").open("w", encoding="utf-8") as fh:
            for r in items:
                r = walk(r)
                if rtype == "Patient" and r["id"] in back:
                    mrn = back[r["id"]]
                    r["id"] = mrn
                    r["identifier"] = [{"system": "urn:oid:1.2.392.100495.20.3.51.1", "value": mrn}]
                    r["name"] = [{"text": pts[mrn].get("name") or ""}]
                    r["telecom"] = [{"system": "phone", "value": pts[mrn].get("phone") or ""}]
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        counts[rtype] = len(items)
    return counts


def sc_fhir(a: Any, work: Path) -> Result:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    res = Result("emr-fhir")
    n = sizes(a.patients)["emr-fhir"]
    s = Stage("FHIR: bulk export in, chart numbers out, the funnel")
    t = time.perf_counter()
    dirs, feed, _ = synth(work, f"fh:TW:{n}")
    sec = secrets_dir(work)
    rep_csv = csv_lake(feed, work / "lake-csv", sec)
    sent = fhir_export(work / "lake-csv", feed, work / "export")
    text = (work / "export" / "Patient.ndjson").read_text(encoding="utf-8")
    s.check(
        "the export carries chart numbers, names and phones, as an EMR's does",
        '"identifier"' in text and '"name"' in text,
        sum(sent.values()),
    )
    rep = _ingest("fhir_bulk", work / "export", work / "lake-fhir", sec, "tw_core/demo_his.yaml", work)
    same = {
        k: (rep_csv.counts.get(k), rep.counts.get(k))
        for k in ("Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "DocumentReference")
    }
    s.check("every resource of the export is read", all(x == y and x for x, y in same.values()), same)
    lk = LakeLocal(work / "lake-fhir", HashEmbedder())
    cols = set(lk.query("SELECT * FROM patient LIMIT 1").column_names)
    mrns = {p["mrn"] for p in _rows(feed / "patient.csv")}
    pids = {r["pid"] for r in lk.query("SELECT pid FROM patient").to_pylist()}
    csv_pids = {
        r["pid"] for r in LakeLocal(work / "lake-csv", HashEmbedder()).query("SELECT pid FROM patient").to_pylist()
    }
    s.check(
        "no chart number, name or phone in the lake",
        not (pids & mrns) and not (cols & {"name", "phone", "mrn"}),
        sorted(cols & {"name", "phone", "mrn"}),
    )
    s.check("the same pseudonyms as the hospital feed (joins by pseudonym)", pids == csv_pids, len(pids ^ csv_pids))
    want = recount_feas(feed)
    f = feas(work / "lake-fhir")
    got = {k: f.get(k) for k in want}
    s.check("FEAS start, age and gout steps = the generator's recount", got == want, {"want": want, "got": got})
    s.check("the whole funnel equals the CSV path's", f == feas(work / "lake-csv"), f)
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    s2 = Stage("FHIR: screening with the run's model")
    t = time.perf_counter()
    w = world(work, work / "lake-fhir", sec, a)
    res.block = {
        "input": f"FHIR bulk export of {n:,} patients ({sum(sent.values()):,} resources, NDJSON)",
        "counts": dict(rep.counts),
        "expected": want,
        "got": got,
        "model_calls": 0,
    }
    screen_stage(s2, w.box, note_truth(dirs, fd.KEY), res.block, a)
    s0 = (res.block.get("screen") or {}).get("funnel", {}).get("S0", 0)
    refs = (
        {r["pr"] for r in lk.query("SELECT DISTINCT practitioner_id AS pr FROM appointment").to_pylist() if r["pr"]}
        if "practitioner_id" in set(lk.query("SELECT * FROM appointment LIMIT 1").column_names)
        else set()
    )
    staff = {r["id"] for r in lk.query("SELECT * FROM practitioner").to_pylist() for k in ("id",) if k in r}
    res.finding(
        "FHIR-01",
        "SCREEN scope on the FHIR path (patients booked in the study's clinics): the bulk path "
        "hashes Practitioner references but keeps Practitioner ids",
        "S0 > 0, as on the SS-MIX2 path",
        f"S0 = {s0}; appointment practitioners found in the practitioner table: {len(refs & staff)} of {len(refs)}",
        s0 > 0,
    )
    s2.seconds = time.perf_counter() - t
    res.stages.append(s2)
    res.app, res.pages = w.app, [("admin", "/admin?tab=sources")]
    return res


# ------------------------------------------------------------------------------------------------ the site's sheets
def answer_checks(svc: Any, ws: str, by: str = "crc") -> int:
    """The scripted coordinator: each open check gets its suggested answer (a possible chart-number column is left
    out, as D-135's coordinator does)."""
    n = 0
    for _ in range(200):
        open_ = svc.store.checks(ws, True)
        if not open_:
            return n
        c = open_[0]
        opts = list(c["options"])
        ans = "drop" if c["kind"] == "chart_column" and "drop" in opts else (c.get("suggestion") or "")
        if ans not in opts:
            ans = next((o for o in opts if o != "drop"), opts[0])
        svc.answer(int(c["id"]), ans, by)
        n += 1
    return n


def map_codes(svc: Any, ws: str, known: dict[tuple[str, str], str], by: str = "crc") -> dict[str, Any]:
    """Map every local code once: the suggested standard code when there is one, else the site's own knowledge
    (``known``: (domain, local code or wording) -> code). Returns how many took the suggestion."""
    from sitesetup import mapping

    took = told = 0
    wrong: list[str] = []
    out: dict[str, Any]
    for loc in svc.store.locals(ws):
        if loc.get("mapped_at"):
            continue
        mine = known.get((loc["domain"], loc["code"])) or known.get((loc["domain"], loc.get("display") or ""))
        sug = loc.get("suggested_code") or ""
        code = mine or sug  # a careful coordinator: the site's own knowledge wins over a suggestion
        if not code:
            continue
        took += bool(sug) and code == sug
        told += code != sug
        if sug and mine and sug.split(".")[0] != mine.split(".")[0]:
            wrong.append(f"{loc['code']} {loc.get('display') or ''}: suggested {sug}, the site's code {mine}")
        svc.map_code(
            ws, loc["domain"], loc["system"], loc["code"], {"system": mapping.TARGET[loc["domain"]], "code": code}, by
        )
    out = {"suggested": took, "site_knowledge": told, "wrong_suggestions": wrong}
    return out


def _feed_truth(feed: Path) -> dict[str, Truth]:
    out: dict[str, Truth] = {}
    for p in _rows(feed / "patient.csv"):
        out[p["mrn"]] = Truth(birth=p["birth_date"])
    for r in _rows(feed / "diagnosis.csv"):
        out.setdefault(r["mrn"], Truth()).dx.add(r["icd10"])
    for r in _rows(feed / "lab.csv"):
        if r["local_code"] == "UA" and r["result_value"]:
            out.setdefault(r["mrn"], Truth()).urate.append((r["sample_datetime"][:10], float(r["result_value"])))
    return out


FW = str.maketrans("0123456789.", "０１２３４５６７８９．")


def sheets(feed: Path, n: int, seed: int = 7) -> tuple[list[tuple[str, bytes]], dict[str, Truth], dict[str, Any]]:
    """The PI's lists over ``n`` feed patients with a gout diagnosis: an Excel list in ja (title row, merged cells,
    era dates, full-width digits, µmol/L, a slashed-date column, a name column), a Shift_JIS CSV, and a Big5 CSV in
    zh-TW (民國 dates). Each row carries a new urate measured after every urate in the feed. Returns the files, the
    truth by chart number (feed and sheet together) and what was planted."""
    rng = random.Random(seed)
    truth = _feed_truth(feed)
    pts = {p["mrn"]: p for p in _rows(feed / "patient.csv")}
    lastlab = {m: max((d for d, _ in t.urate), default="2000-01-01") for m, t in truth.items()}
    pool = sorted(m for m, t in truth.items() if any(c.startswith(GOUT) for c in t.dx) and lastlab[m] < "2026-10-14")
    rng.shuffle(pool)
    pick = pool[:n]
    jp = [m for m in pick if m.startswith("2")]
    tw = [m for m in pick if not m.startswith("2")]
    planted: Counter[str] = Counter()
    rows: dict[str, list[list[Any]]] = {"xlsx": [], "sjis": [], "big5": []}
    for i, m in enumerate(jp + tw):
        birth = date.fromisoformat(pts[m]["birth_date"])
        day = date(2026, 10, rng.randint(14, 31))
        if i % 9 == 0:
            day = date(2026, 10, rng.randint(14, 31)).replace(day=rng.randint(1, 12)) if False else day
        v = round(rng.uniform(4.5, 10.5), 1)
        while abs(v - 7.0) < 0.15:
            v = round(rng.uniform(4.5, 10.5), 1)
        truth[m].urate.append((day.isoformat(), v))
        dx = "痛風"
        if m in tw:
            rows["big5"].append(
                [
                    m,
                    pts[m].get("name") or "",
                    sc.minguo(birth),
                    "男" if pts[m]["sex"] == "M" else "女",
                    dx,
                    f"{v}",
                    "mg/dL",
                    f"{day.year}/{day.month:02d}/{day.day:02d}",
                ]
            )
            planted["minguo"] += 1
            continue
        cell_v, unit = f"{v}", "mg/dL"
        if i % 4 == 1:
            cell_v, unit = f"{round(v * 59.48)}", "µmol/L"
            planted["unit"] += 1
        no = m.translate(FW) if i % 5 == 0 else m
        planted["width"] += (i % 5 == 0) + (i % 4 == 3)
        if i % 4 == 3:
            cell_v = cell_v.translate(FW)
        row = [
            no,
            pts[m].get("name") or "",
            sc.era(birth).replace("年", "年", 1),
            dx,
            cell_v,
            unit,
            f"{day.day:02d}/{day.month:02d}/{day.year}",
        ]
        planted["era"] += 1
        rows["sjis" if i % 4 == 2 else "xlsx"].append(row)
    files: list[tuple[str, bytes]] = []
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["痛風外来 候補者リスト（2026年10月 山田班）", None, None, None, None, None, None])
    ws.append(["カルテ番号", "氏名", "生年月日", "診断", "尿酸値", "単位", "受診日"])
    for r in rows["xlsx"]:
        ws.append(r)
    ws.merge_cells("A1:G1")
    first = 3
    for k in range(len(rows["xlsx"]) // 3):  # the diagnosis merged over pairs of rows, as PIs do
        r0 = first + 3 * k
        ws.cell(r0 + 1, 4).value = None
        ws.merge_cells(start_row=r0, start_column=4, end_row=r0 + 1, end_column=4)
        planted["merged"] += 1
    buf = io.BytesIO()
    wb.save(buf)
    files.append(("候補者リスト.xlsx", buf.getvalue()))
    if rows["sjis"]:
        s = io.StringIO()
        csv.writer(s, lineterminator="\r\n").writerows(
            [["カルテ番号", "氏名", "生年月日", "診断", "尿酸値", "単位", "受診日"], *rows["sjis"]]
        )
        files.append(("候補者_sjis.csv", s.getvalue().encode("cp932")))
    if rows["big5"]:
        s = io.StringIO()
        csv.writer(s, lineterminator="\r\n").writerows(
            [["病歷號", "姓名", "出生日期", "性別", "診斷", "尿酸值", "單位", "就診日"], *rows["big5"]]
        )
        files.append(("候選名單_big5.csv", s.getvalue().encode("big5", errors="replace")))
    info = {"rows": {k: len(v) for k, v in rows.items()}, "planted": dict(planted), "patients": pick}
    return files, {m: truth[m] for m in pick}, info


def sc_excel(a: Any, work: Path) -> Result:
    from tb_common.crypto import pid_for_mrn

    res = Result("site-excel")
    z = sizes(a.patients)
    n, nf = z["site-excel"], z["site-feed"]
    s = Stage("the PI's lists: messy Excel, Shift_JIS and Big5 CSV, joined to the feed")
    t = time.perf_counter()
    dirs, feed, _ = synth(work, f"xa:JP:{nf // 2},xb:TW:{nf - nf // 2}")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    files, truth, info = sheets(feed, n)
    w = world(work, work / "lake", sec, a)
    svc = w.svc
    rs = site_ruleset()
    res.block = {"model_calls": 0}
    s0 = Stage("the feed: screening with the run's model, before the lists arrive")
    t0 = time.perf_counter()
    screen_stage(s0, w.box, note_truth(dirs, fd.KEY), res.block, a)
    s0.seconds = time.perf_counter() - t0
    loaded = {}
    for name, data in files:
        out = svc.add_sheet("main", "sheet", name, data, {}, "crc")
        loaded[name] = {k: out[k] for k in ("rows", "patients", "facts", "fixes", "checks", "dropped")}
    fixes = {f["kind"] for f in svc.store.fixes("main")}
    s.check(
        "safe fixes made and listed: era and 民國 dates, full width, units, merged cells, the title row",
        {"era", "minguo", "width", "unit", "merged", "header_row"} <= fixes,
        sorted(fixes),
    )
    s.check(
        "the name columns are dropped",
        all("氏名" in v["dropped"] or "姓名" in v["dropped"] for v in loaded.values()),
        {k: v["dropped"] for k, v in loaded.items()},
    )
    answered = answer_checks(svc, "main")
    mapped = map_codes(svc, "main", {("condition", "痛風"): "M10.9"})
    answered += answer_checks(svc, "main")
    got = patient_states(svc, "main", rs)
    want = {pid_for_mrn(fd.KEY, m): expected_state(tr) for m, tr in truth.items()}
    tw = {pid_for_mrn(fd.KEY, m) for m in info["patients"] if not m.startswith("2")}
    cmp = compare_states(got, want)
    joined = sum(1 for p in want if p in got)
    for label, group in (
        ("Excel and Shift_JIS", [p for p in want if p not in tw]),
        ("Big5 (zh-TW, 民國)", [p for p in want if p in tw]),
    ):
        agree = sum(1 for p in group if got.get(p) == want[p])
        s.check(
            f"{label} rows: every patient joined to the feed and counted as the generator says",
            agree == len(group) and group,
            {"agree": agree, "of": len(group)},
        )
    s.seconds = time.perf_counter() - t
    res.stages += [s0, s]
    # the same SCREEN once the lists are in the hospital's own space (review: D-135 "main needs a batched apply")
    calls0 = llm_calls(w.box)
    t1 = time.perf_counter()
    job, _scr, _cap = screen_once(w.box)
    err = "" if job is None or job.error is None else str(job.error.detail or job.error.message)[:160]
    dup = svc.lake("main").query("SELECT count(*) - count(DISTINCT pid) AS d FROM patient").to_pylist()[0]["d"]
    s.check(
        "XL-02: SCREEN GZQO on the hospital's own space after the lists are published into it is done, one patient "
        "row per pseudonym",
        bool(job and job.state == "done") and dup == 0,
        f"{job.state if job else 'no job'} in {time.perf_counter() - t1:.0f} s; duplicate patient rows {dup} {err}",
    )
    res.block["model_calls"] += llm_calls(w.box) - calls0
    res.block.update(
        {
            "input": f"{n} patients in 3 files over a {nf:,}-patient feed: {info['rows']}",
            "counts": {"files": loaded, "checks_answered": answered, "codes": mapped, "planted": info["planted"]},
            "expected": cmp["expected"],
            "got": cmp["got"],
            "joined": f"{joined} of {len(want)}",
        }
    )
    res.app, res.pages = (
        w.app,
        [("crc", f"/studies/{TRIAL}/week?list=all"), ("crc", f"/site/checks?ws=main&study={SITE_RS}")],
    )
    return res


# ------------------------------------------------------------------------------------------------ charts
def _chart_scenario(a: Any, work: Path, name: str, ws: str, files: bool) -> Result:
    from sitesetup.ocr import TesseractOcr

    res = Result(name)
    n = sizes(a.patients)[name]
    ppl = sc.patients(n, seed=20261109 if not files else 20261110, first=30000001 if not files else 31000001)
    charts = [c for p in ppl for c in p.charts]
    fake = sc.FakeOcr()
    ocr: Any = fake if getattr(a, "ocr", "fake") == "fake" else TesseractOcr()
    s = Stage("charts in: the model proposes facts, nothing counts yet")
    t = time.perf_counter()
    _dirs, feed, _ = synth(work, "cf:JP:60")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    w = world(work, work / "lake", sec, a, ocr=ocr)
    svc = w.svc
    rs = site_ruleset()
    calls0 = llm_calls(w.box, "chart_facts")
    methods: Counter[str] = Counter()
    refused: list[str] = []
    for i, c in enumerate(charts):
        fname, data, pasted = "pasted.txt", c.text.encode("utf-8"), True
        if files:
            kind = ("docx", "pdf", "png", "scan")[i % 4]
            pasted = False
            if kind == "docx":
                fname, data = "chart.docx", sc.docx(c)
            elif kind == "pdf":
                fname, data = "chart.pdf", sc.pdf(c)
            else:
                fake.remember(c)
                fname, data = ("scan.png", sc.png(c)) if kind == "png" else ("scan.pdf", sc.scan_pdf(c))
        try:
            out = svc.add_chart(ws, c.chart_no, fname, data, "crc", c.lang, pasted=pasted)
            methods[out["method"]] += 1
        except Exception as exc:
            refused.append(f"{fname}: {exc}")
    s.check("every chart is read", not refused and sum(methods.values()) == len(charts), refused[:3] or methods)
    if files:
        s.check("Word, PDF text and OCR paths all used", {"docx", "pdf", "ocr"} <= set(methods), dict(methods))
    pid_of = {p.chart_no: svc.pseudonym(p.chart_no) for p in ppl}
    truth = {pid_of[p.chart_no]: p.facts() for p in ppl}
    proposed = svc.store.facts(ws, "proposed")
    got_facts: dict[str, list[dict[str, Any]]] = {}
    for f in proposed:
        got_facts.setdefault(f["pid"], []).append(f)
    scr = sc.score(truth, got_facts)
    from sitesetup import readiness

    rows = readiness.patient_check(svc, ws, rs, TODAY)
    before = {r["pid"]: r["state"] for r in rows}
    prop_ids = {str(f["id"]) for f in proposed}
    blocking = [
        (r["pid"][:8], c["id"], c["verdict"], c["reason"], c["facts"])
        for r in rows
        for c in r["criteria"]
        if c["verdict"] in ("excluded", "not_met")
    ]
    on_proposed = [b for b in blocking if b[2] == "excluded" or any(x.split("-")[-1] in prop_ids for x in b[4])]
    s.check(
        "a proposed fact never excludes before confirmation: no exclusion, no failed criterion rests on one",
        not on_proposed,
        {
            "states": dict(Counter(before.values())),
            "on_proposed": on_proposed[:5],
            "failed_for_lack_of_data": len(blocking),
        },
    )
    s.check(
        "proposed facts alone make nobody ready",
        not [p for p, st in before.items() if st == "ready"],
        Counter(before.values()),
    )
    s.check(
        f"extraction precision >= {FLOORS['precision']}",
        scr["precision"] >= FLOORS["precision"],
        {k: scr[k] for k in ("precision", "recall", "wrong")},
    )
    s.check(
        f"extraction recall >= {FLOORS['recall']}",
        scr["recall"] >= FLOORS["recall"],
        {k: scr[k] for k in ("precision", "recall", "missed")},
    )
    calls = llm_calls(w.box, "chart_facts") - calls0
    s.check("one chart-reading call per chart", calls >= len(charts), (calls, len(charts)))
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    s2 = Stage("the coordinator confirms or rejects each fact; then the patient check counts")
    t = time.perf_counter()
    conf = rej = 0
    for f in proposed:
        ok = sc.matches(truth.get(f["pid"], []), f)
        svc.decide(int(f["id"]), "confirm" if ok else "reject", "crc")
        conf += ok
        rej += not ok
    after = patient_states(svc, ws, rs)
    want: dict[str, str] = {}
    for p in ppl:
        tr = Truth(birth=p.birth.isoformat())
        for f in p.facts():
            if f.domain == "condition":
                tr.dx.add(f.code)
            elif f.domain == "observation" and f.code == sc.URATE:
                tr.urate.append((f.day, float(f.value)))
        want[pid_of[p.chart_no]] = expected_state(tr)
    # a fact the model missed cannot be confirmed: the recount is of what the coordinator could confirm
    seen = {pid: [x for x in got_facts.get(pid, []) if sc.matches(truth[pid], x)] for pid in truth}
    want_seen: dict[str, str] = {}
    for pid, fs in seen.items():
        tr = Truth()
        for x in fs:
            if x["domain"] == "demographic" and x["code"] == "birth_date":
                tr.birth = x["value"]
            elif x["domain"] == "condition":
                tr.dx.add(x["code"])
            elif x["domain"] == "observation" and x["code"] == sc.URATE:
                tr.urate.append((x["day"], float(x["value"])))
        want_seen[pid] = expected_state(tr)
    cmp = compare_states(after, want_seen)
    s2.check("after confirmation the patient check equals the recount of the confirmed facts", cmp["differ"] == 0, cmp)
    full = compare_states(after, want)
    s2.check(
        "confirmed malignancy in past history now excludes; negated and family-history ones never do",
        all(after.get(p) == "not_eligible" for p, st in want_seen.items() if st == "not_eligible"),
        full,
    )
    s2.seconds = time.perf_counter() - t
    res.stages.append(s2)
    res.block = {
        "input": f"{len(ppl)} patients, {len(charts)} charts ({'files: ' + str(dict(methods)) if files else 'pasted'}"
        f"; ja {sum(1 for c in charts if c.lang == 'ja')}, zh-TW {sum(1 for c in charts if c.lang == 'zh-TW')})",
        "counts": {
            "proposed": len(proposed),
            "confirmed": conf,
            "rejected": rej,
            "traps": dict(Counter(x for c in charts for x in c.traps)),
        },
        "expected": full["expected"],
        "got": full["got"],
        "model_calls": calls,
        "extraction": {k: scr[k] for k in ("precision", "recall", "truth", "proposed", "matched", "by_domain")},
        "ocr": getattr(ocr, "name", "?"),
    }
    res.app, res.pages = w.app, [("crc", f"/site/facts?ws={ws}&study={SITE_RS}")]
    return res


def sc_chart_paste(a: Any, work: Path) -> Result:
    return _chart_scenario(a, work, "chart-paste", "charts", files=False)


def sc_chart_files(a: Any, work: Path) -> Result:
    return _chart_scenario(a, work, "chart-files", "files", files=True)


# ------------------------------------------------------------------------------------------------ IT dump
DUMP_DX = {
    "ZG01": ("痛風", "M10.9"),
    "ZI10": ("本態性高血圧症", "I10"),
    "ZE11": ("2型糖尿病", "E11.9"),
    "ZC16": ("胃癌", "C16.9"),
    "ZC50": ("乳癌", "C50.919"),
}
DUMP_LAB = ("3C020000002327101", "尿酸")
DUMP_DRUG = ("3943001F1020", "アロプリノール錠100mg")


def dump(
    n: int, seed: int = 11, first: int = 40000001, plant_undated: int = 3
) -> tuple[bytes, dict[str, Truth], dict[str, Any]]:
    """An IT department's one-time dump (Shift_JIS, one row per record, the hospital's own codes, the record's date)
    of ``n`` synthetic patients, and their truth by chart number. ``plant_undated`` cancer rows carry no date (an old
    diagnosis carried over from a previous system), to show how an undated diagnosis is counted."""
    rng = random.Random(seed)
    undated = 0
    planted: set[str] = set()
    head = [
        "患者番号",
        "性別",
        "生年月日",
        "病名コード",
        "病名",
        "検査コード",
        "検査値",
        "単位",
        "検査日",
        "薬剤コード",
        "薬剤名",
    ]
    rows: list[list[str]] = [head]
    truth: dict[str, Truth] = {}
    for i in range(n):
        no = f"{first + i:08d}"
        birth = date(rng.randint(1940, 2012), rng.randint(1, 12), rng.randint(1, 28))
        sex = rng.choice("MF")
        tr = Truth(birth=birth.isoformat())
        dxs = ["ZG01"] if rng.random() < 0.7 else []
        dxs += [c for c, p in (("ZI10", 0.3), ("ZE11", 0.2), ("ZC16", 0.08), ("ZC50", 0.05)) if rng.random() < p]
        if not dxs:
            dxs = ["ZI10"]
        for k, code in enumerate(dxs):
            tr.dx.add(DUMP_DX[code][1])
            day = TODAY - timedelta(days=rng.randint(10, 700))
            lab = ["", "", "", day.strftime("%Y/%m/%d")]
            adult_gout = "ZG01" in dxs and _age(birth.isoformat(), TODAY) >= 18
            if code.startswith("ZC") and adult_gout and undated < plant_undated:  # an old cancer with no date
                lab[3] = ""
                undated += 1
                planted.add(no)
            if k == 0:
                v = round(rng.uniform(4.5, 10.5), 1)
                tr.urate.append((day.isoformat(), v))
                lab = [DUMP_LAB[0], f"{v}", "mg/dL", day.strftime("%Y/%m/%d")]
            drug = list(DUMP_DRUG) if code == "ZG01" and rng.random() < 0.5 else ["", ""]
            rows.append(
                [no, sex, birth.strftime("%Y/%m/%d"), code, DUMP_DX[code][0], lab[0], lab[1], lab[2], lab[3], *drug]
            )
        truth[no] = tr
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue().encode("cp932"), truth, {"rows": len(rows) - 1, "patients": n, "undated": sorted(planted)}


def sc_dump(a: Any, work: Path) -> Result:
    res = Result("it-dump")
    n = sizes(a.patients)["it-dump"]
    s = Stage("IT dump: hospital codes unknown until mapped, then counted")
    t = time.perf_counter()
    _dirs, feed, _ = synth(work, "du:JP:60")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    w = world(work, work / "lake", sec, a)
    svc, rs, ws = w.svc, site_ruleset(), "dump"
    data, truth, info = dump(n)
    out = svc.add_sheet(ws, "dump", "it_dump.csv", data, {}, "crc")
    s.check(
        "every row and patient read",
        out["rows"] == info["rows"] and out["patients"] == n,
        {k: out[k] for k in ("rows", "patients", "facts")},
    )
    before = patient_states(svc, ws, rs)
    pid_of = {no: svc.pseudonym(no) for no in truth}
    minors = {pid_of[no] for no, tr in truth.items() if _age(tr.birth, TODAY) < 18}
    wrong = [p for p, st in before.items() if st == "not_eligible" and p not in minors]
    s.check(
        "until mapped, a local code is unknown (D-130): only the under-18s are not eligible, nobody is ready",
        not wrong and not [p for p, st in before.items() if st == "ready"],
        Counter(before.values()),
    )
    known = {("condition", c): v[1] for c, v in DUMP_DX.items()} | {
        ("observation", DUMP_LAB[0]): sc.URATE,
        ("medication", DUMP_DRUG[0]): "M04AA01",
    }
    mapped = map_codes(svc, ws, known)
    res.finding(
        "MAP-01",
        "suggested standard codes for the dump's local codes (by name) that name another disease",
        "none",
        "; ".join(mapped["wrong_suggestions"]) or "none",
        not mapped["wrong_suggestions"],
    )
    answered = answer_checks(svc, ws)
    after = patient_states(svc, ws, rs)
    undated = {pid_of[no] for no in info["undated"]}
    want = {pid_of[no]: expected_state(tr) for no, tr in truth.items() if pid_of[no] not in undated}
    cmp = compare_states({p: v for p, v in after.items() if p not in undated}, want)
    s.check("mapped once: every patient counted as the generator says", cmp["differ"] == 0, cmp)
    hit = sum(1 for no in info["undated"] if after.get(pid_of[no]) == expected_state(truth[no]))
    res.finding(
        "DUMP-01",
        "a cancer diagnosis row with no date (any time, no window): the patient is excluded",
        f"{len(undated)} of {len(undated)}",
        f"{hit} of {len(undated)} ({Counter(after.get(p) for p in undated)})",
        hit == len(undated),
    )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    res.block = {
        "input": f"Shift_JIS dump, {info['rows']:,} rows of {n:,} patients, {len(DUMP_DX)} local diagnosis "
        "codes, a JLAC10 lab code and a YJ drug code",
        "counts": {"codes": mapped, "checks": answered, "facts": out["facts"]},
        "expected": cmp["expected"],
        "got": cmp["got"],
        "model_calls": 0,
        "note": "no notes in a dump: the patient check is the structured SQL engine",
    }
    res.app, res.pages = w.app, [("crc", f"/site/codes?ws={ws}&study={SITE_RS}")]
    return res


# ------------------------------------------------------------------------------------------------ REDCap and forms
def sc_redcap(a: Any, work: Path) -> Result:
    from fastapi.testclient import TestClient
    from rc_sim.app import create_app, load_projects, register_inproc

    from tools import rc_demo

    res = Result("redcap")
    n = sizes(a.patients)["redcap"]
    s = Stage("REDCap two-way: TrialBox's records out, REDCap's fields back")
    t = time.perf_counter()
    dirs, feed, _ = synth(work, "rc:JP:300")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    sim = create_app()
    register_inproc(sim)
    w = world(work, work / "lake", sec, a)
    api = w.h.bk.study_api
    proj = next(p for p in load_projects().values() if p["project"]["project_id"] == 202)
    page = w.admin.get("/admin/redcap")
    w.admin.post(
        "/admin/redcap",
        data={"csrf": fd._csrf(page.text), "token_ref": "rb", "url": rc_demo.SIM_URL, "token": proj["token"]},
    )
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=list(proj["metadata"][0]))
    wr.writeheader()
    wr.writerows(proj["metadata"])
    api("POST", "/studies/RA-BIO/forms/dictionary", {"csv": buf.getvalue(), "record_field": "rec_id", "by": "crc1"})
    rng = random.Random(5)
    mine = {}
    for i in range(n):
        no = f"RB{2000 + i:04d}"
        mine[no] = {
            "tb_status": str(rng.choice((1, 2, 3))),
            "tb_screen_date": (TODAY - timedelta(days=rng.randint(0, 90))).isoformat(),
        }
        api("PUT", f"/studies/RA-BIO/data/{no}", {"values": mine[no], "by": "crc1"})
    fields = ["icf_dt", "rand_yn", "withdrawn", "tb_status", "tb_screen_date"]
    api(
        "PUT",
        "/studies/RA-BIO/sources/redcap",
        {
            "token_ref": "rb",
            "field_map": {f: f for f in fields},
            "owned": ["icf_dt", "rand_yn", "withdrawn"],
            "key_field": "tb_screening_no",
            "event": "screening_arm_1",
            "dag": "cgmh_linkou",
            "create": True,
            "by": "crc1",
        },
    )
    r1 = api("POST", "/studies/RA-BIO/sync/redcap", {"by": "crc1"})
    simc = TestClient(sim)

    def theirs() -> dict[str, dict[str, str]]:
        r = simc.post("/api/", data={"token": proj["token"], "content": "record", "format": "json", "type": "flat"})
        return {
            x["tb_screening_no"]: x
            for x in r.json()
            if x.get("tb_screening_no") and x.get("redcap_event_name", "screening_arm_1") == "screening_arm_1"
        }

    th = theirs()
    pushed_ok = sum(
        1
        for no, v in mine.items()
        if th.get(no, {}).get("tb_status") == v["tb_status"]
        and th.get(no, {}).get("tb_screen_date") == v["tb_screen_date"]
    )
    s.check("every TrialBox record is in REDCap with its values", pushed_ok == n, (pushed_ok, n, r1.get("pushed")))
    k = max(1, n // 3)
    consent = {}
    for no in sorted(mine)[:k]:
        consent[no] = (TODAY - timedelta(days=rng.randint(0, 30))).isoformat()
        edit = {"rec_id": str(th[no]["rec_id"]), "redcap_event_name": "screening_arm_1", "icf_dt": consent[no]}
        simc.post("/sim/records", json={"project_id": 202, "records": [edit]})
    r2 = api("POST", "/studies/RA-BIO/sync/redcap", {"by": "crc1"})
    data = api("GET", "/studies/RA-BIO/data")["records"]
    back = sum(
        1
        for no, d in consent.items()
        if any(v.get("value") == d for kk, v in (data.get(no) or {}).items() if kk.endswith("icf_dt"))
    )
    s.check("REDCap's consent dates read back into TrialBox", back == k, (back, k))
    s.check("no conflict: each side writes only its own fields", not r2.get("conflicts"), r2.get("conflicts"))
    # review B-03: the same longitudinal project linked with no event set; values must survive two syncs
    api("POST", "/studies/RA-COH/forms/dictionary", {"csv": buf.getvalue(), "record_field": "rec_id", "by": "crc1"})
    longi = {f"RL{3000 + i}": {"tb_status": "2", "tb_screen_date": TODAY.isoformat()} for i in range(5)}
    for no, vals in longi.items():
        api("PUT", f"/studies/RA-COH/data/{no}", {"values": vals, "by": "crc1"})
    api(
        "PUT",
        "/studies/RA-COH/sources/redcap",
        {
            "token_ref": "rb",
            "field_map": {f: f for f in fields},
            "owned": ["icf_dt", "rand_yn", "withdrawn"],
            "key_field": "tb_screening_no",
            "event": "",
            "dag": "cgmh_linkou",
            "create": True,
            "by": "crc1",
        },
    )
    for _ in range(2):
        try:
            api("POST", "/studies/RA-COH/sync/redcap", {"by": "crc1"})
        except Exception as exc:  # the sync refusing is also an answer to B-03
            longi_err = str(exc)[:160]
            break
    else:
        longi_err = ""
    r = simc.post("/api/", data={"token": proj["token"], "content": "record", "format": "json", "type": "flat"})
    kept = sum(
        1
        for no, v in longi.items()
        if any(
            x.get("tb_screening_no") == no
            and x.get("tb_status") == v["tb_status"]
            and x.get("tb_screen_date") == v["tb_screen_date"]
            for x in r.json()
        )
    )
    s.check(
        "B-03 (D-142): a longitudinal REDCap project linked with no event keeps TrialBox's values after two syncs",
        kept == len(longi) and not longi_err,
        f"{kept} of {len(longi)} kept{'; ' + longi_err if longi_err else ''}",
    )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    s2 = Stage("built-in forms: records entered in TrialBox, exported as ODM")
    t = time.perf_counter()
    page = w.crc.get(f"/studies/{TRIAL}/forms")
    w.crc.post(f"/studies/{TRIAL}/forms/builtin", data={"csrf": fd._csrf(page.text)})
    nb = max(5, n // 2)
    for i in range(nb):
        api(
            "PUT",
            f"/studies/{TRIAL}/data/{TRIAL}-{9000 + i}",
            {
                "values": {
                    "ic_date": (TODAY - timedelta(days=i % 30)).isoformat(),
                    "ic_version": "v2.1",
                    "ic_copy": "1",
                    "ic_by": "KT",
                },
                "by": "crc1",
            },
        )
    got_b = api("GET", f"/studies/{TRIAL}/data")["records"]
    odm = w.crc.get(f"/studies/{TRIAL}/export.odm.xml")
    in_odm = len(re.findall(r"<SubjectData ", odm.text))
    s2.check(
        "every entered record is kept and exported",
        len([r for r in got_b if r.startswith(f"{TRIAL}-9")]) == nb and in_odm >= nb,
        (len(got_b), in_odm, nb),
    )
    mrns = {p["mrn"] for p in _rows(feed / "patient.csv")}
    s2.check("no chart number in REDCap or the export", not any(m in odm.text or m in json.dumps(th) for m in mrns))
    s2.seconds = time.perf_counter() - t
    res.stages.append(s2)
    s3 = Stage("REDCap site: screening with the run's model")
    res.block = {
        "input": f"rc_sim project 202 (longitudinal, DAGs), {n} TrialBox records; {nb} built-in form records",
        "counts": {"pushed": pushed_ok, "consent_back": back, "odm_subjects": in_odm},
        "expected": {"in_redcap": n, "read_back": k, "forms": nb},
        "got": {"in_redcap": pushed_ok, "read_back": back, "forms": in_odm},
        "model_calls": 0,
    }
    t = time.perf_counter()
    screen_stage(s3, w.box, note_truth(dirs, fd.KEY), res.block, a)
    s3.seconds = time.perf_counter() - t
    res.stages.append(s3)
    res.app, res.pages = w.app, [("crc", "/studies/RA-BIO/sources"), ("crc", f"/studies/{TRIAL}/forms")]
    return res


# ------------------------------------------------------------------------------------------------ registry
def sc_registry(a: Any, work: Path) -> Result:
    from criteria_compiler.ctgov import CtGov
    from tb_common import refdata as rd
    from tb_contracts import CtgovSearchRequest

    from tools import refdata_fetch as rf
    from tools.e2e_simple import _no_network

    res = Result("registry")
    s = Stage("offline registry: the pack loaded, trials found with no network")
    t = time.perf_counter()
    _dirs, feed, _ = synth(work, "rg:JP:60")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    w = world(work, work / "lake", sec, a)
    raw = rf.sample_raw(work / "refdata" / "raw")
    studies = json.loads((raw / "ctgov" / "sample.json").read_text(encoding="utf-8"))["studies"]

    def has(st: dict[str, Any], cond: str, country: str) -> bool:
        p = st.get("protocolSection") or {}
        conds = " ".join((p.get("conditionsModule") or {}).get("conditions") or []).lower()
        locs = {x.get("country") for x in (p.get("contactsLocationsModule") or {}).get("locations") or []}
        return cond in conds and country in locs

    want = {
        c: sorted(st["protocolSection"]["identificationModule"]["nctId"] for st in studies if has(st, "gout", c))
        for c in ("Japan", "Taiwan")
    }
    tar = rf.build(raw, work / "refdata", "20261109", sample=True)
    with rd.opened(tar) as pack:
        rd.verify(pack)
        with rd.RefStore() as st:
            loaded = st.load(pack, by="complete_run")
    ct = CtGov(mode="offline")
    got = {}
    with _no_network():
        for c in ("Japan", "Taiwan"):
            got[c] = sorted(x.nct_id for x in ct.search(CtgovSearchRequest(condition="gout", locations=[c])).studies)
    s.check(
        "trials by condition and site country = the recount of the pack's raw records",
        got == want,
        {"want": want, "got": got},
    )
    s.check("every record of the sample is loaded", loaded.counts.get("ctgov") == len(studies), loaded.counts)
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    res.block = {
        "input": f"reference data pack sample ({len(studies)} CT.gov records and five other sources)",
        "counts": dict(loaded.counts),
        "expected": want,
        "got": got,
        "model_calls": 0,
        "note": "a registry has no patients: trials are found with no network; no patient model is called",
    }
    res.app, res.pages = w.app, [("admin", "/admin/notice")]
    return res


# ------------------------------------------------------------------------------------------------ the gateway probe
def sc_gateway(a: Any, work: Path) -> Result:
    """One judge call and one chart-reading call through the gateway as an installed box builds it (review A-01:
    the gateway confirms no study step and refuses D3, and install leaves TB_DATA_CLASS empty, so a PHI prompt is
    labelled D3). On the stub the upstream is the in-process stub; on the card it is the VM's two servers."""
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub
    from tb_common.llm import LlmClient, LlmError

    res = Result("gateway")
    s = Stage("installed-box gateway: a judge call and a chart-reading call")
    t = time.perf_counter()
    work.mkdir(parents=True, exist_ok=True)
    saved = os.environ.pop("TB_DATA_CLASS", None)
    env = installed_env(
        work / "audit", a.judge_url if a.model == "pair" else "", a.verifier_url if a.model == "pair" else ""
    )
    upstream = None if a.model == "pair" else TestClient(stub)
    if upstream is not None:
        env["TB_ENV"] = "PRODUCTION"
    out: dict[str, str] = {}
    try:
        from orchestrator.selftest import load_cases

        c = LlmClient("http://unused/v1", "", gateway=gateway_client(env, upstream))
        case = load_cases()[0]  # the box's own self-test case (fictional)
        calls = {
            "judge": ("judge", {k: case[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")}),
            "chart_facts": ("chart_facts", {"text": "診断：痛風", "language": "ja", "language_name": "Japanese"}),
        }
        for name, (pid, var) in calls.items():
            try:
                c.chat_json(pid, var, job_id="probe")
                out[name] = "answered"
            except (LlmError, ValueError) as exc:
                out[name] = f"refused: {str(exc)[:160]}"
            except Exception as exc:  # a template variable the probe does not know is still a reached gateway
                out[name] = f"error before the gateway: {type(exc).__name__}: {str(exc)[:120]}"
    finally:
        if saved is not None:
            os.environ["TB_DATA_CLASS"] = saved
    s.check("the probe ran", bool(out), out)
    for name, got in out.items():
        s.check(
            f"{'A-01' if name == 'judge' else 'GW-02'} (D-142): a {name} call (a PHI prompt) through the installed "
            "box's gateway is answered",
            got == "answered",
            got,
        )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    res.block = {
        "input": "TB_ENV=PRODUCTION, TB_PROFILE=P-PRO6000, no TB_DATA_CLASS (as install.sh leaves it)",
        "counts": {},
        "expected": dict.fromkeys(out, "answered"),
        "got": out,
        "model_calls": 0,
    }
    return res


# ------------------------------------------------------------------------------------------------ real public data
def sc_mimic(a: Any, work: Path) -> Result:
    """MIMIC-IV Clinical Database Demo on FHIR (ODbL 1.0, 100 real de-identified patients; fetched to .cache, never
    committed): the FHIR bulk path, FEAS of the two open-data rulesets, and the cascade S0..S5 with the model path
    of ``tools.cascade_e2e`` (its in-process gateway; the stub)."""
    import gzip
    import subprocess
    import sys

    from tools import cascade_e2e
    from tools import open_data_e2e as od

    res = Result("public-mimic")
    s = Stage("MIMIC-IV FHIR demo: ingest, FEAS, recount")
    t = time.perf_counter()
    if not od.data_available(od.DATA_DIR):
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "fetch_open_data.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=1800,
        )
    s.check(
        "the dataset is here (fetched from PhysioNet, sha256 checked)", od.data_available(od.DATA_DIR), str(od.DATA_DIR)
    )
    if not od.data_available(od.DATA_DIR):
        res.stages.append(s)
        return res
    with gzip.open(od.DATA_DIR / "fhir" / "MimicPatient.ndjson.gz", "rt", encoding="utf-8") as fh:
        recount = sum(1 for line in fh if line.strip())
    rep = od.run(od.DATA_DIR, repro=False)
    s.check(
        "patients in the lake = the patients in the release (recount)",
        rep["patients"] == recount,
        (rep["patients"], recount),
    )
    s.check(
        "FEAS invariants: monotone funnel, counts within the cohort, small cells rounded",
        all(not v for v in rep["invariants"].values()),
        rep["invariants"],
    )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    s2 = Stage("MIMIC-IV FHIR demo: the cascade S0..S5 (EMPULSE)")
    t = time.perf_counter()
    r = cascade_e2e.run_end_to_end(od.DATA_DIR, "EMPULSE", work / "cascade", kind="mimic_fhir", repro=False)
    s2.check(
        "cascade, DL-1 pack and recall certificate: every invariant",
        r.passed,
        [k for k, v in r.checks.items() if not v],
    )
    fun = {k: (v["patients_in"], v["patients_out"]) for k, v in r.stage_counts.items()}
    s2.check("S0 = every patient of the release", fun.get("S0", (0, 0))[0] == recount, fun)
    s2.seconds = time.perf_counter() - t
    res.stages.append(s2)
    res.block = {
        "input": f"MIMIC-IV demo on FHIR v2.1.0: {recount} patients (ODbL 1.0)",
        "counts": rep["ingest"].get("counts", {}),
        "expected": {"patients": recount},
        "got": {"patients": rep["patients"], "cascade": fun},
        "model_calls": r.gateway.get("calls", 0),
        "note": "the cascade's model path is tools.cascade_e2e's in-process gateway over the stub",
    }
    return res


def medtxt_reports(n: int) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """``n`` MedTxt-CR case reports in Japanese (CC BY 4.0, Sociocom NAIST; in .cache, never committed): (id, plain
    text, [(certainty, tagged finding)])."""
    import html as _html

    from tools import medtxt_eval as mt

    if not (mt.CACHE / "Test collection").exists():
        return []
    out = []
    for rid, raw in sorted(mt.articles("CR", "ja").items())[:n]:
        tags = [(c, " ".join(_html.unescape(mt.TAG.sub("", x)).split())) for c, x in mt.DTAG.findall(raw)]
        text = "\n".join(mt.sentences(raw, "ja"))
        out.append((rid, text, tags))
    return out


def sc_medtxt(a: Any, work: Path) -> Result:
    """Real Japanese clinical text pasted as charts: MedTxt-CR case reports. Truth: the corpus's own annotation of
    every disease mention as positive, negative (stated absent) or suspicious. A condition the model proposes whose
    quote holds only a negated mention is a negation error; only a suspected one, an over-reading."""
    res = Result("public-medtxt")
    n = sizes(a.patients)["public-medtxt"]
    s = Stage("MedTxt-CR (ja): case reports pasted, conditions read, negations kept out")
    t = time.perf_counter()
    reports = medtxt_reports(n)
    s.check("the corpus is here", bool(reports), "MedTxt in .cache/medtxt")
    if not reports:
        res.stages.append(s)
        return res
    _dirs, feed, _ = synth(work, "mt:JP:60")
    sec = secrets_dir(work)
    csv_lake(feed, work / "lake", sec)
    w = world(work, work / "lake", sec, a)
    svc, ws = w.svc, "medtxt"
    calls0 = llm_calls(w.box, "chart_facts")
    read = 0
    for i, (_rid, text, _tags) in enumerate(reports):
        try:
            svc.add_chart(
                ws, f"{50000001 + i:08d}", "pasted.txt", text[:20000].encode("utf-8"), "crc", "ja", pasted=True
            )
            read += 1
        except Exception as exc:
            s.check(f"report {i} read", False, str(exc)[:160])
    tally: Counter[str] = Counter()
    bad: list[str] = []
    for i, (rid, _text, tags) in enumerate(reports):
        pid = svc.pseudonym(f"{50000001 + i:08d}")
        pos = {x for c, x in tags if c == "positive" and len(x) >= 2}
        neg = {x for c, x in tags if c == "negative" and len(x) >= 2} - pos
        sus = {x for c, x in tags if c == "suspicious" and len(x) >= 2} - pos
        for f in svc.store.facts(ws, pid=pid):
            if f["domain"] != "condition":
                continue
            q = f.get("quote") or ""
            tally["conditions"] += 1
            if any(x in q for x in pos):
                tally["on_positive_mention"] += 1
            elif any(x in q for x in neg):
                tally["on_negated_mention"] += 1
                bad.append(f"{rid}: {q[:80]}")
            elif any(x in q for x in sus):
                tally["on_suspected_mention"] += 1
            else:
                tally["on_untagged_text"] += 1
        tally["positive_tags"] += len(pos)
        tally["negative_tags"] += len(neg)
    calls = llm_calls(w.box, "chart_facts") - calls0
    s.check("every report read, one call each", read == len(reports) and calls >= read, (read, calls))
    s.check("no proposed condition rests only on a mention the corpus marks negative", not bad, bad[:5])
    res.finding(
        "MT-01",
        "conditions proposed from a mention the corpus marks suspected (疑い)",
        "0",
        tally["on_suspected_mention"],
        tally["on_suspected_mention"] == 0,
    )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    res.block = {
        "input": f"{len(reports)} MedTxt-CR case reports (ja, real clinician text, CC BY 4.0)",
        "counts": dict(tally),
        "expected": {"conditions_on_negated_mentions": 0},
        "got": {"conditions_on_negated_mentions": tally["on_negated_mention"]},
        "model_calls": calls,
    }
    res.app, res.pages = w.app, [("crc", f"/site/facts?ws={ws}&study={SITE_RS}")]
    return res


def sc_trec(a: Any, work: Path) -> Result:
    """TREC Clinical Trials 2021/2022 (NIST topics and qrels, English patient descriptions; trial texts from the NCBI
    corpus of ClinicalTrials.gov records; in .cache, never committed): sampled patient-trial pairs judged criterion by
    criterion, a pair lost when the model blocks one; the qrels say which patients are eligible (2) or excluded (1)."""
    import httpx
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub

    from tools import mlbench, trec_ct_eval
    from tools.trialgpt_compare import Client

    res = Result("public-trec")
    k = sizes(a.patients)["public-trec"]
    s = Stage("TREC CT: real trials, patient descriptions, qrels as truth")
    t = time.perf_counter()
    if not (trec_ct_eval.CACHE / "sample_trials.json").exists():
        s.check("the collection is here", False, str(trec_ct_eval.CACHE))
        res.stages.append(s)
        return res
    pairs, notes, _, _ = trec_ct_eval.dataset()
    pick = [p for p in pairs if p["label"] == "2"][:k] + [p for p in pairs if p["label"] == "1"][:k]
    cps = trec_ct_eval.criterion_pairs(pick)
    clients: list[tuple[Any, str]] = []
    if a.model == "pair":
        for url, name in ((a.judge_url, "local/gemma-4-26b-a4b-nvfp4"), (a.verifier_url, "local/qwen3.5-9b-awq")):
            c = Client(url, os.environ.get("TB_GPU_KEY", ""), work / "responses")
            c.http = httpx.Client(timeout=600.0)
            clients.append((c, name))
    else:
        c = Client("http://stub/v1", "none", work / "responses")
        c.http = TestClient(stub, headers={"X-TB-Prompt-Id": "mlbench_judge"})
        clients.append((c, "stub"))
    answers: dict[str, dict[str, Any]] = {}
    for c, name in clients:
        answers[name] = {p.annotation_id: mlbench.judge(c, name, "en", p, notes[p.patient_id]) for p in cps}
    errors = sum(1 for m in answers.values() for r in m.values() if r.error)
    lost = caught = 0
    for p in pick:
        ids = [f"{p['patient']}|{p['trial']}|{i}" for i in range(len(p["criteria"]))]
        blocked = any(all((answers[m][x].label or "") in mlbench.BLOCKS for m in answers) for x in ids)
        lost += p["label"] == "2" and blocked
        caught += p["label"] == "1" and blocked
    n2 = sum(1 for p in pick if p["label"] == "2")
    n1 = len(pick) - n2
    s.check("every criterion answered", errors == 0, errors)
    if a.model == "pair":
        s.check(
            "eligible patients lost by the pair <= 10 % (VALIDATION §3: 3.1 % on the deployed files)",
            n2 and lost / n2 <= 0.10,
            (lost, n2),
        )
    s.seconds = time.perf_counter() - t
    res.stages.append(s)
    res.block = {
        "input": f"{len(pick)} TREC CT 2021/22 patient-trial pairs ({n2} eligible, {n1} excluded by the "
        f"qrels), {len(cps)} criteria",
        "counts": {"criteria": len(cps), "models": list(answers)},
        "expected": {"eligible_lost": 0, "excluded_caught": n1},
        "got": {"eligible_lost": lost, "excluded_caught": caught},
        "model_calls": len(cps) * len(answers),
        "note": "judged by tools.mlbench's prompt straight to the model (an evaluation path, not the box)",
    }
    return res


RUNNERS: dict[str, Callable[[Any, Path], Result]] = {
    "public-mimic": sc_mimic,
    "public-medtxt": sc_medtxt,
    "public-trec": sc_trec,
    "emr-ssmix2": sc_ssmix2,
    "emr-fhir": sc_fhir,
    "site-excel": sc_excel,
    "chart-paste": sc_chart_paste,
    "chart-files": sc_chart_files,
    "redcap": sc_redcap,
    "it-dump": sc_dump,
    "registry": sc_registry,
    "gateway": sc_gateway,
}
