"""Card H-4 (lane H, 2026-11-17): the offline replay of a stored launch (D-1111, D-1112).

The run is a slice of launch P1b's stored sets, ``tests/fixtures/public_accuracy_p1b/replay_slice.json``: seven sigir
protocols (public SIGIR 2016, NCBI, ``eval/criterion_ml/LICENSE.NCBI``; protocol text from ClinicalTrials.gov) and
the two jmed protocols over six patients (synthetic JMED-Personas by Sociocom, NAIST, CC BY 4.0), with their stored
answers, job ids and model replies. Chart numbers are kept as offsets and made here, at run time, from the set's
offset (``site.SET_OFFSETS``); the jmed notes (the judge's excerpts) are not in it."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import replay, site

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "tests" / "fixtures" / "public_accuracy_p1b" / "replay_slice.json"
POC1 = ROOT / "docs" / "plan" / "measurements" / "poc-1-2026-11-15"
DAY = date(2026, 11, 16)  # launch P1b's build and SCREEN day (MANIFEST.json, launch_p1b.build_day)


def _write_set(d: Path, name: str, s: dict[str, Any]) -> Path:
    mrn0 = site.SET_OFFSETS[name][0]

    def mrn(off: Any) -> str:
        return str(mrn0 + int(off))

    gold, work = d / "built" / "gold", d / "work"
    gold.mkdir(parents=True)
    work.mkdir(parents=True)
    ids = {**s["ids"], "patients": {p: mrn(o) for p, o in s["ids"]["patients"].items()}}
    (gold / "ids.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")
    for f in ("pairs", "criteria"):
        rows = [{**r, "mrn": mrn(r["mrn"])} for r in s[f]]
        (gold / f"{f}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    (gold / "compile_gold.json").write_text("{}", encoding="utf-8")
    (work / "answers.json").write_text(json.dumps(s["answers"], ensure_ascii=False), encoding="utf-8")
    (work / "progress.json").write_text(json.dumps(s["progress"]), encoding="utf-8")
    (work / "pidmap.json").write_text(json.dumps({mrn(o): p for o, p in s["pidmap"].items()}), encoding="utf-8")
    (work / "raw-traces.json").write_text(json.dumps({"traces": s["traces"]}, ensure_ascii=False), encoding="utf-8")
    return d


def _tgz(src: Path, out: Path) -> Path:
    with tarfile.open(out, "w:gz") as tar:
        for sub in ("built", "work"):
            tar.add(src / sub, arcname=sub)
    return out


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The slice as the driver stores it (one tarball per set), replayed once at both levels."""
    tmp = tmp_path_factory.mktemp("h4")
    sl = json.loads(SLICE.read_text(encoding="utf-8"))
    tgz = tmp / "stored"
    tgz.mkdir()
    for name, s in sl["sets"].items():
        _tgz(_write_set(tmp / "src" / name, name, s), tgz / f"{name}.tgz")
    # the slice is part of P1b's gold, so it cannot match MANIFEST.json's pins: key v2 is applied to it by leave of
    # the test (require_pin=False); the command line never gives that leave
    rep = replay.replay([tgz], tmp / "scratch", pathology_run=POC1, index_day=DAY, build_day=DAY, require_pin=False)
    return {"tmp": tmp, "tgz": tgz, "report": rep}


# ---------------------------------------------------------------- the safe extractor
def _tar(entries: list[tarfile.TarInfo], tmp: Path) -> Path:
    p = tmp / "bad.tgz"
    with tarfile.open(p, "w:gz") as tar:
        for ti in entries:
            tar.addfile(ti, io.BytesIO(b"x" * ti.size) if ti.isreg() else None)
    return p


def _member(name: str, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name)
    ti.type = kind
    ti.size = 1 if kind == tarfile.REGTYPE else 0
    ti.linkname = link
    return ti


@pytest.mark.parametrize(
    "bad",
    [
        _member("../escape.txt"),
        _member("/abs/escape.txt"),
        _member("work/../../escape.txt"),
        _member("work/link", tarfile.SYMTYPE, "/etc/hostname"),
        _member("work/hard", tarfile.LNKTYPE, "work/answers.json"),
        _member("work/fifo", tarfile.FIFOTYPE),
        _member("work/dev", tarfile.CHRTYPE),
    ],
    ids=["parent", "absolute", "parent-inside", "symlink", "hardlink", "fifo", "device"],
)
def test_the_extractor_refuses_an_unsafe_member_and_writes_nothing(tmp_path: Path, bad: tarfile.TarInfo) -> None:
    arc = _tar([_member("work/answers.json"), bad], tmp_path)
    dest = tmp_path / "out"
    with pytest.raises(replay.Refused):
        replay.safe_extract(arc, dest)
    assert not dest.exists() or not any(dest.rglob("*"))
    assert not (tmp_path / "escape.txt").exists()


