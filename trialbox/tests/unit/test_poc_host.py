"""The PoC host scripts (T-509, D-330), checked offline in their dry-run mode: nothing here calls a cloud.

``deploy/gcp/poc-host.sh`` (the owner's commands) and ``deploy/gcp/hosted-demo-startup.sh`` (the VM's boot script)
run with ``--dry-run`` and a PATH whose ``gcloud``, ``docker``, ``curl`` and ``ssh`` fail the test if they are ever
called. The checks are what can be shown without a VM: the image by digest and no build on the VM, the front door
before ``/login`` (tunnel token check, Caddy refusal, no open web port), kept data at restart, the daily snapshot,
a purge that leaves no disk or snapshot, a rebuild in one command, and no secret in the output. The real runs need
the owner's yes on the cost (Q-03)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
HOST = GCP / "poc-host.sh"
START = GCP / "hosted-demo-startup.sh"
DIGEST = "asia-east1-docker.pkg.dev/demo-proj/tb-poc/demo@sha256:" + "ab" * 32
TOKEN = "cf-token-must-never-show-0123456789"
MAILS = "tester.one@example.org,tester.two@example.org"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A PATH where every cloud tool records the call and fails; the settings of a synthetic project."""
    fake = tmp_path / "bin"
    fake.mkdir()
    for tool in ("gcloud", "docker", "curl", "ssh", "gsutil"):
        p = fake / tool
        p.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{tmp_path}/called"\nexit 97\n', encoding="utf-8")
        p.chmod(0o755)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("TB_POC_", "TB_MD_", "CLOUDFLARE_"))}
    e.update(
        PATH=f"{fake}:{os.environ['PATH']}",
        HOME=str(tmp_path),
        TB_POC_PROJECT="demo-proj",
        TB_POC_DOMAIN="poc.example.org",
        TB_POC_ACCESS_TEAM="demo-team",
        TB_POC_DOOR_EMAILS=MAILS,
        CLOUDFLARE_API_TOKEN=TOKEN,
        CLOUDFLARE_ACCOUNT_ID="acct-1",
        CLOUDFLARE_ZONE_ID="zone-1",
        TB_MD_TB_IMAGE=DIGEST,
        TB_MD_TB_DOMAIN="poc.example.org",
        TB_CALLED=str(tmp_path / "called"),
    )
    return e


