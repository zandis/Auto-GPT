"""Japan's review committees and the head of the institution's permission (plan 10 card 10C-4, JP-3, D-1227).

The Japan profile's committees part is data (``japan_profile.json``, commitment C-7): each Japanese study kind names
the committee that reviews it and what this box records before the study opens. Read as the project's reading of
the public sources named in the file, to be confirmed by the first site's trial office. What is recorded here is not
the complete set of a site's requirements; the others are the site's own (the Japan pack, 10C-2):

* ``chiken`` (治験, GCP省令): the IRB's (治験審査委員会) approval of the current protocol version;
* ``tokutei`` (特定臨床研究, 臨床研究法): the CRB's (認定臨床研究審査委員会) approval of it;
* ``shishin`` (a study under the 倫理指針): this site's head of institution's permission (研究機関の長, 実施許可) for
  it, given after the ethics committee's (倫理審査委員会) review, often one review for every site (一括審査).

The profile is on for a site whose country is Japan (``site.tz``); anywhere else :func:`findings` says nothing, so a
box outside Japan behaves as before. The one rule, used by the console's moves into open and by the orchestrator's
open check before every list (``orchestrator.scheduler.require_open`` and the timer's hold):

* :func:`at_open`, a move into open (start-up or paused to open, a close taken back to open): every refusal, and a
  study kind not chosen;
* :func:`at_lists`, a list of a study the box treats as open: a study with no recorded state never passed the move
  into open, so every refusal holds it; a study recorded open is held by every refusal except the amendment ones
  (``earlier_*``: as every amendment today, D-311 and D-364, it keeps screening on the version before);
* :func:`in_waiting`, the rest for an open study (a kind not chosen, an amendment not yet approved or permitted):
  shown on the state page and the IRB page, with the date by which to record it when the site sets one; nothing
  stops by itself. A study already open when this rule arrived has no committee record, so it keeps running.

Standard library only (and ``tb_common.db`` for :func:`read`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

PROFILE = Path(__file__).with_name("japan_profile.json")
KINDS = ("chiken", "tokutei", "shishin")  # 治験, 特定臨床研究, 指針 study; "" is the other-country default
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,39}$")
REFUSE, WARN = "refuse", "warn"
COMMITTEES = ("irb", "crb", "ethics")  # 治験審査委員会, 認定臨床研究審査委員会, 倫理審査委員会
# what :func:`findings` names ("none": nothing is missing, the page's word)
CODES = ("kind_unset", "no_version", "no_approval", "earlier_approval", "no_permission", "earlier_permission",
         "no_contract", "none")  # fmt: skip
AMENDMENT = ("earlier_approval", "earlier_permission")
BAD_FIELDS = (
    "kind",
    "current_version",
    "approved_version",
    "contract_on",
    "approved_on",
    "due_on",
    "permission_version",
    "permission_permitted_on",
    "permission_site",
)  # what a record refused names (``problems``, ``permission_`` for the site's)


@cache
def _layer() -> dict[str, Any]:
    return dict(json.loads(PROFILE.read_text(encoding="utf-8")))


def profile() -> dict[str, Any]:
    """The committees part of the Japan profile (read once)."""
    return dict(_layer()["committees"])


def on(country: str) -> bool:
    """Is the Japan profile on for a site of ``country`` (``JP``, ``TW``, "")?"""
    return bool(country) and country.upper() == str(_layer()["country"])


def committee_of(kind: str) -> str:
    """The committee a study kind needs (``irb``, ``crb``, ``ethics``), or "" for the other-country default."""
    spec = profile()["study_kinds"].get(kind)
    return str(spec["committee"]) if spec else ""


@dataclass(frozen=True)
class Committee:
    """A study's committee record: its kind, the committee (internal or external, its 設置者, the contract date when
    external), the protocol version the site runs now, the version the committee approved and the date, whether the
    review was central (一括審査), the documents by title and date only, and the date by which what is missing is to
    be recorded, when the site sets one."""

    kind: str = ""
    external: bool = False
    establisher: str = ""
    contract_on: str = ""
    current_version: str = ""
    approved_version: str = ""
    approved_on: str = ""
    central: bool = False
    documents: str = ""
    by: str = ""
    at: str = ""
    due_on: str = ""

    @property
    def committee(self) -> str:
        return committee_of(self.kind)

    def problems(self, today: date) -> list[str]:
        """What is malformed, by field (empty when the record may be saved)."""
        bad = []
        if self.kind and self.kind not in KINDS:
            bad.append("kind")
        for name in ("current_version", "approved_version"):
            text = getattr(self, name)
            if text and not VERSION.match(text):
                bad.append(name)
        for name in ("contract_on", "approved_on"):
            day = _day(getattr(self, name))
            if getattr(self, name) and (day is None or day > today):
                bad.append(name)
        if self.due_on and _day(self.due_on) is None:
            bad.append("due_on")
        if self.approved_on and not self.approved_version:
            bad.append("approved_version")
        return bad


@dataclass(frozen=True)
class Permission:
    """One site's head-of-institution permission (実施許可): the site, the protocol version it covers, its date."""

    site: str = ""
    version: str = ""
    permitted_on: str = ""
    by: str = ""
    at: str = ""

    def problems(self, today: date) -> list[str]:
        bad = []
        if not self.site:
            bad.append("site")
        if self.version and not VERSION.match(self.version):
            bad.append("version")
        day = _day(self.permitted_on) if self.permitted_on else None
        if self.permitted_on and (day is None or day > today):
            bad.append("permitted_on")
        if bool(self.version) != bool(self.permitted_on):
            bad.append("permitted_on" if self.version else "version")
        return bad


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _held_by(text: str, today: date) -> bool:
    """A date recorded and not after the site's today (a date in the future is not yet held)."""
    day = _day(text) if text else None
    return day is not None and day <= today


