"""SESSION-EGRESS (D-1131): the session applies the box's own egress rules by the product's own script and reads them
back before any link is given (deploy/gcp/box-install-run.sh 55-session-egress, deploy/gcp/box_vm.py session-egress).

The direct bring-up route never loaded the egress table (only deploy/install.sh runs `deploy/network.sh apply`). The
read-back is held here against the product's own renderer (deploy/egress.py ``render``), so the check reads the format
the box writes. Synthetic networks and documentation-style addresses only."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = ROOT / "deploy" / "gcp" / "box-install-run.sh"

pytestmark = pytest.mark.nodb


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


egress = _load("h13_egress", ROOT / "deploy" / "egress.py")
vm = _load("h13_box_vm", ROOT / "deploy" / "gcp" / "box_vm.py")
NETS = ["172.18.0.0/16", "172.19.0.0/16"]
BOX = egress.Box(
    subnets=NETS,
    addresses={"gateway": ["172.18.0.5"], "mail-gateway": ["172.19.0.4"], "criteria-compiler": ["172.18.0.6"]},
)


def _table(allows: list[Any]) -> str:
    script, _ = egress.render(BOX, allows, resolver=lambda h: [h])
    return "\n".join(x for x in script.splitlines() if not x.startswith("delete"))


def test_the_products_closed_table_keeps_the_text_in_the_box() -> None:
    res = vm.session_egress(_table([]), NETS)
    assert res["live"] and not res["text_can_leave"] and res["problems"] == []
    assert res["under_default_deny"] == NETS
    assert any(r["does"] == "drops" for r in res["rules"])


@pytest.mark.parametrize(
    "allow",
    [("gateway", "198.51.100.7", 443, "model endpoint openrouter (dev_public)"),
     ("mail-gateway", "198.51.100.25", 587, "outbound mail"),
     ("criteria-compiler", "198.51.100.80", 443, "ClinicalTrials.gov public registry")],
)  # fmt: skip
def test_any_way_out_of_the_box_is_text_leaving_it(allow: tuple[str, str, int, str]) -> None:
    """Must never: the pasted text leaving the box. A DEV box's table opens a model host to the gateway; a site with a
    mail relay or the live registry opens those: each is a way out, and the session stops at 55 with no link."""
    res = vm.session_egress(_table([egress.Allow(*allow)]), NETS)
    assert res["text_can_leave"] and len(res["problems"]) == 1 and allow[1] in res["problems"][0]


def test_a_table_not_loaded_or_a_network_outside_it_is_refused() -> None:
    assert vm.session_egress("", NETS)["text_can_leave"]
    res = vm.session_egress(_table([]), [*NETS, "172.20.0.0/16"])
    assert res["text_can_leave"] and "172.20.0.0/16" in res["problems"][0]
    assert vm.session_egress(_table([]), [])["text_can_leave"]  # the stack down: nothing filtered


def test_the_vm_calls_the_products_script_and_never_copies_it() -> None:
    text = VM_SCRIPT.read_text()
    assert 'd_egress() { (cd "$BOXROOT" && deploy/network.sh "$1" --env deploy/.env --state "$EGRESS_STATE"); }' in text
    step = text[text.index("step_session_egress() {") : text.index("# the accounts, by the console's own code")]
    assert step.index("d_egress apply") < step.index("d_egress status") < step.index("vm session-egress")
    assert "nft " not in step and "egress.py" not in step  # the product's script only
    # read back before any account or link is made
    assert text.index("run_step 55-session-egress") < text.index("run_step 56-session-accounts")


def test_the_heartbeat_counts_the_owners_requests_only() -> None:
    lines = [
        'caddy  | {"level":"info","logger":"http.log.access","request":{"client_ip":"1.2.3.4","uri":"/"}}',
        '{"request":{"client_ip":"127.0.0.1","uri":"/healthz"}}',
        '{"request":{"remote_ip":"172.18.0.9","uri":"/"}}',
        '{"request":{"remote_ip":"5.6.7.8","uri":"/studies"}}',
        "not json at all",
    ]
    assert vm.session_requests(lines) == 2


def test_the_record_always_says_it_is_no_evidence(tmp_path: Path) -> None:
    f = tmp_path / "records" / "session.json"
    vm.session_record(f, ["environment=DEV", "evidence=a measurement"])
    rec = vm.session_record(f, ["closed_by=the session's stop"])
    assert rec["evidence"] == "nothing from this session is evidence" and rec["environment"] == "DEV"
    assert json.loads(f.read_text())["closed_by"] == "the session's stop"
