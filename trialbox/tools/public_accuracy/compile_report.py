"""A stored run's compile report and its concepts' coverage, read offline (card H-26, plan 8 V4 and V5).

    python -m tools.public_accuracy.compile_report RUN [RUN ...] [--no-recompile] [--installed DIR] [--top N]
                                                    [--index-day DAY] [--json OUT] [--scratch DIR]

``RUN`` is read as :mod:`.replay` reads it (a driver's ``.tgz``, unpacked by its safe extractor into a new empty folder
outside the repository; an extracted folder; or a folder of them). Nothing in a run is executed or changed. No model,
no GPU, no network.

Per protocol set, three parts:

* **The compile as the run stored it** (``work/answers.json``): the protocols, how many reached SCREEN (a SCREEN job
  ran, done or failed) and how many were screened; the drafted criteria by kind and class; the criteria sent to a
  person (class ``human``) and why: "drafted for a person by the model" when the run's own ``ir_extract`` reply for the
  line already said ``human``, else the compile's flags on the criterion (``needs_review`` alone is said as such),
  counted once under each of its reasons and apart for the criteria with one reason only; and
  the ``qualifier_dropped`` flags the stored drafts carry.
* **#996's rule on today's code** (``qualifier_dropped``, lane A2's ``ir_extract.postprocess``): every protocol is
  compiled again from the run's stored ``ir_extract`` and ``concept_map`` replies by :func:`.rerun.recompile` (the
  compiler's own public entry point, with a model that answers only from the stored replies). Its flags are counted,
  the criteria that carry ``qualifier_dropped`` are listed with their class before and after, and every criterion
  whose class moved is counted. The CQL translator and the FHIR server are not run, so a recompile's
  ``equivalence_fail`` flag says only that the step was not run; it is counted apart and never read as a finding.
  The stored drafts' exclusions whose coded logic is an age or a sex alone (``semantics.demographic_alone``), in a
  class whose logic runs, are listed beside it: the lines the rule looks at.
* **The concepts' coverage** (``tools.terminology_coverage``, the mapper with no model and no synonym dictionary):
  each ``extract_criteria`` call's non-demographic candidates, mapped or not, by which answer (the mapper's method and
  the code systems of the codes it gave), and the most frequent unmapped names with their counts. A candidate is mapped
  in the domain it was drafted in, as lane E measured; the unmapped ones the compile would read as a condition
  (``postprocess.is_diagnosis_name`` on a procedure or encounter) are counted apart, with how many map as one.
  ``--installed`` reads the tables a box loaded into that folder as well (``tools.terminology_install``).

Exit 0 when the tool ran, whatever it found; 2 on an input it will not read.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from tools.public_accuracy.replay import Refused, collect, commit

SCHEMA_VERSION = 1
FILTERED = ("structured", "mixed")  # criteria_compiler.semantics.FILTERED: the classes whose logic runs
#: a recompile flag that says only that a step was not run offline (no translator, no FHIR server)
NOT_RUN_FLAGS = ("equivalence_fail",)
GENERIC_FLAGS = ("needs_review",)
BY_MODEL = "drafted for a person by the model"


def _json(p: Path, default: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def _ir_extract_classes(traces: dict[str, Any]) -> dict[tuple[str, str], str]:
    """(kind, line) -> the class the run's first ``ir_extract`` reply gave the line."""
    out: dict[tuple[str, str], str] = {}
    for call in sorted(traces.get("traces") or [], key=lambda t: str(t.get("ts") or "")):
        if (call.get("attributes") or {}).get("tb.role") != "extract_criteria":
            continue
        try:
            reply = json.loads(call.get("output") or "")
        except (TypeError, ValueError):
            continue
        for c in reply.get("criteria") or [] if isinstance(reply, dict) else []:
            if isinstance(c, dict):
                out.setdefault((str(c.get("kind")), _norm(c.get("text"))), str(c.get("class") or ""))
    return out


def why_human(crit: dict[str, Any], drafted: dict[tuple[str, str], str]) -> list[str]:
    """Why a stored criterion of class ``human`` went to a person: the model's own draft, else its flags."""
    if drafted.get((str(crit.get("kind")), _norm(crit.get("text")))) == "human":
        return [BY_MODEL]
    flags = [str(f) for f in crit.get("flags") or [] if f not in GENERIC_FLAGS]
    return flags or ["needs_review only" if crit.get("flags") else "no flag"]


