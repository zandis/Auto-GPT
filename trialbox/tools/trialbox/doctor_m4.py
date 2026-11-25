"""M4's doctor rows (F0's hook): ``check_audit_heads`` is the body of the check of that name (the signed head against
the chain), ``doctor_checks`` adds the open custody row. The body is ``tools/trialbox/audit_heads.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.trialbox import audit_heads

if TYPE_CHECKING:
    from datetime import datetime

    from tools.trialbox.doctor import DoctorInputs

_PLATFORM = "on a platform no host cron signs the audit head: STD-002 is open there"


def _rows(inp: DoctorInputs, now: datetime | None = None) -> list[tuple[str, str, str]]:
    from tools.trialbox.doctor import ROOT

    return audit_heads.doctor_checks(inp.env, inp.deploy or ROOT / "deploy", now)


def check_audit_heads(inp: DoctorInputs, now: datetime | None = None) -> tuple[str, str, str]:
    if inp.platform:  # nothing signs heads on a platform yet: said, not passed
        return ("audit_heads", "WARN", _PLATFORM)
    return _rows(inp, now)[0]


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    return [] if inp.platform else _rows(inp)[1:]
