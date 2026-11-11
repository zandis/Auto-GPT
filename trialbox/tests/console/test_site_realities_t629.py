"""T-629 (D-415): the safety-relevant site realities of TB-DR-01 §4, one test per need.

* FIT-U04: a death recorded after the run takes the patient off the Approach lists, the call tasks and the marks at
  once; while the death records cannot be read, nobody is marked Approach or called.
* FIT-U03: the same patient in another study is shown, by name only to an account that may see that study;
  consented or enrolled elsewhere puts the patient on "needs information".
* FIT-U06: the study's type for SAE reporting (one of the site's country) selects the reporting table, and a study
  that reports SAEs does not open without it.
* FIT-U09: a chart-number column that Excel turned into numbers is refused at import, naming the column: the site
  set-up's sheets (in English, Japanese and Chinese on the console) and the nightly feed.

All data is synthetic."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from console.backend import RulesetInfo, Unavailable
from console.i18n import CATALOGUES
from datacore import lifecycle as lc
from orchestrator.scenarios.screen import deceased_now
from tb_common import chartno
from tb_contracts import RegistryEntry

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_lifecycle_pages import PW as LB_PW
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_site_setup_pages import PW as SB_PW
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the fixture is used by name
from tests.unit.test_his_csv_reader import SITE_A, _cfg, _night, _transcode

A, B = "a" * 32, "b" * 32
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def _events(b: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        json.loads(x) for f in sorted((b["dir"] / "audit").glob("*.jsonl")) for x in f.read_text().splitlines() if x
    ]


# ---------------------------------------------------------------------------------------------- FIT-U04: death
class _Lake:
    """The lake's ``query`` on an in-memory DuckDB with the schema-4 patient table (T-616)."""

    def __init__(self) -> None:
        self.con = duckdb.connect()
        self.con.execute("CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, "
                         "deceased BOOLEAN)")  # fmt: skip
        self.con.execute("INSERT INTO patient VALUES ('p-dated-01', NULL, 'F', DATE '2026-11-01', TRUE), "
                         "('p-flagged-1', NULL, 'M', NULL, TRUE), ('p-alive-001', NULL, 'F', NULL, NULL), "
                         "('p-other-01', NULL, 'M', DATE '2026-01-01', TRUE)")  # fmt: skip

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        rows = self.con.execute(sql, params or []).fetchall()
        return pa.table({"pid": [r[0] for r in rows]})


def test_u04_a_death_record_removes_the_patient_from_approach_lists(box: dict[str, Any]) -> None:  # noqa: F811
    """The lake says who died now (a date, or T-616's flag without one), of the listed patients only; the console
    drops them from every list at once, refuses a mark or a call outcome, and stops contacts when it cannot ask."""
    lake = _Lake()
    assert deceased_now(lake, ["p-dated-01", "p-flagged-1", "p-alive-001"]) == ["p-dated-01", "p-flagged-1"]
    assert deceased_now(lake, []) == []

    bk = box["backend"]
    _done_screen(bk, _ulid(961))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="row-aaaaaaaa"' in page
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code in (200, 303)
    crc = _user(box, "crc1", "coordinator")
    assert 'data-testid="task-call"' in crc.get("/home").text  # the call task before the death is recorded

    asked: list[list[str]] = []

    def dead(pids: list[str]) -> set[str]:
        asked.append(list(pids))
        return {A, "z" * 32}  # a pseudonym not on the list is never reported back as on it

    bk.deceased = dead
    page = pi.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="row-aaaaaaaa"' not in page and 'data-testid="row-bbbbbbbb"' in page
    assert 'data-testid="dead-removed"' in page and asked and A in asked[-1]
    assert 'data-testid="task-call"' not in crc.get("/home").text
    assert pi.get(f"/studies/GZQO/patients/{A}").status_code == 404
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code == 409 and CATALOGUES["en"]["patient.deceased"][:20] in r.text
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome",
                 data={"csrf": _csrf(crc.get("/home").text), "outcome": "reached_booked"})  # fmt: skip
    assert r.status_code == 409
    refused = [e for e in _events(box) if e.get("event") == "console.refused"]
    assert any((e.get("detail") or {}).get("reason") == "deceased" for e in refused)

    def down(pids: list[str]) -> set[str]:
        raise Unavailable("lake down")

    bk.deceased = down
    page = pi.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="dead-unchecked"' in page  # never a quiet "nobody died"
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code == 503
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "need_info"})
    assert r.status_code in (200, 303)  # only contacts wait
    for lang in ("ja", "zh-TW"):
        for key in ("asof.dead", "asof.dead_unchecked", "patient.deceased", "patient.death_unchecked"):
            assert key in CATALOGUES[lang], (lang, key)


