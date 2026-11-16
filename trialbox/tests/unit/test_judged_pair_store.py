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

And the adversarial review's findings (2026-11-16): the store is on for a new job (its snapshot is read when first
used); a wake check's canary call below a question is never keyed; the role's build follows its latest live answer;
the register is read before every write and read hit; retention is the site's rule over every night, at each job's
end, the store on or off; the cascade's role is in the key; a fault of the store asks live.

Synthetic: scripted model clients, no patient data.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from matching.cascade.judge import ASKING, Asking, question_digest
from orchestrator import judged_store
from orchestrator.db import JobDB
from orchestrator.jobs import GuardedLlm
from orchestrator.judged_store import JudgedPairs
from orchestrator.scenarios.evaluate import NoteJudge
from orchestrator.twophase import DeferredVerifier, MemoClient
from tb_common.llm import LlmError, LlmResult

ROOT = Path(__file__).resolve().parents[2]
EXCERPTS = [{"date": "2026-10-01", "note_type": "progress", "text": "History of stroke in 2019.", "did": "d1"}]
VARS: dict[str, Any] = {
    "criterion_text": "Prior stroke",
    "note_question": "Has the patient had a stroke?",
    "index_date": "2026-10-05",
    "excerpts": [{k: e[k] for k in ("date", "note_type", "text")} for e in EXCERPTS],
}
QUESTION = question_digest(VARS["criterion_text"], VARS["note_question"], VARS["index_date"], EXCERPTS)
ASK = Asking("p" * 32, "sha256:crit", ("2023-10-05", "2026-10-05"), question=QUESTION)


def ask_for(**kw: Any) -> Asking:
    """The cascade's context for a question with ``kw`` changed in its variables."""
    v = {**VARS, **kw}
    q = question_digest(str(v["criterion_text"]), str(v["note_question"]), str(v["index_date"]), list(v["excerpts"]))
    return Asking(ASK.pid, ASK.criterion_hash, ASK.window, question=q)


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


def _register(register: frozenset[str] | None) -> Any:
    def now() -> frozenset[str]:
        if register is None:
            raise RuntimeError("the register did not answer")
        return register

    return now


def _store(
    db: Any, snapshot: str = "2026-10-05", register: frozenset[str] | None = frozenset(), on: bool = True
) -> JudgedPairs:
    return JudgedPairs(db, lambda: snapshot, _register(register), lambda: "2026-10-05T01:00:00", on=on)


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
def _learn(store: JudgedPairs, label: str, m: Model) -> None:
    store.asked(label, m.chat_json("judge", VARS), VARS)