def test_the_extractor_unpacks_plain_files_outside_the_repository_only(tmp_path: Path) -> None:
    arc = _tar([_member("built/gold/ids.json"), _member("work/answers.json")], tmp_path)
    assert sorted(replay.safe_extract(arc, tmp_path / "out")) == ["built/gold/ids.json", "work/answers.json"]
    with pytest.raises(replay.Refused, match="not empty"):
        replay.safe_extract(arc, tmp_path / "out")
    with pytest.raises(replay.Refused, match="outside the repository"):
        replay.safe_extract(arc, ROOT / "tests" / "never-written")
    assert not (ROOT / "tests" / "never-written").exists()


# ---------------------------------------------------------------- level (a)
def test_level_a_scores_the_stored_verdicts_on_key_v1_and_v2(run: dict[str, Any]) -> None:
    r = run["report"]
    assert sorted(r["sets"]) == ["jmed", "sigir"] and r["schema_version"] == replay.SCHEMA_VERSION
    jm = r["sets"]["jmed"]
    assert jm["key_v2"]["applied"] == 4  # the slice's four MANIFEST rows; the others' patients are not in it
    v2 = jm["level_a"]["v2"]
    assert v2["answer_key"]["key"] == "v2" and "MANIFEST.json" in v2["answer_key"]["how"]
    assert v2["scorer_read_the_folder_as"]["key"] == "v1"  # no key.json: the scorer's own reading, kept apart
    a1 = r["targets"]["eligible_wrongly_excluded"]["a"]["v1"]
    a2 = r["targets"]["eligible_wrongly_excluded"]["a"]["v2"]
    by1 = {x["set"]: x for x in a1["per_set"]}
    by2 = {x["set"]: x for x in a2["per_set"]}
    # jmed, key v1: four rows "not excluded" the box blocked on their own line (one DM, three HT). Key v2 calls the three
    # HT rows "excluded" (key faults, B3) and one HT row it now calls "not excluded" was blocked by the box
    assert (by1["jmed"]["numerator"], by1["jmed"]["denominator"]) == (4, 9)
    assert (by2["jmed"]["numerator"], by2["jmed"]["denominator"]) == (2, 7)
    # sigir: the infant of NCT01260883 and the 25-year-old of NCT00606840 (an age line each) are eligible and excluded
    assert (
        (by1["sigir"]["numerator"], by1["sigir"]["denominator"])
        == (2, 2)
        == (
            by2["sigir"]["numerator"],
            by2["sigir"]["denominator"],
        )
    )
    assert a1["level"] == "a" and a1["met"] is False and a1["within_target"] is False


def test_the_p1b_record_is_checked_only_on_p1bs_own_key(run: dict[str, Any]) -> None:
    for s in run["report"]["sets"].values():
        assert s["identified"]["launch_p1b_key_v1"] is False and "p1b_record" not in s  # a slice is not P1b's key
    full = {"pairs": {"summary": {"en": {"eligible_lost": {"k": 4, "n": 30}}}}}
    assert replay._record("sigir", full)["reproduced"] is True
    crit = {"criteria": {"wrong_exclusion": {"k": 7, "n": 321}, "no_verdict": 34, "caught": {"k": 182, "n": 239}}}
    assert replay._record("jmed", crit)["reproduced"] is True


