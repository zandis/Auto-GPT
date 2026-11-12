"""Trigger functions and triggers a store makes when it opens (EDC-009, D-582).

A plpgsql body holds ``;``, so it cannot go through ``Database.migrate``; each store makes its functions and triggers
after its migration. ``CREATE OR REPLACE FUNCTION`` on every open needs the function's owner. After a restore
(``pg_restore --no-owner``) the functions belong to the restoring role, not to the service's group, and the store did
not open again: so a function is made only when it is absent or its body differs, and a trigger only when it is
absent; a trigger someone disabled is switched on again.
"""

from __future__ import annotations

import re
from typing import Any

_DDL = re.compile(r"CREATE OR REPLACE FUNCTION (\w+)\(\).*?\$\$(.*)\$\$", re.DOTALL)
_HAVE = (
    "SELECT t.tgname, c.relname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() AND NOT t.tgisinternal"
)
_BODY = (
    "SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = current_schema() AND p.proname = ?"
)


def ensure(tx: Any, lock: str, functions: tuple[str, ...], triggers: dict[str, str]) -> None:
    """Make ``functions`` (``CREATE OR REPLACE FUNCTION name() ... $$ body $$``) and ``triggers`` (name -> DDL) in
    the current schema, one maker at a time (``lock`` names the advisory lock). Idempotent."""
    tx.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema() || ?))", (f".{lock}",))
    for ddl in functions:
        m = _DDL.match(ddl)
        if m is None:
            raise ValueError("pgfunc.ensure: not a CREATE OR REPLACE FUNCTION name() ... $$ body $$ statement")
        rows = tx.fetchall(_BODY, (m.group(1),))
        if not rows or str(rows[0][0]) != m.group(2):
            tx.execute(ddl)
    have = {str(r[0]): (str(r[1]), str(r[2])) for r in tx.fetchall(_HAVE)}
    for name, ddl in triggers.items():
        if name not in have:
            tx.execute(ddl)
        elif have[name][1] == "D":
            tx.execute(f'ALTER TABLE "{have[name][0]}" ENABLE TRIGGER "{name}"')
