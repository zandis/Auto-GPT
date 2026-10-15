"""Host ports of the compose test stack (deploy/docker-compose.test.yml). 8000 and 8080 are often taken on a
developer machine, so they can be moved: set ``TB_HOST_LLM_PORT`` / ``TB_HOST_FHIR_PORT`` in the environment or in
``deploy/.env`` (where compose reads them too)."""

from __future__ import annotations

import os
from pathlib import Path

from tb_common.config import _read_dotenv

ROOT = Path(__file__).resolve().parents[1]


def host_port(name: str, default: int) -> int:
    raw = os.environ.get(name) or _read_dotenv(ROOT / "deploy" / ".env").get(name) or str(default)
    return int(raw)


FHIR_PORT = host_port("TB_HOST_FHIR_PORT", 8080)
LLM_PORT = host_port("TB_HOST_LLM_PORT", 8000)
FHIR_URL = f"http://127.0.0.1:{FHIR_PORT}/fhir"
