"""The live session's free checks and readers (D-1123, the owner's session on the GPU VM; deploy/gcp/box-run.sh).

Standard library only, as deploy/gcp/demo_vm.py, whose checks it reuses rather than copies: the allowed ranges
(``demo_vm.parse_allow``), the people (``demo_vm.parse_people``), the reaching rules (``demo_vm.reaching_rules``)
and the serial pages (``demo_vm.serial_text``, ``serial_next``, ``instant``). Nothing here calls gcloud: box-run.sh
makes the calls and hands their output in.

    python3 deploy/gcp/session_vm.py shell --allow RANGES --env dev|validation --hours N [--people P] [--synth N]
        the session's options checked, as shlex-quoted shell assignments for box-run.sh; a refused one exits 2
    python3 deploy/gcp/session_vm.py plan RANGES [NETWORK]
        the two firewall rules the session would make (D-1130), as text: the preflight prints it
    python3 deploy/gcp/session_vm.py rules-check NETWORK "TAG TAG ..." RANGES < rules.json
        D-1130: from `gcloud compute firewall-rules list --format=json` and the VM's own tags, whether only tcp:443
        from RANGES reaches the VM: the session's two rules exactly as made, the VM carrying the session's tag, and
        every other rule that applies to the VM (by any of its tags, by no target, by a service account) beaten by
        the session's deny. One JSON report; exit 0 when it holds, 3 when not
    python3 deploy/gcp/session_vm.py boot-state [--last-start T] [--boot-id ID] PAGE.json ...
        D-1132: the session's own lines from the serial console and one line `session: ...`: ready only from this
        boot (its id, or its stamp at or after the instance's lastStartTimestamp T), as D-1120 reads the demo VM
    python3 deploy/gcp/session_vm.py links-meta < links.txt
        D-1133: the boot id, the certificate's SHA-256 and the stop time the links object names (never a code)

The limits, each with its reason (OD-10; constants here, not settings: the integrator sets each session's own values
on box-run.sh's command line):

    MIN_PREFIX 24     an allowed range broader than /24 is refused: the session is one person, the owner, from his
                      own line; a home or office line is /24 or narrower (the demo VM's /16 floor was for two guests'
                      unknown providers). The word `any` and 0.0.0.0/0 are refused outright: never the world
    MAX_RANGES 4      the owner's own places (home, office, a phone's provider): more is a list nobody checked
    MAX_HOURS 3       the sitting of D-1123 section 1: at most three hours of the owner's time
"""

from __future__ import annotations

import ipaddress
import json
import re
import shlex
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_vm  # the demo VM's checks, beside this file

TAG = "tb-session"  # the network tag the session's two rules target; added to the VM for the session only
ALLOW_RULE = "tb-session-https"
DENY_RULE = "tb-session-deny"
ALLOW_PRIORITY = demo_vm.ALLOW_PRIORITY  # 500: the session's allow first
DENY_PRIORITY = demo_vm.DENY_PRIORITY  # 510: its deny-all next; any other rule that reaches the VM must come after
WORLD = demo_vm.WORLD
MIN_PREFIX = 24
MAX_RANGES = 4
MAX_HOURS = 3
ENVS = {"dev": "DEV", "validation": "VALIDATION"}  # never PRODUCTION: the session is no hospital box (D-1036)
ROLES = demo_vm.STEPS_ROLES  # investigator, coordinator, viewer, admin, steward
DEFAULT_PEOPLE = {
    # DEV: one sign-in, the acting role (D-1063, D-877: console.steps_roles); the first role is the account's own
    "dev": "owner:coordinator+investigator+steward+admin",
    # VALIDATION: no acting role (D-1063 item 3): one account per role, as D-1123 first proposed
    "validation": "owner-crc:coordinator,owner-inv:investigator,owner-stw:steward,owner-adm:admin",
}
DEFAULT_SYNTH = 200  # the synthetic hospital's patients: a few hundred to screen beside the public sets (D-1132)
MAX_SYNTH = 5000  # the g6 night's generator at 50,000 is a 5-hour night; a sitting needs a hospital, not a night
EVIDENCE = "nothing from this session is evidence"


