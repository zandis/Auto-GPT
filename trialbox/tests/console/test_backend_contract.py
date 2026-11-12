"""T-714 (D-482; plan v6.1 §5.3 "fakes are made from the real thing"): ``FakeBackend`` against the real routes.

Most console tests run on ``FakeBackend`` (``tests/console/test_console_app.py``). For reveal, export and jobs it
now refuses by the orchestrator's own rule functions. This test holds its answers against the real orchestrator on
a box (``tests/orch_box.py``) for every signed role and study scope of the table below: the same call is given the
same answer, a value or the same refusal, by both. What the fake does not model is ``NOT_MODELLED``, each line with
the test that covers the real behaviour.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import pytest
from console.backend import HttpBackend, Refused
from tb_common.authz import BREAK_GLASS_ROLE, MATRIX_ROLES
from tb_contracts import JobCreate

from tests.actor3 import log_pi, signer
from tests.console.test_console_app import FakeBackend, _done_screen, _ulid
from tests.orch_box import STUDY, OrchBox

SIGNED_ROLES = (*sorted(MATRIX_ROLES), BREAK_GLASS_ROLE, "", "nobody")
SCOPES = ("*", STUDY, f"OTHER,{STUDY}", "OTHER", "")
JOB_TYPES = ("FEAS", "SCREEN", "MICROBATCH", "NAV", "CASE", "COHORT", "CONSENT", "INGEST", "RETENTION")
#: what the fake does not model, and where the real behaviour is tested
NOT_MODELLED = {
    "a break-glass grant row (the fake reads the real store; tested on the box)": "test_grant_box.py",
    "a patient the job did not list (403)": "test_orch_box.py::test_the_orchestrator_refuses_what_the_console_did_not_check",
    "a patient who opted out since (403)": "test_orch_box.py::test_the_orchestrator_refuses_what_the_console_did_not_check",
    "the hourly caps per person and per service (429)": "tests/unit/test_d273_orchestrator_guards.py",
    "a job with no signed role: the mailbox rules of the settings": "test_orch_box.py::test_a_console_job_is_authorised_by_the_signed_role",
    "the daily limit of heavy job types": "tests/unit (Orchestrator.create)",
    "an assertion that does not verify, a foreign service token": "test_orch_box.py::test_the_box_is_the_production_configuration",
}


def _answer(call: Any) -> str:
    """ "ok" for a value, else the refusal's reason as both sides word it."""
    try:
        got = call()
    except Refused as exc:
        text = str(exc)
        for why in ("role may not run", "break-glass grant", "study scope", "delegation", "right", "role"):
            if why in text:
                return f"refused: {why}"
        return f"refused: {text[:80]}"
    return "ok" if got else "nothing"


def test_reveal_and_export_answer_as_the_real_routes(orch_box: OrchBox) -> None:
    real, fake = orch_box.backend(), FakeBackend()
    real_job, real_pid = orch_box.screen(), orch_box.listed()[0]
    fake_job, fake_pid = _done_screen(fake, _ulid(714)), "a" * 32
    log_pi("named", STUDY)  # the delegation log both sides read (one trial database): its PI, and nobody else
    differ: list[str] = []
    seen: set[str] = set()
    n = 0
    # the reveal (T-716, D-484): a v3 claim; the role, the one study, the person the log names or does not
    for role in (r for r in SIGNED_ROLES if r):  # a claim cannot be minted without a role
        for study in (STUDY, "OTHER", ""):
            for person in ("named", "other"):
                n += 1
                sign = partial(signer, study, sub=f"console:{person}", role=role)  # a person per case: not the cap
                a = _answer(partial(real.reveal, real_job.job_id, real_pid, sign()))
                b = _answer(partial(fake.reveal, fake_job.job_id, fake_pid, sign()))
                seen.add(a)
                if a != b:
                    differ.append(f"reveal role={role!r} study={study!r} {person}: real {a}, fake {b}")
    # the whole-list export: the older assertion (a role and a study list)
    for role, scope in ((r, s) for r in SIGNED_ROLES for s in SCOPES):
        n += 1
        who = f"console:p{n}"
        a = _answer(partial(real.registry_export, STUDY, who, role=role, scope=scope))
        b = _answer(partial(fake.registry_export, STUDY, who, role=role, scope=scope))
        seen.add(a)
        if a != b:
            differ.append(f"export role={role!r} scope={scope!r}: real {a}, fake {b}")
    assert differ == []
    # the table reaches every answer, so an agreement is not an agreement on refusals only
    assert seen == {"ok", "refused: right", "refused: role", "refused: study scope", "refused: delegation"}


def test_a_signed_job_is_answered_as_the_real_route(orch_box: OrchBox) -> None:
    """Refusals only are compared on the real side without running anything: the job is queued, never drained."""
    real, fake = orch_box.backend(), FakeBackend()
    differ: list[str] = []
    seen: set[str] = set()
    for role in (r for r in SIGNED_ROLES if r):  # no role is the mailbox path (NOT_MODELLED)
        for jtype in JOB_TYPES:
            req = JobCreate(type=jtype, ruleset=STUDY, requested_by=f"{role}@hospa.test", options={})  # type: ignore[arg-type]
            a = _answer(partial(HttpBackend.create_job, real, req, by=f"console:{role}", role=role))
            b = _answer(partial(fake.create_job, req, by=f"console:{role}", role=role))
            seen.add(a)
            if a != b:
                differ.append(f"{jtype} role={role!r}: real {a}, fake {b}")
    assert differ == []
    assert seen == {"ok", "refused: role may not run"}


def test_the_fake_cannot_be_asked_without_a_role_or_scope() -> None:
    """The acceptance of the card on the fake as well: a console call that drops ``scope=`` or ``role=`` is refused,
    so the many console tests that run on the fake fail too."""
    fake = FakeBackend()
    job = _done_screen(fake, _ulid(715))
    with pytest.raises(Refused, match="study scope"):
        fake.reveal(job.job_id, "a" * 32, signer(""))  # the study dropped from the claim
    with pytest.raises(Refused, match="right"):
        fake.reveal(job.job_id, "a" * 32, signer("GZQO", role="viewer"))
    with pytest.raises(Refused, match="request"):
        fake.reveal(job.job_id, "a" * 32, lambda m, p, b: signer("GZQO")(m, p, {"pid": "b" * 32}))  # another body
    with pytest.raises(Refused, match="study scope"):
        fake.registry_export("GZQO", "console:crc", role="coordinator")
    assert fake.revealed == [] and len(fake.signed) == 4
    assert fake.reveal(job.job_id, "a" * 32, signer("GZQO")) == "MRN-000123"
    assert len(NOT_MODELLED) == 7
