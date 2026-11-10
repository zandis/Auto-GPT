"""tools/doclint.py (TB-PLAN-04 step 9, D-139): the eight documents are clean, and the checks catch what they claim."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import doclint


def test_the_repository_is_clean() -> None:
    assert doclint.main([]) == 0


def test_the_eight_documents() -> None:
    assert len(doclint.DOCS) == 8 and "docs/DECISIONS.md" in doclint.DOCS
    assert not doclint.check_set()


def test_slug_matches_github() -> None:
    assert doclint.slug("11. Cloud runs (owner's OK first)") == "11-cloud-runs-owners-ok-first"
    assert doclint.slug("Secrets (D-128, D-138): the one place") == "secrets-d-128-d-138-the-one-place"


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "real.py").write_text("")
    monkeypatch.setattr(doclint, "ROOT", tmp_path)
    monkeypatch.setattr(doclint, "ignored", lambda rel: False)
    return tmp_path


def test_catches_links_anchors_paths_and_headings(fake_root: Path) -> None:
    (fake_root / "docs" / "B.md").write_text("# B\n\n## Real part\n")
    (fake_root / "docs" / "A.md").write_text(
        "# A\n\n#### skipped\n\n## Twice\n\n## Twice\n\n"
        "[ok](B.md#real-part) [bad anchor](B.md#nope) [gone](C.md) [web](https://example.org)\n\n"
        "`tools/real.py` `tools/missing.py` `deploy/site/<gpu>.json`\n\n```\n[in a block](nowhere.md)\n```\n"
    )
    errs = doclint.check_doc("docs/A.md")
    text = "\n".join(errs)
    assert "head: level 4 after level 1" in text
    assert "head: twice" in text
    assert "#nope is not a heading" in text
    assert "C.md does not exist" in text
    assert "tools/missing.py does not exist" in text
    assert "real.py" not in text and "example.org" not in text and "nowhere.md" not in text and "<gpu>" not in text
    assert doclint.check_doc("docs/B.md") == []


def test_decisions_is_history(fake_root: Path) -> None:
    (fake_root / "docs" / "DECISIONS.md").write_text("# Decisions\n\n`tools/removed_long_ago.py` [x](gone.md)\n")
    assert doclint.check_doc("docs/DECISIONS.md", history=True) == []


def test_retired_names() -> None:
    hits = [m.group(0) for m in doclint.RETIRED_RE.finditer("see docs/HANDOFF.md and SPEC.md, not SIMPLE-PLAN.md")]
    assert hits == ["docs/HANDOFF.md", "SPEC.md"]
    assert not list(doclint.RETIRED_RE.finditer("spec/archive/SPEC.md and docs/RUNBOOK.md"))


GOOD_RECORD = (
    "# Gate G0\n\n## Register condition\n\n| Source | Open Blocker |\n| --- | --- |\n| TB-REG-01 | to fill |\n\n"
    "## Criteria\n\n| # | Criterion | Measure | Evidence | Result |\n| --- | --- | --- | --- | --- |\n"
    "| 1 | approved | recorded | `docs/plan/x.md` | open |\n\n## Notes\n\n| a | |\n"
)


def test_the_gate_records_are_complete() -> None:
    assert doclint.check_gates() == []
    for gate in ("G0", "GP-0", "GP-1", "GP", "G1"):
        assert gate in doclint.GATES


def test_catches_a_missing_record_and_a_missing_evidence_cell(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doclint, "GATES", ("G0", "G1"))
    gates = fake_root / doclint.GATE_DIR
    gates.mkdir(parents=True)
    (gates / "G0.md").write_text(GOOD_RECORD)
    assert doclint.check_gates() == [f"{doclint.GATE_DIR}/G1.md: gate: G1 has no record"]
    (gates / "G1.md").write_text(GOOD_RECORD.replace("`docs/plan/x.md`", " "))
    text = "\n".join(doclint.check_gates())
    assert "G1.md:13: gate: criterion row has no evidence cell" in text and "G0.md" not in text
    (gates / "G1.md").write_text(GOOD_RECORD.replace("## Register condition", "## Counts"))
    assert doclint.check_gates() == [f"{doclint.GATE_DIR}/G1.md:1: gate: no '## Register condition' section"]
    (gates / "G1.md").write_text(GOOD_RECORD.replace("Evidence", "Proof"))
    assert "no Evidence column" in "\n".join(doclint.check_gates())
