"""R22-34 (D-1072; the integrator's go, comment 7079138866): the box of ``tests/orch_box.py`` runs as VALIDATION
because rc1 made no live patient list on a PRODUCTION box. SAFE-1 A2 (the owner's decision of 2026-11-28) allows
lists on PRODUCTION; a box whose TB_ENV is unknown still lists nothing. Here the same box with an unknown TB_ENV is
refused its SCREEN list: the job fails at its first step with the table's message, and nothing is listed; and a
PRODUCTION box reveals a listed patient as a VALIDATION box does, with the same audit event. Synthetic data only."""

from __future__ import annotations

import pytest
from tb_common import rc1_refusals

from tests.orch_box import STUDY, OrchBox

KEY = "rc1.live_patient_lists"
REFUSED_BOX = "PILOT"  # an unknown TB_ENV (SAFE-1 A2: PRODUCTION lists)


def test_the_same_box_as_production_is_refused_its_screen_list(
    orch_box: OrchBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_ENV", REFUSED_BOX)
    assert orch_box.box.mail(f"SCREEN {STUDY} version=1.0.0") == "Processed"
    orch_box.box.orch.drain()
    (job,) = orch_box.box.orch.db.find(type_="SCREEN")
    assert job.state == "failed", job.state
    assert job.error is not None and job.error.step == "rc1"
    assert job.error.detail == f"{KEY}: an unknown TB_ENV"  # the message key and the environment
    assert job.error.message.startswith("rc1 makes and shows no live patient list on this box.")
    assert rc1_refusals.refused("live_patient_lists")
    assert not [o for o in job.outputs or [] if o.filename.startswith("candidate_list_")]  # nothing listed
    assert not orch_box.events("screen.done") and not orch_box.events("screen.listed")


def test_the_orchestrator_reveals_no_listed_patient_on_a_production_box(
    orch_box: OrchBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``orchestrator.app.reveal`` (the integrator's go, 7080612399): on a refused box a list made before is still
    named by nobody. SAFE-1 A2: a PRODUCTION box names the patient as a VALIDATION box does, audited the same way."""
    from console.backend import Refused

    from tests.actor3 import signer

    job, pid = orch_box.screen(), orch_box.listed()[0]  # the list of a VALIDATION box
    bk = orch_box.backend()
    monkeypatch.setenv("TB_ENV", REFUSED_BOX)
    with pytest.raises(Refused, match=KEY):
        bk.reveal(job.job_id, pid, signer(STUDY))
    assert not orch_box.events("screen.reveal")  # nobody named
    (ev,) = orch_box.events("screen.reveal_refused")
    assert ev["detail"] == {"pid": pid, "reason": "rc1", "environment": REFUSED_BOX} and ev["job_id"] == job.job_id
    monkeypatch.setenv("TB_ENV", "VALIDATION")
    assert bk.reveal(job.job_id, pid, signer(STUDY)) == orch_box.mrn[pid]  # the same box allowed
    validation = orch_box.events("screen.reveal")
    assert len(validation) == 1
    monkeypatch.setenv("TB_ENV", "PRODUCTION")  # SAFE-1 A2
    assert bk.reveal(job.job_id, pid, signer(STUDY)) == orch_box.mrn[pid]
    production = orch_box.events("screen.reveal")
    assert len(production) == 2 and production[1]["detail"] == validation[0]["detail"]  # the same audit record


def test_the_orchestrator_exports_no_registry_with_chart_numbers_on_a_production_box(
    orch_box: OrchBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``orchestrator.app.registry_export``: no file of chart numbers leaves a PRODUCTION box."""
    from console.backend import Refused

    bk = orch_box.backend()
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    with pytest.raises(Refused, match="rc1.patient_mail_and_downloads"):
        bk.registry_export(STUDY, "console:crc")
    assert not orch_box.events("registry.export")  # nothing exported
    (ev,) = orch_box.events("registry.export_refused")
    assert ev["detail"] == {"reason": "rc1", "environment": "PRODUCTION"} and ev["ruleset"] == STUDY
