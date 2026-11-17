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


# ---------------------------------------------------------------- the security review's finding 3: exact shapes only
# What `nft list table inet trialbox_egress` printed (nftables 1.0.9, in a network namespace, 2026-11-17) for the
# product's own script (deploy/egress.py render) of three networks: adjacent networks merged into one /15, a set of
# one element without braces, counters. These are the shapes the paid run's 55-session-egress reads back.
REAL_NETS = ["172.18.0.0/16", "172.19.0.0/16", "fd00:1::/64"]
REAL = """table inet trialbox_egress {
	chain forward {
		type filter hook forward priority filter - 10; policy accept;
		ct state established,related accept
		ip saddr { 172.18.0.0/15 } ip daddr { 172.18.0.0/15 } accept comment "intra-box"
		ip6 saddr fd00:1::/64 ip6 daddr fd00:1::/64 accept comment "intra-box"
		ip daddr { 172.18.0.0/15 } ct status dnat accept comment "published ports"
		ip daddr { 172.18.0.0/15 } counter packets 0 bytes 0 drop comment "trialbox no direct access"
		ip saddr { 172.18.0.0/15 } counter packets 0 bytes 0 drop comment "trialbox default deny"
		ip6 daddr fd00:1::/64 ct status dnat accept comment "published ports"
		ip6 daddr fd00:1::/64 counter packets 0 bytes 0 drop comment "trialbox no direct access"
		ip6 saddr fd00:1::/64 counter packets 0 bytes 0 drop comment "trialbox default deny"
	}

	chain input {
		type filter hook input priority filter - 10; policy accept;
		ct state established,related accept
		ip saddr { 172.18.0.0/15 } counter packets 0 bytes 0 drop comment "trialbox no access to the host"
		ip6 saddr fd00:1::/64 counter packets 0 bytes 0 drop comment "trialbox no access to the host"
	}
}
"""
# the same for four networks (three adjacent ones listed as a range a-b) with one allow out (a DEV box's)
REAL_OPEN_NETS = ["172.18.0.0/16", "172.19.0.0/16", "172.20.0.0/16", "192.168.5.0/24"]
REAL_OPEN = """table inet trialbox_egress {
	chain forward {
		type filter hook forward priority filter - 10; policy accept;
		ct state established,related accept
		ip saddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } ip daddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } accept comment "intra-box"
		ip saddr 172.18.0.5 ip daddr 198.51.100.7 tcp dport 443 accept comment "gateway -> 198.51.100.7:443 (model endpoint openrouter (dev_public))"
		ip daddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } ct status dnat accept comment "published ports"
		ip daddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } counter packets 0 bytes 0 drop comment "trialbox no direct access"
		ip saddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } counter packets 0 bytes 0 drop comment "trialbox default deny"
	}

	chain input {
		type filter hook input priority filter - 10; policy accept;
		ct state established,related accept
		ip saddr 172.18.0.5 ip daddr 198.51.100.7 tcp dport 443 accept comment "gateway -> 198.51.100.7:443 (model endpoint openrouter (dev_public))"
		ip saddr { 172.18.0.0-172.20.255.255, 192.168.5.0/24 } counter packets 0 bytes 0 drop comment "trialbox no access to the host"
	}
}
"""


def test_the_kernels_own_listing_of_the_closed_table_is_read_with_its_merged_networks() -> None:
    res = vm.session_egress(REAL, REAL_NETS)
    assert not res["text_can_leave"] and res["problems"] == [], res["problems"]
    assert res["under_default_deny"] == sorted(REAL_NETS)
    opened = vm.session_egress(REAL_OPEN, REAL_OPEN_NETS)  # ranges a-b read; the one allow out refused
    assert opened["text_can_leave"] and len(opened["problems"]) == 1 and "198.51.100.7" in opened["problems"][0]
    assert opened["under_default_deny"] == sorted(REAL_OPEN_NETS)


