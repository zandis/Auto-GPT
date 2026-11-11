"""coverage_ratchet: no package of the tree loses coverage unnoticed (T-651, ENG-029; TB-DR-04 §3.2).

    python -m tools.coverage_ratchet coverage.json                     # print the table; exit 1 on a drop
    python -m tools.coverage_ratchet coverage.json --write-baseline    # take this run as the new baseline

The input is pytest-cov's JSON report (``--cov-report=json:<path>``) of the unit suite. Files are grouped by package
(``services/<name>``, ``libs/<name>``, ``tools``) and compared with ``tools/coverage_baseline.json``:

* a package whose line or branch percentage is more than ``TOLERANCE`` (0.5) points under its baseline fails;
* a safety-core file (``[safety_core]`` of ``tools/mutation.toml``) must hold 95 % line and 90 % branch; a file
  that is not there yet must not fall more than the tolerance under its own baseline (it is listed as under target);
* branch figures are compared only when both the run and the baseline have them. The pull-request unit job measures
  lines only (``COVERAGE_CORE=sysmon``, cheap); the nightly run measures branches too.

A package or file with no baseline is listed and never fails. A rise is never a failure: when a package rises by more
than a point the table says so, and ``--write-baseline`` (run on the unit job's ``coverage.json`` artifact, then
committed) moves the ratchet up. Writing keeps the baseline's branch figures when the run has none.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "coverage_baseline.json"
TOLERANCE = 0.5  # points
LINE_TARGET = 95.0  # safety-core files (TB-PLAN-06 T-651)
BRANCH_TARGET = 90.0


@dataclass
class Counts:
    statements: int = 0
    covered: int = 0
    branches: int = 0
    covered_branches: int = 0
    has_branches: bool = False

    def add(self, summary: Mapping[str, object], has_branches: bool) -> None:
        self.statements += int(summary.get("num_statements", 0))  # type: ignore[call-overload]
        self.covered += int(summary.get("covered_lines", 0))  # type: ignore[call-overload]
        self.branches += int(summary.get("num_branches", 0) or 0)  # type: ignore[call-overload]
        self.covered_branches += int(summary.get("covered_branches", 0) or 0)  # type: ignore[call-overload]
        self.has_branches = self.has_branches or has_branches

    @property
    def line(self) -> float:
        return 100.0 * self.covered / self.statements if self.statements else 100.0

    @property
    def branch(self) -> float | None:
        if not self.has_branches:
            return None
        return 100.0 * self.covered_branches / self.branches if self.branches else 100.0

    def figures(self) -> dict[str, float | int]:
        out: dict[str, float | int] = {"statements": self.statements, "line": round(self.line, 2)}
        if self.branch is not None:
            out["branch"] = round(self.branch, 2)
        return out


def package_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] in ("services", "libs") and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if len(parts) > 1 else "."


def _relative(path: str, root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(root)
        except ValueError:
            return p.as_posix()
    return p.as_posix()


def measure(report: Mapping[str, object], root: Path = ROOT) -> tuple[dict[str, Counts], dict[str, Counts]]:
    """(per package, per file) from a coverage JSON report."""
    has_branches = bool(report.get("meta", {}).get("branch_coverage"))  # type: ignore[attr-defined]
    packages: dict[str, Counts] = {}
    files: dict[str, Counts] = {}
    for name, data in report.get("files", {}).items():  # type: ignore[attr-defined]
        rel = _relative(name, root)
        summary = data.get("summary", {})
        packages.setdefault(package_of(rel), Counts()).add(summary, has_branches)
        files.setdefault(rel, Counts()).add(summary, has_branches)
    return packages, files


def safety_core(config: Path = ROOT / "tools" / "mutation.toml") -> list[str]:
    import tomllib

    data = tomllib.loads(config.read_text(encoding="utf-8"))
    return list(data.get("safety_core", {}).get("files", []))


@dataclass
class Row:
    name: str
    statements: int
    line: float
    base_line: float | None
    branch: float | None
    base_branch: float | None
    status: str  # ok | DROP | under target | new | up


def _get(base: Mapping[str, float] | None, kind: str) -> float | None:
    return None if base is None else base.get(kind)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _delta(now: float | None, base: float | None) -> str:
    return "-" if now is None or base is None else f"{round(now - base, 1) + 0.0:+.1f}"  # no "-0.0"


def check(
    packages: Mapping[str, Counts],
    files: Mapping[str, Counts],
    baseline: Mapping[str, Mapping[str, Mapping[str, float]]],
    core: Sequence[str],
) -> tuple[list[Row], list[Row], list[str]]:
    """(package rows, safety-core rows, failures)."""
    failures: list[str] = []
    prows: list[Row] = []
    base_p = baseline.get("packages", {})
    for name in sorted(packages):
        c, b = packages[name], base_p.get(name)
        status = "new"
        if b is not None:
            status = "ok"
            for kind, now in (("line", c.line), ("branch", c.branch)):
                was = b.get(kind)
                if now is None or was is None:
                    continue
                if now < was - TOLERANCE:
                    status = "DROP"
                    failures.append(
                        f"{name}: {kind} coverage {now:.2f} % is under the baseline {was:.2f} % - {TOLERANCE}"
                    )
                elif now > was + 1.0 and status == "ok":
                    status = "up"
        prows.append(Row(name, c.statements, c.line, _get(b, "line"), c.branch, _get(b, "branch"), status))
    crows: list[Row] = []
    base_f = baseline.get("files", {})
    for name in core:
        b = base_f.get(name)
        if name not in files:
            crows.append(Row(name, 0, 0.0, _get(b, "line"), None, _get(b, "branch"), "not measured"))
            continue
        c = files[name]
        status = "ok"
        for kind, now, target in (("line", c.line, LINE_TARGET), ("branch", c.branch, BRANCH_TARGET)):
            if now is None:
                continue
            was = b.get(kind) if b else None
            floor = target if was is None or was >= target else was - TOLERANCE
            if was is None and now < target:
                status = "under target" if status == "ok" else status
                continue
            if now < floor:
                status = "DROP"
                failures.append(f"{name}: {kind} coverage {now:.2f} % is under its floor {floor:.2f} %")
            elif now < target and status == "ok":
                status = "under target"
        crows.append(Row(name, c.statements, c.line, _get(b, "line"), c.branch, _get(b, "branch"), status))
    return prows, crows, failures


def render(prows: Sequence[Row], crows: Sequence[Row], failures: Sequence[str]) -> str:
    head = "| {} | Statements | Line % | Baseline | Δ | Branch % | Baseline | Δ | Status |"
    rule = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    out = ["### Coverage by package", "", head.format("Package"), rule]
    for r in prows:
        out.append(
            f"| {r.name} | {r.statements} | {r.line:.1f} | {_fmt(r.base_line)} | {_delta(r.line, r.base_line)} | "
            f"{_fmt(r.branch)} | {_fmt(r.base_branch)} | {_delta(r.branch, r.base_branch)} | {r.status} |"
        )
    out += ["", f"### Safety-core files (target {LINE_TARGET:.0f} % line, {BRANCH_TARGET:.0f} % branch)", ""]
    out += [head.format("File"), rule]
    for r in crows:
        out.append(
            f"| `{r.name}` | {r.statements} | {r.line:.1f} | {_fmt(r.base_line)} | {_delta(r.line, r.base_line)} | "
            f"{_fmt(r.branch)} | {_fmt(r.base_branch)} | {_delta(r.branch, r.base_branch)} | {r.status} |"
        )
    out.append("")
    if failures:
        out += [f"Coverage fell (tolerance {TOLERANCE:.1f} point):", ""] + [f"* {f}" for f in failures]
    else:
        out.append(f"No package and no safety-core file fell more than {TOLERANCE:.1f} point under its baseline.")
    return "\n".join(out) + "\n"


def write_baseline(
    path: Path,
    packages: Mapping[str, Counts],
    files: Mapping[str, Counts],
    core: Sequence[str],
    old: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> None:
    def merged(now: dict[str, float | int], was: Mapping[str, float] | None) -> dict[str, float | int]:
        if "branch" not in now and was and "branch" in was:
            now["branch"] = was["branch"]
        return now

    data = {
        "note": "tools/coverage_ratchet.py --write-baseline (T-651); line from the unit job, branch from the nightly",
        "packages": {k: merged(packages[k].figures(), old.get("packages", {}).get(k)) for k in sorted(packages)},
        "files": {k: merged(files[k].figures(), old.get("files", {}).get(k)) for k in core if k in files},
    }
    path.write_text(json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.coverage_ratchet", description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path, help="pytest-cov JSON report")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--write-baseline", action="store_true", help="write this run as the baseline and exit 0")
    args = ap.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else {}
    packages, files = measure(report)
    core = safety_core()
    if args.write_baseline:
        write_baseline(args.baseline, packages, files, core, baseline)
        print(f"wrote {args.baseline}")
        return 0
    prows, crows, failures = check(packages, files, baseline, core)
    text = render(prows, crows, failures)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Coverage ratchet\n\n" + text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
