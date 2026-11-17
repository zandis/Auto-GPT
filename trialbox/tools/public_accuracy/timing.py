"""Where a set's time went, protocol by protocol, in two stored runs of it (card H-36). Offline: no GPU, no model, no
network.

    python -m tools.public_accuracy.timing BEFORE AFTER [--set NAME] [--json OUT]

``BEFORE`` and ``AFTER`` are read as :mod:`.replay` reads a run (a driver's ``.tgz``, unpacked by its safe extractor
into a new empty folder outside the repository; an extracted folder; or a folder of them). Nothing in a run is
executed or changed. A protocol is matched across the runs by its trial: the ruleset id without the run's prefix
(``Sm3NCT00002897`` and ``Sm4NCT00002897`` are both ``NCT00002897``).

What it reads, for each protocol, from each run (and nothing else):

* ``work/box-calls.log``: each job's own record (the JSON line with ``metrics``): its type (FEAS, APPROVE, SCREEN) and
  ``metrics.wall_seconds``; and the driver's clock line before the job's ``send`` (``+ ... send HH:MM:SS``), which
  gives the order the protocols were sent and, with the wall time, how many jobs of each type were in flight at once
  (a mean over the set's span, and the share of seconds with 0, 1, 2, 3 or more APPROVE jobs in flight).
* ``work/progress.json``: the protocol's three job ids, its ``outcome`` (``not_run_time_budget`` is a protocol the
  set's budget cut), and SCREEN's ``screen_metrics`` (model calls and tokens in and out; FEAS and APPROVE record none).
* ``work/raw-traces.json``: the model calls of each job (``tb.study_id``), by prompt (``ir_extract``, ``concept_map``,
  ``judge``) and, for ``judge``, by alias; schema repairs (a call whose prompt holds an earlier answer); gateway cache
  hits (``tb.cache``); refusals (``tb.refusal``).
* ``work/screen/<ruleset>.json``: ``cascade.metrics.pairs_judged`` (S3, S4) and ``cascade.judged_store`` (``read``,
  ``live``).

It says where the time is, not why: no record holds a step's time inside a job. Exit 0 when the tool ran, whatever it
found; 2 on an input it will not read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.public_accuracy.replay import Refused, collect

SCHEMA_VERSION = 1
TYPES = ("FEAS", "APPROVE", "SCREEN")
_PREFIX = re.compile(r"^[A-Z][a-z]m?\d+")  # the run's ruleset prefix: Sm3, Gm4, Mm4
_CLOCK = re.compile(r"^\+ \S+ \S+ (\w+) (\d\d:\d\d:\d\d)\s*$")


def trial(ruleset: str) -> str:
    """The trial a ruleset id names, without the run's prefix."""
    return _PREFIX.sub("", ruleset, count=1)


