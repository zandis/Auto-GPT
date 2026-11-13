"""The cloud driver after the 2026-11-13 launch that met a spot STOCKOUT: a --no-wait launch whose start was refused
exited 0 (B1), the start was not tried again (B3), and the refusal over an uncollected run did not say what to do
when that run was collected in another folder (B4). Each test failed before its fix. The cloud is the rehearsal's
own fake gcloud (tests/rehearsal/driver-shims/gcloud) over a temporary state folder: nothing here touches GCP."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tools import complete_run as cr

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
SHIMS = ROOT / "tests" / "rehearsal" / "driver-shims"
PY = str(ROOT / ".venv" / "bin" / "python")
LAUNCH = ("--patients", "500", "--only", "scenario-it-dump", "--no-wait")


def _state(tmp: Path, status: str = "TERMINATED") -> Path:
    s = tmp / "state"
    for d in ("metadata", "knobs/metadata", "bucket/tb-runs", "secrets/tb-gpu-door", "units"):
        (s / d).mkdir(parents=True, exist_ok=True)
    (s / "status").write_text(status + "\n", encoding="utf-8")
    return s


def _knob(tmp: Path, name: str, n: int) -> None:
    (tmp / "state" / "knobs" / name).write_text(str(n), encoding="utf-8")


def _env(tmp: Path, *, docker_ok: bool = False, **kw: str) -> dict[str, str]:
    (tmp / "gc").mkdir(exist_ok=True)
    path = [str(SHIMS)]
    if docker_ok:  # a VM's boot that succeeds: the start answers, nothing boots
        b = tmp / "bin"
        b.mkdir(exist_ok=True)
        (b / "docker").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (b / "docker").chmod(stat.S_IRWXU)
        path.insert(0, str(b))
    env = dict(os.environ, PATH=":".join([*path, os.environ["PATH"]]), CLOUDSDK_CONFIG=str(tmp / "gc"),
               TB_SA_KEY_FILE="/dev/null", TB_COMPLETE_DIR=str(tmp / "out"), PY=PY, GC_TIMEOUT_S="20",
               TB_REH_STATE=str(tmp / "state"), TB_REH_CONTAINER="tb-no-such-container", TB_DOOR_DIRECT="1",
               TB_LOCK_DIR=str(tmp / "locks"), TB_SETTLE_S="5", TB_START_RETRY_SECONDS="0", **kw)  # fmt: skip
    for k in ("TB_ZONES", "TB_BUCKET", "TB_RUN_ID", "TB_DRIVER_LOCK_HELD", "TB_DRIVER_CHILD", "TB_RUNS_DIR",
              "TB_START_RETRIES", "TB_PROVISIONING"):  # fmt: skip
        if k not in kw:
            env.pop(k, None)
    return env


def _run(env: dict[str, str], *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          check=False, timeout=timeout)  # fmt: skip


def _starts(tmp: Path) -> int:
    p = tmp / "state" / "gcloud.log"
    log = p.read_text(encoding="utf-8") if p.exists() else ""
    return sum(1 for ln in log.splitlines() if " gcloud compute instances start " in ln)


def _said(r: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    return r.stdout[-2000:], r.stderr[-2000:]


# ---------------------------------------------------------------- B1: a refused start is a failed --no-wait launch
def test_a_no_wait_launch_whose_start_is_refused_exits_non_zero(tmp_path: Path) -> None:
    """2026-11-13: "the start failed: stopping it, its door destroyed ... VM 1 ended with an error", and exit 0."""
    _state(tmp_path)
    _knob(tmp_path, "start-fail", 1)
    r = _run(_env(tmp_path, TB_RUN_ID="B1", TB_START_RETRIES="0"), *LAUNCH)
    assert "the start failed: stopping it, its door destroyed" in r.stderr, _said(r)
    assert "VM 1 ended with an error" in r.stderr and r.returncode != 0, (r.returncode, *_said(r))
    assert (tmp_path / "out" / "shard-1" / "state").read_text(encoding="utf-8").strip() == "noresults"


def test_a_no_wait_launch_that_started_exits_zero(tmp_path: Path) -> None:
    _state(tmp_path)
    r = _run(_env(tmp_path, docker_ok=True, TB_RUN_ID="B1OK", TB_BUCKET="gs://tb-runs"), *LAUNCH)
    assert r.returncode == 0 and "started tb-gpu-sim" in r.stdout, (r.returncode, *_said(r))


# ---------------------------------------------------------------- B3: a stockout is tried again, nothing else is
def test_a_start_refused_for_a_stockout_is_tried_again(tmp_path: Path) -> None:
    _state(tmp_path)
    _knob(tmp_path, "start-fail", 2)  # the first two starts meet a stockout, the third starts
    r = _run(_env(tmp_path, docker_ok=True, TB_RUN_ID="B3", TB_BUCKET="gs://tb-runs"), *LAUNCH)
    assert r.returncode == 0 and "started tb-gpu-sim" in r.stdout, (r.returncode, *_said(r))
    assert _starts(tmp_path) == 3 and "refused for a stockout: retry 2 of 3 in 0 s" in r.stderr, _said(r)
    assert "the start failed" not in r.stderr


def test_the_stockout_retries_end(tmp_path: Path) -> None:
    _state(tmp_path)
    _knob(tmp_path, "start-fail", 9)
    r = _run(_env(tmp_path, docker_ok=True, TB_RUN_ID="B3END", TB_BUCKET="gs://tb-runs", TB_START_RETRIES="2"),
             *LAUNCH)  # fmt: skip
    assert r.returncode != 0 and _starts(tmp_path) == 3, (r.returncode, *_said(r))
    assert "refused for a stockout 3 time(s) (TB_START_RETRIES=2)" in r.stderr and "the start failed" in r.stderr


def test_another_refusal_is_not_tried_again(tmp_path: Path) -> None:
    _state(tmp_path)
    _knob(tmp_path, "start-fail-other", 1)
    r = _run(_env(tmp_path, docker_ok=True, TB_RUN_ID="B3Q", TB_BUCKET="gs://tb-runs"), *LAUNCH)
    assert r.returncode != 0 and _starts(tmp_path) == 1, (r.returncode, *_said(r))
    assert "QUOTA_EXCEEDED" in r.stderr and "retry" not in r.stderr and "the start failed" in r.stderr


def test_a_bad_retry_setting_refuses_before_anything_changes(tmp_path: Path) -> None:
    _state(tmp_path)
    r = _run(_env(tmp_path, docker_ok=True, TB_RUN_ID="B3X", TB_START_RETRIES="three"), *LAUNCH)
    assert "TB_START_RETRIES must be a whole number from 0" in r.stderr and r.returncode != 0, _said(r)
    log = (tmp_path / "state" / "gcloud.log").read_text(encoding="utf-8")
    assert "instances set-scheduling" not in log and "instances start" not in log


def test_the_retry_settings_and_the_stockout_words() -> None:
    assert cr.start_retry({}) == (cr.START_RETRIES_DEFAULT, cr.START_RETRY_SECONDS_DEFAULT) == (3, 240)
    assert cr.start_retry({"TB_START_RETRIES": "0", "TB_START_RETRY_SECONDS": " 30 "}) == (0, 30)
    for bad in ("-1", "2.5", "x"):
        with pytest.raises(ValueError, match="whole number"):
            cr.start_retry({"TB_START_RETRY_SECONDS": bad})
    for text in ("ERROR: (gcloud.compute.instances.start) ZONE_RESOURCE_POOL_EXHAUSTED",
                 "The zone 'projects/p/zones/asia-east1-a' does not have enough resources available to fulfill the "
                 "request. '(resource type:compute)'.", "code: STOCKOUT", "ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS"):  # fmt: skip
        assert cr.is_stockout(text), text
    for text in ("QUOTA_EXCEEDED: Quota 'GPUS_ALL_REGIONS' exceeded", "PERMISSION_DENIED", "", "not TERMINATED"):
        assert not cr.is_stockout(text), text
    from tb_common.config import DECLARED

    assert DECLARED["TB_START_RETRIES"].default == "3" and DECLARED["TB_START_RETRY_SECONDS"].default == "240"


# ---------------------------------------------------------------- B4: the refusal names --discard-previous
def test_the_refusal_over_an_uncollected_run_names_discard_previous_for_another_folder(tmp_path: Path) -> None:
    import json

    _state(tmp_path)
    vm = {"name": "tb-gpu-sim", "tags": {"items": ["tb-gpu-door"]},
          "networkInterfaces": [{"network": "projects/rehearsal/global/networks/default"}],
          "serviceAccounts": [{"email": "tb-gpu@rehearsal.iam.gserviceaccount.com",
                               "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}],
          "metadata": {"items": [{"key": "tb-run-id", "value": "OLD-s1"}]}}  # fmt: skip
    (tmp_path / "state" / "vm.json").write_text(json.dumps(vm), encoding="utf-8")
    r = _run(_env(tmp_path, TB_RUNS_DIR=str(tmp_path / "runs"), TB_RUN_ID="NEW"), *LAUNCH)
    assert r.returncode == 3 and "holds run OLD-s1" in r.stderr, _said(r)
    assert "collected in another folder" in r.stderr and f"looks in {tmp_path / 'runs'}" in r.stderr
    assert "--discard-previous is the way" in r.stderr and _starts(tmp_path) == 0


def test_every_apt_on_the_vm_waits_for_the_dpkg_lock_not_only_the_scripts_own() -> None:
    """Run 20261113T072836Z: playwright's own apt-get (install --with-deps) met unattended-upgrades' lock and the VM
    ended at TB-SETUP-FAILED. The wait is an apt configuration file, written before anything installs."""
    vm = (Path(__file__).resolve().parents[2] / "deploy/gcp/complete-run-vm.sh").read_text(encoding="utf-8")
    conf = "echo 'DPkg::Lock::Timeout \"600\";' >/etc/apt/apt.conf.d/99tb-lock-timeout"
    assert conf in vm
    assert vm.index(conf) < vm.index('"${APT[@]}" update') < vm.index("npx playwright install --with-deps")
