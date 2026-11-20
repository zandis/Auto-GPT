"""Card 9g-15 (D-1348; review 03 B3-11): licence refusal rules in the allow-list check.

`make allowlist-check` refuses each planted entry (``tests/fixtures/supply_chain/planted/``, one per kind: FSL, SSPL,
non-profit-only, cloud features on by default). The project's own allow-list still passes. Package names are made up.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.supply_chain import __main__ as cli
from tools.supply_chain import allowlist

ROOT = Path(__file__).resolve().parents[2]
PLANTED = ROOT / "tests" / "fixtures" / "supply_chain" / "planted"
ON = dt.date(2026, 11, 20)  # the planted entries' review_by (2027-01-10) is inside the window from this day
KINDS = ("FSL", "SSPL", "non-profit-only", "cloud-on-by-default")
FILES = {"FSL": "fsl.yaml", "SSPL": "sspl.yaml", "non-profit-only": "non-profit-only.yaml",
         "cloud-on-by-default": "cloud-on-by-default.yaml"}  # fmt: skip


def test_one_planted_file_per_kind() -> None:
    assert sorted(p.name for p in PLANTED.glob("*.yaml")) == sorted(FILES.values())
    assert [k for k, _, _ in allowlist.REFUSED] == list(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_allowlist_check_refuses_each_planted_entry(
    kind: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(allowlist, "today", lambda: ON)
    assert cli.main(["--allowlist", str(PLANTED / FILES[kind]), "allowlist-check"]) == 1
    out = capsys.readouterr()
    assert f"({kind}): refused, no allow-list entry accepts it" in out.err
    assert "allowlist-check: FAIL (0 valid entries)" in out.out


@pytest.mark.parametrize("kind", KINDS)
def test_the_same_entry_without_the_refused_licence_passes(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the control: the planted entry with a plain MIT licence is valid, so the refusal is the licence's
    doc = yaml.safe_load((PLANTED / FILES[kind]).read_text(encoding="utf-8"))
    doc["licences"][0]["licence"] = "MIT (planted control)"
    p = tmp_path / "control.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    monkeypatch.setattr(allowlist, "today", lambda: ON)
    assert cli.main(["--allowlist", str(p), "allowlist-check"]) == 0
    assert "allowlist-check: PASS (1 valid entries)" in capsys.readouterr().out


def _entry(**kw: Any) -> dict[str, Any]:
    e = {"package": "planted-x", "class": "unknown", "licence": "MIT",
         "reason": "Planted entry for the refusal test of card 9g-15", "review_by": "2027-01-10"}  # fmt: skip
    e.update(kw)
    return e


@pytest.mark.parametrize(
    ("entry", "kind"),
    [
        (_entry(licence="fsl-1"), "FSL"),
        (_entry(licence="Licence: SSPL"), "SSPL"),
        (_entry(licence="Non Profit only"), "non-profit-only"),
        (_entry(licence="nonprofit use only"), "non-profit-only"),
        (_entry(licence="MIT; on by default it syncs to a cloud service"), "cloud-on-by-default"),
        (_entry(**{"class": "dual", "licence": None, "chosen": "SSPL"}), "SSPL"),
        (_entry(reason="Accepted although the cloud features are on by default"), "cloud-on-by-default"),
        (_entry(**{"class": "gpl", "licence": None, "reason": "Accepted as FSL by the planted refusal test"}),
         "FSL"),
    ],
)
def test_each_field_the_entry_records_is_read(entry: dict[str, Any], kind: str) -> None:
    entry = {k: v for k, v in entry.items() if v is not None}
    allow, errors = allowlist.parse({"licences": [entry]}, today=ON)
    assert allow.licences == []
    assert any(f"({kind}): refused" in e for e in errors), errors


@pytest.mark.parametrize(
    "licence", ["MIT", "FSLX-1", "Elsewhere-SSPLish", "for-profit use", "cloud features off by default"]
)
def test_other_text_is_not_refused(licence: str) -> None:
    assert allowlist.refused_licence(licence) is None


def test_the_project_allowlist_still_passes_unchanged() -> None:
    allow, errors = allowlist.load(today=None)
    assert errors == []
    assert not [e for e in allow.licences if any(allowlist.refused_licence(t or "") for t in (e.licence, e.chosen))]
