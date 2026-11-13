"""OMOP-STORE (D-721): the admin's step that makes a second lake's OMOP store.

The box's lake (``TB_LAKE_DIR``) writes the ``omop`` schema, which the role script makes for its group
(``tbs_omop``). A lake in another folder has a store of its own, ``omop_<10 hex of the folder>``
(``omop.schema.schema_for``). Under the role script a service does not make that store: it would own it, and no
other service could open it (``omop.schema.connect`` refuses). This step makes it, as the host tools' admin, for
the OMOP group: every service with ``omop`` on its list then works in it as the group, and no other service does.

    python3 -m tools.trialbox omop-store --lake /srv/practice-b/lake

On a database without the role script (a test, a tool run) there is no group: the store is made as whoever asks,
as before.
"""

from __future__ import annotations

from pathlib import Path


def make(url: str | None, lake_dir: Path) -> str:
    """Make the OMOP store of ``lake_dir`` (schema, tables, vocabulary seed); its name. A second run changes
    nothing."""
    import psycopg
    from omop import schema
    from tb_common.db import GROUP_PREFIX, split_url

    url = url or schema.db_url()
    if not url:
        raise RuntimeError("no trial database (TB_DB_URL)")
    dsn, prefix = split_url(url)
    name = schema.schema_for(lake_dir)
    full = prefix + name
    group = (GROUP_PREFIX + prefix + schema.SCHEMA)[:63]
    with psycopg.connect(dsn, autocommit=True) as con:
        has_group = con.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (group,)).fetchone() is not None
        there = con.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (full,)).fetchone() is not None
        if has_group and not there:
            # the group owns the schema from its first moment: what the migration below makes is the group's
            con.execute(f'CREATE SCHEMA "{full}" AUTHORIZATION "{group}"')
    schema.connect(url, name, lake_dir=lake_dir, admin=True).close()
    return name


def main_action(lake: Path) -> int:
    import sys

    try:
        name = make(None, lake)
    except Exception as exc:
        print(f"omop-store: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1
    print(f"omop-store: the OMOP store of {lake} is {name}")
    return 0
