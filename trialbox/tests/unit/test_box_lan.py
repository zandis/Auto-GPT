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
    for r in ["192.0.2.0/24", "2001:db8:5::/64"]:  # deploy/hardening/apply.sh check_ranges
        assert not set(r) - set("0123456789ABCDEFabcdef.:/")


def test_detect_reads_the_routes_and_both_families() -> None:
    text = Path(bp.__file__).read_text(encoding="utf-8")
    body = text[text.index("def detect(") : text.index("def parse_lsblk(")]
    assert '"route", "show", "default"' in body and '"-6", "route", "show", "default"' in body
    assert '"-4", "addr"' not in body  # the addresses of both families


def test_the_plan_says_when_no_network_was_found() -> None:
    assert "127.0.0.1/32" in bp.hardening_conf(bp.Hardware(arch="x86_64", cpu_count=8, ram_gib=64, disk_free_gib=500))
    assert "CLINIC_RANGES" in bp.LAN_UNKNOWN and "443" in bp.LAN_UNKNOWN


# ---------------------------------------------------------------------------------------------- from the review
@pytest.mark.parametrize(
    ("ip", "n"),
    [
        ("192.168.1.5", 0),  # odd JSON: 0.0.0.0/0 would open 443 to everyone
        ("192.168.1.5", 1),
        ("10.1.2.3", 8),  # wider than a site's network
        ("8.8.4.4", 16),  # a public address straight on the uplink
        ("100.64.0.9", 10),  # carrier-grade NAT / an overlay
        ("0.1.2.3", 8),
        ("224.0.0.5", 24),
    ],
)
def test_review_a_network_too_wide_or_not_private_is_never_written(ip: str, n: int) -> None:
    assert _lan([_if("eth0", ("inet", ip, n))], _routes(("eth0", 100))) == ""


def test_review_ipv6_is_admitted_only_beside_a_private_ipv4_or_as_a_local_prefix() -> None:
    """Before this card 443 over IPv6 answered nobody. A global /64 on a card with no private IPv4 can be an ISP's
    shared segment."""
    alone = _if("eth0", ("inet6", "2600:1f18:1::5", 64))
    assert _lan([alone], "[]", _routes(("eth0", 1))) == ""
    ula = _if("eth0", ("inet6", "fd12:3456:789a:1::5", 64))
    assert _lan([ula], "[]", _routes(("eth0", 1))) == "fd12:3456:789a:1::/64"
    wide = _if("eth0", ("inet", "192.168.1.5", 24), ("inet6", "2600:1f18::5", 3), ("inet6", "ff02::5", 64))
    assert _lan([wide], _routes(("eth0", 1))) == "192.168.1.0/24"
    beside = _if("eth0", ("inet", "192.168.1.5", 24), ("inet6", "2600:1f18:1::5", 64))
    assert _lan([beside], _routes(("eth0", 1))) == "192.168.1.0/24 2600:1f18:1::/64"
    public = _if("eth0", ("inet", "8.8.4.4", 24), ("inet6", "2600:1f18:1::5", 64))
    assert _lan([public], _routes(("eth0", 1))) == ""


@pytest.mark.parametrize(
    "bad",
    [
        [{"ifname": "eth0", "flags": 5, "addr_info": 5}],
        [{"ifname": "eth0", "addr_info": [{"family": "inet", "local": "192.168.1.5", "prefixlen": "x"}]}],
        [{"ifname": 7, "addr_info": [None, 3, {"family": "inet"}]}],
        [3, None, "eth0"],
        {"ifname": "eth0"},
    ],
)
def test_review_odd_shapes_never_raise(bad: Any) -> None:
    for routes in ("[]", json.dumps([{"dst": "default", "dev": "eth0", "metric": "abc"}]),
                   json.dumps([{"dst": "default", "dev": ["eth0"], "metric": {"a": 1}}]), "5", "null"):  # fmt: skip
        assert bp.clinic_ranges(json.dumps(bad), routes, routes) == ""
    good = [_if("eth0", ("inet", "192.168.1.5", 24))]
    assert _lan(good, json.dumps([{"dst": "default", "dev": "eth0", "metric": "abc"}])) == "192.168.1.0/24"


def test_review_a_tunnel_by_its_flag_and_a_loopback_by_its_kind() -> None:
    nord = _if("nordlynx", ("inet", "10.5.0.2", 24), flags=("POINTOPOINT", "NOARP", "UP"), kind="none")
    loop = _if("lo", ("inet", "10.9.9.9", 24), flags=("LOOPBACK", "UP"), kind="loopback")
    odd = _if("dummy7", ("inet", "10.9.8.7", 24), kind="loopback")
    inner = _if("eth0", ("inet", "192.168.1.5", 24))
    assert _lan([nord, loop, odd]) == ""
    assert _lan([nord, loop, odd, inner], _routes(("nordlynx", 1))) == "192.168.1.0/24"


def test_review_a_route_with_several_next_hops_and_one_with_no_metric() -> None:
    a, b = _if("eth0", ("inet", "192.168.1.5", 24)), _if("eth1", ("inet", "192.168.2.5", 24))
    multi = json.dumps(
        [{"dst": "default", "nexthops": [{"gateway": "x", "dev": "eth1"}, {"gateway": "y", "dev": "eth9"}]}]
    )
    assert _lan([a, b], multi) == "192.168.2.0/24"
    assert _lan([a, b], json.dumps([{"dst": "default", "dev": "eth0"}])) == "192.168.1.0/24"


@pytest.mark.parametrize("name", ["lxcbr0", "lxdbr0", "incusbr0", "vboxnet0", "vmnet8", "cni0", "podman1"])
def test_review_more_bridges_of_container_and_vm_tools_are_no_candidates(name: str) -> None:
    assert _lan([_if(name, ("inet", "10.0.3.1", 24)), _if("eth0", ("inet", "192.168.1.5", 24))]) == "192.168.1.0/24"
    assert _lan([_if("br0", ("inet", "192.168.1.5", 24))]) == "192.168.1.0/24"  # a bridge holding the real card


def test_review_the_plan_warns_when_it_writes_no_network() -> None:
    from tests.unit.test_box_plan import _answers, _hw

    assert bp.LAN_UNKNOWN in bp.plan(_answers(), _hw(lan="")).warnings
    assert bp.LAN_UNKNOWN not in bp.plan(_answers(), _hw()).warnings


def test_review_the_record_says_what_the_code_does_about_a_vpn_and_a_second_card() -> None:
    rec = (Path(bp.__file__).resolve().parents[2] / "docs" / "decisions").glob("D-629-*.md")
    text = " ".join(next(rec).read_text(encoding="utf-8").split())
    assert "behind a full-tunnel VPN, or" not in text  # it said such a box is not guessed; one card left IS taken
    assert "uplink" in text and "private" in text
