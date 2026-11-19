"""Checksummed schema migrations (T-104, D-204).

Every store's schema versions are whole scripts recorded in its own ``_schema_version`` with ``sha256`` and
``script_name``. Rows from before D-204 are back-filled once (``backfilled = true``) without failing; from then on a
changed applied script stops the store with :class:`MigrationChanged` naming the store and the version; a script
applied out of order is refused. The D-204 baseline (:mod:`tb_common.migration_baseline`, shipped with the code, which
also gates the back-fill) plus ``ADDED`` below hold the checksum of every store's applied DDL: a planted change to any
of those strings fails :func:`test_no_applied_ddl_string_changed`. A new version is appended to its store's tuple and
its checksum to ``ADDED``; an applied one is never edited, and the baseline never changes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from tb_common.db import (
    AppliedVersion,
    Database,
    DatabaseError,
    Migration,
    MigrationChanged,
    MigrationError,
    MigrationOrderError,
    extensions,
    read_migration_dir,
    require_extensions,
    script_sha256,
)
from tb_common.migration_baseline import BASELINE, baseline_for

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


def _mail() -> list[str]:
    from mail_gateway.store import SCHEMA_V1, SCHEMA_V2

    return [SCHEMA_V1, SCHEMA_V2]


def test_back_fill_of_a_known_store_checks_the_baseline(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    """A box on a pre-D-204 schema whose first D-204 release carries an edited past DDL is refused, not recorded."""
    with Database.connect(db_url, "mail") as db:
        assert db.store == "mail" and baseline_for(db.store) == BASELINE["mail"]
        _pre_d204(db, _mail())
        edited = [_mail()[0] + " ", _mail()[1]]
        with pytest.raises(MigrationChanged) as ei:
            db.migrate(edited)
        assert (ei.value.version, ei.value.recorded) == (1, BASELINE["mail"][0])
        assert [r.sha256 for r in db.applied()] == [None, None]  # nothing recorded
        with caplog.at_level(logging.WARNING, logger="tb_common.db"):
            db.migrate(_mail())
        assert "back-filled" in caplog.text and "matches the baseline" in caplog.text
        rows = db.applied()
        assert [(r.sha256, r.backfilled) for r in rows] == [(h, True) for h in BASELINE["mail"]]
        assert all(r.backfilled_at is not None for r in rows)


def test_a_row_without_checksum_after_the_back_fill_is_refused(db_url: str) -> None:
    with Database.connect(db_url, "mig_late") as db:
        db.migrate([V1, V2])
        db.execute("UPDATE _schema_version SET sha256 = NULL WHERE version = 2")  # an old release or a hand edit
        with pytest.raises(MigrationError, match=r"\[2\] have no checksum"):
            db.migrate([V1, V2])
        db.execute("INSERT INTO _schema_version (version) VALUES (3)")  # an old release applying a version
        with pytest.raises(MigrationError, match="no checksum"):
            db.migrate([V1, V2, V3])


def test_a_restored_pre_d204_dump_is_back_filled_again_against_the_baseline(db_url: str) -> None:
    with Database.connect(db_url, "mail") as db:
        db.migrate(_mail())
        with db.transaction() as tx:  # what restoring a dump taken before D-204 brings back
            tx.execute("DROP TABLE _schema_version")
            tx.execute(
                "CREATE TABLE _schema_version (version BIGINT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL "
                "DEFAULT now())"
            )
            tx.execute("INSERT INTO _schema_version (version) VALUES (1), (2)")
        db.migrate(_mail())
        assert [r.backfilled for r in db.applied()] == [True, True]


def test_a_null_row_newer_than_the_baseline_is_refused(db_url: str) -> None:
    with Database.connect(db_url, "mail") as db:
        _pre_d204(db, [*_mail(), "CREATE TABLE later (id INT)"])
        with pytest.raises(MigrationError, match="newer than the D-204 baseline"):
            db.migrate([*_mail(), "CREATE TABLE later (id INT)"])


def test_the_baseline_covers_scratch_twins() -> None:
    assert baseline_for("omop_0123456789") == BASELINE["omop"]
    assert baseline_for("orch_rerun_ab12cd34") == BASELINE["orch"]
    assert baseline_for("mig_x") is None and baseline_for("release") is None


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


def test_migrate_dir_refuses_links_folders_odd_suffixes_and_non_utf8(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("SELECT 1")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.sql"
    outside.write_text("SELECT 2")
    (tmp_path / "002_b.sql").symlink_to(outside)
    with pytest.raises(MigrationOrderError, match="regular file"):
        read_migration_dir(tmp_path)
    (tmp_path / "002_b.sql").unlink()
    (tmp_path / "002_b.sql").mkdir()
    with pytest.raises(MigrationOrderError, match="regular file"):
        read_migration_dir(tmp_path)
    (tmp_path / "002_b.sql").rmdir()
    (tmp_path / "002_b.SQL").write_text("SELECT 2")
    with pytest.raises(MigrationOrderError, match="NNN_<name>.sql"):
        read_migration_dir(tmp_path)
    (tmp_path / "002_b.SQL").unlink()
    (tmp_path / "002_b.sql").write_bytes(b"SELECT '\xff'")
    with pytest.raises(MigrationError, match="002_b.sql is not UTF-8") as ei:
        read_migration_dir(tmp_path, "mystore")
    assert ei.value.store == "mystore"


def test_migrate_dir_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="does not exist"):
        read_migration_dir(tmp_path / "nope")


def test_the_workflow_backend_has_the_same_api(db_url: str, tmp_path: Path) -> None:
    from orchestrator.db_pg import PostgresBackend
    from orchestrator.recall.ledger import LEDGER_SCHEMA, MIGRATIONS

    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (id INT)")
    be = PostgresBackend(db_url, "mig_be")
    try:
        assert be.migrate_dir(tmp_path) == 1
        assert [r.script_name for r in be.applied()] == ["001_a.sql"]
        with pytest.raises(MigrationChanged, match="mig_be"):
            be.migrate(MIGRATIONS)  # the recall ledger's version 1 is not this directory's
    finally:
        be.close()
    led = PostgresBackend(db_url, LEDGER_SCHEMA)  # NEW-ARCH-2 (D-524): schema wf is gone; the ledger's stands in
    try:
        led.migrate(MIGRATIONS)
        assert [r.sha256 for r in led.applied()] == [script_sha256(s) for s in MIGRATIONS]
    finally:
        led.close()


def test_extensions_reports_what_is_installed(db_url: str) -> None:
    with Database.connect(db_url, "mig_ext") as db:
        got = extensions(db)
        assert set(got) == {"vector", "pgroonga"}  # None on a cluster without them (tools/pglocal.py)
        assert extensions(db, ("plpgsql",)) == {"plpgsql": db.fetchval("SELECT extversion FROM pg_extension "
                                                                       "WHERE extname = 'plpgsql'")}  # fmt: skip


def test_require_extensions_names_the_missing_ones(db_url: str) -> None:
    with Database.connect(db_url, "mig_req") as db:
        assert require_extensions(db, ("plpgsql",)) == {"plpgsql": extensions(db, ("plpgsql",))["plpgsql"]}
        if not all(extensions(db).values()):  # the local cluster: no pgvector, no PGroonga
            with pytest.raises(DatabaseError, match="lacks the extension"):
                require_extensions(db)


# ----------------------------------------------------------------------------------------------- the stores
def store_migrations() -> dict[str, list[str]]:
    """Every store's schema versions, as each passes them to ``migrate`` (store name: its schema)."""
    from adapter import licensed, pidmap
    from console import auth, feedback, saerecord, sitestore, teamstore
    from console import breakglass_store as breakglass  # the store stands apart from its page (T-716)
    from criteria_compiler.library import ddl as library
    from datacore import dataops, lifecycle, sponsor
    from datacore import store as datacore
    from edc import store as edc
    from edc_backend import store as edcdoor
    from mail_gateway import store as mail
    from omop import schema as omop
    from orchestrator import db as orch
    from orchestrator import studystore
    from orchestrator.recall import ledger
    from patient_profile import twin
    from sitesetup import store as sitesetup
    from tb_common import derived_store, flags, notmatched, optout, refdata
    from tracestore import store as trace
    from vec import store as vec

    return {
        "refdata": list(refdata.MIGRATIONS),
        "optout": list(optout.MIGRATIONS),
        "recall": list(ledger.MIGRATIONS),
        "study": list(studystore.MIGRATIONS),
        "orch": list(orch.MIGRATIONS),
        "sitesetup": [sitesetup.SCHEMA, sitesetup.SCHEMA_V2],
        "mail": list(mail.MIGRATIONS),
        "library": [library.DDL],
        "terminology": [licensed.SCHEMA],
        "pidmap": list(pidmap.MIGRATIONS),
        "omop": omop.migrations(),
        "trace": [trace.SCHEMA_V1],
        "datacore": [datacore.SCHEMA, lifecycle.SCHEMA, *lifecycle.SAE_MIGRATIONS, sponsor.SCHEMA],
        "auth": list(auth.MIGRATIONS),
        "site": list(sitestore.MIGRATIONS),
        "team": list(teamstore.MIGRATIONS),
        "feedback": list(feedback.MIGRATIONS),
        "breakglass": list(breakglass.MIGRATIONS),
        "edc": list(edc.MIGRATIONS),
        "sae": list(saerecord.MIGRATIONS),
        "app": list(flags.MIGRATIONS),
        "derived": list(derived_store.MIGRATIONS),
        "dataops": list(dataops.MIGRATIONS),
        "tuned": list(notmatched.MIGRATIONS),
        "vec": list(vec.MIGRATIONS),
        "profile": list(twin.MIGRATIONS),
        "edcdoor": list(edcdoor.MIGRATIONS),
    }


