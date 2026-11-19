"""H-53: the 48 GB measuring run's decisions and its driver, on stand-ins (no gcloud call, no VM, no cost):
tools/measure48_vm.py (the estimate's arithmetic, the stop-line gate, the ladder, the disk guard, the upload
allow-list and its redaction, the quota with HDB_TOTAL_GB, the collect summary) and deploy/gcp/measure48-run.sh
(--estimate with no gcloud, the kept VMs refused, --preflight and a --dry-run launch against a stand-in gcloud)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "deploy" / "gcp" / "measure48-run.sh"
_spec = importlib.util.spec_from_file_location("measure48_vm", ROOT / "tools" / "measure48_vm.py")
assert _spec and _spec.loader
m48 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m48)
PAGE = ROOT / "docs" / "plan" / "measurements" / "48gb-measuring-run-2026-11-19.md"


# ---------------------------------------------------------------- the estimate
def test_price_is_complete_runs() -> None:
    assert m48.PRICE_PER_HOUR == complete_run.PRICE_PER_HOUR
    assert m48.ON_DEMAND_PRICE_PER_HOUR == complete_run.ON_DEMAND_PRICE_PER_HOUR


def test_the_estimate_is_h47s_with_the_smaller_disk() -> None:
    e = m48.estimate(with_o=True)
    assert (e["low_h"], e["estimate_h"], e["high_h"]) == (1.1, 2.3, 5.62)
    assert (e["low_usd"], e["estimate_usd"], e["high_usd"]) == (3.01, 6.3, 15.4)
    assert e["stop_line_h"] == 3.5 and e["stop_line_usd"] == 9.45
    assert e["cap_usd"] == 10.96
    assert e["disk_usd_at_cap"] == 0.05  # 100 GB x US$0.093 a GiB-month x 4 h / 730 h
    assert e["worst_case_usd"] == 11.01
    assert e["worst_case_on_demand_usd"] == 32.88
    assert e["vm_stop_line_min"] == 204  # 3.5 h less stage 1's 0.10 h
    n = m48.estimate(with_o=False)
    assert (n["low_h"], n["estimate_h"], n["high_h"], n["estimate_usd"]) == (1.04, 2.18, 5.37, 5.97)
    assert n["stop_line_h"] == 3.3 and m48.vm_stop_line_min(False) == 192
    assert round(m48.estimate(disk_gb=250)["disk_usd_at_cap"], 2) == 0.13  # H-47's 250 GB figure


def test_the_stages_are_the_pages_table() -> None:
    text = PAGE.read_text(encoding="utf-8")
    for key, _what, lo, est, hi in m48.STAGES:
        row = next((x for x in text.splitlines() if x.startswith(f"| {key}. ") or x.startswith(f"| {key} ")), None)
        if key == "O":
            row = next(x for x in text.splitlines() if x.startswith("| O. OPTIONAL"))
        assert row, key
        assert f"| {lo:.2f} h | {est:.2f} h | {hi:.2f} h |" in row, (key, row)


# ---------------------------------------------------------------- the gate
LINE = 204 * 60


@pytest.mark.parametrize(("left_h", "o", "nine"), [(1.0, True, True), (0.5, True, False), (0.2, False, False)])
def test_o_and_step_9_against_the_line(left_h: float, o: bool, nine: bool) -> None:
    used = LINE - left_h * 3600
    assert m48.gate("O", used, LINE)[0] is o
    assert m48.gate("9", used, LINE)[0] is nine  # step 9 (0.80 h) is dropped before O (0.25 h)


def test_the_screens_tools_need_the_screens_time_too() -> None:
    used = LINE - 0.6 * 3600
    assert m48.gate("7", used, LINE)[0] is True
    ok, why = m48.gate("7", used, LINE, ["8"])
    assert not ok and "stage 7 + 8 not started" in why and "0.90 h" in why


def test_the_gate_is_inclusive_at_the_line() -> None:
    assert m48.gate("6", LINE - 0.8 * 3600, LINE)[0] is True
    assert m48.gate("6", LINE - 0.8 * 3600 + 1, LINE)[0] is False


# ---------------------------------------------------------------- the ladder
@pytest.mark.parametrize(("tried", "nxt"), [
    ([], "pair-32k"), ([("pair-32k", 1)], "pair-16k"), ([("pair-32k", 1), ("pair-16k", 1)], "judge-alone"),
    ([("pair-32k", 1), ("pair-16k", 1), ("judge-alone", 1)], ""), ([("pair-32k", 0)], ""),
    ([("pair-32k", 2)], ""), ([("pair-32k", 1), ("pair-16k", 130)], ""),
])  # fmt: skip
def test_ladder(tried: list[tuple[str, int]], nxt: str) -> None:
    assert m48.ladder_next(tried)[0] == nxt


def test_ladder_reasons() -> None:
    assert m48.ladder_next([("pair-32k", 1)])[1] == "pair-32k did not start"
    assert "refused, broke or stopped" in m48.ladder_next([("pair-32k", 2)])[1]
    assert m48.ladder_next([("pair-32k", 0)])[1] == "pair-32k started and is kept"


# ---------------------------------------------------------------- the disk
def test_disk_guard() -> None:
    ok, why = m48.disk_ok("/", 30.0, free_bytes=29_000_000_000)
    assert not ok and "DISK-SHORT" in why and "29.0 GB free" in why
    assert m48.disk_ok("/", 30.0, free_bytes=31_000_000_000)[0]


def test_the_disk_budget_fits_100_gb() -> None:
    """The page's peak (section 'Unattended'): what is on the disk at the engine pull, the largest step, with the
    build cache freed, plus the guard's own room for it, stays under the 100 GB disk."""
    on_disk_before_engine = 3.0 + 2.0 + 0.05 + 27.9 + 3.7 + 2.0  # OS, driver+Docker, source, weights, images, bases
    assert on_disk_before_engine + m48.NEED_GB["engine"] < 97  # the root file system of a 100 GB disk
    peak = on_disk_before_engine + 23.4 + m48.NEED_GB["tools"] + m48.NEED_GB["screen"]
    assert peak < 97


