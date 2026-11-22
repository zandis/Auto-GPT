import importlib

import pytest


def test_backup_cli_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure that the backup CLI modules can be imported without requiring the
    host to set PYTHONPATH manually. The import should succeed even when
    only the repository root is on sys.path.
    """
    # Import the top‑level tools.trialbox package
    trialbox_pkg = importlib.import_module("tools.trialbox")
    assert trialbox_pkg is not None

    # Import a backup‑related submodule that depends on tb_common
    backup_mod = importlib.import_module("tools.trialbox.backup_keygen")
    assert backup_mod is not None
