# ruff: noqa: F811 - the console fixture box is imported from test_console_app and taken by name
"""The small demo VM of 2026-11-17 (deploy/gcp/demo-vm.sh, demo_vm.py, demo-vm-boot.sh; runbook 11).

The owner approved "a small VM with TLS in front, reachable by me and my guest, no real-model mode". These tests drive
the real scripts against a fake ``gcloud`` on PATH (as tests/rehearsal/driver-shims/gcloud does): nothing touches GCP.
They hold: the estimate's arithmetic from the declared prices; a dry run prints and runs nothing; the refusals (the
world, an empty allow list, the default gcloud config, a real-model setting, a GPU, a public-certificate host name);
the firewall rule has exactly the given ranges and tcp:443 and nothing else is opened; no secret value reaches the
output or the fake gcloud's argv; ``down`` waits for TERMINATED; the VM's boot script fixes the stub model, refuses a
secret in the metadata, binds :443 only with ``tls internal`` and arms the hard stop."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_console_app import box  # noqa: F401 - the console fixture, by name

GCP = Path(__file__).resolve().parents[2] / "deploy" / "gcp"
ROOT = GCP.parents[1]
DRIVER = GCP / "demo-vm.sh"
BOOT = GCP / "demo-vm-boot.sh"
KEY_CONTENT = "SENTINEL-PRIVATE-KEY-MATERIAL"
PASSWORD = "SENTINEL-DEMO-PASSWORD-xyz"
ALLOW = "1.2.3.4/32,5.6.7.0/24"
DIGEST = "europe-docker.pkg.dev/p/tb/demo@sha256:" + "a" * 64

FAKE = r"""#!/bin/bash
# the fake gcloud of test_g1_demo_vm.py: every call logged (one line each, %q-quoted), a little state in $S
S=${FAKE_STATE:?}
{ printf '%q ' "$@"; echo; } >> "$S/argv.log"
nf() { echo "ERROR: (gcloud.$1) The resource '$2' was not found" >&2; exit 1; }
fmt=""; for a in "$@"; do case "$a" in --format=*) fmt=${a#--format=} ;; esac; done
case "$1 $2 $3" in
  "auth activate-service-account"*) exit 0 ;;
  "auth print-access-token"*) echo fake-token ;;
  "config get-value project") echo fake-project ;;
  "secrets versions list") [ -f "$S/no-version" ] || echo "projects/fake/secrets/$4/versions/3" ;;
  "secrets versions access") cat "$S/secret-value" ;;   # the scripts must never call this here
  "compute instances describe")
    [ -f "$S/status" ] || nf compute.instances.describe "$4"
    case "$fmt" in
      *natIP*) echo 34.80.0.10 ;;
      *status*)
        n=$(cat "$S/stopping" 2>/dev/null || echo 0)
        if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$S/stopping"; echo STOPPING; else cat "$S/status"; fi ;;
      *) echo "43200 STOP" ;;
    esac ;;
  "compute instances create") echo RUNNING > "$S/status" ;;
  "compute instances start") echo RUNNING > "$S/status" ;;
  "compute instances stop")
    if [ -f "$S/never-stops" ]; then echo RUNNING > "$S/status"; else echo TERMINATED > "$S/status"; fi ;;
  "compute instances delete") rm -f "$S/status" ;;
  "compute instances add-metadata" | "compute instances set-scheduling") true ;;
  "compute instances get-serial-port-output") printf 'TB-DEMO-VM 10:00:00 ready https://34.80.0.10/\nDEMO-VM-READY\n' ;;
  "compute networks describe") [ -f "$S/net-$4" ] || nf compute.networks.describe "$4" ;;
  "compute networks create") touch "$S/net-$4" ;;
  "compute networks delete") rm -f "$S/net-$4" ;;
  "compute networks subnets")
    case "$4" in
      describe) [ -f "$S/subnet-$5" ] || nf compute.subnetworks.describe "$5" ;;
      create) touch "$S/subnet-$5" ;;
      delete) rm -f "$S/subnet-$5" ;;
    esac ;;
  "compute firewall-rules describe") [ -f "$S/fw-$4" ] || nf compute.firewalls.describe "$4"
    printf 'sourceRanges:\n- %s\n' "$(cat "$S/fw-$4")" ;;
  "compute firewall-rules create" | "compute firewall-rules update")
    for a in "$@"; do case "$a" in --source-ranges=*) echo "${a#--source-ranges=}" > "$S/fw-$4" ;; esac; done ;;
  "compute firewall-rules delete") rm -f "$S/fw-$4" ;;
  "compute firewall-rules list") for f in "$S"/fw-*; do [ -f "$f" ] && basename "$f" | sed 's/^fw-//'; done; true ;;
  *) echo "fake gcloud: not faked: $*" >&2; exit 1 ;;
