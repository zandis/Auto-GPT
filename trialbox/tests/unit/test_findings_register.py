"""tools/findings_register.py (card V-0, D-1180): the one findings register of plan 8 is well formed, the check cannot
read fewer rows than the file holds, its seed holds every finding of its three sources, --release is criterion 11,
a union merge's copies of a row are folded by --resolve, and a card's findings.json is appended as rows that read
back the same."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.e2e import life_cycle_walk_plan as lp
from tools import findings_register as fr

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "handover" / "findings-register.md"
WALK = ROOT / "docs" / "handover" / "life-cycle-walk-findings-2026-11-17.md"
INSTALL = ROOT / "docs" / "plan" / "measurements" / "runbook-install-2026-11-17.md"
INSTALL_JSON = ROOT / "docs" / "plan" / "measurements" / "runbook-install-2026-11-17" / "findings.json"
P2B = ROOT / "docs" / "plan" / "measurements" / "p2b-review-2026-11-17.md"
SRC = REGISTER.read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb

GOOD_ROW = "| V9-01 | 2026-11-17 | [page](page.md) | High | A claim in one line | B2 | shown | open |"


def make(tmp_path: Path, rows: list[str], heading: str = "## V9: a test card") -> Path:
    folder = tmp_path / "docs" / "handover"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.md").write_text("# A source page\n", encoding="utf-8")
    reg = folder / "findings-register.md"
    reg.write_text("\n".join(["# Register", "", heading, "", fr.HEADER, fr.RULE, *rows, ""]), encoding="utf-8")
    return reg


def tree(tmp_path: Path, text: str = SRC) -> Path:
    """The committed register and its three sources in a new tree, the register's text replaced by ``text``."""
    (tmp_path / "docs" / "handover").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "plan" / "measurements").mkdir(parents=True, exist_ok=True)
    shutil.copy(WALK, tmp_path / "docs" / "handover")
    shutil.copy(INSTALL, tmp_path / "docs" / "plan" / "measurements")
    shutil.copy(P2B, tmp_path / "docs" / "plan" / "measurements")
    reg = tmp_path / "docs" / "handover" / "findings-register.md"
    reg.write_bytes(text.encode("utf-8"))
    return reg


def errors_of(reg: Path) -> list[str]:
    return fr.check(fr.parse(reg))


def by_card(card: str) -> list[fr.Row]:
    return [r for r in fr.parse(REGISTER).rows if r.card == card]


def row_of(fid: str, text: str = SRC) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"| {fid} |"))


def sub(old: str, new: str, text: str = SRC) -> str:
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1)


# --- the committed register ------------------------------------------------------------------------------------------


def test_the_committed_register_passes_check() -> None:
    reg = fr.parse(REGISTER)
    assert fr.check(reg) == []
    assert len(reg.rows) == len(SEED)
    assert fr.main(["--check"]) == 0


def test_the_register_keeps_no_counts_line() -> None:
    """D-1180: the counts are printed by --counts; a counts line in the file would conflict in every pair of PRs."""
    assert not re.search(r"open High \d", SRC)


