"""The live preflight (plan 10 row 10K-3, review 18 SO-3, D-1361): the checks of ``tb_common.preflight.ITEMS``.

    python -m tools.trialbox doctor --preflight --env-file deploy/.env [--settings deploy/settings.yaml] [--lang ja]
    python -m tools.trialbox doctor --preflight --env-file deploy/.env --out /run/trialbox-firstrun/preflight.json
    python -m tools.settings_wizard --answers site.yaml --env-out deploy/.env --preflight

Every check is read-only and needs no internet: it lists folders, asks the file system whether this process may
write (``os.access``, nothing is written), resolves the box's name with the hospital's resolver, opens a connection
to the hospital's mail relay or Tang server and closes it, asks ``nvidia-smi`` and the TPM. A check that raises is a
FAIL (as ``doctor``). The clock is ``doctor``'s own ``check_clock``; the certificate is the console's own
``check_tls``; the backup targets are read and classified by ``backup_schedule``; the audit folders by ``anchors``;
the tier record by ``tb_common.tier_value``'s path and profile rule. Each line is printed with the next action from
``tb_common.preflight`` in the language asked.

The feed is counted, never read: the number of readable files under the feed folder, no name and no content.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import sys
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
CONNECT_TIMEOUT_S = 3.0
RED = "\033[31m"
RESET = "\033[0m"


def _resolve(host: str) -> list[str]:
    return sorted({str(a[4][0]) for a in socket.getaddrinfo(host, None)})


def _banner(host: str, port: int, timeout: float) -> str:
    """Opens a connection, reads the server's first line, says QUIT and closes: nothing is sent."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        line = s.recv(512).decode("ascii", "replace").strip()
        with contextlib.suppress(OSError):
            s.sendall(b"QUIT\r\n")
        return line


def _reach(host: str, port: int, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout):
        return "open"


def _gpu() -> tuple[str, float] | None:
    from tools.box.plan import _run

    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    line = out.strip().splitlines()[0] if out.strip() else ""
    name, _, mem = line.partition(",")
    try:
        return name.strip(), float(mem.strip())
    except ValueError:
        return None


def _tpm() -> bool:
    from tools.box.plan import tpm_usable

    return tpm_usable()


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
    banner: Callable[[str, int, float], str] = _banner  # the mail relay's first line
    reach: Callable[[str, int, float], str] = _reach  # a Tang server's port
    gpu: Callable[[], tuple[str, float] | None] = _gpu  # (card name, memory MiB)
    tpm: Callable[[], bool] = _tpm
    disk_usage: Callable[[Path], Any] = shutil.disk_usage
    euid: Callable[[], int] = _euid
    tiers_dir: Path | None = None  # tb_common.tier_value.TIERS_DIR when None


