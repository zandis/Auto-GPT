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


def _instance(tags: list[str] | None = None, **nic: Any) -> dict[str, Any]:
    """`gcloud compute instances describe --format=json` of the GPU VM: one IPv4 interface on default."""
    return {"tags": {"items": tags if tags is not None else VM_TAGS},
            "networkInterfaces": [{"network": NET, "stackType": "IPV4_ONLY",
                                   "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "natIP": "34.80.0.10"}], **nic}]}  # fmt: skip


NO_POLICY: dict[str, Any] = {"firewalls": [], "firewallPolicys": []}


def _check(rules: list[dict[str, Any]], tags: list[str] | None = None, inst: dict[str, Any] | None = None,
           eff: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:  # fmt: skip
    i = inst if inst is not None else _instance(tags)
    ok, report = sv.rules_check(
        rules, "default", sv.instance_tags(i), [OWNER], i, eff if eff is not None else NO_POLICY
    )
    return bool(ok), dict(report)


def _rules(**over: dict[str, Any] | None) -> list[dict[str, Any]]:
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
    ok, report = _check(_rules())
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
    ok, report = _check(rules, tags)
    assert not ok and report["problems"] and report["reaches_the_vm"] is None, report


def test_a_rule_on_another_network_does_not_count() -> None:
    other = _rules(default_allow_ssh={"priority": 100, "network": NET.replace("/default", "/other")})
    ok, report = _check(other)
    assert ok, report["problems"]


def test_the_rules_check_runs_from_the_command_line(tmp_path: Path) -> None:
    """box-run.sh pipes `gcloud compute firewall-rules list --format=json` in, with the VM's own description and its
    effective firewalls in files; exit 3 names the rule that reaches. Without them nothing is proved."""
    (tmp_path / "i.json").write_text(json.dumps(_instance()))
    (tmp_path / "e.json").write_text(json.dumps(NO_POLICY))
    cmd = [sys.executable, str(SV), "rules-check", "default", "-", OWNER, "--instance", str(tmp_path / "i.json"),
           "--effective", str(tmp_path / "e.json")]  # fmt: skip
    good = subprocess.run(cmd, input=json.dumps(_rules()), capture_output=True, text=True, check=False)
    assert good.returncode == 0, good.stdout + good.stderr
    bad = subprocess.run(cmd, input=json.dumps(_rules(tb_gpu_door={"priority": 100})), capture_output=True, text=True,
                         check=False)  # fmt: skip
    assert bad.returncode == 3 and "tb-gpu-door reaches the VM" in bad.stdout
    blind = subprocess.run([sys.executable, str(SV), "rules-check", "default", " ".join(VM_TAGS), OWNER],
                           input=json.dumps(_rules()), capture_output=True, text=True, check=False)  # fmt: skip
    assert blind.returncode == 3 and "was not read" in blind.stdout
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


# ---------------------------------------------------------------- the security review's finding 7: what VPC rules miss
@pytest.mark.parametrize(
    "case",
    ["allow-source-tags", "allow-source-accounts", "ipv6-access", "dual-stack", "two-nics", "policy-allow"],
)
def test_ways_in_the_vpc_rules_do_not_show_are_refused(case: str) -> None:
    rules, inst, eff = _rules(), _instance(), NO_POLICY
    if case == "allow-source-tags":  # other VMs of the project reach 443 by their tag
        rules = _rules(tb_session_https={"sourceTags": ["tb-other"]})
    elif case == "allow-source-accounts":
        rules = _rules(tb_session_https={"sourceServiceAccounts": ["x@p.iam.gserviceaccount.com"]})
    elif case == "ipv6-access":  # the deny names 0.0.0.0/0 only
        inst = _instance(ipv6AccessConfigs=[{"type": "DIRECT_IPV6", "externalIpv6": "2001:db8::5"}])
    elif case == "dual-stack":
        inst = _instance(stackType="IPV4_IPV6")
    elif case == "two-nics":
        inst = _instance()
        inst["networkInterfaces"].append({"network": NET.replace("/default", "/other"), "stackType": "IPV4_ONLY"})
    else:  # a hierarchical policy rule is evaluated before every VPC rule, and firewall-rules list does not show it
        eff = {"firewalls": [], "firewallPolicys": [{"name": "org-policy", "type": "HIERARCHY", "rules": [
            {"priority": 100, "direction": "INGRESS", "action": "allow",
             "match": {"srcIpRanges": ["0.0.0.0/0"], "layer4Configs": [{"ipProtocol": "tcp", "ports": ["22"]}]}}]}]}  # fmt: skip
    ok, report = _check(rules, inst=inst, eff=eff)
    assert not ok and report["reaches_the_vm"] is None, report


def test_a_policy_that_denies_or_hands_on_is_no_way_in() -> None:
    eff = {"firewallPolicys": [{"name": "org", "type": "HIERARCHY", "rules": [
        {"priority": 10, "direction": "INGRESS", "action": "deny", "match": {"srcIpRanges": ["0.0.0.0/0"]}},
        {"priority": 20, "direction": "INGRESS", "action": "goto_next", "match": {"srcIpRanges": ["0.0.0.0/0"]}},
        {"priority": 30, "direction": "EGRESS", "action": "allow", "match": {"destIpRanges": ["0.0.0.0/0"]}}]}]}  # fmt: skip
    ok, report = _check(_rules(), eff=eff)
    assert ok, report["problems"]


# ---------------------------------------------------------------- finding 4: the links object's bucket
PRIVATE = {"uniform_bucket_level_access": True, "public_access_prevention": "enforced", "versioning_enabled": False,
           "soft_delete_policy": {"retentionDurationSeconds": "604800"}}  # fmt: skip
IAM = {"bindings": [{"role": "roles/storage.objectAdmin", "members": ["serviceAccount:x@p.iam.gserviceaccount.com"]}]}


@pytest.mark.parametrize(
    "case, describe, iam",
    [("allUsers", PRIVATE, {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]}),
     ("allAuthenticated", PRIVATE, {"bindings": [{"role": "r", "members": ["allAuthenticatedUsers"]}]}),
     ("object-acls-can-apply", {**PRIVATE, "uniform_bucket_level_access": False,
                                "public_access_prevention": "inherited"}, IAM),
     ("versioning", {**PRIVATE, "versioning_enabled": True}, IAM)],
)  # fmt: skip
def test_a_bucket_that_could_show_the_links_is_refused(
    case: str, describe: dict[str, Any], iam: dict[str, Any]
) -> None:
    ok, problems, _notes = sv.bucket_check(describe, iam)
    assert not ok and problems, case


def test_a_private_bucket_passes_and_its_soft_delete_is_said() -> None:
    ok, problems, notes = sv.bucket_check(PRIVATE, IAM)
    assert ok and problems == [] and "soft delete keeps a deleted object 7 day(s)" in notes[0]
    assert sv.bucket_check({**PRIVATE, "uniform_bucket_level_access": False}, IAM)[0]  # enforced prevention suffices


def test_a_name_the_vm_would_make_too_long_is_refused_by_the_driver() -> None:
    """Finding 9: the VM adds the run's 10-character stamp; the console takes 32."""
    assert sv.parse_people("a" * 22 + ":coordinator", "VALIDATION")
    with pytest.raises(sv.Refused, match="longer than 22"):
        sv.parse_people("a" * 23 + ":coordinator", "VALIDATION")


# ---------------------------------------------------------------- the re-review of 2026-11-17: B and a note
@pytest.mark.parametrize(
    "dest, holds",
    [(["192.0.2.1/32"], False),  # the review's case: a deny of traffic to another address only
     (["10.128.0.0/9"], False),  # the internal range only: the VM's external address is not denied
     (["34.80.0.10/32", "10.128.0.5/32"], True),  # every address of the VM
     (["0.0.0.0/0"], True),
     ([], True)],
    ids=["another-address", "internal-only", "every-address", "world", "none"],
)  # fmt: skip
def test_the_deny_must_cover_every_address_of_the_vm(dest: list[str], holds: bool) -> None:
    """The re-review's B: `destinationRanges` narrows a deny to traffic for those addresses; the check read none."""
    inst = _instance(networkIP="10.128.0.5")
    ok, report = _check(_rules(tb_session_deny={"destinationRanges": dest}), inst=inst)
    assert ok is holds, report["problems"]
    if not holds:
        assert any("tb-session-deny denies only traffic to" in p for p in report["problems"])


@pytest.mark.parametrize("action", ["apply_security_profile_group", "ALLOW", "", "some_action_added_later"])
def test_a_policy_action_other_than_deny_or_goto_next_is_a_way_in(action: str) -> None:
    """The re-review's B: only `deny` and `goto_next` leave the decision to the session's rules."""
    eff = {"firewallPolicys": [{"name": "org", "type": "HIERARCHY", "rules": [
        {"priority": 10, "direction": "INGRESS", "action": action, "match": {"srcIpRanges": ["0.0.0.0/0"]}}]}]}  # fmt: skip
    ok, report = _check(_rules(), eff=eff)
    assert not ok and any("firewall policy org" in p for p in report["problems"]), report


def test_a_bucket_readable_by_a_whole_domain_is_refused_and_a_group_is_said() -> None:
    """The re-review's note: a `domain:` binding lets every account of an organisation read the links object."""
    dom = {"bindings": [{"role": "roles/storage.objectViewer", "members": ["domain:hospa.test"]}]}
    ok, problems, _notes = sv.bucket_check(PRIVATE, dom)
    assert not ok and "whole domains" in problems[0]
    grp = {"bindings": [{"role": "roles/storage.objectViewer", "members": ["group:ops@hospa.test"]}]}
    ok, problems, notes = sv.bucket_check(PRIVATE, grp)
    assert ok and any("group:ops@hospa.test" in n for n in notes)


# ---------------------------------------------------------------- the re-review's round 3: finding 6
@pytest.mark.parametrize(
    "dest, holds",
    [(["34.80.0.10/32", "10.128.0.5/32"], False),  # the review's case: the VM's two addresses, not its alias range
     (["34.80.0.10/32", "10.128.0.0/24"], False),  # an alias range only half held
     (["34.80.0.10/32", "10.128.0.0/16"], True)],  # every address and the whole alias range
    ids=["alias-not-denied", "alias-half", "alias-held"],
)  # fmt: skip
def test_the_deny_must_cover_the_vms_alias_ranges_too(dest: list[str], holds: bool) -> None:
    """Round 3's finding 6: an alias IP range of the interface is an address of the VM; a deny narrowed to its
    networkIP and natIP passed while the alias range was not denied."""
    inst = _instance(networkIP="10.128.0.5", aliasIpRanges=[{"ipCidrRange": "10.128.1.0/25"}])
    ok, report = _check(_rules(tb_session_deny={"destinationRanges": dest}), inst=inst)
    assert ok is holds, report["problems"]
    if not holds:
        assert any("10.128.1.0/25" in p for p in report["problems"]), report["problems"]


def test_an_alias_range_that_cannot_be_read_is_never_held() -> None:
    inst = _instance(networkIP="10.128.0.5", aliasIpRanges=[{"subnetworkRangeName": "pods"}])
    ok, report = _check(_rules(tb_session_deny={"destinationRanges": ["34.80.0.10/32", "10.0.0.0/8"]}), inst=inst)
    assert not ok and any("tb-session-deny denies only traffic to" in p for p in report["problems"])
