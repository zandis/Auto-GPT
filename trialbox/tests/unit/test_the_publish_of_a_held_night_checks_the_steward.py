"""NEW-SEC-4 (D-760): the publish of a held night checks the steward who accepted it (plan v7 wave 1; found in
T-723's review).

The steward's accept (``dataops.decide``) published a held night through the adapter's ``POST /publish``, which
took any caller's service token and no person: the console's token alone published a night the gate had held. Now
the console asks the orchestrator (``POST /dataops/publish``), which checks the signed person and the matrix's
right with its one dependency (``require_actor``), as for every changing route, and starts the adapter's publish
with its own token; the adapter takes ``POST /publish`` from the orchestrator only. The actor key stays with the
orchestrator alone (``service_auth``: no other service holds it). Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import actor_v3
from tb_common import service_auth as sa

from tests.actor3 import signed
from tools.trialbox.svc_secrets import IDENTITIES

BODY = {"snapshot": "2026-10-02", "source": "csv", "attempt": 1}
RUN = "0123456789abcdef"  # an adapter run id (os.urandom(8).hex())


def _token(name: str) -> str:
    return f"new-sec-4-token-of-{name}-0123456789abcdef"


def _registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {"schema": sa.REGISTRY_SCHEMA, "services": {n: sa.token_hash(_token(n)) for n in IDENTITIES}}
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv(sa.REGISTRY_ENV, str(path))


def _auth(name: str) -> dict[str, str]:
    return {sa.TOKEN_HEADER: _token(name)}


# ---------------------------------------------------------------------------------------------- the adapter
def test_the_adapter_takes_the_publish_from_the_orchestrator_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter import app as adapter_app

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    _registry(tmp_path, monkeypatch)
    started: list[Any] = []

    def config() -> Any:  # the handler was reached: its configuration is the first thing it asks for
        started.append(1)
        raise RuntimeError("the test's adapter has no configuration")

    monkeypatch.setattr(adapter_app, "build_config", config)
    http = TestClient(adapter_app.app, raise_server_exceptions=False)
    r = http.post("/publish", json=BODY, headers=_auth("console"))
    assert r.status_code == 403 and started == []  # the console's token alone publishes nothing
    r = http.post("/publish", json=BODY, headers=_auth("orchestrator"))
    assert r.status_code != 403 and started == [1]  # the orchestrator's passes the gate (the test's config fails)


# ---------------------------------------------------------------------------------------------- the orchestrator
class _Ops:
    """The ``DataOps`` store as the routes call it: records each decision (NEW-ARCH-3, D-761: the decision and the
    publish run at the orchestrator)."""

    def __init__(self, refuse: str = "", publish_raises: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.refuse, self.publish_raises = refuse, publish_raises

    def decide(self, audit: Any, bid: int, decision: str, *, by: str, at: str, reason: str, promote: Any) -> Any:
        from datacore.dataops import Batch, DataOpsError

        self.calls.append({"bid": bid, "decision": decision, "by": by, "reason": reason, "promote": promote})
        if self.refuse:
            raise DataOpsError(self.refuse, "refused")
        b = Batch(bid, "csv", "2026-10-02", 1, "HELD", 1, "", "", "", {})
        if decision == "accept" and promote is not None:
            promote(b)
        return Batch(bid, "csv", "2026-10-02", 1, "PUBLISHED" if decision == "accept" else "REJECTED", 2, "", "",
                     by, {})  # fmt: skip


class _Adapter:
    def __init__(self, status: int = 0) -> None:
        self.calls: list[Any] = []
        self.status = status

    def publish(self, body: dict[str, Any]) -> dict[str, Any]:
        from tb_common.http import ServiceError

        self.calls.append(body)
        if self.status:
            raise ServiceError("adapter", self.status, "refused")
        return {"run": RUN, "state": "done"}

    def publish_state(self, rid: str) -> dict[str, Any]:
        return {"run": rid, "state": "done"}


def _routes(ops: Any, adapter: Any) -> TestClient:
    from fastapi import FastAPI
    from orchestrator.dataops_api import router
    from tb_common.jobpoll import Poll

    app = FastAPI()
    app.include_router(router(lambda: ops, lambda: adapter, lambda: None,
                              Poll(interval=0.01, lost_after=5.0, sleep=lambda _s: None)))  # fmt: skip
    return TestClient(app, raise_server_exceptions=False)


DECIDE = {"decision": "accept", "reason": "checked"}
PATH = "/dataops/batches/7/decide"


def test_the_orchestrator_decides_and_publishes_only_for_the_steward_who_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TB_ENV", "TEST")  # a test box: the claim is still checked
    ops, adapter = _Ops(), _Adapter()
    client = _routes(ops, adapter)
    assert client.post(PATH, json=DECIDE).status_code == 403  # nobody
    coordinator = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:crc", role="coordinator")
    assert client.post(PATH, json=DECIDE, headers=coordinator).status_code == 403  # a role without the right
    other = signed("dataops.decide", "", "POST", PATH, {**DECIDE, "reason": "x"}, sub="console:stew", role="steward")
    assert client.post(PATH, json=DECIDE, headers=other).status_code == 403  # a claim for another body
    assert ops.calls == [] and adapter.calls == []
    steward = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:stew", role="steward")
    r = client.post(PATH, json=DECIDE, headers=steward)
    assert r.status_code == 200 and r.json()["state"] == "PUBLISHED"
    assert ops.calls[0]["by"] == "console:stew" and adapter.calls == [BODY]  # the publish ran here
    assert client.get("/dataops/can-publish").json() == {"publish": True}


@pytest.mark.parametrize(("status", "served", "started"), [(404, True, False), (409, False, True), (500, False, False)])
def test_a_publish_that_did_not_end_done_answers_its_marks(monkeypatch: pytest.MonkeyPatch, status: int, served: bool,
                                                           started: bool) -> None:  # fmt: skip
    monkeypatch.setenv("TB_ENV", "TEST")
    client = _routes(_Ops(), _Adapter(status))
    steward = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:stew", role="steward")
    r = client.post(PATH, json=DECIDE, headers=steward)
    assert r.status_code == 502
    assert r.json()["detail"] == {"why": "promote", "nothing_served": served, "not_started": started}


def test_an_accept_whose_publish_runs_is_answered_publishing_and_ends_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision's answer does not wait for the publish (never timed, D-472): once the accept is recorded and
    the adapter's publish runs, 202 and ``publishing``; the publish is followed to its end at the orchestrator."""
    import threading

    monkeypatch.setenv("TB_ENV", "TEST")
    release = threading.Event()
    ended: list[str] = []

    class Slow(_Adapter):
        def publish(self, body: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(body)
            return {"run": RUN, "state": "running"}

        def publish_state(self, rid: str) -> dict[str, Any]:
            release.wait()
            ended.append(rid)
            return {"run": rid, "state": "done"}

    ops = _Ops()

    class Store(_Ops):
        def batch(self, bid: int) -> Any:
            from datacore.dataops import Batch

            return Batch(bid, "csv", "2026-10-02", 1, "HELD", 1, "", "", "", {"step": "accept:publishing"})

        def decide(self, *a: Any, **k: Any) -> Any:
            return ops.decide(*a, **k)

    client = _routes(Store(), Slow())
    steward = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:stew", role="steward")
    r = client.post(PATH, json=DECIDE, headers=steward)
    assert r.status_code == 202 and r.json()["publishing"] is True and r.json()["detail"]["step"] == "accept:publishing"
    assert ended == []  # answered before the publish ended
    release.set()
    for _ in range(500):
        if ended:
            break
        threading.Event().wait(0.01)
    assert ended == [RUN] and ops.calls[0]["by"] == "console:stew"


def test_a_refusal_of_the_store_and_a_box_that_cannot_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "TEST")
    steward = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:stew", role="steward")
    r = _routes(_Ops(refuse="not_held"), _Adapter()).post(PATH, json=DECIDE, headers=steward)
    assert r.status_code == 409 and r.json()["detail"]["why"] == "not_held"
    client = _routes(_Ops(), None)
    steward = signed("dataops.decide", "", "POST", PATH, DECIDE, sub="console:stew", role="steward")
    r = client.post(PATH, json=DECIDE, headers=steward)
    assert r.status_code == 409 and r.json()["detail"] == {"why": "promote"}
    assert client.get("/dataops/can-publish").json() == {"publish": False}