# ---------------------------------------------------------------- what may leave the VM
@pytest.mark.parametrize("rel", [
    "raw/poc-up.txt", "records/raw/x.json", "deploy/.env", "records/x.env", "records/secrets/model/vllm.env",
    "records/tb-dgpu48-pair-32k/down.json", "records/tb-dgpu48-pair-32k/verifier-flag.yml",
    "records/tb-dgpu48-pair-32k/.serving_config.pair-32k.raw.json", "records/poc-up.txt", "logs/../raw/poc-up.txt",
    "records/screen/parts/hospital-ja.debug.txt", "records/screen/work/answers.json", "records/vm.key",
    "records/tb-dgpu48-pair-32k/key.json", "records/.hidden/measure.x.json",
])  # fmt: skip
def test_never_uploaded(rel: str) -> None:
    assert not m48.allowed(rel)


@pytest.mark.parametrize("rel", [
    "steps.json", "decisions.json", "disk.jsonl", "records/o0-card.csv", "records/plan.txt", "records/ballast.log",
    "records/tb-dgpu48-pair-32k/measure.pair-32k.json", "records/tb-dgpu48-pair-16k/canary.pair-16k.json",
    "records/tb-dgpu48-pair-32k/serving_config.dgpu48.pair-32k.json", "records/screen-during.json",
    "records/screen/parts/hospital-ja.json", "records/canary-verifier-flag-diff.json", "logs/s08-ladder.log",
])  # fmt: skip
def test_uploaded(rel: str) -> None:
    assert m48.allowed(rel)


def test_pack_masks_the_key_and_redacts_logs(tmp_path: Path) -> None:
    run, out = tmp_path / "run", tmp_path / "up"
    key = "sk-0123456789abcdefXYZ"
    (run / "logs").mkdir(parents=True)
    (run / "records" / "tb-dgpu48-pair-32k").mkdir(parents=True)
    (run / "raw").mkdir()
    (run / "raw" / "poc-up.txt").write_text("password: hunter22hunter22\n")
    (run / "logs" / "s08.log").write_text(f"start\ncalling with {key}\nadmin password is x\nkv_cache_tokens 9\n")
    rec = {"engine_log": {"judge": {"kv_cache_tokens": 98304}}, "cmd": f"--api-key {key}"}
    (run / "records" / "tb-dgpu48-pair-32k" / "measure.pair-32k.json").write_text(json.dumps(rec))
    (run / "records" / "tb-dgpu48-pair-32k" / "down.json").write_text(key)
    env = tmp_path / "vllm.env"
    env.write_text(f'VLLM_API_KEY="{key}"\n')
    took = m48.pack(run, out, m48.read_masks(m48.mask_files([env], [])))
    assert sorted(took) == ["logs/s08.log", "records/tb-dgpu48-pair-32k/measure.pair-32k.json"]
    log = (out / "logs" / "s08.log").read_text()
    assert key not in log and "calling with [masked]" in log and "password" not in log and "[redacted line]" in log
    got = json.loads((out / "records" / "tb-dgpu48-pair-32k" / "measure.pair-32k.json").read_text())
    assert got["engine_log"]["judge"]["kv_cache_tokens"] == 98304 and key not in got["cmd"]


