"""NOTICE-ACCOUNT (D-879): an account notice leaves the box.

D-719 tells an account's holder and its PIs when someone else set a factor of the account (a password reset, a new
authenticator). The console sends it through the orchestrator's ``POST /notices`` with the kind ``ACCOUNT``; the
orchestrator accepted only N1, N2, BG and HEALTH, so every account notice was refused (422) and the console's best
effort recorded it as not sent. Like every notice, it is an aggregate mail to hospital addresses only.

A real orchestrator in PRODUCTION with per-service tokens, the console's signed actor header. Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import service_auth as sa

from tests.service_tokens import token_of
from tests.unit.test_admin_retry_scheduled import client, orch  # noqa: F401 - the fixtures are used by name


class Mail:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    def send(self, req: Any) -> Any:
        from tb_contracts import SendResult

        self.sent.append(req)
        return SendResult(message_id="<acct@t>", sent_to=req.to, encrypted=False)


def _post(client: TestClient, body: dict[str, Any]) -> Any:  # noqa: F811
    headers = {sa.TOKEN_HEADER: token_of("console"), **sa.actor_header("console:admin")}
    return client.post("/notices", json=body, headers=headers)


@pytest.mark.parametrize("to", [["holder@hospa.test", "pi@hospa.test"]])
def test_an_account_notice_reaches_the_mail_gateway(client: TestClient, orch: Any, to: list[str]) -> None:  # noqa: F811
    mail = Mail()
    orch.services.mail = mail
    body = {"kind": "ACCOUNT", "to": to, "subject": "TrialBox account crc1: a new password",
            "body_md": "TrialBox account crc1: a new password, by admin.\n\nIf this was not asked for, tell IT."}  # fmt: skip
    r = _post(client, body)
    assert r.status_code == 200, r.text
    assert r.json()["message_id"] == "<acct@t>"
    (req,) = mail.sent
    assert req.to == to and req.tag == "aggregate"  # like every notice: aggregate, hospital addresses only


def test_an_account_notice_to_an_outside_address_is_refused(client: TestClient, orch: Any) -> None:  # noqa: F811
    mail = Mail()
    orch.services.mail = mail
    body = {"kind": "ACCOUNT", "to": ["someone@example.com"], "subject": "s", "body_md": "b"}
    assert _post(client, body).status_code == 400 and mail.sent == []


def test_an_unknown_kind_is_still_refused(client: TestClient, orch: Any) -> None:  # noqa: F811
    body = {"kind": "OTHER", "to": ["holder@hospa.test"], "subject": "s", "body_md": "b"}
    assert _post(client, body).status_code == 422
