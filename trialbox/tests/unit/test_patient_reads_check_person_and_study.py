"""NEW-SEC-1 (D-717): every route of the orchestrator that returns a patient's row checks the verified person and
the study.

The deep review of 2026-11-13 (SEC-07): the patient-level reads of the data core (``GET /studies/{rs}/data``,
``/records``, ``/export``, ``/fhir``) carried no person or study check at the orchestrator; any admitted token read
every record of any study. The same was so of the lifecycle's, the set-up's, the registry's, the REDCap read-back
and two of the EDC's.

Every GET route of the app is now in one of two lists (``tb_common.patient_reads``): a read that returns a
patient's row, which takes a verified v3 claim for ``phi.view`` on the route's study (``require_actor``), or a read
that returns none, with its reason (``route_actors.yaml``). A new GET route in neither list stops the service at
import and fails here. Then each patient read, on the real app in the production trust configuration: no claim,
a claim for another study, and a role without the right are refused (403, audited); a coordinator's claim passes.

Synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest
from orchestrator import actor as ra
from tb_common import patient_reads

from tests.actor3 import signed
from tests.orch_box import STUDY, OrchBox

FILL = {"{rs}": STUDY, "{ruleset}": STUDY, "{record}": "GZQO-0001", "{fmt}": "csv", "{ws}": "main"}


def _concrete(template: str) -> str:
    out = template
    for k, v in FILL.items():
        out = out.replace(k, v)
    return out


def test_every_get_route_is_a_patient_read_or_says_why_it_is_not() -> None:
    from orchestrator.app import CALLER_GATE, app

    gets = {f"GET {p}" for m, p, _, _, _ in ra.walk(app) if m == "GET"}
    reads = set(patient_reads.PATIENT_READS)
    others = set(ra.TABLE["reads_without_patient"])
    assert reads <= gets, sorted(reads - gets)
    assert others <= gets, sorted(others - gets)
    assert not reads & others, sorted(reads & others)
    assert gets == reads | others, f"a GET route in neither list: {sorted(gets - reads - others)}"
    assert all(why.strip() for why in ra.TABLE["reads_without_patient"].values())
    assert ra.route_problems(app, CALLER_GATE.table.group_of) == []


def test_each_patient_read_names_the_person_and_the_study_it_checks() -> None:
    """The walk sees ``require_actor`` with the table's action on every patient read; the study is the route's
    own ``{rs}`` or ``{ruleset}``, and a set-up route of the whole site checks a claim that names no study."""
    from orchestrator.app import app

    marked = {f"{m} {p}": (st, act) for m, p, st, act, _ in ra.walk(app)}
    for key, action in patient_reads.PATIENT_READS.items():
        assert marked[key] == ("refuse", action), (key, marked[key])
        assert "{rs}" in key or "{ruleset}" in key or key.startswith("GET /setup/{ws}/"), key


def test_the_route_problems_find_an_unlisted_get_and_a_patient_read_without_the_check() -> None:
    from fastapi import APIRouter, FastAPI

    def toy(defect: str) -> FastAPI:
        app, r = FastAPI(), APIRouter()
        if defect == "unlisted":

            @r.get("/studies/{rs}/brand-new")
            def brand_new(rs: str) -> dict[str, Any]:
                return {}
        elif defect == "unchecked":

            @r.get("/studies/{rs}/data")
            def data(rs: str) -> dict[str, Any]:
                return {}

        app.include_router(r)
        return app

    table = {**ra.TABLE, "reads_without_patient": {}}
    bad = ra.route_problems(toy("unlisted"), lambda key: "datacore", table)
    assert any("brand-new" in b and "neither" in b for b in bad), bad
    bad = ra.route_problems(toy("unchecked"), lambda key: "datacore", table)
    assert any("/studies/{rs}/data" in b and "phi.view" in b for b in bad), bad


@pytest.mark.parametrize("template", sorted(patient_reads.PATIENT_READS))
def test_a_patient_read_refuses_no_claim_another_study_and_a_role_without_the_right(
    orch_box: OrchBox, template: str
) -> None:
    path = _concrete(template.split(" ", 1)[1])
    study = "" if path.startswith("/setup/") else STUDY
    c = orch_box.client("console")
    cases = {
        "no claim": {},
        "another study": signed("phi.view", "OTHER1" if study else STUDY, "GET", path),
        "a role without the right": signed("phi.view", study, "GET", path, sub="console:viewer1", role="viewer"),
        "another action": signed("study.setup", study, "GET", path),
    }
    for why, headers in cases.items():
        r = c.get(path, headers=headers)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "ACTOR", (why, r.status_code, r.text[:200])
    refused = [e for e in orch_box.events("actor.refused") if e["detail"]["route"] == template]
    assert len(refused) == len(cases), refused
    r = c.get(path, headers=signed("phi.view", study, "GET", path, sub="console:crc", role="coordinator"))
    assert r.status_code != 403, (r.status_code, r.text[:300])


def test_the_operator_and_mail_tokens_still_read_jobs_which_hold_no_patient_row(orch_box: OrchBox) -> None:
    job = orch_box.screen()
    assert orch_box.client("operator").get(f"/jobs/{job.job_id}").status_code == 200
    assert "GET /jobs/{job_id}" in ra.TABLE["reads_without_patient"]


#: the reads the morning mail makes (the review of D-717: the timer's principal reads these and nothing else)
NOTIFY_READS = {
    "GET /studies/{rs}/visits",
    "GET /studies/{rs}/aes",
    "GET /studies/{rs}/subjects",
    "GET /studies/{rs}/subjects/{record}",
    "GET /registry/{ruleset}",
}


@pytest.mark.parametrize("template", sorted(patient_reads.PATIENT_READS))
def test_the_mail_principal_reads_only_what_the_morning_mail_needs(orch_box: OrchBox, template: str) -> None:
    path = _concrete(template.split(" ", 1)[1])
    study = "" if path.startswith("/setup/") else STUDY
    action = patient_reads.actions(template)[0]
    headers = signed(action, study, "GET", path, sub="service:console-notify", role="service")
    r = orch_box.client("console").get(path, headers=headers)
    if template in NOTIFY_READS:
        assert r.status_code != 403, (r.status_code, r.text[:300])
    else:  # the export, FHIR, the whole site's set-up, the REDCap read-back: never the timer's
        assert r.status_code == 403 and r.json()["detail"]["code"] == "ACTOR", (r.status_code, r.text[:200])
