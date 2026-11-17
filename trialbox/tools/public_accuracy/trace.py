"""The patient behind each exclusion, read from a stored run (card H-18, D-1134). Offline: no GPU, no model, no network.

    python -m tools.public_accuracy.trace RUN [RUN ...] [--patient KEY] [--ruleset ID] [--ref DAY] [--json OUT]

``RUN`` is read as :mod:`.replay` reads it (a driver's ``.tgz``, unpacked by its safe extractor into a new empty folder
outside the repository; an extracted folder; or a folder of them). Nothing in a run is executed or changed.

The replay counts; this tool names. Two views:

* **exclusions.** Every gold pair labelled ``eligible`` that the box excluded; with ``--patient`` or ``--ruleset``,
  every excluded pair of that patient or protocol, whatever its label. For each: the patient's key and chart number,
  the trial, and each line that failed, with its class, its compiled logic, the verdict's basis and the SCREEN stage
  the basis implies (``coded``: S1, the records; ``notes``, ``pair``, ``single``: S3 or S4, the models; ``person``:
  S5), the quote, whether the benchmark wrote the line (``gold/written.json``), whether a gold criterion row judges
  it, the pair's own criterion labels, and the model calls of the protocol's SCREEN job on that line (each model's
  verdict and quote, and whether the quote is in the excerpts the model was sent).
* **judged.** The note questions of each SCREEN job, grouped by question (the prompt's input), with each model's
  verdicts in order: a schema repair (a call whose prompt holds an earlier answer) and a reply that is no JSON are
  said. With ``--ref`` (the set's build day), each question's first excerpt day is joined to the patients whose
  placed visit falls on it (``site.build``: the i-th patient's visit is ``ref - (7 + i*37 % 300)`` days), at most two
  per day; a day on no visit is counted, which also checks the build day given.

Exit 0 when the tool ran, whatever it found; 2 on an input it will not read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tools.public_accuracy.replay import Refused, collect, commit

SCHEMA_VERSION = 1
#: a verdict's basis (``orchestrator.scenarios.screen_cascade.basis_of``) -> the SCREEN stage it implies
STAGE_OF_BASIS = {"coded": "S1 (the records)", "notes": "S3/S4 (the models)", "pair": "S3/S4 (the models)",
                  "single": "S3/S4 (the models)", "person": "S5 (a person)"}  # fmt: skip
#: the box's two note-judging aliases (``tb_llm`` routing), shortened in a reply pattern
SHORT = {"j-workhorse": "J", "v-verifier": "V"}


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _json(p: Path, default: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).lower()


def _input(trace: dict[str, Any]) -> dict[str, Any] | None:
    """The prompt's input (criterion, question, index date, excerpts) of a note-question trace, else None."""
    prompt = trace.get("prompt") or []
    user = next((m.get("content") for m in prompt if isinstance(m, dict) and m.get("role") == "user"), None)
    if not isinstance(user, str) or "```json" not in user:
        return None
    try:
        got = json.loads(user.split("```json", 1)[1].rsplit("```", 1)[0])
    except (ValueError, IndexError):
        return None
    return got if isinstance(got, dict) else None


def _reply(trace: dict[str, Any]) -> dict[str, Any] | None:
    try:
        out = json.loads(str(trace.get("output")))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _call(trace: dict[str, Any], inp: dict[str, Any] | None) -> dict[str, Any]:
    """One model call as the views print it."""
    rep = _reply(trace)
    text = _norm(" ".join(str(e.get("text") or "") for e in (inp or {}).get("excerpts") or []))
    quote = (rep or {}).get("quote")
    return {"model": (trace.get("attributes") or {}).get("tb.model_alias"),
            "repair": any(isinstance(m, dict) and m.get("role") == "assistant" for m in trace.get("prompt") or []),
            "verdict": rep.get("verdict") if rep else "no reply (not JSON)", "quote": quote,
            "quote_in_excerpts": (bool(quote) and _norm(quote) in text) if rep and quote else None,
            "confidence": (rep or {}).get("confidence"), "ts": trace.get("ts")}  # fmt: skip


def _judge_traces(work: Path) -> list[dict[str, Any]]:
    t = _json(work / "raw-traces.json", {})
    rows = t.get("traces") if isinstance(t, dict) else t
    return [x for x in rows or [] if str((x.get("attributes") or {}).get("tb.prompt") or "").startswith("judge@")]


