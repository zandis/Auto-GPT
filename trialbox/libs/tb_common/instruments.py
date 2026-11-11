"""The instrument copyright register (T-307, WS-04.5, D-375): what each licensed instrument's terms say, from public
sources, and the site's switches.

* :func:`register` reads ``catalogue/instruments.csv``: one row per instrument with its holder, ``licence``
  (``needed``, ``free-with-terms`` or ``unclear``), what the terms say, the source read and when, and the catalogue
  items it covers. An instrument with no items (EQ-5D, SF-36, FACT, EORTC, PROMIS) is listed and cannot be stored at
  all. :func:`check` refuses a register that names an item the catalogue does not have.
* What a site may keep of an item is the catalogue's ``storable`` (T-107, :mod:`tb_common.catalogue`) unless the site
  switched the instrument. A **switch** raises the level for all the instrument's items and needs a licence reference
  (:func:`switch`); with an empty reference it is refused. Going back to the catalogue's level needs none.
  The switches are one setting (:data:`SETTING`, a JSON object) of the site set-up store.
* :func:`refused_fact` is :func:`tb_common.catalogue.refused_fact` with the switches: a fact the catalogue's gate
  refuses is kept only when the site switched that instrument to a level that keeps item answers.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tb_common import catalogue

SETTING = "instrument_switches"
LICENCES = ("needed", "free-with-terms", "unclear")
MAX_REF = 200


class SwitchRefused(ValueError):
    """A switch the register's rules refuse; ``code`` names the rule for the page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    holder: str
    licence: str
    terms: str
    source: str
    checked: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class Switch:
    instrument: str
    storable: str
    licence_ref: str
    by: str
    at: str

    def as_dict(self) -> dict[str, str]:
        return {"storable": self.storable, "licence_ref": self.licence_ref, "by": self.by, "at": self.at}


def _rank(storable: str) -> int:
    return catalogue.STORABLE.index(storable)


def read(folder: Path | None = None) -> list[Instrument]:
    path = (folder or catalogue.catalogue_dir()) / "instruments.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        Instrument(
            id=r["instrument_id"].strip(),
            name=r["name"].strip(),
            holder=r["holder"].strip(),
            licence=r["licence"].strip(),
            terms=r["terms"].strip(),
            source=r["source"].strip(),
            checked=r["checked"].strip(),
            items=tuple(i.strip() for i in (r.get("items") or "").split(";") if i.strip()),
        )
        for r in rows
    ]


