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
from mail_gateway import app as mail_app
from mail_gateway.gateway import MAX_ATTEMPTS
from tb_common.config import Env

import tests.unit.test_mail_resolve as _mr


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
    monkeypatch.setattr(mail_app.tls, "audit_modes", lambda *a, **k: None)
    monkeypatch.setenv("SMTP_HOST", smtp)
    mail_app.gateway()
    assert built["relay"] is relay


@pytest.mark.parametrize(("imap", "polled"), [("", False), ("imap.hospa.test", True)])
def test_the_mailbox_is_polled_only_when_its_server_is_given(imap: str, polled: bool) -> None:
    assert mail_app.imap_given({"IMAP_HOST": imap}) is polled
