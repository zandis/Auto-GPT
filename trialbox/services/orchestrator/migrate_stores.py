"""T-695's rest (D-921): a service's start-time migrations as a step of the update of their own.

Every TrialBox service migrates the stores it opens (``tb_common.db.Database.migrate``); the stores below are opened
before the service answers ``/healthz`` (an app factory or a lifespan start), so a migration that takes longer than
the service's health wait (the start period and retries of ``deploy/docker-compose.yml``) failed ``up --wait`` and the
update was rolled back (F-10 of ``docs/reviews/2026-11-11-scale-timeouts.md``). ``trialbox db-up`` (and so the update
and ``install.sh``) now runs ``python -m orchestrator.migrate_stores`` in a one-off container of each service listed
here, before the services start: the service's own image, settings and database role, under a limit sized from the
database (``ComposeBox.migrate_limit_s``). At its start the service then finds its versions applied.

The stores a service opens later (on a request, a job or a timer) still migrate there: not this step's.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

from tb_common.db import DatabaseError


def _closed(store: Any) -> str:
    close = getattr(store, "close", None)
    if close is not None:
        close()
    return "migrated"


def _orch() -> str:
    from orchestrator.db import JobDB

    return _closed(JobDB())


def _mail() -> str:
    from mail_gateway.store import MailDB

    return _closed(MailDB())


def _trace() -> str:
    # as the gateway's start (gateway.app.from_env): the store only when the trace store is on
    if (os.environ.get("TB_TRACESTORE") or "").strip().lower() != "on":
        return "the trace store is off"
    from tracestore.store import TraceStore

    return _closed(TraceStore(os.environ.get("TB_DB_URL")))


def _console(module: str, cls: str) -> Callable[[], str]:
    def open_() -> str:
        import importlib

        return _closed(getattr(importlib.import_module(module), cls)())

    return open_


def _flags() -> str:
    from tb_common.db import Database
    from tb_common.flags import SCHEMA, Flags

    db = Database.connect(os.environ.get("TB_DB_URL"), SCHEMA)
    try:
        Flags(db).install(db)
    finally:
        db.close()
    return "migrated"


def _vocab() -> str:
    # as the compiler's start: the vocabulary store only when the compiler resolves through it
    from criteria_compiler.terminology import resolver

    if resolver.source() != "vocab":
        return "the compiler reads its terminology files"
    return _closed(resolver._vocab_db())


#: service (``TB_SERVICE_NAME``) -> its start-time stores: (schema, open it and close it). The services with a database
#: role and a store opened at start; a service not here opens none at start. Kept equal to the update's list
#: (``tools.trialbox.update.STORE_SERVICES``) by tests/unit/test_t695_service_migrations.py.
AT_START: dict[str, tuple[tuple[str, Callable[[], str]], ...]] = {
    "orchestrator": (("orch", _orch),),
    "mail-gateway": (("mail", _mail),),
    "gateway": (("trace", _trace),),
    "criteria-compiler": (("omop", _vocab),),
    "console": (
        ("auth", _console("console.auth", "UserStore")),
        ("site", _console("console.sitestore", "SiteStore")),
        ("team", _console("console.teamstore", "TeamStore")),
        ("optout", _console("tb_common.optout", "OptOutRegister")),
        ("app", _flags),
        ("feedback", _console("console.feedback", "FeedbackStore")),
        ("sae", _console("console.saerecord", "SaeStore")),
        ("breakglass", _console("console.breakglass_store", "BreakGlassStore")),
        ("tuned", _console("tb_common.notmatched", "NotMatchedStore")),
    ),
}


def run(service: str, say: Callable[[str], None] = print) -> int:
    stores = AT_START.get(service, ())
    if not stores:
        say(f"{service or 'this service'}: no store opened at start")
    for schema, open_ in stores:
        say(f"{service}: {schema}: {open_()}")
    return 0


def main() -> int:
    service = os.environ.get("TB_SERVICE_NAME", "")
    try:
        return run(service)
    except DatabaseError as exc:
        print(f"migrate-stores: {service}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
