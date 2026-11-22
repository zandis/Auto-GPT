"""Four PRODUCTION-only branches the box of ``tests/orch_box.py`` reached while it ran as PRODUCTION (R22-34: it runs
as VALIDATION now, because rc1 makes no list in PRODUCTION; the integrator's ruling, comment 7080612399). Each is
held here on a bare PRODUCTION box (``TB_ENV=PRODUCTION``, nothing else), proving what the branch does. No product
change. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common.audit import AuditLog


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")


def test_a_production_box_builds_no_model_client_without_the_gateway(
    production: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tb_common.llm.LlmClient.from_config`` (T-604): in PRODUCTION a prompt goes through tb-gateway or nowhere."""
    from tb_common.config import get_config
    from tb_common.llm import LlmClient, LlmError

    monkeypatch.delenv("TB_GATEWAY_URL", raising=False)
    get_config.cache_clear()
    try:
        with pytest.raises(LlmError, match="no TB_GATEWAY_URL in PRODUCTION"):
            LlmClient.from_config()
        monkeypatch.setenv("TB_ENV", "VALIDATION")  # the same box elsewhere builds its client
        assert isinstance(LlmClient.from_config(), LlmClient)
    finally:
        get_config.cache_clear()


def test_a_production_gateway_never_falls_back_to_another_prompt(
    production: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tb_common.llm.LlmClient.chat_json`` (D-359): an unqualified version refused by a PRODUCTION gateway is
    raised as it is; no fallback is taken or audited."""
    from tb_common.llm import LlmClient, LlmPromptUnqualified

    audit = AuditLog(tmp_path / "audit")
    c = LlmClient("http://stub/v1", "stub", audit=audit, gateway=SimpleNamespace(prompt_environment="PRODUCTION"))
    tried: list[str] = []

    def refused(prompt: Any, *_a: Any, **_k: Any) -> Any:
        tried.append(prompt.meta.id)
        raise LlmPromptUnqualified("refused (prompt_unqualified): no qualification record")

    monkeypatch.setattr(c, "_chat_json", refused)
    with pytest.raises(LlmPromptUnqualified):
        c.chat_json("judge", {})
    assert len(tried) == 1  # asked once, never again with another version
    written = "".join(f.read_text(encoding="utf-8") for f in (tmp_path / "audit").glob("*.jsonl"))
    assert "llm.prompt_fallback" not in written


def test_a_production_box_serves_only_a_qualified_prompt(production: None) -> None:
    """``tb_llm.prompt_registry.PromptRegistry.served`` (D-359): with no environment named, this box's PRODUCTION; the
    version served is one whose qualification holds, never a newer one that waits for its record."""
    from tb_llm.prompt_registry import default_registry

    reg = default_registry()
    for pid in ("judge", "ir_extract"):
        served = reg.served(pid)
        assert reg.qualifies(served, "PRODUCTION"), pid
        assert served == reg.served(pid, "PRODUCTION")
        assert served.version <= reg.served(pid, "DEV").version, pid


def test_a_production_console_sets_secure_cookies_and_refuses_them_off(production: None) -> None:
    """``console.identity.secure_cookie_default`` (D-192, review M1): on by default in PRODUCTION, an explicit off
    refused there."""
    import os

    from console.identity import IdentityConfigError, secure_cookie_default
    from tb_common.config import environment_name

    env = environment_name(os.environ)
    assert env == "PRODUCTION" and secure_cookie_default({}, env) is True
    with pytest.raises(IdentityConfigError, match="refused in PRODUCTION"):
        secure_cookie_default({"TB_CONSOLE_SECURE_COOKIE": "0"}, env)
    assert secure_cookie_default({}, "VALIDATION") is False
