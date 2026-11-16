"""The gateway's start-time store (D-921; the runner: ``tb_common.start_migrations``): ``create_app`` opens the trace
store when it is on (``gateway.app.from_env``)."""

from __future__ import annotations

import os

from tb_common.start_migrations import Store, closed, main


def _trace() -> str:
    if (os.environ.get("TB_TRACESTORE") or "").strip().lower() != "on":
        return "the trace store is off"
    from tracestore.store import TraceStore

    return closed(TraceStore(os.environ.get("TB_DB_URL")))


STORES: tuple[Store, ...] = (("trace", _trace),)

if __name__ == "__main__":
    raise SystemExit(main("gateway", STORES))
