"""T-115 (E-12) on the console: the review page shows, beside each signed value, who signed it, as what, when and
the meaning they signed; the trail lists the values each signature covers. Synthetic data only."""

from __future__ import annotations

import html
from typing import Any

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages_d281 import _confirm_and_sign


def test_e12_the_signature_shows_beside_each_signed_value(eb: dict[str, Any]) -> None:  # noqa: F811
    crc, _ = _confirm_and_sign(eb)
    sig = eb["svc"].store.signatures("GZQO", NO)[0]
    rev = html.unescape(crc.get(f"/studies/GZQO/edc/review/{NO}").text)
    for item in ("weight", "urate"):
        assert f'data-testid="signed-by-{item}"' in rev and f'data-testid="signed-meaning-{item}"' in rev
    assert f"Signed by {sig['printed_name']}" in rev and sig["meaning_text"] in rev
    assert 'data-testid="signed-by-sex"' not in rev  # not signed: nothing beside it
    trail = html.unescape(crc.get(f"/studies/GZQO/edc/trail/{NO}").text)
    assert f'data-testid="trail-sig-items-{sig["id"]}"' in trail and "weight, urate" in trail
