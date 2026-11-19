"""Japan's review committees and the head of the institution's permission (plan 10 card 10C-4, JP-3, D-1227).

The Japan profile's committees part is data (``japan_profile.json``, commitment C-7): each Japanese study kind names
the committee that reviews it and what the site must hold before the study opens. Read as the project's reading of
the public sources named in the file, to be confirmed by the first site's trial office:

* ``chiken`` (治験, GCP省令): the IRB (治験審査委員会) approves the current protocol version;
* ``tokutei`` (特定臨床研究, 臨床研究法): the CRB (認定臨床研究審査委員会) approves it;
* ``shishin`` (a study under the 倫理指針): the ethics committee (倫理審査委員会) reviews it, often once for every site
  (一括審査), and each site's head of institution (研究機関の長) permits it (実施許可) for that version.

The profile is on for a site whose country is Japan (``site.tz``) and a study whose kind is recorded; anywhere else
:func:`findings` says nothing, so a box outside Japan behaves as before. :func:`findings` is pure: the console's one
gate on a study's move to open (``console.study_setup``) refuses on a ``refuse`` finding, and the IRB page shows every
finding. Standard library only."""

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
BAD_FIELDS = (
    "kind",
    "current_version",
    "approved_version",
    "contract_on",
    "approved_on",
    "permission_version",
    "permission_permitted_on",
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
    external), the protocol version the site runs now, the version the committee approved and the date, and whether
    the review was central (一括審査). Documents are named by title and date only."""

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
            text = getattr(self, name)
            if text and (_day(text) is None or str(_day(text)) > today.isoformat()):
                bad.append(name)
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


def _same(a: str, b: str) -> bool:
    return bool(a) and a.strip().casefold() == b.strip().casefold()


def findings(country: str, rec: Committee, permission: Permission | None) -> list[tuple[str, str]]:
    """What the study lacks at this site, as ``(code, level)``; ``refuse`` stops the move to open. Nothing outside
    Japan, nothing for the other-country default (no kind recorded) beyond the one reminder that it is not chosen.

    * ``kind_unset`` (warn): a Japanese site's study whose kind is not recorded;
    * ``no_version`` (refuse): the protocol version the site runs now is not given;
    * ``no_approval`` / ``earlier_approval``: no committee approval, or one for an earlier version: refuse for a 治験
      or 特定臨床研究, warn for a 指針 study (its gate is the permission, given after the review);
    * ``no_permission`` / ``earlier_permission`` (refuse, 指針 study): no permission at this site, or one for an
      earlier version;
    * ``no_contract`` (warn): an external committee without the contract's date."""
    if not on(country):
        return []
    if not rec.kind:
        return [("kind_unset", WARN)]
    spec = profile()["study_kinds"][rec.kind]
    needs_approval = "approval" in spec["needs"]
    out: list[tuple[str, str]] = []
    if not rec.current_version:
        out.append(("no_version", REFUSE))
    elif not rec.approved_on:
        out.append(("no_approval", REFUSE if needs_approval else WARN))
    elif not _same(rec.approved_version, rec.current_version):
        out.append(("earlier_approval", REFUSE if needs_approval else WARN))
    if "permission" in spec["needs"] and rec.current_version:
        if permission is None or not permission.permitted_on:
            out.append(("no_permission", REFUSE))
        elif not _same(permission.version, rec.current_version):
            out.append(("earlier_permission", REFUSE))
    if rec.external and not rec.contract_on:
        out.append(("no_contract", WARN))
    return out


def refusals(found: list[tuple[str, str]]) -> list[str]:
    return [code for code, level in found if level == REFUSE]
