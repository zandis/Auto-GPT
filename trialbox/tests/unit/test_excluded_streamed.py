"""NEW-B-48 (D-749): the excluded patients are written one line each (JSONL) and read without loading the list.

T-694 part 5 (F-36 of ``docs/reviews/2026-11-11-scale-timeouts.md``): SCREEN wrote every excluded patient into one
JSON document (``json.dumps(indent=1)``), and every micro-batch read the whole document again to collect patient
ids (85 MB at 50,000 patients, 850 MB at 500,000, five to ten times that as Python objects). The format, posted for
lane C2's readers on the integrator's inbox: a header line, one line per excluded patient, an end line with the
count (a file without it was cut off). Synthetic ids only."""

from __future__ import annotations

import json

import pytest
from orchestrator import excluded

HEADER = {"ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-11-15", "snapshot": "2026-11-14",
          "judging": {}, "confirmed_facts": "read", "coded_values": "read"}  # fmt: skip
ROWS = [{"pid": f"P-{i:03d}", "criteria": [{"id": "GZQO-EXC-01", "source": "coded"}], "actions": []} for i in range(5)]


def test_the_file_is_a_header_a_line_per_patient_and_an_end() -> None:
    data = excluded.write_jsonl(HEADER, iter(ROWS))
    lines = [json.loads(x) for x in data.decode("utf-8").splitlines()]
    assert lines[0] == {"kind": "header", "format": 1, **HEADER}
    assert [x for x in lines[1:-1]] == [{"kind": "row", **r} for r in ROWS]
    assert lines[-1] == {"kind": "end", "rows": 5}
    assert all(list(json.loads(x)) == sorted(json.loads(x)) for x in data.decode().splitlines())  # keys sorted


def test_reading_it_back_gives_the_document_of_old() -> None:
    doc = excluded.read(excluded.write_jsonl(HEADER, iter(ROWS)), "excluded_GZQO_v1.0.0.jsonl")
    assert doc == {**HEADER, "rows": ROWS}
    old = json.dumps({**HEADER, "rows": ROWS}).encode()
    assert excluded.read(old, "excluded_GZQO_v1.0.0.json") == {**HEADER, "rows": ROWS}  # a run of before


def test_a_file_that_was_cut_off_is_said() -> None:
    data = excluded.write_jsonl(HEADER, iter(ROWS))
    cut = b"\n".join(data.splitlines()[:-1])
    with pytest.raises(excluded.Incomplete, match="cut off"):
        excluded.read(cut, "excluded_GZQO_v1.0.0.jsonl")
    with pytest.raises(excluded.Incomplete):
        excluded.pids(cut, "excluded_GZQO_v1.0.0.jsonl")


def test_the_ids_are_read_line_by_line() -> None:
    data = excluded.write_jsonl(HEADER, iter(ROWS))
    assert excluded.pids(data, "excluded_GZQO_v1.0.0.jsonl") == {r["pid"] for r in ROWS}
    assert excluded.pids(json.dumps({"rows": ROWS}).encode(), "excluded_x.json") == {r["pid"] for r in ROWS}


def test_the_names_of_the_file() -> None:
    assert excluded.is_excluded("excluded_GZQO_v1.0.0.jsonl") and excluded.is_excluded("excluded_GZQO_v1.0.0.json")
    assert not excluded.is_excluded("candidate_list_GZQO_v1.0.0.json")
    assert excluded.newest(["excluded_a_v1.json", "excluded_a_v1.jsonl"]) == "excluded_a_v1.jsonl"


def test_the_screen_job_writes_both_until_the_console_reads_the_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both files, the same rows, both ``phi`` and to nobody: lane C2's console readers move to the lines in a card
    of theirs; the old file goes when they have (a later card)."""
    from types import SimpleNamespace

    from orchestrator.scenarios import screen

    monkeypatch.setattr(screen, "excluded_doc", lambda ctx, run: {**HEADER, "rows": list(ROWS)})
    sent: dict[str, tuple[bytes, str, list[str]]] = {}
    ctx = SimpleNamespace(publish=lambda name, data, tag, to: sent.__setitem__(name, (data, tag, to)))
    screen.publish_excluded(ctx, SimpleNamespace(id="GZQO", version="1.0.0"), None)  # type: ignore[arg-type]
    lines, old = sent["excluded_GZQO_v1.0.0.jsonl"], sent["excluded_GZQO_v1.0.0.json"]
    assert lines[1:] == old[1:] == ("phi", [])
    assert excluded.read(lines[0], "x.jsonl") == excluded.read(old[0], "x.json") == {**HEADER, "rows": ROWS}


def test_microbatch_reads_the_ids_of_the_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from orchestrator.scenarios import microbatch

    store = {"k": excluded.write_jsonl(HEADER, iter(ROWS))}
    ctx = SimpleNamespace(store=SimpleNamespace(get=store.__getitem__))
    got = microbatch.read_sources(ctx, ["k"], names={"k": "excluded_GZQO_v1.0.0.jsonl"})  # type: ignore[arg-type]
    assert got.excluded == {r["pid"] for r in ROWS} and not got.listed
