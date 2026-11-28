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
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import chartno, host_folders, site_country
from tb_common.dates import PRINTED_STYLES, YEAR_BASES
from tb_common.retention import MAX_DAYS, OVERRIDABLE

LANGUAGES = ("en", "ja", "zh-TW")  # the console's three catalogues
# M1 (D-1280): the marked name a box carries until the hospital's is given
PLACEHOLDER_NAME = "TrialBox (site name needed)"
#: the site id the install derives from it (``tools.box.plan.site_id``): go-live is refused while the box carries it,
#: and a backup tagged with it needs --other-site to restore once the name is given
PLACEHOLDER_SITE_ID = "TRIALBOX-SITE-NAME-NEEDE"


class SourceKind(StrEnum):
    """Where the box's patient data comes from (OD-14). The connectors themselves are T-731's."""

    RESEARCH_DB = "research_db"  # the hospital's research database (CGRD) by a read connection, approved scope
    REDCAP = "redcap"  # a REDCap project, read
    OWN_DB = "own_db"  # the team's own patient database, read-only connection
    EMR_FEED = "emr_feed"  # the EMR or hospital feed (an HIS export) for site activation
    SSMIX2 = "ssmix2"  # 10K-1: the chart system's SS-MIX2 storage, read-only, read by the adapter's ssmix2 reader
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
_ROOT_DIR = re.compile(r"^/[A-Za-z0-9._/-]*$")  # a host folder as deploy/.env and compose take it: no space, no quote
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
    # 10K-1: the site's country (tb_common.site_country.COUNTRIES); empty: not asked (the page's flag is off, or an
    # answers file from before), and the box's settings follow the zone as before
    country: str = ""
    # 10K-1: an SS-MIX2 source: the storage's root folder on the box (mounted read-only) and its order-number key
    ssmix2_root: str = ""
    ssmix2_order_numbers: str = ""
    # 10K-1: the retention days, asked only for a country with no retention rules in TrialBox (tb_common.retention)
    retention_days: tuple[tuple[str, int], ...] = ()
    # 10C-13, 10C-15: how printed pages write a date (tb_common.dates.PRINTED_STYLES) and what a yearly report's year
    # is (YEAR_BASES); empty: follows the site's country (Japan: both and 年度; others: western and calendar)
    printed_dates: str = ""
    year_basis: str = ""
    # 10K-21 (D-1365): the person who opens the health page every working day (a box's backup alert route is the
    # health page, D-735); and who in hospital IT confirmed that the box's root certificate (Caddy's own CA) is on
    # the team's computers, and on which day. Empty: not answered (an answers file from before)
    health_page_person: str = ""
    tls_root_confirmed_by: str = ""
    tls_root_confirmed_on: str = ""
    # 10K-4 (D-1390): the host folders the owner chose. ``backup_dir``: where the second disk or the share is mounted
    # (empty: the plan's fixed mount point); ``anchor_dir``: the folder of the audit chain's signed heads (the
    # hospital's write-once share, mounted); ``log_dir``: where the collected logs go (empty: deploy/logs). Whether
    # the box may finish with them is the host's question (``tools.trialbox.finish_check``), not the parser's
    backup_dir: str = ""
    anchor_dir: str = ""
    log_dir: str = ""
    # M1 (D-1280): what is offered while the install runs or filled in on "Information still needed". ``source_dir``:
    # the host folder of the records (a CSV or spreadsheet source); empty: not given
    source_dir: str = ""
    sae_office_mailbox: str = ""
    smtp_host: str = ""
    smtp_port: str = ""

    @property
    def hostname(self) -> str:
        return self.box_name if "." in self.box_name else f"{self.box_name}.local"

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["backup"]["kind"] = self.backup.kind.value
        d["source"] = self.source.value
        d["retention_days"] = dict(self.retention_days)
        # 10K-1 (and 10K-21's people): its keys only when answered, so a box that was not asked writes the file it
        # wrote before
        named = ("health_page_person", "tls_root_confirmed_by", "tls_root_confirmed_on")
        folders = ("backup_dir", "anchor_dir", "log_dir")  # 10K-4: only when chosen
        later = ("source_dir", "sae_office_mailbox", "smtp_host", "smtp_port")  # M1: only when given
        for k in (
            "country",
            "ssmix2_root",
            "ssmix2_order_numbers",
            "retention_days",
            "printed_dates",
            "year_basis",
            *named,
            *folders,
            *later,
        ):
            if not d[k]:
                del d[k]
        return d


BOX_ENVIRONMENTS = ("PRODUCTION", "VALIDATION")  # D-822
# D-825: one host name (labels of letters, digits and inner hyphens, at least one dot), as an MTA names itself
# D-736: one plain mail address, as deploy/install.sh and tools.settings_wizard check it
MAILBOX = re.compile(
    r"[A-Za-z0-9._%+-][A-Za-z0-9._%+'-]*"
    r"@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"
)
_HOST = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def _s(raw: Any, limit: int = 200) -> str:
    return str(raw if raw is not None else "").strip()[:limit]


