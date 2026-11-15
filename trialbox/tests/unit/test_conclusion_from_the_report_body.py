"""CGRD-A4 (D-816): a report's conclusion falls back to its body, and is masked like any note text.

Some sources fill the column mapped to ``conclusion`` on a few reports only and keep the words in the report body.
``{column: conclusion, else: report_text}``: the first non-empty of the two. The conclusion reaches the lake's
``report`` table and the screening facts as it is (it is not a labelled note column), so it now passes through
``phi_guard.mask_note`` with the site's chart-number pattern (``masked: true``), as note text does before it is
chunked. Synthetic text only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping, MappingError

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"


def _report(conclusion: str, body: str) -> dict[str, str]:
    return {"rpt_no": "R1", "mrn": "P1", "exam_code": "RAD-CXR", "exam_name": "x", "exam_date": "2026-01-13",
            "conclusion": conclusion, "report_text": body}  # fmt: skip


def _conclusion(row: dict[str, str], mrn_regex: str | None = r"\d{8}") -> Any:
    m = Mapping.load(BASE)
    (res,) = Mapper(m, b"k" * 32, "s", mrn_regex=mrn_regex).map_table("report", iter([row]))
    return res.get("conclusion")


def test_the_conclusion_column_is_used_when_it_is_filled() -> None:
    assert _conclusion(_report("No active lung lesion.", "Full body text.")) == "No active lung lesion."


def test_an_empty_conclusion_falls_back_to_the_body() -> None:
    assert _conclusion(_report("", "Heart size normal. No active lung lesion.")) == (
        "Heart size normal. No active lung lesion."
    )
    assert _conclusion(_report("  ", "Body.")) == "Body."
    assert _conclusion(_report("", "")) is None


def test_the_conclusion_is_masked_like_note_text() -> None:
    got = str(_conclusion(_report("", "Compared with study 12345678 of last year. MRN: 10000001. Stable.")))
    assert "12345678" not in got and "10000001" not in got and got.endswith("Stable.")
    assert len(got) == len("Compared with study 12345678 of last year. MRN: 10000001. Stable.")  # the length is kept


@pytest.mark.parametrize("element", [{"column": "conclusion", "else": ""}, {"column": "conclusion", "masked": "yes"}])
def test_else_and_masked_stated_badly_are_refused_at_load(tmp_path: Path, element: dict[str, Any]) -> None:
    import yaml

    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for spec in (doc.get("lookups") or {}).values():
        spec["file"] = str(BASE.parent / spec["file"])
    rep = next(r for r in doc["resources"] if r["table"] == "report")
    rep["elements"]["conclusion"] = element
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(MappingError):
        Mapping.load(path)