# ---------------------------------------------------------------------------------- FIT-U03: several studies
def test_u03_the_same_patient_in_another_study(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    bk = box["backend"]
    _done_screen(bk, _ulid(962))
    trials = [RulesetInfo("GZQO", "1.0.0", "approved", "trial"), RulesetInfo("STB", "1.0.0", "approved", "trial")]
    monkeypatch.setattr(bk, "rulesets", lambda: trials)
    for pid, status in ((A, "enrolled"), (B, "contacted")):
        bk.registry[("STB", pid)] = RegistryEntry.model_validate({"ruleset": "STB", "pid": pid, "status": status,
                                                                  "updated_at": T0, "updated_by": "console:crc",
                                                                  "source": "manual"})  # fmt: skip
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/studies/GZQO/week?list=all").text
    assert "Consented or enrolled in STB" in page and "Also a candidate in STB" in page
    # enrolled in the other study: "needs information" until a person checks this protocol's rule, never "ready"
    assert 'data-testid="row-aaaaaaaa"' in pi.get("/studies/GZQO/week?list=needs").text
    assert 'data-testid="row-aaaaaaaa"' not in pi.get("/studies/GZQO/week?list=ready").text
    assert "In another study: check this protocol" in pi.get("/studies/GZQO/week?list=all&pid=" + A).text
    # an account that may not see the other study is told "another study", never its name
    box["users"].create("drsuzuki", "investigator", "role-pages-password-01", "drsuzuki@hospa.test")
    box["users"].set_scope("drsuzuki", studies="GZQO")
    name_pi(box, "drsuzuki")  # D-380
    other, _ = login(box["app"], "drsuzuki", "role-pages-password-01")
    page = other.get("/studies/GZQO/week?list=all").text
    shown = re.sub(r'name="csrf" value="[^"]*"', "", page)  # a random CSRF token can hold the letters "STB"
    assert "Consented or enrolled in another study" in page and "STB" not in shown
    for lang in ("ja", "zh-TW"):
        for key in ("elsewhere.candidate", "elsewhere.enrolled.other", "elsewhere.open"):
            assert key in CATALOGUES[lang], (lang, key)


# ---------------------------------------------------------------------------------- FIT-U06: study type
def test_u06_the_study_type_selects_the_sae_table_and_is_required(lb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf = login(lb["app"], "crc", LB_PW)
    page = c.get("/studies/GZQO/setup").text
    assert 'value="tw_research"' in page and 'value="jp_crb"' not in page  # the site's country only (Taipei)
    r = c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "jp_crb"})
    assert r.status_code == 200 and "SAE-COUNTRY" in r.text
    assert lb["oc"].get("/studies/GZQO/sae-rule").json()["rule_set"] == ""  # nothing saved
    # a study that reports SAEs does not open without its type
    r = c.post(
        "/studies/GZQO/state", data={"csrf": csrf, "state": "paused", "reason": "site visit"}, follow_redirects=False
    )
    assert r.status_code == 303
    r = c.post("/studies/GZQO/state", data={"csrf": csrf, "state": "open"}, follow_redirects=False)
    assert r.status_code == 409 and CATALOGUES["en"]["sstate.sae_type"][:20] in r.text
    # the type chosen selects the reporting table, and the study opens
    r = c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_research"}, follow_redirects=False)
    assert r.status_code == 303
    rules = lb["oc"].get("/studies/GZQO/sae-rule").json()["rules"]
    assert rules["name"] == "tw_research"
    assert {k: tuple(v) for k, v in rules["parties"].items()} == dict(lc.RULE_SETS["tw_research"].parties)
    assert (
        c.post("/studies/GZQO/state", data={"csrf": csrf, "state": "open"}, follow_redirects=False).status_code == 303
    )
    for lang in ("ja", "zh-TW"):
        for key in ("sstate.sae_type", "sstate.sae_unknown", "rc.err.SAE-COUNTRY"):
            assert key in CATALOGUES[lang], (lang, key)


