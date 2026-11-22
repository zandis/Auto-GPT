"""BH1-06: a site chart-number pattern anchored on each branch is not applied to running text.

Entry points: ``tb_common.logging.set_mrn_regex`` / ``redact`` (the log scrubber), ``tb_common.phi_guard.scan`` (the
gateway tripwire's v1 scan) and ``guard.guard.Guard(mrn_regex).redact`` (the trace store's redaction). Each turns
``settings.mrn_regex`` into a search pattern with ``pattern.strip("^$")``, which removes only the outermost anchors.
A valid pattern for a site with two chart-number formats, ``^\\d{8}$|^C\\d{7}$``, keeps its inner anchors, so a
chart number in the middle of a line is never found. Synthetic values only.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from guard.guard import Guard
from tb_common import logging as tb_logging
from tb_common import phi_guard

SITE_RULE = r"^\d{8}$|^C\d{7}$"  # two formats, each anchored: a valid regex the settings schema accepts
LINE = "lab drawn for C1234567 and 12345678 today"  # synthetic chart numbers, unlabelled, mid-line


@pytest.fixture
def site_rule() -> Iterator[None]:
    saved = list(tb_logging._EXTRA_MRN)
    tb_logging.set_mrn_regex(SITE_RULE)
    yield
    tb_logging._EXTRA_MRN[:] = saved


@pytest.mark.xfail(strict=True, reason="open finding: BH1-06: anchors inside an alternation survive strip('^$')")
def test_log_scrubber_masks_both_formats_mid_line(site_rule: None) -> None:
    out = tb_logging.redact(LINE)
    assert "C1234567" not in out and "12345678" not in out


@pytest.mark.xfail(strict=True, reason="open finding: BH1-06: anchors inside an alternation survive strip('^$')")
def test_phi_scan_flags_both_formats_mid_line() -> None:
    kinds = [k for k, _ in phi_guard.scan(LINE, SITE_RULE).findings]
    assert kinds.count("mrn") == 2


@pytest.mark.xfail(strict=True, reason="open finding: BH1-06: anchors inside an alternation survive strip('^$')")
def test_guard_redacts_both_formats_mid_line() -> None:
    out = Guard(SITE_RULE).redact(LINE)
    assert "C1234567" not in out and "12345678" not in out


def test_single_format_rule_still_masks_mid_line(site_rule: None) -> None:
    """Control: the shipped single-format form works, so the probes above fail for the alternation alone."""
    tb_logging.set_mrn_regex(r"^\d{8}$")
    assert "12345678" not in tb_logging.redact("lab drawn for 12345678 today")
    assert "12345678" not in Guard(r"^\d{8}$").redact("lab drawn for 12345678 today")
