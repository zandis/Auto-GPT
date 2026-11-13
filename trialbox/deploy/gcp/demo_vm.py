"""The settings, checks and cost estimate of the small demo VM (deploy/gcp/demo-vm.sh; docs/runbook/11-cloud-runs.md).

Standard library only: the operator's host runs it with any Python 3.10+, before any gcloud call.

    python3 deploy/gcp/demo_vm.py estimate          the machine, US$ per hour, day and week, the disk, the sources
    python3 deploy/gcp/demo_vm.py shell up|status|down|delete|dry
                                                    the checked settings as shell assignments (shlex-quoted) for
                                                    demo-vm.sh; a refused setting exits 2 with the reason

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
    TB_DEMO_ALLOW         (required)      the only source ranges of tcp:443, comma separated (1.2.3.4/32,5.6.7.8/32)
    TB_DEMO_VM_IMAGE      (up)            REGISTRY/PATH@sha256:<64 hex>, or gs://BUCKET/trialbox-demo.tar.gz
                                          (`make demo-bundle`) with TB_DEMO_VM_IMAGE_SHA256, checked on the VM
    TB_DEMO_VM_SECRET     tb-demo-password  the Secret Manager secret that holds the demo password (setup-gcp.sh)
    TB_DEMO_VM_HOST       (not built)     a DNS name for a publicly trusted certificate: refused (see below)
    TB_DEMO_VM_STOP_WAIT_S 300            `down`: how long to wait for TERMINATED after the stop returned; an e2 VM
                                          stops in under a minute, five times that means it is stuck
    prices                                TB_DEMO_VM_PRICE_HOUR, TB_DEMO_VM_DISK_PRICE_GB_MONTH,
                                          TB_DEMO_VM_IP_PRICE_HOUR, with TB_DEMO_VM_PRICE_SOURCE and _DATE: list
                                          prices change, so they are settings with their source and date, never
                                          constants; a machine other than e2-standard-4 needs its own hourly price

TLS: Caddy in front with `tls internal` (its own CA): the browser warns once per device. A publicly trusted
certificate for a DNS name would need ACME, and with tcp:80 and tcp:443 closed to the world HTTP-01 and TLS-ALPN-01
cannot pass; DNS-01 needs the DNS provider's credential and a Caddy built with that provider. Not built.
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


class Refused(Exception):
    """A setting the demo VM must not run with; the message says which and why (never a secret value)."""


@dataclass(frozen=True)
class Settings:
    name: str
    zone: str
    region: str
    machine: str
    disk_gb: int
    hours: int
    min_prefix: int
    allow: tuple[str, ...]
    image: str
    image_sha256: str
    secret: str
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


def parse_allow(raw: str, min_prefix: int) -> tuple[str, ...]:
    """The source ranges of the tcp:443 rule: IPv4 networks, each at least /min_prefix; never the world, never none."""
    items = [x.strip() for x in raw.split(",") if x.strip()]
    if not items:
        raise Refused("TB_DEMO_ALLOW is empty: name the owner's and the guest's addresses (1.2.3.4/32,5.6.7.8/32)")
    out: list[str] = []
    for item in items:
        try:
            net = ipaddress.ip_network(item if "/" in item else f"{item}/32", strict=True)
        except ValueError:
            raise Refused(f"TB_DEMO_ALLOW: '{item}' is not an IPv4 address or network (host bits set?)") from None
        if net.version != 4:
            raise Refused(f"TB_DEMO_ALLOW: '{item}' is IPv6; the demo VM's network is IPv4 only")
        if net.prefixlen == 0:
            raise Refused("TB_DEMO_ALLOW: 0.0.0.0/0 is the whole internet; the demo is for two people only")
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
            "TB_DEMO_VM_HOST: a publicly trusted certificate is not built. With tcp:80 and tcp:443 closed to the "
            "world, ACME's HTTP-01 and TLS-ALPN-01 cannot pass; DNS-01 needs the DNS provider's credential and a "
            "Caddy built with that provider. Unset it: the default is Caddy's own certificate (the browser warns once)"
        )
    name = (env.get("TB_DEMO_VM_NAME") or "tb-demo-vm").strip()
    if not NAME_RE.fullmatch(name):
        raise Refused(f"TB_DEMO_VM_NAME must be a short lower-case name (got '{name}')")
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
    secret = (env.get("TB_DEMO_VM_SECRET") or "tb-demo-password").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", secret):
        raise Refused("TB_DEMO_VM_SECRET must be a Secret Manager secret name")
    lang = (env.get("TB_DEMO_LANG") or "ja").strip()
    site_lang = (env.get("TB_DEMO_SITE_LANG") or "").strip()
    if lang not in LANGS:
        raise Refused(f"TB_DEMO_LANG must be one of {', '.join(LANGS)}")
    if site_lang and site_lang not in ("ja", "zh-TW"):
        raise Refused("TB_DEMO_SITE_LANG must be ja or zh-TW (or unset: both campuses)")
    return Settings(
        name=name,
        zone=zone,
        region=zone.rsplit("-", 1)[0],
        machine=machine,
        disk_gb=_int(env, "TB_DEMO_VM_DISK_GB", "30", MIN_DISK_GB),
        hours=_int(env, "TB_DEMO_VM_HOURS", "12", 1),
        min_prefix=min_prefix,
        allow=allow,
        image=image,
        image_sha256=sha,
        secret=secret,
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
        "  not counted: egress (a demo is a few hundred MB, cents), Secret Manager (one secret version, cents), "
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
        "ZONE": s.zone,
        "REGION": s.region,
        "MACHINE": s.machine,
        "DISK_GB": str(s.disk_gb),
        "HOURS": str(s.hours),
        "ALLOW": ",".join(s.allow),
        "IMAGE": s.image,
        "IMAGE_SHA256": s.image_sha256,
        "SECRET": s.secret,
        "DEMO_LANG": s.lang,
        "SITE_LANG": s.site_lang,
        "STOP_WAIT_S": str(s.stop_wait_s),
    }
    return "\n".join(f"{k}={shlex.quote(v)}" for k, v in pairs.items())


def main(argv: list[str], env: Mapping[str, str]) -> int:
    if not argv or argv[0] not in ("estimate", "shell"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if argv[0] == "estimate":
            print(estimate_text(load(env, "estimate")))
            return 0
        cmd = argv[1] if len(argv) > 1 else ""
        if cmd not in ("up", "status", "down", "delete", "dry"):
            print("shell: up, status, down, delete or dry", file=sys.stderr)
            return 2
        print(shell_lines(load(env, cmd)))
        return 0
    except Refused as e:
        print(f"demo-vm: refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ))
