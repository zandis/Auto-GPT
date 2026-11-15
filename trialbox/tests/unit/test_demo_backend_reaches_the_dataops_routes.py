"""NEW-ARCH-3 (D-761), train 16's journeys: the in-process demo backend (``tools/role_demo.InprocBackend``) gives the
console's data-operations page the orchestrator the way the real backend does (``backend.orch`` and the
never-retrying ``backend.orch_once``), over the box's own orchestrator routes. A refusal of the orchestrator reaches
the page as the real client raises it (``ServiceError`` with the status), so the page reads it the same way."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tb_common.http import ServiceError


class _Client:
    def __init__(self, status: int = 200, answer: Any = None) -> None:
        self.status, self.answer = status, answer
        self.seen: list[tuple[str, str, Any, dict[str, str]]] = []

    def _r(self) -> Any:
        status, answer = self.status, self.answer

        class R:
            status_code = status
            text = "refused" if status >= 400 else ""

            @staticmethod
            def json() -> Any:
                return answer

        return R()

    def get(self, path: str, headers: dict[str, str] | None = None) -> Any:
        self.seen.append(("GET", path, None, dict(headers or {})))
        return self._r()

    def post(self, path: str, json: Any = None, headers: dict[str, str] | None = None) -> Any:
        self.seen.append(("POST", path, json, dict(headers or {})))
        return self._r()


def _backend(client: _Client) -> Any:
    from tools.role_demo import InprocBackend

    box = type("Box", (), {"orch": type("O", (), {"cfg": None})()})()
    return InprocBackend(box, client, Path("."))


def test_the_demo_backend_reads_the_dataops_routes_through_its_orchestrator() -> None:
    client = _Client(answer={"LANDED": 1})
    bk = _backend(client)
    assert bk.orch.get_json("/dataops/counts") == {"LANDED": 1}
    assert client.seen[0][:2] == ("GET", "/dataops/counts")


def test_the_decision_is_posted_signed_through_the_client_that_does_not_retry() -> None:
    client = _Client(answer={"id": 7})
    bk = _backend(client)
    r = bk.orch_once.post_raw("/dataops/batches/7/decide", {"decision": "reject", "reason": "r"}, {"h": "v"})
    assert r.json() == {"id": 7}
    assert client.seen == [("POST", "/dataops/batches/7/decide", {"decision": "reject", "reason": "r"}, {"h": "v"})]


@pytest.mark.parametrize("status", [403, 404, 409, 502])
def test_a_refusal_reaches_the_page_as_the_real_client_raises_it(status: int) -> None:
    bk = _backend(_Client(status=status))
    with pytest.raises(ServiceError) as got:
        bk.orch.get_json("/dataops/batches/7")
    assert got.value.status == status and got.value.service == "orchestrator"
    with pytest.raises(ServiceError):
        bk.orch_once.post_raw("/dataops/batches/7/decide", {"decision": "accept", "reason": ""})
