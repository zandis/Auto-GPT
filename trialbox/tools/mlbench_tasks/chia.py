"""Chia corpus loader for ``criteria_extract_public`` (spec v4 S1-13, App. H). A stub until the licence is confirmed.

The loader ships only after the Chia licence is confirmed (App. H marks it *uncertain*). Until then it refuses to run,
fetches nothing and reads nothing.
"""

from __future__ import annotations

from pathlib import Path

LICENCE_CONFIRMED = False


class ChiaLicenceUnconfirmed(RuntimeError):
    pass


def load_chia(dest: Path) -> list[dict[str, str]]:
    if not LICENCE_CONFIRMED:
        raise ChiaLicenceUnconfirmed("Chia corpus licence not confirmed (App. H); loader disabled")
    raise NotImplementedError("Chia loader is implemented after licence confirmation")  # pragma: no cover
