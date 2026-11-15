"""T-315a (D-448): the journeys of ``journeys.yaml`` as the PQ script, walked on the in-process box.

One journey per console role on the synthetic Taiwan site, each a readable list of steps with the expected result of
each step; the walk runs every step in the file's ``walk`` order and checks what the step expects. A step whose
feature is not on master yet is an expected failure naming the card that delivers it: it must fail, and when it
passes the walk fails until that card removes the mark (never a silent skip). ``rerun_after_break.yaml`` is the list
of journeys a site re-runs after a long break (RSK-64).

No docker, no network, stub model: the walk runs in the ``unit`` job. It builds one site (about two to three minutes
on a CI runner) and walks it in one test, as the PoC scripts' walk does (T-508)."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
PLAN = ROOT / "docs" / "plan" / "28-master-plan-v6.md"
STEP_ID = re.compile(r"^(J-[A-Z]{2,3})-(\d{2})$")
CARD = re.compile(r"^T-\d{3}[a-z]?$")
LANGS = {"en", "ja", "zh-TW"}
#: NEW-JRN-20 (D-773): what a site does once in a study's life; a step that covers one is never in the re-run list
ONCE = {"new_account", "sae", "deviation", "edc_sign_send", "monitor_visit", "study_close", "visits"}
#: and NEW-JRN-1's (D-540) new study, its PI named and its first approval and list: done once
ONCE_STEPS = {"J-ADM-05", "J-STW-05", "J-PI-08", "J-CRC-08"}


def journeys() -> dict[str, Any]:
    data = yaml.safe_load((HERE / "journeys.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def all_steps(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {st["id"]: st for j in data["journeys"] for st in j["steps"]}


# ---------------------------------------------------------------------------------------------------- the file
def test_each_journey_is_a_numbered_list_of_steps_with_expected_results() -> None:
    data = journeys()
    topics = set(data["topics"])
    seen: set[str] = set()
    for j in data["journeys"]:
        assert re.fullmatch(r"J-[A-Z]{2,3}", j["id"]) and j["id"] not in seen, j["id"]
        seen.add(j["id"])
        assert j["role"] and j["who"] and j["steps"], j["id"]
        for n, st in enumerate(j["steps"], 1):
            assert st["id"] == f"{j['id']}-{n:02d}", (j["id"], st["id"])
            assert str(st.get("do") or "").strip() and str(st.get("expect") or "").strip(), st["id"]
            assert set(st.get("covers") or []) <= topics, st["id"]
            assert set(st.get("langs") or []) <= LANGS, st["id"]
            assert set(st) <= {"id", "do", "expect", "covers", "langs", "expected_failure"}, st["id"]


def test_the_journeys_cover_every_role_and_every_topic_of_the_card() -> None:
    data = journeys()
    roles = {j["role"] for j in data["journeys"]}
    matrix = yaml.safe_load((ROOT / "libs" / "tb_common" / "authz_matrix.yaml").read_text(encoding="utf-8"))
    assert set(matrix["roles"]) <= roles, set(matrix["roles"]) - roles
    covered = {t for st in all_steps(data).values() for t in st.get("covers") or []}
    assert covered == set(data["topics"]), set(data["topics"]) - covered
    # every role signs in with the second factor in its own journey; the language-sensitive steps run in three
    for j in data["journeys"]:
        assert "sign_in_2fa" in (j["steps"][0].get("covers") or []), j["id"]
    assert any(set(st.get("langs") or []) == LANGS for st in all_steps(data).values())


def test_the_walk_holds_every_step_once_in_journey_order() -> None:
    data = journeys()
    steps = all_steps(data)
    walk = data["walk"]
    assert sorted(walk) == sorted(steps), (set(steps) - set(walk), set(walk) - set(steps))
    for j in data["journeys"]:
        mine = [x for x in walk if x.startswith(j["id"] + "-")]
        assert mine == [st["id"] for st in j["steps"]], j["id"]


def test_every_step_has_its_walk_and_every_walk_its_step() -> None:
    from tests.e2e.journeys.steps import STEPS

    steps = all_steps(journeys())
    assert set(STEPS) == set(steps), (set(steps) - set(STEPS), set(STEPS) - set(steps))


def test_an_expected_failure_names_a_card_of_the_plan_and_why() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    marked = [st for st in all_steps(journeys()).values() if "expected_failure" in st]
    assert marked, "no expected failure: remove this test's last line when every feature is on master"
    for st in marked:
        ef = st["expected_failure"]
        assert set(ef) == {"card", "why"} and CARD.fullmatch(ef["card"]), st["id"]
        assert f"| **{ef['card']}** |" in plan, (st["id"], ef["card"])
        assert len(str(ef["why"]).strip()) > 20, st["id"]


def test_the_rerun_list_after_a_long_break_names_only_existing_journeys() -> None:
    data = journeys()
    ids = {j["id"] for j in data["journeys"]}
    steps = all_steps(data)
    rerun = yaml.safe_load((HERE / "rerun_after_break.yaml").read_text(encoding="utf-8"))
    assert rerun["version"] == 1 and rerun["after"]
    names: list[str] = []
    for row in rerun["rerun"]:
        assert set(row) in ({"journey", "why"}, {"step", "why"}), row
        assert str(row["why"]).strip(), row
        name = row.get("journey") or row.get("step")
        assert (name in ids) if "journey" in row else (name in steps), name
        names.append(name)
    assert len(names) == len(set(names)), names
    assert "J-ADM-02" in names, "the held nights of the break are read before any list (J-ADM-02)"
    # NEW-JRN-20 (D-773): a step done once in a study's life is never re-run, as a step or inside a journey
    once = {sid for sid, st in steps.items() if set(st.get("covers") or []) & ONCE}
    once |= ONCE_STEPS
    rerun_steps = {x for n in names for x in ([n] if n in steps else [s for s in steps if s.startswith(n + "-")])}
    assert not rerun_steps & once, sorted(rerun_steps & once)


# ---------------------------------------------------------------------------------------------------- the walk
def test_the_journeys_walk_on_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.e2e.journeys import journey_site
    from tests.e2e.journeys.steps import STEPS

    data = journeys()
    steps = all_steps(data)
    t0 = time.monotonic()
    s = journey_site.build(tmp_path, monkeypatch)
    took = {"build": time.monotonic() - t0}
    failed_as_expected: list[str] = []
    why: dict[str, str] = {}
    for sid in data["walk"]:
        st = {"langs": [], **steps[sid]}
        t1 = time.monotonic()
        ef = st.get("expected_failure")
        if ef is None:
            STEPS[sid](s, st)
        else:
            try:
                STEPS[sid](s, st)
            except AssertionError as exc:
                failed_as_expected.append(sid)
                why[sid] = f"{ef['card']}: {str(exc)[:120]}"
            else:
                pytest.fail(f"{sid} passed: card {ef['card']} delivered it; remove its expected_failure lines")
        took[sid] = time.monotonic() - t1
    assert failed_as_expected == [x for x in data["walk"] if "expected_failure" in steps[x]]
    print("journey timings (s):", {k: round(v, 1) for k, v in took.items()})
    print("expected failures:", why)
