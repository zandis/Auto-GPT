"""NEW-JRN-7 (D-770, the deep review's JRN-007): a consent date in the future is refused.

The built-in consent form saved "Consent: given 2027-03-01" without a word, and the screening log and the enrolment
report carried it: consent before any study procedure is the first thing an inspector checks. The form's date fields
of consent now take REDCap's own ``today`` as their maximum, read as the site's day (``site.tz``); a later day is
refused with the ``max`` reason, as any value out of range. (Consent after enrolment or after a visit was already
flagged: ``enrolment_before_consent``, ``visit_before_consent``.) Synthetic data only."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from datacore import forms

ROOT = Path(__file__).resolve().parents[2]


def _consent_fields() -> dict[str, forms.Field]:
    text = (ROOT / "services/datacore/builtin/forms.csv").read_text(encoding="utf-8")
    return {f.name: f for f in forms.read_dictionary(text) if f.form == "tb_consent"}


@pytest.mark.parametrize("name", ["ic_date", "ic_reconsent_date"])
def test_a_consent_date_after_the_sites_day_is_refused(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    f = _consent_fields()[name]
    monkeypatch.setattr(forms, "site_today", lambda: date(2026, 11, 14))
    assert forms.problem(f, "2026-11-14") is None
    got = forms.problem(f, "2026-11-15")
    assert got is not None and got["code"] == "max" and got["max"] == "2026-11-14"
    assert forms.problem(f, "2027-03-01") is not None


def test_today_is_the_sites_day_and_reads_as_a_limit_anywhere() -> None:
    """``today`` as a minimum works the same way (REDCap's own word), for any date field."""
    f = forms.Field(name="x", form="f", kind="date", label="x", vmin="today", vmax="")
    assert forms.problem(f, (forms.site_today() - timedelta(days=1)).isoformat())["code"] == "min"  # type: ignore[index]
    assert forms.problem(f, forms.site_today().isoformat()) is None
