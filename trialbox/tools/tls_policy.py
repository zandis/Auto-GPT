"""tls_policy: the box's TLS as served, judged against one policy file (plan 10 row 10G-48, review 21 OT-12, D-1328).

The policy is ``deploy/security/tls-policy.json``: the protocols each target may offer (the box's 443 and the
two-device link), AEAD ciphers with forward secrecy only, no cipher of the weak categories, the certificate's key size
and signature, HSTS on the box, a client certificate on the link.

    python -m tools.tls_policy judge --target box  build/security/<release>/tls.json
    python -m tools.tls_policy judge --target link build/security/<release>/tls-link.json
    python -m tools.tls_policy caddyfile [deploy/identity/Caddyfile]

``judge`` reads a result of testssl.sh (``--jsonfile``: a list of objects with ``id``, ``severity`` and ``finding``;
``--jsonfile-pretty`` is read too) and prints one ``FAIL <id>: <why>`` line per failing id, exit 1; ``PASS`` and
exit 0 when nothing fails. An id the policy needs that the result does not hold fails as missing: a scan that did not
look cannot pass. ``caddyfile`` reads the shipped Caddyfile and holds its TLS settings to the same policy without a
running box: every ``protocols`` within the allowed ones, every ``ciphers`` suite ECDHE with AEAD, every HTTPS site
with a ``tls`` directive and HSTS of at least the policy's age (its imports followed), and a plain-HTTP site only on
the loopback. Exit 2 on a file that cannot be read. testssl.sh itself is never run, fetched or kept here: it runs from
the test laptop at release (RUNBOOK §12, the TLS check per release).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "deploy" / "security" / "tls-policy.json"
CADDYFILE = ROOT / "deploy" / "identity" / "Caddyfile"
PROTOCOL_IDS = ("SSLv2", "SSLv3", "TLS1", "TLS1_1", "TLS1_2", "TLS1_3")
CERT_IDS = ("cert_keySize", "cert_signatureAlgorithm", "cert_expirationStatus")
AEAD = ("GCM", "CHACHA20", "CCM")
TLS13_SUITES = re.compile(r"^TLS_(AES_\d+_(GCM|CCM)|CHACHA20_POLY1305)(_\d+)?_SHA\d+$")
CIPHER_NAME = re.compile(r"^(?:[A-Z0-9]+(?:-[A-Z0-9]+)+|TLS_[A-Z0-9_]+)$")


def load_policy(path: Path = POLICY) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


# ------------------------------------------------------------------------------------------- testssl.sh result
def findings(result: Any) -> list[dict[str, str]]:
    """The flat list of ``{id, severity, finding}`` of a ``--jsonfile`` or ``--jsonfile-pretty`` result."""
    out: list[dict[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "finding" in node:
                out.append({k: str(node.get(k, "")) for k in ("id", "severity", "finding")})
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(result)
    return out


def _offered(finding: str) -> bool:
    f = finding.strip().lower()
    return "offered" in f and "not offered" not in f


def cipher_names(text: str) -> list[str]:
    """The cipher names in a testssl.sh cipher line (OpenSSL's ``ECDHE-RSA-AES128-GCM-SHA256`` or IANA's)."""
    return [t for t in text.split() if CIPHER_NAME.match(t) and not t.startswith(("TLSv", "SSLv"))]


def cipher_problem(name: str, aead_only: bool, forward_secrecy: bool) -> str:
    if TLS13_SUITES.match(name):
        return ""  # TLS 1.3 suites are AEAD with an ephemeral key exchange by definition
    if aead_only and not any(a in name for a in AEAD):
        return f"{name} is not an AEAD cipher (CBC, RC4 or NULL)"
    if forward_secrecy and not name.startswith(("ECDHE-", "DHE-", "TLS_ECDHE_", "TLS_DHE_")):
        return f"{name} has no forward secrecy"
    return ""


def _base_id(fid: str) -> str:
    return fid.split(" ", 1)[0]  # "cert_keySize <cert#1>" -> "cert_keySize"


def judge(result: Any, target: str, policy: dict[str, Any]) -> list[str]:
    """The failing ids of one testssl.sh result for one target, each ``<id>: <why>``; empty when it meets the policy."""
    rule = policy["targets"][target]
    rows = findings(result)
    by_id: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_id.setdefault(_base_id(r["id"]), []).append(r)
    out: list[str] = []
    if not rows:
        return ["result: no testssl.sh findings in the file"]
    for r in rows:
        if r["severity"].upper() in policy["fail_on_severity"]:
            out.append(f"{r['id']}: severity {r['severity']}: {r['finding']}")
    for pid in PROTOCOL_IDS:
        got = by_id.get(pid)
        if not got:
            out.append(f"{pid}: missing from the result")
            continue
        offered = any(_offered(r["finding"]) for r in got)
        if pid in rule["protocols_forbidden"] and offered:
            out.append(f"{pid}: offered; the policy allows {', '.join(rule['protocols_allowed'])} only")
    if not any(_offered(r["finding"]) for p in rule["protocols_allowed"] for r in by_id.get(p, [])):
        out.append(f"protocols: none of {', '.join(rule['protocols_allowed'])} offered")
    for cid in policy["cipher_categories_not_offered"]:
        got = by_id.get(cid)
        if not got:
            out.append(f"{cid}: missing from the result")
        elif any(_offered(r["finding"]) for r in got):
            out.append(f"{cid}: offered")
    names = [(r["id"], n) for r in rows if r["id"].startswith("cipher") and not r["id"].startswith("cipherlist_")
             for n in cipher_names(r["finding"])]  # fmt: skip
    if not names:
        out.append("ciphers: no offered cipher listed in the result (run with --cipher-per-proto)")
    for fid, name in names:
        why = cipher_problem(name, rule["aead_only"], rule["forward_secrecy"])
        if why:
            out.append(f"{fid}: {why}")
    out += _certificate(by_id, policy["certificate"])
    hsts = rule.get("hsts_min_seconds")
    if hsts:
        out += _hsts(by_id, int(hsts))
    if rule.get("client_certificate") == "required":
        got = by_id.get("clientAuth")
        if not got:
            out.append("clientAuth: missing from the result")
        elif not any("required" in r["finding"].lower() for r in got):
            out.append(f"clientAuth: {got[0]['finding']!r}; the policy requires a client certificate")
    return out


def _certificate(by_id: dict[str, list[dict[str, str]]], rule: dict[str, Any]) -> list[str]:
    out = [f"{cid}: missing from the result" for cid in CERT_IDS if cid not in by_id]
    for r in by_id.get("cert_keySize", []):
        m = re.search(r"\b(RSA|EC|ECDSA|EdDSA)\b\D*(\d+)\s*bits", r["finding"])
        if not m:
            out.append(f"{r['id']}: cannot read the key size from {r['finding']!r}")
            continue
        kind, bits = m.group(1), int(m.group(2))
        need = rule["rsa_min_bits"] if kind == "RSA" else rule["ec_min_bits"]
        if bits < need:
            out.append(f"{r['id']}: {kind} {bits} bits; the policy needs at least {need}")
    for r in by_id.get("cert_signatureAlgorithm", []):
        sig = r["finding"].upper().replace("-", "")
        bad = [s for s in rule["forbidden_signature"] if re.search(rf"\b{s}\b", sig)]
        if bad:
            out.append(f"{r['id']}: signed with {r['finding']!r}")
    if rule.get("expired_fails"):
        for r in by_id.get("cert_expirationStatus", []):
            if "expired" in r["finding"].lower():
                out.append(f"{r['id']}: {r['finding']}")
    return out


def _hsts(by_id: dict[str, list[dict[str, str]]], need: int) -> list[str]:
    for r in by_id.get("HSTS", []):
        if "not offered" in r["finding"].lower():
            return [f"HSTS: not offered; the policy needs max-age of at least {need}"]
    got = by_id.get("HSTS_time")
    if not got:
        return ["HSTS_time: missing from the result"]
    m = re.search(r"=?\s*(\d+)\s*seconds", got[0]["finding"]) or re.search(r"(\d+)", got[0]["finding"])
    seconds = int(m.group(1)) if m else 0
    if "day" in got[0]["finding"] and "second" not in got[0]["finding"]:
        seconds *= 86400
    if seconds < need:
        return [f"HSTS_time: {got[0]['finding']!r}; the policy needs at least {need} seconds"]
    return []


# ------------------------------------------------------------------------------------------------- Caddyfile
class Block:
    def __init__(self, head: str) -> None:
        self.head = head
        self.lines: list[str] = []  # statements, in order
        self.children: list[Block] = []


def parse_caddyfile(text: str) -> Block:
    """The Caddyfile as nested blocks (enough for its TLS settings: no quoting across lines, no heredocs)."""
    top = Block("")
    stack = [top]
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        if line == "}":
            if len(stack) == 1:
                raise ValueError("a closing brace with no block open")
            stack.pop()
        elif line.endswith("{"):
            child = Block(line[:-1].strip())
            stack[-1].children.append(child)
            stack.append(child)
        else:
            stack[-1].lines.append(line)
    if len(stack) != 1:
        raise ValueError("a block is not closed")
    return top


def _walk(block: Block) -> Iterable[tuple[Block, str]]:
    for line in block.lines:
        yield block, line
    for c in block.children:
        yield block, c.head  # a block's head is a statement of its parent ("header", "tls ... {")
        yield from _walk(c)


def _snippets(top: Block) -> dict[str, Block]:
    return {b.head[1:-1]: b for b in top.children if b.head.startswith("(") and b.head.endswith(")")}


def _expand(block: Block, snippets: dict[str, Block], seen: tuple[str, ...] = ()) -> list[str]:
    """Every statement of a block with its imports followed; a name with a ``{$VAR:default}`` takes every snippet
    the placeholder could name."""
    out: list[str] = []
    for _b, line in _walk(block):
        out.append(line)
        parts = line.split()
        if parts[:1] == ["import"] and len(parts) > 1:
            pat = re.escape(parts[1])
            pat = re.sub(r"\\\{\\\$[^}]*\\\}", ".+", pat)
            for name, snip in snippets.items():
                if re.fullmatch(pat, name) and name not in seen:
                    out += _expand(snip, snippets, (*seen, name))
    return out


def _sites(top: Block) -> list[Block]:
    return [b for b in top.children if b.head and not (b.head.startswith("(") and b.head.endswith(")"))]


def _plain_http(address: str) -> bool:
    return address.startswith("http://") or address.endswith(":80")


def caddyfile_problems(text: str, policy: dict[str, Any]) -> list[str]:
    rule = policy["caddyfile"]
    allowed = rule["protocols"]
    try:
        top = parse_caddyfile(text)
    except ValueError as exc:
        return [f"Caddyfile: {exc}"]
    out: list[str] = []
    for _b, line in _walk(top):
        parts = line.split()
        if parts[:1] == ["protocols"] and any(p.startswith(("tls", "ssl")) for p in parts[1:]):
            for p in parts[1:]:
                if p not in allowed:
                    out.append(f"protocols {' '.join(parts[1:])}: {p} is not one of {', '.join(allowed)}")
        if parts[:1] == ["ciphers"]:
            for suite in parts[1:]:
                why = cipher_problem(suite, True, True)
                if why:
                    out.append(f"ciphers: {why}")
    snippets = _snippets(top)
    sites = _sites(top)
    if not sites:
        out.append("Caddyfile: no site")
    for site in sites:
        addresses = [a for a in re.split(r"[\s,]+", site.head) if a]
        body = _expand(site, snippets)
        if all(_plain_http(a) for a in addresses):
            hosts = {re.sub(r"^http://|:\d+$", "", a) for a in addresses}
            binds = [w for line in body if line.split()[:1] == ["bind"] for w in line.split()[1:]]
            loop = set(rule["plain_http_only_on"])
            if not (hosts <= loop and binds and set(binds) <= loop):
                out.append(f"site {site.head}: plain HTTP not bound to the loopback")
            continue
        if not any(line.split()[:1] == ["tls"] for line in body):
            out.append(f"site {site.head}: no tls directive")
        if any(re.search(r"(^|\s)-Strict-Transport-Security\b", line) for line in body):
            out.append(f"site {site.head}: removes Strict-Transport-Security")
        ages = [int(m.group(1)) for line in body if "Strict-Transport-Security" in line and "-Strict" not in line
                for m in [re.search(r"max-age=(\d+)", line)] if m]  # fmt: skip
        if not ages:
            out.append(f"site {site.head}: no Strict-Transport-Security header with a max-age")
        elif min(ages) < int(rule["hsts_min_seconds"]):
            out.append(f"site {site.head}: HSTS max-age={min(ages)}; the policy needs {rule['hsts_min_seconds']}")
    return out


# ------------------------------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--policy", type=Path, default=POLICY)
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge", help="judge a testssl.sh JSON result")
    j.add_argument("--target", choices=("box", "link"), required=True)
    j.add_argument("result", type=Path)
    c = sub.add_parser("caddyfile", help="hold a Caddyfile's TLS settings to the policy")
    c.add_argument("file", type=Path, nargs="?", default=CADDYFILE)
    args = ap.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if args.cmd == "judge":
            problems = judge(json.loads(args.result.read_text(encoding="utf-8")), args.target, policy)
        else:
            problems = caddyfile_problems(args.file.read_text(encoding="utf-8"), policy)
    except (OSError, ValueError, KeyError) as exc:
        print(f"tls_policy: {exc}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
