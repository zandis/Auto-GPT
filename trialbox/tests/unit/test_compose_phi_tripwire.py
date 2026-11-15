"""COMPOSE-TRIPWIRE (D-795), the owner's blocker 4 with lane A2's #654: the gateway's container gets the PHI tripwire
setting from deploy/.env, on unless the site writes otherwise (fails safe)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tb_common.config import DECLARED

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def test_the_gateway_takes_the_tripwire_setting_on_by_default() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["gateway"]["environment"]
    assert env["TB_GATEWAY_PHI_TRIPWIRE"] == "${TB_GATEWAY_PHI_TRIPWIRE:-on}"
    assert "TB_GATEWAY_PHI_TRIPWIRE" in DECLARED


def test_no_other_service_gets_it() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    others = [n for n, s in compose["services"].items() if n != "gateway"
              and isinstance(s.get("environment"), dict) and "TB_GATEWAY_PHI_TRIPWIRE" in s["environment"]]  # fmt: skip
    assert others == []
