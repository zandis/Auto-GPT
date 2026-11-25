"""H-137, the owner's decision on #639 (7156806411 item 7): one named list of proxies the console trusts.

``TB_CONSOLE_FORWARDED_ALLOW_IPS``: on a box, Caddy's fixed address (the installer writes it); on the cluster form, the
site's ingress range; "all" is refused in PRODUCTION; the doctor says what is trusted; the install check fails a fixed
range that clashes with one this host is on. Made-up addresses only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import doctor
from tools.trialbox import preflight as pf

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


@pytest.mark.parametrize("value", ["*", "all", "0.0.0.0/0", "::/0", "172.31.252.250,*"])
def test_the_console_refuses_all_proxies_in_production(value: str) -> None:
    from console.app import ConsoleSettings, PilotRefused

    with pytest.raises(PilotRefused, match="TB_CONSOLE_FORWARDED_ALLOW_IPS"):
        ConsoleSettings.from_env({"TB_ENV": "PRODUCTION", "TB_CONSOLE_FORWARDED_ALLOW_IPS": value})
    ConsoleSettings.from_env({"TB_ENV": "VALIDATION", "TB_CONSOLE_FORWARDED_ALLOW_IPS": value})  # said by the doctor


@pytest.mark.parametrize("value", ["", "172.31.252.250", "10.40.0.0/16,10.41.0.0/16"])
def test_the_console_starts_with_a_named_list_in_production(value: str) -> None:
    from console.app import ConsoleSettings

    ConsoleSettings.from_env({"TB_ENV": "PRODUCTION", "TB_CONSOLE_FORWARDED_ALLOW_IPS": value})


def _doctor(env: dict[str, str]) -> doctor.Check:
    return next(c for c in doctor.CHECKS if c.__name__ == "check_trusted_proxy")(doctor.DoctorInputs(env=env))


def test_the_doctor_says_what_the_console_trusts() -> None:
    assert _doctor({"TB_ENV": "PRODUCTION", "TB_CONSOLE_FORWARDED_ALLOW_IPS": "*"}).status == "FAIL"
    assert _doctor({"TB_ENV": "DEV", "TB_CONSOLE_FORWARDED_ALLOW_IPS": "all"}).status == "WARN"
    behind = {"TB_ENV": "PRODUCTION", "TB_TLS_HOSTNAME": "trialbox.hospital.test"}
    stale = _doctor({**behind, "TB_CONSOLE_FORWARDED_ALLOW_IPS": "127.0.0.1"})
    assert stale.status == "WARN" and "172.31.252.250" in stale.detail  # V3-01 back: every browser one address
    good = _doctor({**behind, "TB_CONSOLE_FORWARDED_ALLOW_IPS": "172.31.252.250"})
    assert good.status == "PASS" and "172.31.252.250" in good.detail
    moved = {**behind, "TB_PROXY_ADDR": "10.99.0.250", "TB_CONSOLE_FORWARDED_ALLOW_IPS": "10.99.0.250"}
    assert _doctor(moved).status == "PASS"
    assert _doctor({"TB_ENV": "PRODUCTION"}).status == "PASS"  # no proxy: each browser is its own address


def test_the_box_files_give_caddy_a_fixed_address_and_trust_only_it() -> None:
    overlay = (DEPLOY / "docker-compose.identity.yml").read_text(encoding="utf-8")
    subnet = re.search(r'subnet:\s*"\$\{TB_NET_SUBNET:-([^}]+)\}"', overlay)
    addr = re.search(r'ipv4_address:\s*"\$\{TB_PROXY_ADDR:-([^}]+)\}"', overlay)
    assert subnet and addr, "the identity overlay fixes neither the range nor Caddy's address"
    import ipaddress

    assert ipaddress.ip_address(addr.group(1)) in ipaddress.ip_network(subnet.group(1))
    console = overlay[overlay.index("\n  console:\n") :]
    trusted = re.findall(r"\$\{TB_CONSOLE_FORWARDED_ALLOW_IPS:-([^}]+)\}", console)
    assert trusted and set(trusted) == {addr.group(1)}  # the command and what the console reads agree
    base = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r'TB_CONSOLE_FORWARDED_ALLOW_IPS: "\$\{TB_CONSOLE_FORWARDED_ALLOW_IPS:-127\.0\.0\.1\}"', base)
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert 'envset TB_CONSOLE_FORWARDED_ALLOW_IPS "${PROXY_ADDR:-' + addr.group(1) + '}"' in install


def test_the_cluster_form_trusts_the_sites_range_not_everyone() -> None:
    apps = (DEPLOY / "platform/base/apps.yaml").read_text(encoding="utf-8")
    flags = re.findall(r'"--forwarded-allow-ips",\s*"([^"]*)"', apps)
    assert flags == ["$(TB_CONSOLE_FORWARDED_ALLOW_IPS)"], flags
    site = (DEPLOY / "platform/base/site.env").read_text(encoding="utf-8")
    assert re.search(r"^TB_CONSOLE_FORWARDED_ALLOW_IPS=$", site, re.M)  # the site names its range; empty trusts none


def _name_cert(nets: list[str] | None, env: dict[str, str] | None = None) -> doctor.Check:
    inp = doctor.DoctorInputs(env={"TB_TLS_HOSTNAME": "trialbox.hospital.test", **(env or {})})
    probes = pf.Probes(resolve=lambda h: ["192.0.2.10"], own_addrs=lambda: {"192.0.2.10"}, host_nets=lambda: nets)
    return pf.check_name_cert(inp, probes)


def test_the_install_check_fails_a_range_that_clashes_with_this_hosts() -> None:
    c = _name_cert(["192.0.2.10/24", "172.31.0.0/16"])
    assert c.status == "FAIL" and "172.31.252.0/24" in c.detail and "172.31.0.0/16" in c.detail
    assert "TB_NET_SUBNET" in c.detail
    moved = _name_cert(["192.0.2.10/24", "172.31.0.0/16"], {"TB_NET_SUBNET": "10.99.0.0/24"})
    assert "clashes" not in moved.detail
    assert "clashes" not in _name_cert(["192.0.2.10/24"]).detail
    assert "clashes" not in _name_cert(None).detail  # the ranges could not be read: not compared


def test_the_hosts_own_container_bridges_are_not_its_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.box import plan

    addr = [
        {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
        {"ifname": "eno1", "addr_info": [{"local": "10.20.30.40", "prefixlen": 24}]},
        {"ifname": "br-4f2a", "addr_info": [{"local": "172.31.252.1", "prefixlen": 24}]},
        {"ifname": "docker0", "addr_info": [{"local": "172.17.0.1", "prefixlen": 16}]},
    ]
    route = [
        {"dst": "default", "dev": "eno1"},
        {"dst": "10.50.0.0/16", "dev": "eno1"},
        {"dst": "172.31.252.0/24", "dev": "br-4f2a"},
    ]

    def run(cmd: list[str], *a: Any, **k: Any) -> str:
        return json.dumps(addr if "addr" in cmd else route)

    monkeypatch.setattr(plan, "_run", run)
    assert pf._host_nets() == ["10.20.30.40/24", "10.50.0.0/16"]
