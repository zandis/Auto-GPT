"""H-35 (D-1101): the list of stated limits is built from the tree and every row has a source; the judging helpers;
the drivers that run on functions and stand-ins (no database). The box's drivers are ``tests/e2e/test_limits_edge_box.py``
(``make limits-edge``)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from tools import limits_edge as le
from tools.limits_lint import load_allow

pytestmark = [pytest.mark.nodb]
ROOT = Path(__file__).resolve().parents[2]


def test_the_list_is_built_with_no_problem() -> None:
    doc = le.build()
    assert doc["problems"] == []
    assert doc["schema"] == le.SCHEMA


def test_every_stated_row_has_a_source_line_that_holds_its_phrase() -> None:
    for row in le.build()["stated"]:
        path = ROOT / row["source"]
        assert path.is_file(), row["id"]
        assert row["line"] >= 1, row["id"]
        line = path.read_text(encoding="utf-8").splitlines()[row["line"] - 1]
        assert row["anchor"] in line, (row["id"], line)


def test_every_stated_row_is_driven_or_says_why_not() -> None:
    ids = [r.id for r in le.STATED]
    assert len(ids) == len(set(ids))
    for r in le.STATED:
        assert bool(r.driver) != bool(r.not_driven), r.id
        if r.driver:
            assert r.driver in le.DRIVERS, r.id
        assert r.lane in {"A2", "B2", "C2", "D", "E", "H", "Int"}, r.id
        assert r.value and r.unit and r.who and r.enforced, r.id


def test_the_register_rows_are_every_row_of_the_limits_register() -> None:
    rows = le.register_rows()
    assert len(rows) == len(load_allow())
    assert all(r["source"].startswith("tools/limits_allow.yaml:") for r in rows)


def test_unstated_constants_leave_out_what_the_catalogue_claims() -> None:
    claimed = {c for r in le.STATED for c in r.constants}
    found = le.unstated(claimed)
    assert found, "the code has bounds no document states"
    assert not claimed & {f"{u['where'].rsplit(':', 1)[0]}:{u['name']}" for u in found}
    assert all(":" in u["where"] and isinstance(u["value"], int | float) for u in found)


@pytest.mark.parametrize(
    ("text", "lang", "plain"),
    [
        ("Keep the reason to 500 characters.", "en", True),
        ("理由は 500 文字以内にしてください。", "ja", True),
        ("Traceback (most recent call last)", "en", False),
        ("flags.err.long", "en", False),
        ("拒否されました：the end date is at most", "ja", False),
        ("", "en", False),
    ],
)
def test_plainness(text: str, lang: str, plain: bool) -> None:
    assert (le.plainness(text, lang) == "") is plain


def test_names_value_reads_a_thousands_comma() -> None:
    assert le.names_value("at most 2,000 characters", ("2000",))
    assert not le.names_value("too long", ("2000",))


def test_page_text_is_the_main_part() -> None:
    body = "<nav>menu</nav><main><h1>Refused</h1><p>at most &lt;50&gt; MB</p><script>x()</script></main>"
    assert le.page_text(body) == "Refused at most <50> MB"


def test_verdict() -> None:
    ok = [{"case": "at", "accepted": True}, {"case": "one_over", "accepted": False, "before_work": True},
          {"case": "far_over", "accepted": False, "before_work": True}]  # fmt: skip
    assert le.verdict("X", ok) == "holds"
    late = [*ok[:2], {"case": "far_over", "accepted": False, "before_work": False}]
    assert le.verdict("X", late) == "far_over refused after work"
    assert le.verdict("X", [{"case": "at", "accepted": False}, *ok[1:]]) == "at refused"
    assert le.verdict("X", [*ok[:2], {"case": "far_over", "accepted": True}]) == "far_over accepted"


@pytest.mark.parametrize("row_id", ["L02", "L03", "L06", "L09", "L12", "L14", "L15", "L16", "L17", "L18"])
def test_the_function_drivers_run_and_the_limit_holds(row_id: str, tmp_path: Path) -> None:
    """The drivers on functions and stand-ins need no database; each holds today (the words are judged on the page)."""
    row = next(r for r in le.STATED if r.id == row_id)
    _where, fn = le.DRIVERS[row.driver]
    cases = [asdict(c) for c in fn(le.Ctx(tmp_path))]
    assert cases
    assert le.verdict(row_id, cases) == "holds", cases


def test_the_odm_driver_pads_to_the_exact_size() -> None:
    base = le._odm_file()
    for n in (len(base) + 7, 5_000_000):
        assert len(le._pad_xml(base, n)) == n
    assert len(le._sheet(2_000_000)) == 2_000_000


def test_markdown_writes_one_row_per_stated_limit() -> None:
    doc = le.build()
    doc["results"] = {}
    text = le.markdown(doc)
    assert text.count("\n| L") == len(le.STATED)