# 10K-21 (D-1365): a staff member's name, written as one plain value in deploy/.env, which compose (it substitutes
# $ and reads a leading quote), the Python readers (they split lines and strip) and the installer's shell all read.
# An allow-list, not a deny-list: letters, combining marks and digits of any script (山田 太郎, 陳 大文, José Ñúñez),
# single spaces between words (the ASCII or the ideographic space) and the few marks a name, or a role beside it,
# holds. Everything else is refused: control characters (CR, LF, NUL, tab), the Unicode line and paragraph
# separators, double quotes, an apostrophe first or last, $, backquote, backslash, #, =, ;, &, |, <, >, braces and
# the like
PERSON_MAX = 100
# dot, comma, hyphen, brackets (and the full-width ones a Japanese IME types), slash, ’ and ' (O’Brien, O'Brien),
# the two middle dots, the wave dashes 〜 and ～. The ASCII apostrophe only inside a name, never first or last:
# tb_common.config's reader strips a quote pair around a value, so 'Ann' would read back as Ann
_PERSON_MARKS = frozenset(".,-()（）/’'・·〜～")
_PERSON_SPACES = frozenset(" 　")  # the ASCII space and the ideographic space


def person_name(raw: Any) -> str | None:
    """10K-21: a named person (operational contact data, never patient data). Empty: not answered. None: refused
    (a character outside the allow-list above, two spaces in a row, an ASCII apostrophe first or last,
    or longer than ``PERSON_MAX``)."""
    text = str(raw if raw is not None else "").strip(" 　")
    if not text:
        return ""
    if len(text) > PERSON_MAX or text[0] == "'" or text[-1] == "'":
        return None
    prev_space = False
    for ch in text:
        if ch in _PERSON_SPACES:
            if prev_space:
                return None
            prev_space = True
        elif ch in _PERSON_MARKS or unicodedata.category(ch)[0] in "LMN":
            prev_space = False
        else:
            return None
    return text


def host_dir(raw: Any) -> str | None:
    """10K-4 (D-1390): a host folder as the owner writes it (a backup, anchor or log folder), by the allow rule of
    ``tb_common.host_folders``: one plain full path that is not ``/`` and does not overlap a system folder. Empty: not
    answered. None: refused. A trailing ``/`` is dropped, so one folder is written one way."""
    return host_folders.allowed(raw)


def confirmed_on(raw: Any, today: date | None = None) -> str | None:
    """10K-21: the day a confirmation was given (``YYYY-MM-DD``); empty: today. None: not a date, or a day to come."""
    now = today or date.today()
    text = str(raw if raw is not None else "").strip()
    if not text:
        return now.isoformat()
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    return day.isoformat() if len(text) == 10 and day <= now else None


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
    country = _s(raw.get("country"), 8).lower()
    cd = site_country.LEGACY
    try:
        cd = site_country.defaults(country)
    except ValueError:
        problems.append(Problem("country", "country"))
    if country and cd.tz and tz and tz != cd.tz and not any(p.field == "tz" for p in problems):
        problems.append(Problem("tz", "tz_country"))  # a country with one zone: its shipped mapping states it
    ss_root, ss_order = "", ""
    if source is SourceKind.SSMIX2 and not site_country.reads_ssmix2(country):
        problems.append(Problem("source", "source_country"))  # offered only where a shipped mapping reads it
    elif source is SourceKind.SSMIX2:
        ss_root = _s(raw.get("ssmix2_root"), 255)
        if not _ROOT_DIR.fullmatch(ss_root) or ss_root == "/" or "/../" in f"{ss_root}/":
            problems.append(Problem("ssmix2_root", "ssmix2_root"))
        ss_order = _s(raw.get("ssmix2_order_numbers"), 16) or "unique"
        if ss_order not in site_country.SSMIX2_ORDER_NUMBERS:
            problems.append(Problem("ssmix2_order_numbers", "ssmix2_order_numbers"))
    days: list[tuple[str, int]] = []
    if country and cd.retention_rules is None:  # no rules here for this country: the site gives the days
        given = raw["retention_days"] if isinstance(raw.get("retention_days"), dict) else raw
        for k in OVERRIDABLE:
            text = _s(given.get(k), 6)
            if not (text.isascii() and text.isdigit() and 1 <= int(text) <= MAX_DAYS):
                problems.append(Problem(k, "retention_days"))
            else:
                days.append((k, int(text)))
    # 10C-13, 10C-15 (D-1229): with a country, the effective values (an omitted answer is the country's default, as
    # the installer's wizard would write it), so the answers file and the audit record say what the site gets
    printed_dates = _s(raw.get("printed_dates"), 16) or (cd.printed_dates if country else "")
    if printed_dates not in ("", *PRINTED_STYLES):
        problems.append(Problem("printed_dates", "printed_dates"))
    year_basis = _s(raw.get("year_basis"), 16) or (cd.year_basis if country else "")
    if year_basis not in ("", *YEAR_BASES):
        problems.append(Problem("year_basis", "year_basis"))
    # 10K-21 (D-1365): named people; whether they are required is production_gaps' question, not the parser's
    person = person_name(raw.get("health_page_person"))
    if person is None:
        problems.append(Problem("health_page_person", "person_name"))
    it_by = person_name(raw.get("tls_root_confirmed_by"))
    it_on = ""
    if it_by is None:
        problems.append(Problem("tls_root_confirmed_by", "person_name"))
    elif it_by:
        it_on = confirmed_on(raw.get("tls_root_confirmed_on")) or ""
        if not it_on:
            problems.append(Problem("tls_root_confirmed_on", "confirmed_on"))
    # 10K-4 (D-1390): the folders. A backup folder belongs to a backup place: with "later" there is none to name
    folders: dict[str, str] = {}
    for k in ("backup_dir", "anchor_dir", "log_dir"):
        got = host_dir(raw.get(k))
        if got is None:
            problems.append(Problem(k, "host_dir"))
        folders[k] = got or ""
    if kind is BackupKind.LATER:
        folders["backup_dir"] = ""
    pair = host_folders.overlapping_pair(folders)  # three separate folders, none inside another
    if pair:
        problems.append(Problem(pair[1], "host_dir_overlap"))
    # M1 (D-1280): optional; a malformed one is named, never written
    source_dir = _s(raw.get("source_dir"), 255)
    if source_dir and (host_folders.allowed(source_dir) is None or not _ROOT_DIR.fullmatch(source_dir)):
        problems.append(Problem("source_dir", "host_dir"))
    office = _s(raw.get("sae_office_mailbox"), 254)
    if office and not MAILBOX.fullmatch(office):
        problems.append(Problem("sae_office_mailbox", "email"))
    relay = _s(raw.get("smtp_host"), 253).lower()
    if relay and not _HOST.fullmatch(relay):
        problems.append(Problem("smtp_host", "mta_authserv_id"))
    port = _s(raw.get("smtp_port"), 5)
    if port and not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        problems.append(Problem("smtp_port", "port"))
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
            country,
            ss_root,
            ss_order,
            tuple(days),
            printed_dates,
            year_basis,
            person or "",
            it_by or "",
            it_on,
            folders["backup_dir"],
            folders["anchor_dir"],
            folders["log_dir"],
            source_dir,
            office,
            relay,
            port,
        ),
        [],
    )