def demographic_alone_lines(answers: dict[str, Any]) -> list[dict[str, Any]]:
    """The stored drafts' exclusions in a class whose logic runs, whose coded logic is an age or a sex alone."""
    from criteria_compiler.semantics import demographic_alone

    from tools.public_accuracy.rerun import criterion_ir

    out = []
    for ruleset, a in sorted(answers.items()):
        for d in a.get("draft") or []:
            if d.get("kind") != "exclusion" or d.get("class") not in FILTERED:
                continue
            ir = criterion_ir(d, ruleset)
            if ir is not None and demographic_alone(ir.logic):
                out.append({"ruleset": ruleset, "id": d.get("id"), "class": d.get("class"), "text": d.get("text"),
                            "logic": d.get("logic")})  # fmt: skip
    return out


def stored(d: Path) -> dict[str, Any]:
    """The compile as the run stored it (``work/answers.json``)."""
    answers = _json(d / "work" / "answers.json", {})
    drafted = _ir_extract_classes(_json(d / "work" / "raw-traces.json", {}))
    by_class: Counter[str] = Counter()
    by_kind_class: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    human_why: Counter[str] = Counter()
    human_only: Counter[str] = Counter()
    human = 0
    for a in answers.values():
        for c in a.get("draft") or []:
            by_class[str(c.get("class"))] += 1
            by_kind_class[f"{c.get('kind')} {c.get('class')}"] += 1
            flags.update(str(f) for f in c.get("flags") or [])
            if c.get("class") == "human":
                human += 1
                why = why_human(c, drafted)
                human_why.update(why)
                if len(why) == 1:
                    human_only[why[0]] += 1
    screen = Counter(str(a.get("screen")) for a in answers.values())
    return {
        "protocols": len(answers),
        "outcome": dict(Counter(str(a.get("outcome")) for a in answers.values())),
        "reached_screen": sum(1 for a in answers.values() if a.get("screen") in ("done", "failed")),
        "screened": screen.get("done", 0),
        "screen_failed": screen.get("failed", 0),
        "failed_before_screen": sum(1 for a in answers.values() if a.get("screen") not in ("done", "failed")),
        "criteria": sum(by_class.values()),
        "by_class": dict(by_class),
        "by_kind_class": dict(by_kind_class),
        "flags": dict(flags.most_common()),
        "human": human,
        "human_why": dict(human_why.most_common()),
        "human_only_reason": dict(human_only.most_common()),
        "qualifier_dropped": flags.get("qualifier_dropped", 0),
        "exclusions_demographic_alone": demographic_alone_lines(answers),
    }


def recompiled(d: Path, index_day: date, tz: str = "UTC") -> dict[str, Any]:
    """#996's rule on today's code: every protocol compiled again from the run's stored replies."""
    from tools.public_accuracy import rerun

    st = rerun.Stored.read(d / "work")
    answers = _json(d / "work" / "answers.json", {})
    before = {str(c.get("id")).upper(): c for a in answers.values() for c in a.get("draft") or []}
    status: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    moved: Counter[str] = Counter()
    dropped: list[dict[str, Any]] = []
    not_rerun: list[dict[str, str]] = []
    concepts_not_stored = 0
    for job in sorted(j for j in st.by_job if st.calls(j, "ir_extract")):
        r = rerun.recompile(st, job, index_day, tz)
        status[r.status] += 1
        concepts_not_stored += len(r.concepts_not_stored)
        if r.status != "compiled":
            not_rerun.append({"ruleset": r.ruleset, "status": r.status, "step": r.step, "message": r.message[:200]})
            continue
        for c in r.criteria:
            cls = str(c.class_)
            by_class[cls] += 1
            fl = [str(f) for f in c.flags or []]
            flags.update(fl)
            old = before.get(str(c.id).upper())
            old_cls = str(old.get("class")) if old else None
            if old_cls is not None and old_cls != cls:
                moved[f"{old_cls} -> {cls}"] += 1
            if "qualifier_dropped" in fl:
                dropped.append({"ruleset": r.ruleset, "id": c.id, "text": c.text, "class_stored": old_cls,
                                "class_now": cls})  # fmt: skip
    not_run = {f: flags.pop(f) for f in NOT_RUN_FLAGS if f in flags}
    return {
        "index_day": index_day.isoformat(),
        "status": dict(status),
        "not_rerun": not_rerun,
        "criteria": sum(by_class.values()),
        "by_class": dict(by_class),
        "flags": dict(flags.most_common()),
        "flags_of_steps_not_run": not_run,
        "class_moved": dict(moved.most_common()),
        "qualifier_dropped": len(dropped),
        "qualifier_dropped_lines": dropped,
        "concept_map_replies_not_stored": concepts_not_stored,
    }


