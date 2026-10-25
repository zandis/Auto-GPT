"""File-drop extraction for L0 (§5.5 ``file_drop``; the synthetic CSV site and FHIR bulk NDJSON directories).

A drop directory holds one object per table (``<table>.csv`` or ``<Type>.ndjson[.gz]``) and, optionally,
``control_totals.json``: the totals the source system took in the same read as the extract (§5.9.1). When the drop
carries no totals, the connector computes them at extract time from the same bytes (origin ``extract``); those
totals cannot reveal a loss between source and drop, and the manifest says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tb_contracts.landing import ControlTotals

from dataplat.landing.shape import table_name

CONTROL_TOTALS_FILE = "control_totals.json"
_PATTERNS = ("*.csv", "*.ndjson", "*.ndjson.gz")


@dataclass(frozen=True)
class Drop:
    files: dict[str, Path]
    control_totals: dict[str, ControlTotals] | None


def read_drop(source_dir: Path, tables: list[str] | None = None) -> Drop:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source directory not found: {source_dir}")
    files: dict[str, Path] = {}
    for pattern in _PATTERNS:
        for p in sorted(source_dir.glob(pattern)):
            t = table_name(p)
            if tables is None or t in tables:
                files[t] = p
    totals: dict[str, ControlTotals] | None = None
    ct = source_dir / CONTROL_TOTALS_FILE
    if ct.exists():
        doc = json.loads(ct.read_text(encoding="utf-8"))
        totals = {t: ControlTotals.model_validate(v) for t, v in sorted((doc.get("tables") or {}).items())}
    return Drop(dict(sorted(files.items())), totals)


def write_control_totals(source_dir: Path, totals: dict[str, ControlTotals]) -> Path:
    """Write ``control_totals.json`` (what a source system would deliver with its drop)."""
    path = source_dir / CONTROL_TOTALS_FILE
    body = {"tables": {t: v.model_dump(mode="json") for t, v in sorted(totals.items())}}
    path.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
