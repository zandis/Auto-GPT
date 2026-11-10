"""Checksummed schema migrations (T-104, D-204).

Every store's schema versions are whole scripts recorded in its own ``_schema_version`` with ``sha256`` and
``script_name``. Rows from before D-204 are back-filled once (``backfilled = true``) without failing; from then on a
changed applied script stops the store with :class:`MigrationChanged` naming the store and the version; a script
applied out of order is refused. ``PINNED`` below holds the checksum of every store's applied DDL as it is in the
code: a planted change to any of those strings fails :func:`test_no_applied_ddl_string_changed`. A new version is
appended to its store's tuple (and to ``PINNED``); an applied one is never edited.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tb_common.db import (
    AppliedVersion,
    Database,
    Migration,
    MigrationChanged,
    MigrationError,
    MigrationOrderError,
    extensions,
    read_migration_dir,
    script_sha256,
)

V1 = "CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)"
V2 = "ALTER TABLE marks ADD COLUMN note TEXT"
V3 = "CREATE TABLE notes (id INT PRIMARY KEY); CREATE INDEX notes_id ON notes (id)"


def _tables(db: Database) -> list[str]:
    return sorted(
        str(r[0])
        for r in db.fetchall("SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (db.schema,))
    )


def _pre_d204(db: Database, scripts: list[str]) -> None:
    """A store as every box had it before D-204: the scripts applied, ``_schema_version`` without checksums."""
    with db.transaction() as tx:
        tx.execute(
            "CREATE TABLE _schema_version (version BIGINT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        for n, script in enumerate(scripts, start=1):
            for stmt in (s.strip() for s in script.split(";")):
                if stmt:
                    tx.execute(stmt)
            tx.execute("INSERT INTO _schema_version (version) VALUES (?)", (n,))


# ----------------------------------------------------------------------------------------------- the record
def test_each_version_is_recorded_with_its_checksum_and_name(db_url: str) -> None:
    with Database.connect(db_url, "mig_rec") as db:
        assert db.applied() == []
        assert db.migrate([V1, Migration(2, V2, "002_note.sql")]) == 2
        rows = db.applied()
        assert [(r.version, r.sha256, r.script_name, r.backfilled) for r in rows] == [
            (1, script_sha256(V1), "v001", False),
            (2, script_sha256(V2), "002_note.sql", False),
        ]
        assert all(isinstance(r, AppliedVersion) and r.store == db.schema for r in rows)
        assert db.migrate([V1, V2]) == 2  # idempotent; a renamed script with the same text is not a change
        assert len(db.applied()) == 2


def test_back_fill_once_without_failing(db_url: str) -> None:
    with Database.connect(db_url, "mig_bf") as db:
        _pre_d204(db, [V1, V2])
        assert [r.sha256 for r in db.applied()] == [None, None]
        assert db.migrate([V1, V2]) == 2  # the first run after D-204 back-fills, never fails
        rows = db.applied()
        assert [(r.sha256, r.script_name, r.backfilled) for r in rows] == [
            (script_sha256(V1), "v001", True),
            (script_sha256(V2), "v002", True),
        ]
        stamp = [r.applied_at for r in rows]
        db.migrate([V1, V2, V3])  # once: later runs check against the back-filled record and append
        rows = db.applied()
        assert [r.backfilled for r in rows] == [True, True, False] and [r.applied_at for r in rows[:2]] == stamp
        with pytest.raises(MigrationChanged):
            db.migrate([V1, V2 + " ", V3])


def test_back_fill_only_covers_the_versions_passed(db_url: str) -> None:
    with Database.connect(db_url, "mig_bf2") as db:
        _pre_d204(db, [V1, V2])
        db.migrate([])  # reading the version (tools.trialbox.update does this) back-fills nothing
        assert [r.sha256 for r in db.applied()] == [None, None]
        db.migrate([V1])
        assert [r.backfilled for r in db.applied()] == [True, False] and db.applied()[1].sha256 is None


def test_a_changed_applied_version_is_refused_naming_store_and_version(db_url: str) -> None:
    with Database.connect(db_url, "mig_chg") as db:
        db.migrate([V1, V2])
        changed = V2.replace("note", "remark")
        with pytest.raises(MigrationChanged) as ei:
            db.migrate([V1, changed, V3])  # the new version 3 is not applied either
        e = ei.value
        assert (e.store, e.version, e.script_name) == (db.schema, 2, "v002")
        assert (e.recorded, e.current) == (script_sha256(V2), script_sha256(changed))
        assert f"store {db.schema!r}" in str(e) and "schema version 2" in str(e)
        assert isinstance(e, MigrationError) and "notes" not in _tables(db) and len(db.applied()) == 2
        with pytest.raises(MigrationChanged):  # whitespace is a change too: the text is hashed as it is
            db.migrate([V1 + "\n", V2])


def test_a_new_version_appended_passes(db_url: str) -> None:
    with Database.connect(db_url, "mig_app") as db:
        db.migrate([V1])
        db.execute("INSERT INTO marks (pid, mark) VALUES (?, ?)", ("p1", "approach"))
        assert db.migrate([V1, V2, V3]) == 3
        assert [r.version for r in db.applied()] == [1, 2, 3]
        assert db.fetchall("SELECT pid, mark, note FROM marks") == [("p1", "approach", None)]
        assert "notes" in _tables(db)


def test_two_stores_with_version_3_do_not_collide(db_url: str) -> None:
    a_scripts = [V1, V2, "CREATE TABLE a_only (id INT)"]
    b_scripts = ["CREATE TABLE b1 (id INT)", "CREATE TABLE b2 (id INT)", "CREATE TABLE b3 (id INT)"]
    with Database.connect(db_url, "mig_a") as a, Database.connect(db_url, "mig_b") as b:
        a.migrate(a_scripts)
        b.migrate(b_scripts)
        a.migrate(a_scripts)
        b.migrate(b_scripts)
        assert [r.sha256 for r in a.applied()] == [script_sha256(s) for s in a_scripts]
        assert [r.sha256 for r in b.applied()] == [script_sha256(s) for s in b_scripts]
        assert {r.store for r in a.applied()} == {a.schema} and {r.store for r in b.applied()} == {b.schema}
        with pytest.raises(MigrationChanged) as ei:
            b.migrate([*b_scripts[:2], a_scripts[2]])
        assert ei.value.store == b.schema and ei.value.version == 3


# ----------------------------------------------------------------------------------------------- order
def test_a_script_applied_out_of_order_is_refused(db_url: str) -> None:
    with Database.connect(db_url, "mig_ord") as db:
        db.migrate([V1, V2, V3])
        db.execute("DELETE FROM _schema_version WHERE version = 2")  # version 3 ran without version 2
        with pytest.raises(MigrationOrderError, match=r"skip version 2.*out of order"):
            db.migrate([V1, V2, V3])
        with pytest.raises(MigrationOrderError, match="position 1"):
            db.migrate([Migration(2, V2, "002_note.sql")])


def test_migrate_dir_reads_numbered_scripts(db_url: str, tmp_path: Path) -> None:
    d = tmp_path / "mig"
    d.mkdir()
    (d / "001_marks.sql").write_bytes(V1.encode())
    (d / "002_note.sql").write_bytes(b"ALTER TABLE marks ADD COLUMN note TEXT;\r\n")  # bytes as they are: CRLF kept
    (d / "README.txt").write_text("not a migration")
    migs = read_migration_dir(d)
    assert [(m.version, m.name) for m in migs] == [(1, "001_marks.sql"), (2, "002_note.sql")]
    assert migs[1].sha256 == script_sha256("ALTER TABLE marks ADD COLUMN note TEXT;\r\n")
    with Database.connect(db_url, "mig_dir") as db:
        assert db.migrate_dir(d) == 2
        assert [r.script_name for r in db.applied()] == ["001_marks.sql", "002_note.sql"]
        (d / "003_notes.sql").write_text(V3)
        assert db.migrate_dir(str(d)) == 3
        (d / "002_note.sql").write_bytes(b"ALTER TABLE marks ADD COLUMN note TEXT;\n")  # CRLF -> LF is a change
        with pytest.raises(MigrationChanged, match="002_note.sql"):
            db.migrate_dir(d)


@pytest.mark.parametrize(
    ("files", "match"),
    [
        (["001_a.sql", "003_c.sql"], "version 2 is missing before 003_c.sql"),
        (["002_b.sql"], "version 1 is missing"),
        (["001_a.sql", "001_b.sql"], "two scripts for version 1"),
        (["001_a.sql", "2_b.sql"], "NNN_<name>.sql"),
        (["001_a.sql", "a.sql"], "NNN_<name>.sql"),
    ],
)
def test_migrate_dir_refuses_gaps_duplicates_and_strays(tmp_path: Path, files: list[str], match: str) -> None:
    for f in files:
        (tmp_path / f).write_text("SELECT 1")
    with pytest.raises(MigrationOrderError, match=match):
        read_migration_dir(tmp_path)


def test_migrate_dir_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="does not exist"):
        read_migration_dir(tmp_path / "nope")


def test_the_workflow_backend_has_the_same_api(db_url: str, tmp_path: Path) -> None:
    from orchestrator.db_pg import MIGRATIONS, PostgresBackend

    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (id INT)")
    be = PostgresBackend(db_url, "mig_be")
    try:
        assert be.migrate_dir(tmp_path) == 1
        assert [r.script_name for r in be.applied()] == ["001_a.sql"]
        with pytest.raises(MigrationChanged, match="mig_be"):
            be.migrate(MIGRATIONS)  # the wf schema's version 1 is not this directory's
    finally:
        be.close()
    wf = PostgresBackend(db_url)
    try:
        wf.migrate(MIGRATIONS)
        assert [r.sha256 for r in wf.applied()] == [script_sha256(s) for s in MIGRATIONS]
    finally:
        wf.close()


def test_extensions_reports_what_is_installed(db_url: str) -> None:
    with Database.connect(db_url, "mig_ext") as db:
        got = extensions(db)
        assert set(got) == {"vector", "pgroonga"}  # None on a cluster without them (tools/pglocal.py)
        assert extensions(db, ("plpgsql",)) == {"plpgsql": db.fetchval("SELECT extversion FROM pg_extension "
                                                                       "WHERE extname = 'plpgsql'")}  # fmt: skip


# ----------------------------------------------------------------------------------------------- the stores
def store_migrations() -> dict[str, list[str]]:
    """Every store's schema versions, as each passes them to ``migrate`` (store name: its schema)."""
    from adapter import licensed, pidmap
    from console import auth, sitestore, teamstore
    from criteria_compiler.library import ddl as library
    from datacore import lifecycle
    from datacore import store as datacore
    from dataplat import mpi
    from edc import store as edc
    from mail_gateway import store as mail
    from omop import schema as omop
    from orchestrator import db as orch
    from orchestrator import db_pg, studystore
    from orchestrator.recall import ledger
    from sitesetup import store as sitesetup
    from tb_common import optout, refdata
    from tracestore import store as trace

    return {
        "refdata": [refdata.DDL],
        "optout": list(optout.MIGRATIONS),
        "wf": list(db_pg.MIGRATIONS),
        "recall": list(ledger.MIGRATIONS),
        "studies": list(studystore.MIGRATIONS),
        "orch": list(orch.MIGRATIONS),
        "sitesetup": [sitesetup.SCHEMA, sitesetup.SCHEMA_V2],
        "mail": [mail.SCHEMA_V1, mail.SCHEMA_V2],
        "mpi": [mpi.SCHEMA_V1],
        "library": [library.DDL],
        "terminology": [licensed.SCHEMA],
        "pidmap": list(pidmap.MIGRATIONS),
        "omop": omop.migrations(),
        "trace": [trace.SCHEMA_V1],
        "datacore": [datacore.SCHEMA, lifecycle.SCHEMA, lifecycle.SAE_SCHEMA],
        "auth": list(auth.MIGRATIONS),
        "site": list(sitestore.MIGRATIONS),
        "team": list(teamstore.MIGRATIONS),
        "edc": [edc.SCHEMA],
    }