def test_counts_prints_the_open_findings(capsys: pytest.CaptureFixture[str]) -> None:
    assert fr.main(["--counts"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("open High 5, open Medium 38, open Low 5, total 51 ")


# --- the seed: every finding of the three sources, none dropped, none invented ----------------------------------------

#: the reviewed seed: id, severity, lane, basis, state, and the first 10 hex of the sha256 of the claim
SEED = [
    ("H20-F-01", "Medium (mapped)", "C2", "shown", "open", "63ea9b66be"),
    ("H20-F-02", "Low (mapped)", "C2", "shown", "open", "6aead54b24"),
    ("H20-F-03", "Medium (mapped)", "C2", "shown", "open", "7c23264ca2"),
    ("H20-F-04", "Medium (mapped)", "C2", "shown", "open", "6a849b2a01"),
    ("H20-F-05", "Medium (mapped)", "C2", "shown", "open", "4b858f3ead"),
    ("H20-F-06", "Medium (mapped)", "C2", "shown", "open", "a8d90d6c41"),
    ("H20-F-07", "Medium (mapped)", "C2", "shown", "open", "5b32142c06"),
    ("H20-F-08", "Medium (mapped)", "C2", "shown", "open", "ac384c834e"),
    ("H20-F-09", "Low (mapped)", "C2", "shown", "open", "3313307581"),
    ("H20-F-10", "Medium (mapped)", "C2", "shown", "open", "5bf053eae6"),
    ("H20-F-11", "Medium (mapped)", "C2", "shown", "open", "31a9a0aaf2"),
    ("H20-F-12", "Low (mapped)", "C2", "shown", "open", "7f3da60dab"),
    ("H20-F-13", "Medium (mapped)", "C2", "shown", "open", "a006619c62"),
    ("H20-F-14", "Medium (mapped)", "C2", "shown", "open", "d845adcdf1"),
    ("H20-F-15", "Medium (mapped)", "C2", "shown", "open", "1d85e8e002"),
    ("H20-F-16", "Medium (mapped)", "C2", "shown", "open", "49875a8e01"),
    ("H20-F-17", "Medium (mapped)", "C2", "shown", "open", "6c28da265b"),
    ("H20-F-18", "Medium (mapped)", "C2", "shown", "open", "c9fb4c82ec"),
    ("H20-F-19", "Low (mapped)", "C2", "shown", "open", "aa3b656705"),
    ("H20-F-20", "High (mapped)", "Int", "shown", "fixed 09b26e8ca", "552e4894f8"),
    ("H20-F-21", "Medium (mapped)", "C2", "shown", "open", "4f9ddbfe55"),
    ("H20-F-22", "Medium (mapped)", "C2", "shown", "open", "0b2c0bcc41"),
    # H-30 (D-1106): what the walk saw on WALK-1's new steps, added to the walk's page and so here
    ("H20-F-23", "Medium (mapped)", "C2", "shown", "open", "b1b89f94d9"),
    ("H20-F-24", "Medium (mapped)", "C2", "shown", "open", "5652664ce2"),
    ("H20-F-25", "Low (mapped)", "C2", "shown", "open", "ea3fd042b5"),
    ("H22-no-host-tree", "High (mapped)", "D", "shown", "open", "7446e30613"),
    ("H22-vendor-key-after-start", "High (mapped)", "D", "shown", "open", "96dce1b88a"),
    ("H22-stub-fragment-vs-tier", "Medium (mapped)", "D", "shown", "open", "dea98c5bdf"),
    ("H22-bundle-sidecar-path", "High (mapped)", "D", "shown", "open", "6dc3f7672a"),
    ("H22-stub-production-embedder", "High (mapped)", "D", "shown", "open", "96f2a215e9"),
    ("H22-unmentioned-questions", "Medium (mapped)", "D", "hypothesis", "open", "9759688dbe"),
    ("H22-host-packages-unnamed", "Medium (mapped)", "D", "hypothesis", "open", "591e217472"),
    ("H22-site-folder-place-unstated", "Medium (mapped)", "D", "hypothesis", "open", "e73aa12ad4"),
    ("H22-feed-folder-content-unstated", "Medium (mapped)", "D", "hypothesis", "open", "3d22903a52"),
    ("H22-python-not-python3", "Medium (mapped)", "D", "hypothesis", "open", "d28d595b78"),
    ("H22-compose-cwd-unstated", "Medium (mapped)", "D", "hypothesis", "open", "5ff30c1570"),
    ("H22-ingest-report-in-volume", "Medium (mapped)", "D", "hypothesis", "open", "c723e8b48e"),
    ("H18-01", "High (mapped)", "A2", "shown", "fixed 0ee24331a", "2a547249fb"),
    ("H18-02", "Medium (mapped)", "A2", "shown", "fixed f549bfb8b", "32e0c65475"),
    ("H18-03", "High (mapped)", "A2", "hypothesis", "open", "06fc8c3cac"),
    ("H18-04", "Medium (mapped)", "A2", "not stated", "open", "14893d87e2"),
    ("H18-05", "Medium (mapped)", "H", "not stated", "open", "96ef23df68"),
    ("H18-06", "Medium (mapped)", "H", "shown", "open", "87d104b4ea"),
    ("H18-07", "Medium (mapped)", "H", "shown", "open", "c1320b7147"),
    ("H18-08", "Medium (mapped)", "H", "shown", "open", "8c59f0ceaa"),
    ("H18-09", "Medium (mapped)", "H", "hypothesis", "open", "8ce0047c19"),
    ("H18-10", "Medium (mapped)", "A2", "shown", "open", "91582dad0a"),
    ("H18-11", "Medium (mapped)", "H", "shown", "open", "9314858e92"),
    ("H18-12", "Medium (mapped)", "H", "not_run", "open", "377771a1ec"),
    ("H18-13", "Medium (mapped)", "H", "not_run", "open", "583b8a7352"),
    ("H18-14", "Medium (mapped)", "H", "not_run", "open", "cf2fab1169"),
]


def test_the_seed_is_the_reviewed_seed() -> None:
    """Each seeded row's severity, lane, basis, state and claim are pinned: a claim turned into its opposite fails."""
    got = {
        r.id: (
            r.cells["Severity"],
            r.cells["Lane"],
            r.cells["Basis"],
            r.cells["State"],
            hashlib.sha256(r.cells["Claim"].encode()).hexdigest()[:10],
        )
        for r in fr.parse(REGISTER).rows
        if r.card in ("H18", "H20", "H22")
    }
    assert got == {s[0]: s[1:] for s in SEED}


def test_the_walk_seed_holds_every_finding_of_the_walks_page() -> None:
    """Every finding in the walk's table (between its markers) has its row here; the one that blocks a step is High.
    The page is lane H's and moves (H-25 settled F-20 and took its row out, and added F-22), so no count is pinned:
    a row is never deleted here, and a finding new on the page fails this test until it has its row."""
    text = WALK.read_text(encoding="utf-8")
    table = text.split("### The findings by step", 1)[1].split("<!-- life-cycle-walk: end of findings -->", 1)[0]
    source = {}
    for line in table.splitlines():
        if line.startswith("| F-"):
            cells = [c.strip() for c in line.strip("|").split(" | ")]
            source[cells[0]] = (cells[-2], cells[-1])
    # H-30 (D-1106): the page's open findings are exactly the plan's (a finding the walk no longer sees stands after
    # the table), so a short read fails here rather than by a floor that the page's own changes move
    assert set(source) == {f.id for f in lp.FINDINGS} and len(source) == len(lp.FINDINGS)
    rows = {r.id.removeprefix("H20-"): r for r in by_card("H20")}
    assert set(source) <= set(rows), sorted(set(source) - set(rows))
    for fid, (sev, lane) in source.items():
        assert (rows[fid].level == "High") == (sev == "blocks the step"), fid
        assert rows[fid].cells["Lane"] == ("Int" if lane == "integrator" else lane), fid


def test_the_install_seed_holds_the_install_runs_12_findings() -> None:
    data = json.loads(INSTALL_JSON.read_text(encoding="utf-8"))
    source = {f["id"]: f["severity"] for f in data["findings"]}
    assert len(source) == 12
    scale = {"stops the install": "High", "slows the reader": "Medium"}
    rows = {r.id.removeprefix("H22-"): r for r in by_card("H22")}
    assert set(rows) == set(source)
    for fid, sev in source.items():
        assert rows[fid].cells["Severity"] == f"{scale[sev]} (mapped)", fid
    shown = {f["id"] for f in data["findings"] if f["seen_on"]}
    assert {k for k, r in rows.items() if r.cells["Basis"] == "shown"} == shown


def test_the_p2b_seed_holds_its_8_proposed_cards_then_6_more_findings() -> None:
    """The P2b review gives no ids: its 8 proposed cards are H18-01 to 08 (checked by hand on 2026-11-17), and six
    more statements of something wrong or unproven in sections 1 and 2 and "Not shown" are H18-09 to 14."""
    text = P2B.read_text(encoding="utf-8")
    cards = text.split("## Proposed cards", 1)[1].split("\n## ", 1)[0]
    lanes = re.findall(r"^- \*\*Lane (\w+)", cards, flags=re.M)
    assert len(lanes) == 8
    rows = by_card("H18")
    assert [r.id for r in rows] == [f"H18-{i:02d}" for i in range(1, 15)]
    assert [r.cells["Lane"] for r in rows[:8]] == lanes
    not_shown = text.split("## Not shown", 1)[1]
    assert len(re.findall(r"^- \*\*", not_shown, flags=re.M)) == 6  # 3 are H18-03/09, H18-04; 3 are H18-12 to 14
    for words in ("TCGA-AZ-5403", "NCT01701453", "counts only"):
        assert words in text


def test_the_seed_closes_only_what_a_commit_plainly_fixed() -> None:
    closed = {r.id: r.cells["State"] for r in fr.parse(REGISTER).rows if r.cells["State"] != "open"}
    assert closed == {"H18-01": "fixed 0ee24331a", "H18-02": "fixed f549bfb8b", "H20-F-20": "fixed 09b26e8ca"}


# --- the parser cannot read fewer rows than the file holds -------------------------------------------------------------

LAST_H22 = row_of("H22-ingest-report-in-volume")
FIRST_H22 = row_of("H22-no-host-tree")
R21 = row_of("H20-F-21")
H22_HEAD = "## H22: the install runbook followed alone (lane H, 2026-11-17)"
TABLE = f"{fr.HEADER}\n{fr.RULE}\n"

STRICT_CASES = {
    "header Id -> ID": sub(f"{H22_HEAD}\n\n| Id |", f"{H22_HEAD}\n\n| ID |"),
    "blank line between the rule and the first row": sub(f"{fr.RULE}\n{FIRST_H22}", f"{fr.RULE}\n\n{FIRST_H22}"),
    "a card heading mistyped": sub("## H22: the install", "## H22 - the install"),
    "a level-3 heading inside a table": sub(R21, "### note\n" + R21),
    "a pipe row after a blank line": sub(LAST_H22, LAST_H22 + "\n\n" + LAST_H22.replace("ingest-report", "x")),
    "a row with no leading pipe": sub(R21, R21 + "\n" + R21[2:].replace("H20-F-21", "H20-F-23")),
    "a row with no closing pipe": sub(R21, R21 + "\n" + R21[:-2].replace("H20-F-21", "H20-F-23")),
    "a junk row outside any table, at the end": SRC.rstrip("\n")
    + "\n\n| H99-01 | bad | nope | Huge | x | Q | y | z |\n",
    "a junk row in the head": sub(
        "## H20: the life-cycle", "| X-01 | junk | no | no | no | no | no | no |\n\n## H20: the life-cycle"
    ),
    "prose between two tables": sub(LAST_H22, LAST_H22 + "\n\nA note.\n"),
    "prose inside a table": sub(R21, "A note.\n" + R21),
    "a newline in a claim": sub(R21, R21.replace("on the metrics page", "on the\nmetrics page")),
    "an empty table": SRC.rstrip("\n") + "\n\n## V5: nothing found\n\n" + TABLE,
    "a card heading with no table": SRC.rstrip("\n") + "\n\n## V6: nothing\n",
    "a card heading with prose and no table": SRC.rstrip("\n") + "\n\n## V6: nothing\n\nprose\n",
    "a second section of one card": SRC.rstrip("\n")
    + "\n\n## H20: again\n\n"
    + TABLE
    + R21.replace("F-21", "F-30")
    + "\n",
    "a header without its rule": sub(f"{fr.HEADER}\n{fr.RULE}\n{FIRST_H22}", f"{fr.HEADER}\n{FIRST_H22}"),
    "a fenced block at the end": SRC.rstrip("\n")
    + "\n\n```\n## V7: x\n\n"
    + TABLE
    + R21.replace("H20-F-21", "V7-01")
    + "\n```\n",
    "a table in a fenced block in the head": sub(
        "## H20: the life-cycle", "```\n" + TABLE + R21 + "\n```\n\n## H20: the life-cycle"
    ),
    "no card heading at all": "# Register\n",
    "a card name with a hyphen": SRC.rstrip("\n")
    + "\n\n## V-8: x\n\n"
    + TABLE
    + R21.replace("H20-F-21", "V-8-01")
    + "\n",
}


@pytest.mark.parametrize("name", sorted(STRICT_CASES))
def test_a_line_the_parser_would_skip_is_an_error(tmp_path: Path, name: str) -> None:
    errors = errors_of(tree(tmp_path, STRICT_CASES[name]))
    assert errors, name
    assert all(re.match(r"findings-register\.md(:\d+)?: ", e) for e in errors), errors


def test_a_hidden_high_cannot_pass_release(tmp_path: Path) -> None:
    """The reviewer's case: every Medium closed, the H22 table's header misspelt. Before, --check passed and
    --release saw 2 Highs of 6; now --check fails."""
    closed = "\n".join(
        ln.replace("| open |", "| not a defect: test |") if ln.startswith("| ") and "| High" not in ln else ln
        for ln in SRC.splitlines()
    )
    hidden = sub(f"{H22_HEAD}\n\n| Id |", f"{H22_HEAD}\n\n| ID |", closed + "\n")
    reg = tree(tmp_path, hidden)
    assert fr.main(["--check", "--release", "--register", str(reg)]) == 1
    assert errors_of(reg)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("trailing spaces", SRC.replace(" |\n", " |   \n")),
        ("CRLF", SRC.replace("\n", "\r\n")),
        ("a UTF-8 byte-order mark", "﻿" + SRC),
    ],
)
def test_harmless_forms_read_every_row(tmp_path: Path, name: str, text: str) -> None:
    reg = fr.parse(tree(tmp_path, text))
    assert fr.check(reg) == [] and len(reg.rows) == len(SEED), name


