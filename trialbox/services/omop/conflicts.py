"""Clinical conflicts for the people who settle them (T-201, D-426): the steward's view of ``tb_conflict``.

The loader (``omop.load``) records a conflict when two sources give different values for one patient item (today
birth date, sex and death date; ``kind`` ``source_vs_source``) and keeps it until the sources agree again or a person
settles it: a source that goes silent withdraws nothing (DATA-011). While a conflict is open the lake reads the item as
unknown, and unknown never excludes (D-130, D-144); once resolved the lake reads the chosen value (``omop.export``).

* :func:`listing`: the open conflicts (or every conflict, with the trail), each with the patient's pseudonym and the
  claims (value and source) the sources made;
* :func:`counts`: open conflicts per item, for a tile or a mail;
* :func:`resolve`: a person keeps one of the claimed values, or keeps the item unknown, with a reason. A value nobody
  claimed is refused (a resolution chooses, it does not type a new fact). The row keeps who, when, why and on what
  authority; nothing is deleted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tb_common.db import Database

from omop.load import resolve_conflict
from omop.schema import OmopError

ITEMS: tuple[str, ...] = ("birth_date", "sex", "deceased_date")
AUTHORITIES: tuple[str, ...] = ("steward", "pi_clinical_judgement", "hospital_record", "source_owner")
UNKNOWN = "unknown"  # the choice that keeps the item unknown
MAX_ROWS = 500


@dataclass(frozen=True)
class Conflict:
    conflict_id: int
    pid: str  # the patient's pseudonym (``tb_id_map``), never a chart number
    kind: str
    item: str
    claims: list[dict[str, Any]]  # [{"value": ..., "source": [kind, resource type, source id]}]
    state: str
    detected_at: datetime | None
    detected_batch: str
    resolved_value: str | None
    resolution: str | None
    reason: str | None
    authority: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    closed_batch: str | None

    @property
    def values(self) -> list[str]:
        """The distinct claimed values, in the order the sources gave them (the hospital's first)."""
        return list(dict.fromkeys(str(c.get("value")) for c in self.claims if c.get("value") is not None))


# whole statements, no string building (bandit B608)
_OPEN = (
    "SELECT c.conflict_id, coalesce(m.source_id, ''), c.kind, c.item, c.claims, c.state, c.detected_at, "
    "coalesce(c.detected_batch, ''), c.resolved_value, c.resolution, c.reason, c.authority, "
    "c.resolved_by, c.resolved_at, c.closed_batch FROM tb_conflict c LEFT JOIN tb_id_map m ON m.id_kind "
    "= 'person' AND m.omop_id = c.person_id WHERE c.state = 'open' ORDER BY c.conflict_id LIMIT ?"
)
_ALL = (
    "SELECT c.conflict_id, coalesce(m.source_id, ''), c.kind, c.item, c.claims, c.state, c.detected_at, "
    "coalesce(c.detected_batch, ''), c.resolved_value, c.resolution, c.reason, c.authority, "
    "c.resolved_by, c.resolved_at, c.closed_batch FROM tb_conflict c LEFT JOIN tb_id_map m ON m.id_kind "
    "= 'person' AND m.omop_id = c.person_id ORDER BY c.conflict_id DESC LIMIT ?"
)
_ONE = (
    "SELECT c.conflict_id, coalesce(m.source_id, ''), c.kind, c.item, c.claims, c.state, c.detected_at, "
    "coalesce(c.detected_batch, ''), c.resolved_value, c.resolution, c.reason, c.authority, "
    "c.resolved_by, c.resolved_at, c.closed_batch FROM tb_conflict c LEFT JOIN tb_id_map m ON m.id_kind "
    "= 'person' AND m.omop_id = c.person_id WHERE c.conflict_id = ?"
)


def _row(r: Any) -> Conflict:
    claims = r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]")
    return Conflict(int(r[0]), str(r[1]), str(r[2]), str(r[3]), claims, str(r[5]), r[6], str(r[7]), *r[8:15])


def listing(db: Database, everything: bool = False, limit: int = MAX_ROWS) -> list[Conflict]:
    """Open conflicts, oldest first; ``everything``: every state, newest first (the trail)."""
    return [_row(r) for r in db.fetchall(_ALL if everything else _OPEN, (int(limit),))]


def one(db: Database, conflict_id: int) -> Conflict | None:
    r = db.fetchone(_ONE, (int(conflict_id),))
    return _row(r) if r is not None else None


def counts(db: Database) -> dict[str, int]:
    """Open conflicts per item (every item of :data:`ITEMS` named, zero when none)."""
    got: dict[str, int] = dict(db.fetchall("SELECT item, count(*) FROM tb_conflict WHERE state = 'open' GROUP BY item"))
    return {i: int(got.get(i, 0)) for i in ITEMS} | {k: int(v) for k, v in got.items() if k not in ITEMS}


def resolve(db: Database, conflict_id: int, choice: str, by: str, reason: str, authority: str = "steward") -> Conflict:
    """Settle an open conflict: ``choice`` is one of its claimed values, or :data:`UNKNOWN`. Raises ``OmopError``
    for an unknown or already settled conflict, a value nobody claimed, or a missing reason."""
    c = one(db, conflict_id)
    if c is None or c.state != "open":
        raise OmopError(f"no open conflict {conflict_id}")
    if choice != UNKNOWN and choice not in c.values:
        raise OmopError("a resolution keeps a value one of the sources gave, or keeps the item unknown")
    resolve_conflict(db, conflict_id, None if choice == UNKNOWN else choice, by, reason, authority)
    got = one(db, conflict_id)
    if got is None:  # pragma: no cover - a conflict row is never deleted
        raise OmopError(f"no conflict {conflict_id}")
    return got
