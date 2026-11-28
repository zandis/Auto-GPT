"""``rank_key``: the order "closest to eligible" is a pure key over the verdict rows (MATCH-ARCH 1(e), build item 6).

The properties are checked over an exhaustive small domain, as ``tests/unit/test_safety_properties.py`` does: two
structured criteria, two note criteria and one a person decides, every combination of a handful of verdict states each
(800 patients), under a run on which notes may exclude and one on which they may not.

* turning an open criterion into met never lowers a patient, and strictly raises it;
* adding an unknown never raises a patient, and an unknown with a quote adds nothing to the evidence count;
* a coded "no" sends a patient to the excluded block whatever the other keys say, and a note answer never does it alone;
* the key is a pure function of the rows: the same on a re-run, whatever the order of the verdicts, and the tier in it is
  ``status_of``'s own;
* a list sorted by it holds the same patients, each once, in one fixed order (nobody leaves the list);
* the console, which reads stored rows with no run policy, builds the same key as the engine where both can know.
"""

from __future__ import annotations

import itertools
import random
from types import SimpleNamespace
from typing import Any

import pytest
from matching.decision import Policy, rank_key, status_of
from tb_common.rank_key import (
    SITE_GAP,
    TIER_RANK,
    WEIGHT_NOTE,
    WEIGHT_SITE,
    WEIGHT_VALUE,
    coded_counts,
    open_weight,
    stored_rank_key,
)
from tb_common.reasons import CODES
from tb_common.verdict_word import shown_of
from tb_contracts import CriterionVerdict, Evidence

pytestmark = pytest.mark.nodb

T = 0.75
CRITERIA = {
    c.id: c
    for c in (
        SimpleNamespace(id="S-INC", kind="inclusion", class_="structured", action="", text="", human_question=None),
        SimpleNamespace(id="S-EXC", kind="exclusion", class_="structured", action="", text="", human_question=None),
        SimpleNamespace(
            id="N-INC", kind="inclusion", class_="note", action="", text="Gout flare noted", human_question=None
        ),
        SimpleNamespace(
            id="N-EXC", kind="exclusion", class_="note", action="", text="Abscess noted", human_question=None
        ),
        SimpleNamespace(id="H-INC", kind="inclusion", class_="human", action="", text="", human_question=None),
    )
}
CLASSES = {cid: c.class_ for cid, c in CRITERIA.items()}
QUOTE = "Gouty flare of the right knee, March."
ABSCESS = "Skin abscess on the left forearm, drained today."


def _v(cid: str, verdict: str, *, reason: str | None = None, quote: str | None = None, conf: float | None = None,
       basis: Any = None, affirmed: bool | None = None) -> CriterionVerdict:  # fmt: skip
    return CriterionVerdict(id=cid, verdict=verdict, basis=basis, affirmed=affirmed,  # type: ignore[arg-type]
                            evidence=Evidence(resource_refs=[], reason=reason, quote=quote, confidence=conf))  # fmt: skip


#: the states of each criterion: (name, verdict). Each state is one the engine can give; the open ones say why
STATES: dict[str, list[tuple[str, CriterionVerdict]]] = {
    "S-INC": [
        ("pass", _v("S-INC", "pass", reason="coded", basis="coded")),
        ("fail", _v("S-INC", "fail", reason="coded", basis="coded")),
        ("gap", _v("S-INC", "unknown", reason="data_gap")),
        ("nokind", _v("S-INC", "unknown", reason="no_record_of_kind")),
    ],
    "S-EXC": [
        ("pass", _v("S-EXC", "pass", reason="coded", basis="coded")),
        ("fail", _v("S-EXC", "fail", reason="coded", basis="coded")),
        ("gap", _v("S-EXC", "unknown", reason="data_gap")),
        ("nokind", _v("S-EXC", "unknown", reason="no_record_of_kind")),
    ],
    "N-INC": [
        ("pass_q", _v("N-INC", "pass", reason="note", quote=QUOTE, conf=0.9, basis="pair")),
        ("pass_noq", _v("N-INC", "pass", reason="note", conf=0.9, basis="pair")),
        ("not_met", _v("N-INC", "fail", reason="note", quote=QUOTE, conf=0.9, basis="pair", affirmed=True)),
        ("no_notes", _v("N-INC", "unknown", reason="no_notes")),
        ("not_mentioned", _v("N-INC", "unknown", reason="not_mentioned")),
    ],
    "N-EXC": [
        ("pass_q", _v("N-EXC", "pass", reason="note", quote="No skin lesion noted.", conf=0.9, basis="pair")),
        ("present_pair", _v("N-EXC", "fail", reason="note", quote=ABSCESS, conf=0.9, basis="pair", affirmed=True)),
        (
            "present_single",
            _v("N-EXC", "fail", reason="single_model", quote=ABSCESS, conf=0.9, basis="single", affirmed=True),
        ),
        ("no_notes", _v("N-EXC", "unknown", reason="no_notes")),
        ("not_mentioned", _v("N-EXC", "unknown", reason="not_mentioned")),
    ],
    "H-INC": [
        ("person", _v("H-INC", "pending_human", reason="human", basis="person")),
        ("decided", _v("H-INC", "pass", reason="human", basis="person")),
    ],
}
COMBOS = list(itertools.product(*(range(len(STATES[c])) for c in CRITERIA)))
POLICIES = (Policy(T, True), Policy(T, False))


