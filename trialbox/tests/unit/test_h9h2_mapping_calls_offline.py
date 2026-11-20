"""9h-2 (D-1350): mapping calls and unmapped criteria counted offline, each record kept to its study.

The records here are made up (a synthetic analyte, LOINC-shaped codes) or read from the public replay slice
``tests/fixtures/public_accuracy_p1b/replay_slice.json`` (launch P1b: SIGIR 2016 and JMED-Personas, see its README).
No model, no network: every test fails on a socket connect. Each test names the review finding of draft #1244 (head
``6ce361cf``) it closes.
"""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools import terminology_coverage
from tools import terminology_replay as tr
from tools.public_accuracy import rerun

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "tests" / "fixtures" / "public_accuracy_p1b" / "replay_slice.json"
LOINC = "http://loinc.org"
A, B = "01SYNTHSTUDYAAAAAAAAAAAAAA", "01SYNTHSTUDYBBBBBBBBBBBBBB"
CANDS = [{"code": "2160-0", "system": LOINC, "display": "Creatinine"}]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("9h-2 counts offline: no socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _block(v: dict[str, Any]) -> str:
    return "INPUT:\n```json\n" + json.dumps(v) + "\n```"


def cmap(
    study: str | None,
    out: Any,
    cands: list[dict[str, Any]] = CANDS,
    concept: str = "creatinine",
    extra: list[dict[str, Any]] | None = None,
    ts: str = "1",
) -> dict[str, Any]:
    attrs = {"tb.prompt": "concept_map@2"} | ({"tb.study_id": study} if study is not None else {})
    v = {"concept": concept, "domain": "observation", "candidates": cands}
    rec = {"ts": ts, "attributes": attrs, "prompt": [{"role": "user", "content": _block(v)}, *(extra or [])]}
    if out is not None:
        rec["output"] = out if isinstance(out, str) else json.dumps(out)
    return rec


def chosen(code: str) -> dict[str, Any]:
    return {"choices": [{"code": code, "system": LOINC, "confidence": 0.95}], "needs_review": False}


EMPTY = {"choices": [], "needs_review": True}


def extract(study: str | None, out: Any = None, ts: str = "0") -> dict[str, Any]:
    line = {"text": "Serum creatinine above 2 mg/dL", "source_ref": "Inclusion criteria #1", "kind": "inclusion"}
    crit = {
        **line,
        "class": "mixed",
        "concept_candidates": [{"domain": "observation", "name": "creatinine", "synonyms": []}],
    }
    attrs = {"tb.prompt": "ir_extract@4"} | ({"tb.study_id": study} if study is not None else {})
    out = {"criteria": [crit]} if out is None else out
    return {
        "ts": ts,
        "attributes": attrs,
        "prompt": [{"role": "user", "content": _block({"criteria": [line]})}],
        "output": out if isinstance(out, str) else json.dumps(out),
    }


class Term:
    """A mapper that always asks the model, with one candidate (the hook's contract: ``llm(name, domain, cands)``)."""

    def map(self, domain: str, name: str, synonyms: Any = None, llm: Any = None) -> Any:
        cands = [SimpleNamespace(code=c["code"], system=c["system"]) for c in CANDS]
        choices, _ = llm(name, domain, cands)
        return SimpleNamespace(concepts=choices)


# ---------------------------------------------------------------- High 1: study isolation
def test_two_studies_same_criterion_different_choices_stay_apart() -> None:
    """High 1. Study A chose 2160-0 for creatinine, study B chose nothing for the same words and candidates, and a
    record without a study id chose 2160-0 too. Each study gets its own answer; the record without a study id
    answers nothing and is counted apart."""
    traces = [
        extract(A),
        extract(B),
        extract(None),
        extract(""),
        cmap(A, chosen("2160-0")),
        cmap(B, EMPTY),
        cmap(None, chosen("2160-0")),
        cmap("  ", chosen("2160-0")),
    ]
    r = tr.model_calls(traces, Term())
    sim = r["simulated"]
    assert sim["by_study"][A] | {"calls_by_domain": None} == {
        "extract_records": 1,
        "extract_invalid": 0,
        "drafted": 1,
        "resolved": 1,
        "calls": 1,
        "not_recorded": 0,
        "calls_by_domain": None,
    }
    assert (sim["by_study"][B]["resolved"], sim["by_study"][B]["not_recorded"]) == (0, 0)
    assert set(sim["by_study"]) == {A, B}  # "" and "  " are no study
    assert sim["no_study_id"] == {"extract_records": 2, "mapped": 0}
    rec = r["recorded"]
    assert (rec["by_study"][A]["mapped"], rec["by_study"][B]["unmapped"]) == (1, 1)
    assert rec["no_study_id"]["calls"] == rec["no_study_id"]["mapped"] == 2
    assert rec["total"]["calls"] == rec["records"] == 4


def test_a_study_without_its_own_reply_is_not_answered_by_another() -> None:
    """High 1. Study B's call has no reply of its own: A's reply and the study-less one do not answer it."""
    traces = [extract(A), extract(B), cmap(A, chosen("2160-0")), cmap(None, chosen("2160-0"))]
    sim = tr.model_calls(traces, Term())["simulated"]["by_study"]
    assert (sim[B]["calls"], sim[B]["not_recorded"], sim[B]["resolved"]) == (1, 1, 0)
    assert sim[A]["resolved"] == 1


def test_the_replay_model_answers_from_its_own_study_only() -> None:
    """High 1, ``--replay``: the compile's model for B never reads A's reply nor a study-less one."""
    recs = tr.split([cmap(A, chosen("2160-0")), cmap(None, chosen("2160-0")), cmap(B, EMPTY)])
    variables = {"concept": "Creatinine", "domain": "observation", "candidates": CANDS}
    model_a = tr.StudyReplayModel(recs.by_study[A])
    model_b = tr.StudyReplayModel(recs.by_study[B])
    assert model_a.chat_json("concept_map", variables).data["choices"][0]["code"] == "2160-0"
    assert model_b.chat_json("concept_map", variables).data["choices"] == []
    assert model_b.concepts_not_stored == []  # B's own empty reply answered it
    assert model_b.chat_json("concept_map", variables).data["choices"] == []
    assert model_b.concepts_not_stored == ["Creatinine"]  # one reply, one call: the second is not recorded
    assert len(recs.no_study) == 1


def test_replay_on_the_public_slice_keeps_a_study_less_record_apart() -> None:
    """High 1 on recorded public data: the jmed slice's two studies, with one study's mapping records stripped of
    their study id. That study's count becomes unknown; the other's is unchanged; the stripped records answer
    nothing and are counted in ``no_study_id``."""
    traces = tr.load(SLICE, "jmed")
    whole = tr.replay(traces)
    dm, ht = sorted(whole["by_study"])
    cut = copy.deepcopy(traces)
    stripped = 0
    for rec in cut:
        if rec["attributes"].get("tb.study_id") == dm and tr.step(rec) == "map":
            rec["attributes"]["tb.study_id"] = ""
            stripped += 1
    assert stripped
    part = tr.replay(cut)
    assert part["by_study"][ht] == whole["by_study"][ht]
    assert part["by_study"][dm]["concept_unmapped"] is None
    assert part["by_study"][dm]["not_recorded"] == stripped
    assert part["concept_unmapped"] is None
    assert part["no_study_id"] == {"records": stripped, "compiled": 0}
    rec = tr.recorded(cut)
    assert rec["no_study_id"]["calls"] == stripped and rec["by_study"][dm]["calls"] == 0


# ---------------------------------------------------------------- High 2: the run's own count beside today's
def test_replay_gives_the_runs_stored_count_beside_todays() -> None:
    """High 2. The stored figure (the run's ``answers.json``) is given beside the re-compile's, by ruleset, so the
    historical baseline is reproducible through the command."""
    sl = json.loads(SLICE.read_text(encoding="utf-8"))["sets"]["sigir"]
    r = tr.replay(tr.load(SLICE, "sigir"), sl["answers"])
    by_rs = {s["ruleset"]: (s["concept_unmapped"], s["stored_concept_unmapped"]) for s in r["by_study"].values()}
    assert by_rs == {
        "SM2NCT00277680": (3, 4),
        "SM2NCT00493103": (2, 0),
        "SM2NCT00606840": (1, 1),
        "SM2NCT01260883": (2, 4),
        "SM2NCT01723137": (0, 0),
        "SM2NCT02378311": (None, 0),
    }
    assert r["stored_concept_unmapped"] == 9
    assert r["concept_unmapped"] is None  # one study did not compile again: the total is unknown, not a sum


# ---------------------------------------------------------------- Mediums
def test_inputs_are_read_from_the_first_user_message_on_a_repair_retry() -> None:
    """Medium 3. A schema-repair retry appends the model's answer and a correction: the inputs are still read."""
    retry = cmap(
        A,
        chosen("2160-0"),
        extra=[
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "Your answer did not match the schema."},
        ],
    )
    rec = tr.recorded([retry])
    assert rec["by_study"][A]["by_domain"] == {"observation": 1}
    replies = tr.StudyReplies([retry])
    assert replies.take("creatinine", "observation", CANDS) is not None


