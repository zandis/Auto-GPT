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
  "compute instances get-serial-port-output") cat "$S/serial" 2>/dev/null || true ;;
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
    net=""; act=ALLOW; prio=1000; tags=""; prev=""
    for a in "$@"; do
      case "$a" in --source-ranges=*) echo "${a#--source-ranges=}" > "$S/fw-$4" ;; esac
      case "$prev" in --network) net=$a ;; --action) act=$a ;; --priority) prio=$a ;; --target-tags) tags=$a ;; esac
      prev=$a
    done
    if [ "$3" = create ]; then
      kind=allowed; [ "$act" = DENY ] && kind=denied
      printf '{"name": "%s", "network": "https://x/global/networks/%s", "direction": "INGRESS", "priority": %s, "targetTags": ["%s"], "%s": [{"IPProtocol": "x"}]}\n' \
        "$4" "$net" "$prio" "$tags" "$kind" > "$S/fwj-$4"
    fi ;;
  "compute firewall-rules delete") rm -f "$S/fw-$4" "$S/fwj-$4" ;;
  "storage ls "*) ls "$S/gcs" 2>/dev/null | grep -E '^enrol-.*\.txt$' | sed "s|^|${3%/enrol-\*.txt}/|" ;;
  "storage cat "*) cat "$S/gcs/${3##*/}" ;;
  "storage rm "*) rm "$S/gcs/${3##*/}" ;;
  "compute firewall-rules list")
    if [ "$fmt" = json ]; then
      echo "["; first=1
      for f in "$S"/fwj-*; do [ -f "$f" ] || continue; [ $first = 1 ] || echo ","; cat "$f"; first=0; done
      echo "]"
    else for f in "$S"/fw-*; do [ -f "$f" ] && basename "$f" | sed 's/^fw-//'; done; true; fi ;;
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
        (state / "net-default").touch()  # the project's own network exists
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
        TB_BUCKET="gs://b-test",
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
        "compute networks describe default",
        "compute firewall-rules create tb-demo-vm-deny --network default --direction INGRESS --action DENY --rules=all",
        "compute firewall-rules create tb-demo-vm-https --network default",
        "--network default --tags tb-demo-vm",
        "block-project-ssh-keys=TRUE",
        f"--source-ranges={ALLOW}",
        "compute instances create tb-demo-vm --zone asia-east1-a --machine-type e2-standard-4",
        "--max-run-duration 12h --instance-termination-action STOP",
    ):
        assert want in out, want
    assert "--accelerator" not in out and "tcp:80" not in out and "tcp:22" not in out
    assert "networks create" not in out  # the project's network: no networkAdmin needed
    assert "secrets " not in out  # no Secret Manager: each person chooses the password on /enrol
    rc, out = _run(tmp_path, "--dry-run", TB_DEMO_VM_NETWORK="own")
    assert (
        rc == 0
        and "compute networks create tb-demo-vm-net --subnet-mode=custom" in out
        and "--subnet tb-demo-vm-subnet" in out
    )
    assert "tb-demo-vm-deny" not in out


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
    made = [c for c in calls if c.startswith(("compute firewall-rules create", "compute firewall-rules update"))]
    allows = [c for c in made if "--action DENY" not in c]
    assert len(allows) == 1, calls
    rule = allows[0]
    assert "--rules=tcp:443 " in rule and "--source-ranges=0.0.0.0/0 " in rule and "--priority 500 " in rule
    assert "--direction INGRESS" in rule and "--action ALLOW" in rule and "--target-tags tb-demo-vm" in rule
    # the other rule made is the deny-all on the VM's tag, after the allow in precedence: nothing else opens a port
    (deny,) = [c for c in made if "--action DENY" in c]
    assert "--rules=all " in deny and "--target-tags tb-demo-vm " in deny and "--priority 510 " in deny
    assert not any(re.search(r"tcp:(80|22|3389)\b|--accelerator", c) for c in calls)
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
    assert len(fw) == 2, calls
    (rule,) = [c for c in fw if "--action ALLOW" in c]
    (deny,) = [c for c in fw if "--action DENY" in c]
    assert "--rules=tcp:443 " in rule and f"--source-ranges={ALLOW} " in rule
    assert "--direction INGRESS" in rule and "--target-tags tb-demo-vm" in rule and "--network default" in rule
    # the project's network: its SSH/RDP rules target every instance, so a deny-all on the tag comes before them
    assert "--rules=all " in deny and "--source-ranges=0.0.0.0/0 " in deny and "--target-tags tb-demo-vm " in deny
    prio = [re.search(r"--priority (\d+)", c) for c in (rule, deny)]
    assert prio[0] and prio[1] and int(prio[0].group(1)) < int(prio[1].group(1)) < 65534
    # nothing else opens a port: no other allow rule, no port 80 or 22 anywhere, no network made
    assert not any(re.search(r"tcp:(80|22)\b|--accelerator|networks create", c) for c in calls)
    assert "0.0.0.0/0" not in rule
    create = [c for c in calls if c.startswith("compute instances create")]
    assert len(create) == 1
    vm = create[0]
    for want in ("--machine-type e2-standard-4", "--zone asia-east1-a", "--network default", "block-project-ssh-keys=TRUE",
                 "--max-run-duration 12h", "--instance-termination-action STOP", "--provisioning-model STANDARD",
                 "startup-script=" + str(BOOT), f"tb-demo-image={DIGEST}", "tb-demo-hours=12",
                 "tb-demo-people=owner:investigator;guest:coordinator", "tb-demo-enrol-hours=24",
                 "tb-demo-handoff=gs://b-test/demo-vm"):  # fmt: skip
        assert want in vm, want
    assert "password" not in vm.replace("--metadata-from-file startup-script=", "")  # no password, nor its name
    assert not any(c.startswith("secrets ") for c in calls)  # the deployer needs no Secret Manager right
    # the order: auth first, the network before its rule, the rule before the VM
    order = [next(i for i, c in enumerate(calls) if c.startswith(p)) for p in
             ("auth activate-service-account", "compute networks describe default",
              "compute firewall-rules create tb-demo-vm-deny", "compute firewall-rules create tb-demo-vm-https",
              "compute firewall-rules list", "compute instances create")]  # fmt: skip
    assert order == sorted(order), calls
    assert "--key-file " + str(tmp_path / "key.json") in calls[0]
    assert "https://34.80.0.10/" in out and "warns once" in out