#: checksums of versions added after the D-204 baseline, per store (append here; never edit the baseline)
ADDED: dict[str, tuple[str, ...]] = {
    # D-317: refdata version 3, the record of withdrawn sources
    "refdata": ("9e976b5878b8d5a8d1a89e417b61450471874a0e1122e43764d755d11662af83",),
    # D-279: users.must_change, login_failures.source, sessions.via
    # T-209c (D-406): users.last_login, for the unused-account report
    # T-109b (D-447): users.pw_history, the account's earlier password hashes
    # D-719: who opened an account, factor resets, account requests and notices
    "auth": (
        "44f1f94e5797899b13e8b807b4b20ace62bd584cf226dd4e207cf500b466deb6",
        "d08533082518372c9c3972573a7370f745b1a7bb754798cb3c60408ecd9744a8",
        "bb7564dcd900b6be7567a5d5f0db38eff6ecef1d03f9127fcf353d55332dc1ce",
        "cc898ef7e93cba0f79116b2e2ce6602150cf6e54b1535dddaf5f7d6d2d7054ca",
        # STEPS-ROLE (D-877): users.extra_roles, sessions.acting_role (a test box only)
        "4775e64bb8830064e1a8b965c60bb4cd34bf2e5fae88e5ca7136d3d892606a77",
        # STEPS-ROLE-2 (D-1151): users.last_acting_role, the next sign-in's role
        "dfab16954d5d5931634cc8fa42810402cae9d271cfa6072ec0886f81e87b25eb",
    ),
    # D-301: migration 3, the one-million block and the vocabulary tables
    # T-106 (D-339): migration 4, the large clinical tables partitioned by year
    # T-106b (STD-032): migration 5, the other fifteen CDM v5.4 tables
    # T-202 (D-384): migration 6, the record's own before-image on tb_record_event
    # T-206a (D-441): migration 7, tb_withheld (the persons the opt-out worker keeps out)
    # SCR-01 (D-655): migration 8, a grouper row may be a code family (match 'family')
    # T-702 (D-753): migration 9, the row ids bigint
    "omop": (
        "0eec88a07c4476ca00fdfb2e8fc414fb2257a293e381d8115a668fa7df0dc6f9",
        "36aaec4b30675bd3f2fa9006cbb7e9869f5df899613d179dde3068d19156094c",
        "5e12313c13360ff7f760649cce2f8bd954e6cfbace79c3dc399b47ae842055c6",
        "139401a1b2873fdd27e3b299507dd52005abea7bc62666af95c9af45ec85fcf8",
        "8e3745a426403fc8446601c4221225fa3cee581f63569387c59de741041c4523",
        "3c1516feffb316a4b8ac253e770fc5a7671553427ba6c400c57acc7426a44366",
        "eaae339681eca35b2b01ccd356bc1e4dce55a664a2b06214f3c47274f53d0daf",
    ),
    # T-612: pidmap version 2, the site key's fingerprint
    # T-659b (D-370): pidmap version 3, the patient index as the append-only pid_alias table
    # T-723 (D-489): pidmap version 4, a night's chart numbers staged until the night is published (``pending``)
    "pidmap": (
        "b7cf6c229898b30f609be2151ff4422b2a0bc0cd068b0b5150e1d58c07c98ae3",
        "2d6727cad7056592bdcb1c9a2c0f28f419debbc79880f81e6f4346cd59646f08",
        "9d3348bbf4c423dbdbe7bb199eb50e107304bfabaf16b0b0b04eb59b5d48f8e3",
        "411b2c02652903b18652e7797ec3169f3e10e8e55f7fdf9e07bc394a6c079f25",  # D-595: site_key.chartno_rule
    ),
    # D-277: datacore version 4 (the study's SAE rule set); sae version 3 (one initial report per party, CR-011)
    # D-364 (T-621): datacore version 5 (schedule versions); site version 4 (the criteria version on each mark)
    "datacore": (
        "8250b52d4e13e66e149ffa956f83b3a8027f95d4094f1a32b999771e459f7aa5",
        "d9f888838f2280f9e49a6d3f9a9bf210ace25104632200683567a4389fa03884",
        # D-387 (T-623): datacore version 6 (the criterion not met and its version on a screen-failure step)
        "668c23320ea6fe609efb7a779800ad02501c28559dc45abac20610e63f6f7a5a",
        # D-407 (T-620): datacore version 7 (the contact-attempt rule and the answers to possible deviations)
        "4a4c7c69ae18a17beda387cb3524504041d44a99212609f07d25f897b8735e35",
        # D-435 (T-302d): datacore version 8 (the sponsor's layout: screening-log columns, the weekly sheet)
        "cd15f0cb005567fbcaa623030a4e5ea5dd4bc947add082f57bcbe23b1cb7547d",
    ),
    # D-442 (T-207): derived version 2, the derive batch of each snapshot
    "derived": ("375852250dfeb38566f9172945e0d268f2a9f6b3d34f139e0c452eac4a59c711",),
    # D-386 (T-622): site version 5 (the study's state log and identifiers)
    # D-395 (T-310b): site version 6 (the IRB-text record of the cross-department candidate view)
    "site": (
        "7f7cf970ce4268ca7fdc4fd725535442b586b8ea1e2b23fa631dddf9d3a7575d",
        "2ab6655ef5282d733ea7c4b2804d496be62b238fee5fbee5d7d4d9ccd78540ff",
        "cc5a0e95c1dc50da9a3d8c9fa782fa1f5d6138e370dd9e7bad0c484ac3904996",
        # D-779 (T-305c): site version 7 (the years a close keeps the study's files)
        "52624415f200e587c75788fec3851f6880a403abe34f504786ac76ea56c2bf93",
    ),
    "sae": ("78527251f39fb58cd728b207c0fc332740a2d06444492dbd617b4d1b0cb7b6d3",),
    # T-510 (D-331): the feedback store, new after the baseline
    "feedback": ("3981b6201cd514508bed945433f3415993494cb24e52809cca7f37fe3801e368",),
    # D-281: edc version 2, the signature's version and key id, and signature_void
    # T-115 (D-368): edc version 3, what each draft was built under and the stored re-entry result
    # T-302c (D-434): edc version 4, the copy-assist ticks
    # T-720 (D-461): edc version 5, sig_version defaults to 2 and must be 2
    "edc": (
        "660d794773184321ebd80015911a26e65973b24d93fa2415c39b6114a22f561b",
        "7307dbdcdff73f68593da4a33739e1803bcc90079eff738c175f3ad13bd26003",
        "c5d2472d93df214f26cf8e3bd80d6fc5230e058da95ff5551ea03dbf22d7016c",
        "7e110573b03265c6d4e76d209c98dd467f37b489a30a00f4501be39ee916634f",
        # NEW-EDC-4 (D-694): edc version 6, the source changed since a decision and the source it was kept under
        "01f49e5f642301298ffc286954e0aa41cf47ed5b849ecd78faffb61db125db36",
        # EDC-023 (D-859): edc version 7, the data-flow reference with the switch, and the direct-source list
        "237fcba81e000e604f3cc4bac1e217bd99ed1a73bc031522efb79fb04801fdac",
        # E-PROV-1 (D-1047, D-989): edc version 8, the model calls each draft came from
        "9d2f3dc99b16a609aeefd428212cadc11d3b1c75f7014354a9e12d83323d4697",
    ),
    # T-108c (D-401): mail version 3, the send keys as the outbox and the job type on each intake row
    "mail": ("dc540a482b5619e6226318becb615e79a639ab2be3c2d47154b43029886f8579",),
    # D-399 (T-302a): team version 2, the approved consent-form versions as history rows
    # T-303 (D-436): team version 3, the monitoring-visit records
    # 10C-4 (D-1227): team version 4, the Japan profile's committee record and each site's permission
    "team": (
        "ad5cea87a2f6b2b0210c392f8c698a0c72253a93cbbb6ec74915bf0cefbd076f",
        "e3f9d90d7bb93b34988eed53250d15178b95f8b39de74d715c67a7bae376574f",
        "2716c0a7720edcde712359eccd4d1ac5de63efe979d51bf14f5abb100a3025f3",
    ),
    # D-280: the break-glass grants, new after the baseline
    # T-309 (D-430): version 2, each use of a grant (the steward's review list)
    "breakglass": (
        "0347aae3f58f7558d041191f25bd2fc5bc654e6f5139c9ee28b1588e91544b83",
        "a109d4561de2163aa76c7efdb78674bc128bd1d8ce65f968aaabd6e63b9bdb99",
    ),
    # T-112a (D-427): the data-operations batches, new after the baseline
    # T-725 (D-491): dataops version 2, which generation each derived artefact is built from (``built``)
    # NEW-B-4 (D-525): dataops version 3, the finished generations that can still be read (``built_kept``)
    "dataops": (
        "01925afb0e82837617a880fa2d2b32f7efaa6d5e98945e7144f57510d76efbcf",
        "684ba94dca3b1a27f4dc387083319f161caf1f69b705fda4754fcf7f5b97c59a",
        "0e9ec5476d9f2cb25aae184f604ab37cd94831969bee62d503e590dc3c458465",
    ),
    # T-103 (D-438): orch version 2, the orchestrator's identifier caps as use rows (``id_limits``)
    # T-689 (D-456): orch version 3, a job's restart count (``jobs.attempts``) and its kept model answers
    # (``judge_answers``)
    # D-648: orch version 4, the record of every table the alliance store was given (``cohort_stored``),
    # of where a merge read (``cohort_read``), and the tables found at the update (``cohort_tables_before``)
    # D-908 (D-519): orch version 5, the judged-pair store (``judged_pairs``)
    "orch": (
        "444cff97a092dda26501bfa81db70438eae3dda40e545bb86721748c241eba11",
        "8333ee74b006be58803a9a2b9d78ab736096234963c149ec1549165e70ccf5b4",
        "7dc9328a293c68018db4b8292e95bfb0e905cbf680987d7f3b90c6488020e610",
        "4f2b17e86f1c9432f09f2c7559696a3a312d5f965b6c15e2a367db9268f6487f",
        # D-1226: how an alliance table was verified (its key, its signed sequence and hash)
        "885e09aba43f78d4d69e16a0f210ccbc9e9442c25e8e60cc6ef704856c7c34c7",
    ),
    # T-310a (D-446): the weekly PI sample of criteria not matched and the site's check, new after the baseline
    "tuned": ("e8565a9e2288df90d120272ab2956fafe4595465ecd7c58c2e2debb35ee934a1",),
    # T-203a (D-439): the vector store, new after the baseline (needs pgvector: the db image)
    "vec": ("cd645d93e9d8d0a809c92eeaf6ff8997c201fb0e32b07a2d112288447f86b429",),
    # T-204 (D-440): the patient twin, new after the baseline
    "profile": ("e1107c0c7de613b72141fb70237b6eb35c1f98f5a1549f9c60f8537512a751b6",),
    # E-EDCB-2 (D-1044): the EDC door's state (OIDC codes, held writes, event ids), new after the baseline
    "edcdoor": ("d6190fca3834816cb6d64137dfd92f84faefb9103476d79b3ab84c0fb0f1bf73",),
}
#: stores whose DDL needs an extension of the box's db image (D-204); a cluster without it cannot migrate them, so
#: :func:`test_every_store_migrates_twice_and_checks_its_record` creates the extension where the server offers it and
#: leaves the store to ``tests/integration/test_vec_store.py`` only where it does not
NEEDS_EXTENSION = {"vec": "vector"}
#: stores of the baseline whose code is gone (T-659b: ``mpi``, the retired data platform's patient index)
RETIRED = {"mpi"}
PINNED: dict[str, tuple[str, ...]] = {
    k: BASELINE.get(k, ()) + ADDED.get(k, ()) for k in (BASELINE.keys() | ADDED.keys()) - RETIRED
}