def test_the_key_names_every_part_the_owner_listed(db: JobDB, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(db)
    m = Model("judge-a", "b1")
    with asking():
        assert store.key("judge", m, "judge", VARS, None) is None  # the role has not answered live in this job
        _learn(store, "judge", m)
        _learn(store, "verifier", Model("ver-b", "b2"))
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None and k == store.key("judge", m, "judge", dict(reversed(list(VARS.items()))), None)
        assert store.key("verifier", m, "judge", VARS, None) not in (k, None)  # the client's role (and its build)
        assert store.key("judge", m, "judge", VARS, "schema-2") not in (k, None)  # the schema
        monkeypatch.setattr(judged_store, "NOTE_MASK_VERSION", "6")
        assert store.key("judge", m, "judge", VARS, None) not in (k, None)  # the note mask's version
        monkeypatch.setattr(judged_store, "NOTE_MASK_VERSION", "5")
        assert store.key("judge", m, "no_such_prompt", VARS, None) is None  # a prompt that cannot be loaded
    change: dict[str, Any]
    for change in ({"criterion_text": "Prior TIA"}, {"note_question": "Any TIA?"}, {"excerpts": []},
                   {"index_date": "2026-10-06"}):  # fmt: skip
        v = {**VARS, **change}
        with asking(ask_for(**change)):
            assert store.key("judge", m, "judge", v, None) not in (k, None), change
    for other in (Asking("q" * 32, ASK.criterion_hash, ASK.window, question=QUESTION),
                  Asking(ASK.pid, "sha256:other", ASK.window, question=QUESTION),
                  Asking(ASK.pid, ASK.criterion_hash, ("2024-10-05", "2026-10-05"), question=QUESTION),
                  Asking(ASK.pid, ASK.criterion_hash, ASK.window, role="second_opinion", question=QUESTION)):  # fmt: skip
        with asking(other):  # pseudonym, canonical hash, window, the cascade's role
            assert store.key("judge", m, "judge", VARS, None) not in (k, None)
    assert store.key("judge", m, "judge", VARS, None) is None  # outside the cascade's questions: nothing kept


def test_a_call_that_is_not_the_question_is_never_keyed_stored_or_counted(db: JobDB) -> None:
    """Review finding 2: a wake check's canary case is asked below a patient's question (same thread)."""
    store = _store(db)
    m = Model("judge-a", "b1")
    canary = {**VARS, "criterion_text": "Canary case 3", "excerpts": [{"date": "2026-01-01", "note_type": "x",
                                                                       "text": "Synthetic."}]}  # fmt: skip
    g = GuardedLlm(m, lambda: False, None, "judge", pairs=store)
    with asking():
        g.chat_json("judge", canary)
        g.chat_json("judge", canary)
        assert store.key("judge", m, "judge", canary, None) is None
    assert m.calls == 2 and db.pair_count() == 0 and store.live == 0 and not store._build  # nothing learnt either


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
    other = {"criterion_text": "Prior TIA"}
    with asking(ask_for(**other)):
        _ask(_judge(second, judge, verifier), _other(**other))  # each role answers live once in the new job
    with asking():
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
        _learn(store, "judge", m)
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None
        store.put(k, "judge", LlmError("refused"), VARS)  # a refusal or a fault is an exception, never a result
        store.put(k, "judge", {"verdict": "fail"}, VARS)
        bad = m.chat_json("judge", VARS)
        bad.data = {"refusal": "cannot help"}  # not a parsed answer
        store.put(k, "judge", bad, VARS)
        store.put(k, "judge", Model("judge-a", "b9").chat_json("judge", VARS), VARS)  # not the role's build now
        store.put(k, "judge", Model("judge-a", "").chat_json("judge", VARS), VARS)  # names no build
    assert db.pair_count() == 0
    failing = Model("judge-a", "b1")
    failing.fail = True
    g = GuardedLlm(failing, lambda: False, None, "judge", pairs=store)
    with asking(), pytest.raises(LlmError):
        g.chat_json("judge", VARS)
    assert db.pair_count() == 0 and store.live == 2


def test_the_roles_build_follows_its_latest_live_answer(db: JobDB) -> None:
    """Review finding 3: a rollout serves build B after build A; B's answers are stored and read, not A's."""
    store = _store(db)
    a, b = Model("judge-a", "bA"), Model("judge-a", "bB")
    with asking():
        _learn(store, "judge", a)
        ka = store.key("judge", a, "judge", VARS, None)
        _learn(store, "judge", b)
        kb = store.key("judge", b, "judge", VARS, None)
        assert ka != kb and kb is not None
        store.put(kb, "judge", b.chat_json("judge", VARS), VARS)
        store.put(kb, "judge", a.chat_json("judge", VARS), VARS)  # the old build's answer: not stored
    assert db._db.fetchall("SELECT build_sha FROM judged_pairs") == [("bB",)]


def test_another_patients_row_is_never_read(db: JobDB) -> None:
    store = _store(db)
    m = Model("judge-a", "b1")
    with asking():
        _learn(store, "judge", m)
        k = store.key("judge", m, "judge", VARS, None)
        assert k is not None
        db.pair_put(k, "q" * 32, "2026-10-05", "judge", "b1", json.dumps({"forged": True}), "t")
        assert store.get(k, VARS) is None


# ------------------------------------------------------------------------------------------------ bypass and erasure
def test_an_audit_sample_is_asked_live_and_never_stored(db: JobDB) -> None:
    store = _store(db)
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2")
    audit = Asking(ASK.pid, ASK.criterion_hash, ASK.window, audit=True, question=QUESTION)
    with asking(audit):
        _ask(_judge(store, judge, verifier))
        _ask(_judge(store, judge, verifier))
    assert (judge.calls, verifier.calls) == (2, 2) and db.pair_count() == 0


def test_an_opted_out_patient_is_never_read_or_written_and_their_rows_go(db: JobDB) -> None:
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2")
    register: set[str] = set()
    s = JudgedPairs(db, lambda: "2026-10-05", lambda: frozenset(register), lambda: "t")
    with asking():
        _ask(_judge(s, judge, verifier))
        _ask(_judge(s, judge, verifier))
        assert db.pair_count() == 2 and s.read == 2
        register.add(ASK.pid)  # the patient opts out while the job runs
        _ask(_judge(s, judge, verifier))
    assert s.read == 2 and (judge.calls, verifier.calls) == (2, 2)  # never read after the opt-out: asked live
    assert db.pair_count() == 2  # and nothing new written
    s.close(date(2026, 10, 5))  # however the job ends, its end deletes the rows it wrote for them
    assert db.pair_count() == 0
    down = _store(db, register=None)  # a register that does not answer: no read, no write
    with asking():
        _ask(_judge(down, judge, verifier))
        _ask(_judge(down, judge, verifier))
    assert db.pair_count() == 0 and down.read == 0
    from datacore.optout_worker import OWED_TABLES

    orch = dict(OWED_TABLES)["orch"]
    assert any(t == "judged_pairs" and "pid = ANY" in d for t, _, d in orch)  # the opt-out worker deletes them


def test_rows_go_with_their_snapshot_under_the_sites_rule_store_on_or_off(db: JobDB) -> None:
    """Review finding 5: the rule over every night, not the store's own sparse snapshots; at each job's end."""
    for snap in ("2026-01-05", "2026-03-31", "2026-06-02", "2026-10-02", "2026-10-03", "2026-10-04"):
        db.pair_put(f"k-{snap}", "p" * 32, snap, "judge", "b1", "{}", "t")
    off = _store(db, snapshot="2026-10-05", on=False)
    assert off.close(date(2026, 10, 5)) == {"on": False, "read": 0, "live": 0}  # the report says it was off
    assert sorted(db.pair_snapshots()) == ["2026-03-31", "2026-10-03", "2026-10-04"]  # nightly 3 and month ends
    assert judged_store.kept_snapshots(["2026-01-05", "2026-03-10"], "2026-06-02", date(2026, 6, 2), 3, 36) == {
        "2026-06-02"
    }  # neither is a night the lake keeps
    late = _store(db, snapshot="")  # the job has not pinned its snapshot: nothing is swept, the store is not on
    assert not late.on and late.retain(date(2026, 10, 5)) == 0


def test_the_store_is_on_once_the_job_pins_its_snapshot(db: JobDB, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 1: SCREEN builds its services before it pins the snapshot."""
    from types import SimpleNamespace

    from orchestrator.jobs import judged_pairs_for

    monkeypatch.delenv(judged_store.ENV, raising=False)
    job = SimpleNamespace(snapshot_date=None)
    ctx = SimpleNamespace(
        orch=SimpleNamespace(db=db, _now=lambda: datetime(2026, 10, 5, 1)),
        job=job,
        decision=SimpleNamespace(register_now=frozenset),
        cfg=SimpleNamespace(settings=SimpleNamespace(retention=SimpleNamespace(nightly_snapshots=5,
                                                                               month_end_snapshots_months=12))),
    )  # fmt: skip
    pairs = judged_pairs_for(ctx)
    assert not pairs.on and pairs.retention == (5, 12)
    job.snapshot_date = date(2026, 10, 5)  # pinned after the services were built
    assert pairs.on and pairs.snapshot == "2026-10-05"
    monkeypatch.setenv(judged_store.ENV, "off")
    assert not judged_pairs_for(ctx).on


def test_a_fault_of_the_store_asks_live(db: JobDB) -> None:
    class Broken:
        def __getattr__(self, name: str) -> Any:
            def fail(*a: Any, **k: Any) -> Any:
                raise RuntimeError("database down")

            return fail

    store = _store(Broken())
    judge, verifier = Model("judge-a", "b1"), Model("ver-b", "b2")
    with asking():
        r1 = _ask(_judge(store, judge, verifier))
        r2 = _ask(_judge(store, judge, verifier))
    assert r1.predicate == r2.predicate == "fail" and (judge.calls, verifier.calls) == (2, 2)
    assert store.close(date(2026, 10, 5))["read"] == 0


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


def test_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judged_store.ENV, raising=False)
    assert judged_store.enabled()
    monkeypatch.setenv(judged_store.ENV, "off")
    assert not judged_store.enabled()
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
