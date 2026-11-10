"""The committed goldens (T-006, D-205, TST-GOLD-01): the comparison, the write rule, the 50k path, and the cheap
parts of the gate that run in every ``make test`` (the lake schema, one golden per ruleset, size). The full 5k
build is ``make goldens-check`` (about 2 minutes)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools import goldens as g

GOLDEN = g.GOLDEN_DIR


def committed() -> dict[str, dict[str, Any]]:
    return {
        str(p.relative_to(GOLDEN)): json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(GOLDEN.rglob("*.json"))
        if "@50k" not in p.name
    }


def test_check_passes_on_identical() -> None:
    res = g.compare(GOLDEN, committed())
    assert res.ok, res.lines


def test_head_and_reason_do_not_count() -> None:
    now = committed()
    for body in now.values():
        body["meta"] = {**body["meta"], "head": "f" * 40, "reason": "D-999: another branch"}
    assert g.compare(GOLDEN, now).ok


def test_fails_on_one_count_and_names_the_criterion() -> None:
    now = committed()
    rem = now["funnels/GOUT-COH@ci.json"]["sets"]["synthetic-jp-a"]["remaining"]
    rem["GOUT-COH-INC-03"] -= 1
    res = g.compare(GOLDEN, now)
    assert not res.ok
    text = "\n".join(res.lines)
    assert "FAIL funnels/GOUT-COH@ci.json: 1 value(s) changed" in text
    assert "synthetic-jp-a.remaining.GOUT-COH-INC-03" in text
    assert any(line.startswith("+") and "GOUT-COH-INC-03" in line for line in res.lines)  # the unified diff


def test_fails_on_a_changed_candidate() -> None:
    now = committed()
    s = now["screen/GOUT-COH@ci.candidates.json"]["sets"]["synthetic-tw-a"]
    s["candidate_pids"] = s["candidate_pids"][1:]
    res = g.compare(GOLDEN, now)
    assert not res.ok and any("candidate_pids" in line and "-1" in line for line in res.lines), res.lines


def test_fails_on_a_column_drift() -> None:
    now = committed()
    cols = now["lake/tables@ci.json"]["sets"]["synthetic-jp-a"]["tables"]["encounter"]["columns"]
    col = sorted(cols)[0]
    cols[col] = "0" * 64
    res = g.compare(GOLDEN, now)
    assert not res.ok and any(f"encounter.columns.{col}" in line for line in res.lines)


def test_fails_on_a_missing_ruleset() -> None:
    now = committed()
    del now["funnels/RA-BIO@ci.json"]
    res = g.compare(GOLDEN, now)
    assert not res.ok and any("FAIL funnels/RA-BIO@ci.json: committed, but nothing computes it" in x for x in res.lines)


def test_fails_on_a_ruleset_without_a_golden() -> None:
    now = committed()
    now["funnels/NEW-STUDY@ci.json"] = copy.deepcopy(now["funnels/RA-BIO@ci.json"])
    res = g.compare(GOLDEN, now)
    assert not res.ok and any("FAIL funnels/NEW-STUDY@ci.json: no committed golden" in x for x in res.lines)


def test_fails_on_a_schema_sha_change() -> None:
    now = committed()
    now["lake/schema@2.json"]["schema_sha"] = "0" * 64
    res = g.compare(GOLDEN, now)
    assert not res.ok and any(x.startswith("  schema_sha:") for x in res.lines), res.lines


def test_a_new_schema_version_needs_its_golden() -> None:
    now = committed()
    body = now.pop("lake/schema@2.json")
    now["lake/schema@3.json"] = {**body, "version": 3}
    text = "\n".join(g.compare(GOLDEN, now).lines)
    assert "lake/schema@3.json: no committed golden" in text and "lake/schema@2.json: committed, but" in text


def test_ruleset_version_counts() -> None:
    now = committed()
    now["funnels/GZQO@ci.json"]["meta"]["ruleset_version"] = "9.9.9"
    assert not g.compare(GOLDEN, now).ok


# ---------------------------------------------------------------- the live parts of the gate (every make test)
def test_lake_schema_golden_is_the_code() -> None:
    """``lake.flatten.SCHEMAS``, the chunk columns and ``schema_sha`` as committed; a change regenerates the golden."""
    rel, body = g.schema_golden()
    path = GOLDEN / rel
    assert path.exists(), f"{rel} missing: a lake schema version change needs its golden (tools.goldens --write)"
    res = g.compare(GOLDEN, {**committed(), rel: body})
    assert res.ok, res.lines


def test_every_ruleset_has_its_goldens() -> None:
    from tools.omop_parity import RULESETS, load_ruleset

    for d in RULESETS:
        rs = load_ruleset(d)
        for rel in (f"funnels/{rs.id}@ci.json", f"screen/{rs.id}@ci.candidates.json"):
            body = json.loads((GOLDEN / rel).read_text(encoding="utf-8"))
            assert body["meta"]["ruleset_version"] == rs.version, (rel, rs.version)
            assert set(body["sets"]) == {
                "synthetic-jp-a",
                "synthetic-jp-a-deletes",
                "synthetic-tw-a",
                "ssmix2-jp",
                "public-en",
            }


def test_goldens_carry_their_provenance_and_cover_the_kinds() -> None:
    for rel, body in committed().items():
        meta = body["meta"]
        assert meta["lake_schema_version"] == 2, rel
        assert meta["head"] and g.REASON_RE.search(meta["reason"]), rel
        if not rel.startswith("lake/schema@"):
            assert meta["seed"] == g.SEED and meta["profile"] == "ci", rel
        assert (GOLDEN / rel).read_text(encoding="utf-8") == g.dumps(body), f"{rel} is not sorted canonical JSON"
    sets = committed()["lake/tables@ci.json"]["sets"]
    kinds = {v["kind"] for v in sets.values()}
    assert {
        "csv feed + site inputs",
        "deletes (tombstones)",
        "notes only (public text)",
        "SS-MIX2 storage (HL7 v2)",
    } <= kinds
    assert {v["tz"] for v in sets.values()} == {"Asia/Tokyo", "Asia/Taipei"}
    dele, base = sets["synthetic-jp-a-deletes"]["tables"], sets["synthetic-jp-a"]["tables"]
    assert dele["condition"]["rows"] < base["condition"]["rows"] and dele["patient"]["rows"] == base["patient"]["rows"]
    assert dele["site_fact"]["rows"] < base["site_fact"]["rows"]


def test_goldens_are_small() -> None:
    total = sum(p.stat().st_size for p in GOLDEN.rglob("*") if p.is_file())
    assert total < 2_000_000, total


# ---------------------------------------------------------------- the write rule
def test_write_without_a_reason_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert g.main(["--write", "--golden-dir", str(tmp_path)]) == 2
    assert g.main(["--write", "--reason", "  ", "--golden-dir", str(tmp_path)]) == 2
    assert "refused" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="reason"):
        g.write(tmp_path, committed(), "", "legacy")


def test_write_keeps_unchanged_files_and_records_the_reason(tmp_path: Path) -> None:
    gd = tmp_path / "golden"
    shutil.copytree(GOLDEN, gd)
    now = committed()
    assert g.write(gd, now, "D-999: nothing moved", "legacy") == []
    now["funnels/GZQO@ci.json"]["sets"]["public-en"]["start"] += 1
    assert g.write(gd, now, "D-999: one more patient", "omop") == ["funnels/GZQO@ci.json"]
    meta = json.loads((gd / "funnels/GZQO@ci.json").read_text(encoding="utf-8"))["meta"]
    assert meta["reason"] == "D-999: one more patient" and meta["written_with_source"] == "omop"
    assert g.compare(gd, now).ok


# ---------------------------------------------------------------- the 50k goldens: only from a run's report
def _report(**kw: Any) -> dict[str, Any]:
    rep: dict[str, Any] = {
        "schema": "tb-complete-run/3",
        "git": {"head": "abc"},
        "patients": 50_000,
        "run_ids": ["run-5"],
        "parts": [
            {"tag": "hospital-ja", "screen": {"funnel": [["S0", 9], ["S1", 5]], "tiers": {"high": 2}, "listed": 2}},
            {"tag": "public-en", "stages": []},
        ],
    }
    rep.update(kw)
    return rep


def test_50k_from_a_run_report(tmp_path: Path) -> None:
    out = g.from_report(_report())
    (rel, body), *_ = out.items()
    assert rel.endswith("@50k.json") and body["meta"]["run_ids"] == ["run-5"]
    assert body["parts"] == {"hospital-ja": {"screen_funnel": {"S0": 9, "S1": 5}, "tiers": {"high": 2}, "listed": 2}}
    assert g.write(tmp_path, out, "D-999: run 5", None) == [rel]
    later = g.from_report(_report(run_ids=["run-6"], git={"head": "def"}))
    assert g.compare(tmp_path, later, "50k").ok  # another run with the same numbers
    later[rel]["parts"]["hospital-ja"]["screen_funnel"]["S1"] = 4
    res = g.compare(tmp_path, later, "50k")
    assert not res.ok and any("hospital-ja.screen_funnel.S1: 5 -> 4" in x for x in res.lines)


@pytest.mark.parametrize(
    ("kw", "why"),
    [({"patients": 5000}, "not 50k"), ({"run_ids": []}, "run id"), ({"schema": "x"}, "complete_run"),
     ({"parts": [{"tag": "a"}]}, "SCREEN funnel")],
)  # fmt: skip
def test_50k_refuses_anything_but_a_50k_run(kw: dict[str, Any], why: str) -> None:
    with pytest.raises(ValueError, match=why):
        g.from_report(_report(**kw))


def test_50k_is_never_generated_locally(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert g.main(["--write", "--profile", "50k", "--reason", "D-999: x", "--golden-dir", str(tmp_path)]) == 2
    assert "only from a run's report" in capsys.readouterr().out
    assert g.main(["--check", "--profile", "50k", "--golden-dir", str(tmp_path)]) == 0


def test_the_next_night_drops_records_but_never_a_patient(tmp_path: Path) -> None:
    src = tmp_path / "a"
    src.mkdir()
    for t in ("Patient", "Condition"):
        (src / f"{t}.ndjson").write_text("".join(json.dumps({"id": f"{t}{i}"}) + "\n" for i in range(20)))
    g.next_night(src, tmp_path / "b")
    read = {t: (tmp_path / "b" / f"{t}.ndjson").read_text().splitlines() for t in ("Patient", "Condition")}
    assert len(read["Patient"]) == 20 and len(read["Condition"]) == 18