def test_a_parse_error_names_its_line(tmp_path: Path) -> None:
    errors = errors_of(tree(tmp_path, sub(R21, "### note\n" + R21)))
    n = sub(R21, "### note\n" + R21).splitlines().index("### note") + 1
    assert errors[0].startswith(f"findings-register.md:{n}: inside card H20's table, a line that is not a row")


# --- each kind of broken row is caught ---------------------------------------------------------------------------------


def test_a_good_row_passes(tmp_path: Path) -> None:
    states = [
        "open",
        "card issued #1012",
        "fixed 0ee24331a",
        "fixed " + "a" * 40,
        "fixed 0ee24331a, seen closed by lane R on 2026-11-20",
        "not a defect: a recorded ruling (D-954)",
    ]
    rows = [GOOD_ROW.replace("V9-01", f"V9-{i:02d}").replace("| open |", f"| {s} |") for i, s in enumerate(states, 1)]
    rows.append(GOOD_ROW.replace("V9-01", "V9-100").replace("| High |", "| Low (mapped) |"))
    rows.append(GOOD_ROW.replace("V9-01", "V9-101").replace("| B2 |", "| G |"))
    rows.append(GOOD_ROW.replace("V9-01", "V9-102").replace("A claim", "A \\| claim"))
    assert errors_of(make(tmp_path, rows)) == []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("V9-01", "V9-F01", "lane V id"),
        ("V9-01", "V9-1", "lane V id"),
        ("V9-01", "V2-01", "must start with its heading's card"),
        ("V9-01", "v9-01", "must start with its heading's card"),
        ("2026-11-17", "17.11.2026", "not a real date"),
        ("2026-11-17", "2026-02-30", "not a real date"),
        ("2026-11-17", "2026-13-45", "not a real date"),
        ("[page](page.md)", "[page](gone.md)", "not an existing file"),
        ("[page](page.md)", "[page](.)", "not an existing file"),
        ("[page](page.md)", "[page](../../../../../../etc/hosts)", "leaves the trialbox/ tree"),
        ("[page](page.md)", "docs/handover/page.md", "not a relative link"),
        ("[page](page.md)", "[page](/etc/hosts)", "not a relative path"),
        ("[page](page.md)", "[page](https://example.org/page.md)", "not a relative path"),
        ("| High |", "| Critical |", "severity 'Critical'"),
        ("| High |", "| high |", "severity 'high'"),
        ("| High |", "| High (guessed) |", "severity"),
        ("| High |", "| Medium(mapped) |", "severity"),
        ("A claim in one line", "", "claim is empty"),
        ("| B2 |", "| Q |", "lane 'Q'"),
        ("| shown |", "| read |", "basis 'read'"),
        ("| shown |", "| maybe |", "basis 'maybe'"),
        ("| shown |", "| Shown |", "basis 'Shown'"),
        ("| open |", "| closed |", "state 'closed'"),
        ("| open |", "| fixed |", "state 'fixed'"),
        ("| open |", "| fixed xyz1234 |", "state"),
        ("| open |", "| fixed abcdefg |", "state"),
        ("| open |", "| fixed ABCDEF1 |", "state"),
        ("| open |", "| fixed 0ee24 |", "state"),
        ("| open |", "| fixed 0ee24331a, seen closed by lane R on yesterday |", "state"),
        ("| open |", "| fixed 0ee24331a, seen closed by lane R on 2026-02-30 |", "not a real date"),
        ("| open |", "| card issued |", "state"),
        ("| open |", "| card issued 1012 |", "state"),
        ("| open |", "| card issued #0 |", "state"),
        ("| open |", "| not a defect |", "state"),
        ("| open |", "| not a defect: |", "state"),
        ("| open |", "| open, card issued #3 |", "state"),
        ("| open |", "| open (see #12) |", "state"),
    ],
)
def test_each_kind_of_broken_row_is_named(tmp_path: Path, old: str, new: str, message: str) -> None:
    errors = errors_of(make(tmp_path, [GOOD_ROW.replace(old, new, 1)]))
    assert len(errors) == 1, errors
    assert message in errors[0] and ":7: row " in errors[0], errors