def check(instruments: list[Instrument], items: Mapping[str, catalogue.Item]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    owner: dict[str, str] = {}
    for ins in instruments:
        if not ins.id or ins.id in seen:
            problems.append(f"{ins.id or '(blank)'}: instrument id missing or given twice")
        seen.add(ins.id)
        if ins.licence not in LICENCES:
            problems.append(f"{ins.id}: licence {ins.licence!r} is not one of {', '.join(LICENCES)}")
        if not ins.terms or not ins.source or not ins.checked:
            problems.append(f"{ins.id}: terms, source and the date checked are required")
        for i in ins.items:
            if i not in items:
                problems.append(f"{ins.id}: item {i} is not in the catalogue")
            if i in owner:
                problems.append(f"{ins.id}: item {i} is already {owner[i]}'s")
            owner[i] = ins.id
    return problems


def register(folder: Path | None = None) -> list[Instrument]:
    """The register, checked against the catalogue; :class:`tb_common.catalogue.CatalogueError` otherwise."""
    rows = read(folder)
    problems = check(rows, {i.id: i for i in catalogue.items(folder)})
    if problems:
        raise catalogue.CatalogueError(problems)
    return rows


def default_storable(ins: Instrument, folder: Path | None = None) -> str:
    """The lowest ``storable`` of the instrument's items in the catalogue ('' for an instrument with no items)."""
    by_id = {i.id: i for i in catalogue.items(folder)}
    levels = [by_id[i].storable for i in ins.items if i in by_id]
    return min(levels, key=_rank) if levels else ""


# ------------------------------------------------------------------------------------------------ switches
def switches(value: str) -> dict[str, Switch]:
    """The switches held in the setting's ``value`` (empty or unreadable: none, so the catalogue's levels hold)."""
    try:
        raw = json.loads(value or "{}")
    except ValueError:
        return {}
    out: dict[str, Switch] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if not isinstance(v, dict) or v.get("storable") not in catalogue.STORABLE:
            continue
        ref = str(v.get("licence_ref") or "").strip()
        if not ref:
            continue  # a switch without a reference is never honoured, even if one was written by hand
        out[str(k)] = Switch(str(k), str(v["storable"]), ref, str(v.get("by") or ""), str(v.get("at") or ""))
    return out


def dump(sw: Mapping[str, Switch]) -> str:
    return json.dumps({k: s.as_dict() for k, s in sorted(sw.items())}, ensure_ascii=False, sort_keys=True)


def switch(
    current: Mapping[str, Switch],
    instrument_id: str,
    storable: str,
    licence_ref: str,
    by: str,
    at: str,
    folder: Path | None = None,
) -> dict[str, Switch]:
    """The switches after a site sets ``instrument_id`` to ``storable``. Raising it above the catalogue's level needs
    a licence reference (1 to :data:`MAX_REF` characters); setting it to the catalogue's level removes the switch.
    Lowering below the catalogue's level, an unknown instrument and one with no catalogue items are refused."""
    ins = {i.id: i for i in register(folder)}.get(instrument_id)
    if ins is None:
        raise SwitchRefused("unknown", f"{instrument_id!r} is not in the register")
    if not ins.items:
        raise SwitchRefused("no_items", f"{ins.id} has no catalogue item: nothing of it can be stored")
    if storable not in catalogue.STORABLE:
        raise SwitchRefused("storable", f"{storable!r} is not one of {', '.join(catalogue.STORABLE)}")
    base = default_storable(ins, folder)
    out = dict(current)
    if _rank(storable) < _rank(base):
        raise SwitchRefused("below", f"{ins.id}: the catalogue already keeps {base}; a switch only raises it")
    if storable == base:
        out.pop(ins.id, None)
        return out
    ref = " ".join((licence_ref or "").split())
    if not ref:
        raise SwitchRefused("no_ref", f"{ins.id}: keeping more than {base} needs the site's licence reference")
    if len(ref) > MAX_REF:
        raise SwitchRefused("long_ref", f"{ins.id}: the licence reference is longer than {MAX_REF} characters")
    out[ins.id] = Switch(ins.id, storable, ref, by, at)
    return out


def item_storable(item_id: str, sw: Mapping[str, Switch], folder: Path | None = None) -> str:
    """What the site may keep of one item: the catalogue's level, raised by its instrument's switch."""
    by_id = {i.id: i for i in catalogue.items(folder)}
    level = by_id[item_id].storable
    for ins in read(folder):
        if item_id in ins.items and ins.id in sw and _rank(sw[ins.id].storable) > _rank(level):
            return sw[ins.id].storable
    return level


def refused_fact(
    term: str, code: str = "", sw: Mapping[str, Switch] | None = None, folder: Path | None = None
) -> catalogue.Item | None:
    """The catalogue's gate (:func:`tb_common.catalogue.refused_fact`), with the site's switches: an instrument the
    site switched to keep item answers (with a licence reference) is not refused."""
    owner = catalogue.refused_fact(term, code, folder)
    if owner is None or not sw:
        return owner
    level = item_storable(owner.id, sw, folder)
    return None if "items" in level.split("+") else owner


def rows(sw: Mapping[str, Switch], folder: Path | None = None) -> list[dict[str, Any]]:
    """The register as the page shows it: each instrument, its items with the catalogue's and the site's level."""
    by_id = {i.id: i for i in catalogue.items(folder)}
    out = []
    for ins in register(folder):
        s = sw.get(ins.id)
        out.append(
            {
                "ins": ins,
                "default": default_storable(ins, folder),
                "switch": s,
                "items": [(by_id[i], item_storable(i, sw, folder)) for i in ins.items],
            }
        )
    return out
