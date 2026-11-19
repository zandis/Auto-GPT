"""A value of this box's tier record, for the services that read one (plan 10 row 10E-1c, D-1320, D-1322).

The tier record is ``models/tiers/<profile>.json`` (``tools/tier_record.py`` checks it; the trialbox-py image copies
``models/`` to ``/app/models``, so the path relative to this file is the same on the host and in a container). The
box's profile comes from ``TB_PROFILE``, the label the installer writes (``deploy/install.sh``): ``P-PRO6000`` is
``rtxpro6000`` and ``P-5090`` is ``rtx5090``; any other label has no record.

**Measured only (D-1322).** A reader takes the record's value only when the field's basis is ``measured``. A
``declared`` or ``not_measured`` field, a missing or malformed record and an unknown label give no value, and the
reader keeps the value it had before the record existed (its named fallback). :class:`TierValue` says which case it
was, for the reader's start-up log line. A box never fails to start because of its tier record.

**Never raises (card H-51, finding H51-01).** An operator can replace the file, so :func:`measured` answers
``malformed`` with a fixed reason (never the file's content) for any file it cannot read as a record: over
:data:`TIER_RECORD_MAX_BYTES` (refused before it is parsed), not UTF-8, not JSON, nested too deep for the parser
(``RecursionError``), a directory, a symbolic-link loop, no permission. :func:`read_record` is the one bounded read;
the checker (``tools/tier_record.py``) uses it too and fails loudly where this reader keeps its fallback.
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
# the largest tier record read (bytes): the shipped records are under 8 kB; a file over this is refused unread, so a
# replaced file cannot make a reader (the gateway at start, a console page) hold an unbounded file in memory
TIER_RECORD_MAX_BYTES = 1_000_000
CASES = ("measured", "declared", "not_measured", "no_record", "malformed", "unknown_profile")


class TierRecordUnreadable(ValueError):
    """A tier record file that is not readable as one; the message is fixed words and the file's name only."""


def read_record(path: Path, max_bytes: int = TIER_RECORD_MAX_BYTES) -> Any:
    """The parsed JSON of the tier record at ``path``, read at most ``max_bytes`` bytes.

    Raises ``FileNotFoundError`` when there is no file, and :class:`TierRecordUnreadable` for any other file that
    cannot be read as JSON (the other ``OSError`` cases, a file over the cap, not UTF-8, not JSON, nested too deep).
    """
    try:
        with path.open("rb") as fh:
            raw = fh.read(max_bytes + 1)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise TierRecordUnreadable(f"{path.name}: not readable ({type(exc).__name__})") from None
    if len(raw) > max_bytes:
        raise TierRecordUnreadable(f"{path.name}: over {max_bytes} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise TierRecordUnreadable(f"{path.name}: not UTF-8") from None
    except RecursionError:
        raise TierRecordUnreadable(f"{path.name}: nested too deep to read") from None
    except ValueError as exc:
        raise TierRecordUnreadable(f"{path.name}: not JSON ({type(exc).__name__})") from None


def _shown(v: Any) -> str:
    """``repr`` of a record's value for a log line, bounded; fixed words when it cannot be shown."""
    try:
        r = repr(v)
    except (RecursionError, ValueError):
        return "(a value that cannot be shown)"
    return r if len(r) <= 80 else r[:77] + "..."


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
            return f"{where}: {self.field} = {_shown(self.value)} (measured)"
        if self.case == "declared":
            return (
                f"{where}: {self.field} is declared {_shown(self.declared)}, not measured: {fallback!r} kept (the "
                "record and the running value differ)"
                if not _same(self.declared, fallback)
                else f"{where}: {self.field} is declared {_shown(self.declared)}, not measured: {fallback!r} kept"
            )
        if self.case == "not_measured":
            return f"{where}: {self.field} not measured: {fallback!r} kept"
        if self.case == "unknown_profile":
            return f"no tier record for TB_PROFILE {self.why or '(unset)'}: {self.field} {fallback!r} kept"
        return f"{where}: {self.case} ({self.why}): {self.field} {fallback!r} kept"


def _same(a: Any, b: Any) -> bool:
    try:
        return bool(a == b)
    except (RecursionError, ValueError):
        return False


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
        doc = read_record(path)
    except FileNotFoundError:
        return TierValue(field, "no_record", profile, why=f"no {path.name}")
    except TierRecordUnreadable as exc:
        return TierValue(field, "malformed", profile, why=str(exc))
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