def test_same_words_at_two_references_are_two_lines() -> None:
    """Medium 4. Two parts asked apart, the same words at ``#1`` and ``#12``: two lines, not a retry of one."""

    def part(ref: str) -> dict[str, Any]:
        line = {"text": "Age 18 or over", "source_ref": ref, "kind": "inclusion"}
        return {
            "attributes": {"tb.prompt": "ir_extract@4", "tb.study_id": A},
            "output": '{"criteria": []}',
            "prompt": [{"content": _block({"ruleset": "R", "criteria": [line]})}],
        }

    stored = rerun.Stored(by_job={A: [part("Inclusion criteria #1"), part("Inclusion criteria #12")]})
    _, _, lines, _ = rerun.protocol_lines(stored, A)
    assert [ln["source_ref"] for ln in lines] == ["Inclusion criteria #1", "Inclusion criteria #12"]
    retry = rerun.Stored(by_job={A: [part("Inclusion criteria #1"), part("Inclusion criteria #1")]})
    assert len(rerun.protocol_lines(retry, A)[2]) == 1  # a retry of the same line stays one line


def test_replay_runs_the_compilers_own_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mediums 5 and 6. The replay does not align batches or retries itself: it compiles through
    ``Compiler.compile``, whose alignment and omission retry decide the criteria."""
    from criteria_compiler.service import Compiler

    seen: list[str] = []
    real = Compiler.compile

    def spy(self: Any, req: Any) -> Any:
        seen.append(req.job_id)
        return real(self, req)

    monkeypatch.setattr(Compiler, "compile", spy)
    r = tr.replay(tr.load(SLICE, "jmed"))
    assert sorted(seen) == sorted(r["by_study"]) and len(seen) == 2


def test_an_empty_choice_for_other_candidates_answers_nothing() -> None:
    """Medium 7. A stored rejection of 29463-7 is not a rejection of 2160-0."""
    other = [{"code": "29463-7", "system": LOINC, "display": "Body weight"}]
    replies = tr.StudyReplies([cmap(A, EMPTY, cands=other)])
    assert replies.take("creatinine", "observation", CANDS) is None
    assert sum(replies.not_recorded.values()) == 1


def test_each_call_takes_the_reply_to_its_own_candidates() -> None:
    """Medium 8. Calls offering {2160-0, 4548-4} then {2160-0}; replies stored for {2160-0} (2160-0) then for
    {2160-0, 4548-4} (4548-4). No greedy match: each call gets the reply to its own list, none is left without."""
    two = [*CANDS, {"code": "4548-4", "system": LOINC, "display": "HbA1c"}]
    replies = tr.StudyReplies([cmap(A, chosen("2160-0"), ts="1"), cmap(A, chosen("4548-4"), cands=two, ts="2")])
    first = replies.take("creatinine", "observation", two)
    second = replies.take("creatinine", "observation", CANDS)
    assert first is not None and second is not None
    assert (first.choices[0].code, second.choices[0].code) == ("4548-4", "2160-0")
    assert sum(replies.not_recorded.values()) == 0


def test_a_schema_rejected_attempt_neither_answers_nor_overrides_its_retry() -> None:
    """Medium 9. ``{"choices": []}`` lacks the required ``needs_review``: the client refused it; its retry stands."""
    recs = [cmap(A, {"choices": []}, ts="1"), cmap(A, chosen("2160-0"), ts="2")]
    reply = tr.StudyReplies(recs).take("creatinine", "observation", CANDS)
    assert reply is not None and reply.choices[0].code == "2160-0"
    row = tr.recorded(recs)["by_study"][A]
    assert (row["invalid"], row["mapped"], row["unmapped"]) == (1, 1, 0)


def test_a_fenced_reply_is_read_as_the_client_reads_it() -> None:
    """Medium 10. The model client accepts a reply in a ```json fence; so does the count."""
    fenced = "```json\n" + json.dumps(chosen("2160-0")) + "\n```"
    assert tr.recorded([cmap(A, fenced)])["by_study"][A]["mapped"] == 1
    assert tr.StudyReplies([cmap(A, fenced)]).take("creatinine", "observation", CANDS) is not None


def test_a_schema_invalid_extraction_does_not_stop_the_count() -> None:
    """Medium 11. ``{"criteria": [null]}`` then a valid retry: the first is counted invalid, the retry is read."""
    traces = [extract(A, {"criteria": [None]}, ts="0"), extract(A, ts="1"), cmap(A, chosen("2160-0"))]
    row = tr.model_calls(traces, Term())["simulated"]["by_study"][A]
    assert (row["extract_records"], row["extract_invalid"], row["drafted"], row["resolved"]) == (2, 1, 1, 1)


# ---------------------------------------------------------------- Low 12 and the sums
def test_a_role_only_mapping_record_is_counted() -> None:
    """Low 12. A redacted record with ``tb.role`` ``concept_select`` and no prompt or output is a recorded call
    whose reply is unknown."""
    rec = {"attributes": {"tb.role": "concept_select", "tb.study_id": A}}
    row = tr.recorded([rec])["by_study"][A]
    assert (row["calls"], row["invalid"], row["by_domain"]) == (1, 1, {"unknown": 1})


def test_every_record_lands_in_one_bucket_and_impossible_counts_are_refused() -> None:
    traces = [
        cmap(A, chosen("2160-0")),
        cmap(A, EMPTY),
        cmap(B, "not json"),
        cmap(None, EMPTY),
        extract(A),
        {"attributes": {"tb.prompt": "judge@5", "tb.study_id": A}},
    ]
    r = tr.recorded(traces)
    assert r["records"] == r["total"]["calls"] == 4
    assert {k: r["total"][k] for k in tr.OUTCOMES} == {"mapped": 1, "unmapped": 2, "invalid": 1}
    for broken in ("outcome", "total", "records", "negative"):
        bad = copy.deepcopy(r)
        if broken == "outcome":
            bad["by_study"][A]["mapped"] += 1
        elif broken == "total":
            bad["total"]["unmapped"] += 1
        elif broken == "records":
            bad["records"] += 1
        else:
            bad["no_study_id"].update(calls=-1, unmapped=-1, by_domain={"observation": -1})
        with pytest.raises(ValueError):
            tr.check(bad)


def test_the_command_reads_one_set_of_the_slice(capsys: pytest.CaptureFixture[str]) -> None:
    assert terminology_coverage.main([str(SLICE), "--set", "jmed", "--model-calls"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recorded"]["total"]["calls"] == out["recorded"]["records"] == 2
    with pytest.raises(SystemExit):
        terminology_coverage.main([str(SLICE), "--model-calls"])  # a slice needs --set
