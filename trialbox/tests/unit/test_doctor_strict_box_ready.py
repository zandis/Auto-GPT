"""ASSESS-1 §8 step 6 (TRIAGE-1 G2, RC3, RC4): ``trialbox doctor --strict`` proves the box ready for a night, or fails.

The R1 box ended its install with no backup key (P-01), a site mapping that mapped no table (P-09), no mail relay and
nobody saying so (P-10), served models that were not the pinned ones and a pair canary at 18/54 (P-08); the doctor
said WARN or nothing, and the night failed. Each of those is a row now, in the one readiness list ``doctor.READINESS``;
under --strict each must PASS, the time source too, and --strict always asks the model servers. A box whose own
served models fail their canary is not ready: the canary's record is a readiness row, so "doctor --strict all PASS"
(the acceptance's sign-off row) cannot hold without a passing selftest.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from tools.box import plan as bp
from tools.trialbox import __main__ as cli
from tools.trialbox import backup as bk
from tools.trialbox import doctor as d

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]


def _inp(tmp_path: Path, **env: str) -> d.DoctorInputs:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text("", encoding="utf-8")
    return d.DoctorInputs(env={"TB_ENV": "PRODUCTION", **env}, settings={}, deploy=deploy, in_image=True)


def test_the_contract_names_every_row_of_the_step() -> None:
    for row in ("backup_key", "site_mapping", "mail_relay", "serving", "clock", "selftest"):
        assert row in d.READINESS, row
    every = {fn.__name__.removeprefix("check_") for fn in d.CHECKS + d.LIVE}
    assert {"backup_key", "site_mapping", "mail_relay", "selftest"} <= every
    assert "site_mapping" in d.IMAGE_CHECKS  # the adapter's code: the box image's part on a host


def test_no_backup_key_fails_on_production_and_a_key_passes(tmp_path: Path) -> None:
    inp = _inp(tmp_path)
    c = d.check_backup_key(inp)
    assert c.status == "FAIL" and "no backup key" in c.detail and "ceremony" in c.detail
    assert d.check_backup_key(_inp(tmp_path, TB_ENV="DEV")).status == "WARN"
    pub = tmp_path / "deploy" / "secrets" / "backup.pub"
    bk.keygen(tmp_path / "backup.key", pub)  # a throwaway key pair: the backup can encrypt to it
    assert d.check_backup_key(inp).status == "PASS"
    pub.write_text("", encoding="utf-8")  # an empty file is no key
    assert d.check_backup_key(inp).status == "FAIL"


def test_during_the_install_a_missing_backup_key_is_a_warn_with_the_ceremony_line(tmp_path: Path) -> None:
    """The key can only be made once the box runs (RUNBOOK section 5), so install.sh's host check (which sets
    TB_DOCTOR_INSTALL_PHASE) cannot require it; after the install the row FAILs again, and --strict always does."""
    for env in ("VALIDATION", "PRODUCTION"):
        c = d.check_backup_key(_inp(tmp_path, TB_ENV=env, TB_DOCTOR_INSTALL_PHASE="1"))
        assert c.status == "WARN" and "RUNBOOK" in c.detail and "ceremony" in c.detail, env
        assert d.check_backup_key(_inp(tmp_path, TB_ENV=env)).status == "FAIL", env
    strict = d.strict([d.check_backup_key(_inp(tmp_path, TB_DOCTOR_INSTALL_PHASE="1"))])
    assert next(c for c in strict if c.name == "backup_key").status == "FAIL"
    pub = tmp_path / "deploy" / "secrets" / "backup.pub"
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text("not a key\n", encoding="utf-8")  # there but wrong is no "not yet": FAIL in the install too
    assert d.check_backup_key(_inp(tmp_path, TB_DOCTOR_INSTALL_PHASE="1")).status == "FAIL"


def test_a_backup_key_the_backup_cannot_encrypt_to_fails(tmp_path: Path) -> None:
    """TB-01: a file that is there is not yet a key; the backup must be able to encrypt to it."""
    inp = _inp(tmp_path)
    pub = tmp_path / "deploy" / "secrets" / "backup.pub"
    bk.keygen(tmp_path / "backup.key", pub)
    good = pub.read_text(encoding="utf-8").strip()
    for bad in ("age1 synthetic public key for a test", good[: len(good) // 2], "A" * 43 + "="):
        pub.write_text(bad + "\n", encoding="utf-8")
        c = d.check_backup_key(inp)
        assert c.status == "FAIL" and "cannot encrypt" in c.detail, (bad, c)
        assert d.check_backup_key(_inp(tmp_path, TB_ENV="DEV")).status == "WARN"


def test_the_installers_site_mapping_maps_tables_and_an_empty_one_fails(tmp_path: Path) -> None:
    inp = _inp(tmp_path, TB_SETTINGS_FILE="settings.yaml")  # the box's own settings file, read without --settings
    site_file = tmp_path / "deploy" / "site" / bp.BOX_MAPPING
    site_file.parent.mkdir(parents=True)
    site_file.write_text(bp.mapping_text("Asia/Taipei"), encoding="utf-8")  # as the installer writes it
    settings = tmp_path / "deploy" / "settings.yaml"
    settings.write_text(f"data_source: {{type: csv, mapping: {bp.BOX_MAPPING}}}\n", encoding="utf-8")
    c = d.check_site_mapping(inp)
    assert c.status == "PASS" and str(site_file) in c.detail and "table(s)" in c.detail, c.detail
    site_file.write_text(bp.mapping_text("Asia/Taipei") + "tables: {}\n", encoding="utf-8")  # declared, none
    c = d.check_site_mapping(inp)
    assert c.status == "FAIL" and "declares no table" in c.detail
    c = d.check_site_mapping(_inp(tmp_path))  # no settings file: the mapping is not known
    assert c.status == "FAIL" and "no box settings" in c.detail
    settings.write_text("data_source: {type: csv}\n", encoding="utf-8")  # no mapping: the adapter's default
    c = d.check_site_mapping(inp)
    assert c.status == "PASS" and "demo_his.yaml" in c.detail, c.detail


def test_mail_relay_given_or_no_mail_accepted_by_name(tmp_path: Path) -> None:
    c = d.check_mail_relay(_inp(tmp_path))
    assert c.status == "WARN" and "TB_NO_MAIL_ACCEPTED_BY" in c.detail and "SMTP_HOST" in c.detail
    assert d.strict([c])[0].status == "FAIL"  # the plain doctor warns (U5-1); --strict fails
    assert d.check_mail_relay(_inp(tmp_path, SMTP_HOST="relay.example.org")).status == "PASS"
    named = d.check_mail_relay(_inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead", TB_NO_MAIL_ACCEPTED_ON="2026-11-27"))
    assert named.status == "PASS" and "IT lead" in named.detail
    assert d.check_mail_relay(_inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead")).status == "WARN"  # no day
    bad_day = _inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead", TB_NO_MAIL_ACCEPTED_ON="soon")
    assert d.check_mail_relay(bad_day).status == "WARN"


def _canary(folder: Path, **over: Any) -> None:
    rep = {"ok": True, "pair": {"decided_wrong": 0}, "problems": [], "at_epoch": time.time(), **over}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "selftest.json").write_text(json.dumps(rep), encoding="utf-8")


def test_selftest_row_needs_a_recent_passing_pair_canary(tmp_path: Path) -> None:
    orch = tmp_path / "orch"
    inp = _inp(tmp_path, TB_ORCH_DIR=str(orch))
    c = d.check_selftest(inp)
    assert c.status == "WARN" and "no canary result" in c.detail and "trialbox selftest" in c.detail
    assert d.strict([c])[0].status == "FAIL"
    _canary(orch, ok=False, problems=["judge failed the canary (18/54)"])  # the R1 box (E2E P-08)
    c = d.check_selftest(inp)
    assert c.status == "WARN" and "18/54" in c.detail
    _canary(orch, at_epoch=time.time() - 80 * 3600)
    assert d.check_selftest(inp).status == "WARN"
    _canary(orch, pair=None)
    assert d.check_selftest(inp).status == "WARN"
    _canary(orch)
    assert d.check_selftest(inp).status == "PASS"


def test_strict_turns_each_new_row_and_the_clock_into_a_fail() -> None:
    lines = [d.Check(n, "PASS", "ok") for n in d.READINESS]
    assert d.ok(d.strict(lines))
    for name in ("backup_key", "site_mapping", "mail_relay", "clock", "serving", "selftest"):
        warned = [d.Check(c.name, "WARN", "soft") if c.name == name else c for c in lines]
        assert d.ok(warned) and not d.ok(d.strict(warned)), name
        assert not d.ok(d.strict([c for c in lines if c.name != name])), name  # unchecked is a FAIL


def test_strict_always_asks_the_model_servers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    asked: list[tuple[str, ...]] = []

    def run(_inp: Any, which: tuple[Any, ...], *_a: Any, **_k: Any) -> list[d.Check]:
        names = tuple(fn.__name__.removeprefix("check_") for fn in which)
        asked.append(names)
        return [d.Check(n, "PASS", "ok") for n in (*names, "key_escrow")]  # key_escrow: doctor_m5's module row

    monkeypatch.setattr(d, "run", run)
    monkeypatch.setattr(d, "needs_image", lambda: False)
    assert cli.main(["doctor"]) == 0
    assert "serving" not in asked[-1]  # the plain doctor is as before
    assert cli.main(["doctor", "--strict"]) == 0
    assert "serving" in asked[-1] and "doctor passed" in capsys.readouterr().out


def test_the_box_image_does_not_call_a_target_it_cannot_see_on_this_box(tmp_path: Path) -> None:
    """REAL2 M-5: the host check runs the doctor in the box image, where the hospital's share is not mounted; it said
    "1 target(s), 0 off-box" while the install's finish check had shown the same share off the box."""
    share = tmp_path / "srv-share-on-the-host"  # not there in this process: the image's view of a host folder
    inp = _inp(tmp_path, TB_BACKUP_TARGETS=str(share), TB_BACKUP_ALERT_CMD="true")
    c = d.check_backup(inp)
    assert c.status == "WARN" and "not judged in the box image" in c.detail and str(share) in c.detail, c
    assert "every target is on this box" not in c.detail
    on_host = d.check_backup(d.DoctorInputs(env=inp.env, settings={}, deploy=inp.deploy, in_image=False))
    assert on_host.status == "FAIL" and "every target is on this box" in on_host.detail, on_host


def test_the_doctors_stand_in_audit_is_not_held_to_the_boxs_signed_heads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REAL2 M-5: on a box whose anchor folder holds a signed head (event 308), judge_route's throwaway audit chain
    (a new temporary folder) refused its first write with AuditAnchorBroken: "check error", a FAIL on a healthy box."""
    from tb_common import audit

    from tests.unit.test_gateway_one_role_one_model import _doctor_env

    heads = tmp_path / "anchor" / "heads"
    heads.mkdir(parents=True)
    head = {"lines": 308, "hash": "ab" * 32, "ts": "2026-11-27T11:35:53+00:00"}
    (heads / "20261127T113553+0000-000000000308.json").write_text(json.dumps(head), encoding="utf-8")
    monkeypatch.setenv(audit.ANCHOR_TARGETS_ENV, str(tmp_path / "anchor"))
    env = _doctor_env(tmp_path / "box", TB_AUDIT_ANCHOR_TARGETS=str(tmp_path / "anchor"))
    c = d.check_judge_route(d.DoctorInputs(env=env))
    assert c.status == "PASS", c
