"""The live preflight (plan 10 row 10K-3, review 18 SO-3, D-1361): the checks of ``tb_common.preflight.ITEMS``.

    python -m tools.trialbox doctor --preflight --env-file deploy/.env [--settings deploy/settings.yaml] [--lang ja]
    python -m tools.trialbox doctor --preflight --env-file deploy/.env --out /run/trialbox-firstrun/preflight.json
    python -m tools.settings_wizard --answers site.yaml --env-out deploy/.env --preflight

Every check is read-only and needs no internet. It lists folders and reads file modes (``lstat``, ``os.access``:
nothing is written), resolves the box's name with the hospital's resolver, reads the hospital mail relay's greeting
and says ``QUIT`` (over TLS on port 465), opens a Tang server's port and closes it, and asks ``ip``, ``nvidia-smi``,
``docker info`` and the TPM. A check that raises is a FAIL, as in ``doctor``; a check that does not finish within
:data:`CHECK_TIMEOUT_S` (a hard-mounted share that hangs, a resolver that does not answer) is a FAIL whose detail
starts with ``timed out`` and whose action is the time-out's, never green. The feed's walk is bounded in files and
in time.

What is reused: the clock is ``doctor``'s own ``check_clock``; the certificate is the console's ``check_tls``; the
backup targets are read and classified by ``backup_schedule`` (and so is where an audit folder lives,
``target_kind``); the audit folders by ``anchors``; the tier record by ``tb_common.tier_value``'s path and profile
rule; the card names by ``deploy/gpu_profile.sh``'s rule (a name the card's name contains); the TPM by
``tools.box.plan.tpm_usable``; the free space by ``deploy/check_host.sh``'s rule and paths.

The feed is counted, never read: readable files under the feed folder as the services' user (uid and gid
:data:`SERVICE_ID`, the images' ``tb``) reads them, judged from the modes; no file is opened, no link followed, no
name printed.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tb_common import preflight as text

from tools.trialbox import doctor
from tools.trialbox.doctor import Check, DoctorInputs, Status

FREE_FAIL_PCT = 10  # as deploy/check_host.sh's free space: below 10 % FAIL, below 20 % WARN
FREE_WARN_PCT = 20
GPU_MEM_TOLERANCE = 0.03  # a card's reported memory differs from the stated one by a few hundred MiB at most
FEED_CAP = 200_000  # the count stops here (a very large SS-MIX2 store); the line says "at least"
FEED_TIME_S = 15.0  # and here: a slow share is counted for this long, then said so
CONNECT_TIMEOUT_S = 3.0
CHECK_TIMEOUT_S = 20.0  # one check
RUN_TIMEOUT_S = 70.0  # all of them: below deploy/box-install.sh's limit for the process (TB_BOX_PREFLIGHT_S, 90 s)
SERVICE_ID = 10001  # deploy/docker/python.Dockerfile: the services run as tb, uid 10001 (its group 10001)
SMTPS_PORT = 465  # implicit TLS: the greeting comes after the handshake
KEK_BACKENDS = ("tpm", "shamir", "passphrase")  # deploy/hardening/seal_keys.sh
APPLIED = Path("site") / "box" / "applied"  # deploy/box-install.sh: the owner's answers were applied (D-576)
RED = "\033[31m"
RESET = "\033[0m"


def _resolve(host: str) -> list[str]:
    return sorted({str(a[4][0]) for a in socket.getaddrinfo(host, None)})


def _own_addrs() -> set[str] | None:
    """This machine's addresses (``ip -j addr show``); None when they cannot be read."""
    from tools.box.plan import _run

    try:
        links = json.loads(_run(["ip", "-j", "addr", "show"]) or "null")
    except ValueError:
        return None
    if not isinstance(links, list):
        return None
    return {str(a.get("local")) for link in links for a in link.get("addr_info") or () if a.get("local")}


_BRIDGES = ("lo", "docker", "br-", "veth")  # the host's own container bridges are not the hospital's ranges


def _host_nets() -> list[str] | None:
    """H-137: the ranges this host is on (its addresses with their prefix, and its routes), container bridges left
    out; None when they cannot be read."""
    from tools.box.plan import _run

    try:
        links = json.loads(_run(["ip", "-j", "addr", "show"]) or "null")
        routes = json.loads(_run(["ip", "-j", "route", "show"]) or "null")
    except ValueError:
        return None
    if not isinstance(links, list) or not isinstance(routes, list):
        return None
    kept = [link for link in links if not str(link.get("ifname", "")).startswith(_BRIDGES)]
    out = [
        f"{a['local']}/{a.get('prefixlen', 32)}" for link in kept for a in link.get("addr_info") or () if a.get("local")
    ]
    out += [str(r["dst"]) for r in routes if r.get("dst") not in (None, "default")
            and not str(r.get("dev", "")).startswith(_BRIDGES)]  # fmt: skip
    return out


