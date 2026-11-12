"""Two-way sync between the data core and one source, under per-field ownership (D-123).

Every source (REDCap, a PI's spreadsheet, a FHIR bundle) is a ``Source``: ``pull`` returns its rows keyed by the
TrialBox record (screening number or pseudonym) and ``push`` writes TrialBox-owned fields back. The rules, per field:

* **source-owned** (attached to that source): a change at the source is taken; if TrialBox's value differs from what
  the source last said (TrialBox had its own value before the source was attached, or a person kept TrialBox's
  value in a resolution) the change is a **conflict**, listed and never forced. TrialBox never pushes these.
* **TrialBox-owned**: TrialBox's value is pushed when it changed since the last push. A different value at the source
  that TrialBox did not push is a **conflict** (someone changed TrialBox's field in the source); it is not taken.
* a blank at the source the first time it is seen is missing data, not a conflict.

``resolve`` closes a conflict with the person's choice: ``theirs`` takes the source's value, ``trialbox`` keeps
TrialBox's (and, for a TrialBox-owned field, pushes it again).

**The record key** (TB-PLAN-04 §2): the screening number first; else the pseudonym (the chart number turned into
the HMAC pseudonym with the site key at import); else the row is refused and listed in ``SyncResult.refused`` with
its place in the source, never guessed or matched on anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from datacore.store import TRIALBOX, DataCore, DataError


@dataclass
class Row:
    record: str
    event: str
    values: dict[str, str]
    source_id: str = ""


class Source(Protocol):
    name: str

    def fields(self) -> list[str]: ...  # TrialBox field names this source carries

    def pull(self) -> list[Row]: ...

    def push(self, rows: list[Row]) -> dict[str, str]: ...  # record -> the source's id for it


@dataclass
class SyncResult:
    source: str
    pulled: int = 0
    taken: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    pushed: int = 0
    created: dict[str, str] = field(default_factory=dict)
    waiting: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)  # rows with no usable key (never guessed)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "pulled": self.pulled, "taken": self.taken, "conflicts": self.conflicts,
                "pushed": self.pushed, "created": self.created, "waiting": self.waiting,
                "refused": self.refused}  # fmt: skip


def attach(dc: DataCore, study: str, source: Source, owned: list[str]) -> None:
    """Hand ``owned`` fields to the source; every other field it carries stays TrialBox's."""
    for f in owned:
        if f not in source.fields():
            raise DataError("DATA-FIELD", f"{source.name} does not carry {f}")
        dc.set_owner(study, f, source.name)


def detach(dc: DataCore, study: str, source: Source) -> None:
    for f, o in dc.owners(study).items():
        if o == source.name:
            dc.set_owner(study, f, TRIALBOX)


def sync(dc: DataCore, study: str, source: Source, by: str, at: str, push: bool = True) -> SyncResult:
    res = SyncResult(source.name)
    carried = set(source.fields())
    owners = dc.owners(study)
    rows = source.pull()
    res.refused = list(getattr(source, "refused", []) or [])
    for row in rows:
        res.pulled += 1
        if row.source_id:
            dc.put_source_id(study, source.name, row.record, row.source_id)
        for f, v in row.values.items():
            if f not in carried:
                continue
            v = str(v)
            owner = owners.get(f, TRIALBOX)
            cur = dc.get(study, row.record, row.event, f)

            def clash(theirs: str = v, cur: dict[str, Any] | None = cur, f: str = f, owner: str = owner,
                      row: Row = row) -> None:  # fmt: skip
                cid = dc.add_conflict(study, row.record, row.event, f, owner, source.name,
                                      cur["value"] if cur else None, theirs, at)  # fmt: skip
                if cid:
                    res.conflicts.append({"id": cid, "record": row.record, "event": row.event, "field": f,
                                          "owner": owner, "trialbox": cur["value"] if cur else None,
                                          "theirs": theirs})  # fmt: skip

            if owner == source.name:
                if cur is None:
                    if v != "":
                        dc.write(study, row.record, row.event, f, v, source.name, at, source.name, seen=v)
                        res.taken += 1
                elif cur["seen"] is None:
                    if v == "" or v == cur["value"]:
                        dc.mark(study, row.record, row.event, f, seen=v)
                    else:
                        clash()
                elif v != cur["seen"]:
                    if cur["value"] != cur["seen"]:
                        clash()
                    else:
                        dc.write(study, row.record, row.event, f, v, source.name, at, source.name, seen=v)
                        res.taken += 1
            elif owner == TRIALBOX:
                if cur is None:
                    if v != "":  # TrialBox has nothing yet: adopt the source's value as the starting point
                        dc.write(study, row.record, row.event, f, v, source.name, at, source.name, seen=v)
                        dc.mark(study, row.record, row.event, f, pushed=v)
                        res.taken += 1
                elif v in ("", cur["value"], cur["pushed"], cur["seen"]):
                    dc.mark(study, row.record, row.event, f, seen=v)
                else:
                    clash()
            # a field owned by another source is that source's business
    if push:
        _push(dc, study, source, res)
    return res


