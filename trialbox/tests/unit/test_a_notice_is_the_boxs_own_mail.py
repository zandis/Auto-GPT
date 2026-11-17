"""T-715 refuse mode for the notices (D-1150): a notice is the box's own mail, sent by one of four service principals.

``POST /notices`` takes a verified v3 assertion of a service principal, each acting under a row it already holds
(``route_actors.yaml``), and each may send only its own kinds (``orchestrator.app.NOTICE_KINDS``):

* ``service:console-notify`` (``phi.view``): N1, N2 and HEALTH;
* ``service:console-sae-sync`` (``sae.view``): N2;
* ``service:console-accounts`` (``account.reset``): ACCOUNT;
* ``service:console-breakglass`` (``breakglass.open``): BG.

A kind outside a principal's set is refused, as is a person's assertion (an administrator holds ``account.reset``,
yet a notice is never a person's), the older v2 header, and no assertion at all. A real orchestrator in PRODUCTION
with per-service tokens. Synthetic addresses only."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import actor_v3
from tb_common import service_auth as sa

from tests.actor3 import signed
from tests.service_tokens import token_of
from tests.unit.test_admin_retry_scheduled import client, orch  # noqa: F401 - the fixtures are used by name
from tests.unit.test_an_account_notice_leaves_the_box import Mail

PRINCIPALS = {
    "service:console-notify": ("phi.view", {"N1", "N2", "HEALTH"}),
    "service:console-sae-sync": ("sae.view", {"N2"}),
    "service:console-accounts": ("account.reset", {"ACCOUNT"}),
    "service:console-breakglass": ("breakglass.open", {"BG"}),
}
KINDS = ("N1", "N2", "HEALTH", "ACCOUNT", "BG")


def _body(kind: str) -> dict[str, Any]:
    return {"kind": kind, "to": ["office@hospa.test"], "subject": f"TrialBox {kind}", "body_md": "synthetic"}


def _post(client: TestClient, body: dict[str, Any], header: dict[str, str]) -> Any:  # noqa: F811
    return client.post("/notices", json=body, headers={sa.TOKEN_HEADER: token_of("console"), **header})


def _as(principal: str, body: dict[str, Any]) -> dict[str, str]:
    action = PRINCIPALS[principal][0]
    return signed(action, "", "POST", "/notices", body, sub=principal, role=actor_v3.SERVICE_ROLE)


@pytest.mark.parametrize("principal", sorted(PRINCIPALS))
def test_each_principal_sends_its_own_kinds_and_no_other(client: TestClient, orch: Any, principal: str) -> None:  # noqa: F811
    mail = Mail()
    orch.services.mail = mail
    own = PRINCIPALS[principal][1]
    for kind in KINDS:
        body = _body(kind)
        r = _post(client, body, _as(principal, body))
        if kind in own:
            assert r.status_code == 200, (principal, kind, r.text)
        else:
            assert r.status_code == 403, (principal, kind, r.status_code)  # a kind outside its set
    assert sorted(m.subject for m in mail.sent) == sorted(f"TrialBox {k}" for k in own)


def test_a_persons_assertion_is_refused_even_with_the_row(client: TestClient, orch: Any) -> None:  # noqa: F811
    mail = Mail()
    orch.services.mail = mail
    body = _body("ACCOUNT")
    header = signed("account.reset", "", "POST", "/notices", body, sub="console:admin", role="admin")
    assert _post(client, body, header).status_code == 403
    assert mail.sent == []


def test_a_principal_of_another_route_is_refused(client: TestClient, orch: Any) -> None:  # noqa: F811
    body = _body("N1")
    header = signed("optout.keep", "", "POST", "/notices", body, sub="service:console-optout-check",
                    role=actor_v3.SERVICE_ROLE)  # fmt: skip
    assert _post(client, body, header).status_code == 403


def test_the_older_header_and_no_assertion_are_refused(client: TestClient, orch: Any) -> None:  # noqa: F811
    body = _body("N1")
    assert _post(client, body, sa.actor_header("console:notify")).status_code == 403
    assert _post(client, body, {}).status_code == 403


def test_the_console_signs_each_sender_as_its_own_principal() -> None:
    from console import actor

    assert {sub: action for sub, (action, _k) in PRINCIPALS.items()} == actor.NOTICE_ACTION
