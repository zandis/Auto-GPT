"""The box's settings from the owner's answers and the detected hardware (T-729, D-466; plan v6.1 OD-10, OD-11, OD-13).

One function, :func:`plan`, turns :class:`tb_common.box_answers.OwnerAnswers` plus a :class:`Hardware` description
into everything ``deploy/install.sh`` needs to install a box with no further question:

* the answers file of ``tools.settings_wizard`` (``wizard_answers``): the site from the owner's answers, the mail
  and sender lists from the owner's own address, TLS in ``internal`` mode under the box's name, the data source of
  the kind the owner chose (its connector and mapping are T-731's; until then a site mapping that only states the
  site's zone), ClinicalTrials.gov offline;
* the ``deploy/.env`` lines the wizard does not write (``env_extra``): the memory cap of every service from the RAM
  (OD-10: the compose files' own defaults are the proportions, the machine's RAM is the size), the backup target
  (a second disk or a share) and who is told when it fails;
* the install's own flags (``install_args``): the GPU profile from the card (``deploy/gpu_profile.sh``, the one
  rule) and the model mode;
* the site files (``files``): ``site/hardening.conf`` with the KEK back end (``tpm`` where the board has one, else
  ``passphrase``: the owner sets it in the wizard; Tang is the IT-managed form, T-634) and the input firewall opened
  to the box's own network (derived from its address, never asked), and the site mapping.

Nothing here asks a question, and nothing here needs more than the standard library: the installer runs it with the
host's ``python3`` before any image is loaded. :func:`detect` reads the machine (``nvidia-smi``, ``/proc``,
``lsblk``, ``ip``); every other function is pure.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tb_common import host_zone, site_country, site_needs
from tb_common.box_answers import BackupKind, OwnerAnswers, SourceKind, person_name, stand_ins

from tools.trialbox import memcaps

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
PAIR_PROFILES = ("rtxpro6000", "gb10", "rtx5090")  # judge and verifier (D-124)
WORKSTATION_PROFILES = ("rtxpro6000", "rtx5090", "rtx4090", "default")
REFUSED_PROFILES = ("shared-quota", "b200-no-mig")  # install.sh refuses them: a platform, not a box (D-211, D-409)
# card 10E-5 (D-1335): a DGX Spark under 96 GiB (gb10-64) is planned as a stub box, as install.sh refuses its GPU mode
SMALL_SPARK = (
    "this DGX Spark has under 96 GiB of memory (the 64 GB class): TrialBox does not serve the model pair on it (the "
    "gb10 profile is sized for 128 GB and no 64 GB profile is measured), so the box is planned without a model: "
    "structured criteria only"
)
# where the box keeps its backups and its first-run answers; the folders are the box's own, never the owner's choice
SECOND_DISK_MOUNT = "/srv/trialbox-backup"
SHARE_MOUNT = "/mnt/trialbox-share"
FIRSTRUN_DIR = "/run/trialbox-firstrun"  # tmpfs: the answers (and a passphrase) never reach a disk
BOX_MAPPING = "mapping/tw_core/box_site.yaml"
PROVISIONAL_MAIL = "owner@box.invalid"
SAMPLE_FEED = "./site/sample"  # M1: the sample hospital (synthetic, tools/site_seed.py)
SHIPPED_DEPARTMENTS = "shipped"  # the wizard reads the shipped list (M2's): it is in the image, not on the host
BOX_SOURCE_MOUNT = "/data/source/site"  # where compose mounts the feed folder, read-only (TB_SOURCE_MOUNT)
# OD-10: below half of the compose files' own caps the services were never measured: such a machine is refused
MIN_SERVICE_SHARE = 0.5
_MEM = re.compile(r"mem_limit:\s*(?:\$\{(TB_MEM_[A-Z_]+):-([0-9.]+[mgMG])\}|([0-9.]+[mgMG]))")


@dataclass(frozen=True)
class Disk:
    path: str  # /dev/sdb
    size_gib: float
    transport: str = ""  # usb, nvme, sata
    mounted: str = ""  # its mount point, if any


@dataclass(frozen=True)
class Hardware:
    arch: str
    cpu_count: int
    ram_gib: float
    disk_free_gib: float
    gpu_name: str = ""
    gpu_mem_gib: float = 0.0
    mig: str = ""
    tpm: bool = False
    disks: tuple[Disk, ...] = ()  # disks other than the one the system is on: candidates for backups
    lan: str = ""  # the box's network, CIDR; with IPv6 two, space-separated (192.0.2.0/24 2001:db8::/64), D-629
    hostname: str = "trialbox"
    host_tz: str = ""
    mem_total_kib: int = 0  # /proc/meminfo's MemTotal as read (ram_gib is rounded); 0: unknown (card 10E-5)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Hardware:
        disks = tuple(Disk(**x) for x in d.get("disks") or ())
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "disks"}
        return cls(**known, disks=disks)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BoxPlan:
    profile: str  # deploy/gpu_profile.sh's word
    mode: str  # gpu | stub (install.sh --mode)
    wizard_answers: dict[str, Any]
    env_extra: dict[str, str]
    files: dict[str, str]  # path under deploy/ -> text
    warnings: list[str] = field(default_factory=list)
    stand_ins: frozenset[str] = frozenset()  # M1 (D-1280): items of site_needs the box runs on its own value for

    @property
    def install_args(self) -> list[str]:
        if self.mode == "gpu":
            return ["--mode", "gpu", "--gpu", self.profile]
        return ["--mode", "stub"]


class PlanError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ hardware
def gpu_profile(arch: str, gpu_name: str, mig: str = "", deploy: Path = DEPLOY, mem_kib: int = 0) -> str:
    """deploy/gpu_profile.sh's answer for this machine: one rule, shared with install.sh. ``mem_kib`` is MemTotal in
    kB (0: unknown); a GB10 under 96 GiB is ``gb10-64`` (card 10E-5, D-1335)."""
    if not gpu_name:
        return "none"
    out = subprocess.run(
        ["sh", str(deploy / "gpu_profile.sh"), arch, gpu_name, mig, str(mem_kib) if mem_kib > 0 else ""],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _has_tpm2() -> bool:
    """``systemd-creds has-tpm2``: what seal_keys.sh, check_host.sh and install.sh ask (D-836); False without it."""
    try:
        done = subprocess.run(["systemd-creds", "has-tpm2"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def tpm_usable(host_root: Path = Path("/"), has_tpm2: Callable[[], bool] | None = None) -> bool:
    """D-897: a TPM the KEK can be sealed to: a device node and ``systemd-creds has-tpm2``. A node alone (a vTPM
    without its driver, a TPM 1.2) gave KEK_BACKEND=tpm and a seal step that stopped."""
    if not ((host_root / "dev/tpmrm0").exists() or (host_root / "dev/tpm0").exists()):
        return False
    return (has_tpm2 or _has_tpm2)()


def detect(deploy: Path = DEPLOY, host_root: Path = Path("/")) -> Hardware:  # pragma: no cover - reads the machine
    """This machine, as the wizard and :func:`plan` need it. Read-only."""
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total,mig.mode.current", "--format=csv,noheader,nounits"])
    name, mem, mig = (
        [*[x.strip() for x in gpu.splitlines()[0].split(",")], "", "", ""] if gpu.strip() else ["", "", ""]
    )[:3]
    meminfo = (host_root / "proc/meminfo").read_text(encoding="utf-8") if (host_root / "proc/meminfo").exists() else ""
    kib = re.search(r"MemTotal:\s+(\d+)", meminfo)
    return Hardware(
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        ram_gib=round(int(kib.group(1)) / 1024**2, 1) if kib else 0.0,
        disk_free_gib=round(shutil.disk_usage(deploy).free / 1024**3, 1),
        gpu_name=name,
        gpu_mem_gib=round(float(mem) / 1024, 1) if re.fullmatch(r"[0-9.]+", mem or "") else 0.0,
        mig=mig if mig not in ("[N/A]", "N/A") else "",
        tpm=tpm_usable(host_root),
        disks=parse_lsblk(_run(["lsblk", "-J", "-b", "-o", "PATH,SIZE,TYPE,TRAN,MOUNTPOINT"])),
        lan=clinic_ranges(
            _run(["ip", "-j", "addr", "show", "scope", "global"]),
            _run(["ip", "-j", "route", "show", "default"]),
            _run(["ip", "-j", "-6", "route", "show", "default"]),
        ),
        hostname=socket.gethostname().split(".")[0].lower() or "trialbox",
        host_tz=host_zone.read(host_root),  # the one reading check_host.sh does too
        mem_total_kib=int(kib.group(1)) if kib else 0,
    )


def parse_lsblk(text: str) -> tuple[Disk, ...]:
    """The disks a backup may go to: whole disks, none of whose parts holds the system (/, /boot, /var, swap)."""
    try:
        devices = json.loads(text or "{}").get("blockdevices") or []
    except ValueError:
        return ()
    system = ("/", "/boot", "/boot/efi", "/var", "/usr", "[SWAP]")

    def mounts(d: dict[str, Any]) -> list[str]:
        own = [d["mountpoint"]] if d.get("mountpoint") else []
        return own + [m for c in d.get("children") or () for m in mounts(c)]

    out = []
    for d in devices:
        if d.get("type") != "disk" or any(m in system for m in mounts(d)):
            continue
        out.append(Disk(str(d.get("path") or ""), round(int(d.get("size") or 0) / 1024**3, 1),
                        str(d.get("tran") or ""), ",".join(mounts(d))))  # fmt: skip
    return tuple(x for x in out if x.path)


#: D-629: never the clinic's network: a bridge of a container or VM tool, a tunnel
_BRIDGES = ("docker", "br-", "veth", "virbr", "cni", "podman", "lxcbr", "lxdbr", "incusbr", "vboxnet", "vmnet")
_TUNNELS = ("tun", "tap", "wg", "ppp", "tailscale", "zt", "utun", "ipsec")
#: the IPv4 networks a site uses inside (RFC 1918), and the three of RFC 5737 that the examples and the tests use
#: (never routed). A public network, carrier-grade NAT (100.64.0.0/10) and everything else is not written (D-629)
_SITE_V4 = tuple(
    ipaddress.IPv4Network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
#: IPv6 that is local by its prefix: unique local addresses, and the documentation prefix of the examples
_SITE_V6 = (ipaddress.IPv6Network("fc00::/7"), ipaddress.IPv6Network("2001:db8::/32"))
MIN_PREFIX_V4, MIN_PREFIX_V6 = 16, 48  # nothing wider than a site's network is ever written
#: the plan's warning when no network could be told (D-629)
LAN_UNKNOWN = (
    "network: the clinic's network could not be told from this machine (no private network on the card the "
    "default route uses, or no default route and not exactly one network card): CLINIC_RANGES in "
    "deploy/site/hardening.conf is the box itself, so port 443 answers nobody else until the range is written there"
)


def _json_list(text: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(text or "[]")
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _networks(link: dict[str, Any]) -> list[str]:
    """The networks of one interface that could be the clinic's (D-629). None for a loopback interface, a bridge of
    a container or VM tool, or a tunnel. Of its addresses: IPv4 only a site's private network, /16 or narrower;
    IPv6 /48 or narrower, and only a prefix that is local by itself or one beside a private IPv4 network on the
    same card (the same segment); never a loopback, link-local, multicast or host (/32, /128) address."""
    name = link.get("ifname")
    flags = link.get("flags")
    flags = {str(f) for f in flags} if isinstance(flags, list) else set()
    if (
        not isinstance(name, str)
        or name == "lo"
        or name.startswith((*_BRIDGES, *_TUNNELS))
        or flags & {"LOOPBACK", "POINTOPOINT"}
        or link.get("link_type") == "loopback"
    ):
        return []
    v4: list[str] = []
    v6: list[tuple[str, bool]] = []
    info = link.get("addr_info")
    for a in info if isinstance(info, list) else ():
        if not isinstance(a, dict) or a.get("family") not in ("inet", "inet6") or not isinstance(a.get("local"), str):
            continue
        try:
            ifc = ipaddress.ip_interface(f"{a['local']}/{int(a['prefixlen'])}")
        except (KeyError, TypeError, ValueError):
            continue
        net, ip = ifc.network, ifc.ip
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            continue
        if net.prefixlen == ip.max_prefixlen:
            continue
        if isinstance(net, ipaddress.IPv4Network):
            if net.prefixlen >= MIN_PREFIX_V4 and any(net.subnet_of(s) for s in _SITE_V4) and str(net) not in v4:
                v4.append(str(net))
        elif (
            isinstance(net, ipaddress.IPv6Network)
            and net.prefixlen >= MIN_PREFIX_V6
            and str(net) not in [n for n, _ in v6]
        ):
            v6.append((str(net), any(net.subnet_of(s) for s in _SITE_V6)))
    return v4 + [n for n, local in v6 if local or v4]


def _route_devs(routes: str) -> list[str]:
    """The interfaces of the default routes, lowest metric first; a route with several next hops gives each."""
    rows = []
    for r in _json_list(routes):
        if r.get("dst") not in ("default", "0.0.0.0/0", "::/0"):
            continue
        try:
            metric = int(r.get("metric") or 0)
        except (TypeError, ValueError):
            metric = 0
        hops = r.get("nexthops")
        devs = [r.get("dev"), *(h.get("dev") for h in (hops if isinstance(hops, list) else ()) if isinstance(h, dict))]
        rows += [(metric, d) for d in devs if isinstance(d, str)]
    return [d for _, d in sorted(rows, key=lambda x: x[0])]


def clinic_ranges(addrs: str, routes4: str = "", routes6: str = "") -> str:
    """The box's network for ``CLINIC_RANGES`` (who reaches port 443), from ``ip -j addr show scope global`` and
    ``ip -j [-6] route show default`` (D-629): the networks (see :func:`_networks`) of the interface the default
    route uses, lowest metric first, IPv4's route before IPv6's. A route through an interface that has no such
    network (a tunnel, a public uplink) is passed over. With no route to go by, the one interface that could be the
    clinic's; with several, or none, the empty string: it decides who reaches the console, so it is not guessed.
    Never raises: text that is not what ``ip`` prints gives the empty string."""
    nets: dict[str, list[str]] = {}
    for link in _json_list(addrs):
        found = _networks(link)
        if found:
            nets[str(link["ifname"])] = found
    for routes in (routes4, routes6):
        for dev in _route_devs(routes):
            if dev in nets:
                return " ".join(nets[dev])
    return " ".join(next(iter(nets.values()))) if len(nets) == 1 else ""


def parse_ip(text: str, routes4: str = "", routes6: str = "") -> str:
    """The name from before D-629; see :func:`clinic_ranges`."""
    return clinic_ranges(text, routes4, routes6)


# ------------------------------------------------------------------------------------------------ memory (OD-10)
def _gib(v: str) -> float:
    n = float(v[:-1])
    return n if v[-1] in "gG" else n / 1024


def compose_caps(files: list[Path]) -> tuple[dict[str, float], float]:
    """(each ``TB_MEM_<NAME>`` with its default in GiB, the sum of the literal caps) over these compose files; a later
    file's default of the same variable wins, as compose reads them."""
    var: dict[str, float] = {}
    fixed = 0.0
    for f in files:
        for m in _MEM.finditer(f.read_text(encoding="utf-8")):
            if m.group(1):
                var[m.group(1)] = _gib(m.group(2))
            else:
                fixed += _gib(m.group(3))
    return var, fixed


