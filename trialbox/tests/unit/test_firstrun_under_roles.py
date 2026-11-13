"""NEW-FR-1 (D-710): the first-run page asks the pid map over a connection that may ask.

On a box, the role script (``deploy/docker/db-init/30-service-roles.sh``) gives each store a group role and a
connection of a store takes that role (``SET ROLE``). ``console.firstrun.box_holds_patients`` asked about the pid
map over the console's ``auth`` connection, whose role may not use the ``pidmap`` schema: the question raised, was
caught, and the answer was "cannot tell", which the page read as "holds patients". So on every box with roles the
chart-number rule could never be chosen on the first-run page, and the page did not say why.

The real script on a cluster of its own, the console's own login role. Synthetic data only."""

from __future__ import annotations

import pytest
from tb_common.db import Database

from tests.unit.test_db_roles import _as, roles_cluster  # noqa: F401 - the fixture is used by name

CONSOLE = "tb_console"


@pytest.fixture
def as_console(roles_cluster: tuple, monkeypatch: pytest.MonkeyPatch) -> str:  # noqa: F811
    url = roles_cluster[1]
    monkeypatch.setenv("TB_DB_URL", _as(url, CONSOLE))
    return url


def test_the_auth_connection_may_not_ask_about_the_pid_map(as_console: str) -> None:
    """Why the old question failed: the store's role, not the login's, is the one that asks."""
    import os

    import psycopg

    with Database.connect(os.environ["TB_DB_URL"], "auth") as db:
        assert db.fetchval("SELECT current_user") == "tbs_auth"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.fetchone("SELECT to_regclass(?)", ('"pidmap".pid_map',))


def test_a_box_with_roles_and_no_patient_says_so_and_one_with_a_patient_says_that(as_console: str) -> None:
    from console import firstrun

    # the map's schema is there (the box's admin made it), with no map in it yet: nothing was ever loaded
    assert firstrun.box_holds_patients() is False
    with Database.connect(as_console, "pidmap") as db:  # the box's admin, as a migration and a first night would
        db.execute("CREATE TABLE pid_map (pid TEXT PRIMARY KEY)")
        db.execute("ALTER TABLE pid_map OWNER TO tbs_pidmap")
    assert firstrun.box_holds_patients() is False  # made, and empty
    with Database.connect(as_console, "pidmap") as db:
        db.execute("INSERT INTO pid_map VALUES ('p-synthetic')")
    assert firstrun.box_holds_patients() is True
    with Database.connect(as_console, "pidmap") as db:
        db.execute("DROP TABLE pid_map")
