"""The lake exported from OMOP as of an earlier time, NOTE_NLP from the site's facts, the flip (T-202, D-384).

Two nights loaded into one store: the export as of the first night equals the first night's NDJSON-flattened lake,
the export as of the second the second's; a conflict resolved and a fact confirmed later do not reach the earlier
export; the export as of a time writes nothing. A fact read from a chart reaches NOTE_NLP; publish writes exactly the
facts a person kept. The flip is refused on a parity report that is not IDENTICAL and, on one that is, is an
audited flag change naming the report's sha256. A flag flipped while a rebuild runs takes effect at the next one.
Synthetic data only."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ICD = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
TZ = "Asia/Taipei"
BASIS = "urn:trialbox:basis"


@pytest.fixture
def store(db_url: str) -> Any:
    from omop import schema

    db = schema.connect(db_url, "omop_t202")
    yield db
    db.close()


def _cond(cid: str, pid: str, code: str, day: str = "2026-09-02") -> dict[str, Any]:
    return {
        "resourceType": "Condition",
        "id": cid,
        "subject": {"reference": f"Patient/{pid}"},
        "onsetDateTime": day,
        "code": {"coding": [{"system": ICD, "code": code}]},
    }


def _glu(value: float) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": "o-glu",
        "status": "final",
        "subject": {"reference": "Patient/P1"},
        "effectiveDateTime": "2026-09-02T11:00:00+08:00",
        "code": {"coding": [{"system": LOINC, "code": "2345-7"}]},
        "valueQuantity": {"value": value, "unit": "mmol/L"},
    }


def _night1() -> dict[str, list[dict[str, Any]]]:
    return {
        "Patient": [
            {"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"},
            {"resourceType": "Patient", "id": "P2", "birthDate": "1971-05-05", "gender": "male"},
        ],
        "Condition": [_cond("c1", "P1", "E11.9"), _cond("c2", "P1", "I10"), _cond("c3", "P2", "M10.0")],
        "Observation": [_glu(5.4)],
    }


def _night2() -> dict[str, list[dict[str, Any]]]:
    """The next night: P2 and their gout are gone at the source, c1 recoded, the glucose corrected, c4 new."""
    return {
        "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}],
        "Condition": [_cond("c1", "P1", "E11.65"), _cond("c2", "P1", "I10"), _cond("c4", "P1", "N18.3")],
        "Observation": [_glu(6.0)],
    }


def _site() -> dict[str, list[dict[str, Any]]]:
    """The site's inputs: a different birth date for P1 (a conflict) and a proposed diagnosis."""
    proposed = _cond("tbpf-1", "P1", "M10.9")
    proposed["meta"] = {"tag": [{"system": BASIS, "code": "proposed"}]}
    return {
        "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-02"}],
        "Condition": [proposed],
    }


def _legacy(feed: dict[str, Any], site: dict[str, Any], snapshot: str) -> dict[str, list[dict[str, Any]]]:
    from lake.source import lake_rows

    return lake_rows(feed, site, tz=TZ, snapshot=snapshot, source="legacy")


def _tick() -> datetime:
    """An instant strictly between two transactions (``now()`` is the transaction's start)."""
    time.sleep(0.01)
    at = datetime.now(UTC)
    time.sleep(0.01)
    return at


def _same(a: dict[str, list[dict[str, Any]]], b: dict[str, list[dict[str, Any]]]) -> None:
    from lake.flatten import SCHEMAS

    for name in SCHEMAS:
        assert a[name] == b[name], name


# ------------------------------------------------------------------------------------------------ point in time
def test_as_of_each_night_equals_that_nights_flattened_lake(store: Any) -> None:
    from omop.export import export_rows
    from omop.load import load_batch, resolve_conflict, set_status

    before_any = _tick()
    load_batch(store, "feed", "2026-10-05", _night1(), tz=TZ)
    load_batch(store, "site", "site@2026-10-05", _site(), tz=TZ)
    night1 = _tick()
    rep = load_batch(store, "feed", "2026-10-06", _night2(), tz=TZ)
    assert (rep.inserted, rep.updated, rep.tombstoned) == (1, 2, 2)  # c4; c1 and o-glu; P2 and c3
    night2 = _tick()
    conflict = store.fetchval("SELECT conflict_id FROM tb_conflict WHERE state = 'open'")
    resolve_conflict(store, int(conflict), "1960-01-01", by="steward:t", reason="the EMR is right")
    set_status(store, ("site", "Condition", "tbpf-1", 0), "confirmed", "steward:t", "read in the chart")

    first, second = _legacy(_night1(), _site(), "2026-10-05"), _legacy(_night2(), _site(), "2026-10-06")
    assert first["condition"] != second["condition"]  # the nights differ, so the comparison means something
    now = export_rows(store)
    _same(export_rows(store, as_of=night1), first)
    _same(export_rows(store, as_of=night2), second)
    # later decisions are not in the earlier exports, and are in the current one
    assert [r["birth_date"] for r in second["patient"]] == [None]  # the conflict open: unknown
    assert [str(r["birth_date"]) for r in now["patient"]] == ["1960-01-01"]
    assert {r["basis"] for r in now["site_fact"]} == {"confirmed"} != {r["basis"] for r in second["site_fact"]}
    # nothing was written: the store exports as before, and as of before the first load it held nothing
    _same(export_rows(store), now)
    assert all(not rows for rows in export_rows(store, as_of=before_any).values())


