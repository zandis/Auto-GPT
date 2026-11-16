"""The judged-pair store (D-908; the owner's D-519, 2026-11-16; CAS-5): a model's answer to a note question, kept
across SCREEN jobs so the same question asked again of the same build is read, not asked.

The owner's conditions, each tested here:

* the key: pseudonym; canonical hash, exact wording and note question; the hash of the exact excerpt set (D-479);
  role; prompt id and file sha; the build that answers the role; the window (and the index date); NOTE_MASK_VERSION;
* only a parsed answer from the build that answers the role is stored: never a refusal, a fault, an answer that names
  no build or an unanswered call;
* the judge's and verifier's answers are stored apart and recombined when read, by the pair rule (D-478), never a
  stored verdict: a second job's answer is the first job's, disagreement included;
* an audit sample (CAS-8) is asked live and never stored;
* an opt-out deletes the patient's rows (the opt-out worker's owed tables, and the job's end for one who opted out
  while it ran); a pseudonym on the register is never read or written; a register that cannot be read turns the
  store off;
* rows go with their snapshot under D-452's retention;
* class D3: listed in the erasure registry, the record inventory and the support bundle's exclusions;
* ``TB_JUDGED_STORE=off`` turns it off, and the job's report says how many calls were read and how many asked.

Synthetic: scripted model clients, no patient data.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching.cascade.judge import ASKING, Asking
from orchestrator import judged_store
from orchestrator.db import JobDB
from orchestrator.jobs import GuardedLlm
from orchestrator.judged_store import JudgedPairs
from orchestrator.scenarios.evaluate import NoteJudge
from orchestrator.twophase import DeferredVerifier, MemoClient
from tb_common.llm import LlmError, LlmResult

ROOT = Path(__file__).resolve().parents[2]
EXCERPTS = [{"date": "2026-10-01", "note_type": "progress", "text": "History of stroke in 2019.", "did": "d1"}]
VARS = {
    "criterion_text": "Prior stroke",
    "note_question": "Has the patient had a stroke?",
    "index_date": "2026-10-05",
    "excerpts": [{k: e[k] for k in ("date", "note_type", "text")} for e in EXCERPTS],
}
ASK = Asking("p" * 32, "sha256:crit", ("2023-10-05", "2026-10-05"))


class Model:
    """A scripted model: its verdict, its build; counts its calls."""

    def __init__(self, name: str, build: str, verdict: str = "fail", quote: str | None = "History of stroke") -> None:
        self.model = name
        self.build = build
        self.verdict = verdict
        self.quote = quote
        self.calls = 0
        self.fail = False

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        self.calls += 1
        if self.fail:
            raise LlmError("refused")
        data = {"verdict": self.verdict, "confidence": 0.9, "quote": self.quote, "quote_date": "2026-10-01"}
        return LlmResult(data, prompt_id, 4, self.model, "local", "in", f"o{self.calls}", 100, 10, 1, "", self.build)


@contextlib.contextmanager
def asking(a: Asking | None = ASK) -> Iterator[None]:
    tok = ASKING.set(a)
    try:
        yield
    finally:
        ASKING.reset(tok)


@pytest.fixture
def db() -> JobDB:
    d = JobDB()
    with d.tx() as con:
        con.execute("DELETE FROM judged_pairs")
    return d


def _store(db: JobDB, snapshot: str = "2026-10-05", register: frozenset[str] | None = frozenset()) -> JudgedPairs:
    return JudgedPairs(db, snapshot, register, lambda: "2026-10-05T01:00:00")


def _judge(store: JudgedPairs, judge: Model, verifier: Model) -> NoteJudge:
    j = GuardedLlm(judge, lambda: False, None, "judge", pairs=store)
    v = GuardedLlm(verifier, lambda: False, None, "verifier", pairs=store)
    return NoteJudge(lake=None, llm=j, verifier=v, job_id="J")  # type: ignore[arg-type]


def _ask(nj: NoteJudge, variables: dict[str, Any] | None = None) -> Any:
    v = variables or VARS
    return nj.judge_excerpts(str(v["criterion_text"]), str(v["note_question"]), date(2026, 10, 5), EXCERPTS)


def _other(**kw: Any) -> dict[str, Any]:
    return {**VARS, **kw}


# ------------------------------------------------------------------------------------------------ the key
def test_the_key_names_every_part_the_owner_listed(db: JobDB, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(db)
    m = Model("judge-a", "b1")
    with asking():
        assert store.key("judge", m, "judge", VARS, None) is None  # the role has not answered live in this job
        store.asked("judge", m.chat_json("judge", VARS))
        store.asked("verifier", Model("ver-b", "b2").chat_json("judge", VARS))
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None and k == store.key("judge", m, "judge", dict(reversed(list(VARS.items()))), None)
        differ = [
            store.key("verifier", m, "judge", VARS, None),  # the role (and its build)
            store.key("judge", m, "judge", _other(criterion_text="Prior TIA"), None),  # the wording
            store.key("judge", m, "judge", _other(note_question="Any TIA?"), None),  # the note question
            store.key("judge", m, "judge", _other(excerpts=[]), None),  # the excerpt set
            store.key("judge", m, "judge", _other(index_date="2026-10-06"), None),  # the index date
            store.key("judge", m, "judge", VARS, "schema-2"),  # the schema
        ]
        assert k not in differ and None not in differ
        monkeypatch.setattr(judged_store, "NOTE_MASK_VERSION", "6")
        assert store.key("judge", m, "judge", VARS, None) != k  # the note mask's version
        monkeypatch.setattr(judged_store, "NOTE_MASK_VERSION", "5")
        assert store.key("judge", m, "no_such_prompt", VARS, None) is None  # a prompt that cannot be loaded
    for other in (Asking("q" * 32, ASK.criterion_hash, ASK.window), Asking(ASK.pid, "sha256:other", ASK.window),
                  Asking(ASK.pid, ASK.criterion_hash, ("2024-10-05", "2026-10-05"))):  # fmt: skip
        with asking(other):
            assert store.key("judge", m, "judge", VARS, None) not in (k, None)  # pseudonym, canonical hash, window
    assert store.key("judge", m, "judge", VARS, None) is None  # outside the cascade's questions: nothing kept


# ------------------------------------------------------------------------------------------------ what is stored
def test_a_second_job_reads_both_models_answers_and_recombines_them(db: JobDB) -> None:
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2", verdict="pass")  # they disagree
    first = _store(db)
    with asking():
        one = _ask(_judge(first, judge, verifier))
        two = _ask(_judge(first, judge, verifier))  # stored with the build its first answer named: read
    assert one.predicate == "unknown" and one.reason == "disagree" and one.opinions
    assert (judge.calls, verifier.calls) == (1, 1) and db.pair_count() == 2  # one row per model, no verdict row
    assert two.predicate == one.predicate and two.reason == one.reason
    second = _store(db)
    with asking():
        _ask(_judge(second, judge, verifier), _other(criterion_text="Prior TIA"))  # each role answers live once
        again = _ask(_judge(second, judge, verifier))
    assert (judge.calls, verifier.calls) == (2, 2)  # the stored question was read, not asked
    assert (again.predicate, again.reason, again.quote) == (one.predicate, one.reason, one.quote)
    assert again.opinions == one.opinions and second.report() == {"on": True, "read": 2, "live": 2}
    assert again.tokens_in == 0  # read, not asked: no tokens spent in this job
    rows = db._db.fetchall("SELECT role, build_sha, answer FROM judged_pairs ORDER BY role")
    assert {r[0] for r in rows} == {"judge", "verifier"}
    assert all(json.loads(r[2])["data"]["verdict"] in ("pass", "fail") for r in rows)  # each model's own answer


def test_never_a_refusal_a_fault_an_unbuilt_answer_or_another_build(db: JobDB) -> None:
    store = _store(db)
    m = Model("judge-a", "b1")
    with asking():
        store.asked("judge", m.chat_json("judge", VARS))
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None
        store.put(k, "judge", LlmError("refused"))  # a refusal or a fault is an exception, never a result
        store.put(k, "judge", {"verdict": "fail"})
        bad = m.chat_json("judge", VARS)
        bad.data = {"refusal": "cannot help"}  # not a parsed answer
        store.put(k, "judge", bad)
        other = Model("judge-a", "b9").chat_json("judge", VARS)
        store.put(k, "judge", other)  # another build than the one answering the role in this job
        none = Model("judge-a", "").chat_json("judge", VARS)
        store.put(k, "judge", none)  # names no build
    assert db.pair_count() == 0
    failing = Model("judge-a", "b1")
    failing.fail = True
    g = GuardedLlm(failing, lambda: False, None, "judge", pairs=store)
    with asking(), pytest.raises(LlmError):
        g.chat_json("judge", VARS)
    assert db.pair_count() == 0 and store.live == 2


def test_another_patients_row_is_never_read(db: JobDB) -> None:
    store = _store(db)
    m = Model("judge-a", "b1")
    with asking():
        store.asked("judge", m.chat_json("judge", VARS))
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None
        db.pair_put(k, "q" * 32, "2026-10-05", "judge", "b1", json.dumps({"forged": True}), "t")
        assert store.get(k) is None


# ------------------------------------------------------------------------------------------------ bypass and erasure
def test_an_audit_sample_is_asked_live_and_never_stored(db: JobDB) -> None:
    store = _store(db)
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2")
    audit = Asking(ASK.pid, ASK.criterion_hash, ASK.window, audit=True)
    with asking(audit):
        _ask(_judge(store, judge, verifier))
        _ask(_judge(store, judge, verifier))
    assert (judge.calls, verifier.calls) == (2, 2) and db.pair_count() == 0


def test_an_opted_out_patient_is_never_read_or_written_and_their_rows_go(db: JobDB) -> None:
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2")
    with asking():
        s = _store(db)
        _ask(_judge(s, judge, verifier))
        _ask(_judge(s, judge, verifier))
    assert db.pair_count() == 2
    held = _store(db, register=frozenset({ASK.pid}))  # on the register when the job started
    with asking():
        _ask(_judge(held, judge, verifier))
        _ask(_judge(held, judge, verifier))
    assert held.read == 0 and (judge.calls, verifier.calls) == (3, 3)
    off = _store(db, register=None)  # the register did not answer: the store is off for the job
    assert not off.on
    with asking():
        _ask(_judge(off, judge, verifier))
    assert off.read == 0
    late = _store(db)  # a patient who opts out while the job runs: no row left at its end
    assert late.close(lambda: {ASK.pid}) == 2 and db.pair_count() == 0
    from datacore.optout_worker import OWED_TABLES

    orch = dict(OWED_TABLES)["orch"]
    assert any(t == "judged_pairs" and "pid = ANY" in d for t, _, d in orch)  # the opt-out worker deletes them


def test_rows_go_with_their_snapshot(db: JobDB) -> None:
    for snap in ("2026-06-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        db.pair_put(f"k-{snap}", "p" * 32, snap, "judge", "b1", "{}", "t")
    store = _store(db, snapshot="2026-10-05")
    db.pair_touch("k-2026-10-01", "2026-10-05")  # read by a later run: it goes with that run's snapshot
    gone = store.retain(date(2026, 10, 5))
    left = sorted(db.pair_snapshots())
    assert gone == 1 and left == ["2026-06-30", "2026-10-03", "2026-10-04", "2026-10-05"]  # nightly 3 + month end


# ------------------------------------------------------------------------------------------------ two phase, setting
def test_the_deferred_verifier_asks_in_the_questions_context(db: JobDB) -> None:
    seen: list[Asking | None] = []

    class Seeing(Model):
        def chat_json(self, *a: Any, **kw: Any) -> LlmResult:
            seen.append(ASKING.get())
            return super().chat_json(*a, **kw)

    dv = DeferredVerifier(Seeing("ver-b", "b2"), MemoClient(Model("judge-a", "b1")))  # type: ignore[arg-type]
    with asking(), contextlib.suppress(LlmError):
        dv.chat_json("judge", VARS)  # pending: no judge answer to stand in for
    assert dv.resolve(2) == 1 and seen == [ASK]  # answered in a worker thread, in the question's context


def test_the_setting_turns_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judged_store.ENV, raising=False)
    assert judged_store.enabled()
    monkeypatch.setenv(judged_store.ENV, "off")
    assert not judged_store.enabled()
    from orchestrator.jobs import judged_pairs_for

    assert judged_pairs_for(object()) is None
    monkeypatch.setenv(judged_store.ENV, "maybe")
    with pytest.raises(ValueError):
        judged_store.enabled()
    from tb_common.config import DECLARED

    assert DECLARED[judged_store.ENV].default == "on"


def test_it_is_listed_where_the_d3_tables_are() -> None:
    from tb_common.erasure import TABLES

    assert "orch.judged_pairs" in TABLES
    assert "judged_pairs" in (ROOT / "docs/validation/record-inventory.md").read_text(encoding="utf-8")
    assert "judged_pairs" in (ROOT / "tools/support_bundle.py").read_text(encoding="utf-8").split('"""')[1]
    assert "judged_pairs" in (ROOT / "docs/runbook/05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
