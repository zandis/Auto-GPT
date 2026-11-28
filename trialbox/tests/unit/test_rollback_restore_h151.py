"""H-151: the update's rollback put the rollback point back with ``pg_restore --clean`` over the database in place.
On a box whose lake tables are partitioned (omop's migration 4: ``<table>_ydefault`` and one partition per year,
the key added on the parent), ``--clean`` drops the key of a partition child, which PostgreSQL refuses ("cannot drop
inherited constraint"), so the restore exited 3 and the rollback failed with the box between two releases.

The restore now loads the dump into a database made fresh beside the one in place (no ``--clean``: nothing is ever
dropped from a database that holds data), and swaps the two names in one transaction only when the whole load
succeeded; the database that was in place is dropped after the swap. Each test runs ``update.RESTORE_SH`` itself,
under dash, against the session's local test cluster (``tools/pglocal.py``), as the db container runs it: the
restoring role is the database's owner and not a superuser (``trialbox``), a member of the group that owns the lake
schema; the cluster's superuser makes and swaps the databases (``POSTGRES_USER``, as in the db container)."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools import pglocal
from tools.trialbox import update as up

ADMIN = "postgres"  # the local cluster's superuser (pglocal's initdb -U postgres), as POSTGRES_USER in the db container

# omop's migration 4 (services/omop/ddl/partitions.sql) for one table, then rows in the default partition and in a
# year's partition, a table of the owner's own in public with an index, a foreign key and a grant
LAKE_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
CREATE SCHEMA lake AUTHORIZATION {group};
SET ROLE {group};
CREATE TABLE lake.visit_occurrence (visit_occurrence_id bigint NOT NULL, visit_start_date date NOT NULL,
                                    note text) PARTITION BY RANGE (visit_start_date);
CREATE TABLE lake.visit_occurrence_ydefault PARTITION OF lake.visit_occurrence DEFAULT;
CREATE TABLE lake.visit_occurrence_y2025 PARTITION OF lake.visit_occurrence
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
ALTER TABLE lake.visit_occurrence ADD CONSTRAINT xpk_visit_occurrence PRIMARY KEY (visit_occurrence_id,
                                                                                   visit_start_date);
CREATE INDEX idx_visit_note ON lake.visit_occurrence (note);
INSERT INTO lake.visit_occurrence VALUES (1, '2025-03-01', 'synthetic a'), (2, '2019-06-01', 'synthetic b');
GRANT USAGE ON SCHEMA lake TO {owner};
GRANT SELECT ON ALL TABLES IN SCHEMA lake TO {owner};
RESET ROLE;
SET ROLE {owner};
CREATE TABLE public.steps (id int PRIMARY KEY, label text NOT NULL);
CREATE TABLE public.step_notes (id int PRIMARY KEY, step int NOT NULL REFERENCES public.steps (id), body text);
CREATE INDEX idx_steps_label ON public.steps USING gin (label gin_trgm_ops);
INSERT INTO public.steps VALUES (1, 'synthetic step');
INSERT INTO public.step_notes VALUES (10, 1, 'synthetic note');
GRANT SELECT ON public.steps TO {group};
"""

# what the failed release did after the dump: a row in each kind of table, a partition of its own, a table of its own
AFTER_SQL = """
INSERT INTO lake.visit_occurrence VALUES (3, '2020-01-01', 'after the dump');
CREATE TABLE lake.visit_occurrence_y2026 PARTITION OF lake.visit_occurrence
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
INSERT INTO public.steps VALUES (2, 'after the dump');
CREATE TABLE public.added_by_the_release (n int);
"""

