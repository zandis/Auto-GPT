"""M9's doctor rows (F0's hook): the Docker Engine against its tested range, the machine profile and its caps. The body
is ``tools/trialbox/profile_m9.py`` (standard library only: a host's own python runs it)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.trialbox import profile_m9

if TYPE_CHECKING:
    from tools.trialbox.doctor import DoctorInputs


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    return profile_m9.doctor_checks(inp)
