"""The RTX PRO 6000's tier record (plan 10 row 10E-1b, D-1320): each measured value is the serving record's own figure."""

from __future__ import annotations

import json
from typing import Any

import jsonschema

from tools import tier_record as tr

RECORD = tr.TIERS_DIR / "rtxpro6000.json"


def load(path: Any) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return out


def test_the_rtxpro6000_record_is_complete_and_sound() -> None:
    rec = load(RECORD)
    assert tr.problems(rec, "rtxpro6000") == []
    jsonschema.validate(rec, tr.schema())
    assert tr.counts(rec) == {"measured": 7, "declared": 13, "not_measured": 8}


def test_each_measured_value_is_the_serving_records_figure() -> None:
    rec = load(RECORD)
    serving = load(tr.ROOT / rec["measured_on"]["serving_record"])
    by_role = {s["role"]: s for s in serving["servers"]}
    f = rec["fields"]
    assert serving["card"]["capped_to"] is None
    assert f["card_memory_mib"]["value"] == serving["card"]["memory_total_mib"]
    assert f["driver"]["value"] == serving["card"]["driver"]
    assert f["judge_sequences"]["value"] == by_role["judge"]["max_num_seqs"]
    assert f["verifier_sequences"]["value"] == by_role["verifier"]["max_num_seqs"]
    assert {s["max_model_len"] for s in serving["servers"]} == {f["context_tokens"]["value"]}
    assert f["gpu_memory_utilization"]["value"] == {r: s["gpu_memory_utilization"] for r, s in by_role.items()}
    assert f["models_on_card"]["value"] == "pair_resident"
    assert not any("--enable-sleep-mode" in s["extra_args"] for s in serving["servers"])
    measured = {n for n, v in f.items() if v["basis"] == "measured"}
    assert measured == {
        "card_memory_mib",
        "driver",
        "judge_sequences",
        "verifier_sequences",
        "context_tokens",
        "gpu_memory_utilization",
        "models_on_card",
    }


def test_no_rate_or_peak_is_filled_in_from_outside_the_record() -> None:
    f = load(RECORD)["fields"]
    for name in ("judge_calls_per_second", "free_memory_at_peak_mib", "night_budget_patients", "first_load_nights"):
        assert f[name]["basis"] == "not_measured" and f[name]["value"] is None


def test_both_records_on_file_pass_and_differ_where_the_tiers_differ() -> None:
    assert {p.stem for p in tr.record_files()} >= {"rtx5090", "rtxpro6000"}
    assert {p: w for p, w in tr.check(tr.record_files()).items() if w} == {}
    big, small = load(RECORD)["fields"], load(tr.TIERS_DIR / "rtx5090.json")["fields"]
    assert big["protocol_route"]["value"] == "on_box"
    assert small["protocol_route"]["value"] == "package_from_coordinating_box"
    assert "protocol" in big["role_groups_on_box"]["value"]
    assert "protocol" not in small["role_groups_on_box"]["value"]
