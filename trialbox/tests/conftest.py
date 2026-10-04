from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("TB_", "IMAP_", "SMTP_", "MINIO_", "LLM_", "CLOUD_LLM", "MAIL_")):
            monkeypatch.delenv(key, raising=False)
    yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TB_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="needs compose services (set TB_INTEGRATION=1, run `make up-test`)")
    for item in items:
        if "integration" in item.keywords or "e2e" in item.keywords:
            item.add_marker(skip)
