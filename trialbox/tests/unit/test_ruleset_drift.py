"""T-613a (STD-040, D-322): the shipped rulesets are what today's compiler gives, and a sibling code is in.

* every shipped ruleset's ValueSets, SQL and CQL equal the compiler's output for the current terminology release
  (``tools.build_rulesets --check``, the same check the CI ``contracts`` job runs);
* a patient coded ``M06.09`` (rheumatoid arthritis without rheumatoid factor, a code that was not one of the five
  listed before the recompile) meets RA-BIO's rheumatoid-arthritis criterion (INC-02) and its age criterion (INC-01);
* a drifted ValueSet makes the check fail and names it.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest
from lake.flatten import SCHEMAS
from tb_common.ruleset import Ruleset

from tools import build_rulesets

ROOT = Path(__file__).resolve().parents[2]
RULESETS = ROOT / "rulesets"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
INDEX = date(2026, 10, 5)


def test_every_shipped_ruleset_is_the_compilers_output(capsys: pytest.CaptureFixture[str]) -> None:
    ids = build_rulesets.shipped(RULESETS)
    assert {"GZQO", "GOUT-COH", "RA-BIO", "RA-COH", "ONC-OSI", "AD-MAB", "NEUR-COH"} <= set(ids)
    rc = build_rulesets.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert all(f"{rid}: equal to the compiler's output" in out for rid in ids), out


def test_ra_valueset_has_the_families() -> None:
    vs = json.loads((RULESETS / "RA-BIO" / "valuesets" / "VS_RHEUMATOID_ARTHRITIS.json").read_text(encoding="utf-8"))
    codes = {x["code"] for inc in vs["compose"]["include"] for x in inc["concept"]}
    assert {"M06.09", "M05.711", "M06.9"} <= codes and len(codes) > 400
    assert {e["valueString"] for e in vs["extension"]} == {f"{ICD}|M05", f"{ICD}|M06"}


def _run(sql: str, conditions: dict[str, str]) -> dict[str, dict[str, bool | None]]:
    con = duckdb.connect()
    for name, spec in SCHEMAS.items():
        columns = ", ".join(f'"{c}" {t}' for c, t in spec)
        con.execute(f'CREATE TABLE "{name}" ({columns})')
    for i, (pid, code) in enumerate(conditions.items()):
        con.execute("INSERT INTO patient (pid, birth_date, sex) VALUES (?, DATE '1970-03-01', 'female')", [pid])
        con.execute(
            "INSERT INTO condition (cid, pid, code, system, onset, recorded, status) "
            "VALUES (?, ?, ?, ?, DATE '2025-01-10', DATE '2025-01-10', 'active')",
            [f"c{i}", pid, code, ICD],
        )
    rows = con.execute(sql, [[INDEX.isoformat()], None]).fetchall()
    cols = [d[0] for d in con.description]
    out = {}
    for r in rows:
        rec = dict(zip(cols, r, strict=True))
        out[rec["pid"]] = {k[2:]: v for k, v in rec.items() if k.startswith("C_")}
    return out


def test_a_patient_coded_m06_09_is_included_by_ra_bio() -> None:
    rs = Ruleset.load(RULESETS / "RA-BIO")
    got = _run(rs.sql, {"sibling": "M06.09", "listed": "M06.9", "other": "M10.00"})
    assert got["sibling"]["RA-BIO-INC-01"] is True  # 56 years old at the index date
    assert got["sibling"]["RA-BIO-INC-02"] is True  # RA for more than six months, coded with a sibling code
    assert got["listed"]["RA-BIO-INC-02"] is True
    assert got["other"]["RA-BIO-INC-02"] is False  # gout is not rheumatoid arthritis


def test_a_drifted_valueset_fails_the_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copytree(RULESETS / "RA-COH", tmp_path / "RA-COH")
    p = tmp_path / "RA-COH" / "valuesets" / "VS_RHEUMATOID_ARTHRITIS.json"
    vs = json.loads(p.read_text(encoding="utf-8"))
    vs["compose"]["include"][0]["concept"] = vs["compose"]["include"][0]["concept"][:5]
    vs.pop("extension")
    p.write_text(json.dumps(vs), encoding="utf-8")
    assert build_rulesets.main(["--check", "RA-COH", "--out", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "RA-COH: " in out and "valuesets/VS_RHEUMATOID_ARTHRITIS.json" in out
    assert "VS_RHEUMATOID_ARTHRITIS: 5 -> 418 codes (+413 -0); families none -> M05, M06" in out
