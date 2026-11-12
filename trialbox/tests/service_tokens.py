"""Per-service tokens for a test box (D-138, D-464): a token registry naming every service, the console's own token in
``TB_SERVICE_TOKEN`` (so ``service_auth.actor_header`` signs as the console does) and the orchestrator's actor-key
file. Outside DEV and TEST the orchestrator admits only a caller it can name (T-713, D-464), so a PRODUCTION test of
an orchestrator route runs in this mode, as a real box does. Synthetic tokens only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from tb_common import service_auth as sa

ACTOR_SIGN_KEY = hashlib.sha256(b"a synthetic actor-signing key of the test box").hexdigest()
SERVICES = ("console", "mail-gateway", "operator", "adapter", "lake", "criteria-compiler", "doc-parser")


def token_of(service: str) -> str:
    return f"test-token-of-{service}-0123456789abcdef"


def per_service_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, me: str = "console") -> str:
    """Write the registry and the actor keys, make this process the service ``me``; return ``me``'s token."""
    reg = tmp_path / "tokens.json"
    reg.write_text(json.dumps({"schema": sa.REGISTRY_SCHEMA,
                               "services": {s: sa.token_hash(token_of(s)) for s in SERVICES}}),
                   encoding="utf-8")  # fmt: skip
    # T-717 (D-485): the console's signing key is a secret of its own (never a function of its token); the
    # orchestrator's keys file holds it. This process plays both, as the tests do.
    sign = tmp_path / "actor-sign.key"
    sign.write_text(ACTOR_SIGN_KEY + "\n", encoding="utf-8")
    keys = tmp_path / "actor-keys"
    keys.write_text(ACTOR_SIGN_KEY + "\n", encoding="utf-8")
    monkeypatch.setenv(sa.ACTOR_SIGN_KEY_ENV, str(sign))
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv(sa.REGISTRY_ENV, str(reg))
    monkeypatch.setenv(sa.ACTOR_KEYS_ENV, str(keys))
    monkeypatch.setenv("TB_SERVICE_TOKEN", token_of(me))
    return token_of(me)