def patient(combo: tuple[int, ...]) -> list[CriterionVerdict]:
    return [STATES[cid][i][1] for cid, i in zip(CRITERIA, combo, strict=True)]


def key(vs: list[CriterionVerdict], policy: Policy, appt: str | None = None, pid: str = "p") -> tuple[Any, ...]:
    return rank_key(CRITERIA, vs, policy, appt, pid)


def met(c: Any) -> CriterionVerdict:
    """The verdict that makes a criterion answer ``yes``: what the engine gives once the gap is closed."""
    if c.class_ == "human":
        return _v(c.id, "pass", reason="human", basis="person")
    if c.class_ == "note":
        return _v(c.id, "pass", reason="note", quote=QUOTE, conf=0.9, basis="pair")
    return _v(c.id, "pass", reason="coded", basis="coded")


def open_ids(vs: list[CriterionVerdict], policy: Policy) -> list[str]:
    from matching.decision import answer_of

    return [v.id for v in vs if answer_of(CRITERIA[v.id], v, policy) == "unknown"]


def test_the_domain_is_the_one_the_properties_claim() -> None:
    assert len(COMBOS) == 4 * 4 * 5 * 5 * 2 == 800


@pytest.mark.parametrize("policy", POLICIES, ids=("notes-may-exclude", "notes-held"))
def test_turning_an_open_criterion_into_met_raises_the_patient(policy: Policy) -> None:
    n = 0
    for combo in COMBOS:
        vs = patient(combo)
        before = key(vs, policy)
        for cid in open_ids(vs, policy):
            after = key([met(CRITERIA[v.id]) if v.id == cid else v for v in vs], policy)
            assert after < before, (combo, cid, before, after)  # smaller is nearer; never equal, never larger
            n += 1
    assert n > 1000


@pytest.mark.parametrize("policy", POLICIES, ids=("notes-may-exclude", "notes-held"))
@pytest.mark.parametrize("reason", sorted(CODES))
def test_adding_an_unknown_never_raises_a_patient(policy: Policy, reason: str) -> None:
    extra = SimpleNamespace(id="X-INC", kind="inclusion", class_="structured", action="", text="", human_question=None)
    by_id = {**CRITERIA, "X-INC": extra}
    for combo in COMBOS[::7]:
        vs = patient(combo)
        before = rank_key(CRITERIA, vs, policy, None, "p")
        after = rank_key(by_id, [*vs, _v("X-INC", "unknown", reason=reason)], policy, None, "p")
        assert after >= before, (combo, reason, before, after)


def test_an_unknown_with_a_quote_adds_nothing_to_the_evidence_count() -> None:
    seen = 0
    for policy in POLICIES:
        for combo in COMBOS:
            if STATES["N-INC"][combo[2]][1].verdict != "unknown":
                continue
            vs = patient(combo)
            quoted = [_v("N-INC", "unknown", reason="not_mentioned", quote=QUOTE) if v.id == "N-INC" else v for v in vs]
            plain = [_v("N-INC", "unknown", reason="not_mentioned") if v.id == "N-INC" else v for v in vs]
            assert key(quoted, policy) == key(plain, policy), combo  # an unknown carries nothing, a quote or not
            seen += 1
    assert seen > 100