def test_a_seeded_id_keeps_its_sources_id(tmp_path: Path) -> None:
    rows = [GOOD_ROW.replace("V9-01", i) for i in ("H20-F-16", "H20-no-host-tree", "H20-01")]
    assert errors_of(make(tmp_path, rows, heading="## H20: a lane H card")) == []
    bad = [GOOD_ROW.replace("V9-01", "H20-F--16")]
    assert "letters, digits and single hyphens" in errors_of(make(tmp_path, bad, heading="## H20: a lane H card"))[0]


def test_an_id_used_twice_is_named_and_points_to_resolve(tmp_path: Path) -> None:
    errors = errors_of(make(tmp_path, [GOOD_ROW, GOOD_ROW.replace("| open |", "| fixed 0ee24331a |")]))
    assert errors == [
        "findings-register.md:8: row V9-01: the id is used twice (first at line 7); run --resolve after a merge"
    ]


def test_a_row_with_too_few_cells_is_named(tmp_path: Path) -> None:
    errors = errors_of(make(tmp_path, ["| V9-01 | 2026-11-17 | [page](page.md) | High | claim | B2 | open |"]))
    assert errors and "row V9-01: 7 cells" in errors[0]


def test_check_exits_non_zero_and_names_the_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg = make(tmp_path, [GOOD_ROW.replace("| B2 |", "| Q |")])
    assert fr.main(["--check", "--register", str(reg)]) == 1
    assert "row V9-01: lane 'Q'" in capsys.readouterr().err


