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

from tests.rulesets_guard import RULESETS, approve_at_site, copy_rulesets

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


def test_without_a_repository_nothing_is_approved_on_a_site_box(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #412 (M1): a box seeded by an earlier release holds manifests that differ from today's image by a
    byte (D-103 re-approved them in place). An approval is a tag of the repository; a folder without one holds
    none, whatever its manifests say. A DEV or TEST box reads such a folder as before."""
    rulesets = copy_rulesets(tmp_path / "copied")
    for rid, change in (("ONC-OSI", b"\n"), ("RA-BIO", None)):
        manifest = rulesets / rid / "manifest.yaml"
        data = manifest.read_bytes()
        manifest.write_bytes(data + change if change else data.replace(b"\n", b"\r\n"))
    manifest = rulesets / "RA-JAK" / "manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("（合成）", "（本院）"), encoding="utf-8")
    _env(monkeypatch, "TEST")
    assert load_approved(rulesets, "RA-JAK").id == "RA-JAK"
    _env(monkeypatch, "PRODUCTION")
    for rid in ("ONC-OSI", "RA-BIO", "RA-JAK"):
        with pytest.raises(RulesetNotApproved, match="not approved at this site"):
            load_approved(rulesets, rid)
    assert scheduler.nav_rulesets(_orch(rulesets)) == []  # type: ignore[arg-type]


def test_a_tag_that_names_nobody_is_no_approval_on_a_site_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of #412 (L1): a bare (lightweight) tag has no message, so nobody is named: not an approval."""
    repo = RulesetRepo(tmp_path / "repo", RULESETS)
    commit = repo.ref("refs/tags/RA-BIO/v1.0.0")
    assert commit is not None
    repo.refs[b"refs/tags/RA-BIO/v1.0.0"] = commit
    _env(monkeypatch, "PRODUCTION")
    with pytest.raises(RulesetNotApproved, match="not approved at this site"):
        load_approved(tmp_path / "repo", "RA-BIO")


def test_a_broken_repository_stops_no_timer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of #412 (L2): the timers now open the repository. A tag that points at nothing is a ruleset the
    timer does not start, not an exception in the scheduler; its neighbour still runs."""
    repo = RulesetRepo(tmp_path / "repo", RULESETS)
    approve_at_site(tmp_path / "repo")
    repo.refs[b"refs/tags/ONC-OSI/v1.0.0"] = b"0" * 40
    _env(monkeypatch, "PRODUCTION")
    assert scheduler.nav_rulesets(_orch(tmp_path / "repo")) == ["RA-BIO"]  # type: ignore[arg-type]
    _env(monkeypatch, "TEST")  # a TEST box does not read the tag (as before): the job itself would
    assert scheduler.nav_rulesets(_orch(tmp_path / "repo")) == ["ONC-OSI", "RA-BIO"]  # type: ignore[arg-type]


def test_an_update_installed_over_a_seeded_example_is_the_operators_act(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #412 (M2): the import said "installed" over a seeded tag of the same content and left the seeded
    tag, so the ruleset stayed refused. The operator's install is recorded on the tag (D-77) and stands."""
    import io
    import zipfile

    from criteria_compiler.import_ruleset import install

    repo = RulesetRepo(tmp_path / "repo", RULESETS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in sorted((RULESETS / "RA-JAK").rglob("*")):
            if f.is_file():
                z.write(f, f"RA-JAK/{f.relative_to(RULESETS / 'RA-JAK').as_posix()}")
    _env(monkeypatch, "PRODUCTION")
    with pytest.raises(RulesetNotApproved):
        load_approved(tmp_path / "repo", "RA-JAK")
    assert install(repo, buf.getvalue(), "update:2026.11-1") == "RA-JAK/v1.0.0"
    assert repo.tag_message("RA-JAK/v1.0.0") == "RA-JAK/v1.0.0 (offline update, update:2026.11-1)"
    assert load_approved(tmp_path / "repo", "RA-JAK").version == "1.0.0"
    assert install(repo, buf.getvalue(), "update:2026.11-2") == "RA-JAK/v1.0.0"  # again: nothing to do, tag kept
    assert repo.tag_message("RA-JAK/v1.0.0").endswith("update:2026.11-1)")


def test_the_fixture_of_a_production_box_approves_its_studies_the_sites_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    RulesetRepo(tmp_path / "repo", RULESETS)
    assert len(approve_at_site(tmp_path / "repo")) == len(SHIPPED) and approve_at_site(tmp_path / "repo") == []
    _env(monkeypatch, "PRODUCTION")
    assert [load_approved(tmp_path / "repo", rid).id for rid in SHIPPED] == SHIPPED


def test_the_synthetic_compose_stack_says_it_is_a_test_box() -> None:
    """Review of #412 (H2): the test overlay left TB_ENV unset for the compiler and the orchestrator, which is
    PRODUCTION: with D-640 that stack would hold no example study. The services that seed or run rulesets say TEST."""
    import yaml

    overlay = yaml.safe_load((RULESETS.parent / "deploy" / "docker-compose.test.yml").read_text(encoding="utf-8"))
    for name in ("criteria-compiler", "orchestrator"):
        assert overlay["services"][name]["environment"]["TB_ENV"] == "${TB_ENV:-TEST}", name


def test_the_synthetic_in_process_box_names_who_approved_its_example_studies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Train 5's demo-boot: ``tools.cgmh_demo`` (and the other tools on ``tests.inproc_box.make_box``) run with no
    ``TB_ENV``, which is PRODUCTION, on a box whose studies carried the seeded approval only, so with D-640 its
    SCREEN failed "no approved version on this box". The synthetic box says what it is: its example studies are
    approved by the box builder, by name, the way the site's approval writes a tag."""
    from datetime import date

    from tests.inproc_box import SYNTHETIC_APPROVER, make_box

    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"trialbox-test-site-key-0123456789abcdef")
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))
    rulesets = box.orch.rulesets_dir
    for name in SITE:
        _env(monkeypatch, name)
        assert [load_approved(rulesets, rid).id for rid in SHIPPED] == SHIPPED
    assert RulesetRepo(rulesets).tag_message("GZQO/v1.0.0") == f"GZQO v1.0.0 approved by {SYNTHETIC_APPROVER}"
    # a box reopened on its own folder (the demo's --keep) keeps the approval it has
    make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))
    assert RulesetRepo(rulesets).tag_message("GZQO/v1.0.0") == f"GZQO v1.0.0 approved by {SYNTHETIC_APPROVER}"
