"""NEW-LIFE-1 (D-640; deep review 2026-11-12, LIFE-001): no pre-approved ruleset on a VALIDATION or PRODUCTION box.

A new box copied the eight shipped rulesets into its working copy, each ``status: approved`` by the project owner or
a synthetic coordinator, and the timers ran them on the hospital's data. A study is approved on a site box only by
that site: the shipped rulesets are examples for DEV, TEST and the demo.

* a box that is not DEV or TEST seeds nothing (the two readers' ``seed_working_copy`` and the compiler's repository);
* a box seeded before this card holds the examples already: there the approval that came from seeding is no
  approval (``load_approved`` refuses it, so no job runs it and the console lists it as not approved), while an
  approval the site gave, or an offline update an operator installed (D-77), stands.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from criteria_compiler import app as compiler_app
from criteria_compiler.repo import RulesetRepo
from orchestrator import scheduler
from tb_common.ruleset import RulesetNotApproved, list_rulesets, load_approved, seed_working_copy

from tests.rulesets_guard import RULESETS, copy_rulesets

SHIPPED = ["AD-MAB", "GOUT-COH", "GZQO", "NEUR-COH", "ONC-OSI", "RA-BIO", "RA-COH", "RA-JAK"]
SITE = ["PRODUCTION", "VALIDATION", None, "production", "STAGING"]  # None: unset is PRODUCTION (D-127)


def _env(monkeypatch: pytest.MonkeyPatch, name: str | None) -> None:
    if name is None:
        monkeypatch.delenv("TB_ENV", raising=False)
    else:
        monkeypatch.setenv("TB_ENV", name)


def _orch(rulesets: Path) -> SimpleNamespace:
    return SimpleNamespace(rulesets_dir=rulesets, cfg=SimpleNamespace(settings=SimpleNamespace(cohort=None)))


# ------------------------------------------------------------------------------------------------ a new box
@pytest.mark.parametrize("name", SITE)
def test_a_site_box_starts_with_no_ruleset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str | None) -> None:
    _env(monkeypatch, name)
    dest = tmp_path / "rulesets"
    assert seed_working_copy(dest) is False
    assert not dest.exists() or list_rulesets(dest) == []


@pytest.mark.parametrize("name", SITE)
def test_the_compilers_repository_seeds_nothing_on_a_site_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str | None
) -> None:
    _env(monkeypatch, name)
    repo = compiler_app.ruleset_repo(tmp_path / "rulesets")
    assert list_rulesets(tmp_path / "rulesets") == [] and repo.tags() == []


@pytest.mark.parametrize("name", ["DEV", "TEST", "test"])
def test_a_dev_or_test_box_is_seeded_as_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _env(monkeypatch, name)
    assert seed_working_copy(tmp_path / "a") is True and list_rulesets(tmp_path / "a") == SHIPPED
    repo = compiler_app.ruleset_repo(tmp_path / "b")
    assert list_rulesets(tmp_path / "b") == SHIPPED and "RA-JAK/v1.0.0" in repo.tags()
    assert load_approved(tmp_path / "a", "RA-JAK").id == "RA-JAK" and load_approved(tmp_path / "b", "GZQO").id == "GZQO"


# ------------------------------------------------------------------------------------------------ a box seeded before
def _seeded_by_copy(tmp_path: Path) -> Path:
    """What ``seed_working_copy`` left on a box before this card: the shipped folder, no repository."""
    return copy_rulesets(tmp_path / "copied")


def _seeded_by_compiler(tmp_path: Path) -> Path:
    """What the compiler's first start left: the repository, each shipped ruleset tagged "vendor-shipped"."""
    RulesetRepo(tmp_path / "repo", RULESETS)
    return tmp_path / "repo"


@pytest.mark.parametrize("seeded", [_seeded_by_copy, _seeded_by_compiler])
@pytest.mark.parametrize("name", SITE)
def test_a_seeded_approval_is_no_approval_on_a_site_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seeded: object, name: str | None
) -> None:
    rulesets = seeded(tmp_path)  # type: ignore[operator]
    _env(monkeypatch, "TEST")
    assert [load_approved(rulesets, rid).id for rid in SHIPPED] == SHIPPED  # a TEST box runs its examples
    _env(monkeypatch, name)
    for rid in SHIPPED:
        with pytest.raises(RulesetNotApproved, match="not approved at this site"):
            load_approved(rulesets, rid)
        with pytest.raises(RulesetNotApproved):
            load_approved(rulesets, rid, "1.0.0")


@pytest.mark.parametrize("seeded", [_seeded_by_copy, _seeded_by_compiler])
def test_the_timers_and_the_console_find_no_approved_study_on_a_box_seeded_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seeded: object
) -> None:
    from console.backend import ruleset_infos

    rulesets = seeded(tmp_path)  # type: ignore[operator]
    _env(monkeypatch, "TEST")
    assert scheduler.nav_rulesets(_orch(rulesets)) == ["ONC-OSI", "RA-BIO"]  # type: ignore[arg-type]
    assert scheduler.cohort_rulesets(_orch(rulesets)) == ["GOUT-COH", "NEUR-COH", "RA-COH"]  # type: ignore[arg-type]
    _env(monkeypatch, "PRODUCTION")
    assert scheduler.nav_rulesets(_orch(rulesets)) == []  # type: ignore[arg-type]
    assert scheduler.cohort_rulesets(_orch(rulesets)) == []  # type: ignore[arg-type]
    assert {(i.id, i.status) for i in ruleset_infos(rulesets)} == {(rid, "draft") for rid in SHIPPED}


@pytest.mark.parametrize(
    "message",
    ["RA-JAK v1.0.0 approved by pi@site.example", "RA-JAK/v1.0.0 (offline update, update:2026.11-1)"],
)
def test_the_sites_own_approval_and_an_installed_update_stand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    """The same files, approved the site's way (the compiler's tag names who) or installed by an operator from a
    verified update (D-77): not a seeded approval, whatever the manifest says."""
    repo = RulesetRepo(tmp_path / "repo", RULESETS)
    del repo.refs[b"refs/tags/RA-JAK/v1.0.0"]
    repo.tag("RA-JAK/v1.0.0", "main", message, "pi@site.example")
    _env(monkeypatch, "PRODUCTION")
    assert load_approved(tmp_path / "repo", "RA-JAK").version == "1.0.0"
    with pytest.raises(RulesetNotApproved, match="not approved at this site"):
        load_approved(tmp_path / "repo", "GZQO")  # its neighbour is still the seeded one


def test_a_ruleset_without_a_repository_that_is_not_a_shipped_one_is_read_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the shipped example is refused: a folder some tool materialized (no repository) with another manifest
    keeps the rule it had (status approved)."""
    rulesets = copy_rulesets(tmp_path / "copied")
    manifest = rulesets / "RA-JAK" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("（合成）", "（本院）"), encoding="utf-8")
    _env(monkeypatch, "PRODUCTION")
    assert load_approved(rulesets, "RA-JAK").id == "RA-JAK"
