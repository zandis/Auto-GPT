"""Erasure is an obligation of every store (T-727, D-465; review 2026-11-12 lifecycle F-7, root cause R4).

The stores are enumerated from the code, not from a hand list: every table every store's migrations create (the
same source as ``tests/unit/test_migrations.py``: :func:`store_migrations`), every top-level entry the lake and the
adapter write under the lake directory, every object-store key prefix. Each must have exactly one entry in
:mod:`tb_common.erasure`, and every entry must name something that still exists. A new table, lake folder or object
prefix fails here until its card gives it an obligation: erased (a clear, or owed by a card), kept (a decision) or
no patient data.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tb_common import erasure

from tests.unit.test_migrations import store_migrations

ROOT = Path(__file__).resolve().parents[2]

_CREATE = re.compile(r"\bCREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\"?[A-Za-z_][\w.\"]*)", re.I)
_DROP = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][\w.\"]*)", re.I)
_RENAME = re.compile(r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w.\"]+)\s+RENAME\s+TO\s+([\w\"]+)", re.I)
_COMMENT = re.compile(r"--[^\n]*")


def _name(raw: str) -> str:
    return raw.rsplit(".", maxsplit=1)[-1].strip('"')


def _body(text: str, at: int) -> str:
    """The parenthesised column list that starts at or after ``at`` (empty for ``PARTITION OF``)."""
    start = text.find("(", at)
    if start < 0 or text[at:start].strip().upper().startswith("PARTITION"):
        return ""
    depth = 0
    for i in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[start + 1 : i]
    return text[start + 1 :]


def tables_of(scripts: list[str]) -> set[str]:
    """The tables a store's migrations leave, in order: created or renamed to, less dropped or renamed away."""
    have: set[str] = set()
    for script in scripts:
        text = _COMMENT.sub("", str(script))
        events: list[tuple[int, str, str, str]] = [
            (m.start(), "create", _name(m[1]), "") for m in _CREATE.finditer(text)
        ]
        events += [(m.start(), "drop", _name(m[1]), "") for m in _DROP.finditer(text)]
        events += [(m.start(), "rename", _name(m[1]), _name(m[2])) for m in _RENAME.finditer(text)]
        for _, kind, a, b in sorted(events):
            if kind == "create":
                have.add(a)
            elif kind == "drop":
                have.discard(a)
            else:
                have.discard(a)
                have.add(b)
    return have


def migrated_tables(stores: dict[str, list[str]] | None = None) -> set[str]:
    """``schema.table`` of every table of every store (the store name is its schema)."""
    stores = store_migrations() if stores is None else stores
    return {f"{store}.{t}" for store, scripts in stores.items() for t in tables_of(scripts)}


#: the code that writes under the lake directory: the lake itself and the adapter (tools and tests are not the box)
LAKE_CODE = ("services/lake", "services/adapter")
_LAKE_PATH = re.compile(r"(?:self\.dir|lake_dir)\s*/\s*\"([^\"/]+)\"")
_LAKE_CONST = re.compile(r"^RERUN_DIR\s*=\s*\"([^\"]+)\"", re.M)


def lake_entries(root: Path = ROOT) -> set[str]:
    out: set[str] = set()
    for d in LAKE_CODE:
        for f in (root / d).rglob("*.py"):
            if "/tests/" in f.as_posix():
                continue
            text = f.read_text(encoding="utf-8")
            out |= {f"lake:{n}" for n in _LAKE_PATH.findall(text) + _LAKE_CONST.findall(text)}
    return out


_OBJECT_KEY = re.compile(r"\b(?:\w*key|base)\s*=\s*f\"([a-z][a-z_-]*)/")
#: a file whose keys are not object-store keys (the compiler's git refs)
NOT_OBJECT_KEYS = {"services/criteria_compiler/repo.py"}


