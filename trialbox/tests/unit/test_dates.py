"""One date reader (T-118, D-215; review E-05, MR-015): ``tb_common.dates``.

Part 1 pins what the six modules that read or find dates (PHI guard, the stub chart reader, CASE, site set-up's
chart-date finder, the messy-sheet cell reader and the guard's DOB recogniser) returned before they became callers of
``tb_common.dates``: ``tests/fixtures/dates/six_modules.json`` was recorded from origin/master before the module
existed and is replayed here through the modules as they are now, byte for byte.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from guard import recognisers
from llm_stub import handlers
from orchestrator.scenarios import case
from sitesetup import messy, service
from tb_common import phi_guard

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "dates" / "six_modules.json"
CASES: dict[str, dict[str, Any]] = json.loads(RECORDED.read_text(encoding="utf-8"))["cases"]


def _now(s: str) -> dict[str, Any]:
    p = messy.parse_date(s)
    found = case.find_date(s)
    return {
        "phi": phi_guard.DATE.findall(s),
        "stub": handlers._DATE_ANY.findall(s),
        "case": None if found is None else found.isoformat(),
        "first": service._first_date(s),
        "messy": [p.iso, p.kind, p.problem, p.suggestion],
        "messy_noserial": messy.parse_date(s, serial=False).iso,
        "dmy": messy.parse_date(s, "dmy").iso,
        "dob": [m.group("v") for m in recognisers.DOB.finditer(s)],
        "date_re": re.findall(recognisers._DATE, s),
    }


@pytest.mark.parametrize("text", sorted(CASES))
def test_the_six_modules_answer_as_recorded(text: str) -> None:
    assert _now(text) == CASES[text]
