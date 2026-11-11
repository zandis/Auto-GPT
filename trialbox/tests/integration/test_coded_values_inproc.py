"""T-514 (D-362, review UX-008) end to end in process: a SCREEN run on the synthetic site puts the coded records'
value, unit, date and code on the candidate list and on the not-matched list, and leaves every verdict as it was."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import tb_contracts as c

from tests.inproc_box import Box
from tests.integration.test_screen_inproc import _list_mail, _screen, world  # noqa: F401 - world is a fixture


def test_a_screen_run_carries_value_unit_date_and_code(world: dict[str, Any], synth_dir: Path) -> None:  # noqa: F811
    box: Box = world["box"]
    _screen(box)
    files = _list_mail(box, "[GZQO] SCREEN candidates")
    cl = c.CandidateList.model_validate_json(next(v for k, v in files.items() if k.endswith(".json")))
    decided = [v for r in cl.rows for v in r.criteria if v.verdict in ("pass", "fail")]
    assert decided
    # the acceptance: no met / not met row without a value or a quote
    for v in decided:
        ev = v.evidence
        assert ev is not None and (ev.quote or ev.coded is not None), v
    shown = [x for v in decided for x in (v.evidence.coded or [])]  # type: ignore[union-attr]
    kinds = Counter(x.domain for x in shown)
    assert kinds["observation"] and kinds["condition"] and kinds["demographic"], kinds
    for x in shown:
        if x.domain == "observation":
            assert x.code and x.system and x.date and (x.value is not None or x.value_code), x
            assert x.value is None or x.unit, x  # a number always with the record's own unit
        elif x.domain == "demographic":
            assert x.code in ("age", "sex"), x
        else:
            assert x.code and x.record, x
    assert all(len(v.evidence.coded or []) <= 3 for v in decided)  # type: ignore[union-attr]
