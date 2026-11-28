"""TOL-INSTALL (TOL-1 section 2.1, the owner's CLINICAL TOLERANCE of 2026-11-28): an install's stop that protects
none of the kept classes warns and goes on on EVERY box, PRODUCTION included; the install ends running, rc 0, with
each such point an open item (``deploy/site/poc-stops.jsonl``) that ``doctor`` and the Operations page show.

The kept classes still stop on every box: their own tests (``test_poc_stops_h94.py``, ``test_poc_stops_review_h94.py``)
are unchanged; here a planted secret's mode and a planted full disk on PRODUCTION still end 1. The update and start
paths keep their rule (a PRODUCTION update without a backup is LOSS: STOPS T-U063, T-U064)."""

from __future__ import annotations

import json
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
    """Done-when (b), planted: a secret's file others can read (5) or a disk too full (2) ends 1 on PRODUCTION with
    master's FAIL lines; a point before it still warned and was listed."""
    r = _prod(tmp_path).install("--mode", "stub", "--yes", force=(force, "memcaps"), env={**DEFER, **PLANT})
    assert r.rc == 1, r.text[-4000:]
    assert r.err.splitlines()[-1] == "install: FAIL: the host check reported FAIL lines (above; docs/SECURITY.md)"
    assert "install.sh/memcaps" in r.listed_keys()


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
