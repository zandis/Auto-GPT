"""Japan's review committees and the head of the institution's permission (plan 10 card 10C-4, JP-3, D-1227).

The Japan profile's committees part is data (part P3 of the country layer ``japan_profile.json``, read through
``tb_common.country_layer``; commitment C-7, D-1250): each Japanese study kind names
the committee that reviews it and what this box records before the study opens. Read as the project's reading of
the public sources named in the file, to be confirmed by the first site's trial office. What is recorded here is not
the complete set of a site's requirements; the others are the site's own (the Japan pack, 10C-2):

* ``chiken`` (治験, GCP省令): the IRB's (治験審査委員会) approval of the current protocol version;
* ``tokutei`` (特定臨床研究, 臨床研究法): the CRB's (認定臨床研究審査委員会) approval of it;
* ``shishin`` (a study under the 倫理指針): this site's head of institution's permission (研究機関の長, 実施許可) for
  it, given after the ethics committee's (倫理審査委員会) review, often one review for every site (一括審査).

The profile is on for a site whose country is Japan; :func:`here` is the one place the console and the orchestrator
read the site (``TB_SITE_ID``) and its country (``TB_TZ``). Anywhere else :func:`findings` says nothing, so a box
outside Japan behaves as before. Each kind needs both records to open (``needs`` in the profile): the committee's
approval and the site's head-of-institution record (``permission_is``). The one rule, used by the console's moves into
open and by the orchestrator's open check before every list (``require_open`` and the timer's hold):

* :func:`at_open`, a move into open (start-up or paused to open, a close taken back to open): every refusal, and a
  study kind not chosen. Each opening is recorded (:class:`Opened`, ``why`` ``gate``: the kind and version opened);
* :func:`at_lists`, a list of a study the box treats as open, state row or not:
  - a study with no opening recorded and no mark is held as a move into open would be;
  - a study marked open before the rule (``why`` ``before_rule``, :func:`take_baseline`: every study open when the
    profile first applied at this site) is not held for a kind not chosen; once a kind is recorded the rule is whole;
  - a study opened through the gate is not held by an amendment's findings (``earlier_*``) while its kind is the one
    it opened with: as every amendment today (D-311, D-364) it screens on the version before; a kind changed since
    the opening holds it;
* :func:`in_waiting`, the rest for an open study, shown on the state page and the IRB page with the date the site
  sets, if any; nothing stops by itself. The baseline is the console's (at its start on a Japanese site, or its
  first read there); until a site has one, the rule has not arrived there and the orchestrator holds nothing.

Standard library only (and ``tb_common.db`` for :func:`read`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

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


def here(environ: Any = None) -> tuple[str, str]:
    """``(site id, country)`` of this box, the one reading for the console and the orchestrator: ``TB_SITE_ID`` (empty
    when unset: no permission is recorded) and the country of ``TB_TZ`` (``JP``, ``TW`` or "")."""
    import os

    from tb_common.derived import country_of

    env = os.environ if environ is None else environ
    return str(env.get("TB_SITE_ID") or "").strip(), country_of(str(env.get("TB_TZ") or "").strip()) or ""


def profile() -> dict[str, Any]:
    """The committees part (P3) of the country layer that carries one (the Japan profile)."""
    from tb_common import country_layer

    return dict(country_layer.having("P3", "committees").value("P3", "committees"))


def on(country: str) -> bool:
    """Is the committees part on for a site of ``country`` (``JP``, ``TW``, "")? Its country's layer carries it. A
    site whose country's layer is broken stays under its rule (True): :func:`profile` then raises
    ``country_layer.LayerBroken``, so a move into open is refused and the lists are held, never opened without the
    record (D-1250)."""
    from tb_common import country_layer

    lay = country_layer.layer(country)
    return lay.broken or bool(lay.value("P3", "committees"))


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


def at_lists(found: list[tuple[str, str]], rec: Committee, opened: Opened | None) -> list[str]:
    """What holds the lists of a study the box treats as open (see the module's rule)."""
    if opened is None:
        return at_open(found)
    exempt: set[str] = set()
    if opened.why == "before_rule" and not rec.kind:
        exempt.add("kind_unset")
    if opened.why == "gate" and rec.kind == opened.kind:
        exempt.update(AMENDMENT)
    return [code for code in at_open(found) if code not in exempt]


def in_waiting(found: list[tuple[str, str]], rec: Committee, opened: Opened | None) -> list[str]:
    """For an open study: what a move into open would refuse but its lists are not held by."""
    held = set(at_lists(found, rec, opened))
    return [code for code in at_open(found) if code not in held]


def held(country: str, rec: Committee, permission: Permission | None, opened: Opened | None, today: date) -> list[str]:
    """What holds an open study's lists at this site on ``today``."""
    return at_lists(findings(country, rec, permission, today), rec, opened)


def read(url: str, ruleset: str, site: str) -> tuple[Committee, Permission | None, Opened | None, bool] | None:
    """The study's committee record, this site's permission, its last opening and whether this site's baseline was
    taken, from the trial database (schema ``team``), for a reader that has no ``console.teamstore`` (the
    orchestrator). None when the console has not made the tables (the rule has not arrived at this box)."""
    from tb_common.db import Database

    rid = (ruleset or "").upper()
    with Database.connect(url, "team") as db:
        if len(db.applied()) < TEAM_VERSION:  # the store's own version record: no new table question (D-683)
            return None
        opened, taken = opened_of(db, rid, site), baseline_taken(db, site)
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
    return rec, (permission_row(perms[-1]) if perms and site else None), opened, taken


def committee_row(r: Any) -> Committee:
    t = [str(x or "") for x in r]
    return Committee(t[0], bool(r[1]), t[2], t[3], t[4], t[5], t[6], bool(r[7]), t[8], t[9], t[10], t[11])


@dataclass(frozen=True)
class Opened:
    """The last opening of a study at a site under the rule: ``gate`` (a move into open passed, with the kind and the
    protocol version it opened with) or ``before_rule`` (the study was open when the rule first applied here)."""

    kind: str = ""
    version: str = ""
    why: str = "gate"
    at: str = ""


TEAM_VERSION = 4  # console.teamstore's version that makes the committee tables
BASELINE = "*"  # the ruleset of the row that says this site's baseline was taken


def opened_of(db: Any, ruleset: str, site: str) -> Opened | None:
    rows = db.fetchall(
        "SELECT kind, version, why, at FROM committee_open WHERE ruleset = ? AND site = ? ORDER BY at, id",
        (ruleset, site),
    )
    return Opened(*(str(x or "") for x in rows[-1])) if rows else None


def record_open(db: Any, ruleset: str, site: str, opened: Opened, by: str, at: str) -> None:
    db.execute(
        "INSERT INTO committee_open (ruleset, site, kind, version, why, by, at) VALUES (?,?,?,?,?,?,?)",
        (ruleset, site, opened.kind, opened.version, opened.why, by, at),
    )


def baseline_taken(db: Any, site: str) -> bool:
    return opened_of(db, BASELINE, site) is not None


def take_baseline(db: Any, site: str, open_now: list[str], by: str, at: str) -> list[str]:
    """Mark the studies open now as open before the rule, once per site (the first call wins); returns those marked
    (empty when the baseline was taken before)."""
    if baseline_taken(db, site):
        return []
    marked = sorted({r.upper() for r in open_now if r and r != BASELINE})
    for rid in marked:
        if opened_of(db, rid, site) is None:
            record_open(db, rid, site, Opened(why="before_rule"), by, at)
    record_open(db, BASELINE, site, Opened(why="before_rule"), by, at)
    return marked


def permission_row(r: Any) -> Permission | None:
    """A stored permission row; a cleared one (no date) reads as no permission."""
    p = Permission(*(str(x or "") for x in r))
    return p if p.permitted_on else None
