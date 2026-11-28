"""The validator gate against the rates a steward accepted, per class (TOL-HOLDS, SAFE-1 A5):
``<lake>/validation_baseline.json``.

The gate holds a night whose sampled validation error rate is over ``validation_max_pct`` (0.5 %). On a hospital
whose feed has a standing gap (a Patient table where 7 % have no birth date) every night is over it, and the steward
accepted the same gap every night. Now the steward's accept of a held night (:func:`adapter.publish.publish_held`)
records each problem class of that night and its rate; a later accept raises a class to the rate accepted. A class
is ``<resource type> <element>: <kind>`` (:class:`~adapter.validate.validator.ValidationResult` ``classes``), its rate
its share of the sampled resources of its own type, so a table read whole on a delta night is measured against its
own rate, not the delta's mix.

With a baseline, a night over the ceiling still holds when

* a class is above its accepted rate by the margin, the larger of 2x and +1 point, or
* the resources with a problem outside the baseline (a NEW class, or an error the validator names no class for)
  are over the ceiling on their own;

otherwise it publishes, and the gate record carries a warning with every class's rate against its accepted one.
The baseline only excuses: a night under the ceiling passes with or without it. Without the file (or with one that
cannot be read) the gate is the ceiling alone, as before. Class names and percentages only: no value of a row.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from adapter.validate.validator import ValidationResult

log = logging.getLogger("adapter")
BASELINE = "validation_baseline.json"  # <lake>/: class -> the rate (percent) a steward accepted
NIGHT = "validation_classes.json"  # beside the night's report: class -> its rate that night


def rates(v: ValidationResult) -> dict[str, float]:
    """Each class's share (percent) of the sampled resources of its own type."""
    counts: dict[str, int] = {}
    for labels in v.classes.values():
        for c in labels:
            counts[c] = counts.get(c, 0) + 1
    return {c: round(100.0 * n / (v.types.get(c.split(" ", 1)[0]) or v.sampled or 1), 3)
            for c, n in sorted(counts.items())}  # fmt: skip


def _margin(accepted: float) -> float:
    return max(2 * accepted, accepted + 1)


def judge(base: dict[str, float] | None, v: ValidationResult, max_pct: float) -> tuple[list[str], list[str]]:
    """The night's validation verdict: (the lines that hold it, the warnings when the baseline excuses it)."""
    if v.error_pct <= max_pct:
        return [], []
    over = f"validation error rate {v.error_pct:.2f}% exceeds {max_pct}%"
    if base is None:
        return [over], []
    got = rates(v)
    held = []
    worse = [f"{c} {r:g}% (accepted {base[c]:g}%)" for c, r in got.items() if c in base and r > _margin(base[c])]
    if worse:
        held.append(f"{over}: above the rate the steward accepted: {'; '.join(worse)}")
    known = sum(1 for labels in v.classes.values() if labels and all(c in base for c in labels))
    outside = 100.0 * (v.errors - known) / v.sampled
    if outside > max_pct:
        new = sorted({c for labels in v.classes.values() for c in labels if c not in base})
        held.append(f"{over}: {outside:.2f}% not among the classes the steward accepted"
                    + (f" (new: {', '.join(new[:10])})" if new else ""))  # fmt: skip
    if held:
        return held, []
    said = "; ".join(f"{c} {r:g}% ({f'accepted {base[c]:g}%' if c in base else 'new'})" for c, r in got.items())
    return [], [f"{over}, within the rates the steward accepted: {said}"]


def _read(path: Path) -> dict[str, float] | None:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError):
        log.warning("%s cannot be read; the validation gate is the ceiling alone", path.name)
        return None
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(x, int | float) for k, x in raw.items()):
        return None
    return {k: float(x) for k, x in raw.items()}


def load(lake_dir: Path) -> dict[str, float] | None:
    """The accepted baseline, or None (none accepted yet, or a file that is not that shape)."""
    return _read(lake_dir / BASELINE)


def write_night(night_dir: Path, night_rates: dict[str, float]) -> None:
    (night_dir / NIGHT).write_text(json.dumps(night_rates, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_night(night_dir: Path) -> dict[str, float] | None:
    return _read(night_dir / NIGHT)


def accept(lake_dir: Path, night_rates: dict[str, float] | None) -> None:
    """The steward accepted a held night with these class rates: each becomes the class's baseline, or raises it.
    Never raises: a baseline that cannot be written must not fail the publish that ran (the next night is judged
    against the ceiling, as before, and the steward is asked again)."""
    if not night_rates:
        return
    try:
        base = load(lake_dir) or {}
        for c, r in night_rates.items():
            base[c] = max(r, base.get(c, 0.0))
        tmp = lake_dir / f".{BASELINE}.tmp"
        tmp.write_text(json.dumps(base, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(lake_dir / BASELINE)
        log.info("validation baseline: %d classes accepted", len(base))
    except OSError as exc:
        log.warning("validation baseline not written (%s); the next night is judged against the ceiling",
                    type(exc).__name__)  # fmt: skip
