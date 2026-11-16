"""T-695's rest (D-921): the runner of a service's start-time migrations, as a step of the update of their own.

Every TrialBox service migrates the stores it opens (``tb_common.db.Database.migrate``). The stores it opens before
it answers ``/healthz`` (an app factory or a lifespan start) are listed in the service's own ``migrate_stores``
module, which names only stores on its own database role's list (D-378). ``trialbox db-up``, and so the update and
``install.sh``, runs ``python -m <service>.migrate_stores`` in a one-off container of the service before the services
start. The container has the service's image, settings and role, and a limit sized from the database. At its start
the service then finds its versions applied, so a long migration never meets the health wait (F-10 of
``docs/reviews/2026-11-11-scale-timeouts.md``). A store a service opens later (on a request, a job or a timer) still
migrates there: that is not this step's.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Any

from tb_common.db import DatabaseError

#: (schema, open it, migrate it and close it; returns what was done)
Store = tuple[str, Callable[[], str]]


def closed(store: Any) -> str:
    close = getattr(store, "close", None)
    if close is not None:
        close()
    return "migrated"


def run(service: str, stores: Sequence[Store], say: Callable[[str], None] = print) -> int:
    for schema, open_ in stores:
        say(f"{service}: {schema}: {open_()}")
    return 0


def main(service: str, stores: Sequence[Store]) -> int:
    try:
        return run(service, stores)
    except DatabaseError as exc:
        print(f"migrate-stores: {service}: {exc}", file=sys.stderr)
        return 1
