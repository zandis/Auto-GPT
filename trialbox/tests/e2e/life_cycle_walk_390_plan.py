"""H-21 (D-1138): H-20's whole-life-cycle walk on a phone, 390 px wide, and what does not fit there.

The same steps, roles, languages and refusals as ``tests/e2e/life_cycle_walk_plan.py`` (H-20, D-1135), driven by the
same browser driver (``tests/e2e/life_cycle_walk.js``) with a phone's viewport: 390 x 844 px, a touch screen. The
driver measures every page it reaches and every control it clicks (a horizontal page scroll, a control off the screen
or covered, a tap target under the size the UI spec names, text cut, a table wider than the screen) and writes them to
its log with a screenshot each, outside the repository. A control the phone cannot reach stops the walk there.

:data:`FINDINGS` is the findings list by step, read from the logs of the runs of 2026-11-17, each with where its
expectation comes from: ``docs/plan/design/09-ui-ux-spec.md`` (§10 "Phone (390 px)", the WCAG table: 1.4.10 reflow
without horizontal scroll at 390 px; 2.5.8 targets of at least 24 x 24 px, the PI's mark buttons at least 44 x 44 px
on a phone; the phone's pages: the role's work list, the PI home, S20 approval, the report, the PI's card list and
marks; "data entry and reveal are desktop only") and ``docs/plan/design/01-SRS.md`` FR-UI-09. The card's own 44 px
for every other control is logged as its own kind. ``docs/handover/life-cycle-walk-390-findings-2026-11-17.md`` holds
the findings table as :func:`render_findings` writes it; a fast test keeps them equal. The walk reports and fixes
nothing: no product file is changed, and no fault is asserted as correct.

    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_390_plan --plan en      # the browser's plan
    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_390_plan --write        # rewrite the table
    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_390_plan --summary LOG.. # the logs' measures
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.e2e import life_cycle_walk_plan as lp
from tests.e2e import new_study_walk_plan as nw

ROOT = nw.ROOT
LANGS = nw.LANGS
#: a phone (docs/plan/design/04-verification-operations.md: "phone 390 x 844")
VIEWPORT = {"width": 390, "height": 844}
#: the phone walk's own new ruleset ids (never H-10's or H-20's: the walks may share one box)
RULESETS = {"en": "LIFEPHONE", "zh-TW": "LIFEPHONEZH", "ja": "LIFEPHONEJA"}
FINDINGS_PAGE = ROOT / "docs" / "handover" / "life-cycle-walk-390-findings-2026-11-17.md"
BEGIN = "<!-- life-cycle-walk-390: findings, written by tests/e2e/life_cycle_walk_390_plan.py; do not edit by hand -->"
END = "<!-- life-cycle-walk-390: end of findings -->"
SEVERITIES = lp.SEVERITIES
LANES = lp.LANES
#: the measures of the driver (``pageMeasures`` and ``reachable`` in tests/e2e/life_cycle_walk.js)
KINDS = (
    "behind the menu",
    "page scrolls sideways",
    "off the screen",
    "covered",
    "cannot be reached",
    "target under 24 px",
    "mark button under 44 px",
    "target under 44 px",
    "text cut",
    "table wider than the screen",
    "not shown on the phone",
)
SPEC = "`docs/plan/design/09-ui-ux-spec.md`"


@dataclass(frozen=True)
class Finding:
    """One finding at 390 px: the step and role, the page (path), the measure (:data:`KINDS`), what the page showed,
    what was expected and where that comes from, the severity and the owning lane."""

    id: str
    step: int
    role: str
    path: str
    kind: str
    showed: str
    expected: str
    source: str
    severity: str
    lane: str
    also: tuple[int, ...] = ()  # the other steps the same measure was seen at, on the same pages

    def steps(self) -> tuple[int, ...]:
        return (self.step, *self.also)


TABLES = "the table scrolls sideways inside its own frame, the page does not"

FINDINGS: tuple[Finding, ...] = (
    Finding("P-01", 1, "coordinator", "/home", "behind the menu",
            "on a phone the top bar's links, the language box and Sign out are behind \"☰ Menu\"; that visible "
            "label is hidden from assistive technology (`aria-hidden`), the accessible control being a hidden check "
            "box named \"Menu\"; the walk finds the button by its data-testid, at every step and every role",
            "one Menu button that is the control a person sees and the one assistive technology names",
            "D-133 (\"one Menu button\"); WCAG 4.1.2 in " + SPEC + " (accessibility table)",
            "cosmetic", "C2", also=tuple(range(2, 23))),
    Finding("P-02", 3, "coordinator", "/pilot/jobs/{job}", "table wider than the screen",
            "the job page's thread table is 666 to 861 px wide and the SCREEN job's rows 783 to 894 px (en to ja); "
            + TABLES,
            "the job page in one column on a phone (not among the phone's pages)", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2", also=(7, 8, 9, 10, 11, 13)),
    Finding("P-03", 4, "coordinator", "/pilot/jobs/{job}/approval", "table wider than the screen",
            "in ja only, the approval table (S20) is 463 to 485 px wide; " + TABLES,
            "S20 approval readable on a phone (\"allowed on a phone when no row is amber\")",
            SPEC + " §10 (phone 390–767 px: S20 approval), S20", "cosmetic", "C2", also=(5, 7, 8)),
    Finding("P-04", 6, "steward", "/studies/{rs}/team", "table wider than the screen",
            "the delegation log is 792 to 932 px wide; " + TABLES,
            "not among the phone's pages: no expectation for a phone", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2", also=(19,)),
    Finding("P-05", 9, "coordinator", "/studies/{rs}/feasibility", "table wider than the screen",
            "the feasibility funnel is 435 to 501 px wide and the reports list 416 to 466 px; " + TABLES,
            "S3 report readable on a phone", SPEC + " §10 (phone 390–767 px: S3 report)",
            "cosmetic", "C2"),
    Finding("P-06", 9, "coordinator", "/studies/{rs}/feasibility", "target under 44 px",
            "in zh-TW and ja the report's five step links (\"狀態 1\" … , \"状況 1\" …) are 40 and 31 px wide by 44 "
            "px; in en they are wider",
            "44 px controls on a phone (the card's size; the spec asks 24 px except for the PI's marks)",
            SPEC + " (2.5.8)", "cosmetic", "C2"),
    Finding("P-07", 11, "operator", "/home", "target under 24 px",
            "the administrator's home: the tabs and links \"Jobs\", \"Services and models\", \"Sources and "
            "licences\", \"Open\", \"Mail notices\" (seven in all) are 20 px high",
            "targets at least 24 x 24 px", SPEC + " (2.5.8 Target size (minimum))", "slows the tester", "C2"),
    Finding("P-08", 11, "coordinator", "/studies/{rs}/week", "table wider than the screen",
            "the weekly page's worklist is a table 437 to 482 px wide; " + TABLES,
            "on a phone a card list instead of a table: pseudonym, next visit, state counts, mark buttons",
            SPEC + " §10 (\"Phone (390 px): card list instead of table\"), S5 (\"Table (phone: cards)\"); FR-UI-09",
            "slows the tester", "C2", also=(12, 13, 14, 15, 18, 20)),
    Finding("P-09", 11, "coordinator", "/studies/{rs}/candidates", "table wider than the screen",
            "the candidate list is 643 to 724 px wide; " + TABLES,
            "not among the phone's pages: no expectation for a phone", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2", also=(12, 20)),
    Finding("P-10", 12, "coordinator", "/studies/{rs}/week", "not shown on the phone",
            "the coordinator's line \"The investigator decides here; you get a task…\" is only in the patient "
            "sheet, which a phone shows after a row is tapped; the desktop shows it beside the list",
            "the list first on a phone, the sheet after a tap", "D-133 (the phone's sheet)", "cosmetic", "C2"),
    Finding("P-11", 15, "coordinator", "/studies/{rs}/week", "covered",
            "with a patient's sheet open, the sheet's bar (\"← Back to the list\") covers \"☰ Menu\": the "
            "coordinator taps Back first to reach the menu and My studies",
            "the menu reachable from every page", "D-133 (Back, Next and the menu on the phone's sheet)",
            "slows the tester", "C2"),
    Finding("P-12", 17, "coordinator", "/studies/{rs}/state", "table wider than the screen",
            "in en the study's state history is 413 px wide; " + TABLES,
            "not among the phone's pages: no expectation for a phone", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2", also=(18,)),
    Finding("P-13", 19, "steward", "/site/opt-outs", "table wider than the screen",
            "the opt-out register's list is 467 to 565 px wide; " + TABLES,
            "not among the phone's pages: no expectation for a phone", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2", also=(21,)),
    Finding("P-14", 21, "steward", "/audit", "table wider than the screen",
            "the audit trail's table is 1,304 to 1,332 px wide; the worker's run sits in its first row, its time on "
            "the left and its detail on the right; " + TABLES,
            "not among the phone's pages: no expectation for a phone", SPEC + " §10 (phone's pages)",
            "cosmetic", "C2"),
    Finding("P-15", 21, "steward", "/audit", "target under 44 px",
            "the audit filter's \"Clear\" link (\"清除\", \"クリア\") is 32 to 40 by 24 px",
            "44 px controls on a phone (the card's size; the spec asks 24 px except for the PI's marks)",
            SPEC + " (2.5.8)", "cosmetic", "C2"),
)  # fmt: skip

#: the steps the phone could not complete, and why (read from the logs)
NOT_COMPLETED: tuple[tuple[int, str, str], ...] = ()  # H-25 (D-1124) settled the erase; the phone adds none


def plan_json(lang: str, rs: str, accounts: dict[str, str], log: str = "", shots: str = "") -> dict[str, Any]:
    """H-20's plan for ``lang`` and ``rs`` with the phone's viewport, and the folder the screenshots go to."""
    plan = lp.plan_json(lang, rs, accounts, log)
    plan["viewport"] = dict(VIEWPORT)
    plan["shots"] = shots
    return plan


def finding(fid: str) -> Finding:
    return next(f for f in FINDINGS if f.id == fid)


# ---------------------------------------------------------------------------------------------- the findings page
def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_findings() -> str:
    out = [BEGIN, "", "| Id | Step | Role | Page | Measure | What the phone showed | Expected (from) | Severity | Lane |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted(FINDINGS, key=lambda f: (f.step, f.id)):
        steps = "1 to 22" if len(f.steps()) == 22 else ", ".join(str(n) for n in f.steps())
        out.append(
            f"| {f.id} | {steps} | {f.role} | `{f.path}` | {f.kind} | {_cell(f.showed)} | {_cell(f.expected)} "
            f"({_cell(f.source)}) | {f.severity} | {f.lane} |"
        )
    out += ["", END]
    return "\n".join(out)


def block_of(page: str) -> str:
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), page, re.S)
    return m.group(0) if m else ""


def write_page() -> bool:
    page = FINDINGS_PAGE.read_text(encoding="utf-8")
    old = block_of(page)
    if not old:
        raise SystemExit(f"{FINDINGS_PAGE}: no marker lines")
    new = page.replace(old, render_findings())
    if new != page:
        FINDINGS_PAGE.write_text(new, encoding="utf-8")
    return new != page


# ---------------------------------------------------------------------------------------------- the runs' logs
def measures(logs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per step: each measure (kind, path, what) with the languages it was seen in, and the stops."""
    out: dict[int, dict[str, Any]] = {}
    for lg in logs:
        lang = lg.get("lang", "")
        for st in lg.get("steps", []):
            row = out.setdefault(int(st["n"]), {"role": st["role"], "layout": {}, "stopped": set()})
            for m in st.get("layout", []):
                row["layout"].setdefault((m["kind"], m["path"]), {"what": "", "langs": set(), "shots": []})
                cell = row["layout"][(m["kind"], m["path"])]
                cell["langs"].add(lang)
                if lang == "en" and not cell["what"]:
                    cell["what"] = m["what"]
                cell["shots"].append(m.get("shot", ""))
            if st.get("stopped"):
                row["stopped"].add((st["stopped"].get("finding", ""), st["stopped"].get("page", "")))
    return out


def summary_text(logs: list[dict[str, Any]]) -> str:
    lines = []
    for n, row in sorted(measures(logs).items()):
        for (kind, path), cell in sorted(row["layout"].items()):
            lines.append(f"{n}\t{row['role']}\t{kind}\t{path}\t{','.join(sorted(cell['langs']))}\t{cell['what']}")
        for stop in sorted(row["stopped"]):
            lines.append(f"{n}\t{row['role']}\tSTOP\t{stop[0]}\t\t{stop[1]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", metavar="LANG", help="print the browser's plan for one language (four seeded accounts)")
    ap.add_argument("--write", action="store_true", help="rewrite the findings table of the findings page")
    ap.add_argument("--summary", nargs="+", metavar="LOG", help="the measures of the walk's JSON logs")
    a = ap.parse_args(argv)
    if a.plan:
        print(json.dumps(plan_json(a.plan, RULESETS[a.plan], nw.SEEDED_ACCOUNTS), ensure_ascii=False, indent=1))
    if a.write:
        print("rewritten" if write_page() else "the page is up to date")
    if a.summary:
        print(summary_text([json.loads(Path(p).read_text(encoding="utf-8")) for p in a.summary]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
