"""Trace store and redaction (spec v4 §8.14, LLM-45, PRIV-30; S1-08 done-criterion).

On the generated ``deid_synthetic`` items (≥ 200, zh-TW / ja / en, fixed seed) no planted identifier appears in
the stored traces, and recall per identifier type and per language is reported and held to the suite floor.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from guard.guard import Guard
from tracestore.app import create_app
from tracestore.store import TraceAccessDenied, TraceSettings, TraceStore

from eval.suites.deid_synthetic.generate import generate, load_suite

SUITE = load_suite()
GUARD = Guard(SUITE["mrn_regex"])


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def stored_text(store: TraceStore) -> str:
    """Everything the store holds (every column of every row), as the raw file was read before D-126."""
    rows = store.db.fetchall("SELECT concat_ws(' ', call_id, ts, body) FROM traces") + store.db.fetchall(
        "SELECT concat_ws(' ', ts, \"user\", purpose, action, call_id, detail) FROM access_log"
    )
    return "\n".join(str(r[0]) for r in rows)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@pytest.mark.req("LLM-45", "PRIV-30", "S1-08")
def test_no_planted_identifier_reaches_the_trace_store(tmp_path: Path) -> None:
    items = generate(SUITE)
    assert len(items) >= 200 and {it.lang for it in items} == {"zh-TW", "ja", "en"}
    assert generate(SUITE)[17].text == items[17].text  # fixed seed: reproducible
    store = TraceStore(None, GUARD, clock=Clock())
    for it in items:
        store.write(
            {
                "call_id": f"call-{it.id}",
                "span": "chat",
                "attributes": {"tb.data_class": "D3", "tb.study_id": "STUDY-1", "note": it.text},
                "prompt": [{"role": "user", "content": it.text}],
                "output": json.dumps({"quote": it.text}, ensure_ascii=False),
            }
        )
    raw = stored_text(store)
    stored_digits = _digits(raw)
    planted = Counter[str]()
    caught = Counter[str]()
    per_lang = Counter[str]()
    per_lang_caught = Counter[str]()
    leaks: list[str] = []
    for it in items:
        for p in it.planted:
            planted[p["type"]] += 1
            per_lang[it.lang] += 1
            d = _digits(p["value"])
            leaked = p["value"] in raw or (len(d) >= 7 and d in stored_digits)
            if leaked:
                leaks.append(f"{it.id} {p['type']}")
            else:
                caught[p["type"]] += 1
                per_lang_caught[it.lang] += 1
    report = {k: round(caught[k] / planted[k], 4) for k in sorted(planted)}
    report_lang = {k: round(per_lang_caught[k] / per_lang[k], 4) for k in sorted(per_lang)}
    print("\ndeid_synthetic recall per identifier type:", json.dumps(report, ensure_ascii=False))
    print("deid_synthetic recall per language:", json.dumps(report_lang))
    (tmp_path / "deid_recall.json").write_text(json.dumps({"type": report, "language": report_lang}))
    assert sum(planted.values()) >= 400 and len(planted) >= 11
    assert len(leaks) <= SUITE["max_leaks"], leaks
    assert min(report.values()) >= SUITE["recall_floor"] and min(report_lang.values()) >= SUITE["recall_floor"]


@pytest.mark.req("PRIV-30")
def test_false_positive_rate_on_negative_items_reported() -> None:
    items = [it for it in generate(SUITE) if not it.planted]
    assert items
    hits = sum(bool(GUARD.detect(it.text)) for it in items)
    print(f"\ndeid_synthetic negatives: {hits}/{len(items)} items with a redaction")
    assert hits / len(items) <= SUITE["max_negative_hit_rate"]


@pytest.mark.req("LLM-45", "S1-08")
def test_reads_need_purpose_and_role_and_are_logged(tmp_path: Path) -> None:
    store = TraceStore(None, GUARD, clock=Clock())
    store.write({"call_id": "c1", "span": "chat", "attributes": {"tb.call_id": "c1"}, "prompt": "MRN 20481234"})
    (t,) = store.read("c1", user="qa1", purpose="dispute review", roles=frozenset({"trace:read"}))
    assert t["prompt"] == "MRN [MRN]" and t["attributes"]["tb.call_id"] == "c1"
    with pytest.raises(TraceAccessDenied):
        store.read("c1", user="qa1", purpose="", roles=frozenset({"trace:read"}))
    with pytest.raises(TraceAccessDenied):
        store.read("c1", user="dev", purpose="curious", roles=frozenset())
    log = store.access_log()
    assert [(r["user"], r["purpose"], r["granted"]) for r in log if r["action"] == "read"] == [
        ("qa1", "dispute review", 1),
        ("qa1", "", 0),
        ("dev", "curious", 0),
    ]
    with pytest.raises(ValueError, match="call_id"):
        store.write({"span": "chat"})


@pytest.mark.req("LLM-45", "S1-08")
def test_retention_prune_with_injected_clock(tmp_path: Path) -> None:
    clock = Clock()
    manual = dataclasses.replace(TraceSettings.load(), prune_every_hours=0)  # the prune on write: see T-605 below
    store = TraceStore(None, GUARD, clock=clock, settings=manual)
    store.write({"call_id": "old", "span": "chat"})
    store.write({"call_id": "sc", "span": "chat", "sc": True})
    clock.now += timedelta(days=45)
    store.write({"call_id": "new", "span": "chat"})
    assert store.prune() == 1  # the special-category trace is past its reduced retention
    clock.now += timedelta(days=44)  # day 89 for "old"
    assert store.prune() == 0 and store.count() == 2
    clock.now += timedelta(days=2)  # day 91
    assert store.prune() == 1 and store.count() == 1
    roles = frozenset({"trace:read"})
    assert store.read("old", user="a", purpose="p", roles=roles) == []
    assert store.read("new", user="a", purpose="p", roles=roles)
    prunes = [r for r in store.access_log() if r["action"] == "prune"]
    assert len(prunes) == 3 and all(r["user"] == "system" for r in prunes)
    assert store.settings.retention_days == 90


def test_tracestore_http_surface(tmp_path: Path) -> None:
    http = TestClient(create_app(TraceStore(None, GUARD, clock=Clock())))
    assert http.post("/v1/traces", json={"call_id": "c9", "prompt": "身分證 A123456789"}).status_code == 200
    denied = http.get("/v1/traces/c9", headers={"X-TB-User": "u", "X-TB-Purpose": "p"})
    assert denied.status_code == 403
    ok = http.get("/v1/traces/c9", headers={"X-TB-User": "u", "X-TB-Purpose": "p", "X-TB-Roles": "trace:read"})
    assert ok.json()["traces"][0]["prompt"] == "身分證 [TW_NATIONAL_ID]"
    assert http.post("/v1/traces", json={"prompt": "x"}).status_code == 422


# ------------------------------------------------------------------------------------------------ T-605 (D-431)
MARKER = "T605-PLANTED-MARKER 糖尿病 HbA1c 9.1 同居の娘"


def _production_store(clock: Clock) -> TraceStore:
    return TraceStore(None, GUARD, clock=clock, settings=TraceSettings.load(environment="PRODUCTION"))


def test_planted_marker_never_stored_for_d3_in_production() -> None:
    """LLM-040: in PRODUCTION a D3 or D4 trace keeps a sha256 and a size of the prompt and the output, no text."""
    store = _production_store(Clock())
    for cls in ("D3", "D4"):
        store.write(
            {
                "call_id": f"call-{cls}",
                "span": "chat",
                "attributes": {"tb.data_class": cls, "tb.call_id": f"call-{cls}", "note": MARKER},
                "prompt": [{"role": "user", "content": MARKER}],
                "output": json.dumps({"quote": MARKER}, ensure_ascii=False),
            }
        )
    raw = stored_text(store)
    assert "T605-PLANTED-MARKER" not in raw and "HbA1c" not in raw and "同居" not in raw
    (t,) = store.read("call-D3", user="qa1", purpose="dispute review", roles=frozenset({"trace:read"}))
    assert set(t) >= {"prompt_digest", "output_digest"} and "prompt" not in t and "output" not in t
    assert len(t["prompt_digest"]["sha256"]) == 64 and t["attributes"] == {
        "tb.data_class": "D3",
        "tb.call_id": "call-D3",
    }
    dev = TraceStore(None, GUARD, clock=Clock())  # DEV and TEST keep redacted text for debugging on synthetic data
    dev.write({"call_id": "dev-1", "attributes": {"tb.data_class": "D3"}, "prompt": "HbA1c 9.1"})
    assert "HbA1c" in stored_text(dev)


def test_scheduled_prune_deletes_an_8_day_trace_and_keeps_pre_d431_rows() -> None:
    clock = Clock()
    store = _production_store(clock)
    assert store.settings.retention_days == 7 and store.settings.prune_every_hours == 1
    store.db.execute(  # a row written before D-431 (policy 0): kept until the owner rules on existing rows
        "INSERT INTO traces (call_id, ts, sc, body) VALUES ('legacy', ?, 0, '{}')", (clock.now.isoformat(),)
    )
    store.write({"call_id": "old", "attributes": {"tb.data_class": "D1"}})
    clock.now += timedelta(days=8)
    store.write({"call_id": "new", "attributes": {"tb.data_class": "D1"}})  # the write runs the scheduled prune
    ids = {r[0] for r in store.db.fetchall("SELECT call_id FROM traces")}
    assert ids == {"legacy", "new"}
    assert [r for r in store.access_log() if r["action"] == "prune"][-1]["detail"].startswith('{"deleted": 1')
