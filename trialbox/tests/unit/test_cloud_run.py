"""The cloud run made reliable (D-150, the independent review of 2026-11-09): the pieces that run on a CPU.

The whole path (the real driver and VM script against stand-ins) is ``make rehearse`` (``tests/rehearsal``); here:
run identity and ``--resume`` (H-01), the in-run heartbeat (H-03), data that fails fast (C-03), the report's truth
(M-02, M-03, M-09), the bounded estimate, the quota check (H-05, with the driver refusing before anything is made),
and what the VM script must hold (H-02, M-01, M-04, M-05, M-06, M-08, M-10, L-05)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run as cr
from tools import fetch_run_data

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
REH = ROOT / "tests" / "rehearsal"
VM = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")


def _res(run_id: str, head: str, ok: bool = True) -> dict[str, Any]:
    return {"stages": [{"name": "s", "ok": ok, "seconds": 0, "checks": [["c", ok, ""]]}],
            "run": {"id": run_id, "head": head}}  # fmt: skip


# ------------------------------------------------------------------------------------------------ H-01: run identity
def test_resume_keeps_only_parts_of_this_run_id_and_head(tmp_path: Path) -> None:
    assert cr.same_run(_res("R1", "abc"), "R1", "abc") == (True, "")
    assert not cr.same_run(_res("R0", "abc"), "R1", "abc")[0]  # a passed part of another run: never kept
    assert not cr.same_run(_res("R1", "old"), "R1", "abc")[0]  # the same run id at another HEAD: never kept
    assert not cr.same_run({"stages": []}, "R1", "abc")[0]  # a result from before run ids: never kept
    assert not cr.same_run(_res("R1", ""), "R1", "")[0]  # no HEAD known: nothing is kept
    parts = tmp_path / "parts"
    parts.mkdir()
    for tag, r in (("a", _res("R1", "abc")), ("b", _res("R0", "abc")), ("c", _res("R1", "def"))):
        (parts / f"{tag}.json").write_text(json.dumps(r), encoding="utf-8")
    assert cr.drop_stale_parts(parts, "R1", "abc") == ["b", "c"]
    assert sorted(p.stem for p in parts.glob("*.json")) == ["a"]


@pytest.mark.skipif(
    not cr.NODE_TOOLS.exists() and not os.environ.get("NODE_PATH"),
    reason="the part's screenshot needs the preinstalled Node Playwright",
)
def test_a_part_records_its_run_and_a_new_run_runs_it_again(tmp_path: Path) -> None:
    env = dict(os.environ, PYTHONPATH="libs:services:.", TB_SELFTEST_SECONDS="0.2", TB_ENV="DEV")

    def run(run_id: str) -> str:
        r = subprocess.run([sys.executable, "-m", "tools.complete_run", "--dir", str(tmp_path), "--run-id", run_id,
                            "--only", "selftest-busy", "--resume"], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=300, check=False)  # fmt: skip
        assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
        return r.stdout

    run("R1")
    rec = json.loads((tmp_path / "parts" / "selftest-busy.json").read_text(encoding="utf-8"))["run"]
    assert rec["id"] == "R1" and rec["head"] == cr.git_head()["head"] and rec["host"]["cpus"]
    assert "kept (--resume)" in run("R1")
    out = run("R2")
    assert "kept" not in out and "of another run or HEAD removed: selftest-busy" in out


def test_git_head_comes_from_the_archive_when_there_is_no_repository(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The VM has the uploaded archive, no .git, and before setup no git at all (rehearsal boot 1: the run died)."""
    root = tmp_path / "src" / "trialbox"
    root.mkdir(parents=True)
    (root.parent / cr.HEAD_FILE).write_text(json.dumps({"head": "f" * 40, "subject": "s", "dirty": False}), "utf-8")
    monkeypatch.setattr(cr, "ROOT", root)

    def no_git(*a: Any, **k: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert cr.git_head() == {"head": "f" * 40, "subject": "s", "dirty": False, "source": "archive"}
    (root.parent / cr.HEAD_FILE).unlink()
    assert cr.git_head()["head"] == ""


# ------------------------------------------------------------------------------------------------ H-03: heartbeat
@pytest.mark.parametrize("busy", [True, False])
def test_the_heartbeat_follows_the_part_working_not_its_output(tmp_path: Path, busy: bool) -> None:
    hb = tmp_path / "hb"
    hb.touch()
    os.utime(hb, (0, 0))
    code = (
        "import time\nt=time.time()\nwhile time.time()-t<2.5: sum(range(10000))"
        if busy
        else "import time; time.sleep(2.5)"
    )
    p = subprocess.Popen([sys.executable, "-c", code])
    beat = cr.Heartbeat(str(hb), p.pid, every=0.5)
    time.sleep(1.2)  # the child has started; from here a busy child beats, a sleeping one does not
    os.utime(hb, (0, 0))
    p.wait()
    beat.close()
    if Path("/proc").exists():
        assert (hb.stat().st_mtime > 0) is busy


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="the CPU check reads /proc (Linux)")
def test_a_part_that_has_ended_gives_no_heartbeat(tmp_path: Path) -> None:
    # the window between the part's end (p.wait()) and Heartbeat.close(): a process that is gone is not busy
    hb = tmp_path / "hb"
    hb.touch()
    os.utime(hb, (0, 0))
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    beat = cr.Heartbeat(str(hb), p.pid, every=0.05)
    time.sleep(0.5)
    beat.close()
    assert beat.beats == 0 and hb.stat().st_mtime == 0


