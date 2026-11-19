"""The peak record, a second kind of measured source (plan 10 row 10E-1d, D-1320 amended): accepted only as stated."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import tier_record as tr

RECORD = tr.TIERS_DIR / "rtxpro6000.json"
PEAK = "eval/parity/gpu-run-2026-11-08-pro6000/gpu_peak.json"


def record() -> dict[str, Any]:
    out: dict[str, Any] = json.loads(RECORD.read_text(encoding="utf-8"))
    return out


def origin(rec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = rec["measured_on"]["peak_record"]["origin"]
    return out


def test_the_shipped_peak_is_accepted_and_is_total_minus_peak() -> None:
    rec = record()
    peak = json.loads((tr.ROOT / PEAK).read_text(encoding="utf-8"))
    assert tr.problems(rec, "rtxpro6000") == []
    assert rec["measured_on"]["peak_record"]["path"] == PEAK
    f = rec["fields"]["free_memory_at_peak_mib"]
    assert f["basis"] == "measured" and f["source"].split()[0] == PEAK
    assert f["value"] == peak["total_mib"] - peak["peak_mib"] == 35299


def test_the_origin_says_what_the_file_does_not_state() -> None:
    o = origin(record())
    for key in ("commit_or_bundle", "card", "driver", "workload", "sampling"):
        assert o[key].startswith("not stated in the file"), key
    assert o["capped"] == "uncapped" and o["profile"] == "rtxpro6000" and o["not"]


def _refused(rec: dict[str, Any], says: str, root: Path = tr.ROOT) -> None:
    why = tr.problems(rec, "rtxpro6000", root)
    assert any(says in w for w in why), why


def _root_with_peak(tmp_path: Path, peak: dict[str, Any]) -> Path:
    for part in ("deploy", "docs", "services", "models"):
        (tmp_path / part).symlink_to(tr.ROOT / part)
    run = tmp_path / "eval" / "parity" / "gpu-run-2026-11-08-pro6000"
    run.mkdir(parents=True)
    (run / "README.md").symlink_to(tr.ROOT / "eval/parity/gpu-run-2026-11-08-pro6000/README.md")
    (run / "gpu_peak.json").write_text(json.dumps(peak), encoding="utf-8")
    return tmp_path


def test_a_peak_of_another_card_is_refused(tmp_path: Path) -> None:
    root = _root_with_peak(tmp_path, {"peak_mib": 30000, "used_mib": 30000, "total_mib": 49140})
    _refused(record(), "another card", root)


def test_a_capped_or_ballast_peak_is_refused() -> None:
    rec = record()
    origin(rec)["capped"] = "RTX 5090 (32 GB), by --gpu-memory-utilization"
    _refused(rec, "capped card")
    rec = record()
    origin(rec)["run"] = "O-1 on the owner's card, RTX 5090 (32 GB), by ballast"
    _refused(rec, "ballast stand-in")


@pytest.mark.parametrize("key", [*tr.PEAK_ORIGIN, "not"])
def test_a_missing_origin_fact_is_refused(key: str) -> None:
    rec = record()
    del origin(rec)[key]
    _refused(rec, "missing")


def test_a_peak_of_another_profile_or_configuration_is_refused() -> None:
    rec = record()
    origin(rec)["profile"] = "rtx5090"
    _refused(rec, "not 'rtxpro6000'")
    rec = record()
    origin(rec)["configuration"]["judge_sequences"] = 4
    _refused(rec, "the peak is of another configuration")
    rec = record()
    del origin(rec)["configuration"]["source"]
    _refused(rec, "configuration must state")


def test_the_value_must_be_the_files_arithmetic() -> None:
    rec = record()
    rec["fields"]["free_memory_at_peak_mib"]["value"] = 40000
    _refused(rec, "total_mib - peak_mib (35299)")


def test_a_peak_record_measures_no_other_field() -> None:
    rec = record()
    rec["fields"]["idle_memory_mib"] = {"basis": "measured", "value": 62588, "source": PEAK}
    _refused(rec, "not the record's measured_on.serving_record")


def test_a_refused_peak_record_measures_nothing() -> None:
    rec = copy.deepcopy(record())
    origin(rec)["capped"] = "capped"
    why = tr.problems(rec, "rtxpro6000")
    assert any("field 'free_memory_at_peak_mib'" in w for w in why)


def test_the_check_from_the_command_line() -> None:
    out = subprocess.run(
        [sys.executable, str(tr.ROOT / "tools" / "tier_record.py"), "summary", str(RECORD)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tr.ROOT,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    assert "measured 8, declared 13, not measured 7" in out.stdout
