"""G6 of the integrator's second review of the P1b run (#639, 2026-11-16): every all-human ruleset that was approved
failed SCREEN at the report with a ValidationError. D-909 sets ``judging.mode = "nothing"`` when no criterion is a
machine's (``screen_cascade``), but ``Judging.mode`` (``schemas/candidate_list.schema.json``, the generated model)
allowed only agreement / single / none, and ``screen.candidate_list`` raised. D-909's test stopped at the cascade.

* ``nothing`` is a mode of the candidate list: the run's list builds and the stored JSON is valid against the schema.
* Every mode the screen code writes is one the schema allows.
* The mail and the PDF say it in three languages.

Synthetic: the shipped GZQO ruleset, no patients.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from orchestrator.scenarios import screen
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "candidate_list.schema.json").read_text(encoding="utf-8"))


def _run(judging: dict[str, object]) -> screen.ScreenRun:
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    return screen.ScreenRun(rs=rs, run_date=date(2026, 11, 16), snapshot="2026-11-15", scoped=[], results={}, rows=[],
                            practitioners=["D1"], departments=[], window_days=30, judge=None, judging=judging,
                            cascade={"stages": []})  # fmt: skip


def test_a_run_where_nothing_decides_builds_its_candidate_list() -> None:
    judging = {**screen.judging_info(None), "mode": "nothing"}  # what the D-909 path stores
    cl = screen.candidate_list(_run(judging))
    assert cl.judging is not None and cl.judging.mode == "nothing"
    jsonschema.validate(json.loads(cl.model_dump_json(by_alias=True, exclude_none=True)), SCHEMA)


def test_every_mode_the_screen_writes_is_one_the_schema_allows() -> None:
    allowed = set(SCHEMA["$defs"]["judging"]["properties"]["mode"]["enum"])
    scenarios = ROOT / "services" / "orchestrator" / "scenarios"
    src = "".join((scenarios / f).read_text(encoding="utf-8") for f in ("screen.py", "screen_cascade.py"))
    judge = (scenarios / "evaluate.py").read_text(encoding="utf-8")  # NoteJudge.mode
    written = set(re.findall(r'"mode":\s*"(\w+)"', src)) | set(re.findall(r'"(agreement|single)"', judge)) | {"none"}
    assert written <= allowed, written - allowed


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_mail_says_nothing_decided_in_three_languages(lang: str) -> None:
    said = screen.judging_sentence({"mode": "nothing"}, lang)
    assert said and "screen.judging" not in said