# ------------------------------------------------------------------------------------------------ C-02, C-03: data
def test_a_part_without_its_data_fails_at_once_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import medtxt_eval, trec_ct_eval

    monkeypatch.setattr(medtxt_eval, "CACHE", tmp_path / "medtxt")
    monkeypatch.setattr(trec_ct_eval, "CACHE", tmp_path / "trec")
    assert cr.data_needs("hospital-ja") == ("cql",) and "medtxt" in cr.data_needs("public-zh-TW")
    assert cr.data_needs("scenario-it-dump") == () and cr.data_missing("scenario-it-dump") == []
    assert "MedTxt" in cr.data_missing("scenario-public-medtxt")[0]
    assert "sample_trials.json" in cr.data_missing("scenario-public-trec")[0]
    a = argparse.Namespace(part="scenario", lang="ja", scenario="public-trec", dir=tmp_path, shots=tmp_path / "shots",
                           run_id="R1", resume=False, model="pair", direct=False)  # fmt: skip
    t0 = time.perf_counter()
    assert cr.run_part(a) == 1
    res = json.loads((tmp_path / "parts" / "scenario-public-trec.json").read_text(encoding="utf-8"))
    assert time.perf_counter() - t0 < 30 and res["not_run"] == "data missing" and res["run"]["id"] == "R1"
    assert res["stages"][0]["checks"][0][0] == "the part's data is on this machine"


def test_fetch_run_data_fetches_only_what_the_planned_parts_need() -> None:
    assert fetch_run_data.needed([]) == ["cql", "medtxt", "trec"]
    assert fetch_run_data.needed(["hospital-ja", "scenario-gateway"]) == ["cql"]
    assert fetch_run_data.needed(["scenario-public-trec", "selftest-busy"]) == ["trec"]
    assert fetch_run_data.QUICK_URL.startswith("https://repo1.maven.org/maven2/org/cqframework/quick/5.4.0/")
    assert len(fetch_run_data.QUICK_SHA256) == 64


def test_fetch_links_its_cache_and_leaves_a_laptops_own_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch_run_data, "ROOT", tmp_path / "src")
    got = fetch_run_data._link(tmp_path / "cache", "medtxt")
    assert got.is_symlink() and got.resolve() == (tmp_path / "cache" / "medtxt").resolve()
    own = tmp_path / "src" / ".cache" / "trec_ct"
    own.mkdir(parents=True)
    assert not fetch_run_data._link(tmp_path / "cache", "trec_ct").is_symlink()