# ---------------------------------------------------------------------------------- FIT-U09: chart numbers
def test_u09_the_check_itself() -> None:
    assert chartno.column_refusal(["00123456", "00987654"]) is None
    assert chartno.column_refusal(["00123456", "123456.0"]) == "excel_number"
    assert chartno.column_refusal(["1.23457E+11"]) == "excel_number"
    # with the site's pattern: a number that matches only with its zeros put back lost them
    assert chartno.column_refusal(["00123456", "123456"], r"^\d{8}$") == "lost_zeros"
    assert chartno.column_refusal(["00123456", "AB-1"], r"^\d{8}$") is None  # another fault: not this check's
    assert chartno.column_refusal(["123456"], r"^\d{8}$", "digits:8") is None  # the site's rule pads it back


def _numeric_sheet() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["カルテ番号", "生年月日", "診断"])
    ws.append([123456, "1961-04-03", "痛風"])  # Excel kept a number: 00123456 lost its zeros
    ws.append(["00654321", "1970-01-02", "痛風"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_u09_a_numeric_chart_number_sheet_is_refused_naming_the_column(sb: dict[str, Any]) -> None:  # noqa: F811
    c, _ = login(sb["app"], "crc", SB_PW)
    page = c.get("/site/sheets?ws=main&study=GZQO").text
    before = sb["svc"].store.db.fetchdicts("SELECT * FROM input")
    for lang, words in (("en", "chart-number column “カルテ番号”"), ("ja", "カルテ番号の列「カルテ番号」"),
                        ("zh-TW", "病歷號欄位「カルテ番号」")):  # fmt: skip
        c.post("/lang", data={"csrf": _csrf(page), "lang": lang, "back": "/site/sheets"})
        r = c.post("/site/sheets", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "kind": "sheet"},
                   files={"file": ("list.xlsx", _numeric_sheet(), "application/octet-stream")})  # fmt: skip
        assert 'data-testid="sheet-err"' in r.text and words in r.text, (lang, r.text[-1500:])
    assert sb["svc"].store.db.fetchdicts("SELECT * FROM input") == before  # nothing of it was stored


def test_u09_a_numeric_chart_number_column_holds_the_night(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    _transcode(SITE_A, feed, "utf-8", ("patient", "practitioner", "diagnosis"))
    text = (feed / "patient.csv").read_text(encoding="utf-8")
    (feed / "patient.csv").write_text(text.replace("\n10000001,", "\n10000001.0,", 1), encoding="utf-8")
    rep = _night(_cfg(tmp_path), feed)
    assert rep.held and any(e.startswith("patient: chart-number column 'mrn' refused (excel_number)")
                            for e in rep.errors), rep.errors  # fmt: skip
    # the site's pattern: chart numbers that match it only with a zero put back lost it on the way
    feed2, tmp2 = tmp_path / "feed2", tmp_path / "n2"
    _transcode(SITE_A, feed2, "utf-8", ("patient", "practitioner", "diagnosis"))
    rep = _night(_cfg(tmp2, mrn_regex=r"^0\d{8}$"), feed2)
    assert rep.held and any("'mrn' refused (lost_zeros)" in e for e in rep.errors), rep.errors
