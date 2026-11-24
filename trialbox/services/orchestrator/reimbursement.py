"""Reimbursement fenced off in 1.0 (card 9e-9; plan 9 decision 8, ruled path (ii)).

NAV (the reimbursement lists), TWPAS (its prior-authorisation bundles) and SUBMIT (the one path on which a bundle
leaves the box for the NHI) inform an individual patient's care, which 1.0's intended use rules out (condition C2 of
``docs/plan/intended-use.md``). They ship switched off, behind the audited flag :data:`FLAG`:

* off by default, on a fresh box and on any box whose flag store cannot be read;
* switched on only on ``/ops/flags`` (or :meth:`tb_common.flags.Flags.set`) with a reason, and only on a test box:
  ``Flags.set`` refuses it when ``TB_ENV`` is VALIDATION or PRODUCTION (unset is PRODUCTION), as it refuses
  ``steps.acting_role``;
* read at run time with the box's ``TB_ENV`` too, so a row that says ``on`` (a database restored from a test box)
  opens nothing on a validation or production box.

Each of the three asks :func:`is_open` in one place: NAV and SUBMIT at their first step (:func:`require_open`), TWPAS
in :func:`orchestrator.scenarios.twpas.enabled`. The night passes over its NAV step while it is closed, and says so
once per night.
"""

from __future__ import annotations

from collections.abc import Mapping

from tb_common.flags import Flags, test_box

FLAG = "reimbursement.paths"


def is_open(env: Mapping[str, str] | None = None, url: str | None = None) -> bool:
    """True only on a test box whose flag :data:`FLAG` is ``on``. A flag that cannot be read is off."""
    import os

    if not test_box(dict(env) if env is not None else dict(os.environ)):
        return False
    return Flags(url=url).get(FLAG, "off") == "on"


def require_open() -> None:
    """The first check of NAV and SUBMIT: a job fails at once, before anything is read, while the fence stands."""
    from orchestrator.clients import StepFailed

    if not is_open():
        raise StepFailed(
            "reimbursement",
            "Refused: reimbursement (NAV, TWPAS and SUBMIT) is not part of this release and is switched off on this "
            "box. It can be switched on only on a test box (TB_ENV DEV or TEST), on /ops/flags with a reason "
            "(reimbursement.paths).",
        )
