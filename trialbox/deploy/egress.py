#!/usr/bin/env python3
"""Container egress allowlist for the TrialBox host (SPEC §2, §10.1) — rendered as one nftables table.

Default: every packet from a TrialBox container network to a destination outside those networks is dropped.
Allowed (only when the variable is set):

* mail-gateway      -> SMTP_HOST:SMTP_PORT, IMAP_HOST:IMAP_PORT
* criteria-compiler -> host of CLOUD_LLM_BASE_URL; clinicaltrials.gov:443 when TB_CTGOV_MODE=live (COHORT, D-76)
* orchestrator      -> host of NHI_TWPAS_BASE_URL (SUBMIT)
* EGRESS_EXTRA      -> "service=host:port[,service=host:port]" for site-specific additions (documented in RUNBOOK)

Container addresses come from ``docker inspect`` of the compose project; host names are resolved when the rules are
applied (re-run after an address change or a container restart: ``deploy/network.sh apply``). Traffic between the
box's own containers, replies to inbound connections (published ports) and the Docker embedded DNS are unaffected.

    deploy/network.sh print   # render the ruleset (no root needed)
    deploy/network.sh apply   # nft -f (root)
    deploy/network.sh flush   # remove the table
    deploy/network.sh status  # show the live table with counters

Standard library only: runs on a bare appliance host.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

TABLE = "trialbox_egress"
HERE = Path(__file__).resolve().parent
CTGOV = ("clinicaltrials.gov", 443)


@dataclass(frozen=True)
class Allow:
    service: str
    host: str
    port: int
    why: str


@dataclass
class Box:
    """What the rules are rendered from (taken from docker; injectable for tests)."""

    subnets: list[str] = field(default_factory=list)  # every subnet of the project's networks
    addresses: dict[str, list[str]] = field(default_factory=dict)  # service -> container IPs


def read_env(path: Path | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k in _KEYS})
    return env


_KEYS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "IMAP_HOST",
    "IMAP_PORT",
    "CLOUD_LLM_BASE_URL",
    "NHI_TWPAS_BASE_URL",
    "TB_CTGOV_MODE",
    "EGRESS_EXTRA",
)


def _url(url: str) -> tuple[str, int] | None:
    if not url:
        return None
    u = urlparse(url)
    if not u.hostname:
        return None
    return u.hostname, u.port or (443 if u.scheme == "https" else 80)


def allowlist(env: dict[str, str]) -> list[Allow]:
    out: list[Allow] = []
    if env.get("SMTP_HOST"):
        out.append(Allow("mail-gateway", env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587), "outbound mail"))
    if env.get("IMAP_HOST"):
        out.append(Allow("mail-gateway", env["IMAP_HOST"], int(env.get("IMAP_PORT") or 993), "intake mailbox"))
    cloud = _url(env.get("CLOUD_LLM_BASE_URL", ""))
    if cloud:
        out.append(Allow("criteria-compiler", cloud[0], cloud[1], "cloud LLM (PHI guard enforced)"))
    if (env.get("TB_CTGOV_MODE") or "live").lower() == "live":
        out.append(Allow("criteria-compiler", CTGOV[0], CTGOV[1], "ClinicalTrials.gov public registry"))
    nhi = _url(env.get("NHI_TWPAS_BASE_URL", ""))
    if nhi:
        out.append(Allow("orchestrator", nhi[0], nhi[1], "NHI TWPAS (SUBMIT only)"))
    for item in filter(None, (x.strip() for x in env.get("EGRESS_EXTRA", "").split(","))):
        svc, _, hp = item.partition("=")
        host, _, port = hp.rpartition(":")
        if not (svc and host and port.isdigit()):
            raise SystemExit(f"bad EGRESS_EXTRA entry {item!r} (want service=host:port)")
        out.append(Allow(svc.strip(), host.strip(), int(port), "site addition (EGRESS_EXTRA)"))
    return out


def resolve(host: str) -> list[str]:
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        return sorted({str(ai[4][0]) for ai in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror:
        return []


def docker_box(project: str) -> Box:
    def run(*args: str) -> str:
        return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout

    box = Box()
    nets = [n for n in run("network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}").split()]
    for net in json.loads(run("network", "inspect", *nets)) if nets else []:
        for cfg in (net.get("IPAM") or {}).get("Config") or []:
            if cfg.get("Subnet"):
                box.subnets.append(cfg["Subnet"])
    ids = run("ps", "-q", "--filter", f"label=com.docker.compose.project={project}").split()
    for c in json.loads(run("inspect", *ids)) if ids else []:
        svc = c["Config"]["Labels"].get("com.docker.compose.service", c["Name"].lstrip("/"))
        for n in (c.get("NetworkSettings") or {}).get("Networks", {}).values():
            for key in ("IPAddress", "GlobalIPv6Address"):
                if n.get(key):
                    box.addresses.setdefault(svc, []).append(n[key])
    return box


def _family(addr: str) -> str:
    return "ip6" if ipaddress.ip_network(addr, strict=False).version == 6 else "ip"


def render(box: Box, allows: list[Allow], resolver: object = resolve) -> tuple[str, list[str]]:
    """The nft script (idempotent: the table is recreated) and warnings."""
    warnings: list[str] = []
    res = resolver if callable(resolver) else resolve
    lines = [
        f"table inet {TABLE}",
        f"delete table inet {TABLE}",
        f"table inet {TABLE} {{",
        "  chain forward {",
        "    type filter hook forward priority -10; policy accept;",
        "    ct state established,related accept",
    ]
    v4 = sorted(s for s in box.subnets if _family(s) == "ip")
    v6 = sorted(s for s in box.subnets if _family(s) == "ip6")
    for fam, nets in (("ip", v4), ("ip6", v6)):
        if nets:
            joined = ", ".join(nets)
            lines.append(f'    {fam} saddr {{ {joined} }} {fam} daddr {{ {joined} }} accept comment "intra-box"')
    for a in allows:
        srcs = box.addresses.get(a.service, [])
        dsts = res(a.host)  # type: ignore[operator]
        if not srcs:
            warnings.append(f"{a.service}: no running container; rule for {a.host}:{a.port} skipped")
            continue
        if not dsts:
            warnings.append(f"{a.host}: does not resolve; {a.service} rule skipped")
            continue
        for fam in ("ip", "ip6"):
            s = sorted(x for x in srcs if _family(x) == fam)
            d = sorted(x for x in dsts if _family(x) == fam)
            if s and d:
                lines.append(
                    f"    {fam} saddr {{ {', '.join(s)} }} {fam} daddr {{ {', '.join(d)} }} tcp dport {a.port} "
                    f'accept comment "{a.service} -> {a.host}:{a.port} ({a.why})"'
                )
    for fam, nets in (("ip", v4), ("ip6", v6)):
        if nets:
            lines.append(f'    {fam} saddr {{ {", ".join(nets)} }} counter drop comment "trialbox default deny"')
    lines += ["  }", "}"]
    if not box.subnets:
        warnings.append("no TrialBox networks found (is the stack up?); nothing is filtered")
    return "\n".join(lines) + "\n", warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["print", "apply", "flush", "status"])
    ap.add_argument("--env", type=Path, default=HERE / ".env")
    ap.add_argument("--project", default=os.environ.get("COMPOSE_PROJECT_NAME", "trialbox"))
    args = ap.parse_args(argv)
    if args.action == "flush":
        subprocess.run(["nft", "delete", "table", "inet", TABLE], check=False)
        print(f"removed table inet {TABLE} (if present)")
        return 0
    if args.action == "status":
        return subprocess.run(["nft", "list", "table", "inet", TABLE], check=False).returncode
    script, warnings = render(docker_box(args.project), allowlist(read_env(args.env)))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.action == "print":
        sys.stdout.write(script)
        return 0
    subprocess.run(["nft", "-f", "-"], input=script, text=True, check=True)
    print(f"applied table inet {TABLE}: {script.count(' accept comment') - 1} allow rules, default deny")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
