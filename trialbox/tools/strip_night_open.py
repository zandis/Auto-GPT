"""Rollback past job schema 1.3.0 (F17 5a/5b): remove ``metrics.night_open`` from every MICROBATCH job record, so the
previous release's reader (it refuses a key it does not know) loads them. Run it with the NEW release, with the
orchestrator stopped, before the old images start; it changes nothing else and is safe to run twice.

    python -m tools.strip_night_open          # TB_DB_URL as the services use it; prints how many records changed
"""

from __future__ import annotations

import json

from orchestrator.db import JobDB


def strip(db: JobDB) -> int:
    n = 0
    for job_id, data in db._db.fetchall("SELECT job_id, data FROM jobs WHERE type = ?", ("MICROBATCH",)):
        if "night_open" not in (json.loads(data).get("metrics") or {}):  # present, whatever its value (null too)
            continue
        j = db.get(job_id)
        if j is not None and j.metrics is not None:
            db.put(
                j.model_copy(update={"metrics": j.metrics.model_copy(update={"night_open": None})})
            )  # put omits None
            n += 1
    return n


if __name__ == "__main__":
    db = JobDB()
    try:
        print(f"night_open removed from {strip(db)} job records")
    finally:
        db.close()
