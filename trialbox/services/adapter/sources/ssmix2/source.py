"""``ssmix2`` source (JP SS-MIX2 standardized storage). Not part of v1.0 scope for Taiwan sites (DECISIONS D-28).

The reader raises a clear error instead of silently producing nothing; Japanese sites can export SS-MIX2 to CSV
and use the ``csv`` source with a JP Core mapping until the native reader ships.
"""

from __future__ import annotations

from pathlib import Path


class Ssmix2Source:
    name = "ssmix2"

    def __init__(self, directory: Path) -> None:
        raise NotImplementedError(
            "ssmix2 source is planned for v1.1; export SS-MIX2 to CSV and use --source csv with a jp_core mapping "
            f"(requested directory: {directory})"
        )
