"""Alliance site keys for tests (D-1320): a key pair per synthetic site, made inside the test run and never written
anywhere but the test's own folder; the root's register of them; a site's table signed as its box signs it."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common import alliance
from tb_common.crypto import ed25519_generate, ed25519_public_of
from tb_common.opportunity import key_fingerprint

_KEYS: dict[str, bytes] = {}
#: a fixed signing time, so a table signed twice in a test signs the same bytes; ``seq`` is passed per table
AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def key(site: str) -> bytes:
    """The site's private key (PEM), made once per test process."""
    if site not in _KEYS:
        _KEYS[site] = ed25519_generate()[0]
    return _KEYS[site]


def register(folder: Path, sites: tuple[str, ...] | list[str]) -> Path:
    """The root's register of ``sites``, as ``tools.opportunity_feed keygen`` prints its entries."""
    path = folder / "alliance-site-keys.json"
    entries = {s: {"name": f"{s} (synthetic)", "key_sha256": key_fingerprint(ed25519_public_of(key(s)))} for s in sites}
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sites": entries}, indent=1) + "\n", encoding="utf-8")
    return path


def env(folder: Path, sites: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {alliance.REGISTER_FILE: str(register(folder, sites))}


def signature(rows: list[dict[str, Any]], seq: int = 1, private: bytes | None = None) -> bytes:
    """The signature file of one site's table, by its own key unless ``private`` is given. The rows go through the
    root's reader first, as the box does."""
    from orchestrator.scenarios import cohort

    parsed, errors = cohort.parse_csv(cohort.to_csv(rows))
    if errors:  # a table the root refuses for its form: signed as it is, so the form is what refuses it
        parsed = rows
    site = str(rows[0]["site_id"])
    return alliance.to_bytes(alliance.sign(parsed, private or key(site), seq, AT))
