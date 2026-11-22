"""Gate 2's cross-path test (review 2026-11-22 §3.5, as the owner ruled): can two people ever share a record, or one
person's record split, by any road into the box?

Synthetic people who exist to collide (:mod:`tests.gate2_people`) are driven through every road the product has
(:mod:`tests.gate2_kit`), in three row orders, once more as a replay and once as a rebuild from empty, and the six
invariants are judged over what the box published: the served NDJSON, the screening lake, its note chunks and its
retrieval answers, the OMOP CDM tables as stored and as exported, the EDC drafts, and for a held chart the patient
index and the audit. Each case reports every finding at once (``<invariant> store=<store> person=<letters>: <what>``).

The judges, the kind collector and the case matrix are themselves tested here on small hand-built stores, so a judge
emptied, a store dropped or an order lost turns this file red. The randomised version with hundreds of generated
people is ``tests/perf/test_gate2_cross_path_nightly.py`` (marker ``perf``: the bench's nightly). The planted-mistake
harness that proves this test is ``tools/gate2_planted.py``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from tests import gate2_kit as kit
from tests import gate2_people as gp

STORIES: dict[str, Callable[[], gp.Story]] = {
    "one_night": gp.one_night_story,
    "corrections": gp.corrections_story,
    "conflict_birth": partial(gp.conflict_story, ("J", "K")),
    "conflict_national": partial(gp.conflict_story, ("M", "N")),
    "conflict_birth_later": partial(gp.conflict_story, ("J", "K"), later=True),
    "conflict_national_later": partial(gp.conflict_story, ("M", "N"), later=True),
}

#: every road with every story its input can say (a road's ``cannot`` names the stories its source format has no way
#: to write, and why), in every order
CASES = [(r.name, s, o) for r in kit.ROADS for s in STORIES if s not in r.cannot for o in gp.ORDERS]


@pytest.fixture(autouse=True)
def _site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", gp.CHART_RULE)
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    monkeypatch.setenv("TB_TZ", kit.TZ)
    monkeypatch.setenv("TB_SITE_ID", kit.SITE)


@pytest.mark.nodb
def test_edc_is_drafted_in_one_order_of_every_road_and_story() -> None:
    assert {(r, s) for r, s, o in CASES if o == "as_written"} == {(r, s) for r, s, _ in CASES}


@pytest.mark.parametrize(("road", "story", "order"), CASES)
def test_cross_path(road: str, story: str, order: str, tmp_path: Path, db_url: str) -> None:
    r = kit.ROAD[road]
    # the EDC drafts read the lake, which every order's case judges; they are drafted (twice) in the as-written order
    d = kit.drive(r, STORIES[story](), order, tmp_path, db_url, edc=order == "as_written")
    assert d.kinds == set(r.kinds), f"{road} declares {r.kinds}; the product opened {sorted(d.kinds)}"
    findings = kit.judge(d)
    assert not findings, f"{road} / {story} / {order}: {len(findings)} findings\n" + kit.summary(findings)


# ---------------------------------------------------------------------------------------------- the registry
def test_every_source_kind_has_a_road() -> None:
    """The product's source kinds, collected from every adapter module, each have a road here (each road's kind is
    checked as observed, not declared, by every case above); a reviewed non-kind no longer found fails too, so the
    exclusion table cannot rot."""
    found = {v for _, _, v in kit.product_kind_sites()}
    kinds = kit.product_source_kinds()
    assert {"csv", "cgrd_sql", "ssmix2", "fhir_bulk"} <= kinds, kinds
    covered = {k for road in kit.ROADS for k in road.kinds}
    assert kinds <= covered, f"source kinds with no road in the cross-path test: {sorted(kinds - covered)}"
    assert set(kit.NOT_SOURCE_KINDS) <= found, f"stale non-kinds: {sorted(set(kit.NOT_SOURCE_KINDS) - found)}"


SPELLINGS = """
import argparse
KINDS = ("k_const",)
D = {"k_dget": 1}
def f(kind, source_kind, obj, ap):
    if kind == "k_eq": pass
    if "k_rev" == source_kind: pass
    if kind != "k_ne": pass
    if kind in ("k_tuple",): pass
    if kind in ["k_list"]: pass
    if kind not in {"k_set"}: pass
    if kind in frozenset({"k_fs"}): pass
    if kind in KINDS: pass
    if kind.lower() == "k_lower": pass
    if obj.source_kind == "k_attr": pass
    x = {"k_dict": 1}[kind]
    y = D.get(source_kind)
    match kind:
        case "k_match" | "k_match_or":
            pass
    ap.add_argument("--source", choices=["k_choice"])
