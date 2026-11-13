"""Failure modes of the cloud driver and the VM script found by an independent review (2026-11-12, numbered as in
the review); each test failed before its fix. The cloud is the rehearsal's own fake gcloud
(tests/rehearsal/driver-shims/gcloud) over a temporary state folder: nothing here touches GCP, and its ``docker exec``
(a VM's boot) goes to a container that does not exist, unless a test puts its own ``docker`` first on PATH."""

from __future__ import annotations

import fcntl
import io
import json
import os
import stat
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

from tools import complete_run as cr

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
SHIMS = ROOT / "tests" / "rehearsal" / "driver-shims"
PY = str(ROOT / ".venv" / "bin" / "python")
HEAD = "d" * 40


# ---------------------------------------------------------------- the fake cloud: the rehearsal's shim
def _state(tmp: Path, status: str = "TERMINATED") -> Path:
    s = tmp / "state"
    for d in ("metadata", "knobs/metadata", "bucket", "secrets/tb-gpu-door", "units"):
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
               TB_LOCK_DIR=str(tmp / "locks"), TB_SETTLE_S="5", **kw)  # fmt: skip
    for k in ("TB_ZONES", "TB_BUCKET", "TB_RUN_ID", "TB_DRIVER_LOCK_HELD", "TB_DRIVER_CHILD", "TB_RUNS_DIR"):
        if k not in kw:
            env.pop(k, None)
    return env


def _run(env: dict[str, str], *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          check=False, timeout=timeout)  # fmt: skip


def _calls(tmp: Path) -> str:
    p = tmp / "state" / "gcloud.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _tgz(parts: dict[str, bool]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for tag, ok in parts.items():
            body = json.dumps({"stages": [{"name": "s", "ok": ok, "seconds": 0, "checks": [["c", ok, ""]]}],
                               "run": {"id": "R1-s1", "head": HEAD}}).encode()  # fmt: skip
            info = tarfile.TarInfo(f"parts/{tag}.json")
            info.size = len(body)
            t.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def _collect_run(tmp: Path, tags: tuple[str, ...] = ("scenario-it-dump",), door: bool = True) -> Path:
    """A launched run R1 as its folder has it: the plan, shard 1's door, nothing collected yet."""
    out = tmp / "out"
    sh = out / "shard-1"
    sh.mkdir(parents=True)
    shard = {"shard": 1, "vm": "tb-gpu-sim", "zone": "asia-east1-a", "tags": list(tags), "rows": [], "hours": 1.0,
             "usd": 2.74, "cap_hours": 2, "cap_usd": 5.48}  # fmt: skip
    plan = {"vms": 1, "shards": [shard], "wall_hours": 1.0, "hours": 1.0, "usd": 2.74, "cap_usd": 5.48}
    (out / "plan.json").write_text(json.dumps({"patients": 500, "parts": ["g1"], "only": list(tags), "plan": plan}),
                                   encoding="utf-8")  # fmt: skip
    if door:
        for f, v in (("tb-key", "k"), ("door.crt", "c"), ("door.pin", "p"), ("door-version", "7")):
            (sh / f).write_text(v, encoding="utf-8")
        (tmp / "state" / "secrets" / "tb-gpu-door" / "7").write_text("{}", encoding="utf-8")
    return sh


def _bucket_results(tmp: Path, parts: dict[str, bool]) -> None:
    d = tmp / "state" / "bucket" / "tb-runs" / "runs" / "R1-s1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.tgz").write_bytes(_tgz(parts))


# ---------------------------------------------------------------- 1. the driver's poll is not the run's heartbeat
def test_the_drivers_poll_touches_driver_alive_not_the_runs_heartbeat() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    door = vm[vm.index("def do_POST(self):") : vm.index("def do_PUT(self):")]
    assert '(TB / "driver-alive").touch()' in door and '(TB / "heartbeat").touch()' not in door
    dog = vm[vm.index("cat >/usr/local/sbin/tb-watchdog") : vm.index("chmod 0755 /usr/local/sbin/tb-watchdog")]
    assert "driver-alive" not in dog.split("while :; do", 1)[1]  # the run's idle limit: the part's own work only


