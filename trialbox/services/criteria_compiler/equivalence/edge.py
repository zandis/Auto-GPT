"""The edge cases of the equivalence fixture (T-619a, STD-070, CR-001/CR-098/CR-115): where SQL and CQL could part.

Five synthetic patients, each with one ALT result and GZQO-EXC-13 ("ALT > 120 U/L", the latest result of the 180
days before the index date) as the criterion both engines answer:

* ``edge-utc``: 200 U/L at 23:30 UTC on the day before the window opens. In the site zone (UTC+8) it is 07:30
  on the first day of the window, so it counts. Before the ingest wrote instants in the site's offset
  (``adapter.instants``), SQL read the site day (inside) and CQL the UTC day (outside): true against unknown.
* ``edge-cens-above`` ">500 U/L": every value above 500 is above 120: true in both.
* ``edge-cens-below`` "<50 U/L": every value below 50 is below 120: false in both.
* ``edge-cens-open`` "<200 U/L": the true value may be either side of 120: unknown in both (CQL read 200 > 120 as
  true before it read the comparator).
* ``edge-plain`` 80 U/L: false.

Nothing here is a person: the ids, dates and values are made up for the check (synthetic data only).
"""

from __future__ import annotations

from datetime import date
from typing import Any

RULESET = "GZQO"
CRITERION = "GZQO-EXC-13"
INDEX_DATE = date(2026, 10, 5)  # the window opens on 2026-04-08 (index - 180 days)
SITE_TZ = "Etc/GMT-8"  # a site at UTC+8, as in Taiwan (no real site zone in code, D-315); IANA writes it GMT-8
ALT = {"system": "http://loinc.org", "code": "1742-6", "display": "ALT"}
UCUM = "http://unitsofmeasure.org"

# patient -> (effectiveDateTime, value, comparator or None, expected answer of CRITERION)
CASES: dict[str, tuple[str, float, str | None, bool | None]] = {
    "edge-utc": ("2026-04-07T23:30:00Z", 200.0, None, True),
    "edge-cens-above": ("2026-09-01T09:00:00+08:00", 500.0, ">", True),
    "edge-cens-below": ("2026-09-01T09:00:00+08:00", 50.0, "<", False),
    "edge-cens-open": ("2026-09-01T09:00:00+08:00", 200.0, "<", None),
    "edge-plain": ("2026-09-01T09:00:00+08:00", 80.0, None, False),
}


def resources() -> list[dict[str, Any]]:
    """The FHIR resources of the fixture, as an inbound feed would send them (offsets as stated)."""
    out: list[dict[str, Any]] = []
    for i, (pid, (when, value, comparator, _)) in enumerate(sorted(CASES.items())):
        out.append({"resourceType": "Patient", "id": pid, "gender": "female", "birthDate": f"19{60 + i}-03-01"})
        qty: dict[str, Any] = {"value": value, "unit": "U/L", "system": UCUM, "code": "U/L"}
        if comparator:
            qty["comparator"] = comparator
        out.append(
            {
                "resourceType": "Observation",
                "id": f"{pid}-alt",
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory",
                            }
                        ]
                    }
                ],
                "code": {"coding": [ALT]},
                "subject": {"reference": f"Patient/{pid}"},
                "effectiveDateTime": when,
                "valueQuantity": qty,
            }
        )
    return out


def expected() -> dict[str, bool | None]:
    """pid -> the answer both engines must give for :data:`CRITERION`."""
    return {pid: case[3] for pid, case in CASES.items()}
