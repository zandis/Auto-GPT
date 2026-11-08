"""Write-back of TrialBox's screening instrument into REDCap (D-123, TB-PLAN-03 step 8).

TrialBox owns three fields on its own instrument (``tb_screen_date``, ``tb_status``, ``tb_status_date``) and writes
nothing else into an existing record. ``plan`` turns the study's screening numbers into REDCap import rows:

* a screening number REDCap already has (joined on the link field) gets an update of the three fields only;
* in ``create`` mode a screening number REDCap lacks gets a new record (auto-numbered by REDCap) carrying the link
  field and the three fields; in ``existing`` mode it waits until the coordinator creates the record;
* a row identical to the last one written (same hash) is skipped, so a nightly run writes only what changed;
* a screening number on two REDCap records (RC-LINK-DUP) is never written.

Nothing here talks to REDCap; ``orchestrator.study_api`` imports the rows with ``RedcapClient.import_records``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from rc_bridge.link import ProjectLink

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