def _banner(host: str, port: int, timeout: float) -> str:
    """Opens a connection (TLS first on port 465), reads the server's greeting, sends ``QUIT`` and closes."""
    with socket.create_connection((host, port), timeout=timeout) as raw:
        s: socket.socket = raw
        if port == SMTPS_PORT:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False  # the greeting is asked for, not the certificate (the mail gateway judges it)
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(raw, server_hostname=host)
        s.settimeout(timeout)
        line = s.recv(512).decode("ascii", "replace").strip()
        with contextlib.suppress(OSError):
            s.sendall(b"QUIT\r\n")
        return line


def _mail_cert(host: str, port: int, cafile: str, timeout: float) -> str:
    """H-137: the relay's certificate checked as the mail gateway checks it (the public CAs plus the hospital's CA
    file when one is named), over TLS on port 465 and after STARTTLS on any other port. Raises when it fails."""
    import smtplib

    ctx = ssl.create_default_context()
    if cafile:
        ctx.load_verify_locations(cafile)
    if port == SMTPS_PORT:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as s:
            s.noop()
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as s:
            s.starttls(context=ctx)
    return "verified"


def _reach(host: str, port: int, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout):
        return "open"


def _gpus() -> list[tuple[str, float]]:
    """Every card: (name, memory MiB)."""
    from tools.box.plan import _run

    out = []
    for line in _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]).splitlines():
        name, _, mem = line.partition(",")
        with contextlib.suppress(ValueError):
            out.append((name.strip(), float(mem.strip())))
    return out


def _tpm() -> bool:
    from tools.box.plan import tpm_usable

    return tpm_usable()


