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


def funnel_drops_publishable(remaining: list[int], threshold: int = 5) -> list[bool]:
    """Which drops of a funnel may be published (D-467 rule 5), for exact remaining counts r_0 ≥ r_1 ≥ …

    The drop of step i (i ≥ 1) is d_i = r_{i-1} − r_i; index 0 (the pool) has no drop and is never published. A drop
    is published only when the drop and its remainder r_i are both at or above ``threshold``. Every withheld step also
    withholds one neighbouring step (complementary suppression, as ``deliverables.disclosure.complementary`` does for
    the full funnel; the next step first, else the previous one), unless a neighbour is already withheld on its own, so
    no withheld drop is the difference of published values."""
    n = len(remaining)
    if any(r < 0 for r in remaining):
        raise ValueError("negative count")
    primary = [False] + [
        remaining[i - 1] - remaining[i] >= threshold and remaining[i] >= threshold for i in range(1, n)
    ]
    out = list(primary)
    for i in range(1, n):
        if primary[i]:
            continue
        nbrs = [j for j in (i + 1, i - 1) if 1 <= j < n]
        if any(not primary[j] for j in nbrs):
            continue  # a neighbour is withheld on its own: the two cover each other
        if nbrs:
            out[nbrs[0]] = False
    return out