@pytest.mark.parametrize("policy", POLICIES, ids=("notes-may-exclude", "notes-held"))
def test_a_coded_no_sends_the_patient_to_the_excluded_block(policy: Policy) -> None:
    keys = []
    for combo in COMBOS:
        vs = patient(combo)
        k = key(vs, policy)
        coded_no = any(v.verdict == "fail" and v.id.startswith("S-") for v in vs)
        if coded_no:
            assert k[0] == TIER_RANK["excluded"], combo
        keys.append((k, coded_no))
    last = min(k for k, no in keys if no)
    # whatever else they hold, no patient without an answer "no" sorts after a patient with a coded "no"
    assert all(k < last for k, no in keys if not no and k[0] < TIER_RANK["excluded"])


def test_a_note_answer_never_excludes_alone_and_never_when_notes_are_held() -> None:
    for combo in COMBOS:
        vs = patient(combo)
        if any(v.verdict == "fail" and v.id.startswith("S-") for v in vs):
            continue  # a coded no is a different property
        assert key(vs, Policy(T, False))[0] != TIER_RANK["excluded"], combo  # notes held: nothing excludes
        if key(vs, Policy(T, True))[0] == TIER_RANK["excluded"]:  # the only way: a pair's quoted, affirmed "present"
            assert STATES["N-EXC"][combo[3]][0] == "present_pair", combo


@pytest.mark.parametrize("policy", POLICIES, ids=("notes-may-exclude", "notes-held"))
def test_the_tier_in_the_key_is_status_ofs_own(policy: Policy) -> None:
    for combo in COMBOS:
        vs = patient(combo)
        st = status_of(CRITERIA, vs, policy)
        k = key(vs, policy)
        assert k[0] == TIER_RANK[st.tier], combo
        assert k[1] >= st.n_unknown  # every unknown verdict is open, and a weak note answer is open too
        if st.tier == "high":
            assert all(CRITERIA[i].class_ == "human" for i in open_ids(vs, policy)), combo  # only a person's are open


def test_the_key_is_a_pure_function_of_the_rows() -> None:
    rnd = random.Random(2026_11_27)
    for policy in POLICIES:
        for combo in COMBOS:
            vs = patient(combo)
            first = key(vs, policy, "2026-10-07 09:30", "pid-1")
            assert repr(key(vs, policy, "2026-10-07 09:30", "pid-1")) == repr(first)  # byte-identical on a re-run
            shuffled = vs[:]
            rnd.shuffle(shuffled)
            assert key(shuffled, policy, "2026-10-07 09:30", "pid-1") == first


def test_a_sorted_list_holds_everyone_once_in_one_order() -> None:
    policy = POLICIES[0]
    rows = [
        (f"{i:04d}", patient(c), None if i % 3 == 0 else f"2026-10-{1 + i % 28:02d} 09:00")
        for i, c in enumerate(COMBOS)
    ]
    keyed = [(key(vs, policy, appt, pid), pid) for pid, vs, appt in rows]
    ordered = sorted(keyed)
    assert sorted(p for _k, p in ordered) == sorted(p for p, _v, _a in rows)  # a permutation: nobody dropped
    assert len({k for k, _p in keyed}) == len(keyed)  # the pseudonym makes the order total
    assert [k for k, _p in ordered] == sorted(k for k, _p in keyed)
    # reading the list from the other end of the input gives the same order
    assert [p for _k, p in sorted(reversed(keyed))] == [p for _k, p in ordered]
    # the excluded block is last and still holds its patients
    tiers = [k[0] for k, _p in ordered]
    assert tiers == sorted(tiers) and tiers[-1] == TIER_RANK["excluded"]


def test_the_visit_and_the_pseudonym_only_break_ties() -> None:
    vs = patient(COMBOS[0])
    p = POLICIES[0]
    assert key(vs, p, "2026-10-06 09:00", "b") < key(vs, p, "2026-10-07 09:00", "a")  # the earlier visit first
    assert key(vs, p, "2026-10-07 09:00", "a") < key(vs, p, None, "a")  # no visit last
    assert key(vs, p, None, "a") < key(vs, p, None, "b")
    # and they never outweigh a criterion: the nearer patient is first however late their visit or pseudonym
    nearer = [met(c) for c in CRITERIA.values()]
    assert key(nearer, p, "2027-01-01 00:00", "z") < key(vs, p, "2026-01-01 00:00", "a")