def memory_caps(
    ram_gib: float, profile: str, deploy: Path = DEPLOY, patients: int = 0
) -> tuple[dict[str, str], list[str]]:
    """``TB_MEM_*`` for this machine (OD-10): no cap is a constant. The compose files' defaults give each service's
    share; the RAM, less what the system keeps (a tenth, at least 4 GiB) and the fixed small caps, is shared out in
    those proportions. When the defaults do not fit, every cap shrinks by the same factor, and a machine where that
    factor falls below :data:`MIN_SERVICE_SHARE` is refused (:class:`PlanError`: the services were never measured
    there). When they fit with room to spare, the services grow into it (the lake and the database use it) and the
    model servers keep their default (their weights are on the card; more host memory does not serve them faster).
    The Spark (``gb10``) is one machine: its profile (``deploy/gb10-profile.yaml``) is its caps, so nothing is
    derived for it.

    E2E P-02: then each cap of a service in the measured-peak table holds 1.5 times its peak for a hospital of
    ``patients`` (``TB_SITE_PATIENTS``; not given: the smallest measured class), as :func:`measured_floors` says."""
    if profile == "gb10":
        return {}, []
    files = [deploy / "docker-compose.yml", deploy / "docker-compose.identity.yml"]
    # dgpu48: the UNMEASURED 48 GB draft (card 24-5): arithmetic only, never detected, refused by install.sh
    overlay = {"rtxpro6000": "rtxpro6000", "rtx5090": "rtx5090", "rtx4090": "rtx5090", "dgpu48": "dgpu48"}.get(profile)
    if overlay:
        files.append(deploy / f"docker-compose.{overlay}.yml")
    var, fixed = compose_caps(files)
    models = {"TB_MEM_LLM", "TB_MEM_VERIFIER"}
    if profile in ("none", "stub"):
        running: set[str] = set()
    elif profile in ("rtx4090", "default"):
        running = {"TB_MEM_LLM"}
    else:
        running = models
    svc = {k: v for k, v in var.items() if k not in models}
    mod = {k: v for k, v in var.items() if k in running}
    reserve = max(4.0, ram_gib / 10)
    avail = ram_gib - reserve - fixed
    total = sum(svc.values()) + sum(mod.values())
    factor = avail / total
    if factor < MIN_SERVICE_SHARE:
        least = reserve + fixed + total * MIN_SERVICE_SHARE
        raise PlanError(
            f"this machine has {ram_gib:g} GiB of memory; TrialBox needs at least {least:.0f} GiB with this GPU profile"
        )
    if factor <= 1:
        caps = {k: v * factor for k, v in (svc | mod).items()}
    else:  # room to spare: the models keep their default, the services share the rest
        rest = avail - sum(mod.values())
        caps = {k: v * rest / sum(svc.values()) for k, v in svc.items()} | mod
    notes = [f"memory: {ram_gib:g} GiB, {reserve:g} GiB kept for the system, the caps at {factor:.2f} of the defaults"]
    caps, said = measured_floors(caps, var, *site_floors(deploy, patients))
    return {k: f"{int(v * 1024 + 1e-6)}m" for k, v in sorted(caps.items())}, notes + said


