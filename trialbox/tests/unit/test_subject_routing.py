from __future__ import annotations

import pytest
from tb_common.routing import RoutingViolation, check, check_gateway
from tb_common.subject import SubjectError, parse_subject
from tb_contracts import Routing


@pytest.mark.parametrize(
    "raw,cmd,ruleset,opts,comment",
    [
        (
            "FEAS GZQO lookback=36 variant=bmi:24,25,27",
            "FEAS",
            "GZQO",
            {"lookback": "36", "variant": "bmi:24,25,27"},
            None,
        ),
        (
            "SCREEN GZQO version=1.0.0 window=180 pract=P12345,P23456",
            "SCREEN",
            "GZQO",
            {"version": "1.0.0", "window": "180", "pract": "P12345,P23456"},
            None,
        ),
        ("NAV RA-BIO dept=RHEU", "NAV", "RA-BIO", {"dept": "RHEU"}, None),
        ("Re: APPROVE GZQO version=1.0.0 -- looks good", "APPROVE", "GZQO", {"version": "1.0.0"}, "looks good"),
        ("status 01JB0000000000000000000000", "STATUS", "01JB0000000000000000000000", {}, None),
        ("回覆: FEAS GZQO", "FEAS", "GZQO", {}, None),
        ("feas gzqo", "FEAS", "GZQO", {}, None),
        (
            "SUBMIT RA-BIO bundle=01JB0000000000000000000000",
            "SUBMIT",
            "RA-BIO",
            {"bundle": "01JB0000000000000000000000"},
            None,
        ),
    ],
)
def test_valid_subjects(raw: str, cmd: str, ruleset: str, opts: dict[str, str], comment: str | None) -> None:
    s = parse_subject(raw)
    assert (s.cmd, s.ruleset, s.options, s.comment) == (cmd, ruleset, opts, comment)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "FEAS",
        "DELETE GZQO",
        "FEAS GZQO lookback",
        "FEAS GZQO color=red",
        "FEAS GZQO!",
        "STATUS GZQO",
        "FEAS ABCDEFGHIJKLMNOPQ",
        "FEAS GZQO window=1 window=2",
        "FEAS GZQO dept=a/b",
    ],
)
def test_invalid_subjects(raw: str) -> None:
    with pytest.raises(SubjectError):
        parse_subject(raw)


def test_routing_enforcement() -> None:
    r = Routing(
        aggregate_to=["sponsor@pharma.example"],
        list_to=["pi@hospa.test", "crc1@hospa.test"],
        referral_to={"META": "meta-head@hospa.test", "X": "outside@other.example"},
    )
    dom = ["hospa.test"]
    check("aggregate", ["sponsor@pharma.example"], r, dom)
    check("phi", ["pi@hospa.test", "META-HEAD@hospa.test"], r, dom)
    with pytest.raises(RoutingViolation):
        check("phi", ["sponsor@pharma.example"], r, dom)
    with pytest.raises(RoutingViolation):
        check("phi", ["outside@other.example"], r, dom)  # referral outside internal domains
    with pytest.raises(RoutingViolation):
        check("phi", ["nurse@hospa.test"], r, dom)  # internal but not routed for this ruleset
    assert check_gateway("phi", ["a@hospa.test", "b@x.example"], dom) == ["b@x.example"]