#: sha256 of every store's applied schema versions (D-204). Append a new version's checksum; never edit one.
PINNED: dict[str, tuple[str, ...]] = {
    "refdata": ("abce30a55cd0af022855d67d6dfb60abd2ac6b76b63f4fcf871b48795cc823aa",),
    "optout": ("c2fc173c7d7df7894299b132c44b8f85cd477099b8234c7583b8ef03f4f90c80",),
    "wf": ("cf4331c1cfebbaf0a6f2cae40abcf355c7d163511232559b8a53c789237a5093",),
    "recall": ("d9ea5b8161e5241298321b3c464d503bc6801d22e0707c117a79821131474e6e",),
    "studies": (
        "5717d9a039883ec8978f59ee201464037183cb8e5f7f0767b679f688ef35d20e",
        "811adda424ba9d77e1176bd42e16c9aa7e7d4dcb0506daf65166f508a6f6a1d2",
        "5c03473c7c1d4842383c7536aa8f47483b2d7023af5b3081c66f2261aac7014d",
    ),
    "orch": ("9edc901b745b7b7e2aa1f2c87e0ad1f3d7860c6825e0e638be9cfb8320c40578",),
    "sitesetup": (
        "a5869c5da66e3335d50e18aaf520637d760ca8dd59a1216d1a2557872c896a3f",
        "eba55b194e0590fe228b7556c30e8409cfec5516f9d42d157c50ee8d8d296398",
    ),
    "mail": (
        "df646b957ffbad2bc96bb32327d51f6fe697e549781dc00f982d5065b8069908",
        "bde1c3613c70f347ce15a163c1c4df2c111ad93ad0e460c96c1687c14f9c20f2",
    ),
    "mpi": ("b52288b816a9aeca37187009f576159d8ee3901cdf539a57d962b30075cae022",),
    "library": ("564fff938db5977ada9d769d6a285708f839f937e9bcbdafd24f72a19b9a58e3",),
    "terminology": ("d7d6eb1dd726abc79b148fbd8f650a30606230f71d08d984ffaffdc24ae7a769",),
    "pidmap": ("0e1b2d77c92fecd822baf15acb7cfdb57db4137867869f1d48f079e89821363e",),
    "omop": (
        "d1b8130f6cc7ae41e0cadec24ad648f9b00919482ac98228c7dd18ed02c4fedb",
        "a9dfd840a8666e0060540bc6171819d22541a021dcd15ee8e6687ad203db292b",
    ),
    "trace": ("bfdb0077229852c4e139292ba57b6b1f79fffdd9610d33071b6478feba109cab",),
    "datacore": (
        "124270ebcd80078b44955fc22be582db67169b8566cefc3d2d8d764cfb1bab24",
        "0e3a813b0aea05c327f1443e830e0379bd8c13e623aaf4005baed29bec0f494b",
        "758a9577e1643839cf7ece62ae10bed88404a46b69c6a0252029e062bcd917a3",
    ),
    "auth": ("e9a25f1f3827e28dda3aa778c3a1fa46b7fc6b5a93ea23a5a3f27b160ada2f3e",),
    "site": (
        "61b88958f98cc442a6fc3ffd35fe1d4b561b1630ef045b6afe06c16391c4bbb5",
        "462f84721c6f0cc396262d232f3b8b32b3cb48fc09ef6ea8fceb84da47b1f99a",
    ),
    "team": ("f7e2ed4c4423ffa6e0c1d7c045108868a2eaf39a6ec829bd2b8536a2b9cdd632",),
    "edc": ("4adb60686c2312912b6d2991b58d3fe2f901b4d59b539c418090f79bec9b7260",),
}


def test_no_applied_ddl_string_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)  # the OMOP version 2 carries the default block
    now = {k: tuple(script_sha256(s) for s in v) for k, v in store_migrations().items()}
    assert set(now) == set(PINNED), "a store was added or removed: list it in store_migrations and PINNED"
    for store, pinned in PINNED.items():
        got = now[store]
        assert got[: len(pinned)] == pinned, (
            f"store {store!r}: an applied migration's text changed (version "
            f"{next(i for i, (a, b) in enumerate(zip(got, pinned, strict=False), 1) if a != b)}); "
            "add a new version instead (D-204)"
        )
        assert len(got) == len(pinned), f"store {store!r}: a new version was added: append its sha256 to PINNED"


def test_every_store_migrates_twice_and_checks_its_record(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_OMOP_CONCEPT_BLOCK", raising=False)
    for store, scripts in store_migrations().items():
        with Database.connect(db_url, f"pin_{store}") as db:
            db.migrate(scripts)
            db.migrate(scripts)
            assert [r.sha256 for r in db.applied()] == [script_sha256(s) for s in scripts], store