# ---------------------------------------------------------------- 2. an unknown status is not the end of the run
def test_a_failed_describe_is_not_taken_as_stopped(tmp_path: Path) -> None:
    """One look (--collect) while a status describe fails: before, the poll broke, the partial results were marked
    final, `collected` sent and the door retired, so the parts still to come could never be fetched."""
    _state(tmp_path, "RUNNING")
    sh = _collect_run(tmp_path, ("scenario-it-dump", "scenario-gateway"))
    _bucket_results(tmp_path, {"scenario-it-dump": True})  # one of the two parts so far
    _knob(tmp_path, "describe-fail", 1)
    r = _run(_env(tmp_path, TB_BUCKET="gs://tb-runs"), "--collect", "R1")
    assert "status unknown: taken as still running" in r.stdout, (r.stdout[-1500:], r.stderr[-1500:])
    assert not (sh / "results.final").exists() and (sh / "state").read_text().strip() == "running"
    assert (sh / "tb-key").exists() and "secrets versions destroy" not in _calls(tmp_path)


def test_the_poll_breaks_only_on_a_stopped_vm() -> None:
    drv = (GCP / "complete-run.sh").read_text(encoding="utf-8")
    poll = drv[drv.index("# -------------------------------------------------------------- poll:") :
               drv.index("# -------------------------------------------------------------- this VM's results")]  # fmt: skip
    assert "TERMINATED|STOPPED) break" in poll and '[ "$s" = RUNNING ] || break' not in poll


# ---------------------------------------------------------------- 3. a refused results-only start
def test_a_refused_results_only_start_marks_nothing(tmp_path: Path) -> None:
    """A stockout refuses the start: before, collect-boot was written first and the next --collect said "its disk has
    no results" and destroyed the door; here nothing is marked and the next --collect tries again."""
    _state(tmp_path, "TERMINATED")
    sh = _collect_run(tmp_path)
    _knob(tmp_path, "start-fail", 1)
    r = _run(_env(tmp_path), "--collect", "R1", timeout=120)
    assert "results-only start was refused" in r.stderr, (r.stdout[-1500:], r.stderr[-1500:])
    assert not (sh / "collect-boot").exists() and (sh / "state").read_text().strip() == "stopped"
    assert (sh / "door.crt").exists()  # the next --collect makes a new door and starts it again
    r2 = _run(_env(tmp_path), "--collect", "R1", timeout=120)  # the start fails again (no VM here): said again
    assert "found nothing earlier" not in r2.stderr and "results-only start" in r2.stdout + r2.stderr


