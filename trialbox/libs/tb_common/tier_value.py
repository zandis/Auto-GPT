"""A value of this box's tier record, for the services that read one (plan 10 row 10E-1c, D-1320, D-1322).

The tier record is ``models/tiers/<profile>.json`` (``tools/tier_record.py`` checks it; the trialbox-py image copies
``models/`` to ``/app/models``, so the path relative to this file is the same on the host and in a container). The
box's profile comes from ``TB_PROFILE``, the label the installer writes (``deploy/install.sh``): ``P-PRO6000`` is
``rtxpro6000`` and ``P-5090`` is ``rtx5090``; any other label has no record.

**Measured only (D-1322).** A reader takes the record's value only when the field's basis is ``measured``. A
``declared`` or ``not_measured`` field, a missing or malformed record and an unknown label give no value, and the
reader keeps the value it had before the record existed (its named fallback). :class:`TierValue` says which case it
was, for the reader's start-up log line. A box never fails to start because of its tier record.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TIERS_DIR = Path(__file__).resolve().parents[2] / "models" / "tiers"
PROFILE_OF_LABEL = {"P-PRO6000": "rtxpro6000", "P-5090": "rtx5090"}
# the gateway's slots per endpoint when no record, setting or measured tier value says otherwise (before 10E-1c the
# module constant ``SLOTS`` of services/gateway/load.py)
FALLBACK_SLOTS = 16
CASES = ("measured", "declared", "not_measured", "no_record", "malformed", "unknown_profile")


@dataclass(frozen=True)
class TierValue:
    """One field of the box's tier record as a reader sees it; ``value`` is set only when ``case`` is measured."""

    field: str
    case: str
    profile: str | None = None
    value: Any = None
    declared: Any = None
    why: str = ""

    def line(self, fallback: Any) -> str:
        """The start-up log text: which case, and the value used."""
        where = f"tier record {self.profile}" if self.profile else "tier record"
        if self.case == "measured":
            return f"{where}: {self.field} = {self.value!r} (measured)"
        if self.case == "declared":
            return (
                f"{where}: {self.field} is declared {self.declared!r}, not measured: {fallback!r} kept (the record "
                "and the running value differ)"
                if self.declared != fallback
                else f"{where}: {self.field} is declared {self.declared!r}, not measured: {fallback!r} kept"
            )
        if self.case == "not_measured":
            return f"{where}: {self.field} not measured: {fallback!r} kept"
        if self.case == "unknown_profile":
            return f"no tier record for TB_PROFILE {self.why or '(unset)'}: {self.field} {fallback!r} kept"
        return f"{where}: {self.case} ({self.why}): {self.field} {fallback!r} kept"


def profile_of(env: Mapping[str, str] | None = None) -> str | None:
    """The record's profile for this box's ``TB_PROFILE`` label, or None."""
    e = os.environ if env is None else env
    return PROFILE_OF_LABEL.get((e.get("TB_PROFILE") or "").strip())


def measured(field: str, env: Mapping[str, str] | None = None, tiers_dir: Path | None = None) -> TierValue:
    """The field of this box's tier record (module docstring); never raises."""
    e = os.environ if env is None else env
    profile = profile_of(e)
    if profile is None:
        return TierValue(field, "unknown_profile", why=repr((e.get("TB_PROFILE") or "").strip()))
    path = (tiers_dir or TIERS_DIR) / f"{profile}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TierValue(field, "no_record", profile, why=f"no {path.name}")
    except (OSError, ValueError) as exc:
        return TierValue(field, "malformed", profile, why=f"{path.name}: {type(exc).__name__}")
    fields = doc.get("fields") if isinstance(doc, dict) else None
    f = fields.get(field) if isinstance(fields, dict) else None
    if not isinstance(f, dict) or f.get("basis") not in ("measured", "declared", "not_measured"):
        return TierValue(field, "malformed", profile, why=f"{path.name}: no readable field {field}")
    if f["basis"] == "measured" and f.get("value") is not None:
        return TierValue(field, "measured", profile, value=f["value"])
    if f["basis"] == "declared":
        return TierValue(field, "declared", profile, declared=f.get("value"))
    if f["basis"] == "measured":
        return TierValue(field, "malformed", profile, why=f"{path.name}: {field} measured with no value")
    return TierValue(field, "not_measured", profile)


def positive_int(tv: TierValue) -> int | None:
    """The measured value as a count (sequences, patients), or None when it is not one."""
    v = tv.value
    return v if tv.case == "measured" and isinstance(v, int) and not isinstance(v, bool) and v > 0 else None