def test_up_on_its_own_network_makes_one_rule_and_no_deny(tmp_path: Path) -> None:
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_VM_NETWORK="own")
    assert rc == 0, out
    calls = _argv(tmp_path)
    fw = [c for c in calls if c.startswith("compute firewall-rules create")]
    assert len(fw) == 1 and "--network tb-demo-vm-net" in fw[0] and "--rules=tcp:443 " in fw[0], calls
    order = [next(i for i, c in enumerate(calls) if c.startswith(p)) for p in
             ("compute networks create", "compute networks subnets create", "compute firewall-rules create",
              "compute instances create")]  # fmt: skip
    assert order == sorted(order), calls
    assert any("--subnet tb-demo-vm-subnet" in c for c in calls if c.startswith("compute instances create"))
    rc, out = _run(tmp_path, "delete", "--yes", TB_DEMO_VM_NETWORK="own")
    assert rc == 0 and "network tb-demo-vm-net" in out, out
    assert not (tmp_path / "state" / "net-tb-demo-vm-net").exists()


def test_up_refuses_when_the_project_has_no_default_network(tmp_path: Path) -> None:
    _env(tmp_path)
    (tmp_path / "state" / "net-default").unlink()
    rc, out = _run(tmp_path, "up", "--yes")
    assert rc == 3 and "no network named default" in out and "TB_DEMO_VM_NETWORK=own" in out, out
    assert not any(c.startswith(("compute instances create", "compute firewall-rules create")) for c in _argv(tmp_path))


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


