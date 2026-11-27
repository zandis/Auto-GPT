"""E2E P-12: ``/studies/{rs}/edc`` and ``/edc/drafts`` raised an unhandled ``EdcError`` (HTTP 500 with a traceback),
so the console said only "orchestrator returned 500". Every EDC route now answers the refusal's own status, code and
message, as the write routes already did."""

from __future__ import annotations

from typing import Any

import pytest
from edc.store import EdcError
from fastapi import FastAPI
from orchestrator.edc_api import router as edc_router

from tests.actor3 import SignedClient

pytestmark = pytest.mark.nodb

STUDY = "GOUT-301"


def _refusing() -> Any:
    raise EdcError("edc.sign_key", "the signature key: cannot be opened", 500)  # the installed box's refusal


@pytest.mark.parametrize(
    "path",
    [f"/studies/{STUDY}/edc", f"/studies/{STUDY}/edc/drafts", f"/studies/{STUDY}/edc/map/suggest",
     f"/studies/{STUDY}/edc/trail/R001"],
)  # fmt: skip
def test_an_edc_read_answers_its_refusal_not_a_traceback(path: str) -> None:
    api = FastAPI()
    api.include_router(edc_router(_refusing))
    r = SignedClient(api).get(path)  # an unhandled error raises here (the test client's default)
    assert r.status_code == 500
    assert r.json()["detail"] == {"code": "edc.sign_key", "message": "the signature key: cannot be opened"}