def _same(a: str, b: str) -> bool:
    return bool(a) and a.strip().casefold() == b.strip().casefold()


def findings(country: str, rec: Committee, permission: Permission | None, today: date) -> list[tuple[str, str]]:
    """What the study lacks at this site on ``today`` (the site's day), as ``(code, level)``. Nothing outside Japan.

    * ``kind_unset`` (warn): a Japanese site's study whose kind is not recorded;
    * ``no_version`` (refuse): the protocol version the site runs now is not given;
    * ``no_approval`` / ``earlier_approval``: no committee approval (or one dated after today), or one for an earlier
      version: refuse for a 治験 or 特定臨床研究, warn for a 指針 study (its gate is the permission, given after the
      review);
    * ``no_permission`` / ``earlier_permission`` (refuse, 指針 study): no permission at this site (or one dated after
      today), or one for an earlier version;
    * ``no_contract`` (warn): an external committee without the contract's date (or one after today)."""
    if not on(country):
        return []
    if not rec.kind:
        return [("kind_unset", WARN)]
    spec = profile()["study_kinds"][rec.kind]
    needs_approval = "approval" in spec["needs"]
    out: list[tuple[str, str]] = []
    if not rec.current_version:
        out.append(("no_version", REFUSE))
    elif not _held_by(rec.approved_on, today):
        out.append(("no_approval", REFUSE if needs_approval else WARN))
    elif not _same(rec.approved_version, rec.current_version):
        out.append(("earlier_approval", REFUSE if needs_approval else WARN))
    if "permission" in spec["needs"] and rec.current_version:
        if permission is None or not _held_by(permission.permitted_on, today):
            out.append(("no_permission", REFUSE))
        elif not _same(permission.version, rec.current_version):
            out.append(("earlier_permission", REFUSE))
    if rec.external and not _held_by(rec.contract_on, today):
        out.append(("no_contract", WARN))
    return out


def refusals(found: list[tuple[str, str]]) -> list[str]:
    return [code for code, level in found if level == REFUSE]


def at_open(found: list[tuple[str, str]]) -> list[str]:
    """What refuses a move into open: every refusal, and a study kind not chosen (Japan profile only)."""
    return [code for code, level in found if level == REFUSE or code == "kind_unset"]


def at_lists(found: list[tuple[str, str]], recorded: bool) -> list[str]:
    """What holds the lists of a study the box treats as open. ``recorded``: its open state is recorded (it passed
    a move into open); a study with no recorded state is held by every refusal."""
    return [code for code in refusals(found) if not (recorded and code in AMENDMENT)]


def in_waiting(found: list[tuple[str, str]]) -> list[str]:
    """For a study recorded open: what a move into open would refuse but its lists are not held by."""
    held = set(at_lists(found, True))
    return [code for code in at_open(found) if code not in held]


def read(url: str, ruleset: str, site: str) -> tuple[Committee, Permission | None]:
    """The study's committee record and this site's permission from the trial database (schema ``team``), for a
    reader that has no ``console.teamstore`` (the orchestrator). No table yet: an empty record."""
    from tb_common.db import Database

    with Database.connect(url, "team") as db:
        if db.fetchval("SELECT to_regclass(?)", (f'"{db.schema}".committee',)) is None:
            return Committee(), None
        rows = db.fetchall(
            "SELECT kind, external, establisher, contract_on, current_version, approved_version, approved_on, central, "
            "documents, by, at, due_on FROM committee WHERE ruleset = ? ORDER BY at, id",
            ((ruleset or "").upper(),),
        )
        perms = db.fetchall(
            "SELECT site, version, permitted_on, by, at FROM site_permission WHERE ruleset = ? AND site = ? "
            "ORDER BY at, id",
            ((ruleset or "").upper(), site),
        )
    rec = committee_row(rows[-1]) if rows else Committee()
    return rec, (permission_row(perms[-1]) if perms and site else None)


def committee_row(r: Any) -> Committee:
    t = [str(x or "") for x in r]
    return Committee(t[0], bool(r[1]), t[2], t[3], t[4], t[5], t[6], bool(r[7]), t[8], t[9], t[10], t[11])


def permission_row(r: Any) -> Permission | None:
    """A stored permission row; a cleared one (no date) reads as no permission."""
    p = Permission(*(str(x or "") for x in r))
    return p if p.permitted_on else None