def _json(p: Path, default: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def jobs(work: Path) -> dict[str, dict[str, Any]]:
    """{job id: {type, wall, sent}} from the driver's log (``sent``: seconds of the day of the send's clock line)."""
    out: dict[str, dict[str, Any]] = {}
    clock: float | None = None
    path = work / "box-calls.log"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _CLOCK.match(line)
        if m:
            t = datetime.strptime(m.group(2), "%H:%M:%S")
            clock = float(t.hour * 3600 + t.minute * 60 + t.second)
            continue
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or not d.get("job"):
            continue
        row = out.setdefault(str(d["job"]), {"type": None, "wall": None, "sent": None})
        if "folder" in d and row["sent"] is None:
            row["sent"] = clock
        if isinstance(d.get("metrics"), dict):
            row["type"] = d.get("type")
            row["wall"] = d["metrics"].get("wall_seconds")
    return out


def calls(work: Path) -> dict[str, Counter[str]]:
    """{job id: Counter} of its model calls: ``<prompt>`` (and ``judge:<alias>``), ``repair``, ``cache_hit``,
    ``refusal``."""
    t = _json(work / "raw-traces.json", {})
    rows = t.get("traces") if isinstance(t, dict) else t
    out: dict[str, Counter[str]] = {}
    for x in rows or []:
        a = x.get("attributes") or {}
        c = out.setdefault(str(a.get("tb.study_id")), Counter())
        prompt = str(a.get("tb.prompt") or "?").split("@", 1)[0]
        c[prompt] += 1
        if prompt == "judge":
            c[f"judge:{a.get('tb.model_alias')}"] += 1
        if any(isinstance(m, dict) and m.get("role") == "assistant" for m in x.get("prompt") or []):
            c["repair"] += 1
        if a.get("tb.cache") == "hit":
            c["cache_hit"] += 1
        if a.get("tb.refusal"):
            c["refusal"] += 1
    return out


def protocols(d: Path) -> dict[str, dict[str, Any]]:
    """{trial: the protocol's figures in this run}."""
    work = d / "work"
    js, cs = jobs(work), calls(work)
    out: dict[str, dict[str, Any]] = {}
    for rid, v in (_json(work / "progress.json", {}) or {}).items():
        row: dict[str, Any] = {"ruleset": rid, "outcome": v.get("outcome"), "attempt": v.get("attempt", 1),
                               "sent": None, "wall": {}, "calls": Counter()}  # fmt: skip
        for typ, key in zip(TYPES, ("feas_job", "approve_job", "screen_job"), strict=True):
            job = v.get(key)
            if not job:
                continue
            j = js.get(job) or {}
            row["wall"][typ] = j.get("wall")
            if typ == "FEAS":
                row["sent"] = j.get("sent")
            row["calls"].update(cs.get(job) or {})
        sm = v.get("screen_metrics") or {}
        row["tokens_in"], row["tokens_out"] = sm.get("tokens_in"), sm.get("tokens_out")
        scr = _json(work / "screen" / f"{rid}.json", {}) or {}
        cas = scr.get("cascade") or {}
        pj = (cas.get("metrics") or {}).get("pairs_judged") or {}
        row["pairs_s3"], row["pairs_s4"] = pj.get("S3"), pj.get("S4")
        store = cas.get("judged_store") or {}
        row["store_read"], row["store_live"] = store.get("read"), store.get("live")
        out[trial(rid)] = row
    return out


def in_flight(d: Path) -> dict[str, Any]:
    """The mean number of jobs of each type in flight over the set's span, and the share of seconds with 0, 1, 2 and
    3 or more APPROVE jobs in flight (each job from its send's clock line for its own wall time)."""
    iv = [(j["type"], j["sent"], j["sent"] + float(j["wall"])) for j in jobs(d / "work").values()
          if j["type"] in TYPES and j["sent"] is not None and j["wall"] is not None]  # fmt: skip
    if not iv:
        return {"span_s": 0, "mean": {}, "approve_share": {}}
    t0, t1 = min(a for _, a, _ in iv), max(b for _, _, b in iv)
    span = max(1, int(t1 - t0))
    mean = {t: round(sum(min(b, t1) - a for typ, a, b in iv if typ == t) / span, 2) for t in TYPES}
    hist: Counter[int] = Counter()
    for s in range(span):
        x = t0 + s + 0.5
        hist[min(3, sum(1 for typ, a, b in iv if typ == "APPROVE" and a <= x < b))] += 1
    share = {("3+" if k == 3 else str(k)): round(100 * hist[k] / span) for k in range(4)}
    return {"span_s": span, "mean": mean, "approve_share": share}


def _q(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {}
    s = sorted(xs)
    pick = {"min": 0.0, "p25": 0.25, "median": 0.5, "p75": 0.75, "max": 1.0}
    return {k: round(s[min(len(s) - 1, round(f * (len(s) - 1)))], 1) for k, f in pick.items()}


def compare(before: Path, after: Path) -> dict[str, Any]:
    """The two runs of one set side by side."""
    b, a = protocols(before), protocols(after)
    ran = {n: {t for t, r in p.items() if r["wall"]} for n, p in (("before", b), ("after", a))}
    both = sorted(ran["before"] & ran["after"])
    rows = []
    for t in both:
        row: dict[str, Any] = {"trial": t}
        for side, p in (("before", b[t]), ("after", a[t])):
            row[side] = {**{k: v for k, v in p.items() if k != "calls"}, "calls": dict(p["calls"])}
        rows.append(row)

    def tot(side: str, f: Any) -> float:
        return round(sum(float(f(r[side]) or 0) for r in rows), 1)

    totals: dict[str, Any] = {}
    for typ in TYPES:
        totals[f"wall_{typ}"] = {s: tot(s, lambda r, typ=typ: r["wall"].get(typ)) for s in ("before", "after")}
    keys = sorted({k for r in rows for s in ("before", "after") for k in r[s]["calls"]})
    for k in keys:
        totals[f"calls_{k}"] = {s: tot(s, lambda r, k=k: r["calls"].get(k)) for s in ("before", "after")}
    for k in ("tokens_in", "tokens_out", "pairs_s3", "pairs_s4", "store_read", "store_live"):
        totals[k] = {s: tot(s, lambda r, k=k: r.get(k)) for s in ("before", "after")}
    diff = {typ: _q([float(r["after"]["wall"].get(typ) or 0) - float(r["before"]["wall"].get(typ) or 0)
                     for r in rows]) for typ in TYPES}  # fmt: skip
    order = {n: [t for t, r in sorted(p.items(), key=lambda kv: (kv[1]["sent"] is None, kv[1]["sent"] or 0))
                 if r["sent"] is not None] for n, p in (("before", b), ("after", a))}  # fmt: skip
    cut = {n: sorted(t for t, r in p.items() if r["outcome"] == "not_run_time_budget")
           for n, p in (("before", b), ("after", a))}  # fmt: skip
    tail = order["before"][len(order["before"]) - len(cut["after"]) :] if cut["after"] else []
    return {"schema_version": SCHEMA_VERSION, "protocols_both": len(both), "rows": rows, "totals": totals,
            "difference_quantiles_s": diff, "order": order, "cut": cut,
            "after_cut_is_before_tail": bool(cut["after"]) and sorted(tail) == cut["after"],
            "in_flight": {"before": in_flight(before), "after": in_flight(after)}}  # fmt: skip


def render(r: dict[str, Any]) -> str:
    out = [f"Protocols both runs ran: {r['protocols_both']}", "Totals over them (before -> after):"]
    for k, v in r["totals"].items():
        out.append(f"  {k}: {v['before']} -> {v['after']}")
    out.append("Per-protocol difference of wall seconds (after - before), quantiles:")
    for typ, q in r["difference_quantiles_s"].items():
        out.append(f"  {typ}: {q}")
    for side in ("before", "after"):
        f = r["in_flight"][side]
        out.append(f"In flight ({side}): span {f['span_s']} s, mean {f['mean']}, APPROVE seconds share % "
                   f"{f['approve_share']}")  # fmt: skip
    out.append(f"Cut by the budget: before {len(r['cut']['before'])}, after {len(r['cut']['after'])}; the after run's "
               f"cut is the before run's tail of its order: {r['after_cut_is_before_tail']}")  # fmt: skip
    out.append("It says where the time is, not why: no record holds a step's time inside a job.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.timing", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--set", default="", help="the set to compare when a run holds several (default: the only one)")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="tb-timing-") as tmp:
            got = [collect([p], Path(tmp) / side) for p, side in ((a.before, "b"), (a.after, "a"))]
            name = a.set or (next(iter(got[0])) if len(got[0]) == 1 else "")
            if not name or any(name not in g for g in got):
                raise Refused(f"name one set both runs hold with --set (before: {sorted(got[0])}, after: "
                              f"{sorted(got[1])})")  # fmt: skip
            r = compare(got[0][name], got[1][name])
    except Refused as exc:
        print(f"timing: {exc}", file=sys.stderr)
        return 2
    if a.json:
        a.json.write_text(json.dumps(r, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    sys.stdout.write(render(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
