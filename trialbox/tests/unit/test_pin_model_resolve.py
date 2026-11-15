"""PIN-RESOLVE (D-738), lane G's blocker 6: nothing said which build PRODUCTION routes each role to.

``pin_model --resolve`` walks the gateway's own path for each role and data class on PRODUCTION: the route the
routing table picks for the box's topology and profile (``gateway.policy.RoutingPolicy.candidates``, its no-fallback
rule included), then the registry's resolution of each candidate in order (``Registry.resolve``, with the site's
pins). Each line names the build, its alias, endpoint and served name, or the registry's refusal codes. ``--require``
makes a role that does not route on D3 an exit 1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gateway.policy import RoutingPolicy
from registry.registry import Registry

from tools import pin_model

pytestmark = pytest.mark.nodb

SHA = "ab" * 32
ENV = {"TB_TOPOLOGY": "A", "TB_PROFILE": "P-PRO6000"}


def _build(build_id: str, alias: str, endpoint: str, served: str, *, qualified: bool = True) -> dict[str, Any]:
    b: dict[str, Any] = {"build_id": build_id, "alias": alias, "status": "champion", "serving": "vllm",
                         "context_length": 32768, "served": {endpoint: served}, "sha256": SHA,
                         "licence": {"name": "test"}, "origin": {"developer": "test"}}  # fmt: skip
    if qualified:
        b["qualification"] = {"record_id": "q-1", "sha256": "cd" * 32, "weights_sha256": SHA,
                              "qualifies_production": True}  # fmt: skip
    return b


def _registry(*builds: dict[str, Any]) -> Registry:
    aliases = ("trialbox-stub", "j-workhorse", "v-verifier", "x-external", "f-frontdesk", "e-embed")
    return Registry({"version": "t", "aliases": {a: {"class": "J"} for a in aliases}, "builds": list(builds)})


JUDGE = _build("j-test-1", "j-workhorse", "serving", "local/judge")
VERIFIER = _build("v-test-1", "v-verifier", "verifier", "local/verifier")


def _row(rows: list[pin_model.RouteRow], role: str, cls: str) -> pin_model.RouteRow:
    return next(r for r in rows if r.role == role and r.data_class == cls)


def test_a_qualified_pair_routes_the_judge_to_its_build() -> None:
    rows = pin_model.resolve_roles(_registry(JUDGE, VERIFIER), RoutingPolicy.load(), ENV)
    judge = _row(rows, "judge", "D3")
    assert (judge.build, judge.alias, judge.endpoint, judge.served) == ("j-test-1", "j-workhorse", "serving",
                                                                         "local/judge")  # fmt: skip
    assert judge.route and judge.refusals == []


def test_an_unqualified_champion_is_named_with_the_registry_s_code() -> None:
    rows = pin_model.resolve_roles(_registry(_build("j-test-1", "j-workhorse", "serving", "j", qualified=False),
                                             VERIFIER), RoutingPolicy.load(), ENV)  # fmt: skip
    judge = _row(rows, "judge", "D3")
    assert judge.build is None and any("champion_unqualified" in r for r in judge.refusals)


def test_a_patient_role_never_shows_another_build_as_its_answer() -> None:
    """D-276: the judge's route has the verifier further down; the judge never falls back to it."""
    rows = pin_model.resolve_roles(_registry(VERIFIER), RoutingPolicy.load(), ENV)
    judge = _row(rows, "judge", "D3")
    assert judge.build is None and judge.alias != "v-verifier"


def test_every_role_of_the_table_is_reported_for_both_classes() -> None:
    policy = RoutingPolicy.load()
    rows = pin_model.resolve_roles(_registry(JUDGE, VERIFIER), policy, ENV)
    roles = {r.role for r in rows}
    assert {n for n in policy.roles if not n.startswith("shadow:")} <= roles
    assert {r.data_class for r in rows} == {"D1", "D3"}


def test_the_cli_prints_one_line_a_role_and_require_fails_a_role_that_does_not_route(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TB_TOPOLOGY=A\nTB_PROFILE=P-PRO6000\n", encoding="utf-8")
    missing = tmp_path / "no-override.yaml"  # no site pins: nothing local routes
    assert pin_model.main(["--resolve", "--env-file", str(env_file), "--out", str(missing)]) == 0
    out = capsys.readouterr().out
    judge = next(ln for ln in out.splitlines() if ln.startswith("judge D3 "))
    assert judge.startswith("judge D3 -> none (route ") and "j-workhorse@serving: no_eligible_build" in judge
    assert out.startswith("PRODUCTION, topology A, profile P-PRO6000")
    assert pin_model.main(["--resolve", "--env-file", str(env_file), "--out", str(missing), "--require",
                           "judge"]) == 1  # fmt: skip
