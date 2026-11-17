"""The judged-pair store read from a stored run (card H-16, D-1126): what the store did in the run, what a second run
of the same set on the same box would save, and the questions asked twice in one run. Offline: no GPU, no model, no
network.

    python -m tools.public_accuracy.pair_store RUN [RUN ...] [--json OUT]

``RUN`` is read as :mod:`.replay` reads it (a driver's ``.tgz``, unpacked by its safe extractor into a new empty folder
outside the repository; an extracted folder; or a folder of them). Nothing in a run is ever executed.

The store is lane A2's (``orchestrator.judged_store``, D-908, the owner's D-519): SCREEN keeps each model's parsed
answer to a note question, keyed by everything that could change it, and reads it back when the same question is asked
of the same build. What the tool reads:

* **(a) the run's own record.** Each SCREEN report's ``cascade.judged_store`` (``on``, ``read``: note-question calls
  answered from the store, ``live``: asked of a model) and ``metrics.pairs_judged``; the hit rate is
  ``read / (read + live)``, numerator and denominator printed. Beside it, from ``raw-traces.json``, the note-question
  calls that reached the gateway (prompt ``judge@n``, context ``s3_note_judgement`` or ``s4_second_opinion``), by model
  alias, with the schema repairs (a trace whose prompt holds an earlier answer) apart.
* **(b) a second run of the same set on the same box.** Each question of this run whose answer the store would have
  kept (a parsed answer, :func:`orchestrator.judged_store.parsed`, from a build the trace names) is found again, except
  the first question of each model in each job: a model that has not answered live in a job reads nothing (D-908).
  The questions are told apart by the store's key where the run recorded it whole (:func:`store_key`, which calls
  ``JudgedPairs.key`` itself); otherwise by the part of the key the traces hold (:func:`traced_key`) and the parts
  they do not hold are named. Time and US$ are an estimate from this run's own rates, never a measurement.
* **(c) the same question asked again in the same run**, by protocol, in its own job or a later one: the store should
  have answered a repeat once the first answer was kept and the model had answered live in the repeat's job.
* **(d) what it could not tell**, by name.

Exit 0 when the tool ran, whatever the figures; 2 on an input it will not read.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.public_accuracy.replay import Refused, collect, commit

SCHEMA_VERSION = 1
VM_USD_PER_HOUR = 2.74  # the GPU VM's price per hour that card H-16 states for this estimate (D-1126)
#: the cascade's note-question contexts (``matching.cascade.judge``) and the cascade role each is
CONTEXTS = {"s3_note_judgement": "judge", "s4_second_opinion": "second_opinion"}
#: every part of the store's key (``JudgedPairs.key``, D-908) and where a stored run holds it; None: nowhere
KEY_PARTS: tuple[tuple[str, str | None], ...] = (
    ("the patient's pseudonym", None),
    ("the criterion's canonical hash", None),
    ("the criterion's wording", "the trace's prompt input (criterion_text)"),
    ("the note question", "the trace's prompt input (note_question)"),
    ("the exact excerpt set", "the trace's prompt input (excerpts)"),
    # every SCREEN note call is labelled s3_note_judgement (tb_llm/v1_roles.yaml), its S3 or S4 role not traced
    ("the cascade's role (S3 or S4)", None),
    ("the model client (judge or verifier)", "the trace's tb.model_alias"),
    ("the prompt id as the call named it", None),
    ("the prompt file's sha", None),
    ("the output schema named by the call", None),
    ("the build answering the role", "the trace's tb.build_sha"),
    ("the criterion's window", None),
    ("the index date", "the trace's prompt input (index_date)"),
    ("the note mask version", None),
)
#: the parts not recorded that are the same for every question of one commit and build, so equal on a second run of
#: the same set on the same box; the other unrecorded parts differ from question to question
FIXED_BY_THE_BOX = (
    "the prompt id as the call named it",
    "the prompt file's sha",
    "the output schema named by the call",
    "the note mask version",
)
#: the trace attribute that, if a run recorded it, would let :func:`store_key` compute the store's own key: the
#: cascade's ``Asking`` (pid, criterion_hash, window, role, audit) and the call's ``prompt_id`` and ``schema``.
#: No record of the product writes it today (a question for lane A2, D-1126)
ASKING_ATTR = "tb.asking"
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


# ---------------------------------------------------------------- the product's own functions, by import
def is_parsed(output: Any, build: str) -> bool:
    """Whether the store would keep this answer: ``orchestrator.judged_store.parsed`` on the reply as the client
    returns it, and a build named (the store keeps no answer that names none)."""
    from orchestrator.judged_store import parsed
    from tb_common.llm import LlmResult

    data = _json(output)
    if not isinstance(data, dict) or not build:
        return False
    return bool(parsed(LlmResult(data, "judge", 0, "", "local", "", "", 0, 0, 1, build_sha=build)))


def traced_key(c: Call) -> tuple[str, ...]:
    """The part of the store's key a trace holds: the model alias, the build, the served prompt and the question as
    the models saw it (``matching.cascade.judge.question_digest`` over the trace's input, which covers the criterion's
    wording, the note question, the index date and the excerpts)."""
    from matching.cascade.judge import question_digest

    v = c.variables
    digest = question_digest(str(v.get("criterion_text")), str(v.get("note_question")), str(v.get("index_date")),
                             list(v.get("excerpts") or []))  # fmt: skip
    return (c.alias, c.build, c.prompt, digest)


def store_key(c: Call, snapshot: str = "stored-run") -> str | None:
    """The store's own key of this call (``JudgedPairs.key``, called as SCREEN calls it), when the trace carries the
    cascade's question (:data:`ASKING_ATTR`); None when it does not or the product refuses to key it."""
    a = c.asking
    if not isinstance(a, dict):
        return None
    from matching.cascade.judge import ASKING, Asking, question_digest
    from orchestrator.judged_store import JudgedPairs
    from tb_common.llm import LlmResult

    v = c.variables
    try:
        asking = Asking(str(a["pid"]), str(a["criterion_hash"]), (str(a["window"][0]), str(a["window"][1])),
                        audit=bool(a.get("audit", False)), role=str(a.get("role") or c.role),
                        question=question_digest(str(v.get("criterion_text")), str(v.get("note_question")),
                                                 str(v.get("index_date")), list(v.get("excerpts") or [])))  # fmt: skip
        prompt_id, schema = str(a["prompt_id"]), a.get("schema")
    except (KeyError, IndexError, TypeError):
        return None
    store = JudgedPairs(None, lambda: snapshot, lambda: (), lambda: "")
    token = ASKING.set(asking)
    try:
        # the store keys a call only after the role's model has answered live in the job: say it has, with this build
        store.asked(c.label, LlmResult({}, "judge", 0, "", "local", "", "", 0, 0, 1, build_sha=c.build), v)
        return store.key(c.label, None, prompt_id, v, schema)
    finally:
        ASKING.reset(token)


