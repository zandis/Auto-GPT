"""Detect new, duplicated and retired bypasses independently of the reviewed list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.record_identity_check import expected_inventory, scan

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

ROOT = Path(__file__).resolve().parents[2]


def test_all_local_record_and_patient_key_construction_is_listed() -> None:
    assert scan(ROOT, detailed=True) == expected_inventory(ROOT / "tools/record_identity_ratchet.json", detailed=True)


@pytest.mark.parametrize("directory", ["libs", "services"])
def test_new_bypass_in_an_unknown_module_and_changes_in_an_existing_function(tmp_path: Path, directory: str) -> None:
    package = tmp_path / directory / "new_importer"
    package.mkdir(parents=True)
    module = package / "rows.py"
    header = "from adapter.pipeline import bulk_id as mint\nfrom tb_common.identity import resolve_record\n"
    function = "def ingest(key, row):\n    return mint(key, 'Encounter', row['id'])\n"
    module.write_text(header + function)
    location = (module.relative_to(tmp_path).as_posix(), "ingest")
    assert scan(tmp_path) == {location: {"call bulk_id": 1}}
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            [
                {
                    "area": "bulk",
                    "file": location[0],
                    "function": location[1],
                    "why": "legacy",
                    "operation": "call bulk_id",
                    "expression": "mint(key, 'Encounter', row['id'])",
                }
            ]
        )
    )
    expected = expected_inventory(baseline)
    module.write_text(header + function.replace("    return", "    mint(key, 'Condition', row['id'])\n    return"))
    assert scan(tmp_path)[location]["call bulk_id"] == 2
    assert scan(tmp_path) != expected
    module.write_text(header + "def ingest(*args, **kwargs):\n    return resolve_record(*args, **kwargs)\n")
    assert not scan(tmp_path)
    assert scan(tmp_path) != expected


def test_unregistered_local_algorithms_and_first_bindings_are_discovered(tmp_path: Path) -> None:
    src = tmp_path / "services" / "elsewhere"
    src.mkdir(parents=True)
    (src / "keys.py").write_text("""
def direct(patient_id, record_id):
    return f"{patient_id}/{record_id}"

def hashed(row, h):
    return {"resourceType": "Observation", "id": h(row["raw_id"]).hexdigest()}

class Feed:
    def first(self, db):
        db.execute("insert into new_binding(pid, site, record, study) values (?, ?, ?, ?)")
""")
    assert {fn for _, fn in scan(tmp_path)} == {"direct", "hashed", "Feed.first"}


def test_nonidentity_hashes_and_the_gate_itself_are_outside_the_inventory(tmp_path: Path) -> None:
    src = tmp_path / "libs" / "tb_common"
    src.mkdir(parents=True)
    (src / "identity.py").write_text("def owner(k, v):\n    return pid_for_mrn(k, v)\n")
    (src / "other.py").write_text("def snapshot(body):\n    return hashlib.sha256(body).hexdigest()\n")
    assert scan(tmp_path) == {}


def test_indirect_key_construction_and_standalone_sql_are_checked(tmp_path: Path) -> None:
    src = tmp_path / "libs" / "another_feed"
    src.mkdir(parents=True)
    module = src / "export.py"
    module.write_text("""
def build(row):
    token = uuid.uuid4().hex
    return {"resourceType": "Observation", "id": token}

def alias(row, key):
    make = legacy.resource_id
    return make(key, "Observation", row["number"])
""")
    (src / "load.sql").write_text("-- first binding\nINSERT INTO link (record_id, pid) VALUES (?, ?);")
    assert {fn for _, fn in scan(tmp_path)} == {"build", "alias", "<sql>"}
