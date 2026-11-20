"""Offline CLI measurements on synthetic protocol records.

Public acceptance (separate from these fixtures): 2bcf5ca9:trialbox/.p2b-artefacts/sigir.tgz,
work/raw-traces.json (SHA256 9804533698469dc8e3a695993e629981f7a20b78a5e5bc0fc08d6215ebfeb878),
only ir_extract@4 (200) and concept_map@2 (676). With shipped tables and --synonyms, e20500dc
measures 718 calls (target 609–743): observation 386, condition 254, procedure 59, encounter 14,
claim 5, medication 0. There are 626 stored empty replies, 50 nonempty, and 54 simulated
invocations without a corresponding stored reply. Across 104 studies and
1,165 ordered lines its postprocessor flags 405, 11 below 416, with zero replay gaps. Substituting
only the launch postprocessor (57263236) on the same inputs gives 416 with zero gaps. All 11
criteria that lost concept_unmapped now carry negated_inclusion_presence.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Never, assert_type

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from criteria_compiler.ir_extract import postprocess as pp
from tb_common import llm

from tools import terminology_coverage as coverage

OBS = {"domain": "observation", "name": "synthetic creatinine"}
COND = {"domain": "condition", "name": "synthetic hypertension"}
HIT = {"domain": "observation", "name": "Body weight"}
AGE = {"domain": "demographic", "name": "age"}
CODE = {"system": "http://loinc.org", "code": "2160-0"}

type JsonObject = dict[str, Any]
type Cli = Callable[[Sequence[JsonObject] | None, *tuple[str, ...]], Any]


def criterion(text: str, *candidates: JsonObject) -> JsonObject:
    atoms = [{"domain": c["domain"], "concept": c["name"], "quantifier": "any"} for c in candidates]
    logic: JsonObject = {"domain": "demographic", "age": {"min": 18}}
    if atoms:
        logic = atoms[0] if len(atoms) == 1 else {"op": "and", "args": atoms}
    return {
        "text": text,
        "kind": "inclusion",
        "class": "structured",
        "logic": logic,
        "concept_candidates": list(candidates),
    }


def record(study: str, prompt: str, role: str, inputs: JsonObject, output: JsonObject | None) -> JsonObject:
    return {
        "attributes": {"tb.study_id": study, "tb.prompt": prompt, "tb.role": role},
        "prompt": [{"role": "user", "content": "```json\n" + json.dumps(inputs) + "\n```"}],
        "output": json.dumps(output) if output is not None else None,
    }


def extract(study: str, criteria: list[JsonObject], lines: list[str] | None = None) -> JsonObject:
    if lines is None:
        lines = [c["text"] for c in criteria]
    # Identical ruleset IDs in different study jobs deliberately produce identical local criterion IDs.
    inputs = {"ruleset": "R1", "language": "en", "criteria": [{"text": t, "kind": "inclusion"} for t in lines]}
    return record(study, "ir_extract@4", "extract_criteria", inputs, {"criteria": criteria})


def mapping(study: str, candidate: dict[str, str] = OBS, chosen: bool = False) -> JsonObject:
    code = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10"} if candidate == COND else CODE
    inputs = {"concept": candidate["name"], "domain": candidate["domain"], "candidates": [code]}
    choices = [{**code, "confidence": 1.0}] if chosen else []
    return record(study, "concept_map@2", "concept_select", inputs, {"choices": choices, "needs_review": True})


@pytest.fixture
def cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> Cli:
    def unexpected(*args: object, **kwargs: object) -> Never:
        pytest.fail("attempted a live model call")

    monkeypatch.setattr(llm.LlmClient, "chat_json", unexpected)
    monkeypatch.setattr(llm, "chat_json", unexpected)

    def run(records: Sequence[JsonObject] | None, *args: str) -> str | JsonObject:
        argv = list(args)
        if records is not None:
            path = tmp_path / "protocol.json"
            path.write_text(json.dumps({"traces": records}), encoding="utf-8")
            argv.insert(0, str(path))
        assert coverage.main(argv) == 0
        output = capsys.readouterr().out
        return json.loads(output) if "--json" in args else output

    return run


def test_counts_real_fallback_invocations_including_repetitions(cli: Cli) -> None:
    records = [extract("A", [criterion("A", HIT, AGE, OBS), criterion("B", OBS, COND)])]
    records.append(mapping("A"))
    result = cli(records, "--model-calls", "--json")
    assert result["stored_empty"] == 1 and result["replay_gaps"] == 2
    assert result["model_calls_by_domain"] == {"observation": 2, "condition": 1}
    assert result["model_calls"] == 3
    assert result["table_resolved"] == 1


def test_synonyms_can_resolve_before_fallback(cli: Cli) -> None:
    records = [extract("A", [criterion("A", {**OBS, "synonyms": [HIT["name"]]})])]
    assert cli(records, "--model-calls", "--json")["model_calls"] == 1
    result = cli(records, "--model-calls", "--synonyms", "--json")
    assert (result["model_calls"], result["table_resolved"]) == (0, 1)


def test_existing_site_table_is_read_only(cli: Cli, tmp_path: Path) -> None:
    where = tmp_path / "installed"
    where.mkdir()
    table = where / "site_synthetic.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "local_code": "S1",
                    "local_name": OBS["name"],
                    "system": "loinc",
                    "code": CODE["code"],
                    "display": "Synthetic lab",
                }
            ]
        ),
        table,
    )
    manifest = {"tables": {table.stem: {"sha256": hashlib.sha256(table.read_bytes()).hexdigest(), "rows": 1}}}
    (where / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def snapshot() -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in where.iterdir()}

    before = snapshot()
    records = [extract("A", [criterion("A", OBS)])]
    assert cli(records, "--model-calls", "--json")["model_calls"] == 1
    for _ in range(2):
        result = cli(records, "--model-calls", "--installed", str(where), "--json")
        assert (result["model_calls"], result["table_resolved"]) == (0, 1)
        assert snapshot() == before


@pytest.mark.parametrize("missing_record", [False, True])
def test_demand_empty_nonempty_and_unknown_are_independent(cli: Cli, missing_record: bool) -> None:
    other = {**OBS, "name": "other creatinine"}
    records = [
        extract("A", [criterion("A", OBS), criterion("B", other), criterion("C", COND)]),
        mapping("A"),
        mapping("A", other, chosen=True),
    ]
    if missing_record:
        records.append({**mapping("A", COND), "output": None})
    counts = cli(records, "--model-calls", "--json")
    assert counts["model_calls"] == 3
    assert (counts["stored_empty"], counts["stored_nonempty"], counts["replay_gaps"]) == (1, 1, 1)
    assert counts["stored_unknown"] == int(missing_record)
    replay = cli(records, "--replay-postprocess", "--json")
    assert replay["replay_gaps"] == 1
    assert replay["concept_unmapped"] is None
    assert replay["by_study"]["A"]["concept_unmapped"] is None


@pytest.mark.parametrize("chosen_b", [False, True])
def test_flag_is_scoped_to_study_and_repeatable(cli: Cli, chosen_b: bool) -> None:
    line = criterion("A", OBS)
    records = [extract("A", [line]), extract("B", [line]), mapping("A"), mapping("B", chosen=chosen_b)]
    for _ in range(2):
        result = cli(records, "--replay-postprocess", "--json")
        assert result["replay_gaps"] == 0
        assert {s: row["concept_unmapped"] for s, row in result["by_study"].items()} == {"A": 1, "B": int(not chosen_b)}
        assert result["concept_unmapped"] == (1 if chosen_b else 2)


def test_replay_aligns_parts_and_retries_before_counting_final_flags(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    first = extract("A", [criterion("A", HIT)], lines=["A", "B"])
    last = extract("A", [criterion("C")])
    retry = extract("A", [criterion("B", OBS, COND), criterion("A", OBS)])
    records = [{**retry, "ts": "3"}, {**first, "ts": "1"}, {**last, "ts": "2"}, mapping("A"), mapping("A", COND)]
    final: list[tuple[str, bool]] = []
    real = pp.postprocess

    def observe(*args: Any, **kwargs: Any) -> pp.PostResult:
        post = real(*args, **kwargs)
        final.extend((c.text, "concept_unmapped" in (c.flags or [])) for c in post.criteria)
        return post

    monkeypatch.setattr(pp, "postprocess", observe)
    result = cli(records, "--replay-postprocess", "--json")
    assert final == [("A", False), ("B", True), ("C", False)]
    assert result["by_study"]["A"] == {"criteria": 3, "concept_unmapped": 1, "replay_gaps": 0}
    assert result["concept_unmapped"] == 1


def test_repeated_line_in_a_new_part_keeps_its_own_reply(cli: Cli) -> None:
    records = [
        extract("A", [criterion("A", OBS), criterion("B")]),
        extract("A", [criterion("A", HIT), criterion("C")]),
        mapping("A"),
    ]
    result = cli(records, "--replay-postprocess", "--json")
    assert result["by_study"]["A"] == {"criteria": 4, "concept_unmapped": 1, "replay_gaps": 0}


def test_omitted_line_needs_a_stored_retry(cli: Cli) -> None:
    batch = extract("A", [criterion("A", HIT)], lines=["A", "B"])
    partial = cli([batch], "--replay-postprocess", "--json")
    assert partial["concept_unmapped"] is None and partial["replay_gaps"] == 1
    complete = cli([batch, extract("A", [], lines=["B"])], "--replay-postprocess", "--json")
    assert complete["by_study"]["A"] == {"criteria": 2, "concept_unmapped": 0, "replay_gaps": 0}


def test_lost_extraction_only_counts_unrecovered_lines(cli: Cli) -> None:
    records = [{**extract("A", [], lines=["A", "B"]), "output": None}, extract("A", [criterion("B", HIT)])]
    result = cli(records, "--replay-postprocess", "--json")
    assert result["concept_unmapped"] is None
    assert result["replay_gaps"] == 1


def test_extraction_keeps_a_split_line_beside_a_valid_answer() -> None:
    batch = assert_type(
        extract("A", [criterion("A", HIT), criterion("B", OBS), criterion("B", COND)], lines=["A", "B"]),
        dict[str, Any],
    )
    stored = coverage._protocol_records({"traces": [batch]})
    _, extracted, gaps = coverage._extraction(stored, "A")
    assert gaps == 0
    assert [(c.text, c.class_) for c in extracted.criteria] == [("A", "structured"), ("B", "human")]


def test_legacy_trace_table_json_and_weighted_csv(cli: Cli, tmp_path: Path) -> None:
    records = [
        {
            "attributes": {"tb.role": "extract_criteria"},
            "output": json.dumps({"criteria": [{"concept_candidates": [HIT] * 3}]}),
        }
    ]
    human = cli(records)
    assert "| observation | 3 | 3 |" in human and "| **all** | **3** | **3 (100.0 %)** |" in human
    result = cli(records, "--json")
    assert result == {
        "calls": 1,
        "candidates": 3,
        "by_domain": {"observation": [3, 3]},
        "methods": {"exact": 3},
        "for_review": {"observation": 0},
        "unmapped": {},
    }
    path = tmp_path / "concepts.csv"
    cli(records, "--write-concepts", str(path))
    assert list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))) == [{**HIT, "count": "3"}]
    assert cli(None, "--concepts", str(path), "--json") == {**result, "calls": None}


@pytest.mark.parametrize(
    ("mode", "labels"),
    [
        ("--model-calls", ["Simulated model calls", "模擬模型呼叫次數", "モデル呼び出し推定回数"]),
        (
            "--replay-postprocess",
            ["Criteria flagged concept_unmapped", "標記 concept_unmapped 的條件數", "concept_unmapped が付いた基準数"],
        ),
    ],
)
def test_localized_reports_share_one_json_schema(cli: Cli, mode: str, labels: list[str]) -> None:
    records = [extract("A", [criterion("A", OBS)]), mapping("A")]
    results = []
    for lang, label in zip(("en", "zh-TW", "ja"), labels, strict=True):
        assert label in cli(records, mode, "--lang", lang)
        results.append(cli(records, mode, "--lang", lang, "--json"))
    assert results[0] == results[1] == results[2]
