#!/bin/sh
# Stand-in for the installed box's deploy/network.sh in the box-run rehearsal (the session's 55-session-egress,
# D-1131): `network.sh apply|status --env F --state F`. The paid run runs the box's own script (deploy/egress.py
# rendered into nftables, root). Here the REAL renderer (deploy/egress.py render) makes the table for two stand-in
# networks of the box, so the VM script reads back the product's own format; nothing is loaded into a kernel.
# Knob egress-open: the table also lets the gateway out to a model host (as a DEV box's table opens openrouter).
set -eu
echo "network.sh $1" >> "$BR_S/calls.log"
exec python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path
s, here = Path(os.environ["BR_S"]), Path(os.environ["BR_HERE"])
sys.path.insert(0, str(here.parents[2] / "deploy"))
import egress  # noqa: E402  (the product's own renderer)
action, args = sys.argv[1], sys.argv[2:]
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
    sys.stdout.write("\n".join(x for x in live.read_text().splitlines() if not x.startswith("delete")) + "\n")
else:
    sys.exit(f"network.sh stand-in: {action} is not rehearsed")
PY
