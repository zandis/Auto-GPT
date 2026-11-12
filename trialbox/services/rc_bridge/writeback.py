"""Write-back of TrialBox's screening instrument into REDCap (D-123, TB-PLAN-03 step 8).

TrialBox owns three fields on its own instrument (``tb_screen_date``, ``tb_status``, ``tb_status_date``) and writes
nothing else into an existing record. ``plan`` turns the study's screening numbers into REDCap import rows:

* a screening number REDCap already has (joined on the link field) gets an update of the three fields only;
* in ``create`` mode a screening number REDCap lacks gets a new record (auto-numbered by REDCap) carrying the link
  field and the three fields; in ``existing`` mode it waits until the coordinator creates the record;
* a row identical to the last one written (same hash) is skipped, so a nightly run writes only what changed;
* a screening number on two REDCap records (RC-LINK-DUP) is never written.

TB-PLAN-04 step 5 (D-134): the three fields are the data core's TrialBox-owned fields, so one writer owns each REDCap
field. ``orchestrator.study_api`` puts TrialBox's values into the data core and syncs them with ``LinkSource`` (the
S21 link as a data-core source): a value is pushed when it changed since the last push, and a REDCap-side edit of a
TrialBox field is listed as a conflict, never overwritten. ``plan`` stays as the rules' reference (tests).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from datacore.sync import Row

from rc_bridge.link import WRITE_FIELDS, ProjectLink

STATUSES = ("candidate", "contacted", "consented", "enrolled", "screen_fail", "declined", "withdrawn")
STATUS_CODES = {s: str(i) for i, s in enumerate(STATUSES, 1)}  # tb_status choices "1, candidate | 2, contacted | ..."


@dataclass
class Entry:
    """One screening number as TrialBox knows it."""

    no: str
    issued: str  # date the screening number was issued (YYYY-MM-DD)
    status: str  # registry status, "candidate" when the registry has no row yet
    status_at: str  # date of that status (YYYY-MM-DD)


@dataclass
class WritePlan:
    updates: list[dict[str, str]] = field(default_factory=list)  # rows for existing records
    creates: list[dict[str, str]] = field(default_factory=list)  # rows for new records (temporary names)
    hashes: dict[str, str] = field(default_factory=dict)  # screening number -> hash of what is written
    record_of: dict[str, str] = field(default_factory=dict)  # screening number -> REDCap record id (updates)
    waiting: list[str] = field(default_factory=list)  # existing mode: no REDCap record yet
    skipped_dup: list[str] = field(default_factory=list)
    unchanged: int = 0


def values(e: Entry) -> dict[str, str]:
    return {
        "tb_screen_date": e.issued[:10],
        "tb_status": STATUS_CODES.get(e.status, STATUS_CODES["candidate"]),
        "tb_status_date": e.status_at[:10],
    }


def digest(vals: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(vals, sort_keys=True).encode()).hexdigest()[:16]


def plan(
    link: ProjectLink,
    entries: list[Entry],
    existing: dict[str, list[str]],
    last: dict[str, str],
    id_field: str,
) -> WritePlan:
    """``existing``: link value -> REDCap record ids carrying it; ``last``: screening number -> last written hash."""
    out = WritePlan()
    for e in sorted(entries, key=lambda x: x.no):
        no = e.no.strip().upper()
        vals = values(e)
        h = digest(vals)
        rids = existing.get(no, [])
        if len(rids) > 1:
            out.skipped_dup.append(no)
            continue
        if rids and last.get(no) == h:
            out.unchanged += 1
            continue
        row: dict[str, str] = {}
        if link.write_event:
            row["redcap_event_name"] = link.write_event
        if rids:
            out.updates.append({id_field: rids[0], **row, **vals})
            out.record_of[no] = rids[0]
        elif link.write_mode == "create":
            if link.dag:
                row["redcap_data_access_group"] = link.dag
            out.creates.append({id_field: f"tb-new-{len(out.creates) + 1}", **row, link.link_field: no, **vals})
        else:
            out.waiting.append(no)
            continue
        out.hashes[no] = h
    return out


def existing_index(rows: list[dict[str, Any]], link: ProjectLink, id_field: str) -> dict[str, list[str]]:
    """Link value -> record ids, from an export of ``[id_field, link_field]`` (all events)."""
    idx: dict[str, set[str]] = {}
    for r in rows:
        v = str(r.get(link.link_field) or "").strip().upper()
        rid = str(r.get(id_field) or "")
        if v and rid:
            idx.setdefault(v, set()).add(rid)
    return {k: sorted(v) for k, v in idx.items()}


@dataclass
class LinkSource:
    """The S21 project link as a data-core source (``datacore.sync.Source``) for TrialBox's three screening fields.

    Only TrialBox's own screening numbers are read and written; a number on two REDCap records is never written
    (RC-LINK-DUP); a number without a record waits (``existing`` mode) or gets one (``create`` mode, auto-numbered by
    REDCap, with the link field and the link's DAG)."""

    client: Callable[[], Any]
    link: ProjectLink
    numbers: set[str]
    id_field: str = "record_id"
    name: str = "redcap-link"
    refused: list[dict[str, str]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    record_of: dict[str, str] = field(default_factory=dict)  # screening number -> REDCap record id (pulled)
    updated: dict[str, str] = field(default_factory=dict)  # this push
    created: dict[str, str] = field(default_factory=dict)

    def fields(self) -> list[str]:
        return list(WRITE_FIELDS)

    def pull(self) -> list[Row]:
        with self.client() as rc:
            rows = rc.records(fields=[self.id_field, self.link.link_field, *WRITE_FIELDS], dags=bool(self.link.dag))
        if self.link.dag:
            rows = [r for r in rows if str(r.get("redcap_data_access_group") or "") == self.link.dag]
        idx = existing_index(rows, self.link, self.id_field)
        self.duplicates = sorted(no for no in self.numbers if len(idx.get(no, [])) > 1)
        self.record_of = {no: ids[0] for no, ids in idx.items() if no in self.numbers and len(ids) == 1}
        out = []
        for no, rid in sorted(self.record_of.items()):
            vals: dict[str, str] = {}
            for r in rows:
                ev = str(r.get("redcap_event_name") or "")
                if str(r.get(self.id_field)) == rid and (not self.link.write_event or ev == self.link.write_event):
                    vals.update({f: str(r.get(f) or "") for f in WRITE_FIELDS if f in r})
            out.append(Row(no, "", vals, rid))
        return out

    def push(self, rows: list[Row]) -> dict[str, str]:
        upd: list[dict[str, str]] = []
        new: list[tuple[str, dict[str, str]]] = []
        for r in rows:
            if r.record in self.duplicates or r.record not in self.numbers:
                continue
            base: dict[str, str] = {"redcap_event_name": self.link.write_event} if self.link.write_event else {}
            if r.source_id:
                upd.append({self.id_field: r.source_id, **base, **r.values})
                self.updated[r.record] = r.source_id
            elif self.link.write_mode == "create":
                if self.link.dag:
                    base["redcap_data_access_group"] = self.link.dag
                new.append((r.record, {self.id_field: f"tb-new-{len(new) + 1}", **base,
                                       self.link.link_field: r.record, **r.values}))  # fmt: skip
        with self.client() as rc:
            if upd:
                rc.import_records(upd)
            ids = rc.import_records([n[1] for n in new], auto_number=True) if new else []
        self.created = {no: rid for (no, _), rid in zip(new, ids, strict=False)}
        return {**self.updated, **self.created}
