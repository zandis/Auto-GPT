"""Card H-6 (lane H, 2026-11-17): the replay never meets a target (D-1064 item 4), reads the site's zone from the run's
own record (D-315), and scores a run built on answer key v2 as it is (D-1104).

The run is the slice of launch P1b's stored sets that card H-4's tests use (``tests/fixtures/public_accuracy_p1b``:
public SIGIR 2016, NCBI, ``eval/criterion_ml/LICENSE.NCBI``; synthetic JMED-Personas by Sociocom, NAIST, CC BY 4.0).
Here its gold is stamped key v2, as a new launch's is, and its sigir set records a zone."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_h4_replay_2026_11_17 import DAY, SLICE, _tgz, _write_set
from tools.public_accuracy import key as answer_keys
from tools.public_accuracy import replay

pytestmark = pytest.mark.nodb

#: a zone other than UTC, written into the record by the test (settings, not code: D-315)
RECORD_ZONE = "Asia/Tokyo"


def _stamp(d: Path) -> None:
    answer_keys.stamp(d / "built" / "gold", "v2")
    (d / "built" / "gold" / "written.json").write_text("{}", encoding="utf-8")


@pytest.fixture(scope="module")
def native(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The slice built on key v2 natively (gold/key.json says v2, written.json present), sigir's record naming a zone,
    replayed at both levels with no leave to skip the pins."""
    tmp = tmp_path_factory.mktemp("h6")
    sl = json.loads(SLICE.read_text(encoding="utf-8"))
    stored = tmp / "stored"
    stored.mkdir()
    for name, s in sl["sets"].items():
        d = _write_set(tmp / "src" / name, name, s)
        _stamp(d)
        if name == "sigir":
            (d / "work" / "set-clock.json").write_text(json.dumps({"used_s": 1.0, "tz": RECORD_ZONE}), "utf-8")
        _tgz(d, stored / f"{name}.tgz")
    seen: dict[str, str] = {}
    real = replay.rerun_level

    def spy(name: str, d: Path, scratch: Path, tz: str, *a: Any) -> dict[str, Any]:
        seen[name] = tz
        return real(name, d, scratch, tz, *a)

    mp = pytest.MonkeyPatch()
    mp.setattr(replay, "rerun_level", spy)
    mp.delenv("TB_TZ", raising=False)
    try:
        rep = replay.replay([stored], tmp / "scratch", index_day=DAY, build_day=DAY)
    finally:
        mp.undo()
    return {"tmp": tmp, "stored": stored, "report": rep, "tz_used": seen}


# ---------------------------------------------------------------- a run built on key v2
def test_a_v2_stamped_run_is_scored_as_it_is_with_no_overlay_and_no_pin(native: dict[str, Any]) -> None:
    r = native["report"]
    for name, s in r["sets"].items():
        assert s["key_stated"] == {"key": "v2", "what": answer_keys.KEYS["v2"], "stamped": True}, name
        assert s["key_v2"]["native"] is True and "refused" not in s["key_v2"] and s["key_v2"]["applied"] == 0
        assert "states key v2" in s["key_v1"]["refused"]
        assert s["level_a"]["v2"]["scorer_read_the_folder_as"]["key"] == "v2"
        assert s["level_a"]["v1"] == {"answer_key": s["key_v1"], "not_scored_because": s["key_v1"]["refused"]}
    for lvl in ("a", "b"):
        t = r["targets"]["eligible_wrongly_excluded"][lvl]
        assert t["v2"]["all_sets_scored"] is True and all(x["scored"] for x in t["v2"]["per_set"])
        assert t["v1"]["all_sets_scored"] is False and not any(x["scored"] for x in t["v1"]["per_set"])
    # the same verdicts as the H-4 slice on its offline v2 (sigir: 2 of 2 at (a), 0 of 2 at (b))
    a2 = {x["set"]: x for x in r["targets"]["eligible_wrongly_excluded"]["a"]["v2"]["per_set"]}
    b2 = {x["set"]: x for x in r["targets"]["eligible_wrongly_excluded"]["b"]["v2"]["per_set"]}
    assert (a2["sigir"]["numerator"], a2["sigir"]["denominator"]) == (2, 2)
    assert (b2["sigir"]["numerator"], b2["sigir"]["denominator"]) == (0, 2)
    said = replay.render(r)
    assert "key the folder states: v2" in said and "the run's own gold (built on v2)" in said
    assert any("Built on key v2" in x for x in r["limits"])