def sh(script: Path, *args: str, env: dict[str, str], ok: bool = True) -> str:
    r = subprocess.run(["bash", str(script), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=60, check=False)  # fmt: skip
    out = r.stdout
    assert not Path(env["TB_CALLED"]).exists(), (
        "a cloud tool was called in a dry run: " + Path(env["TB_CALLED"]).read_text()
    )
    assert (r.returncode == 0) is ok, out
    assert TOKEN not in out and "tester.one" not in out and "tester.two" not in out, (
        "a secret or an address was printed"
    )
    return out


def calls(out: str, prefix: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith(f"+ {prefix}")]


# ------------------------------------------------------------------------------------- no paid step without a yes
@pytest.mark.parametrize("cmd", ["image", "door", "create", "rebuild", "purge"])
def test_a_paid_command_without_yes_only_shows_what_it_would_run(env: dict[str, str], cmd: str) -> None:
    out = sh(HOST, cmd, env=env)  # no --dry-run, no --yes: the fakes would fail the test if anything ran
    assert "Add --yes to run it" in out


def test_cost_gives_an_hourly_and_a_monthly_figure(env: dict[str, str]) -> None:
    out = sh(HOST, "cost", env=env)
    month = re.search(r"total\s+([\d.]+) a month, about ([\d.]+) an hour", out)
    assert month, out
    assert 80 < float(month.group(1)) < 200 and 0.1 < float(month.group(2)) < 0.3


# --------------------------------------------------------------------------- the image by digest, no build on the VM
def test_image_is_built_once_here_from_a_clean_export_of_the_tag(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "image", env=env)
    assert any(" archive poc-1 trialbox" in c for c in calls(out, "git"))  # the tag, not the working tree
    assert calls(out, "docker build") and calls(out, "docker push")
    assert "demo:poc-1" in out and "@sha256:" in out  # printed: the digest the VM runs


def test_the_vm_runs_the_image_by_digest_and_never_builds(env: dict[str, str]) -> None:
    out = sh(START, "--dry-run", env=env)
    assert f"+ docker pull -q {DIGEST}" in out
    runs = calls(out, "docker run")
    assert len(runs) == 4  # caddy, the tunnel, two sites
    for c in runs:
        assert re.search(r"@sha256:[0-9a-f]{64}( |$)", c), c  # every container by digest
    assert not calls(out, "docker build") and not calls(out, "git")
    text = "\n".join(x for x in START.read_text(encoding="utf-8").splitlines() if not x.lstrip().startswith("#"))
    assert "docker build" not in text and "git clone" not in text and "get.docker.com" not in text
    assert not re.search(r"\bcaddy:2\b(?!\.)", text)  # never caddy by a moving tag (OPS-008)


@pytest.mark.parametrize("image", ["asia-east1-docker.pkg.dev/demo-proj/tb-poc/demo:poc-1", "trialbox-demo", ""])
def test_the_vm_refuses_an_image_without_a_digest(env: dict[str, str], image: str) -> None:
    env["TB_MD_TB_IMAGE"] = image
    out = sh(START, "--dry-run", env=env, ok=False)
    assert "by digest" in out and not calls(out, "docker")


def test_create_and_rebuild_pass_a_digest_to_the_vm(env: dict[str, str]) -> None:
    for cmd in ("create", "rebuild"):
        out = sh(HOST, "--dry-run", cmd, env=env)
        (vm,) = [c for c in calls(out, "gcloud compute instances create")]
        assert "tb-image=asia-east1-docker.pkg.dev/demo-proj/tb-poc/demo@sha256:" in vm
        assert "startup-script=" in vm and vm.count("hosted-demo-startup.sh") == 1
    env["TB_POC_IMAGE"] = "registry.example.org/demo:latest"
    out = subprocess.run(["bash", str(HOST), "--yes", "rebuild"], env=env, capture_output=True, text=True, check=False)
    assert out.returncode != 0 and "pinned by digest" in out.stderr  # refused before any call


# ------------------------------------------------------------------------------------- the front door before /login
def test_the_tunnel_checks_the_access_token_for_every_host(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "door", env=env)
    (cfg,) = [line for line in out.splitlines() if "/configurations" in line]
    for site in ("jp", "tw"):
        host = f"{site}.poc.example.org"
        assert f'"hostname": "{host}", "service": "https://127.0.0.1:443"' in cfg
        rule = cfg.split(f'"hostname": "{host}"')[1].split('"hostname"')[0]
        assert '"access": {"required": true, "teamName": "demo-team"' in rule
        assert '"originServerName": "' + host + '"' in rule  # TLS to Caddy, checked against Caddy's root
    assert '{"service": "http_status:404"}' in cfg  # any other host name: nothing
    pol = [line for line in out.splitlines() if line.startswith("+ curl -X POST") and "/policies" in line]
    assert len(pol) == 2 and all(
        '"decision": "allow"' in p and "<2 addresses from TB_POC_DOOR_EMAILS>" in p for p in pol
    )
    assert "onetimepin" in out
    assert "versions add tb-poc-tunnel-token --data-file=-" in out  # the token goes straight to Secret Manager


def test_caddy_refuses_every_request_without_a_front_door_token(env: dict[str, str]) -> None:
    caddy = sh(START, "--print-caddyfile", env=env)
    blocks = re.findall(r"^(\S+) \{\n(.*?)^\}", caddy, flags=re.M | re.S)
    sites = {name: body for name, body in blocks if name.endswith(".poc.example.org")}
    assert set(sites) == {"jp.poc.example.org", "tw.poc.example.org"}
    for body in sites.values():
        assert "bind 127.0.0.1" in body and "tls internal" in body
        refuse = body.index("respond @nodoor")
        assert "@nodoor header !Cf-Access-Jwt-Assertion" in body and " 403" in body[refuse:].splitlines()[0]
        assert refuse < body.index("reverse_proxy")  # the refusal comes before the console
    assert "admin off" in caddy


@pytest.mark.skipif(
    shutil.which("caddy") is None, reason="no caddy binary here (CI job shell validates with the image)"
)
def test_the_caddyfile_is_valid_for_caddy(env: dict[str, str], tmp_path: Path) -> None:
    f = tmp_path / "Caddyfile"
    f.write_text(sh(START, "--print-caddyfile", env=env), encoding="utf-8")
    r = subprocess.run(["caddy", "validate", "--adapter", "caddyfile", "--config", str(f)], capture_output=True,
                       text=True, check=False, env={**env, "PATH": os.environ["PATH"], "XDG_DATA_HOME": str(tmp_path)})  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_web_port_is_open_to_the_internet(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "create", env=env)
    rules = calls(out, "gcloud compute firewall-rules create")
    assert len(rules) == 1 and "--rules tcp:22 --source-ranges 35.235.240.0/20" in rules[0]  # SSH through IAP only
    assert "0.0.0.0/0" not in out and "--subnet tb-poc-subnet" in out  # its own network: no default-allow rules
    vm = sh(START, "--dry-run", env=env)
    for c in calls(vm, "docker run"):
        published = re.findall(r"-p (\S+)", c)
        assert all(p.startswith("127.0.0.1:") for p in published), c  # sites on loopback; Caddy binds 127.0.0.1


# ------------------------------------------------------------------------------- kept data, snapshot, rebuild, purge
def test_a_restart_keeps_the_data(env: dict[str, str]) -> None:
    out = sh(START, "--dry-run", env=env)
    for site, port in (("jp", 8081), ("tw", 8082)):
        (run,) = [c for c in calls(out, "docker run") if f"tb-poc-{site} " in c]
        assert f"-v /srv/trialbox/{site}:/data" in run and f"-p 127.0.0.1:{port}:8080" in run
        assert "--restart unless-stopped" in run
    assert out.count("TB_DEMO_KEEP=1") == 2 and out.count("TB_DEMO_DIR=/data/demo") == 2
    assert "formatted only when blkid finds no file system" in out  # an existing disk is never formatted
    assert not calls(out, "rm ") and not calls(out, "mkfs")  # a boot never deletes or formats data
    assert "TB_CONSOLE_SECURE_COOKIE=1" in out and "TB_TZ=Asia/Tokyo" in out and "TB_DEMO_LANG=zh-TW" in out


def test_reset_empties_only_the_named_site(env: dict[str, str]) -> None:
    out = sh(START, "--dry-run", "--reset-site", "jp", env=env)
    assert "+ rm -rf --one-file-system /srv/trialbox/jp/demo" in out
    assert "/srv/trialbox/tw" not in out and "POC-RESET-DONE" in out
    sh(START, "--dry-run", "--reset-site", "xx", env=env, ok=False)
    out = sh(HOST, "--dry-run", "reset", "jp", env=env)
    (ssh,) = calls(out, "gcloud compute ssh")
    assert "--tunnel-through-iap" in ssh and "--reset-site jp" in ssh
    sh(HOST, "--dry-run", "reset", "jp;reboot", env=env, ok=False)


def test_the_data_disk_has_a_daily_snapshot_and_outlives_the_vm(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "create", env=env)
    (pol,) = calls(out, "gcloud compute resource-policies create snapshot-schedule")
    assert "--daily-schedule" in pol and "--max-retention-days 70" in pol and "--snapshot-labels tb-poc=tb-poc" in pol
    (disk,) = calls(out, "gcloud compute disks create tb-poc-data")
    assert "--resource-policies tb-poc-daily" in disk
    (vm,) = calls(out, "gcloud compute instances create")
    assert "auto-delete=no" in vm


def test_rebuild_from_the_tag_is_one_command(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "rebuild", env=env)
    steps = [c.split(" --")[0] for c in calls(out, "gcloud")]
    assert steps == [
        "+ gcloud artifacts docker images describe asia-east1-docker.pkg.dev/demo-proj/tb-poc/demo:poc-1",
        "+ gcloud compute disks snapshot tb-poc-data",
        "+ gcloud compute instances delete tb-poc",
        "+ gcloud compute instances create tb-poc",
    ]
    assert "--keep-disks data" in out and not calls(out, "docker")


def test_purge_deletes_every_volume_and_snapshot_and_checks_none_is_left(env: dict[str, str]) -> None:
    out = sh(HOST, "--dry-run", "purge", env=env)
    for what in (
        "gcloud compute instances delete tb-poc",
        "gcloud compute disks delete tb-poc-data",
        "gcloud compute snapshots delete",
        "gcloud compute resource-policies delete tb-poc-daily",
        "gcloud compute networks delete tb-poc-net",
        "gcloud artifacts repositories delete tb-poc",
        "gcloud secrets delete tb-poc-tunnel-token",
        "gcloud secrets delete tb-poc-accounts-jp",
        "gcloud iam service-accounts delete tb-poc-vm@",
    ):
        assert calls(out, what), what
    assert "--delete-disks all" in out
    assert "curl -X DELETE https://api.cloudflare.com/client/v4/accounts/acct-1/cfd_tunnel/" in out
    for kind in ("instances", "disks", "snapshots"):
        assert f"left: 0 {kind}" in out
    assert "PURGED: no VM, no disk, no snapshot left" in out
    i = out.index("+ gcloud compute snapshots list")
    assert out.index("gcloud compute disks delete tb-poc-data") < i  # the kept auto-snapshots are listed after


# ------------------------------------------------------------------------------------------------ the scripts
@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck here (CI job shell runs it)")
def test_shellcheck() -> None:
    r = subprocess.run(["shellcheck", "-x", "--severity=warning", str(HOST), str(START)], cwd=ROOT,
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout


def test_secrets_never_reach_a_command_line_or_metadata() -> None:
    for script in (HOST, START):
        text = script.read_text(encoding="utf-8")
        assert "Bearer $CLOUDFLARE_API_TOKEN" not in text and "set -x" not in text and "secrets.env" not in text
    assert "printf 'Authorization: Bearer %s\\n' \"$CLOUDFLARE_API_TOKEN\" | curl" in HOST.read_text(encoding="utf-8")
    meta = re.search(r'--metadata "\^\|\^([^"]+)"', HOST.read_text(encoding="utf-8"))
    assert meta and not re.search(r"password|token|accounts", meta.group(1), flags=re.I)
