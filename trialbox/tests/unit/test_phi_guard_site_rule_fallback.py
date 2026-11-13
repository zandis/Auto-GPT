"""AR-01 (deep review `architecture`): the note mask's chart-number rule does not fail open on a box.

`phi_guard.site_mrn_regex()` answered ``None`` whenever the site configuration could not be read, and ``None`` means
"labelled chart numbers only": an unlabelled chart number in a note then stayed in the lake, the embed service's
input and a revealed note. The log scrubber already fell back to the contract's default pattern for the same fault.
Outside DEV and TEST the note mask now does the same; DEV and TEST keep ``None`` (a test lake, a tool run without a
site)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from tb_common import phi_guard
from tb_common.config import get_config

pytestmark = pytest.mark.nodb

NOTE = "seen today, chart 12345678, no change"


@pytest.fixture
def no_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A box whose settings.yaml is missing: the configuration cannot be read."""
    monkeypatch.setenv("TB_SETTINGS", str(tmp_path / "missing.yaml"))
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", "production", None])
def test_an_unreadable_site_configuration_masks_an_unlabelled_chart_number(
    no_site: None, monkeypatch: pytest.MonkeyPatch, env: str | None
) -> None:
    if env is None:
        monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION (D-127)
    else:
        monkeypatch.setenv("TB_ENV", env)
    pattern = phi_guard.site_mrn_regex()
    assert pattern is not None
    assert "12345678" not in phi_guard.mask_note(NOTE, pattern)


@pytest.mark.parametrize("env", ["DEV", "TEST"])
def test_dev_and_test_keep_labelled_numbers_only(no_site: None, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("TB_ENV", env)
    assert phi_guard.site_mrn_regex() is None


def test_the_fallback_is_the_log_scrubbers_pattern(no_site: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """One rule, one fallback: the note mask and the log scrubber use the same default."""
    from tb_contracts.generated.models import Settings

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert phi_guard.site_mrn_regex() == str(Settings.model_fields["mrn_regex"].default)