def fill(raw: dict[str, Any]) -> dict[str, Any]:
    """M1 (D-1280): the answers with every question nobody answered at its default: the marked name, backups later.
    Only a key that is not there is filled; an answer that is there and wrong stays, and :func:`parse` names it."""
    out = dict(raw)
    out.setdefault("site_name", PLACEHOLDER_NAME)
    if "backup" not in out:
        out.setdefault("backup_kind", BackupKind.LATER.value)
    return out


def without_backup(raw: dict[str, Any]) -> dict[str, Any]:
    """``raw`` with backups left for later: a disk the answers name that this machine does not have."""
    out = {k: v for k, v in raw.items() if k not in ("backup", "backup_disk", "backup_share", "backup_dir")}
    return {**out, "backup_kind": BackupKind.LATER.value}


def stand_ins(a: OwnerAnswers) -> frozenset[str]:
    """M1 (D-1280): the items of ``site_needs`` the box runs on a value of its own for, until the hospital gives one.
    The install marks them; the step that needs one refuses it on a PRODUCTION box and warns elsewhere."""
    open_ = {
        "site_name": a.site_name == PLACEHOLDER_NAME,
        "chart_number": not a.chartno_rule,
        "data_source": a.source is SourceKind.LATER,
        "backup_target": a.backup.kind is BackupKind.LATER,
        "backup_alarm": not a.health_page_person,
        "audit_share": not a.anchor_dir,
        "office_mailbox": not a.sae_office_mailbox,
    }
    return frozenset(k for k, v in open_.items() if v)


def production_gaps(a: OwnerAnswers, *, chartno_asked: bool = True) -> list[Problem]:
    """10K-21 (D-1365): what a PRODUCTION box's first run may not leave silent. The chart-number rule: an explicit
    answer (``asis`` is one; no answer is not), unless the page could not ask it (the box already holds patients, or
    that could not be read: ``chartno_asked`` False). The person who opens the health page every working day: a box's
    backup alert route is the health page (``tools.box.plan``, D-735), and a route nobody is named for is no route.
    The caller decides whether the box is PRODUCTION; IT's confirmation of the root certificate is never a gap here
    (the box makes its root at its first start: ``doctor`` reports it until it is recorded)."""
    gaps: list[Problem] = []
    if chartno_asked and not a.chartno_rule:
        gaps.append(Problem("chartno_rule", "chartno_required"))
    if not a.health_page_person:
        gaps.append(Problem("health_page_person", "health_page_person_required"))
    return gaps


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
