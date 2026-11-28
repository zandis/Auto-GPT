"""planted_faults: plant each fault of card H-32 on a box this machine runs, and record what a person meets.

Card H-32 (plan 8, V17; D-1110): "plant each fault (backup target gone, disk nearly full, morning mail not sent,
certificate near its end, clock off, model service down, feed folder empty): each shows on the administrator's first
page, in the mail and in ``/metrics``, with a runbook page that works." This tool reports; it fixes nothing.

    python -m tools.planted_faults run --out <record.json> [--fault backup_target ...] [--db-url URL]
    python -m tools.planted_faults faults           # the seven faults, how each is planted, the product's check
    make planted-faults                             # the drill test (tests/e2e/test_planted_faults.py), all seven

**The box.** No Docker daemon runs here, so not the compose box: the in-process box of the console tests and the
demo (``console.app.create_app`` with ``TB_OPS_RUNNER=inline``: the operations runner, the host facts, the health
checks, ``/metrics``, the timers' mail calls and the admin pages are the product's own code in this process), a
throwaway PostgreSQL (``tools.pglocal``) and the orchestrator's in-memory stand-in (``FakeBackend`` of the console
tests). The stand-in is the mail outbox: every notice the console sends is recorded there, as the orchestrator's
``POST /notices`` would hand it to the mail gateway. The backup's own alert route (``TB_BACKUP_ALERT_CMD``) is a
second outbox, a file the command appends to.

**One fault at a time** (:data:`FAULTS`): check the box is green; plant the fault by the least invasive means that
makes the product's own check see it; run the product's tick (``OpsRunner.write_status``, as ``trialbox ops run``
does every minute; the nightly backup and the hourly ``backup-status`` where the fault is the backup's; the 07:00
health mail and the 07:30 digest for a day of the fault's own, as the console's timers call them; the adapter's
night for the feed); read the four surfaces as a person meets them; remove the fault; tick again; read again.

The four surfaces (D-1110 fixes what "shows" means): (1) the administrator's first page after sign-in (``/``, which
is the ``/admin`` Health tab for an administrator) in en, zh-TW and ja: the lines that are new against the green
page; (2) the mail: every mail sent in the fault's round and the backup alert route; (3) ``/metrics``: every
``tb_health_check_level`` line and ``tb_health_level``; (4) the runbook: what page the line or mail names, whether it
exists, and the page's steps that run on this box, run as written (with the box's deploy folder where the page's
command reads ``deploy/``) and timed. A step that needs Docker is listed, not run.

Each fault says whether it is planted as the real condition or by a stand-in (:attr:`Fault.planted`). Nothing here
reads a secret, a key file or a patient row; the box is synthetic.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
LANGS = ("en", "zh-TW", "ja")
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
RUNBOOK_DIR = ROOT / "docs" / "runbook"
LEVELS = {0: "ok", 1: "warn", 2: "red"}
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")


# ------------------------------------------------------------------------------------------------ the faults
@dataclass(frozen=True)
class Step:
    """One step of a runbook page, quoted. ``cmd``: the command as the page writes it, run on this box (``{deploy}``,
    ``{py}`` filled in); empty when the step needs what this box has not (``needs``)."""

    page: str  # path below trialbox/
    line: int
    quote: str
    cmd: tuple[str, ...] = ()
    needs: str = ""


@dataclass(frozen=True)
class Fault:
    key: str
    words: str  # the card's words
    planted: str  # how, and whether it is the real condition or a stand-in
    checks: tuple[str, ...]  # the product's health checks (``/metrics`` names; ``disk:`` a prefix) that should see it
    other_check: str  # a check of the product outside /metrics that sees it (doctor, the adapter), or ""
    keywords: Mapping[str, tuple[str, ...]]  # per page language: words a line about this fault carries
    runbook: str  # the page a person should land on (path below trialbox/), or "" when the runbook has none
    steps: tuple[Step, ...] = ()


DISK_KW = ("disk", "full")
FAULTS: tuple[Fault, ...] = (
    Fault(
        "backup_target",
        "backup target gone",
        "real when root: the NAS target is a tmpfs mount, unmounted (gone) and then remounted read-only (unwritable); "
        "else chmod 0555 on the target folder. Then the nightly backup (backup_schedule.nightly with the in-process "
        "box's backup.backup) and the hourly backup-status (status, alert) run as cron runs them",
        ("backup", "backup_verified"),
        "",
        {"en": ("backup",), "zh-TW": ("備份",), "ja": ("バックアップ",)},
        "docs/runbook/05-updates-backup-restore-secrets.md",
        (
            Step(
                "docs/runbook/05-updates-backup-restore-secrets.md",
                145,
                "`python3 -m tools.trialbox backup-status` shows the newest good off-box backup",
                ("{py}", "-m", "tools.trialbox", "backup-status", "--deploy", "{deploy}"),
            ),
            Step(
                "docs/runbook/05-updates-backup-restore-secrets.md",
                151,
                "Fix the cause, then run `backup-nightly` by hand.",
                needs="Docker (backup-nightly runs the compose backup container); the drill runs the same nightly "
                "function with the in-process box's backup writer after the target is back",
            ),
        ),
    ),
    Fault(
        "disk_full",
        "disk nearly full",
        "real when root: a 16 MiB tmpfs named in TB_HEALTH_DISKS (the product's own setting for the disks it "
        "watches) filled to about 94 % with a junk file; else planted by a stand-in (shutil.disk_usage answers 94 % "
        "for every path on that folder's device, which the product measures by its first path)",
        ("disk:",),
        "",
        {"en": DISK_KW, "zh-TW": ("磁碟",), "ja": ("ディスク",)},
        "docs/runbook/04-disk-full.md",
        (
            Step(
                "docs/runbook/04-disk-full.md",
                11,
                "`df -h /data /var/lib/docker /` and `docker system df`. Note which disk is full.",
                ("df", "-h", "/data", "/var/lib/docker", "/"),
            ),
            Step(
                "docs/runbook/04-disk-full.md",
                12,
                "`python3 -m tools.trialbox backup-status`",
                ("{py}", "-m", "tools.trialbox", "backup-status", "--deploy", "{deploy}"),
            ),
            Step("docs/runbook/04-disk-full.md", 15, "`tools/apply_update.sh clean`", needs="a box's /opt/trialbox"),
            Step("docs/runbook/04-disk-full.md", 16, "`docker image prune`", needs="Docker"),
        ),
    ),
    Fault(
        "morning_mail",
        "morning mail not sent",
        "real: the 07:00 and 07:30 timers do not run for the fault's day (the console timers held back, as on a box "
        "whose TB_CONSOLE_TIMERS is off or whose console was down at 07:30); the mail path itself is not touched",
        (),
        "",
        {"en": ("notice", "mail"), "zh-TW": ("通知", "郵件"), "ja": ("通知", "メール")},
        "docs/runbook/04-morning-mail-missing.md",
        (
            Step(
                "docs/runbook/04-morning-mail-missing.md",
                13,
                "the console's login page; the Operations page (§15)",
                needs="a browser: done by the drill as the admin's sign-in",
            ),
            Step(
                "docs/runbook/04-morning-mail-missing.md",
                14,
                "`docker compose logs console --since 12h` names the timer runs",
                needs="Docker",
            ),
            Step(
                "docs/runbook/04-morning-mail-missing.md",
                23,
                "the administrator's **Send notices now** sends the "
                "morning's notices. A notice goes at most once per person and day, so nobody gets two.",
                ("console", "POST /ops/notices"),
            ),
        ),
    ),
    Fault(
        "certificate",
        "certificate near its end",
        "real: TB_TLS_MODE=hospital and TB_TLS_CERT_FILE a self-signed synthetic certificate that ends in 12 days "
        "(the check's red window is 30 days); the green box's certificate ends in 200 days",
        ("certificate",),
        "",
        {"en": ("certificate",), "zh-TW": ("憑證",), "ja": ("証明書",)},
        "docs/runbook/12-certificate-renewal.md",
        (
            Step(
                "docs/runbook/12-certificate-renewal.md",
                15,
                "`python -m console.cli check-tls` warns 30 days before the end.",
                ("{py}", "-m", "console.cli", "check-tls"),
            ),
            Step(
                "docs/runbook/12-certificate-renewal.md",
                21,
                "`docker compose up -d --force-recreate caddy`",
                needs="Docker",
            ),
        ),
    ),
    Fault(
        "clock_off",
        "clock off",
        "real offset, stand-in time server: TB_NTP_SERVER names a local SNTP server (this tool's) that answers 600 s "
        "behind this clock, so the product's own check (doctor's clock check, tb_common.audit.clock_state) measures "
        "the box +600 s ahead; the box's own clock is not changed",
        (),
        "doctor: check_clock",
        {"en": ("clock", "time"), "zh-TW": ("時鐘", "時間"), "ja": ("時計", "時刻")},
        "",
    ),
    Fault(
        "model_down",
        "model service down",
        "stand-in for the model server, the product's own gate: the orchestrator's canary gate (orchestrator."
        "canary_gate.Gate, the real class) records the night's canary as unreached (record_unreached, D-915), as it "
        "does when the model servers do not answer; the console reads it through the backend stand-in's /models. "
        "Two cases: a passing canary of this morning stands (the usual night), and none stands (a box restarted)",
        ("canary",),
        "",
        {"en": ("model",), "zh-TW": ("模型",), "ja": ("モデル",)},
        "docs/runbook/04-gpu-fault.md",
        (
            Step(
                "docs/runbook/04-gpu-fault.md",
                15,
                "`nvidia-smi` on the host ... `docker compose ps`",
                needs="a GPU and Docker",
            ),
            Step(
                "docs/runbook/04-gpu-fault.md",
                21,
                '`sudo python3 -m tools.trialbox selftest` on the box ..., or "Run now" on the admin Models tile',
                needs="the compose stack (the stand-in only counts the call)",
            ),
        ),
    ),
    Fault(
        "feed_empty",
        "feed folder empty",
        "real: the adapter's night (adapter.pipeline.run_ingest, csv, the synthetic site-a mapping) on the feed folder "
        "emptied after a good night; the lake rebuild is the adapter tests' stand-in hook (AdapterConfig.rebuild)",
        (),
        "adapter: the night's ingest.failed or ingest.held",
        {"en": ("feed", "ingest", "source", "export"), "zh-TW": ("資料來源", "匯入"), "ja": ("データ元", "取り込み")},
        "",
    ),
)
BY_KEY = {f.key: f for f in FAULTS}


# ------------------------------------------------------------------------------------------------ reading a page
class _Lines(HTMLParser):
    BLOCK: ClassVar[set[str]] = {
        "p",
        "li",
        "h1",
        "h2",
        "h3",
        "tr",
        "section",
        "div",
        "dt",
        "dd",
        "summary",
        "td",
        "th",
        "br",
        "ul",
    }
    SKIP: ClassVar[set[str]] = {"script", "style", "title", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.hrefs: list[str] = []
        self.skip = 0

    def _flush(self) -> None:
        text = " ".join(" ".join(self.buf).split())
        if text:
            self.lines.append(text + "".join(f" <{h}>" for h in self.hrefs))
        self.buf, self.hrefs = [], []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self._flush()
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href:
                self.hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.buf.append(data)


def page_lines(page: str) -> list[str]:
    """The text lines of a page as a person reads them, a link's target after its line in ``<...>``; the
    ``<main>`` part only when there is one (the header and footer are the same on every page)."""
    m = re.search(r"<main\b.*?</main>", page, re.S)
    p = _Lines()
    p.feed(m.group(0) if m else page)
    p._flush()
    return p.lines


def _norm(line: str) -> str:
    """A line with its numbers and times blanked, so an age that moved is not a new line."""
    return re.sub(r"\d+", "#", line)


def new_lines(before: Sequence[str], after: Sequence[str]) -> list[str]:
    """The lines of ``after`` that ``before`` does not have (numbers ignored), in their order."""
    seen = {_norm(x) for x in before}
    return [x for x in after if _norm(x) not in seen]


def in_language(lang: str, line: str, fault: Fault | None = None) -> bool:
    """Whether a line is written in ``lang``: a zh-TW or ja line carries Chinese characters or kana, and does not
    name the fault in English (a translated level before an English check text is not the reader's language)."""
    if lang == "en":
        return True
    english = fault.keywords.get("en", ()) if fault is not None else ()
    return bool(_CJK.search(line)) and not any(k in line.lower() for k in english)


def about(fault: Fault, lang: str, lines: Sequence[str]) -> list[str]:
    """The lines that speak of the fault, by its keywords in ``lang`` or in English (an untranslated line)."""
    kws = {k.lower() for k in (*fault.keywords.get(lang, ()), *fault.keywords.get("en", ()))}
    return [x for x in lines if any(k in x.lower() for k in kws)]


def page_verdict(fault: Fault, new: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Per language: ``shown`` (a new line about the fault, in that language), ``not in the language`` (only in
    English), ``not shown``; with the lines and whether one carries a link (where to read or what to do)."""
    out: dict[str, Any] = {}
    for lang in LANGS:
        hits = about(fault, lang, new.get(lang, ()))
        local = [x for x in hits if in_language(lang, x, fault)]
        verdict = "shown" if local else "not in the language" if hits else "not shown"
        out[lang] = {"verdict": verdict, "lines": list(hits), "link": any("<" in x for x in hits)}
    return out


# ------------------------------------------------------------------------------------------------ /metrics
_CHECK = re.compile(r'^tb_health_check_level\{check="((?:[^"\\]|\\.)*)"\}\s+(\d+)', re.M)
_LEVEL = re.compile(r"^tb_health_level\{[^}]*\}\s+(\d+)", re.M)


def parse_metrics(text: str) -> dict[str, Any]:
    checks = {m.group(1): LEVELS.get(int(m.group(2)), m.group(2)) for m in _CHECK.finditer(text)}
    lv = _LEVEL.search(text)
    return {"level": LEVELS.get(int(lv.group(1)), "?") if lv else None, "checks": checks}


def _matches(name: str, checks: Sequence[str]) -> bool:
    return any(name == c or (c.endswith(":") and name.startswith(c)) for c in checks)


def metrics_verdict(fault: Fault, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """``shown`` when a check of the fault (or any check) left ``ok``; the checks that moved, with their levels."""
    b, a = before.get("checks") or {}, after.get("checks") or {}
    moved = {n: lv for n, lv in a.items() if lv != "ok" and b.get(n) != lv}
    own = {n: lv for n, lv in moved.items() if _matches(n, fault.checks)}
    return {"verdict": "shown" if own else "shown by another check" if moved else "not shown",
            "moved": moved, "level": after.get("level")}  # fmt: skip


# ------------------------------------------------------------------------------------------------ mail
@dataclass
class Mail:
    route: str  # "notice" (the console's notices) or "backup-alert" (TB_BACKUP_ALERT_CMD)
    kind: str
    to: str
    subject: str
    body: str
    lang: str = "en"


def _green(line: str) -> bool:
    """A line that says a check is fine: ``- [ok] ...`` of the health mail, or the all-green health line."""
    from console.i18n import CATALOGUES

    if line.lstrip().startswith("- [ok]"):
        return True
    heads = [str(CATALOGUES[lg].get("health.line.ok", "")).split("{")[0].strip() for lg in LANGS]
    return any(h and line.startswith(h) for h in heads)


def mail_verdict(fault: Fault, mails: Sequence[Mail], admins: Mapping[str, str]) -> dict[str, Any]:
    """Who got a mail about the fault, how many, and whether its line is in the reader's language. ``admins``: each
    administrator's mailbox and language."""
    rows = []
    for m in mails:
        hits = [x for x in about(fault, m.lang, [m.subject, *m.body.splitlines()]) if not _green(x)]
        if hits:
            rows.append({"route": m.route, "kind": m.kind, "to": m.to, "lang": m.lang, "lines": hits[:4],
                         "in_language": all(in_language(m.lang, x, fault) for x in hits)})  # fmt: skip
    per_admin = {to: sum(r["to"] == to for r in rows) for to in admins}
    if not rows:
        verdict = "not shown"
    elif all(r["in_language"] for r in rows):
        verdict = "shown"
    else:
        verdict = "not in the language"
    return {"verdict": verdict, "mails": rows, "per_admin": per_admin, "sent": len(mails)}


# ------------------------------------------------------------------------------------------------ the runbook
_REF = re.compile(
    r"(?:docs/)?(?:RUNBOOK(?:\.md)?|runbook)\s*§\s*(\d+)|docs/runbook/[\w.-]+\.md|docs/RUNBOOK\.md|/help\b[^\s>]*"
)


def runbook_refs(texts: Sequence[str]) -> list[str]:
    out: list[str] = []
    for t in texts:
        for m in _REF.finditer(t):
            ref = m.group(0)
            if ref not in out:
                out.append(ref)
    return out


def resolve_ref(ref: str) -> list[str]:
    """The files a reference names (paths below trialbox/); a ``/help`` link is the console's help page."""
    m = re.search(r"(?:RUNBOOK|runbook)(?:\.md)?\s*§\s*(\d+)", ref)
    if m:
        n = int(m.group(1))
        return sorted(str(p.relative_to(ROOT)) for p in RUNBOOK_DIR.glob(f"{n:02d}-*.md"))
    if ref.startswith("docs/"):
        return [ref] if (ROOT / ref).is_file() else []
    return [ref]


def runbook_verdict(fault: Fault, texts: Sequence[str]) -> dict[str, Any]:
    refs = runbook_refs(texts)
    files = sorted({f for r in refs for f in resolve_ref(r)})
    return {"refs": refs, "files": files, "expected": fault.runbook,
            "expected_exists": bool(fault.runbook) and (ROOT / fault.runbook).is_file(),
            "leads_there": bool(fault.runbook) and fault.runbook in files}  # fmt: skip


# ------------------------------------------------------------------------------------------------ stand-ins
class SntpStandIn:
    """A one-thread SNTP server on 127.0.0.1 that answers ``offset_s`` seconds off this clock (for the clock
    fault: the box then reads itself ``-offset_s`` from the site's time server)."""

    def __init__(self, offset_s: float) -> None:
        self.offset = offset_s
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.sock.getsockname()[1]}"

    @staticmethod
    def _stamp(t: float) -> bytes:
        s = t + 2208988800
        return struct.pack("!II", int(s), int((s % 1) * 2**32))

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                _data, peer = self.sock.recvfrom(512)
            except OSError:
                continue
            t = time.time() + self.offset
            pkt = b"\x24\x01\x00\xec" + b"\0" * 28 + self._stamp(t) + self._stamp(t)
            with contextlib.suppress(OSError):
                self.sock.sendto(pkt, peer)

    def __enter__(self) -> SntpStandIn:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop.set()
        self.thread.join(2)
        self.sock.close()


def make_cert(cert: Path, key: Path, days: float, host: str = "trialbox.hospa.test") -> datetime:
    """A synthetic self-signed certificate for ``host`` that ends ``days`` from now (and its key, 0600)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    k = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    end = now + timedelta(days=days)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    c = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(end)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .sign(k, hashes.SHA256())
    )  # fmt: skip
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))  # fmt: skip
    key.chmod(0o600)
    return end


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _mount(*args: str) -> bool:
    return subprocess.run(["mount", *args], capture_output=True, check=False).returncode == 0


# ------------------------------------------------------------------------------------------------ the box
ADMINS = {"admin": "en", "adminzh": "zh-TW", "adminja": "ja"}
COORDS = {"crc": "en", "crcja": "ja"}
PASSWORD = "planted-faults-password-0001"  # a synthetic box's own accounts, made and dropped by this run
HOST = "trialbox.hospa.test"
#: the settings the box's deploy/.env carries (backup-status on the command line reads them from there)
ENV_FILE_KEYS = ("TB_BACKUP_TARGETS", "TB_BACKUP_PUBKEY", "TB_BACKUP_DIRS", "TB_BACKUP_ALERT_CMD", "TB_HEALTH_DISKS",
                 "TB_SITE_ID")  # fmt: skip
FIRST_PAGE = "/home"  # where sign-in lands (console.app: "/home" with the workspace on, in every environment)


class Box:
    """The in-process box (see the module's text). ``root``: a folder this run owns."""

    def __init__(self, root: Path, db_url: str) -> None:
        from console.app import create_app
        from console.auth import UserStore
        from tb_common.audit import AuditLog

        from tests.console.test_console_app import MODELS_INFO, PILOT_ENV, FakeBackend
        from tools.trialbox import backup as bkp
        from tools.trialbox import ops as tb_ops
        from tools.trialbox import svc_secrets

        self.root = root
        self.deploy = root / "deploy"
        (self.deploy / "secrets").mkdir(parents=True)
        (self.deploy / "site").mkdir()
        svc_secrets.init(self.deploy, uid=None)
        self.pub = self.deploy / "secrets" / "backup.pub"
        bkp.keygen(root / "usb-key" / "backup.key", self.pub)
        self.data = root / "data"
        self.data.mkdir()
        (self.data / "a.txt").write_text("synthetic\n", encoding="utf-8")
        self.nas, self.usb = root / "nas", root / "usbdisk"
        self.nas.mkdir()
        self.usb.mkdir()
        self.nas_mounted = is_root() and _mount("-t", "tmpfs", "-o", "size=32m", "tmpfs", str(self.nas))
        self.disk = root / "watched-disk"
        self.disk.mkdir()
        self.disk_mounted = is_root() and _mount("-t", "tmpfs", "-o", "size=16m", "tmpfs", str(self.disk))
        self.tls = root / "tls"
        self.tls.mkdir()
        make_cert(self.tls / "cert.pem", self.tls / "key.pem", 200, HOST)
        self.alert_out = root / "backup-alert-outbox.txt"
        alert_cmd = (
            f"{shlex_quote(sys.executable)} -c "
            + shlex_quote("import sys; open(sys.argv[1], 'a', encoding='utf-8').write(sys.stdin.read() + '\\n----\\n')")
            + " "
            + shlex_quote(str(self.alert_out))
        )
        self.env: dict[str, str] = {
            **PILOT_ENV,
            "TB_CONSOLE_DIR": str(root / "console"),
            "TB_OPS_DIR": str(root / "ops"),
            "TB_OPS_RUNNER": "inline",
            "TB_OPS_DEPLOY": str(self.deploy),
            "TB_BACKUP_TARGETS": f"{self.nas} {self.usb}",
            "TB_BACKUP_PUBKEY": str(self.pub),
            "TB_BACKUP_DIRS": f"data={self.data}",
            "TB_BACKUP_ALERT_CMD": alert_cmd,
            "TB_HEALTH_DISKS": str(self.disk),
            "TB_TLS_MODE": "hospital",
            "TB_TLS_HOSTNAME": HOST,
            "TB_TLS_CERT_FILE": str(self.tls / "cert.pem"),
            "TB_TLS_KEY_FILE": str(self.tls / "key.pem"),
            "TB_DB_URL": db_url,
            "TB_SITE_ID": "TEST",
        }
        (self.deploy / ".env").write_text("".join(f"{k}={v!r}\n".replace("'", '"') for k, v in self.env.items()
                                                  if k in ENV_FILE_KEYS),
                                          encoding="utf-8")  # fmt: skip
        from orchestrator.canary_gate import Gate

        self.gate = Gate()
        self.gate.configure(root / "orchestrator-data")
        gate = self.gate

        class Backend(FakeBackend):
            """The orchestrator stand-in, with the canary gate's own status in /models and the services list the
            Health tab probes (the gateway's /healthz stays 200 while a model server is down: gateway.app)."""

            def models(self) -> dict[str, Any] | None:
                return {**MODELS_INFO, "canary": gate.status()}

        self.backend = Backend()
        self.backend.audit_dir = root / "audit"
        self.audit = AuditLog(self.backend.audit_dir)
        self.users = UserStore()
        for u in ADMINS:
            self.users.create(u, "admin", PASSWORD, f"{u}@hospa.test")
        for u in COORDS:
            self.users.create(u, "coordinator", PASSWORD, f"{u}@hospa.test")
        self.app = create_app(self.env, backend=self.backend, audit=self.audit, users=self.users)
        self.h: Any = self.app.state.helpers
        from console.sitestore import NotifyPerson

        for u, lang in {**ADMINS, **COORDS}.items():
            self.h.store.save_notify_person(NotifyPerson(u, None, lang=lang))
        self.runner = tb_ops.OpsRunner(tb_ops.Box.local(self.deploy, self.env), tb_ops.OpsDir(root / "ops"))
        self.clients: dict[str, Any] = {}
        self.day = date(2026, 12, 1)  # each fault's own mail day (the console keeps one notice per person and day)

    # -------------------------------------------------------------- the product's ticks
    def nightly_backup(self) -> dict[str, Any]:
        """The nightly run (backup_schedule.nightly) with the in-process box's backup writer, then the hourly
        backup-status with its alert route, as cron runs them."""
        from tools.trialbox import backup as bkp
        from tools.trialbox import backup_schedule as bsch

        cfg = bsch.config(self.deploy, self.env)
        res = bsch.nightly(cfg, lambda targets: bkp.backup(targets, self.pub, env=self.env, dirs=bkp.layout(self.env),
                                                           keep=cfg.keep), self._audit)  # fmt: skip
        self.backup_status()
        return res

    def backup_status(self) -> str:
        from tools.trialbox import backup_schedule as bsch

        cfg = bsch.config(self.deploy, self.env)
        st = bsch.status(cfg)
        return bsch.alert(cfg, st, self._audit, bsch.send_cmd(cfg.alert_cmd))

    def _audit(self, event: str, detail: dict[str, Any]) -> None:
        self.audit.append(event, actor="planted-faults:cron", detail=detail)

    def tick(self) -> None:
        """``trialbox ops run``: the host facts into the operations status the console reads."""
        self.runner.write_status()

    def mail_round(self, day: date) -> list[Any]:
        """The 07:00 health mail and the 07:30 digest of ``day``, as the console's timers call them."""
        from console import notify

        return notify.send_all(self.h, day, ("HEALTH",), by="console:timer") + notify.send_all(
            self.h, day, ("N2",), by="console:timer"
        )

    # -------------------------------------------------------------- what a person meets
    def client(self, user: str) -> Any:
        if user not in self.clients:
            from tests.console.test_console_app import login

            c, csrf = login(self.app, user, PASSWORD)
            c.post("/lang", data={"lang": ADMINS.get(user, "en"), "csrf": csrf, "back": "/"})
            self.clients[user] = (c, csrf)
        return self.clients[user][0]

    def first_pages(self) -> dict[str, list[str]]:
        return {lang: page_lines(self.client(u).get(FIRST_PAGE).text) for u, lang in ADMINS.items()}

    def metrics(self) -> dict[str, Any]:
        r = self.client("admin").get("/metrics")
        return {"status": r.status_code, **parse_metrics(r.text)}

    def outbox(self) -> tuple[int, int]:
        return len(self.backend.notices), self.alert_out.stat().st_size if self.alert_out.exists() else 0

    def mails_since(self, mark: tuple[int, int]) -> list[Mail]:
        lang_of = {f"{u}@hospa.test": lang for u, lang in {**ADMINS, **COORDS}.items()}
        out = [Mail("notice", k, ",".join(to), s, b, lang_of.get(to[0] if to else "", "en"))
               for k, to, s, b in self.backend.notices[mark[0]:]]  # fmt: skip
        if self.alert_out.exists():
            text = self.alert_out.read_bytes()[mark[1] :].decode("utf-8")
            out += [Mail("backup-alert", "backup.alert", "TB_BACKUP_ALERT_CMD", m.splitlines()[0] if m else "", m)
                    for m in text.split("\n----\n") if m.strip()]  # fmt: skip
        return out

    def close(self) -> None:
        for p, on in ((self.nas, self.nas_mounted), (self.disk, self.disk_mounted)):
            if on:
                subprocess.run(["umount", "-l", str(p)], capture_output=True, check=False)


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


# ------------------------------------------------------------------------------------------------ plant and clear
@contextlib.contextmanager
def _env(**kv: str) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update(kv)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _plant_backup(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    if box.nas_mounted:
        subprocess.run(["umount", str(box.nas)], capture_output=True, check=False)  # the share is gone
        rec["gone"] = _observe_light(box, "after the share was unmounted, before the night")
        rec["gone"]["night"] = _night_summary(box.nightly_backup())
        rec["gone"]["after_night"] = _observe_light(box, "after the night with the share gone")
        for f in box.nas.iterdir():  # what the night wrote to the box's own disk in the share's place
            rec["gone"].setdefault("written_on_box_disk", []).append(f.name)
            f.unlink()
        _mount("-t", "tmpfs", "-o", "size=32m,ro", "tmpfs", str(box.nas))  # back, read-only: unwritable
        how = "remounted read-only"
    else:
        box.nas.chmod(0o555)
        how = "chmod 0555"
    rec["how"] = how
    rec["night"] = _night_summary(box.nightly_backup())

    def clear() -> None:
        if box.nas_mounted:
            subprocess.run(["umount", str(box.nas)], capture_output=True, check=False)
            _mount("-t", "tmpfs", "-o", "size=32m", "tmpfs", str(box.nas))
        else:
            box.nas.chmod(0o755)
        rec["clear_night"] = _night_summary(box.nightly_backup())

    return clear


def _night_summary(res: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": res.get("ok"), "errors": [str(e)[:240] for e in res.get("errors") or []]}


def _plant_disk(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    junk = box.disk / "junk.bin"
    if box.disk_mounted:
        total = shutil.disk_usage(box.disk).total
        with open(junk, "wb") as fh:
            fh.write(b"\0" * int(total * 0.94))
        rec["how"] = f"tmpfs {total // 2**20} MiB filled to {shutil.disk_usage(box.disk).used * 100 // total} %"
        return junk.unlink
    real = shutil.disk_usage  # tb_common.metrics calls shutil.disk_usage: the stand-in answers for one device
    # H-39: not as root the watched folder is not a mount: it is on the device of the box's deploy folder, and the
    # product measures one path per device (tb_common.metrics.disk_paths keeps the first path of each st_dev), so it
    # never asks for the watched folder itself. A full device is full for every path on it (statvfs answers per file
    # system), so the stand-in answers 94 % for every path on the watched folder's device, as a full disk would.
    dev = box.disk.stat().st_dev

    def fake(p: Any) -> Any:
        u = real(p)
        try:
            same = os.stat(p).st_dev == dev
        except OSError:
            same = False
        return type(u)(u.total, int(u.total * 0.94), u.total - int(u.total * 0.94)) if same else u

    setattr(shutil, "disk_usage", fake)  # noqa: B010 - the stand-in, undone by clear()
    rec["how"] = ("planted by a stand-in: shutil.disk_usage of tb_common.metrics answers 94 % for every path on the "
                  "watched folder's device (not a mount when not root)")  # fmt: skip

    def clear() -> None:
        setattr(shutil, "disk_usage", real)  # noqa: B010

    return clear


def _plant_cert(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    end = make_cert(box.tls / "cert.pem", box.tls / "key.pem", 12, HOST)
    rec["how"] = f"certificate ends {end:%Y-%m-%d} (12 days)"

    def clear() -> None:
        make_cert(box.tls / "cert.pem", box.tls / "key.pem", 200, HOST)

    return clear


def _plant_model(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    unreached = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "unreached": ["judge", "verifier"],
                 "problems": ["judge: upstream_down", "verifier: upstream_down"]}  # fmt: skip
    box.gate.record_unreached(unreached)
    rec["how"] = "the night's canary recorded as unreached (judge and verifier: upstream_down); a passing canary stands"

    def clear() -> None:
        box.gate.record(_passing_canary())

    return clear


def _passing_canary() -> dict[str, Any]:
    return {"ok": True, "at": datetime.now(UTC).isoformat(timespec="seconds"), "at_epoch": time.time(), "cases": 54,
            "pair": {"correct": 54, "decided_wrong": 0}, "problems": [],
            "models": [{"role": "judge", "ok": True}, {"role": "verifier", "ok": True}]}  # fmt: skip


def _no_canary_variant(
    box: Box, rec: dict[str, Any], base: Mapping[str, list[str]], base_metrics: Mapping[str, Any]
) -> None:
    """The second case of the model fault: no passing canary stands (the gate restarted), the canary unreached."""
    from orchestrator.canary_gate import Gate

    keep = {k: v for k, v in box.gate.__dict__.items() if k != "_lock"}
    g = Gate()
    g.record_unreached({"at": datetime.now(UTC).isoformat(timespec="seconds"), "unreached": ["judge", "verifier"],
                        "problems": ["judge: upstream_down", "verifier: upstream_down"]})  # fmt: skip
    box.gate.__dict__.update({k: v for k, v in g.__dict__.items() if k not in ("_lock",)})
    box.gate.path = None
    seen = _observe_light(box, "the gate restarted: no passing canary, the canary unreached")
    seen["page_new"] = {lang: new_lines(base[lang], now) for lang, now in box.first_pages().items()}
    seen["page"] = page_verdict(BY_KEY["model_down"], seen["page_new"])
    seen["metrics"] = metrics_verdict(BY_KEY["model_down"], base_metrics, seen["metrics"])
    rec["no_passing_canary"] = seen
    box.gate.__dict__.update(keep)


def _plant_clock(box: Box, rec: dict[str, Any], stack: contextlib.ExitStack) -> Callable[[], None]:
    from tools.trialbox import doctor

    srv = stack.enter_context(SntpStandIn(-600.0))
    env = {**box.env, "TB_NTP_SERVER": srv.address, "TB_ENV": "PRODUCTION"}
    chk = doctor.check_clock(doctor.DoctorInputs(env=env))
    rec["product_check"] = {"name": "doctor: clock", "status": chk.status, "text": chk.detail}
    rec["how"] = f"TB_NTP_SERVER={srv.address} answers 600 s behind this clock"

    def clear() -> None:
        with SntpStandIn(0.0) as ok:
            c = doctor.check_clock(doctor.DoctorInputs(env={**env, "TB_NTP_SERVER": ok.address}))
            rec["product_check_after"] = {"status": c.status, "text": c.detail}

    return clear


def _plant_feed(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    from adapter.pipeline import AdapterConfig, run_ingest
    from tb_contracts import RebuildResult

    site_a = ROOT / "tests" / "fixtures" / "synthetic_patients" / "site-a"
    feed, lake, sec = box.root / "feed", box.root / "lake", box.root / "adapter-secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    shutil.copytree(site_a, feed, ignore=shutil.ignore_patterns("*.json"), dirs_exist_ok=True)

    def rebuild(snap: str, nd: Path) -> Any:
        lake.mkdir(parents=True, exist_ok=True)
        (lake / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)

    cfg = AdapterConfig(lake_dir=lake, secrets_dir=sec, site_id="T", audit_dir=box.backend.audit_dir,
                        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml", rebuild=rebuild,
                        db_url=box.env["TB_DB_URL"], tz="UTC")  # fmt: skip

    def night(snap: str) -> dict[str, Any]:
        try:
            r = run_ingest(cfg, "csv", str(feed), snapshot=snap, load_fhir=False, validate=False)
        except Exception as exc:
            return {"raised": type(exc).__name__, "text": str(exc)[:300]}
        d = r.model_dump(mode="json")
        return {k: d[k] for k in ("snapshot", "held", "counts", "missing_required", "errors") if k in d}

    today = datetime.now(UTC).date()
    rec["good_night"] = night((today - timedelta(days=2)).isoformat())
    for p in feed.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    rec["empty_night"] = night((today - timedelta(days=1)).isoformat())
    rec["how"] = "the feed folder emptied after a good night; the adapter's night run on it"
    sources = box.client("admin").get("/admin?tab=sources")
    rec["sources_tab"] = [x for x in page_lines(sources.text) if "csv" in x.lower()][:6]

    def clear() -> None:
        shutil.copytree(site_a, feed, ignore=shutil.ignore_patterns("*.json"), dirs_exist_ok=True)
        rec["clear_night"] = night(today.isoformat())

    return clear


def _plant_mail(box: Box, rec: dict[str, Any]) -> Callable[[], None]:
    rec["how"] = "the fault's day passes with no 07:00 or 07:30 timer run"
    rec["held"] = True
    return lambda: None


# ------------------------------------------------------------------------------------------------ one fault
def _observe_light(box: Box, what: str) -> dict[str, Any]:
    box.tick()
    return {"what": what, "metrics": box.metrics(), "page_en": page_lines(box.client("admin").get(FIRST_PAGE).text)}


def _run_step(box: Box, step: Step) -> dict[str, Any]:
    if not step.cmd:
        return {"quote": step.quote, "at": f"{step.page}:{step.line}", "ran": False, "needs": step.needs}
    if step.cmd[0] == "console":
        t0 = time.monotonic()
        c, csrf = box.clients["admin"]
        mark = box.outbox()
        r1 = c.post("/ops/notices", data={"csrf": csrf}, follow_redirects=False)
        n1 = len(box.mails_since(mark))
        r2 = c.post("/ops/notices", data={"csrf": csrf}, follow_redirects=False)
        n2 = len(box.mails_since(mark)) - n1
        return {"quote": step.quote, "at": f"{step.page}:{step.line}", "ran": True, "cmd": step.cmd[1],
                "exit": f"{r1.status_code}, {r2.status_code}", "seconds": round(time.monotonic() - t0, 2),
                "out": f"first press sent {n1} mail(s); second press sent {n2}"}  # fmt: skip
    cmd = [x.replace("{py}", sys.executable).replace("{deploy}", str(box.deploy)) for x in step.cmd]
    env = {**os.environ, **box.env, "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT / 'services'}:{ROOT}"}
    t0 = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=300, check=False)
    out = (p.stdout + p.stderr).strip().replace(str(box.root), "<box>")
    return {"quote": step.quote, "at": f"{step.page}:{step.line}", "ran": True, "cmd": " ".join(step.cmd),
            "exit": p.returncode, "seconds": round(time.monotonic() - t0, 2), "out": out[-900:]}  # fmt: skip


def drill(box: Box, fault: Fault, stack: contextlib.ExitStack) -> dict[str, Any]:
    rec: dict[str, Any] = {"fault": fault.key, "words": fault.words, "planted": fault.planted}
    day = box.day
    box.day += timedelta(days=3)
    box.tick()
    base_pages, base_metrics = box.first_pages(), box.metrics()
    rec["green_before"] = base_metrics["level"] == "ok" or base_metrics
    plant = {"backup_target": _plant_backup, "disk_full": _plant_disk, "certificate": _plant_cert,
             "model_down": _plant_model, "feed_empty": _plant_feed, "morning_mail": _plant_mail}  # fmt: skip
    mark = box.outbox()  # before the plant: the backup's alert route mails during the planted night
    t0 = time.monotonic()
    clear = _plant_clock(box, rec, stack) if fault.key == "clock_off" else plant[fault.key](box, rec)
    box.tick()
    rec["seconds_to_show"] = round(time.monotonic() - t0, 2)
    pages, met = box.first_pages(), box.metrics()
    if fault.key != "morning_mail":
        box.mail_round(day)
        again = box.outbox()
        box.mail_round(day)
        rec["second_round_same_day"] = len(box.mails_since(again))
    mails = box.mails_since(mark)
    new = {lang: new_lines(base_pages[lang], pages[lang]) for lang in LANGS}
    rec["page"] = page_verdict(fault, new)
    rec["page_new_lines"] = new
    rec["metrics"] = metrics_verdict(fault, base_metrics, met)
    rec["metrics_raw"] = met
    rec["mail"] = mail_verdict(fault, mails, {f"{u}@hospa.test": lang for u, lang in ADMINS.items()})
    rec["mail_bodies"] = [asdict(m) for m in mails]
    texts = [x for v in new.values() for x in v] + [m.body for m in mails]
    rec["runbook"] = runbook_verdict(fault, texts)
    rec["steps"] = [_run_step(box, s) for s in fault.steps]
    if fault.key == "model_down":
        _no_canary_variant(box, rec, base_pages, base_metrics)
    # remove the fault, run the product's tick, read again
    t1 = time.monotonic()
    clear()
    box.tick()
    rec["seconds_to_clear"] = round(time.monotonic() - t1, 2)
    after_pages, after_met = box.first_pages(), box.metrics()
    nxt = day + timedelta(days=1)
    mark2 = box.outbox()
    box.mail_round(nxt)
    after_mails = box.mails_since(mark2)
    rec["cleared"] = {
        "page": {lang: not about(fault, lang, new_lines(base_pages[lang], after_pages[lang])) for lang in LANGS},
        "metrics": metrics_verdict(fault, base_metrics, after_met)["verdict"] == "not shown",
        "metrics_level": after_met["level"],
        "mail_next_morning": (
            bool(after_mails)
            if fault.key == "morning_mail"
            else mail_verdict(fault, after_mails, {})["verdict"] == "not shown"
        ),
        "next_morning_mails": [f"{m.kind} to {m.to}: {m.subject}" for m in after_mails],
    }
    return rec


def run(
    out: Path | None, keys: Sequence[str] = (), db_url: str | None = None, root: Path | None = None
) -> dict[str, Any]:
    """Plant each fault in turn on one in-process box; the record (also written to ``out``)."""
    base = root or (Path(os.environ["TB_SCRATCH"]) if os.environ.get("TB_SCRATCH") else None)
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="planted-faults-", dir=base))
    if db_url is None:
        from tools import pglocal

        db_url = pglocal.ensure(work / "pg")
    record: dict[str, Any] = {
        "card": "H-32", "decision": "D-1110", "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "box": "in-process console (TB_OPS_RUNNER=inline), throwaway PostgreSQL, orchestrator stand-in; no Docker",
        "root": is_root(), "faults": [],
    }  # fmt: skip
    with _env(TB_DB_URL=db_url, TB_CANARY_GATE="on"), contextlib.ExitStack() as stack:
        box = Box(work / "box", db_url)
        stack.callback(box.close)
        box.gate.record(_passing_canary())
        box.nightly_backup()
        from tb_common import metrics

        # the green box's last key check: the record backup-verify writes after a check with the private key (a
        # stand-in: this tool never opens a key file)
        good = json.loads((box.deploy / "site" / "backup-last.json").read_text(encoding="utf-8")).get("good_file")
        metrics.record_verified(box.deploy, {"file": (good or {}).get("name", ""), "site": "TEST"})
        record["mounts"] = {"nas": box.nas_mounted, "disk": box.disk_mounted}
        for f in FAULTS:
            if keys and f.key not in keys:
                continue
            try:
                record["faults"].append(drill(box, f, stack))
            except Exception as exc:  # a fault that could not be planted is recorded, never hidden
                record["faults"].append({"fault": f.key, "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        shutil.rmtree(work)
    return record


def table(record: Mapping[str, Any]) -> list[str]:
    """One line per fault: page (en, zh-TW, ja), mail, /metrics, runbook."""
    out = []
    for r in record.get("faults") or []:
        if "error" in r:
            out.append(f"{r['fault']}: could not be planted: {r['error']}")
            continue
        pg = ", ".join(f"{lang} {r['page'][lang]['verdict']}" for lang in LANGS)
        rb = r["runbook"]
        out.append(f"{r['fault']}: page [{pg}]; mail {r['mail']['verdict']}; /metrics {r['metrics']['verdict']} "
                   f"{r['metrics']['moved']}; runbook named {rb['files'] or rb['refs'] or 'none'}, expected "
                   f"{rb['expected'] or 'none'}")  # fmt: skip
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.planted_faults", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="plant each fault on an in-process box and write the record")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--fault", action="append", choices=list(BY_KEY), default=[])
    r.add_argument("--db-url", default=None, help="a PostgreSQL URL (else a throwaway one by tools.pglocal)")
    sub.add_parser("faults", help="the seven faults and how each is planted")
    a = ap.parse_args(argv)
    if a.cmd == "faults":
        for f in FAULTS:
            print(f"{f.key}: {f.words}\n  planted: {f.planted}\n  checks: {', '.join(f.checks) or f.other_check}"
                  f"\n  runbook: {f.runbook or 'none'}")  # fmt: skip
        return 0
    rec = run(a.out, a.fault, a.db_url)
    print("\n".join(table(rec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