def test_as_of_needs_an_aware_instant_and_a_kept_before_image(store: Any) -> None:
    from omop.export import export_rows
    from omop.load import load_batch
    from omop.schema import OmopError

    load_batch(store, "feed", "2026-10-05", _night1(), tz=TZ)
    night1 = _tick()
    load_batch(store, "feed", "2026-10-06", _night2(), tz=TZ)
    with pytest.raises(ValueError, match="aware"):
        export_rows(store, as_of=night1.replace(tzinfo=None))
    # an event written before migration 6 has no record before-image: refused, never guessed
    store.execute("UPDATE tb_record_event SET record_before = NULL WHERE event = 'update'")
    with pytest.raises(OmopError, match="no record before-image"):
        export_rows(store, as_of=night1)
    assert export_rows(store)["condition"]  # the current export is not affected


def test_events_keep_the_record_as_it_was(store: Any) -> None:
    from omop.load import load_batch

    load_batch(store, "feed", "2026-10-05", _night1(), tz=TZ)
    load_batch(store, "feed", "2026-10-06", _night2(), tz=TZ)
    rows = store.fetchall(
        "SELECT r.source_record_id, e.event, e.record_before FROM tb_record_event e JOIN tb_record r "
        "USING (record_key) WHERE e.batch = '2026-10-06' ORDER BY r.source_record_id, e.event"
    )
    got = {(str(s), str(ev)): b for s, ev, b in rows}
    assert got[("c4", "insert")] is None
    assert got[("c3", "tombstone")]["status"] == "coded" and got[("c3", "tombstone")]["last_batch"] == "2026-10-05"
    assert got[("c1", "update")]["source_batch"] == "2026-10-05"


# ------------------------------------------------------------------------------------------------ NOTE_NLP, publish
def _facts() -> list[dict[str, Any]]:
    base = {"pid": "P1", "domain": "condition", "code": "", "system": ICD, "local_code": "", "local_system": "",
            "value": "", "unit": "", "day": "2026-09-03"}  # fmt: skip
    return [
        {**base, "id": 1, "input_id": 7, "term": "gout", "code": "M10.9", "status": "confirmed"},
        {**base, "id": 2, "input_id": 7, "term": "renal stone", "code": "N20.0", "status": "proposed"},
        {**base, "id": 3, "input_id": 7, "term": "psoriasis", "code": "L40.0", "status": "rejected"},
        {**base, "id": 4, "input_id": 8, "term": "hypertension", "code": "I10", "status": "coded"},
    ]


def _charts() -> list[dict[str, Any]]:
    return [{"id": 7, "pid": "P1", "day": "2026-09-03", "text": "[redacted] gout flare, query renal stone"}]


def test_publish_names_the_chart_a_fact_was_read_from() -> None:
    from omop.load import NOTE_SOURCE, note_source
    from sitesetup import publish

    assert publish.NOTE_SOURCE == NOTE_SOURCE
    res = publish.resources(_facts(), {}, _charts())
    by_id = {r["id"]: r for r in res["Condition"]}
    assert note_source(by_id["tbcf-1"]) == ("tbch-7", "gout")
    assert note_source(by_id["tbpf-2"]) == ("tbch-7", "renal stone")
    assert note_source(by_id["tbsd-4"]) is None  # from a sheet, not a chart
    assert "tbpf-3" not in by_id and "tbcf-3" not in by_id  # rejected: left out
    assert (
        base64.b64decode(res["DocumentReference"][0]["content"][0]["attachment"]["data"]).decode()
        == (_charts()[0]["text"])
    )


