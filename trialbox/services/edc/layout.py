"""Where a value lives in a REDCap project: arm, event, repeating instrument and instance (T-302b, D-414).

REDCap's flat export has one row per record, event and repeat instance: ``redcap_event_name`` (longitudinal
projects), ``redcap_repeat_instrument`` and ``redcap_repeat_instance`` (projects with repeating instruments or
events; both blank on the base row). TrialBox names the row of a value in its ``visit`` (one text, so the drafts,
decisions and signatures stay keyed by record and visit, as before):

* ``<event>``: the base row of an event (``event_1_arm_1`` in a classic project);
* ``<event>__<instrument>__<n>``: instance ``n`` of a repeating instrument on that event;
* ``<event>__<n>``: instance ``n`` of a repeating event.

:func:`slot_of` reads a visit against the project's events and repeating set; :class:`Layout` says whether a field
may be written to a row: its instrument designated for the event (``not_on_event``), the record's arm
(``wrong_arm``), a repeating instrument's field only on its own instance rows and never on the base row
(``repeating_form``, review E-05's hazard), and on an instance row only the fields of that instrument
(``not_repeating_form``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from datacore.export import BASE_EVENT

_REPEAT_INSTRUMENT = re.compile(r"(?P<head>[a-z][a-z0-9_]*?)__(?P<form>[a-z][a-z0-9_]*)__(?P<n>[1-9]\d{0,3})")
_REPEAT_EVENT = re.compile(r"(?P<head>[a-z][a-z0-9_]*?)__(?P<n>[1-9]\d{0,3})")


@dataclass(frozen=True)
class Slot:
    """One row of a record: the event, and for a repeat the instrument ("" for a repeating event) and instance."""

    event: str
    instrument: str = ""
    instance: int = 0

    @property
    def repeat(self) -> bool:
        return self.instance > 0

    @property
    def visit(self) -> str:
        if not self.repeat:
            return self.event
        if self.instrument:
            return f"{self.event}__{self.instrument}__{self.instance}"
        return f"{self.event}__{self.instance}"


def visit_of(event: str, instrument: str = "", instance: int = 0) -> str:
    """The visit text of a row (``event`` "" is the classic project's one event)."""
    return Slot(event or BASE_EVENT, instrument, instance).visit


def split_visit(visit: str, forms: Iterable[str]) -> Slot:
    """A visit read without the project: an instrument repeat when the middle part is one of ``forms``, an event
    repeat when it ends in ``__<n>``, else a base row. The ODM writer uses it; the send uses :meth:`Layout.slot`."""
    v = visit or BASE_EVENT
    known = set(forms)
    m = _REPEAT_INSTRUMENT.fullmatch(v)
    if m:
        for form in sorted(known, key=len, reverse=True):
            if v.endswith(f"__{form}__{m.group('n')}"):
                head = v[: -len(f"__{form}__{m.group('n')}")]
                if head:
                    return Slot(head, form, int(m.group("n")))
    m = _REPEAT_EVENT.fullmatch(v)
    if m:
        return Slot(m.group("head"), "", int(m.group("n")))
    return Slot(v)


def row_slot(row: dict[str, Any], longitudinal: bool) -> Slot:
    """The slot of one exported row."""
    ev = str(row.get("redcap_event_name") or "") if longitudinal else BASE_EVENT
    inst = str(row.get("redcap_repeat_instance") or "").strip()
    return Slot(ev or BASE_EVENT, str(row.get("redcap_repeat_instrument") or ""), int(inst) if inst.isdigit() else 0)


@dataclass
class Layout:
    """A project's arms, events, instrument designations and repeating set, as its API gives them."""

    longitudinal: bool
    events: dict[str, int] = field(default_factory=dict)  # unique event name -> arm number
    designated: dict[str, set[str]] = field(default_factory=dict)  # event -> instruments ({} = every one)
    repeating: set[tuple[str, str]] = field(default_factory=set)  # (event, instrument; "" = the whole event)

    @classmethod
    def read(cls, project: dict[str, Any], events: list[dict[str, Any]], mapping: list[dict[str, Any]],
             repeating: list[dict[str, Any]]) -> Layout:  # fmt: skip
        """From ``content=project``, ``event``, ``formEventMapping`` and ``repeatingFormsEvents``."""
        longitudinal = bool(int(project.get("is_longitudinal") or 0))
        evs = {str(e.get("unique_event_name")): int(e.get("arm_num") or 1) for e in events} if longitudinal else {}
        if not longitudinal:
            evs = {BASE_EVENT: 1}
        designated: dict[str, set[str]] = {}
        for m in mapping if longitudinal else []:
            designated.setdefault(str(m.get("unique_event_name")), set()).add(str(m.get("form")))
        rep = {(str(r.get("event_name") or "") if longitudinal else BASE_EVENT, str(r.get("form_name") or ""))
               for r in repeating}  # fmt: skip
        rep = {(e or BASE_EVENT, f) for e, f in rep}
        return cls(longitudinal, evs, designated, rep)

    @property
    def repeats(self) -> bool:
        return bool(self.repeating)

    def repeating_instrument(self, event: str, form: str) -> bool:
        return (event, form) in self.repeating

    def repeating_event(self, event: str) -> bool:
        return (event, "") in self.repeating

    def slot(self, visit: str) -> Slot | None:
        """The row a visit names in this project, or None when it names none (``no_event``)."""
        v = visit or BASE_EVENT
        if v in self.events:
            return None if self.repeating_event(v) else Slot(v)  # a repeating event needs its instance
        for ev, form in self.repeating:
            if form:
                pre = f"{ev}__{form}__"
                if v.startswith(pre) and re.fullmatch(r"[1-9]\d{0,3}", v[len(pre) :]):
                    return Slot(ev, form, int(v[len(pre) :]))
            else:
                pre = f"{ev}__"
                if v.startswith(pre) and re.fullmatch(r"[1-9]\d{0,3}", v[len(pre) :]):
                    return Slot(ev, "", int(v[len(pre) :]))
        return None

    def on_event(self, event: str, form: str) -> bool:
        if not self.longitudinal:
            return True
        forms = self.designated.get(event)
        return True if forms is None and not self.designated else form in (forms or set())

    def misplaced(self, slot: Slot, form: str, arms: set[int]) -> str:
        """Why a field of instrument ``form`` cannot be written to ``slot`` of a record already on ``arms`` ("" if
        it can)."""
        if not self.on_event(slot.event, form):
            return "not_on_event"
        if arms and self.events.get(slot.event, 1) not in arms:
            return "wrong_arm"
        if slot.instrument and form != slot.instrument:
            return "not_repeating_form"
        if not slot.repeat and self.repeating_instrument(slot.event, form):
            return "repeating_form"
        return ""

    def import_row(self, rid: str, record: str, slot: Slot) -> dict[str, str]:
        """The keys of an import row for ``slot``."""
        row = {rid: record}
        if self.longitudinal:
            row["redcap_event_name"] = slot.event
        if slot.repeat:
            row["redcap_repeat_instrument"] = slot.instrument
            row["redcap_repeat_instance"] = str(slot.instance)
        return row

    def key(self, record: str, slot: Slot) -> tuple[str, str, str, int]:
        return record, slot.event, slot.instrument, slot.instance
