"""D-387 (T-623, LIFE-015, LIFE-016): the pre-screen log and the screen-failure detail.

Every investigator mark is a row of the pre-screen log, approached or not, with the criteria version it was made on;
only an approached patient has a screening number and a screening-log row. A screen failure for "not eligible" names
the criterion not met, picked from the latest list's approved criteria, and keeps that list's criteria version; the
screening-log row shows "GZQO-EXC-06 (v3.0.0)". All data is synthetic."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import pytest
from console.i18n import CATALOGUES
from console.i18n_prescreen import EN, JA, ZH
from console.screening_log import prescreen_rows
from console.sitestore import Mark
from datacore import lifecycle as lc
from datacore.builtin import builtin_questionnaires
from datacore.lifecycle import Lifecycle, LifeError
from datacore.store import DataCore
from openpyxl import load_workbook
from tb_common.wording import check_page

from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW as LIFE_PW
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name

PW = "prescreen-log-password-01"
A, B, C = "a" * 32, "b" * 32, "c" * 32
FAILED = "GZQO-EXC-06"
AT = "2026-11-08T09:00:00+09:00"


def _row(pid: str) -> dict[str, Any]:
    return {"pid": pid, "tier": "high", "next_appointment": None, "practitioner_id": "DR-SYN", "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}},
                         {"id": FAILED, "verdict": "pass", "evidence": {"resource_refs": []}}],
            "actions": [], "n_unknown": 0}  # fmt: skip


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _sheet(xlsx: bytes, name: str) -> list[tuple[Any, ...]]:
    wb = load_workbook(io.BytesIO(xlsx))
    return [tuple(r) for r in wb[name].iter_rows(values_only=True)]


# ---------------------------------------------------------------------------------------------- acceptance (LIFE-015)
def test_three_marks_give_three_pre_screen_rows_and_one_log_row(box: dict[str, Any]) -> None:  # noqa: F811
    """Three marks on a v3.0.0 list (Approach, Not suitable now, Not now); the coordinator reaches the approached
    patient, who gets a screening number: three pre-screen rows, one screening-log row."""
    _screen(box, 9801, "3.0.0", [_row(A), _row(B), _row(C)], 0)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    name_pi(box, "pi")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "pi", PW)
    week = pi.get("/studies/GZQO/week").text
    for pid, mark, extra in ((A, "approach", {}), (B, "not_suitable", {"reason": "comorbidity"}),
                             (C, "not_now", {"recheck": "2026-12-01"})):  # fmt: skip
        r = pi.post(f"/studies/GZQO/patients/{pid}/mark", data={"csrf": _csrf(week), "mark": mark, **extra})
        assert r.status_code in (200, 303), r.text[:300]
    crc, ccsrf = login(box["app"], "crc", PW)
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": ccsrf, "outcome": "reached_booked"})
    assert r.status_code in (200, 303), r.text[:300]
    page = crc.get("/studies/GZQO/screening-log").text
    log = page.split('data-testid="screening-log"')[1].split("</table>")[0]
    assert len(re.findall(r'data-testid="log-GZQO-\d+"', log)) == 1
    pre = page.split('data-testid="prescreen-log"')[1].split("</table>")[0]
    assert re.findall(r'data-pid="(\w+)"', pre) == ["aaaaaaaa", "bbbbbbbb", "cccccccc"]
    assert pre.count("3.0.0") == 3 and "other illness" in pre  # the version and the mark's reason on every row
    assert 'data-testid="version-GZQO-' in log and "(v3.0.0)" in log
    assert not check_page(page)  # T-116: no verdict word
    xlsx = crc.get("/studies/GZQO/screening-log.xlsx").content
    log_rows = _sheet(xlsx, "screening log")
    assert len(log_rows) == 2 and log_rows[0][-6:-1] == ("criteria_version", "criterion_not_met", "consent_date",
                                                         "consent_form_version", "enrolment_date")  # fmt: skip
    assert log_rows[1][-6] == "3.0.0"  # D-407 (LIFE-020) added the randomisation date after the enrolment date
    pre_rows = _sheet(xlsx, "pre-screen log")
    assert len(pre_rows) == 4  # the header and three rows
    assert [(r[0], r[2], r[3], r[8]) for r in pre_rows[1:]] == [
        (A, "3.0.0", "approach", log_rows[1][0]),
        (B, "3.0.0", "not_suitable", None),
        (C, "3.0.0", "not_now", None),
    ]
    # the Japanese page names the pre-screen log
    pi.post("/lang", data={"csrf": _csrf(week), "lang": "ja", "back": "/"})
    assert "プレスクリーニングログ" in pi.get("/studies/GZQO/screening-log").text


def test_a_withdrawn_or_replaced_mark_stays_a_row() -> None:
    def mk(pid: str, mark: str, at: str, version: str | None = "3.0.0") -> Mark:
        return Mark(pid, mark, None, None, "pi", f"2026-11-0{at}T00:00:00+00:00", "J1", version)

    marks = [mk(A, "need_info", "1"), mk(A, "approach", "2"), mk(B, "not_now", "1", None), mk(B, "withdrawn", "3"),
             mk(C, "not_suitable", "1")]  # fmt: skip
    rows = prescreen_rows(marks, {A: "GZQO-0001"}, {}, {}, {}, {C})
    assert [(r["short"], r["mark"].mark, r["later"], r["no"], r["version"]) for r in rows] == [
        ("aaaaaaaa", "need_info", "replaced", "GZQO-0001", "3.0.0"),
        ("aaaaaaaa", "approach", "", "GZQO-0001", "3.0.0"),
        ("bbbbbbbb", "not_now", "withdrawn", "", ""),  # a mark made before D-364 has no version
    ]  # C opted out: on no log


# ---------------------------------------------------------------------------------------------- LIFE-016
def test_the_log_row_shows_the_criterion_not_met_and_its_version(lb: dict[str, Any]) -> None:  # noqa: F811
    no, other = lb["nos"]
    _screen(lb, 9811, "3.0.0", [_row(A)], 0)
    c, csrf = login(lb["app"], "crc", LIFE_PW)
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="step-criterion"' in page and f'<option value="{FAILED}">' in page and "3.0.0" in page
    # "not eligible" without a criterion, or one not on the approved list: refused, nothing changed
    for crit in ("", "GZQO-EXC-99"):
        r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "screen_fail",
                                                              "reason": "not_eligible", "criterion": crit})  # fmt: skip
        assert r.status_code == 409 and "choose the criterion not met" in r.text
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "screen_fail", "reason": "not_eligible",
                                                          "criterion": FAILED, "on_day": "2026-11-05"})  # fmt: skip
    assert 'data-testid="life-saved"' in r.text and f"criterion not met: {FAILED} (v3.0.0)" in r.text
    # another reason takes no criterion
    r = c.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail", "reason": "declined",
                                                             "criterion": FAILED})  # fmt: skip
    assert 'data-testid="life-saved"' in r.text
    sub = lb["oc"].get(f"/studies/GZQO/subjects/{other}").json()
    assert sub["steps"][-1]["criterion"] == ""
    log = c.get("/studies/GZQO/screening-log").text
    assert f'data-testid="failed-{no}">Criterion not met: {FAILED} (v3.0.0)' in log
    assert f'data-testid="failed-{other}"' not in log
    rows = _sheet(c.get("/studies/GZQO/screening-log.xlsx").content, "screening log")
    by_no = {r[0]: r for r in rows[1:]}
    assert by_no[no][-5] == f"{FAILED} (v3.0.0)" and not by_no[other][-5]


def test_the_api_refuses_a_criterion_on_another_reason(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _ = lb["nos"]
    lb["oc"].post("/studies/GZQO/subjects/refresh", json={"screening": {no: "1" * 32}, "by": "t"})
    r = lb["oc"].post(f"/studies/GZQO/subjects/{no}/step", json={"to": "screen_fail", "reason": "declined",
                                                                  "criterion": FAILED, "by": "t"})  # fmt: skip
    assert r.status_code == 409
    assert "criterion_only" in r.text


# ---------------------------------------------------------------------------------------------- the data core
@pytest.fixture
def life() -> Any:
    dc = DataCore()
    for q in builtin_questionnaires("GZQO"):
        dc.put_form("GZQO", q, "builtin", AT)
    yield Lifecycle(dc)
    dc.close()


def test_the_step_keeps_the_criterion_and_the_form_feeds_it(life: Lifecycle) -> None:
    life.ensure("GZQO", "GZQO-0001", A, "crc", AT)
    life.ensure("GZQO", "GZQO-0002", B, "crc", AT)
    life.ensure("GZQO", "GZQO-0003", C, "crc", AT)
    for kw, why in (({"reason": "declined", "criterion": FAILED}, "criterion_only"),
                    ({"reason": "not_eligible", "criterion": "EXC 06"}, "criterion"),
                    ({"reason": "not_eligible", "criterion": FAILED, "criteria_version": "v 3"}, "criterion"),
                    ({"reason": "not_eligible", "criteria_version": "3.0.0"}, "criterion")):  # fmt: skip
        with pytest.raises(LifeError) as e:
            life.step("GZQO", "GZQO-0001", "screen_fail", by="crc", at=AT, **kw)  # type: ignore[arg-type]
        assert e.value.why == why
    life.step("GZQO", "GZQO-0001", "screen_fail", by="crc", at=AT, reason="not_eligible", criterion=FAILED,
              criteria_version="3.0.0")  # fmt: skip
    # the screening-log form names the criterion: derivation keeps it
    for f, v in {"sl_eligible": "0", "sl_date": "2026-10-30", "sl_criterion": "GZQO-INC-02",
                 "sl_crit_version": "3.0.0"}.items():  # fmt: skip
        life.dc.write("GZQO", "GZQO-0002", "", f, v, "crc", AT, "trialbox")
    life.derive("GZQO", "GZQO-0002", by="crc", at=AT)
    # consent with its form version, then enrolment
    for f, v in {"ic_date": "2026-11-01", "ic_version": "ICF-2.1", "en_date": "2026-11-03", "en_eligible": "1"}.items():
        life.dc.write("GZQO", "GZQO-0003", "", f, v, "crc", AT, "trialbox")
    life.derive("GZQO", "GZQO-0003", by="crc", at=AT)
    got = life.screen_detail("GZQO")
    assert got["GZQO-0001"]["criterion"] == FAILED and got["GZQO-0001"]["criteria_version"] == "3.0.0"
    assert got["GZQO-0002"]["criterion"] == "GZQO-INC-02" and got["GZQO-0002"]["criteria_version"] == "3.0.0"
    assert got["GZQO-0003"] == {"consented": "2026-11-01", "icf_version": "ICF-2.1", "enrolled": "2026-11-03",
                                "criterion": "", "criteria_version": "", "randomised": ""}  # fmt: skip
    assert lc.failed_label(FAILED, "3.0.0") == f"{FAILED} (v3.0.0)" and lc.failed_label("", "3") == ""
    assert date.fromisoformat(got["GZQO-0003"]["enrolled"])


# ---------------------------------------------------------------------------------------------- strings
def test_every_key_in_three_languages_with_the_same_placeholders() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for cat in (JA, ZH):
        for k, v in cat.items():
            assert sorted(re.findall(r"\{(\w+)\}", EN[k])) == sorted(re.findall(r"\{(\w+)\}", v)), k
    for lang, cat in CATALOGUES.items():
        assert all(k in cat for k in EN), lang
        assert not any(check_page(cat[k]) for k in EN), lang  # T-116: no verdict word
