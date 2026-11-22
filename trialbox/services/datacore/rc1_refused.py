"""rc1's refusal of an EDC write from screening, as the REDCap bridge's error (R22-34; the integrator's go, comment
7079138866): ``datacore.sync._push`` raises it on a PRODUCTION box (``tb_common.rc1_refusals``), so a caller that
catches the bridge's errors (``orchestrator.study_api``: "the read stands; the write is retried next run") keeps the
read and records the refusal instead of failing whole."""

from __future__ import annotations

from rc_bridge.client import RcError
from tb_common import rc1_refusals

CODE = "RC-RC1"


class EdcWriteRefused(RcError):
    """Nothing was pushed. ``key`` is the table's message key, ``environment`` the box's; refused, HTTP 403."""

    def __init__(self, refused: rc1_refusals.Rc1Refused) -> None:
        super().__init__(CODE, refused.say(), refused=True)
        self.status = 403
        self.key = refused.refusal.key
        self.environment = refused.environment