# --- --check --release: criterion 11 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "state", "passes"),
    [
        ("High", "open", False),
        ("High", "card issued #5", False),
        ("High", "fixed 0ee24331a", False),  # a High closes when it is seen closed
        ("High", "fixed 0ee24331a, seen closed by lane R on 2026-11-20", True),
        ("High (mapped)", "not a defect: ruled by D-954", True),
        ("Medium", "open", False),
        ("Medium", "card issued #7", False),  # a card issued is not a card done
        ("Medium (mapped)", "fixed 0ee24331a", True),
        ("Medium", "not a defect: ruled by D-954", True),
        ("Low", "open", True),
        ("Low", "card issued #7", True),
    ],
)
def test_release_is_criterion_11(tmp_path: Path, severity: str, state: str, passes: bool) -> None:
    reg = make(tmp_path, [GOOD_ROW.replace("| High |", f"| {severity} |").replace("| open |", f"| {state} |")])
    assert fr.main(["--check", "--register", str(reg)]) == 0
    assert fr.main(["--check", "--release", "--register", str(reg)]) == (0 if passes else 1)


def test_release_names_what_stops_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [GOOD_ROW, GOOD_ROW.replace("V9-01", "V9-02").replace("| High |", "| Low |")]
    assert fr.main(["--check", "--release", "--register", str(make(tmp_path, rows))]) == 1
    err = capsys.readouterr().err
    assert "release: V9-01 (High, open)" in err and "V9-02" not in err and "1 findings stop the release" in err


