"""The orchestrator's start-time stores (D-921; the runner: ``tb_common.start_migrations``). Its lifespan opens the
job store; the rest it opens on a route, a job or a timer."""

from __future__ import annotations

from tb_common.start_migrations import Store, closed, main


def _orch() -> str:
    from orchestrator.db import JobDB

    return closed(JobDB())


STORES: tuple[Store, ...] = (("orch", _orch),)

if __name__ == "__main__":
    raise SystemExit(main("orchestrator", STORES))