#: every file that opens a store and migrates it, covered by :func:`store_migrations` (or not a store of its own)
STORE_FILES = {
    "libs/tb_common/derived_store.py", "libs/tb_common/flags.py", "libs/tb_common/notmatched.py", "libs/tb_common/optout.py", "libs/tb_common/refdata.py", "services/adapter/licensed.py",
    "services/adapter/pidmap.py", "services/console/auth.py", "services/console/breakglass_store.py", "services/console/feedback.py", "services/console/saerecord.py",
    "services/console/sitestore.py", "services/console/teamstore.py", "services/criteria_compiler/library/repository.py",
    "services/datacore/dataops.py", "services/datacore/store.py", "services/edc/store.py", "services/edc_backend/store.py",
    "services/mail_gateway/store.py", "services/omop/schema.py", "services/orchestrator/db.py",
    "services/orchestrator/recall/ledger.py",
    "services/orchestrator/studystore.py", "services/patient_profile/twin.py", "services/sitesetup/store.py",
    "services/tracestore/store.py", "services/vec/store.py",
}  # fmt: skip
#: files that migrate but are not a store: the machinery, the update path's bundle-driven ``release``, the drill's
#: throwaway database
NOT_STORES = {
    "libs/tb_common/db.py",
    "services/console/storedb.py",
    "services/orchestrator/db_pg.py",  # NEW-ARCH-2 (D-524): the backend only; its schema ``wf`` is removed
    "tools/trialbox/update.py",
    "tools/backup_drill.py",
}


