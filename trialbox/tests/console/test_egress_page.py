"""M3: the page "What left this box" on the real console, in three languages, for the administrator only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from console import egress_page, i18n_egress
from tb_common import egress_record

from tests.console.test_console_app import CRC_PW, login
from tests.console.test_rc1_guard import _console


def _app(tmp_path: Path) -> dict[str, Any]:
    b = _console(tmp_path, "TEST")
    if not any(getattr(r, "path", "") == "/admin/egress" for r in b["app"].routes):  # until console.app registers it
        egress_page.register(b["app"], b["app"].state.rc1_guard.h)
    return b


def test_the_three_catalogues_hold_the_same_keys() -> None:
    assert set(i18n_egress.EN) == set(i18n_egress.JA) == set(i18n_egress.ZH)


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_administrator_reads_what_left(tmp_path: Path, lang: str) -> None:
    b = _app(tmp_path)
    c, csrf = login(b["app"])
    h = b["app"].state.rc1_guard.h
    for result, reason in (("masked", ""), ("refused", "identifiers")):
        egress_record.write(h.au, actor="t", route="mail.staff", destination="mail:hospa.test", kind="Message", items=1,
                            rule="mask", size=3, sha256="0" * 64, result=result, reason=reason)  # fmt: skip
    c.post("/lang", data={"lang": lang, "csrf": csrf})
    page = c.get("/admin/egress")
    assert page.status_code == 200 and "mail.staff" in page.text and "egress.tripwire" in page.text
    words = {"en": i18n_egress.EN, "ja": i18n_egress.JA, "zh-TW": i18n_egress.ZH}
    assert any(w["egress.title"] in page.text and w["egress.reason.identifiers"] in page.text for w in words.values())


def test_nobody_else_reads_it(tmp_path: Path) -> None:
    b = _app(tmp_path)
    users = b["app"].state.rc1_guard.h.users
    users.create("crc9", "coordinator", CRC_PW, "crc9@hospa.test")
    c, _ = login(b["app"], "crc9", CRC_PW)
    assert c.get("/admin/egress").status_code == 403


def test_a_real_aggregate_download_passes_the_edge_unchanged(tmp_path: Path) -> None:
    b = _app(tmp_path)
    c, _ = login(b["app"])
    r = c.get(f"/pilot/jobs/01JB{2:022d}/files/feasibility_GZQO.json")
    assert r.status_code == 200 and json.loads(r.content) == {"start_n": 600}
    lines = [json.loads(x) for p in sorted((tmp_path / "audit").glob("*.jsonl")) for x in p.read_text().splitlines()]
    got = [x for x in lines if x["event"] == egress_record.EVENT]
    assert [x["detail"]["route"] for x in got] == ["download.aggregate"] and got[0]["detail"]["result"] == "sent"