# ------------------------------------------------------------------------------------------------ M-02, M-03, M-09
def _row(tag: str, part: str, ok: bool = True, **kw: Any) -> dict[str, Any]:
    return {"tag": tag, "part": part, "lang": "", "seconds_total": 1.0,
            "stages": [{"name": tag, "ok": ok, "seconds": 1, "checks": [["c", ok, ""]]}], **kw}  # fmt: skip


def _args(**kw: Any) -> argparse.Namespace:
    base = {"model": "pair", "direct": False, "ocr": "tesseract", "patients": 50000, "langs": ["ja", "zh-TW"],
            "planned_from": None}  # fmt: skip
    return argparse.Namespace(**{**base, **kw})


def test_the_report_names_the_vms_head_and_host_and_the_parts_that_never_ran(tmp_path: Path) -> None:
    vm = {"id": "R-s1", "head": "a" * 40, "subject": "on the VM", "dirty": False, "weight_pins": "synthetic",
          "host": {"machine": "x86_64", "cpus": 48, "node": "tb-gpu-sim"}}  # fmt: skip
    rows = [_row("scenario-it-dump", "scenario", run=vm),
            _row("hospital-ja", "hospital", ok=False, not_run="crashed", run=vm),
            _row("public-ja", "public", ok=False, not_run="data missing", run=vm)]  # fmt: skip
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"parts": [{"tag": "hospital-ja", "stages": [{"checks": [[1, 1, 1]] * 169}]},
                                         {"tag": "public-ja", "stages": [{"checks": [[1, 1, 1]] * 120}]}]}), "utf-8")  # fmt: skip
    rep = cr.report(_args(planned_from=ref), rows, cr.made_by(rows), datetime.now(UTC))
    assert rep["git"]["head"] == "a" * 40 and rep["host"]["cpus"] == 48 and rep["run_ids"] == ["R-s1"]
    assert rep["path"] == "gateway (installed box, synthetic weight pins)" and rep["ocr"] == "tesseract"
    assert rep["checks_never_ran"] == 289 and [x["tag"] for x in rep["not_run"]] == ["hospital-ja", "public-ja"]
    md = cr.markdown(rep)
    assert "Head `aaaaaaaaaaaa` (on the VM)" in md and "48 CPUs" in md and "50,000 synthetic patients" in md
    assert "**2 part(s) crashed or never ran** (hospital-ja, public-ja): 289 of their checks never ran" in md
    rep2 = cr.report(_args(), rows, cr.made_by(rows), datetime.now(UTC))
    assert "number unknown" in cr.markdown(rep2)


def test_parts_from_two_commits_are_named(tmp_path: Path) -> None:
    rows = [
        _row("a", "scenario", run={"id": "R", "head": "1" * 40}),
        _row("walk", "walk", run={"id": "R", "head": "2" * 40}),
    ]
    g = cr.made_by(rows)
    assert g["head"] == "1" * 40 and g["heads"] == ["1" * 40, "2" * 40]
    assert "parts from 2 commits" in cr.markdown(cr.report(_args(), rows, g, datetime.now(UTC)))


def test_profile_passes_only_through_the_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import bench_profile

    def fake_run(*a: Any, **k: Any) -> dict[str, Any]:
        m = {"answered": 2, "patients": 2, "citations_valid": 1.0, "tokens_in": {"mean": 9}, "tokens_out": {"mean": 3}}
        return {"path": path, "gateway_refused": "upstream_failed", "measured": m}

    monkeypatch.setattr(cr, "_bench_synth", lambda work, sites: (work.mkdir(parents=True), work)[1])
    monkeypatch.setattr(bench_profile, "make_call", lambda a, work: None)
    monkeypatch.setattr(bench_profile, "run", fake_run)
    monkeypatch.setattr(bench_profile, "summary", lambda res: {})
    a = argparse.Namespace(dir=tmp_path, model="pair", direct=False, profile_patients=2, profile_workers=1, patients=10)
    path = "direct (the gateway refused: upstream_failed)"
    res = cr.part_profile(a)
    gw = [c for c in res["stages"][0]["checks"] if "gateway answered" in c[0]]
    assert gw and gw[0][1] is False and res["findings"][0]["id"] == "PROFILE-GW"
    path = "gateway (installed box)"
    assert cr._passed(cr.part_profile(a)) and not cr.part_profile(a)["findings"]


