"""H-139 (H139-10, the integrator's 7155439799): a key test's box is a deploy folder of its own, not the checkout's.

The key commands read the box's environment from its ``deploy/.env`` (``tb_common.rc1_refusals.host_env``, the
stricter of the box's and the caller's ``TB_ENV``). A checkout has no ``deploy/.env`` until ``make up-test`` copies
``.env.example``, which names no ``TB_ENV``: from then on the checkout reads as a PRODUCTION box. Every key test
there met "rc1 holds no backup key ceremony ... on a PRODUCTION box". That happened on the bench host, whose unit
stage ran after a compose stage, and it does not happen in CI. Each such test now gives the code a deploy folder of
its own, with no ``.env`` (a checkout that is not a box, as in CI). Its ``TB_ENV`` is then the one the test sets.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def own_deploy(monkeypatch: pytest.MonkeyPatch, folder: Path, *, ceremony: bool = False) -> Path:
    """Point ``tools.keys``'s deploy folder at ``folder`` (made, 0755, no ``.env``). With ``ceremony``, also
    ``tools.backup_key_ceremony``'s and the one ``trialbox backup-keygen`` finds beside its own file."""
    from tools import keys

    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o755)
    monkeypatch.setattr(keys, "DEFAULT_DEPLOY", str(folder))
    if ceremony:
        from tools import backup_key_ceremony as bkc
        from tools.trialbox import __main__ as entry

        monkeypatch.setattr(bkc, "DEPLOY", folder)
        # the CLI's deploy folder is beside its release tools (as tests/unit/test_restore_drill.py points it)
        monkeypatch.setattr(entry, "__file__", str(folder.parent / "tools" / "trialbox" / "__main__.py"))
    return folder