def test_the_committed_register_does_not_pass_release() -> None:
    blockers = {r.id for r in fr.release_blockers(fr.parse(REGISTER))}
    assert "H18-01" in blockers  # fixed, not yet seen closed
    assert "H18-02" not in blockers  # a Medium with its fix


@pytest.mark.parametrize("argv", [["--release"], ["--release", "--counts"]])
def test_release_goes_with_check_only(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        fr.main(argv)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


# --- --resolve ---------------------------------------------------------------------------------------------------------


def test_resolve_folds_a_state_change_and_leaves_a_conflict(tmp_path: Path) -> None:
    rows = [
        GOOD_ROW,
        GOOD_ROW.replace("V9-01", "V9-02"),
        GOOD_ROW.replace("| open |", "| card issued #12 |"),
        GOOD_ROW.replace("V9-01", "V9-03"),
        GOOD_ROW.replace("V9-01", "V9-03").replace("| open |", "| fixed 0ee24331a |"),
        GOOD_ROW.replace("V9-01", "V9-03").replace("| open |", "| not a defect: no |"),
        GOOD_ROW.replace("V9-01", "V9-04"),
        GOOD_ROW.replace("V9-01", "V9-04").replace("A claim", "Another claim"),
        GOOD_ROW.replace("V9-01", "V9-05"),
        GOOD_ROW.replace("V9-01", "V9-05"),
    ]
    reg = make(tmp_path, rows)
    folded, left = fr.resolve(reg)
    assert folded == ["V9-01", "V9-05"]
    assert [p.split(":")[0] for p in left] == ["V9-03", "V9-04"]
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert lines[6] == GOOD_ROW.replace("| open |", "| card issued #12 |")  # in the place of the first copy
    assert sum(ln.startswith("| V9-05 ") for ln in lines) == 1
    assert sum(ln.startswith("| V9-03 ") for ln in lines) == 3  # left for a person


# The reviewer's merges (merge_sim.sh): real `git merge --no-ff` with the union attribute, in a temporary repository.

ROW_NEW = "| {id} | 2026-11-18 | [life-cycle-walk-findings-2026-11-17.md](life-cycle-walk-findings-2026-11-17.md) | Medium | claim of {id} | C2 | shown | open |"
SECTION = (
    "\n## {card}: a new card\n\n"
    + TABLE
    + "| {card}-01 | 2026-11-18 | [p2b-review-2026-11-17.md](../plan/measurements/p2b-review-2026-11-17.md) | Low | claim | B2 | shown | open |\n"
)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip


def append_after(fid: str, new: str) -> Callable[[str], str]:
    return lambda t: t.replace(row_of(fid, t), row_of(fid, t) + "\n" + new, 1)


def set_state(fid: str, state: str) -> Callable[[str], str]:
    return lambda t: t.replace(row_of(fid, t), row_of(fid, t).replace("| open |", f"| {state} |"), 1)


def new_section(card: str) -> Callable[[str], str]:
    return lambda t: t.rstrip("\n") + "\n" + SECTION.format(card=card)


MERGES: dict[str, tuple[Callable[[str], str], Callable[[str], str], str]] = {
    "same table, both append after its last row": (
        append_after("H20-F-21", ROW_NEW.format(id="H20-F-32")),
        append_after("H20-F-21", ROW_NEW.format(id="H20-F-33")),
        "clean",
    ),
    "two tables, one row each": (
        append_after("H20-F-21", ROW_NEW.format(id="H20-F-32")),
        append_after("H22-ingest-report-in-volume", ROW_NEW.format(id="H22-extra")),
        "clean",
    ),
    "two new cards at the end of the file": (new_section("V2"), new_section("V3"), "clean"),
    "one row, two different state changes": (
        set_state("H20-F-01", "card issued #1200"),
        set_state("H20-F-01", "not a defect: ruled"),
        "person",
    ),
    "neighbouring rows, each changed on one side": (
        set_state("H20-F-01", "card issued #1200"),
        set_state("H20-F-02", "card issued #1201"),
        "resolve",
    ),
    "one side changes the last row's state, the other appends after it": (
        set_state("H20-F-21", "card issued #1200"),
        append_after("H20-F-21", ROW_NEW.format(id="H20-F-32")),
        "resolve",
    ),
    "one side changes the file's last row, the other adds a card at the end": (
        set_state("H18-14", "card issued #1200"),
        new_section("V3"),
        "resolve",
    ),
}


@pytest.mark.parametrize("name", list(MERGES))
def test_a_real_union_merge(tmp_path: Path, name: str) -> None:
    edit_a, edit_b, outcome = MERGES[name]
    reg = tree(tmp_path)
    rel = reg.relative_to(tmp_path).as_posix()
    (tmp_path / ".gitattributes").write_text(f"{rel} merge=union\n", encoding="utf-8")
    assert git(tmp_path, "init", "-q", "-b", "base").returncode == 0
    git(tmp_path, "add", "-A")
    assert git(tmp_path, "commit", "-qm", "base").returncode == 0
    for branch, edit in (("a", edit_a), ("b", edit_b)):
        git(tmp_path, "checkout", "-q", "-B", branch, "base")
        reg.write_text(edit(SRC), encoding="utf-8")
        assert errors_of(reg) == [], branch  # each side alone is well formed
        assert git(tmp_path, "commit", "-qam", branch).returncode == 0
    git(tmp_path, "checkout", "-q", "a")
    merged = git(tmp_path, "merge", "--no-ff", "--no-edit", "b")
    assert merged.returncode == 0, merged.stdout + merged.stderr  # the union never conflicts
    errors = errors_of(reg)
    if outcome == "clean":
        assert errors == []
        return
    assert errors and all("run --resolve after a merge" in e for e in errors), errors
    folded, left = fr.resolve(reg)
    if outcome == "person":
        assert folded == [] and left and "two states other than open" in left[0]
        assert errors_of(reg)
    else:
        assert left == [] and folded
        assert errors_of(reg) == []
        rows = {r.id: r.cells["State"] for r in fr.parse(reg).rows}
        assert [s for s in rows.values() if s.startswith("card issued")]


# --- --add-from ----------------------------------------------------------------------------------------------------------


def findings_file(
    tmp_path: Path,
    card_name: str,
    ids: list[str],
    *,
    name: str = "findings.json",
    over: dict[str, object] | None = None,
) -> Path:
    data: dict[str, object] = {
        "card": card_name,
        "decision": "D-1180",
        "date": "2026-11-18",
        "source": "docs/plan/page.md",
        "findings": [
            {
                "id": fid,
                "place": "libs/x.py:1",
                "expected": "what the plan says",
                "happened": "what ran",
                "severity": "Medium",
                "claim": f"claim of {fid} | with a pipe and \\| one escaped",
                "lane": "B2",
                "basis": "hypothesis",
            }
            for fid in ids
        ],
    }
    for key, value in (over or {}).items():
        if key.startswith("f_"):
            for f in data["findings"]:  # type: ignore[attr-defined]
                f[key[2:]] = value
        else:
            data[key] = value
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def area(tmp_path: Path) -> Path:
    make(tmp_path, [GOOD_ROW])
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "plan" / "page.md").write_text("# Page\n", encoding="utf-8")
    return tmp_path


