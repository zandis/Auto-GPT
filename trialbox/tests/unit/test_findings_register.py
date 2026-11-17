"""tools/findings_register.py (card V-0, D-1180): the one findings register of plan 8 is well formed, its seed holds
every finding of its three sources, and a card's findings.json is appended as rows that read back the same."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools import findings_register as fr

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "handover" / "findings-register.md"
WALK = ROOT / "docs" / "handover" / "life-cycle-walk-findings-2026-11-17.md"
INSTALL_JSON = ROOT / "docs" / "plan" / "measurements" / "runbook-install-2026-11-17" / "findings.json"
P2B = ROOT / "docs" / "plan" / "measurements" / "p2b-review-2026-11-17.md"

pytestmark = pytest.mark.nodb

GOOD_ROW = "| V9-01 | 2026-11-17 | [page](page.md) | High | A claim in one line | B2 | shown | open |"


def make(tmp_path: Path, rows: list[str], heading: str = "## V9: a test card") -> Path:
    folder = tmp_path / "docs" / "handover"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.md").write_text("# A source page\n", encoding="utf-8")
    reg = folder / "findings-register.md"
    reg.write_text("\n".join(["# Register", "", heading, "", fr.HEADER, fr.RULE, *rows, ""]), encoding="utf-8")
    return reg


def errors_of(reg: Path) -> list[str]:
    return fr.check(fr.parse(reg))


def by_card(card: str) -> list[fr.Row]:
    return [r for r in fr.parse(REGISTER).rows if r.card == card]


# --- the committed register ------------------------------------------------------------------------------------------


def test_the_committed_register_passes_check() -> None:
    reg = fr.parse(REGISTER)
    assert fr.check(reg) == []
    assert len(reg.rows) >= 41
    assert fr.main(["--check"]) == 0


def test_the_register_keeps_no_counts_line() -> None:
    """D-1180: the counts are printed by --counts; a counts line in the file would conflict in every pair of PRs."""
    text = REGISTER.read_text(encoding="utf-8")
    assert not re.search(r"open High \d", text)


def test_counts_prints_the_open_findings(capsys: pytest.CaptureFixture[str]) -> None:
    assert fr.main(["--counts"]) == 0
    out = capsys.readouterr().out
    assert re.match(r"open High \d+, open Medium \d+, open Low \d+, total \d+ ", out)


# --- the seed: every finding of the three sources, none dropped, none invented ----------------------------------------


def test_the_walk_seed_holds_the_walks_21_findings_with_their_mapped_severity() -> None:
    """The walk's findings table (between its markers) has 21 rows: 1 blocks the step, 10 slow the tester, 10 are
    cosmetic (its own counts table, checked by hand on 2026-11-17)."""
    text = WALK.read_text(encoding="utf-8")
    table = text.split("### The findings by step", 1)[1].split("<!-- life-cycle-walk: end of findings -->", 1)[0]
    source = {}
    for line in table.splitlines():
        if line.startswith("| F-"):
            cells = [c.strip() for c in line.strip("|").split(" | ")]
            source[cells[0]] = (cells[-2], cells[-1])
    assert len(source) == 21
    scale = {"blocks the step": "High", "slows the tester": "Medium", "cosmetic": "Low"}
    assert sorted(v[0] for v in source.values()).count("slows the tester") == 10
    rows = {r.id.removeprefix("H20-"): r for r in by_card("H20")}
    assert set(rows) == set(source)
    for fid, (sev, lane) in source.items():
        assert rows[fid].cells["Severity"] == f"{scale[sev]} (mapped)", fid
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
        assert rows[fid].cells["Lane"] == "D", fid
    shown = {f["id"] for f in data["findings"] if f["seen_on"]}
    assert {k for k, r in rows.items() if r.cells["Basis"] == "shown"} == shown


def test_the_p2b_seed_holds_one_row_per_proposed_card() -> None:
    """The P2b review gives no ids: its findings are its 8 proposed cards (checked by hand on 2026-11-17)."""
    text = P2B.read_text(encoding="utf-8")
    cards = text.split("## Proposed cards", 1)[1].split("\n## ", 1)[0]
    lanes = re.findall(r"^- \*\*Lane (\w+)", cards, flags=re.M)
    assert len(lanes) == 8
    rows = by_card("H18")
    assert [r.id for r in rows] == [f"H18-{i:02d}" for i in range(1, 9)]
    assert [r.cells["Lane"] for r in rows] == lanes


def test_the_seed_closes_only_what_a_commit_plainly_fixed() -> None:
    closed = {r.id: r.cells["State"] for r in fr.parse(REGISTER).rows if r.card in ("H18", "H20", "H22")}
    assert {k: v for k, v in closed.items() if v != "open"} == {
        "H18-01": "fixed 0ee24331a",
        "H18-02": "fixed f549bfb8b",
    }


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
    assert errors_of(make(tmp_path, rows)) == []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("V9-01", "V9-F01", "lane V id"),
        ("V9-01", "V9-1", "lane V id"),
        ("V9-01", "V2-01", "must start with its heading's card"),
        ("2026-11-17", "17.11.2026", "not an ISO date"),
        ("[page](page.md)", "[page](gone.md)", "does not exist"),
        ("[page](page.md)", "docs/handover/page.md", "not a relative link"),
        ("[page](page.md)", "[page](/etc/hosts)", "not a relative path"),
        ("| High |", "| Critical |", "severity 'Critical'"),
        ("| High |", "| high |", "severity 'high'"),
        ("| High |", "| High (guessed) |", "severity"),
        ("A claim in one line", "", "claim is empty"),
        ("| B2 |", "| G |", "lane 'G'"),
        ("| shown |", "| read |", "basis 'read'"),
        ("| open |", "| closed |", "state 'closed'"),
        ("| open |", "| fixed |", "state 'fixed'"),
        ("| open |", "| fixed xyz1234 |", "state"),
        ("| open |", "| fixed 0ee24 |", "state"),
        ("| open |", "| card issued |", "state"),
        ("| open |", "| card issued 1012 |", "state"),
        ("| open |", "| not a defect |", "state"),
        ("| open |", "| not a defect: |", "state"),
        ("| open |", "| open, card issued #3 |", "state"),
    ],
)
def test_each_kind_of_broken_row_is_named(tmp_path: Path, old: str, new: str, message: str) -> None:
    errors = errors_of(make(tmp_path, [GOOD_ROW.replace(old, new, 1)]))
    assert len(errors) == 1, errors
    assert message in errors[0] and ":7:" in errors[0], errors


def test_a_seeded_id_keeps_its_sources_id(tmp_path: Path) -> None:
    rows = [GOOD_ROW.replace("V9-01", i) for i in ("H20-F-16", "H20-no-host-tree", "H20-01")]
    assert errors_of(make(tmp_path, rows, heading="## H20: a lane H card")) == []
    bad = [GOOD_ROW.replace("V9-01", "H20-F--16")]
    assert "letters, digits and single hyphens" in errors_of(make(tmp_path, bad, heading="## H20: a lane H card"))[0]


def test_an_id_used_twice_is_named(tmp_path: Path) -> None:
    """A row whose state two branches changed shows twice after the union merge: --check names it."""
    errors = errors_of(make(tmp_path, [GOOD_ROW, GOOD_ROW.replace("| open |", "| fixed 0ee24331a |")]))
    assert errors == ["findings-register.md:8: row V9-01: the id is used twice (first at line 7)"]


def test_a_row_with_too_few_cells_is_named(tmp_path: Path) -> None:
    errors = errors_of(make(tmp_path, ["| V9-01 | 2026-11-17 | [page](page.md) | High | claim | B2 | open |"]))
    assert errors and "row V9-01: 7 cells" in errors[0]


def test_an_escaped_pipe_stays_in_its_cell(tmp_path: Path) -> None:
    assert errors_of(make(tmp_path, [GOOD_ROW.replace("A claim", "A \\| claim")])) == []


def test_a_table_outside_a_card_heading_and_a_second_table_are_refused(tmp_path: Path) -> None:
    assert "under a heading '## <card>: <words>'" in errors_of(make(tmp_path, [GOOD_ROW], heading="## Notes"))[0]
    reg = make(tmp_path, [GOOD_ROW])
    with reg.open("a", encoding="utf-8") as fh:
        fh.write("\n## V9: again\n\n" + fr.HEADER + "\n" + fr.RULE + "\n" + GOOD_ROW.replace("V9-01", "V9-02") + "\n")
    assert any("second table" in e for e in errors_of(reg))


def test_check_exits_non_zero_and_names_the_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg = make(tmp_path, [GOOD_ROW.replace("| B2 |", "| Q |")])
    assert fr.main(["--check", "--register", str(reg)]) == 1
    assert "row V9-01: lane 'Q'" in capsys.readouterr().err


# --- --check --release: criterion 11 ------------------------------------------------------------------------------------


def test_release_fails_on_an_open_high_or_an_open_medium(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        GOOD_ROW.replace("| open |", "| card issued #5 |"),  # a High with a card is still open
        GOOD_ROW.replace("V9-01", "V9-02").replace("| High |", "| Medium |"),  # a Medium with nothing
        GOOD_ROW.replace("V9-01", "V9-03").replace("| High |", "| Low |"),  # a Low never stops it
    ]
    reg = make(tmp_path, rows)
    assert fr.main(["--check", "--register", str(reg)]) == 0
    assert fr.main(["--check", "--release", "--register", str(reg)]) == 1
    err = capsys.readouterr().err
    assert "V9-01" in err and "V9-02" in err and "V9-03" not in err and "2 findings stop the release" in err


def test_release_passes_with_highs_closed_and_mediums_carded(tmp_path: Path) -> None:
    rows = [
        GOOD_ROW.replace("| open |", "| fixed 0ee24331a, seen closed by lane R on 2026-11-20 |"),
        GOOD_ROW.replace("V9-01", "V9-02").replace("| High |", "| Medium |").replace("| open |", "| card issued #7 |"),
        GOOD_ROW.replace("V9-01", "V9-03")
        .replace("| High |", "| Medium (mapped) |")
        .replace("| open |", "| not a defect: ruled by D-954 |"),
        GOOD_ROW.replace("V9-01", "V9-04").replace("| High |", "| Low |"),
    ]
    reg = make(tmp_path, rows)
    assert fr.main(["--check", "--release", "--register", str(reg)]) == 0
    assert fr.counts(fr.parse(reg))["open Medium"] == 1  # the carded Medium is open, though it does not stop it


# --- --add-from ----------------------------------------------------------------------------------------------------------


def findings_file(tmp_path: Path, card: str, ids: list[str], name: str = "findings.json") -> Path:
    data = {
        "card": card,
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
                "claim": f"claim of {fid} | with a pipe\nand a second line",
                "lane": "B2",
                "basis": "hypothesis",
            }
            for fid in ids
        ],
    }
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_add_from_round_trips(tmp_path: Path) -> None:
    reg = make(tmp_path, [GOOD_ROW])
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "plan" / "page.md").write_text("# Page\n", encoding="utf-8")
    src = findings_file(tmp_path, "V2", ["V2-01", "V2-02"])
    assert fr.main(["--add-from", str(src), "--register", str(reg), "--root", str(tmp_path)]) == 0
    parsed = fr.parse(reg)
    assert fr.check(parsed) == []
    added = {r.id: r for r in parsed.rows if r.card == "V2"}
    data = json.loads(src.read_text(encoding="utf-8"))
    assert list(added) == ["V2-01", "V2-02"]
    for f in data["findings"]:
        cells = added[f["id"]].cells
        assert cells["Claim"].replace("\\|", "|") == " ".join(f["claim"].split())
        assert (cells["Severity"], cells["Lane"], cells["Basis"], cells["State"]) == (
            "Medium",
            "B2",
            "hypothesis",
            "open",
        )
        assert cells["Date found"] == "2026-11-18" and cells["Source"] == "[page.md](../plan/page.md)"
    # a second file of the same card goes into the card's table, before the next card's heading
    more = findings_file(tmp_path, "V9", ["V9-02"], name="more.json")
    assert fr.add_from(more, reg, tmp_path) == []
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert lines.index(next(x for x in lines if x.startswith("| V9-02 "))) < lines.index("## V2: findings of card V2")
    assert fr.check(fr.parse(reg)) == []


def test_add_from_refuses_a_known_id_or_a_bad_row_and_writes_nothing(tmp_path: Path) -> None:
    reg = make(tmp_path, [GOOD_ROW])
    (tmp_path / "docs" / "plan").mkdir(parents=True)
    (tmp_path / "docs" / "plan" / "page.md").write_text("# Page\n", encoding="utf-8")
    before = reg.read_text(encoding="utf-8")
    assert "already in the register" in fr.add_from(findings_file(tmp_path, "V9", ["V9-01"]), reg, tmp_path)[0]
    bad = findings_file(tmp_path, "V3", ["V3-01"])
    data = json.loads(bad.read_text(encoding="utf-8"))
    data["findings"][0]["lane"] = "lane B"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert "lane 'lane B'" in fr.add_from(bad, reg, tmp_path)[0]
    del data["findings"][0]["claim"]
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert "'claim' is missing" in fr.add_from(bad, reg, tmp_path)[0]
    assert reg.read_text(encoding="utf-8") == before


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
