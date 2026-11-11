"""``trialbox model``: what to do when a model build misbehaves (T-609, OPS-042, RUNBOOK §19).

    python -m tools.trialbox model status
    python -m tools.trialbox model hold --reason "judge quotes the wrong patient, ticket 123"
    python -m tools.trialbox model report --build <build sha or build id> --from 2026-11-01 --to 2026-11-11
    python -m tools.trialbox model release --reason "canary passed on the re-pinned build"

**Hold.** Sets the audited flag ``notes.reading`` (:mod:`tb_common.flags`) to ``off``. Every note-stage call after it
asks no model: the answer is ``unknown`` (not evaluated) and the patient goes to review; no note answer excludes; a run
whose note stage ends under the hold drops the note answers it got before (``orchestrator.scenarios.evaluate``). The
flag is read through its five-second cache before each model call, so a running job stops calling within one step,
without a restart. The coded filters keep running: lists still go out, with every note criterion left to a person.

**Release.** Sets the flag back to ``on``, only when the orchestrator's last pair canary (``<data dir>/selftest.json``,
D-117) passed, checked two different models, is younger than ``TB_CANARY_MAX_AGE_H`` (36 h) and ran *after* the hold.
Run the canary first: admin Models tile, "Run now".

**Report.** The runs and the patients one build touched between two dates, from the records the box already keeps:

* the gateway ledger in the audit trail (``llm.gateway.call``, allowed calls only): the build (``detail.model_sha``,
  ``detail.build_id``), the time and the study label. A call labelled with a job id belongs to that job; a call
  labelled with a ruleset (the cascade) belongs to that ruleset's job that was open at the call's time; any other
  call (the canary, the compiler) is counted as "not tied to a run";
* the job table (``orch.jobs``): type, ruleset, state and dates of each run;
* the candidate pool (``orch.pool``) and the candidate registry (``orch.candidates``): the patients (pseudonyms, never
  a chart number) whose current row came from one of those runs, with the criteria the notes decided.

A patient whose pool row a later run replaced is not listed under the earlier run; the later run is listed if it used
the same build. The report is read-only and holds pseudonyms only: give it to the PI, who re-reviews each patient.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

FLAG = "notes.reading"
CALL_EVENT = "llm.gateway.call"
MAX_AGE_H = 36.0
_JOB_ID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
MIN_SHA_PREFIX = 8


class ModelError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------- hold and release
def _flags(audit_dir: Path | None) -> Any:
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    return Flags(audit=AuditLog(audit_dir or Path(os.environ.get("TB_AUDIT_DIR") or "/data/audit")))


def _actor(given: str | None) -> str:
    if given and given.strip():
        return given.strip()
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:  # no user name in a bare container
        return "cli:operator"


def hold(reason: str, actor: str | None = None, audit_dir: Path | None = None) -> dict[str, Any]:
    """Note reading off (the flag ``notes.reading``), audited with the actor and the reason."""
    flags = _flags(audit_dir)
    if flags.row(FLAG) == "off":
        raise ModelError("note reading is already held")
    return dict(flags.set(FLAG, "off", actor=_actor(actor), reason=reason))


def _held_since(flags: Any) -> datetime | None:
    """When the current hold began (the newest change to off), None when note reading is not held."""
    if flags.row(FLAG) != "off":
        return None
    for e in flags.events(FLAG, limit=50):
        if e.get("new_value") == "off":
            at = e["at"]
            return at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
    return None


def canary_problem(data_dir: Path, since: datetime | None, max_age_h: float, now: float | None = None) -> str | None:
    """Why the last pair canary does not allow a release, or None when it does."""
    path = data_dir / "selftest.json"
    try:
        rep = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"no canary result at {path}: run the canary first (admin Models tile, Run now)"
    if not rep.get("ok"):
        return "the last canary failed: " + "; ".join(rep.get("problems") or [])[:200]
    if not rep.get("pair"):
        return "the last canary checked one model, not the pair"
    at = float(rep.get("at_epoch") or path.stat().st_mtime)
    age_h = ((time.time() if now is None else now) - at) / 3600
    if age_h > max_age_h:
        return f"the last passing canary is {age_h:.0f} h old (at most {max_age_h:.0f} h): run it again"
    if since is not None and at <= since.timestamp():
        return "the last passing canary ran before the hold: run it again on the build you release"
    return None


def release(
    reason: str,
    actor: str | None = None,
    audit_dir: Path | None = None,
    data_dir: Path | None = None,
    max_age_h: float | None = None,
) -> dict[str, Any]:
    """Note reading back on, only after a passing pair canary that ran after the hold."""
    flags = _flags(audit_dir)
    if flags.row(FLAG) != "off":
        raise ModelError("note reading is not held")
    folder = data_dir or Path(os.environ.get("TB_DATA_DIR") or "/data")
    limit = max_age_h if max_age_h is not None else float(os.environ.get("TB_CANARY_MAX_AGE_H") or MAX_AGE_H)
    why = canary_problem(folder, _held_since(flags), limit)
    if why:
        raise ModelError(f"not released: {why}")
    return dict(flags.set(FLAG, "on", actor=_actor(actor), reason=reason))


def status(audit_dir: Path | None = None) -> dict[str, Any]:
    flags = _flags(audit_dir)
    value = flags.row(FLAG)
    since = _held_since(flags)
    return {"flag": FLAG, "value": value or "on (never set)", "held": value == "off",
            "held_since": since.isoformat() if since else None}  # fmt: skip


# ---------------------------------------------------------------------------------------------- the report
@dataclass
class Run:
    job_id: str
    type: str = ""
    ruleset: str | None = None
    state: str = ""
    received_at: str = ""
    updated_at: str | None = None
    calls: int = 0
    first_call: str = ""
    last_call: str = ""
    prompts: set[str] = field(default_factory=set)
    patients: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "type": self.type, "ruleset": self.ruleset, "state": self.state,
                "received_at": self.received_at, "updated_at": self.updated_at, "calls": self.calls,
                "first_call": self.first_call, "last_call": self.last_call, "prompts": sorted(self.prompts),
                "patients": self.patients}  # fmt: skip


def matches(build: str, detail: dict[str, Any]) -> bool:
    """A gateway record answered by ``build``: its build id, or its weights sha256 (a prefix of at least 8)."""
    b = build.strip().lower()
    if not b:
        return False
    if str(detail.get("build_id") or "").lower() == b:
        return True
    sha = str(detail.get("model_sha") or "").lower()
    return len(b) >= MIN_SHA_PREFIX and bool(sha) and sha.startswith(b)


def build_calls(audit_dirs: list[Path], build: str, start: date, end: date) -> list[dict[str, Any]]:
    """The allowed gateway calls of ``build`` with a timestamp in [start, end] (whole days, the box's zone)."""
    out: list[dict[str, Any]] = []
    for folder in audit_dirs:
        for f in sorted(folder.glob("*.jsonl")):
            m = _DAY_FILE.match(f.name)
            # the day before too: an event stamped before midnight and written after it lands in the newer file,
            # and one stamped after midnight may sit in the older one
            if not m or not (start.toordinal() - 1 <= date.fromisoformat(m.group(1)).toordinal() <= end.toordinal()):
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                if CALL_EVENT not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("event") != CALL_EVENT:
                    continue
                d = rec.get("detail") or {}
                if d.get("decision", "allow") != "allow" or not matches(build, d):
                    continue
                if not (start <= date.fromisoformat(str(rec.get("ts", ""))[:10]) <= end):
                    continue
                out.append(rec)
    out.sort(key=lambda r: str(r.get("ts")))
    return out


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _note_criteria(verdicts: Any) -> list[str]:
    out = []
    for v in verdicts if isinstance(verdicts, list) else []:
        ev = (v or {}).get("evidence") or {}
        if ev.get("reason") == "note" or ev.get("opinions"):
            out.append(str(v.get("id")))
    return out


def _runs(calls: list[dict[str, Any]], jobs: dict[str, dict[str, Any]]) -> tuple[dict[str, Run], dict[str, int]]:
    """The calls grouped by the run they belong to, and the count of calls tied to no run, by study label."""
    runs: dict[str, Run] = {}
    loose: dict[str, int] = {}
    for c in calls:
        d = c.get("detail") or {}
        study = str(d.get("study") or "")
        at = _ts(c.get("ts"))
        job_id: str | None = None
        if _JOB_ID.match(study) and study in jobs:
            job_id = study
        elif study and at is not None:  # the cascade labels its calls with the ruleset: the job open at that time
            open_ = []
            for j in jobs.values():
                lo, hi = _ts(j["received_at"]), _ts(j["updated_at"])
                if j["ruleset"] == study and lo is not None and lo <= at and (hi is None or at <= hi):
                    open_.append(j)
            if open_:
                job_id = str(max(open_, key=lambda j: str(j["received_at"]))["job_id"])
        if job_id is None:
            loose[study or "none"] = loose.get(study or "none", 0) + 1
            continue
        j = jobs[job_id]
        run = runs.setdefault(job_id, Run(job_id, j["type"], j["ruleset"], j["state"], j["received_at"],
                                          j["updated_at"]))  # fmt: skip
        run.calls += 1
        run.first_call = run.first_call or str(c.get("ts"))
        run.last_call = str(c.get("ts"))
        if c.get("prompt_version"):
            run.prompts.add(str(c["prompt_version"]))
    return runs, loose


def _patients(tx: Any, runs: dict[str, Run]) -> None:
    """Each run's patients: its rows in the candidate pool, and its registry rows no longer in the pool."""
    ids = sorted(runs)
    marks = ",".join("?" for _ in ids)
    status_of = {(r["ruleset"], r["pid"]): r for r in tx.fetchdicts(
        f"SELECT ruleset, pid, status, source_job FROM candidates WHERE source_job IN ({marks}) ORDER BY ruleset, pid",
        ids)}  # fmt: skip
    pool = tx.fetchdicts(
        f"SELECT ruleset, pid, tier, verdicts, job_id FROM pool WHERE job_id IN ({marks}) ORDER BY ruleset, pid", ids
    )
    for p in pool:
        verdicts = json.loads(p["verdicts"]) if isinstance(p["verdicts"], str) else p["verdicts"]
        reg = status_of.pop((p["ruleset"], p["pid"]), None)
        runs[p["job_id"]].patients.append({"pid": p["pid"], "ruleset": p["ruleset"], "tier": p["tier"],
                                           "note_criteria": _note_criteria(verdicts),
                                           "registry_status": reg["status"] if reg else None})  # fmt: skip
    for r in status_of.values():  # in the registry from this run, no longer in the pool
        runs[r["source_job"]].patients.append({"pid": r["pid"], "ruleset": r["ruleset"], "tier": None,
                                               "note_criteria": [], "registry_status": r["status"]})  # fmt: skip


def report(
    build: str,
    start: date,
    end: date,
    audit_dirs: list[Path],
    db_url: str | None = None,
) -> dict[str, Any]:
    """The runs and the patients ``build`` touched between ``start`` and ``end`` (both days included)."""
    if not build.strip():
        raise ModelError("name the build: its sha256 (at least 8 characters) or its build id")
    if end < start:
        raise ModelError("--to is before --from")
    calls = build_calls(audit_dirs, build, start, end)
    from orchestrator.db import JobDB

    db = JobDB(db_url)
    try:
        with db.tx() as tx:
            rows = tx.fetchdicts("SELECT job_id, type, state, ruleset, received_at, updated_at FROM jobs")
            runs, loose = _runs(calls, {str(r["job_id"]): r for r in rows})
            if runs:
                _patients(tx, runs)
    finally:
        db.close()
    ordered = sorted(runs.values(), key=lambda r: (r.first_call, r.job_id))
    pids = {(p["ruleset"], p["pid"]) for r in ordered for p in r.patients}
    return {
        "build": build,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "calls": len(calls),
        "runs": [r.as_dict() for r in ordered],
        "patients": len(pids),
        "calls_not_tied_to_a_run": dict(sorted(loose.items())),
        "note": "pseudonyms only; the PI re-reviews each patient (RUNBOOK §19). A patient whose pool row a later run "
        "replaced is listed under that later run only if it used the same build.",
    }


def render(rep: dict[str, Any]) -> str:
    lines = [
        f"# Runs and patients of build {rep['build']}",
        "",
        f"{rep['from']} to {rep['to']}: {rep['calls']} model calls, {len(rep['runs'])} runs, "
        f"{rep['patients']} patients.",
        "",
        "| Run (job) | Type | Ruleset | State | Received | Calls | Patients |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rep["runs"]:
        lines.append(f"| {r['job_id']} | {r['type']} | {r['ruleset'] or ''} | {r['state']} | {r['received_at']} | "
                     f"{r['calls']} | {len(r['patients'])} |")  # fmt: skip
    for r in rep["runs"]:
        if not r["patients"]:
            continue
        lines += ["", f"## {r['job_id']}", "", "| Patient (pseudonym) | Ruleset | Tier | Note criteria | Registry |",
                  "| --- | --- | --- | --- | --- |"]  # fmt: skip
        for p in r["patients"]:
            lines.append(f"| {p['pid']} | {p['ruleset']} | {p['tier'] or ''} | {', '.join(p['note_criteria'])} | "
                         f"{p['registry_status'] or ''} |")  # fmt: skip
    if rep["calls_not_tied_to_a_run"]:
        lines += ["", "Calls not tied to a run (canary, compiler, other): "
                  + ", ".join(f"{k} {v}" for k, v in rep["calls_not_tied_to_a_run"].items())]  # fmt: skip
    lines += ["", rep["note"], ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- command line
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trialbox model", description="model misbehaviour procedure (RUNBOOK §19)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="is note reading held?")
    h = sub.add_parser("hold", help="note reading off: note answers never exclude, no note-stage model call")
    h.add_argument("--reason", required=True)
    h.add_argument("--actor", default=None)
    rl = sub.add_parser("release", help="note reading on again; needs a passing pair canary run after the hold")
    rl.add_argument("--reason", required=True)
    rl.add_argument("--actor", default=None)
    rl.add_argument("--data-dir", type=Path, default=None, help="the orchestrator's data folder (TB_DATA_DIR)")
    rp = sub.add_parser("report", help="the runs and patients one build touched between two dates")
    rp.add_argument("--build", required=True, help="the build's weights sha256 (8 characters or more) or build id")
    rp.add_argument("--from", dest="start", type=date.fromisoformat, default=None, help="first day (default: today)")
    rp.add_argument("--to", dest="end", type=date.fromisoformat, default=None, help="last day (default: today)")
    rp.add_argument("--json", action="store_true")
    rp.add_argument("--out", type=Path, default=None, help="write the report here instead of printing it")
    for p in (sub.choices["status"], h, rl, rp):
        p.add_argument("--audit-dir", type=Path, action="append", default=None,
                       help="the audit folder (TB_AUDIT_DIR); report: repeat for the gateway's own")  # fmt: skip
    a = ap.parse_args(argv)
    audit = a.audit_dir[0] if a.audit_dir else None
    try:
        if a.cmd == "status":
            print(json.dumps(status(audit), indent=1))
            return 0
        if a.cmd == "hold":
            res = hold(a.reason, a.actor, audit)
            print(f"note reading held (event {res['event']}): every service stops note-stage calls within seconds")
            return 0
        if a.cmd == "release":
            res = release(a.reason, a.actor, audit, a.data_dir)
            print(f"note reading released (event {res['event']})")
            return 0
        today = date.today()
        dirs = a.audit_dir or [Path(os.environ.get("TB_AUDIT_DIR") or "/data/audit")]
        rep = report(a.build, a.start or today, a.end or a.start or today, dirs)
        text = json.dumps(rep, indent=1, ensure_ascii=False) if a.json else render(rep)
        if a.out:
            a.out.write_text(text, encoding="utf-8")
            print(f"wrote {a.out}: {len(rep['runs'])} runs, {rep['patients']} patients")
        else:
            print(text)
        return 0
    except (ModelError, ValueError, LookupError) as exc:
        print(f"model {a.cmd}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