def reg_of(area: Path) -> Path:
    return area / "docs" / "handover" / "findings-register.md"


def test_add_from_round_trips(area: Path) -> None:
    reg = reg_of(area)
    src = findings_file(area, "V2", ["V2-01", "V2-02"])
    assert fr.main(["--add-from", str(src), "--register", str(reg), "--root", str(area)]) == 0
    parsed = fr.parse(reg)
    assert fr.check(parsed) == []
    added = {r.id: r for r in parsed.rows if r.card == "V2"}
    data = json.loads(src.read_text(encoding="utf-8"))
    assert list(added) == ["V2-01", "V2-02"]
    for f in data["findings"]:
        cells = added[f["id"]].cells
        assert cells["Claim"] == f"claim of {f['id']} \\| with a pipe and \\| one escaped"  # never \\\\|
        assert (cells["Severity"], cells["Lane"], cells["Basis"], cells["State"]) == (
            "Medium",
            "B2",
            "hypothesis",
            "open",
        )
        assert cells["Date found"] == "2026-11-18" and cells["Source"] == "[page.md](../plan/page.md)"
    # a second file of the same card goes into the card's table, before the next card's heading
    more = findings_file(area, "V9", ["V9-02"], name="more.json")
    assert fr.add_from(more, reg, area) == []
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert lines.index(next(x for x in lines if x.startswith("| V9-02 "))) < lines.index("## V2: findings of card V2")
    assert fr.check(fr.parse(reg)) == []


