"""What this box's tier does not include, worded as a status and never as an error (plan 10 row 10E-17, D-1244).

The box's tier record (``models/tiers/<profile>.json``, plan 10 row 10E-1, D-1320) lists in ``console_promises`` what
the console may promise on the box: one row per capability with its ``status`` and ``because``. This module reads
that field through the services' one reader, ``tb_common.tier_value`` (lane H, D-1322), and keeps only the rows whose
status says the tier does not include the capability (:data:`WORDED`). The administrator's home page shows them as
plain lines that end "nothing is wrong", in the tile style of a status, with no warning or error pill; a line
worded from a declared field adds that it is declared for the tier and not yet measured on this hardware.

Words only. The rows decide nothing: no route, button, run or permission reads them, so a declared field may be shown
(D-1244; D-1322's "measured only" stays the rule for a value that changes what the box does). A capability the tier
does include is never in the list, so when it breaks, the page's own warning or error for it is unchanged.

Nothing is shown, and the page is byte for byte what it was, when the tier includes everything it lists (the
RTX PRO 6000 record), when the box has no record (``TB_PROFILE`` of another profile, unset, or a missing or malformed
file), and for a row this module has no words for (a new capability or status reads as nothing until it is worded
in en, ja and zh-TW). Never raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tb_common import tier_value

from console.i18n import CATALOGUES
from console.i18n_tier import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

FIELD = "console_promises"
#: the (capability, status) rows of a tier record that mean "this tier does not include it", each worded as
#: ``tier.lacks.<capability>``; "available" and "not_measured" are not absences and are never worded here
WORDED: dict[str, str] = {
    "protocol_reading": "not_on_this_box",
    "chat_during_a_screening_run": "busy_until_the_run_releases_the_card",
}


def lacks(env: Mapping[str, str] | None = None, tiers_dir: Path | None = None) -> list[dict[str, str]]:
    """The rows of this box's tier record that the tier does not include, in the record's order; [] when none.

    Each row carries ``basis``, the field's basis in the record (``measured`` or ``declared``): the page says of a
    declared row that it is declared for the tier and not yet measured on this hardware, and says nothing of a
    measured one, so a declared row never reads as a measured fact (D-1244)."""
    tv = tier_value.measured(FIELD, env, tiers_dir)
    rows: Any = tv.value if tv.case == "measured" else tv.declared if tv.case == "declared" else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cap, status = row.get("capability"), row.get("status")
        if isinstance(cap, str) and WORDED.get(cap) == status and all(c["capability"] != cap for c in out):
            out.append({"capability": cap, "status": str(status), "basis": tv.case})
    return out
