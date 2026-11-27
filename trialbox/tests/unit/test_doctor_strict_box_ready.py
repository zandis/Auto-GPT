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
    pub.parent.mkdir()
    pub.write_text("age1 synthetic public key for a test\n", encoding="utf-8")
    assert d.check_backup_key(inp).status == "PASS"
    pub.write_text("", encoding="utf-8")  # an empty file is no key
    assert d.check_backup_key(inp).status == "FAIL"


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
    c = d.check_site_mapping(_inp(tmp_path))
    assert c.status == "FAIL" and "no data_source.mapping" in c.detail


def test_mail_relay_given_or_no_mail_accepted_by_name(tmp_path: Path) -> None:
    c = d.check_mail_relay(_inp(tmp_path))
    assert c.status == "FAIL" and "TB_NO_MAIL_ACCEPTED_BY" in c.detail and "SMTP_HOST" in c.detail
    assert d.check_mail_relay(_inp(tmp_path, SMTP_HOST="relay.example.org")).status == "PASS"
    named = d.check_mail_relay(_inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead", TB_NO_MAIL_ACCEPTED_ON="2026-11-27"))
    assert named.status == "PASS" and "IT lead" in named.detail
    assert d.check_mail_relay(_inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead")).status == "FAIL"  # no day
    bad_day = _inp(tmp_path, TB_NO_MAIL_ACCEPTED_BY="IT lead", TB_NO_MAIL_ACCEPTED_ON="soon")
    assert d.check_mail_relay(bad_day).status == "FAIL"


def _canary(folder: Path, **over: Any) -> None:
    rep = {"ok": True, "pair": {"decided_wrong": 0}, "problems": [], "at_epoch": time.time(), **over}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "selftest.json").write_text(json.dumps(rep), encoding="utf-8")


def test_selftest_row_needs_a_recent_passing_pair_canary(tmp_path: Path) -> None:
    orch = tmp_path / "orch"
    inp = _inp(tmp_path, TB_ORCH_DIR=str(orch))
    c = d.check_selftest(inp)
    assert c.status == "FAIL" and "no canary result" in c.detail and "trialbox selftest" in c.detail
    _canary(orch, ok=False, problems=["judge failed the canary (18/54)"])  # the R1 box (E2E P-08)
    c = d.check_selftest(inp)
    assert c.status == "FAIL" and "18/54" in c.detail
    _canary(orch, at_epoch=time.time() - 80 * 3600)
    assert d.check_selftest(inp).status == "FAIL"
    _canary(orch, pair=None)
    assert d.check_selftest(inp).status == "FAIL"
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
