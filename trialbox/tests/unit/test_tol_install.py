"""TOL-INSTALL (TOL-1 section 2.1, the owner's CLINICAL TOLERANCE of 2026-11-28): an install's stop that protects
none of the kept classes warns and goes on on EVERY box, PRODUCTION included; the install ends running, rc 0, with
each such point an open item (``deploy/site/poc-stops.jsonl``) that ``doctor`` and the Operations page show.

The kept classes still stop on every box: their own tests (``test_poc_stops_h94.py``, ``test_poc_stops_review_h94.py``)
are unchanged; here a planted secret's mode and a planted full disk on PRODUCTION still end 1. The update and start
paths keep their rule (a PRODUCTION update without a backup is LOSS: STOPS T-U063, T-U064)."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import pytest

from tests.unit.test_poc_stops_bench_h94 import Box
from tests.unit.test_poc_stops_h94 import PLANTED, PROD_SITE, RUNNING
from tools.trialbox import doctor, ops, stops

pytestmark = [pytest.mark.nodb]
GOES_ON = "install: warning (the install goes on; an open item on the Operations page): "
#: the REAL2 kit minus the audit share, the backup target and the alert route, and one host check FAIL: as the bench
#: forces them (finish-gate: the finish check's folders; backup-schedule: no alert route; memcaps; host-check)
FOUR = ("finish-gate", "backup-schedule", "memcaps", "host-check")
DEFER = {"TB_BOX_DEFER_SEAL": "1"}  # the site keys' sealing is root's (kept class 4): left to a box's apply step
PLANT = {**PLANTED, "TB_STOP_ALWAYS": "0"}  # a caller's variable never changes the rule


def _prod(tmp_path: Path) -> Box:
    box = Box(tmp_path / "prod", env=PROD_SITE + f"TB_SOURCE_DIR={tmp_path}\n")
    curl = box.tmp / "bin" / "curl"  # the console answers at its URL (the bench has no web server)
    curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    curl.chmod(0o755)
    return box


def test_a_production_install_with_four_open_items_runs_once_to_the_end(tmp_path: Path) -> None:
    """Done-when (a): ONE run, "TrialBox is running", four WARN lines, four open items, exit 0."""
    box = _prod(tmp_path)
    r = box.install("--mode", "stub", "--yes", force=FOUR, env={**DEFER, **PLANT})
    assert r.rc == 0 and RUNNING in r.out, r.text[-4000:]
    warned = [ln for ln in r.err.splitlines() if ln.startswith(GOES_ON)]
    assert len(warned) == 4, warned
    keys = r.listed_keys()
    assert {"install.sh/finish-gate", "install.sh/backup-schedule", "install.sh/memcaps"} <= keys, keys
    assert len(keys) == 4 and any(k.startswith("install.sh/fail: ") for k in keys), keys
    assert "4 items still needed" in r.out and "Operations page" in r.out, r.out[-2000:]
    assert "install: FAIL: " not in r.err and "PoC box" not in r.err


def test_a_clean_production_install_lists_nothing(tmp_path: Path) -> None:
    r = _prod(tmp_path).install("--mode", "stub", "--yes", env={**DEFER, **PLANT})
    assert r.rc == 0 and RUNNING in r.out, r.text[-4000:]
    assert r.listed_keys() == set() and "still needed" not in r.out


@pytest.mark.parametrize("force", ["env-mode", "disk-full"])
def test_on_production_a_kept_class_still_ends_1(tmp_path: Path, force: str) -> None:
    """Done-when (b), planted: a secret's file others can read (5) whose repair does not hold (the stand-in reports it
    whatever the file's mode) or a disk too full (2) ends 1 on PRODUCTION with master's FAIL lines; a point before it
    still warned and was listed."""
    r = _prod(tmp_path).install("--mode", "stub", "--yes", force=(force, "memcaps"), env={**DEFER, **PLANT})
    assert r.rc == 1, r.text[-4000:]
    assert r.err.splitlines()[-1] == "install: FAIL: the host check reported FAIL lines (above; docs/SECURITY.md)"
    assert "install.sh/memcaps" in r.listed_keys()


def test_on_production_a_secret_s_loose_mode_is_tightened_and_the_install_goes_on(tmp_path: Path) -> None:
    """TOL-INSTALL (the owner's ruling): the check names deploy/.env at 644; the install tightens it, says so in the
    check's words (no value), checks again and ends running."""
    box = _prod(tmp_path)
    r = box.install("--mode", "stub", "--yes", force=("env-loose",), env={**DEFER, **PLANT})
    assert r.rc == 0 and RUNNING in r.out, r.text[-4000:]
    assert "FAIL  .env mode 644 (want 600, root-owned) [H-94 (5)]" in r.out  # planted, and found
    said = [ln for ln in r.err.splitlines() if ln.startswith("install: repaired: .env mode 644")]
    assert len(said) == 1 and said[0].endswith(f"chmod 600 {box.deploy / '.env'}"), r.err[-3000:]
    assert stat.S_IMODE((box.deploy / ".env").stat().st_mode) == 0o600 and "install: FAIL: " not in r.err
    secrets = [v for k, _, v in (ln.partition("=") for ln in (box.deploy / ".env").read_text().splitlines())
               if re.search("PASSWORD|TOKEN", k) and len(v) >= 8]  # fmt: skip
    assert secrets and not any(v in r.text for v in secrets)


def test_on_production_a_backup_route_that_cannot_alert_is_an_open_item_and_a_schedule_that_cannot_be_written_stops(
    tmp_path: Path,
) -> None:
    """TOL-INSTALL (the owner's ruling): backup-install writes the health page as the route and installs the schedule
    (a warning, an open item, rc 0); a schedule that cannot be written stays a stop on PRODUCTION (no backup)."""
    r = _prod(tmp_path / "route").install("--mode", "stub", "--yes", force=("backup-schedule",), env={**DEFER, **PLANT})
    assert r.rc == 0 and RUNNING in r.out, r.text[-4000:]
    assert any(ln.startswith(GOES_ON + "the backup alert route given cannot carry the alerts") for ln in
               r.err.splitlines()) and r.listed_keys() == {"install.sh/backup-schedule"}, r.err[-3000:]  # fmt: skip
    r = _prod(tmp_path / "none").install("--mode", "stub", "--yes", force=("backup-schedule-write",),
                                         env={**DEFER, **PLANT})  # fmt: skip
    assert r.rc == 1 and RUNNING not in r.out, r.text[-4000:]
    assert r.err.splitlines()[-1].startswith("install: the backup schedule is not installed (above)"), r.err[-2000:]
    assert "install.sh/backup-schedule" not in r.listed_keys()


@pytest.mark.parametrize(("args", "force"), [
    (("--gpu", "rtxpro6000"), ("gpu-driver",)),  # the driver below the pinned image's minimum
    (("--gpu", "shared-quota"), ()), (("--gpu", "b200-no-mig"), ()), (("--gpu", "arm64-dgpu"), ()),
    (("--gpu", "b200"), ()),  # an unknown profile
])  # fmt: skip
def test_on_production_a_gpu_the_box_cannot_use_installs_the_coded_only_profile(
    tmp_path: Path, args: tuple[str, ...], force: tuple[str, ...]
) -> None:
    """TOL-INSTALL (the owner's ruling): the install completes with the no-GPU profile written, and says so."""
    box = _prod(tmp_path)
    r = box.install("--mode", "gpu", *args, "--yes", force=force, env={**DEFER, **PLANT})
    assert r.rc == 0 and RUNNING in r.out, r.text[-4000:]
    assert ("note reading is off on this box; coded criteria still decide; note criteria go to a person"
            in r.out), r.out[-3000:]  # fmt: skip
    env = (box.deploy / ".env").read_text(encoding="utf-8").splitlines()
    assert "COMPOSE_PROFILES=stub" in env and "TB_LLM_MODE=stub" in env, env
    assert any(ln.startswith(GOES_ON) for ln in r.err.splitlines()), r.err[-3000:]


def test_doctor_shows_each_open_item_as_a_warn_with_its_action(tmp_path: Path) -> None:
    """Done-when (c)."""
    box = _prod(tmp_path)
    box.install("--mode", "stub", "--yes", force=FOUR, env={**DEFER, **PLANT})
    lines = doctor.poc_stops(doctor.DoctorInputs(deploy=box.deploy), [])
    assert len(lines) == 4, lines
    assert all(c.status == "WARN" and c.name == "open_item" and "Action: " in c.detail for c in lines), lines


def test_the_operations_page_status_carries_the_open_items(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    stops.append(deploy, "install.sh/backup-schedule", "the backup schedule is not installed", by="install.sh")
    st = ops.snapshot(ops.Box.local(deploy, {}))
    assert [(i["key"], i["what"]) for i in st["open_items"]] == [
        ("install.sh/backup-schedule", "the backup schedule is not installed")
    ]
    assert json.loads(json.dumps(st))["open_items"]  # the status file is JSON


def test_only_the_install_takes_the_new_rule() -> None:
    """install.sh sets the rule to 1; the update, start and box scripts set it to 0 themselves: a PRODUCTION box still
    stops there (a caller's TB_STOP_ALWAYS is never read: each script assigns it)."""
    from tests.unit.test_poc_stops_h94 import ROOT

    for rel, v in (("deploy/install.sh", 1), ("tools/apply_update.sh", 0), ("deploy/settings_guard.sh", 0),
                   ("deploy/box-install.sh", 0), ("deploy/check_host.sh", 0)):  # fmt: skip
        assert f"\nTB_STOP_ALWAYS={v}; TB_STOP_KEEP=" in (ROOT / rel).read_text(encoding="utf-8"), rel


@pytest.mark.parametrize(("args", "force", "last"), [
    (("--environment", "PROD"), (), "install: the environment 'PROD' (--environment) is not DEV"),
    ((), ("pre-start",), "install: a start-up step of this release failed (pre-start above)"),
])  # fmt: skip
def test_on_production_a_kept_point_still_stops(
    tmp_path: Path, args: tuple[str, ...], force: tuple[str, ...], last: str
) -> None:
    """A point whose STOPS row is a HARD STOP, or an ASK-ONCE not built yet, keeps the old rule on PRODUCTION: here
    T-I012 (an unknown environment, at second 0) and T-I120 (pre-start), master's words, nothing listed."""
    r = _prod(tmp_path).install(*args, "--mode", "stub", "--yes", force=force, env={**DEFER, **PLANT})
    assert r.rc == 1 and r.err.splitlines()[-1].startswith(last), r.text[-3000:]
    assert r.listed_keys() == set()
