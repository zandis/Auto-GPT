"""E2E P-15: ``sudo trialbox mail status`` on the installed box crashed with ``ConfigError: settings file not found:
/etc/trialbox/settings.yaml`` (a traceback). The outbox is the mail-gateway's: on the host the same command now runs
in that container, as the module's docstring tells the operator to do by hand."""

from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from mail_gateway import app as mail_app
from tb_common.config import get_config

from tools.trialbox.__main__ import main as trialbox_main

pytestmark = pytest.mark.nodb


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A host with no settings file and a compose that records what it was asked to run."""
    log = tmp_path / "compose.log"
    fake = tmp_path / "compose"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\necho "0 queued, 0 uncertain, 0 failed"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("TB_SETTINGS", str(tmp_path / "etc" / "settings.yaml"))  # not there, as on the host
    monkeypatch.setenv("TB_COMPOSE", str(fake))
    monkeypatch.setattr(mail_app, "_gw", None)
    get_config.cache_clear()
    yield log
    get_config.cache_clear()


@pytest.mark.parametrize("argv", [["mail", "status"], ["mail", "status", "--json"]])
def test_mail_status_on_the_host_runs_in_the_mail_gateway(host: Path, argv: list[str]) -> None:
    assert trialbox_main(argv) == 0
    called = host.read_text().splitlines()
    assert called[:6] == ["exec", "-T", "mail-gateway", "python", "-m", "tools.trialbox"]
    assert called[6 : 6 + len(argv)] == argv
    assert called[-2] == "--by" and called[-1]  # the person on the host, not the container's user


def test_a_resolve_keeps_the_person_who_decides(host: Path) -> None:
    assert trialbox_main(["mail", "resolve", "tbmail-1", "--drop", "--by", "steward1"]) == 0
    called = host.read_text().splitlines()
    assert called[6:] == ["mail", "resolve", "tbmail-1", "--drop", "--by", "steward1"]
    assert json.dumps(called).count("--by") == 1
