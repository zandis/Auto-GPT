"""Lane K (HOLISTIC-3 §5.2): the watch mark on the weekly page, end to end in the console. The PI marks "Not now"
and names the criterion to watch; the patient leaves the list; a later SCREEN gives that criterion another answer and
the patient is back with the criterion named. A criterion that is not on the patient's row is refused. The list
carries no visit, so the clinic list is not offered. All data is synthetic."""

from __future__ import annotations

import re
from typing import Any

from console.sitestore import SiteStore

from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name

PW = "watch-mark-password-01"
A = "a" * 32
WATCHED = "GZQO-EXC-06"


def _row(verdict: str) -> dict[str, Any]:
    return {"pid": A, "tier": "review", "next_appointment": None, "practitioner_id": "DR-SYN", "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}},
                         {"id": WATCHED, "verdict": verdict, "evidence": {"resource_refs": []}}],
            "actions": [], "n_unknown": 1 if verdict == "unknown" else 0}  # fmt: skip


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def test_a_watched_criterion_that_changes_brings_the_patient_back(box: dict[str, Any]) -> None:  # noqa: F811
    _screen(box, 9811, "3.0.0", [_row("unknown")], 0)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    pi, _ = login(box["app"], "pi", PW)
    week = pi.get("/studies/GZQO/week?list=all").text
    sheet = pi.get(f"/studies/GZQO/patients/{A}").text  # the full chart's mark box offers the open criteria
    assert f'data-testid="watch-{A[:8]}"' in sheet and f'<option value="{WATCHED}=unknown">' in sheet
    assert 'data-testid="list-clinic"' not in week  # no visit on the list: no visit list
    bad = pi.post(f"/studies/GZQO/patients/{A}/mark",
                  data={"csrf": _csrf(week), "mark": "not_now", "reason": "GZQO-INC-99"})  # fmt: skip
    assert bad.status_code == 400
    r = pi.post(
        f"/studies/GZQO/patients/{A}/mark",
        data={"csrf": _csrf(week), "mark": "not_now", "reason": f"{WATCHED}=unknown"},
    )
    assert r.status_code in (200, 303), r.text[:300]
    assert str(SiteStore().latest_marks("GZQO")[A].reason).endswith(f" watch:{WATCHED}=unknown")
    assert f'data-testid="row-{A[:8]}"' not in pi.get("/studies/GZQO/week?list=all").text  # set aside
    _screen(box, 9812, "3.0.0", [_row("fail")], 2)  # the next run answers the watched criterion
    back = pi.get("/studies/GZQO/week?list=all").text
    assert f'data-testid="watch-fired-{A[:8]}"' in back and WATCHED in back


def test_a_fired_watch_stays_on_the_list_when_the_next_run_reads_the_first_answer_again(box: dict[str, Any]) -> None:  # noqa: F811
    """Review K1: the patient is not set aside again before the PI acts; a new mark clears the kept firing."""
    _screen(box, 9821, "3.0.0", [_row("unknown")], 0)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    name_pi(box, "pi")
    pi, _ = login(box["app"], "pi", PW)
    week = pi.get("/studies/GZQO/week?list=all").text
    mark = {"csrf": _csrf(week), "mark": "not_now", "reason": f"{WATCHED}=unknown"}
    pi.post(f"/studies/GZQO/patients/{A}/mark", data=mark)
    _screen(box, 9822, "3.0.0", [_row("fail")], 2)
    assert f'data-testid="watch-fired-{A[:8]}"' in pi.get("/studies/GZQO/week?list=all").text  # the view keeps it
    _screen(box, 9823, "3.0.0", [_row("unknown")], 4)  # the run after reads the first answer, no change
    assert f'data-testid="watch-fired-{A[:8]}"' in pi.get("/studies/GZQO/week?list=all").text
    pi.post(f"/studies/GZQO/patients/{A}/mark", data=mark)  # the PI marks again
    assert f'data-testid="row-{A[:8]}"' not in pi.get("/studies/GZQO/week?list=all").text  # set aside afresh
