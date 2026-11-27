"""The e2e-box gate's verdict on one run (TRIAGE-1 G1, G5).

    verdict.py RUN_DIR [BASELINE_JOURNEYS_CSV] [KNOWN_TSV]

Reads RUN_DIR/metrics/steps.csv (the last row of each journey step counts) and writes metrics/journeys.csv (one row
per journey) and metrics/fails.tsv (each product failure, with its listed finding or NEW). A failure the driver
caused (HARNESS) or a refusal the product is meant to give at that point (BY_DESIGN) is counted apart.
GREEN only when:
  * the install passed;
  * every product failure is listed in KNOWN_TSV (journey, step, finding, owner, release note);
  * no journey regressed against the baseline run (fewer passes or more product failures);
  * every setting that differs between the box as installed and the box before the update journey
    (metrics/config-installed.txt against metrics/config-checked.txt) is named by a DEVIATION row.
Prints one line ``E2E <id> GREEN|RED ...`` (also written to RUN_DIR/verdict) and the reasons; exit 0 only on GREEN.
"""

import csv
import re
import sys
from pathlib import Path

HARNESS = re.compile(
    r"Cannot read properties|context or browser has been closed|was not saved by an earlier step|harness"
    r"|Failed to find browser context|ERR_SSL_PROTOCOL_ERROR|no update is in progress"
)
BY_DESIGN = re.compile(
    r"Not opened: choose this study|is startup: lists run only|No one to screen|scope could not be counted"
    r"|open every amber row|cannot follow Consented|set by someone else and not used since|/approve -> 409"
    r"|This candidate page is closed|newer night|the box never moves back in time"
)
COLS = ["journey", "steps", "pass", "fail_product", "refused_by_design", "fail_harness", "skipped", "seconds_total",
        "slowest_step", "slowest_seconds"]  # fmt: skip


def latest(steps: Path) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for r in csv.DictReader(steps.read_text(encoding="utf-8").splitlines()):
        out[(r["journey"], r["step"])] = r
    return out


def kind(r: dict[str, str]) -> str:
    if r["result"] in ("PASS", "SKIP"):
        return r["result"].lower()
    if HARNESS.search(r["detail"] + " " + r["step"]):
        return "harness"
    if BY_DESIGN.search(r["detail"]):
        return "design"
    return "product"


def journeys(rows: dict[tuple[str, str], dict[str, str]]) -> dict[str, dict[str, str]]:
    agg: dict[str, dict[str, float]] = {}
    slow: dict[str, tuple[str, float]] = {}
    for (j, s), r in rows.items():
        if j == "DEVIATION":
            continue
        a = agg.setdefault(j, dict.fromkeys(("steps", "pass", "product", "design", "harness", "skip", "sec"), 0.0))
        k, sec = kind(r), float(r["seconds"] or 0)
        a["steps"] += 1
        a["sec"] += sec
        a[k] += 1
        if sec >= slow.get(j, ("", -1.0))[1]:
            slow[j] = (s, sec)
    return {j: {"journey": j, "steps": str(int(a["steps"])), "pass": str(int(a["pass"])), "fail_product": str(int(a["product"])),
                "refused_by_design": str(int(a["design"])), "fail_harness": str(int(a["harness"])),
                "skipped": str(int(a["skip"])), "seconds_total": f"{a['sec']:.1f}", "slowest_step": slow[j][0][:80],
                "slowest_seconds": f"{slow[j][1]:.1f}"} for j, a in sorted(agg.items())}  # fmt: skip


def known(path: Path | None) -> dict[tuple[str, str], str]:
    if not path or not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            j, s, finding, owner, *_ = [*line.split("\t"), "", "", ""][:5]
            out[(j, s)] = f"{finding} ({owner})"
    return out


def config(path: Path) -> dict[str, str]:
    """``name sha`` lines: env:KEY for deploy/.env, file:PATH for the site's files (values never, only their hash)."""
    if not path.exists():
        return {}
    return dict(line.split(" ", 1) for line in path.read_text(encoding="utf-8").splitlines() if " " in line)


def regressions(now: dict[str, dict[str, str]], baseline: Path | None) -> list[str]:
    if not baseline or not baseline.exists():
        return []
    out = []
    for b in csv.DictReader(baseline.read_text(encoding="utf-8").splitlines()):
        n = now.get(b["journey"])
        if n and (int(n["pass"]) < int(b["pass"]) or int(n["fail_product"]) > int(b["fail_product"])):
            out.append(
                f"{b['journey']}: pass {b['pass']} -> {n['pass']}, product failures {b['fail_product']} -> {n['fail_product']}"
            )
    return out


def main(run: Path, baseline: Path | None = None, known_tsv: Path | None = None) -> int:
    m = run / "metrics"
    rows = latest(m / "steps.csv")
    per = journeys(rows)
    with (m / "journeys.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(per.values())
    listed = known(known_tsv)
    fails = [(j, s, r) for (j, s), r in rows.items() if j != "DEVIATION" and kind(r) == "product"]
    unlisted = [(j, s) for j, s, _ in fails if (j, s) not in listed]
    with (m / "fails.tsv").open("w", encoding="utf-8") as fh:
        for j, s, r in fails:
            fh.write(f"{j}\t{s}\t{listed.get((j, s), 'NEW')}\t{r['detail'][:200]}\n")
    devs = [s for (j, s), r in rows.items() if j == "DEVIATION"]
    before, after = config(m / "config-installed.txt"), config(m / "config-checked.txt")
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    unrecorded = [k for k in changed if not any(k.split(":", 1)[1].rsplit("/", 1)[-1] in d for d in devs)]
    regressed = regressions(per, baseline)
    installed = any(
        j == "INSTALL" and s.startswith("one-command install") and r["result"] == "PASS" for (j, s), r in rows.items()
    )
    green = installed and not unlisted and not regressed and not unrecorded
    tot = {
        c: sum(int(p[c]) for p in per.values())
        for c in ("steps", "pass", "fail_product", "refused_by_design", "fail_harness", "skipped")
    }
    line = (f"E2E {run.name} {'GREEN' if green else 'RED'} steps={tot['steps']} pass={tot['pass']} fail_product={tot['fail_product']} "
            f"listed={len(fails) - len(unlisted)} unlisted={len(unlisted)} by_design={tot['refused_by_design']} "
            f"harness={tot['fail_harness']} skipped={tot['skipped']} regressed={len(regressed)} deviations={len(devs)} "
            f"unrecorded={len(unrecorded)}")  # fmt: skip
    reasons = ([] if installed else ["the install did not pass"]) + [f"unlisted FAIL [{j}] {s}" for j, s in unlisted]
    reasons += [f"regressed {g}" for g in regressed] + [f"unrecorded deviation {k}" for k in unrecorded]
    (run / "verdict").write_text(line + "\n" + "".join(f"  {r}\n" for r in reasons), encoding="utf-8")
    print(line)
    for why in reasons:
        print(" ", why)
    return 0 if green else 1


if __name__ == "__main__":
    args = [Path(a) if a else None for a in sys.argv[2:4]]
    sys.exit(main(Path(sys.argv[1]), *args))