# ---------------------------------------------------------------- 4. a launch over another run's results
def _vm_holding(tmp: Path, run: str) -> None:
    vm = {"name": "tb-gpu-sim", "tags": {"items": ["tb-gpu-door"]},
          "networkInterfaces": [{"network": "projects/rehearsal/global/networks/default"}],
          "serviceAccounts": [{"email": "tb-gpu@rehearsal.iam.gserviceaccount.com",
                               "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}],
          "metadata": {"items": [{"key": "tb-run-id", "value": run}]}}  # fmt: skip
    (tmp / "state" / "vm.json").write_text(json.dumps(vm), encoding="utf-8")


def test_a_launch_refuses_while_the_vm_holds_an_uncollected_run(tmp_path: Path) -> None:
    _state(tmp_path)
    _vm_holding(tmp_path, "OLD-s1")
    runs = tmp_path / "runs"
    env = _env(tmp_path, TB_RUNS_DIR=str(runs), TB_RUN_ID="NEW")
    r = _run(env, "--patients", "500", "--only", "scenario-it-dump", "--no-wait")
    assert r.returncode == 3 and "holds run OLD-s1" in r.stderr, (r.stdout[-1500:], r.stderr[-1500:])
    assert "--discard-previous" in r.stderr and "instances start" not in _calls(tmp_path)
    (runs / "OLD" / "shard-1").mkdir(parents=True)  # collected since: the launch goes ahead (the start fails here)
    (runs / "OLD" / "shard-1" / "state").write_text("done\n", encoding="utf-8")
    env["TB_COMPLETE_DIR"] = str(tmp_path / "out2")
    r = _run(env, "--patients", "500", "--only", "scenario-it-dump", "--no-wait")
    assert "holds run" not in r.stderr and "instances start" in _calls(tmp_path), r.stderr[-1500:]


def test_discard_previous_launches_over_it(tmp_path: Path) -> None:
    _state(tmp_path)
    _vm_holding(tmp_path, "OLD-s1")
    env = _env(tmp_path, TB_RUNS_DIR=str(tmp_path / "runs"), TB_RUN_ID="NEW")
    r = _run(env, "--patients", "500", "--only", "scenario-it-dump", "--no-wait", "--discard-previous")
    assert "is discarded (--discard-previous)" in r.stderr and "instances start" in _calls(tmp_path), r.stderr[-1500:]


# ---------------------------------------------------------------- 5. any give-up after the start
def test_an_error_between_the_start_and_the_upload_stops_the_vm(tmp_path: Path) -> None:
    """The address describe fails after the start (set -e ends the shard): before, the VM ran on with its door."""
    _state(tmp_path)
    _knob(tmp_path, "natip-fail", 1)
    env = _env(tmp_path, docker_ok=True, TB_RUN_ID="R5")
    r = _run(env, "--patients", "500", "--only", "scenario-it-dump", "--no-wait")
    calls = _calls(tmp_path)
    assert "instances start" in calls, (r.stdout[-1500:], r.stderr[-1500:])
    assert "the driver ended before the code was accepted" in r.stderr and "instances stop" in calls
    assert "secrets versions destroy" in calls and (tmp_path / "state" / "status").read_text().strip() == "TERMINATED"
    left = [p.name for p in (tmp_path / "state" / "secrets" / "tb-gpu-door").iterdir() if p.name != ".last"]
    assert left == [] and (tmp_path / "out" / "shard-1" / "state").read_text().strip() == "noresults"


# ---------------------------------------------------------------- 6. a failed bucket upload
def test_the_vm_retries_the_bucket_upload_and_keeps_the_archive() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    pack = vm[vm.index("cat >/usr/local/sbin/tb-pack") : vm.index("chmod 0755 /usr/local/sbin/tb-pack")]
    assert "for wait in 30 60 0" in pack and "upload-failed" in pack and "TB-UPLOAD-FAILED" in pack
    only = vm[vm.index('if [ "$COLLECT_ONLY" = 1 ]; then  # a stopped VM') :]
    assert 'gcloud storage cp "$TB/out/results.tgz" "$BUCKET/runs/$RUN_ID/results.tgz"' in only


def test_a_bucket_collect_without_results_starts_it_and_says_what_is_missing(tmp_path: Path) -> None:
    _state(tmp_path, "TERMINATED")
    _collect_run(tmp_path)
    r = _run(_env(tmp_path, TB_BUCKET="gs://tb-runs"), "--collect", "R1", timeout=120)
    assert "gs://tb-runs/runs/R1-s1/results.tgz: not in the bucket" in r.stderr, (r.stdout[-1500:], r.stderr[-1500:])
    assert "instances start" in _calls(tmp_path)  # a results-only start (it fails here: no VM)


# ---------------------------------------------------------------- 7. one driver per run folder
def test_a_second_driver_says_who_holds_the_run(tmp_path: Path) -> None:
    _state(tmp_path, "RUNNING")
    _collect_run(tmp_path)
    lock = tmp_path / "out" / "driver.lock"
    (tmp_path / "out" / "driver.lock.who").write_text("pid 4242, since 2026-11-13T00:00:00Z, the first\n")
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(_env(tmp_path), "--collect", "R1")
    assert r.returncode == 7 and "held by another driver (pid 4242" in r.stderr, (r.stdout[-800:], r.stderr[-800:])
    assert "instances describe" not in _calls(tmp_path)


# ---------------------------------------------------------------- 8. the serving watchdog and the images
def _sh_value(script: str, name: str) -> int:
    lines = [ln for ln in script.splitlines() if ln.split("=", 1)[0] in
             {"DOCKER_WAIT_S", "DOOR_WAIT_S", "HEALTH_WAIT_S", "CHECK_WAIT_S", "CAPTURE_WAIT_S", "SERVING_LIMIT_S"}]  # fmt: skip
    out = subprocess.run(["bash", "-c", "\n".join(lines) + f'\necho "${name}"'], capture_output=True, text=True,
                         check=True).stdout  # fmt: skip
    return int(out.strip())


def test_the_serving_limit_is_the_sum_of_its_waits() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    dog = vm[vm.index("cat >/usr/local/sbin/tb-watchdog") : vm.index("chmod 0755 /usr/local/sbin/tb-watchdog")]
    assert 'serving) [ "$since" -ge "$serving" ]' in dog and "serving|setup) [" not in dog
    assert '/usr/local/sbin/tb-watchdog "$IDLEM" "$GRACE" "$SERVING_LIMIT_S"' in vm
    waits = 120 + 30 * 7 + 2 * 240 * 5 + 2 * (30 + 300 + 30)  # docker, the door, two healths, two servers' checks
    assert _sh_value(vm, "SERVING_LIMIT_S") >= waits > 2700  # the old fixed 45 minutes cut a boot inside its waits
    assert "$((HEALTH_WAIT_S / 5))" in vm and 'HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"' in vm
    assert 'echo "TB-IMAGES$imgs"' in vm


def test_the_preflight_reads_the_images_from_the_last_boots_console(tmp_path: Path) -> None:
    vm = json.dumps({"serviceAccounts": [{"email": "vm@p.iam.gserviceaccount.com"}]})
    d = tmp_path / "pf"
    d.mkdir()
    for k, v in {"project.txt": "trialbox-demo", "account.txt": "dep@trialbox-demo.iam.gserviceaccount.com",
                 "mode.txt": "door", "vms.txt": "tb-gpu-sim asia-east1-a\n", "vm-tb-gpu-sim.json": vm,
                 "console-tb-gpu-sim.txt": "TB-IMAGES vllm/vllm-openai:v0.32.0=present nginx:1.27-alpine=present\n"
                                           "x\nTB-IMAGES vllm/vllm-openai:v0.32.0=missing nginx:1.27-alpine=present\n"}.items():  # fmt: skip
        (d / k).write_text(v, encoding="utf-8")
    bad, _ = cr.preflight_problems(d)
    assert len(bad) == 1 and "sudo docker pull vllm/vllm-openai:v0.32.0" in bad[0]
    (d / "console-tb-gpu-sim.txt").write_text("an older boot\n", encoding="utf-8")
    bad, notes = cr.preflight_problems(d)
    assert bad == [] and any("no TB-IMAGES line" in n for n in notes)


# ---------------------------------------------------------------- 9. work inside docker run, or on the card
def test_the_heartbeat_counts_a_parts_container_and_the_card(tmp_path: Path) -> None:
    hb = tmp_path / "hb"
    p = subprocess.Popen(["sleep", "30"])  # a part whose own process tree does nothing
    try:
        cpu = iter(float(i) for i in range(100))
        h = cr.Heartbeat(str(hb), p.pid, 0.05, gpu=lambda: False, containers=lambda: next(cpu))
        time.sleep(0.6)
        h.close()
        assert h.beats > 0 and h.why["container"] == h.beats
        g = cr.Heartbeat(str(hb), p.pid, 0.05, gpu=lambda: True, containers=lambda: None)
        time.sleep(0.6)
        g.close()
        assert g.beats > 0 and g.why["gpu"] == g.beats
        idle = cr.Heartbeat(str(hb), p.pid, 0.05, gpu=lambda: False, containers=lambda: 3.0)
        time.sleep(0.6)
        idle.close()
        assert idle.beats == 0  # stuck: nothing anywhere, the watchdog may power off
    finally:
        p.kill()
        p.wait()
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "docker run --rm --label tb-part=1" in vm and cr.PART_LABEL == "tb-part"


# ---------------------------------------------------------------- 10, 11. apt's lock; the grace after a failure
def test_apt_waits_for_the_lock_and_a_failure_has_a_short_grace() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    assert "APT=(apt-get -o DPkg::Lock::Timeout=600)" in vm and '"${APT[@]}" install -y' in vm
    assert "\napt-get " not in vm
    fin = vm[vm.index("finish() {") : vm.index('if [ "$COLLECT_ONLY" != 1 ]; then')]
    assert 'echo "$FAILGRACE" > "$TB/grace"' in fin and "tb-fail-grace || echo 5" in vm
    dog = vm[vm.index("cat >/usr/local/sbin/tb-watchdog") : vm.index("chmod 0755 /usr/local/sbin/tb-watchdog")]
    assert "[ -s $tb/grace ] && g=$(cat $tb/grace)" in dog


# ---------------------------------------------------------------- 12. the door's certificate outlives a late collect
def test_the_door_certificate_is_valid_for_weeks(tmp_path: Path) -> None:
    sh = f'. "{GCP}/door-tls.sh"; PY="{PY}" door_make "{tmp_path}" && openssl x509 -checkend {25 * 86400} -noout ' \
         f'-in "{tmp_path}/door.crt"'  # fmt: skip
    assert subprocess.run(["bash", "-c", sh], capture_output=True, text=True, check=False).returncode == 0


# ---------------------------------------------------------------- 13-16
def test_a_shard_restart_by_hand_reads_its_zones_quota(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    e = json.loads(subprocess.run([PY, "-m", "tools.complete_run", "--estimate", "--json", "--patients", "500",
                                   "--only", "scenario-it-dump"], cwd=ROOT, capture_output=True, text=True, check=True,
                                  env=dict(os.environ, PYTHONPATH="libs:services:.")).stdout)  # fmt: skip
    for s in e["plan"]["shards"]:
        s["vm"], s["zone"] = "tb-gpu-sim", "us-central1-b"
    (out / "plan.json").write_text(json.dumps(e), encoding="utf-8")
    env = _env(tmp_path, TB_RUN_ID="R13")
    r = _run(env, "--dry-run", "--shard", "1")
    assert "gcloud compute regions describe us-central1 --format=json" in r.stdout, (r.stdout[-1500:], r.stderr[-800:])
    child = _run(dict(env, TB_DRIVER_CHILD="1"), "--dry-run", "--shard", "1")
    assert "regions describe" not in child.stdout  # the driver read the quota before its children


def test_a_collected_vm_goes_back_to_spot(tmp_path: Path) -> None:
    _state(tmp_path, "TERMINATED")
    sh = _collect_run(tmp_path)
    _bucket_results(tmp_path, {"scenario-it-dump": True})
    r = _run(_env(tmp_path, TB_BUCKET="gs://tb-runs"), "--collect", "R1")
    calls = _calls(tmp_path)
    assert (sh / "results.final").exists(), (r.stdout[-1500:], r.stderr[-1500:])
    assert "--provisioning-model=SPOT" in calls and "startup-script=" in calls and "gpu-sim-startup.sh" in calls
    assert "back to spot and the usual startup script" in r.stdout


def _part(ok: bool) -> dict[str, Any]:
    return {"stages": [{"name": "s", "ok": ok, "seconds": 0, "checks": [["c", ok, ""]]}]}


def test_prepare_merges_as_failed_if_any_vm_failed_it(tmp_path: Path) -> None:
    out = tmp_path / "parts"
    for i, ok in ((1, False), (2, True)):
        d = tmp_path / f"shard-{i}" / "parts"
        d.mkdir(parents=True)
        (d / "prepare.json").write_text(json.dumps(_part(ok)), encoding="utf-8")
        (d / f"hospital-ja@c{i}.json").write_text(json.dumps(_part(True)), encoding="utf-8")
    cr.merge_parts(tmp_path / "shard-1" / "parts", out)
    said = cr.merge_parts(tmp_path / "shard-2" / "parts", out)
    assert not cr._passed(json.loads((out / "prepare.json").read_text(encoding="utf-8")))
    assert said and "kept as failed" in said[0] and (out / "hospital-ja@c2.json").exists()
    drv = (GCP / "complete-run.sh").read_text(encoding="utf-8")
    assert 'cr --merge-parts "$SH/parts" --parts-dir "$OUT/parts"' in drv and 'cp -p "$SH"/parts/*.json' not in drv


def test_hours_must_be_whole(tmp_path: Path) -> None:
    _state(tmp_path)
    r = _run(_env(tmp_path), "--hours", "2.5", "--patients", "500", "--only", "scenario-it-dump", "--no-wait")
    assert r.returncode == 2 and "--hours: a whole number" in r.stderr and _calls(tmp_path) == ""


# ---------------------------------------------------------------- audit c: the gateway's audit comes back
def test_the_results_carry_the_gateways_audit_and_g1s_texts() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    pack = vm[vm.index("cat >/usr/local/sbin/tb-pack") : vm.index("chmod 0755 /usr/local/sbin/tb-pack")]
    assert "gw-audit-* chat-template; do" in pack
