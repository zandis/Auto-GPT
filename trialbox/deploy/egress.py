#!/usr/bin/env python3
"""Container egress allowlist for the TrialBox host (SPEC §2, §10.1) — rendered as one nftables table.

Default: every packet from a TrialBox container network to a destination outside those networks is dropped.
Allowed (only when the variable is set):

* mail-gateway      -> SMTP_HOST:SMTP_PORT, IMAP_HOST:IMAP_PORT
* gateway           -> every non-perimeter model endpoint of ``models/routing.yaml`` (zone external / dev_public)
                       whose URL is set and that is open in ``TB_ENV`` (spec v4 NFR-B9, S1-06: only tb-gateway
                       reaches a model host). CLOUD_LLM_BASE_URL opens nothing: the gateway never calls it (T-604,
                       review LLM-037 d)
* criteria-compiler -> clinicaltrials.gov:443 when TB_CTGOV_MODE=live (COHORT, D-76; offline, the default since D-140,
                       reads the reference data pack and needs no outbound access)
* orchestrator      -> host of NHI_TWPAS_BASE_URL (SUBMIT)
* EGRESS_EXTRA      -> "service=host:port[,service=host:port]" for site-specific additions (documented in RUNBOOK);
                       an entry that would give any service other than the gateway a model host is refused, and so is
                       an entry for the gateway that is not one of the routing table's open model endpoints above
                       (T-604, review LLM-036: one extra line must not send the box's prompts to another server)

Container addresses come from ``docker inspect`` of the compose project; host names are resolved when the rules are
applied (re-run after an address change or a container restart: ``deploy/network.sh apply``; the unit
``trialbox-egress-refresh.timer`` does it every two minutes when the table would change, and ``network.sh watch``,
run by ``trialbox-egress-watch.service``, does it at once when a container of the stack starts, so a restarted
container's new address gets its rule and its old address loses it without the two-minute gap; T-604, LLM-037 b).
Traffic between the box's own containers, replies to inbound connections (published ports) and the Docker embedded
DNS are unaffected.
Inbound, only a published port opens a connection into a box network; a direct route to a container address is dropped.
A box container opens no connection to the host itself (the input hook), except to an allowed destination there.

    deploy/network.sh print   # render the ruleset (no root needed)
    deploy/network.sh apply   # nft -f (root)
    deploy/network.sh flush   # remove the table
    deploy/network.sh status  # show the live table with counters
    deploy/network.sh save    # write the state file only (apply writes it too)
    deploy/network.sh restore # load the closed table from the state file (root; at boot, before Docker)
    deploy/network.sh watch   # apply now and again whenever a container of the stack starts (root)

Kept across a reboot (T-108b, D-377; CR-043): ``apply`` writes the box's subnets and the applied script to the state
file (``--state``, default ``TB_EGRESS_STATE`` or ``/var/lib/trialbox/egress-state.json``). At boot the unit
``trialbox-egress.service`` runs ``restore`` before ``docker.service``: it loads the closed table for the saved
subnets (intra-box traffic, published ports, the default deny; no allow rule, since container addresses may change),
so no container that Docker restarts by itself has a way out. ``trialbox.service`` then starts the stack and runs
``apply``, which opens the allowed pairs for the new addresses. Docker keeps a named network's subnet across a
restart; a subnet that changed is closed again at the next ``apply``.

Standard library only, except that reading ``models/routing.yaml`` needs PyYAML (``python3-yaml``); without it the
model-endpoint rules are skipped with a warning (fail closed: nothing is opened).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

TABLE = "trialbox_egress"
STATE = Path(os.environ.get("TB_EGRESS_STATE") or "/var/lib/trialbox/egress-state.json")
HERE = Path(__file__).resolve().parent
ROUTING = HERE.parent / "models" / "routing.yaml"
CTGOV = ("clinicaltrials.gov", 443)
GATEWAY = "gateway"  # compose service name of tb-gateway
MODEL_ZONES = ("external", "dev_public")


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
    env.update({k: v for k, v in os.environ.items() if k in _KEYS or k.startswith("TB_EP_")})
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
    "TB_ENV",
)
# model endpoint URL and key variables named in routing.yaml are read too (see model_endpoints)


def _url(url: str) -> tuple[str, int] | None:
    if not url:
        return None
    u = urlparse(url)
    if not u.hostname:
        return None
    return u.hostname, u.port or (443 if u.scheme == "https" else 80)


def _routing_endpoints(
    env: dict[str, str], routing: Path | None, *, opened_only: bool = False
) -> list[tuple[str, str, int, str]]:
    """``(endpoint, host, port, zone)`` for every endpoint of the routing policy whose URL is set (its ``url_env``
    variable, else its ``default_url``)."""
    if routing is None or not routing.exists():
        return []
    try:
        import yaml
    except ImportError:
        print("warning: PyYAML missing; no model-endpoint egress rules rendered", file=sys.stderr)
        return []
    doc = yaml.safe_load(routing.read_text(encoding="utf-8")) or {}
    out: list[tuple[str, str, int, str]] = []
    site_env = env.get("TB_ENV") or "PRODUCTION"
    for name, ep in sorted((doc.get("endpoints") or {}).items()):
        if opened_only and ep.get("environments") and site_env not in ep["environments"]:
            continue
        if opened_only and "g5_record" in ep and not ep["g5_record"]:
            continue
        hp = _url(env.get(str(ep.get("url_env") or ""), "") or str(ep.get("default_url") or ""))
        if hp:
            out.append((str(name), hp[0], hp[1], str(ep.get("zone"))))
    return out


def model_endpoints(env: dict[str, str], routing: Path | None = ROUTING) -> list[tuple[str, str, int, str]]:
    """Non-perimeter endpoints (zone external / dev_public): the only model hosts that need an egress rule.
    Perimeter endpoints are reached inside the box networks. An endpoint restricted to other environments than
    ``TB_ENV`` (default PRODUCTION), or an external one without a G5 record, gets no rule."""
    return [e for e in _routing_endpoints(env, routing, opened_only=True) if e[3] in MODEL_ZONES]


def model_hosts(env: dict[str, str], routing: Path | None = ROUTING) -> set[str]:
    """Every host name that serves a model: routing.yaml endpoints of every zone, and CLOUD_LLM_BASE_URL."""
    hosts = {h for _, h, _, _ in _routing_endpoints(env, routing)}
    cloud = _url(env.get("CLOUD_LLM_BASE_URL", ""))
    if cloud:
        hosts.add(cloud[0])
    return hosts


def allowlist(env: dict[str, str], routing: Path | None = ROUTING) -> list[Allow]:
    out: list[Allow] = []
    if env.get("SMTP_HOST"):
        out.append(Allow("mail-gateway", env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587), "outbound mail"))
    if env.get("IMAP_HOST"):
        out.append(Allow("mail-gateway", env["IMAP_HOST"], int(env.get("IMAP_PORT") or 993), "intake mailbox"))
    opened = model_endpoints(env, routing)
    for name, ep_host, ep_port, zone in opened:
        out.append(Allow(GATEWAY, ep_host, ep_port, f"model endpoint {name} ({zone})"))
    if (env.get("TB_CTGOV_MODE") or "offline").lower() == "live":  # D-140: offline by default
        out.append(Allow("criteria-compiler", CTGOV[0], CTGOV[1], "ClinicalTrials.gov public registry"))
    nhi = _url(env.get("NHI_TWPAS_BASE_URL", ""))
    if nhi:
        out.append(Allow("orchestrator", nhi[0], nhi[1], "NHI TWPAS (SUBMIT only)"))
    for item in filter(None, (x.strip() for x in env.get("EGRESS_EXTRA", "").split(","))):
        svc, _, hp = item.partition("=")
        host, _, port = hp.rpartition(":")
        if not (svc and host and port.isdigit()):
            raise SystemExit(f"bad EGRESS_EXTRA entry {item!r} (want service=host:port)")
        if svc.strip() != GATEWAY and host.strip() in model_hosts(env, routing):
            raise SystemExit(f"EGRESS_EXTRA entry {item!r} gives {svc.strip()} a model host; only {GATEWAY} may")
        if svc.strip() == GATEWAY and (host.strip(), int(port)) not in {(h, p) for _, h, p, _ in opened}:
            raise SystemExit(
                f"EGRESS_EXTRA entry {item!r} is not an open model endpoint of the routing table; the gateway "
                "reaches only those (set the endpoint's URL variable instead)"
            )
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
        dsts = res(a.host)
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
            # inbound: only a published port (Docker's DNAT) may open a connection into a box network from outside;
            # a neighbour that routes to a container address directly (the console's non-internal console-net,
            # D-176, on a Docker before 28) is dropped
            joined = ", ".join(nets)
            lines.append(f'    {fam} daddr {{ {joined} }} ct status dnat accept comment "published ports"')
            lines.append(f'    {fam} daddr {{ {joined} }} counter drop comment "trialbox no direct access"')
            lines.append(f'    {fam} saddr {{ {joined} }} counter drop comment "trialbox default deny"')
    lines.append("  }")
    # the host itself (D-176 review): console-net is not internal, so a box container has a route to the host's own
    # addresses (sshd, the Docker API on TCP, a database ...). New connections from a box network to the host are
    # dropped, except an allowed destination that is on the host (an SMTP relay on localhost's address, say).
    lines += [
        "  chain input {",
        "    type filter hook input priority -10; policy accept;",
        "    ct state established,related accept",
        *[ln for ln in lines if "tcp dport" in ln and "accept comment" in ln],
    ]
    for fam, nets in (("ip", v4), ("ip6", v6)):
        if nets:
            lines.append(
                f'    {fam} saddr {{ {", ".join(nets)} }} counter drop comment "trialbox no access to the host"'
            )
    lines += ["  }", "}"]
    if not box.subnets:
        warnings.append("no TrialBox networks found (is the stack up?); nothing is filtered")
    return "\n".join(lines) + "\n", warnings


def render_networkpolicy(
    allows: list[Allow], resolver: object = resolve, *, part_of: str = "trialbox"
) -> tuple[list[dict[str, object]], list[str]]:
    """The same allowlist as ``render`` (one source, D-211), as Kubernetes NetworkPolicy objects for a hospital
    platform (WS-14.8): one ``trialbox-egress-<service>`` policy per service with an allowed host, selecting the pods
    labelled ``app.kubernetes.io/component=<service>``, one rule per host with its addresses as /32 or /128
    ``ipBlock``s and the TCP port. A NetworkPolicy cannot name a host, so each rule's host is kept in the policy's
    ``trialbox.io/egress-hosts`` annotation (``host:port`` list, the same order as the rules); hosts are resolved
    when this is rendered, as ``render`` resolves them when the nftables table is applied. A host that does not
    resolve gets no rule and a warning (fail closed). The default deny, DNS and the traffic inside the namespace are
    the static policies of ``deploy/platform/base/networkpolicy.yaml``; this adds only the allowed destinations."""
    res = resolver if callable(resolver) else resolve
    warnings: list[str] = []
    per_service: dict[str, list[tuple[Allow, list[str]]]] = {}
    for a in allows:
        dsts = sorted(res(a.host))
        if not dsts:
            warnings.append(f"{a.host}: does not resolve; {a.service} rule skipped")
            continue
        per_service.setdefault(a.service, []).append((a, dsts))
    out: list[dict[str, object]] = []
    for svc in sorted(per_service):
        rules: list[dict[str, object]] = []
        for a, dsts in per_service[svc]:
            blocks = [{"ipBlock": {"cidr": f"{d}/{128 if _family(d) == 'ip6' else 32}"}} for d in dsts]
            rules.append({"to": blocks, "ports": [{"protocol": "TCP", "port": a.port}]})
        out.append(
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": f"trialbox-egress-{svc}",
                    "labels": {"app.kubernetes.io/part-of": part_of, "trialbox.io/policy": "egress-allowlist"},
                    "annotations": {
                        "trialbox.io/egress-hosts": ",".join(f"{a.host}:{a.port}" for a, _ in per_service[svc]),
                        "trialbox.io/egress-why": "; ".join(a.why for a, _ in per_service[svc]),
                    },
                },
                "spec": {
                    "podSelector": {"matchLabels": {"app.kubernetes.io/component": svc}},
                    "policyTypes": ["Egress"],
                    "egress": rules,
                },
            }
        )
    return out, warnings


def save_state(path: Path, box: Box, script: str) -> None:
    """Write what ``restore`` needs (the subnets) and, for a person, the script that was applied. Atomic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"table": TABLE, "version": 1, "subnets": sorted(box.subnets), "script": script}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path) -> dict[str, object]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("table") != TABLE or not isinstance(doc.get("subnets"), list):
        raise ValueError(f"{path}: not a {TABLE} state file")
    for s in doc["subnets"]:
        ipaddress.ip_network(str(s), strict=False)  # a bad subnet is refused, never passed to nft
    return doc


