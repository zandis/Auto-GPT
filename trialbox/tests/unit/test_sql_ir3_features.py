"""Compiler execution with synthetic rows and a fixed index date."""

import json
import unittest
from datetime import date
from pathlib import Path
from typing import cast

import duckdb
import pytest
import yaml
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import CompileError
from criteria_compiler.terminology.mapper import SYSTEMS, ValueSets
from tb_contracts import CriterionIR
from tb_contracts.criterion_ir import CriterionIRv3, upgrade_v1

ROOT = Path(__file__).resolve().parents[2]
INDEX = date(2026, 10, 5)


def criterion(**fields: object) -> CriterionIRv3:
    return CriterionIRv3.model_validate(
        {
            "id": "SYN-INC-01",
            "ruleset": "SYN",
            "kind": "inclusion",
            "class": "structured",
            "text": {"source": "Synthetic threshold"},
            "logic": "a",
            "atoms": [{"id": "a", "domain": "observation", "valueset": "VS_X", **fields}],
        }
    )


def render(cr: CriterionIRv3) -> str:
    vs = {
        "VS_X": {
            "compose": {
                "include": [
                    {"system": SYSTEMS["atc"], "concept": [{"code": "X"}]},
                    {"system": "urn:synthetic", "concept": [{"code": "X"}]},
                ]
            }
        }
    }
    return SqlGenerator("SYN", "1.0.0", ValueSets("SYN", vs)).render([cr])


