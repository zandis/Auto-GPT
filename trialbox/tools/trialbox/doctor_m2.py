"""M2's doctor rows (F0's hook): the terminology update's state and every table with its rows, version and hash.
The body is ``tools/terminology_pack.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tools import terminology_pack

if TYPE_CHECKING:
    from tools.trialbox.doctor import DoctorInputs


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    return terminology_pack.doctor_checks(inp.env, datetime.now(UTC))
