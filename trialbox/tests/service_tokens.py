"""Per-service tokens for a test box (D-138, D-464): a token registry naming every service, the console's own token in
``TB_SERVICE_TOKEN`` (so ``service_auth.actor_header`` signs as the console does) and the orchestrator's actor-key
file. Outside DEV and TEST the orchestrator admits only a caller it can name (T-713, D-464), so a PRODUCTION test of
an orchestrator route runs in this mode, as a real box does. Synthetic tokens only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tb_common import service_auth as sa

SERVICES = ("console", "mail-gateway", "operator", "adapter", "lake", "criteria-compiler", "doc-parser")


def token_of(service: str) -> str:
    return f"test-token-of-{service}-0123456789abcdef"


def per_service_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, me: str = "console") -> str:
    """Write the registry and the actor keys, make this process the service ``me``; return ``me``'s token."""
    reg = tmp_path / "tokens.json"
    reg.write_text(json.dumps({"schema": sa.REGISTRY_SCHEMA,
                               "services": {s: sa.token_hash(token_of(s)) for s in SERVICES}}),
                   encoding="utf-8")  # fmt: skip
    keys = tmp_path / "actor-keys"
    keys.write_text(sa.actor_key(token_of("console")).hex() + "\n", encoding="utf-8")
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv(sa.REGISTRY_ENV, str(reg))
    monkeypatch.setenv(sa.ACTOR_KEYS_ENV, str(keys))
    monkeypatch.setenv("TB_SERVICE_TOKEN", token_of(me))
    return token_of(me)