class Refused(Exception):
    """A session option the driver must not run with; the message says which and why (never a secret value)."""


def parse_allow(raw: str) -> tuple[str, ...]:
    """The source ranges of the session's tcp:443 rule: public IPv4 networks, each /24 or narrower, at most four;
    never empty, never the word ``any``, never 0.0.0.0/0 (the demo VM's own parser, with the session's floor)."""
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if any(x.lower() == demo_vm.OPEN_WORD for x in items):
        raise Refused(
            f"--session-allow: '{demo_vm.OPEN_WORD}' opens tcp:443 to every address; the session takes the owner's "
            "own ranges only (D-1130)"
        )
    for x in items:
        try:
            if ipaddress.ip_network(x if "/" in x else f"{x}/32", strict=False).prefixlen == 0:
                raise Refused("--session-allow: 0.0.0.0/0 is the whole internet; the session never opens to every "
                              "address, only to the owner's own ranges (D-1130)")  # fmt: skip
        except ValueError:
            pass  # not a network: demo_vm's parser below says so
    if len(items) > MAX_RANGES:
        raise Refused(f"--session-allow: at most {MAX_RANGES} ranges (the owner's own places), got {len(items)}")
    try:
        out = demo_vm.parse_allow(raw, MIN_PREFIX)
    except demo_vm.Refused as exc:
        msg = (
            str(exc).replace("TB_DEMO_ALLOW", "--session-allow").replace("TB_DEMO_VM_MIN_PREFIX", "the session's floor")
        )
        raise Refused(msg.replace("the guest's browser", "the owner's browser") + " (D-1130)") from None
    if WORLD in out:  # demo_vm gives the world only for the word, refused above; held here all the same
        raise Refused("--session-allow: 0.0.0.0/0 is the whole internet (D-1130)")
    return out


def env_name(opt: str) -> str:
    """``dev`` or ``validation`` (the driver's option) as the box's TB_ENV."""
    key = (opt or "dev").strip().lower()
    if key not in ENVS:
        raise Refused(
            f"--session-env must be one of {', '.join(ENVS)} (got '{opt}'): a session is never PRODUCTION (D-1132)"
        )
    return ENVS[key]


def parse_people(raw: str, env: str) -> str:
    """name:role[+role] pairs: in DEV a person may act in several roles (D-1063); in VALIDATION one role each."""
    key = env.lower()
    try:
        return demo_vm.parse_people(raw or DEFAULT_PEOPLE[key], ROLES, plus=key == "dev")
    except demo_vm.Refused as exc:
        msg = str(exc).replace("TB_DEMO_VM_PEOPLE", "--session-people")
        if key == "validation" and "+" in (raw or ""):
            msg += " (VALIDATION has no acting role, D-1063 item 3: one role per account)"
        raise Refused(msg) from None


def parse_hours(raw: str) -> int:
    v = (raw or str(MAX_HOURS)).strip()
    if not re.fullmatch(r"[0-9]+", v) or not 1 <= int(v) <= MAX_HOURS:
        raise Refused(f"--session-hours must be a whole number from 1 to {MAX_HOURS} (got '{raw}')")
    return int(v)


def parse_synth(raw: str) -> int:
    v = (raw or str(DEFAULT_SYNTH)).strip()
    if not re.fullmatch(r"[0-9]+", v) or not 0 <= int(v) <= MAX_SYNTH:
        raise Refused(f"--session-synth must be a number of patients from 0 to {MAX_SYNTH} (got '{raw}')")
    return int(v)