"""


@pytest.mark.nodb
def test_the_kind_collector_finds_every_spelling() -> None:
    got = {v for _, _, v in kit.kinds_in_text(SPELLINGS)}
    want = {"k_const", "k_dget", "k_eq", "k_rev", "k_ne", "k_tuple", "k_list", "k_set", "k_fs", "k_lower"}
    want |= {"k_attr", "k_dict", "k_match", "k_match_or", "k_choice"}
    assert want <= got, sorted(want - got)
    assert not kit.kinds_in_text("def f(other):\n    return other == 'nope'\n")


# ---------------------------------------------------------------------------------------------- the case matrix
@pytest.mark.nodb
def test_the_case_matrix_is_whole() -> None:
    assert set(gp.ORDERS) == {"as_written", "reversed", "interleaved"}
    night = gp.base_night(gp.people())
    orders = [tuple(r.marker for r in gp.ordered(night, o).records) for o in gp.ORDERS]
    assert len(set(orders)) == 3 and sorted(orders[0]) == sorted(orders[1]) == sorted(orders[2])
    assert {r.name for r in kit.ROADS} == {"csv", "cgrd_sql", "ssmix2", "fhir_bulk_one", "fhir_bulk_two", "backfill"}
    cannot = {("ssmix2", s) for s in STORIES if s.startswith("conflict")}
    want = {(r.name, s, o) for r in kit.ROADS for s in STORIES for o in gp.ORDERS}
    want -= {(r, s, o) for r, s in cannot for o in gp.ORDERS}
    assert set(CASES) == want and len(CASES) == len(want)
    assert set(kit.STORES) == {"ndjson", "lake", "chunks", "answers", "omop", "omop_export", "edc"}
    assert set(kit.PATH_STORES) == {"ndjson", "lake", "chunks", "omop", "omop_export"}


@pytest.mark.nodb
def test_every_store_expects_rows_of_the_people() -> None:
    """What each store must hold, read from the people table: no store is expected to stay empty (the notes, and
    so the chunks and answers, are in the one-night story)."""
    for name, make in STORIES.items():
        story = make()
        for store in kit.STORES:
            if store in ("chunks", "answers") and name != "one_night":
                continue
            assert kit.expected_for(story, store).total() > 0, (name, store)


# ---------------------------------------------------------------------------------------------- the judges
def _two() -> gp.Story:
    x = gp.Person("X", "00000001", "1950-01-01", "Z000000001")
    y = gp.Person("Y", "00000002", "1960-01-01", "Z000000002")
    night = gp.Night(
        [(x, x.chart), (y, y.chart)],
        [
            gp.Rec("X", "lab", "1", x.chart, "2026-01-01", "1.00"),
            gp.Rec("Y", "lab", "1", y.chart, "2026-01-01", "2.00"),
        ],
    )
    exp = Counter({("X", "Patient"): 1, ("Y", "Patient"): 1, ("X", "Observation"): 1, ("Y", "Observation"): 1})
    return gp.Story({"X": x, "Y": y}, [night], expected=exp)


def _row(rtype: str, key: str, pid: str, marker: str, store: str = "lake", ref: str = "") -> kit.Row:
    return kit.Row(store, rtype, key, pid, marker, ref)


GOOD = [
    _row("Patient", "px", "px", "1950-01-01"),
    _row("Patient", "py", "py", "1960-01-01"),
    _row("Observation", "o1", "px", "1.00"),
    _row("Observation", "o2", "py", "2.00"),
]


@pytest.mark.nodb
def test_sharing_flags_a_shared_pseudonym_and_a_shared_key() -> None:
    owner = _two().owner_of()
    assert not kit.sharing("lake", GOOD, owner, {})
    found = kit.sharing("lake", [*GOOD[:3], _row("Observation", "o1", "px", "2.00")], owner, {})
    assert any("one pseudonym" in f for f in found) and any("one Observation key" in f for f in found)


@pytest.mark.nodb
def test_references_flag_another_persons_visit() -> None:
    owner = {"V1": "X", "V2": "Y", "C1": "X"}
    rows = [_row("Encounter", "e1", "px", "V1"), _row("Encounter", "e2", "py", "V2")]
    assert not kit.references("lake", [*rows, _row("Condition", "c", "px", "C1", ref="e1")], owner, {})
    assert kit.references("lake", [*rows, _row("Condition", "c", "px", "C1", ref="e2")], owner, {})
    assert kit.references("lake", [*rows, _row("Condition", "c", "px", "C1", ref="gone")], owner, {})


@pytest.mark.nodb
def test_splitting_flags_a_second_pseudonym_a_lost_record_and_a_double() -> None:
    story = _two()
    owner, want = story.owner_of(), kit.expected_for(story, "lake")
    assert not kit.splitting("lake", GOOD, owner, story, want)
    assert kit.splitting("lake", [*GOOD[:3], _row("Observation", "o2", "pz", "2.00")], owner, story, want)
    assert kit.splitting("lake", GOOD[:3], owner, story, want)
    assert kit.splitting("lake", [*GOOD, _row("Observation", "o3", "py", "2.00")], owner, story, want)


@pytest.mark.nodb
def test_opt_out_flags_any_row_of_the_opted_out_person() -> None:
    from tb_common.crypto import pid_for_mrn

    story = _two()
    story.optouts = ["00000002"]
    eff = {pid_for_mrn(kit.KEY, "00000002")}
    assert not kit.opt_out([GOOD[0], GOOD[2]], story.owner_of(), story, eff, "after the last night")
    assert kit.opt_out(GOOD, story.owner_of(), story, eff, "after the last night")
    assert kit.opt_out(GOOD[:1], story.owner_of(), story, set(), "after the last night")


@pytest.mark.nodb
def test_hold_flags_a_published_conflict(tmp_path: Path) -> None:
    story = _two()
    story.held = {"Y"}
    story.expected[("Y", "Patient")] = 0
    box = kit.Box(tmp_path, "unused", kit.MAPPINGS["tw"])
    nights = [kit.NightOutcome("n1"), kit.NightOutcome("n2", "HeldOwner", False), kit.NightOutcome("n3")]
    found = kit.hold(kit.Drive(story, box, nights, [GOOD[:1], GOOD[:1]], GOOD[:1], held_pids={"py"}), [nights[1]])
    assert found == [f for f in found if "store=audit" in f]  # a hand-built box has no audit: only that is said
    published = [kit.NightOutcome("n1"), kit.NightOutcome("n2")]
    found = kit.hold(kit.Drive(story, box, published, [GOOD, GOOD], GOOD, held_pids={"py"}), [])
    assert any("was published, not held" in f for f in found) and any("rows of the held chart" in f for f in found)


@pytest.mark.nodb
def test_stability_flags_replay_drift_and_unrecorded_key_changes() -> None:
    story = _two()
    owner = story.owner_of()
    moved = [*GOOD[:3], _row("Observation", "o9", "py", "2.00")]
    assert not kit.stability([GOOD, GOOD], GOOD, owner, story)
    assert kit.stability([GOOD], moved, owner, story)
    assert kit.stability([GOOD, moved], moved, owner, story)
    story.merges = {1: [("00000001", "00000009", "correction")]}  # names X only: Y's key change is still flagged
    assert kit.stability([GOOD, moved], moved, owner, story)
    moved_x = [GOOD[0], GOOD[1], _row("Observation", "o9", "px", "1.00"), GOOD[3]]
    assert not kit.stability([GOOD, moved_x], moved_x, owner, story)


@pytest.mark.nodb
def test_path_flags_a_difference_from_the_rebuild() -> None:
    owner = _two().owner_of()
    assert not kit.path(GOOD, GOOD, owner)
    assert kit.path(GOOD, GOOD[:3], owner)


@pytest.mark.nodb
def test_judge_flags_an_empty_store(tmp_path: Path) -> None:
    story = _two()
    box = kit.Box(tmp_path, "unused", kit.MAPPINGS["tw"])
    rows = [kit.Row("ndjson", r.rtype, r.key, r.pid, r.marker) for r in GOOD]
    d = kit.Drive(story, box, [kit.NightOutcome("n1"), kit.NightOutcome("n2")], [rows], rows, rebuilt=rows)
    empty = {f.split()[1] for f in kit.judge(d) if f.startswith("read ")}
    assert empty == {f"store={s}" for s in kit.STORES if s != "ndjson" and kit.expected_for(story, s).total()}
    assert empty