def restore_script(state: dict[str, object]) -> str:
    """The closed table for the saved subnets: intra-box, published ports and the default deny, no allow rule (the
    saved container addresses may belong to another container after a reboot)."""
    subnets = [str(s) for s in state["subnets"]] if isinstance(state["subnets"], list) else []
    script, _ = render(Box(subnets=subnets), [])
    return script


def watch(apply: Callable[[], object], events: Iterable[str]) -> int:
    """Apply once, then again for every event line (a container of the stack started). An apply that fails is
    reported and the watch goes on; the next event or the refresh timer tries again. Returns 1 when the event stream
    ends (systemd restarts the watch)."""

    def once() -> None:
        try:
            apply()
        except (SystemExit, subprocess.CalledProcessError, OSError, ValueError) as exc:
            print(f"watch: apply failed: {exc}", file=sys.stderr)

    once()
    for line in events:
        if line.strip():
            once()
    return 1


def docker_events(project: str) -> Iterable[str]:
    """One line per container start of the compose project (a restart included), as Docker reports it."""
    cmd = ["docker", "events", "--format", "{{.ID}}", "--filter", "type=container", "--filter", "event=start"]
    cmd += ["--filter", f"label=com.docker.compose.project={project}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    yield from proc.stdout


def _table_live() -> bool:
    return subprocess.run(["nft", "list", "table", "inet", TABLE], capture_output=True, check=False).returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["print", "apply", "flush", "status", "save", "restore", "watch"])
    ap.add_argument("--state", type=Path, default=STATE, help="the state file kept across a reboot")
    ap.add_argument("--no-save", action="store_true", help="apply: do not write the state file")
    ap.add_argument("--if-changed", action="store_true", help="apply: skip when the live table is the saved one")
    ap.add_argument("--dry-run", action="store_true", help="restore: print the script, load nothing")
    ap.add_argument("--env", type=Path, default=HERE / ".env")
    ap.add_argument("--project", default=os.environ.get("COMPOSE_PROJECT_NAME", "trialbox"))
    args = ap.parse_args(argv)
    if args.action == "flush":
        subprocess.run(["nft", "delete", "table", "inet", TABLE], check=False)
        print(f"removed table inet {TABLE} (if present)")
        return 0
    if args.action == "status":
        return subprocess.run(["nft", "list", "table", "inet", TABLE], check=False).returncode
    if args.action == "restore":
        try:
            state = load_state(args.state)
        except (OSError, ValueError) as exc:
            print(f"restore: no usable state file ({exc}); run deploy/network.sh apply once", file=sys.stderr)
            return 1
        script = restore_script(state)
        if args.dry_run:
            sys.stdout.write(script)
            return 0
        subprocess.run(["nft", "-f", "-"], input=script, text=True, check=True)
        n = script.count("intra-box")
        print(f"restored table inet {TABLE}, closed ({n} address families; no allow rule until apply)")
        return 0
    if args.action == "watch":
        again = ["apply", "--if-changed", "--env", str(args.env), "--project", args.project, "--state", str(args.state)]
        return watch(lambda: main(again), docker_events(args.project))
    allows = allowlist(read_env(args.env))  # a refused entry stops here, before docker is asked anything
    box = docker_box(args.project)
    script, warnings = render(box, allows)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.action == "print":
        sys.stdout.write(script)
        return 0
    if args.action == "save":
        if not box.subnets:
            print("save: no TrialBox networks found; nothing saved (is the stack up?)", file=sys.stderr)
            return 1
        save_state(args.state, box, script)
        print(f"saved {args.state}")
        return 0
    if not box.subnets and args.action == "apply":
        # the stack is down (a refresh between stop and start, say): never replace a closed table with an empty one
        try:
            script = restore_script(load_state(args.state))
            print("warning: no TrialBox networks found; the closed table of the state file is loaded", file=sys.stderr)
        except (OSError, ValueError):
            pass
    if args.if_changed and _table_live():
        try:
            if load_state(args.state).get("script") == script:
                return 0
        except (OSError, ValueError):
            pass
    subprocess.run(["nft", "-f", "-"], input=script, text=True, check=True)
    print(f"applied table inet {TABLE}: {script.count(' accept comment') - 1} allow rules, default deny")
    if not args.no_save:
        if box.subnets:
            save_state(args.state, box, script)
        else:
            print("warning: no TrialBox networks found; the state file is kept as it was", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
