"""F5 of the integrator's root-cause review of the P1b run (#639, 2026-11-16): one age fact decided twice in sigir's
rulesets (NCT01790477: INC age >= 18 and EXC age <= 17), so a minor failed two criteria and the counts and reasons
said it twice.

* An exclusion whose age is the exact complement of an inclusion's is kept, marked rejected with a comment naming the
  inclusion (``restates_inclusion``): the inclusion alone decides; the reviewer may approve it back.
* Anything else is left alone: a narrower exclusion (over 75 under an 18+ inclusion), a bound that is not the
  complement, an age with sex.

The run's own lines (public SIGIR protocols); no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput


def _run(inc: dict[str, Any], exc_text: str, exc: dict[str, Any]) -> Any:
    crit = [{"kind": "inclusion", "class": "structured", "text": "Age", "logic": inc, "concept_candidates": []},
            {"kind": "exclusion", "class": "structured", "text": exc_text, "logic": exc, "concept_candidates": []}]  # fmt: skip
    post = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": crit}), Terminology(), "1.0.0")
    return post.criteria, post.warnings


@pytest.mark.parametrize(
    ("inc", "text", "exc"),
    [({"min": 18}, "Participant is under 18 years old.", {"max": 17}),
     ({"min": 18}, "age < 18 years", {"max": 17}),
     ({"max": 65}, "Aged over 65", {"min": 66})],
)  # fmt: skip
def test_an_exclusion_that_is_the_inclusions_complement_is_marked_rejected(
    inc: dict[str, float], text: str, exc: dict[str, float]
) -> None:
    (i, e), warnings = _run({"domain": "demographic", "age": inc}, text, {"domain": "demographic", "age": exc})
    assert i.review is not None and i.review.status == "draft"
    assert e.review is not None and e.review.status == "rejected" and i.id in (e.review.comment or "")
    assert "restates_inclusion" in (e.flags or []) and any(i.id in w for w in warnings)


@pytest.mark.parametrize(
    ("inc", "text", "exc"),
    [({"min": 18}, "Aged over 75", {"min": 76}),  # narrower: an ordinary exclusion
     ({"min": 18}, "Under 16", {"max": 15}),  # not the complement
     ({"min": 18, "max": 65}, "Under 18", {"max": 17})],  # the inclusion is a range: no single complement
)  # fmt: skip
def test_any_other_age_exclusion_is_left_alone(inc: dict[str, float], text: str, exc: dict[str, float]) -> None:
    (_, e), _ = _run({"domain": "demographic", "age": inc}, text, {"domain": "demographic", "age": exc})
    assert e.review is not None and e.review.status == "draft" and "restates_inclusion" not in (e.flags or [])


def test_an_age_with_sex_is_left_alone() -> None:
    (_, e), _ = _run({"domain": "demographic", "age": {"min": 18}}, "Boys under 18",
                     {"domain": "demographic", "age": {"max": 17}, "sex": "male"})  # fmt: skip
    assert e.review is not None and e.review.status == "draft"