# ---------------------------------------------------------------- the zone of the run's record (D-315)
def test_the_zone_is_taken_from_the_runs_record_and_said(native: dict[str, Any]) -> None:
    r = native["report"]
    z = r["sets"]["sigir"]["zone"]
    assert z["tz"] == RECORD_ZONE and z["from"] == "the run's own record (work/set-clock.json: tz)"
    assert native["tz_used"]["sigir"] == RECORD_ZONE
    # jmed's record names none: TB_TZ is unset here, so UTC, and it says so
    j = r["sets"]["jmed"]["zone"]
    assert j["tz"] == "UTC" and j["record"]["tz"] is None and "names no zone" in j["from"]
    assert native["tz_used"]["jmed"] == "UTC"
    said = replay.render(r)
    assert f"zone for the re-run: {RECORD_ZONE}, from the run's own record" in said


def test_a_record_naming_no_zone_falls_back_to_tb_tz_then_utc(tmp_path: Path) -> None:
    (tmp_path / "work" / "screen").mkdir(parents=True)
    rec = replay.zone_of_record(tmp_path)
    assert rec["tz"] is None and "work/set-clock.json: tz" in rec["looked_in"]
    assert replay.choose_zone(rec, None, {"TB_TZ": RECORD_ZONE})["tz"] == RECORD_ZONE
    assert replay.choose_zone(rec, None, {})["tz"] == "UTC"
    assert replay.choose_zone(rec, None, {})["from"].startswith("UTC (the run's record names no zone")


def test_the_record_wins_over_tb_tz_and_tz_given_wins_over_both(tmp_path: Path) -> None:
    (tmp_path / "work" / "screen").mkdir(parents=True)
    (tmp_path / "work" / "screen" / "Sm2X.json").write_text(json.dumps({"provenance": {"tz": RECORD_ZONE}}), "utf-8")
    rec = replay.zone_of_record(tmp_path)
    assert rec["tz"] == RECORD_ZONE and rec["from"] == "work/screen/Sm2X.json: provenance.tz"
    assert replay.choose_zone(rec, None, {"TB_TZ": "UTC"})["tz"] == RECORD_ZONE
    given = replay.choose_zone(rec, "UTC", {"TB_TZ": "UTC"})
    assert given["tz"] == "UTC" and given["from"] == "given with --tz"
    assert given["differs_from_the_record"] == RECORD_ZONE


def test_a_zone_that_is_no_iana_name_is_not_used_and_disagreement_is_said(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "set-clock.json").write_text(json.dumps({"tz": "Mars/Olympus"}), "utf-8")
    (tmp_path / "work" / "acc-env.json").write_text(json.dumps({"tz": RECORD_ZONE, "TB_TZ": "UTC"}), "utf-8")
    rec = replay.zone_of_record(tmp_path)
    assert rec["tz"] == RECORD_ZONE and rec["from"] == "work/acc-env.json: tz"
    assert rec["unreadable"] == ["work/set-clock.json: tz = 'Mars/Olympus' (not an IANA zone)"]
    assert rec["disagrees"] == ["work/acc-env.json: TB_TZ = UTC"]


# ---------------------------------------------------------------- met only by a launch (D-1064 item 4)
def test_no_figure_of_the_replay_is_ever_met(native: dict[str, Any]) -> None:
    r = native["report"]
    t = r["targets"]
    figs = [f for lvl in ("a", "b") for f in t["eligible_wrongly_excluded"][lvl].values()]
    figs += [t["protocols_failing"]["a"], t["protocols_failing"]["b"], t["pathology"]["run"]]
    assert all(f["met"] is False and f["met_only_by"] == replay.MET_ONLY_BY for f in figs)
    assert all(f["met_before_screen_only"] is False for f in (t["protocols_failing"]["a"], t["protocols_failing"]["b"]))
    assert not any(v for k, v in r["met"].items() if k != "at_level")
    # sigir's figure at level (b) on key v2 is 0 (the slice's jmed rows keep v1's labels under the stamp): within
    # the target where it is 0, never met
    b2 = {x["set"]: x for x in t["eligible_wrongly_excluded"]["b"]["v2"]["per_set"]}
    assert b2["sigir"]["numerator"] == 0 and b2["jmed"]["numerator"] > 0
    within = t["eligible_wrongly_excluded"]["b"]["v2"]["within_target"]
    assert r["within_target"]["eligible_wrongly_excluded"] is within
    assert r["schema_version"] == 2
    said = replay.render(r)
    assert said.count("met only by a launch") >= 3 and "none is met by this replay" in said
    assert not re.search(r"(: | )met(;|$)", said, re.M)  # no figure is called met


def test_require_targets_reads_within_the_target(native: dict[str, Any]) -> None:
    out = native["tmp"] / "cli.json"
    args = [str(native["stored"]), "--json", str(out), "--no-rerun"]
    assert replay.main(args) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["sets"]["sigir"]["key_stated"]["key"] == "v2" and "refused" not in rep["sets"]["sigir"]["key_v2"]
    assert replay.main([*args, "--require-targets"]) == 3  # no tcga: the pathology figure is not within the target