def site_floors(deploy: Path, patients: int) -> tuple[dict[str, float], int, list[str]]:
    """E2E P-02: ``(HEADROOM times each measured peak in GiB, the hospital's size, notes)`` from the measured-peak table
    (``deploy/measured/site_peaks.json``) for ``patients``, the nearest larger size class (not given: the smallest
    class); none without the table."""
    peaks = memcaps.load_peaks(deploy / "measured" / memcaps.PEAKS_NAME)
    if not peaks:
        return {}, 0, []
    n = patients or peaks[0][0]
    said = []
    if n > peaks[-1][0]:
        said.append(
            f"memory: {n:,} patients is above the largest measured size ({peaks[-1][0]:,}): the caps follow the line "
            "through the measured peaks; measure a night at this size (tools/scale_gate.py)"
        )
    names = sorted({k for _, row in peaks for k in row})
    return {k: math.ceil(memcaps.HEADROOM * memcaps.peak_mib(peaks, k, n)) / 1024 for k in names}, n, said


def measured_floors(
    caps: dict[str, float], defaults: dict[str, float], floor: dict[str, float], n: int, said: list[str]
) -> tuple[dict[str, float], list[str]]:
    """E2E P-02: a cap below its ``floor`` (HEADROOM times the measured peak for a hospital of ``n`` patients) is
    raised to it, the other caps giving the same memory back from what each has above its own lowest (its floor, and
    :data:`MIN_SERVICE_SHARE` of its default), in proportion to that surplus, so the total stays what the machine has.
    When the surplus of all of them is less than what is missing, the caps stay as they were and a note says so: the
    machine's caps do not hold a hospital of that size (``(caps, notes)``, in GiB)."""
    floor = {k: f for k, f in floor.items() if k in caps}
    short = {k: floor[k] - caps[k] for k in floor if caps[k] < floor[k]}
    if not short:
        return caps, said
    spare = {k: caps[k] - max(MIN_SERVICE_SHARE * defaults[k], floor.get(k, 0.0)) for k in caps if k not in short}
    spare = {k: v for k, v in spare.items() if v > 0}
    if sum(short.values()) <= sum(spare.values()):
        take = sum(short.values()) / sum(spare.values())
        return {k: caps[k] + short.get(k, 0.0) - spare.get(k, 0.0) * take for k in caps}, said
    under = ", ".join(f"{k} {int(caps[k] * 1024)}m < {int(floor[k] * 1024)}m" for k in sorted(short))
    return caps, [
        *said,
        f"memory: {under} ({memcaps.HEADROOM:g} x the measured peak for {n:,} patients): this machine's caps do not "
        "hold a night or a SCREEN of a hospital that size; the service is killed at its cap (E2E P-02)",
    ]