@pytest.mark.nodb
class SqlIR3Features(unittest.TestCase):
    def setUp(self) -> None:
        self.db = duckdb.connect()
        self.addCleanup(self.db.close)
        self.db.execute("""
            CREATE TABLE patient AS SELECT 'p' pid, DATE '1980-01-01' birth_date,
                'female' sex, NULL::DATE deceased_date, false deceased;
            CREATE TABLE observation AS SELECT 'o' oid, 'p' pid, 'X' code,
                'urn:synthetic' AS system, TIMESTAMP '2026-10-01' effective,
                150.0 value_num, 'U/L' unit, NULL::VARCHAR value_code, NULL::VARCHAR value_cmp;
            CREATE TABLE measurement AS SELECT 1 measurement_id, 1 person_id,
                'X' measurement_source_value, 150.0 value_as_number, 40.0 range_high, 60.0 range_low;
            CREATE TABLE tb_id_map AS SELECT 'person' id_kind, 1 omop_id, 'p' source_id;
            CREATE TABLE tb_record AS SELECT 'measurement' cdm_table, 1 record_id,
                'o' source_record_id, 0 part, 'coded' status;
            CREATE TABLE medication AS SELECT 'm' mid, 'p' pid, 'X' atc,
                NULL::VARCHAR nhi_code, DATE '2026-10-01' authored;
            CREATE TABLE drug_exposure AS SELECT 2 drug_exposure_id, 1 person_id,
                20.0 quantity, 2 days_supply, 7 route_concept_id, 'mg' dose_unit_source_value,
                DATE '2026-10-01' drug_exposure_start_date, NULL::DATE drug_exposure_end_date;
            INSERT INTO tb_record VALUES ('drug_exposure', 2, 'm', 0, 'coded');
            CREATE TABLE criterion_anchors (ruleset VARCHAR, pid VARCHAR, index_date DATE,
                screening_date DATE, randomization_date DATE);
        """)

    def result(self, cr: CriterionIRv3) -> bool | None:
        row = self.db.execute(render(cr), [[INDEX], None]).fetchone()
        assert row is not None
        return cast(bool | None, row[2])

    def test_reference_range_true_false_unknown(self) -> None:
        for bound in ("uln", "lln"):
            cr = criterion(value={"op": ">", "ref": {"kind": bound, "multiple": 3}}, quantifier="latest")
            col = "range_high" if bound == "uln" else "range_low"
            for limit, expected in ((40, True), (60, False), (None, None)):
                with self.subTest(bound=bound, limit=limit):
                    self.db.execute(f"UPDATE measurement SET {col} = ?", [limit])
                    self.assertIs(self.result(cr), expected)
            self.db.execute(f"UPDATE measurement SET {col} = 40, value_as_number = NULL")
            self.assertIsNone(self.result(cr))
            self.db.execute("UPDATE measurement SET value_as_number = 150")

    def test_reference_sql_uses_row_bound(self) -> None:
        sql = render(criterion(value={"op": ">", "ref": {"kind": "uln", "multiple": 3}}))
        self.assertIn("m.range_high", sql)
        self.assertIn("m.value_as_number", sql)
        self.assertIn("o.ref_bound * 3", sql)
        self.assertNotIn("120", sql)

    def test_anchor_true_false_unknown(self) -> None:
        for anchor in ("screening", "randomization"):
            cr = criterion(window={"anchor": anchor, "from_days": -5, "to_days": 0})
            for day, expected in (("2026-10-05", True), ("2026-09-01", False), (None, None)):
                with self.subTest(anchor=anchor, day=day):
                    self.db.execute("DELETE FROM criterion_anchors")
                    self.db.execute(
                        f"INSERT INTO criterion_anchors (ruleset, pid, index_date, {anchor}_date) VALUES (?, ?, ?, ?)",
                        ["SYN", "p", INDEX, day],
                    )
                    self.assertIs(self.result(cr), expected)
            self.db.execute("DELETE FROM criterion_anchors")
            self.assertIsNone(self.result(cr))

    def test_medication_route_is_refused_without_a_route_mapping(self) -> None:
        # review R2: the IR route is SNOMED, route_concept_id is OMOP, and no table maps one to the other
        with self.assertRaisesRegex(CompileError, "no_route_mapping"):
            render(criterion(domain="medication", medication={"route": ["47625008"]}))

    def test_medication_dose_true_false_unknown(self) -> None:
        for basis, threshold in (("cumulative", 15), ("daily", 8)):
            cr = criterion(
                domain="medication", medication={"dose": {"op": ">", "num": threshold, "unit": "mg", "basis": basis}}
            )
            for dose, unit, expected in (
                (20, "mg", True),
                (5, "mg", False),
                (None, "mg", None),
                (20, None, None),
                (20, "g", None),
            ):
                with self.subTest(basis=basis, dose=dose, unit=unit):
                    self.db.execute("UPDATE drug_exposure SET quantity = ?, dose_unit_source_value = ?", [dose, unit])
                    self.assertIs(self.result(cr), expected)

    def test_single_dose_is_not_exposure_quantity(self) -> None:
        with self.assertRaisesRegex(CompileError, "single"):
            render(
                criterion(
                    domain="medication", medication={"dose": {"op": ">", "num": 10, "unit": "mg", "basis": "single"}}
                )
            )

    def test_medication_window_includes_days_supply(self) -> None:
        cr = criterion(
            domain="medication",
            window={"from_days": -1, "to_days": 0},
            medication={"dose": {"op": ">", "num": 15, "unit": "mg", "basis": "cumulative"}},
        )
        self.db.execute("UPDATE drug_exposure SET days_supply = 5")
        self.assertIs(self.result(cr), True)
        self.db.execute("UPDATE drug_exposure SET days_supply = 2")
        self.assertIs(self.result(cr), False)

    def test_daily_dose_without_positive_supply_is_unknown(self) -> None:
        cr = criterion(domain="medication", medication={"dose": {"op": ">", "num": 8, "unit": "mg", "basis": "daily"}})
        for days in (None, 0, -1):
            self.db.execute("UPDATE drug_exposure SET days_supply = ?", [days])
            self.assertIsNone(self.result(cr))

    def test_missing_exposure_end_cannot_disprove_window_overlap(self) -> None:
        cr = criterion(
            domain="medication",
            window={"from_days": -1, "to_days": 0},
            medication={"dose": {"op": ">", "num": 15, "unit": "mg", "basis": "cumulative"}},
        )
        self.db.execute("UPDATE drug_exposure SET days_supply = NULL")
        self.assertIsNone(self.result(cr))

    def test_a_route_beside_a_dose_is_refused(self) -> None:
        cr = criterion(
            domain="medication",
            medication={"route": ["47625008"], "dose": {"op": ">", "num": 100, "unit": "mg", "basis": "cumulative"}},
        )
        with self.assertRaisesRegex(CompileError, "no_route_mapping"):
            render(cr)

    def test_reference_censored_and_boolean_unknown(self) -> None:
        cr = criterion(value={"op": ">", "ref": {"kind": "uln", "multiple": 3}})
        self.db.execute("UPDATE observation SET value_cmp = '<'")
        self.assertIsNone(self.result(cr))
        self.db.execute("UPDATE measurement SET value_as_number = 100")
        self.assertIs(self.result(cr), False)
        data = cr.model_dump()
        data["logic"] = {"op": "not", "args": ["a"]}
        cr = CriterionIRv3.model_validate(data)
        self.db.execute("UPDATE measurement SET range_high = NULL")
        self.assertIsNone(self.result(cr))

    def test_duplicate_anchor_is_rejected(self) -> None:
        cr = criterion(window={"anchor": "screening"})
        self.db.execute(
            "INSERT INTO criterion_anchors VALUES ('SYN', 'p', ?, ?, NULL), ('SYN', 'p', ?, ?, NULL)",
            [INDEX, INDEX, INDEX, INDEX],
        )
        with self.assertRaises(duckdb.InvalidInputException):
            self.result(cr)

    def test_nonfinite_threshold_is_rejected(self) -> None:
        for number in (float("inf"), float("nan")):
            with self.subTest(number=number), self.assertRaises(CompileError):
                render(criterion(value={"op": ">", "ref": {"kind": "uln", "multiple": number}}))

    def test_all_reference_quantifiers_preserve_unknown(self) -> None:
        for quantifier in ("any", "none", "all", "latest", "count>="):
            cr = criterion(quantifier=quantifier, count=1, value={"op": ">", "ref": {"kind": "uln", "multiple": 3}})
            self.db.execute("UPDATE measurement SET range_high = NULL")
            self.assertIsNone(self.result(cr))

    def test_record_mapping_is_patient_specific_and_respects_status(self) -> None:
        cr = criterion(value={"op": ">", "ref": {"kind": "uln", "multiple": 3}})
        self.db.execute("INSERT INTO tb_id_map VALUES ('person', 9, 'other')")
        self.db.execute("INSERT INTO measurement VALUES (9, 9, 'X', 900, 10, 1)")
        self.db.execute("INSERT INTO tb_record VALUES ('measurement', 9, 'o', 0, 'coded')")
        self.assertIs(self.result(cr), True)
        self.db.execute("UPDATE tb_record SET status = 'rejected' WHERE record_id = 1")
        self.assertIsNone(self.result(cr))

    def test_unsupported_fields_are_not_silently_dropped(self) -> None:
        with self.assertRaises(CompileError):
            render(criterion(attribute={"path": "score", "op": ">", "num": 1, "source_priority": ["note"]}))

    def test_all_live_v1_rulesets_stay_byte_identical(self) -> None:
        dirs = sorted((ROOT / "rulesets").glob("*/manifest.yaml"))
        self.assertEqual(len(dirs), 8)
        for path in dirs:
            with self.subTest(ruleset=path.parent.name):
                manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
                criteria = [
                    CriterionIR.model_validate_json((path.parent / "ir" / f"{cid}.json").read_text(encoding="utf-8"))
                    for cid in manifest["criteria"]
                ]
                vs = {
                    p.stem: json.loads(p.read_text(encoding="utf-8"))
                    for p in (path.parent / "valuesets").glob("*.json")
                }
                gen = SqlGenerator(manifest["id"], manifest["version"], ValueSets(manifest["id"], vs))
                before = gen.render(criteria)
                self.assertEqual(before, gen.render([upgrade_v1(c) for c in criteria]))
                self.assertEqual(before, (path.parent / "sql" / f"{manifest['id']}.sql").read_text(encoding="utf-8"))
