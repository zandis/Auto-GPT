"""MICROBATCH takes the same note-block decision as SCREEN (D-276; adversarial review F-01).

The weekly run re-judges the time-sensitive criteria of the pool's patients and works out the tier again. It used to
call ``tier`` with no ``note_block``, so the configured policy alone (``both_agree``) applied: on a box with one model
(no verifier, or the judge named twice) a confident note "present" on an exclusion took the patient out, although
SCREEN on the same box would never exclude on it. Now the tier needs the run's decision (``effective_note_block``).
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.scenarios import microbatch
from orchestrator.scenarios.evaluate import PatientVerdicts
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
NOTE = "GZQO-EXC-11"  # a time-sensitive note exclusion (current gout flare)
RUN = date(2026, 10, 5)


class _Stop(Exception):
    pass


def _pool_verdicts() -> list[dict[str, Any]]:
    out = []
    for c in GZQO.active():
        verdict: Any = "pending_human" if c.class_ == "human" else "pass"
        conf = 0.9 if c.class_ == "note" else None
        out.append(
            CriterionVerdict(id=c.id, verdict=verdict, evidence=Evidence(resource_refs=[], confidence=conf)).model_dump(
                mode="json"
            )
        )
    return out


def _weekly_tier(monkeypatch: pytest.MonkeyPatch, llm: Any, verifier: Any) -> str:
    """One pool patient; this week the judge answers the note exclusion as present at 0.95. The tier the run gives."""
    fresh = CriterionVerdict(
        id=NOTE, verdict="fail", evidence=Evidence(resource_refs=["DocumentReference/D1"], quote="q", confidence=0.95)
    )
    seen: list[Any] = []

    def stop(ctx: Any, rs: Any, rows: list[Any]) -> None:
        seen.extend(rows)
        raise _Stop

    monkeypatch.setattr(microbatch, "require_approved", lambda ctx, rs, v: GZQO)
    monkeypatch.setattr(microbatch, "drop_opted_out", lambda ctx, scoped: scoped)
    monkeypatch.setattr(
        microbatch,
        "evaluate_scope",
        lambda *a, **kw: {"P1": PatientVerdicts("P1", [fresh], "excluded", [], 0)},
    )
    monkeypatch.setattr(microbatch, "persist_pool", stop)
    appt = {"pid": "P1", "next_appt": datetime(2026, 10, 7, 9, 0), "practitioner_id": "D1", "dept": "rheum"}
    ctx: Any = SimpleNamespace(
        job=SimpleNamespace(
            ruleset="GZQO", options={"incident": "0"}, job_id="J1", received_at=datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
        ),
        update=lambda **kw: None,
        state=lambda s: None,
        metrics=lambda **kw: None,
        today=lambda: RUN,
        orch=SimpleNamespace(
            db=SimpleNamespace(
                pool=lambda rid: [{"pid": "P1", "verdicts": _pool_verdicts()}],
                find=lambda **kw: [],
                locked=lambda name: nullcontext(),
            )
        ),
        services=SimpleNamespace(
            lake=SimpleNamespace(
                snapshot=lambda: "2026-10-05",
                query=lambda sql, *a, **kw: SimpleNamespace(  # no consent statement (D-477); the visit otherwise
                    to_pylist=lambda: [] if "consent" in sql else [appt]
                ),
            ),
            llm=llm,
            verifier=verifier,
        ),
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo"), settings=SimpleNamespace(thresholds=None)),
    )
    with pytest.raises(_Stop):
        microbatch.run(ctx)
    (row,) = seen
    return str(row.tier)


@pytest.fixture(autouse=True)
def _policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")  # the default
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    monkeypatch.delenv("TB_SCREEN_JUDGE", raising=False)


def test_a_one_model_box_never_excludes_on_a_note_answer_in_the_weekly_run(monkeypatch: pytest.MonkeyPatch) -> None:
    judge = SimpleNamespace(model="judge-a", base_url="http://a/v1", gateway=None, served_root="judge-a")
    assert _weekly_tier(monkeypatch, judge, None) == "review"  # no verifier
    same = SimpleNamespace(model="judge-a", base_url="http://b/v1", gateway=None, served_root="judge-a")
    assert _weekly_tier(monkeypatch, judge, same) == "review"  # the judge named twice


def test_a_pair_of_two_models_still_excludes_in_the_weekly_run(monkeypatch: pytest.MonkeyPatch) -> None:
    judge = SimpleNamespace(model="judge-a", base_url="http://a/v1", gateway=None, served_root="judge-a")
    verifier = SimpleNamespace(model="verifier-b", base_url="http://b/v1", gateway=None, served_root="verifier-b")
    assert _weekly_tier(monkeypatch, judge, verifier) == "excluded"  # control
