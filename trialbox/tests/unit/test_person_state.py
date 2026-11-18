"""D-1221 (review R10): one person's one state, from the facts the console holds, by one written rule."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace as Row
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import person_state as ps
from console.i18n import CATALOGUES
from console.sitestore import MARKS, OUTCOMES
from datacore.lifecycle import STATES as LIFE_STATES
from orchestrator.candidates import STATUSES

TODAY = date(2026, 11, 17)

T1, T2, T3, T4 = "2026-11-01T09:00:00", "2026-11-02T09:00:00", "2026-11-03T09:00:00", "2026-11-04T09:00:00"

# (facts, the state, where it came from)
CASES: list[tuple[dict[str, Any], str, str]] = [
    ({}, "listed", "list"),
    ({"registry": "candidate"}, "listed", "registry"),
    ({"life": "candidate"}, "listed", "participant"),
    ({"mark": "need_info"}, "need_info", "mark"),
    ({"mark": "not_suitable"}, "set_aside", "mark"),
    ({"mark": "not_now", "recheck": "2026-12-01"}, "set_aside", "mark"),
    ({"mark": "not_now", "recheck": "2026-11-17"}, "listed", "mark"),  # the re-check day has come: back on the list
    ({"mark": "approach"}, "to_contact", "mark"),  # F-05: approved, nobody has called yet
    ({"mark": "approach", "registry": "candidate"}, "to_contact", "mark"),
    ({"mark": "approach", "mark_at": T1, "outcome": "not_reached", "outcome_at": T2}, "to_contact", "outcome"),
    ({"mark": "approach", "mark_at": T1, "outcome": "not_approached", "outcome_at": T2}, "not_approached", "outcome"),
    (
        {
            "mark": "approach",
            "mark_at": T1,
            "outcome": "reached_booked",
            "outcome_at": T2,
            "registry": "contacted",
            "registry_at": T2,
        },
        "contacted",
        "registry",
    ),
    (
        {
            "mark": "approach",
            "mark_at": T1,
            "outcome": "reached_declined",
            "outcome_at": T2,
            "registry": "declined",
            "registry_at": T2,
        },
        "declined",
        "registry",
    ),
    # a contact outcome whose screening-log write did not land still names the person's state
    ({"mark": "approach", "mark_at": T1, "outcome": "reached_declined", "outcome_at": T2}, "declined", "outcome"),
    # the later outcome closes a contact the log called contacted before it
    (
        {"registry": "contacted", "registry_at": T1, "outcome": "not_approached", "outcome_at": T2},
        "not_approached",
        "outcome",
    ),
    ({"registry": "contacted", "life": "approached"}, "contacted", "participant"),  # a tie: the participant record
    # from consent on, the record is the state; the newer of the participant record and the log
    (
        {"mark": "approach", "registry": "contacted", "registry_at": T1, "life": "consented", "life_at": T2},
        "consented",
        "participant",
    ),
    ({"registry": "consented", "registry_at": T1, "life": "enrolled", "life_at": T2}, "enrolled", "participant"),
    ({"registry": "enrolled", "registry_at": T1, "life": "on_study", "life_at": T2}, "on_study", "participant"),
    # the log is newer (the REDCap read-back): the record takes it at its next refresh
    ({"registry": "consented", "registry_at": T2, "life": "approached", "life_at": T1}, "consented", "registry"),
    ({"registry": "enrolled", "registry_at": T2, "life": "consented", "life_at": T1}, "enrolled", "registry"),
    # B-2: the log said consented, the participant record withdrew later
    ({"registry": "consented", "registry_at": T1, "life": "withdrawn", "life_at": T2}, "withdrawn", "participant"),
    ({"life": "screen_fail", "life_reason": "declined"}, "declined", "participant"),
    # review of J-2: an old hand-set end state on the log never beats a later participant step
    ({"registry": "withdrawn", "registry_at": T1, "life": "consented", "life_at": T2}, "consented", "participant"),
    ({"registry": "declined", "registry_at": T1, "life": "consented", "life_at": T2}, "consented", "participant"),
    # a set-aside mark never hides what the log says happened after it
    ({"mark": "not_suitable", "mark_at": T1, "registry": "contacted", "registry_at": T2}, "contacted", "registry"),
    # S1: approached, not reached, then the investigator sets the person aside or takes the mark back
    ({"mark": "not_suitable", "mark_at": T3, "outcome": "not_reached", "outcome_at": T2}, "set_aside", "mark"),
    ({"mark": "withdrawn", "mark_at": T3, "outcome": "not_reached", "outcome_at": T2}, "listed", "mark"),
    # A: not approached, then the investigator marks Approach again: to contact again
    ({"mark": "approach", "mark_at": T3, "outcome": "not_approached", "outcome_at": T2}, "to_contact", "mark"),
    # B: declined, then contacted again on the log
    (
        {"outcome": "reached_declined", "outcome_at": T1, "registry": "contacted", "registry_at": T2},
        "contacted",
        "registry",
    ),
    # C: lost contact, then a later fact (reached and booked)
    (
        {"outcome": "reached_booked", "outcome_at": T3, "registry": "screen_fail", "registry_at": T2},
        "contacted",
        "outcome",
    ),
    # D: declined, the record screen-failed, then the coordinator undoes the step on the participant page
    (
        {
            "outcome": "reached_declined",
            "outcome_at": T1,
            "registry": "declined",
            "registry_at": T1,
            "life": "approached",
            "life_at": T4,
        },
        "contacted",
        "participant",
    ),
    # D, undone to the start: the log set back after the outcome wrote it; the Approach in force speaks again
    (
        {
            "mark": "approach",
            "mark_at": T1,
            "outcome": "reached_declined",
            "outcome_at": T2,
            "registry": "candidate",
            "registry_at": T3,
            "life": "candidate",
            "life_at": T3,
        },
        "to_contact",
        "mark",
    ),
]


@pytest.mark.parametrize(("facts", "want", "source"), CASES)
def test_one_state_by_the_written_rule(facts: dict[str, Any], want: str, source: str) -> None:
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
    for reg in ("declined", "screen_fail"):  # the review: a candidate the study has finished with keeps the panel
        assert ps.state_of(ps.Facts(registry=reg)).contactable
    # the facts could not be read: unknown, never on the list, never contactable, counted nowhere
    people = ps.People({"a": ps.Facts(mark="approach")}, TODAY, readable=False)
    assert people.of("a").name == ps.UNKNOWN and not people.of("a").contactable
    assert ps.shown_counts(people.counts()) == []
    for cat in CATALOGUES.values():
        assert cat[ps.key(ps.UNKNOWN)] and cat["outcome.participant"] and cat["outcome.state_unknown"]


def test_the_latest_record_of_a_pseudonym_is_kept_and_the_funnel_reconciles() -> None:
    subs: list[dict[str, Any]] = [{"pid": "a", "record": "X-0002", "state": "withdrawn", "changed_at": T3, "ever": ["consented", "withdrawn"]},
            {"pid": "a", "record": "X-0001", "state": "consented", "changed_at": T1}]  # fmt: skip
    people = ps.gather(subjects=subs, registry=[Row(pid="b", status="enrolled", updated_at=T2, updated_by="")])
    assert people.of("a").name == "withdrawn" and people.of("a").record == "X-0002"
    c = people.counts()
    f = ps.funnel(people, ["a", "b", "c"])
    # the written definition (D-1221): consented on the home card = everyone who ever consented (the withdrawn "a" too)
    assert f["consented"] == sum(c[s] for s in ps.PARTICIPANT) == 2
    assert f["enrolled"] == c["enrolled"] + c["on_study"] + c["completed"] == 1
    assert f["found"] == 3 and f["contacted"] == 2


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


# ---------------------------------------------------------------------------------------------- review of J-2, round 2
TOKYO, NEW_YORK = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/New_York")
# (site zone, facts, the state): the console stamps marks and outcomes in UTC, the orchestrator the log and the record in
# the site's zone; a comparison of text would make every log row 9 h newer in Tokyo
ZONED: list[tuple[ZoneInfo, dict[str, Any], str]] = [
    # 1. declined at 10:00Z (the log 19:00+09:00); the PI marks Approach again at 11:00Z: to contact
    (
        TOKYO,
        {
            "outcome": "reached_declined",
            "outcome_at": "2026-11-17T10:00:00+00:00",
            "registry": "declined",
            "registry_at": "2026-11-17T19:00:00+09:00",
            "mark": "approach",
            "mark_at": "2026-11-17T11:00:00.123456+00:00",
        },
        "to_contact",
    ),
    # 4. a site at -05:00: the outcome undone two hours later (the log back to "on the list" at 12:00-05:00)
    (
        NEW_YORK,
        {
            "outcome": "reached_declined",
            "outcome_at": "2026-11-17T15:00:00+00:00",
            "registry": "candidate",
            "registry_at": "2026-11-17T12:00:00-05:00",
            "mark": "approach",
            "mark_at": "2026-11-17T14:00:00+00:00",
        },
        "to_contact",
    ),
    # 5. set aside after a booked contact (Tokyo)
    (
        TOKYO,
        {
            "outcome": "reached_booked",
            "outcome_at": "2026-11-17T10:00:00+00:00",
            "registry": "contacted",
            "registry_at": "2026-11-17T19:00:00+09:00",
            "mark": "not_suitable",
            "mark_at": "2026-11-17T12:00:00+00:00",
        },
        "set_aside",
    ),
    # a time without an offset is read in its source's zone: the log's naive 19:30 is Tokyo time (10:30Z)
    (
        TOKYO,
        {
            "registry": "contacted",
            "registry_at": "2026-11-17T19:30:00",
            "mark": "not_suitable",
            "mark_at": "2026-11-17T10:45:00",
        },
        "set_aside",
    ),
    # 6. consent undone to a candidate on the record, the log not mirrored: the record's undo is the newer fact
    (
        TOKYO,
        {
            "life": "candidate",
            "life_at": "2026-11-18T10:00:00+09:00",
            "registry": "consented",
            "registry_at": "2026-11-17T10:00:00+09:00",
        },
        "listed",
    ),
    # 7. a plain day is coarse: a timed fact of that day is later
    (
        TOKYO,
        {"life": "approached", "life_at": "2026-11-17", "mark": "not_suitable", "mark_at": "2026-11-17T01:00:00+00:00"},
        "set_aside",
    ),
    # 8. "Z" is UTC
    (
        TOKYO,
        {
            "outcome": "reached_declined",
            "outcome_at": "2026-11-17T10:00:01Z",
            "mark": "approach",
            "mark_at": "2026-11-17T10:00:00+00:00",
        },
        "declined",
    ),
    # frozen clock (every fact at one instant): the order of the work decides.
    # not reached, then Not suitable: a mark other than Approach came after the outcome
    (
        TOKYO,
        {"mark": "not_suitable", "mark_at": T1, "outcome": "not_reached", "outcome_at": T1, "marks": 2},
        "set_aside",
    ),
    # not approached, then Not now, then Approach again (the third mark event): to contact
    (
        TOKYO,
        {"mark": "approach", "mark_at": T1, "outcome": "not_approached", "outcome_at": T1, "marks": 3},
        "to_contact",
    ),
    # the first Approach came before its outcome
    (
        TOKYO,
        {
            "mark": "approach",
            "mark_at": T1,
            "outcome": "reached_declined",
            "outcome_at": T1,
            "registry": "declined",
            "registry_at": T1,
            "marks": 1,
        },
        "declined",
    ),
    # 3. an undo in the same second as its outcome (the log keeps seconds): the undo follows its original
    (
        TOKYO,
        {
            "outcome": "reached_declined",
            "outcome_at": "2026-11-17T10:00:00.5+00:00",
            "registry": "candidate",
            "registry_at": "2026-11-17T10:00:00+00:00",
            "mark": "approach",
            "mark_at": "2026-11-17T09:00:00+00:00",
        },
        "to_contact",
    ),
]


@pytest.mark.parametrize(("tz", "facts", "want"), ZONED)
def test_times_are_instants_and_ties_follow_the_work(tz: ZoneInfo, facts: dict[str, Any], want: str) -> None:
    assert ps.state_of(ps.Facts(**facts), TODAY, tz).name == want


def test_an_erased_token_or_an_opted_out_person_is_in_no_count() -> None:
    from tb_common.erased import Gone

    reg = [
        Row(pid="erased:2026-11-01:abcd", status="consented", updated_at=T1, updated_by=""),
        Row(pid="o", status="enrolled", updated_at=T1, updated_by=""),
        Row(pid="a", status="contacted", updated_at=T1, updated_by=""),
    ]
    people = ps.gather(registry=reg, gone=Gone({"o"}))
    assert set(people.states()) == {"a"}
    assert sum(people.counts().values()) == 1
    assert ps.funnel(people, ["o", "erased:2026-11-01:abcd"])["found"] == 1


def test_enrolled_ever_reached_stays_counted_after_a_withdrawal() -> None:
    subs = [
        {
            "pid": "a",
            "record": "X-1",
            "state": "withdrawn",
            "changed_at": T2,
            "ever": ["candidate", "approached", "consented", "enrolled", "withdrawn"],
        }
    ]
    people = ps.gather(subjects=subs)
    assert people.of("a").name == "withdrawn"
    f = ps.funnel(people)
    assert f["contacted"] == f["consented"] == f["enrolled"] == 1