def test_mask_dir_reads_every_secret_file(tmp_path: Path) -> None:
    d = tmp_path / "secrets" / "model"
    d.mkdir(parents=True)
    (d / "vllm.env").write_text("VLLM_API_KEY=aaaaaaaaaaaaaaaa\n")
    (tmp_path / "secrets" / "admin").write_text("bbbbbbbbbbbbbbbb\n")
    masks = m48.read_masks(m48.mask_files([], [tmp_path / "secrets"]))
    assert "aaaaaaaaaaaaaaaa" in masks and "bbbbbbbbbbbbbbbb" in masks


# ---------------------------------------------------------------- the quota
def _quota_dir(tmp: Path, hdb: tuple[float, float] | None, rows: int = 0) -> Path:
    """``rows``: the region's list padded to that many rows with synthetic metrics (H-59: the integrator's asia-east1
    list had 113 rows and no HDB_TOTAL_GB)."""
    q = tmp / "q"
    q.mkdir()
    (q / "project.json").write_text(json.dumps({"quotas": [{"metric": "GPUS_ALL_REGIONS", "limit": 2, "usage": 0}]}))
    quotas = [{"metric": "CPUS", "limit": 200, "usage": 0}, {"metric": "PREEMPTIBLE_CPUS", "limit": 0, "usage": 0}]
    if hdb:
        quotas.append({"metric": "HDB_TOTAL_GB", "limit": hdb[0], "usage": hdb[1]})
    quotas += [{"metric": f"SYNTHETIC_METRIC_{i:03d}", "limit": 10, "usage": 0} for i in range(rows - len(quotas))]
    (q / "region-asia-east1.json").write_text(json.dumps({"quotas": quotas}))
    return q


def test_quota_hdb_100_fits(tmp_path: Path) -> None:
    assert m48.quota(_quota_dir(tmp_path, (500, 400)), "asia-east1-a", 100) == []


def test_quota_hdb_short_is_refused(tmp_path: Path) -> None:
    bad = m48.quota(_quota_dir(tmp_path, (500, 401)), "asia-east1-a", 100)
    assert bad and "HDB_TOTAL_GB" in bad[0] and "free 99 GB" in bad[0]
    (tmp_path / "b").mkdir()
    assert m48.quota(_quota_dir(tmp_path / "b", (500, 400)), "asia-east1-a", 250)  # the sheet's 250 GB: refused


ABSENT = (
    "quota: asia-east1: HDB_TOTAL_GB is not in the region's quota list (113 rows), so the 100 GB disk quota "
    "cannot be checked beforehand; the create call itself refuses if it is short (--hdb-free-gb N gives the "
    "free figure by hand)"
)