def test_every_store_that_migrates_is_pinned() -> None:
    """A new store (a new file calling ``migrate`` or ``open_db``) must be added to store_migrations and the pin."""
    root = Path(__file__).resolve().parents[2]
    calls = re.compile(r"\.migrate\(|\.migrate_dir\(|\bopen_db\(")
    found = {
        str(f.relative_to(root))
        for top in ("libs", "services", "tools")
        for f in (root / top).rglob("*.py")
        if calls.search(f.read_text(encoding="utf-8"))
    }
    assert found - NOT_STORES == STORE_FILES, (
        "files that migrate a store changed: list a new store in store_migrations, PINNED (ADDED) and STORE_FILES"
    )


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
    migrated: list[str] = []
    for store, scripts in store_migrations().items():
        with Database.connect(db_url, f"pin_{store}") as db:
            ext = NEEDS_EXTENSION.get(store)
            if ext and not extensions(db, (ext,))[ext]:
                if not db.fetchval("SELECT count(*) FROM pg_available_extensions WHERE name = ?", (ext,)):
                    continue  # the server has no pgvector: tests/integration/test_vec_store.py migrates it on the image
                db.execute(f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA public")  # offered: never skip then
            db.migrate(scripts)
            db.migrate(scripts)
            assert [r.sha256 for r in db.applied()] == [script_sha256(s) for s in scripts], store
            migrated.append(store)
    with Database.connect(db_url, "pin_probe") as db:
        offered = {str(r[0]) for r in db.fetchall("SELECT name FROM pg_available_extensions")}
    # a store is left out only where its extension is not on the server at all
    assert set(store_migrations()) - set(migrated) == {s for s, e in NEEDS_EXTENSION.items() if e not in offered}
