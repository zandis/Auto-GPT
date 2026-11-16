"""T-715f (D-799), its review (2): ``tools.signed_api`` mints assertions with the process's actor key, so it refuses to
run on a box (PRODUCTION, VALIDATION, unset) and signs only in DEV or TEST, where the in-process walks seed."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", ""])
def test_signed_api_refuses_outside_dev_and_test(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    from tools import signed_api

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION (D-127)
    with pytest.raises(RuntimeError, match="DEV or TEST"):
        signed_api.signed(lambda *_a, **_k: None)


def test_signed_api_signs_a_refuse_route_and_drops_the_typed_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import actor_v3

    from tools import signed_api

    monkeypatch.setenv("TB_ENV", "TEST")
    seen: list[tuple[Any, ...]] = []

    def api(method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        seen.append((method, path, body, headers))
        return {}

    signed_api.signed(api)("POST", "/studies/GZQO/sync/redcap", {"by": "crc1"})
    signed_api.signed(api)("GET", "/studies/GZQO/forms")
    (_m1, _p1, b1, h1), (_m2, _p2, _b2, h2) = seen
    assert b1 == {} and h1 and actor_v3.HEADER in h1 and not h2
    claim = actor_v3.verify(h1[actor_v3.HEADER])
    assert claim.sub == "console:crc1" and claim.action == "study.setup" and claim.study == "GZQO"
