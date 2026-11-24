"""H-112: the serving engine comparison (the owner's go, #639 7121371183): the same chart set through each serving
engine, with the same models and the same quantization, on the bench host.

    python -m tools.engine_compare run --engine current --candidate A --quant <label> \\
        --image-digest "$(python3 -m tools.serving_profile image --deploy deploy)" \\
        --base-url <the judge's /v1> --served-name <served name> --key-file <root-only key file> \\
        --set <frozen set> --expect-set-sha <sha256> [--repeats 3] [--workers 8] --out <results>/current-A
    python -m tools.engine_compare table <results>/current-A <results>/second-A ... [--out <results>/table.md]

``run`` sends one engine's served model the frozen synthetic chart set (``python -m tools.judge_bakeoff --write-set
F``: ``eval/qualification/judge_set.jsonl``, the synthetic hospital's note criteria) ``--repeats`` times. Every item
goes through the product's own judge (``tools.judge_bakeoff.judge_item``: the registry prompt, structured output,
the quote check), so an engine is measured on what the box would send it. One run's measures:

* **per-chart time, p50 and p95**: a chart is one synthetic patient; its time is the sum of its own calls' times
  (every attempt), as R1-P2 counts a chart's model time (``tools/chart_times.py``, PR #1451). The percentiles are
  ``tools.run_metrics.percentile`` over the charts the model was asked about, pooled over the repeats;
* **throughput**: the charts in the set times the repeats over the repeats' summed wall time, in charts per hour, and
  the generated tokens per second over the same time;
* **GPU memory**: the peak of the card's used memory over the run, as ``tools.run_metrics.Monitor`` samples it every
  ``--sample-every`` seconds (the whole card, so both servers on it; none on a machine without the card's monitor);
* **repeat agreement**, as E2-9 counts it (the walk's line 7117120038; the ruling 7122790579): each (patient,
  criterion) answer (the judge's answer after the product's checks, or ``no_answer``) in each run of the same input.
  Per later run, the pairs whose answer differs from run 1's, in all and per criterion ("differences from run 1 in
  (patient, criterion) answers: run 2 28 (27 on X, 1 on Y)"); and over all the runs, the pairs whose answers are not
  all the same and the patients with such a pair. A pair differs by ``tools.run_metrics.lists_compare``'s rule, called
  as is: its answers are not all equal, a pair missing from a run counting as an answer of its own;
* **the image**: the digest the engine ran (``--image-digest``, ``sha256:<64 hex>``, never a tag), recorded with the
  run.

``table`` joins the runs' ``summary.json`` into one Markdown table. Counts and times only: no chart text, no
excerpt, no quote, no patient or item id is written to any file or log, and the summary names the engine
(``current`` or ``second``), the candidate (A to D) and the quantization by the labels given, never a model.

The key is read from ``--key-file`` (a root-only file) and sent to ``--base-url`` only (no proxy); it is never
printed or written. Exit 0 done, 2 usage or a refused set or key.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from tools import judge_bakeoff as jb  # it puts libs/ and services/ on the path the judge needs
from tools.run_metrics import Monitor, _listed, lists_compare, percentile

ENGINES = ("current", "second")
CANDIDATES = ("A", "B", "C", "D")
LABEL = re.compile(r"^[A-Za-z0-9.+-]{1,24}$")
MIN_REPEATS = 2
NO_ANSWER = "no_answer"
SUMMARY = "summary.json"
COLUMNS = (
    ("engine", "engine"),
    ("candidate", "candidate"),
    ("quant", "quantization"),
    ("charts", "charts"),
    ("items", "items"),
    ("repeats", "repeats"),
    ("chart_p50_s", "per-chart p50 (s)"),
    ("chart_p95_s", "per-chart p95 (s)"),
    ("charts_per_hour", "charts per hour"),
    ("gen_tokens_per_s", "generated tokens/s"),
    ("gpu_memory_peak_mib", "GPU memory peak (MiB)"),
    ("pairs", "(patient, criterion) pairs"),
    ("pairs_differ", "pairs that differ"),
    ("patients_differ", "patients with a pair that differs"),
    ("no_answer", "no answer (all repeats)"),
    ("image", "image digest"),
)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


# ------------------------------------------------------------------------------------------------- the numbers
def pair_of(row: jb.Row) -> tuple[str, str]:
    """(patient, criterion) of a row: the patient is the item's cluster, the criterion the rest of its id."""
    rest = row.id.removeprefix(f"{row.source}:").removeprefix(f"{row.cluster}:")
    return row.cluster, rest


def answer_of(row: jb.Row) -> str:
    return NO_ANSWER if row.error else row.predicate


