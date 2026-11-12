"""``fhir_bulk`` source: NDJSON files from a FHIR Bulk Data ``$export`` (already FHIR; no mapping step).

An export with ``_since`` lists what was deleted in that window in the manifest's ``deleted`` array: NDJSON files
of ``Bundle`` resources whose entries are ``DELETE Type/id`` requests (Bulk Data Access IG). They sit beside the
resource files or in a ``deleted/`` folder; :meth:`FhirBulkSource.deleted` reads them as tombstones and
:meth:`FhirBulkSource.resources` never yields a Bundle as a resource (dataflow review P0-1).
"""

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

    def _lines(self, paths: list[Path]) -> Iterator[dict[str, Any]]:
        for path in paths:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield json.loads(line)

    def resources(self) -> Iterator[dict[str, Any]]:
        for r in self._lines(sorted(self.directory.glob("*.ndjson"))):
            if r.get("resourceType") != "Bundle":
                yield r

    def deleted(self) -> Iterator[tuple[str, str]]:
        """``(resource type, source id)`` of every ``DELETE`` entry in the export's deleted Bundles."""
        paths = sorted(self.directory.glob("*.ndjson")) + sorted((self.directory / "deleted").glob("*.ndjson"))
        for b in self._lines(paths):
            if b.get("resourceType") != "Bundle":
                continue
            for e in b.get("entry") or []:
                req = e.get("request") or {}
                rtype, _, rid = str(req.get("url") or "").partition("/")
                if str(req.get("method") or "").upper() == "DELETE" and rtype and rid:
                    yield rtype, rid.split("/", 1)[0]
