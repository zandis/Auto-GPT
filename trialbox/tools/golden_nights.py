"""The goldens' next night (``tools.goldens``): which records the source deletes and which results it corrects.

D-1253: the choice depends on each record's content, never on its id or on its place in the id-sorted snapshot, so
a change of the id rule changes no record that is deleted or corrected (``tools/goldens_id_proof.py`` builds the
goldens of two releases with this one choice). A record's key is its canonical JSON with every 32-hex token (an id,
a reference, a pid) blanked and its source row (``meta.source``) kept; two records with one key share their fate.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


def _bucket(r: dict[str, Any], every: int, salt: str) -> bool:
    key = _TOKEN.sub("#", json.dumps(r, sort_keys=True, ensure_ascii=False))
    return int(hashlib.sha256(f"{salt}|{key}".encode()).hexdigest()[:12], 16) % every == 0


def next_night(ndjson: Path, out: Path) -> None:
    """The next night's feed: the same snapshot with about a tenth of the clinical records gone (deleted at the
    source) and about every 25th remaining numeric result corrected in place (the OMOP store updates it, with its
    before-image). Patients stay (removing a person is the opt-out path's job, never a feed delta's)."""
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(ndjson.glob("*.ndjson")):
        rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
        if f.stem != "Patient":
            rows = [r for r in rows if not _bucket(r, 10, "deleted")]
        if f.stem == "Observation":
            for r in rows:
                v = (r.get("valueQuantity") or {}).get("value")
                if isinstance(v, int | float) and _bucket(r, 25, "corrected"):
                    r["valueQuantity"]["value"] = round(v + 1, 4)
        (out / f.name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
