"""SESSION-DOOR (D-1130): the live session's firewall on the GPU VM, checked for free (deploy/gcp/session_vm.py).

The session reaches the box on tcp:443 only, from the owner's own range, through two rules on a session tag, as the
demo VM does (deploy/gcp/demo-vm.sh `up` and `rules_check`). The GPU VM also carries the tags of the hand-over (its
old door rule opens 443 to an earlier range on `tb-gpu-door`, and the project's `default-allow-ssh` targets every
instance), and it has no deny rule of its own (GPU hand-over T16). The rules check therefore asks about every tag the
VM carries, not only the session's. Synthetic addresses only (documentation-style public addresses)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SV = ROOT / "deploy" / "gcp" / "session_vm.py"

pytestmark = pytest.mark.nodb


def _sv() -> Any:
    spec = importlib.util.spec_from_file_location("h13_session_vm", SV)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sv = _sv()
OWNER = "1.2.3.4/32"
NET = "https://www.googleapis.com/compute/v1/projects/p/global/networks/default"
VM_TAGS = ["tb-gpu", "tb-gpu-door", "tb-session"]


def _rules(**over: dict[str, Any]) -> list[dict[str, Any]]:
    """The project's network as the hand-over describes it, with the session's two rules as box-run.sh makes them."""
    rules = {
        "tb-session-https": {"name": "tb-session-https", "network": NET, "direction": "INGRESS", "priority": 500,
                             "sourceRanges": [OWNER], "targetTags": ["tb-session"],
                             "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}]},
        "tb-session-deny": {"name": "tb-session-deny", "network": NET, "direction": "INGRESS", "priority": 510,
                            "sourceRanges": ["0.0.0.0/0"], "targetTags": ["tb-session"],
                            "denied": [{"IPProtocol": "all"}]},
        "default-allow-ssh": {"name": "default-allow-ssh", "network": NET, "direction": "INGRESS", "priority": 65534,
                              "sourceRanges": ["0.0.0.0/0"], "allowed": [{"IPProtocol": "tcp", "ports": ["22"]}]},
        "tb-gpu-door": {"name": "tb-gpu-door", "network": NET, "direction": "INGRESS", "priority": 1000,
                        "sourceRanges": ["5.6.7.0/24"], "targetTags": ["tb-gpu-door"],
                        "allowed": [{"IPProtocol": "tcp", "ports": ["443"]}]},
        "default-allow-internal": {"name": "default-allow-internal", "network": NET, "direction": "INGRESS",
                                   "priority": 65534, "sourceRanges": ["10.128.0.0/9"],
                                   "allowed": [{"IPProtocol": "all"}]},
    }  # fmt: skip
    for name, change in over.items():
        if change is None:
            rules.pop(name.replace("_", "-"))
        else:
            rules.setdefault(name.replace("_", "-"), {"name": name.replace("_", "-"), "network": NET}).update(change)
    return list(rules.values())


@pytest.mark.parametrize(
    "raw",
    ["", "any", "ANY", "any,1.2.3.4", "0.0.0.0/0", "0/0", "0.0.0.0/1,128.0.0.0/1", "8.0.0.0/8", "100.64.0.0/10",
     "1.2.0.0/16", "10.1.2.0/24", "192.168.1.5", "2001:db8::/64", "1.2.3.4,5.6.7.8,9.9.9.9,8.8.8.8,1.1.1.1"],
)  # fmt: skip
def test_a_range_too_wide_or_not_the_owners_is_refused(raw: str) -> None:
    """Never the world, never the word any, nothing broader than /24, never a private range, at most four."""
    with pytest.raises(sv.Refused):
        sv.parse_allow(raw)


def test_the_owners_own_ranges_are_taken() -> None:
    assert sv.parse_allow("1.2.3.4, 5.6.7.0/24") == ("1.2.3.4/32", "5.6.7.0/24")


def test_the_plan_names_two_rules_and_no_port_but_443() -> None:
    text = sv.plan(("1.2.3.4/32",))
    assert "tb-session-deny: INGRESS DENY all from 0.0.0.0/0, priority 510" in text
    assert "tb-session-https: INGRESS ALLOW tcp:443 from 1.2.3.4/32 only, priority 500" in text
    assert "tcp:80" not in text and "tcp:22" not in text and "no rule for port 80 or 22" in text


def test_only_443_from_the_owners_range_reaches_the_vm() -> None:
    ok, report = sv.rules_check(_rules(), "default", VM_TAGS, [OWNER])
    assert ok, report["problems"]
    assert report["reaches_the_vm"] == "tcp:443 from 1.2.3.4/32 only"
    verdict = {r["rule"]: r["verdict"] for r in report["other_rules_that_apply_to_the_vm"]}
    # the hand-over's two: the old door (on a tag the VM carries) and the project's SSH rule, both beaten by the deny
    assert verdict["tb-gpu-door"].startswith("beaten by tb-session-deny")
    assert verdict["default-allow-ssh"].startswith("beaten by tb-session-deny")


@pytest.mark.parametrize(
    "case",
    ["door-before-deny", "ssh-before-deny", "allow-80-too", "allow-world", "no-deny", "deny-disabled",
     "deny-narrow", "allow-other-tag", "vm-lacks-tag"],
)  # fmt: skip
def test_any_other_way_in_is_refused(case: str) -> None:
    """Must never: any port but 443, any source but the owner's ranges, a rule that comes before the deny."""
    tags = VM_TAGS
    rules = {
        # the old door's rule given a priority above the deny: it reaches by the VM's own tag tb-gpu-door, which a
        # check of the session's tag alone (the demo VM's) would not see
        "door-before-deny": _rules(tb_gpu_door={"priority": 100}),
        "ssh-before-deny": _rules(default_allow_ssh={"priority": 400}),
        "allow-80-too": _rules(tb_session_https={"allowed": [{"IPProtocol": "tcp", "ports": ["443", "80"]}]}),
        "allow-world": _rules(tb_session_https={"sourceRanges": ["0.0.0.0/0"]}),
        "no-deny": _rules(tb_session_deny=None),
        "deny-disabled": _rules(tb_session_deny={"disabled": True}),
        "deny-narrow": _rules(tb_session_deny={"sourceRanges": ["1.2.3.0/24"]}),
        "allow-other-tag": _rules(tb_session_https={"targetTags": ["tb-session", "tb-gpu"]}),
        "vm-lacks-tag": _rules(),
    }[case]
    if case == "vm-lacks-tag":
        tags = ["tb-gpu", "tb-gpu-door"]
    ok, report = sv.rules_check(rules, "default", tags, [OWNER])
    assert not ok and report["problems"] and report["reaches_the_vm"] is None, report