# ---------------------------------------------------------------- reading the records
@dataclass
class Call:
    """One note-question call through the gateway, from one trace."""

    job: str
    alias: str
    role: str  # the trace's context of use, as the cascade's role it names (S3 judge, S4 second_opinion)
    build: str
    prompt: str
    ts: str
    variables: dict[str, Any]
    output: Any
    repair: bool  # a schema repair: the same question sent again with the model's earlier answer
    asking: Any = None
    label: str = "judge"  # the job's model client: judge or verifier
    repairs: list[Call] = field(default_factory=list)

    @property
    def final(self) -> Any:
        return self.repairs[-1].output if self.repairs else self.output


def _json(x: Any) -> Any:
    if isinstance(x, dict):
        return x
    if not isinstance(x, str):
        return None
    with contextlib.suppress(ValueError):
        return json.loads(x)
    m = _FENCE.search(x)
    if m:
        with contextlib.suppress(ValueError):
            return json.loads(m.group(1))
    return None


def _load(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def note_calls(traces: list[dict[str, Any]]) -> tuple[list[Call], Counter[str], int]:
    """The note-question calls of ``raw-traces.json`` (in time order), the other model calls by prompt, and the note
    traces whose input could not be read."""
    calls: list[Call] = []
    other: Counter[str] = Counter()
    unreadable = 0
    for t in sorted(traces, key=lambda t: str(t.get("ts") or "")):
        a = t.get("attributes") or {}
        prompt = str(a.get("tb.prompt") or "")
        ctx = str(a.get("tb.context_of_use") or "")
        if not (prompt.startswith("judge@") and ctx in CONTEXTS):
            other[prompt or "(no prompt)"] += 1
            continue
        raw_msgs = t.get("prompt")
        msgs: list[Any] = raw_msgs if isinstance(raw_msgs, list) else []
        user = next((m for m in msgs if isinstance(m, dict) and m.get("role") == "user"), None)
        variables = _json(str((user or {}).get("content") or ""))
        if not isinstance(variables, dict):
            unreadable += 1
            continue
        calls.append(Call(job=str(a.get("tb.study_id") or ""), alias=str(a.get("tb.model_alias") or ""),
                          role=CONTEXTS[ctx], build=str(a.get("tb.build_sha") or ""), prompt=prompt,
                          ts=str(t.get("ts") or ""), variables=variables, output=t.get("output"),
                          repair=any(isinstance(m, dict) and m.get("role") == "assistant" for m in msgs),
                          asking=a.get(ASKING_ATTR)))  # fmt: skip
    return calls, other, unreadable


def _questions(calls: list[Call], key: Any) -> list[Call]:
    """The questions: each repair is attached to the latest earlier question with the same key in its job."""
    out: list[Call] = []
    last: dict[Any, Call] = {}
    for c in calls:
        k = (c.job, key(c))
        if c.repair and k in last:
            last[k].repairs.append(c)
            continue
        out.append(c)
        last[k] = c
    return out


def _seconds(ts: list[str]) -> float | None:
    try:
        d = sorted(datetime.fromisoformat(x) for x in ts)
    except ValueError:
        return None
    return (d[-1] - d[0]).total_seconds() if len(d) > 1 else None


# ---------------------------------------------------------------- one set
def read_set(name: str, d: Path) -> dict[str, Any]:
    work = d / "work"
    reports: dict[str, dict[str, Any]] = {}
    for f in sorted((work / "screen").glob("*.json")) if (work / "screen").is_dir() else []:
        r = _load(f)
        job = str(((r or {}).get("provenance") or {}).get("job_id") or "")
        if job:
            reports[job] = r
    progress = _load(work / "progress.json") or {}
    jobs: dict[str, dict[str, Any]] = {}
    for rs, row in progress.items() if isinstance(progress, dict) else []:
        if isinstance(row, dict) and row.get("screen_job"):
            jobs[str(row["screen_job"])] = {"protocol": rs, "screen": row.get("screen"),
                                            "metrics": row.get("screen_metrics") or {}}  # fmt: skip
    raw = _load(work / "raw-traces.json")
    traces = raw.get("traces") if isinstance(raw, dict) else raw if isinstance(raw, list) else None
    gw = _load(work / "gateway-audit.json")
    log = work / "services.log"
    faults = sum(1 for x in log.read_text(encoding="utf-8", errors="replace").splitlines()
                 if "judged-pair store" in x) if log.is_file() else None  # fmt: skip
    out: dict[str, Any] = {"set": name, "folder": str(d), "could_not": []}
    cn = out["could_not"].append

    # (a) the run's own record of the store
    per_job: dict[str, dict[str, Any]] = {}
    rec: Counter[str] = Counter()
    for job, r in reports.items():
        c = r.get("cascade") or {}
        js, pj = c.get("judged_store"), (c.get("metrics") or {}).get("pairs_judged") or {}
        row = per_job.setdefault(job, {"protocol": str(r.get("ruleset") or (jobs.get(job) or {}).get("protocol"))})
        row["report"] = True
        row["pairs_judged"] = {k: int(v) for k, v in pj.items()}
        rec["reports"] += 1
        if isinstance(js, dict):
            row["store"] = {
                "on": bool(js.get("on")),
                "read": int(js.get("read") or 0),
                "live": int(js.get("live") or 0),
            }
            rec["store_block"] += 1
            rec["on"] += bool(js.get("on"))
            rec["read"] += row["store"]["read"]
            rec["live"] += row["store"]["live"]
        for k, v in row["pairs_judged"].items():
            rec[f"pairs_{k}"] += v
        verifier = (r.get("judging") or {}).get("verifier_model")
        row["verifier_alias"] = str(verifier) if verifier else None
    if not reports:
        cn("the store's own counts: no SCREEN report (work/screen/*.json) in the run")
    elif rec["store_block"] < rec["reports"]:
        cn(f"the store's own counts: {rec['reports'] - rec['store_block']} of {rec['reports']} SCREEN reports have no "
           "cascade.judged_store block (written from train 43, D-908)")  # fmt: skip
    hit_den = rec["read"] + rec["live"]
    out["recorded"] = {
        "reports": rec["reports"], "with_store_block": rec["store_block"], "store_on": rec["on"],
        "read": rec["read"], "live": rec["live"],
        "hit_rate": {"numerator": rec["read"], "denominator": hit_den,
                     "value": (rec["read"] / hit_den) if hit_den else None},
        "pairs_judged": {k[6:]: v for k, v in sorted(rec.items()) if k.startswith("pairs_")},
        "store_log_lines": faults,
    }  # fmt: skip
    if isinstance(gw, dict):
        judge = {k: v for k, v in (gw.get("calls_by_prompt") or {}).items() if str(k).startswith("judge@")}
        out["recorded"]["gateway_audit_box_wide"] = {"since": gw.get("since"), "judge_calls": judge}

    if not isinstance(traces, list):
        cn("the model calls: no raw-traces.json, so (b) and (c) are not derivable from this run's records")
        out["traced"] = out["second_run"] = out["duplicates"] = None
        out["key"] = None
        return out
    calls, other, unreadable = note_calls(traces)
    if unreadable:
        cn(f"{unreadable} note-question traces whose prompt input could not be read are left out of (b) and (c)")
    for c in calls:  # the job's model client, from the report's verifier alias where there is a report
        v = (per_job.get(c.job) or {}).get("verifier_alias")
        c.label = "verifier" if v and c.alias == v else "judge"
    full = bool(calls) and all(store_key(c) is not None for c in calls)
    key = store_key if full else traced_key
    qs = _questions(calls, key)
    missing = [p for p, where in KEY_PARTS if where is None]
    out["key"] = {
        "by": "the store's own key (JudgedPairs.key)" if full else "the part of the store's key the traces hold",
        "not_recorded": [] if full else missing,
        "not_recorded_and_varying": [] if full else [p for p in missing if p not in FIXED_BY_THE_BOX],
        "index_dates": sorted({str(c.variables.get("index_date")) for c in qs}),
    }
    if not full:
        cn("the store's own key: not computable from this run's records: "
           + ", ".join(out["key"]["not_recorded_and_varying"]) + " are not recorded (and "
           + ", ".join(FIXED_BY_THE_BOX) + " are not recorded but fixed by the box's commit and build); questions are "
           "told apart by the part of the key the traces hold")  # fmt: skip

    by_job: dict[str, list[Call]] = defaultdict(list)
    for q in qs:
        by_job[q.job].append(q)
    aliases = Counter(c.alias for c in calls)
    out["traced"] = {
        "gateway_calls": len(calls), "by_alias": dict(sorted(aliases.items())),
        "by_context": dict(sorted(Counter(c.role for c in calls).items())),
        "questions": len(qs), "schema_repairs": sum(len(q.repairs) for q in qs),
        "jobs": len(by_job), "jobs_without_report": sorted(j for j in by_job if j not in reports),
        "other_calls_by_prompt": dict(sorted(other.items())),
    }  # fmt: skip
    for job, js in by_job.items():
        row = per_job.setdefault(job, {"protocol": (jobs.get(job) or {}).get("protocol") or "?"})
        row["questions"] = len(js)
        row["gateway_calls"] = len(js) + sum(len(q.repairs) for q in js)
    mismatched = sorted(j for j, r in per_job.items() if "store" in r
                        and r["store"]["read"] + r["store"]["live"] != r.get("questions", 0))  # fmt: skip
    out["traced"]["jobs_where_store_count_differs_from_traced_questions"] = mismatched

    # (b) a second run of the same set on the same box, and (c) a question asked again in the same run. Jobs ran one
    # after another (their questions in time order); the store's key names no job, so a later job reads an earlier
    # job's row once its own model has answered live in it (D-908)
    keys = {id(q): key(q) for q in qs}
    kept_in_run = {keys[id(q)] for q in qs if is_parsed(q.final, q.build)}
    hits: Counter[str] = Counter()
    saved_by_job: dict[str, dict[str, Any]] = {}
    dups: dict[str, Counter[str]] = defaultdict(Counter)
    seen: set[Any] = set()
    kept_so_far: set[Any] = set()
    built: dict[str, set[str]] = defaultdict(set)  # job -> the model clients that have answered live in it
    per: dict[str, Counter[str]] = defaultdict(Counter)
    for q in qs:  # in time order
        k, p = keys[id(q)], per_job[q.job]["protocol"]
        if k in seen:
            dups[p]["repeats"] += 1
            dups[p]["in_another_job"] += not any(keys[id(x)] == k for x in by_job[q.job] if x.ts < q.ts)
            dups[p]["store_should_have_answered"] += q.label in built[q.job] and k in kept_so_far
        seen.add(k)
        if q.label in built[q.job] and k in kept_in_run:  # a second run: every row of this run is in the store
            per[q.job]["questions"] += 1
            per[q.job]["gateway_calls"] += 1 + len(q.repairs)
        else:
            per[q.job]["live"] += 1
        if is_parsed(q.final, q.build):
            kept_so_far.add(k)
        if q.build:  # the store keys this model's next questions with the build of its latest live answer
            built[q.job].add(q.label)
    for job, js in by_job.items():
        s = per[job]
        span = _seconds([c.ts for q in js for c in [q, *q.repairs]])
        rate = span / len(js) if span is not None and span > 0 else None
        saved_by_job[job] = {"protocol": per_job[job]["protocol"], "questions": len(js),
                             "saved": s["questions"], "saved_gateway_calls": s["gateway_calls"],
                             "still_live": s["live"], "span_s": span, "s_per_question": rate,
                             "saved_s": s["questions"] * rate if rate is not None else None,
                             "wall_seconds": (jobs.get(job) or {}).get("metrics", {}).get("wall_seconds")}  # fmt: skip
        hits.update(s)
    timed = [r for r in saved_by_job.values() if r["saved_s"] is not None]
    untimed = sum(r["saved"] for r in saved_by_job.values() if r["saved_s"] is None)
    saved_s = sum(r["saved_s"] for r in timed) if timed else None
    out["second_run"] = {
        "questions": len(qs), "saved": hits["questions"], "saved_gateway_calls": hits["gateway_calls"],
        "still_live": hits["live"],
        "share": {"numerator": hits["questions"], "denominator": len(qs),
                  "value": hits["questions"] / len(qs) if qs else None},
        "seconds_per_call_measured": None,
        "estimate": {"saved_s": saved_s, "saved_questions_not_timed": untimed,
                     "usd": saved_s / 3600 * VM_USD_PER_HOUR if saved_s is not None else None,
                     "usd_per_vm_hour": VM_USD_PER_HOUR},
        "by_job": dict(sorted(saved_by_job.items(), key=lambda kv: kv[1]["protocol"])),
    }  # fmt: skip
    cn(
        "the seconds of one model call: not measured (each trace has one timestamp and no duration); the time and US$ "
        "of (b) are an estimate from each job's span of note-question traces (first to last) divided by its questions"
    )
    if untimed:
        cn(f"(b) time: {untimed} saved questions are in jobs with one traced question, whose span is not measurable")
    out["duplicates"] = {
        "repeats": sum(c["repeats"] for c in dups.values()),
        "in_another_job": sum(c["in_another_job"] for c in dups.values()),
        "store_should_have_answered": sum(c["store_should_have_answered"] for c in dups.values()),
        "by_protocol": {p: dict(c) for p, c in sorted(dups.items())},
    }
    if not full and dups:
        cn(
            "(c) repeats are by the traced part of the key: two of them may still be different pairs to the store by "
            "pseudonym, criterion hash, window or the cascade's role (S3 or S4), which the traces do not hold"
        )
    return out


# ---------------------------------------------------------------- the whole run
def analyse(paths: list[Path], scratch: Path) -> dict[str, Any]:
    sets = collect(paths, scratch)
    per = {n: read_set(n, d) for n, d in sorted(sets.items())}

    def total(part: str, k: str) -> int:
        return sum(int((s.get(part) or {}).get(k) or 0) for s in per.values())

    read, live = total("recorded", "read"), total("recorded", "live")
    q, saved = total("second_run", "questions"), total("second_run", "saved")
    secs = [s["second_run"]["estimate"]["saved_s"] for s in per.values()
            if s.get("second_run") and s["second_run"]["estimate"]["saved_s"] is not None]  # fmt: skip
    return {
        "schema_version": SCHEMA_VERSION, **commit(),
        "sets": per,
        "all": {
            "recorded": {"read": read, "live": live,
                         "hit_rate": {"numerator": read, "denominator": read + live,
                                      "value": read / (read + live) if read + live else None}},
            "second_run": {"questions": q, "saved": saved,
                           "saved_gateway_calls": total("second_run", "saved_gateway_calls"),
                           "share": {"numerator": saved, "denominator": q, "value": saved / q if q else None},
                           "estimate": {"saved_s": sum(secs) if secs else None,
                                        "usd": sum(secs) / 3600 * VM_USD_PER_HOUR if secs else None,
                                        "usd_per_vm_hour": VM_USD_PER_HOUR}},
            "duplicates": total("duplicates", "repeats"),
        },
    }  # fmt: skip


# ---------------------------------------------------------------- printing
def _rate(f: dict[str, Any]) -> str:
    v = f.get("value")
    return f"{f['numerator']}/{f['denominator']}" + (f" = {100 * v:.1f}%" if v is not None else " (no calls)")


def _est(e: dict[str, Any]) -> str:
    if e.get("saved_s") is None:
        return "not derivable from this run's records: no job with two or more traced questions"
    return (f"about {e['saved_s']:.0f} s ({e['saved_s'] / 60:.1f} min), US${e['usd']:.2f} at "
            f"US${e['usd_per_vm_hour']:.2f} a VM hour (an estimate from this run's rates, "
            "not a measurement)")  # fmt: skip


def render(r: dict[str, Any]) -> str:
    lines: list[str] = []
    w = lines.append
    w(f"Judged-pair store read from a stored run (schema {r['schema_version']}) on commit {r['commit'][:12]}"
      + (" (working tree differs)" if r.get("working_tree_differs") else ""))  # fmt: skip
    for n, s in r["sets"].items():
        a = s["recorded"]
        w("")
        w(f"set {n}: {s['folder']}")
        w(f"  (a) the run's record: SCREEN reports {a['reports']}, with a store block {a['with_store_block']}, "
          f"store on in {a['store_on']}")  # fmt: skip
        w(f"      note-question calls answered from the store (read) {a['read']}, asked of a model (live) {a['live']}; "
          f"hit rate read/(read+live) = {_rate(a['hit_rate'])}")  # fmt: skip
        w(f"      pairs judged: {', '.join(f'{k} {v}' for k, v in a['pairs_judged'].items()) or 'none recorded'}")
        if a.get("store_log_lines") is not None:
            w(f"      services.log lines naming the store (a read or write fault): {a['store_log_lines']}")
        t = s.get("traced")
        if not t:
            for x in s["could_not"]:
                w(f"  could not: {x}")
            continue
        by = ", ".join([f"{k} {v}" for k, v in t["by_alias"].items()] + [f"context {k} {v}" for k, v in
                                                                          t["by_context"].items()])  # fmt: skip
        w(f"      traced: {t['gateway_calls']} note-question gateway calls ({by}) = {t['questions']} questions + "
          f"{t['schema_repairs']} schema repairs, in {t['jobs']} jobs ({len(t['jobs_without_report'])} with no "
          "report)")  # fmt: skip
        if t["jobs_where_store_count_differs_from_traced_questions"]:
            w(f"      jobs whose store count (read+live) differs from their traced questions: "
              f"{len(t['jobs_where_store_count_differs_from_traced_questions'])}")  # fmt: skip
        b = s["second_run"]
        w(f"  (b) a second run of this set on this box, by {s['key']['by']}, at index date "
          f"{', '.join(s['key']['index_dates']) or '-'}:")  # fmt: skip
        w(f"      questions found again {_rate(b['share'])} (gateway calls saved {b['saved_gateway_calls']}); still "
          f"asked live {b['still_live']} (each model's first question in each job, and answers the store would not "
          "keep)")  # fmt: skip
        w("      seconds per call: not measured; time and money: " + _est(b["estimate"]))
        dd = s["duplicates"]
        w(f"  (c) the same question asked again in this run: {dd['repeats']}"
          + (f" ({dd['in_another_job']} in a later job; the store should have answered "
             f"{dd['store_should_have_answered']} of them by its own rule); by protocol: "
             + ", ".join(f"{p} {c['repeats']}" for p, c in dd["by_protocol"].items())
             if dd["repeats"] else ""))  # fmt: skip
        for x in s["could_not"]:
            w(f"  (d) could not: {x}")
    al = r["all"]
    w("")
    w(f"all sets: hit rate in the run {_rate(al['recorded']['hit_rate'])}; a second run would find again "
      f"{_rate(al['second_run']['share'])} questions ({al['second_run']['saved_gateway_calls']} gateway calls), "
      f"{_est(al['second_run']['estimate'])}; questions asked again in the run {al['duplicates']}")  # fmt: skip
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- command line
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.pair_store", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--json", type=Path, help="write the report here (JSON)")
    ap.add_argument("--scratch", type=Path, help="an empty folder outside the repository (default: a temporary one)")
    a = ap.parse_args(argv)
    os.environ.setdefault("TB_ENV", "DEV")  # the prompt registry's environment, as the replay sets it
    try:
        if a.scratch:
            if a.scratch.exists() and any(a.scratch.iterdir()):
                raise Refused(f"--scratch {a.scratch}: not empty")
            res = analyse(a.runs, a.scratch)
        else:
            with tempfile.TemporaryDirectory(prefix="tb-pairs-") as t:
                res = analyse(a.runs, Path(t))
    except (Refused, tarfile.TarError, OSError) as exc:
        print(f"pair_store: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(res))
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
