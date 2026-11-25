"""The unit tier's own fixtures.

H-92 (D-1090): the backup schedule asks the host whether systemd is its init (``/run/systemd/system``,
``systemctl``) and whether a cron daemon runs (``/proc``). A unit test never gets the answer of the machine it runs
on (the bench is a systemd host with no cron daemon; CI is neither): here systemd is not the init and a cron daemon
runs, the host every unit test before H-92 assumed. A test of the schedule stands in its own host on top
(``tests/unit/test_backup_schedule_timer.py``)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_host_schedule(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    from tools.trialbox import backup_schedule as bs

    monkeypatch.setattr(bs, "SYSTEMD_RUN", Path(tmp_path_factory.getbasetemp()) / "no-systemd-here")
    monkeypatch.setattr(bs, "cron_daemon", lambda proc=None: True)


@pytest.fixture(autouse=True)
def _no_host_tpm_credential(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Review of #1478 (1478-1): rotate-kek and status look for the TPM credential at a fixed host place
    (/etc/credstore.encrypted); a unit test never gets the host's. A test of the credential stands in its own."""
    from tools import keys

    monkeypatch.setattr(
        keys, "CREDENTIAL_FILE", Path(tmp_path_factory.getbasetemp()) / "no-credstore-here" / "trialbox-kek"
    )
