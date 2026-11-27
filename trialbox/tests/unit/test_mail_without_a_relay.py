"""E2E P-10: a box installed with the four questions has no mail relay (``SMTP_HOST`` empty); the configuration then
falls back to ``localhost``, so every notice was tried six times against a refused connection and deferred (42
``mail.deferred``), and the mailbox was polled every minute against no server (58 warnings). With no relay given
nothing can be sent, in any environment: the mail waits, the try not counted, under the line that names the page
"Information still needed" (the stand-in of ``mail_relay``), and goes once IT gives the relay. Synthetic addresses."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from mail_gateway import app as mail_app
from mail_gateway import tls as mail_tls
from mail_gateway.gateway import MAX_ATTEMPTS, NO_RELAY
from tb_common.config import Env

import tests.unit.test_mail_resolve as _mr
from tools.box import needs_apply


def test_no_relay_given_means_no_send_is_tried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "VALIDATION")  # the rehearsal box of the run: the U-5 gate lets it through
    mta = _mr.MTA()
    gw = _mr._gw(tmp_path, mta)
    gw.relay = False
    out = gw.deliver(_mr._req("k-norelay"))
    for _ in range(MAX_ATTEMPTS + 2):  # the dispatcher's passes while IT has not given the relay
        gw.drain(force=True)
    row = _mr._row(gw, "k-norelay")
    assert out.state == "queued" and row.state == "queued" and row.attempts == 0 and mta.sent == []
    assert "mail relay" in (row.last_error or "") and "Information still needed" in (row.last_error or "")
    gw.relay, mta.cause = True, None  # IT gives the relay
    gw.drain(force=True)
    assert _mr._row(gw, "k-norelay").state == "sent" and len(mta.sent) == 1


@pytest.mark.parametrize(("smtp", "relay"), [("", False), ("  ", False), ("relay.hospa.test", True)])
def test_the_gateway_knows_whether_a_relay_was_given(monkeypatch: pytest.MonkeyPatch, smtp: str, relay: bool) -> None:
    built: dict[str, Any] = {}
    env = Env(audit_dir="/nonexistent")  # SMTP_HOST unset reads as localhost here
    monkeypatch.setattr(mail_app, "_gw", None)
    monkeypatch.setattr(mail_app, "get_config", lambda: SimpleNamespace(env=env))
    monkeypatch.setattr(mail_app, "open_audit", lambda *a: None)
    monkeypatch.setattr(mail_app, "from_config", lambda: None)
    monkeypatch.setattr(mail_app, "MailDB", lambda: None)
    monkeypatch.setattr(mail_app, "Gateway", lambda **kw: built.update(kw) or SimpleNamespace(**kw))
    monkeypatch.setattr(mail_tls, "audit_modes", lambda *a, **k: None)
    monkeypatch.setenv("SMTP_HOST", smtp)
    mail_app.gateway()
    assert built["relay"] is relay


@pytest.mark.parametrize(("imap", "polled"), [("", False), ("imap.hospa.test", True)])
def test_the_mailbox_is_polled_only_when_its_server_is_given(imap: str, polled: bool) -> None:
    assert mail_app.imap_given({"IMAP_HOST": imap}) is polled


def test_a_relay_in_the_dotenv_the_config_reads_counts_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Q-1: the gate reads the same source as ``Env`` (TB_DOTENV, then the environment), so a relay given
    only in the dotenv file is not held as missing, and an empty one in the environment wins as it does for Env."""
    built: dict[str, Any] = {}
    monkeypatch.setattr(mail_app, "_gw", None)
    monkeypatch.setattr(mail_app, "get_config", lambda: SimpleNamespace(env=Env(audit_dir="/nonexistent")))
    monkeypatch.setattr(mail_app, "open_audit", lambda *a: None)
    monkeypatch.setattr(mail_app, "from_config", lambda: None)
    monkeypatch.setattr(mail_app, "MailDB", lambda: None)
    monkeypatch.setattr(mail_app, "Gateway", lambda **kw: built.update(kw) or SimpleNamespace(**kw))
    monkeypatch.setattr(mail_tls, "audit_modes", lambda *a, **k: None)
    dotenv = tmp_path / "box.env"
    dotenv.write_text("SMTP_HOST=relay.hospa.test\n")
    monkeypatch.setenv("TB_DOTENV", str(dotenv))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mail_app.gateway()
    assert built["relay"] is True
    monkeypatch.setattr(mail_app, "_gw", None)
    monkeypatch.setenv("SMTP_HOST", "")
    mail_app.gateway()
    assert built["relay"] is False


def test_the_pages_relay_reaches_the_mail_gateway_by_a_new_start(tmp_path: Path) -> None:
    """Review M-1: the page's answer is SMTP_HOST in deploy/.env, which is the mail-gateway's env_file, and the
    runner recreates the services on it (compose up -d): a new process, a new gateway with the relay."""
    compose = yaml.safe_load((Path(__file__).parents[2] / "deploy" / "docker-compose.yml").read_text())
    assert ".env" in compose["services"]["mail-gateway"]["env_file"]
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n")
    ran: list[list[str]] = []
    needs_apply.run(
        deploy, {"item": "mail_relay", "smtp_host": "relay.hospa.test"}, restart=True, sh=lambda c, **k: ran.append(c)
    )
    assert "SMTP_HOST=relay.hospa.test" in (deploy / ".env").read_text().splitlines()
    assert ran == [["docker", "compose", "--project-directory", str(deploy), "up", "-d"]]


def test_after_the_new_start_the_held_mail_goes_on_the_next_ordinary_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review M-1, L-1: the box held a notice for want of a relay; the new start (relay given) wakes it, and the
    dispatcher's own pass (no ``force``) sends it, not an hour later."""
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    mta = _mr.MTA()
    before = _mr._gw(tmp_path, mta)
    before.relay = False
    before.deliver(_mr._req("k-held"))
    assert before.wake() == 0 and before.drain() == {} and _mr._row(before, "k-held").last_error == NO_RELAY
    mta.cause = None
    after = _mr._gw(tmp_path, mta)  # the process the restart starts: SMTP_HOST given, so ``relay`` is True
    assert after.relay is True
    assert after.wake() == 1
    after.drain()
    assert _mr._row(after, "k-held").state == "sent" and len(mta.sent) == 1


def test_the_start_wakes_the_held_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review M-1, L-1: the app's start calls the wake, so the restart of the page's runner releases the mail."""
    import asyncio

    woke: list[bool] = []
    stub = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(imap_user="")), wake=lambda: woke.append(True))
    monkeypatch.setattr(mail_app, "_gw", stub)
    monkeypatch.setenv("TB_MAIL_POLL_SECONDS", "0")

    async def start() -> None:
        async with mail_app.lifespan(mail_app.app):
            pass

    asyncio.run(start())
    assert woke == [True]