def _source(res: Any) -> str:
    """The answer's method and the code systems of its codes (short names), e.g. ``icd10cm: icd10cm``."""
    from criteria_compiler.terminology.mapper import LOADED_SYSTEMS

    short = {uri: name for name, uri in LOADED_SYSTEMS.items()}
    systems = sorted({short.get(c.system, c.system) for c in res.concepts})
    shipped = any("shipped NHI table" in n for n in res.notes)
    return f"{res.method}: {'+'.join(systems)}" + (" (shipped NHI table)" if shipped else "")


def coverage(traces: list[dict[str, Any]], term: Any, top: int = 20) -> dict[str, Any]:
    """The non-demographic concept candidates of every ``extract_criteria`` call, mapped by ``term`` (no model, no
    synonyms): by domain, by answer source, and the ``top`` most frequent unmapped names."""
    from criteria_compiler.ir_extract.postprocess import is_diagnosis_name

    from tools.terminology_coverage import ORDER, candidates

    by_domain: dict[str, list[int]] = {}
    by_source: Counter[str] = Counter()
    review: Counter[str] = Counter()
    unmapped: Counter[tuple[str, str]] = Counter()
    refiled = [0, 0]  # unmapped as drafted, a diagnosis filed as a procedure or encounter: [of them, mapped as one]
    seen: dict[tuple[str, str], Any] = {}
    calls = drafted = 0
    for t in traces:
        calls += sum(
            1 for c in t.get("traces") or [] if (c.get("attributes") or {}).get("tb.role") == "extract_criteria"
        )
        for cand in candidates(t):
            drafted += 1
            domain = str(cand.get("domain") or "")
            if domain == "demographic":
                continue
            key = (domain, str(cand["name"]))
            if key not in seen:
                seen[key] = term.map(domain, key[1], None)
            res = seen[key]
            row = by_domain.setdefault(domain, [0, 0])
            row[0] += 1
            if res.concepts:
                row[1] += 1
                by_source[_source(res)] += 1
                review[domain] += 1 if res.needs_review else 0
            else:
                unmapped[(domain, key[1].strip().lower())] += 1
                if domain in ("procedure", "encounter") and is_diagnosis_name(key[1]):
                    refiled[0] += 1
                    cond = ("condition", key[1])
                    if cond not in seen:
                        seen[cond] = term.map("condition", key[1], None)
                    refiled[1] += 1 if seen[cond].concepts else 0
    names = [d for d in ORDER if d in by_domain] + sorted(set(by_domain) - set(ORDER))
    distinct_unmapped = len(unmapped)
    return {
        "calls": calls,
        "candidates": drafted,
        "concepts": sum(v[0] for v in by_domain.values()),
        "mapped": sum(v[1] for v in by_domain.values()),
        "by_domain": {d: by_domain[d] for d in names},
        "by_source": dict(by_source.most_common()),
        "for_review": dict(review),
        "unmapped": sum(unmapped.values()),
        "unmapped_distinct": distinct_unmapped,
        "unmapped_once": sum(1 for n in unmapped.values() if n == 1),
        "unmapped_refiled_as_condition": {"diagnoses": refiled[0], "mapped_as_a_condition": refiled[1]},
        "top_unmapped": [
            {"domain": d, "name": n, "count": k}
            for (d, n), k in sorted(unmapped.items(), key=lambda x: (-x[1], x[0]))[:top]
        ],
    }


def report(paths: list[Path], scratch: Path, *, recompile: bool = True, index_day: date | None = None,
           installed: Path | None = None, top: int = 20) -> dict[str, Any]:  # fmt: skip
    from criteria_compiler.terminology.mapper import Terminology

    found = collect(paths, scratch)
    term = Terminology(installed=installed or Path("/nonexistent/terminology-none"))
    sets: dict[str, Any] = {}
    traces = []
    for name, d in sorted(found.items()):
        t = _json(d / "work" / "raw-traces.json", {})
        traces.append(t)
        sets[name] = {
            "folder": str(d),
            "stored": stored(d),
            "recompiled": recompiled(d, index_day or date.today()) if recompile else None,
            "coverage": coverage([t], term, top),
        }
    return {"schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.compile_report", **commit(),
            "installed": str(installed) if installed else None, "installed_problems": list(term.installed_problems),
            "sets": sets, "coverage_all": coverage(traces, term, top)}  # fmt: skip