def object_prefixes(root: Path = ROOT) -> set[str]:
    out: set[str] = set()
    for top in ("services", "libs"):
        for f in (root / top).rglob("*.py"):
            rel = f.relative_to(root).as_posix()
            if "/tests/" in rel or rel in NOT_OBJECT_KEYS:
                continue
            out |= {f"objects:{p}" for p in _OBJECT_KEY.findall(f.read_text(encoding="utf-8"))}
    return out


# ------------------------------------------------------------------------------------------------ the tables
def test_every_migrated_table_has_an_entry_and_every_entry_a_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    found = migrated_tables()
    assert len(found) > 150, "the scan read the stores"
    assert {"vec.note_chunk", "profile.tb_patient_profile", "orch.pool", "omop.tb_record_event"} <= found
    assert "omop.tb_unpart_note" not in found, "a table renamed and dropped by a later migration is gone"
    missing = sorted(found - set(erasure.TABLES))
    assert not missing, f"tables with no erasure obligation (add them to tb_common/erasure.py): {missing}"
    gone = sorted(set(erasure.TABLES) - found)
    assert not gone, f"erasure entries for tables no migration creates any more: {gone}"


def test_a_new_table_in_any_store_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    stores = store_migrations()
    stores["edc"] = [*stores["edc"], "CREATE TABLE IF NOT EXISTS countersign (id BIGINT, pid TEXT)"]
    stores["newstore"] = ['CREATE TABLE "widget" (pid TEXT)']
    assert migrated_tables(stores) - set(erasure.TABLES) == {"edc.countersign", "newstore.widget"}
    stores["vec"] = [*stores["vec"], "DROP TABLE note_chunk"]
    assert "vec.note_chunk" in set(erasure.TABLES) - migrated_tables(stores)


def test_the_scan_follows_renames_and_drops() -> None:
    scripts = [
        "CREATE TABLE a (x INT); CREATE TABLE IF NOT EXISTS s.b (y INT) -- CREATE TABLE ghost (z INT)",
        "ALTER TABLE a RENAME TO a_old; CREATE TABLE a (x INT) PARTITION BY RANGE (x); "
        "CREATE TABLE a_ydefault PARTITION OF a DEFAULT; DROP TABLE a_old",
    ]
    assert tables_of(scripts) == {"a", "b", "a_ydefault"}


# ------------------------------------------------------------------------------------------------ the lake and objects
def test_every_lake_entry_the_code_writes_has_an_obligation() -> None:
    found = lake_entries()
    assert {"lake:ndjson", "lake:db", "lake:parquet", "lake:embed_cache.duckdb", "lake:ndjson-rerun"} <= found
    assert found == set(erasure.LAKE), (
        f"no entry: {sorted(found - set(erasure.LAKE))}; no longer written: {sorted(set(erasure.LAKE) - found)}"
    )


def test_a_new_lake_folder_is_found(tmp_path: Path) -> None:
    (tmp_path / "services" / "lake").mkdir(parents=True)
    (tmp_path / "services" / "adapter").mkdir(parents=True)
    (tmp_path / "services" / "lake" / "store.py").write_text('p = self.dir / "quarantine" / snap\n', encoding="utf-8")
    (tmp_path / "services" / "adapter" / "x.py").write_text('RERUN_DIR = "again"\nq = lake_dir / "ndjson"\n')
    assert lake_entries(tmp_path) == {"lake:quarantine", "lake:again", "lake:ndjson"}


def test_every_object_prefix_the_code_writes_has_an_obligation() -> None:
    found = object_prefixes()
    assert {"objects:outputs", "objects:attachments"} <= found
    assert found == set(erasure.OBJECTS), (
        f"no entry: {sorted(found - set(erasure.OBJECTS))}; no longer written: {sorted(set(erasure.OBJECTS) - found)}"
    )


def test_a_new_object_prefix_is_found(tmp_path: Path) -> None:
    (tmp_path / "services" / "x").mkdir(parents=True)
    (tmp_path / "libs").mkdir()
    (tmp_path / "services" / "x" / "a.py").write_text('key = f"exports/{job_id}/{name}"\n', encoding="utf-8")
    assert object_prefixes(tmp_path) == {"objects:exports"}


