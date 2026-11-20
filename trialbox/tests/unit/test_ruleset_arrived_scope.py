"""10D-28 (D-1369), the review of #1174 at f8fcc04e: 1 High, 4 Medium, 8 Low, each reproduced at the real call.

H1: an arrived rule set runs only as SCREEN and MICROBATCH, narrowed; every other job type refuses it, audited; the
table of job types is held to the scenario registry. M1: a profile naming nobody is closed. M2: MICROBATCH's given
patients are narrowed. M3: a narrower profile takes effect at once. M4: the release floor counts the release the part
rides with. L1-L7 as the review lists them. Synthetic data only.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import os
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from criteria_compiler.import_ruleset import ImportRefused, Verified, install_outcome, put_site_profile
from criteria_compiler.repo import RulesetRepo
from tb_common.audit import AuditLog
from tb_common.ruleset import ArrivedScopeClosed, arrived_scope, load_approved
from tb_common.ruleset_part import VERSION

from tests.rulesets_guard import approve_at_site, copy_rulesets
from tests.unit.test_ruleset_in_update_bundle import (
    PLANTED,
    _cli,
    _plain_zip,
    _plant,
    apply_bundle,
    audit_events,
    evidence,
    make_part,
    members,
    site_box,
)
from tools import ruleset_bundle, sign_bundle


@pytest.fixture
def site_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")


@pytest.fixture
def head(tmp_path: Path, site_env: None) -> RulesetRepo:
    seed = copy_rulesets(tmp_path / "seed")
    _plant(seed)
    repo = RulesetRepo(tmp_path / "head", seed)
    approve_at_site(tmp_path / "head", by=PLANTED[0])
    return repo


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path]:
    return sign_bundle.keygen(tmp_path / "vendor")


def _profile(practitioners: list[str] | None, departments: list[str] | None = None, list_to: str = "pi@site.test"
             ) -> bytes:  # fmt: skip
    screen: dict[str, Any] = {"appointment_window_days": 90}
    if practitioners is not None:
        screen["practitioners"] = practitioners
    if departments is not None:
        screen["departments"] = departments
    return yaml.safe_dump({"routing": {"list_to": [list_to]}, "scopes": {"screen": screen}}).encode()


def _put(box_dir: Path, prof: bytes, version: str = "1.0.0", sha: str | None = None) -> None:
    put_site_profile(RulesetRepo(box_dir), "GZQO", prof, "op", version=version, part_sha256=sha,
                     audit=AuditLog(box_dir.parent / "pa"))  # fmt: skip


def _arrived(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path, prof: bytes) -> Path:
    """A site box holding GZQO v1.0.0 that arrived through the update with the site's ``prof``."""
    priv, pub = keys
    box, updates = site_box(tmp_path, profile=False)
    _put(box.repo_dir, prof)
    part = make_part(head, tmp_path / "GZQO.part.zip")
    ruleset_bundle.build(priv, "rs1", [part], tmp_path / "rs.tar", release_seq=4)
    assert apply_bundle(tmp_path / "rs.tar", pub, box, updates, tmp_path / "stage")["ok"]
    return box.repo_dir


def _ctx(repo_dir: Path, kind: str, audit: AuditLog) -> Any:
    return SimpleNamespace(rulesets_dir=repo_dir, job=SimpleNamespace(type=kind, job_id="J1", options={}),
                           orch=SimpleNamespace(audit=audit), today=lambda: date(2026, 11, 20))  # fmt: skip