@pytest.mark.parametrize(
    ("extra", "why"),
    [
        ({"TB_BUCKET": "", "TB_DEMO_VM_HANDOFF": ""}, "TB_DEMO_VM_HANDOFF (or TB_BUCKET)"),
        ({"TB_DEMO_VM_HANDOFF": "s3://x/y"}, "TB_DEMO_VM_HANDOFF (or TB_BUCKET)"),
        ({"TB_DEMO_VM_PEOPLE": "pi:investigator"}, "one of the seed's own accounts"),
        ({"TB_DEMO_VM_PEOPLE": "owner:admin"}, "role must be one of investigator, coordinator, viewer"),
        ({"TB_DEMO_VM_PEOPLE": "owner:viewer,owner:coordinator"}, "listed twice"),
        ({"TB_DEMO_VM_PEOPLE": "Owner Name:viewer"}, "is not a user name"),
        ({"TB_DEMO_VM_ENROL_HOURS": "73"}, "from 1 to 72"),
    ],
)
def test_up_refuses_bad_people_settings_before_any_gcloud_call(tmp_path: Path, extra: dict[str, str], why: str) -> None:
    rc, out = _run(tmp_path, "up", "--yes", env=_env(tmp_path, **extra))
    assert rc == 2 and why in out, out
    assert _argv(tmp_path) == []


def test_links_prints_the_newest_codes_once_and_deletes_every_object(tmp_path: Path) -> None:
    _env(tmp_path)
    gcs = tmp_path / "state" / "gcs"
    gcs.mkdir()
    (gcs / "enrol-20261117T000000Z.txt").write_text("old set\n")
    (gcs / "enrol-20261117T010000Z.txt").write_text("owner (investigator): https://34.80.0.10/enrol  code: abcd\n")
    rc, out = _run(tmp_path, "links")
    assert rc == 0, out
    assert "code: abcd" in out and "old set" not in out and "Give each person their own line" in out
    assert list(gcs.iterdir()) == []  # read once: both objects are gone
    calls = _argv(tmp_path)
    assert any(c.startswith("storage ls gs://b-test/demo-vm/enrol-*.txt") for c in calls), calls
    rc, out = _run(tmp_path, "links")
    assert rc == 3 and "no codes under gs://b-test/demo-vm" in out and "down and up" in out, out
    rc, out = _run(tmp_path, "--dry-run", "links")
    assert rc == 0 and "+ gcloud storage cat" in out


def _hand_rule(tmp: Path, name: str, network: str, priority: int, tags: list[str], kind: str = "allowed") -> None:
    rule = {"name": name, "network": f"https://x/global/networks/{network}", "direction": "INGRESS",
            "priority": priority, "targetTags": tags, kind: [{"IPProtocol": "tcp", "ports": ["22"]}]}  # fmt: skip
    (tmp / "state" / f"fwj-{name}").write_text(json.dumps(rule))
    (tmp / "state" / f"fw-{name}").write_text("0.0.0.0/0")


@pytest.mark.parametrize(
    ("network", "rule", "refused"),
    [
        ("own", ("tb-demo-vm-allow-ssh", "tb-demo-vm-net", 1000, []), True),  # someone added SSH by hand
        ("default", ("ssh-first", "default", 400, []), True),  # an allow for every instance before the deny
        ("default", ("ssh-tag", "default", 509, ["tb-demo-vm"]), True),  # one on the VM's own tag
        ("default", ("default-allow-ssh", "default", 65534, []), False),  # the project's default rule: the deny wins
        ("default", ("tie", "default", 510, []), False),  # at equal priority a deny wins
        ("default", ("other-vm", "default", 100, ["web"]), False),  # another machine's tag
        ("default", ("other-net", "elsewhere", 100, []), False),  # another network
    ],
)
def test_up_refuses_a_rule_that_could_reach_the_vm(
    tmp_path: Path, network: str, rule: tuple[str, str, int, list[str]], refused: bool
) -> None:
    _env(tmp_path)
    _hand_rule(tmp_path, *rule)
    rc, out = _run(tmp_path, "up", "--yes", TB_DEMO_VM_NETWORK=network)
    created = any(c.startswith("compute instances create") for c in _argv(tmp_path))
    if refused:
        assert rc == 3 and f"firewall rules that reach the VM ({rule[0]}" in out, out
        assert not created
    else:
        assert rc == 0 and created, out


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