def test_quota_hdb_absent_is_said_and_goes_on(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """H-59: a well-formed list of 113 rows with no HDB_TOTAL_GB row: said in one line, the quota step passes."""
    q = _quota_dir(tmp_path, None, rows=113)
    assert len(json.loads((q / "region-asia-east1.json").read_text())["quotas"]) == 113
    bad, notes = m48.quota_check(q, "asia-east1-a", 100)
    assert bad == [] and len(notes) == 1
    assert m48.main(["quota", str(q), "--zone", "asia-east1-a", "--disk-gb", "100"]) == 0
    out = capsys.readouterr()
    assert out.out.splitlines()[0] == ABSENT and out.err == ""
    assert "its 100 GB disk: not checked (above)" in out.out


@pytest.mark.parametrize(("given", "ok"), [("100", True), ("250.5", True), ("99", False), ("0", False)])
def test_quota_hdb_free_by_hand_is_checked_like_a_row(tmp_path: Path, given: str, ok: bool) -> None:
    """H-59: --hdb-free-gb N, checked against the need exactly like a listed row (the row absent)."""
    q = _quota_dir(tmp_path, None, rows=113)
    rc = m48.main(["quota", str(q), "--zone", "asia-east1-a", "--disk-gb", "100", "--hdb-free-gb", given])
    assert rc == (0 if ok else 4)
    assert bool(m48.quota(q, "asia-east1-a", 100, float(given))) is not ok


def test_quota_hdb_by_hand_does_not_hide_a_short_row(tmp_path: Path) -> None:
    assert m48.quota(_quota_dir(tmp_path, (500, 450)), "asia-east1-a", 100, 300.0)


@pytest.mark.parametrize("given", ["abc", "", "-5", "nan", "inf"])
def test_quota_hdb_free_by_hand_not_a_number_is_refused(tmp_path: Path, given: str) -> None:
    q = _quota_dir(tmp_path, None, rows=113)
    with pytest.raises(SystemExit) as exc:
        m48.main(["quota", str(q), "--zone", "asia-east1-a", "--hdb-free-gb", given])
    assert exc.value.code == 2


@pytest.mark.parametrize("region_text", ["", "ERROR: (gcloud) not json", "[]", '{"quotas": "x"}', '{"quotas": [1]}',
                                         '{"name": "asia-east1"}'])  # fmt: skip
def test_quota_unparseable_output_still_refuses(tmp_path: Path, region_text: str) -> None:
    """H-59: only a well-formed list without the row goes on; output that is not a quota list refuses."""
    q = _quota_dir(tmp_path, None, rows=113)
    (q / "region-asia-east1.json").write_text(region_text)
    assert m48.quota(q, "asia-east1-a", 100)
    assert m48.main(["quota", str(q), "--zone", "asia-east1-a", "--hdb-free-gb", "200"]) == 4


def test_quota_missing_output_still_refuses(tmp_path: Path) -> None:
    q = _quota_dir(tmp_path, (500, 400))
    (q / "project.json").unlink()
    assert m48.quota(q, "asia-east1-a", 100)


# ---------------------------------------------------------------- the collect's summary
def test_summary(tmp_path: Path) -> None:
    d = tmp_path
    m = d / "records" / "tb-dgpu48-pair-32k"
    m.mkdir(parents=True)
    (m / "measure.pair-32k.json").write_text(
        json.dumps(
            {
                "option": "pair-32k",
                "started": True,
                "outcome": "BY BALLAST: ok",
                "card_peak_mib": 45128,
                "ballast": {"free_at_peak_mib": 4012},
                "engine_log": {"judge": {"kv_cache_tokens": 98304}},
            }
        )
    )
    (m / "canary.pair-32k.json").write_text(json.dumps({"models": [{"role": "judge", "cases": 54, "seconds": 108}]}))
    (d / "records" / "screen-during.json").write_text(json.dumps({"wall_seconds": 700.5, "exit_code": 0}))
    (d / "records" / "canary-verifier-flag-diff.json").write_text(json.dumps({"verdicts_differ": 3, "exact": True,
                                                                             "runs": {}}))  # fmt: skip
    (d / "steps.json").write_text(json.dumps({"ended": "complete", "used_s": 8000, "steps": [{"step": "s01-host"}]}))
    (d / "decisions.json").write_text(json.dumps({"kept": "pair-32k", "decisions": [{"what": "O", "choice": "run"}]}))
    s = m48.summary(d, ROOT)
    assert s["kept"] == "pair-32k"
    o = s["options"]["pair-32k"]
    assert o["free_at_peak_mib"] == 4012 and o["seconds_per_judged_call"] == 2.0
    assert o["sequences"]["judge"] == {"kv_cache_tokens": 98304, "max_len": 32768, "full_context_sequences": 3}
    assert s["screen"]["wall_seconds"] == 700.5 and s["o"]["verdicts_differ"] == 3


# ---------------------------------------------------------------- the driver
GCLOUD = """#!/bin/bash
echo "gcloud $*" >> "$M48_CALLS"
case "$*" in
  "auth print-access-token") exit 0 ;;
  "compute instances describe"*"--format=json"*) [ -f "${M48_DESCRIBE:-/nonexistent}" ] || exit 1; cat "$M48_DESCRIBE" ;;
  "compute instances describe"*) [ ! -f "${M48_CREATE_LEAVES:-/nonexistent}" ] || { echo STAGING; exit 0; }
    [ -n "${M48_STATUS:-}" ] || { echo "ERROR: not found" >&2; exit 1; }; echo "$M48_STATUS" ;;
  "compute instances delete"*|"compute instances stop"*|"compute instances start"*|"compute instances set-scheduling"*) exit 0 ;;
  "storage rsync"*) [ -d "${M48_GCS:-/nonexistent}" ] && cp -a "$M48_GCS/." "$5/" ; exit 0 ;;
  "compute project-info describe"*) cat "$M48_Q/project.json" ;;
  "compute regions describe"*) [ -z "${M48_REGION_FAIL:-}" ] || { echo "ERROR: (gcloud) denied" >&2; exit 1; }
    cat "$M48_Q/region-asia-east1.json" ;;
  "storage ls"*|"storage cp"*) exit 0 ;;
  "compute instances create"*) [ -z "${M48_CREATE_LEAVES:-}" ] || touch "$M48_CREATE_LEAVES"
    [ -z "${M48_CREATE_ERR:-}" ] || { echo "$M48_CREATE_ERR" >&2; exit 1; }; exit 0 ;;
  *) echo "stand-in gcloud: not expected: $*" >&2; exit 3 ;;
esac
"""


def _driver(
    tmp: Path, *args: str, hdb: tuple[float, float] | None = (500, 400), rows: int = 0, **extra: str
) -> subprocess.CompletedProcess[str]:
    b = tmp / "bin"
    b.mkdir(exist_ok=True)
    (b / "gcloud").write_text(GCLOUD)
    (b / "gcloud").chmod(0o755)
    if not (tmp / "quota").exists():
        (tmp / "quota").mkdir()
        _quota_dir(tmp / "quota", hdb, rows)
    q = tmp / "quota" / "q"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUNBUFFERED", "TB_SA_KEY_FILE", "GC_DRY")}
    env.update({"PATH": f"{b}:{env['PATH']}", "TB_BUCKET": "gs://bk", "TB_M48_DIR": str(tmp / "local"),
                "M48_CALLS": str(tmp / "calls.txt"), "M48_Q": str(q), "TB_RUN_ID": "m48-test", **extra})  # fmt: skip
    return subprocess.run(["bash", str(DRIVER), *args], env=env, capture_output=True, text=True, timeout=300,
                          check=False, cwd=ROOT)  # fmt: skip


def test_driver_estimate_makes_no_gcloud_call(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--estimate")
    assert r.returncode == 0, r.stderr
    assert "US$6.30" in r.stdout and "stop line: 3.5 h" in r.stdout and "worst case US$11.01" in r.stdout
    assert not (tmp_path / "calls.txt").exists()


@pytest.mark.parametrize(
    "vm", ["tb-gpu-sim", "tb-demo-vm", "tb-preview-vm", "tb-steps-vm", "tb-gpu-sim-2", "tb-gpu-sim2", "tb-demo-vm-2",
           "tb-h47", "tb-h47-", "tb-h53-X", "my-vm"],
)  # fmt: skip
def test_driver_refuses_the_kept_vms(tmp_path: Path, vm: str) -> None:
    r = _driver(tmp_path, "--preflight", vm)
    assert r.returncode == 2 and "not this run's VM name" in r.stderr
    assert not (tmp_path / "calls.txt").exists()


def test_driver_preflight_reads_only(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--preflight")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "preflight: the launch's checks passed" in r.stdout
    assert "quota: one Spot RTX PRO 6000 VM in asia-east1-a and its 100 GB disk fit" in r.stdout
    calls = (tmp_path / "calls.txt").read_text()
    assert "instances create" not in calls and "storage cp" not in calls
    assert (tmp_path / "local" / "m48-test" / "src.tgz").is_file()


def test_driver_preflight_refuses_a_short_disk_quota(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--preflight", hdb=(500, 450))
    assert r.returncode == 4 and "HDB_TOTAL_GB" in r.stderr


def test_driver_preflight_goes_on_without_the_hdb_row(tmp_path: Path) -> None:
    """H-59: the integrator's preflight (113 rows, no HDB_TOTAL_GB) refused with exit 4; now it says so and goes on."""
    r = _driver(tmp_path, "--preflight", hdb=None, rows=113)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ABSENT in r.stdout.splitlines() and "preflight: the launch's checks passed" in r.stdout
    assert "instances create" not in (tmp_path / "calls.txt").read_text()


@pytest.mark.parametrize(("given", "rc"), [("100", 0), ("50", 4)])
def test_driver_preflight_takes_the_free_figure_by_hand(tmp_path: Path, given: str, rc: int) -> None:
    r = _driver(tmp_path, "--preflight", "--hdb-free-gb", given, hdb=None, rows=113)
    assert r.returncode == rc, r.stdout + r.stderr
    assert f"free {given} GB (given by hand, --hdb-free-gb)" in r.stdout + r.stderr


def test_driver_refuses_a_free_figure_that_is_not_a_number(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--preflight", "--hdb-free-gb", "lots", hdb=None, rows=113)
    assert r.returncode == 2 and "--hdb-free-gb takes a number of GB" in r.stderr
    assert not (tmp_path / "calls.txt").exists()


def test_driver_preflight_refuses_when_gcloud_fails(tmp_path: Path) -> None:
    """H-59: a failed regions describe is not "the row is absent": refused."""
    r = _driver(tmp_path, "--preflight", hdb=None, rows=113, M48_REGION_FAIL="1")
    assert r.returncode == 4 and "regions describe asia-east1 failed" in r.stderr
    assert "preflight: the launch's checks passed" not in r.stdout


def test_driver_preflight_refuses_unparseable_output(tmp_path: Path) -> None:
    (tmp_path / "quota").mkdir()
    (_quota_dir(tmp_path / "quota", None, 113) / "region-asia-east1.json").write_text("<html>error</html>")
    r = _driver(tmp_path, "--preflight")
    assert r.returncode == 4 and "not readable" in r.stderr


def test_driver_launch_ends_cleanly_when_the_create_is_refused(tmp_path: Path) -> None:
    """H-59: the row absent, the launch goes on to the create call; the create is refused for the disk quota: the
    run ends with gcloud's reason shown, exit 5, and the driver has checked that no VM by the name is left."""
    err = "ERROR: (gcloud.compute.instances.create) Quota 'HDB_TOTAL_GB' exceeded. Limit: 500.0 in region asia-east1."
    r = _driver(tmp_path, hdb=None, rows=113, M48_CREATE_ERR=err)
    assert r.returncode == 5, r.stdout + r.stderr
    assert "Quota 'HDB_TOTAL_GB' exceeded" in r.stderr
    assert "the create call was refused (its reason above): no VM or disk was made" in r.stderr
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    i = next(n for n, c in enumerate(calls) if "compute instances create" in c)
    assert any("compute instances describe tb-h47-48gb" in c for c in calls[i + 1 :])  # checked afterwards
    assert not any(w in c for c in calls for w in ("instances start", "instances delete", "disks create"))
    assert "started on" not in r.stdout


def test_driver_launch_create_failed_but_a_vm_is_there(tmp_path: Path) -> None:
    """A create that fails yet leaves a VM (a time-out, say) is not reported as "nothing made": the delete is named."""
    r = _driver(tmp_path, hdb=None, rows=113, M48_CREATE_ERR="ERROR: timed out",
                M48_CREATE_LEAVES=str(tmp_path / "left"))  # fmt: skip
    assert r.returncode == 5, r.stdout + r.stderr
    assert "a VM tb-h47-48gb is there (STAGING)" in r.stderr and "--delete m48-test" in r.stderr
    assert "no VM or disk was made" not in r.stderr


def test_driver_dry_run_launch(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    create = next(x for x in r.stdout.splitlines() if "compute instances create" in x)
    for want in ("tb-h47-48gb", "--zone asia-east1-a", "--machine-type g4-standard-48", "--provisioning-model SPOT",
                 "--instance-termination-action STOP", "--max-run-duration 4h", "--boot-disk-size 100GB",
                 "--scopes storage-rw", "startup-script=", "measure48-vm.sh", "tb-m48-helper=",
                 "tb-stop-line-minutes=204", "tb-cap-minutes=240", "tb-o=1", "tb-src=gs://bk/m48runs/m48-test/src.tgz"):  # fmt: skip
        assert want in create, want
    assert "+ gcloud storage cp" in r.stdout and "nothing was uploaded, made or started" in r.stdout


def test_driver_no_o_sets_the_line_without_o(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--dry-run", "--no-o")
    assert r.returncode == 0
    create = next(x for x in r.stdout.splitlines() if "compute instances create" in x)
    assert "tb-o=0" in create and "tb-stop-line-minutes=192" in create


@pytest.mark.parametrize("vm", ["tb-h47-48gb", "tb-h53-48gb-2"])
def test_driver_takes_its_own_names(tmp_path: Path, vm: str) -> None:
    assert _driver(tmp_path, "--dry-run", vm).returncode == 0


def _describe(tmp: Path, label: str = "h53-48gb", run: str = "m48-run1") -> str:
    f = tmp / "describe.json"
    f.write_text(json.dumps({"status": "TERMINATED", "labels": {"trialbox": label},
                             "metadata": {"items": [{"key": "tb-run-id", "value": run}]}}))  # fmt: skip
    return str(f)


def _bucket(tmp: Path, steps: dict[str, Any] | None, clock: str = "") -> str:
    g = tmp / "gcs"
    g.mkdir()
    if steps is not None:
        (g / "steps.json").write_text(json.dumps(steps))
    if clock:
        (g / "clock.txt").write_text(clock)
    return str(g)


@pytest.mark.parametrize(("label", "run"), [("h53-48gb", "m48-other"), ("demo-vm", "m48-run1"), ("", "")])
@pytest.mark.parametrize("how", [("--delete", "m48-run1"), ("--stop", "m48-run1"), ("--resume", "m48-run1")])
def test_driver_acts_only_on_its_runs_vm(tmp_path: Path, label: str, run: str, how: tuple[str, str]) -> None:
    r = _driver(tmp_path, *how, M48_DESCRIBE=_describe(tmp_path, label, run), M48_STATUS="TERMINATED",
                M48_GCS=_bucket(tmp_path, {"used_s": 600, "ended": ""}))  # fmt: skip
    assert r.returncode == 2 and "is not run m48-run1's VM" in r.stderr
    calls = (tmp_path / "calls.txt").read_text()
    for verb in ("instances delete", "instances stop", "instances start", "set-scheduling"):
        assert verb not in calls


def test_collect_deletes_only_its_runs_ended_vm(tmp_path: Path) -> None:
    g = _bucket(tmp_path, {"used_s": 600, "ended": "complete", "steps": []})
    r = _driver(tmp_path, "--collect", "m48-run1", M48_DESCRIBE=_describe(tmp_path, run="m48-other"),
                M48_STATUS="TERMINATED", M48_GCS=g)  # fmt: skip
    assert "is not run m48-run1's VM" in r.stderr and "instances delete" not in (tmp_path / "calls.txt").read_text()
    (tmp_path / "describe.json").unlink()
    r = _driver(tmp_path, "--collect", "m48-run1", M48_DESCRIBE=_describe(tmp_path), M48_STATUS="TERMINATED", M48_GCS=g)
    assert r.returncode == 0 and "instances delete tb-h47-48gb" in (tmp_path / "calls.txt").read_text()


def test_resume_refuses_without_the_vms_clock(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--resume", "m48-run1", M48_DESCRIBE=_describe(tmp_path), M48_STATUS="TERMINATED",
                M48_GCS=_bucket(tmp_path, None))  # fmt: skip
    assert r.returncode == 2 and "has no used_s" in r.stderr
    assert "instances start" not in (tmp_path / "calls.txt").read_text()


def test_resume_cap_is_whats_left_less_a_boot_margin(tmp_path: Path) -> None:
    clock = "2026-11-20T01:00:00Z boot (used 0 s of the run)\n2026-11-20T01:30:00Z boot (used 1800 s of the run)\n"
    r = _driver(tmp_path, "--resume", "m48-run1", M48_DESCRIBE=_describe(tmp_path), M48_STATUS="TERMINATED",
                M48_GCS=_bucket(tmp_path, {"used_s": 3600, "ended": ""}, clock))  # fmt: skip
    assert r.returncode == 0, r.stderr
    sched = next(x for x in (tmp_path / "calls.txt").read_text().splitlines() if "set-scheduling" in x)
    assert "--max-run-duration=164m" in sched  # 240 - 60 on the clock - 2 boots x 8
    assert "--provisioning-model=SPOT" in sched and "--instance-termination-action=STOP" in sched
