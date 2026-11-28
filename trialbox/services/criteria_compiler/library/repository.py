"""Repository over the criterion-library tables (``ddl.py``), keyed by canonical hash (spec v4 §6.2.7, §6.3).

The library is site-owned, mutable state (drafts, gate approvals, deprecations, the rulesets that use a criterion),
so it lives in schema ``library`` of the trial database (D-126) like every other store the box owns."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from tb_common.db import ENV, Database
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
    """The criterion library in schema ``library`` of the trial database."""

    def __init__(self, url: str | None = None) -> None:
        """``url``: the trial database (``TB_DB_URL`` when ``None``; :class:`~tb_common.db.DatabaseError` if unset)."""
        self.db = Database.connect(url or os.environ.get(ENV), "library")
        self.db.migrate([DDL])
        self.db.execute(
            "INSERT INTO criterion_library_meta (key, value) VALUES ('schema_version', ?) ON CONFLICT DO NOTHING",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.db.close()

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
        row = self.db.fetchone("SELECT record_json FROM criterion_library WHERE lib_id = ?", (lib_id,))
        return self._row_record(row)

    def by_hash(self, chash: str) -> CriterionLibraryRecord | None:
        row = self.db.fetchone("SELECT record_json FROM criterion_library WHERE canonical_hash = ?", (chash,))
        return self._row_record(row)

    def records(self, status: str | None = None) -> list[CriterionLibraryRecord]:
        if status is None:
            rows = self.db.fetchall('SELECT record_json FROM criterion_library ORDER BY lib_id COLLATE "C"')
        else:
            rows = self.db.fetchall(
                'SELECT record_json FROM criterion_library WHERE status = ? ORDER BY lib_id COLLATE "C"', (status,)
            )
        return [CriterionLibraryRecord.model_validate_json(r[0]) for r in rows]

    def used_by(self, ruleset: str) -> list[str]:
        rows = self.db.fetchall(
            'SELECT lib_id FROM criterion_library_usage WHERE ruleset = ? ORDER BY lib_id COLLATE "C"', (ruleset,)
        )
        return [str(r[0]) for r in rows]

    def with_valueset(self, sha: str) -> list[str]:
        rows = self.db.fetchall(
            'SELECT DISTINCT lib_id COLLATE "C" FROM criterion_library_valueset WHERE sha = ? ORDER BY 1', (sha,)
        )
        return [str(r[0]) for r in rows]

    def count(self) -> int:
        return int(self.db.fetchval("SELECT COUNT(*) FROM criterion_library", default=0))

    # ------------------------------------------------------------------------------------------- writes
    def put(self, record: CriterionLibraryRecord) -> None:
        """Insert or replace one record (the record JSON is the source of truth; child tables are rebuilt)."""
        rec = CriterionLibraryRecord.model_validate(record.model_dump(by_alias=True))
        if rec.ir.canonical_hash not in (None, rec.canonical_hash):
            raise LibraryError(f"{rec.lib_id}: ir.canonical_hash differs from the record's canonical_hash")
        now = _now()
        with self.db.transaction() as tx:
            other = tx.fetchone(
                "SELECT lib_id FROM criterion_library WHERE canonical_hash = ? AND lib_id <> ?",
                (rec.canonical_hash, rec.lib_id),
            )
            if other:
                raise LibraryError(f"canonical hash {rec.canonical_hash} already belongs to {other[0]}")
            created = tx.fetchone("SELECT created_at FROM criterion_library WHERE lib_id = ?", (rec.lib_id,))
            tx.execute(
                "INSERT INTO criterion_library (lib_id, canonical_hash, schema_version, ir_version, status,"
                " kind, class, seed_source, approved_gate, approval_id, supersedes, data_class, record_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (lib_id) DO UPDATE SET canonical_hash = EXCLUDED.canonical_hash,"
                " schema_version = EXCLUDED.schema_version, ir_version = EXCLUDED.ir_version,"
                " status = EXCLUDED.status, kind = EXCLUDED.kind, class = EXCLUDED.class,"
                " seed_source = EXCLUDED.seed_source, approved_gate = EXCLUDED.approved_gate,"
                " approval_id = EXCLUDED.approval_id, supersedes = EXCLUDED.supersedes,"
                " data_class = EXCLUDED.data_class, record_json = EXCLUDED.record_json,"
                " created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at",
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
                tx.execute(f"DELETE FROM criterion_library_{table} WHERE lib_id = ?", (rec.lib_id,))
            tx.executemany(
                "INSERT INTO criterion_library_text (lib_id, lang, source, text) VALUES (?, ?, ?, ?)"
                " ON CONFLICT DO NOTHING",
                [(rec.lib_id, t.lang, t.source, t.text) for t in rec.texts],
            )
            tx.executemany(
                "INSERT INTO criterion_library_valueset (lib_id, valueset_id, sha, terminology_version)"
                " VALUES (?, ?, ?, ?) ON CONFLICT (lib_id, valueset_id) DO UPDATE SET sha = EXCLUDED.sha,"
                " terminology_version = EXCLUDED.terminology_version",
                [(rec.lib_id, v.id, v.sha, v.terminology_version) for v in rec.valuesets],
            )
            tx.executemany(
                "INSERT INTO criterion_library_lexicon_key (lib_id, entry_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [(rec.lib_id, k) for k in rec.lexicon_keys],
            )
            tx.executemany(
                "INSERT INTO criterion_library_usage (lib_id, ruleset) VALUES (?, ?) ON CONFLICT DO NOTHING",
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
        approved: LibraryApproval | None = None,
        supersedes: str | None = None,
    ) -> tuple[CriterionLibraryRecord, bool]:
        """Add ``ir`` as a ``draft`` record, or attach its text and ruleset to the record with the same canonical
        hash. Returns ``(record, created)``.

        ``approved``: the record is written ``approved`` with that gate and approval in the same single ``put`` (one
        transaction); a draft with the same hash is approved by it, an approved one keeps its own approval, a
        deprecated one is refused. ``supersedes``: the lib_id a new record replaces (it must exist; it is not
        changed)."""
        chash = self.hash_of(ir, valuesets)
        text = LibraryText(lang=ir.text.lang or "und", text=ir.text.source, source=text_source or ir.id)
        if supersedes is not None:
            self._require(supersedes)
        existing = self.by_hash(chash)
        if existing is not None:
            changed = False
            if approved is not None and existing.status == "deprecated":
                raise LibraryError(f"{existing.lib_id} is deprecated and cannot be approved again")
            if approved is not None and existing.status == "draft":
                existing = existing.model_copy(update={"status": "approved", "approved": approved})
                changed = True
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
                "status": "draft" if approved is None else "approved",
                "approved": approved.model_dump() if approved else None,
                "supersedes": supersedes,
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
