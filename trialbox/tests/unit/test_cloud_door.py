"""T-119 (CR-048, D-423): the cloud run's door and the rest of the cloud hygiene, checked with stand-ins only.

No cloud is called: the door's TLS is checked against local HTTPS and HTTP servers (the negative case of the card: a
fetch without the pinned certificate is refused), the firewall check against synthetic rule lists, the driver in its
dry run and against the rehearsal's gcloud, the scripts as text (no ``set -x``, no port 80 for the GPU VM, no key in
the metadata), and the hosted demo's start-up script in its dry run. The whole path is ``make rehearse
CASES=run-a,bucket`` (``tests/rehearsal``), which needs docker and about an hour."""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import ssl
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
REH = ROOT / "tests" / "rehearsal"
DOOR = GCP / "door-tls.sh"
PY = str(ROOT / ".venv" / "bin" / "python")

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="no openssl here")


def bash(script: str, **env: str) -> subprocess.CompletedProcess[str]:
    e = {k: v for k, v in os.environ.items() if k not in ("TB_ZONES", "TB_BUCKET")}
    e.update(env)
    return subprocess.run(["bash", "-c", f'. "{DOOR}"\n{script}'], env=e, capture_output=True, text=True, timeout=60,
                          check=False)  # fmt: skip


def make_door(d: Path) -> Path:
    d.mkdir(parents=True)
    r = bash(f'door_make "{d}"', PY=PY)
    assert r.returncode == 0, r.stderr
    return d


class _Door(http.server.BaseHTTPRequestHandler):
    key = ""

    def do_GET(self) -> None:
        ok = self.headers.get("Authorization") == f"Bearer {self.key}"
        body = b"phase run\n" if ok else b"no\n"
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        pass


def serve(door: Path | None, key: str) -> tuple[http.server.ThreadingHTTPServer, int]:
    """An HTTPS server with ``door``'s certificate (None: plain HTTP) that answers the key, as the VM's nginx does."""
    handler = type("H", (_Door,), {"key": key})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if door is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(door / "door.crt", door / "door.key")
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


@pytest.fixture
def door(tmp_path: Path) -> Iterator[Path]:
    yield make_door(tmp_path / "door")


# ------------------------------------------------------------------------------------- the door: TLS, pinned, a key
@needs_openssl
def test_door_make_writes_private_files_and_a_secret_for_the_vm(door: Path) -> None:
    for f in ("tb-key", "door.key", "door.crt", "door.pin", "door-secret.json"):
        assert (door / f).stat().st_mode & 0o077 == 0, f  # nothing readable by others
    sec = json.loads((door / "door-secret.json").read_text(encoding="utf-8"))
    assert sec["key"] == (door / "tb-key").read_text(encoding="utf-8").strip() and len(sec["key"]) >= 40
    assert "PRIVATE KEY" in sec["tls_key"] and "CERTIFICATE" in (door / "door.crt").read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in (door / "door.crt").read_text(encoding="utf-8")  # the metadata half is public only


@needs_openssl
def test_the_pinned_door_answers_and_refuses_plain_http_another_certificate_and_another_key(
    door: Path, tmp_path: Path
) -> None:
    key = (door / "tb-key").read_text(encoding="utf-8").strip()
    good, port = serve(door, key)
    try:
        r = bash(f'door_curl "{door}" 127.0.0.1 GET progress', DOOR_PORT=str(port))
        assert r.returncode == 0 and r.stdout == "phase run\n", r.stderr
    finally:
        good.shutdown()
    other = make_door(tmp_path / "other")  # the same name, a certificate the driver did not make
    for srv, port in (serve(other, key), serve(None, key)):
        try:
            r = bash(f'door_curl "{door}" 127.0.0.1 GET progress', DOOR_PORT=str(port))
            assert r.returncode != 0 and r.stdout == "", (port, r.stderr)  # refused: no answer, no key given away
        finally:
            srv.shutdown()
    srv, port = serve(door, "another-key")
    try:
        assert bash(f'door_curl "{door}" 127.0.0.1 GET progress', DOOR_PORT=str(port)).returncode != 0
    finally:
        srv.shutdown()


