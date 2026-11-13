"""E2E-DETAIL (D-628): a check's detail is recorded whole; only the printed report is cut. On the GPU run a failed
check's JSON had lost the part of its detail that said why."""

from __future__ import annotations

import pytest

from tools import e2e_simple, public_e2e

pytestmark = pytest.mark.nodb

LONG = "why it failed: " + "x" * 900 + " THE END"


@pytest.mark.parametrize("mod", [e2e_simple, public_e2e])
def test_the_record_keeps_the_whole_detail(mod: object) -> None:
    st = mod.Stage("a stage")  # type: ignore[attr-defined]
    st.check("a check", False, LONG)
    assert st.checks[-1] == ("a check", False, LONG)


@pytest.mark.parametrize("mod", [e2e_simple, public_e2e])
def test_the_printed_line_is_cut_and_says_so(mod: object) -> None:
    line = mod.shown(LONG)  # type: ignore[attr-defined]
    assert line.startswith(LONG[:300]) and "THE END" not in line
    assert str(len(LONG)) in line and "JSON" in line
    assert mod.shown("short") == "short"  # type: ignore[attr-defined]


def test_the_report_prints_the_cut_line_for_a_failed_check() -> None:
    st = e2e_simple.Stage("a stage")
    st.check("a check", False, LONG)
    text = e2e_simple.report({"stages": [st], "ok": False, "seconds": 1, "chain_seconds": 1})
    assert "THE END" not in text and "JSON" in text
