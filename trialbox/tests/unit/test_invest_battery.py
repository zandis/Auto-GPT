"""The investigation battery (bench/invest/analysis): one closed code per failure row, the preventable rule, grouping
and maps over a small ledger, the repeat join, the real-data export that suppresses and refuses, the renderer's
real-data section, residual clustering, and the metamorphic transforms. Synthetic rows only."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tb_common.reasons import CODES as REASONS
from tb_common.ruleset import Ruleset

from bench.invest import export, ledger
from bench.invest.analysis import battery, cluster, findings, metamorphic, taxonomy

ROOT = Path(__file__).resolve().parents[2]
ATOMS_LAB = json.dumps([{"domain": "observation", "valueset": "VS_HBA1C", "quantifier": "latest"}])
ATOMS_DX = json.dumps([{"domain": "condition", "valueset": "VS_GOUT", "quantifier": "any"}])


def _crits() -> list[Any]:
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    return [c for c in rs.active() if c.kind in ("inclusion", "exclusion")]


def _ledger(root: Path, rows: list[dict[str, Any]], tag: str = "a") -> Path:
    header = {"code_sha": tag, "sets_json": {"synthetic": ["GZQO"]}}
    w = ledger.LedgerWriter(root, ledger.run_id_of(header), header)
    for r in rows:
        w.add("match_stage", "GZQO", {"protocol_id": "GZQO", "attempt": 0, **r})
    w.close()
    return w.dir


def _rows(crits: list[Any]) -> list[dict[str, Any]]:
    a, b, c = crits[0], crits[1], crits[2]
    rows: list[dict[str, Any]] = []
    for i in range(30):  # a site gap, inherent
        rows.append({"pid": f"p{i}", "criterion_id": a.id, "stage": "S1", "verdict": "U", "reason_code": "data_gap",
                     "unknown_kind": "data_gap", "atoms_json": ATOMS_LAB, "basis": "coded"})  # fmt: skip
    for i in range(12):  # a code the list does not hold, preventable
        rows.append({"pid": f"p{i}", "criterion_id": b.id, "stage": "S1", "verdict": "U",
                     "reason_code": "code_outside_list", "unknown_kind": "data_gap", "atoms_json": ATOMS_DX,
                     "basis": "coded"})  # fmt: skip
    want = "T" if c.kind == "exclusion" else "F"  # gold "yes" passes an inclusion, fails an exclusion
    for i in range(11):  # decided against gold
        rows.append({"pid": f"p{i}", "criterion_id": c.id, "stage": "S3", "verdict": want, "reason_code": "note",
                     "basis": "pair", "gold": json.dumps("yes"), "atoms_json": "[]"})  # fmt: skip
    for i in range(40):  # settled, not failures
        rows.append({"pid": f"q{i}", "criterion_id": a.id, "stage": "S1", "verdict": "T", "reason_code": "coded",
                     "basis": "coded", "atoms_json": ATOMS_LAB})  # fmt: skip
    rows.append({"pid": "q0", "criterion_id": b.id, "stage": "S5", "verdict": "U", "reason_code": "human",
                 "unknown_kind": "pending_human", "basis": "person"})  # fmt: skip
    return rows


def test_every_product_reason_maps_to_one_closed_code_or_is_by_design() -> None:
    by_design = set()
    for r in sorted(REASONS):
        hit = taxonomy.classify_match("S1", "U", r, "data_gap")
        if hit is None:
            by_design.add(r)
        else:
            assert hit[0] in taxonomy.CODES and hit[1] in ("preventable", "inherent", "undetermined")
            assert hit[0] in taxonomy.INSTRUMENT
    assert by_design == {"human"}
    assert taxonomy.classify_match("S0", "F", "out_of_scope", None) is None
    assert taxonomy.classify_match("tier", "not_applicable", "strong", None) is None
    assert taxonomy.classify_match("S1", "not_applicable", "not_evaluated", None) is None
    assert taxonomy.classify_match("S2", "U", "not_evaluated", "uncertain") == ("P5", "preventable")
    assert taxonomy.classify_match("S3", "U", "veto status:stated", None, "T") == ("P7", "preventable")


def test_gold_verdict_follows_the_products_oracle() -> None:
    assert taxonomy.gold_verdict('"yes"', "inclusion") == "T"
    assert taxonomy.gold_verdict('"yes"', "exclusion") == "F"
    assert taxonomy.gold_verdict('"no"', "exclusion") == "T"
    assert taxonomy.gold_verdict('"unknown"', "inclusion") == "U"
    assert taxonomy.gold_verdict('"F"', None) == "F"
    assert taxonomy.gold_verdict('"yes"', None) is None
    assert taxonomy.gold_verdict(None, "inclusion") is None


def test_the_preventable_rule_reads_only_ledger_columns() -> None:
    c = taxonomy.classify_match
    assert c("S1", "U", "code_outside_list", "data_gap") == ("P2", "preventable")
    assert c("S1", "U", "data_gap", "data_gap") == ("P1", "inherent")
    assert c("S1", "U", "data_gap", "data_gap", "T") == ("P1", "preventable")  # gold: the record holds the answer
    assert c("S1", "U", "data_gap", "data_gap", "U") is None  # gold: an unknown is right
    assert c("S3", "U", "abstained", "uncertain") == ("P6", "undetermined")  # passages not kept: cannot tell
    assert c("S3", "T", "note", None, "F") == ("P9", "preventable")
    assert c("S3", "T", "note", None, "U") == ("P6", "preventable")
    assert c("S3", "T", "note", None, "T") is None
    assert c("S3", "T", "note", None) is None  # no gold: a decided answer is not a failure
    assert taxonomy.classify_trial("card_proposal", "no_card", None) == ("T8", "preventable")
    assert taxonomy.classify_trial("equivalence", "CompileError", None) == ("T11", "preventable")
    assert taxonomy.classify_trial("compile_sql", "ok", None) is None


def test_the_battery_groups_failures_largest_first_with_shares_and_the_gap_map(tmp_path: Path) -> None:
    crits = _crits()
    d = _ledger(tmp_path, _rows(crits))
    con = battery.open_runs([d])
    meta = battery.criteria_meta(["GZQO"])
    b = battery.run_battery(con, meta, name="t")
    assert b["criterion_rows"] == 30 + 12 + 11 + 40 + 1
    assert b["failure_rows"] == 30 + 12 + 11
    sizes = [(c["code"], c["n"], c["preventable_share"]) for c in b["clusters"]]
    assert sizes == [("P1", 30, 0.0), ("P2", 12, 1.0), ("P9", 11, 1.0)]
    assert b["clusters"][0]["criteria"] == {f"GZQO/{crits[0].id}": 30}
    assert b["clusters"][0]["instrument"] == taxonomy.INSTRUMENT["P1"]
    assert b["by_code"]["P2"] == {"n": 12, "preventable_n": 12, "undetermined_n": 0}
    gap = {(g["view"], g["field"], g["reason_code"]): g["n"] for g in b["data_gap"]}
    assert gap == {("lab+vital", "VS_HBA1C", "data_gap"): 30, ("diagnosis", "VS_GOUT", "code_outside_list"): 12}
    acc = {r["protocol_id"]: r for r in b["accuracy"]}["GZQO"]
    assert (acc["n"], acc["wrong_decided"], acc["correct"]) == (11, 11, 0)
    assert b["retrieval"]["status"] == "no_data"


def test_the_repeat_join_flags_a_coded_flip_as_a_product_bug(tmp_path: Path) -> None:
    crits = _crits()
    rows = _rows(crits)
    flipped = [dict(r) for r in rows]
    first_settled = next(i for i, r in enumerate(rows) if r["pid"] == "q0")
    flipped[first_settled]["verdict"] = "F"  # one settled coded answer of criterion a
    a = battery.open_runs([_ledger(tmp_path / "a", rows)])
    b = battery.open_runs([_ledger(tmp_path / "b", flipped, tag="b")])
    table = {(r["criterion_id"], r["basis"]): r for r in battery.diff_runs(a, b)}
    row = table[(crits[0].id, "coded")]
    assert (row["changed"], row["coded_bug"]) == (1, True)
    assert all(not r["changed"] for k, r in table.items() if k != (crits[0].id, "coded"))


def test_the_real_export_suppresses_small_cells_and_refuses_planted_leaks(tmp_path: Path) -> None:
    crits = _crits()
    d = _ledger(tmp_path / "l", _rows(crits))
    con = battery.open_runs([d])
    meta = battery.criteria_meta(["GZQO"])
    b = battery.run_battery(con, meta, name="twin")
    pids = {r[0] for r in con.execute("SELECT DISTINCT pid FROM match_stage").fetchall()}
    known = findings.known_ids(meta, ["GZQO"])
    out = battery.write_real(tmp_path / "ok.json", b, pids, known)
    clean = json.loads(out.read_text("utf-8"))
    assert all(c["n"] is None or c["n"] >= 10 for c in clean["clusters"])
    assert {r["protocol_id"]: r["n"] for r in clean["accuracy"]}["GZQO"] == 11

    def planted(fn: Any) -> dict[str, Any]:
        x: dict[str, Any] = battery.suppress(json.loads(json.dumps(b)))
        fn(x)
        return x

    leaks = {
        "pid": lambda x: x["clusters"][0]["criteria"].update({f"GZQO/{crits[0].id}-p7": 12}),
        "date": lambda x: x["clusters"][0].update({"reason_code": "2026-03-14"}),
        "quote": lambda x: x["clusters"][0].update({"name": "痛風發作，關節紅腫"}),
        "small": lambda x: x["clusters"][0].update({"n": 4}),
        "foreign_id": lambda x: x["clusters"][0]["protocols"].update({"NOT-A-RULESET": 20}),
    }
    for what, fn in leaks.items():
        with pytest.raises(battery.Refused):
            battery.refuse(planted(fn), pids | {"p7"}, known)
        assert what  # each leak refused on its own
    with pytest.raises(battery.Refused):
        battery.write_real(tmp_path / "bad.json", planted(leaks["quote"]), pids, known)
    assert not (tmp_path / "bad.json").exists()


def test_a_share_is_blanked_with_its_suppressed_numerator() -> None:
    out = battery.suppress({"n": 200, "preventable_n": 4, "preventable_share": 0.02, "changed": 3, "rate": 0.015})
    assert out == {"n": 200, "preventable_n": None, "preventable_share": None, "changed": None, "rate": None}


def test_the_renderer_refuses_a_real_section_with_a_quote_and_renders_counts(tmp_path: Path) -> None:
    crits = _crits()
    con = battery.open_runs([_ledger(tmp_path, _rows(crits))])
    meta = battery.criteria_meta(["GZQO"])
    real = battery.suppress(battery.run_battery(con, meta, name="twin"))
    text = findings.render([], real, None, "R1")
    assert "## Real data (counts only)" in text and "| D001 |" in text
    bad = json.loads(json.dumps(real))
    bad["clusters"][0]["name"] = "病人表示關節痛"
    with pytest.raises(battery.Refused):
        findings.render([], bad, None, "R1")


def test_residual_clustering_is_deterministic_and_names_without_a_server() -> None:
    x = np.vstack([np.random.default_rng(0).normal(0, 0.01, (6, 4)), np.random.default_rng(1).normal(5, 0.01, (6, 4))])
    labels = cluster.kmeans(x, 2)
    assert len(set(labels[:6])) == 1 and len(set(labels[6:])) == 1 and labels[0] != labels[6]
    assert (cluster.kmeans(x, 2) == labels).all()
    labs, method = cluster.cluster(x)
    assert len(labs) == 12 and method in ("kmeans", "hdbscan+kmeans")
    recs = [{"protocol_id": "GZQO", "criterion_id": f"c{i}", "stage": "S1", "verdict": "U", "gold": None,
             "family": "observation", "reason_code": "unit_mismatch", "code": "P3", "preventable": "preventable",
             "n": 10 + i} for i in range(4)]  # fmt: skip
    recs[3]["criterion_id"] = "c2"  # one criterion in two records: its rows add up
    out = cluster.residual_clusters(recs, [0, 0, 1, 1])
    assert [c["n"] for c in out] == [25, 21] and out[0]["cluster_id"] == "R001"
    assert out[0]["criteria"] == {"GZQO/c2": 25}
    assert out[0]["name"] == "unit mismatch in observation"
    assert battery._NAME.fullmatch(out[0]["name"])


def _site(d: Path) -> None:
    d.mkdir(parents=True)

    def w(name: str, cols: list[str], rows: list[list[str]]) -> None:
        with (d / f"{name}.csv").open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows([cols, *rows])

    w("patient", ["mrn", "birth_date", "sex"], [["1", "1960-01-01", "M"], ["2", "1970-02-02", "F"], ["3", "", "M"]])
    w("diagnosis", ["diag_no", "enc_no", "mrn", "icd10", "diag_date"],
      [["D1", "E1", "1", "M10.0", "2026-01-02"], ["D2", "E2", "2", "E11.9", "2026-02-03"], ["D3", "E3", "3", "M10.0", "2026-03-04"]])  # fmt: skip
    w("lab", ["lab_no", "mrn", "unit", "sample_datetime"],
      [["L1", "1", "mg/dL", "2026-03-15 15:30:00"], ["L2", "2", "%", "2026-03-16 08:00:00"]])  # fmt: skip
    w("medication", ["rx_no", "mrn", "start_date"], [["M1", "1", "2026-01-28"], ["M2", "2", "2026-02-01"]])
    w("vital", ["vital_no", "mrn", "measure_datetime"], [["V1", "1", "2026-05-08 15:50:00"]])
    w("practitioner", ["staff_id", "dept_code"], [["P1", "RHEU"]])
    (d / "meta.json").write_text(json.dumps({"ref_date": "2026-10-05", "site_id": "DEMO-A"}), encoding="utf-8")


def _csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_the_metamorphic_transforms_change_only_what_they_name(tmp_path: Path) -> None:
    _site(tmp_path / "src")
    keep = metamorphic.subsample(tmp_path / "src", tmp_path / "base", 2)
    assert keep == ["1", "2"] and len(_csv(tmp_path / "base" / "diagnosis.csv")) == 2
    assert json.loads((tmp_path / "base" / "meta.json").read_text("utf-8"))["counts"]["practitioner"] == 1

    def t(kind: str) -> Path:
        metamorphic.transform(tmp_path / "base", tmp_path / kind, kind, keep)
        return tmp_path / kind

    dx = _csv(t("irrelevant") / "diagnosis.csv")
    assert [r["icd10"] for r in dx].count(metamorphic.IRRELEVANT_ICD) == 2 and len(dx) == 4
    s = t("shift")
    assert _csv(s / "lab.csv")[0]["sample_datetime"] == "2026-03-16 15:30:00"
    assert _csv(s / "patient.csv")[0]["birth_date"] == "1960-01-02"
    assert json.loads((s / "meta.json").read_text("utf-8"))["ref_date"] == "2026-10-06"
    dup = _csv(t("duplicate") / "lab.csv")
    assert [r["lab_no"] for r in dup] == ["L1", "L2", "L1D", "L2D"]
    assert [r["unit"] for r in _csv(t("unit_case") / "lab.csv")] == ["mg/dl", "%"]
    assert [r["mrn"] for r in _csv(t("delete_lab") / "lab.csv")] == ["2"]  # patient 1 is in the emptied half
    assert _csv(tmp_path / "delete_lab" / "vital.csv") == []
    assert len(_csv(tmp_path / "delete_lab" / "diagnosis.csv")) == 2


def test_the_metamorphic_comparison_names_the_criterion_that_broke() -> None:
    base = {("R", "p1", "c1"): "T", ("R", "p2", "c1"): "F", ("R", "p1", "c2"): "U", ("R", "p1", "c3"): "T"}
    same = metamorphic.compare("duplicate", base, dict(base), {})
    assert same["pass"] and same["compared"] == 4
    moved = metamorphic.compare("duplicate", base, {**base, ("R", "p2", "c1"): "T"}, {})
    assert not moved["pass"] and moved["criteria"] == {"R/c1": 1}
    doms = {("R", "c1"): {"medication"}, ("R", "c3"): {"medication", "condition"}}
    gone = {("R", "p1", "c1"): "U", ("R", "p2", "c1"): "T", ("R", "p1", "c3"): "F"}
    d = metamorphic.compare("delete_medication", base, gone, doms)
    assert d["compared"] == 2 and d["criteria"] == {"R/c1": 1}  # c3 reads another table too: not compared
    lost = metamorphic.compare("delete_medication", base, {}, doms)
    assert lost["compared"] == 0 and lost["not_comparable"] == 2 and lost["pass"]


# ---- the real-data wall: defaults, no raw side files, nothing small or identifying on disk or on screen ----------------

PATS = [f"pat-77{i:02d}-x" for i in range(40)]


def _real_ledger(root: Path, sets: dict[str, Any]) -> Path:
    """25 failure groups of 3 rows each (a card id apart) over patient ids that must never leave, plus 30 big rows."""
    a = _crits()[0]
    header = {"code_sha": "r", "sets_json": sets}
    w = ledger.LedgerWriter(root, ledger.run_id_of(header), header)
    for g in range(25):
        for k in range(3):
            w.add("match_stage", "GZQO", {"protocol_id": "GZQO", "attempt": 0, "pid": PATS[(3 * g + k) % 40],
                                          "criterion_id": a.id, "stage": "S1", "verdict": "U", "card_id": f"card{g}",
                                          "reason_code": "data_gap", "unknown_kind": "data_gap", "basis": "coded",
                                          "atoms_json": ATOMS_LAB})  # fmt: skip
    for k in range(30):
        w.add("match_stage", "GZQO", {"protocol_id": "GZQO", "attempt": 0, "pid": PATS[k], "criterion_id": a.id,
                                      "stage": "S2", "verdict": "T", "reason_code": "coded", "basis": "coded"})  # fmt: skip
    w.close()
    return w.dir


def _clean(text: str) -> None:
    """No patient id and no count of 1..9 anywhere in ``text`` (a json file or a printed line)."""
    assert not any(p in text for p in PATS)
    for v in re.findall(r"(?<=[:\[,]) ?(\d+)(?=[,}\]\n])", text):
        assert not 0 < int(v) < export.MIN_CELL, text


def test_the_battery_command_protects_by_default_and_writes_no_raw_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _real_ledger(tmp_path / "real", {"real_twin": ["GZQO"]})  # not marked synthetic or public
    out, rec = tmp_path / "b.json", tmp_path / "rec.json"
    assert findings.main(["battery", "--runs", str(d), "--name", "twin", "--out", str(out), "--records", str(rec)]) == 0
    shown = capsys.readouterr()
    assert not rec.exists()  # R2: clustered in memory, only the protected aggregate is written
    assert json.loads(out.read_text("utf-8"))["residual"]
    for text in (out.read_text("utf-8"), shown.out):  # R1 (no flag), R3 (screen), R4 (the codes and stages maps)
        _clean(text)
    assert json.loads(shown.out)["clusters"] == 25 and "WARN" in shown.err
    out2 = tmp_path / "b2.json"  # --real gives the same file
    rec2 = tmp_path / "rec2.json"
    findings.main(["battery", "--runs", str(d), "--name", "twin", "--out", str(out2), "--records", str(rec2), "--real"])
    assert not rec2.exists()
    assert out2.read_text("utf-8") == out.read_text("utf-8")


def test_a_run_marked_synthetic_keeps_its_exact_counts_and_its_records_file(tmp_path: Path) -> None:
    d = _real_ledger(tmp_path / "syn", {"synthetic": ["GZQO"], "tag": "t"})
    out, rec = tmp_path / "b.json", tmp_path / "rec.json"
    findings.main(["battery", "--runs", str(d), "--name", "syn", "--out", str(out), "--records", str(rec)])
    assert rec.exists() and any(c["n"] == 3 for c in json.loads(out.read_text("utf-8"))["clusters"])


def test_the_residual_pass_checks_the_final_payload_against_the_source_ledgers_patient_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = _real_ledger(tmp_path / "real", {"real_twin": ["GZQO"]})
    out = tmp_path / "b.json"
    findings.main(["battery", "--runs", str(d), "--name", "twin", "--out", str(out)])
    con = battery.open_runs([d])
    meta = battery.criteria_meta(["GZQO"])
    recs = findings.residual_records(con, battery.run_battery(con, meta, name="twin"), meta)
    recs_f, labels_f = tmp_path / "recs.json", tmp_path / "labels.json"
    labels_f.write_text(json.dumps({"labels": [0] * len(recs), "method": "kmeans", "embedder": "hash"}), "utf-8")
    recs_f.write_text(json.dumps(recs), "utf-8")
    capsys.readouterr()
    argv = ["residual", "--battery", str(out), "--records", str(recs_f), "--labels", str(labels_f), "--real",
            "--runs", str(d)]  # fmt: skip
    assert findings.main(argv) == 0
    for text in (out.read_text("utf-8"), capsys.readouterr().out):
        _clean(text)
    before = out.read_text("utf-8")
    recs[0]["protocol_id"] = f"GZQO-{PATS[5]}"  # an identifier the records file brought in
    recs_f.write_text(json.dumps(recs), "utf-8")
    with pytest.raises(battery.Refused):
        findings.main(argv)
    assert out.read_text("utf-8") == before


def test_scalar_protocol_counts_and_the_code_and_stage_maps_are_suppressed_and_checked() -> None:
    raw = {"data_gap": [{"n": 50, "criteria": 3, "protocols": 2}],
           "residual": [{"n": 50, "codes": {"P1": 4, "P2": 30}, "stages": {"S1": 9, "S2": 12}}]}  # fmt: skip
    out = battery.suppress(raw)
    assert out["data_gap"][0] == {"n": 50, "criteria": None, "protocols": None}
    assert out["residual"][0]["codes"] == {"P1": None, "P2": 30}
    assert out["residual"][0]["stages"] == {"S1": None, "S2": 12}
    battery.refuse(out, (), ())
    for leak in ({"data_gap": [{"protocols": 2}]}, {"residual": [{"codes": {"P1": 4}}]},
                 {"residual": [{"stages": {"S1": 4}}]}):  # fmt: skip
        with pytest.raises(battery.Refused):
            battery.refuse(leak, (), ())


def test_a_latency_quantile_is_suppressed_by_the_number_of_timed_rows() -> None:
    out = battery.suppress({"n": 500, "timed": 1, "p50_ms": 120.0, "p99_ms": 120.0})
    assert out == {"n": 500, "timed": None, "p50_ms": None, "p99_ms": None}
    assert battery.suppress({"n": 500, "timed": 40, "p50_ms": 120.0})["p50_ms"] == 120.0


def test_suppressing_an_already_suppressed_battery_is_a_no_op() -> None:
    once = battery.suppress({"n": 50, "criteria": {"GZQO/a": 3, "GZQO/b": 30}, "protocols": {"GZQO": 3}, "changed": 2,
                             "rate": 0.04, "timed": 2, "p50_ms": 5.0})  # fmt: skip
    assert once["criteria"] == {"GZQO/a": None, "GZQO/b": 30}
    assert battery.suppress(once) == once


def test_the_repeat_join_pairs_stages_and_attempts_one_to_one(tmp_path: Path) -> None:
    a = _crits()[0]
    rows = [{"pid": "p0", "criterion_id": a.id, "stage": "S1", "attempt": 0, "verdict": "T", "basis": "coded"},
            {"pid": "p0", "criterion_id": a.id, "stage": "S1", "attempt": 1, "verdict": "F", "basis": "coded"},
            {"pid": "p0", "criterion_id": a.id, "stage": "S2", "attempt": 0, "verdict": "U", "basis": "coded"}]  # fmt: skip
    x = battery.open_runs([_ledger(tmp_path / "x", rows)])
    y = battery.open_runs([_ledger(tmp_path / "y", [dict(r) for r in rows], tag="y")])
    (row,) = battery.diff_runs(x, y)
    assert (row["n"], row["changed"]) == (3, 0)  # identical repeats: three answers, no change


def test_the_failure_share_is_patient_side_and_trial_failures_are_reported_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = battery.open_runs([_ledger(tmp_path, _rows(_crits()))])
    fake = [{"side": "patient", "n": 5}, {"side": "trial", "n": 200}]
    monkeypatch.setattr(battery, "failure_rows", lambda *_a, **_k: fake)
    monkeypatch.setattr(battery, "by_code", lambda _f: {})
    monkeypatch.setattr(battery, "group", lambda _f: [])
    monkeypatch.setattr(battery, "data_gap_map", lambda _f: [])
    b = battery.run_battery(con, {}, name="t")
    assert (b["failure_rows"], b["trial_failure_rows"]) == (5, 200) and b["failure_rows"] <= b["criterion_rows"]


def test_the_metamorphic_run_never_deletes_its_source(tmp_path: Path) -> None:
    work = tmp_path / "work"
    _site(work / "site-base")  # the source is the directory the run used to wipe
    out = metamorphic.run(work / "site-base", work, 2, (), "UTC", ("shift",), lambda *_a, **_k: ({}, {}))
    assert (work / "site-base" / "patient.csv").exists() and out["patients"] == 2
