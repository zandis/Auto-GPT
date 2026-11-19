"""D-1253: the rule a store's lake ids were made under, recorded with the store, and never mixed.

A lake id of a record that belongs to a patient is made from the source's number **and** the patient (rule 2,
``adapter.mapping.engine.patient_resource_id``); before D-1253 it was made from the number alone (rule 1), and two
patients sharing a number were one record. Every id of a patient's record changed once with rule 2. A store that
keeps such ids and was written under rule 1 would hold ids no rule-2 night gives again: it is never added to.

* **Where the rule is kept.** Each NDJSON snapshot carries :data:`SNAPSHOT_RECORD` (written by
  ``adapter.ndjson.write_snapshot``); a snapshot without it was written under rule 1. Each store of the trial
  database that keeps lake ids (:data:`STORES`) has a ``tb_id_rule`` table (:data:`DDL`, a migration of its own):
  a row with :data:`RULE` says its ids are rule 2.
* **When a store is stamped.** :func:`ensure` runs in the store's own write transaction, before it writes lake ids:
  a store that already says :data:`RULE` goes on; one that holds no lake ids yet is stamped and goes on; one that
  holds lake ids and does not say :data:`RULE` is refused with :class:`IdRuleError`, naming the store and the
  runbook step. Nothing is written to it.
* **The night's check.** The adapter refuses a night, before it reads or writes anything, when the lake's snapshots
  or a store it can read (:func:`probe`) are under rule 1 (``adapter.pipeline.check_id_rule``).
* **The one way out** is the rebuild of ``python -m tools.id_rule_rebuild`` (runbook
  ``docs/runbook/30-lake-id-rule-rebuild.md``): every store above is cleared, the first night after it is a full one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RULE = 2
SNAPSHOT_RECORD = "id_rule.json"
RUNBOOK = "docs/runbook/30-lake-id-rule-rebuild.md"
COMMAND = "python -m tools.id_rule_rebuild"
#: the table each store keeps its rule in (one row per rule the store was stamped with)
DDL = (
    "CREATE TABLE IF NOT EXISTS tb_id_rule (rule INTEGER PRIMARY KEY CHECK (rule > 0), "
    "recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


@dataclass(frozen=True)
class Store:
    """A store of the trial database that keeps lake ids: its schema name (without the box's prefix) and the query
    that says whether it holds any (a Patient's id is not a lake id of this rule: a patient's pseudonym is the same
    under both rules)."""

    name: str
    schema: str
    table: str
    where: str = "TRUE"

    @property
    def holds(self) -> str:
        return f"SELECT 1 FROM {self.table} WHERE {self.where} LIMIT 1"  # noqa: S608 - the names are this module's


OMOP = Store("omop", "omop", "tb_record", "source_kind = 'feed' AND resource_type <> 'Patient'")
DERIVED = Store("derived", "derived", "score_row")
VEC = Store("vec", "vec", "note_chunk")
TWIN = Store("profile", "profile", "tb_patient_profile")
POOL = Store("orch", "orch", "pool")
EDC = Store("edc", "edc", "draft", "citation IS NOT NULL OR final_citation IS NOT NULL")
STORES = (OMOP, DERIVED, VEC, TWIN, POOL, EDC)


class IdRuleError(RuntimeError):
    """D-1253: a store (or the lake) holds lake ids made under an earlier rule: nothing is added to it."""

    def __init__(self, stores: Iterable[str]) -> None:
        self.stores = sorted(set(stores))
        super().__init__(
            f"lake ids of rule {RULE} (D-1253: a patient's record id holds the patient) cannot be added to "
            f"{', '.join(self.stores)}, which hold{'s' if len(self.stores) == 1 else ''} ids of an earlier rule: "
            f"nothing was written. Rebuild once ({COMMAND}; {RUNBOOK})"
        )


def stamped(tx: Any) -> bool:
    """Whether the store of ``tx`` (its search path) says :data:`RULE`."""
    return tx.fetchone("SELECT 1 FROM tb_id_rule WHERE rule = ?", (RULE,)) is not None


def ensure(tx: Any, store: Store) -> None:
    """In the store's write transaction, before lake ids are written: go on, stamp an empty store, or refuse."""
    if stamped(tx):
        return
    if tx.fetchone(store.holds) is not None:
        raise IdRuleError([store.name])
    tx.execute("INSERT INTO tb_id_rule (rule) VALUES (?) ON CONFLICT (rule) DO NOTHING", (RULE,))


# ------------------------------------------------------------------------------------------------ read-only checks
CURRENT, EMPTY, OLD, UNREAD = "current", "empty", "old", "not readable"


def probe(url: str, store: Store, schema: str | None = None) -> str:
    """The rule state of ``store`` in the trial database at ``url``, read only (no schema or table is made):
    :data:`CURRENT`, :data:`EMPTY` (no schema, no table, or no lake id), :data:`OLD`, or :data:`UNREAD` (this role may
    not read it: D-378 gives each service the schemas of its own work only)."""
    import psycopg

    from tb_common.db import split_url

    dsn, prefix = split_url(url)
    name = prefix + (schema or store.schema)
    missing = (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName)
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
        try:  # the store's own tables, read as they are: a schema or a table that is not there holds no lake id
            holds = con.execute(
                f'SELECT 1 FROM "{name}".{store.table} WHERE {store.where} LIMIT 1'  # noqa: S608 - names are ours
            ).fetchone()
        except missing:
            return EMPTY
        except psycopg.errors.InsufficientPrivilege:
            return UNREAD
        if holds is None:
            return EMPTY
        try:
            row = con.execute(f'SELECT 1 FROM "{name}".tb_id_rule WHERE rule = %s', (RULE,)).fetchone()  # noqa: S608
        except missing:  # a store not yet migrated to D-1253's version: written under rule 1
            return OLD
        except psycopg.errors.InsufficientPrivilege:
            return UNREAD
        return CURRENT if row is not None else OLD


def write_snapshot_record(directory: Path) -> None:
    (directory / SNAPSHOT_RECORD).write_text(json.dumps({"rule": RULE}) + "\n", encoding="utf-8")


def snapshot_rule(directory: Path) -> int:
    """The rule a snapshot's ids were made under: 1 when it carries no record (written before D-1253)."""
    try:
        return int(json.loads((directory / SNAPSHOT_RECORD).read_text(encoding="utf-8"))["rule"])
    except FileNotFoundError:
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        return 0  # unreadable: never taken for the current rule


def old_snapshots(ndjson_root: Path) -> list[str]:
    """The snapshots under ``ndjson_root`` (``<lake>/ndjson``) whose ids are not :data:`RULE`'s."""
    if not ndjson_root.is_dir():
        return []
    return sorted(
        p.name for p in ndjson_root.iterdir() if p.is_dir() and not p.name.startswith(".") and snapshot_rule(p) != RULE
    )