def _push(dc: DataCore, study: str, source: Source, res: SyncResult) -> None:
    owners = dc.owners(study)
    mine = [f for f in source.fields() if owners.get(f, TRIALBOX) == TRIALBOX]
    open_c = {(c["record"], c["event"], c["field"]) for c in dc.conflicts(study) if c["source"] == source.name}
    batch: dict[tuple[str, str], dict[str, str]] = {}
    for r in dc.values(study):
        if (
            r["field"] not in mine
            or r["value"] == (r["pushed"] or "")
            or (r["record"], r["event"], r["field"]) in open_c
        ):
            continue
        batch.setdefault((r["record"], r["event"]), {})[r["field"]] = r["value"]
    rows = [
        Row(rec, ev, vals, dc.source_id(study, source.name, rec) or "") for (rec, ev), vals in sorted(batch.items())
    ]
    if not rows:
        return
    ids = source.push(rows)
    for row in rows:
        sid = ids.get(row.record) or row.source_id
        if not sid:
            res.waiting.append(row.record)
            continue
        if not row.source_id:
            res.created[row.record] = sid
            dc.put_source_id(study, source.name, row.record, sid)
        for f, v in row.values.items():
            dc.mark(study, row.record, row.event, f, pushed=v, seen=v)
            res.pushed += 1


def resolve(dc: DataCore, cid: int, keep: str, by: str, at: str) -> dict[str, Any]:
    c = dc.conflict(cid)
    if c is None or c["resolved"]:
        raise DataError("DATA-CONFLICT", "no open conflict with that number")
    if keep not in ("theirs", "trialbox"):
        raise DataError("DATA-CONFLICT", "keep is theirs or trialbox")
    s, rec, ev, f = c["study"], c["record"], c["event"], c["field"]
    if keep == "theirs":
        dc.write(s, rec, ev, f, c["theirs"], by, at, f"resolve:{c['source']}", seen=c["theirs"])
        dc.mark(s, rec, ev, f, pushed=c["theirs"])
    else:
        dc.mark(s, rec, ev, f, seen=c["theirs"])
        if c["owner"] == TRIALBOX:
            dc.mark(s, rec, ev, f, pushed=c["theirs"])  # TrialBox's value differs from it: pushed on the next sync
    dc.close_conflict(cid, keep, by, at)
    return {**c, "resolved": keep, "resolved_by": by, "resolved_at": at}


def enter(dc: DataCore, study: str, record: str, event: str, values: dict[str, str], by: str, at: str) -> int:
    """A person enters values in TrialBox. A field owned by a source is changed in that source, never here."""
    from datacore.forms import check_value

    fields = dc.fields(study)
    owners = dc.owners(study)
    problems = []
    for f, v in values.items():
        if f not in fields:
            problems.append(f"{f}: not a field of this study")
        elif owners.get(f, TRIALBOX) != TRIALBOX:
            problems.append(f"{f}: owned by {owners[f]}")
        elif (why := check_value(fields[f], v)) is not None:
            problems.append(why)
    if problems:
        code = "DATA-OWNED" if any("owned by" in p for p in problems) else "DATA-VALUE"
        raise DataError(code, "; ".join(problems))
    return sum(dc.write(study, record, event, f, str(v), by, at, TRIALBOX) for f, v in values.items())


def form_fields(dc: DataCore, study: str, form: str) -> list[Any]:
    """The fields of one form, in order (``[]`` if the study has no such form)."""
    from datacore.forms import fields_of

    q = next((q for q in dc.forms(study) if q.get("name") == form), None)
    return fields_of(q) if q else []


def save_form(dc: DataCore, study: str, record: str, event: str, form: str, values: dict[str, str], by: str,
              at: str) -> dict[str, Any]:  # fmt: skip
    """A person saves a whole form (TB-PLAN-04 step 4). Checked together, refused together with every reason:

    * branching (``datacore.branching``) on the record's values with this save laid over them; a hidden field is
      never required and a value sent for it is not written (a value already stored stays);
    * required: only for shown fields, and not for a field whose rule is outside the subset (it is shown, but
      TrialBox cannot know whether REDCap would hide it);
    * type and range per field (``forms.problem``);
    * ownership as in ``enter``: a field owned by a source is changed in that source, never here.

    Returns ``{changed, written, hidden}``; raises ``DataError("DATA-FORM", ..., problems)``."""
    from datacore import branching
    from datacore.forms import problem, reason

    fields = form_fields(dc, study, form)
    if not fields:
        raise DataError("DATA-FORM", f"no form {form}", [{"field": form, "code": "form"}])
    by_name = {f.name: f for f in fields}
    owners = dc.owners(study)
    current = dc.record(study, record, event)
    merged = {**current, **{k: str(v) for k, v in values.items()}}
    problems: list[dict[str, str]] = [{"field": n, "code": "unknown"} for n in values if n not in by_name]
    write: dict[str, str] = {}
    hidden: list[str] = []
    for f in fields:
        sent = f.name in values
        v = str(values[f.name]) if sent else current.get(f.name, "")
        if f.kind in ("display", "calc"):
            if v != current.get(f.name, ""):
                problems.append({"field": f.name, "code": "not_entered"})
            continue
        owner = owners.get(f.name, TRIALBOX)
        if owner != TRIALBOX:
            if sent and v != current.get(f.name, ""):
                problems.append({"field": f.name, "code": "owned", "owner": owner})
            continue
        rule = branching.parse(f.branching) if f.branching else None
        if rule is not None and not branching.evaluate(rule, merged):
            if sent and v:
                hidden.append(f.name)
            continue
        if f.required and v == "" and not (f.branching and rule is None):
            problems.append({"field": f.name, "code": "required"})
            continue
        p = problem(f, v)
        if p is not None:
            problems.append(p)
        elif sent and v != current.get(f.name, ""):
            write[f.name] = v
    if problems:
        msg = "; ".join(reason(p, str(values.get(p["field"], ""))) for p in problems)
        raise DataError("DATA-FORM", msg, problems)
    changed = sum(dc.write(study, record, event, f, v, by, at, TRIALBOX) for f, v in write.items())
    return {"changed": changed, "written": sorted(write), "hidden": hidden}
