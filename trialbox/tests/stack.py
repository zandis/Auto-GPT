"""The compose test stack as seen from the host (deploy/docker-compose.test.yml).

Every published port can be moved when it is taken on the developer machine: set ``TB_HOST_<NAME>_PORT`` in the
environment or in ``deploy/.env`` (where compose reads it too). ``ensure_ingested()`` loads synthetic site A once, so
the compose integration and e2e tests do not depend on a manual ingest or on test order."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from tb_common.config import _read_dotenv

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "2026-10-04"  # synthetic fixtures' snapshot (tools/synth/generator.py: reference date minus one day)

DEFAULT_PORTS = {
    "SMTP": 3025,  # GreenMail SMTP (mail into the box)
    "IMAP": 3143,  # GreenMail IMAP
    "MAILHOG": 8025,  # MailHog UI/API (mail out of the box)
    "ORCH": 8010,
    "PARSER": 8011,
    "COMPILER": 8012,
    "LAKE": 8013,
    "MAIL_GATEWAY": 8015,
    "ADAPTER": 8016,
    "MINIO": 9000,
    "FHIR": 8080,
    "LLM": 8000,
}


def host_port(name: str) -> int:
    key = f"TB_HOST_{name}_PORT"
    raw = os.environ.get(key) or _read_dotenv(ROOT / "deploy" / ".env").get(key) or str(DEFAULT_PORTS[name])
    return int(raw)


def url(name: str, path: str = "") -> str:
    return f"http://127.0.0.1:{host_port(name)}{path}"


def ensure_ingested(force: bool = False) -> dict[str, object] | None:
    """Run the adapter's CSV ingest unless the lake already has a snapshot; returns the adapter report if it ran."""
    if not force:
        health = httpx.get(url("LAKE", "/healthz"), timeout=30).json()
        if health.get("checks", {}).get("snapshot", "none") != "none":
            return None
    resp = httpx.post(url("ADAPTER", "/run"), json={"source": "csv", "snapshot": SNAPSHOT}, timeout=1800)
    resp.raise_for_status()
    report: dict[str, object] = resp.json()
    return report


if __name__ == "__main__":  # `make ingest-test`
    rep = ensure_ingested(force=True)
    assert rep is not None
    print({k: rep.get(k) for k in ("passed", "counts", "fhir_loaded")})
