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
import os
import platform
import re
import shutil
import socket
import subprocess
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tb_common.box_answers import BackupKind, OwnerAnswers, SourceKind

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
PAIR_PROFILES = ("rtxpro6000", "gb10", "rtx5090")  # judge and verifier (D-124)
WORKSTATION_PROFILES = ("rtxpro6000", "rtx5090", "rtx4090", "default")
REFUSED_PROFILES = ("shared-quota", "b200-no-mig")  # install.sh refuses them: a platform, not a box (D-211, D-409)
# where the box keeps its backups and its first-run answers; the folders are the box's own, never the owner's choice
SECOND_DISK_MOUNT = "/srv/trialbox-backup"
SHARE_MOUNT = "/mnt/trialbox-share"
FIRSTRUN_DIR = "/run/trialbox-firstrun"  # tmpfs: the answers (and a passphrase) never reach a disk
BOX_MAPPING = "mapping/tw_core/box_site.yaml"
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
    lan: str = ""  # the box's network, CIDR (192.0.2.0/24)
    hostname: str = "trialbox"
    host_tz: str = ""

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

    @property
    def install_args(self) -> list[str]:
        if self.mode == "gpu":
            return ["--mode", "gpu", "--gpu", self.profile]
        return ["--mode", "stub"]


class PlanError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ hardware
def gpu_profile(arch: str, gpu_name: str, mig: str = "", deploy: Path = DEPLOY) -> str:
    """deploy/gpu_profile.sh's answer for this machine: one rule, shared with install.sh."""
    if not gpu_name:
        return "none"
    out = subprocess.run(
        ["sh", str(deploy / "gpu_profile.sh"), arch, gpu_name, mig], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def detect(deploy: Path = DEPLOY, host_root: Path = Path("/")) -> Hardware:  # pragma: no cover - reads the machine
    """This machine, as the wizard and :func:`plan` need it. Read-only."""
    gpu = _run(["nvidia-smi", "--query-gpu=name,memory.total,mig.mode.current", "--format=csv,noheader,nounits"])
    name, mem, mig = (
        [*[x.strip() for x in gpu.splitlines()[0].split(",")], "", "", ""] if gpu.strip() else ["", "", ""]
    )[:3]
    meminfo = (host_root / "proc/meminfo").read_text(encoding="utf-8") if (host_root / "proc/meminfo").exists() else ""
    kib = re.search(r"MemTotal:\s+(\d+)", meminfo)
    tz = ""
    with_tz = host_root / "etc/timezone"
    if with_tz.is_file():
        tz = with_tz.read_text(encoding="utf-8").strip()
    elif (host_root / "etc/localtime").is_symlink():
        tz = str(os.readlink(host_root / "etc/localtime")).split("zoneinfo/")[-1]
    return Hardware(
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        ram_gib=round(int(kib.group(1)) / 1024**2, 1) if kib else 0.0,
        disk_free_gib=round(shutil.disk_usage(deploy).free / 1024**3, 1),
        gpu_name=name,
        gpu_mem_gib=round(float(mem) / 1024, 1) if re.fullmatch(r"[0-9.]+", mem or "") else 0.0,
        mig=mig if mig not in ("[N/A]", "N/A") else "",
        tpm=(host_root / "dev/tpmrm0").exists() or (host_root / "dev/tpm0").exists(),
        disks=parse_lsblk(_run(["lsblk", "-J", "-b", "-o", "PATH,SIZE,TYPE,TRAN,MOUNTPOINT"])),
        lan=parse_ip(_run(["ip", "-j", "-4", "addr", "show", "scope", "global"])),
        hostname=socket.gethostname().split(".")[0].lower() or "trialbox",
        host_tz=tz,
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


def parse_ip(text: str) -> str:
    """The box's network as a CIDR, from ``ip -j -4 addr``: the first global address that is not a container bridge."""
    try:
        links = json.loads(text or "[]")
    except ValueError:
        return ""
    for link in links:
        if str(link.get("ifname", "")).startswith(("docker", "br-", "veth", "virbr")):
            continue
        for a in link.get("addr_info") or ():
            if a.get("family") == "inet" and a.get("local"):
                return str(ipaddress.ip_interface(f"{a['local']}/{a.get('prefixlen', 24)}").network)
    return ""


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


def memory_caps(ram_gib: float, profile: str, deploy: Path = DEPLOY) -> tuple[dict[str, str], list[str]]:
    """``TB_MEM_*`` for this machine (OD-10): no cap is a constant. The compose files' defaults give each service's
    share; the RAM, less what the system keeps (a tenth, at least 4 GiB) and the fixed small caps, is shared out in
    those proportions. When the defaults do not fit, every cap shrinks by the same factor, and a machine where that
    factor falls below :data:`MIN_SERVICE_SHARE` is refused (:class:`PlanError`: the services were never measured
    there). When they fit with room to spare, the services grow into it (the lake and the database use it) and the
    model servers keep their default (their weights are on the card; more host memory does not serve them faster).
    The Spark (``gb10``) is one machine: its profile (``deploy/gb10-profile.yaml``) is its caps, so nothing is
    derived for it."""
    if profile == "gb10":
        return {}, []
    files = [deploy / "docker-compose.yml", deploy / "docker-compose.identity.yml"]
    overlay = {"rtxpro6000": "rtxpro6000", "rtx5090": "rtx5090", "rtx4090": "rtx5090"}.get(profile)
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
    return {k: f"{int(v * 1024)}m" for k, v in sorted(caps.items())}, notes


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
    return f"^[0-9{'a-f' if rule.case == 'lower' else 'A-F'}]{{{rule.width}}}$"


def retention_rules(tz: str) -> str:
    """D-138's country rules from the site's zone: Japan's for a site in Japan, Taiwan's (the wizard's own default)
    otherwise. The report language does not decide it: a Taiwanese site may read its reports in English."""
    return "jp" if tz == "Asia/Tokyo" else "tw"


def mapping_text(tz: str) -> str:
    """The site mapping until the data source's own mapping step (T-731): the shared mapping and the site's zone."""
    return (
        "# The box's site mapping (T-729, D-466): written by tools/box/plan.py from the owner's time zone. The data\n"
        "# source's own columns and codes are mapped on the box by its connector's mapping step (T-731).\n"
        f"version: 1\nname: box_site\nextends: ../tw_core/demo_his.yaml\ntz: {tz}\n"
    )


def hardening_conf(hw: Hardware) -> str:
    backend = "tpm" if hw.tpm else "passphrase"
    ranges = hw.lan or "127.0.0.1/32"
    return (
        "# The box's host baseline (T-729, D-466): written by tools/box/plan.py from the detected hardware; the\n"
        "# IT-managed form (Tang, the clinic ranges from IT) is deploy/hardening/hardening.example.conf (T-634).\n"
        f'CLINIC_RANGES="{ranges}"\nSSH=off\nIT_RANGES=""\n'
        f"KEK_BACKEND={backend}\n"
        'KEK_SHARES_OUT=""\nTANG_URLS=""\n'
    )


def plan(a: OwnerAnswers, hw: Hardware, deploy: Path = DEPLOY) -> BoxPlan:
    """Everything the installer needs, from the owner's answers and this machine (pure but for reading the compose
    files and running deploy/gpu_profile.sh)."""
    profile = gpu_profile(hw.arch, hw.gpu_name, hw.mig, deploy)
    if profile in REFUSED_PROFILES:
        raise PlanError(
            f"this GPU ({hw.gpu_name}) serves TrialBox only on a shared platform (RUNBOOK §17), not as a box"
        )
    mode = "gpu" if profile in (*PAIR_PROFILES, "rtx4090") else "stub"
    warnings: list[str] = []
    if mode == "stub":
        warnings.append(f"no GPU of a TrialBox profile ({hw.gpu_name or 'none'}): structured criteria only")
    caps, notes = memory_caps(hw.ram_gib, profile if mode == "gpu" else "stub", deploy)
    warnings += notes
    email = a.owner.email
    domain = email.split("@", 1)[1]
    ds: dict[str, Any] = {"data_source_host_dir": "./site/feed", "mapping": BOX_MAPPING}
    if a.source in (SourceKind.RESEARCH_DB, SourceKind.OWN_DB):
        # a read connection: its address and account are the one thing hospital IT gives (OD-13; T-731 connects it)
        ds |= {"data_source_type": "cgrd_sql", "data_source_dsn_env": "TB_SOURCE_DSN"}
        warnings.append("data source: a read connection; hospital IT gives its address and account (T-731)")
    else:
        ds |= {"data_source_type": "csv", "data_source_path": "/data/source/site"}
        if a.source is not SourceKind.LATER:
            warnings.append(f"data source {a.source.value}: its connector and mapping step are on the box (T-731)")
    env: dict[str, str] = dict(caps)
    if a.backup.kind is BackupKind.SECOND_DISK:
        env |= {"TB_BACKUP_TARGETS": SECOND_DISK_MOUNT, "TB_BACKUP_OFFBOX": SECOND_DISK_MOUNT}
    elif a.backup.kind is BackupKind.SHARE:
        env |= {"TB_BACKUP_TARGETS": SHARE_MOUNT}
    else:
        warnings.append("backups: none yet; the box's health stays red until a second disk or a share is set (T-730)")
    env["TB_BACKUP_MAILTO"] = email  # OD-16: the owner is told (the message path itself is T-730's)
    wizard: dict[str, Any] = {
        "site_id": site_id(a.site_name),
        "site_name": a.site_name,
        "tz": a.tz,
        "locale": a.language,
        "contact": email,
        "internal_domains": [domain],
        "intake_address": f"trialbox@{domain}",
        "senders": [email],
        "physicians": [email],
        "reviewers": [email],
        "alliance_sites": [],
        **ds,
        "registry_type": "none",
        "departments": {},
        "practitioners": {},
        "llm_mode": mode,
        "cloud_enabled": "no",
        "attachment_encryption": "link",
        "console_url": f"https://{a.hostname}",
        "twpas_enabled": "no",
        "alliance_root": "no",
        "cohort_rulesets": [],
        "smtp_host": "",
        "imap_host": "",
        "mta_authserv_id": "",
        "tls_hostname": a.hostname,
        # NEW-DIN-3 (D-579): the first-run page's answer, once it has the field; empty: the wizard decides and warns.
        # The pattern that goes with it: the page asks the format once, not a regular expression too
        "chartno_rule": getattr(a, "chartno_rule", ""),
        "mrn_regex": chart_pattern(getattr(a, "chartno_rule", "")),
        "tls_mode": "internal",  # the box's default; the hospital's certificate is IT's optional step (one page, T-735)
        "retention_rules": retention_rules(a.tz),
        "ctgov_mode": "offline",
        "env_extra": env,
    }
    files = {"site/hardening.conf": hardening_conf(hw), f"site/{BOX_MAPPING}": mapping_text(a.tz)}
    if not hw.tpm:
        warnings.append("no TPM: the site keys are sealed under a passphrase the owner sets, typed after every restart")
    return BoxPlan(profile, mode, wizard, env, files, warnings)


def provisional(hw: Hardware) -> OwnerAnswers:
    """The answers the installer starts the box with, before the owner has given any: they serve only the wizard's
    page and are all replaced when the owner finishes it."""
    from tb_common.box_answers import parse

    a, problems = parse({
        "site_name": "TrialBox", "tz": hw.host_tz or "UTC", "language": "en",
        "owner": {"full_name": "owner", "username": "owner", "email": "owner@box.invalid"},
        "box_name": hw.hostname, "backup": {"kind": "later"}, "source": "later",
    })  # fmt: skip
    if a is None:
        raise PlanError("; ".join(map(str, problems)))
    return a


def write(p: BoxPlan, deploy: Path, answers_out: Path) -> None:
    """The site files under ``deploy`` and the wizard's answers file (JSON, which is YAML), 0600."""
    for rel, text in p.files.items():
        f = deploy / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    answers_out.parent.mkdir(parents=True, exist_ok=True)
    answers_out.write_text(json.dumps(p.wizard_answers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    answers_out.chmod(0o600)
