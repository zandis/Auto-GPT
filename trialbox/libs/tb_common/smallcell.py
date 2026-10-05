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


def round_count(n: int, threshold: int = 5) -> int | str:
    """Controlled rounding for published counts that sit next to other counts (funnels, sensitivity rows, monthly
    series): 1..threshold-1 become ``"<threshold"``, larger counts are rounded to the nearest multiple of
    ``threshold``. Differences between published counts are then multiples of the threshold, so a small cell can
    never be recomputed from its neighbours (100 → 97 would expose a suppressed drop of 3)."""
    if n < 0:
        raise ValueError("negative count")
    if 0 < n < threshold:
        return f"<{threshold}"
    return int(threshold * ((n + threshold // 2) // threshold))


def rate_publishable(numerator: int, denominator: int, threshold: int = 5) -> bool:
    """A published rate must not reveal a small count: neither its numerator, nor its complement
    (denominator − numerator), nor the denominator may be a small cell."""
    rest = denominator - numerator
    return denominator >= threshold and not (0 < numerator < threshold) and not (0 < rest < threshold)