# the serial console as the trial `up` of 2026-11-15 showed it: Compute Engine's script runner prefixes every line of
# the startup script; the boot's tee to /dev/ttyS0 writes some lines bare as well (no address here)
RUNNER = "2026-11-15T05:08:29.98+00:00 tb-demo-vm google_metadata_script_runner[949]: "
RUNNER += 'Metadata key("startup-script"), command("/bin/bash"): '
SERIAL_BOOT = [
    "TB-DEMO-VM 04:59:29 hard stop: this VM powers off 12 h after this boot\r",
    RUNNER + "TB-DEMO-VM 04:59:29 hard stop: this VM powers off 12 h after this boot",
    "[  OK  ] Started docker.service - Docker Application Container Engine.",
    RUNNER + "TB-DEMO-VM 05:00:54 the demo (stub model, synthetic hospital; seeds for 3 to 6 minutes)",
]
SERIAL_READY = [
    RUNNER + "TB-DEMO-VM 05:08:24 caddy on :443 (tls internal for the address)",
    RUNNER + "TB-DEMO-VM 05:08:29 ready https://the-address/ (each person: /enrol with their code)",
    RUNNER + "DEMO-VM-READY",
    "Nov 15 05:08:30 tb-demo-vm google_metadata_script_runner[949]: Finished running startup scripts.",
]