esac
"""


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    state = tmp / "state"
    bin_ = tmp / "bin"
    if not bin_.exists():
        bin_.mkdir()
        state.mkdir()
        (bin_ / "gcloud").write_text(FAKE, encoding="utf-8")
        (bin_ / "gcloud").chmod(stat.S_IRWXU)
        (state / "secret-value").write_text(PASSWORD, encoding="utf-8")
        (tmp / "gc").mkdir()
        (tmp / "key.json").write_text(f'{{"private_key": "{KEY_CONTENT}"}}', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "CLOUDSDK_", "GC_"))}
    env.update(
        PATH=f"{bin_}:{os.environ['PATH']}",
        FAKE_STATE=str(state),
        CLOUDSDK_CONFIG=str(tmp / "gc"),
        TB_SA_KEY_FILE=str(tmp / "key.json"),
        TB_DEMO_ALLOW=ALLOW,
        TB_DEMO_VM_IMAGE=DIGEST,
        TB_DEMO_PASSWORD=PASSWORD,  # in the operator's shell by mistake: it must go nowhere
        PY=str(ROOT / ".venv" / "bin" / "python"),
    )
    env.update(extra)
    return env


def _run(tmp: Path, *args: str, env: dict[str, str] | None = None, **extra: str) -> tuple[int, str]:
    e = env if env is not None else _env(tmp, **extra)
    p = subprocess.run([str(DRIVER), *args], check=False, cwd=ROOT, env=e, capture_output=True, text=True, timeout=120)
    out = p.stdout + p.stderr
    for secret in (KEY_CONTENT, PASSWORD):
        assert secret not in out, f"a secret value in the output of {args}"
    return p.returncode, out


def _argv(tmp: Path) -> list[str]:
    log = tmp / "state" / "argv.log"
    raw = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    lines = [" ".join(shlex.split(line)) + " " for line in raw]  # the fake logs each argument %q-quoted
    for line in lines:
        assert KEY_CONTENT not in line and PASSWORD not in line, line
        assert "secrets versions access" not in line, "the driver read the password"
    return lines


# --------------------------------------------------------------------------------------------- the estimate


def _estimate(tmp: Path, **extra: str) -> tuple[int, str]:
    return _run(tmp, "--estimate", env=_env(tmp, **extra))


def test_estimate_arithmetic_from_the_declared_prices(tmp_path: Path) -> None:
    rc, out = _estimate(tmp_path)
    assert rc == 0, out
    disk_h = 30 * 0.11 / 730
    run_h = 0.1528 + disk_h + 0.005
    assert "e2-standard-4 in asia-east1-a" in out and "no GPU" in out
    assert f"per hour          US$ {run_h:8.4f}" in out
    assert f"per day (24 h)    US$ {run_h * 24:8.2f}" in out
    assert f"per week (168 h)  US$ {run_h * 168:8.2f}" in out
    assert f"at most US$ {run_h * 12:.2f}" in out
    assert f"per day           US$ {disk_h * 24:8.2f}" in out and f"per week          US$ {disk_h * 168:8.2f}" in out
    assert "30 GB pd-balanced" in out
    assert "price source" in out and "price date" in out and "unchecked" in out
    assert "WARNS ONCE" in out  # which TLS mode gives a browser warning is said plainly
    assert _argv(tmp_path) == []  # the estimate calls no gcloud


def test_estimate_follows_the_settings_and_wants_a_price_for_another_machine(tmp_path: Path) -> None:
    rc, out = _estimate(
        tmp_path,
        TB_DEMO_VM_PRICE_HOUR="1.0",
        TB_DEMO_VM_DISK_GB="73",
        TB_DEMO_VM_DISK_PRICE_GB_MONTH="1.0",
        TB_DEMO_VM_IP_PRICE_HOUR="0",
        TB_DEMO_VM_HOURS="3",
        TB_DEMO_VM_PRICE_SOURCE="pricing page",
        TB_DEMO_VM_PRICE_DATE="2026-11-14",
    )
    assert rc == 2 and "TB_DEMO_VM_IP_PRICE_HOUR must be above 0" in out
    rc, out = _estimate(
        tmp_path, TB_DEMO_VM_PRICE_HOUR="1.0", TB_DEMO_VM_DISK_GB="73", TB_DEMO_VM_DISK_PRICE_GB_MONTH="1.0",
        TB_DEMO_VM_IP_PRICE_HOUR="0.5", TB_DEMO_VM_HOURS="3", TB_DEMO_VM_PRICE_SOURCE="pricing page",
        TB_DEMO_VM_PRICE_DATE="2026-11-14",
    )  # fmt: skip
    assert rc == 0, out
    assert "per hour          US$   1.6000" in out  # 1.0 + 73 x 1.0 / 730 + 0.5
    assert "at most US$ 4.80" in out and "pricing page" in out and "2026-11-14" in out
    rc, out = _estimate(tmp_path, TB_DEMO_VM_MACHINE="e2-standard-8")
    assert rc == 2 and "no declared price for e2-standard-8" in out


# --------------------------------------------------------------------------------------------- the refusals


@pytest.mark.parametrize(
    ("extra", "why"),
    [
        ({"TB_DEMO_ALLOW": "0.0.0.0/0"}, "whole internet"),
        ({"TB_DEMO_ALLOW": "1.2.3.4/32,0.0.0.0/0"}, "whole internet"),
        ({"TB_DEMO_ALLOW": ""}, "TB_DEMO_ALLOW is empty"),
        ({"TB_DEMO_ALLOW": " , "}, "TB_DEMO_ALLOW is empty"),
        ({"TB_DEMO_ALLOW": "0.0.0.0/1,128.0.0.0/1"}, "broader than /16"),
        ({"TB_DEMO_ALLOW": "10.0.0.0/24"}, "not a public range"),
        ({"TB_DEMO_ALLOW": "1.2.3.4/24"}, "host bits"),
        ({"TB_DEMO_ALLOW": "2001:db8::/48"}, "IPv6"),
        ({"TB_LLM_MODE": "vllm"}, "stub model only"),
        ({"TB_LLM_MODE": "openai"}, "stub model only"),
        ({"TB_DEMO_VM_MACHINE": "g4-standard-48", "TB_DEMO_VM_PRICE_HOUR": "2.74"}, "never has a GPU"),
        ({"TB_DEMO_VM_MACHINE": "a2-highgpu-1g", "TB_DEMO_VM_PRICE_HOUR": "3.7"}, "never has a GPU"),
        ({"TB_DEMO_VM_HOST": "demo.example.org"}, "not built"),
        ({"TB_DEMO_VM_HOURS": "0"}, "TB_DEMO_VM_HOURS must be a whole number from 1"),
        ({"TB_DEMO_VM_HOURS": "2.5"}, "TB_DEMO_VM_HOURS must be a whole number from 1"),
        ({"TB_DEMO_VM_IMAGE": ""}, "TB_DEMO_VM_IMAGE is not set"),
        ({"TB_DEMO_VM_IMAGE": "trialbox-demo:latest"}, "by digest"),
        ({"TB_DEMO_VM_IMAGE": "gs://b-x/trialbox-demo.tar.gz"}, "TB_DEMO_VM_IMAGE_SHA256"),
    ],
)
def test_up_refuses_before_any_gcloud_call(tmp_path: Path, extra: dict[str, str], why: str) -> None:
    rc, out = _run(tmp_path, "up", "--yes", env=_env(tmp_path, **extra))
    assert rc == 2, out
    assert why in out, out
    assert _argv(tmp_path) == []


def test_the_default_or_no_gcloud_config_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for cmd in ("up", "status", "down", "delete"):
        args = (cmd, "--yes") if cmd in ("up", "delete") else (cmd,)
        e = _env(tmp_path, HOME=str(home), CLOUDSDK_CONFIG=str(home / ".config" / "gcloud"))
        rc, out = _run(tmp_path, *args, env=e)
        assert rc == 2 and "must be private" in out, out
        e.pop("CLOUDSDK_CONFIG")
        rc, out = _run(tmp_path, *args, env=e)
        assert rc != 0 and "CLOUDSDK_CONFIG" in out, out
    assert _argv(tmp_path) == []


def test_a_dry_run_prints_every_command_and_runs_none(tmp_path: Path) -> None:
    for args in (("--dry-run",), ("--dry-run", "up"), ("up",), ("--dry-run", "down"), ("--dry-run", "delete"),
                 ("delete",), ("--dry-run", "status")):  # fmt: skip
        rc, out = _run(tmp_path, *args)
        assert rc == 0, (args, out)
        assert "+ gcloud" in out
    assert _argv(tmp_path) == []  # the fake gcloud was never called
    rc, out = _run(tmp_path, "--dry-run")
    for want in (
        "auth activate-service-account",
        "config get-value project",
        "secrets versions list tb-demo-password",
        "compute networks create tb-demo-vm-net --subnet-mode=custom",
        "compute firewall-rules create tb-demo-vm-https",
        f"--source-ranges={ALLOW}",
        "compute instances create tb-demo-vm --zone asia-east1-a --machine-type e2-standard-4",
        "--max-run-duration 12h --instance-termination-action STOP",
    ):
        assert want in out, want
    assert "--accelerator" not in out and "tcp:80" not in out and "tcp:22" not in out


# --------------------------------------------------------------------------------------------- TB_DEMO_ALLOW=any

OPEN_TEXT = "open to any address; the sign-in password is the only gate"


@pytest.mark.parametrize("word", ["any", " any ", "ANY"])
def test_any_opens_one_rule_tcp_443_from_the_world_and_nothing_else(tmp_path: Path, word: str) -> None:
    """The owner's ruling of 2026-11-15: the demo is a PoC with synthetic data only, reachable from any address and
    kept by the sign-in password and TLS alone. Only the explicit word does it; the one rule is still tcp:443."""
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_ALLOW=word)
    assert rc == 0, out
    assert OPEN_TEXT in out and "owner's ruling of 2026-11-15" in out
    calls = _argv(tmp_path)
    rules = [c for c in calls if c.startswith(("compute firewall-rules create", "compute firewall-rules update"))]
    assert len(rules) == 1, calls
    assert "--rules=tcp:443 " in rules[0] and "--source-ranges=0.0.0.0/0 " in rules[0]
    assert "--direction INGRESS" in rules[0] and "--action ALLOW" in rules[0] and "--target-tags tb-demo-vm" in rules[0]
    assert not any(re.search(r"tcp:(80|22|3389)\b|--accelerator|--rules=(all|tcp)(?!:443)", c) for c in calls)
    assert (tmp_path / "state" / "fw-tb-demo-vm-https").read_text().strip() == "0.0.0.0/0"


@pytest.mark.parametrize(
    ("allow", "why"),
    [
        ("any,1.2.3.4/32", "stands alone"),
        ("1.2.3.4/32, any", "stands alone"),
        ("anything", "not an IPv4 address"),
        ("0.0.0.0/0", "write the word any"),
    ],
)
def test_any_is_only_the_word_alone(tmp_path: Path, allow: str, why: str) -> None:
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_ALLOW=allow)
    assert rc == 2 and why in out, out
    assert _argv(tmp_path) == []


def test_a_missing_allow_is_still_refused(tmp_path: Path) -> None:
    e = _env(tmp_path)
    e.pop("TB_DEMO_ALLOW")
    for args in (("up", "--yes"), ("--dry-run",)):
        rc, out = _run(tmp_path, *args, env=e)
        assert rc == 2 and "TB_DEMO_ALLOW is empty" in out, out
    assert _argv(tmp_path) == []


def test_the_plan_and_status_say_the_open_mode_plainly(tmp_path: Path) -> None:
    rc, out = _run(tmp_path, "--dry-run", "up", TB_DEMO_ALLOW="any")
    assert rc == 0 and OPEN_TEXT in out and "--source-ranges=0.0.0.0/0" in out, out
    assert "https from any address" in out  # the rule's own description says it too
    rc, out = _run(tmp_path, "--dry-run", "status")
    assert rc == 0 and OPEN_TEXT in out, out
    assert _run(tmp_path, "up", "--yes", TB_DEMO_ALLOW="any")[0] == 0
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and f"reach: {OPEN_TEXT}" in out, out
    # the address lock reads differently, and its plan never says open
    assert _run(tmp_path, "up", "--yes")[0] == 0
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and OPEN_TEXT not in out and "reach: the ranges above only" in out, out
    rc, out = _run(tmp_path, "--dry-run", "up")
    assert rc == 0 and OPEN_TEXT not in out and f"tcp:443 from {ALLOW} only" in out, out


# --------------------------------------------------------------------------------------------- up, status, down


def test_up_makes_one_rule_tcp_443_from_exactly_the_given_ranges(tmp_path: Path) -> None:
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_ALLOW="1.2.3.4, 5.6.7.0/24 ,1.2.3.4/32")
    assert rc == 0, out
    calls = _argv(tmp_path)
    fw = [c for c in calls if c.startswith("compute firewall-rules create")]
    assert len(fw) == 1, calls
    rule = fw[0]
    assert "--rules=tcp:443 " in rule and f"--source-ranges={ALLOW} " in rule
    assert "--direction INGRESS" in rule and "--target-tags tb-demo-vm" in rule and "--network tb-demo-vm-net" in rule
    # nothing else opens a port: no other rule, no default network, no port 80 or 22 anywhere
    assert not any("firewall-rules" in c and "create" in c and c != rule for c in calls)
    assert not any(re.search(r"tcp:(80|22)\b|0\.0\.0\.0/0|--network default|--accelerator", c) for c in calls)
    create = [c for c in calls if c.startswith("compute instances create")]
    assert len(create) == 1
    vm = create[0]
    for want in ("--machine-type e2-standard-4", "--zone asia-east1-a", "--subnet tb-demo-vm-subnet",
                 "--max-run-duration 12h", "--instance-termination-action STOP", "--provisioning-model STANDARD",
                 "startup-script=" + str(BOOT), f"tb-demo-image={DIGEST}", "tb-demo-hours=12",
                 "tb-demo-password-secret=tb-demo-password"):  # fmt: skip
        assert want in vm, want
    assert "password=" not in vm.replace("password-secret=", "")  # the metadata names the secret, never a value
    # the order: auth first, the network before its rule, the rule before the VM
    order = [next(i for i, c in enumerate(calls) if c.startswith(p)) for p in
             ("auth activate-service-account", "compute networks create", "compute networks subnets create",
              "compute firewall-rules create", "compute instances create")]  # fmt: skip
    assert order == sorted(order), calls
    assert "--key-file " + str(tmp_path / "key.json") in calls[0]
    assert "https://34.80.0.10/" in out and "warns once" in out


def test_up_again_narrows_the_rule_to_the_new_ranges_and_starts_a_stopped_vm(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    assert _run(tmp_path, "down")[0] == 0
    (tmp_path / "state" / "argv.log").unlink()
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_ALLOW="9.9.9.9/32")
    assert rc == 0, out
    calls = _argv(tmp_path)
    assert any(c.startswith("compute firewall-rules update tb-demo-vm-https --rules=tcp:443 --source-ranges=9.9.9.9/32")
               for c in calls), calls  # fmt: skip
    assert (tmp_path / "state" / "fw-tb-demo-vm-https").read_text().strip() == "9.9.9.9/32"
    assert not any(c.startswith(("compute instances create", "compute networks create")) for c in calls)
    i_sched = next(i for i, c in enumerate(calls) if c.startswith("compute instances set-scheduling"))
    i_start = next(i for i, c in enumerate(calls) if c.startswith("compute instances start"))
    assert i_sched < i_start and "--max-run-duration 12h" in calls[i_sched]


def test_up_refuses_when_the_password_secret_has_no_version(tmp_path: Path) -> None:
    _env(tmp_path)
    (tmp_path / "state" / "no-version").touch()
    rc, out = _run(tmp_path, "up", "--yes")
    assert rc == 3 and "has no version" in out
    assert not any(c.startswith("compute ") and "describe" not in c for c in _argv(tmp_path))


def test_up_refuses_a_network_with_another_rule(tmp_path: Path) -> None:
    _env(tmp_path)
    (tmp_path / "state" / "fw-tb-demo-vm-allow-ssh").write_text("0.0.0.0/0")  # someone added SSH by hand
    rc, out = _run(tmp_path, "up", "--yes")
    assert rc == 3 and "other firewall rules (tb-demo-vm-allow-ssh" in out, out
    assert not any(c.startswith("compute instances create") for c in _argv(tmp_path))


def test_down_stops_and_waits_for_terminated(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    (tmp_path / "state" / "stopping").write_text("2")  # two describes say STOPPING first
    rc, out = _run(tmp_path, "down", TB_DEMO_VM_STOP_WAIT_S="30")
    assert rc == 0, out
    assert "TERMINATED" in out
    calls = _argv(tmp_path)
    i_stop = max(i for i, c in enumerate(calls) if c.startswith("compute instances stop"))
    after = [c for c in calls[i_stop:] if c.startswith("compute instances describe")]
    assert after, "down did not check the status after the stop"


def test_down_fails_when_the_vm_does_not_reach_terminated(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    (tmp_path / "state" / "never-stops").touch()
    rc, out = _run(tmp_path, "down", TB_DEMO_VM_STOP_WAIT_S="10")
    assert rc == 3 and "not TERMINATED" in out, out


def test_down_never_says_stopped_when_the_status_cannot_be_read(tmp_path: Path) -> None:
    e = _env(tmp_path)
    (tmp_path / "bin" / "gcloud").write_text(
        FAKE.replace('"compute instances describe")', '"compute instances describe") echo "ERROR: 503" >&2; exit 1;;\n  "x y z")'),
        encoding="utf-8",
    )  # fmt: skip
    rc, out = _run(tmp_path, "down", env=e)
    assert rc == 3 and "cannot be read" in out, out


def test_status_and_delete(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "RUNNING" in out and "DEMO-VM-READY" in out and "https://34.80.0.10/" in out
    assert "1.2.3.4/32,5.6.7.0/24" in out
    rc, out = _run(tmp_path, "delete", "--yes")
    assert rc == 0, out
    assert not [p.name for p in (tmp_path / "state").iterdir() if p.name.startswith(("net-", "subnet-", "fw-"))]
    assert not (tmp_path / "state" / "status").exists()
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "NONE" in out


# --------------------------------------------------------------------------------------------- the VM's boot script


def _boot(tmp: Path, *args: str, **md: str) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_MD_")}
    env.update(
        TB_MD_EXTERNAL_IP="34.80.0.10",
        TB_MD_TB_DEMO_IMAGE=DIGEST,
        TB_MD_TB_DEMO_HOURS="12",
        TB_MD_TB_DEMO_PASSWORD_SECRET="tb-demo-password",
        TB_MD_TB_DEMO_LANG="ja",
    )
    env.update(md)
    p = subprocess.run(["bash", str(BOOT), *args], check=False, env=env, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def test_boot_dry_run_fixes_the_stub_model_and_arms_the_hard_stop(tmp_path: Path) -> None:
    rc, out = _boot(tmp_path, "--dry-run")
    assert rc == 0, out
    assert "TB_LLM_MODE=stub" in out and "TB_DEMO_TOOL=demo" in out and "TB_CONSOLE_SECURE_COOKIE=1" in out
    assert "+ shutdown -P +720" in out
    assert out.index("shutdown -P") < out.index("apt-get")  # armed before anything that could hang
    assert "-p 127.0.0.1:8080:8080" in out  # the console only behind Caddy
    assert "secrets versions access latest --secret=tb-demo-password" in out and "never printed" in out
    assert "--env-file /etc/tb-demo-vm/secret.env" in out
    assert "docker.io" in out and "get.docker.com" not in out
    assert "DEMO-VM-DRY-RUN-DONE" in out


def test_boot_seeds_with_demo_mode_off_and_turns_it_on_before_caddy_opens_443(tmp_path: Path) -> None:
    """Deep review CON-DEMO-2 wants the hosted demo in demo mode (banner, uploads refused). Lane G's rehearsal of
    2026-11-14: with TB_DEMO_MODE=on in the container the demo's own seed was refused (its protocol paste, POST
    /pilot/protocol, is a guarded route: 403) and the container restarted 14 times in 19 minutes. So the container
    seeds with the flag off, the boot switches it on once the seed answers on the loopback, and only then starts Caddy:
    nobody outside reaches the console before demo mode is on. The container never restarts by itself (a restart
    would reseed with demo mode off)."""
    from console import demo_guard as dg
    from tb_common.flags import DECLARED

    # why: the seed's first paste is a route demo mode refuses, whatever its encoding
    assert dg.guarded("POST", "/pilot/protocol", "application/x-www-form-urlencoded")
    rc, out = _boot(tmp_path, "--dry-run")
    assert rc == 0, out
    flag = DECLARED["demo.mode"]
    assert flag.seed_env == "TB_DEMO_MODE" and "on" in flag.values
    assert f"{flag.seed_env}=" not in out  # never seeded on in the seeding process
    run_demo = out.index("docker run -d --name tb-demo ")
    seeded = out.index("http://127.0.0.1:8080/login (the seed")
    switch = out.index("docker exec -i tb-demo python - http://127.0.0.1:8080 < (demo-vm-boot.sh --print-demo-switch)")
    caddy = out.index("docker run -d --name tb-demo-caddy")
    assert run_demo < seeded < switch < caddy, out
    assert out.index("docker rm -f tb-demo-caddy") < run_demo  # an old Caddy does not keep :443 open meanwhile
    demo_line = out[run_demo : out.index("\n", run_demo)]
    assert "--restart no" in demo_line and "unless-stopped" not in demo_line


def test_the_boots_demo_switch_sets_the_flag_on_the_flag_page_and_sees_the_refusal(
    box: dict[str, Any], tmp_path: Path
) -> None:
    """The Python the boot pipes into the container, run as it is printed against a served console: it signs in as
    admin, sets demo.mode on /ops/flags with a reason (one audited flag.set), and exits 0 only after a multipart post
    was refused with the demo banner. Run a second time (demo mode already on) it fails: never a silent success."""
    import socket
    import sys
    import threading
    import time

    import uvicorn
    from console import demo_guard as dg
    from tb_common import flags as fl

    from tests.console.test_console_app import ADMIN_PW

    fl.clear_cache()
    assert fl.Flags().row(dg.FLAG) == "off"
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(box["app"], host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        rc, script = _boot(tmp_path, "--print-demo-switch")
        assert rc == 0 and "TB_DEMO_PASSWORD" in script, script
        env = {**os.environ, "TB_DEMO_PASSWORD": ADMIN_PW}

        def switch() -> subprocess.CompletedProcess[str]:
            return subprocess.run([sys.executable, "-", f"http://127.0.0.1:{port}"], input=script, env=env,
                                  capture_output=True, text=True, timeout=120, check=False)  # fmt: skip

        p = switch()
        assert p.returncode == 0, p.stdout + p.stderr
        assert ADMIN_PW not in p.stdout + p.stderr
        fl.clear_cache()
        assert dg.flag_on()
        events = []
        for f in sorted((box["dir"] / "audit").glob("*.jsonl")):
            events += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
        (ev,) = [e for e in events if e["event"] == "flag.set"]
        assert ev["actor"] == "console:admin" and ev["detail"]["flag"] == dg.FLAG and ev["detail"]["new"] == "on"
        assert "demo-vm-boot.sh" in ev["detail"]["reason"]
        assert [e["detail"]["path"] for e in events if e["event"] == dg.REFUSED_EVENT] == ["/pilot/case"]
        again = switch()
        assert again.returncode != 0 and "demo switch:" in again.stderr, again.stdout + again.stderr
    finally:
        server.should_exit = True
        th.join(timeout=10)
        fl.clear_cache()


def test_boot_caddyfile_is_tls_internal_on_443_only(tmp_path: Path) -> None:
    rc, out = _boot(tmp_path, "--print-caddyfile")
    assert rc == 0, out
    assert "tls internal" in out and "https://34.80.0.10:443 {" in out and "default_sni 34.80.0.10" in out
    assert "auto_https disable_redirects" in out and "admin off" in out
    assert not re.search(r":80\b|\bhttp://", out)  # no plain-http site, no :80 listener (127.0.0.1:8080 is the console)
    assert "reverse_proxy 127.0.0.1:8080" in out


@pytest.mark.parametrize(
    ("md", "why"),
    [
        ({"TB_MD_TB_DEMO_PASSWORD": "x"}, "looks like a secret"),
        ({"TB_MD_TB_LLM_MODE": "vllm"}, "stub model"),
        ({"TB_MD_TB_DEMO_TOOL": "public_e2e"}, "stub model"),
        ({"TB_MD_TB_DEMO_HOURS": ""}, "tb-demo-hours"),
        ({"TB_MD_TB_DEMO_IMAGE": "trialbox-demo:latest"}, "by digest"),
        ({"TB_MD_TB_DEMO_IMAGE": "gs://b/x.tar.gz", "TB_MD_TB_DEMO_IMAGE_SHA256": ""}, "sha256"),
        ({"TB_MD_EXTERNAL_IP": ""}, "no external IPv4"),
    ],
)
def test_boot_refuses(tmp_path: Path, md: dict[str, str], why: str) -> None:
    rc, out = _boot(tmp_path, "--dry-run", **md)
    assert rc == 3 and why in out, out


def test_boot_and_the_poc_host_pin_the_same_caddy() -> None:
    pin = re.compile(r'CADDY_IMAGE_PIN="(caddy:[^"]+@sha256:[0-9a-f]{64})"')
    a = pin.search(BOOT.read_text(encoding="utf-8"))
    b = pin.search((GCP / "hosted-demo-startup.sh").read_text(encoding="utf-8"))
    assert a and b and a.group(1) == b.group(1)


def test_no_setting_of_the_demo_vm_reads_as_a_secret_that_reaches_a_container() -> None:
    # the setting's earlier name, ending in "secret" (the name of the Secret Manager entry, never a value; now
    # TB_DEMO_VM_SM_NAME), was taken for a secret by the scan of
    # what reaches each container, and failed it on every compose stack wherever docker compose is installed
    from tests.unit.test_compose_secret_reach import secret_names

    assert not {n for n in secret_names() if n.startswith(("TB_DEMO_VM_", "TB_G8_", "TB_DOOR_", "TB_BUCKET"))}