# ------------------------------------------------------------------------------------------------ the bounded estimate
def test_a_bounded_run_estimates_and_plans_only_its_parts() -> None:
    e = cr.restrict(cr.estimate(5000), ["install", "hospital-ja", "scenario-gateway"])
    assert {t for r in e["rows"] for t in r["tags"]} == {"hospital-ja", "scenario-gateway"}
    assert e["hours"] < cr.estimate(5000)["hours"] and e["cap_hours"] >= 1
    p = cr.shard_plan(e, 1)
    assert p["shards"][0]["tags"][:2] == ["install", "prepare"] and "scenario-it-dump" not in p["shards"][0]["tags"]
    assert "install" not in cr.shard_plan(cr.restrict(cr.estimate(5000), ["scenario-gateway"]), 1)["shards"][0]["tags"]
    with pytest.raises(ValueError, match="no such part"):
        cr.restrict(cr.estimate(5000), ["hospital-xx"])
    st = cr.shard_plan(cr.restrict(cr.estimate(500), ["selftest-busy"]), 1)
    assert st["shards"][0]["tags"] == ["selftest-busy"]


# ------------------------------------------------------------------------------------------------ H-05: quota
def _q(metric: str, limit: float, usage: float = 0) -> dict[str, Any]:
    return {"metric": metric, "limit": limit, "usage": usage}


def test_quota_too_small_for_the_vms_is_named() -> None:
    project = {"quotas": [_q("GPUS_ALL_REGIONS", 1)]}
    region = {"quotas": [_q("NVIDIA_RTX_PRO_6000_GPUS", 1), _q("PREEMPTIBLE_NVIDIA_RTX_PRO_6000_GPUS", 0),
                         _q("CPUS", 96), _q("PREEMPTIBLE_CPUS", 0)]}  # fmt: skip
    assert cr.quota_problems(project, {"asia-east1": region}, ["asia-east1-a"]) == []
    two = cr.quota_problems(project, {"asia-east1": region, "us-central1": region}, ["asia-east1-a", "us-central1-b"])
    assert len(two) == 1 and "GPUS_ALL_REGIONS" in two[0] and "needs 2" in two[0]
    busy = {"quotas": [_q("NVIDIA_RTX_PRO_6000_GPUS", 1, 1), _q("CPUS", 96, 60)]}  # tb-gpu-sim running: no GPU left
    bad = cr.quota_problems({"quotas": [_q("GPUS_ALL_REGIONS", 4)]}, {"asia-east1": busy}, ["asia-east1-a"])
    assert any("regular quota" in b and "GPUs" in b for b in bad) and any("CPUs" in b for b in bad)
    pre = {"quotas": [_q("PREEMPTIBLE_NVIDIA_RTX_PRO_6000_GPUS", 2), _q("NVIDIA_RTX_PRO_6000_GPUS", 0), _q("CPUS", 0),
                      _q("PREEMPTIBLE_CPUS", 96)]}  # fmt: skip
    assert cr.quota_problems({"quotas": [_q("GPUS_ALL_REGIONS", 4)]}, {"asia-east1": pre}, ["asia-east1-a"]) == []
    assert any("not readable" in b for b in cr.quota_problems({}, {}, ["asia-east1-a"]))
    # the real asia-east1 list (2026-11-10): other GPUs and CPUs, no RTX PRO 6000 metric; GPUS_ALL_REGIONS bounds it
    no_metric = {"quotas": [_q("NVIDIA_L4_GPUS", 1), _q("CPUS", 96), _q("PREEMPTIBLE_CPUS", 0)]}
    one = {"quotas": [_q("GPUS_ALL_REGIONS", 1)]}
    assert cr.quota_problems(one, {"asia-east1": no_metric}, ["asia-east1-a"]) == []
    two = cr.quota_problems(one, {"asia-east1": no_metric, "us-central1": no_metric}, ["asia-east1-a", "us-central1-b"])
    assert len(two) == 1 and "GPUS_ALL_REGIONS" in two[0]  # the project bound still refuses
    # the CPUs must still be readable, and an unreadable project quota still refuses
    assert any(
        "CPUs quota not readable" in b
        for b in cr.quota_problems(one, {"asia-east1": {"quotas": [_q("NVIDIA_L4_GPUS", 1)]}}, ["asia-east1-a"])
    )
    assert any(
        "GPUS_ALL_REGIONS not readable" in b for b in cr.quota_problems({}, {"asia-east1": no_metric}, ["asia-east1-a"])
    )


