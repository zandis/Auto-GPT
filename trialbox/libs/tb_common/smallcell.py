"""Small-cell suppression for aggregate outputs (SPEC §8.1, §8.3, §10.1)."""

from __future__ import annotations


def suppress(n: int, threshold: int = 5) -> int | str:
    """Counts 1..threshold-1 become ``"<threshold"``; 0 and counts >= threshold are kept."""
    if n < 0:
        raise ValueError("negative count")
    if 0 < n < threshold:
        return f"<{threshold}"
    return n


def is_suppressed(value: int | str) -> bool:
    return isinstance(value, str)