def _with(line: str, form: str) -> str:
    """``line`` put after the first rule of the forward chain, in the kernel's listing or in the product's script."""
    if form == "nft-list":
        return REAL.replace("\t\tct state established,related accept\n",
                            f"\t\tct state established,related accept\n\t\t{line}\n", 1)  # fmt: skip
    script, _ = egress.render(egress.Box(subnets=REAL_NETS, addresses={}), [], resolver=lambda h: [h])
    out: str = script.replace("    ct state established,related accept\n",
                              f"    ct state established,related accept\n    {line}\n", 1)  # fmt: skip
    return out


@pytest.mark.parametrize(
    "line",
    ["ct state new accept",
     "ct state { established, related, new } accept",
     'ip saddr { 172.18.0.0/15 } ip daddr 0.0.0.0/0 accept comment "intra-box"',
     'ip saddr 0.0.0.0/0 ip daddr { 172.18.0.0/15 } accept comment "intra-box"',
     'ip daddr { 172.18.0.0/15 } tcp dport 443 accept comment "published ports"',
     'ip daddr 0.0.0.0/0 ct status dnat accept comment "published ports"',
     "jump out",
     "goto out",
     "ip saddr { 172.18.0.0/15 } accept",
     'ip saddr != { 172.18.0.0/15 } counter packets 0 bytes 0 drop comment "trialbox default deny"'],
)  # fmt: skip
@pytest.mark.parametrize("form", ["nft-list", "script"])
def test_any_rule_shape_the_product_does_not_write_is_refused(line: str, form: str) -> None:
    """Each line, inserted into the kernel's own listing of the product's closed table, is a way out (or a deny that
    is not one): the read-back says the text could leave."""
    assert not vm.session_egress(_with("", form).replace("\n\t\t\n", "\n").replace("\n    \n", "\n"), REAL_NETS)[
        "text_can_leave"
    ]  # the closed table alone passes, in either form
    res = vm.session_egress(_with(line, form), REAL_NETS)
    assert res["text_can_leave"], (line, res["problems"])


def test_a_deny_that_is_not_last_or_a_chain_the_product_does_not_make_is_refused() -> None:
    moved = REAL.replace('drop comment "trialbox no access to the host"', 'drop comment "x"')  # input chain: harmless
    assert not vm.session_egress(moved, REAL_NETS)["text_can_leave"]
    last = REAL.replace('\t\tip6 saddr fd00:1::/64 counter packets 0 bytes 0 drop comment "trialbox default deny"\n\t}',
                        '\t\tip6 saddr fd00:1::/64 counter packets 0 bytes 0 drop comment "trialbox default deny"\n'
                        '\t\tip6 daddr fd00:1::/64 ct status dnat accept comment "published ports"\n\t}')  # fmt: skip
    assert last != REAL and vm.session_egress(last, REAL_NETS)["text_can_leave"]
    chain = REAL.replace("\tchain input {", "\tchain postrouting {")
    assert vm.session_egress(chain, REAL_NETS)["text_can_leave"]


def test_the_rehearsals_stand_in_prints_what_nft_prints(tmp_path: Path) -> None:
    """The stand-in's `status` is the kernel's listing of the same script, byte for byte (so the rehearsal reads back
    the paid run's format)."""
    import os
    import subprocess

    for nets, allows, want in ((REAL_NETS, [], REAL), (REAL_OPEN_NETS,
            [egress.Allow("gateway", "198.51.100.7", 443, "model endpoint openrouter (dev_public)")], REAL_OPEN)):  # fmt: skip
        script, _ = egress.render(egress.Box(subnets=nets, addresses={"gateway": ["172.18.0.5"]}), allows,
                                  resolver=lambda h: [h])  # fmt: skip
        (tmp_path / "s.nft").write_text(script)
        env = {**os.environ, "BR_S": str(tmp_path), "BR_HERE": str(ROOT / "tests" / "rehearsal" / "box-run")}
        out = subprocess.run(["sh", str(ROOT / "tests/rehearsal/box-run/standins/network.sh"), "nft-list",
                              str(tmp_path / "s.nft")], env=env, capture_output=True, text=True, check=True).stdout  # fmt: skip
        assert out == want