def test_add_from_twice_writes_nothing_the_second_time(area: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg = reg_of(area)
    src = findings_file(area, "V2", ["V2-01"])
    assert fr.main(["--add-from", str(src), "--register", str(reg), "--root", str(area)]) == 0
    before = reg.read_text(encoding="utf-8")
    assert fr.main(["--add-from", str(src), "--register", str(reg), "--root", str(area)]) == 1
    assert "V2-01: already in the register: nothing written" in capsys.readouterr().err
    assert reg.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"title": "line1\n## V9: injected"}, "'title' holds a line break"),
        ({"title": ["x"]}, "'title' is missing or not text"),
        ({"f_claim": "a\tb"}, "'claim' holds a line break or a control character"),
        ({"f_claim": "a\nb"}, "'claim' holds a line break"),
        ({"f_severity": 3}, "'severity' is missing or not text"),
        ({"f_lane": "lane B"}, "lane 'lane B'"),
        ({"f_basis": "maybe"}, "basis 'maybe'"),
        ({"f_date": "2026-13-45"}, "not a real date"),
        ({"f_source": "/etc/hosts"}, "not a path relative to trialbox/"),
        ({"f_source": "../../etc/hosts"}, "leaves the trialbox/ tree"),
        ({"f_source": "docs/plan"}, "not an existing file"),
        ({"f_source": "docs/plan/gone.md"}, "not an existing file"),
        ({"f_state": "fixed abcdefg"}, "state"),
        ({"card": "V-2"}, "not a card name"),
    ],
)
def test_add_from_refuses_and_writes_nothing(area: Path, over: dict[str, object], message: str) -> None:
    reg = reg_of(area)
    before = reg.read_text(encoding="utf-8")
    problems = fr.add_from(findings_file(area, "V2", ["V2-01"], over=over), reg, area)
    assert problems and any(message in p for p in problems), problems
    assert reg.read_text(encoding="utf-8") == before


def test_add_from_refuses_an_id_twice_in_its_file(area: Path) -> None:
    problems = fr.add_from(findings_file(area, "V2", ["V2-01", "V2-01"]), reg_of(area), area)
    assert problems == ["findings.json: V2-01: twice in the file: nothing written"]


def test_add_from_refuses_a_register_that_does_not_pass_check(area: Path) -> None:
    reg = reg_of(area)
    reg.write_text(reg.read_text(encoding="utf-8").replace("| B2 |", "| Q |"), encoding="utf-8")
    before = reg.read_text(encoding="utf-8")
    problems = fr.add_from(findings_file(area, "V2", ["V2-01"]), reg, area)
    assert problems[0] == "the register does not pass --check before the addition: nothing written"
    assert reg.read_text(encoding="utf-8") == before


def test_add_from_puts_the_old_file_back_when_the_result_fails(area: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = reg_of(area)
    before = reg.read_text(encoding="utf-8")
    monkeypatch.setattr(fr, "render", lambda cells: "| broken |")
    problems = fr.add_from(findings_file(area, "V2", ["V2-01"]), reg, area)
    assert problems[0].startswith("the register after the addition fails --check; the old file is put back")
    assert reg.read_text(encoding="utf-8") == before


def test_a_failed_add_from_exits_1(area: Path) -> None:
    src = findings_file(area, "V2", ["V2-01"], over={"f_lane": "nope"})
    assert fr.main(["--add-from", str(src), "--register", str(reg_of(area)), "--root", str(area)]) == 1


# --- the wiring ------------------------------------------------------------------------------------------------------------


def test_the_check_runs_in_make_lint_and_in_ci() -> None:
    make_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    lint = make_text.split("\nlint:", 1)[1].split("\n\n", 1)[0]
    assert "-m tools.findings_register --check" in lint
    ci = (ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml").read_text(encoding="utf-8")
    checks = ci.split("\n  checks:", 1)[1].split("\n  standards:", 1)[0]
    assert ".venv/bin/python -m tools.findings_register --check\n" in checks
    assert "--release" not in checks  # criterion 11's mode is not wired into CI now
    assert "docs/handover/findings-register.md merge=union" in (ROOT / ".gitattributes").read_text(encoding="utf-8")