def chart_times(rows: Iterable[jb.Row]) -> list[float]:
    """Each chart's time in one repeat: the sum of its items' times (each item: every attempt and the backoff), over
    the charts with at least one item put to the model (an item with no note in its window asks no model)."""
    per: dict[str, float] = defaultdict(float)
    asked: set[str] = set()
    for r in rows:
        if r.attempts > 0:
            per[r.cluster] += r.latency_s
            asked.add(r.cluster)
    return [per[c] for c in sorted(asked)]


def differ(repeats: Sequence[Sequence[jb.Row]]) -> dict[str, int]:
    """Repeat agreement over the repeats, by ``tools.run_metrics.lists_compare``'s rule (see the module text)."""
    if len(repeats) < MIN_REPEATS:
        raise ValueError(f"repeat agreement needs at least {MIN_REPEATS} repeats")
    keys = {"\t".join(pair_of(r)) for rows in repeats for r in rows}
    diff = _differing(repeats)
    return {
        "pairs": len(keys),
        "pairs_differ": len(diff),
        "patients_differ": len({d.split("\t", 1)[0] for d in diff}),
    }


def from_run_1(repeats: Sequence[Sequence[jb.Row]]) -> list[dict[str, Any]]:
    """E2-9's form: per later run, the (patient, criterion) pairs whose answer differs from run 1's (lists_compare
    on run 1 and that run), in all and per criterion, the largest first."""
    if len(repeats) < MIN_REPEATS:
        raise ValueError(f"repeat agreement needs at least {MIN_REPEATS} repeats")
    out = []
    for k in range(1, len(repeats)):
        d = _differing([repeats[0], repeats[k]])
        per: dict[str, int] = defaultdict(int)
        for key in d:
            per[key.split("\t", 1)[1]] += 1
        by = dict(sorted(per.items(), key=lambda kv: (-kv[1], kv[0])))
        out.append({"run": k + 1, "pairs": len(d), "by_criterion": by})
    return out


def _differing(repeats: Sequence[Sequence[jb.Row]]) -> list[str]:
    runs = []
    for k, rows in enumerate(repeats, 1):
        pairs = [("\t".join(pair_of(r)), answer_of(r)) for r in rows]
        runs.append({"part": "hospital", "lang": "bench", "tag": f"r{k}", "candidates": _listed(pairs)})
    return [str(d["pid"]) for d in lists_compare(runs)["bench"]["differ"]]


