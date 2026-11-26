"""SCREEN's result for a whole hospital is written a row (or a batch of patients) at a time, never built whole.

At 48,344 patients the job's memory was flat through every model call, then took about 3.3 GiB more in one step at
the end, where the result was built: the candidate list and the excluded list each went through ``json.dumps`` with
``indent`` (whose encoder holds every small piece of the whole document at once, about seven times the file), the
answer store's rows for every patient and criterion were built as one list, and the pool's rows as one list of
dicts. A kill there restarted the job into the same step. Now the files are written one row at a time, byte for
byte as before, and the stores are written in batches inside their one transaction. Synthetic pseudonyms only.
"""

from __future__ import annotations

import json
import tracemalloc
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import answer_store
from orchestrator.scenarios import screen
from orchestrator.scenarios.evaluate import PatientVerdicts, row, sort_key
from tb_common.ruleset import Ruleset
from tb_contracts import CodedValue, CriterionVerdict, Evidence

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
RUN = date(2026, 10, 5)
TIERS = ["excluded"] * 9 + ["review"]  # a whole hospital: most are excluded by the coded filters


def _verdicts(i: int) -> list[CriterionVerdict]:
    out = []
    for k, c in enumerate(GZQO.active()):
        refs = [f"Observation/o{i}-{k}-{j}" for j in range(5)]
        coded = [CodedValue(record=r, domain="lab", code="1234-5", system="loinc", date="2026-01-01", value=1.5,
                            unit="mg") for r in refs[:3]]  # fmt: skip
        out.append(CriterionVerdict(id=c.id, verdict="fail" if k == 0 else "pass", basis="coded", prov=[],
                                    evidence=Evidence(resource_refs=refs, reason="coded", coded=coded)))  # fmt: skip
    return out


def _run(n: int) -> screen.ScreenRun:
    results = {f"p{i:07d}": PatientVerdicts(f"p{i:07d}", _verdicts(i), TIERS[i % 10], [], 0) for i in range(n)}
    rows = sorted((row(pv, None, "D1", "RHEU", "2026-10-05T09:00:00+08:00") for pv in results.values()), key=sort_key)
    scoped = [screen.Scoped(p, None, "D1", "RHEU") for p in results]
    return screen.ScreenRun(GZQO, RUN, "2026-10-04", scoped, results, rows, [], [], 180, None, {}, whole_hospital=True)


class _Db:
    """The trial database's two writes as the real one makes them: each batch is materialised (``executemany``)."""

    def __init__(self) -> None:
        self.answers = 0
        self.largest = 0
        self.pool: list[str] = []

    def answer_store_put(self, batches: Any) -> None:
        for rows, open_only in batches:
            batch = [tuple(r) for r in [*rows, *open_only]]
            self.answers += len(batch)
            self.largest = max(self.largest, len(batch))

    def answer_store_snapshots(self) -> list[str]:
        return []

    def pool_upsert(self, ruleset: str, version: str, rows: Any, job_id: str, at: str) -> None:
        for r in rows:
            json.dumps(r["verdicts"], sort_keys=True)  # the real write encodes each row's verdicts
            self.pool.append(r["pid"])


def _ctx(db: _Db, sent: dict[str, int]) -> Any:
    lake = SimpleNamespace(query=lambda *_a, **_k: SimpleNamespace(to_pylist=lambda: []))
    return SimpleNamespace(
        publish=lambda name, data, tag, to: sent.__setitem__(name, len(data)),
        services=SimpleNamespace(lake=lake),
        job=SimpleNamespace(job_id="J1"),
        orch=SimpleNamespace(db=db, audit=None, _now=lambda: SimpleNamespace(isoformat=lambda: "2026-10-05T09:00")),
        decision=SimpleNamespace(register_now=frozenset),
        today=lambda: RUN,
    )


def _peak(fn: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize(
    "doc,rows",
    [
        ({"a": 1, "z": [1, {"y": None}]}, []),
        ({}, [{"pid": "p1"}]),
        ({"zz": "last", "judging": {"rows": None, "text": 'a\n "rows": null'}}, [{"b": [1, 2], "a": {"c": "名"}}] * 3),
        ({"aa": True}, [[], {}, "s", 1.5, None, {"nested": [{"k": [[]]}]}]),
    ],
    ids=["empty", "alone", "look-alike-key-and-unicode", "every-kind"],
)
def test_the_rows_written_one_at_a_time_are_the_documents_bytes(doc: dict[str, Any], rows: list[Any]) -> None:
    old = json.dumps({**doc, "rows": rows}, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    assert screen.json_rows(doc, "rows", iter(rows)) == old


def test_the_candidate_list_file_is_the_contracts_dump_as_before() -> None:
    from tb_contracts import dump

    cl = screen.candidate_list(_run(30))
    assert cl.rows  # the file has rows to compare
    old = json.dumps(dump(cl), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    assert screen.candidate_list_json(cl) == old


def test_the_answer_store_writes_a_whole_hospital_a_batch_at_a_time() -> None:
    # two batches against six: the batch being written and the next one being built are both held, never more
    small, large = _run(answer_store.BATCH * 2), _run(answer_store.BATCH * 6)
    per = len(list(GZQO.active()))
    peaks = []
    for srun in (small, large):
        db = _Db()
        peaks.append(
            _peak(partial(answer_store.record, _ctx(db, {}), "GZQO", "1.0.0", srun.results, RUN, "2026-10-04"))
        )
        assert db.answers == len(srun.results) * per  # every answer of every patient, once
        assert db.largest <= answer_store.BATCH * per  # never more than a batch of patients' answers at once
    assert peaks[1] < 1.5 * peaks[0], f"the answer store's memory grew with the patients: {peaks}"


def test_a_large_scopes_result_stays_under_a_ceiling_far_below_the_old_peak(monkeypatch: pytest.MonkeyPatch) -> None:
    """2,000 patients, the result as ``screen.run`` builds it after the model calls: the answer store, the candidate
    list's file (held to the end of the run, as ``run`` holds it), the pool and both excluded files. Measured on this
    scope with the old code's expressions: 34.5 MiB (34.2 MiB the candidate list's ``json.dumps`` alone, for a file of
    4.5 MiB); this code: 10.3 MiB. What stays is the bytes of the files themselves."""
    monkeypatch.setattr(screen, "opted_out_now", lambda ctx, pids, where: frozenset())  # nobody on the register
    srun = _run(2000)
    db, sent = _Db(), {}
    ctx = _ctx(db, sent)
    cl = screen.candidate_list(srun)
    held: list[bytes] = []

    def result() -> None:
        answer_store.record(ctx, "GZQO", "1.0.0", srun.results, RUN, srun.snapshot)
        held.append(screen.candidate_list_json(cl))
        screen.persist_pool(ctx, GZQO, [r for r in srun.rows if r.tier in ("high", "review")])
        screen.publish_excluded(ctx, GZQO, srun)

    peak = _peak(result)
    assert db.pool and set(sent) == {"excluded_GZQO_v1.0.0.jsonl", "excluded_GZQO_v1.0.0.json"}
    assert peak < 15 * 2**20, f"the result took {peak / 2**20:.1f} MiB"
