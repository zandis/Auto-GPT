"""The lake's build as a process of its own (PERF-001 / PERF-025, D-539).

    python -m lake.build <lock fd> <spec as JSON>

Started by the lake service for one rebuild job (``lake.app``): it inherits the open file that holds the snapshot's
build lock, runs the build and writes the job's end, exactly as the service's thread did. The service's workers go
on answering queries; when this process is killed (the kernel, under the container's memory cap; a restart) the lock
goes with it and the job reads ``interrupted``. Nothing is passed but the job and where to build: the lake's folder,
the site's zone and chart-number pattern and the embedder come from the environment, as the service's own do.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from lake.store import BuildLock, Lake, write_rebuild_job

log = logging.getLogger("lake")

#: the kernel's own scale for "kill this one first" ends at 1000 (proc(5), oom_score_adj): not a limit of ours
OOM_FIRST = "1000"


def prefer_me_when_memory_runs_out() -> None:
    """Under the container's memory cap the kernel picks a process to kill. It should be the build, which can be
    started again, and not a query worker. A process may always raise its own score; where the file is not there
    (not Linux) nothing is done."""
    with contextlib.suppress(OSError):
        Path("/proc/self/oom_score_adj").write_text(OOM_FIRST, encoding="ascii")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    spec: dict[str, Any] = json.loads(args[1])
    job: dict[str, Any] = spec["job"]
    lake_dir = Path(spec["lake_dir"])
    lock = BuildLock.adopt(int(args[0]), lake_dir, str(job["snapshot"]))
    try:
        try:
            from embed_service.embedder import from_env
            from tb_common.config import site_tz
            from tb_common.logging import setup_logging
            from tb_common.phi_guard import site_mrn_regex

            setup_logging("lake")
            prefer_me_when_memory_runs_out()
            lake = Lake(lake_dir, site_tz(), site_mrn_regex())
            embedder = from_env(os.environ.get("TB_LAKE_EMBEDDER", "http"), os.environ.get("EMBED_URL"))
        except Exception as exc:  # the build could not even begin: the job's end, by the error's type only
            log.exception("the build of %s could not begin", job.get("snapshot"))  # which setting: in the log
            why = f"the build's process could not begin ({type(exc).__name__})"
            write_rebuild_job(lake_dir, {**job, "state": "failed", "detail": why, "ended": time.time()})
            return 1
        ndjson_dir = spec.get("ndjson_dir")
        lake.run_rebuild_job(
            job,
            embedder,
            Path(ndjson_dir) if ndjson_dir else None,
            promote=bool(spec.get("promote", True)),
            check=bool(spec.get("check", False)),
        )
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
