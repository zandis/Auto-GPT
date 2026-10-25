"""Repository over the criterion-library tables (``ddl.py``), keyed by canonical hash (spec v4 §6.2.7, §6.3)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tb_common.ulid import new_ulid
from tb_contracts.criterion_ir import (
    CriterionIRv3,
    CriterionLibraryRecord,
    LibraryApproval,
    LibraryRef,
    LibraryText,
    LibraryValueSet,
    canonical_hash,
    valueset_content_hash,
)

from criteria_compiler.library.ddl import DDL, SCHEMA_VERSION

SeedSource = Literal["chia", "ctgov", "site"]


class LibraryError(ValueError):
    """A library operation that would break an invariant (unknown id, status change not allowed, ...)."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valuesets_used(ir: CriterionIRv3) -> list[str]:
    names = {a.valueset for a in ir.atoms if a.valueset and a.valueset != "NONE"}
    names |= {a.aggregate.weight_valueset for a in ir.atoms if a.aggregate and a.aggregate.weight_valueset}
    return sorted(names)


class CriterionLibrary:
    """SQLite-backed criterion library. ``path`` may be ``":memory:"`` (tests)."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(DDL)
        self.db.execute(
            "INSERT OR IGNORE INTO criterion_library_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------------------------------- hashing
    @staticmethod
    def hash_of(ir: CriterionIRv3, valuesets: Mapping[str, Mapping[str, Any]] | None = None) -> str:
        """Canonical hash with ValueSet names replaced by the content hashes of the given ValueSet resources."""
        vsh = {name: valueset_content_hash(vs) for name, vs in (valuesets or {}).items()}
        return canonical_hash(ir, vsh)

    # ------------------------------------------------------------------------------------------- reads
    def _row_record(self, row: tuple[Any, ...] | None) -> CriterionLibraryRecord | None:
        return None if row is None else CriterionLibraryRecord.model_validate_json(row[0])

    def get(self, lib_id: str) -> CriterionLibraryRecord | None:
        cur = self.db.execute("SELECT record_json FROM criterion_library WHERE lib_id = ?", (lib_id,))
        return self._row_record(cur.fetchone())

    def by_hash(self, chash: str) -> CriterionLibraryRecord | None:
        cur = self.db.execute("SELECT record_json FROM criterion_library WHERE canonical_hash = ?", (chash,))
        return self._row_record(cur.fetchone())

    def records(self, status: str | None = None) -> list[CriterionLibraryRecord]:
        if status is None:
            cur = self.db.execute("SELECT record_json FROM criterion_library ORDER BY lib_id")
        else:
            cur = self.db.execute(
                "SELECT record_json FROM criterion_library WHERE status = ? ORDER BY lib_id", (status,)
            )
        return [CriterionLibraryRecord.model_validate_json(r[0]) for r in cur.fetchall()]

    def used_by(self, ruleset: str) -> list[str]:
        cur = self.db.execute(
            "SELECT lib_id FROM criterion_library_usage WHERE ruleset = ? ORDER BY lib_id", (ruleset,)
        )
        return [str(r[0]) for r in cur.fetchall()]

    def with_valueset(self, sha: str) -> list[str]:
        cur = self.db.execute(
            "SELECT DISTINCT lib_id FROM criterion_library_valueset WHERE sha = ? ORDER BY lib_id", (sha,)
        )
        return [str(r[0]) for r in cur.fetchall()]

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM criterion_library").fetchone()[0])

    # ------------------------------------------------------------------------------------------- writes
    def put(self, record: CriterionLibraryRecord) -> None:
        """Insert or replace one record (the record JSON is the source of truth; child tables are rebuilt)."""
        rec = CriterionLibraryRecord.model_validate(record.model_dump(by_alias=True))
        if rec.ir.canonical_hash not in (None, rec.canonical_hash):
            raise LibraryError(f"{rec.lib_id}: ir.canonical_hash differs from the record's canonical_hash")
        now = _now()
        with self._tx() as db:
            other = db.execute(
                "SELECT lib_id FROM criterion_library WHERE canonical_hash = ? AND lib_id <> ?",
                (rec.canonical_hash, rec.lib_id),
            ).fetchone()
            if other:
                raise LibraryError(f"canonical hash {rec.canonical_hash} already belongs to {other[0]}")
            created = db.execute("SELECT created_at FROM criterion_library WHERE lib_id = ?", (rec.lib_id,)).fetchone()
            db.execute(
                "INSERT OR REPLACE INTO criterion_library (lib_id, canonical_hash, schema_version, ir_version, status,"
                " kind, class, seed_source, approved_gate, approval_id, supersedes, data_class, record_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.lib_id,
                    rec.canonical_hash,
                    rec.schema_version,
                    rec.ir.ir_version,
                    rec.status,
                    rec.kind,
                    rec.class_,
                    rec.seed_source,
                    rec.approved.gate if rec.approved else None,
                    rec.approved.approval if rec.approved else None,
                    rec.supersedes,
                    rec.data_class,
                    rec.model_dump_json(by_alias=True, exclude_none=True),
                    created[0] if created else now,
                    now,
                ),
            )
            for table in ("text", "valueset", "lexicon_key", "usage"):
                db.execute(f"DELETE FROM criterion_library_{table} WHERE lib_id = ?", (rec.lib_id,))
            db.executemany(
                "INSERT OR IGNORE INTO criterion_library_text (lib_id, lang, source, text) VALUES (?, ?, ?, ?)",
                [(rec.lib_id, t.lang, t.source, t.text) for t in rec.texts],
            )
            db.executemany(
                "INSERT OR REPLACE INTO criterion_library_valueset (lib_id, valueset_id, sha, terminology_version)"
                " VALUES (?, ?, ?, ?)",
                [(rec.lib_id, v.id, v.sha, v.terminology_version) for v in rec.valuesets],
            )
            db.executemany(
                "INSERT OR IGNORE INTO criterion_library_lexicon_key (lib_id, entry_id) VALUES (?, ?)",
                [(rec.lib_id, k) for k in rec.lexicon_keys],
            )
            db.executemany(
                "INSERT OR IGNORE INTO criterion_library_usage (lib_id, ruleset) VALUES (?, ?)",
                [(rec.lib_id, r) for r in rec.used_by],
            )

    def add(
        self,
        ir: CriterionIRv3,
        *,
        seed_source: SeedSource,
        valuesets: Mapping[str, Mapping[str, Any]] | None = None,
        terminology_version: str | None = None,
        text_source: str | None = None,
    ) -> tuple[CriterionLibraryRecord, bool]:
        """Add ``ir`` as a ``draft`` record, or attach its text and ruleset to the record with the same canonical
        hash. Returns ``(record, created)``."""
        chash = self.hash_of(ir, valuesets)
        text = LibraryText(lang=ir.text.lang or "und", text=ir.text.source, source=text_source or ir.id)
        existing = self.by_hash(chash)
        if existing is not None:
            changed = False
            if not any(t.lang == text.lang and t.source == text.source for t in existing.texts):
                existing.texts.append(text)
                changed = True
            if ir.ruleset not in existing.used_by:
                existing.used_by.append(ir.ruleset)
                changed = True
            if changed:
                self.put(existing)
            return existing, False
        lib_ir = ir.model_copy(update={"canonical_hash": chash, "library_ref": None})
        vs_rows = [
            LibraryValueSet(
                id=name, sha=valueset_content_hash(valuesets[name]), terminology_version=terminology_version
            )
            for name in _valuesets_used(ir)
            if valuesets and name in valuesets
        ]
        rec = CriterionLibraryRecord.model_validate(
            {
                "lib_id": f"cl_{new_ulid()}",
                "canonical_hash": chash,
                "status": "draft",
                "kind": ir.kind,
                "class": ir.class_,
                "ir": lib_ir.model_dump(by_alias=True, exclude_none=True),
                "texts": [text.model_dump()],
                "valuesets": [v.model_dump() for v in vs_rows],
                "lexicon_keys": [k.entry_id for k in ir.lexicon_keys or []],
                "note_question": ir.note_question.model_dump(by_alias=True) if ir.note_question else None,
                "used_by": [ir.ruleset],
                "seed_source": seed_source,
            }
        )
        self.put(rec)
        return rec, True

    def match(self, ir: CriterionIRv3, valuesets: Mapping[str, Mapping[str, Any]] | None = None) -> LibraryRef:
        """``exact`` when an approved or draft record has the same canonical hash, else ``new`` ("match then draft",
        §10.1). Variant detection with a diff needs the extractor's retrieval step and is not done here."""
        rec = self.by_hash(self.hash_of(ir, valuesets))
        if rec is None or rec.status == "deprecated":
            return LibraryRef(match="new")
        return LibraryRef(lib_id=rec.lib_id, match="exact")

    def approve(self, lib_id: str, gate: str, approval: str) -> CriterionLibraryRecord:
        rec = self._require(lib_id)
        if rec.status == "deprecated":
            raise LibraryError(f"{lib_id} is deprecated and cannot be approved again")
        upd = rec.model_copy(update={"status": "approved", "approved": LibraryApproval(gate=gate, approval=approval)})
        self.put(upd)
        return upd

    def deprecate(self, lib_id: str) -> CriterionLibraryRecord:
        upd = self._require(lib_id).model_copy(update={"status": "deprecated"})
        self.put(upd)
        return upd

    def _require(self, lib_id: str) -> CriterionLibraryRecord:
        rec = self.get(lib_id)
        if rec is None:
            raise LibraryError(f"unknown library record {lib_id}")
        return rec

    def __enter__(self) -> CriterionLibrary:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def export(self) -> list[dict[str, Any]]:
        """Every record as JSON-ready dicts (for a release bundle or a diff)."""
        return [json.loads(r.model_dump_json(by_alias=True, exclude_none=True)) for r in self.records()]
