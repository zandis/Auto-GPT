"""The paid run of 2026-11-12 (20261112T165042Z-931a0f79, hospital-ja at 1, 4, 16, 48 calls in flight) found these in
the driver and its report; each test failed before its fix.

* A6: the door cannot be reached from a machine whose HTTPS goes through a proxy; the VM waited for code and idled.
* A7: no free pre-flight of the project (firewall, Secret Manager API, the secret, the deployer's viewer role, bucket).
* A8: the door secret's version stayed enabled after a collect while the VM ran (or through the bucket).
* M1: the throughput table's list came from a later stage's one-patient SCREEN and "identical" was claimed for lists
  of 54, 54, 55 and 55 patients.
* M2: the gateway's refusals (the PHI tripwire, the guard ...) per part: "N of M calls refused".

A fake ``gcloud`` on PATH stands in for the cloud: nothing here touches GCP. Synthetic data only: the ids below are
pseudonymous ids of synthetic patients from that run's report."""

from __future__ import annotations

import argparse
import io
import json
import os
import stat
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools import complete_run as cr
from tools import run_metrics as rm

GCP = Path(__file__).resolve().parents[2] / "deploy" / "gcp"
ROOT = GCP.parents[1]
PY = str(ROOT / ".venv" / "bin" / "python")
HEAD = "c" * 40
ONE = ["bc27eaa4e2cba51a755d45f8c4fea92d", "high"]  # the one patient of the stage-17 SCREEN, at every setting
SHA1 = "632590f638def460cf04a398a33b1e8db9ad1ba8da4e7e0343a30b9adb2ffd84"


# ---------------------------------------------------------------- M1: the main SCREEN's list
def _hospital(tag: str, listed: int, cand: dict[str, Any]) -> dict[str, Any]:
    n = int(tag.rsplit("@c", 1)[1])
    return {"tag": tag, "part": "hospital", "lang": "ja", "llm_concurrency": n, "candidates": cand,
            "screen": {"funnel": [["S0", 3022], ["S1", 92], ["S3", 92], ["S4", listed]], "listed": listed},
            "throughput": {"calls": 626, "calls_per_second": 1.0}, "stages": [], "seconds_total": 1}  # fmt: skip


