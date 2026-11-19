"""10G-48 (review 21 OT-12, D-1328): the TLS policy file, the judge of a testssl.sh result, and the shipped Caddyfile.

The results are hand-written in testssl.sh's ``--jsonfile`` form (``tests/fixtures/tls/``): one that meets the policy
per target, and copies of it weakened one way each. No scan runs here. The Caddyfile check reads
``deploy/identity/Caddyfile`` as shipped and weakened copies of it, so "a weakened Caddyfile fails" needs no box.
"""

from __future__ import annotations

import copy
import json
import ssl
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools import tls_policy
from tools import two_device as td

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "tls"
CADDY = (ROOT / "deploy" / "identity" / "Caddyfile").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _result(name: str) -> list[dict[str, Any]]:
    return list(json.loads((FIX / name).read_text(encoding="utf-8")))


def _set(rows: list[dict[str, Any]], fid: str, finding: str, severity: str = "") -> list[dict[str, Any]]:
    rows = copy.deepcopy(rows)
    hit = [r for r in rows if r["id"] == fid]
    if not hit:
        rows.append({"id": fid, "ip": "box.test/192.0.2.10", "port": "443", "severity": severity or "INFO",
                     "cve": "", "cwe": "", "finding": finding})  # fmt: skip
    for r in hit:
        r["finding"] = finding
        if severity:
            r["severity"] = severity
    return rows


def _drop(rows: list[dict[str, Any]], fid: str) -> list[dict[str, Any]]:
    return [r for r in copy.deepcopy(rows) if r["id"] != fid]


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return tls_policy.load_policy()


def test_the_policy_holds_the_reviews_and_the_repositorys_tls_decisions(policy: dict[str, Any]) -> None:
    box, link = policy["targets"]["box"], policy["targets"]["link"]
    # review 21 OT-12: TLS 1.2/1.3, no CBC-SHA1, HSTS; docs/security/02-network.md: "TLS 1.2 or 1.3" at Caddy
    assert box["protocols_allowed"] == ["TLS1_2", "TLS1_3"]
    assert "TLS1_1" in box["protocols_forbidden"] and "TLS1" in box["protocols_forbidden"]
    assert box["aead_only"] and box["forward_secrecy"]
    assert "cipherlist_OBSOLETED" in policy["cipher_categories_not_offered"]  # the CBC ciphers
    # the Caddyfile's one year (D-193); includeSubDomains stays open (D-447) and is not asked
    assert box["hsts_min_seconds"] == 31536000 == policy["caddyfile"]["hsts_min_seconds"]
    assert policy["caddyfile"]["protocols"] == ["tls1.2", "tls1.3"]
    # the link: mutual TLS 1.3 (tools/two_device.py)
    assert link["protocols_allowed"] == ["TLS1_3"] and link["client_certificate"] == "required"
    assert link["hsts_min_seconds"] is None
    assert policy["decision"] == "D-1328"


def test_the_link_policy_is_what_the_link_code_sets(policy: dict[str, Any], tmp_path: Path) -> None:
    td.make_certs(tmp_path, days=2)
    ctx = td._context(td.LinkConfig("spark", "127.0.0.1", tmp_path), server=True)
    names = {ssl.TLSVersion.TLSv1_2: "TLS1_2", ssl.TLSVersion.TLSv1_3: "TLS1_3"}
    assert policy["targets"]["link"]["protocols_allowed"] == [names[ctx.minimum_version]]
    assert ctx.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("target", ["box", "link"])
def test_a_result_that_meets_the_policy_passes(target: str, policy: dict[str, Any]) -> None:
    assert tls_policy.judge(_result(f"{target}-pass.json"), target, policy) == []