def summarize(
    repeats: Sequence[Sequence[jb.Row]],
    walls: Sequence[float],
    meta: dict[str, Any],
    gpu: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The run's one summary: counts and times only (see the module text)."""
    if len(repeats) != len(walls) or not repeats:
        raise ValueError("one wall time per repeat")
    times = [t for rows in repeats for t in chart_times(rows)]
    charts = len({r.cluster for r in repeats[0]})
    wall = sum(walls)
    gen = sum(r.tokens_out for rows in repeats for r in rows)
    agree = differ(repeats)
    keys_no: dict[tuple[str, str], int] = defaultdict(int)
    for rows in repeats:
        for r in rows:
            if r.error:
                keys_no[pair_of(r)] += 1
    out: dict[str, Any] = {
        "engine": meta["engine"],
        "candidate": meta["candidate"],
        "quant": meta["quant"],
        "charts": charts,
        "items": len(repeats[0]),
        "repeats": len(repeats),
        "charts_timed": len(times),
        "chart_p50_s": round(percentile(times, 0.50), 3),
        "chart_p95_s": round(percentile(times, 0.95), 3),
        "wall_s": round(wall, 3),
        "charts_per_hour": round(charts * len(repeats) * 3600 / wall, 1) if wall > 0 else None,
        "gen_tokens_per_s": round(gen / wall, 1) if wall > 0 else None,
        "gpu_memory_peak_mib": (gpu or {}).get("memory_peak_mib"),
        "gpu_samples": (gpu or {}).get("samples", 0),
        **agree,
        "no_answer": sum(1 for n in keys_no.values() if n == len(repeats)),
        "from_run_1": from_run_1(repeats),
        "image": meta.get("image", ""),
        "set_sha256": meta.get("set_sha256", ""),
    }
    return out


def render_table(summaries: Sequence[dict[str, Any]]) -> str:
    def cell(v: Any) -> str:
        return "not measured" if v is None else str(v)

    head = "| " + " | ".join(title for _, title in COLUMNS) + " |"
    rule = "|" + "|".join(" --- " for _ in COLUMNS) + "|"
    body = ["| " + " | ".join(cell(s.get(k)) for k, _ in COLUMNS) + " |" for s in summaries]
    shas = sorted({str(s.get("set_sha256", "")) for s in summaries})
    note = (
        f"\nOne chart set for every row (sha256 {shas[0][:12]})."
        if len(shas) == 1 and shas[0]
        else "\nNOT COMPARABLE: the rows were run on different chart sets."
    )
    lines = ["", "Repeat agreement, as E2-9 counts it: differences from run 1 in (patient, criterion) answers."]
    for s in summaries:
        runs = "; ".join(_run_line(x) for x in s.get("from_run_1") or []) or "not measured"
        lines.append(f"- {s.get('engine')} {s.get('candidate')} {s.get('quant')}: {runs}.")
    return "\n".join([head, rule, *body]) + "\n" + note + "\n" + "\n".join(lines) + "\n"


def _run_line(x: dict[str, Any]) -> str:
    by = x.get("by_criterion") or {}
    detail = f" ({', '.join(f'{n} on {c}' for c, n in by.items())})" if by else ""
    return f"run {x['run']} {x['pairs']}{detail}"


# ------------------------------------------------------------------------------------------------------ the run
def read_key(path: Path | None) -> str:
    if path is None:
        return ""
    return path.read_text(encoding="utf-8").strip()


def run(
    base_url: str,
    served_name: str,
    items: list[jb.Item],
    meta: dict[str, Any],
    out: Path,
    *,
    key: str = "",
    repeats: int = 3,
    workers: int = 8,
    sample_every: float = 10.0,
    gpu_cmd: list[str] | None = None,
) -> dict[str, Any]:
    """``repeats`` runs of ``items`` against one served model; writes and returns ``out/summary.json``."""
    if repeats < MIN_REPEATS:
        raise ValueError(f"--repeats must be at least {MIN_REPEATS}")
    client = jb.BakeoffClient(base_url, served_name, key=key)
    jb.models_entry(client.http, base_url, served_name)  # the served name must be listed (PinRefused otherwise)
    out.mkdir(parents=True, exist_ok=True)
    mon = Monitor(out / "card", servers=None, key="", every=sample_every, gpu_cmd=gpu_cmd).start()
    all_rows: list[list[jb.Row]] = []
    walls: list[float] = []
    try:
        for _ in range(repeats):
            t0 = time.perf_counter()
            all_rows.append(jb.run(client, items, workers=workers))  # no out: no per-item file
            walls.append(time.perf_counter() - t0)
    finally:
        card = mon.stop()
    gpu = card.get("gpu") if card.get("sampled") else None
    summary = summarize(all_rows, walls, meta, gpu)
    (out / SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _label(kind: str, value: str, allowed: Sequence[str] | None = None) -> str:
    if allowed is not None and value not in allowed:
        raise SystemExit(f"engine_compare: --{kind} must be one of {', '.join(allowed)}")
    if not LABEL.match(value):
        raise SystemExit(f"engine_compare: --{kind} is a short label (letters, digits, . + -), never a model name")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.engine_compare", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--engine", required=True)
    r.add_argument("--candidate", required=True)
    r.add_argument("--quant", required=True)
    r.add_argument("--image-digest", required=True, help="sha256:<64 hex> of the image the engine runs")
    r.add_argument("--base-url", required=True)
    r.add_argument("--served-name", required=True)
    r.add_argument("--key-file", type=Path)
    r.add_argument("--set", type=Path, required=True)
    r.add_argument("--expect-set-sha", required=True)
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--sample-every", type=float, default=10.0)
    r.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("table")
    t.add_argument("runs", type=Path, nargs="+")
    t.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "table":
        summaries = [json.loads((d / SUMMARY).read_text(encoding="utf-8")) for d in a.runs]
        text = render_table(summaries)
        if a.out:
            a.out.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0
    meta = {
        "engine": _label("engine", a.engine, ENGINES),
        "candidate": _label("candidate", a.candidate, CANDIDATES),
        "quant": _label("quant", a.quant),
    }
    if not DIGEST.match(a.image_digest):
        print("engine_compare: --image-digest is sha256:<64 hex>, never a tag", file=sys.stderr)
        return 2
    meta["image"] = a.image_digest
    if not jb._loopback(a.base_url) and not a.base_url.startswith("https://") and not a.key_file:
        print("engine_compare: a non-loopback http endpoint needs --key-file", file=sys.stderr)
        return 2
    try:
        items, sha = jb.read_set(a.set, a.expect_set_sha)
    except (OSError, ValueError) as e:
        print(f"engine_compare: the set is refused ({type(e).__name__})", file=sys.stderr)
        return 2
    meta["set_sha256"] = sha
    try:
        key = read_key(a.key_file)
    except OSError:
        print("engine_compare: the key file cannot be read", file=sys.stderr)
        return 2
    try:
        s = run(a.base_url, a.served_name, items, meta, a.out, key=key, repeats=a.repeats, workers=a.workers,
                sample_every=a.sample_every)  # fmt: skip
    except jb.PinRefused:
        print("engine_compare: the served name is not listed by the endpoint", file=sys.stderr)
        return 2
    print(render_table([s]), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
