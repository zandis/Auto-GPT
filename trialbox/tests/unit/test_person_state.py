"""D-1221 (review R10): one person's one state, from the facts the console holds, by one written rule."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace as Row

import pytest
from console import person_state as ps
from console.i18n import CATALOGUES
from console.sitestore import MARKS, OUTCOMES
from datacore.lifecycle import STATES as LIFE_STATES
from orchestrator.candidates import STATUSES

TODAY = date(2026, 11, 17)

# (facts, the state, where it came from)
CASES: list[tuple[dict[str, str], str, str]] = [
    ({}, "listed", "list"),
    ({"registry": "candidate"}, "listed", "registry"),
    ({"life": "candidate"}, "listed", "participant"),
    ({"mark": "need_info"}, "need_info", "mark"),
    ({"mark": "not_suitable"}, "set_aside", "mark"),
    ({"mark": "not_now", "recheck": "2026-12-01"}, "set_aside", "mark"),
    ({"mark": "not_now", "recheck": "2026-11-17"}, "listed", "list"),  # the re-check day has come: back on the list
    ({"mark": "approach"}, "to_contact", "mark"),  # F-05: approved, nobody has called yet
    ({"mark": "approach", "registry": "candidate"}, "to_contact", "mark"),
    ({"mark": "approach", "outcome": "not_reached"}, "to_contact", "outcome"),
    ({"mark": "approach", "outcome": "not_approached"}, "not_approached", "outcome"),
    ({"mark": "approach", "outcome": "reached_booked", "registry": "contacted"}, "contacted", "registry"),
    ({"mark": "approach", "outcome": "reached_declined", "registry": "declined"}, "declined", "registry"),
    ({"mark": "approach", "outcome": "lost_contact", "registry": "screen_fail"}, "screen_fail", "registry"),
    # a contact outcome whose screening-log write did not land still names the person's state
    ({"mark": "approach", "outcome": "reached_declined"}, "declined", "outcome"),
    # the later outcome closes a contact the log still calls contacted
    ({"registry": "contacted", "outcome": "not_approached"}, "not_approached", "outcome"),
    ({"registry": "contacted", "life": "approached"}, "contacted", "participant"),
    # the participant record is further along: it wins over the log and over the mark
    ({"mark": "approach", "registry": "contacted", "life": "consented"}, "consented", "participant"),
    ({"registry": "consented", "life": "enrolled"}, "enrolled", "participant"),
    ({"registry": "enrolled", "life": "on_study"}, "on_study", "participant"),
    ({"registry": "enrolled", "life": "completed"}, "completed", "participant"),
    # the log is further along (the REDCap read-back): the record takes it at its next refresh
    ({"registry": "consented", "life": "approached"}, "consented", "registry"),
    ({"registry": "enrolled", "life": "consented"}, "enrolled", "registry"),
    # B-2: the log says consented, the participant record withdrawn: the record's end state wins
    ({"registry": "consented", "life": "withdrawn"}, "withdrawn", "participant"),
    ({"registry": "enrolled", "life": "screen_fail"}, "screen_fail", "participant"),
    ({"life": "screen_fail", "life_reason": "declined"}, "declined", "participant"),
    # an end state on the log wins over a participant record not yet at an end
    ({"registry": "withdrawn", "life": "on_study"}, "withdrawn", "registry"),
    ({"registry": "declined", "life": "approached"}, "declined", "registry"),
    # a set-aside mark never hides what the log says happened
    ({"mark": "not_suitable", "registry": "contacted"}, "contacted", "registry"),
]


@pytest.mark.parametrize(("facts", "want", "source"), CASES)
def test_one_state_by_the_written_rule(facts: dict[str, str], want: str, source: str) -> None:
    got = ps.state_of(ps.Facts(**facts), TODAY)
    assert (got.name, got.source) == (want, source)
    assert got.key == f"person.state.{want}"


def test_every_source_word_has_a_state_and_every_state_its_words() -> None:
    assert set(ps.FROM_LIFE) == set(LIFE_STATES)
    assert set(ps.FROM_REGISTRY) == set(STATUSES)
    assert set(ps.FROM_OUTCOME) == set(OUTCOMES)
    assert set(ps.FROM_MARK) == set(MARKS)
    assert set(ps.CANDIDATE) | set(ps.PARTICIPANT) == set(ps.STATES) and len(ps.STATES) == 13
    for lang, cat in CATALOGUES.items():
        words = [cat[ps.key(s)] for s in ps.STATES]
        assert len(set(words)) == len(words), (lang, words)  # one word per state, none shared
        # the older key families read the same words: one state, one name, on every page and sheet
        for old, name in ps.FROM_LIFE.items():
            assert cat[f"life.state.{old}"] == cat[ps.key(name)], (lang, old)
        for old, name in ps.FROM_REGISTRY.items():
            assert cat[f"registry.status.{old}"] == cat[ps.key(name)], (lang, old)
    assert CATALOGUES["en"][ps.key("to_contact")] == "To contact"


def test_phase_and_contact_step() -> None:
    s = ps.state_of(ps.Facts(mark="approach"))
    assert s.phase == "candidate" and s.contactable and not s.ended
    for life in ("consented", "enrolled", "on_study", "completed", "withdrawn"):
        s = ps.state_of(ps.Facts(life=life))
        assert s.phase == "participant" and not s.contactable, life  # F-13: no contact step for a participant
    for reg in ("declined", "screen_fail"):
        assert not ps.state_of(ps.Facts(registry=reg)).contactable


def test_a_study_gathered_from_its_four_sources_and_counted_once() -> None:
    reg = [Row(pid="a", status="contacted", updated_at="2026-11-10T09:00:00+00:00", updated_by="console:crc"),
           Row(pid="b", status="consented", updated_at="2026-11-11T09:00:00+00:00", updated_by="console:crc"),
           Row(pid="c", status="enrolled", updated_at="2025-12-30T09:00:00+00:00", updated_by="rc-bridge"),
           Row(pid="o", status="consented", updated_at="2026-11-11T09:00:00+00:00", updated_by="console:crc")]  # fmt: skip
    marks = {"a": Row(mark="approach", at="2026-11-09T01:00:00+00:00", by="pi", reason=None),
             "d": Row(mark="approach", at="2026-11-12T01:00:00+00:00", by="pi", reason=None),
             "e": Row(mark="not_now", at="2026-11-01T01:00:00+00:00", by="pi", reason="2026-11-15")}  # fmt: skip
    outs = [Row(pid="d", outcome="not_reached", at="2026-11-13T02:00:00+00:00", by="crc")]
    subs = [
        {"pid": "b", "record": "GZQO-0002", "state": "withdrawn", "since": "2026-11-14", "changed_by": "crc"},
        {"pid": "", "record": "GZQO-0009", "state": "consented", "since": "2026-11-15", "changed_by": "crc"},
    ]
    people = ps.gather(registry=reg, marks=marks, outcomes=outs, subjects=subs, gone={"o"}, today=TODAY)
    states = people.states()
    assert {k: v.name for k, v in states.items()} == {
        "a": "contacted", "b": "withdrawn", "c": "enrolled", "d": "to_contact", "e": "listed",
        "#GZQO-0009": "consented"}  # fmt: skip
    assert "o" not in states and people.of("o").name == "consented"  # opted out: in no count, still readable
    assert people.of("nobody").name == "listed"
    c = people.counts()
    assert sum(c.values()) == 6 and c["withdrawn"] == 1 and c["to_contact"] == 1
    assert ps.shown_counts(c) == [("to_contact", 1), ("contacted", 1), ("consented", 1), ("enrolled", 1),
                                  ("withdrawn", 1)]  # fmt: skip
    # the research office's year: the state began in the year (c was enrolled in 2025)
    assert people.in_year(2026)["enrolled"] == 0 and people.in_year(2025)["enrolled"] == 1
    assert states["b"].source == "participant" and states["b"].since == "2026-11-14"
