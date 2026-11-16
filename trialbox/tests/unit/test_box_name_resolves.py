"""OPS-005 (wave 11, the bare Ubuntu box): the address the box prints can be opened. The box's TLS name is
`<name>.local`; the input firewall the plan writes dropped UDP 5353, nothing set the host name to the owner's
choice, and nothing started an mDNS responder, so a team computer got "site not found". Now the plan's hardening.conf
says MDNS=on for a .local box, the firewall lets mDNS in from the box's own network only, the apply step sets the
host name and starts the responder (or says it is missing), and the first-run screen also prints the box's address."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_host_baseline import _conf, _env, _sh, _stubs
from tools.box import plan as bp

ROOT = Path(__file__).resolve().parents[2]
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _render(tmp: Path, **kw: str) -> tuple[int, str, str]:
    r = _sh(["deploy/hardening/apply.sh", "--conf", str(_conf(tmp, **kw)), "render"], _env(tmp, _stubs(tmp, {})))
    return r.returncode, r.stdout, r.stderr


def test_mdns_is_let_in_from_the_boxs_network_only_when_on(tmp_path: Path) -> None:
    rc, rules, err = _render(tmp_path, MDNS="on")
    assert rc == 0, err
    assert (
        "udp dport 5353 ip saddr @clinic_v4 accept" in rules and "udp dport 5353 ip6 saddr @clinic_v6 accept" in rules
    )
    assert "udp dport 5353 accept" not in rules  # never from anywhere
    rc, rules, _ = _render(tmp_path)  # MDNS unset: off, as before
    assert rc == 0 and "5353" not in rules
    rc, _, err = _render(tmp_path, MDNS="yes")
    assert rc == 1 and "MDNS must be on or off" in err


def test_the_box_plan_turns_mdns_on_for_a_local_name_and_off_for_a_dns_name() -> None:
    hw = bp.Hardware(arch="x86_64", cpu_count=8, ram_gib=64, disk_free_gib=500, lan="192.0.2.0/24")
    assert "MDNS=on" in bp.hardening_conf(hw, mdns=True) and "MDNS=off" in bp.hardening_conf(hw, mdns=False)
    assert "MDNS=off" in bp.hardening_conf(hw)  # the IT form's default: the hospital's DNS names the box


def test_the_apply_step_sets_the_host_name_starts_the_responder_and_prints_the_address() -> None:
    zone = BOX_INSTALL[BOX_INSTALL.index("# OPS-005") :]
    assert 'hostnamectl set-hostname "${HOST%.local}"' in zone
    assert "systemctl enable --now avahi-daemon" in zone
    assert "no mDNS responder (avahi-daemon)" in zone  # said, not hidden, when it is missing
    show = BOX_INSTALL[BOX_INSTALL.index("show_code() {") : BOX_INSTALL.index("show_code\n")]
    assert "box_address" in show and "certificate" in show
