"""The tier record (plan 10 row 10E-1, commitment C-4, D-1320): complete, sourced, never filled in, never ballast."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tools import tier_record as tr

SITE_BOX = tr.TIERS_DIR / "rtx5090.json"
PRO6000 = "deploy/measured/serving_config.rtxpro6000.json"


def site_box() -> dict[str, Any]:
    rec: dict[str, Any] = json.loads(SITE_BOX.read_text(encoding="utf-8"))
    return rec


def test_the_32gb_site_box_record_is_complete_and_sound() -> None:
    rec = site_box()
    assert tr.problems(rec, "rtx5090") == []
    assert set(rec["fields"]) == set(tr.required_fields())
    jsonschema.validate(rec, tr.schema())


def test_the_32gb_record_measures_nothing_yet_and_says_so() -> None:
    rec = site_box()
    assert rec["measured_on"] == {"serving_record": None, "qualification_record": None}
    assert tr.counts(rec) == {"measured": 0, "declared": 18, "not_measured": 10}
    for name in ("judge_calls_per_second", "free_memory_at_peak_mib", "first_load_nights", "night_budget_patients"):
        assert rec["fields"][name] == {**rec["fields"][name], "basis": "not_measured", "value": None}


def test_the_32gb_record_states_what_the_waiting_rows_read() -> None:
    f = site_box()["fields"]
    assert f["protocol_route"]["value"] == "package_from_coordinating_box"  # 10E-33
    assert f["interactive_lane"]["value"] == "when_no_run_holds_the_card"  # 10E-33, 10E-17
    assert f["role_groups_on_box"]["value"] == ["patient", "converse"]  # C-14
    assert f["desk_side"]["value"] is True  # 10G-11
    assert f["arch"]["value"] == "x86_64"  # 10K-3
    caps = {p["capability"]: p["status"] for p in f["console_promises"]["value"]}  # 10E-17, 10K-11
    assert caps["protocol_reading"] == "not_on_this_box"


def test_every_tier_record_on_file_is_complete() -> None:
    files = tr.record_files()
    assert SITE_BOX in files
    assert {p: w for p, w in tr.check(files).items() if w} == {}


def test_a_figure_not_measured_is_never_filled_in() -> None:
    rec = site_box()
    rec["fields"]["judge_calls_per_second"]["value"] = 1.43
    assert any("value is null" in w for w in tr.problems(rec, "rtx5090"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rec, tr.schema())


def test_a_missing_field_is_refused() -> None:
    rec = site_box()
    del rec["fields"]["first_load_nights"]
    assert any("'first_load_nights' is missing" in w for w in tr.problems(rec, "rtx5090"))


@pytest.mark.parametrize(
    "source, says",
    [
        ("", "no source"),
        ("deploy/no-such-file.yml:3 nothing", "no file"),
        ("deploy/docker-compose.rtx5090.yml:99999 past the end", "lines"),
        ("deploy/docker-compose.rtx5090.yml:abc", "not n, n-m"),
    ],
)
def test_a_declared_value_names_a_real_file_and_line(source: str, says: str) -> None:
    rec = site_box()
    rec["fields"]["judge_sequences"]["source"] = source
    assert any(says in w for w in tr.problems(rec, "rtx5090"))


def test_a_declared_field_with_no_value_is_refused() -> None:
    rec = site_box()
    rec["fields"]["arch"]["value"] = None
    assert any("not_measured" in w for w in tr.problems(rec, "rtx5090"))


def test_the_profile_and_tier_must_be_the_files_and_the_tiers() -> None:
    rec = site_box()
    assert any("but the file is" in w for w in tr.problems(rec, "rtxpro6000"))
    rec["tier"] = "large"
    assert any("gives profile 'rtx5090' the tier 'small'" in w for w in tr.problems(rec, "rtx5090"))
    rec["profile"] = "igx-a6000"  # the owner's own Arm workstation is not a measured tier
    assert any("not one of the tiers' profiles" in w for w in tr.problems(rec))


def _root_with(tmp_path: Path, name: str, record: dict[str, Any]) -> Path:
    """A repository root that is the real one plus one serving record written by the test."""
    for part in ("deploy", "docs", "services"):
        (tmp_path / part).symlink_to(tr.ROOT / part)
    (tmp_path / name).write_text(json.dumps(record), encoding="utf-8")
    return tmp_path


def _measured_record(serving: str) -> dict[str, Any]:
    rec = site_box()
    rec["measured_on"]["serving_record"] = serving
    rec["fields"]["judge_sequences"] = {"basis": "measured", "value": 16, "source": serving}
    return rec


def test_a_record_made_under_the_ballast_stand_in_is_refused(tmp_path: Path) -> None:
    serving = json.loads((tr.ROOT / PRO6000).read_text(encoding="utf-8"))
    serving["card"]["capped_to"] = "RTX 5090 (32 GB), by ballast"
    root = _root_with(tmp_path, "ballast.json", serving)
    why = tr.problems(_measured_record("ballast.json"), "rtx5090", root)
    assert any("ballast stand-in" in w and "never a tier record" in w for w in why)


def test_the_ballast_words_anywhere_refuse_the_record() -> None:
    rec = site_box()
    rec["fields"]["driver"]["measured_by"] = "O-1 on the owner's card, RTX 5090 (32 GB), by ballast"
    assert any("ballast stand-in" in w for w in tr.problems(rec, "rtx5090"))


def test_a_capped_serving_record_is_not_a_measurement(tmp_path: Path) -> None:
    serving = json.loads((tr.ROOT / PRO6000).read_text(encoding="utf-8"))
    serving["card"]["capped_to"] = "RTX 5090 (32 GB), by --gpu-memory-utilization"
    root = _root_with(tmp_path, "capped.json", serving)
    why = tr.problems(_measured_record("capped.json"), "rtx5090", root)
    assert any("capped card" in w for w in why)


def test_a_measured_value_comes_from_the_profiles_own_record() -> None:
    rec = copy.deepcopy(site_box())
    rec["profile"], rec["tier"] = "rtxpro6000", "large"
    rec["measured_on"]["serving_record"] = PRO6000
    rec["fields"]["judge_sequences"] = {"basis": "measured", "value": 16, "source": PRO6000}
    assert tr.problems(rec, "rtxpro6000") == []  # the mechanism, on the one record that passes the rule
    rec["fields"]["judge_sequences"]["source"] = "deploy/docker-compose.rtxpro6000.yml"
    assert any("not the record's measured_on.serving_record" in w for w in tr.problems(rec, "rtxpro6000"))


def test_the_rtx5090_profile_refuses_the_pro6000_record_as_its_measurement() -> None:
    why = tr.problems(_measured_record(PRO6000), "rtx5090")
    assert any("not an 5090" in w or "sleep-mode" in w for w in why)


def test_the_command_line_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert tr.main(["check"]) == 0
    assert tr.main(["summary", str(SITE_BOX)]) == 0
    assert "measured 0, declared 18, not measured 10" in capsys.readouterr().out
    bad = site_box()
    bad["fields"]["ecc"]["value"] = True
    path = tmp_path / "rtx5090.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert tr.main(["check", str(path)]) == tr.REFUSED
    assert "refused" in capsys.readouterr().err
