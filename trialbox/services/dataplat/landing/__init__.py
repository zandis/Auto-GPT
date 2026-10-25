"""L0 landing (§5.3, DP-04; S1-02): immutable, idempotent batches with sha256 and schema fingerprints."""

from dataplat.landing.connectors import CONTROL_TOTALS_FILE, Drop, read_drop, write_control_totals
from dataplat.landing.shape import fingerprint, iter_rows, shape
from dataplat.landing.zone import (
    RAW_RETENTION_DAYS,
    LandingError,
    LandingResult,
    LandingZone,
    changed_tables,
)

__all__ = [
    "CONTROL_TOTALS_FILE",
    "RAW_RETENTION_DAYS",
    "Drop",
    "LandingError",
    "LandingResult",
    "LandingZone",
    "changed_tables",
    "fingerprint",
    "iter_rows",
    "read_drop",
    "shape",
    "write_control_totals",
]