def test_an_open_criterion_weighs_by_how_hard_it_is_to_close() -> None:
    assert open_weight("structured", "data_gap") == WEIGHT_VALUE
    assert open_weight("human", "human") == WEIGHT_VALUE
    assert open_weight("note", "not_mentioned") == WEIGHT_NOTE
    assert open_weight("mixed", None) == WEIGHT_NOTE
    for reason in SITE_GAP:
        assert open_weight("structured", reason) == WEIGHT_SITE == open_weight("note", reason)
    assert SITE_GAP <= CODES and {"no_notes", "code_system_not_carried"} <= SITE_GAP
    assert WEIGHT_VALUE < WEIGHT_NOTE < WEIGHT_SITE


def test_two_equal_gaps_rank_the_nearer_one_first() -> None:
    """Both have one open criterion; the one a pending value will close ranks above the one the site cannot answer."""
    p = POLICIES[0]
    base = [met(c) for c in CRITERIA.values()]
    pending = [_v("S-INC", "unknown", reason="data_gap") if v.id == "S-INC" else v for v in base]
    gap = [_v("S-INC", "unknown", reason="no_record_of_kind") if v.id == "S-INC" else v for v in base]
    assert key(pending, p, None, "z") < key(gap, p, None, "a")


def test_more_evidence_in_favour_ranks_above_less_when_all_else_is_equal() -> None:
    p = POLICIES[0]
    other = [met(c) for c in CRITERIA.values() if c.id != "N-INC"]
    with_quote = [*other, _v("N-INC", "pass", reason="note", quote=QUOTE, conf=0.9, basis="pair")]
    without = [*other, _v("N-INC", "pass", reason="note", conf=0.9, basis="pair")]
    assert key(with_quote, p, None, "z") < key(without, p, None, "a")


# ---------------------------------------------------------------------------------------------- the console's reading
def dump(vs: list[CriterionVerdict]) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in vs]


def test_the_console_builds_the_same_key_where_the_engine_and_the_page_read_alike() -> None:
    """The page has no run policy: it reads each verdict's own word, a one-model "not met" as open (``shown_of``). It
    agrees with the engine on every patient whose answers are not weak (a note "met" under the confidence threshold is
    open for the engine and met on the page, so the page ranks that patient one open criterion nearer; the stored tier
    is the engine's own either way)."""
    policy = POLICIES[0]
    same = 0
    for combo in COMBOS:
        vs = patient(combo)
        tier = status_of(CRITERIA, vs, policy).tier
        engine = rank_key(CRITERIA, vs, policy, "2026-10-07 09:30", "p")
        page = stored_rank_key(tier, dump(vs), CLASSES, "2026-10-07 09:30", "p")
        assert page[0] == engine[0], combo
        # the held-back note "not met" and the inclusion "not met" are open for the engine and open (held) or met-word
        # on the page: compare whole keys where the engine's open set equals the page's open set
        page_open = [v["id"] for v in dump(vs) if shown_of(v)[0] in ("unknown", "pending_human")]
        if sorted(page_open) == sorted(open_ids(vs, policy)):
            assert page == engine, combo
            same += 1
    assert same > 200


def test_the_coded_complete_count_is_a_count_of_the_records_answers() -> None:
    def vs(*words: str) -> list[dict[str, Any]]:
        return [{"id": f"S{i}", "verdict": w, "evidence": {}} for i, w in enumerate(words)]

    classes = {f"S{i}": "structured" for i in range(5)} | {"N0": "note", "H0": "human"}
    assert coded_counts(vs("pass", "fail", "unknown"), classes) == (2, 3)
    assert coded_counts(
        [*vs("pass"), {"id": "N0", "verdict": "pass"}, {"id": "H0", "verdict": "pending_human"}], classes
    ) == (1, 1)
    assert coded_counts([], classes) == (0, 0)
    assert coded_counts(vs("unknown", "unknown"), classes) == (0, 2)  # no answer yet, and it is not a tier
