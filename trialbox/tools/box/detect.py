"""What the box's own network, disks and records suggest for the questions that stay (M1): the mail relay and the
mailbox server, where backups and the audit record could go, how a chart number is written.

Proposals only: nothing here is applied. The page "Information still needed" shows them filled in, and a person
confirms each. The functions that read the machine are separate from the ones that decide, so a recorded network and
disk description gives the same proposal in a test. No chart number is kept: only its form is.

A name that resolves to a public address is never connected to: the hospital's relay is inside the hospital.
"""

from __future__ import annotations

import csv
import ipaddress
import json
import re
import socket
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from tools.box.plan import Disk, parse_lsblk

RELAY_PORTS, MAILBOX_PORTS = (587, 465, 25), (993, 143)
NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3")
PROPOSALS = Path("ops") / "needs-proposals.json"  # under deploy/: the console reads it in its operations folder
MAX_ROWS = 500  # the first records are enough to see the form of a number
_CHART_COLUMNS = (
    "mrn",
    "chart_no",
    "chartno",
    "chart_number",
    "病歷號",
    "病歷號碼",
    "患者id",
    "患者番号",
    "カルテ番号",
)
_MX = re.compile(r"\bMX\s+\d+\s+(\S+?)\.?\s*$|mail is handled by\s+\d+\s+(\S+?)\.?\s*$", re.M)


# ------------------------------------------------------------------------------------------------ decide (pure)
def server(hosts: Sequence[str], ports: Sequence[int], is_open: Callable[[str, int], bool]) -> tuple[str, int] | None:
    return next(((h, p) for h in hosts for p in ports if is_open(h, p)), None)


def mx_hosts(text: str) -> list[str]:
    found = [(a or b).lower() for a, b in _MX.findall(text)]
    return list(dict.fromkeys(h for h in found if "." in h))


def shares(mounts: str) -> list[str]:
    """The network folders mounted on this machine, from ``/proc/mounts``."""
    rows = [ln.split() for ln in mounts.splitlines()]
    return [r[1] for r in rows if len(r) >= 3 and r[2] in NETWORK_FS]


def storage(disks: Iterable[Disk], mounted: Sequence[str]) -> dict[str, str]:
    """Where backups and the audit record could go. A share whose name says audit is the audit share; a share is
    proposed for one of the two, never for both."""
    out: dict[str, str] = {}
    audit = [m for m in mounted if "audit" in m.lower()]
    rest = [m for m in mounted if m not in audit]
    if audit:
        out["anchor_dir"] = audit[0]
    disk = next((m for d in disks for m in d.mounted.split(",") if m.startswith("/") and m != "/"), "")
    if rest or disk:
        out["backup_dir"] = rest[0] if rest else disk
    return out


def chart_form(values: Iterable[str]) -> str:
    """The rule (``tb_common.chartno``) the numbers are written by, or "": not all of one width, or no pattern."""
    seen = {v.strip() for v in values if v and v.strip()}
    widths = {len(v) for v in seen}
    if len(seen) < 20 or len(widths) != 1:  # ponytail: one width only; a site with two formats confirms it by hand
        return ""
    width = widths.pop()
    if all(v.isascii() and v.isdigit() for v in seen):
        return f"digits:{width}"
    if all(re.fullmatch(r"[0-9A-Fa-f]+", v) for v in seen):
        return f"hex:{width}"
    return ""


def propose(
    *,
    mx: Sequence[str] = (),
    is_open: Callable[[str, int], bool] = lambda _h, _p: False,
    disks: Iterable[Disk] = (),
    mounted: Sequence[str] = (),
    charts: Iterable[str] = (),
) -> dict[str, str]:
    """The proposals by answer name; what was not found is not there (the page says "not found")."""
    out = storage(disks, mounted)
    relay, box = server(mx, RELAY_PORTS, is_open), server(mx, MAILBOX_PORTS, is_open)
    if relay:
        out |= {"smtp_host": relay[0], "smtp_port": str(relay[1])}
    if box:
        out |= {"imap_host": box[0]}
    if form := chart_form(charts):
        out["chartno_rule"] = form
    return out


# ------------------------------------------------------------------------------------------------ read the machine
def chart_numbers(folder: Path) -> list[str]:
    """The first chart numbers of a records folder: the column of a patient sheet, or the folders of an SS-MIX2
    storage (``<first 3>/<next 3>/<id>``). Read-only; the caller keeps none."""
    out: list[str] = []
    for f in sorted(folder.glob("*.csv")):
        try:
            with f.open(encoding="utf-8-sig", newline="") as fh:
                rows = csv.reader(fh)
                head = [h.strip().lower() for h in next(rows, [])]
                at = next((head.index(c) for c in _CHART_COLUMNS if c in head), None)
                if at is None:
                    continue
                for r in rows:
                    if at < len(r):
                        out.append(r[at])
                    if len(out) >= MAX_ROWS:
                        return out
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    if not out:
        for p in folder.glob("[0-9]" * 3 + "/" + "[0-9]" * 3 + "/*"):
            out.append(p.name)
            if len(out) >= MAX_ROWS:
                break
    return out


def inside(host: str, port: int, seconds: float = 2.0) -> bool:  # pragma: no cover - the network
    """Whether a server inside the hospital answers on ``port``; a public address is never connected to."""
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not found or any(not ipaddress.ip_address(a[4][0]).is_private for a in found):
            return False
        with socket.create_connection((str(found[0][4][0]), port), timeout=seconds):
            return True
    except (OSError, ValueError):
        return False


def _run(cmd: list[str]) -> str:  # pragma: no cover - the machine
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def write(deploy: Path) -> dict[str, str]:  # pragma: no cover - the machine
    """This machine's proposals into the operations folder the console reads; a failure writes none and stops
    nothing."""
    from tools.box.__main__ import write_whole
    from tools.trialbox.finish_check import read_env

    env = read_env(deploy / ".env")
    domain = (env.get("TB_BACKUP_MAILTO") or "@").split("@", 1)[1]
    mx = mx_hosts(_run(["resolvectl", "query", "--legend=no", "--type=MX", domain])) if domain else []
    src = env.get("TB_SOURCE_DIR") or ""
    folder = Path(src) if src.startswith("/") else deploy / src
    mounts = Path("/proc/mounts")
    got = propose(
        mx=mx,
        is_open=inside,
        disks=parse_lsblk(_run(["lsblk", "-J", "-b", "-o", "PATH,SIZE,TYPE,TRAN,MOUNTPOINT"])),
        mounted=shares(mounts.read_text(encoding="utf-8")) if mounts.is_file() else [],
        charts=chart_numbers(folder) if src and folder.is_dir() else [],
    )
    write_whole(deploy / PROPOSALS, json.dumps(got, ensure_ascii=False) + "\n", 0o644)
    return got