def test_a_rule_on_another_network_does_not_count() -> None:
    other = _rules(default_allow_ssh={"priority": 100, "network": NET.replace("/default", "/other")})
    ok, report = sv.rules_check(other, "default", VM_TAGS, [OWNER])
    assert ok, report["problems"]


def test_the_rules_check_runs_from_the_command_line() -> None:
    """box-run.sh pipes `gcloud compute firewall-rules list --format=json` in; exit 3 names the rule that reaches."""
    good = subprocess.run([sys.executable, str(SV), "rules-check", "default", " ".join(VM_TAGS), OWNER],
                          input=json.dumps(_rules()), capture_output=True, text=True, check=False)  # fmt: skip
    assert good.returncode == 0, good.stderr
    bad = subprocess.run([sys.executable, str(SV), "rules-check", "default", " ".join(VM_TAGS), OWNER],
                         input=json.dumps(_rules(tb_gpu_door={"priority": 100})), capture_output=True, text=True,
                         check=False)  # fmt: skip
    assert bad.returncode == 3 and "tb-gpu-door reaches the VM" in bad.stdout
    wide = subprocess.run([sys.executable, str(SV), "rules-check", "default", "tb-session", "0.0.0.0/0"],
                          input="[]", capture_output=True, text=True, check=False)  # fmt: skip
    assert wide.returncode == 2 and "whole internet" in wide.stderr


def test_the_session_options_are_checked_and_never_production() -> None:
    lines = sv.shell_lines("1.2.3.4", "dev", "3")
    assert "SESSION_ENV=DEV" in lines and "SESSION_PEOPLE=owner:coordinator+investigator+steward+admin" in lines
    v = sv.shell_lines("1.2.3.4", "validation", "2")
    assert (
        "SESSION_ENV=VALIDATION" in v and "owner-crc:coordinator" in v and "+" not in v.split("PEOPLE=")[1].split()[0]
    )
    for bad in (("production",), ("PRODUCTION",), ("test",)):
        with pytest.raises(sv.Refused, match="never PRODUCTION"):
            sv.env_name(*bad)
    with pytest.raises(sv.Refused, match="one role per account"):
        sv.parse_people("owner:coordinator+admin", "VALIDATION")
    for hours in ("0", "4", "2.5", "x"):
        with pytest.raises(sv.Refused):
            sv.parse_hours(hours)
    with pytest.raises(sv.Refused):
        sv.parse_people("admin:admin", "DEV")  # a seeded account's name


ID_A, ID_B = "a" * 16, "b" * 16


def _serial(*lines: str) -> str:
    return "".join(f"Nov 17 10:00:00 tb-gpu-sim google_metadata_script_runner[1]: startup-script: {x}\n" for x in lines)


def test_ready_counts_only_from_this_boot() -> None:
    """D-1120's order for the session's lines: the id decides alone; else the boot stamped after the start."""
    old = _serial(f"TB-SESSION-BOOT boot={ID_A} started=2026-11-17T01:00:00Z",
                  f"TB-SESSION-READY boot={ID_A} at=2026-11-17T01:40:00Z stop=2026-11-17T04:40:00Z")  # fmt: skip
    start = sv.demo_vm.instant("2026-11-17T06:00:00-00:00")
    assert sv.boot_state(old, start)[0] == "stale"
    new = old + _serial(f"TB-SESSION-BOOT boot={ID_B} started=2026-11-17T06:00:05Z")
    assert sv.boot_state(new, start)[0] == "waiting"
    ready = new + _serial(f"TB-SESSION-READY boot={ID_B} at=2026-11-17T06:40:00Z stop=2026-11-17T09:40:00Z")
    assert sv.boot_state(ready, start)[0] == "ready"
    assert sv.boot_state(ready, None, ID_A)[0] == "ready"  # an id decides alone
    ended = ready + _serial(f"TB-SESSION-END boot={ID_B} at=2026-11-17T09:40:00Z why=the session's stop")
    assert sv.boot_state(ended, start)[0] == "ended"
    assert sv.boot_state(ready)[0] == "unknown"


def test_links_meta_reads_the_id_the_certificate_and_the_stop_and_never_a_code() -> None:
    fp = ":".join(["AB"] * 32)
    text = (f"TrialBox session (boot id {ID_A}); root SHA-256 {fp}; it closes at 2026-11-17T09:40:00Z.\n"
            "owner (coordinator+investigator): https://box/enrol#u=owner&c=SYNTHETIC-CODE-0001\n")  # fmt: skip
    meta = sv.links_meta(text)
    assert meta == {"boot_id": ID_A, "certificate_sha256": fp, "stop": "2026-11-17T09:40:00Z"}
    assert "SYNTHETIC-CODE" not in json.dumps(meta)