def test_door_curl_never_has_the_key_on_its_command_line_and_is_https_only() -> None:
    text = DOOR.read_text(encoding="utf-8")
    body = text[text.index("door_curl() {") : text.index("door_firewall_check() {")]
    assert "--proto =https" in body and "--pinnedpubkey" in body and "--cacert" in body and "--noproxy" in body
    assert "-H @<(printf 'Authorization: Bearer %s\\n'" in body and "http://" not in body


# ------------------------------------------------------------------------------------- the firewall: 80 shut, 443 open
VM_JSON = {"networkInterfaces": [{"network": "projects/p/global/networks/default"}], "tags": {"items": ["tb-gpu-door"]},
           "serviceAccounts": [{"email": "vm@p.iam.gserviceaccount.com"}]}  # fmt: skip


def rule(name: str, ports: list[str] | None, src: str = "0.0.0.0/0", **kw: object) -> dict[str, object]:
    allowed: dict[str, object] = {"IPProtocol": "tcp"}
    if ports is not None:
        allowed["ports"] = ports
    return {"name": name, "network": "projects/p/global/networks/default", "direction": "INGRESS",
            "allowed": [allowed], "sourceRanges": [src], **kw}  # fmt: skip


@pytest.mark.parametrize(
    ("rules", "ok", "says"),
    [
        ([rule("door", ["443"], targetTags=["tb-gpu-door"])], True, ""),
        ([rule("door", ["443"]), rule("default-allow-http", ["80"], targetTags=["tb-gpu-door"])], False, "tcp:80"),
        ([rule("door", ["443"]), rule("wide", ["1-1000"])], False, "tcp:80"),
        ([rule("door", ["443"]), rule("anything", None)], False, "tcp:80"),
        ([rule("door", ["443"]), rule("internal", None, src="10.128.0.0/9")], True, ""),  # inside the VPC only
        ([rule("door", ["443"]), rule("iap", ["22", "80"], src="35.235.240.0/20")], True, ""),  # IAP only
        ([rule("door", ["443"]), rule("other-vms", ["80"], targetTags=["web"])], True, ""),  # not this VM's tag
        ([rule("door", ["443"]), rule("off", ["80"], disabled=True)], True, ""),
        ([rule("ssh", ["22"])], False, "tcp:443"),
        ([rule("door", ["443"], targetTags=["web"])], False, "tcp:443"),
    ],
)
def test_the_firewall_check_refuses_port_80_and_wants_443(tmp_path: Path, rules: list[object], ok: bool,
                                                          says: str) -> None:  # fmt: skip
    (tmp_path / "vm.json").write_text(json.dumps(VM_JSON), encoding="utf-8")
    (tmp_path / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    r = bash(f'door_firewall_check "{PY}" "{tmp_path / "vm.json"}" "{tmp_path / "rules.json"}"')
    assert (r.returncode == 0) is ok, r.stderr
    assert says in r.stderr


# ------------------------------------------------------------------------------------- the driver
def _driver(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    e = {k: v for k, v in os.environ.items() if k not in ("TB_ZONES", "TB_BUCKET")}
    e.update(TB_COMPLETE_DIR=str(tmp_path / "out"), PY=PY, **env)
    return subprocess.run([str(GCP / "complete-run.sh"), *args], cwd=ROOT, env=e, capture_output=True, text=True,
                          check=False, timeout=300)  # fmt: skip


def test_the_dry_run_puts_no_key_in_the_metadata_and_uses_the_pinned_door(tmp_path: Path) -> None:
    r = _driver(tmp_path, "--dry-run", "--patients", "500", "--only", "scenario-it-dump")
    out = r.stdout
    assert r.returncode == 0, r.stderr[-800:]
    meta = [ln for ln in out.splitlines() if "add-metadata" in ln]
    assert meta and all("tb-key" not in ln for ln in meta)
    assert "tb-door-secret=tb-gpu-door,tb-door-version=" in meta[0] and "tb-door-cert=" in meta[0]
    assert "gcloud secrets versions add tb-gpu-door --data-file=" in out
    assert "https://tb-door/tb/upload" in out and "http://<vm-ip>" not in out and "its key pinned" in out
    assert "gcloud compute firewall-rules list --format=json" in out and "remove-metadata tb-gpu-sim" in out
    assert out.index("firewall-rules list") < out.index("set-scheduling") < out.index("instances start")
    assert out.index("secrets versions add") < out.index("add-metadata") < out.index("instances start")
    assert "secrets versions destroy" in out  # once collected


def _shim_env(tmp_path: Path, **kw: str) -> tuple[Path, dict[str, str]]:
    state = tmp_path / "state"
    (state / "metadata").mkdir(parents=True)
    (state / "status").write_text("TERMINATED\n", encoding="utf-8")
    (state / "metadata" / "tb-key").write_text("left-by-an-older-driver", encoding="utf-8")
    (tmp_path / "gc").mkdir()
    env = dict(PATH=f"{REH / 'driver-shims'}:{os.environ['PATH']}", TB_REH_STATE=str(state),
               TB_REH_CONTAINER="tb-no-such-container", CLOUDSDK_CONFIG=str(tmp_path / "gc"),
               TB_SA_KEY_FILE="/dev/null", TB_DOOR_DIRECT="1",
               TB_NOT_PRODUCT_EVIDENCE="1", **kw)  # fmt: skip  # plumbing: past the reset gate, as rehearsed
    return state, env


@needs_openssl
def test_the_driver_refuses_a_vm_with_port_80_open_before_any_cap_secret_or_start(tmp_path: Path) -> None:
    state, env = _shim_env(tmp_path, TB_REH_OPEN80="1")
    (state / "secrets" / "tb-gpu-door").mkdir(parents=True)
    r = _driver(tmp_path, "--no-wait", "--patients", "500", "--only", "scenario-it-dump", **env)
    calls = (state / "gcloud.log").read_text(encoding="utf-8")
    assert "default-allow-http opens tcp:80" in r.stderr and "not started" in r.stderr
    assert "set-scheduling" not in calls and "secrets versions add" not in calls and "instances start" not in calls
    assert not list((state / "secrets" / "tb-gpu-door").glob("[0-9]*"))


@needs_openssl
def test_the_driver_needs_the_secret_and_puts_only_its_name_in_the_metadata(tmp_path: Path) -> None:
    state, env = _shim_env(tmp_path)
    r = _driver(tmp_path, "--no-wait", "--patients", "500", "--only", "scenario-it-dump", **env)
    assert "no secret tb-gpu-door: run deploy/gcp/setup-gcp.sh" in r.stderr  # setup-gcp.sh makes it once
    assert "instances start" not in (state / "gcloud.log").read_text(encoding="utf-8")

    (state / "secrets" / "tb-gpu-door").mkdir(parents=True)
    (state / "gcloud.log").unlink()
    r = _driver(tmp_path, "--no-wait", "--patients", "500", "--only", "scenario-it-dump", **env)
    calls = (state / "gcloud.log").read_text(encoding="utf-8")
    meta = sorted(p.name for p in (state / "metadata").iterdir())
    assert "tb-key" not in meta and {"tb-door-secret", "tb-door-cert"} <= set(meta), meta
    assert "secrets versions add tb-gpu-door" in calls and "--metadata tb-door-secret=tb-gpu-door,tb-door-version=1," \
        in calls  # fmt: skip
    assert "PRIVATE KEY" not in (state / "metadata" / "tb-door-cert").read_text()
    for f in (state / "metadata").iterdir():  # no private key in any metadata value
        assert "PRIVATE KEY" not in f.read_text(encoding="utf-8", errors="replace"), f.name
    shard = tmp_path / "out" / "shard-1"
    assert not (shard / "door.key").exists() and not (shard / "door-secret.json").exists()  # only the VM has them
    assert calls.index("remove-metadata") < calls.index("instances start")
    # the rehearsal's "VM" cannot boot here (no container): the start fails after the metadata, as a refused start
    # would; the driver gives up, stops it and destroys the door's version (A8: no version left enabled)
    assert "instances start" in calls and "the start failed" in r.stderr
    assert "secrets versions destroy 1 --secret tb-gpu-door" in calls
    assert not list((state / "secrets" / "tb-gpu-door").glob("[0-9]*"))


# ------------------------------------------------------------------------------------- the VM script and the others
VM = (GCP / "complete-run-vm.sh").read_text(encoding="utf-8")


def test_the_vm_takes_its_door_from_secret_manager_and_serves_tls_on_443_only() -> None:
    assert "md tb-key" not in VM and 'gcloud secrets versions access "$DVER" --secret="$DSEC"' in VM
    assert VM.index("tb-watchdog") < VM.index("gcloud secrets versions access")  # the nets are up first
    assert "listen 443 ssl" in VM and not re.search(r"listen 80\b", VM) and "-p 443:443" in VM and "-p 80:80" not in VM
    assert "http://127.0.0.1/" not in VM and "https://tb-door/tb/progress" in VM
    assert '"${DOOR_TLS[@]}" "https://tb-door/$1/v1/models"' in VM  # the no-key refusal through the TLS door
    assert "TB-NO-KEY" in VM


def test_deploy_gcp_has_no_set_x_and_no_port_80_for_the_gpu_vm() -> None:
    for f in sorted(GCP.glob("*.sh")):
        lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()]
        assert not [ln for ln in lines if re.fullmatch(r"set -[a-z]*x[a-z]*( .*)?", ln)], f.name
    for name in ("complete-run-vm.sh", "gpu-sim-startup.sh", "gpu-pro6000-run.sh", "gpu-swap-run.sh"):
        text = (GCP / name).read_text(encoding="utf-8")
        published = re.findall(r"-p (\d[\d.:]*)", text)  # docker's published ports
        assert published and all(p.startswith("127.0.0.1:") or p == "443:443" for p in published), (name, published)
        assert "attributes/tb-key" not in text, name  # no key from the metadata


def test_the_demo_vm_reads_its_password_from_secret_manager_and_refuses_one_in_metadata() -> None:
    text = (GCP / "demo-vm-startup.sh").read_text(encoding="utf-8")
    assert "gcloud secrets versions access latest --secret=" in text and 'MD/tb-demo-password"' in text
    assert text.index('MD/tb-demo-password"') < text.index("gcloud secrets versions access")
    assert "exit 3" in text and "printf 'TB_DEMO_PASSWORD=%s" in text  # into the root-only env file only


def test_setup_makes_the_secrets_and_grants_only_what_each_needs() -> None:
    text = (GCP / "setup-gcp.sh").read_text(encoding="utf-8")
    assert "secretmanager.googleapis.com" in text and "for SECRET in tb-gpu-door tb-demo-password" in text
    assert "roles/secretmanager.secretAccessor" in text and "roles/secretmanager.secretVersionManager" in text
    assert "roles/secretmanager.admin" not in text and "read -r -s" in text


# ------------------------------------------------------------------------------------- the hosted demo
DIGEST = "asia-east1-docker.pkg.dev/demo-proj/tb-poc/demo@sha256:" + "ab" * 32


@pytest.mark.parametrize("key", ["TB_MD_TB_OWNER_PASSWORD", "TB_MD_TB_TUNNEL_TOKEN", "TB_MD_TB_KEY",
                                 "TB_MD_TB_ACCOUNTS_JP"])  # fmt: skip
def test_the_hosted_demo_refuses_a_secret_in_its_metadata(tmp_path: Path, key: str) -> None:
    e = {k: v for k, v in os.environ.items() if not k.startswith("TB_MD_")}
    e.update(HOME=str(tmp_path), TB_MD_TB_IMAGE=DIGEST, TB_MD_TB_DOMAIN="poc.example.org")
    ok = subprocess.run(["bash", str(GCP / "hosted-demo-startup.sh"), "--dry-run"], env=e, capture_output=True,
                        text=True, check=False, timeout=60)  # fmt: skip
    assert ok.returncode == 0, ok.stderr
    e[key] = "value-that-must-never-show-0123"
    r = subprocess.run(["bash", str(GCP / "hosted-demo-startup.sh"), "--dry-run"], env=e, capture_output=True,
                       text=True, check=False, timeout=60)  # fmt: skip
    assert r.returncode == 3 and "looks like a secret: put it in Secret Manager" in r.stderr
    assert "value-that-must-never-show" not in r.stdout + r.stderr and "docker run" not in r.stdout


# ------------------------------------------------------------------------------------- the rehearsal
def test_the_rehearsal_has_the_bucket_case_the_secret_and_the_serving_record() -> None:
    sh = (REH / "rehearse.sh").read_text(encoding="utf-8")
    assert "bucket)" in sh and "TB_BUCKET=gs://tb-rehearsal-bucket driven bucket" in sh
    assert "CASES=(${*//,/ })" in sh  # make rehearse CASES=run-a,bucket
    assert "tb-key=" not in sh and 'mkdir -p "$S/secrets/tb-gpu-door"' in sh
    assert os.access(REH / "shims" / "gcloud", os.X_OK)
    vm_gcloud = (REH / "shims" / "gcloud").read_text(encoding="utf-8")
    assert '"secrets versions access")' in vm_gcloud and '"storage cp "*)' in vm_gcloud
    docker = (REH / "shims" / "docker").read_text(encoding="utf-8")
    assert "inspect)" in docker and "vllm.__version__" in docker  # tools/serving_config.py capture runs in run-a
    chk = (REH / "check.py").read_text(encoding="utf-8")
    assert '"bucket"' in chk and "def check_door" in chk and "def check_record" in chk


def test_the_rehearsal_vm_gcloud_shim_reads_the_secret_and_the_bucket(tmp_path: Path) -> None:
    """The VM-side shim as the VM script calls it, with its state folder moved to tmp (it is /rehearsal/s there)."""
    shim = (REH / "shims" / "gcloud").read_text(encoding="utf-8").replace("S=/rehearsal/s", f"S={tmp_path}")
    (tmp_path / "gcloud").write_text(shim, encoding="utf-8")
    (tmp_path / "secrets" / "tb-gpu-door").mkdir(parents=True)
    (tmp_path / "secrets" / "tb-gpu-door" / "3").write_text('{"key": "k"}', encoding="utf-8")
    (tmp_path / "bucket" / "b" / "runs").mkdir(parents=True)
    (tmp_path / "bucket" / "b" / "runs" / "src.tgz").write_bytes(b"code")

    def g(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(tmp_path / "gcloud"), *a], capture_output=True, text=True, check=False)

    assert g("secrets", "versions", "access", "3", "--secret=tb-gpu-door").stdout == '{"key": "k"}'
    assert g("secrets", "versions", "access", "4", "--secret=tb-gpu-door").returncode != 0
    assert g("storage", "cp", "gs://b/runs/src.tgz", str(tmp_path / "got")).returncode == 0
    assert (tmp_path / "got").read_bytes() == b"code"
    assert g("compute", "instances", "list").returncode != 0  # anything else is not rehearsed
    assert '{"key"' not in (tmp_path / "vm-gcloud.log").read_text(encoding="utf-8")
