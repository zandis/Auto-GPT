"""F9 (D-811): a birth date earlier than any human life allows is not the patient's.

The feed's dates are bounded at 1850 (DIN-001): a smaller year is another calendar's. A birth date between 1850
and about 1904 passed, though nobody alive can be that old: the longest verified human life is 122 years. Such a
birth date is a placeholder or an error, and an age read from it would be wrong. ``birthDate`` now carries
``lived_at_most: {years: 122, until: death_date}``: a birth date more than 122 years before the death date, or before
today when there is none, is left out (the patient is kept: refusing the row would orphan every record of theirs)
and counted per table and element in the night's completeness. Synthetic values only."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"


def _patient(m: Mapper, born: str, died: str = "") -> dict[str, object]:
    row = {"mrn": "P1", "name": "x", "id_no": "y", "birth_date": born, "sex": "F", "death_date": died}
    (pat,) = [r for r in m.map_table("patient", iter([row])) if r["resourceType"] == "Patient"]
    return dict(pat)


def _oldest_today() -> date:
    t = date.today()
    return t.replace(year=t.year - 122) if not (t.month == 2 and t.day == 29) else date(t.year - 122, 2, 28)


@pytest.mark.parametrize("born", ["1870-05-01", "1899-12-31", (_oldest_today().replace(day=1) if _oldest_today().day > 1
                                  else _oldest_today()).isoformat()])  # fmt: skip
def test_a_living_patient_born_longer_ago_than_any_life_has_no_birth_date(born: str) -> None:
    m = Mapper(Mapping.load(BASE), b"k" * 32, "s")
    pat = _patient(m, born)
    assert "birthDate" not in pat and pat["gender"] == "female"  # the patient is kept
    assert m.implausible_dates() == {"patient": {"birthDate": 1}}


@pytest.mark.parametrize(("born", "died"), [("1890-03-01", "1985-06-01"), ("1930-01-01", ""), ("1904-12-31", "")])
def test_a_birth_date_a_life_allows_is_kept(born: str, died: str) -> None:
    m = Mapper(Mapping.load(BASE), b"k" * 32, "s")
    assert _patient(m, born, died)["birthDate"] == born
    assert m.implausible_dates() == {}


def test_a_death_more_than_122_years_after_the_birth_leaves_the_birth_date_out() -> None:
    m = Mapper(Mapping.load(BASE), b"k" * 32, "s")
    assert "birthDate" not in _patient(m, "1860-01-01", "1990-01-01")


def test_the_night_counts_them(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    with (feed / "patient.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "name", "id_no", "birth_date", "sex", "death_date"])
        w.writeheader()
        w.writerow(
            {"mrn": "10000001", "name": "a", "id_no": "b", "birth_date": "1880-01-01", "sex": "M", "death_date": ""}
        )
        w.writerow(
            {"mrn": "10000004", "name": "c", "id_no": "d", "birth_date": "1960-01-01", "sex": "F", "death_date": ""}
        )
    run_ingest(cfg, "csv", str(feed), snapshot="2026-10-01", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-10-01")
    assert len(list(read_type(folder, "Patient"))) == 2
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["patient"]["implausible_dates"] == {"birthDate": 1}
