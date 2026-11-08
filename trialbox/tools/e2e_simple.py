"""``e2e_simple``: the one build gate (SRS FR-OPS-11, TB-PLAN-02 "How it is tested", TB-DS-04 §3.4.1, D-111).

One synthetic hospital (the ``ci`` profile: two sites of 2,500 patients, notes in JA, zh-TW and EN), stub model, no
network, no secrets, run in process:

    criteria pasted -> FEAS report (funnel) -> the investigator approves -> SCREEN -> the list (GZQO) and the cohort
    list (GOUT-COH) -> marks -> N1/N2 mail -> REDCap simulator record -> Run now -> screening log (HTML and XLSX)

and each stage is checked against something it did not compute itself: the generator's own counts, a recount from
the hospital CSVs, the sent mail, the hash-chained audit log and a byte-identical re-run of the FEAS and SCREEN jobs.

    python -m tools.e2e_simple [--dir DIR] [--lang ja|zh-TW|en] [--json]      # exit 0 = every check passed
    make e2e-simple

``tests/integration/test_e2e_simple.py`` runs the same function under pytest; ``.github/workflows/trialbox-e2e.yml``
runs it on every pull request that touches ``trialbox/``.
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
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402
from tools import list_demo as ld  # noqa: E402
from tools import rc_demo  # noqa: E402

TRIAL, COHORT = ld.TRIAL, ld.COHORT
GOUT = ("M10", "M1A")  # GZQO-INC-02 / GOUT-COH-INC-01 value set (ICD-10-CM)
BUDGET_S = 15 * 60  # TB-DS-04 §3.4.1: the whole run within 15 minutes


@dataclass
class Stage:
    name: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    seconds: float = 0.0

    def check(self, what: str, ok: Any, detail: Any = "") -> None:
        self.checks.append((what, bool(ok), str(detail)[:300]))

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.checks)


def _age(birth: str, ref: date) -> int:
    b = date.fromisoformat(birth)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def _json_output(box: Any, job: Any, prefix: str) -> dict[str, Any]:
    out = next(
        o
        for o in job.outputs or []
        if o.filename.startswith(prefix) and o.filename.endswith(".json") and not o.filename.endswith(".raw.json")
    )
    data: dict[str, Any] = json.loads(box.store.get(out.minio_key))
    return data


def _mail_text(sent: Any) -> str:
    """Subject, every text part and every plain attachment of one sent mail (what a recipient can read)."""
    parts = [str(sent.subject)]
    for part in sent.msg.walk():
        if part.is_multipart():
            continue
        data = part.get_payload(decode=True) or b""
        if part.get_content_maintype() == "text" or (part.get_filename() or "").endswith((".csv", ".html", ".txt")):
            parts.append(data.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(parts)


def _audit(box: Any) -> list[dict[str, Any]]:
    """Every record of the hash-chained audit log as written (the console's audit page shows a filtered view)."""
    out: list[dict[str, Any]] = []
    for path in sorted(Path(box.audit_dir).glob("*.jsonl")):
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _done(box: Any, type_: str, ruleset: str) -> list[Any]:
    return [j for j in box.orch.db.find(type_=type_, ruleset=ruleset, state="done", limit=50)]


def run(work: Path, password: str, lang: str = "ja") -> dict[str, Any]:
    """Run the whole path once in ``work`` (must be empty or absent); return the stages and the timings."""
    from console.i18n import CATALOGUES
    from openpyxl import load_workbook
    from orchestrator.rerun import rerun
    from tb_common.audit import verify

    t0 = time.perf_counter()
    res = rc_demo.run(work, password, lang)  # FEAS -> approve -> SCREEN -> marks -> mail -> REDCap -> log
    t_chain = time.perf_counter() - t0
    lst = res["list"]
    box, app, pi, crc = lst["box"], res["app"], lst["pi"], res["crc"]
    h = app.state.helpers
    cat = CATALOGUES[lang]
    stages: list[Stage] = []
    hosp = work / "hospital"
    patients = list(csv.DictReader((hosp / "patient.csv").open(encoding="utf-8")))
    mrns = {p["mrn"] for p in patients}
    names = {p["name"] for p in patients if p["name"]}

    # ---------------------------------------------------------------- stage 0: data in
    s = Stage("0 data in")
    t = time.perf_counter()
    synth = json.loads((work / "synth" / "summary.json").read_text(encoding="utf-8"))
    s.check("generator rate checks", not synth["failures"] and synth["rate_cells"]["fail"] == 0, synth["rate_cells"])
    want = {"patient": 0, "note": 0, "encounter": 0}
    for site in synth["sites"]:
        meta = json.loads((work / "synth" / site["dir"] / "meta.json").read_text(encoding="utf-8"))
        for k in want:
            want[k] += int(meta["counts"][k])
    lake = box.orch.services.lake

    def q(sql: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = lake.query(sql).to_pylist()
        return rows

    got = {
        k: int(q(f"SELECT count(*) AS n FROM {t}")[0]["n"])
        for k, t in (("patient", "patient"), ("note", "document"), ("encounter", "encounter"))
    }
    s.check("lake counts = generator counts (patients, notes, encounters)", got == want, f"lake {got} generator {want}")
    tables = (
        "patient",
        "encounter",
        "condition",
        "observation",
        "medication",
        "document",
        "document_chunk",
        "appointment",
        "claim",
        "consent",
        "procedure",
        "report",
        "practitioner",
    )
    cols = {tb: set(lake.query(f"SELECT * FROM {tb} LIMIT 1").column_names) for tb in tables}
    bad = {
        tb: sorted(c & {"mrn", "id_no", "phone", "address"}) for tb, c in cols.items() if c & {"mrn", "id_no", "phone"}
    }
    s.check("no chart number, ID or phone column in the lake", not bad and "name" not in cols["patient"], bad)
    pids = {r["pid"] for r in q("SELECT pid FROM patient")}
    s.check("lake keys are pseudonyms, never chart numbers", not pids & mrns, len(pids & mrns))
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 1: FEAS report
    s = Stage("1 feasibility report")
    t = time.perf_counter()
    feas = _done(box, "FEAS", TRIAL)
    s.check("a finished FEAS job for GZQO", bool(feas), [j.job_id for j in feas])
    fj = feas[0]
    names_out = sorted(o.filename for o in fj.outputs or [])
    s.check("PDF, XLSX and JSON report", all(any(n.endswith(x) for n in names_out) for x in (".pdf", ".xlsx", ".json")))
    rep = _json_output(box, fj, "feasibility_")
    raw = json.loads(box.store.get(next(o.minio_key for o in fj.outputs or [] if o.filename.endswith(".raw.json"))))
    ref = date.fromisoformat(rep["snapshot"])
    adults = {p["mrn"] for p in patients if _age(p["birth_date"], ref) >= 18}
    gout = {
        r["mrn"] for r in csv.DictReader((hosp / "diagnosis.csv").open(encoding="utf-8")) if r["icd10"].startswith(GOUT)
    }
    s.check("start = every patient seen in 36 months", raw["start_n"] == len(patients), raw["start_n"])
    s.check(
        "INC-01 age >= 18 = recount from patient.csv",
        raw["remaining"]["GZQO-INC-01"] == len(adults),
        (raw["remaining"]["GZQO-INC-01"], len(adults)),
    )
    s.check(
        "INC-02 gout dx = recount from diagnosis.csv",
        raw["remaining"]["GZQO-INC-02"] == len(adults & gout),
        (raw["remaining"]["GZQO-INC-02"], len(adults & gout)),
    )
    rem = [row["remaining"] for row in rep["funnel"]]
    s.check("funnel never grows", all(a >= b for a, b in itertools.pairwise(rem)), rem)
    prov = rep.get("provenance") or {}
    need = (
        "study",
        "ruleset_version",
        "snapshot",
        "data_sources",
        "model_summary",
        "prompt_versions",
        "run_date",
        "clock",
        "job_id",
        "language",
    )
    s.check("FR-REP-01 provenance block", all(k in prov for k in need) and prov.get("job_id") == fj.job_id, prov)
    s.check(
        "FEAS ran without a model (D-101)", prov.get("models") == [] and "no model" in str(prov.get("model_summary"))
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 2: approval
    s = Stage("2 investigator approval")
    t = time.perf_counter()
    approved = [r for r in h.bk.audit(None, 5000) if r.event == "console.approve_all"]
    s.check(
        "both studies approved by the investigator",
        len(approved) == 2 and {r.actor for r in approved} == {"console:pi"},
        [(r.ruleset, r.actor) for r in approved],
    )
    job_id = fj.job_id
    page = crc.get(f"/pilot/jobs/{job_id}/approval")
    r = crc.post(f"/pilot/jobs/{job_id}/approve", data={"csrf": fd._csrf(page.text) or ""}, follow_redirects=False)
    s.check("a coordinator's approve is refused (403, FR-AUTH-13)", r.status_code == 403, r.status_code)
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 3: SCREEN
    s = Stage("3 screening")
    t = time.perf_counter()
    sj = _done(box, "SCREEN", TRIAL)[0]
    scr = _json_output(box, sj, "screen_")
    j = scr["judging"]
    s.check("stub model ran, single judge", j["judge_model"] == "stub" and j["verifier_model"] is None, j)
    s.check("no note-based exclusion without two models agreeing", j["note_block"] == "never" and not j["may_block"], j)
    fun = dict((k, v) for k, v in scr["funnel"])
    s.check("funnel S0 >= S1 >= S3 >= S4 > 0", fun["S0"] >= fun["S1"] >= fun["S3"] >= fun["S4"] > 0, fun)
    s.check("listed = high + review", scr["listed"] == scr["tiers"]["high"] + scr["tiers"]["review"], scr["tiers"])
    sp = scr.get("provenance") or {}
    s.check(
        "FR-REP-01 provenance names the model and prompt",
        sp.get("models") == ["stub"] and sp.get("prompt_versions"),
        sp,
    )
    s.check(
        "cohort list for GOUT-COH (no contact step)",
        lst["cohort_new"] > 0 and 'data-testid="mark-' not in lst["cohort_html"],
        lst["cohort_new"],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 4: list, marks, mail
    s = Stage("4 list, marks and mail")
    t = time.perf_counter()
    picks = lst["picks"]
    # the investigator changes their mind on the third patient: not_now -> approach (the history keeps both)
    third = picks[2]["pid"]
    page = pi.get(f"/studies/{TRIAL}/week?list=all&pid={third}")
    r = pi.post(
        f"/studies/{TRIAL}/patients/{third}/mark",
        data={"csrf": fd._csrf(page.text), "mark": "approach", "back": "list:all"},
        follow_redirects=False,
    )
    s.check("replacing a mark is accepted", r.status_code == 303, r.status_code)
    hist = [m.mark for m in h.store.mark_history(TRIAL, third)]
    s.check("mark history keeps the replaced mark", hist[-2:] == ["not_now", "approach"], hist)
    mails = lst["mails"]
    s.check("N1 and N2 mail sent", len(mails) >= 2, [m.subject for m in mails])
    body = "\n".join(_mail_text(m) for m in mails)
    leaked = sorted(m for m in mrns if re.search(rf"(?<!\d){m}(?!\d)", body))
    s.check("mail carries no chart number", not leaked, leaked[:3])
    s.check("mail carries no patient name", not [n for n in names if n in body][:1])
    s.check("mail carries no screening number", lst["screening_no"] not in body, lst["screening_no"])
    s.check(
        "the PI's marked patients appear in the mail by pseudonym",
        all(f"{p['pid'][:8]}" in body for p in picks),
        [p["pid"][:8] for p in picks],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- stage 7: REDCap and the screening log
    s = Stage("7 REDCap read-back and screening log")
    t = time.perf_counter()
    s.check("S36 test connection", res["s36_ok"])
    s.check(
        "candidate -> consented -> enrolled",
        res["before"] == cat["registry.status.candidate"]
        and res["after_consent"].startswith(cat["registry.status.consented"])
        and res["after_enrol"].startswith(cat["registry.status.enrolled"]),
        (res["before"], res["after_consent"], res["after_enrol"]),
    )
    s.check("sponsor subject number shown", res["subject_shown"])
    x = crc.get(f"/studies/{TRIAL}/screening-log.xlsx")
    ok_x = x.status_code == 200 and x.content[:2] == b"PK"
    rows: list[list[Any]] = []
    if ok_x:
        ws = load_workbook(io.BytesIO(x.content), read_only=True).active
        rows = [list(r) for r in ws.iter_rows(values_only=True)] if ws is not None else []
    s.check("screening log exports as XLSX", ok_x and len(rows) >= 2, x.status_code)
    s.check(
        "the log row is consented/enrolled",
        any(res["screening_no"] in [str(c) for c in r] and any("enrol" in str(c) for c in r) for r in rows[1:]),
        rows[1:3],
    )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- audit (FR-AUD-01a/b/e)
    s = Stage("audit")
    t = time.perf_counter()
    reason = "consent"
    approached = picks[0]["pid"]
    page = pi.get(f"/studies/{TRIAL}/patients/{approached}")
    r = pi.post(f"/studies/{TRIAL}/patients/{approached}/reveal", data={"csrf": fd._csrf(page.text), "reason": reason})
    s.check("the investigator reveals one chart number", r.status_code == 200, r.status_code)
    recs = _audit(box)
    ev = [r["event"] for r in recs]

    def det(r: dict[str, Any]) -> dict[str, Any]:
        d: dict[str, Any] = r.get("detail") or {}
        return d

    for jb in (fj, sj):
        seen = [det(r).get("to") for r in recs if r["event"] == "job.state" and r.get("job_id") == jb.job_id]
        s.check(f"01a: {jb.type} state changes in the audit", {"received", "done"} <= set(seen), seen)
        outs = {det(r).get("filename") for r in recs if r["event"] == "output" and r.get("job_id") == jb.job_id}
        s.check(
            f"01a: every {jb.type} output file in the audit", {o.filename for o in jb.outputs or []} <= outs, len(outs)
        )
    rv = [r for r in recs if r["event"] == "console.reveal_patient" and det(r).get("pid") == approached]
    s.check(
        "01b: reveal with user, study, pid, reason and time",
        bool(rv)
        and rv[-1].get("actor") == "console:pi"
        and rv[-1].get("ruleset") == TRIAL
        and det(rv[-1]).get("reason") == reason
        and bool(rv[-1].get("ts")),
        rv[-1] if rv else None,
    )
    s.check(
        "01b: the box side records the same reveal",
        any(r["event"] == "screen.reveal" and det(r).get("pid") == approached for r in recs),
    )
    marks = [r for r in recs if r["event"] == "console.pi_mark"]
    s.check("01e: every investigator mark (3 + 1 replaced)", len(marks) >= 4, len(marks))
    s.check("01e: the coordinator's contact outcome", "console.contact_outcome" in ev)
    changes = [c for r in recs if r["event"] == "redcap.read" for c in det(r).get("status_changes", [])]
    s.check(
        "01e: registry status changes from REDCap, by pseudonym",
        [c["to"] for c in changes][-2:] == ["consented", "enrolled"] and not any(c["pid"] in mrns for c in changes),
        changes,
    )
    chain = verify(box.audit_dir)
    s.check("hash chain verifies", chain.ok, chain.errors[:3])
    trail = "\n".join(json.dumps(r, ensure_ascii=False) for r in recs)
    s.check("no patient name in the audit", not [n for n in names if n in trail][:1])
    s.seconds = time.perf_counter() - t
    stages.append(s)

    # ---------------------------------------------------------------- FR-REP-02: byte-identical re-run
    s = Stage("re-run (FR-REP-02)")
    t = time.perf_counter()
    from tb_contracts import JobCreate

    # the pasted-criteria FEAS job also compiled and wrote the ruleset (a side effect, never repeated): re-run the
    # report as the investigator would re-request it, on the approved version
    again = box.orch.create(JobCreate(type="FEAS", ruleset=TRIAL, requested_by="pi@hospa.test"))
    box.orch.drain()
    again = box.orch.db.get(again.job_id)
    s.check("FEAS on the approved ruleset", again is not None and again.state == "done", again and again.error)
    for jb in [x for x in (again, sj) if x is not None]:
        rr = rerun(box.orch, jb.job_id)
        s.check(
            f"{jb.type} re-run byte-identical", rr.identical, [f for f in rr.files if not f["same"]][:3] or rr.error
        )
    s.seconds = time.perf_counter() - t
    stages.append(s)

    total = time.perf_counter() - t0
    budget = Stage("runtime")
    budget.check(f"whole run within {BUDGET_S // 60} min", total <= BUDGET_S, f"{total:.1f} s")
    stages.append(budget)
    return {
        "ok": all(st.ok for st in stages),
        "stages": stages,
        "seconds": round(total, 1),
        "chain_seconds": round(t_chain, 1),
        "jobs": {"feas": fj.job_id, "screen": sj.job_id},
        "result": res,
    }


def report(out: dict[str, Any]) -> str:
    lines = []
    for st in out["stages"]:
        lines.append(f"{'PASS' if st.ok else 'FAIL'}  {st.name}  ({st.seconds:.1f} s)")
        for what, ok, detail in st.checks:
            lines.append(f"   {'ok ' if ok else 'BAD'} {what}" + ("" if ok else f"  -> {detail}"))
    lines.append(
        f"e2e_simple {'PASSED' if out['ok'] else 'FAILED'} in {out['seconds']} s (chain {out['chain_seconds']} s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_E2E_DIR", "/tmp/tb-e2e-simple")))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--json", type=Path, help="also write the checks as JSON here")
    a = ap.parse_args(argv)
    import logging

    logging.disable(logging.INFO)  # the in-process services log every request; the checks are the output
    if a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True)
    out = run(a.dir, os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12), a.lang)
    print(report(out))
    if a.json:
        a.json.write_text(
            json.dumps(
                {
                    "ok": out["ok"],
                    "seconds": out["seconds"],
                    "stages": [
                        {"name": st.name, "ok": st.ok, "seconds": round(st.seconds, 2), "checks": st.checks}
                        for st in out["stages"]
                    ],
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