WEAKENED_BOX: dict[str, tuple[Callable[[list[dict[str, Any]]], list[dict[str, Any]]], str]] = {
    "tls10 offered": (lambda r: _set(r, "TLS1", "offered (deprecated)", "LOW"), "TLS1:"),
    "tls11 offered": (lambda r: _set(r, "TLS1_1", "offered (deprecated)", "LOW"), "TLS1_1:"),
    "sslv3 offered": (lambda r: _set(r, "SSLv3", "offered", "HIGH"), "SSLv3:"),
    "cbc sha1 cipher": (
        lambda r: _set(
            r,
            "cipher-tls1_2_xc009",
            "TLSv1.2   xc009   ECDHE-ECDSA-AES128-SHA   ECDH 253   AES   128   TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA",
        ),
        "cipher-tls1_2_xc009:",
    ),
    "static rsa key exchange": (
        lambda r: _set(
            r,
            "cipher-tls1_2_x9c",
            "TLSv1.2   x9c   AES128-GCM-SHA256   RSA   AESGCM   128   TLS_RSA_WITH_AES_128_GCM_SHA256",
        ),
        "cipher-tls1_2_x9c:",
    ),
    "obsoleted category": (lambda r: _set(r, "cipherlist_OBSOLETED", "offered", "LOW"), "cipherlist_OBSOLETED:"),
    "3des category": (lambda r: _set(r, "cipherlist_3DES_IDEA", "offered", "MEDIUM"), "cipherlist_3DES_IDEA:"),
    "no hsts": (lambda r: _set(_drop(r, "HSTS_time"), "HSTS", "not offered", "LOW"), "HSTS:"),
    "short hsts": (lambda r: _set(r, "HSTS_time", "1 day (=86400 seconds) < 15552000 seconds", "MEDIUM"), "HSTS_time:"),
    "small rsa key": (lambda r: _set(r, "cert_keySize", "RSA 1024 bits", "HIGH"), "cert_keySize:"),
    "sha1 signature": (
        lambda r: _set(r, "cert_signatureAlgorithm", "SHA1 with RSA", "MEDIUM"),
        "cert_signatureAlgorithm:",
    ),
    "expired": (lambda r: _set(r, "cert_expirationStatus", "expired", "CRITICAL"), "cert_expirationStatus:"),
    "a high finding": (lambda r: _set(r, "ROBOT", "VULNERABLE (NOT ok)", "HIGH"), "ROBOT:"),
    "protocols not looked at": (lambda r: _drop(r, "TLS1_1"), "TLS1_1: missing"),
    "ciphers not listed": (lambda r: [x for x in r if not x["id"].startswith("cipher-")], "ciphers:"),
}


@pytest.mark.parametrize("name", sorted(WEAKENED_BOX))
def test_a_box_result_weakened_one_way_fails_on_that_id(name: str, policy: dict[str, Any]) -> None:
    weaken, expect = WEAKENED_BOX[name]
    problems = tls_policy.judge(weaken(_result("box-pass.json")), "box", policy)
    assert any(p.startswith(expect) for p in problems), problems


@pytest.mark.parametrize(
    ("fid", "finding", "expect"),
    [
        ("TLS1_2", "offered", "TLS1_2: offered"),  # the link is TLS 1.3 only
        ("clientAuth", "optional", "clientAuth:"),
        ("clientAuth", "none", "clientAuth:"),
    ],
)
def test_a_link_result_weakened_one_way_fails(fid: str, finding: str, expect: str, policy: dict[str, Any]) -> None:
    problems = tls_policy.judge(_set(_result("link-pass.json"), fid, finding), "link", policy)
    assert any(p.startswith(expect) for p in problems), problems


def test_a_pretty_result_is_read_too(policy: dict[str, Any]) -> None:
    pretty = {"Invocation": "testssl.sh --jsonfile-pretty", "scanResult": [{"targetHost": "box.test",
              "protocols": _result("box-pass.json")}]}  # fmt: skip
    assert tls_policy.judge(pretty, "box", policy) == []
    assert tls_policy.judge([], "box", policy) == ["result: no testssl.sh findings in the file"]


