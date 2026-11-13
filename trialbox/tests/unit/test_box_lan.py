"""BOX-LAN (D-629): the network the box plan writes as ``CLINIC_RANGES`` (who may reach the console on 443) is the
network of the interface the default route uses. It was the first global IPv4 address listed: under WSL2 mirrored
networking a loopback /32, with a VPN up the VPN's network, and never IPv6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.box import plan as bp

pytestmark = pytest.mark.nodb


def _if(
    name: str, *addrs: tuple[str, str, int], flags: tuple[str, ...] = ("BROADCAST", "UP"), kind: str = "ether"
) -> Any:
    info = [
        {"family": fam, "local": ip, "prefixlen": n, "scope": "link" if ip.startswith("fe80") else "global"}
        for fam, ip, n in addrs
    ]
    return {"ifname": name, "flags": list(flags), "link_type": kind, "addr_info": info}


def _routes(*rows: tuple[str, int]) -> str:
    return json.dumps([{"dst": "default", "gateway": "x", "dev": dev, "metric": m} for dev, m in rows])


ETH = _if("eth0", ("inet", "192.0.2.40", 24), ("inet6", "2001:db8:5::40", 64), ("inet6", "fe80::1", 64))
WSL_LOOP = _if("loopback0", ("inet", "10.255.255.254", 32))
VPN = _if("tun0", ("inet", "10.8.0.6", 24), flags=("POINTOPOINT", "UP"), kind="none")
WG = _if("wg0", ("inet", "100.64.0.9", 24), kind="none")
DOCKER = _if("docker0", ("inet", "172.17.0.1", 16))
SECOND = _if("eth1", ("inet", "198.51.100.7", 24))


def _lan(links: list[Any], r4: str = "[]", r6: str = "[]") -> str:
    return bp.clinic_ranges(json.dumps(links), r4, r6)


def test_the_network_of_the_default_routes_interface_both_families() -> None:
    assert _lan([SECOND, ETH], _routes(("eth0", 100))) == "192.0.2.0/24 2001:db8:5::/64"


def test_a_loopback_slash_32_listed_first_is_not_the_clinic() -> None:
    """WSL2 mirrored networking: before, the range was 10.255.255.254/32 and 443 answered nobody."""
    assert _lan([WSL_LOOP, ETH], _routes(("eth0", 25))) == "192.0.2.0/24 2001:db8:5::/64"
    assert _lan([WSL_LOOP, ETH]) == "192.0.2.0/24 2001:db8:5::/64"  # no route to go by: one candidate is left
    assert _lan([WSL_LOOP]) == ""


def test_a_vpn_listed_first_or_holding_the_default_route_is_not_the_clinic() -> None:
    assert _lan([VPN, ETH], _routes(("eth0", 100))).startswith("192.0.2.0/24")
    # a full-tunnel VPN owns the best default route: the next route's interface is the clinic's
    assert _lan([VPN, ETH], _routes(("tun0", 1), ("eth0", 100))).startswith("192.0.2.0/24")
    assert _lan([WG, ETH], _routes(("wg0", 1))).startswith("192.0.2.0/24")  # only the tunnel has a route: one left
    assert _lan([VPN]) == "" and _lan([VPN], _routes(("tun0", 1))) == ""


def test_the_lowest_metric_wins() -> None:
    assert _lan([ETH, SECOND], _routes(("eth0", 600), ("eth1", 100))) == "198.51.100.0/24"


def test_two_networks_and_no_default_route_are_not_guessed() -> None:
    """It decides who reaches the console: nothing is written as if it were known."""
    assert _lan([ETH, SECOND]) == ""
    assert _lan([DOCKER, SECOND]) == "198.51.100.0/24"  # a container bridge is no candidate


def test_ipv6_only() -> None:
    six = _if("eth0", ("inet6", "2001:db8:9::2", 64), ("inet6", "fe80::2", 64), ("inet6", "2001:db8:9::ffff", 128))
    assert _lan([six], "[]", _routes(("eth0", 1024))) == "2001:db8:9::/64"
    assert _lan([six]) == "2001:db8:9::/64"


def test_a_route_to_an_interface_that_is_not_listed_or_text_that_is_not_json() -> None:
    assert _lan([ETH], _routes(("eth9", 1))).startswith("192.0.2.0/24")  # falls back to the one candidate
    assert bp.clinic_ranges("not json", "not json", "") == ""
    assert bp.clinic_ranges(json.dumps([ETH]), "not json", "{}").startswith("192.0.2.0/24")


def test_the_old_name_still_answers_and_the_range_passes_the_firewalls_check() -> None:
    assert bp.parse_ip(json.dumps([DOCKER, _if("eno1", ("inet", "192.0.2.40", 24))])) == "192.0.2.0/24"
    hw = bp.Hardware(arch="x86_64", cpu_count=8, ram_gib=64, disk_free_gib=500, lan="192.0.2.0/24 2001:db8:5::/64")
    conf = bp.hardening_conf(hw)
    assert 'CLINIC_RANGES="192.0.2.0/24 2001:db8:5::/64"' in conf
    for r in "192.0.2.0/24 2001:db8:5::/64".split():  # deploy/hardening/apply.sh check_ranges
        assert not set(r) - set("0123456789ABCDEFabcdef.:/")


def test_detect_reads_the_routes_and_both_families() -> None:
    text = Path(bp.__file__).read_text(encoding="utf-8")
    body = text[text.index("def detect(") : text.index("def parse_lsblk(")]
    assert '"route", "show", "default"' in body and '"-6", "route", "show", "default"' in body
    assert '"-4", "addr"' not in body  # the addresses of both families


def test_the_plan_says_when_no_network_was_found() -> None:
    assert "127.0.0.1/32" in bp.hardening_conf(bp.Hardware(arch="x86_64", cpu_count=8, ram_gib=64, disk_free_gib=500))
    assert "CLINIC_RANGES" in bp.LAN_UNKNOWN and "443" in bp.LAN_UNKNOWN
