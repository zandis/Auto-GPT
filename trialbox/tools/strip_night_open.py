"""Rollback past job schema 1.3.0 (F17 5a/5b): remove ``metrics.night_open`` from every MICROBATCH job record, so the
previous release's reader (it refuses a key it does not know) loads them. Run it with the NEW release, with the
orchestrator stopped, before the old images start; it changes nothing else and is safe to run twice.

    python -m tools.strip_night_open          # TB_DB_URL as the services use it; prints how many records changed
"""

from __future__ import annotations

from orchestrator.db import JobDB


def strip(db: JobDB) -> int:
    n = 0
    for j in db.find(type_="MICROBATCH", limit=10**9):
        if j.metrics is not None and j.metrics.night_open is not None:
            db.put(j.model_copy(update={"metrics": j.metrics.model_copy(update={"night_open": None})}))
            n += 1
    return n


if __name__ == "__main__":
    db = JobDB()
    try:
        print(f"night_open removed from {strip(db)} job records")
    finally:
        db.close()