def site_patients(deploy: Path) -> int:
    """The hospital's size the box was given (``TB_SITE_PATIENTS``: the environment, else ``deploy/.env``); 0: none."""
    raw = os.environ.get("TB_SITE_PATIENTS", "").strip()
    env = deploy / ".env"
    if not raw and env.is_file():
        raw = memcaps._parse_env(env.read_text(encoding="utf-8")).get("TB_SITE_PATIENTS", "")
    if raw and not (raw.isascii() and raw.isdigit()):
        raise PlanError(f"TB_SITE_PATIENTS={raw!r}: the hospital's patients, a whole number")
    return int(raw or 0)


# ------------------------------------------------------------------------------------------------ the plan
def site_id(name: str) -> str:
    """A site id from the site's name (settings ``site.id``: ``[A-Za-z0-9_-]{1,32}``). A name with no Latin letters
    (示範醫院) gets a short stable id from its hash: the owner is never asked for an id."""
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-").upper()[:24]
    return (
        slug
        if len(re.sub(r"[^A-Z]", "", slug)) >= 3
        else "SITE-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:8].upper()
    )


def chart_pattern(rule_text: str) -> str:
    """The MRN pattern that goes with the owner's chart-number rule (``tb_common.chartno``): a rule with a width
    says exactly what a chart number looks like (``digits:8`` is ``^\\d{8}$``). A rule without a width, ``asis``
    and no answer give no pattern (the empty string): the scrubber masks what the pattern matches in a note, and a
    pattern as wide as "any number" would mask every number."""
    from tb_common import chartno

    try:
        rule = chartno.parse_rule(rule_text or "")
    except ValueError:
        return ""  # the wizard refuses the rule itself, with its reason
    if rule.kind == "asis" or not rule.width:
        return ""
    if rule.kind == "digits":
        return f"^\\d{{{rule.width}}}$"
    return f"^[0-9A-Fa-f]{{{rule.width}}}$"  # either case: the rule folds it; a note or a CRC may write the other