def _join(d: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items()) or "none"


def _cov_lines(c: dict[str, Any], indent: str) -> list[str]:
    share = 100 * c["mapped"] / (c["concepts"] or 1)
    out = [
        f"{indent}{c['calls']} extract_criteria calls, {c['candidates']} candidates; "
        f"{c['concepts']} not demographic, {c['mapped']} mapped ({share:.1f} %)"
    ]
    for d, (n, k) in c["by_domain"].items():
        out.append(f"{indent}  {d}: {k} of {n} (for review {c['for_review'].get(d, 0)})")
    for s, n in c["by_source"].items():
        out.append(f"{indent}  mapped by {s}: {n}")
    rf = c["unmapped_refiled_as_condition"]
    out.append(
        f"{indent}  unmapped as drafted, a diagnosis filed as a procedure or encounter (the compile reads it as a "
        f"condition): {rf['diagnoses']}, of them mapped as a condition {rf['mapped_as_a_condition']}"
    )
    out.append(
        f"{indent}  unmapped {c['unmapped']} ({c['unmapped_distinct']} distinct, {c['unmapped_once']} once); "
        "the most frequent:"
    )
    for u in c["top_unmapped"]:
        out.append(f"{indent}    {u['count']:4d}  {u['name']} ({u['domain']})")
    return out


def render(r: dict[str, Any]) -> str:
    out = [f"Stored-run compile report (schema {r['schema_version']}) on commit {str(r['commit'])[:12]}"]
    for name, s in r["sets"].items():
        st = s["stored"]
        out.append(
            f"set {name}: {st['protocols']} protocols; reached SCREEN {st['reached_screen']}, screened "
            f"{st['screened']}, failed in SCREEN {st['screen_failed']}, failed before {st['failed_before_screen']}"
        )
        out.append(f"  stored criteria {st['criteria']}: {_join(dict(sorted(st['by_kind_class'].items())))}")
        out.append(
            f"  sent to a person (class human): {st['human']}; by reason (a criterion under each of its reasons): "
            f"{_join(st['human_why'])}"
        )
        out.append(f"    with that reason alone: {_join(st['human_only_reason'])}")
        out.append(
            f"  stored qualifier_dropped: {st['qualifier_dropped']}; stored exclusions coded as an age or sex alone "
            f"in a class whose logic runs: {len(st['exclusions_demographic_alone'])}"
        )
        rc = s["recompiled"]
        if rc is not None:
            out.append(
                f"  recompiled on this commit (index day {rc['index_day']}): {_join(rc['status'])}; "
                f"criteria {rc['criteria']}: {_join(dict(sorted(rc['by_class'].items())))}"
            )
            out.append(f"    qualifier_dropped: {rc['qualifier_dropped']}; classes moved: {_join(rc['class_moved'])}")
            for q in rc["qualifier_dropped_lines"]:
                out.append(f"      {q['id']} {q['class_stored']} -> {q['class_now']}: {q['text']!r}")
        out.extend(_cov_lines(s["coverage"], "  "))
    out.append("all sets:")
    out.extend(_cov_lines(r["coverage_all"], "  "))
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.compile_report",
                                 description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--no-recompile", action="store_true", help="the stored compile and the coverage only")
    ap.add_argument("--index-day", type=date.fromisoformat, help="the recompile's index day (default: today)")
    ap.add_argument("--installed", type=Path, help="a TB_TERMINOLOGY_DIR the coverage also reads")
    ap.add_argument("--top", type=int, default=20, help="how many unmapped names to list (default 20)")
    ap.add_argument("--json", type=Path, help="write the report here (JSON)")
    ap.add_argument("--scratch", type=Path, help="an empty folder outside the repository (default: a temporary one)")
    a = ap.parse_args(argv)
    kw: dict[str, Any] = {"recompile": not a.no_recompile, "index_day": a.index_day, "installed": a.installed,
                          "top": a.top}  # fmt: skip
    try:
        if a.scratch:
            if a.scratch.exists() and any(a.scratch.iterdir()):
                raise Refused(f"--scratch {a.scratch}: not empty")
            res = report(a.runs, a.scratch, **kw)
        else:
            with tempfile.TemporaryDirectory(prefix="tb-compile-report-") as t:
                res = report(a.runs, Path(t), **kw)
    except (Refused, tarfile.TarError, OSError) as exc:
        print(f"compile_report: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(res))
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
