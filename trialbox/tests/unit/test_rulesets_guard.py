"""T-650c: the tests never write into the committed rulesets/ folder.

* copies of the rulesets leave out stray temporary files (``.RA-BIO.tmp``), so a copy never trips over one;
* the guard's snapshot sees a ruleset re-materialised in place (rmtree + rename, same bytes);
* the committed folder is the same at the end of a test as at its start (the autouse check in tests/conftest.py
  does this for every test; here it is shown once on its own).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.rulesets_guard import RULESETS, copy_rulesets, describe, snapshot

pytestmark = pytest.mark.nodb


def test_a_copy_leaves_out_stray_temporary_files(tmp_path: Path) -> None:
    src = copy_rulesets(tmp_path / "src", src=RULESETS / "GOUT-COH")
    (src / ".RA-BIO.tmp").mkdir()
    (src / ".RA-BIO.tmp" / "manifest.yaml").write_text("half written\n", encoding="utf-8")
    (src / "valuesets" / "VS_X.json.tmp").write_text("{", encoding="utf-8")
    dst = copy_rulesets(tmp_path / "dst", "tests", src=src)
    assert (dst / "manifest.yaml").is_file()
    assert not (dst / ".RA-BIO.tmp").exists() and not (dst / "valuesets" / "VS_X.json.tmp").exists()
    assert not (dst / "tests").exists()  # the names given are left out too


def test_the_snapshot_sees_a_ruleset_materialised_again(tmp_path: Path) -> None:
    pytest.importorskip("dulwich")
    from criteria_compiler.repo import RulesetRepo

    copy_rulesets(tmp_path / "seed" / "GOUT-COH", src=RULESETS / "GOUT-COH")
    repo = RulesetRepo(tmp_path / "repo", tmp_path / "seed")
    before = snapshot(repo.path)
    repo.materialize("GOUT-COH")  # the same bytes, written to .GOUT-COH.tmp and renamed over GOUT-COH
    after = snapshot(repo.path)
    assert after != before
    assert "GOUT-COH" in describe(before, after)
    assert describe(after, snapshot(repo.path)) == "no difference"


def test_the_committed_rulesets_stay_as_they_are() -> None:
    before = snapshot()
    assert before and any(p == "RA-BIO" for p, *_ in before)
    assert not any(Path(p).name.endswith(".tmp") or Path(p).name.startswith(".") for p, *_ in before)
    assert snapshot() == before