def retention_rules(tz: str) -> str:
    """D-138's country rules from the site's zone: Japan's for a site in Japan, Taiwan's (the wizard's own default)
    otherwise. The report language does not decide it: a Taiwanese site may read its reports in English."""
    return "jp" if tz == "Asia/Tokyo" else "tw"


def box_mapping(a: OwnerAnswers) -> tuple[str, str | None]:
    """10K-1: the box's mapping and, when the box writes a site mapping of its own, the shipped mapping it extends.

    No country, or a country with no shipped mapping: the box's site mapping over the shared one, as before. A country
    whose shipped mapping is a base (it extends nothing): a site mapping over it with the site's zone. A country whose
    shipped mapping itself extends the shared one (Japan's ``jp_core/ssmix2_site.yaml``): that mapping by name and no
    file, since the adapter's loader takes one level of ``extends`` only; its zone is the country's one zone, which
    the owner's answers must state (``tb_common.box_answers.parse``)."""
    cd = site_country.defaults(a.country) if a.country else site_country.LEGACY
    shipped = cd.mapping if a.country else None
    # a shipped mapping that reads one kind of source (Japan's: an SS-MIX2 storage) is not a mapping of another
    # source's export (second review of #1088, item 4): that source gets the placeholder, mapped on the box (T-731)
    if not shipped or (cd.data_source_type == "ssmix2" and a.source is not SourceKind.SSMIX2):
        return BOX_MAPPING, "../tw_core/demo_his.yaml"
    if site_country.extends_another(shipped):
        return shipped, None
    folder = shipped.split("/")[1]  # mapping/<folder>/<file>
    return f"mapping/{folder}/box_site.yaml", f"../{shipped.split('/', 1)[1]}"