def _docker_root() -> Path | None:
    """Where Docker keeps the data, as ``deploy/check_host.sh`` asks it; ``/var/lib/docker`` when it says none."""
    try:
        got = subprocess.run(["docker", "info", "--format", "{{.DockerRootDir}}"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        got = ""
    return Path(got or "/var/lib/docker")


def _writable(path: Path) -> bool:
    """Whether this process may write there (a folder: add a file), asked of the file system; nothing is written."""
    return os.access(path, os.W_OK | (os.X_OK if path.is_dir() else 0))


def _euid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else -1


@dataclass
class Probes:
    """What the checks ask of the machine and the network; the tests hand in their own."""

    writable: Callable[[Path], bool] = _writable
    resolve: Callable[[str], list[str]] = _resolve
    own_addrs: Callable[[], set[str] | None] = _own_addrs
    host_nets: Callable[[], list[str] | None] = _host_nets  # the ranges this host is on (H-137)
    banner: Callable[[str, int, float], str] = _banner  # the mail relay's greeting
    mail_cert: Callable[[str, int, str, float], str] = _mail_cert  # the mail relay's certificate (H-137)
    reach: Callable[[str, int, float], str] = _reach  # a Tang server's port
    gpus: Callable[[], list[tuple[str, float]]] = _gpus  # every card: (name, memory MiB)
    tpm: Callable[[], bool] = _tpm
    disk_usage: Callable[[Path], Any] = shutil.disk_usage
    docker_root: Callable[[], Path | None] = _docker_root
    euid: Callable[[], int] = _euid
    tiers_dir: Path | None = None  # tb_common.tier_value.TIERS_DIR when None
    offbox: Callable[[Path], bool] | None = None  # backup_schedule.target_kind's answer when None
    feed_time_s: float = FEED_TIME_S


def _env(inp: DoctorInputs) -> str:
    return (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()


def _deploy(inp: DoctorInputs) -> Path:
    return inp.deploy or doctor.ROOT / "deploy"


# ------------------------------------------------------------------------------------------------ checks
def _tls_cert_warnings(env: Mapping[str, str]) -> list[str]:
    """In hospital mode, a certificate that signed itself: no chain to the hospital's CA, browsers warn."""
    if (env.get("TB_TLS_MODE") or "internal").strip().lower() != "hospital":
        return []
    from cryptography import x509

    try:
        certs = x509.load_pem_x509_certificates(Path(env.get("TB_TLS_CERT_FILE") or "/nonexistent").read_bytes())
    except (OSError, ValueError):
        return []  # check_tls says so
    if certs[0].issuer == certs[0].subject:
        return ["the certificate signed itself (no chain to the hospital's CA): browsers will warn"]
    return []


def check_name_cert(inp: DoctorInputs, p: Probes) -> Check:
    """The console's name resolves on the hospital's network to this box, and the certificate Caddy will use names it
    and is valid (``console.identity.check_tls``). A ``.local`` name not answered yet is amber before the owner's
    answers are applied (the box takes the name then, OPS-005) and red after."""
    host = (inp.env.get("TB_TLS_HOSTNAME") or "").strip().lower()
    if not host:
        status: Status = "FAIL" if _env(inp) == "PRODUCTION" else "WARN"
        return Check("name_cert", status, "no TB_TLS_HOSTNAME: the box has no name on the hospital network")
    try:
        addrs = (inp.resolver or p.resolve)(host)
    except OSError as e:
        addrs, why = [], f"{type(e).__name__}: {e}"
    else:
        why = "no address"
    if not addrs and host.endswith(".local"):
        if (_deploy(inp) / APPLIED).is_file():
            return Check("name_cert", "FAIL", f"{host} does not resolve ({why}), and the set-up was applied: the "
                         "box does not answer its .local name (avahi-daemon, the host name)")  # fmt: skip
        why = f"{host} does not resolve yet ({why}): the box answers its .local name itself once the set-up is applied"
        return Check("name_cert", "WARN", f"{why}; a computer that cannot resolve .local uses the address")
    if not addrs:
        return Check("name_cert", "FAIL", f"{host} does not resolve here ({why})")
    where = f"{host} is {', '.join(addrs)}"
    addrs = [a for a in addrs if _routable(a)]
    if not addrs:  # /etc/hosts or nss-myhostname answering on the box itself: no record in the hospital's DNS
        return Check("name_cert", "FAIL", f"{where}: only a loopback or link-local address, answered on this box "
                     "and not by the hospital's DNS")  # fmt: skip
    own = p.own_addrs()
    own = {a for a in own if _routable(a)} if own is not None else None
    if own is not None and not set(addrs) & own:
        return Check("name_cert", "FAIL", f"{where}: not an address of this box ({', '.join(sorted(own)) or 'none'})")
    # H-137 (the owner's decision, #639 7156806411 item 7): behind Caddy the box's internal network has a fixed range
    # (Caddy's address is the one trusted proxy); it must not be a range of the hospital's that this host is on
    from tb_common import trusted_proxy as tp

    subnet = (inp.env.get("TB_NET_SUBNET") or "").strip() or tp.DEFAULT_SUBNET
    nets = p.host_nets()
    clash = tp.clashes(subnet, nets) if nets is not None else []
    if clash:
        why = f"the box's internal range {subnet} clashes with this host's {', '.join(clash)}"
        return Check("name_cert", "FAIL", f"{where}; {why}: set TB_NET_SUBNET and TB_PROXY_ADDR to a free range")
    try:
        from console.identity import check_tls
    except ImportError as e:  # a host python without the console's libraries
        return Check("name_cert", "WARN", f"{where}; the certificate not checked here ({e.name})")
    tls = check_tls(inp.env)
    if tls.problems:
        return Check("name_cert", "FAIL", f"{where}; " + "; ".join(tls.problems))
    warns = _tls_cert_warnings(inp.env)
    notes = "".join(f"; {n}" for n in [*warns, *tls.notes])
    unchecked = "" if own is not None else "; this box's own addresses could not be read (not compared)"
    worst: Status = "WARN" if warns or own is None else "PASS"
    return Check("name_cert", worst, f"{where}; certificate mode {tls.mode}{notes}{unchecked}")


def check_backup_share(inp: DoctorInputs, p: Probes) -> Check:
    """Every backup target is there and writable by this process, and one is off the box (``backup_schedule``)."""
    from tools.trialbox import backup_schedule as bs

    if inp.deploy is None:
        return Check("backup_share", "FAIL", "the deploy folder is not known: run with --env-file deploy/.env")
    cfg = bs.config(inp.deploy, dict(inp.env), process_env=False)
    if not cfg.targets:
        return Check("backup_share", "FAIL", "no backup target is set (TB_BACKUP_TARGETS)")
    bad: list[str] = []
    off = 0
    for t in cfg.targets:
        if not t.is_dir():
            bad.append(f"{t} is not there (not mounted?)")
            continue
        if not p.writable(t):
            bad.append(f"{t} is not writable by the box")
        off += (p.offbox or (lambda x: cfg.classify(x).offbox))(t)
    if not off and not bad:
        bad.append("every target is on the box's own disk: a lost box loses its backups")
    facts = f"{len(cfg.targets)} target(s), {off} off the box"
    if bad:
        return Check("backup_share", "FAIL", "; ".join(bad) + f" ({facts})")
    return Check("backup_share", "PASS", f"{facts}, each writable")


def _offbox(path: Path, inp: DoctorInputs) -> bool:
    from tools.trialbox import backup_schedule as bs

    return bs.target_kind(path, local=(Path("/"), _deploy(inp))).offbox


def _routable(addr: str) -> bool:
    """An address other computers can use: not loopback, not link-local (nor something that is not an address)."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_link_local or ip.is_unspecified)


#: owners a box's root may act as on a share: itself, and the identity root-squash maps it to (nobody, 65534)
SQUASHED = 65534


def _unlinkable(folder: Path, st: os.stat_result, euid: int, writable: bool) -> bool:
    """Whether this process could remove a file from ``folder``: it may write there and the folder is not sticky,
    or it owns the folder."""
    return writable and (not st.st_mode & stat.S_ISVTX or st.st_uid in (euid, SQUASHED))


def check_audit_share(inp: DoctorInputs, p: Probes) -> Check:
    """The anchor folders (``TB_AUDIT_ANCHOR_TARGETS``) are off the box (the mount table, as ``backup_schedule``
    judges a backup target), the box can add the nightly signed head, and the box's root can neither write, chmod
    (own) nor remove and replace a signed head already there. A write-once share may refuse what the modes allow;
    that is not visible from here, so a mode that allows it is amber with the advice to confirm, never green."""
    from tools.trialbox import anchors

    try:
        folders = [Path(h) for h, _ in anchors.plan(inp.env)]
    except anchors.AnchorError as e:
        return Check("audit_share", "FAIL", str(e))
    if not folders:
        status: Status = "FAIL" if _env(inp) == "PRODUCTION" else "WARN"
        return Check("audit_share", status, f"no audit share is set ({anchors.ENV})")
    bad: list[str] = []
    soft: list[str] = []
    euid = p.euid()
    for f in folders:
        if not f.is_dir():
            bad.append(f"{f} is not there (not mounted?)")
            continue
        if not (p.offbox or (lambda x: _offbox(x, inp)))(f):
            bad.append(f"{f} is on the box's own disks (not a share or a disk off the box)")
            continue
        heads_dir = f / "heads" if (f / "heads").is_dir() else f
        dir_writable = p.writable(heads_dir)
        if not dir_writable:
            bad.append(f"{f}: the box cannot add the nightly signed head")
            continue
        heads = sorted(heads_dir.glob("*.json")) if heads_dir.name == "heads" else []
        if not heads:
            soft.append(f"{f}: no signed head yet, judged after the first night")
            continue
        if euid != 0:
            soft.append(f"{f}: run as root to see what the box's root may do to a signed head")
            continue
        if any(p.writable(h) for h in heads):
            bad.append(f"{f}: the box's root can change a signed head")
            continue
        owned = any(h.lstat().st_uid in (euid, SQUASHED) for h in heads)
        if owned:
            soft.append(f"{f}: the box's root (or the user root is squashed to, {SQUASHED}) owns the signed heads and "
                        "may make them writable or remove them; confirm the share is write-once")  # fmt: skip
        if _unlinkable(heads_dir, heads_dir.lstat(), euid, dir_writable):
            soft.append(f"{f}: the box's root may remove and replace a signed head (the folder is writable and not "
                        f"sticky, or owned by root or {SQUASHED}); confirm the share is write-once")  # fmt: skip
    if bad:
        return Check("audit_share", "FAIL", "; ".join(bad + soft))
    if soft:
        return Check("audit_share", "WARN", "; ".join(soft))
    return Check("audit_share", "PASS", f"{len(folders)} folder(s) off the box; root can neither change nor remove a "
                 "signed head")  # fmt: skip


def _readable_by_service(st: os.stat_result, need_x: bool = False) -> bool:
    """Whether the services' user (uid and gid :data:`SERVICE_ID`) may read this, from its mode and ownership."""
    want = 0o4 | (0o1 if need_x else 0)
    if st.st_uid == SERVICE_ID:
        bits = (st.st_mode >> 6) & 0o7
    elif st.st_gid == SERVICE_ID:
        bits = (st.st_mode >> 3) & 0o7
    else:
        bits = st.st_mode & 0o7
    return bits & want == want


def check_feed(inp: DoctorInputs, p: Probes) -> Check:
    """The feed folder is there and the services' user can read every file in it; the line gives the number of
    readable files (no name, no content). Links are not followed and count as not readable; a folder the walk
    cannot enter counts as not readable."""
    ds = inp.settings.get("data_source") if isinstance(inp.settings.get("data_source"), Mapping) else {}
    kind = str((ds or {}).get("type") or "")
    raw = (inp.env.get("TB_SOURCE_DIR") or "").strip()
    if kind in ("cgrd_sql", "fhir_bulk"):
        return Check("feed", "WARN", f"a {kind} feed is not a folder: the night's ingest report counts it")
    if not raw and not kind:
        return Check("feed", "WARN", "no data feed is chosen yet (TB_SOURCE_DIR, data_source)")
    folder = Path(raw) if raw else Path(str((ds or {}).get("path") or ""))
    if not folder.is_absolute():
        folder = _deploy(inp) / folder
    if not folder.is_dir():
        return Check("feed", "FAIL", f"the feed folder {folder} is not there")
    if folder.is_symlink() or not _readable_by_service(folder.stat(), need_x=True):
        return Check(
            "feed", "FAIL", f"the feed folder {folder} is not readable by the box's services (uid {SERVICE_ID})"
        )
    count = unreadable = 0
    errors: list[OSError] = []
    end = time.monotonic() + p.feed_time_s
    stopped = ""
    for top, dirs, files in os.walk(folder, onerror=errors.append):
        keep = []
        for d in dirs:
            if d.startswith("."):
                continue
            st = os.lstat(os.path.join(top, d))
            if stat.S_ISLNK(st.st_mode) or not _readable_by_service(st, need_x=True):
                unreadable += 1
            else:
                keep.append(d)
        dirs[:] = keep
        for name in files:
            if name.startswith("."):
                continue
            st = os.lstat(os.path.join(top, name))
            if stat.S_ISREG(st.st_mode) and _readable_by_service(st):
                count += 1
            else:
                unreadable += 1
        if count >= FEED_CAP:
            stopped = f" (counting stopped at {FEED_CAP})"
            break
        if time.monotonic() > end:
            stopped = f" (counting stopped after {p.feed_time_s:g} s)"
            break
    unreadable += len(errors)
    many = "at least " if stopped else ""
    if unreadable:
        why = f"{unreadable} not readable by the box's services (uid {SERVICE_ID}; a link or a folder it cannot enter)"
        return Check("feed", "FAIL", f"{folder}: {many}{count} file(s) readable, {why}{stopped}")
    if not count:
        return Check("feed", "FAIL", f"{folder} holds no file yet")
    if stopped.startswith(" (counting stopped after"):
        return Check("feed", "WARN", f"{folder}: {many}{count} file(s) readable{stopped}")
    return Check("feed", "PASS", f"{folder}: {many}{count} file(s) readable ({kind or 'feed'}){stopped}")


def check_mail_relay(inp: DoctorInputs, p: Probes) -> Check:
    """The hospital's mail relay (``SMTP_HOST``, ``SMTP_PORT``) answers with its greeting (220)."""
    host = (inp.env.get("SMTP_HOST") or "").strip()
    if not host:
        return Check("mail_relay", "WARN", "no mail relay is set (SMTP_HOST): the box sends no mail")
    try:
        port = int((inp.env.get("SMTP_PORT") or "587").strip())
    except ValueError:
        return Check("mail_relay", "FAIL", f"SMTP_PORT {inp.env.get('SMTP_PORT')!r} is not a port")
    try:
        first = p.banner(host, port, CONNECT_TIMEOUT_S)
    except OSError as e:
        return Check("mail_relay", "FAIL", f"{host}:{port} did not answer ({type(e).__name__}: {e})")
    if not first.startswith("220"):
        return Check("mail_relay", "FAIL", f"{host}:{port} answered {first[:60]!r}, not a mail greeting (220)")
    # H-137 (the owner's decision, #639 7156806411 item 6): the certificate is tested as the mail gateway will
    starttls = _on(inp.env.get("SMTP_STARTTLS"), True)
    if port != SMTPS_PORT and not starttls:
        return Check("mail_relay", "WARN", f"{host}:{port} answers, without TLS (SMTP_STARTTLS=false): each start of "
                     "the mail gateway is audited (mail.plaintext)")  # fmt: skip
    if not _on(inp.env.get("SMTP_TLS_VERIFY"), True):
        why = "its certificate is not checked (SMTP_TLS_VERIFY=false)"
        return Check("mail_relay", "WARN", f"{host}:{port} answers; {why}: each start is audited (mail.tls_unverified)")
    cafile = (inp.env.get("TB_EXTRA_CA") or "").strip()
    try:
        p.mail_cert(host, port, cafile, CONNECT_TIMEOUT_S)
    except (ssl.SSLError, ssl.CertificateError) as e:
        how = "name the hospital's CA in TB_EXTRA_CA, or turn the check off for it (SMTP_TLS_VERIFY=false, audited)"
        return Check("mail_relay", "FAIL", f"{host}:{port}: its certificate is not trusted ({e}); {how}")
    except (OSError, ValueError) as e:  # smtplib's errors are OSErrors; a relay without STARTTLS raises one too
        return Check(
            "mail_relay", "FAIL", f"{host}:{port}: the certificate could not be tested ({type(e).__name__}: {e})"
        )
    return Check("mail_relay", "PASS", f"{host}:{port} answers" + (" (TLS)" if port == SMTPS_PORT else "")
                 + ", certificate verified")  # fmt: skip


def _on(value: str | None, default: bool) -> bool:
    """A yes/no setting as tb_common.config reads it; empty is the default."""
    v = (value or "").strip().lower()
    return default if not v else v in ("1", "true", "yes", "on")


def check_disk(inp: DoctorInputs, p: Probes) -> Check:
    """Free space where the box keeps its data: Docker's data root (the databases, as ``deploy/check_host.sh``
    judges it) and the deploy folder (backups' staging, the lake's files); the worst decides."""
    places = [_deploy(inp)]
    root = p.docker_root()
    if root is not None and root.is_dir() and root not in places:
        places.append(root)
    worst: Status = "PASS"
    facts = []
    for where in places:
        u = p.disk_usage(where)
        pct = int(100 * u.free / u.total) if u.total else 0
        line = f"{where}: {u.free / 1024**3:.0f} GiB free ({pct}%)"
        if pct < FREE_FAIL_PCT:
            worst, line = "FAIL", f"{line}, below {FREE_FAIL_PCT}%"
        elif pct < FREE_WARN_PCT:
            worst = "WARN" if worst == "PASS" else worst
            line = f"{line}, below {FREE_WARN_PCT}%"
        facts.append(line)
    return Check("disk", worst, "; ".join(facts))


def _hardening(inp: DoctorInputs) -> dict[str, str]:
    conf = _deploy(inp) / "site" / "hardening.conf"
    out: dict[str, str] = {}
    try:
        lines = conf.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        k, sep, v = line.partition("=")
        if sep and not k.strip().startswith("#"):
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def check_tpm_tang(inp: DoctorInputs, p: Probes) -> Check:
    """What protects the box's keys, as the box uses it.

    * The KEK (``deploy/hardening/seal_keys.sh``): ``KEK_BACKEND`` (``TB_KEK_BACKEND`` wins; tpm when neither says)
      is tpm, shamir or passphrase. tpm needs a usable TPM 2.0 (red without one); shamir and passphrase open the
      keys only with people at each start (amber); any other word is red (the seal step refuses it).
    * The disk unlock (``deploy/hardening/disk-unlock.sh``): with ``TANG_URLS`` set it needs the TPM and one Tang
      server answering, both (red otherwise); without them the disk is not bound to Tang (said on the line).

    Green only for a TPM-sealed KEK on a usable TPM, with a disk unlock that has what it needs."""
    conf = _hardening(inp)
    backend = (inp.env.get("TB_KEK_BACKEND") or conf.get("KEK_BACKEND") or "tpm").strip()
    tpm = p.tpm()
    urls = conf.get("TANG_URLS", "").split()
    reached: list[str] = []
    failed: list[str] = []
    for u in urls:
        s = urlsplit(u)
        try:
            p.reach(s.hostname or "", s.port or (443 if s.scheme == "https" else 80), CONNECT_TIMEOUT_S)
            reached.append(u)
        except (OSError, ValueError) as e:
            failed.append(f"{u} ({type(e).__name__})")
    bad: list[str] = []
    soft: list[str] = []
    kek = ""
    if backend not in KEK_BACKENDS:
        bad.append(f"KEK_BACKEND={backend} is not one the box seals with ({', '.join(KEK_BACKENDS)})")
    elif backend == "tpm" and not tpm:
        bad.append("keys: KEK_BACKEND=tpm but this board has no usable TPM 2.0")
    elif backend == "tpm":
        kek = "keys: sealed to the TPM 2.0"
    else:
        soft.append(f"keys: KEK_BACKEND={backend}, opened only by people at each start (no TPM seal)")
    disk = "disk unlock: not bound to Tang (TANG_URLS empty; deploy/hardening/disk-unlock.sh)"
    if urls and not tpm:
        bad.append("disk unlock: Tang is set (TANG_URLS) but it needs the TPM too, and there is none")
    if urls and not reached:
        bad.append(f"disk unlock: no Tang server answers ({', '.join(failed)})")
    if urls and tpm and reached:
        disk = f"disk unlock: TPM and Tang {', '.join(reached)}" + (
            f"; not answering: {', '.join(failed)}" if failed else ""
        )
    told = [disk] if not any(b.startswith("disk unlock") for b in bad) else []
    if bad:
        return Check("tpm_tang", "FAIL", "; ".join(bad + soft + told))
    if soft:
        return Check("tpm_tang", "WARN", "; ".join(soft + told))
    return Check("tpm_tang", "PASS", "; ".join([kek, *told]))


def _ram_gib(inp: DoctorInputs) -> float | None:
    try:
        for line in (inp.proc / "meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024**2
    except (OSError, ValueError, IndexError):
        return None
    return None


def check_gpu_tier(inp: DoctorInputs, p: Probes) -> Check:
    """Every card, its memory and the host's memory against this box's tier record (``models/tiers/<profile>.json``;
    the profile from ``TB_PROFILE`` as ``tb_common.tier_value`` reads it). A card matches when its name contains one
    of the record's ``card_names``: ``deploy/gpu_profile.sh``'s own rule, which chose the profile (so "RTX 5090 D"
    is a 5090 there too). The record's stated values are compared whatever their basis: this asks whether the
    machine is the one the record is about, not for a tuning value (D-1322 is about those)."""
    from tb_common import tier_value

    profile = tier_value.profile_of(inp.env)
    mode = (inp.env.get("TB_LLM_MODE") or "").strip()
    if profile is None:
        label = (inp.env.get("TB_PROFILE") or "").strip() or "(unset)"
        if mode == "vllm":
            return Check("gpu_tier", "WARN", f"no tier record for TB_PROFILE {label}: the card is not compared")
        return Check("gpu_tier", "PASS", f"no model on a graphics card here (TB_LLM_MODE={mode or 'unset'})")
    path = (p.tiers_dir or tier_value.TIERS_DIR) / f"{profile}.json"
    try:
        fields = json.loads(path.read_text(encoding="utf-8"))["fields"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return Check("gpu_tier", "FAIL", f"the tier record {path.name} cannot be read ({type(e).__name__})")

    def stated(name: str) -> Any:
        f = fields.get(name) if isinstance(fields, dict) else None
        return f.get("value") if isinstance(f, dict) else None

    cards = p.gpus()
    if not cards:
        return Check("gpu_tier", "FAIL", f"no graphics card answers (nvidia-smi); the tier record {profile} names one")
    names = [str(n) for n in stated("card_names") or ()]
    want = stated("card_memory_mib")

    def fits(card: str, mem: float) -> list[str]:
        why = []
        if names and not any(n.lower() in card.lower() for n in names):
            why.append(f"the card is {card!r}, the record names {' or '.join(names)}")
        if isinstance(want, int | float) and want and abs(mem - want) / want > GPU_MEM_TOLERANCE:
            why.append(f"{card!r} has {mem:.0f} MiB, the record {want} MiB")
        return why

    judged = [(c, m, fits(c, m)) for c, m in cards]
    good = [(c, m) for c, m, why in judged if not why]
    bad = [w for _, _, why in judged for w in why]
    ram, ram_min = _ram_gib(inp), stated("host_memory_gib_min")
    host_bad = ram is not None and isinstance(ram_min, int | float) and ram < ram_min * 0.95
    if not good or host_bad:
        if host_bad:
            bad.append(f"the host has {ram:.0f} GiB, the record asks {ram_min} GiB or more")
        return Check("gpu_tier", "FAIL", f"tier record {profile}: " + "; ".join(bad))
    card, mem = good[0]
    facts = f"{card}, {mem:.0f} MiB: as the tier record {profile} states"
    soft = [f"another card does not match: {'; '.join(bad)}"] if bad else []
    if ram is None:
        soft.append(f"the host's memory could not be read ({inp.proc / 'meminfo'}): not compared")
    if soft:
        return Check("gpu_tier", "WARN", f"{facts}; " + "; ".join(soft))
    return Check("gpu_tier", "PASS", facts)


def _clock(inp: DoctorInputs, p: Probes) -> Check:
    return doctor.check_clock(inp)


CHECKS: dict[str, Callable[[DoctorInputs, Probes], Check]] = {
    "name_cert": check_name_cert,
    "clock": _clock,
    "backup_share": check_backup_share,
    "audit_share": check_audit_share,
    "feed": check_feed,
    "mail_relay": check_mail_relay,
    "disk": check_disk,
    "tpm_tang": check_tpm_tang,
    "gpu_tier": check_gpu_tier,
}
if tuple(CHECKS) != text.IDS:  # pragma: no cover - a list edited on one side only
    raise ImportError("tb_common.preflight.ITEMS and the checks of tools.trialbox.preflight must be one list")


# ------------------------------------------------------------------------------------------------ run and show
def _bounded(cid: str, fn: Callable[[], Check], seconds: float) -> Check:
    """``fn`` in a thread of its own, waited for ``seconds``: a check that hangs (a hard-mounted share, a resolver)
    is a red line and the run goes on. The thread is left behind (a daemon); the installer's overall time limit
    ends the process."""
    box: list[Check] = []

    def go() -> None:
        try:
            box.append(fn())
        except Exception as e:
            box.append(Check(cid, "FAIL", f"check error: {type(e).__name__}: {e}"))

    t = threading.Thread(target=go, name=f"preflight-{cid}", daemon=True)
    t.start()
    t.join(seconds)
    if not box:
        return Check(cid, "FAIL", f"{text.TIMEOUT_PREFIX} after {seconds:g} s: a share, a server or a device did "
                     "not answer")  # fmt: skip
    return box[0]


def run(
    inp: DoctorInputs,
    probes: Probes | None = None,
    per_check_s: float = CHECK_TIMEOUT_S,
    total_s: float = RUN_TIMEOUT_S,
) -> list[Check]:
    """Every preflight check in the list's order; a check that raises or does not finish in ``per_check_s`` is a FAIL
    (fail closed, as ``doctor.run``), and so is every check left when the run's ``total_s`` is used up: the file is
    written within the installer's limit (``TB_BOX_PREFLIGHT_S``, 90 s) whatever hangs."""
    p = probes or Probes()
    out: list[Check] = [Check("inputs", "FAIL", why) for why in inp.input_errors]
    end = time.monotonic() + total_s
    for cid, fn in CHECKS.items():
        left = end - time.monotonic()
        if left <= 0:
            out.append(Check(cid, "FAIL", f"{text.TIMEOUT_PREFIX}: the preflight's {total_s:g} s were used up first"))
            continue
        c = _bounded(cid, lambda fn=fn: fn(inp, p), min(per_check_s, left))  # type: ignore[misc]
        out.append(Check(cid, c.status, c.detail))
    return out


def render(checks: list[Check], lang: str = "en", color: bool = False) -> str:
    """``doctor``'s lines, each with its label in ``lang``; a line of the list that is not green has its next action
    under it, and a FAIL is red when ``color`` is on (a terminal)."""
    lg = text.lang_of(lang)
    lines: list[str] = []
    for c in checks:
        head = f"{c.status:<5} {c.name:<14} {text.label(c.name, lg)}: {c.detail}"
        lines.append(f"{RED}{head}{RESET}" if color and c.status == "FAIL" else head)
        if c.status != "PASS" and c.name in text.BY_ID:
            lines.append(f"      -> {text.action(c.name, lg, c.detail)}")
    lines.append("---")
    lines.append(text.summary(sum(c.status == "FAIL" for c in checks), lg))
    return "\n".join(lines)


def as_json(checks: list[Check]) -> list[dict[str, Any]]:
    """``doctor --json``'s lines with the list's group, and the label and action in every language."""
    return [
        {**c.__dict__, "group": text.BY_ID[c.name].group if c.name in text.BY_ID else "",
         "label": {lg: text.label(c.name, lg) for lg in text.LANGS},
         "action": {lg: text.action(c.name, lg, c.detail) for lg in text.LANGS} if c.status != "PASS" else {}}
        for c in checks
    ]  # fmt: skip


def write(checks: list[Check], out: Path, now: datetime | None = None) -> Path:
    """The file the first-run page shows (``tb_common.preflight.FILE``), readable by its owner only."""
    from tb_common import firstrun

    doc = text.document(
        ({"id": c.name, "status": c.status, "detail": c.detail} for c in checks),
        (now or datetime.now(UTC)).isoformat(timespec="seconds"),
    )
    firstrun.write_private(out, doc)
    return out


def color_on() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")