# ------------------------------------------------------------------------------------------------ the entries
def test_every_entry_keeps_the_rules() -> None:
    assert erasure.problems() == []
    registry = (ROOT / "docs" / "decisions" / "REGISTRY.md").read_text(encoding="utf-8")
    owner = (ROOT / "docs" / "reviews" / "2026-11-10-critical-issues-register.md").read_text(encoding="utf-8")
    for k, e in erasure.entries().items():
        if e.kind == erasure.KEEP:  # the decision exists: a numbered record, or an owner decision (OD-n)
            assert f"| {e.decision} |" in (registry if str(e.decision).startswith("D-") else owner), (k, e.decision)
    es = erasure.entries()
    # the stores the review names (F-7) are all either cleared or on the owed list, never "no patient data"
    for k in ("lake:db", "lake:ndjson", "lake:parquet", "lake:embed_cache.duckdb", "outside:fhir_store",
              "omop.tb_record_event", "derived.score_row", "objects:outputs", "edc.draft", "outside:backups",
              "vec.note_chunk", "profile.tb_patient_profile"):  # fmt: skip
        assert es[k].kind == erasure.ERASE, k


_PATIENT_COLUMN = re.compile(r"\b(pid|person_id|subject_id|pid_hash|old_pid|mrn)\b")


def patient_tables_marked_none() -> list[str]:
    flagged: list[str] = []
    for store, scripts in store_migrations().items():
        text = _COMMENT.sub("", "\n".join(str(s) for s in scripts))
        for m in _CREATE.finditer(text):
            key = f"{store}.{_name(m[1])}"
            entry = erasure.TABLES.get(key)
            patient = _PATIENT_COLUMN.search(_body(text, m.end()))
            if patient and entry is not None and entry.kind == erasure.NO_PATIENT_DATA:
                flagged.append(key)
    return sorted(set(flagged))


def test_a_table_with_a_patient_column_is_never_no_patient_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classified from the columns: a pseudonym, a person id or a hash of a pseudonym is patient data."""
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    assert patient_tables_marked_none() == []
    monkeypatch.setitem(erasure.TABLES, "orch.pool", erasure.Entry(erasure.NO_PATIENT_DATA, "planted"))
    monkeypatch.setitem(erasure.TABLES, "pidmap.site_key", erasure.Entry(erasure.NO_PATIENT_DATA, "fingerprint"))
    assert patient_tables_marked_none() == ["orch.pool"]


def test_every_clear_resolves_and_the_worker_runs_each() -> None:
    names = [c.name for c in erasure.clears()]
    # T-723 (D-489) adds pid_pending: the pid map's staging of a held night
    # T-206b part 1 (D-798) adds owed_tables: the plain tables keyed by the pseudonym
    assert names == ["candidate_pool", "candidate_registry", "omop", "owed_tables", "pid_pending", "profile", "vec"]
    for c in erasure.clears():
        clear, verify = c.resolve()
        assert callable(clear) and callable(verify), c.name
        assert erasure.tables_of(c.name), c.name


def test_the_generated_page_is_current() -> None:
    assert erasure.DOC.read_text(encoding="utf-8") == erasure.render(), (
        "docs/validation/erasure-registry.md is out of date: python -m tb_common.erasure --write"
    )
    assert erasure.main(["--check"]) == 0


def test_the_page_lists_the_owed_and_the_check_fails_when_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = erasure.render()
    for key, card, _ in erasure.owed():
        assert f"| `{key}` | {card} |" in page
    stale = tmp_path / "erasure-registry.md"
    stale.write_text("# old\n", encoding="utf-8")
    monkeypatch.setattr(erasure, "DOC", stale)
    assert erasure.main(["--check"]) == 1
    assert "out of date" in capsys.readouterr().out
    assert erasure.main(["--write"]) == 0 and stale.read_text(encoding="utf-8") == page
    assert erasure.main([]) == 0 and capsys.readouterr().out == page