# --------------------------------------------------------------------------------------------- H1
def test_h1_every_job_type_narrows_refuses_or_runs_no_rule_set(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios import registry
    from orchestrator.scenarios.review import ARRIVED_RULE, approved_or_none, guard_arrived

    reg = registry()
    assert set(reg) == set(ARRIVED_RULE), "a job type neither narrows nor refuses an arrived rule set: add it"
    repo_dir = _arrived(head, keys, tmp_path, _profile(["S-001"], ["RHEU"]))
    rs = load_approved(repo_dir, "GZQO")
    log = AuditLog(tmp_path / "orch-audit")
    for kind, rule in ARRIVED_RULE.items():
        ctx = _ctx(repo_dir, kind, log)
        if rule == "narrows":
            guard_arrived(ctx, rs)
        elif rule == "refuses":
            with pytest.raises(StepFailed) as e:
                guard_arrived(ctx, rs)
            assert f"a {kind} job is refused" in str(e.value) and "ja:" in str(e.value) and "zh-TW:" in str(e.value)
        else:  # its module runs no rule set over patients: it never loads one to run
            src = Path(inspect.getsourcefile(reg[kind]) or "").read_text(encoding="utf-8")
            assert "require_approved(" not in src, kind
            assert all("run=False" in ln for ln in src.splitlines() if "approved_or_none(ctx" in ln), kind
            assert "load_approved(" not in src or kind == "APPROVE", kind  # APPROVE reads the approval state only
    refused = [e for e in audit_events(tmp_path / "orch-audit") if e["event"] == "job.ruleset_refused"]
    assert sorted(e["detail"]["job_type"] for e in refused) == sorted(k for k, r in ARRIVED_RULE.items()
                                                                      if r == "refuses")  # fmt: skip
    # the one call sits in approved_or_none, which every scenario that runs a rule set goes through
    with pytest.raises(StepFailed, match="a NAV job is refused"):
        approved_or_none(_ctx(repo_dir, "NAV", log), "GZQO")
    assert approved_or_none(_ctx(repo_dir, "SCREEN", log), "GZQO") is not None
    # a rule set approved here is unchanged
    guard_arrived(_ctx(repo_dir, "NAV", log), load_approved(repo_dir, "RA-JAK"))


def test_h1_no_scenario_module_loads_a_rule_set_to_run_but_through_the_guard() -> None:
    root = Path(__file__).resolve().parents[2] / "services" / "orchestrator" / "scenarios"
    for f in sorted(root.glob("*.py")):
        if f.name in ("review.py", "approve.py"):  # the guard's own module; APPROVE reads the approval state
            continue
        assert "load_approved(" not in f.read_text(encoding="utf-8"), f.name


# --------------------------------------------------------------------------------------------- M1
def test_m1_a_profile_naming_nobody_is_closed(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    box, _updates = site_box(tmp_path, profile=False)
    with pytest.raises(ImportRefused, match="names no practitioner and no department") as e:
        _put(box.repo_dir, _profile(None))
    assert "ja:" in str(e.value) and "zh-TW:" in str(e.value)
    assert RulesetRepo(box.repo_dir).read("main", "profiles/GZQO.yaml") is None
    # the site's current profile (here accepting the next version) leaves nobody of the installed list: closed
    repo_dir = _arrived(head, keys, tmp_path / "b", _profile(["S-001"]))
    _put(repo_dir, _profile(["S-999"]), version="1.0.1")
    with pytest.raises(ArrivedScopeClosed):
        arrived_scope(repo_dir, load_approved(repo_dir, "GZQO"))


# --------------------------------------------------------------------------------------------- M2
def test_m2_given_patients_are_narrowed(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    from orchestrator.scenarios import screen

    repo_dir = _arrived(head, keys, tmp_path, _profile(["P1"], ["RHEU"]))
    rs = load_approved(repo_dir, "GZQO")
    given = [screen.Scoped("A", None, "P1", "RHEU"), screen.Scoped("B", None, "P2", "RHEU"),
             screen.Scoped("C", None, "P1", "META")]  # fmt: skip
    ctx = _ctx(repo_dir, "MICROBATCH", AuditLog(tmp_path / "a"))
    assert [s.pid for s in screen.in_arrived_scope(ctx, rs, given)] == ["A"]
    ctx.metrics = lambda **kw: None
    ctx.services = SimpleNamespace()
    import orchestrator.scenarios.screen as mod

    seen: list[list[str]] = []
    orig = mod.drop_opted_out
    try:
        mod.drop_opted_out = lambda _c, s: seen.append([x.pid for x in s]) or []  # type: ignore[assignment]
        mod.judge_for = lambda _c, _r: None  # type: ignore[assignment]
        screen.run_screen(ctx, rs, date(2026, 11, 20), "s", given=given)
    except Exception:
        pass
    finally:
        mod.drop_opted_out = orig
    assert seen and seen[0] == ["A"]


# --------------------------------------------------------------------------------------------- M3, L1
def test_m3_a_narrower_profile_takes_effect_at_once(head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path) -> None:
    repo_dir = _arrived(head, keys, tmp_path, _profile(["S-001", "S-002"]))
    _put(repo_dir, _profile(["S-001"], list_to="new@site.test"))
    rs = load_approved(repo_dir, "GZQO")
    assert rs.manifest.scopes.screen.practitioners == ["S-001"]  # type: ignore[union-attr]
    assert rs.manifest.routing.list_to == ["new@site.test"]  # type: ignore[union-attr]
    assert arrived_scope(repo_dir, rs) == (["S-001"], None)


def test_l1_a_repeat_never_takes_a_profile_accepted_for_another_version(
    head: RulesetRepo, keys: tuple[Path, Path], tmp_path: Path
) -> None:
    repo_dir = _arrived(head, keys, tmp_path, _profile(["S-001"]))
    _put(repo_dir, _profile(["S-001", "S-009"], list_to="other@site.test"), version="1.0.1")
    data = (tmp_path / "GZQO.part.zip").read_bytes()
    install_outcome(RulesetRepo(repo_dir), data, "update:again", verified=evidence(data))
    rs = load_approved(repo_dir, "GZQO")
    assert rs.manifest.routing.list_to == ["pi@site.test"]  # type: ignore[union-attr]
    assert arrived_scope(repo_dir, rs) == (["S-001"], None)  # the other version's wider list never widens it


# --------------------------------------------------------------------------------------------- M4, L4
def _stage(tmp_path: Path, zbytes: bytes, release: bool) -> Any:
    from tools.trialbox.update import Plan

    stage = tmp_path / "stage4"
    (stage / "ruleset").mkdir(parents=True)
    (stage / "ruleset" / "p.zip").write_bytes(zbytes)
    raw = json.dumps({"files": [{"path": "p.zip", "kind": "ruleset",
                                 "sha256": hashlib.sha256(zbytes).hexdigest()}]}).encode()  # fmt: skip
    (stage / "manifest.json").write_bytes(raw)
    return Plan("b1", hashlib.sha256(raw).hexdigest(), "v", [], stage, 4, release={"x": 1} if release else None)


def test_m4_the_floor_counts_the_release_the_part_rides_with(tmp_path: Path) -> None:
    from tools.trialbox.update import ruleset_evidence

    assert ruleset_evidence(_stage(tmp_path / "a", b"z", True), 3)["box_release_seq"] == 4
    assert ruleset_evidence(_stage(tmp_path / "b", b"z", False), 3)["box_release_seq"] == 3


def test_l4_the_evidence_is_the_signed_manifests_hash(tmp_path: Path) -> None:
    from tools.trialbox.update import UpdateFailed, ruleset_evidence

    plan = _stage(tmp_path, b"zip", False)
    ev = ruleset_evidence(plan, 3)
    assert (
        ev["files"] == {"p.zip": hashlib.sha256(b"zip").hexdigest()} and ev["manifest_sha256"] == plan.manifest_sha256
    )
    (plan.stage / "ruleset" / "p.zip").write_bytes(b"swapped")
    with pytest.raises(UpdateFailed, match="not the one the signed manifest records"):
        ruleset_evidence(plan, 3)
    plan.manifest_sha256 = "0" * 64
    with pytest.raises(UpdateFailed, match="not the one verified"):
        ruleset_evidence(plan, 3)


# --------------------------------------------------------------------------------------------- L2
def test_l2_a_version_has_one_spelling(tmp_path: Path, site_env: None) -> None:
    assert VERSION.fullmatch("1.0.5") and not VERSION.fullmatch("1.0.05") and not VERSION.fullmatch("01.0.5")
    box, _u = site_box(tmp_path)
    files = members(_plain_zip())
    m = yaml.safe_load(files["GZQO/manifest.yaml"])
    m["version"] = "1.0.05"
    files["GZQO/manifest.yaml"] = yaml.safe_dump(m).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    with pytest.raises(ImportRefused, match="not a rule set version"):
        install_outcome(RulesetRepo(box.repo_dir), buf.getvalue(), "u", verified=evidence(buf.getvalue()))


# --------------------------------------------------------------------------------------------- L3
def test_l3_the_evidence_file_is_checked_on_what_was_opened(
    head: RulesetRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from criteria_compiler import import_ruleset

    monkeypatch.setattr(import_ruleset, "EVIDENCE_OWNER", os.getuid())
    d = tmp_path / "ev"
    d.mkdir(mode=0o700)
    real = d / "real.json"
    real.write_text(json.dumps(evidence(b"x").record()))
    real.chmod(0o644)
    assert import_ruleset.evidence_file(str(real)).bundle_id == "2026.11-1-rs1"
    link = d / "link.json"
    link.symlink_to(real)
    with pytest.raises(ImportRefused, match="was not written by the update"):
        import_ruleset.evidence_file(str(link))
    hard = d / "hard.json"
    os.link(real, hard)
    with pytest.raises(ImportRefused, match="was not written by the update"):
        import_ruleset.evidence_file(str(real))  # two names: a link to it may stand anywhere
    hard.unlink()
    d.chmod(0o777)  # a folder others may write: what is in it can be replaced
    with pytest.raises(ImportRefused, match="was not written by the update"):
        import_ruleset.evidence_file(str(real))
    d.chmod(0o700)


# --------------------------------------------------------------------------------------------- L6
def test_l6_the_hand_install_refuses_strays_and_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site_env: None
) -> None:
    box, _u = site_box(tmp_path)
    stray = io.BytesIO()
    with zipfile.ZipFile(stray, "w") as z:
        for n, b in members(_plain_zip()).items():
            z.writestr(n, b)
        z.writestr("EVIL/x.txt", b"x")
    with pytest.raises(ImportRefused, match="outside the rule set's folder"):
        install_outcome(RulesetRepo(box.repo_dir), stray.getvalue(), "u")
    shipped = tmp_path / "GZQO.zip"
    shipped.write_bytes(_plain_zip())
    imp = _cli(monkeypatch, box.repo_dir, tmp_path / "cli-audit")
    assert imp.main([str(shipped), "--by", "synthetic-run:op"]) == 0
    ev = [e for e in audit_events(tmp_path / "cli-audit") if e["event"] == "approve.ruleset_installed"]
    assert len(ev) == 1 and ev[0]["ruleset"] == "GZQO" and ev[0]["detail"]["by_claimed"] == "synthetic-run:op"


# --------------------------------------------------------------------------------------------- L7
def test_l7_the_first_load_says_what_is_true() -> None:
    src = (Path(__file__).resolve().parents[2] / "tools" / "trialbox" / "update.py").read_text(encoding="utf-8")
    assert "again after the start" not in src and "NOT imported by a first install" in src


def test_the_verified_record_binds_the_signed_manifest() -> None:
    rec = evidence(b"x").record()
    assert Verified.from_record(rec).manifest_sha256 == rec["manifest_sha256"]
    with pytest.raises(ImportRefused):
        Verified.from_record({k: v for k, v in rec.items() if k != "manifest_sha256"})
