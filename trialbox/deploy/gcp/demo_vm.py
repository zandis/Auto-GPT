"""The settings, checks and cost estimate of the small demo VM (deploy/gcp/demo-vm.sh; docs/runbook/11-cloud-runs.md).

Standard library only: the operator's host runs it with any Python 3.10+, before any gcloud call.

    python3 deploy/gcp/demo_vm.py estimate          the machine, US$ per hour, day and week, the disk, the sources
    python3 deploy/gcp/demo_vm.py shell up|status|down|delete|dry|links
                                                    the checked settings as shell assignments (shlex-quoted) for
                                                    demo-vm.sh; a refused setting exits 2 with the reason
    python3 deploy/gcp/demo_vm.py rules-check NETWORK MODE RULE DENY TAG < rules.json
                                                    the firewall rules (gcloud ... list --format=json) that could
                                                    reach the VM besides its own two; exit 3 and their names if any
    python3 deploy/gcp/demo_vm.py boot-state < serial.txt
                                                    the last boot's TB-DEMO-VM lines from the serial console (gcloud
                                                    ... get-serial-port-output) and one line `boot: ...` with its
                                                    DEMO-VM-READY or DEMO-VM-NOT-READY marker, or that it is not done

Every limit is a declared TB_* setting with its reason (OD-10; tb_common.config.DECLARED has the rows):

    TB_DEMO_VM_NAME       tb-demo-vm      the prefix of every resource (VM, network, subnet, firewall rule, tag)
    TB_DEMO_VM_ZONE       asia-east1-a    the owner's choice for the 2026-11-17 demo (Taiwan, near both people)
    TB_DEMO_VM_MACHINE    e2-standard-4   4 vCPU, 16 GB: the demo's measured peak is 1.82 GB plus PostgreSQL and the
                                          README plans 4 GB; four cores shorten the 3 to 6 minute seed. Never a GPU.
    TB_DEMO_VM_DISK_GB    30              Debian (about 3 GB), Docker, the demo image (about 1.5 GB unpacked, its
                                          tarball and its layers) and logs; the PoC host's boot disk is the same size
    TB_DEMO_VM_HOURS      12              the hard stop of one `up`: the VM powers itself off after this many hours
                                          (and Compute Engine stops it at the same time), so a forgotten demo cannot
                                          bill for a week. One working day with margin.
    TB_DEMO_VM_MIN_PREFIX 16              an allowed IPv4 range broader than /16 is refused: a home or office range
                                          is /24 or narrower, and 0.0.0.0/1 + 128.0.0.0/1 is the world in two rows
    TB_DEMO_ALLOW         (required)      the only source ranges of tcp:443, comma separated (1.2.3.4/32,5.6.7.8/32);
                                          or the word `any`: tcp:443 from 0.0.0.0/0, OPEN TO ANY ADDRESS, the sign-in
                                          password the only gate. The owner's ruling of 2026-11-15: the demo of
                                          2026-11-17 is a PoC with synthetic data only, reachable from anywhere, kept
                                          by the password and TLS alone. Only the explicit word opens it: an empty or
                                          missing value, 0.0.0.0/0 written out, or `any` mixed with ranges is refused
    TB_DEMO_VM_NETWORK    default         `default`: the project's existing `default` network, so `up` needs only
                                          what the deployer already has (compute.instanceAdmin.v1 and
                                          compute.securityAdmin, deploy/gcp/setup-gcp.sh), not networkAdmin. Its own
                                          rules (default-allow-ssh, -rdp, -icmp, -internal) target every instance, so
                                          the VM gets two rules of its own on its tag: allow tcp:443 (priority 500)
                                          and deny everything else (priority 510), which beats every rule of lower
                                          precedence (a larger number; the default rules are 65534); `up` refuses
                                          when another allow rule could reach the VM before the deny. The VM also
                                          stops sshd at boot. `own`: a network of the VM's own (needs
                                          roles/compute.networkAdmin), with the one tcp:443 rule and no other
    TB_DEMO_VM_IMAGE      (up)            REGISTRY/PATH@sha256:<64 hex>, or gs://BUCKET/trialbox-demo.tar.gz
                                          (`make demo-bundle`) with TB_DEMO_VM_IMAGE_SHA256, checked on the VM
    TB_DEMO_VM_PEOPLE     owner:investigator,guest:coordinator
                                          one account per person, name:role. Each is opened at boot with the
                                          product's one-time enrolment code (D-719): the person chooses the password
                                          on /enrol (the product's rule, at least 12 characters, console/auth.py
                                          MIN_PASSWORD). investigator and coordinator see patient-level synthetic
                                          rows on every demo study (sub-PI or CRC on its delegation log, all four
                                          tasks); viewer sees aggregates only. admin is not offered: it has no
                                          patient-level page (D-280). No role sees everything (D-280, D-380)
    TB_DEMO_VM_ENROL_HOURS 24             how long an unused code is good for: one working day, as the product's
                                          own default (TB_CONSOLE_ENROL_CODE_HOURS, D-719), within its 1 to 72
    TB_DEMO_VM_HANDOFF    $TB_BUCKET/demo-vm  the private gs:// place where the VM writes the one object with the
                                          codes (the VM's service account has objectAdmin on TB_BUCKET; setup-gcp.sh);
                                          `demo-vm.sh links` reads it once and deletes it. Never the metadata, the
                                          serial console or a log. No Secret Manager and no password from anyone
    TB_DEMO_VM_HOST       (not built)     a DNS name for a publicly trusted certificate: refused (see below)
    TB_DEMO_VM_STOP_WAIT_S 300            `down`: how long to wait for TERMINATED after the stop returned; an e2 VM
                                          stops in under a minute, five times that means it is stuck
    prices                                TB_DEMO_VM_PRICE_HOUR, TB_DEMO_VM_DISK_PRICE_GB_MONTH,
                                          TB_DEMO_VM_IP_PRICE_HOUR, with TB_DEMO_VM_PRICE_SOURCE and _DATE: list
                                          prices change, so they are settings with their source and date, never
                                          constants; a machine other than e2-standard-4 needs its own hourly price

TLS: Caddy in front with `tls internal` (its own CA): the browser warns once per device. A publicly trusted
certificate for a DNS name would need ACME: with the address lock HTTP-01 and TLS-ALPN-01 cannot pass; with `any`
TLS-ALPN-01 could, but it needs a DNS name for the VM's address; DNS-01 needs the DNS provider's credential and a
Caddy built with that provider. Not built.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass

HOURS_PER_DAY = 24
HOURS_PER_WEEK = 7 * 24
HOURS_PER_MONTH = 730  # Google's billing month for per-GB-month prices (365 x 24 / 12)
DEFAULT_MACHINE = "e2-standard-4"
# accelerator families (GPU, TPU) and their prefixes: this VM never has one
GPU_FAMILIES = ("a2-", "a3-", "a4-", "g2-", "g4-", "ct", "tpu")
MACHINE_RE = re.compile(r"[a-z][a-z0-9]*-[a-z0-9-]+")
ZONE_RE = re.compile(r"[a-z]+-[a-z]+[0-9]+-[a-z]")
NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,40}[a-z0-9]")
DIGEST_RE = re.compile(r"[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}")
GS_RE = re.compile(r"gs://[a-z0-9._-]{3,63}/[A-Za-z0-9._/-]+\.tar\.gz")
SHA_RE = re.compile(r"[0-9a-f]{64}")
LANGS = ("ja", "zh-TW", "en")
MIN_DISK_GB = 10  # the Debian 12 image's own disk size: Compute Engine refuses a smaller boot disk
OPEN_WORD = "any"  # TB_DEMO_ALLOW=any: the owner's ruling of 2026-11-15 (PoC, synthetic data only)
WORLD = "0.0.0.0/0"
OPEN_TEXT = "open to any address; the sign-in password is the only gate"
NETWORKS = ("default", "own")
DEFAULT_PEOPLE = "owner:investigator,guest:coordinator"
PERSON_ROLES = ("investigator", "coordinator", "viewer")  # admin: no patient-level page (D-280)
PERSON_RE = re.compile(r"[a-z][a-z0-9._-]{1,31}")
SEEDED = ("admin", "crc", "pi", "subpi", "cra", "viewer", "stw")  # tools/demo.py SEEDED: the seed's own accounts
HANDOFF_RE = re.compile(r"gs://[a-z0-9._-]{3,63}(/[A-Za-z0-9._-]+)*")
# firewall priorities on the `default` network (a smaller number wins; at equal priority a deny wins): the VM's
# allow first, its deny-all next; any other allow rule that reaches the VM must come after the deny
ALLOW_PRIORITY = 500
DENY_PRIORITY = 510


class Refused(Exception):
    """A setting the demo VM must not run with; the message says which and why (never a secret value)."""


@dataclass(frozen=True)
class Settings:
    name: str
    network: str
    zone: str
    region: str
    machine: str
    disk_gb: int
    hours: int
    min_prefix: int
    allow: tuple[str, ...]
    open_any: bool
    image: str
    image_sha256: str
    people: str
    enrol_hours: int
    handoff: str
    lang: str
    site_lang: str
    stop_wait_s: int
    price_hour: float
    disk_price_gb_month: float
    ip_price_hour: float
    price_source: str
    price_date: str


def _int(env: Mapping[str, str], key: str, default: str, lowest: int) -> int:
    raw = (env.get(key) or default).strip()
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < lowest:
        raise Refused(f"{key} must be a whole number from {lowest} (got '{raw}')")
    return int(raw)


def _price(env: Mapping[str, str], key: str, default: str) -> float:
    raw = (env.get(key) or default).strip()
    try:
        v = float(raw)
    except ValueError:
        raise Refused(f"{key} must be a price in US$ (got '{raw}')") from None
    if not v > 0:
        raise Refused(f"{key} must be above 0 (got '{raw}')")
    return v


def parse_people(raw: str) -> str:
    """name:role pairs, comma separated: names as the console takes them, not a seeded account, each once."""
    out: list[str] = []
    for item in [x.strip() for x in raw.split(",") if x.strip()]:
        name, _, role = item.partition(":")
        name, role = name.strip().lower(), role.strip()
        if not PERSON_RE.fullmatch(name):
            raise Refused(f"TB_DEMO_VM_PEOPLE: '{name}' is not a user name (a-z 0-9 . _ -, 2 to 32, a letter first)")
        if name in SEEDED:
            raise Refused(f"TB_DEMO_VM_PEOPLE: '{name}' is one of the seed's own accounts; choose another name")
        if role not in PERSON_ROLES:
            raise Refused(f"TB_DEMO_VM_PEOPLE: {name}'s role must be one of {', '.join(PERSON_ROLES)}")
        if any(x.split(":")[0] == name for x in out):
            raise Refused(f"TB_DEMO_VM_PEOPLE: '{name}' is listed twice")
        out.append(f"{name}:{role}")
    if not out:
        raise Refused(
            "TB_DEMO_VM_PEOPLE is empty: name:role for each person (e.g. owner:investigator,guest:coordinator)"
        )
    return ",".join(out)


def parse_allow(raw: str, min_prefix: int) -> tuple[str, ...]:
    """The source ranges of the tcp:443 rule: IPv4 networks, each at least /min_prefix; never none. The world only
    through the explicit word ``any`` alone (the owner's ruling of 2026-11-15), never by accident."""
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if not items:
        raise Refused(
            "TB_DEMO_ALLOW is empty: name the owner's and the guest's addresses (1.2.3.4/32,5.6.7.8/32), or write "
            f"the word {OPEN_WORD} to open tcp:443 to every address (the sign-in password is then the only gate)"
        )
    if any(x.lower() == OPEN_WORD for x in items):
        if len(items) != 1:
            raise Refused(f"TB_DEMO_ALLOW: '{OPEN_WORD}' stands alone (it opens tcp:443 to every address); no ranges")
        return (WORLD,)
    out: list[str] = []
    for item in items:
        try:
            net = ipaddress.ip_network(item if "/" in item else f"{item}/32", strict=True)
        except ValueError:
            raise Refused(f"TB_DEMO_ALLOW: '{item}' is not an IPv4 address or network (host bits set?)") from None
        if net.version != 4:
            raise Refused(f"TB_DEMO_ALLOW: '{item}' is IPv6; the demo VM's network is IPv4 only")
        if net.prefixlen == 0:
            raise Refused(
                f"TB_DEMO_ALLOW: 0.0.0.0/0 is the whole internet; to open the demo to every address write the word "
                f"{OPEN_WORD} alone (the sign-in password is then the only gate)"
            )
        if net.prefixlen < min_prefix:
            raise Refused(
                f"TB_DEMO_ALLOW: '{item}' is broader than /{min_prefix} (TB_DEMO_VM_MIN_PREFIX); "
                "a home or office range is /24 or narrower"
            )
        if not net.is_global:
            raise Refused(
                f"TB_DEMO_ALLOW: '{item}' is not a public range (the guest's browser comes from the internet)"
            )
        if str(net) not in out:
            out.append(str(net))
    return tuple(out)


def refuse_real_model(env: Mapping[str, str]) -> None:
    """The demo runs the stub model only; a real-model setting in the operator's environment is refused, not ignored
    (the VM never passes the operator's environment on: its container's settings are fixed by demo-vm-boot.sh)."""
    mode = (env.get("TB_LLM_MODE") or "").strip()
    if mode and mode != "stub":
        raise Refused(f"TB_LLM_MODE={mode}: the demo VM runs the stub model only (no real-model mode); unset it")


def load(env: Mapping[str, str], cmd: str) -> Settings:
    refuse_real_model(env)
    if (env.get("TB_DEMO_VM_HOST") or "").strip():
        raise Refused(
            "TB_DEMO_VM_HOST: a publicly trusted certificate is not built. With the address lock ACME's HTTP-01 and "
            "TLS-ALPN-01 cannot pass, and with TB_DEMO_ALLOW=any TLS-ALPN-01 would still need a DNS name for the "
            "VM's address; DNS-01 needs the DNS provider's credential and a Caddy built with that provider. Unset "
            "it: the default is Caddy's own certificate (the browser warns once)"
        )
    name = (env.get("TB_DEMO_VM_NAME") or "tb-demo-vm").strip()
    if not NAME_RE.fullmatch(name):
        raise Refused(f"TB_DEMO_VM_NAME must be a short lower-case name (got '{name}')")
    network = (env.get("TB_DEMO_VM_NETWORK") or "default").strip()
    if network not in NETWORKS:
        raise Refused("TB_DEMO_VM_NETWORK must be default (the project's network) or own (needs networkAdmin)")
    zone = (env.get("TB_DEMO_VM_ZONE") or "asia-east1-a").strip()
    if not ZONE_RE.fullmatch(zone):
        raise Refused(f"TB_DEMO_VM_ZONE is not a zone name (got '{zone}')")
    machine = (env.get("TB_DEMO_VM_MACHINE") or DEFAULT_MACHINE).strip()
    if not MACHINE_RE.fullmatch(machine):
        raise Refused(f"TB_DEMO_VM_MACHINE is not a machine type (got '{machine}')")
    if machine.startswith(GPU_FAMILIES):
        raise Refused(f"TB_DEMO_VM_MACHINE={machine} is an accelerator machine; the demo VM never has a GPU")
    price_given = bool((env.get("TB_DEMO_VM_PRICE_HOUR") or "").strip())
    if machine != DEFAULT_MACHINE and not price_given:
        raise Refused(
            f"no declared price for {machine}: set TB_DEMO_VM_PRICE_HOUR (with TB_DEMO_VM_PRICE_SOURCE and "
            "TB_DEMO_VM_PRICE_DATE) from cloud.google.com/compute/vm-instance-pricing"
        )
    min_prefix = _int(env, "TB_DEMO_VM_MIN_PREFIX", "16", 1)
    if min_prefix > 32:
        raise Refused("TB_DEMO_VM_MIN_PREFIX must be from 1 to 32")
    allow: tuple[str, ...] = ()
    if cmd in ("up", "dry"):
        allow = parse_allow(env.get("TB_DEMO_ALLOW") or "", min_prefix)
    image = (env.get("TB_DEMO_VM_IMAGE") or "").strip()
    sha = (env.get("TB_DEMO_VM_IMAGE_SHA256") or "").strip().lower()
    if cmd in ("up", "dry"):
        if not image and cmd == "up":
            raise Refused(
                "TB_DEMO_VM_IMAGE is not set: REGISTRY/PATH@sha256:<digest>, or gs://BUCKET/trialbox-demo.tar.gz "
                "(make demo-bundle) with TB_DEMO_VM_IMAGE_SHA256"
            )
        if image and not (DIGEST_RE.fullmatch(image) or GS_RE.fullmatch(image)):
            raise Refused(f"TB_DEMO_VM_IMAGE must be an image by digest or a gs:// .tar.gz (got '{image}')")
        if image.startswith("gs://") and not SHA_RE.fullmatch(sha):
            raise Refused("TB_DEMO_VM_IMAGE is a gs:// tarball: set TB_DEMO_VM_IMAGE_SHA256 (sha256sum of the file)")
    people = parse_people(env.get("TB_DEMO_VM_PEOPLE") or DEFAULT_PEOPLE)
    enrol_hours = _int(env, "TB_DEMO_VM_ENROL_HOURS", "24", 1)
    if enrol_hours > 72:
        raise Refused("TB_DEMO_VM_ENROL_HOURS must be from 1 to 72 (the product's range, TB_CONSOLE_ENROL_CODE_HOURS)")
    bucket = (env.get("TB_BUCKET") or "").strip().rstrip("/")
    handoff = (env.get("TB_DEMO_VM_HANDOFF") or (f"{bucket}/demo-vm" if bucket else "")).strip().rstrip("/")
    if cmd in ("up", "dry", "links") and not HANDOFF_RE.fullmatch(handoff):
        if cmd == "dry" and not handoff:
            handoff = "gs://<TB_BUCKET>/demo-vm"
        else:
            raise Refused(
                "TB_DEMO_VM_HANDOFF (or TB_BUCKET) must name a private gs://BUCKET[/PATH] where the VM's service "
                f"account may write (got '{handoff}'): the people's one-time codes go there, and only there"
            )
    lang = (env.get("TB_DEMO_LANG") or "ja").strip()
    site_lang = (env.get("TB_DEMO_SITE_LANG") or "").strip()
    if lang not in LANGS:
        raise Refused(f"TB_DEMO_LANG must be one of {', '.join(LANGS)}")
    if site_lang and site_lang not in ("ja", "zh-TW"):
        raise Refused("TB_DEMO_SITE_LANG must be ja or zh-TW (or unset: both campuses)")
    return Settings(
        name=name,
        network=network,
        zone=zone,
        region=zone.rsplit("-", 1)[0],
        machine=machine,
        disk_gb=_int(env, "TB_DEMO_VM_DISK_GB", "30", MIN_DISK_GB),
        hours=_int(env, "TB_DEMO_VM_HOURS", "12", 1),
        min_prefix=min_prefix,
        allow=allow,
        open_any=allow == (WORLD,),
        image=image,
        image_sha256=sha,
        people=people,
        enrol_hours=enrol_hours,
        handoff=handoff,
        lang=lang,
        site_lang=site_lang,
        stop_wait_s=_int(env, "TB_DEMO_VM_STOP_WAIT_S", "300", 10),
        # e2-standard-4 in asia-east1, on demand: the figure poc-host.sh `cost` and the runbook already use (US$0.15
        # an hour, from memory); the disk is pd-balanced in asia-east1; an in-use external IPv4 address since 2024
        price_hour=_price(env, "TB_DEMO_VM_PRICE_HOUR", "0.1528"),
        disk_price_gb_month=_price(env, "TB_DEMO_VM_DISK_PRICE_GB_MONTH", "0.11"),
        ip_price_hour=_price(env, "TB_DEMO_VM_IP_PRICE_HOUR", "0.005"),
        price_source=(env.get("TB_DEMO_VM_PRICE_SOURCE") or "").strip()
        or "list prices as used in deploy/gcp/poc-host.sh cost (from memory; not checked against the pricing page)",
        price_date=(env.get("TB_DEMO_VM_PRICE_DATE") or "").strip() or "2026-11-13 (unchecked)",
    )


@dataclass(frozen=True)
class Estimate:
    running_hour: float  # VM + disk + address, while RUNNING
    stopped_hour: float  # the disk only, while TERMINATED (the address is released at the stop)
    disk_hour: float
    per_up: float  # one `up` that runs until its hard stop

    def running(self, hours: float) -> float:
        return self.running_hour * hours

    def stopped(self, hours: float) -> float:
        return self.stopped_hour * hours


def estimate(s: Settings) -> Estimate:
    disk_hour = s.disk_gb * s.disk_price_gb_month / HOURS_PER_MONTH
    running = s.price_hour + disk_hour + s.ip_price_hour
    return Estimate(running_hour=running, stopped_hour=disk_hour, disk_hour=disk_hour, per_up=running * s.hours)


def estimate_text(s: Settings) -> str:
    e = estimate(s)
    lines = [
        f"Demo VM {s.name}: {s.machine} in {s.zone}, no GPU, stub model, synthetic data only",
        f"  disk                {s.disk_gb} GB pd-balanced (Debian 12), deleted with the VM",
        f"  hard stop           {s.hours} h after each `up` (TB_DEMO_VM_HOURS): the VM powers itself off, and "
        "Compute Engine stops it at the same time",
        f"  prices (US$)        VM {s.price_hour:.4f}/h; disk {s.disk_price_gb_month:.3f}/GB-month; "
        f"external IPv4 {s.ip_price_hour:.4f}/h",
        f"  price source        {s.price_source}",
        f"  price date          {s.price_date}",
        "  cost while RUNNING (VM + disk + address):",
        f"    per hour          US$ {e.running_hour:8.4f}",
        f"    per day (24 h)    US$ {e.running(HOURS_PER_DAY):8.2f}",
        f"    per week (168 h)  US$ {e.running(HOURS_PER_WEEK):8.2f}   (cannot happen by itself: the hard stop ends "
        f"each `up` after {s.hours} h)",
        f"  one `up` until its hard stop: at most US$ {e.per_up:.2f}",
        "  cost while TERMINATED (after `down` or the hard stop; the disk only):",
        f"    per day           US$ {e.stopped(HOURS_PER_DAY):8.2f}",
        f"    per week          US$ {e.stopped(HOURS_PER_WEEK):8.2f}   (`delete` ends it)",
        "  not counted: egress (a demo is a few hundred MB, cents), the codes' object in the bucket (bytes), "
        "Artifact Registry or the bucket that holds the image (cents a month)",
        "  TLS: Caddy's own certificate (tls internal): the browser WARNS ONCE per device; a publicly trusted",
        "       certificate is not built (it needs DNS-01 and the DNS provider's credential)",
        "  prices change: check cloud.google.com/compute/vm-instance-pricing and set TB_DEMO_VM_PRICE_* before `up`",
    ]
    return "\n".join(lines)


def shell_lines(s: Settings) -> str:
    """The checked settings as shell assignments (every value shlex-quoted) for demo-vm.sh."""
    pairs = {
        "N": s.name,
        "NETWORK": s.network,
        "ALLOW_PRIORITY": str(ALLOW_PRIORITY),
        "DENY_PRIORITY": str(DENY_PRIORITY),
        "ZONE": s.zone,
        "REGION": s.region,
        "MACHINE": s.machine,
        "DISK_GB": str(s.disk_gb),
        "HOURS": str(s.hours),
        "ALLOW": ",".join(s.allow),
        "OPEN_ANY": "1" if s.open_any else "0",
        "GATE": OPEN_TEXT if s.open_any else "",
        "IMAGE": s.image,
        "IMAGE_SHA256": s.image_sha256,
        "PEOPLE": s.people,
        "ENROL_HOURS": str(s.enrol_hours),
        "HANDOFF": s.handoff,
        "DEMO_LANG": s.lang,
        "SITE_LANG": s.site_lang,
        "STOP_WAIT_S": str(s.stop_wait_s),
    }
    return "\n".join(f"{k}={shlex.quote(v)}" for k, v in pairs.items())


def reaching_rules(
    rules: list[dict[str, object]], network: str, mode: str, ours: tuple[str, ...], tag: str
) -> list[str]:
    """The names of the ingress rules on ``network`` that could let traffic reach the VM besides ``ours``. On its own
    network (``own``) that is every other rule. On ``default`` an enabled allow rule that applies to the VM (no target,
    the VM's tag, or a service account target, which may be the VM's) and is not beaten by the VM's deny (priority below
    DENY_PRIORITY; at equal priority the deny wins)."""
    out: list[str] = []
    for r in rules:
        name = str(r.get("name") or "")
        if name in ours or not str(r.get("network") or "").rstrip("/").endswith(f"/{network}"):
            continue
        if str(r.get("direction") or "INGRESS") != "INGRESS" or r.get("disabled") is True:
            continue
        if mode == "own":
            out.append(name)
            continue
        tags = r.get("targetTags") or []
        accounts = r.get("targetServiceAccounts") or []
        applies = (not tags and not accounts) or (isinstance(tags, list) and tag in tags) or bool(accounts)
        priority = r.get("priority", 1000)
        if r.get("allowed") and applies and isinstance(priority, int | str) and int(priority) < DENY_PRIORITY:
            out.append(name)
    return out


# The boot's own lines on the serial console. Compute Engine's script runner echoes each with its prefix
# ("<time> <vm> google_metadata_script_runner[<pid>]: Metadata key(...), command(...): TB-DEMO-VM ..."); the boot's tee
# to /dev/ttyS0 writes some bare. Both are read; the same line twice is shown once.
BOOT_LINE_RE = re.compile(r"(TB-DEMO-VM [0-9]{2}:[0-9]{2}:[0-9]{2} .*|TB-DEMO-VM refused: .*|DEMO-VM-[A-Z-]+)\s*$")
BOOT_START = "hard stop: this VM powers off"  # the first line of every boot (demo-vm-boot.sh)
BOOT_MARKERS = ("DEMO-VM-READY", "DEMO-VM-NOT-READY")


def boot_state(serial: str, keep: int = 8) -> tuple[str, list[str]]:
    """The last boot's state from the serial console's text: ``ready``, ``not-ready``, ``refused`` or ``running``
    (no marker yet; the seed takes minutes), with its last ``keep`` lines (the boot never writes a code or a
    password)."""
    lines: list[str] = []
    for raw in serial.replace("\r", "").splitlines():
        m = BOOT_LINE_RE.search(raw)
        if not m:
            continue
        line = m.group(1).strip()
        if BOOT_START in line:
            lines = []  # a new boot: the earlier one's lines are not this one's
        if not lines or lines[-1] != line:
            lines.append(line)
    state = "running"
    for line in lines:
        if line == "DEMO-VM-READY":
            state = "ready"
        elif line == "DEMO-VM-NOT-READY":
            state = "not-ready"
        elif line.startswith("TB-DEMO-VM refused:"):
            state = "refused"
    return state, lines[-keep:]


BOOT_STATE_TEXT = {
    "ready": "boot: DEMO-VM-READY (the demo answers; `links` hands out the one-time codes)",
    "not-ready": "boot: DEMO-VM-NOT-READY (the lines above say why; `down` then `up --yes` boots it again)",
    "refused": "boot: refused (the lines above say why; nothing listens on tcp:443)",
    "running": "boot: not ready yet (no DEMO-VM-READY marker; the seed takes about 5 to 10 minutes; run status again)",
}


def main(argv: list[str], env: Mapping[str, str]) -> int:
    if argv and argv[0] == "boot-state" and len(argv) == 1:
        state, lines = boot_state(sys.stdin.read())
        for line in lines:
            print(f"  {line}")
        print(BOOT_STATE_TEXT[state])
        return 0
    if argv and argv[0] == "rules-check" and len(argv) == 6:
        import json

        _, network, mode, rule, deny, tag = argv
        bad = reaching_rules(json.load(sys.stdin) or [], network, mode, (rule, deny), tag)
        if bad:
            print(" ".join(bad))
            return 3
        return 0
    if not argv or argv[0] not in ("estimate", "shell"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if argv[0] == "estimate":
            print(estimate_text(load(env, "estimate")))
            return 0
        cmd = argv[1] if len(argv) > 1 else ""
        if cmd not in ("up", "status", "down", "delete", "dry", "links"):
            print("shell: up, status, down, delete, dry or links", file=sys.stderr)
            return 2
        print(shell_lines(load(env, cmd)))
        return 0
    except Refused as e:
        print(f"demo-vm: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