def _env(inp: DoctorInputs) -> str:
    return (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()


def _deploy(inp: DoctorInputs) -> Path:
    return inp.deploy or doctor.ROOT / "deploy"


# ------------------------------------------------------------------------------------------------ checks
def check_name_cert(inp: DoctorInputs, p: Probes) -> Check:
    """The console's name resolves on the hospital's network, and the certificate Caddy will use names it and is valid
    (``console.identity.check_tls``)."""
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
    if not addrs and host.endswith(".local"):  # OPS-005: the box takes this name and answers it (mDNS) at its apply
        why = f"{host} does not resolve yet ({why}): the box answers its .local name itself once the set-up is applied"
        return Check("name_cert", "WARN", f"{why}; a computer that cannot resolve .local uses the address")
    if not addrs:
        return Check("name_cert", "FAIL", f"{host} does not resolve here ({why})")
    try:
        from console.identity import check_tls
    except ImportError as e:  # a host python without the console's libraries
        return Check("name_cert", "WARN", f"{host} is {', '.join(addrs)}; the certificate not checked here ({e.name})")
    tls = check_tls(inp.env)
    if tls.problems:
        return Check("name_cert", "FAIL", f"{host} is {', '.join(addrs)}; " + "; ".join(tls.problems))
    note = f"; {tls.notes[0]}" if tls.notes else ""
    return Check("name_cert", "PASS", f"{host} is {', '.join(addrs)}; certificate mode {tls.mode}{note}")


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
        off += cfg.classify(t).offbox
    if not off and not bad:
        bad.append("every target is on the box's own disk: a lost box loses its backups")
    facts = f"{len(cfg.targets)} target(s), {off} off the box"
    if bad:
        return Check("backup_share", "FAIL", "; ".join(bad) + f" ({facts})")
    return Check("backup_share", "PASS", f"{facts}, each writable")


def check_audit_share(inp: DoctorInputs, p: Probes) -> Check:
    """The anchor folders (``TB_AUDIT_ANCHOR_TARGETS``) are off the box, the box can add the nightly signed head, and
    the box's root cannot change a signed head already there (a write-once share, or root mapped to nobody)."""
    from tools.trialbox import anchors

    try:
        folders = [Path(h) for h, _ in anchors.plan(inp.env)]
    except anchors.AnchorError as e:
        return Check("audit_share", "FAIL", str(e))
    if not folders:
        status: Status = "FAIL" if _env(inp) == "PRODUCTION" else "WARN"
        return Check("audit_share", status, f"no audit share is set ({anchors.ENV})")
    own = {_dev(Path("/")), _dev(_deploy(inp))} - {None}
    bad: list[str] = []
    unjudged: list[str] = []
    root = p.euid() == 0
    for f in folders:
        if not f.is_dir():
            bad.append(f"{f} is not there (not mounted?)")
            continue
        if _dev(f) in own:
            bad.append(f"{f} is on the box's own disk")
            continue
        if not p.writable(f / "heads" if (f / "heads").is_dir() else f):
            bad.append(f"{f}: the box cannot add the nightly signed head")
            continue
        heads = sorted((f / "heads").glob("*.json")) if (f / "heads").is_dir() else []
        if not heads:
            unjudged.append(f"{f}: no signed head yet, judged after the first night")
        elif not root:
            unjudged.append(f"{f}: run as root to see whether root can change a signed head")
        elif any(p.writable(h) for h in heads):
            bad.append(f"{f}: the box's root can change a signed head")
    if bad:
        return Check("audit_share", "FAIL", "; ".join(bad + unjudged))
    if unjudged:
        return Check("audit_share", "WARN", "; ".join(unjudged))
    return Check("audit_share", "PASS", f"{len(folders)} folder(s) off the box; root cannot change a signed head")


def _dev(path: Path) -> int | None:
    try:
        return path.stat().st_dev
    except OSError:
        return None


def check_feed(inp: DoctorInputs, p: Probes) -> Check:
    """The feed folder is there and readable; the line gives the number of readable files (no name, no content)."""
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
    if not os.access(folder, os.R_OK | os.X_OK):
        return Check("feed", "FAIL", f"the feed folder {folder} is not readable by the box")
    count = unreadable = 0
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            if os.access(os.path.join(top, name), os.R_OK):
                count += 1
            else:
                unreadable += 1
        if count >= FEED_CAP:
            break
    many = "at least " if count >= FEED_CAP else ""
    if unreadable:
        return Check("feed", "FAIL", f"{folder}: {many}{count} file(s) readable, {unreadable} not readable by the box")
    if not count:
        return Check("feed", "FAIL", f"{folder} holds no file yet")
    return Check("feed", "PASS", f"{folder}: {many}{count} file(s) readable ({kind or 'feed'})")


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
    return Check("mail_relay", "PASS", f"{host}:{port} answers")


def check_disk(inp: DoctorInputs, p: Probes) -> Check:
    """Free space where the box keeps its data (the deploy folder's disk), as ``deploy/check_host.sh`` judges it."""
    where = _deploy(inp)
    u = p.disk_usage(where)
    pct = int(100 * u.free / u.total) if u.total else 0
    facts = f"{where}: {u.free / 1024**3:.0f} GiB free ({pct}%)"
    if pct < FREE_FAIL_PCT:
        return Check("disk", "FAIL", f"{facts}, below {FREE_FAIL_PCT}%")
    if pct < FREE_WARN_PCT:
        return Check("disk", "WARN", f"{facts}, below {FREE_WARN_PCT}%")
    return Check("disk", "PASS", facts)


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
    """The site keys can be held by a TPM 2.0 of this board, or by a Tang server the box reaches
    (``deploy/site/hardening.conf``: ``KEK_BACKEND``, ``TANG_URLS``; ``TB_KEK_BACKEND`` wins, as in seal_keys.sh)."""
    conf = _hardening(inp)
    backend = (inp.env.get("TB_KEK_BACKEND") or conf.get("KEK_BACKEND") or "").strip()
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
    if backend == "tpm" and not tpm:
        return Check("tpm_tang", "FAIL", "KEK_BACKEND=tpm but this board has no usable TPM 2.0")
    if urls and not reached:
        return Check("tpm_tang", "FAIL", f"no Tang server answers: {', '.join(failed)}")
    have = (["a usable TPM 2.0"] if tpm else []) + ([f"Tang {', '.join(reached)}"] if reached else [])
    if have:
        return Check(
            "tpm_tang", "PASS", " and ".join(have) + (f"; not answering: {', '.join(failed)}" if failed else "")
        )
    return Check("tpm_tang", "WARN", "no TPM 2.0 and no Tang server: the keys open only with the passphrase "
                 f"typed at each start (KEK_BACKEND={backend or 'not set'})")  # fmt: skip


def _ram_gib(inp: DoctorInputs) -> float | None:
    try:
        for line in (inp.proc / "meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024**2
    except (OSError, ValueError, IndexError):
        return None
    return None


def check_gpu_tier(inp: DoctorInputs, p: Probes) -> Check:
    """The card, its memory and the host's memory against this box's tier record (``models/tiers/<profile>.json``;
    the profile from ``TB_PROFILE`` as ``tb_common.tier_value`` reads it). The record's stated values are compared
    whatever their basis: this check asks whether the machine is the one the record is about, not for a tuning value."""
    import json

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

    got = p.gpu()
    if got is None:
        return Check("gpu_tier", "FAIL", f"no graphics card answers (nvidia-smi); the tier record {profile} names one")
    card, mem = got
    bad: list[str] = []
    names = [str(n) for n in stated("card_names") or ()]
    if names and not any(n.lower() in card.lower() for n in names):
        bad.append(f"the card is {card!r}, the record names {' or '.join(names)}")
    want = stated("card_memory_mib")
    if isinstance(want, int | float) and want and abs(mem - want) / want > GPU_MEM_TOLERANCE:
        bad.append(f"the card has {mem:.0f} MiB, the record {want} MiB")
    ram, ram_min = _ram_gib(inp), stated("host_memory_gib_min")
    if ram is not None and isinstance(ram_min, int | float) and ram < ram_min * 0.95:
        bad.append(f"the host has {ram:.0f} GiB, the record asks {ram_min} GiB or more")
    if bad:
        return Check("gpu_tier", "FAIL", f"tier record {profile}: " + "; ".join(bad))
    return Check("gpu_tier", "PASS", f"{card}, {mem:.0f} MiB: as the tier record {profile} states")


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
def run(inp: DoctorInputs, probes: Probes | None = None) -> list[Check]:
    """Every preflight check in the list's order; a check that raises is a FAIL (fail closed, as ``doctor.run``)."""
    p = probes or Probes()
    out: list[Check] = [Check("inputs", "FAIL", why) for why in inp.input_errors]
    for cid, fn in CHECKS.items():
        try:
            c = fn(inp, p)
        except Exception as e:
            c = Check(cid, "FAIL", f"check error: {type(e).__name__}: {e}")
        out.append(Check(cid, c.status, c.detail))
    return out


def render(checks: list[Check], lang: str = "en", color: bool = False) -> str:
    """``doctor``'s lines, each with its label in ``lang``; a line that is not green has its next action under it, and
    a FAIL is red when ``color`` is on (a terminal)."""
    lg = text.lang_of(lang)
    lines: list[str] = []
    for c in checks:
        head = f"{c.status:<5} {c.name:<14} {text.label(c.name, lg)}: {c.detail}"
        lines.append(f"{RED}{head}{RESET}" if color and c.status == "FAIL" else head)
        act = text.action(c.name, lg) if c.status != "PASS" else ""
        if act:
            lines.append(f"      -> {act}")
    fails = sum(c.status == "FAIL" for c in checks)
    lines.append("---")
    done = {"en": "preflight passed", "ja": "事前確認はすべて合格です", "zh-TW": "事前檢查全部通過"}
    failed = {"en": "{n} check(s) failed", "ja": "{n} 件の確認が不合格です", "zh-TW": "{n} 項檢查未通過"}
    lines.append(done[lg] if not fails else failed[lg].format(n=fails))
    return "\n".join(lines)


def as_json(checks: list[Check]) -> list[dict[str, Any]]:
    """``doctor --json``'s lines with the list's group, and the label and action in every language."""
    return [
        {**c.__dict__, "group": text.BY_ID[c.name].group if c.name in text.BY_ID else "",
         "label": {lg: text.label(c.name, lg) for lg in text.LANGS},
         "action": {lg: text.action(c.name, lg) for lg in text.LANGS} if c.status != "PASS" else {}}
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