# ---------------------------------------------------------------- level (b)
def _failed(run: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = run["report"]["sets"]["sigir"]["level_b"]["failed_protocols"]
    return out


def test_a_feas_equivalence_failure_whose_valueset_id_was_over_64_is_gone_on_rerun(run: dict[str, Any]) -> None:
    row = _failed(run)["Sm2NCT00493103"]
    assert row["class"] == "feas_equivalence" and row["compile"] == "compiled"
    assert row["checks"]["valuesets_whose_p1b_style_id_is_over_64"] >= 1  # P1b's <ruleset>-<name> id
    assert row["checks"]["valueset_ids_are_fhir_ids"] is True and row["outcome"] == "cause_gone"


def test_an_ir_extract_failure_is_not_rerun_and_still_counts(run: dict[str, Any]) -> None:
    row = _failed(run)["Sm2NCT02378311"]
    assert row["class"] == "feas_ir_extract" and row["outcome"] == "not_rerun"
    assert "stored no reply" in row["compile_message"]
    b = run["report"]["targets"]["protocols_failing"]["b"]
    assert "Sm2NCT02378311" not in " ".join(b["no_longer_failing"]) and b["still_failing_by_outcome"]["not_rerun"] >= 1


def test_screen_failures_running_and_judging_are_rerun(run: dict[str, Any]) -> None:
    f = _failed(run)
    assert f["Sm2NCT01723137"]["class"] == "screen_running" and f["Sm2NCT01723137"]["outcome"] == "cause_gone"
    j = f["Sm2NCT00277680"]
    assert j["class"] == "screen_judging" and j["checks"]["stored_replies"] >= 1
    assert j["checks"]["still_no_answer"] == 0 and j["outcome"] == "cause_gone"  # G8: "0000-01-01" is no date


def test_the_protocol_figure_keeps_failures_not_rerun_and_counts_both_shares(run: dict[str, Any]) -> None:
    t = run["report"]["targets"]["protocols_failing"]
    a, b = t["a"], t["b"]
    # the slice: 4 sigir failures + 2 sigir and 2 jmed screened attempted; one budget cut, not attempted
    assert a["per_set"]["sigir"]["not_run_time_budget"] == 1
    assert (a["numerator"], a["denominator"], a["failed_before_screen"]) == (4, 8, 2)
    assert (b["numerator"], b["denominator"], b["failed_before_screen"]) == (1, 8, 1)
    assert a["within_target"] is False and b["within_target"] is False  # 1 of 8 is not fewer than one in ten
    assert a["met"] is False and b["met"] is False  # D-1064 item 4: never met by a replay
    assert b["proof"].startswith("cause-level")


def test_coded_age_lines_are_decided_again_on_each_keys_birth_dates(run: dict[str, Any]) -> None:
    sb = run["report"]["sets"]["sigir"]["level_b"]
    assert sb["rescreen"]["v1"]["calibration_on_key_v1"] == {"agrees": 1}  # the stored coded verdict, reproduced
    t = run["report"]["targets"]["eligible_wrongly_excluded"]["b"]
    b1 = {x["set"]: x for x in t["v1"]["per_set"]}
    b2 = {x["set"]: x for x in t["v2"]["per_set"]}
    # F2 (D-946): "Aged 0.17 years or older" goes to a person; D-945: "Age outside of range specified" is the range's
    # complement, which a 25-year-old is not in
    assert (b1["sigir"]["numerator"], b1["sigir"]["denominator"]) == (0, 2)
    # jmed: the inference guard (F6, D-985) sends two stored note exclusions to review; on key v2 none is left
    assert (b1["jmed"]["numerator"], b2["jmed"]["numerator"], b2["jmed"]["denominator"]) == (3, 0, 7)
    assert t["v2"]["within_target"] is True and t["v2"]["level"] == "b"
    assert t["v2"]["met"] is False and "launch" in t["v2"]["met_only_by"]  # D-1064 item 4: met only by a launch


def test_jmed_age_evidence_is_pooled_over_the_patients_protocols(run: dict[str, Any]) -> None:
    jb = run["report"]["sets"]["jmed"]["level_b"]
    assert "none known here" in jb["rescreen"]["v1"]["birth_dates"]
    changed = jb["rescreen"]["v1"]["verdicts_changed"]
    assert changed.get("pending_human -> pass", 0) + changed.get("pending_human -> fail", 0) >= 1, changed


# ---------------------------------------------------------------- the pathology figure (D-1112)
def test_a_run_without_tcga_is_not_scored_and_not_met(run: dict[str, Any]) -> None:
    p = run["report"]["targets"]["pathology"]
    assert p["run"]["scored"] is False and p["run"]["met"] is False
    assert "no tcga set" in p["run"]["not_scored_because"] and "Gm2TCGA-BRCA" in p["run"]["not_scored_because"]
    assert run["report"]["met"]["pathology"] is False


def test_poc1s_stored_counts_are_read_back_not_rescored(run: dict[str, Any]) -> None:
    sc = run["report"]["targets"]["pathology"]["stored_counts"]
    assert sc["re_scored"] is False and "counts only" in sc["could_not"]
    ok = [x for x in sc["runs"] if x.get("matches_the_claim")]
    assert [(x["file"], x["set"]) for x in ok] == [("sets-b266f9b7.json", "tcga_brca_gate_ok")]
    assert (ok[0]["excluded"], ok[0]["ineligible"], ok[0]["wrong_exclusions"], ok[0]["eligible_lost"]) == (
        384,
        450,
        0,
        0,
    )


# ---------------------------------------------------------------- the command line
def test_the_command_line_writes_json_and_exits_by_the_flag(run: dict[str, Any], capsys: Any) -> None:
    tmp, tgz = run["tmp"], run["tgz"]
    out = tmp / "report.json"
    args = [str(tgz / "sigir.tgz"), "--json", str(out), "--build-day", "2026-11-16", "--no-rerun"]
    assert replay.main(args) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["targets"]["eligible_wrongly_excluded"]["a"]["v1"]["met"] is False and "b" not in rep["met"]
    said = capsys.readouterr().out
    assert "1. Eligible patients wrongly excluded" in said and "not scored" in said
    assert replay.main([*args, "--require-targets"]) == 3
    # key v2's rows are P1b's: a gold that is not P1b's pinned key v1 is refused, and its v2 figure is not scored
    assert "refused" in rep["sets"]["sigir"]["key_v2"]
    v2 = rep["targets"]["eligible_wrongly_excluded"]["a"]["v2"]
    assert v2["all_sets_scored"] is False and v2["met"] is False and v2["per_set"][0]["scored"] is False
    bad = _tar([_member("../escape.txt")], tmp)
    assert replay.main([str(bad)]) == 2
