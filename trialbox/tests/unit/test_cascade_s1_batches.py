"""NEW-B-47 (D-748): the cascade's S1 asks the lake for its patients in batches, and the batches change no answer.

The nightly scale gate of 2026-11-14 (50,000 patients): the screen's S1 query (the ruleset's compiled SQL over the
whole scope, ``patient CROSS JOIN`` the index dates and ``list_contains`` over every scoped patient) ran 190 s and
met the lake's memory limit (3 GB): the screen never ended. A patient's S1 rows depend on that patient alone, so the
scope can be asked for in batches; the architecture review's rule (AD-6): batch sizes 1, 100 and 1,000 give the same
statuses."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_cascade_pipeline import (
    RecordingJudge,
    _answers,
    _run,
    e2e,  # noqa: F401  (the fixture the env fixture asks for)
)
from tests.unit.test_cascade_pipeline import env as _env_fixture  # noqa: F401  (fixture "env")


class _Counting:
    """The lake, counting the S1 queries and the patients each carried."""

    def __init__(self, lake: Any) -> None:
        self.lake = lake
        self.s1: list[int] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.lake, name)

    def query(self, sql: str, params: Any = None, snapshot: str | None = None, *a: Any, **kw: Any) -> Any:
        if params and len(params) == 2 and isinstance(params[1], list) and "idx_dates" in sql:
            self.s1.append(len(params[1]))
        return self.lake.query(sql, params, snapshot, *a, **kw)


@pytest.fixture(scope="module")
def whole(_env_fixture: dict[str, Any]) -> Any:  # noqa: F811
    return _run(_env_fixture, RecordingJudge(), sample_per_stratum=None)


def _check(env: dict[str, Any], base: Any, batch: int, **cfg: Any) -> None:
    counted = _Counting(env["lake"])
    n_idx = len(base.index_dates)
    parts = _run({**env, "lake": counted}, RecordingJudge(), sample_per_stratum=None, s1_rows=batch * n_idx, **cfg)
    assert _answers(parts) == _answers(base)
    assert [s.patients_out for s in parts.stages] == [s.patients_out for s in base.stages]
    scope = sum(counted.s1)
    assert counted.s1 and max(counted.s1) <= batch and len(counted.s1) == -(-scope // batch)  # one query per batch


@pytest.mark.parametrize("batch", [37, 100, 1000])
def test_the_batches_change_no_answer(_env_fixture: dict[str, Any], whole: Any, batch: int) -> None:  # noqa: F811
    _check(_env_fixture, whole, batch)


def test_one_patient_per_query_changes_no_answer(_env_fixture: dict[str, Any], whole: Any) -> None:  # noqa: F811
    """AD-6's batch of one, on 30 of the site's patients (one query each)."""
    pop = sorted(whole.traces)[:30]
    base = _run(_env_fixture, RecordingJudge(), sample_per_stratum=None, population=pop)
    _check(_env_fixture, base, 1, population=pop)


def test_a_setting_that_cannot_be_read_is_refused() -> None:
    from matching.cascade.engine import CascadeError, s1_rows

    assert s1_rows({}) == 4000 and s1_rows({"TB_CASCADE_S1_ROWS": ""}) == 4000
    assert s1_rows({"TB_CASCADE_S1_ROWS": "50"}) == 50
    for bad in ("0", "-5", "ten", "１０"):
        with pytest.raises(CascadeError, match="TB_CASCADE_S1_ROWS"):
            s1_rows({"TB_CASCADE_S1_ROWS": bad})


def test_the_batch_is_a_declared_setting() -> None:
    from tb_common.config import DECLARED

    assert "TB_CASCADE_S1_ROWS" in DECLARED
