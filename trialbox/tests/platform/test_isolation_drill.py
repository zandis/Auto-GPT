"""The offline half of the shared-host isolation drill (T-319, D-432): what CI can show without a cluster.

* a NetworkPolicy with one extra egress host fails ``doctor --platform`` (the card's negative test; the live probe in
  ``test_isolation_probe.py`` shows the same on a cluster);
* the platform KEK variant: the ``kms`` back end of ``tb_common.kek`` against a mock transit KMS on the loopback;
* the noisy-neighbour measurement against a fake model server and a fake neighbour.
"""

from __future__ import annotations

import base64
import copy
import json
import secrets
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tb_common import kek as K

from tests.platform.kustomize_lite import build
from tools import keys
from tools.trialbox import noisy_neighbour as nn
from tools.trialbox import platform as pf

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
ENV = {"TB_ENV": "TEST", "SMTP_HOST": "smtp.hospa.test"}


def _resolve(host: str) -> list[str]:
    return ["10.20.0.25"] if host else []


def _inputs(objs: list[dict[str, Any]]) -> pf.PlatformInputs:
    return pf.PlatformInputs(
        pf.PlatformState(copy.deepcopy(objs), "manifests", "trialbox"),
        pf.load_release(),
        dict(ENV),
        connect=lambda h, p: None,
        sntp=lambda s: 0.0,
        resolve=_resolve,
    )


def _with_egress() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eg = pf._egress()  # type: ignore[attr-defined]
    pols, warn = eg.render_networkpolicy(eg.allowlist(dict(ENV)), _resolve)
    assert pols and not warn
    return [*build(ROOT / "deploy" / "platform" / "overlays" / "shared-quota"), *pols], pols


# ------------------------------------------------------------------------------------------------ egress
def test_the_rendered_egress_passes() -> None:
    objs, _ = _with_egress()
    c = pf.check_network_policy(_inputs(objs))
    assert c.status == "PASS", c.detail


def test_one_extra_egress_host_fails_the_probe() -> None:
    """The card's negative: one more host in an egress policy, declared or not, is a FAIL."""
    objs, pols = _with_egress()
    name = pols[0]["metadata"]["name"]
    # (a) an extra ipBlock only: an address no allowlist entry renders
    sneaky = copy.deepcopy(objs)
    pol = next(o for o in sneaky if o["kind"] == "NetworkPolicy" and o["metadata"]["name"] == name)
    pol["spec"]["egress"].append({"to": [{"ipBlock": {"cidr": "203.0.113.9/32"}}], "ports": [{"port": 443}]})
    c = pf.check_network_policy(_inputs(sneaky))
    assert c.status == "FAIL" and "203.0.113.9/32" in c.detail, c.detail
    # (b) an extra host named in the annotation too
    named = copy.deepcopy(sneaky)
    pol = next(o for o in named if o["kind"] == "NetworkPolicy" and o["metadata"]["name"] == name)
    ann = pol["metadata"]["annotations"]
    ann["trialbox.io/egress-hosts"] += ",exfil.example.net:443"
    c = pf.check_network_policy(_inputs(named))
    assert c.status == "FAIL" and "exfil.example.net:443" in c.detail, c.detail


# ------------------------------------------------------------------------------------------------ kms back end
class _Transit(BaseHTTPRequestHandler):
    keys: ClassVar[dict[str, bytes]] = {}
    token = ""
    tamper = False

    def log_message(self, *a: Any) -> None:
        pass

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n))
        _, op, key = self.path.rsplit("/", 2)
        if self.headers.get("X-Vault-Token") != self.token or key not in self.keys:
            self.send_response(403)
            self.end_headers()
            return
        mask = self.keys[key]
        if op == "encrypt":
            pt = base64.b64decode(body["plaintext"])
            data = {
                "ciphertext": "vault:v1:"
                + base64.b64encode(bytes(a ^ b for a, b in zip(pt, mask, strict=True))).decode()
            }
        else:
            ct = base64.b64decode(body["ciphertext"].removeprefix("vault:v1:"))
            pt = bytes(a ^ b for a, b in zip(ct, mask, strict=True))
            if self.tamper:
                pt = bytes(32)
            data = {"plaintext": base64.b64encode(pt).decode()}
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def kms() -> Iterator[str]:
    _Transit.keys = {"trialbox": secrets.token_bytes(32)}
    _Transit.token = "t-" + secrets.token_hex(8)
    _Transit.tamper = False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Transit)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1/transit"
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_platform_kek_lives_in_the_kms(kms: str, tmp_path: Path) -> None:
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(secrets.token_bytes(32))
    env = {"TB_ENV": "TEST", "TB_KMS_TOKEN": _Transit.token, "TB_KEK_FILE": str(tmp_path / "none")}
    rc = keys.main(["init", "--secrets", str(sec), "--backend", "kms", "--kms-url", kms, "--kms-key", "trialbox"], env)
    assert rc == 0
    meta = K.read_meta(sec)
    assert meta is not None and meta["backend"] == "kms" and meta["kms_ciphertext"].startswith("vault:v1:")
    assert not (sec / "site_hmac.key").exists() and (sec / "site_hmac.key.wrapped").exists()
    kek = K.load_kek(sec, env)  # straight from the KMS: no KEK file anywhere
    assert K.kek_id(kek) == meta["kek_id"]
    assert len(K.load_key_file(sec / "site_hmac.key", env)) == 32
    # no token: locked, not a key made in its place
    with pytest.raises(K.KekLockedError):
        K.load_kek(sec, {"TB_KEK_FILE": str(tmp_path / "none")})
    # a wrong token: refused, and the token is not in the message
    with pytest.raises(K.KekError) as e:
        K.load_kek(sec, {**env, "TB_KMS_TOKEN": "wrong-token"})
    assert "403" in str(e.value) and "wrong-token" not in str(e.value)
    # a KMS that answers with another key: refused by the KEK id
    _Transit.tamper = True
    with pytest.raises(K.KekError, match="not this box's KEK"):
        K.load_kek(sec, env)
    _Transit.tamper = False
    # unseal writes the runtime file, as for the other back ends
    out = tmp_path / "run-kek"
    assert keys.main(["unseal", "--secrets", str(sec), "--out", str(out)], env) == 0
    assert out.read_bytes() == kek


