"""The readers onto the tier record (plan 10 row 10E-1c, D-1322): a value is taken only when it is measured."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from gateway.load import LoadControl
from orchestrator.scenarios import microbatch
from tb_common import tier_value

ENDPOINTS = ["serving", "verifier", "stub"]


def slots(env: dict[str, str]) -> dict[str, int]:
    return {n: s["slots"] for n, s in LoadControl(ENDPOINTS, env).snapshot().items()}


def write(tmp_path: Path, profile: str, fields: dict[str, Any]) -> Path:
    (tmp_path / f"{profile}.json").write_text(json.dumps({"fields": fields}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def tiers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tier_value, "TIERS_DIR", tmp_path)
    return tmp_path


def seqs(basis: str, judge: Any, verifier: Any) -> dict[str, Any]:
    def one(v: Any) -> dict[str, Any]:
        if basis == "not_measured":
            return {"basis": basis, "value": None, "measured_by": "R-1"}
        return {"basis": basis, "value": v, "source": "x"}

    return {"judge_sequences": one(judge), "verifier_sequences": one(verifier)}


# ---------------------------------------------------------------- the shipped records, on each profile label
@pytest.mark.parametrize(
    "label, want",
    [
        ("P-PRO6000", {"serving": 16, "verifier": 16, "stub": 16}),  # measured 16: unchanged
        ("P-5090", {"serving": 16, "verifier": 16, "stub": 16}),  # declared 4: today's 16 kept
        ("P-GB10", {"serving": 16, "verifier": 16, "stub": 16}),  # no record (gb10, stub and cpu boxes)
        ("", {"serving": 16, "verifier": 16, "stub": 16}),
    ],
)
def test_the_shipped_records_change_no_profiles_slots(label: str, want: dict[str, int]) -> None:
    assert slots({"TB_PROFILE": label}) == want


def test_the_32gb_contradiction_is_logged_with_both_numbers(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="gateway.load"):
        slots({"TB_PROFILE": "P-5090"})
    text = caplog.text
    assert "judge_sequences is declared 4, not measured: 16 kept" in text and "differ" in text


def test_the_rtxpro6000_record_is_read_as_measured(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="gateway.load"):
        slots({"TB_PROFILE": "P-PRO6000"})
    assert "tier record rtxpro6000: judge_sequences = 16 (measured)" in caplog.text


# ---------------------------------------------------------------- the gateway, each case
def test_a_measured_record_sizes_the_judge_and_verifier(tiers: Path) -> None:
    write(tiers, "rtx5090", seqs("measured", 8, 6))
    assert slots({"TB_PROFILE": "P-5090"}) == {"serving": 8, "verifier": 6, "stub": 16}


def test_a_declared_or_not_measured_field_falls_back(tiers: Path) -> None:
    write(tiers, "rtx5090", seqs("declared", 4, 4))
    assert slots({"TB_PROFILE": "P-5090"})["serving"] == 16
    write(tiers, "rtx5090", seqs("not_measured", None, None))
    assert slots({"TB_PROFILE": "P-5090"})["verifier"] == 16


def test_no_record_or_a_malformed_one_falls_back_and_says_so(tiers: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="gateway.load"):
        assert slots({"TB_PROFILE": "P-5090"})["serving"] == 16
        (tiers / "rtx5090.json").write_text("{not json", encoding="utf-8")
        assert slots({"TB_PROFILE": "P-5090"})["serving"] == 16
        write(tiers, "rtx5090", {"judge_sequences": "eight"})
        assert slots({"TB_PROFILE": "P-5090"})["serving"] == 16
        write(tiers, "rtx5090", seqs("measured", "eight", 0))
        assert slots({"TB_PROFILE": "P-5090"}) == {"serving": 16, "verifier": 16, "stub": 16}
    assert "no_record" in caplog.text and "malformed" in caplog.text


def test_the_setting_and_the_serving_record_still_win(tiers: Path, tmp_path: Path) -> None:
    write(tiers, "rtx5090", seqs("measured", 8, 6))
    assert slots({"TB_PROFILE": "P-5090", "TB_GATEWAY_SLOTS": "7"}) == {"serving": 7, "verifier": 7, "stub": 7}
    rec = tmp_path / "serving.json"
    rec.write_text(json.dumps({"servers": [{"container": "judge", "max_num_seqs": 3}]}), encoding="utf-8")
    assert slots({"TB_PROFILE": "P-5090", "TB_SERVING_RECORD": str(rec)}) == {"serving": 3, "verifier": 6, "stub": 16}


# ---------------------------------------------------------------- the night budget
def ctx(budget: int = microbatch.DEFAULT_NIGHT_BUDGET) -> Any:
    return cast(Any, SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(microbatch_night_budget=budget))))


@pytest.mark.parametrize("label", ["P-PRO6000", "P-5090", "P-GB10", ""])
def test_the_shipped_records_keep_the_night_budget(label: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", label)
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    assert microbatch.night_budget(ctx()) == 2000


def test_the_night_budget_takes_a_measured_value_only(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    write(tiers, "rtx5090", {"night_budget_patients": {"basis": "measured", "value": 900, "source": "x"}})
    assert microbatch.night_budget(ctx()) == 900
    write(tiers, "rtx5090", {"night_budget_patients": {"basis": "declared", "value": 900, "source": "x"}})
    assert microbatch.night_budget(ctx()) == 2000
    (tiers / "rtx5090.json").write_text("[]", encoding="utf-8")
    assert microbatch.night_budget(ctx()) == 2000
    (tiers / "rtx5090.json").unlink()
    assert microbatch.night_budget(ctx()) == 2000


def test_a_configured_night_budget_wins(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    write(tiers, "rtx5090", {"night_budget_patients": {"basis": "measured", "value": 900, "source": "x"}})
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    assert microbatch.night_budget(ctx(500)) == 500
    monkeypatch.setenv("TB_MICROBATCH_NIGHT_BUDGET", "2000")
    assert microbatch.night_budget(ctx(2000)) == 2000


# ---------------------------------------------------------------- the records reach the container
def test_the_image_copies_the_folder_the_readers_compute() -> None:
    dockerfile = (tier_value.TIERS_DIR.parents[1] / "deploy" / "docker" / "python.Dockerfile").read_text("utf-8")
    assert "COPY --chown=tb:tb models /app/models" in dockerfile
    assert "COPY --chown=tb:tb libs /app/libs" in dockerfile
    assert tier_value.TIERS_DIR.relative_to(tier_value.TIERS_DIR.parents[1]).as_posix() == "models/tiers"
    assert {p.stem for p in tier_value.TIERS_DIR.glob("*.json")} >= {"rtx5090", "rtxpro6000"}
    assert set(tier_value.PROFILE_OF_LABEL.values()) == {"rtx5090", "rtxpro6000"}