def shell_lines(allow: str, env: str, hours: str, people: str = "", synth: str = "") -> str:
    tb_env = env_name(env)
    pairs = {
        "SESSION_ALLOW": ",".join(parse_allow(allow)),
        "SESSION_ENV": tb_env,
        "SESSION_HOURS": str(parse_hours(hours)),
        "SESSION_PEOPLE": parse_people(people, tb_env),
        "SESSION_SYNTH": str(parse_synth(synth)),
        "SESSION_TAG": TAG,
        "SESSION_ALLOW_RULE": ALLOW_RULE,
        "SESSION_DENY_RULE": DENY_RULE,
        "SESSION_ALLOW_PRIORITY": str(ALLOW_PRIORITY),
        "SESSION_DENY_PRIORITY": str(DENY_PRIORITY),
    }
    return "\n".join(f"{k}={shlex.quote(v)}" for k, v in pairs.items())


def plan(ranges: Sequence[str], network: str = "default") -> str:
    """What the session's door makes, before it makes it (the preflight prints this)."""
    return "\n".join(
        [
            f"the session's door (D-1130) on network {network}, both rules on the VM's tag {TAG} only:",
            f"  {DENY_RULE}: INGRESS DENY all from {WORLD}, priority {DENY_PRIORITY} (beats every rule of lower "
            "precedence: default-allow-ssh, the hand-over's old door)",
            f"  {ALLOW_RULE}: INGRESS ALLOW tcp:443 from {','.join(ranges)} only, priority {ALLOW_PRIORITY}",
            "  no rule for port 80 or 22; block-project-ssh-keys=TRUE in the metadata; sshd stopped at every boot",
            f"  the VM gets the tag {TAG} for the session; --stop and the end of a collect remove the tag and both "
            "rules",
        ]
    )


def _ports(entries: object) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict):
            out.append((str(e.get("IPProtocol") or "").lower(), tuple(str(p) for p in e.get("ports") or ())))
    return sorted(out)


def _applies(rule: Mapping[str, object], vm_tags: Sequence[str]) -> bool:
    tags = rule.get("targetTags") or []
    accounts = rule.get("targetServiceAccounts") or []
    listed = tags if isinstance(tags, list) else []
    return (not tags and not accounts) or bool(accounts) or any(t in listed for t in vm_tags)


