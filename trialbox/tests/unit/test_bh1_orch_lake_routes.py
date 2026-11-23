"""Bug hunt BH1 (area 2): the lake service has no route gate, so every service the token registry lets call the lake
(``service_auth.CALLERS["lake"]``: orchestrator, criteria-compiler, adapter) reaches every lake route.

The criteria compiler reads the lake (``LakeHttp`` in ``criteria_compiler/app.py``); it has no part in a night's
publish, which D-760 made the steward's accept (checked by the orchestrator, started at the adapter with the
orchestrator's token only). The lake's ``POST /promote`` is that publish's last step (D-489), and ``DELETE
/holds/{holder}`` releases a running job's pinned snapshot (D-403). Synthetic tokens and a fake lake only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import service_auth as sa

from tests.service_tokens import per_service_tokens, token_of


class _FakeLake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def promote_built(self, snap: str, generation: str | None) -> bool:
        self.calls.append(("promote", snap))
        return True

    def current(self) -> str:
        return "2026-01-05"

    def release(self, holder: str) -> bool:
        self.calls.append(("release", holder))
        return True


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakeLake]:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    per_service_tokens(tmp_path, monkeypatch, me="lake")
    from lake import app as lake_app

    fake = _FakeLake()
    monkeypatch.setattr(lake_app, "lake", lambda: fake)
    return TestClient(lake_app.app), fake


def test_the_criteria_compilers_token_cannot_promote_a_built_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POST /promote`` on the lake (``services/lake/app.py``), called with the criteria compiler's token."""
    c, fake = _client(tmp_path, monkeypatch)
    # control: the registry is live (a token of no service is refused before any route)
    assert c.post("/promote", json={"snapshot": "2026-01-05"},
                  headers={sa.TOKEN_HEADER: "not-a-token-of-this-box-0123456789"}).status_code == 403  # fmt: skip
    r = c.post("/promote", json={"snapshot": "2026-01-05"}, headers={sa.TOKEN_HEADER: token_of("criteria-compiler")})
    assert (r.status_code, fake.calls) == (403, [])


def test_the_criteria_compilers_token_cannot_release_a_jobs_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``DELETE /holds/{holder}`` on the lake (``services/lake/app.py``), called with the criteria compiler's token."""
    c, fake = _client(tmp_path, monkeypatch)
    r = c.delete("/holds/job-0001", headers={sa.TOKEN_HEADER: token_of("criteria-compiler")})
    assert (r.status_code, fake.calls) == (403, [])
