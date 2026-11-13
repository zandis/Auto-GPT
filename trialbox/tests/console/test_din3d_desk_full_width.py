"""NEW-DIN-3d (D-548): the opt-out desk takes a chart number typed in full-width characters.

The desk's own shape check (letters, digits or ``-``) ran on the text as typed and refused full-width digits before
the box was asked, although every path to a pseudonym writes them half-width first (``tb_common.chartno``). A
keeper with a Japanese or Chinese input method on types them without noticing."""

from __future__ import annotations

from typing import Any

import pytest
from console.backend import Unavailable
from tb_common.optout import OptOutRegister

from tests.console.test_console_app import box  # noqa: F401 - the fixture by name
from tests.console.test_d273_privacy_guards import B, _events
from tests.console.test_role_pages import _csrf, _user


def _desk(b: dict[str, Any], sent: list[dict[str, Any]]) -> Any:
    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            sent.append(dict(body or {}))
            return {"pid": B, "known": True}
        raise Unavailable("no study store in this test")

    b["backend"].study_api = study_api
    return _user(b, "dpo1", "privacy")


def _post(c: Any, **form: str) -> Any:
    return c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/site/opt-outs").text), **form}, follow_redirects=False)


@pytest.mark.parametrize(
    ("typed", "sent_as"),
    [
        ("００１２３４５６", "00123456"),  # full-width digits
        ("　００１２３４５６　", "00123456"),  # with ideographic blanks around
        ("ＳＹＮ－０００１", "SYN-0001"),  # full-width letters and hyphen
        (" 00123456 ", "00123456"),  # half-width, as before
    ],
)
def test_a_full_width_chart_number_reaches_the_box_half_width(box: dict[str, Any], typed: str, sent_as: str) -> None:  # noqa: F811
    sent: list[dict[str, Any]] = []
    c = _desk(box, sent)
    r = _post(c, chart_no=typed)
    assert r.status_code == 303 and r.headers["location"] == "/site/opt-outs?done=added", r.text[-300:]
    assert [s["chart_no"] for s in sent] == [sent_as]
    assert [e.pid for e in OptOutRegister().current()] == [B]
    assert len(_events(box, "console.chart_lookup")) == 1


@pytest.mark.parametrize("typed", ["００１２＃４", "12 34", "１２　３４", "患者12"])
def test_what_is_not_a_chart_number_is_still_refused_before_the_box_is_asked(box: dict[str, Any], typed: str) -> None:  # noqa: F811
    sent: list[dict[str, Any]] = []
    c = _desk(box, sent)
    r = _post(c, chart_no=typed)
    assert r.status_code == 400 and sent == [] and OptOutRegister().current() == []


def test_a_whole_pseudonym_in_full_width_is_still_not_a_chart_number(box: dict[str, Any]) -> None:  # noqa: F811
    sent: list[dict[str, Any]] = []
    c = _desk(box, sent)
    wide = "".join(chr(ord(ch) + 0xFEE0) for ch in B)
    r = _post(c, chart_no=wide)
    assert r.status_code == 400 and sent == [] and "pseudonym" in r.text
