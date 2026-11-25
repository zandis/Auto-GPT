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


# ------------------------------------------------------------------------------- test boxes (the rehearsal's red)
def _ip_runner(addr: list[dict[str, Any]], route: list[dict[str, Any]]) -> Any:
    import subprocess

    def run(argv: Any) -> subprocess.CompletedProcess[str]:
        out = json.dumps(addr if "addr" in argv else route)
        return subprocess.CompletedProcess(list(argv), 0, out, "")

    return run


def _deploy_with_overlay(tmp: Path) -> Path:
    import shutil

    d = tmp / "deploy"
    d.mkdir()
    shutil.copy(DEPLOY / "docker-compose.identity.yml", d / "docker-compose.identity.yml")
    return d


def test_every_box_gets_its_own_range_and_proxy_address(tmp_path: Path) -> None:
    import ipaddress

    from tools.trialbox import testbox

    d = _deploy_with_overlay(tmp_path)
    seen = [ipaddress.ip_network(testbox.nets(d, n)["TB_NET_SUBNET"]) for n in range(testbox.MAX_OFFSET + 1)]
    assert str(seen[0]) == "172.31.252.0/24"  # offset 0: the ordinary box's own default
    assert not any(x.overlaps(y) for i, x in enumerate(seen) for y in seen[i + 1 :])
    for n in range(testbox.MAX_OFFSET + 1):
        got = testbox.nets(d, n)
        assert ipaddress.ip_address(got["TB_PROXY_ADDR"]) in ipaddress.ip_network(got["TB_NET_SUBNET"])
    assert testbox.nets(tmp_path, 3) == {}  # no overlay: nothing to move


def test_a_test_box_whose_range_meets_the_hosts_is_refused(tmp_path: Path) -> None:
    from tools.trialbox import testbox

    d = _deploy_with_overlay(tmp_path)
    mine = testbox.nets(d, 2)["TB_NET_SUBNET"]  # 172.31.250.0/24
    lan = _ip_runner([{"ifname": "eno1", "addr_info": [{"local": "172.31.250.9", "prefixlen": 24}]}], [])
    why = testbox.range_clash(d, 2, lan)
    assert why.startswith(f"the box's internal range {mine} (port offset 2)") and "host's 172.31.250.0/24" in why
    bridge = _ip_runner([{"ifname": "br-9f1c", "addr_info": [{"local": "172.31.250.1", "prefixlen": 24}]}],
                        [{"dst": "172.31.250.0/24", "dev": "br-9f1c"}])  # fmt: skip
    assert testbox.range_clash(d, 2, bridge) == ""  # another box's own network: kept apart by the offset
    assert testbox.range_clash(d, 3, lan) == ""

    def broken(argv: Any) -> Any:
        raise OSError("no ip here")

    assert testbox.range_clash(d, 2, broken) == ""  # the ranges cannot be read: not compared, as preflight


def test_the_record_step_refuses_a_clashing_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import testbox

    d = _deploy_with_overlay(tmp_path)
    monkeypatch.setattr(testbox, "_run", _ip_runner([{"ifname": "eno1", "addr_info": [
        {"local": "172.31.251.20", "prefixlen": 23}]}], []))  # fmt: skip
    monkeypatch.setattr(testbox, "clashes", lambda *a: [])
    rc = testbox.main(["record", "--deploy", str(d), "--name", "rh", "--port-offset", "1"])
    assert rc == 2 and not (d / testbox.RECORD).exists()  # refused: nothing was changed
