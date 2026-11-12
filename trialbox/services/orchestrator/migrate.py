"""The install step for the schemas no service owns (T-718, D-486): ``python -m orchestrator.migrate``.

A schema on the ``owned`` list of ``deploy/docker/db-init/30-service-roles.sh`` belongs to ``tbo_<schema>``, and the
service that writes it cannot create, alter or drop anything in it. So its tables, its version rows and its
append-only triggers are made here, by the box's admin (``TB_DB_URL`` as ``trialbox``, a member of every owner role),
before the services start: ``deploy/install.sh`` and ``trialbox update`` run this in a one-off orchestrator container,
and ``trialbox migrate`` runs it by hand. The services then only check (``tb_common.db.Database.migrate``) and refuse
a schema that is behind.

On a box without the roles (DEV, TEST, a test cluster) this does what the service's start would do.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from edc import store as edc_store
from tb_common.db import ENV, DatabaseError

#: schema -> its install function (``url`` -> the version it is at). Kept equal to the role script's ``owned`` list
#: by tests/unit/test_db_roles.py.
OWNED: dict[str, Callable[[str | None], int]] = {"edc": edc_store.install}


def run(url: str | None, say: Callable[[str], None] = print) -> int:
    for schema, install in OWNED.items():
        say(f"{schema}: version {install(url)}")
    return 0


def main() -> int:
    try:
        return run(os.environ.get(ENV))
    except (DatabaseError, edc_store.EdcError) as exc:
        print(f"migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
