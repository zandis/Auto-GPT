"""Chia corpus seed for the criterion library (S1-15): disabled until the corpus licence is confirmed.

The spec lists the Chia annotated eligibility corpus as a seed source (``seed_source: chia``), but its licence is
marked *uncertain* (spec v4 App. H; HANDOFF §2.3). Until the licence is confirmed in writing, nothing from Chia may be
loaded into or shipped with the library.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

REASON = (
    "the Chia corpus licence is unconfirmed (spec v4 App. H, HANDOFF §2.3); the seed loader ships only after the "
    "licence is confirmed"
)


class ChiaLicenceUnconfirmed(RuntimeError):
    """Raised by :func:`load_chia_seed` while the Chia licence is unconfirmed."""


def load_chia_seed(source: Path | str, *args: object, **kwargs: object) -> NoReturn:
    """Load the Chia corpus as ``draft`` library records and report the duplicate rate (not available yet)."""
    raise ChiaLicenceUnconfirmed(f"cannot load {source}: {REASON}")
