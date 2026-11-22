"""R22-34 (D-1072; the integrator's go, comment 7079138866): the box of ``tests/orch_box.py`` runs as VALIDATION
because rc1 makes no live patient list on a PRODUCTION box. Here the same box as PRODUCTION is refused its SCREEN
list: the job fails at its first step with the table's message, and nothing is listed. Synthetic data only."""

from __future__ import annotations

import pytest
from tb_common import rc1_refusals

from tests.orch_box import STUDY, OrchBox

KEY = "rc1.live_patient_lists"


def test_the_same_box_as_production_is_refused_its_screen_list(
    orch_box: OrchBox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert orch_box.box.mail(f"SCREEN {STUDY} version=1.0.0") == "Processed"
    orch_box.box.orch.drain()
    (job,) = orch_box.box.orch.db.find(type_="SCREEN")
    assert job.state == "failed", job.state
    assert job.error is not None and job.error.step == "rc1" and job.error.detail == KEY  # the message key
    assert job.error.message == rc1_refusals.text(KEY, environment="PRODUCTION")
    assert not [o for o in job.outputs or [] if o.filename.startswith("candidate_list_")]  # nothing listed
    assert not orch_box.events("screen.done") and not orch_box.events("screen.listed")
