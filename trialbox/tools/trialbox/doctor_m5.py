"""M5's doctor rows (F0's hook): ``key_escrow`` (INT-M5, R22-33). On a VALIDATION or PRODUCTION box whose KEK is
bound to its board (a TPM) and has no escrow set its custodians signed, the row is a WARN that names the open gate
(``[go-live gate key-escrow: open]``): the acceptance's ``key_escrow`` criterion refuses go-live until it passes. A
WARN, never a FAIL: an installed box before its key ceremony stays green. No row on another box (DEV, TEST). The
body is ``tools/key_escrow.go_live``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.trialbox.doctor import DoctorInputs


def doctor_checks(inp: DoctorInputs) -> list[tuple[str, str, str]]:
    from tb_common import kek

    from tools import key_escrow as ke
    from tools.trialbox.doctor import ROOT, _secrets_dir

    env = (inp.env.get("TB_ENV") or "PRODUCTION").strip().upper()
    if env not in kek.STRICT_ENVS:  # go-live is a VALIDATION or PRODUCTION step: nothing to say elsewhere
        return []
    ok, why = ke.go_live(_secrets_dir(inp), inp.deploy or ROOT / "deploy")
    if ok:
        return [("key_escrow", "PASS", why)]
    return [("key_escrow", "WARN", f"{why} [{ke.GATE}: open]")]
