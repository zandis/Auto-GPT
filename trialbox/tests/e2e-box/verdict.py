"""The e2e-box gate's verdict on one run (TRIAGE-1 G1, G5).

    verdict.py RUN_DIR [BASELINE_JOURNEYS_CSV] [KNOWN_TSV]

Reads RUN_DIR/metrics/steps.csv (the last row of each journey step counts; a step that failed and was then run again
under a recorded deviation has a step name of its own, so its first failure stays) and writes metrics/journeys.csv
(one row per journey) and metrics/fails.tsv (each product failure or skip, with its listed finding or NEW). A failure
the driver caused (HARNESS) and a refusal the product is meant to give at that point (BY_DESIGN) are counted apart.
GREEN only when:
  * the install passed and the box's settings were snapshotted after it;
  * every product failure and every skipped step is listed in KNOWN_TSV with all five fields (journey, step, finding,
    owner, release note);
  * the run is conclusive: no harness failure and no deviation that failed to apply;
  * no journey of the baseline run regressed (fewer passes, more product failures) or vanished;
  * every setting that differs between the box as installed and the box before the update journey
    (metrics/config-installed.txt against metrics/config-checked.txt) is named by a DEVIATION row that applied.
Prints one line ``E2E <id> GREEN|RED ...`` (also written to RUN_DIR/verdict) and the reasons; exit 0 only on GREEN.
"""

import csv
import re
import sys
from pathlib import Path

# matched on the detail only (never on the step's own name), each a failure of the driver, not of the box
HARNESS = re.compile(
    r"Cannot read properties|context or browser has been closed|was not saved by an earlier step"
    r"|Failed to find browser context|no result: the browser runner stopped"
)
# the only refusals the journeys expect: a candidate page before the PI's IRB record; an older night after a newer one
BY_DESIGN = re.compile(
    r"This candidate page is closed|a newer night .* is already served|the box never moves back in time"
)
COLS = ["journey", "steps", "pass", "fail_product", "refused_by_design", "fail_harness", "skipped", "seconds_total",
        "slowest_step", "slowest_seconds"]  # fmt: skip


def latest(steps: Path) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    if steps.exists():
        for r in csv.DictReader(steps.read_text(encoding="utf-8").splitlines()):
            out[(r["journey"], r["step"])] = r
    return out


def kind(r: dict[str, str]) -> str:
    if r["result"] in ("PASS", "SKIP"):
        return r["result"].lower()
    if HARNESS.search(r["detail"]):
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
    """Listed rows with all five fields filled; a row missing its finding, owner or release note lists nothing."""
    if not path or not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        f = [x.strip() for x in line.split("\t")]
        if line.strip() and not line.startswith("#") and len(f) >= 5 and all(f[:5]):
            out[(f[0], f[1])] = f"{f[2]} ({f[3]})"
    return out


def config(path: Path) -> dict[str, str]:
    """``name sha`` lines: env:KEY for deploy/.env, file:PATH for the site's files (values never, only their hash)."""
    if not path.exists():
        return {}
    return dict(line.split(" ", 1) for line in path.read_text(encoding="utf-8").splitlines() if " " in line)


def named(key: str, deviations: list[str]) -> bool:
    """A changed setting is named when an applied deviation's text holds its key (env) or file name as a whole word."""
    word = re.escape(key.split(":", 1)[1].rsplit("/", 1)[-1])
    return any(re.search(rf"(?<![\w.-]){word}(?![\w-])", d) for d in deviations)


def regressions(now: dict[str, dict[str, str]], baseline: Path | None) -> list[str]:
    if not baseline or not baseline.exists():
        return []
    out = []
    for b in csv.DictReader(baseline.read_text(encoding="utf-8").splitlines()):
        n = now.get(b["journey"])
        if n is None:
            out.append(f"{b['journey']}: in the baseline, not in this run")
        elif int(n["pass"]) < int(b["pass"]) or int(n["fail_product"]) > int(b["fail_product"]):
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
    steps = [(j, s, r) for (j, s), r in rows.items() if j != "DEVIATION"]
    fails = [(j, s, r) for j, s, r in steps if kind(r) == "product"]
    skips = [(j, s, r) for j, s, r in steps if kind(r) == "skip"]
    unlisted = [(j, s) for j, s, _ in fails + skips if (j, s) not in listed]
    with (m / "fails.tsv").open("w", encoding="utf-8") as fh:
        for j, s, r in fails + skips:
            fh.write(f"{j}\t{s}\t{r['result']}\t{listed.get((j, s), 'NEW')}\t{r['detail'][:200]}\n")
    harness = [(j, s) for j, s, r in steps if kind(r) == "harness"]
    devs = [s for (j, s), r in rows.items() if j == "DEVIATION" and r["result"] == "APPLIED"]
    failed_devs = [s for (j, s), r in rows.items() if j == "DEVIATION" and r["result"] != "APPLIED"]
    before, after = config(m / "config-installed.txt"), config(m / "config-checked.txt")
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    unrecorded = [k for k in changed if not named(k, devs)]
    regressed = regressions(per, baseline)
    installed = any(
        j == "INSTALL" and s.startswith("one-command install") and r["result"] == "PASS" for (j, s), r in rows.items()
    )
    reasons = [] if installed else ["the install did not pass"]
    if installed and not before:
        reasons.append("no snapshot of the box's settings after the install")
    reasons += [f"unlisted {rows[(j, s)]['result']} [{j}] {s}" for j, s in unlisted]
    reasons += [f"inconclusive: harness failure [{j}] {s}" for j, s in harness]
    reasons += [f"inconclusive: deviation not applied: {d}" for d in failed_devs]
    reasons += [f"regressed {g}" for g in regressed] + [f"unrecorded deviation {k}" for k in unrecorded]
    green = not reasons
    tot = {
        c: sum(int(p[c]) for p in per.values())
        for c in ("steps", "pass", "fail_product", "refused_by_design", "fail_harness", "skipped")
    }
    line = (f"E2E {run.name} {'GREEN' if green else 'RED'} steps={tot['steps']} pass={tot['pass']} fail_product={tot['fail_product']} "
            f"listed={len(fails) + len(skips) - len(unlisted)} unlisted={len(unlisted)} by_design={tot['refused_by_design']} "
            f"harness={tot['fail_harness']} skipped={tot['skipped']} regressed={len(regressed)} deviations={len(devs)} "
            f"unrecorded={len(unrecorded)}")  # fmt: skip
    (run / "verdict").write_text(line + "\n" + "".join(f"  {why}\n" for why in reasons), encoding="utf-8")
    print(line)
    for why in reasons:
        print(" ", why)
    return 0 if green else 1


if __name__ == "__main__":
    args = [Path(a) if a else None for a in sys.argv[2:4]]
    sys.exit(main(Path(sys.argv[1]), *args))
