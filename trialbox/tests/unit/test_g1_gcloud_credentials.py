"""G1 bug A2: the gcloud credentials expired during a long run.

The launch of attempt 2 failed with "Request had invalid authentication credentials", and a later ``--collect`` hung
past 10 minutes on the same error (``rc=124`` from the operator's ``timeout 600``). Now the driver activates the
service account itself from ``TB_SA_KEY_FILE`` (its path, given to gcloud; the driver never reads the file) at the
start of every command, and every gcloud call has a timeout and fails fast with "credentials expired: re-activate".

A fake ``gcloud`` on PATH stands in for the cloud: nothing here touches GCP."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import time
from pathlib import Path

GCP = Path(__file__).resolve().parents[2] / "deploy" / "gcp"
ROOT = GCP.parents[1]
SECRET = "SECRET-KEY-MATERIAL"


def _fake_gcloud(tmp: Path, activate_rc: int, token: str, compute: str) -> Path:
    """``token``/``compute``: ``ok``, ``error`` (the auth error at once) or ``hang`` (waits, as the G1 collect did)."""
    bin_ = tmp / "bin"
    bin_.mkdir()
    log = tmp / "calls.log"
    err = "ERROR: (gcloud) Request had invalid authentication credentials. Expected OAuth 2 access token"
    (bin_ / "gcloud").write_text(f"""#!/bin/sh
echo "$@" >> {log}
act() {{ case "$1" in ok) echo "$2"; exit 0 ;; error) echo "{err}" >&2; exit 1 ;; *) exec sleep 600 ;; esac; }}
case "$1 $2" in
  "auth activate-service-account")
    [ {activate_rc} = 0 ] && exit 0
    echo "ERROR: (gcloud.auth.activate-service-account) invalid_grant: Invalid JWT Signature." >&2; exit 1 ;;
  "auth print-access-token") act {token} fake-token ;;
  *) act {compute} TERMINATED ;;
esac
""", encoding="utf-8")  # fmt: skip
    (bin_ / "gcloud").chmod(stat.S_IRWXU)
    return bin_


def _plan(out: Path) -> None:
    shard = {"shard": 1, "vm": "tb-gpu-sim", "zone": "asia-east1-a", "tags": ["scenario-it-dump"], "rows": [],
             "hours": 1.0, "usd": 2.74, "cap_hours": 2, "cap_usd": 5.48}  # fmt: skip
    plan = {"vms": 1, "shards": [shard], "wall_hours": 1.0, "hours": 1.0, "usd": 2.74, "cap_usd": 5.48}
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan.json").write_text(json.dumps({"patients": 500, "price_per_hour": 2.74, "parts": ["g1"],
                                               "only": ["scenario-it-dump"], "plan": plan}), encoding="utf-8")  # fmt: skip


def _driver(tmp: Path, *args: str, limit: float = 90, **fake: str | int) -> tuple[int, str, float]:
    bin_ = _fake_gcloud(tmp, int(fake.get("activate_rc", 0)), str(fake.get("token", "ok")),
                        str(fake.get("compute", "ok")))  # fmt: skip
    key = tmp / "key.json"
    key.write_text(f'{{"private_key": "{SECRET}"}}', encoding="utf-8")
    (tmp / "gc").mkdir()
    _plan(tmp / "out")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", CLOUDSDK_CONFIG=str(tmp / "gc"),
               TB_SA_KEY_FILE=str(key), TB_COMPLETE_DIR=str(tmp / "out"), PY=str(ROOT / ".venv" / "bin" / "python"))  # fmt: skip
    env.pop("TB_ZONES", None)
    t0 = time.monotonic()
    p = subprocess.Popen([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, start_new_session=True)  # fmt: skip
    try:
        out, _ = p.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        out += f"\n[still running after {limit} s: killed]"
    assert SECRET not in out  # the key file's content is never printed
    return p.returncode, out, time.monotonic() - t0


def test_collect_with_an_expired_token_fails_fast_and_says_so(tmp_path: Path) -> None:
    rc, out, took = _driver(tmp_path, "--collect", "R1", activate_rc=1, token="error", compute="hang")
    assert took < 60, out[-800:]
    assert rc != 0 and "credentials expired: re-activate" in out, out[-800:]
    assert "instances describe" not in (tmp_path / "calls.log").read_text(encoding="utf-8")  # nothing else was tried


def test_a_token_that_hangs_fails_within_the_timeout(tmp_path: Path) -> None:
    rc, out, took = _driver(tmp_path, "--collect", "R1", token="hang", compute="hang")
    assert took < 60, out[-800:]
    assert rc != 0 and "credentials expired: re-activate" in out, out[-800:]


def test_every_command_activates_from_the_key_files_path_first(tmp_path: Path) -> None:
    for i, args in enumerate((["--collect", "R1"], ["--stop", "--collect", "R1"])):
        d = tmp_path / str(i)
        d.mkdir()
        rc, out, _ = _driver(d, *args)
        calls = (d / "calls.log").read_text(encoding="utf-8").splitlines()
        assert calls[0] == f"auth activate-service-account --key-file {d / 'key.json'} --quiet", calls[:3]
        assert calls[1] == "auth print-access-token", calls[:3]
        assert rc == 0, out[-800:]


def test_a_shard_child_activates_too(tmp_path: Path) -> None:
    (tmp_path / "out" / "shard-1").mkdir(parents=True, exist_ok=True)
    _driver(tmp_path, "--collect", "R1", "--shard", "1")
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("auth activate-service-account --key-file "), calls[:3]


def test_a_gcloud_call_that_hangs_with_good_credentials_is_cut_by_its_timeout(tmp_path: Path) -> None:
    script = (f". {GCP / 'gcloud-auth.sh'}; GC_TIMEOUT_S=2; gc compute instances describe vm "
              "'--format=value(status)'")  # fmt: skip
    bin_ = _fake_gcloud(tmp_path, 0, "ok", "hang")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", TB_SA_KEY_FILE=str(tmp_path / "key.json"))
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert time.monotonic() - t0 < 30 and r.returncode != 0
    assert "timed out after 2 s" in r.stderr and "credentials expired" not in r.stderr, r.stderr
