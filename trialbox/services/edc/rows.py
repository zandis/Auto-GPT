"""A REDCap record's rows as the send reads them, with branching logic and calculated fields (T-302b, D-414).

:class:`Rows` holds the exported rows of the records a send touches, keyed by record, event, repeating instrument
and instance (:mod:`edc.layout`), and answers what REDCap would show or compute on one row, with the values about to
be sent laid over what REDCap holds:

* :meth:`Rows.shown`: a field's branching logic on the row. A value for a field REDCap would hide is not sent
  (``hidden``); logic TrialBox cannot read holds the value back too (``logic``): TrialBox does not guess what REDCap
  would hide;
* :meth:`Rows.calculate`: a calculated field's value on the row; the send compares it with what REDCap computed;
* :meth:`Rows.hidden_values`: fields that hold a value while their branching logic hides them (REDCap's "erase
  hidden values" on a form save; the API import does not erase them).

A reference to a repeating instrument's field from outside its own instance row, without an instance, cannot be
resolved and raises :class:`edc.logic.LogicError` (TrialBox fails closed).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from datacore import forms

from edc import logic
from edc.layout import Layout, Slot, row_slot

Key = tuple[str, str, str, int]


def watched(meta: Mapping[str, Mapping[str, Any]], forms: Iterable[str], items: Iterable[str]) -> set[str]:
    """The fields a send reads besides its items: every field with branching logic or a calculation on ``forms``,
    and every field their logic and the items' logic refer to."""
    forms, items = set(forms), set(items)
    out: set[str] = set()
    for name, m in meta.items():
        on_form = str(m.get("form_name") or "") in forms
        is_calc = str(m.get("field_type") or "") == "calc"
        branch = str(m.get("branching_logic") or "")
        if (on_form or name in items) and (branch or is_calc):
            out.add(name)
            out |= logic.fields_of(branch)
            if is_calc:
                out |= logic.fields_of(str(m.get("select_choices_or_calculations") or ""))
    return {f for f in out if f in meta}


class Rows:
    def __init__(self, layout: Layout, meta: Mapping[str, Mapping[str, Any]], rid: str,
                 rows: Iterable[dict[str, Any]], today: date) -> None:  # fmt: skip
        self.layout = layout
        self.meta = meta
        self.rid = rid
        self.today = today
        self.rows: dict[Key, dict[str, Any]] = {}
        for r in rows:
            self.rows[layout.key(str(r.get(rid) or ""), row_slot(r, layout.longitudinal))] = r
        self.overlay: dict[Key, dict[str, str]] = {}

    def form(self, field: str) -> str:
        return str((self.meta.get(field) or {}).get("form_name") or "")

    def arms(self, record: str) -> set[int]:
        """The arms the record already has rows on (empty: a record with no event row yet)."""
        return {self.layout.events.get(k[1], 1) for k in self.rows if k[0] == record}

    def value(self, record: str, slot: Slot, field: str) -> str:
        """The value on the row: the one about to be sent, else what REDCap holds."""
        k = self.layout.key(record, slot)
        if field in self.overlay.get(k, {}):
            return self.overlay[k][field]
        return self.held(record, slot, field)

    def held(self, record: str, slot: Slot, field: str) -> str:
        """What REDCap holds on the row, never what the send is about to lay over it."""
        return self.held_at(self.layout.key(record, slot), field)

    def held_at(self, key: Key, field: str) -> str:
        """:meth:`held` by the row's key. A checkbox (REDCap exports one column per choice, named as
        :func:`datacore.forms.checkbox_column` names it) is the codes ticked, in its choice order (NEW-EDC-3b)."""
        row = self.rows.get(key) or {}
        m = self.meta.get(field) or {}
        if str(m.get("field_type") or "") == "checkbox" and field not in row:
            codes = [p.split(",", 1)[0].strip() for p in str(m.get("select_choices_or_calculations") or "").split("|")
                     if p.strip()]  # fmt: skip
            return ",".join(c for c in codes if str(row.get(forms.checkbox_column(field, c)) or "") == "1")
        return str(row.get(field) or "")

    def lay(self, record: str, slot: Slot, field: str, value: str) -> None:
        self.overlay.setdefault(self.layout.key(record, slot), {})[field] = value

    def unlay(self, record: str, slot: Slot, field: str) -> None:
        self.overlay.get(self.layout.key(record, slot), {}).pop(field, None)

    def _lookup(self, record: str, slot: Slot) -> logic.Lookup:
        def lookup(event: str | None, field: str, code: str | None, instance: int | None) -> str:
            if field not in self.meta:
                raise logic.LogicError(f"the logic names {field}, which is not in the data dictionary")
            ev = event or slot.event
            if self.layout.longitudinal and ev not in self.layout.events:
                raise logic.LogicError(f"the logic names the event {ev}, which the project does not have")
            form = self.form(field)
            if self.layout.repeating_instrument(ev, form):
                if instance is None and not (ev == slot.event and slot.instrument == form):
                    raise logic.LogicError(f"{field} repeats; the logic does not say which instance")
                at = Slot(ev, form, instance or slot.instance)
            elif self.layout.repeating_event(ev):
                if instance is None and not (ev == slot.event and slot.repeat and not slot.instrument):
                    raise logic.LogicError(f"the event {ev} repeats; the logic does not say which instance")
                at = Slot(ev, "", instance or slot.instance)
            else:
                at = Slot(ev)
            val = self.value(record, at, field)  # a checkbox: its ticks as laid, else as REDCap holds (NEW-EDC-3b)
            if code is not None:
                return "1" if code in [c.strip() for c in val.split(",")] else "0"
            return val

        return lookup

    def shown(self, record: str, slot: Slot, field: str) -> bool:
        """Whether REDCap shows ``field`` on the row (raises :class:`edc.logic.LogicError` when unreadable)."""
        rule = str((self.meta.get(field) or {}).get("branching_logic") or "")
        return logic.shown(rule, self._lookup(record, slot), self.today)

    def calculate(self, record: str, slot: Slot, field: str) -> str:
        expr = str((self.meta.get(field) or {}).get("select_choices_or_calculations") or "")
        return logic.calculate(expr, self._lookup(record, slot), self.today)

    def on_row(self, record: str, slot: Slot) -> list[str]:
        """The fields that live on this row (designated, the right instrument), in dictionary order."""
        arms = self.arms(record)
        return [f for f in self.meta if f != self.rid and not self.layout.misplaced(slot, self.form(f), arms)]

    def calcs(self, record: str, slot: Slot) -> list[dict[str, Any]]:
        """Each calculated field on the row: TrialBox's value beside REDCap's (``equal`` None: unreadable logic)."""
        out: list[dict[str, Any]] = []
        for f in self.on_row(record, slot):
            if str(self.meta[f].get("field_type") or "") != "calc":
                continue
            there = self.value(record, slot, f)
            try:
                mine = self.calculate(record, slot, f)
            except logic.LogicError:
                out.append({"item": f, "expected": "", "redcap": there, "equal": None})
                continue
            out.append({"item": f, "expected": mine, "redcap": there, "equal": logic.same_number(mine, there)})
        return out

    def hidden_values(self, record: str, slot: Slot) -> list[str]:
        """Fields on the row that hold a value while their branching logic hides them."""
        out = []
        for f in self.on_row(record, slot):
            if not str(self.meta[f].get("branching_logic") or "") or not self.value(record, slot, f).strip():
                continue
            try:
                if not self.shown(record, slot, f):
                    out.append(f)
            except logic.LogicError:
                continue
        return out