def test_the_kms_address_must_be_https() -> None:
    with pytest.raises(K.KekError, match="not https"):
        K.kms_seal(bytes(32), "http://kms.hosp.test/v1/transit", "trialbox", "t")
    with pytest.raises(K.KekError, match="key name"):
        K.kms_seal(bytes(32), "https://kms.hosp.test/v1/transit", "../sys", "t")


def test_a_kms_token_secret_is_not_a_kek_secret() -> None:
    """On the platform the KMS token is a Secret (revocable, useless without the KMS); the KEK never is."""
    token = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "trialbox-kms"},
        "stringData": {"TB_KMS_TOKEN": "x"},
    }
    c = pf.check_kek_custody(_inputs([token]))
    assert c.status == "PASS", c.detail
    plain = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "keys"}, "stringData": {"pid_map.key": "x"}}
    assert pf.check_kek_custody(_inputs([token, plain])).status == "FAIL"


# ------------------------------------------------------------------------------------------------ noisy neighbour
def test_noisy_neighbour_verdicts() -> None:
    assert nn.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0 and nn.percentile([], 95) == 0.0
    t = [0.0]
    load = {"on": False}
    stopped = []

    def clock() -> float:
        return t[0]

    def call() -> None:
        t[0] += 0.3 if load["on"] else 0.1

    def neighbour() -> Any:
        load["on"] = True

        def stop() -> None:
            stopped.append(1)
            load["on"] = False

        return stop

    res = nn.measure(call, 10, neighbour, clock=clock)
    assert res["verdict"] == "FAIL" and res["p95_ratio"] == pytest.approx(3.0) and stopped == [1]
    res = nn.measure(call, 10, neighbour, clock=clock, max_ratio=4.0)
    assert res["verdict"] == "PASS"


class _Model(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:
        pass

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        ok = self.headers.get("Authorization") == "Bearer k-test"
        out = b'{"choices": [{"message": {"content": "ready"}}]}'
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def test_noisy_neighbour_cli_writes_the_record(tmp_path: Path) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"
        out = tmp_path / "nn.json"
        args = ["--url", url, "--model", "judge", "--requests", "3", "--warmup", "0", "--max-ratio", "1000",
                "--neighbour", f"{sys.executable} -c 'import time; time.sleep(30)'", "--out", str(out)]  # fmt: skip
        assert nn.main(args, {"TB_LLM_API_KEY": "k-test"}) == 0
        rec = json.loads(out.read_text())
        assert rec["schema"] == nn.SCHEMA and rec["verdict"] == "PASS" and rec["alone"]["ok"] == 3
        assert "k-test" not in out.read_text()
        assert nn.main(args, {"TB_LLM_API_KEY": "wrong"}) == 2  # the first request refused: no record
    finally:
        srv.shutdown()
        srv.server_close()


def test_runbook_kms_token_file(kms: str, tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(_Transit.token + "\n")
    token_file.chmod(0o644)
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(secrets.token_bytes(32))
    args = ["init", "--secrets", str(sec), "--backend", "kms", "--kms-url", kms,
            "--kms-key", next(iter(_Transit.keys)), "--kms-token-file", str(token_file)]  # fmt: skip
    assert keys.main(args, {"TB_ENV": "TEST"}) == 1
    assert not (sec / K.META_FILE).exists()
    token_file.chmod(0o600)
    assert keys.main(args, {"TB_ENV": "TEST"}) == 0
