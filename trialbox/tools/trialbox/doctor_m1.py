"""M1's doctor rows (F0's hook): one WARN per item of "Information still needed" that is open, naming the step that waits
for it. The body is ``tools/box/needs_apply.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.box import needs_apply

if TYPE_CHECKING:
    from tools.trialbox.doctor import DoctorInputs


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    if inp.deploy is None:  # not a box's own files: nothing to look at
        return []
    return needs_apply.doctor_checks(inp.deploy, inp.env, inp.settings)