# ---------------------------------------------------------------------------------------------- the console
def test_the_console_signs_the_decision_as_the_steward_and_posts_it_once() -> None:
    from console.dataops_page import DecisionRefused, OrchOps, PromoteFailed
    from tb_common.http import ServiceError

    seen: list[tuple[str, Any, dict[str, str]]] = []

    class Answer:
        def __init__(self, status: int, detail: Any = None) -> None:
            self.status, self.detail = status, detail

    class Once:
        def __init__(self, answer: Answer) -> None:
            self.answer = answer

        def post_raw(self, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
            seen.append((path, body, dict(headers or {})))
            if self.answer.status >= 400:
                raise ServiceError("orchestrator", self.answer.status, json.dumps({"detail": self.answer.detail}))

            class R:
                @staticmethod
                def json() -> dict[str, Any]:
                    return {
                        "id": 7,
                        "source": "csv",
                        "snapshot": "2026-10-02",
                        "attempt": 1,
                        "state": "PUBLISHED",
                        "seq": 2,
                        "started_at": "",
                        "changed_at": "",
                        "changed_by": "console:stew",
                        "detail": {},
                    }

            return R()

    class NeverUsed:
        def post_raw(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("the decision is posted with the client that does not retry")

    def sign(method: str, path: str, body: Any) -> dict[str, str]:
        return signed("dataops.decide", "", method, path, body, sub="console:stew", role="steward")

    def ops(answer: Answer) -> OrchOps:
        return OrchOps(type("Bk", (), {"orch": NeverUsed(), "orch_once": Once(answer)})())

    assert ops(Answer(200)).decide(7, "accept", "checked", sign).row.state == "PUBLISHED"
    path, body, headers = seen[0]
    claim = actor_v3.verify(headers[actor_v3.HEADER])
    assert path == PATH and body == DECIDE and claim.sub == "console:stew" and claim.body == actor_v3.body_hash(DECIDE)
    with pytest.raises(DecisionRefused) as refused:
        ops(Answer(409, {"why": "not_held"})).decide(7, "accept", "checked", sign)
    assert refused.value.why == "not_held"
    with pytest.raises(PromoteFailed) as failed:
        ops(Answer(502, {"why": "promote", "nothing_served": True, "not_started": False})).decide(
            7, "accept", "c", sign
        )
    assert failed.value.nothing_served and not failed.value.not_started
    for status in (401, 403, 422):
        with pytest.raises(PromoteFailed) as before:
            ops(Answer(status, {})).decide(7, "accept", "checked", sign)
        assert before.value.not_started, status


def test_the_backends_publish_client_never_retries() -> None:
    import inspect

    from console import backend

    src = inspect.getsource(backend)
    line = next(x for x in src.splitlines() if "self.orch_once = ServiceClient(" in x)
    assert "retries=0" in line and "idempotent=False" in line


def test_an_old_token_kept_for_a_rotation_does_not_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The review of D-760 (F3): with a token registry the old shared token (kept as ``legacy`` for a rotation) is
    refused at the publish; with no registry it is the box's only token and passes."""
    from adapter import app as adapter_app

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    old = "new-sec-4-the-old-shared-token-0123456789"
    doc = {"schema": sa.REGISTRY_SCHEMA, "services": {n: sa.token_hash(_token(n)) for n in IDENTITIES},
           "legacy": sa.token_hash(old)}  # fmt: skip
    (tmp_path / "tokens.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv(sa.REGISTRY_ENV, str(tmp_path / "tokens.json"))
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    http = TestClient(adapter_app.app, raise_server_exceptions=False)
    assert http.post("/publish", json=BODY, headers={sa.TOKEN_HEADER: old}).status_code == 403