def test_publish_writes_exactly_the_kept_facts_and_note_nlp(store: Any) -> None:
    from omop.export import export_rows
    from omop.load import load_batch
    from sitesetup import publish

    site = publish.resources(_facts(), {}, _charts())
    load_batch(store, "feed", "2026-10-05", _night1(), tz=TZ)
    load_batch(store, "site", "site@2026-10-05", site, tz=TZ)
    _same(export_rows(store), _legacy(_night1(), site, "2026-10-05"))
    live = {
        str(s): str(st)
        for s, st in store.fetchall("SELECT source_record_id, status FROM tb_record WHERE source_kind = 'site'")
    }
    assert {k: v for k, v in live.items() if k.startswith("tb") and not k.startswith("tbenc")} == {
        "tbcf-1": "confirmed",
        "tbpf-2": "proposed",
        "tbsd-4": "coded",
        "tbch-7": "coded",
    }
    nlp = store.fetchall(
        "SELECT n.lexical_variant, n.term_modifiers, n.nlp_date, r.source_record_id FROM note_nlp n "
        "JOIN tb_record r ON r.cdm_table = 'note' AND r.record_id = n.note_id ORDER BY n.lexical_variant"
    )
    assert [(a, b, str(c), d) for a, b, c, d in nlp] == [
        ("gout", "status=confirmed", "2026-09-03", "tbch-7"),
        ("renal stone", "status=proposed", "2026-09-03", "tbch-7"),
    ]
    # the next publish: the proposed fact rejected by a person; its NOTE_NLP row goes with it
    facts = _facts()
    facts[1]["status"] = "rejected"
    load_batch(store, "site", "site@2026-10-06", publish.resources(facts, {}, _charts()), tz=TZ)
    assert store.fetchall("SELECT lexical_variant FROM note_nlp") == [("gout",)]


# ------------------------------------------------------------------------------------------------ the flip
def _report(tmp_path: Path, identical: bool, sets: dict[str, Any] | None = None) -> Path:
    p = tmp_path / "report.json"
    body = {"identical": identical, "sets": {"synthetic": {"identical": identical}} if sets is None else sets}
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_the_flip_needs_an_identical_report_and_names_its_sha(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    from tb_common import flags as fl

    from tools.omop_parity import flip, main

    monkeypatch.delenv("TB_LAKE_SOURCE", raising=False)
    fl.clear_cache()
    audit = tmp_path / "audit"
    with pytest.raises(ValueError, match="not IDENTICAL"):
        flip(_report(tmp_path, False), "ops:t", audit)
    with pytest.raises(ValueError, match="compared nothing"):
        flip(_report(tmp_path, True, {"mimic": {"skipped": "data not fetched"}}), "ops:t", audit)
    assert main(["flip", str(_report(tmp_path, False)), "--actor", "ops:t", "--audit-dir", str(audit)]) == 1
    assert fl.Flags().row("lake.source") is None  # nothing changed
    rep = _report(tmp_path, True)
    sha = hashlib.sha256(rep.read_bytes()).hexdigest()
    assert main(["flip", str(rep), "--actor", "ops:t", "--audit-dir", str(audit)]) == 0
    fl.clear_cache()
    assert fl.Flags().row("lake.source") == "omop"
    ev = fl.Flags().events("lake.source")[-1]
    assert ev["new_value"] == "omop" and ev["actor"] == "ops:t" and sha in ev["reason"]
    with pytest.raises(ValueError, match="already omop"):
        flip(rep, "ops:t", audit)
    fl.clear_cache()


def test_a_flip_during_a_rebuild_takes_effect_at_the_next(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """T-008's rule, kept by the flip: the source is read once, when a rebuild starts (a SCREEN reads the snapshot
    that rebuild made, so its bytes do not move either)."""
    from lake import source as ls
    from lake.flatten import Flattener
    from tb_common import flags as fl

    from tools.omop_parity import recorded_source

    monkeypatch.setenv("TB_LAKE_SOURCE", "legacy")
    fl.clear_cache()
    real = Flattener.flatten

    def flipping(self: Flattener, res: Any) -> Any:
        monkeypatch.setenv("TB_LAKE_SOURCE", "omop")  # the operator flips while the rebuild runs
        return real(self, res)

    monkeypatch.setattr(Flattener, "flatten", flipping)
    lake = tmp_path / "lake"
    first = ls.lake_rows(_night1(), _site(), tz=TZ, snapshot="2026-10-05", lake_dir=lake)
    assert recorded_source(lake, "2026-10-05") == "legacy"
    monkeypatch.setattr(Flattener, "flatten", real)
    again = ls.lake_rows(_night1(), _site(), tz=TZ, snapshot="2026-10-06", lake_dir=lake)
    assert recorded_source(lake, "2026-10-06") == "omop"
    _same(again, first)  # and the two sources agree
    fl.clear_cache()