def rules_check(
    rules: list[dict[str, object]], network: str, vm_tags: Sequence[str], ranges: Sequence[str]
) -> tuple[bool, dict[str, object]]:
    """Only tcp:443 from ``ranges`` reaches the VM: the session's allow exactly as made, its deny-all, the VM carrying
    the session's tag, and every other enabled ingress rule that applies to the VM beaten by the deny (demo_vm's
    reaching_rules, asked once per tag of the VM). Every rule that applies to the VM is in the report with why."""
    problems: list[str] = []
    want = sorted(str(ipaddress.ip_network(r)) for r in ranges)
    on_net = [r for r in rules if str(r.get("network") or "").rstrip("/").endswith(f"/{network}")]
    by_name = {str(r.get("name")): r for r in on_net}
    allow, deny = by_name.get(ALLOW_RULE), by_name.get(DENY_RULE)
    if TAG not in vm_tags:
        problems.append(f"the VM does not carry the tag {TAG}: the session's rules do not apply to it")
    if allow is None:
        problems.append(f"no rule {ALLOW_RULE} on network {network}")
    else:
        if allow.get("disabled") is True or str(allow.get("direction") or "INGRESS") != "INGRESS":
            problems.append(f"{ALLOW_RULE} is disabled or not INGRESS")
        if _ports(allow.get("allowed")) != [("tcp", ("443",))] or allow.get("denied"):
            problems.append(f"{ALLOW_RULE} allows {_ports(allow.get('allowed'))}, not tcp:443 alone")
        if sorted(str(x) for x in allow.get("sourceRanges") or []) != want:  # type: ignore[union-attr]
            problems.append(f"{ALLOW_RULE} is open from {allow.get('sourceRanges')}, not from {want} only")
        if list(allow.get("targetTags") or []) != [TAG]:  # type: ignore[call-overload]
            problems.append(f"{ALLOW_RULE} targets {allow.get('targetTags')}, not [{TAG}] only")
        if int(str(allow.get("priority", 1000))) != ALLOW_PRIORITY:
            problems.append(f"{ALLOW_RULE} has priority {allow.get('priority')}, not {ALLOW_PRIORITY}")
    if deny is None:
        problems.append(f"no rule {DENY_RULE} on network {network}: nothing beats the network's own rules")
    else:
        if deny.get("disabled") is True or str(deny.get("direction") or "INGRESS") != "INGRESS":
            problems.append(f"{DENY_RULE} is disabled or not INGRESS")
        if _ports(deny.get("denied")) != [("all", ())]:
            problems.append(f"{DENY_RULE} denies {_ports(deny.get('denied'))}, not everything")
        if list(deny.get("sourceRanges") or []) != [WORLD]:  # type: ignore[call-overload]
            problems.append(f"{DENY_RULE} denies from {deny.get('sourceRanges')}, not from {WORLD}")
        if list(deny.get("targetTags") or []) != [TAG]:  # type: ignore[call-overload]
            problems.append(f"{DENY_RULE} targets {deny.get('targetTags')}, not [{TAG}] only")
        if int(str(deny.get("priority", 1000))) != DENY_PRIORITY:
            problems.append(f"{DENY_RULE} has priority {deny.get('priority')}, not {DENY_PRIORITY}")
    ours = (ALLOW_RULE, DENY_RULE)
    reaching = sorted({n for t in vm_tags for n in demo_vm.reaching_rules(on_net, network, "default", ours, t)})
    for name in reaching:
        problems.append(f"{name} reaches the VM before {DENY_RULE} (an allow at a priority below {DENY_PRIORITY})")
    seen = []
    for r in on_net:
        name = str(r.get("name") or "")
        if name in ours or str(r.get("direction") or "INGRESS") != "INGRESS" or not _applies(r, vm_tags):
            continue
        if r.get("disabled") is True:
            why = "disabled"
        elif not r.get("allowed"):
            why = "a deny rule"
        elif name in reaching:
            why = f"REACHES the VM (priority {r.get('priority')} < {DENY_PRIORITY})"
        else:
            why = f"beaten by {DENY_RULE} (priority {r.get('priority', 1000)} >= {DENY_PRIORITY})"
        seen.append({"rule": name, "allows": _ports(r.get("allowed")), "from": r.get("sourceRanges"), "verdict": why})
    report = {
        "network": network,
        "vm_tags": list(vm_tags),
        "reaches_the_vm": f"tcp:443 from {','.join(want)} only" if not problems else None,
        "other_rules_that_apply_to_the_vm": seen,
        "problems": problems,
    }
    return not problems, report


# ------------------------------------------------------------------------------------------- the ready line (D-1132)
# The VM prints, on the serial console (deploy/gcp/box-install-run.sh, the session group):
#   TB-SESSION-BOOT boot=<16 hex> started=<RFC 3339>        the first line of every boot of a session run
#   TB-SESSION-READY boot=<id> at=<RFC 3339> stop=<RFC 3339> the session is open; it closes at stop
#   TB-SESSION-NOT-READY boot=<id> at=<RFC 3339> why=<text>  the session did not open on that boot
#   TB-SESSION-END boot=<id> at=<RFC 3339> why=<text>        the session closed: accounts disabled
_LINE_RE = re.compile(
    r"TB-SESSION-(BOOT|READY|NOT-READY|END) boot=([0-9a-f]{16}) (?:started|at)=([0-9TZ:.+-]+)(?: stop=([0-9TZ:.+-]+))?"
    r"(?: why=(.*))?"
)
STATE_TEXT = {
    "ready": "session: TB-SESSION-READY (this boot; the links may be given: box-run.sh --links)",
    "not-ready": "session: TB-SESSION-NOT-READY (this boot; the reason above): no link is given",
    "ended": "session: TB-SESSION-END (this boot): the session is closed, its accounts disabled",
    "waiting": "session: not ready yet (no ready line of this boot)",
    "stale": "session: not ready yet (only an earlier boot's lines; this boot has printed none)",
    "unknown": "session: cannot tell (no lastStartTimestamp and no --boot-id)",
}


