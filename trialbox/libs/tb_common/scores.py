"""Versioned derived-score definitions (WS-04.3, D-189), generated from the catalogue's ``catalogue/scores/*.yaml`` by
``tools/gen_score_defs.py`` into ``score_defs.json``. Read-only at run time; no model ever writes a definition.

* :func:`definition` gives one definition (inputs, windows, examples, ``def_version`` = ``<score_id>@<version>`` and
  the ``sha256`` of its YAML).
* :data:`ENGINE` names, for each score the box computes, the catalogue definition it follows. ``derived.py`` takes the
  same-visit windows of these scores from the definition (:func:`visit_rule`), so the SQL and CQL engines and the
  Python reference all read the catalogue's numbers.
* :data:`TOLERANCE`: how far a documented score may differ from the computed one before a ``derived_vs_documented``
  conflict opens (D-190).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DEFS = Path(__file__).with_name("score_defs.json")

# engine score name (derived.py, the criterion IR) -> catalogue score_id
ENGINE: dict[str, str] = {
    "cdai": "rheum.cdai",
    "sdai": "rheum.sdai",
    "das28_esr": "rheum.das28_esr",
    "das28_crp": "rheum.das28_crp",
    "egfr_ckd_epi": "neph.egfr_ckd_epi_2021",
    "egfr_jsn": "neph.egfr_jsn_2009",
}

# catalogue item id (items.csv) -> derived.py component
ITEM_COMPONENT: dict[str, str] = {
    "rheum.tjc28": "tjc28",
    "rheum.sjc28": "sjc28",
    "rheum.ptga_0_10": "ptga10",
    "rheum.evga_0_10": "evga",
    "rheum.ptga_vas100": "ptga",
    "lab.crp": "crp",
    "lab.esr": "esr",
    "lab.creatinine": "creatinine",
    "vital.weight": "weight",
    "vital.height": "height",
}

# |computed - documented| above this opens a derived_vs_documented conflict (review §4.2: DAS28 0.2, eGFR 5, BMI 0.5;
# CDAI and SDAI 0.5: the catalogue rounds them to one decimal and a written score is often rounded to a whole number)
TOLERANCE: dict[str, float] = {
    "cdai": 0.5,
    "sdai": 0.5,
    "das28_esr": 0.2,
    "das28_crp": 0.2,
    "egfr_ckd_epi": 5.0,
    "egfr_jsn": 5.0,
}

# a documented value is compared with the computed row whose anchor is at most this many days away
DOCUMENTED_SPREAD_DAYS = 7


@cache
def _all() -> dict[str, dict[str, Any]]:
    doc = json.loads(DEFS.read_text(encoding="utf-8"))
    return dict(doc["definitions"])


def definitions() -> dict[str, dict[str, Any]]:
    """Every catalogue definition, by ``score_id``."""
    return dict(_all())


def definition(score: str) -> dict[str, Any]:
    """One definition, by catalogue ``score_id`` or engine name (``cdai``)."""
    return _all()[ENGINE.get(score, score)]


def def_version(score: str) -> str:
    """``<score_id>@<version>`` of an engine score."""
    return str(definition(score)["def_version"])


def output_unit(score: str) -> str:
    return str((definition(score).get("output") or {}).get("unit") or "")


def visit_rule(score: str) -> tuple[str, dict[str, int]]:
    """``(anchor component, {other component: max days from the anchor})`` from the definition's inputs. Inputs that are
    not component rows (age and sex from the person) are left out."""
    anchor: str | None = None
    spread: dict[str, int] = {}
    for inp in definition(score)["inputs"]:
        comp = ITEM_COMPONENT.get(str(inp.get("item")))
        if comp is None:
            continue
        if inp.get("anchor"):
            anchor = comp
        else:
            spread[comp] = int(inp.get("window_days") or 0)
    if anchor is None:
        raise ValueError(f"score definition {def_version(score)} names no anchor input")
    return anchor, spread


def worked_examples(score: str) -> list[dict[str, Any]]:
    """The definition's published examples that give the score itself: inputs (numbers, or text such as a sex) and one
    numeric expected value (``cdai: 27``, ``egfr: 63.1``). Rule and threshold examples are left out."""

    def num(x: Any) -> bool:
        return isinstance(x, int | float) and not isinstance(x, bool)

    short = str(definition(score)["score_id"]).split(".", 1)[1]
    names = {short, short.split("_", 1)[0]}  # "cdai"; "egfr" for egfr_jsn_2009
    out = []
    for ex in definition(score).get("examples") or []:
        inputs = ex.get("inputs") or {}
        expected = [float(v) for k, v in (ex.get("expected") or {}).items() if num(v) and k in names]
        if len(expected) == 1 and inputs and all(num(v) or isinstance(v, str) for v in inputs.values()):
            out.append({"inputs": dict(inputs), "expected": expected[0], "source": ex.get("source")})
    return out
