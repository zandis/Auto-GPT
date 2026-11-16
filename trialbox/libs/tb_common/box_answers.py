"""The box owner's answers (T-729, D-466; plan v6.1 OD-11 to OD-14): the one schema the first-run wizard collects and
the box installer turns into settings.

A box (a GPU workstation or a DGX Spark) is set up by its owner, a research lead who is the data steward (OD-12), not
by hospital IT (OD-13). So the answers are only what an owner knows: the site's name, its time zone and language, the
owner's own account (name, user name, mail address; the password and the second factor stay in the console and never
reach these answers), the box's name on the network, where backups go (a second disk or a share), and the kind of
data source (OD-14's five kinds, or "set up later"). Everything else is derived from the detected hardware
(``tools.box.plan``) or is a safe default; nothing here asks for a shell, a compose file, a DNS record, a certificate
or an IP range.

Pure and standard library only: the console (the wizard's pages) and the host's ``python3`` (the installer, before
any image is loaded) both import it. :func:`parse` returns the answers or a list of :class:`Problem` whose ``code``
is a message key the console translates (``firstrun.err.<code>``).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import chartno

LANGUAGES = ("en", "ja", "zh-TW")  # the console's three catalogues


class SourceKind(StrEnum):
    """Where the box's patient data comes from (OD-14). The connectors themselves are T-731's."""

    RESEARCH_DB = "research_db"  # the hospital's research database (CGRD) by a read connection, approved scope
    REDCAP = "redcap"  # a REDCap project, read
    OWN_DB = "own_db"  # the team's own patient database, read-only connection
    EMR_FEED = "emr_feed"  # the EMR or hospital feed (HIS export, SS-MIX2) for site activation
    SPREADSHEET = "spreadsheet"  # spreadsheets and CSV files a person uploads
    LATER = "later"  # set up later, on the box (T-731's mapping step)


class BackupKind(StrEnum):
    SECOND_DISK = "second_disk"  # a second disk in or attached to the box
    SHARE = "share"  # a network share (SMB or NFS) the owner was given
    LATER = "later"  # not yet: the health page stays red until there is one (OD-16, T-730)


# a share as an owner is given it: \\server\share, //server/share, or server:/export (NFS)
_SHARE = re.compile(r"^(?:(?:\\\\|//)[A-Za-z0-9._-]+[\\/][^\s\\/][^\s]*|[A-Za-z0-9._-]+:/[^\s]*)$")
_DISK = re.compile(r"^/dev/[A-Za-z0-9/_-]+$")  # a device the installer listed (never typed: chosen from a list)
_USER = re.compile(r"^[a-z0-9._-]{1,26}$")  # console.auth.check_username, leaving room for "-admin"
_MAIL = re.compile(r"^[^@\s]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_BOXNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
ADMIN_SUFFIX = "-admin"


@dataclass(frozen=True)
class Problem:
    field: str
    code: str  # firstrun.err.<code> in the console's catalogues

    def __str__(self) -> str:
        return f"{self.field}: {self.code}"


@dataclass(frozen=True)
class Owner:
    full_name: str
    username: str
    email: str


@dataclass(frozen=True)
class Backup:
    kind: BackupKind
    disk: str = ""  # second_disk: the device the owner picked from the detected list
    share: str = ""  # share: the address as given


@dataclass(frozen=True)
class OwnerAnswers:
    site_name: str
    tz: str
    language: str
    owner: Owner
    box_name: str  # the box's name on the network; ".local" is added when it has no dot (mDNS)
    backup: Backup
    source: SourceKind
    # NEW-DIN-3 (D-544, D-579): how the hospital writes chart numbers (``tb_common.chartno``: ``asis``,
    # ``digits[:width]``, ``hex[:width][:lower]``); empty: not answered, the installer keeps the rule the box runs on
    chartno_rule: str = ""
    # D-822 (the owner's blocker 8): PRODUCTION, or VALIDATION for public or synthetic data (D-127); a box is never
    # DEV or TEST (a rehearsal box is made by its own installer argument, D-726, D-887)
    environment: str = "PRODUCTION"
    # D-825 (the owner's blocker 9): the authserv-id the hospital MTA writes first in Authentication-Results; empty:
    # no sender can be authenticated and the box refuses every request mail (D-369, fails closed)
    mta_authserv_id: str = ""

    @property
    def hostname(self) -> str:
        return self.box_name if "." in self.box_name else f"{self.box_name}.local"

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["backup"]["kind"] = self.backup.kind.value
        d["source"] = self.source.value
        return d


BOX_ENVIRONMENTS = ("PRODUCTION", "VALIDATION")  # D-822
# D-825: one host name (labels of letters, digits and inner hyphens, at least one dot), as an MTA names itself
_HOST = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def _s(raw: Any, limit: int = 200) -> str:
    return str(raw if raw is not None else "").strip()[:limit]


def parse(raw: dict[str, Any], *, disks: tuple[str, ...] = ()) -> tuple[OwnerAnswers | None, list[Problem]]:
    """The answers from a form or a JSON file (nested ``owner``/``backup`` or flat ``owner_*``/``backup_*`` keys).
    ``disks``: the devices the installer detected; a second disk must be one of them."""
    own: dict[str, Any] = raw["owner"] if isinstance(raw.get("owner"), dict) else {}
    bak: dict[str, Any] = raw["backup"] if isinstance(raw.get("backup"), dict) else {}
    problems: list[Problem] = []

    site_name = _s(raw.get("site_name"))
    if not site_name:
        problems.append(Problem("site_name", "required"))
    tz = _s(raw.get("tz"), 64)
    try:
        if not tz:
            raise ValueError(tz)
        ZoneInfo(tz)
    except Exception:
        problems.append(Problem("tz", "tz"))
    language = _s(raw.get("language"), 8) or "en"
    if language not in LANGUAGES:
        problems.append(Problem("language", "language"))
    full_name = _s(own.get("full_name", raw.get("owner_full_name")))
    username = _s(own.get("username", raw.get("owner_username")), 64).lower()
    email = _s(own.get("email", raw.get("owner_email")), 254).lower()
    if not full_name:
        problems.append(Problem("owner_full_name", "required"))
    if not _USER.fullmatch(username):
        problems.append(Problem("owner_username", "username"))
    if not _MAIL.fullmatch(email):
        problems.append(Problem("owner_email", "email"))
    box_name = _s(raw.get("box_name"), 253).lower() or "trialbox"
    if not _BOXNAME.fullmatch(box_name):
        problems.append(Problem("box_name", "box_name"))
    try:
        kind = BackupKind(_s(bak.get("kind", raw.get("backup_kind")), 16) or "")
    except ValueError:
        kind = None
        problems.append(Problem("backup_kind", "backup_kind"))
    disk = _s(bak.get("disk", raw.get("backup_disk")), 64)
    share = _s(bak.get("share", raw.get("backup_share")), 255)
    if kind is BackupKind.SECOND_DISK and (not _DISK.fullmatch(disk) or (disks and disk not in disks)):
        problems.append(Problem("backup_disk", "backup_disk"))
    if kind is BackupKind.SHARE and not _SHARE.fullmatch(share):
        problems.append(Problem("backup_share", "backup_share"))
    try:
        source = SourceKind(_s(raw.get("source"), 16) or "later")
    except ValueError:
        source = SourceKind.LATER
        problems.append(Problem("source", "source"))
    rule = chartno_rule(raw)
    if rule is None:
        problems.append(Problem("chartno_rule", "chartno_rule"))
    environment = _s(raw.get("environment"), 16).upper() or "PRODUCTION"
    if environment not in BOX_ENVIRONMENTS:
        problems.append(Problem("environment", "environment"))
    authserv = _s(raw.get("mta_authserv_id"), 253).lower()
    if authserv and not _HOST.fullmatch(authserv):
        problems.append(Problem("mta_authserv_id", "mta_authserv_id"))
    if problems or kind is None or rule is None:
        return None, problems
    backup = Backup(kind, disk if kind is BackupKind.SECOND_DISK else "", share if kind is BackupKind.SHARE else "")
    return (
        OwnerAnswers(
            site_name,
            tz,
            language,
            Owner(full_name, username, email),
            box_name,
            backup,
            source,
            rule,
            environment,
            authserv,
        ),
        [],
    )


# a rule exactly as tb_common.chartno writes one: ASCII digits, one width, no part twice
_RULE = re.compile(r"^(asis|digits(:[0-9]{1,2})?|hex(:[0-9]{1,2})?(:(upper|lower))?)$")


def chartno_rule(raw: dict[str, Any]) -> str | None:
    """The chart-number rule as ``tb_common.chartno`` writes it, from ``chartno_rule`` (a file) or from the form's
    ``chartno_kind`` and ``chartno_width`` (and ``chartno_case`` for hex), never from both. Empty: no answer. None:
    it cannot be read; nothing is cut, guessed or taken in part (the rule decides every patient's pseudonym)."""
    text = str(raw.get("chartno_rule") or "").strip().lower()
    kind = str(raw.get("chartno_kind") or "").strip().lower()
    width, case = str(raw.get("chartno_width") or "").strip(), str(raw.get("chartno_case") or "").strip().lower()
    if text and (kind or width or case):
        return None
    if not text:
        if not kind:
            return None if width or case else ""
        text = ":".join(p for p in (kind, width, case) if p)
    if not _RULE.fullmatch(text):
        return None
    try:
        return str(chartno.parse_rule(text))
    except ValueError:  # ChartNoError is one; a width the pattern let through and int() cannot read is another
        return None


@dataclass(frozen=True)
class AccountPlan:
    username: str
    role: str  # a console role (console.auth.ROLES)
    duty: str  # what the account is for, in the wizard's words: "steward" or "administrator"


def owner_accounts(a: OwnerAnswers) -> list[AccountPlan]:
    """The accounts the first-run wizard makes (OD-12): the owner is the data steward and, by default, holds the
    administrator's duties. Today a console account has one role (``console.auth``), and the administrator sees no
    patient data (D-280), so the owner gets two accounts under one password and one authenticator: ``<name>``
    (steward) and ``<name>-admin`` (administrator). T-736 (OD-17) changes the duties; this is the one place it changes
    what the wizard makes (for example one account with both duties, or the administrator given to another person)."""
    return [
        AccountPlan(a.owner.username, "steward", "steward"),
        AccountPlan(a.owner.username + ADMIN_SUFFIX, "admin", "administrator"),
    ]
