"""D-461 (T-720) on the console: the review page shows "signed" and the signer only while an intact signature covers
the value; a value changed in the database after signing shows as not signed. Synthetic data only."""

from __future__ import annotations

import html
from typing import Any

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages_d281 import _confirm_and_sign


def test_a_value_changed_after_signing_is_not_shown_as_signed(eb: dict[str, Any]) -> None:  # noqa: F811
    crc, _ = _confirm_and_sign(eb)
    store = eb["svc"].store
    weight = next(d for d in store.drafts("GZQO", NO) if d["item"] == "weight")
    rev = html.unescape(crc.get(f"/studies/GZQO/edc/review/{NO}").text)
    assert 'data-testid="signed-weight"' in rev and 'data-testid="signed-by-weight"' in rev
    assert 'data-testid="not-covered-weight"' not in rev
    store.db.execute("UPDATE draft SET final = '99' WHERE id = ?", (weight["id"],))
    rev = html.unescape(crc.get(f"/studies/GZQO/edc/review/{NO}").text)
    assert 'data-testid="signed-weight"' not in rev and 'data-testid="signed-by-weight"' not in rev
    assert 'data-testid="not-covered-weight"' in rev and "not signed: changed after signing" in rev
    assert 'data-testid="signed-urate"' in rev and 'data-testid="signed-by-urate"' in rev  # the others stay signed