def test_the_command_exits_1_with_the_failing_ids_and_0_on_a_pass(tmp_path: Path) -> None:
    bad = tmp_path / "tls.json"
    bad.write_text(json.dumps(_set(_result("box-pass.json"), "TLS1_1", "offered", "LOW")), encoding="utf-8")
    run = [sys.executable, "-m", "tools.tls_policy", "judge", "--target", "box"]
    p = subprocess.run([*run, str(bad)], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 1 and "FAIL TLS1_1: offered" in p.stdout, p.stdout + p.stderr
    p = subprocess.run([*run, str(FIX / "box-pass.json")], cwd=ROOT, capture_output=True, text=True, timeout=60,
                       check=False)  # fmt: skip
    assert p.returncode == 0 and p.stdout.strip() == "PASS", p.stdout + p.stderr
    p = subprocess.run([*run, str(tmp_path / "none.json")], cwd=ROOT, capture_output=True, text=True, timeout=60,
                       check=False)  # fmt: skip
    assert p.returncode == 2


# ------------------------------------------------------------------------------------------------- the Caddyfile
def test_the_shipped_caddyfile_meets_the_policy(policy: dict[str, Any]) -> None:
    assert tls_policy.caddyfile_problems(CADDY, policy) == []
    p = subprocess.run([sys.executable, "-m", "tools.tls_policy", "caddyfile"], cwd=ROOT, capture_output=True,
                       text=True, timeout=60, check=False)  # fmt: skip
    assert p.returncode == 0 and p.stdout.strip() == "PASS", p.stdout + p.stderr


def _swap(old: str, new: str) -> str:
    assert old in CADDY, old
    return CADDY.replace(old, new, 1)


WEAKENED_CADDY = {
    "tls 1.0 allowed": (_swap("protocols tls1.2 tls1.3", "protocols tls1.0 tls1.3"), "protocols"),
    "tls 1.1 allowed": (_swap("protocols tls1.2 tls1.3", "protocols tls1.1 tls1.3"), "protocols"),
    "cbc sha1 suite": (
        _swap(
            "protocols tls1.2 tls1.3",
            "protocols tls1.2 tls1.3\n\t\tciphers "
            "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
        ),
        "ciphers",
    ),
    "hsts removed": (_swap('\t\tStrict-Transport-Security "max-age=31536000"\n', ""), "site"),
    "hsts one day": (_swap('"max-age=31536000"', '"max-age=86400"'), "site"),
    "hsts stripped": (_swap("\t\t-Server\n", "\t\t-Server\n\t\t-Strict-Transport-Security\n"), "site"),
    "a site without the edge": (
        _swap("{$TB_AUTH_HOSTNAME:auth.invalid}:443 {\n\timport edge\n", "{$TB_AUTH_HOSTNAME:auth.invalid}:443 {\n"),
        "site",
    ),
    "plain http on every address": (CADDY + '\nhttp://:80 {\n\trespond "hello" 200\n}\n', "site http://:80"),
    "health site off the loopback": (_swap("\tbind 127.0.0.1\n", "\tbind 0.0.0.0\n"), "site http://127.0.0.1:2020"),
}


@pytest.mark.parametrize("name", sorted(WEAKENED_CADDY))
def test_a_weakened_caddyfile_fails(name: str, policy: dict[str, Any], tmp_path: Path) -> None:
    text, expect = WEAKENED_CADDY[name]
    problems = tls_policy.caddyfile_problems(text, policy)
    assert any(p.startswith(expect) for p in problems), problems
    f = tmp_path / "Caddyfile"
    f.write_text(text, encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "tools.tls_policy", "caddyfile", str(f)], cwd=ROOT,
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert p.returncode == 1 and "FAIL " in p.stdout, p.stdout + p.stderr


def test_an_unbalanced_caddyfile_is_a_failure_not_a_pass(policy: dict[str, Any]) -> None:
    assert tls_policy.caddyfile_problems(CADDY + "\n}\n", policy) == ["Caddyfile: a closing brace with no block open"]
    assert tls_policy.caddyfile_problems("x.test:443 {\n\ttls internal\n", policy) == [
        "Caddyfile: a block is not closed"
    ]