def boot_state(serial: str, last_start: datetime | None = None, boot_id: str = "") -> tuple[str, list[str]]:
    """The session's state on this boot and its lines. ``boot_id`` decides alone; else the boot whose BOOT line is
    stamped at or after ``last_start``; else a marker stamped at or after it (D-1120's order)."""
    events = []
    for m in _LINE_RE.finditer(serial):
        events.append((m.group(1), m.group(2), demo_vm.instant(m.group(3)), m.group(0).strip()))
    if not boot_id and last_start is None:
        return "unknown", [e[3] for e in events]
    if boot_id:
        mine = [e for e in events if e[1] == boot_id]
    else:
        boots = [e[1] for e in events if e[0] == "BOOT" and e[2] is not None and e[2] >= last_start]  # type: ignore[operator]
        if boots:
            mine = [e for e in events if e[1] == boots[-1]]
        else:
            mine = [e for e in events if e[0] != "BOOT" and e[2] is not None and e[2] >= last_start]  # type: ignore[operator]
    lines = [e[3] for e in mine]
    marks = [e for e in mine if e[0] != "BOOT"]
    if not marks:
        return ("stale" if events and not mine else "waiting"), lines or [e[3] for e in events[-3:]]
    last = marks[-1][0]
    return {"READY": "ready", "NOT-READY": "not-ready", "END": "ended"}[last], lines


def links_meta(text: str) -> dict[str, str]:
    """What the links object says besides the links: its boot id, the root certificate's SHA-256, the stop time."""
    out = {}
    for key, rx in (
        ("boot_id", r"boot id ([0-9a-f]{16})"),
        ("certificate_sha256", r"root SHA-256 ([0-9A-F:]{95})"),
        ("stop", r"closes at ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z)"),
    ):
        m = re.search(rx, text)
        out[key] = m.group(1) if m else "none"
    return out


def _boot_state_main(argv: list[str]) -> int:
    last_start: datetime | None = None
    boot_id = ""
    pages: list[str] = []
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--last-start" and args:
            last_start = demo_vm.instant(args.pop(0))
        elif a == "--boot-id" and args:
            boot_id = args.pop(0)
            if not re.fullmatch(r"[0-9a-f]{16}", boot_id):
                print("boot-state: --boot-id is 16 hex digits (the id `--links` printed)", file=sys.stderr)
                return 2
        else:
            pages.append(Path(a).read_text(encoding="utf-8", errors="replace"))
    serial = demo_vm.serial_text(pages)[0] if pages else sys.stdin.read()
    state, lines = boot_state(serial, last_start, boot_id)
    for line in lines:
        print(f"  {line}")
    print(STATE_TEXT[state])
    return 0


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["shell"]:
            opts = dict(zip(argv[1::2], argv[2::2], strict=False))
            print(
                shell_lines(
                    opts.get("--allow", ""),
                    opts.get("--env", "dev"),
                    opts.get("--hours", ""),
                    opts.get("--people", ""),
                    opts.get("--synth", ""),
                )
            )
            return 0
        if argv[:1] == ["plan"] and len(argv) in (2, 3):
            print(plan(parse_allow(argv[1]), argv[2] if len(argv) == 3 else "default"))
            return 0
        if argv[:1] == ["rules-check"] and len(argv) == 4:
            ok, report = rules_check(
                json.load(sys.stdin), argv[1], argv[2].replace(",", " ").split(), parse_allow(argv[3])
            )
            print(json.dumps(report, indent=1))
            return 0 if ok else 3
        if argv[:1] == ["boot-state"]:
            return _boot_state_main(argv[1:])
        if argv[:1] == ["links-meta"] and len(argv) == 1:
            for k, v in links_meta(sys.stdin.read()).items():
                print(f"{k}={v}")
            return 0
    except Refused as exc:
        print(f"session: refused: {exc}", file=sys.stderr)
        return 2
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