def test_the_runs_parts_are_not_called_identical_from_a_one_patient_list() -> None:
    """The run's own parts: candidates.count 1 (sha 632590f638de) while the main SCREEN listed 54, 54, 55, 55."""
    cand = {"count": 1, "sha256": SHA1, "tiers": {"high": 1}, "list": [ONE]}
    rows = [_hospital(f"hospital-ja@c{n}", listed, cand) for n, listed in ((1, 54), (4, 54), (16, 55), (48, 55))]
    assert rm.lists_identical(rows) == {"ja": None}  # was {"ja": True}
    cmp = rm.lists_compare(rows)["ja"]
    assert "not the main SCREEN's list" in cmp["why"] and "hospital-ja@c16: list of 1 patient(s), its main SCREEN " \
        "listed 55" in cmp["why"]  # fmt: skip
    curve = rm.curve(rows)
    assert [(r["candidates"], r["candidates_sha256"]) for r in curve] == [(54, None), (54, None), (55, None),
                                                                          (55, None)]  # fmt: skip
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    md = cr.markdown(cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "**identical**" not in md and "Candidate lists of hospital-ja at every setting: **not compared**" in md


def test_differing_main_lists_name_the_pids_and_their_tiers() -> None:
    base = [[f"{i:032x}", "review"] for i in range(54)]
    c1 = rm.candidate_list_of_rows([{"pid": p, "tier": t} for p, t in base] + [{"pid": "f" * 32, "tier": "excluded"}])
    c16 = rm.candidate_list_of_rows([{"pid": p, "tier": t} for p, t in base] + [{"pid": "e" * 32, "tier": "high"}])
    assert c1["count"] == 54 and c16["count"] == 55
    rows = [_hospital("hospital-ja@c1", 54, c1), _hospital("hospital-ja@c16", 55, c16)]
    cmp = rm.lists_compare(rows)["ja"]
    assert cmp["identical"] is False
    assert cmp["differ"] == [{"pid": "e" * 32, "tiers": {"hospital-ja@c1": "-", "hospital-ja@c16": "high"}}]
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    md = cr.markdown(cr.report(a, rows, {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "**DIFFERENT**" in md and f"| `{'e' * 32}` | - | high |" in md
    same = [_hospital("hospital-ja@c1", 54, c1), _hospital("hospital-ja@c4", 54, dict(c1))]
    assert rm.lists_identical(same) == {"ja": True} and rm.curve(same)[0]["candidates_sha256"] == c1["sha256"]


def test_the_part_records_the_list_of_its_main_screen_job() -> None:
    """``main_candidates``: the job's own candidate_list_*.json, not the last SCREEN captured in the process."""
    rows = [{"pid": "a" * 32, "tier": "high"}, {"pid": "b" * 32, "tier": "review"}]
    store = {"k1": json.dumps({"rows": rows}).encode(), "k2": b"{}"}
    out = [SimpleNamespace(filename="screen_GZQO.json", minio_key="k2"),
           SimpleNamespace(filename="candidate_list_GZQO_v1.0.0.json", minio_key="k1")]  # fmt: skip
    box = SimpleNamespace(store=SimpleNamespace(get=store.__getitem__))
    got = cr.main_candidates(box, SimpleNamespace(job_id="J1", outputs=out))
    assert got["count"] == 2 and got["of"] == "J1" and got["list"] == [["a" * 32, "high"], ["b" * 32, "review"]]
    none = cr.main_candidates(box, SimpleNamespace(job_id="J2", outputs=[]))
    assert none["count"] == 0 and none["list"] is None


# ---------------------------------------------------------------- M2: refusals per part
def test_the_gateways_refusals_are_counted_per_part(tmp_path: Path) -> None:
    t0 = datetime(2026, 11, 12, 17, 0, tzinfo=UTC)

    def line(at: datetime, event: str, **d: Any) -> str:
        return json.dumps({"ts": at.isoformat(timespec="milliseconds"), "event": event, "detail": d})

    lines = [line(t0 - timedelta(minutes=1), "llm.gateway.refuse", reason="phi_tripwire", role="judge")]  # earlier
    lines += [line(t0 + timedelta(seconds=i), "llm.gateway.call", latency_ms=1000, endpoint="serving")
              for i in range(80)]  # fmt: skip
    lines += [line(t0 + timedelta(seconds=90 + i), "llm.gateway.refuse", reason="phi_tripwire", role="judge",
                   message="PHI tripwire hit") for i in range(4)]  # fmt: skip
    lines.append(line(t0 + timedelta(seconds=99), "llm.gateway.refuse", reason="model_busy", role="verifier"))
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    refused = rm.audit_refusals(tmp_path, t0)
    assert len(refused) == 5 and all("message" not in r for r in refused)  # the reason code only, never the text
    s = rm.refusal_stats(rm.audit_calls(tmp_path, t0), refused)
    assert s == {"asked": 85, "refused": 5, "by_reason": {"model_busy": 1, "phi_tripwire": 4},
                 "by_role": {"judge": 4, "verifier": 1}}  # fmt: skip
    assert rm.refused_cell(s) == "5 of 85 (model_busy 1, phi_tripwire 4)" and rm.refused_cell(None) == "-"
    row = {**_hospital("hospital-ja@c4", 54, {}), "refusals": s}
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=5000, langs=["ja"])
    md = cr.markdown(cr.report(a, [row], {"head": HEAD, "subject": "s", "dirty": False}, datetime.now(UTC)))
    assert "refused (of asked) |" in md and "| 5 of 85 (model_busy 1, phi_tripwire 4) |" in md


# ---------------------------------------------------------------- A6: a door no proxy can carry
def test_a_proxy_without_a_bucket_is_refused_with_the_way_out() -> None:
    why = cr.door_reach_problem({"HTTPS_PROXY": "http://user:pw@proxy:3128"})
    assert "TB_BUCKET" in why and "TB_DOOR_DIRECT=1" in why and "pw@proxy" not in why
    assert cr.door_reach_problem({"https_proxy": "http://p:1"}) != ""
    assert cr.door_reach_problem({"HTTPS_PROXY": "http://p:1", "TB_BUCKET": "gs://b"}) == ""
    assert cr.door_reach_problem({"HTTPS_PROXY": "http://p:1", "TB_DOOR_DIRECT": "1"}) == ""
    assert cr.door_reach_problem({}) == ""


def test_the_vm_powers_off_at_once_without_code() -> None:
    vm = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")
    block = vm[vm.index('if [ ! -f "$TB/incoming/src.tgz" ]; then') : vm.index('mv -f "$TB/incoming/src.tgz"')]
    assert "TB-NO-CODE" in block and "systemctl poweroff" in block and "finish " not in block
    assert "tb-code-wait-minutes" in vm  # the wait is the existing setting, unchanged


def test_the_door_waits_are_bounded_by_the_clock() -> None:
    tls = (GCP / "door-tls.sh").read_text(encoding="utf-8")
    assert "--connect-timeout" in tls[tls.index("door_curl() {") : tls.index("door_firewall_check() {")]
    drv = (GCP / "complete-run.sh").read_text(encoding="utf-8")
    body = drv[drv.index("wait_door() {") : drv.index("collect_start() {")]
    assert "SECONDS" in body and "--max-time 30" in body


# ---------------------------------------------------------------- the fake cloud
def _fake(tmp: Path, *, status: str = "TERMINATED", secret: str = "ok", versions: str = "7") -> Path:
    """``secret``: ok, disabled, missing or denied (the answer of ``secrets describe``)."""
    bin_ = tmp / "bin"
    bin_.mkdir()
    (tmp / "enabled").write_text("\n".join(versions.split()) + "\n", encoding="utf-8")
    errs = {"disabled": "ERROR: (gcloud.secrets.describe) PERMISSION_DENIED: Secret Manager API has not been used in "
                        "project 123 before or it is disabled. reason: SERVICE_DISABLED",
            "missing": "ERROR: (gcloud.secrets.describe) NOT_FOUND: Secret [tb-gpu-door] not found",
            "denied": "ERROR: (gcloud.secrets.describe) PERMISSION_DENIED: Permission 'secretmanager.secrets.get' "
                      "denied"}  # fmt: skip
    vm = json.dumps({"name": "tb-gpu-sim", "tags": {"items": ["tb-gpu-door"]},
                     "networkInterfaces": [{"network": "projects/p/global/networks/default"}],
                     "serviceAccounts": [{"email": "vm@p.iam.gserviceaccount.com", "scopes": [
                         "https://www.googleapis.com/auth/cloud-platform"]}]})  # fmt: skip
    rules = json.dumps([{"name": "default-allow-http", "network": "projects/p/global/networks/default",
                         "direction": "INGRESS", "allowed": [{"IPProtocol": "tcp", "ports": ["80"]}],
                         "sourceRanges": ["0.0.0.0/0"]}])  # fmt: skip
    (bin_ / "gcloud").write_text(
        f"""#!/bin/bash
echo "$@" >> {tmp}/calls.log
case "$1 $2 $3" in
  "auth "*) echo token ;;
  "config get-value project") echo trialbox-demo ;;
  "config get-value account") echo trialbox-deployer@trialbox-demo.iam.gserviceaccount.com ;;
  "compute instances describe")
    case "$*" in *status*) echo {status} ;; *natIP*) echo 127.0.0.9 ;; *json*) echo '{vm}' ;; *) echo x ;; esac ;;
  "compute firewall-rules list") echo '{rules}' ;;
  "secrets describe "*) [ {secret} = ok ] && echo name || {{ echo "{errs.get(secret, "")}" >&2; exit 1; }} ;;
  "secrets get-iam-policy "*) echo '{{"bindings": []}}' ;;
  "secrets versions list") sed 's#^#projects/p/secrets/tb-gpu-door/versions/#' {tmp}/enabled | grep -v '/$' || true ;;
  "secrets versions destroy") grep -vx "$4" {tmp}/enabled > {tmp}/e2 || true; mv {tmp}/e2 {tmp}/enabled ;;
  "storage cp "*) [ -f {tmp}/results.tgz ] && cp {tmp}/results.tgz "${{!#}}" ;;
  *) true ;;
esac
""",
        encoding="utf-8",
    )
    (bin_ / "gcloud").chmod(stat.S_IRWXU)
    return bin_


def _env(tmp: Path, bin_: Path, **kw: str) -> dict[str, str]:
    key = tmp / "key.json"
    key.write_text("{}", encoding="utf-8")
    (tmp / "gc").mkdir(exist_ok=True)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", CLOUDSDK_CONFIG=str(tmp / "gc"), TB_SA_KEY_FILE=str(key),
               TB_COMPLETE_DIR=str(tmp / "out"), PY=PY, GC_TIMEOUT_S="20", **kw)  # fmt: skip
    for k in ("TB_ZONES", "TB_BUCKET", "TB_DOOR_DIRECT", "TB_ESTIMATE_LLM_SPEEDUP"):
        if k not in kw:
            env.pop(k, None)
    return env


def _run(tmp: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          check=False, timeout=600)  # fmt: skip


def test_a_launch_behind_a_proxy_without_a_bucket_starts_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path, _fake(tmp_path), HTTPS_PROXY="http://proxy.invalid:3128")
    r = _run(tmp_path, env, "--patients", "500", "--only", "scenario-gateway", "--no-wait")
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert r.returncode == 2 and "TB_BUCKET" in r.stderr, (r.stdout[-800:], r.stderr[-800:])
    assert "instances start" not in calls and "secrets versions add" not in calls
    dry = _run(tmp_path, dict(env, TB_COMPLETE_DIR=str(tmp_path / "dry")), "--dry-run", "--patients", "500", "--only",
               "scenario-gateway")  # fmt: skip
    assert dry.returncode == 0 and "# a launch would refuse here: door: HTTPS_PROXY is set" in dry.stdout


# ---------------------------------------------------------------- A7: the free pre-flight
def _pf(d: Path, **files: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    base = {"project.txt": "trialbox-demo", "account.txt": "trialbox-deployer@trialbox-demo.iam.gserviceaccount.com",
            "mode.txt": "door", "vms.txt": "tb-gpu-sim asia-east1-a\n"}  # fmt: skip
    for k, v in {**base, **files}.items():
        (d / k.replace("__", ".")).write_text(v, encoding="utf-8")
    return d


def test_the_preflight_names_every_problem_of_the_run_with_its_fix(tmp_path: Path) -> None:
    """The run's four failures at once: tcp:80 / no 443, the API off, (then) no secret, the deployer's viewer role."""
    vm = json.dumps({"serviceAccounts": [{"email": "vm@p.iam.gserviceaccount.com"}]})
    fw = "firewall rule default-allow-http opens tcp:80 to the VM ...\nno firewall rule opens tcp:443 to the VM ..."
    bad, _ = cr.preflight_problems(_pf(tmp_path / "a", **{"vm-tb-gpu-sim.json": vm, "firewall-tb-gpu-sim.txt": fw,
        "secret.err": "PERMISSION_DENIED ... reason: SERVICE_DISABLED"}))  # fmt: skip
    assert len(bad) == 3 and any("gcloud services enable secretmanager.googleapis.com --project trialbox-demo" in b
                                 for b in bad)  # fmt: skip
    assert sum("tcp:" in b for b in bad) == 2
    bad, _ = cr.preflight_problems(_pf(tmp_path / "b", **{"vm-tb-gpu-sim.json": vm,
                                                          "secret.err": "NOT_FOUND: Secret [tb-gpu-door] not found"}))  # fmt: skip
    assert bad and "gcloud secrets create tb-gpu-door" in bad[0]
    bad, _ = cr.preflight_problems(_pf(tmp_path / "c", **{"vm-tb-gpu-sim.json": vm,
                                                          "secret.err": "PERMISSION_DENIED: 'secretmanager.secrets.get'"}))  # fmt: skip
    assert bad and "--role=roles/secretmanager.viewer" in bad[0] and "serviceAccount:trialbox-deployer@" in bad[0]
    bad, _ = cr.preflight_problems(_pf(tmp_path / "d", **{"vm-tb-gpu-sim.err": "NOT_FOUND: instance not found"}))
    assert bad and "does not exist" in bad[0]
    bad, notes = cr.preflight_problems(_pf(tmp_path / "e", **{"vm-tb-gpu-sim.json": vm}))
    assert bad == [] and notes == []


def test_the_bucket_preflight_wants_both_accounts_on_the_bucket_and_no_stale_objects(tmp_path: Path) -> None:
    vm = json.dumps({"serviceAccounts": [{"email": "vm@p.iam.gserviceaccount.com"}]})
    dep = "serviceAccount:trialbox-deployer@trialbox-demo.iam.gserviceaccount.com"
    ok = json.dumps({"bindings": [{"role": "roles/storage.objectAdmin",
                                   "members": [dep, "serviceAccount:vm@p.iam.gserviceaccount.com"]}]})  # fmt: skip
    common = {"mode.txt": "bucket", "bucket.txt": "gs://tb-runs", "vm-tb-gpu-sim.json": vm}
    assert cr.preflight_problems(_pf(tmp_path / "ok", **common, **{"bucket-iam.json": ok}))[0] == []
    only_dep = json.dumps({"bindings": [{"role": "roles/storage.objectAdmin", "members": [dep]}]})
    bad, _ = cr.preflight_problems(_pf(tmp_path / "vm", **common, **{"bucket-iam.json": only_dep}))
    assert len(bad) == 1 and "serviceAccount:vm@p.iam.gserviceaccount.com has no objectAdmin on gs://tb-runs" in bad[0]
    bad, _ = cr.preflight_problems(
        _pf(tmp_path / "gone", **common, **{"bucket-ls.err": "BucketNotFoundException: 404"})
    )
    assert bad and "TB_BUCKET=gs://tb-runs bash deploy/gcp/setup-gcp.sh trialbox-demo" in bad[0]
    bad, _ = cr.preflight_problems(_pf(tmp_path / "unread", **common))
    assert bad and "policy is not readable" in bad[0]
    stale = {"bucket-iam.json": ok, "run-id.txt": "R1", "bucket-stale.txt": "gs://tb-runs/runs/R1-s1/src.tgz\n"}
    bad, _ = cr.preflight_problems(_pf(tmp_path / "stale", **common, **stale))
    assert bad and "gcloud storage rm -r 'gs://tb-runs/runs/R1-s*'" in bad[0]


def test_preflight_reads_only_and_says_everything_at_once(tmp_path: Path) -> None:
    env = _env(tmp_path, _fake(tmp_path, secret="disabled"))
    r = _run(tmp_path, env, "--preflight")
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert r.returncode == 6, (r.stdout[-800:], r.stderr[-800:])
    assert "secretmanager.googleapis.com" in r.stderr and "opens tcp:80" in r.stderr and "tcp:443" in r.stderr
    for write in ("instances start", "set-scheduling", "versions add", "add-metadata", "storage cp"):
        assert write not in calls
    assert not (tmp_path / "out").exists()  # no run folder for a pre-flight
    dry = _run(tmp_path, dict(env, TB_BUCKET="gs://b"), "--preflight", "--dry-run")
    assert dry.returncode == 0 and "gcloud storage buckets get-iam-policy gs://b" in dry.stdout


def test_setup_gcp_grants_the_viewer_role_and_makes_the_bucket() -> None:
    s = (GCP / "setup-gcp.sh").read_text(encoding="utf-8")
    assert "--role=roles/secretmanager.viewer" in s
    assert 'gcloud storage buckets create "$TB_BUCKET"' in s and "--role=roles/storage.objectAdmin" in s


# ---------------------------------------------------------------- A8: the door's version after a collect
def _collect_run(tmp: Path, tag: str = "scenario-it-dump") -> None:
    out = tmp / "out"
    sh = out / "shard-1"
    sh.mkdir(parents=True)
    shard = {"shard": 1, "vm": "tb-gpu-sim", "zone": "asia-east1-a", "tags": [tag], "rows": [], "hours": 1.0,
             "usd": 2.74, "cap_hours": 2, "cap_usd": 5.48}  # fmt: skip
    plan = {"vms": 1, "shards": [shard], "wall_hours": 1.0, "hours": 1.0, "usd": 2.74, "cap_usd": 5.48}
    (out / "plan.json").write_text(json.dumps({"patients": 500, "parts": ["g1"], "only": [tag], "plan": plan}),
                                   encoding="utf-8")  # fmt: skip
    for f, v in (("tb-key", "k"), ("door.crt", "c"), ("door.pin", "p"), ("door-version", "7"),
                 ("door-versions", "6\n7")):  # fmt: skip
        (sh / f).write_text(v, encoding="utf-8")
    res = {"stages": [{"name": "s", "ok": True, "seconds": 0, "checks": [["c", True, ""]]}],
           "run": {"id": "R1-s1", "head": HEAD}}  # fmt: skip
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        body = json.dumps(res).encode()
        info = tarfile.TarInfo(f"parts/{tag}.json")
        info.size = len(body)
        t.addfile(info, io.BytesIO(body))
    (tmp / "results.tgz").write_bytes(buf.getvalue())


def test_a_collect_with_every_part_in_destroys_the_runs_versions_while_the_vm_runs(tmp_path: Path) -> None:
    """Through the bucket, the VM still RUNNING (its grace): before, version 7 (and 6, a retried add's) stayed."""
    _collect_run(tmp_path)
    env = _env(tmp_path, _fake(tmp_path, status="RUNNING", versions="3 6 7"), TB_BUCKET="gs://tb-runs")
    r = _run(tmp_path, env, "--collect", "R1")
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "secrets versions destroy 7 --secret tb-gpu-door" in calls, (r.stdout[-1500:], r.stderr[-800:])
    assert "secrets versions destroy 6 --secret tb-gpu-door" in calls and "destroy 3 " not in calls
    assert "door secret tb-gpu-door: enabled version(s) 3 remain" in r.stdout
    rep = (tmp_path / "out" / "report" / "report.md").read_text(encoding="utf-8")
    assert "Door secret after the collect (T-119): door secret tb-gpu-door: enabled version(s) 3 remain" in rep
    assert not (tmp_path / "out" / "shard-1" / "tb-key").exists()


def test_a_collect_says_no_enabled_version_and_a_stop_destroys_the_runs(tmp_path: Path) -> None:
    _collect_run(tmp_path)
    env = _env(tmp_path, _fake(tmp_path, status="RUNNING", versions="7"), TB_BUCKET="gs://tb-runs")
    r = _run(tmp_path, env, "--collect", "R1")
    assert "door secret tb-gpu-door: no enabled version" in r.stdout, (r.stdout[-1500:], r.stderr[-800:])
    stop = tmp_path / "stop"
    stop.mkdir()
    _collect_run(stop)
    env = _env(stop, _fake(stop, versions="6 7"))
    r = _run(stop, env, "--stop", "--collect", "R1")
    calls = (stop / "calls.log").read_text(encoding="utf-8")
    assert r.returncode == 0 and "instances stop" in calls and "secrets versions destroy 7" in calls
    assert "door secret tb-gpu-door: no enabled version" in r.stdout


def test_a_retried_add_is_destroyed_too() -> None:
    """``gc`` retries a timed-out ``versions add``: the versions enabled after it and not before are this VM's."""
    drv = (GCP / "complete-run.sh").read_text(encoding="utf-8")
    add = drv[drv.index("door_secret_add() {") : drv.index("door_enabled() {")]
    assert "door_enabled > " in add and "comm -13" in add and "door-versions" in add and "flock" in add
    retire = drv[drv.index("door_retire() {") : drv.index("door_versions_left() {")]
    assert "door-versions" in retire
