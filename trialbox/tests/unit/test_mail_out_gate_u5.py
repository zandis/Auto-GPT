"""U-5 (D-1280): the mail-out gate. On a PRODUCTION box no mail leaves while the hospital's name or the mail relay is
still needed (missing, or a stand-in marked in the read-only list ``site_needs.MOUNTED``): the mail waits in the
outbox, the try not counted, with the line that names the page "Information still needed", and goes once the item is
given. A PoC box sends with the stand-ins. Synthetic addresses only."""

from __future__ import annotations

from pathlib import Path

import pytest
from mail_gateway.gateway import Gateway
from tb_common import site_needs

import tests.unit.test_mail_resolve as _mr

RELAY = "relay.hospa.test"


def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str, stand_ins: list[str]) -> tuple[_mr.MTA, Gateway]:
    monkeypatch.setenv("TB_ENV", env)
    site_needs.write_stand_ins(tmp_path / "deploy", stand_ins)
    monkeypatch.setattr(site_needs, "MOUNTED", (tmp_path / "deploy" / site_needs.STAND_INS).parent)
    mta = _mr.MTA()
    mta.cause = None
    return mta, _mr._gw(tmp_path, mta)


def test_production_holds_the_mail_while_the_relay_is_still_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mta, gw = _box(tmp_path, monkeypatch, "PRODUCTION", [])
    out = gw.deliver(_mr._req("k-relay"))
    row = _mr._row(gw, "k-relay")
    assert out.state == "queued" and mta.sent == []
    assert row.attempts == 0 and "Information still needed" in (row.last_error or "")
    assert [e["detail"]["key"] for e in _mr._events(tmp_path, "mail.deferred")] == ["k-relay"]


def test_production_holds_the_mail_while_the_hospitals_name_is_a_stand_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_HOST", RELAY)
    mta, gw = _box(tmp_path, monkeypatch, "PRODUCTION", ["site_name"])
    assert gw.deliver(_mr._req("k-name")).state == "queued" and mta.sent == []


def test_production_sends_when_both_are_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", RELAY)
    mta, gw = _box(tmp_path, monkeypatch, "PRODUCTION", [])
    assert gw.deliver(_mr._req("k-given")).state == "sent" and len(mta.sent) == 1


def test_the_held_mail_goes_once_the_relay_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mta, gw = _box(tmp_path, monkeypatch, "PRODUCTION", [])
    gw.deliver(_mr._req("k-later"))
    monkeypatch.setenv("SMTP_HOST", RELAY)
    gw.drain(force=True)
    assert _mr._row(gw, "k-later").state == "sent" and len(mta.sent) == 1


@pytest.mark.parametrize("env", ["DEV", "TEST", "VALIDATION"])
def test_a_poc_box_sends_with_the_stand_ins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    mta, gw = _box(tmp_path, monkeypatch, env, ["site_name"])
    assert gw.deliver(_mr._req(f"k-{env}")).state == "sent" and len(mta.sent) == 1
