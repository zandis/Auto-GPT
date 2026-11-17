#!/bin/sh
# Stand-in for the installed box's deploy/network.sh in the box-run rehearsal (the session's 55-session-egress,
# D-1131): `network.sh apply|status --env F --state F`. The paid run runs the box's own script (deploy/egress.py
# rendered into nftables, root). Here the REAL renderer (deploy/egress.py render) makes the table for the stand-in
# networks of the box, and `status` prints it as `nft list table` does (nftables 1.0: tabs, adjacent networks merged,
# a one-element set without braces, counters), so the VM script reads back the kernel's own format
# (tests/unit/test_h13_session_egress.py holds this form against a listing nft itself printed). Nothing is loaded.
# Knob egress-open: the table also lets the gateway out to a model host (as a DEV box's table opens openrouter).
set -eu
echo "network.sh $1" >> "$BR_S/calls.log"
exec python3 - "$@" <<'PY'
import ipaddress, json, os, re, sys
from pathlib import Path
s, here = Path(os.environ["BR_S"]), Path(os.environ["BR_HERE"])
sys.path.insert(0, str(here.parents[2] / "deploy"))
import egress  # noqa: E402  (the product's own renderer)


def nft_set(body):
    """One set of the script as nft lists it."""
    items = [x.strip() for x in body.split(",") if x.strip()]
    nets = [ipaddress.ip_network(x, strict=False) for x in items]
    if len(items) == 1:
        n = nets[0]
        return str(n.network_address) if n.prefixlen == n.max_prefixlen else str(n)
    out = []
    for fam in (4, 6):
        spans = []
        for n in ipaddress.collapse_addresses(x for x in nets if x.version == fam):
            lo, hi = int(n.network_address), int(n.broadcast_address)
            if spans and spans[-1][1] + 1 == lo:
                spans[-1][1] = hi
            else:
                spans.append([lo, hi])
        for lo, hi in spans:
            a, b = ipaddress.ip_address(lo if fam == 4 else lo), ipaddress.ip_address(hi)
            if fam == 6:
                a, b = ipaddress.IPv6Address(lo), ipaddress.IPv6Address(hi)
            whole = list(ipaddress.summarize_address_range(a, b))
            out.append(str(whole[0]) if len(whole) == 1 else f"{a}-{b}")
    return "{ " + ", ".join(out) + " }"


def nft_list(script):
    lines, depth = [], 0
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("delete table") or line == f"table inet {egress.TABLE}":
            continue
        line = re.sub(r"\{ ([^{}]*) \}", lambda m: nft_set(m.group(1)), line)
        line = line.replace("priority -10;", "priority filter - 10;").replace("counter drop", "counter packets 0 bytes 0 drop")
        if line == "}":
            depth -= 1
            lines.append("\t" * depth + "}")
            if depth == 1:
                lines.append("")
            continue
        lines.append("\t" * depth + line)
        if line.endswith("{"):
            depth += 1
    if lines and lines[-2] == "":
        del lines[-2]
    return "\n".join(lines) + "\n"


action, args = sys.argv[1], sys.argv[2:]
if action == "nft-list":  # the unit test's way in: a rendered script's file, nft's listing of it out
    sys.stdout.write(nft_list(Path(args[0]).read_text()))
    sys.exit(0)
state = Path(args[args.index("--state") + 1])
box = egress.Box(subnets=["172.18.0.0/16", "172.19.0.0/16"], addresses={"gateway": ["172.18.0.5"]})
allows = []
if (s / "knobs" / "egress-open").exists():
    allows = [egress.Allow("gateway", "198.51.100.7", 443, "model endpoint openrouter (dev_public)")]
script, _ = egress.render(box, allows, resolver=lambda h: [h])
live = s / "box" / "egress-live.nft"
if action == "apply":
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(script)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"table": egress.TABLE, "version": 1, "subnets": sorted(box.subnets), "script": script}))
    print(f"applied table inet {egress.TABLE}")
elif action == "status":
    if not live.exists():
        sys.exit(1)
    sys.stdout.write(nft_list(live.read_text()))
else:
    sys.exit(f"network.sh stand-in: {action} is not rehearsed")
PY
