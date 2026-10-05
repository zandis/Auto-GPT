"""``fhir_bulk`` source: NDJSON files from a FHIR Bulk Data ``$export`` (already FHIR; no mapping step)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class FhirBulkSource:
    name = "fhir_bulk"

    def __init__(self, directory: Path) -> None:
        if not directory.is_dir():
            raise FileNotFoundError(f"bulk export directory not found: {directory}")
        self.directory = directory

    def resources(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self.directory.glob("*.ndjson")):
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield json.loads(line)
