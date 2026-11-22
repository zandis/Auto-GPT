"""Gate 5's cross-path test (review 2026-11-22 §3.2 and §3.5, as the owner ruled): can a patient identifier leave
the box, in any form a receiver could read, by any exit?

The synthetic people of :mod:`tests.gate5_people` are planted, one identifier and one encoding class at a time, in
every exit the product has (:mod:`tests.gate5_kit`): the model payload, a mail as handed to its transport (a send and
a reply), the support bundle as built, the enrolment report as downloaded, the sponsor pack as exported. What left is
read as a receiver could read it, and each case reports every finding at once (``<invariant> road=<road>
person=<letter> id=<identifier> class=<class>: <what>``). A refused output must leave nothing; a text with no
identifier must leave; what leaves must be what ``prepare_output`` released for that exit.

The exits are read from the product: every site of the output-sink inventory in an exit area has a road here, or a
reviewed reason it cannot carry patient text (``test_every_exit_site_has_a_road``); a new exit fails it. The judge
is itself tested on known forms below. The planted-mistake harness that proves this test is
``tools/gate5_planted.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tb_common import output_gate

from tests import gate5_kit as kit
from tests import gate5_people as gp

#: the mail roads keep their outbox in the database (MailDB); every other road needs none
CASES = [
    pytest.param(r.name, c.id, marks=() if r.exit == "mail" else (pytest.mark.nodb,))
    for r in kit.ROADS
    for c in gp.CLASSES
    if c.id not in r.cannot
]


@pytest.mark.parametrize(("road", "cls"), CASES)
def test_cross_path(road: str, cls: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    findings = kit.drive(kit.ROAD[road], cls, tmp_path, monkeypatch)
    assert not findings, f"{road} / {cls}: {len(findings)} findings\n" + kit.summary(findings)


@pytest.mark.nodb
def test_every_exit_site_has_a_road() -> None:
    """Every inventory site in an exit area (mail, downloads, job files, the support bundle, packages) has a road
    here, or a reviewed reason it cannot carry patient text; a reviewed site no longer found fails too."""
    sites = {(s.file, s.function) for s in kit.sites()}
    assert set(kit.AREA_EXIT.values()) <= set(output_gate.EXITS)
    assert {r.exit for r in kit.ROADS} == set(output_gate.EXITS), "an exit the gate registers has no road"
    assert {s.area for s in kit.sites()} <= {*kit.AREA_EXIT, "log"}, "an inventory area that is no known exit"
    assert set(kit.ROAD_SITES) | set(kit.NOT_PATIENT_EXITS) <= sites, "a reviewed site is no longer in the product"
    missing = kit.uncovered()
    assert not missing, f"{len(missing)} exit sites with no road in the cross-path test:\n" + "\n".join(missing)


@pytest.mark.nodb
def test_the_case_matrix_is_whole() -> None:
    assert {r.name for r in kit.ROADS} == {
        "model",
        "mail_send",
        "mail_reply",
        "support_bundle",
        "download_enrolment_report",
        "export_sponsor_pack",
    }
    want = set(
        [
            "plain",
            "labelled_name",
            "percent1",
            "percent2",
            "percent3",
            "percent4",
            "percent5",
            "percent_2f_boundary",
            "base64",
            "base64url",
            "base64_json_state",
            "quoted_printable",
            "qp_soft_break",
            "qp_degree_sign",
            "html_entities",
            "html_entities_no_semicolon",
            "x_escape",
            "u_escape",
            "zero_width_joiner",
            "zero_width_space",
            "soft_hyphen",
            "decomposed_macron",
            "fullwidth_digits",
            "encoded_digit_beside",
            "json_integer",
            "cut_at_read_limit",
        ]
    )
    assert {c.id for c in gp.CLASSES} == want
    assert {p.lang for p in gp.people()} == {"ja", "zh-TW", "en"}
    for cls in want:
        assert gp.plants(cls), cls
    assert all(set(r.cannot) <= {"cut_at_read_limit"} for r in kit.ROADS)  # only the bundle reads to a limit
    every = {(p.person.letter, p.ident) for c in gp.CLASSES for p in gp.plants(c.id)}
    assert every == {(p.letter, i) for p in gp.people() for i in gp.IDENTIFIERS}


# ---------------------------------------------------------------------------------------------- the judge
def _left(text: str) -> kit.Outcome:
    return kit.Outcome("x", "body", False, [("body", text.encode("utf-8"))])


@pytest.mark.nodb
@pytest.mark.parametrize("cls", [c.id for c in gp.CLASSES])
def test_the_judge_reads_every_class(cls: str) -> None:
    """Each plant, left as it was planted, is found by the judge in its own class."""
    for p in gp.plants(cls):
        assert kit.survivors(_left(p.text), p.person, p.ident), p.id


@pytest.mark.nodb
def test_the_judge_reads_containers() -> None:
    import gzip
    import io
    import zipfile
    from email.message import EmailMessage

    a = gp.people()[0]
    m = EmailMessage()
    m["Subject"] = "Done"
    m.set_content("x")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("inner.txt", gzip.compress(a.sentence.encode()))
    m.add_attachment(buf.getvalue(), maintype="application", subtype="zip", filename="a.zip")
    o = kit.Outcome("x", "mail", False, [("mail", bytes(m))])
    assert kit.survivors(o, a, "name")
    assert not kit.survivors(kit.Outcome("x", "mail", False, [("mail", b"Subject: Done\n\nnothing here\n")]), a, "name")


@pytest.mark.nodb
def test_the_judge_flags_a_refusal_that_left_bytes_and_a_refused_control() -> None:
    p = gp.plants("plain")[0]
    left = kit.Outcome(p.id, "body", True, [("body", b"held")])
    control = kit.Outcome("control", "body", True)
    found = kit.judge("mail_send", "plain", [left, control], {p.id: p})
    assert any(f.startswith("refusal-left-bytes") for f in found)
    assert any(f.startswith("control-refused") for f in found)
    assert any(f.startswith("ungated") for f in found)


@pytest.mark.nodb
def test_the_judge_finds_half_a_pseudonym() -> None:
    a = gp.people()[0]
    assert kit.survivors(_left("tail " + a.pseudonym[:16]), a, "pseudonym")
    assert not kit.survivors(_left("tail " + a.pseudonym[:8]), a, "pseudonym")