STATE_SQL = {
    "rows": "SELECT visit_occurrence_id || ' ' || visit_start_date || ' ' || note FROM lake.visit_occurrence "
    "UNION ALL SELECT id || ' ' || label FROM public.steps UNION ALL SELECT id || ' ' || step FROM public.step_notes "
    "ORDER BY 1",
    "where": "SELECT tableoid::regclass || ' ' || visit_occurrence_id FROM lake.visit_occurrence ORDER BY 1",
    "constraints": "SELECT conrelid::regclass || ' ' || conname || ' ' || contype::text || ' ' || (conparentid <> 0) "
    "|| ' ' || pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace IN "
    "('lake'::regnamespace, 'public'::regnamespace) ORDER BY 1",
    "partitions": "SELECT inhparent::regclass || ' ' || inhrelid::regclass || ' ' || "
    "pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits JOIN pg_class c ON c.oid = inhrelid ORDER BY 1",
    "indexes": "SELECT indexrelid::regclass || ' ' || indrelid::regclass FROM pg_index i JOIN pg_class c "
    "ON c.oid = i.indrelid WHERE c.relnamespace IN ('lake'::regnamespace, 'public'::regnamespace) ORDER BY 1",
    "tables": "SELECT table_schema || '.' || table_name FROM information_schema.tables WHERE table_schema IN "
    "('lake', 'public') ORDER BY 1",
    "extensions": "SELECT extname FROM pg_extension ORDER BY 1",
    # the grants to every other role, an owner's own left out (the dump is taken --no-owner, as the update takes it: what it holds is made by the
    # restoring role, which then holds every privilege of an owner; the role script, run at the restart, gives each
    # schema and table back to its group, as after the restore before H-151)
    "grants": "SELECT table_name || ' ' || grantee || ' ' || privilege_type FROM information_schema.role_table_grants "
    "WHERE table_schema IN ('lake', 'public') AND grantee <> '{owner}' AND grantor <> grantee ORDER BY 1",
}
# the database itself, read on the maintenance database: its owner, encoding, collation and grants
DB_SQL = (
    "SELECT pg_get_userbyid(datdba) || ' ' || pg_encoding_to_char(encoding) || ' ' || datcollate || ' ' || datctype "
    "|| ' ' || datconnlimit || ' ' || coalesce(datacl::text, '-') FROM pg_database WHERE datname = '{db}'"
)


@dataclass
class Box:
    """One test's own roles and database on the session's cluster, and the environment the restore runs in."""

    db: str
    owner: str
    group: str
    env: dict[str, str]
    work: Path

    def psql(self, sql: str, db: str | None = None, user: str = ADMIN) -> str:
        r = subprocess.run([shutil.which("psql") or "psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-U", user,
                            "-d", db or self.db, "-c", sql], env=self.env, capture_output=True, text=True,
                           check=False)  # fmt: skip
        assert r.returncode == 0, r.stderr[-600:]
        return r.stdout.strip()

    def state(self) -> dict[str, str]:
        out = {k: self.psql(q.replace("{owner}", self.owner)) for k, q in STATE_SQL.items()}
        out["database"] = self.psql(DB_SQL.format(db=self.db), db="postgres")
        return out

    def databases(self) -> list[str]:
        return self.psql(f"SELECT datname FROM pg_database WHERE datname LIKE '{self.db}%' ORDER BY 1",
                         db="postgres").split()  # fmt: skip

    def dump(self, out: Path) -> None:
        subprocess.run([shutil.which("pg_dump") or "pg_dump", "-Fc", "--no-owner", "-U", self.owner, "-d", self.db,
                        "-f", str(out)], env=self.env, check=True)  # fmt: skip

    def restore(self, dump: Path) -> subprocess.CompletedProcess[bytes]:
        shell = shutil.which("dash") or "/bin/sh"
        with dump.open("rb") as stdin:
            return subprocess.run([shell, "-c", up.RESTORE_SH, "tb-restore", self.owner, self.db, up.RESET_SQL],
                                  stdin=stdin, env=self.env, capture_output=True, check=False)  # fmt: skip


@pytest.fixture
def box(pg_cluster_url: str, tmp_path: Path) -> Iterator[Box]:
    from psycopg.conninfo import conninfo_to_dict
    from tb_common.db import split_url

    host = str(conninfo_to_dict(split_url(pg_cluster_url)[0])["host"])
    work = tmp_path / "pgdata"  # PGDATA: the restore's script folder is under it, as on the db volume
    work.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST=host, PGDATA=str(work), POSTGRES_USER=ADMIN,
               PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}")  # fmt: skip
    tag = f"{os.getpid()}_{tmp_path.name[-6:]}".replace("-", "_").lower()
    b = Box(db=f"h151_{tag}", owner=f"h151o_{tag}", group=f"h151g_{tag}", env=env, work=work)
    b.psql(f"CREATE ROLE {b.owner} LOGIN; CREATE ROLE {b.group} NOLOGIN; GRANT {b.group} TO {b.owner}", db="postgres")
    b.psql(f"CREATE DATABASE {b.db} OWNER {b.owner}", db="postgres")
    b.psql(f"REVOKE ALL ON DATABASE {b.db} FROM PUBLIC; GRANT CONNECT ON DATABASE {b.db} TO {b.group}", db="postgres")
    b.psql(LAKE_SQL.format(owner=b.owner, group=b.group))
    try:
        yield b
    finally:
        for name in b.databases():
            b.psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', db="postgres")
        b.psql(f"DROP ROLE IF EXISTS {b.owner}; DROP ROLE IF EXISTS {b.group}", db="postgres")