def _serial(tmp: Path, lines: list[str]) -> None:
    (tmp / "state" / "serial").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_status_reads_the_ready_marker_behind_the_script_runners_prefix(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    _serial(tmp_path, SERIAL_BOOT)
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "boot: not ready yet" in out and "DEMO-VM-READY (" not in out, out
    assert "  TB-DEMO-VM 05:00:54 the demo" in out and "google_metadata_script_runner" not in out, out
    _serial(tmp_path, SERIAL_BOOT + SERIAL_READY)
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "boot: DEMO-VM-READY" in out, out
    assert out.count("hard stop: this VM powers off") == 1, out  # the bare and the prefixed copy shown once
    assert "Finished running" not in out and "docker.service" not in out, out
    # a later boot (down, up) that failed: its own marker counts, not the earlier boot's READY
    _serial(tmp_path, SERIAL_BOOT + SERIAL_READY + SERIAL_BOOT + [RUNNER + "DEMO-VM-NOT-READY"])
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "boot: DEMO-VM-NOT-READY" in out and "boot: DEMO-VM-READY" not in out, out
    _serial(tmp_path, [RUNNER + "TB-DEMO-VM refused: metadata tb-demo-hours must be a whole number of hours"])
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "boot: refused" in out and "tb-demo-hours must be" in out, out
    _serial(tmp_path, [])
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "boot: not ready yet" in out, out


def test_status_and_delete(tmp_path: Path) -> None:
    assert _run(tmp_path, "up", "--yes")[0] == 0
    _serial(tmp_path, SERIAL_BOOT + SERIAL_READY)
    rc, out = _run(tmp_path, "status")
    assert rc == 0 and "RUNNING" in out and "DEMO-VM-READY" in out and "https://34.80.0.10/" in out
    assert "1.2.3.4/32,5.6.7.0/24" in out
    rc, out = _run(tmp_path, "delete", "--yes")
    assert rc == 0, out
    left = [p.name for p in (tmp_path / "state").iterdir() if p.name.startswith(("net-", "subnet-", "fw"))]
    assert left == ["net-default"], left  # the project's network stays; both rules are gone
    assert "rules tb-demo-vm-https and tb-demo-vm-deny" in out
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
        TB_MD_TB_DEMO_PEOPLE="owner:investigator;guest:coordinator",
        TB_MD_TB_DEMO_HANDOFF="gs://b-test/demo-vm",
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
    assert "+ systemctl disable --now ssh.service" in out  # no sshd: the second lock after the firewall's deny-all
    assert out.index("shutdown -P") < out.index("apt-get")  # armed before anything that could hang
    assert "-p 127.0.0.1:8080:8080" in out  # the console only behind Caddy
    assert "TB_DEMO_PASSWORD=<48 random bytes, base64; never printed>" in out and "secrets " not in out
    assert "--env-file /etc/tb-demo-vm/secret.env" in out
    assert "FORWARDED_ALLOW_IPS=*" in out  # failures count per browser address behind Caddy (D-279)
    people = out.index("python - owner:investigator,guest:coordinator 24 < (demo-vm-boot.sh --print-people)")
    assert out.index("--print-demo-switch") < people < out.index("docker run -d --name tb-demo-caddy")
    assert "gcloud storage cp /etc/tb-demo-vm/handoff.txt gs://b-test/demo-vm/enrol-" in out
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


def test_the_boots_people_script_opens_each_account_with_a_one_time_code(box: dict[str, Any], tmp_path: Path) -> None:
    """The Python the boot pipes into the container, run as printed against a console's own database: each person's
    account is opened with the product's enrolment code (D-719) and put on the study's delegation log. The person then
    chooses the password on /enrol; the code works once; a wrong password is refused; an expired code is refused."""
    import sys
    from datetime import UTC, datetime, timedelta

    from console.auth import UserStore
    from console.teamstore import TeamStore
    from fastapi.testclient import TestClient

    rc, script = _boot(tmp_path, "--print-people")
    assert rc == 0 and "open_by_code" in script, script
    p = subprocess.run([sys.executable, "-", "owner:investigator,guest:coordinator", "24", "GZQO"], input=script,
                       cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert p.returncode == 0, p.stderr
    lines = [x.split("\t") for x in p.stdout.splitlines()]
    assert [(x[0], x[1]) for x in lines] == [("owner", "investigator"), ("guest", "coordinator")], p.stdout
    codes = {x[0]: x[2] for x in lines}
    assert all(re.fullmatch(r"[a-z0-9]{4}(-[a-z0-9]{4}){3}", c) for c in codes.values()), codes
    users: UserStore = box["users"]
    assert not users.holder_set("owner") and users.role_of("guest") == "coordinator"
    team = TeamStore()
    log = {(e.username, e.role) for e in team.entries("GZQO")}
    assert ("owner", "sub_pi") in log and ("guest", "crc") in log
    # an expired code is refused (the store's clock 25 h on)
    later = UserStore(clock=lambda: datetime.now(UTC) + timedelta(hours=25))
    assert later.redeem("guest", codes["guest"], "a-long-enough-password-1", spend=True) == "wrong"
    assert not users.holder_set("guest")

    c = TestClient(box["app"], base_url="https://testserver")  # the sign-in cookies are Secure

    def enrol(name: str, code: str, pw: str) -> Any:
        page = c.get("/enrol")
        tok = re.search(r'name="login_csrf" value="([^"]+)"', page.text)
        assert tok, page.text
        form = {"username": name, "enrol_code": code, "password": pw, "password2": pw, "login_csrf": tok.group(1)}
        return c.post("/enrol", data=form, follow_redirects=False)

    assert enrol("owner", codes["owner"], "short").status_code == 400  # the product's rule: 12 characters at least
    r = enrol("owner", codes["owner"], "owner-chose-this-one-1")
    assert r.status_code == 303 and r.headers["location"] == "/", r.text
    assert users.holder_set("owner")
    c.cookies.clear()
    assert enrol("owner", codes["owner"], "someone-else-tries-1").status_code == 401  # the code is dead
    c.cookies.clear()

    def sign_in(pw: str) -> Any:
        tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
        assert tok
        form = {"username": "owner", "password": pw, "login_csrf": tok.group(1)}
        return c.post("/login", data=form, follow_redirects=False)

    assert sign_in("someone-else-tries-1").status_code == 401  # a wrong password is refused
    r = sign_in("owner-chose-this-one-1")
    assert r.status_code == 303 and not r.headers["location"].startswith("/login"), r.text
    # what reached stdout is the codes only for the boot's private file; nothing else of the script prints them
    assert p.stderr.strip() == ""


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
        ({"TB_MD_TB_DEMO_PEOPLE": ""}, "tb-demo-people"),
        ({"TB_MD_TB_DEMO_PEOPLE": "owner:admin"}, "tb-demo-people"),
        ({"TB_MD_TB_DEMO_PEOPLE": "stw:viewer"}, "seeded account"),
        ({"TB_MD_TB_DEMO_HANDOFF": ""}, "tb-demo-handoff"),
        ({"TB_MD_TB_DEMO_ENROL_HOURS": "0"}, "tb-demo-enrol-hours"),
        ({"TB_MD_TB_DEMO_ENROL_HOURS": "73"}, "tb-demo-enrol-hours"),
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