# ---------------------------------------------------------------- exclusions
def exclusions(d: Path, *, patient: str | None = None, ruleset: str | None = None) -> list[dict[str, Any]]:
    """The excluded pairs of one stored set (see the module's docstring)."""
    gold, work = d / "built" / "gold", d / "work"
    pairs, crits = _jsonl(gold / "pairs.jsonl"), _jsonl(gold / "criteria.jsonl")
    written = {(rs, _norm(x)) for rs, xs in _json(gold / "written.json", {}).items() for x in xs}
    answers, pidmap = _json(work / "answers.json", {}), _json(work / "pidmap.json", {})
    progress = _json(work / "progress.json", {})
    by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in _judge_traces(work):
        by_job[str((x.get("attributes") or {}).get("tb.study_id") or "")].append(x)
    crit_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in crits:
        crit_rows[(str(c.get("ruleset")), str(c.get("mrn")))].append(c)
    gold_lines = {(str(c.get("ruleset")), _norm(c.get("text"))) for c in crits}
    out: list[dict[str, Any]] = []
    for g in pairs:
        rs, mrn = str(g.get("ruleset")), str(g.get("mrn"))
        if patient is None and ruleset is None and g.get("label") != "eligible":
            continue
        if (patient is not None and patient not in (g.get("patient"), mrn)) or (ruleset is not None and rs != ruleset):
            continue
        a = answers.get(rs) or {}
        p = (a.get("patients") or {}).get(pidmap.get(mrn, ""))
        if not p or p.get("tier") != "excluded":
            continue
        draft = {c.get("id"): c for c in a.get("draft") or []}
        job = str((progress.get(rs) or {}).get("screen_job") or "")
        lines = []
        for v in p.get("verdicts") or []:
            if v.get("verdict") != "fail":
                continue
            c = draft.get(v.get("id")) or {}
            text = str(c.get("text") or v.get("id"))
            calls = [
                _call(x, inp)
                for x in by_job.get(job, [])
                if (inp := _input(x)) and _norm(inp.get("criterion_text")) == _norm(text)
            ]
            lines.append({"id": v.get("id"), "kind": c.get("kind"), "class": c.get("class"), "line": text,
                          "logic": c.get("logic"), "flags": c.get("flags"), "basis": v.get("basis"),
                          "stage": STAGE_OF_BASIS.get(str(v.get("basis")), "not said"), "quote": v.get("quote"),
                          "written_by_the_benchmark": (rs, _norm(text)) in written,
                          "a_gold_row_judges_it": (rs, _norm(text)) in gold_lines, "calls": calls})  # fmt: skip
        out.append({"patient": g.get("patient"), "mrn": mrn, "trial": g.get("trial"), "ruleset": rs,
                    "label": g.get("label"), "screen_job": job or None, "failed_lines": lines,
                    "criterion_labels": [f"{c.get('kind')} {c.get('label')}: {c.get('text')}"
                                         for c in crit_rows.get((rs, mrn), [])]})  # fmt: skip
    return out


# ---------------------------------------------------------------- judged
def visit_days(ids: dict[str, Any], ref: date, mrn0: int) -> dict[str, list[str]]:
    """{visit day: [patient key, ...]} as ``site.build`` placed them for a set built on ``ref`` with ``mrn0``."""
    days: dict[str, list[str]] = defaultdict(list)
    for key, mrn in sorted((ids.get("patients") or {}).items()):
        i = int(mrn) - mrn0
        days[(ref - timedelta(days=7 + (i * 37) % 300)).isoformat()].append(str(key))
    return days


def judged(d: Path, *, ref: date | None = None, mrn0: int | None = None) -> dict[str, Any]:
    """The note questions of each SCREEN job of one stored set, grouped by question (see the module's docstring)."""
    work = d / "work"
    ids = _json(d / "built" / "gold" / "ids.json", {})
    days = visit_days(ids, ref, mrn0) if ref is not None and mrn0 is not None else {}
    jobs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for x in _judge_traces(work):
        inp = _input(x)
        job = str((x.get("attributes") or {}).get("tb.study_id") or "")
        msgs = x.get("prompt") or []
        first_user = next((m.get("content") for m in msgs if isinstance(m, dict) and m.get("role") == "user"), "")
        q = hashlib.sha256(str(first_user).encode("utf-8")).hexdigest()[:16]
        dates = [str(e.get("date")) for e in (inp or {}).get("excerpts") or [] if e.get("date")]
        row = jobs[job].setdefault(q, {"criterion": (inp or {}).get("criterion_text"), "first_excerpt_day": dates[0]
                                       if dates else None, "calls": []})  # fmt: skip
        row["calls"].append(_call(x, inp))
    patterns: Counter[str] = Counter()
    off_visit = 0
    out_jobs: dict[str, list[dict[str, Any]]] = {}
    for job, qs in sorted(jobs.items()):
        rows = []
        for q, r in qs.items():
            pat = " ".join(
                f"{SHORT.get(str(c['model']), c['model'])}:{c['verdict']}{'+repair' if c['repair'] else ''}"
                for c in r["calls"]
            )
            patterns[pat] += 1
            if days:
                r["patients_on_that_visit_day"] = days.get(str(r["first_excerpt_day"]), [])
                off_visit += int(not r["patients_on_that_visit_day"])
            rows.append({"question": q, "pattern": pat, **r})
        out_jobs[job] = rows
    return {"questions": sum(len(v) for v in out_jobs.values()), "patterns": dict(patterns.most_common()),
            "questions_on_no_visit_day": off_visit if days else None, "jobs": out_jobs}  # fmt: skip


