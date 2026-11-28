"""The canary runner on a real lake: a ruleset against itself moves nothing; another ruleset differs by criteria."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tb_common.ruleset import Ruleset

from tools.blast_radius import canary, lake_runner

ROOT = Path(__file__).resolve().parents[2]


def test_canary_on_the_site_a_lake(ingested: dict[str, Any]) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "RA-COH")
    day = json.loads((ROOT / "rulesets" / "RA-COH" / "tests" / "expected.json").read_text(encoding="utf-8"))[
        "index_date"
    ]
    run = lake_runner(Path(ingested["lake_dir"]))
    same = canary(rs, rs, run, day)
    assert same["patients"] >= 200 and same["moved"] == [] and same["only_old"] == same["only_new"] == []
    other = Ruleset.load(ROOT / "rulesets" / "RA-JAK")
    assert canary(rs, other, run, day)["only_old"]  # the diff does see a different criteria set
