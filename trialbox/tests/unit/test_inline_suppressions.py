"""10G-39, D-1338: every inline security suppression has a reviewed ledger line (tools/inline_suppressions.py).

The card's acceptance: a planted ``# nosec`` without a ledger line fails; so does a ledger line that matches no code
line. The real tree passes against tools/inline_suppressions.yaml."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from tools import inline_suppressions as IS

TODAY = dt.date(2026, 11, 19)


def _entry(path: str, rule: str, code: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "path": path,
        "rule": rule,
        "code": code,
        "verdict": "safe",
        "reason": "a planted line for the test, reviewed as safe",
        "reviewer": "lane H",
        "reviewed": "2026-11-19",
        "review_by": "2027-05-18",
    }
    row.update(over)
    return row


def _tree(tmp_path: Path, files: dict[str, str], entries: list[dict[str, object]]) -> tuple[Path, Path]:
    root = tmp_path / "tree"
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    ledger = tmp_path / "ledger.yaml"
    ledger.write_text(yaml.safe_dump({"suppressions": entries}, sort_keys=False), encoding="utf-8")
    return root, ledger


def _check(root: Path, ledger: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = IS.main(["--check", "--root", str(root), "--ledger", str(ledger), "--today", TODAY.isoformat()])
    return rc, capsys.readouterr().out


GOOD = 'import subprocess\nsubprocess.run(["ls"], check=True)  # nosec B603: fixed argv\n'


def test_the_tree_holds_every_suppression_in_the_ledger(capsys: pytest.CaptureFixture[str]) -> None:
    rc = IS.main(["--check", "--today", TODAY.isoformat()])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS" in out


def test_a_ledgered_line_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, ledger = _tree(tmp_path, {"a.py": GOOD}, [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)')])
    rc, out = _check(root, ledger, capsys)
    assert rc == 0, out


def test_a_planted_nosec_without_a_ledger_line_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The card's acceptance."""
    planted = GOOD + 'subprocess.run("ls", shell=True)  # nosec\n'
    root, ledger = _tree(tmp_path, {"a.py": planted}, [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)')])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1
    assert "FAIL a.py:3: all: an inline suppression with no ledger line" in out


def test_a_planted_nosec_with_a_code_in_a_ledgered_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planted = GOOD + 'x = f"SELECT * FROM {t}"  # nosec B608\n'
    root, ledger = _tree(tmp_path, {"a.py": planted}, [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)')])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and "a.py:3: B608" in out


def test_a_second_identical_line_needs_its_own_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, ledger = _tree(
        tmp_path,
        {"a.py": GOOD + GOOD.splitlines()[1] + "\n"},
        [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)')],
    )
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and "a.py:3: B603" in out


def test_a_planted_noqa_s_without_a_ledger_line_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, ledger = _tree(tmp_path, {"b.py": "import yaml\nd = yaml.load(t)  # noqa: E501, S506\n"}, [])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and "b.py:2: S506" in out


def test_a_file_level_ruff_noqa_s_is_counted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, ledger = _tree(tmp_path, {"c.py": "# ruff: noqa: S608\nx = 1\n"}, [])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and "c.py:1: S608" in out


def test_a_ledger_line_that_matches_no_code_line_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    entries = [
        _entry("a.py", "B603", 'subprocess.run(["ls"], check=True)'),
        _entry("a.py", "B608", "gone = 1"),
    ]
    root, ledger = _tree(tmp_path, {"a.py": GOOD}, entries)
    rc, out = _check(root, ledger, capsys)
    assert rc == 1
    assert "a.py: B608: a ledger line that matches no code line ('gone = 1'): remove it" in out


def test_a_changed_line_no_longer_matches_its_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changed = GOOD.replace('["ls"]', '["ls", "-l"]')
    root, ledger = _tree(tmp_path, {"a.py": changed}, [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)')])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and "no ledger line" in out and "matches no code line" in out


def test_text_that_is_not_a_suppression_comment_is_not_counted() -> None:
    text = (
        's = "x  # nosec B608"  # the string holds the words, the comment does not\n'
        "t = 1  # Trivy writes nanoseconds\n"
        "u = 2  # noqa: E501 - not a security rule\n"
        'v = """\n# nosec\n"""\n'
    )
    assert IS.suppressions_in(text, "d.py") == []


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"verdict": "fine"}, "verdict must be one of"),
        ({"verdict": "finding"}, "names its finding id"),
        ({"finding": "H10G39-01"}, "a `safe` entry names no finding"),
        ({"reason": "ok"}, "at least 20 characters"),
        ({"reviewer": ""}, "needs reviewer"),
        ({"review_by": "soon"}, "review_by must be a date"),
        ({"extra": 1}, "unknown field"),
    ],
)
def test_a_malformed_entry_stops_the_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, object], message: str
) -> None:
    root, ledger = _tree(
        tmp_path, {"a.py": GOOD}, [_entry("a.py", "B603", 'subprocess.run(["ls"], check=True)', **over)]
    )
    rc = IS.main(["--check", "--root", str(root), "--ledger", str(ledger), "--today", TODAY.isoformat()])
    assert rc == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("review_by", "message"), [("2026-11-18", "has passed"), ("2027-06-01", "more than 180 days ahead")]
)
def test_the_review_date_is_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], review_by: str, message: str
) -> None:
    entry = _entry("a.py", "B603", 'subprocess.run(["ls"], check=True)', review_by=review_by)
    root, ledger = _tree(tmp_path, {"a.py": GOOD}, [entry])
    rc, out = _check(root, ledger, capsys)
    assert rc == 1 and message in out


def test_a_finding_is_never_filed_as_safe() -> None:
    """The ledger's `finding` entries name the open findings of the card's findings file, each of them; a finding the
    file says is fixed has no line left in the ledger at its file (H10G39-01, fixed in 47e63df: its suppressed call is
    gone, so neither a `finding` nor a `safe` line stays for it)."""
    import json

    ledger = IS.load_ledger(IS.LEDGER)
    findings = json.loads(
        (IS.ROOT / "docs" / "handover" / "bandit-weekly-ledger-2026-11-19" / "findings.json").read_text(
            encoding="utf-8"
        )
    )["findings"]
    assert findings
    open_ids = {f["id"] for f in findings if f.get("state", "open") == "open"}
    fixed = [f for f in findings if str(f.get("state", "")).startswith("fixed ")]
    assert {f["id"] for f in findings} == open_ids | {f["id"] for f in fixed}  # each finding is one or the other
    kept = [e for e in ledger if e.verdict == "finding"]
    assert {e.finding for e in kept} == open_ids
    for f in fixed:
        at = f["place"].split(":", 1)[0]
        assert not [e for e in ledger if e.path == at], (f["id"], at)