def box_retention(a: OwnerAnswers) -> dict[str, Any]:
    """The wizard's retention answers. 10K-1: with a country, its rules (``tb_common.site_country.TABLE``), or the
    days the owner gave where TrialBox has no rules for it; with none (the page's flag off, an older answers file),
    from the zone as before (:func:`retention_rules`)."""
    if not a.country:
        return {"retention_rules": retention_rules(a.tz)}
    rules = site_country.defaults(a.country).retention_rules
    if rules:
        return {"retention_rules": rules}
    return {"retention_rules": "", **{k: str(v) for k, v in a.retention_days}}


def mapping_text(tz: str, extends: str = "../tw_core/demo_his.yaml") -> str:
    """The site mapping until the data source's own mapping step (T-731): the shipped mapping and the site's zone."""
    return (
        "# The box's site mapping (T-729, D-466): written by tools/box/plan.py from the owner's time zone. The data\n"
        "# source's own columns and codes are mapped on the box by its connector's mapping step (T-731).\n"
        f"version: 1\nname: box_site\nextends: {extends}\ntz: {tz}\n"
    )


def hardening_conf(hw: Hardware, *, mdns: bool = False) -> str:
    """``mdns``: the box answers its ``.local`` name (OPS-005): UDP 5353 from the box's network in the firewall."""
    backend = "tpm" if hw.tpm else "passphrase"
    ranges = hw.lan or "127.0.0.1/32"
    return (
        "# The box's host baseline (T-729, D-466): written by tools/box/plan.py from the detected hardware; the\n"
        "# IT-managed form (Tang, the clinic ranges from IT) is deploy/hardening/hardening.example.conf (T-634).\n"
        f'CLINIC_RANGES="{ranges}"\nSSH=off\nIT_RANGES=""\nMDNS={"on" if mdns else "off"}\n'
        f"KEK_BACKEND={backend}\n"
        'KEK_SHARES_OUT=""\nTANG_URLS=""\n'
    )


