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


def test_links_and_paths_only_warn_unless_strict(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-311: a broken link or path in a document is a warning; set, head and gone problems still fail."""
    monkeypatch.setattr(doclint, "DOCS", ["docs/A.md"])
    monkeypatch.setattr(doclint, "check_gone", lambda: [])
    (fake_root / "docs" / "A.md").write_text("# A\n\n[gone](C.md) `tools/missing.py`\n")
    assert doclint.main([]) == 0
    assert doclint.main(["--strict"]) == 1
    (fake_root / "docs" / "A.md").write_text("no title\n")
    assert doclint.main([]) == 1
