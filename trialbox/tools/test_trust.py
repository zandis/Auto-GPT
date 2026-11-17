"""test_trust: every figure of a test-trust page comes from its JSON files, whole (card V-4, plan 8 V19).

    python -m tools.test_trust --check   # exit 1 when a block of the page differs from its JSON
    python -m tools.test_trust --write   # rewrite the blocks of the page from the JSON

The page ``docs/plan/measurements/test-trust-2026-11-17.md`` holds generated blocks, each between
``<!-- test-trust:begin NAME -->`` and ``<!-- test-trust:end NAME -->``. Each block is written from the JSON files
of the folder beside the page (``mutation.json``, ``coverage.json``, ``findings.json``, ``survivors.json``,
``weak_tests.json``, ``lake.json``, ``nightly_runs.json``) and compared whole: one changed figure in the page or in a
JSON fails the check. A survivor named in ``survivors.json`` must be a survived or uncovered mutant of
``mutation.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from tools.mutation import Result, score

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "plan" / "measurements" / "test-trust-2026-11-17.md"
_BLOCK = re.compile(r"(<!-- test-trust:begin (\w+) -->\n)(.*?)(<!-- test-trust:end \2 -->)", re.S)
CI = "CI artifact, d117301f"

Data = dict[str, Any]


def _load(page: Path) -> Data:
    folder = page.with_suffix("")
    names = ("mutation", "coverage", "findings", "survivors", "weak_tests", "lake", "nightly_runs")
    return {n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8")) for n in names}


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f} %"


def _results(d: Data) -> dict[str, list[Result]]:
    by_file: dict[str, list[Result]] = {}
    for run in d["mutation"]["runs"].values():
        for r in run["results"]:
            by_file.setdefault(r["mutant"].split(":", 1)[0], []).append(Result(**r))
    return by_file


def _ran(rs: list[Result]) -> int:
    return sum(1 for r in rs if r.status != "not-run")


def _cov_under(d: Data) -> list[str]:
    lt, bt = d["coverage"]["line_target"], d["coverage"]["branch_target"]
    return [
        r["file"]
        for r in d["coverage"]["rows"]
        if not r["ci_nightly"] or r["ci_nightly"]["line"] < lt or r["ci_nightly"]["branch"] < bt
    ]


def verdict(d: Data) -> str:
    m = d["mutation"]
    by_file = _results(d)
    every = [r for rs in by_file.values() for r in rs]
    s, c = score(every)
    scored = len(every) - c.get("accepted", 0) - c.get("not-run", 0)
    made = sum(m["made"].values())
    under = [f"`{f.rsplit('/', 1)[1]}` {score(rs)[0]:.1f} %" for f, rs in sorted(by_file.items()) if score(rs)[0] < 60]
    ci = m["ci_nightly_2026_11_16"]
    cov_under = _cov_under(d)
    rows = d["coverage"]["rows"]
    high = [f["id"] for f in d["findings"]["findings"] if f["severity"] == "High"]
    lines = [
        "**Criterion 3's \"writes the safety core's mutation score to the repository, at or above the agreed floor\" "
        "does not hold today.** The nightly writes no score to the repository (V4-01).",
        "",
        f"* Measured here on `{m['commit'][:8]}`: **{s:.1f} %** ({c.get('killed', 0) + c.get('timeout', 0)} killed) "
        f"over {scored} scored mutants of about {made:,} the tool makes; `engine.py` one part of six. Floor "
        f"{m['runs']['small']['floor']:.0f} %, threshold {m['runs']['small']['threshold']:.0f} %.",
        f"* Under the floor alone: {', '.join(under)}.",
        f"* The nightly of 2026-11-16 ({CI}, all cores, every mutant of its own commit): {ci['score']} %. It is not "
        "the same measurement and the two are not compared.",
        f"* Coverage ({CI}): {len(rows) - len(cov_under)} of {len(rows)} safety-core files meet 95 % line and 90 % "
        f"branch; under: {', '.join(f'`{f}`' for f in cov_under)}.",
        f"* High findings: {', '.join(high) if high else 'none'}.",
    ]
    return "\n".join(lines) + "\n"


def ran(d: Data) -> str:
    m = d["mutation"]
    lines = ["| Run | Command | Started (UTC) | Ended (UTC) | Mutants | Not run |"]
    lines.append("| --- | --- | --- | --- | ---: | ---: |")
    for name, run in m["runs"].items():
        n_out = sum(1 for r in run["results"] if r["status"] == "not-run")
        lines.append(
            f"| {name} | `{run['command']}` | {run['started']} | {run['ended']} | {len(run['results'])} | {n_out} |"
        )
    loc = d["coverage"]["local_target_tests"]
    lines += ["", f"Coverage of the target tests on `{loc['commit'][:8]}`: {loc['result']}.", ""]
    lines.append(f"Nightly figures: {m['ci_nightly_2026_11_16']['fetched']}.")
    lines.append(f"Nightly run list: {d['nightly_runs']['fetched']}.")
    return "\n".join(lines) + "\n"


def mutation(d: Data) -> str:
    made = d["mutation"]["made"]
    lines = [
        "| File | Made | Run here | Not run here | Killed | Timeout | Survived | No coverage | Error | Accepted "
        "| Score over those run |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    every: list[Result] = []
    for file, rs in sorted(_results(d).items()):
        every += rs
        lines.append(_mutation_row(f"`{file}`", made.get(file, 0), rs))
    lines.append(_mutation_row("**all**", sum(made.values()), every))
    return "\n".join(lines) + "\n"


def _mutation_row(name: str, made: int, rs: list[Result]) -> str:
    s, c = score(rs)
    n = _ran(rs)
    cells = [made, n, made - n, c.get("killed", 0), c.get("timeout", 0), c.get("survived", 0)]
    cells += [c.get("no-coverage", 0), c.get("error", 0), c.get("accepted", 0)]
    return f"| {name} | " + " | ".join(str(x) for x in cells) + f" | {s:.1f} % |"


def nightly(d: Data) -> str:
    ci = d["mutation"]["ci_nightly_2026_11_16"]
    lines = [f"| Target ({CI}) | Mutants | Baseline run (s) |", "| --- | ---: | ---: |"]
    lines += [f"| `{k}` | {v['mutants']} | {v['baseline_s']} |" for k, v in ci["targets"].items()]
    counts = ", ".join(f"{k} {v}" for k, v in sorted(ci["counts"].items()))
    lines += ["", f"Score {ci['score']} % ({counts}); run {ci['run']}."]
    return "\n".join(lines) + "\n"


def nightly_runs(d: Data) -> str:
    lines = ["| Run | Created | Commit | Conclusion |", "| --- | --- | --- | --- |"]
    for r in d["nightly_runs"]["runs"]:
        lines.append(f"| {r['databaseId']} | {r['createdAt']} | `{r['headSha'][:8]}` | {r['conclusion']} |")
    return "\n".join(lines) + "\n"


def survivors(d: Data) -> str:
    lines = ["| Mutant | Inv. | What no test checks | Finding | Example test |", "| --- | --- | --- | --- | --- |"]
    for s in d["survivors"]["survivors"]:
        lines.append(f"| `{s['mutant']}` | {s['inv']} | {s['untested']} | {s['finding']} | {s['example'] or '-'} |")
    return "\n".join(lines) + "\n"


def coverage(d: Data) -> str:
    lt, bt = d["coverage"]["line_target"], d["coverage"]["branch_target"]
    lines = [
        f"| File | Line ({CI}) | Branch ({CI}) | Arcs missed ({CI}) | Line (target tests, here) "
        "| Branch (target tests, here) | Baseline line | Baseline branch | Against target |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in d["coverage"]["rows"]:
        ci, loc, base = r["ci_nightly"] or {}, r["local_target_tests"] or {}, r["baseline"] or {}
        verdict_ = "met" if ci and ci["line"] >= lt and ci["branch"] >= bt else "UNDER"
        missed = len(ci.get("missing_branches", []))
        lines.append(
            f"| `{r['file']}` | {_pct(ci.get('line'))} | {_pct(ci.get('branch'))} | {missed} "
            f"| {_pct(loc.get('line'))} | {_pct(loc.get('branch'))} | {_pct(base.get('line'))} | "
            f"{_pct(base.get('branch'))} | {verdict_} |"
        )
    return "\n".join(lines) + "\n"


def lake(d: Data) -> str:
    lk = d["lake"]
    lines = [f"Rule: {lk['rule']}.", ""]
    for side, groups in (("In process", lk["in_process"]), ("Over HTTP", lk["http"])):
        for name, files in groups.items():
            lines += [f"<details><summary>{side}, naming {name}: {len(files)} files</summary>", ""]
            lines += [f"- `{f}`" for f in files]
            lines += ["", "</details>", ""]
    return "\n".join(lines)


def weak(d: Data) -> str:
    lines = ["| Test | Why it is weak | The change that would make it bite | Basis | Evidence |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for t in d["weak_tests"]["tests"]:
        lines.append(f"| `{t['test']}` | {t['why']} | `{t['change']}` | {t['basis']} | {t['evidence'] or '-'} |")
    return "\n".join(lines) + "\n"


def findings(d: Data) -> str:
    lines = ["| Id | Severity | Lane | Basis | Place | Claim |", "| --- | --- | --- | --- | --- | --- |"]
    for f in d["findings"]["findings"]:
        claim = f["claim"].replace("|", "\\|")
        lines.append(f"| {f['id']} | {f['severity']} | {f['lane']} | {f['basis']} | `{f['place']}` | {claim} |")
    return "\n".join(lines) + "\n"


RENDER: dict[str, Callable[[Data], str]] = {
    "verdict": verdict,
    "ran": ran,
    "mutation": mutation,
    "nightly": nightly,
    "nightly_runs": nightly_runs,
    "survivors": survivors,
    "coverage": coverage,
    "lake": lake,
    "weak": weak,
    "findings": findings,
}
NAMES = tuple(RENDER)


def render(page: Path) -> dict[str, str]:
    d = _load(page)
    return {name: fn(d) for name, fn in RENDER.items()}


def _bad_survivors(page: Path) -> bool:
    d = _load(page)
    alive = {r.mutant for rs in _results(d).values() for r in rs if r.status in ("survived", "no-coverage")}
    return any(s["mutant"] not in alive for s in d["survivors"]["survivors"])


def check(page: Path = PAGE) -> list[str]:
    """The names of the blocks that differ from their JSON (a missing block counts as differing)."""
    text = page.read_text(encoding="utf-8")
    found = {m.group(2): m.group(3) for m in _BLOCK.finditer(text)}
    want = render(page)
    bad = [name for name in NAMES if found.get(name) != want[name]]
    if _bad_survivors(page) and "survivors" not in bad:
        bad.append("survivors")
    return bad


def write(page: Path = PAGE) -> None:
    want = render(page)
    text = page.read_text(encoding="utf-8")
    page.write_text(_BLOCK.sub(lambda m: m.group(1) + want.get(m.group(2), m.group(3)) + m.group(4), text), "utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.test_trust", description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", type=Path, default=PAGE)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        write(args.page)
        return 0
    bad = check(args.page)
    for name in bad:
        print(f"{args.page}: the block '{name}' differs from its JSON (run python -m tools.test_trust --write)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