# ---------------------------------------------------------------- the whole tool
def trace(paths: list[Path], scratch: Path, *, patient: str | None = None, ruleset: str | None = None,
          ref: date | None = None) -> dict[str, Any]:  # fmt: skip
    from tools.public_accuracy import site

    found = collect(paths, scratch)
    sets = {}
    for name, d in sorted(found.items()):
        mrn0 = site.SET_OFFSETS.get(name, (None,))[0]
        sets[name] = {"folder": str(d), "exclusions": exclusions(d, patient=patient, ruleset=ruleset),
                      "judged": judged(d, ref=ref, mrn0=mrn0)}  # fmt: skip
    return {"schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.trace", **commit(),
            "ref": ref.isoformat() if ref else None, "sets": sets}  # fmt: skip


def render(r: dict[str, Any]) -> str:
    out = [f"Stored-run trace (schema {r['schema_version']}) on commit {str(r['commit'])[:12]}"]
    for name, s in r["sets"].items():
        out.append(f"set {name}: {len(s['exclusions'])} excluded pair(s) listed")
        for e in s["exclusions"]:
            out.append(f"  {e['patient']} ({e['mrn']}) x {e['trial']} [{e['ruleset']}], gold {e['label']}")
            for ln in e["failed_lines"]:
                who = "written by the benchmark" if ln["written_by_the_benchmark"] else "the protocol's own line"
                judged_by = "a gold row judges it" if ln["a_gold_row_judges_it"] else "no gold row judges it"
                out.append(f"    {ln['id']} ({ln['kind']}, {ln['class']}): {ln['line']!r}; {who}; {judged_by}")
                out.append(f"      basis {ln['basis']}, stage {ln['stage']}; logic {json.dumps(ln['logic'])}")
                if ln["quote"]:
                    out.append(f"      quote: {ln['quote']!r}")
                for c in ln["calls"]:  # the model's answer to the line's question (pass: its condition holds)
                    out.append(f"      call {c['model']} answered {c['verdict']}{' (repair)' if c['repair'] else ''}"
                               f", quote in excerpts: {c['quote_in_excerpts']}")  # fmt: skip
            for cl in e["criterion_labels"]:
                out.append(f"    gold row: {cl}")
        j = s["judged"]
        out.append(f"  note questions: {j['questions']}; by the models' replies in order:")
        for pat, n in j["patterns"].items():
            out.append(f"    {n:5d}  {pat}")
        if j["questions_on_no_visit_day"] is not None:
            off = j["questions_on_no_visit_day"]
            out.append(f"  questions whose first excerpt day is no placed visit day of --ref: {off}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.trace", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--patient", help="a patient's key or chart number: every excluded pair of theirs")
    ap.add_argument("--ruleset", help="a ruleset id: every excluded pair of that protocol")
    ap.add_argument("--ref", type=date.fromisoformat, help="the set's build day, to join an excerpt's day to patients")
    ap.add_argument("--json", type=Path, help="write the report here (JSON)")
    ap.add_argument("--scratch", type=Path, help="an empty folder outside the repository (default: a temporary one)")
    a = ap.parse_args(argv)
    kw: dict[str, Any] = {"patient": a.patient, "ruleset": a.ruleset, "ref": a.ref}
    try:
        if a.scratch:
            if a.scratch.exists() and any(a.scratch.iterdir()):
                raise Refused(f"--scratch {a.scratch}: not empty")
            res = trace(a.runs, a.scratch, **kw)
        else:
            with tempfile.TemporaryDirectory(prefix="tb-trace-") as t:
                res = trace(a.runs, Path(t), **kw)
    except (Refused, tarfile.TarError, OSError) as exc:
        print(f"trace: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(res))
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