def plan(a: OwnerAnswers, hw: Hardware, deploy: Path = DEPLOY) -> BoxPlan:
    """Everything the installer needs, from the owner's answers and this machine (pure but for reading the compose
    files and running deploy/gpu_profile.sh)."""
    # the memory as read, never the rounded ram_gib: 96.0 GiB shown can be a KiB under the line (card 10E-5)
    mem_kib = hw.mem_total_kib or int(hw.ram_gib * 1024**2)
    profile = gpu_profile(hw.arch, hw.gpu_name, hw.mig, deploy, mem_kib)
    if profile in REFUSED_PROFILES:
        raise PlanError(
            f"this GPU ({hw.gpu_name}) serves TrialBox only on a shared platform (RUNBOOK §17), not as a box"
        )
    mode = "gpu" if profile in (*PAIR_PROFILES, "rtx4090") else "stub"
    warnings: list[str] = []
    if profile == "gb10-64":
        warnings.append(SMALL_SPARK)
    elif mode == "stub":
        warnings.append(f"no GPU of a TrialBox profile ({hw.gpu_name or 'none'}): structured criteria only")
    patients = site_patients(deploy)
    caps, notes = memory_caps(hw.ram_gib, profile if mode == "gpu" else "stub", deploy, patients)
    warnings += notes
    if not hw.lan:
        warnings.append(LAN_UNKNOWN)  # D-629
    email = a.owner.email
    domain = email.split("@", 1)[1]
    mapping, extends = box_mapping(a)
    if a.country and not site_country.defaults(a.country).mapping:
        warnings.append(
            f"country {a.country}: TrialBox ships no mapping for it; the box starts from the shared one until the "
            "data source's mapping step on the box (T-731)"
        )
    elif mapping == BOX_MAPPING and a.country:
        warnings.append(
            f"country {a.country}: its shipped mapping reads another kind of source; this one starts from the shared "
            "mapping until the data source's mapping step on the box (T-731)"
        )
    if a.source is SourceKind.SSMIX2:
        warnings.append(
            "SS-MIX2: the shipped Japanese code tables (JLAC10, byomei, YJ) are sample rows marked verify: check them "
            "and load the site's licensed releases (services/adapter/mapping/jp_core/ssmix2_site.yaml)"
        )
    # M1: a box that is not in use reads the sample hospital (tools/site_seed.py) until a source is given
    sample = a.source is SourceKind.LATER and a.environment != "PRODUCTION"
    feed = a.source_dir or (SAMPLE_FEED if sample else "./site/feed")
    ds: dict[str, Any] = {"data_source_host_dir": feed, "mapping": mapping}
    if a.source is SourceKind.SSMIX2:
        # 10K-1: the SS-MIX2 storage's root folder, mounted read-only where the adapter reads it (the ssmix2 reader)
        ds |= {
            "data_source_type": "ssmix2",
            "data_source_path": BOX_SOURCE_MOUNT,
            "data_source_host_dir": a.ssmix2_root,
            "ssmix2_order_numbers": a.ssmix2_order_numbers or "unique",
        }
    elif a.source in (SourceKind.RESEARCH_DB, SourceKind.OWN_DB):
        # a read connection: its address and account are the one thing hospital IT gives (OD-13; T-731 connects it)
        ds |= {"data_source_type": "cgrd_sql", "data_source_dsn_env": "TB_SOURCE_DSN"}
        warnings.append("data source: a read connection; hospital IT gives its address and account (T-731)")
    else:
        ds |= {"data_source_type": "csv", "data_source_path": BOX_SOURCE_MOUNT}
        if a.source is not SourceKind.LATER:
            warnings.append(f"data source {a.source.value}: its connector and mapping step are on the box (T-731)")
    env: dict[str, str] = dict(caps)
    if patients:  # E2E P-02: memcaps and doctor size and judge the caps by the same number
        env["TB_SITE_PATIENTS"] = str(patients)
    # 10K-4 (D-1390): the folder the owner chose for the disk or the share, else the fixed mount point
    if a.backup.kind is BackupKind.SECOND_DISK:
        folder = a.backup_dir or SECOND_DISK_MOUNT
        env |= {"TB_BACKUP_TARGETS": folder, "TB_BACKUP_OFFBOX": folder}
    elif a.backup.kind is BackupKind.SHARE:
        env |= {"TB_BACKUP_TARGETS": a.backup_dir or SHARE_MOUNT}
    else:
        warnings.append("backups: none yet; the box's health stays red until a second disk or a share is set (T-730)")
    env["TB_BACKUP_MAILTO"] = email  # OD-16: the owner is told (the message path itself is T-730's)
    env["TB_BACKUP_ALERT_ROUTE"] = "health-page"  # D-735: without a mail agent the health tab carries the alert
    # 10K-21 (D-1365): the first-run page's answers, written only when given (a box that was not asked: as before)
    # M1 (UX finding 6): who opens the health tab every working day; the first administrator until one is named
    provisional_owner = email == PROVISIONAL_MAIL  # before the owner's answers: nobody stands in for anybody
    watcher = a.health_page_person or ("" if provisional_owner else person_name(a.owner.full_name))
    if watcher:
        env["TB_BACKUP_ALERT_WATCHER"] = watcher
    if a.tls_root_confirmed_by:  # who in hospital IT confirmed the box's root certificate is on the PCs, and when
        env["TB_TLS_ROOT_CONFIRMED_BY"] = a.tls_root_confirmed_by
        env["TB_TLS_ROOT_CONFIRMED_ON"] = a.tls_root_confirmed_on
    # 10K-4 (D-1390): the audit chain's signed heads (mounted into the console, D-638: by install.sh, or after the
    # first-run apply by box-install.sh) and the collected logs, written only when chosen (not asked: as before)
    if a.anchor_dir:
        env["TB_AUDIT_ANCHOR_TARGETS"] = a.anchor_dir
    if a.log_dir:
        env["TB_LOG_DIR"] = a.log_dir
    env["TB_ENV"] = a.environment  # D-822: the owner's answer, PRODUCTION unless VALIDATION
    if a.country and site_country.defaults(a.country).consent_proxy:
        env["TB_CONSENT_PROXY"] = "on"  # 10C-19 (D-1232): the Japan profile: the representative and the assent
    wizard: dict[str, Any] = {
        "site_id": site_id(a.site_name),
        "site_name": a.site_name,
        **({"country": a.country} if a.country else {}),
        "tz": a.tz,
        "locale": a.language,
        **{k: v for k, v in (("printed_dates", a.printed_dates), ("year_basis", a.year_basis)) if v},  # 10C-13/15
        "contact": email,
        "internal_domains": [domain],
        "intake_address": f"trialbox@{domain}",
        "senders": [email],
        "physicians": [email],
        "reviewers": [email],
        "alliance_sites": [],
        **ds,
        "registry_type": "none",
        "departments": SHIPPED_DEPARTMENTS,
        "practitioners": {},
        "llm_mode": mode,
        "cloud_enabled": "no",
        "attachment_encryption": "link",
        "console_url": f"https://{a.hostname}",
        "twpas_enabled": "no",
        "alliance_root": "no",
        "cohort_rulesets": [],
        "smtp_host": a.smtp_host,
        **({"smtp_port": a.smtp_port} if a.smtp_port else {}),
        "sae_office_mailbox": a.sae_office_mailbox
        or ("" if provisional_owner else email),  # D-1280: the administrator's mail stands in
        "stand_ins": sorted(stand_ins(a)),
        "imap_host": "",
        "mta_authserv_id": a.mta_authserv_id,  # D-825: the owner's answer; empty: mail stays closed (D-369)
        "tls_hostname": a.hostname,
        # NEW-DIN-3 (D-579): the first-run page's answer, once it has the field; empty: the wizard decides and warns.
        # The pattern that goes with it: the page asks the format once, not a regular expression too
        "chartno_rule": getattr(a, "chartno_rule", ""),
        "mrn_regex": chart_pattern(getattr(a, "chartno_rule", "")),
        "tls_mode": "internal",  # the box's default; the hospital's certificate is IT's optional step (one page, T-735)
        **box_retention(a),
        "ctgov_mode": "offline",
        "env_extra": env,
    }
    files = {"site/hardening.conf": hardening_conf(hw, mdns=a.hostname.endswith(".local"))}
    if extends is not None:
        files[f"site/{mapping}"] = mapping_text(a.tz, extends)
    if not hw.tpm:
        warnings.append(
            "no usable TPM (systemd-creds has-tpm2): the site keys are sealed under a passphrase the owner "
            "sets, typed after every restart"
        )
    return BoxPlan(profile, mode, wizard, env, files, warnings, stand_ins(a))


def provisional(hw: Hardware) -> OwnerAnswers:
    """The answers the installer starts the box with, before the owner has given any: they serve only the wizard's
    page and are all replaced when the owner finishes it."""
    from tb_common.box_answers import parse

    a, problems = parse({
        "site_name": "TrialBox", "tz": hw.host_tz or "UTC", "language": "en",
        "owner": {"full_name": "owner", "username": "owner", "email": PROVISIONAL_MAIL},
        "box_name": hw.hostname, "backup": {"kind": "later"}, "source": "later",
    })  # fmt: skip
    if a is None:
        raise PlanError("; ".join(map(str, problems)))
    return a


def write(p: BoxPlan, deploy: Path, answers_out: Path, *, keep: bool = False) -> None:
    """The site files under ``deploy`` (``keep``: one that is there stays as it is) and the wizard's answers file (JSON,
    which is YAML), 0600."""
    for rel, text in p.files.items():
        f = deploy / rel
        if keep and f.exists():
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    answers_out.parent.mkdir(parents=True, exist_ok=True)
    answers_out.write_text(json.dumps(p.wizard_answers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    answers_out.chmod(0o600)
    site_needs.write_stand_ins(deploy, p.stand_ins)