def test_the_rollback_restores_a_lake_with_partitions_rows_and_constraints_equal(box: Box, tmp_path: Path) -> None:
    """The bench's failure (exit 3, "cannot drop inherited constraint ... _ydefault_pkey"): the restore of a dump
    with a partitioned lake table brings back every row in its partition, every constraint, index, partition, grant
    and extension, and the database's own owner, encoding and grants; what the failed release made is gone and no
    second database is left."""
    dump = tmp_path / "wf.dump"
    at_dump = box.state()
    box.dump(dump)
    box.psql(AFTER_SQL, user=box.owner)
    assert box.state() != at_dump  # the failed release changed rows, partitions and tables
    res = box.restore(dump)
    assert res.returncode == 0, res.stderr.decode(errors="replace")[-800:]
    assert box.state() == at_dump
    assert f"steps {box.group} SELECT" in at_dump["grants"]  # a grant the dump holds, back
    assert "visit_occurrence_ydefault_pkey" in at_dump["constraints"]  # the partition child's key of the bench
    assert box.databases() == [box.db]  # neither the fresh database's name nor the replaced one is left
    assert not (box.work / "tb-rollback").exists()  # the plaintext script and its folder are gone


def test_a_restore_that_fails_leaves_the_database_in_place_as_it_was(box: Box, tmp_path: Path) -> None:
    """Never worse: a dump cut in half (pg_restore fails) and a dump whose load fails half way (a role it grants to
    is gone) both leave the database in place exactly as it was, with no second database beside it; a restore of the
    whole dump afterwards still succeeds (the marker stays meanwhile, so the rollback can be run again)."""
    dump = tmp_path / "wf.dump"
    at_dump = box.state()
    box.dump(dump)
    box.psql(AFTER_SQL, user=box.owner)
    before = box.state()
    cut = tmp_path / "cut.dump"
    cut.write_bytes(dump.read_bytes()[: dump.stat().st_size // 2])
    bad = box.restore(cut)
    assert bad.returncode != 0 and box.state() == before and box.databases() == [box.db]
    gone = f"{box.group}_gone"
    box.psql(f"CREATE ROLE {gone} NOLOGIN; GRANT SELECT ON public.steps TO {gone}", user=ADMIN)
    granted = tmp_path / "granted.dump"
    box.dump(granted)
    box.psql(f"REVOKE SELECT ON public.steps FROM {gone}; DROP ROLE {gone}", user=ADMIN)
    before = box.state()
    half = box.restore(granted)
    assert half.returncode != 0 and b"does not exist" in half.stderr
    assert box.state() == before and box.databases() == [box.db]
    assert not (box.work / "tb-rollback").exists()
    good = box.restore(dump)
    assert good.returncode == 0, good.stderr.decode(errors="replace")[-800:]
    assert box.state() == at_dump and box.databases() == [box.db]


def test_a_signal_while_the_dump_loads_leaves_the_database_in_place_and_no_second_one(box: Box, tmp_path: Path) -> None:
    """A SIGTERM (or SIGHUP, a closed session) while the dump loads into the fresh database: the restore ends
    non-zero, the fresh database is dropped on the way out, and the database in place is untouched."""
    dump = tmp_path / "wf.dump"
    box.dump(dump)
    box.psql(AFTER_SQL, user=box.owner)
    before = box.state()
    shim = tmp_path / "bin"
    shim.mkdir()
    real = shutil.which("psql", path=box.env["PATH"])
    held = tmp_path / "held"
    # the load (the one psql of the restoring role) says it started, then waits to be signalled; every other psql
    # call is the real one
    (shim / "psql").write_text(
        "#!/bin/sh\n"
        f'case " $* " in *" -U {box.owner} "*) : > "{held}"; while :; do sleep 1; done ;; esac\n'
        f'exec "{real}" "$@"\n'
    )
    (shim / "psql").chmod(0o755)
    env = {**box.env, "PATH": f"{shim}:{box.env['PATH']}"}
    shell = shutil.which("dash") or "/bin/sh"
    for sig in (signal.SIGTERM, signal.SIGHUP):
        held.unlink(missing_ok=True)
        with dump.open("rb") as stdin:
            proc = subprocess.Popen([shell, "-c", up.RESTORE_SH, "tb-restore", box.owner, box.db, up.RESET_SQL],
                                    stdin=stdin, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    start_new_session=True)  # fmt: skip
            for _ in range(600):  # the fresh database is made before the load starts
                if held.exists() or proc.poll() is not None:
                    break
                time.sleep(0.05)
            assert held.exists(), proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            assert box.databases() == [box.db, f"{box.db}_tbrb"]
            os.killpg(proc.pid, sig)  # as a closed session or `docker exec` passes it on: the whole group
            _out, err = proc.communicate(timeout=120)
        assert proc.returncode != 0, err.decode(errors="replace")
        assert box.state() == before and box.databases() == [box.db]
        assert not (box.work / "tb-rollback").exists()


def test_the_update_counts_the_fresh_database_on_the_db_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fresh database sits beside the one in place until the swap: the preflight counts the largest database a
    second time on the db volume (Docker's volumes), beside the rollback script and the archive the restore reads
    there (review 1535-1), so the three are summed there."""
    sizes = {"trialbox_wf": 7_000, "hapi": 3_000}

    def run(argv: list[str], **_kw: object) -> str:
        if "SELECT pg_database_size(current_database())" in argv:
            return str(sizes[argv[argv.index("-d") + 1]])
        if argv[-2:] == ["-f", "{{.DockerRootDir}}"]:
            return str(tmp_path / "engine")
        return ""

    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    monkeypatch.setenv("TB_COMPOSE", "dc")
    monkeypatch.setenv("TB_MODELS_DIR", str(tmp_path / "models"))
    box = up.ComposeBox(deploy, run=run)
    plan = up.Plan("B1", "f" * 64, "v", [], tmp_path / "stage")
    volumes = {what: n for p, n, what in box.space_needs(plan, deploy / "updates") if p == tmp_path / "engine/volumes"}
    assert volumes == {"rollback script (largest database) on the db volume": 7_000,
                       "fresh database during a rollback (largest database) on the db volume": 7_000,
                       "rollback archive (largest database) on the db volume": 7_000}  # fmt: skip


# review 1535-1 and 1535-2: stored text whose row in the dump's COPY data begins like the statements the restore once
# picked out of, or left out of, the plain script with grep: a value is data, never run and never dropped
PREFIX_ROWS = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE TABLE public.h151_ran_as_superuser (x int); --",
    "COMMENT ON EXTENSION pg_trgm IS 'a stored note, not a comment';",
)


def test_stored_text_that_begins_like_sql_is_data_never_run_and_never_dropped(box: Box, tmp_path: Path) -> None:
    """A note whose text begins with ``CREATE EXTENSION ...; <SQL>; --`` or ``COMMENT ON EXTENSION`` sits at the start
    of its row in the dump's COPY data. The restore takes the extensions from the archive's own list
    (``pg_restore -l`` and ``-L``), never from lines of the script: the statement in the note never runs (as the
    superuser or at all), and no row is left out, so the swap never puts a short database in place."""
    rows = "".join(f"({i}, $tbq${t}$tbq$), " for i, t in enumerate(PREFIX_ROWS, 1)).rstrip(", ")
    box.psql(f"CREATE TABLE public.notes (body text, id int); INSERT INTO public.notes (id, body) VALUES {rows}",
             user=box.owner)  # fmt: skip
    notes = "SELECT id || ' ' || body FROM public.notes ORDER BY id"
    at_dump = {**box.state(), "notes": box.psql(notes)}
    dump = tmp_path / "wf.dump"
    box.dump(dump)
    box.psql(AFTER_SQL, user=box.owner)
    res = box.restore(dump)
    assert res.returncode == 0, res.stderr.decode(errors="replace")[-800:]
    assert {**box.state(), "notes": box.psql(notes)} == at_dump  # every note, whole
    assert box.psql("SELECT count(*) FROM pg_class WHERE relname = 'h151_ran_as_superuser'") == "0"