def test_the_driver_refuses_to_start_or_provision_without_quota(tmp_path: Path) -> None:
    """The real driver against the rehearsal's gcloud with one GPU in the project: --vms 2 stops at the quota, before
    any machine image, VM or start (review H-05, L-04)."""
    state = tmp_path / "state"
    (state / "metadata").mkdir(parents=True)
    (state / "status").write_text("TERMINATED\n", encoding="utf-8")
    (tmp_path / "gc").mkdir()
    env = dict(os.environ, PATH=f"{REH / 'driver-shims'}:{os.environ['PATH']}", TB_REH_STATE=str(state),
               TB_REH_GPU_LIMIT="1", CLOUDSDK_CONFIG=str(tmp_path / "gc"), TB_SA_KEY_FILE="/dev/null",
               TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))  # fmt: skip
    env.pop("TB_ZONES", None)
    for args in (["--vms", "2", "--zones", "asia-east1-a,us-central1-b"],
                 ["--provision", "--vms", "2", "--zones", "asia-east1-a,us-central1-b"]):  # fmt: skip
        r = subprocess.run([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=300, check=False)  # fmt: skip
        calls = (state / "gcloud.log").read_text(encoding="utf-8")
        assert r.returncode == 4 and "GPUS_ALL_REGIONS" in r.stderr and "nothing was started or made" in r.stderr
        assert "instances start" not in calls and "machine-images" not in calls and "add-metadata" not in calls
    ok = subprocess.run([sys.executable, "-m", "tools.complete_run", "--quota-check", str(tmp_path / "out" / "quota"),
                         "--quota-zones", "asia-east1-a"], cwd=ROOT, env=env, capture_output=True, text=True,
                        check=False)  # fmt: skip
    assert ok.returncode == 0, ok.stderr


# ------------------------------------------------------------------------------------------------ the driver
def _dry(tmp_path: Path, *args: str) -> str:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))
    env.pop("TB_ZONES", None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", *args], cwd=ROOT, env=env, capture_output=True,
                       text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


def test_a_bounded_dry_run_starts_one_vm_with_its_parts_and_size(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "5000", "--only", "install,hospital-ja,scenario-gateway")
    assert "tb-patients=5000," in out  # the children used to fall back to 50,000 whatever --patients said
    assert "tb-only=install prepare hospital-ja scenario-gateway," in out and "tb-collect-only=0" in out
    assert "--add-file=TB_HEAD.json" in out and "tb-src-sha256=" in out
    assert out.index("project-info describe --format=json") < out.index("instances start")  # the quota first
    assert "--only walk backup update scale" not in out  # a bounded run has no stub parts
    assert "--report-only --model pair --patients 5000 --ocr tesseract --run-id" in out


def test_the_full_dry_run_runs_the_stub_parts_at_the_runs_size(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "50000")
    assert "--only walk backup update scale --patients 50000 --ocr tesseract --run-id" in out


# ------------------------------------------------------------------------------------------------ the VM script
def test_vm_checks_both_servers_before_ready_and_stops_loudly() -> None:
    ready = VM.index("echo PRO6000-RUN-READY")
    for s in ('healthy judge || serving_failed', 'healthy verifier || serving_failed', '/v1/models',
              '[ "$ids" = "$2" ] || serving_failed', '[ "$code" = 200 ] || serving_failed',
              '[ "$code" = 401 ] || serving_failed'):  # fmt: skip
        assert -1 < VM.index(s) < ready, s
    assert "serving-logs" in VM and 'finish "TB-SERVING-FAILED: $1" serving-failed' in VM


def test_vm_preflight_phases_and_state_per_run() -> None:
    pf = VM.index('finish "TB-PREFLIGHT-FAILED')
    assert VM.index("docker info 2>/dev/null | grep -qi nvidia") < pf < VM.index("start judge $J")
    assert "/models/hub/$w" in VM and "tb-min-free-gb" in VM
    assert 'RUN="$TB/runs/$RUN_ID"' in VM and '"$TB"/runs/*' in VM and '"$TB/out/results.tgz"' in VM
    assert 'mv -f "$LOG" "$LOG.prev"' in VM and 'mv -f "$CON" "$CON.prev"' in VM
    assert VM.index('COLLECT_ONLY" != 1') < VM.index('rm -rf "$TB/run" "$TB/out/results.tgz"')  # collect keeps them
    for limit in ('serving|setup) [ "$since" -ge 2700 ]', 'code) [ "$since" -ge 2100 ]', "run) [ $((now - hb))"):
        assert limit in VM
    assert "--property=Restart=on-failure" in VM and "TB-DOOR-FAILED" in VM and "TB-NO-KEY" in VM


def test_vm_checks_the_upload_installs_git_fetches_data_and_packs_per_part() -> None:
    assert VM.index('[ "$got" = "$SRC_SHA" ]') < VM.index("tar --no-same-owner --no-same-permissions -xzf")
    assert " xz-utils git " in VM and "chromium.launch()" in VM
    assert VM.index("tools.fetch_run_data") < VM.index("tools.complete_run")
    run = VM[VM.index("tools.complete_run --dir") :]
    assert '--run-id "$RUN_ID"' in run and '--after-part "/usr/local/sbin/tb-pack $RUN $BUCKET"' in run
    assert "--resume --heartbeat" in run and "maven" not in VM and "fetch_jvm_deps" not in VM
    assert 'mv -f "$out.tmp" "$out"' in VM  # the door never serves half an archive
    # a VM stopped mid-part (watchdog, first part never ending) still has a results.tgz: the rehearsal's hang case
    assert 'timeout 120 /usr/local/sbin/tb-pack "$(cat $tb/current-run)"' in VM
    assert VM.index('printf \'%s\' "$RUN" > "$TB/current-run"') < VM.index("\nphase code\n")
    drv = (GCP / "complete-run.sh").read_text(encoding="utf-8")
    assert '[ -f "$SH/collect-boot" ]' in drv and 'echo "noresults" > "$SH/state"' in drv  # one results-only boot


def test_rehearsal_harness_is_complete() -> None:
    for f in ("rehearse.sh", "check.py", "vllm_standin.py", "dns_standin.py", "vm/prep.sh", "vm/boot.sh",
              "driver-shims/gcloud", "shims/curl", "shims/docker", "shims/systemctl", "shims/systemd-run",
              "shims/nvidia-smi"):  # fmt: skip
        assert (REH / f).is_file(), f
        if not f.endswith(".py"):
            assert os.access(REH / f, os.X_OK), f
    sh = (REH / "rehearse.sh").read_text(encoding="utf-8")
    for case in ("run-a)", "run-b)", "served)", "no-upload)", "hang)", "busy)"):
        assert case in sh
    assert "deploy/gcp/complete-run.sh" in sh and "rehearse:" in (ROOT / "Makefile").read_text(encoding="utf-8")
