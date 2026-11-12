"""T-693 (D-457; scale review F-06, the rest): the ingest gate's validation sample has an absolute cap per resource
type beside its 1 %, derived from the gate's own limit, settable, and recorded in the night's report.

The row's acceptance test: a load of 25 M resources samples at most the cap per type; the report names the cap.
Proven on the arithmetic for 25 M and on real samples of tens of thousands of synthetic resources (the nightly scale
gate runs the hospital)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from adapter.pipeline import run_ingest
from adapter.validate.validator import sample, sample_cap, sample_size

from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _Lakes, _row


def _resources(n_by_type: dict[str, int]) -> list[dict[str, Any]]:
    return [{"resourceType": t, "id": f"{t}-{i}"} for t, n in n_by_type.items() for i in range(n)]


@pytest.mark.nodb
def test_a_load_of_25_million_resources_samples_at_most_the_cap_per_type() -> None:
    """The row's acceptance, on the sizes: 50,000 patients x 500 resources. Before: 1 % = 250,000 files."""
    cap = sample_cap(0.5, {})
    assert cap == 4975  # derived from the gate's limit of 0.5 %: the standard error is then a fifth of the limit
    load = {"Observation": 18_000_000, "MedicationRequest": 4_000_000, "Condition": 2_500_000, "Encounter": 450_000,
            "Patient": 50_000}  # fmt: skip
    assert sum(load.values()) == 25_000_000
    sizes = {t: sample_size(n, 0.01, 3, cap) for t, n in load.items()}
    assert sizes == {"Observation": cap, "MedicationRequest": cap, "Condition": cap, "Encounter": 4500, "Patient": 500}
    assert sum(sizes.values()) == 19_925 and all(k <= cap for k in sizes.values())
    assert sum(sample_size(n, 0.01, 3, None) for n in load.values()) == 250_000  # without a cap, as it was
    # small types are as before: the share, at least 3, never more than there are
    assert [sample_size(n, 0.01, 3, cap) for n in (0, 2, 3, 100, 299, 301)] == [0, 2, 3, 3, 3, 3]
    assert sample_size(1000, 0.01, 3, 1) == 3  # a cap under the minimum does not go under it


@pytest.mark.nodb
def test_the_cap_is_derived_from_the_limit_and_settable() -> None:
    assert sample_cap(0.5, {}) == 4975 and sample_cap(1.0, {}) == 2475 and sample_cap(0.1, {}) == 24975
    assert sample_cap(0.5, {"TB_VALIDATION_SAMPLE_CAP": "800"}) == 800
    assert sample_cap(0.5, {"TB_VALIDATION_SAMPLE_CAP": "0"}) is None  # 0: no cap, the plain share
    assert sample_cap(0.0, {}) is None and sample_cap(100.0, {}) is None  # no limit to derive one from
    for bad in ("many", "-5"):
        with pytest.raises(ValueError, match="TB_VALIDATION_SAMPLE_CAP"):
            sample_cap(0.5, {"TB_VALIDATION_SAMPLE_CAP": bad})


@pytest.mark.nodb
def test_a_real_sample_is_cut_at_the_cap_and_an_uncapped_type_is_sampled_as_before() -> None:
    res = _resources({"Observation": 60_000, "Condition": 4_000, "Patient": 200})
    before = sample(res, 0.01)
    capped = sample(res, 0.01, cap_per_type=150)

    def by_type(rs: list[dict[str, Any]]) -> dict[str, list[str]]:
        return {t: [r["id"] for r in rs if r["resourceType"] == t] for t in ("Observation", "Condition", "Patient")}

    was, now = by_type(before), by_type(capped)
    assert {t: len(v) for t, v in was.items()} == {"Observation": 600, "Condition": 40, "Patient": 3}
    assert {t: len(v) for t, v in now.items()} == {"Observation": 150, "Condition": 40, "Patient": 3}
    assert now["Condition"] == was["Condition"] and now["Patient"] == was["Patient"]  # under the cap: unchanged
    assert now["Observation"] == was["Observation"][:150]  # the same order: the cap takes its first part
    assert sample(res, 0.01, cap_per_type=None) == before


def test_the_back_fill_s_sample_follows_the_same_rule(tmp_path: Path) -> None:
    from adapter.backfill import _sample

    folder = tmp_path / "stage"
    folder.mkdir()
    counts = {"Observation": 30_000, "Patient": 100}
    for t, n in counts.items():
        (folder / f"{t}.ndjson").write_text(
            "".join(json.dumps({"resourceType": t, "id": f"{t}-{i}"}) + "\n" for i in range(n)), encoding="utf-8"
        )
    plain = _sample(folder, counts, 0.01)
    capped = _sample(folder, counts, 0.01, cap=120)
    assert len([r for r in plain if r["resourceType"] == "Observation"]) == 300
    obs = [r["id"] for r in capped if r["resourceType"] == "Observation"]
    assert len(obs) == 120 and obs == [r["id"] for r in plain if r["resourceType"] == "Observation"][:120]
    assert [r for r in capped if r["resourceType"] == "Patient"] == [r for r in plain if r["resourceType"] == "Patient"]
    # the in-memory sampler and the folder sampler pick the same resources
    mem = sample(_resources(counts), 0.01, cap_per_type=120)
    assert sorted(r["id"] for r in mem) == sorted(r["id"] for r in capped)


class _Counting:
    """A validator that passes everything and remembers what it was given."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def validate(self, picked: list[dict[str, Any]]) -> Any:
        from adapter.validate.validator import ValidationResult

        self.seen = list(picked)
        return ValidationResult(validator="stub", sampled=len(picked), errors=0)


def test_the_nights_report_names_the_cap_and_what_it_cut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The row's second half. A night of 400 diagnoses with the cap set to 2: the report says the cap, and that
    Condition was cut (with its number of resources); the validator saw at most the cap per type."""
    monkeypatch.setenv("TB_VALIDATION_SAMPLE_CAP", "2")
    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    cfg.sample_fraction = 0.5
    _csv(tmp_path / "n1", [_row(f"D{i}", "2026-09-01") for i in range(400)])
    v = _Counting()
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validator=v)  # type: ignore[arg-type]
    assert rep.passed
    per_type: dict[str, int] = {}
    for r in v.seen:
        per_type[r["resourceType"]] = per_type.get(r["resourceType"], 0) + 1
    assert per_type["Condition"] == 3  # the minimum of 3 stands over a cap of 2
    assert rep.validation.sample_cap == 2 and rep.validation.capped == {"Condition": 400}
    stored = json.loads((cfg.lake_dir / "ndjson" / "2026-10-01" / "ingest_report.json").read_text())
    assert stored["validation"]["sample_cap"] == 2 and stored["validation"]["capped"] == {"Condition": 400}
    # with the derived cap a small night is not cut and says so: the cap is named, nothing is listed as capped
    monkeypatch.delenv("TB_VALIDATION_SAMPLE_CAP")
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-02", load_fhir=False, validator=v)  # type: ignore[arg-type]
    assert rep.validation.sample_cap == 4975 and not rep.validation.capped
    monkeypatch.setenv("TB_VALIDATION_SAMPLE_CAP", "0")
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-03", load_fhir=False, validator=v)  # type: ignore[arg-type]
    assert rep.validation.sample_cap is None and not rep.validation.capped
