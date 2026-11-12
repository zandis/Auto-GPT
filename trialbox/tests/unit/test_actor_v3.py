"""T-715 (D-483): the v3 actor assertion as a format: what is signed, what a change to any part does, one use."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from tb_common import actor_v3 as v3
from tb_common import service_auth as sa
from tb_common.authz import Standing

from tests.service_tokens import per_service_tokens

NOW = 1_800_000_000.0
BODY = {"to": "enrolled", "on_day": "2026-11-12"}


def _mint(**kw: Any) -> str:
    base: dict[str, Any] = {"sub": "console:crc", "role": "coordinator", "action": "study.setup", "method": "post",
                            "path": "/studies/GZQO/subjects/GZQO-0001/step", "body": BODY, "study": "gzqo",
                            "session": "abc123", "now": NOW}  # fmt: skip
    return v3.mint(**{**base, **kw})


@pytest.fixture
def keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    per_service_tokens(tmp_path, monkeypatch)  # this process signs as the console; the keys file verifies it


def test_the_claim_carries_the_person_the_right_and_the_request(keys: None) -> None:
    st = Standing(is_pi=True, tasks=frozenset({"screen", "enter_data"}), log_names_pi=True)
    grant = {"id": "bg-7", "kind": "patient", "pid": "a" * 32, "end": "2026-11-12T10:00:00+00:00"}
    tok = _mint(standing=st, grant=grant, reauth_at=int(NOW) - 30)
    c = v3.verify(tok, now=NOW, replay=sa.ReplayGuard())
    assert (c.sub, c.role, c.session, c.study, c.action) == (
        "console:crc",
        "coordinator",
        "abc123",
        "GZQO",
        "study.setup",
    )
    assert c.target == "POST /studies/GZQO/subjects/GZQO-0001/step" and c.body == v3.body_hash(BODY)
    assert c.standing() == st and c.tasks == ("enter_data", "screen")
    assert c.grant == grant and c.reauth_at == int(NOW) - 30
    assert c.verified and c.name == "console:crc" and not c.is_service
    assert c.exp == int(NOW) + sa.ACTOR_TTL and len(c.nonce) == 22
    assert v3.is_v3(tok) and not v3.is_v3("v2.1.s.n.mac") and not v3.is_v3(None)


def _retag(tok: str, **change: Any) -> str:
    """The same token with fields of its payload changed and the old MAC kept."""
    head, b64, mac = tok.split(".")
    doc = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
    doc.update(change)
    new = base64.urlsafe_b64encode(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{head}.{new}.{mac}"


@pytest.mark.parametrize("change", [
    {"sub": "console:dr_tanaka"}, {"role": "investigator"}, {"study": "OTHER"}, {"action": "sae.ack"},
    {"target": "POST /studies/GZQO/subjects/GZQO-0002/step"}, {"body": "0" * 64}, {"exp": int(NOW) + 100},
    {"standing": {"is_pi": True, "tasks": [], "log_names_pi": True, "monitor": False}},
    {"grant": {"id": "bg-1"}}, {"reauth_at": int(NOW)}, {"session": "other"}, {"nonce": "A" * 22},
], ids=lambda c: next(iter(c)))  # fmt: skip
def test_no_part_of_the_claim_can_be_changed(keys: None, change: dict[str, Any]) -> None:
    with pytest.raises(sa.ActorError, match="does not verify"):
        v3.verify(_retag(_mint(), **change), now=NOW, replay=sa.ReplayGuard())


def test_refused_without_a_key_expired_used_twice_or_not_v3(keys: None, monkeypatch: pytest.MonkeyPatch) -> None:
    guard = sa.ReplayGuard()
    tok = _mint()
    assert v3.verify(tok, now=NOW, replay=guard).sub == "console:crc"
    with pytest.raises(sa.ActorError, match="already used"):
        v3.verify(tok, now=NOW + 1, replay=guard)
    with pytest.raises(sa.ActorError, match="expired"):
        v3.verify(_mint(), now=NOW + sa.ACTOR_TTL + 1, replay=guard)
    with pytest.raises(sa.ActorError, match="expired"):
        v3.verify(_mint(now=NOW + 600), now=NOW, replay=guard)  # issued in the future
    for bad in (None, "", "v2.1.s.n.mac", "v3.only-two", "v3.!!!." + "0" * 64, "v3." + "A" * 9000 + ".x"):
        with pytest.raises(sa.ActorError):
            v3.verify(bad, now=NOW, replay=guard)
    # another service signs nothing the box accepts: the mail gateway holds its token and no signing key (D-485)
    monkeypatch.setenv("TB_SERVICE_TOKEN", "test-token-of-mail-gateway-0123456789abcdef")
    monkeypatch.delenv(sa.ACTOR_SIGN_KEY_ENV)
    assert _mint().endswith(".")  # no key, no MAC
    with pytest.raises(sa.ActorError, match="does not verify"):
        v3.verify(_mint(), now=NOW, replay=guard)
    monkeypatch.setenv(sa.ACTOR_KEYS_ENV, "/nonexistent/keys")  # a keys file that cannot be read: fail closed
    with pytest.raises(sa.ActorError, match="does not verify"):
        v3.verify(tok, now=NOW, replay=sa.ReplayGuard())


def test_a_retry_carries_a_new_assertion_of_the_same_claim(keys: None) -> None:
    guard = sa.ReplayGuard()
    first = _mint()
    again = sa.resign({v3.HEADER: first})[v3.HEADER]
    assert again != first
    a, b = v3.verify(first, now=NOW, replay=guard), v3.verify(again, replay=guard)
    assert (a.sub, a.role, a.study, a.action, a.target, a.body) == (b.sub, b.role, b.study, b.action, b.target, b.body)
    assert a.nonce != b.nonce


def test_the_minting_side_refuses_a_claim_that_is_not_one(keys: None) -> None:
    for bad in ({"sub": "dr_tanaka"}, {"sub": "console:"}, {"role": "Coordinator"}, {"role": "service"},
                {"sub": "service:console-notify"}, {"study": "GZQO,OTHER"}, {"study": "*"}, {"action": "anything"},
                {"grant": {"kind": "patient"}}):  # fmt: skip
        with pytest.raises(ValueError):
            _mint(**bad)
    svc = v3.verify(_mint(sub="service:console-notify", role="service"), now=NOW, replay=sa.ReplayGuard())
    assert svc.is_service and svc.role == v3.SERVICE_ROLE


def test_the_body_hash_is_of_the_value_not_of_the_bytes() -> None:
    same = (BODY, b'{"to": "enrolled", "on_day": "2026-11-12"}', b'{"on_day":"2026-11-12","to":"enrolled"}')
    assert len({v3.body_hash(x) for x in same}) == 1
    assert v3.body_hash({**BODY, "to": "withdrawn"}) != v3.body_hash(BODY)
    assert v3.body_hash({**BODY, "by": "dr_tanaka"}) != v3.body_hash(BODY)  # an added field is another body
    assert v3.body_hash(None) == v3.body_hash(b"") != v3.body_hash({})
    assert v3.body_hash(b"\x00not json") == v3.body_hash(b"\x00not json") != v3.body_hash(b"\x00not jsoN")
    assert v3.body_hash({"名": "日本語"}) == v3.body_hash('{"名": "日本語"}'.encode())


def test_a_box_without_any_token_checks_the_claim_but_no_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEV and TEST without a token, as v2: nothing is signed, and the claim is still read and still expires."""
    for name in ("TB_SERVICE_TOKEN", "TB_SERVICE_TOKEN_FILE", sa.REGISTRY_ENV, sa.ACTOR_KEYS_ENV):
        monkeypatch.delenv(name, raising=False)
    tok = _mint()
    assert tok.endswith(".")
    c = v3.verify(tok, now=NOW, replay=sa.ReplayGuard())
    assert c.sub == "console:crc" and not c.verified
    with pytest.raises(sa.ActorError, match="expired"):
        v3.verify(_mint(), now=NOW + 500, replay=sa.ReplayGuard())
