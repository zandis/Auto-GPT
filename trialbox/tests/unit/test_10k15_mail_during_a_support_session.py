"""Card 10K-15 (D-1364), the review of aeb978e6 H5: background mail read no support-session switch, so a morning
notice (pseudonyms, visit times) or a finished job's mail could go out while the hospital's screen was shared. Now
the mail gateway asks the orchestrator before every send (``GET /support-session``, a yes or no read from the
console's own store); while a session runs every mail is held (queued, the try not counted, ``mail.deferred`` with
the reason) and sent once after the end, but those whose key the orchestrator marks ``SUPPORT_MAIL_PREFIX``: the
serious adverse event copy to the office (safety mail is never delayed), the health mail and the account notice. A
state that cannot be read holds the mail; nothing is dropped. Synthetic data only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mail_gateway.gateway import SUPPORT_HELD
from tb_common import service_auth as sa
from tb_common.authz import SUPPORT_MAIL_PREFIX
from tb_contracts import SendRequest

from tests.service_tokens import token_of
from tests.unit.test_a_notice_is_the_boxs_own_mail import _as, _body, _post
from tests.unit.test_admin_retry_scheduled import client, orch  # noqa: F401 - the fixtures are used by name
from tests.unit.test_an_account_notice_leaves_the_box import Mail
from tests.unit.test_the_outbox_asks_before_it_sends import Register, _gw, _phi, _state

PID = "c0ffee11" * 4


def _notice(key: str) -> SendRequest:
    return SendRequest.model_validate({"job_id": None, "to": ["pi@hospa.test"], "subject": "TrialBox N1",
                                       "body_md": f"Today: {PID[:8]} at 09:30", "tag": "aggregate",
                                       "idempotency_key": key})  # fmt: skip


def _events(tmp_path: Path, name: str) -> list[str]:
    return [line for f in sorted((tmp_path / "audit").glob("*")) for line in f.read_text().splitlines()
            if f'"{name}"' in line]  # fmt: skip


def test_mail_is_held_during_a_session_and_sent_once_after_it(db_url: str, tmp_path: Path) -> None:
    from tests.unit.test_mail_resolve import MTA

    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta, Register())
    on = {"v": True}
    gw.support_session = lambda: on["v"]
    gw.send(_notice("tbmail-n1"))  # the Monday N1 timer during a session
    gw.send(_phi("tbmail-case"))  # a CASE job finishing during it
    gw.send(_notice(SUPPORT_MAIL_PREFIX + "sae"))  # the serious AE copy to the office: never delayed
    assert [to for to, _ in mta.sent] == [["pi@hospa.test"]]  # only the safety mail left
    for key in ("tbmail-n1", "tbmail-case"):
        state, why = _state(gw, key)
        assert state == "queued" and why == SUPPORT_HELD, key
    held = _events(tmp_path, "mail.deferred")
    assert len(held) == 2 and all("support session" in line for line in held) and PID not in "".join(held)
    assert gw.drain(force=True) == {"queued": 2}  # still on: held again, not counted as a try
    assert gw.db.get("tbmail-n1").attempts == 0  # type: ignore[union-attr]
    on["v"] = False  # the session ended
    assert gw.drain(force=True) == {"sent": 2}
    assert _state(gw, "tbmail-n1")[0] == "sent" and _state(gw, "tbmail-case")[0] == "sent"
    after = len(mta.sent)  # the notice, the patient file and its password mail
    assert after >= 3
    assert gw.drain(force=True) == {}  # once
    assert len(mta.sent) == after


def test_a_state_that_cannot_be_read_holds_the_mail(db_url: str, tmp_path: Path) -> None:
    from tests.unit.test_mail_resolve import MTA

    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta, Register())

    def down() -> bool:
        raise ConnectionError("the orchestrator did not answer")

    gw.support_session = down
    gw.send(_notice("tbmail-n2"))
    state, why = _state(gw, "tbmail-n2")
    assert state == "queued" and why.startswith(SUPPORT_HELD) and mta.sent == []


def test_the_orchestrator_marks_only_the_safety_health_and_account_notices(client: TestClient, orch: Any) -> None:  # noqa: F811
    mail = Mail()
    orch.services.mail = mail
    sent = [("service:console-notify", "N1"), ("service:console-notify", "N2"), ("service:console-notify", "HEALTH"),
            ("service:console-sae-sync", "N2"), ("service:console-accounts", "ACCOUNT")]  # fmt: skip
    for principal, kind in sent:
        body = {**_body(kind), "subject": f"TrialBox {kind} {principal}"}
        assert _post(client, body, _as(principal, body)).status_code == 200
    always = {m.subject for m in mail.sent if (m.idempotency_key or "").startswith(SUPPORT_MAIL_PREFIX)}
    assert always == {"TrialBox HEALTH service:console-notify", "TrialBox N2 service:console-sae-sync",
                      "TrialBox ACCOUNT service:console-accounts"}  # fmt: skip


def test_the_orchestrator_reads_the_switch_for_the_mail_gateway(client: TestClient, orch: Any) -> None:  # noqa: F811
    from console.breakglass_store import SupportSessionStore

    gw = {sa.TOKEN_HEADER: token_of("mail-gateway")}
    assert client.get("/support-session", headers=gw).json() == {"on": False}
    st = SupportSessionStore()
    try:
        st.start("admin", "", datetime.now(UTC), lambda s: None)
        assert client.get("/support-session", headers=gw).json() == {"on": True}
        assert client.get("/support-session", headers={sa.TOKEN_HEADER: token_of("lake")}).status_code == 403
    finally:
        st.close()


@pytest.mark.parametrize("module", ["mail_gateway.app"])
def test_the_gateway_service_asks_the_orchestrator(module: str) -> None:
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(module))
    assert "support_session=http_support_session(" in src
