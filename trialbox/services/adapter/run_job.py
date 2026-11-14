"""One ingest as a process of its own (PERF-025, D-663).

    python -m adapter.run_job <lock fd> <spec as JSON>

Started by the adapter service for one run (``adapter.app``): it inherits the open file that holds the run lock,
builds its configuration from the environment as the service does, runs the night and writes the run's end to
``<lake>/adapter-runs/<run id>.json``. The service's process goes on answering; when this process is killed (the
kernel under the container's memory cap, a restart) the lock goes with it and the run reads ``failed: ended without
an answer``. Nothing of the feed is in the arguments: the request's own fields and the run's id.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapter import runs

log = logging.getLogger("adapter")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    spec: dict[str, Any] = json.loads(args[1])
    state: dict[str, Any] = spec["state"]
    lake_dir = Path(spec["lake_dir"])
    lock = runs.RunLock.adopt(int(args[0]), lake_dir)
    try:
        from lake.build import prefer_me_when_memory_runs_out
        from tb_common.logging import setup_logging
        from tb_contracts import dump

        from adapter import failure
        from adapter.cli import build_config
        from adapter.pipeline import LakeBudgetError, NoRoomForNight, SiteKeyError, run_ingest

        setup_logging("adapter")
        prefer_me_when_memory_runs_out()  # a night can be run again; the service's requests cannot
        req: dict[str, Any] = spec["request"]
        end: dict[str, Any]
        try:
            ac = build_config()[0]
            report = run_ingest(
                ac,
                req["source"],
                req["path"] or os.environ.get("TB_SOURCE_PATH", ""),
                since=req.get("since"),
                snapshot=req.get("snapshot"),
                load_fhir=bool(req.get("load_fhir", True)),
                rebuild_lake=bool(req.get("rebuild_lake", True)),
                validate=bool(req.get("validate", True)),
            )
            end = {"state": "done", "report": dump(report)}
        except (SiteKeyError, NoRoomForNight, LakeBudgetError) as exc:  # T-612, D-679: refused before anything was read
            end = {"state": "refused", "detail": f"night refused: {exc}"}
        except Exception as exc:
            failure.log_failure(log, f"ingest run {state.get('run')} failed", exc)
            end = {"state": "failed", "detail": failure.words(exc, str(state.get("run") or ""))}  # D-668
        runs.write(lake_dir, {**state, **end, "ended": _now()})
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
