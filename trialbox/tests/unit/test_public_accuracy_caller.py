"""The accuracy run's services call the model gateway as the verified services they are.

``python -m tools.public_accuracy dryrun`` built its box with no per-service tokens, so every gateway call carried the
old shared token (or none) and the PRODUCTION gateway refused it: ``caller_unverified``, and every protocol failed
before screening. The gateway's refusal is unchanged (``services/orchestrator/callers.py``); the run now carries the
per-service tokens a box has. Synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_public_accuracy import _bundle
from tools.public_accuracy import box, site


def test_the_dry_run_services_are_verified_callers_of_the_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", "a-token-of-this-test-only-0123456789")  # the shared token is set
    monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION: the gateway admits only a caller it can name
    site.build(_bundle(), tmp_path / "built")
    out = box.run(tmp_path / "built", tmp_path / "work")
    failed = {p: a.get("feas_error") for p, a in out["answers"].items() if a.get("feas") == "failed"}
    assert failed == {}, "the gateway refused a compile as an unverified caller"
