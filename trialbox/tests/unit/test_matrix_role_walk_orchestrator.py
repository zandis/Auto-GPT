"""Card V-2 (plan 8 activity V8): every ``require_actor`` route of the orchestrator, as every role, against the matrix.

``tests/unit/test_actor_routes.py`` holds that each such route refuses an unsigned call and a viewer. This walk asks
each route for each action it names, as each role with its standing in the study (on no log, the log's PI, a
sub-investigator, a monitor grant), and compares the dependency's answer with ``permit`` both ways. Every refusal
must be an ``actor.refused`` record. The real app in the production trust configuration, on the stand-in of
``test_actor_routes`` (a call past the dependency fails at the stand-in, which is not a refusal).

Then a sample of forged and stale assertions on one route of each router: each must be refused and recorded."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import actor_v3 as v3
from tb_common import service_auth as sa

from tests.actor3 import signed
from tests.service_tokens import per_service_tokens, token_of
from tools import role_walk as rw

#: V2-01: cells where the route refuses what the row it declares allows, by a second check in the handler. Both are
#: recorded rulings (D-871: the cancel also asks ``ops.view``; D-864: the instrument switches are the
#: administrator's, "no new matrix row"); plan 8 V8 asks for the matrix's answer, so they are listed.
SECOND_CHECK: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("POST", "/jobs/{job_id}/cancel", "request.prepare"): ("crc", "smo_in"),
    ("PUT", "/setup/instruments/{iid}", "site.setup"): ("crc", "smo_in"),
}


@pytest.fixture
def orch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, TestClient, list[dict[str, Any]]]:
    from orchestrator import app as oapp

    per_service_tokens(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    events: list[dict[str, Any]] = []
    audit = SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw}))
    monkeypatch.setattr(oapp, "orch", lambda: SimpleNamespace(audit=audit))
    client = TestClient(oapp.app, headers={sa.TOKEN_HEADER: token_of("console")}, raise_server_exceptions=False)
    return oapp.app, client, events


def test_every_orchestrator_route_answers_every_role_as_the_matrix_says(orch: Any) -> None:
    app, client, events = orch
    rows = rw.orchestrator_walk(app, client, events, signed)
    rw.save_fragment("orchestrator", rows)
    assert len(rows) >= 60
    against = {(r["method"], r["path"], r["action"], n): c["verdict"] for r in rows for n, c in r["cells"].items()
               if c["verdict"] not in ("allowed", "refused")}  # fmt: skip
    known = {(m, p, a, n) for (m, p, a), cols in SECOND_CHECK.items() for n in cols}
    assert set(against) == known, sorted(set(against) ^ known)
    assert all(v == "REFUSED-BUT-MATRIX-ALLOWS" for v in against.values())
    unaudited = [(r["path"], n) for r in rows for n, c in r["cells"].items() if c["got"] == "R" and not c["audited"]]
    assert unaudited == []


class RoleWalkFinding(AssertionError):
    """Raised only by the check a strict xfail names: a fixture error can never satisfy the mark."""


@pytest.mark.parametrize("key", sorted(SECOND_CHECK))
@pytest.mark.xfail(strict=True, raises=RoleWalkFinding,
                   reason="V2-01: ruled by D-871 and D-864; two routes refuse a coordinator the row they declare allows")  # fmt: skip
def test_v2_01_a_route_answers_as_the_row_it_declares(orch: Any, key: tuple[str, str, str]) -> None:
    """D-871 and D-864 record why; the matrix has no row that says so (the guides are frozen)."""
    _, client, _ = orch
    method, template, action = key
    path = rw.orch_fill(template)
    body = rw.orch_body(template)
    st = rw.standing(rw.BY_NAME["crc"])
    r = client.request(method, path, json=body, headers=signed(action, "", method, path, body, role="coordinator",
                                                               standing=st, sub="console:walk-crc"))  # fmt: skip
    if rw._reason(r) == "right":
        raise RoleWalkFinding(f"{method} {template}: the coordinator is refused ({r.status_code})")


def _edc_read_as(tmp_path: Path, step: str, logged_pi: bool) -> Any:
    """GET the copy sheet or the ODM export as the investigator ``drpi``, with or without a delegation log that
    names them PI of the study (V2-05, D-1480: the router reads the log)."""
    from console.teamstore import TeamStore
    from fastapi import FastAPI
    from orchestrator.edc_api import router
    from tb_common.authz import Standing, permit

    from tests import edc_kit as k
    from tests.actor3 import SignedClient

    assert permit(
        "investigator", f"edc.{step.split('/', maxsplit=1)[0]}", Standing(True, frozenset({"enter_data"}), True)
    )
    svc, _, _ = k.service(tmp_path)
    if logged_pi:
        team = TeamStore()
        team.add_entry(k.STUDY, username="drpi", name="Dr Log PI", role="pi", tasks=(), start="2026-01-01", end=None,
                       training_day="2026-01-01", training_ref=None, by="stw", at="2026-01-01T00:00:00+00:00")  # fmt: skip
        team.close()
    app = FastAPI()
    app.include_router(router(lambda: svc))
    return SignedClient(app, sub="console:drpi", role="investigator").get(
        f"/studies/{k.STUDY}/edc/{step}", headers=sa.actor_header("drpi", role="investigator"))  # fmt: skip


@pytest.mark.parametrize("step", ["copy", "export/odm"])
def test_v2_05_the_studys_pi_reads_the_edc_copy_sheet_and_export(tmp_path: Path, step: str) -> None:
    """The matrix: ``edc.copy`` and ``edc.export`` are the investigator's with ``task:enter_data``, which the log's PI
    holds (every task). The router reads the study's delegation log (D-1480)."""
    r = _edc_read_as(tmp_path, step, logged_pi=True)
    if r.status_code == 403 and "edc.role" in r.text:
        raise RoleWalkFinding(f"GET /studies/{{rs}}/edc/{step}: the PI is refused (edc.role)")


@pytest.mark.parametrize("step", ["copy", "export/odm"])
def test_v2_05_an_investigator_on_no_log_is_refused(tmp_path: Path, step: str) -> None:
    """D-380: while the log names no PI, an investigator holds no task, so the router refuses (edc.role)."""
    r = _edc_read_as(tmp_path, step, logged_pi=False)
    assert r.status_code == 403 and "edc.role" in r.text, r.text


# ------------------------------------------------------------------------------------------- forged and stale claims
SAMPLE = {  # one changing route of each router that takes a person, with the action it declares
    "lifecycle": ("POST", "/studies/GZQO/subjects/GZQO-0001/step", "study.setup", "GZQO"),
    "registry": ("POST", "/registry/GZQO", "request.prepare", "GZQO"),
    "dataops": ("POST", "/dataops/batches/1/decide", "dataops.decide", ""),
    "job_reveal": ("POST", "/jobs/J1/reveal", "id.reveal", ""),
}


def _forged(kind: str, action: str, study: str, method: str, path: str, body: Any,
            monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:  # fmt: skip
    if kind == "bad signature":
        h = signed(action, study, method, path, body)
        head, _, mac = h[v3.HEADER].rpartition(".")
        return {v3.HEADER: f"{head}.{'0' if mac[0] != '0' else '1'}{mac[1:]}"}
    if kind == "wrong key":
        other = tmp_path / "other.key"
        other.write_text(hashlib.sha256(b"a key no box holds").hexdigest() + "\n", encoding="utf-8")
        with monkeypatch.context() as m:
            m.setenv(sa.ACTOR_SIGN_KEY_ENV, str(other))
            return signed(action, study, method, path, body)
    if kind == "expired":
        minted = v3.mint(sub="console:crc", role="coordinator", action=action, method=method, path=path, body=body,
                    study=study, standing=rw.standing(rw.BY_NAME["pi"]), now=time.time() - 600)  # fmt: skip
        return {v3.HEADER: minted}
    if kind == "v2 format":
        return sa.actor_header("console:crc", role="coordinator", scope=study)
    if kind == "unknown role":
        return signed(action, study, method, path, body, role="nobody")
    raise AssertionError(kind)


KINDS = ("bad signature", "wrong key", "expired", "v2 format", "unknown role", "replayed")
#: the dependency's reason each kind must be refused with (orchestrator.actor, tb_common.actor_v3)
REASON = {"bad signature": "does not verify", "wrong key": "does not verify", "expired": "has expired",
          "v2 format": "not a v3 assertion", "unknown role": "right", "replayed": "already used"}  # fmt: skip


def test_forged_and_stale_assertions_are_refused_and_recorded(orch: Any, monkeypatch: pytest.MonkeyPatch,
                                                              tmp_path: Path) -> None:  # fmt: skip
    """Each kind on one route of each router: 403 from the dependency and one ``actor.refused`` record. A role that
    changed after the claim was minted, or an account disabled since, is not seen by the orchestrator: a claim
    lives two minutes (``ACTOR_TTL``) and the console mints one only for a live session (the console half below)."""
    _, client, events = orch
    out = []
    for method, path, action, study in SAMPLE.values():
        body = {"x": 1}
        for kind in KINDS:
            if kind == "replayed":
                hdr = signed(action, study, method, path, body, role="coordinator" if action != "dataops.decide"
                             else "steward", standing=rw.standing(rw.BY_NAME["pi"]))  # fmt: skip
                client.request(method, path, json=body, headers=hdr)  # the first use
            else:
                hdr = _forged(kind, action, study, method, path, body, monkeypatch, tmp_path)
            n = len(events)
            r = client.request(method, path, json=body, headers=hdr)
            why = rw._reason(r)
            audited = len(events) > n and events[-1]["kind"] == "actor.refused"
            out.append({"service": "orchestrator", "kind": kind, "route": f"{method} {path}", "status": r.status_code,
                        "refused": "yes" if r.status_code == 403 and why else "NO", "audited": "yes" if audited else "NO",
                        "note": why})  # fmt: skip
    wrong = [o for o in out if o["refused"] != "yes" or o["audited"] != "yes" or REASON[o["kind"]] not in o["note"]]
    # a role changed, or an account disabled, after the console minted the claim (D-483: the orchestrator reads no
    # account; a claim is good for one call within ACTOR_TTL): accepted once inside the two minutes, then refused as
    # used, and refused once it is older than the two minutes
    method, path, action, study = SAMPLE["lifecycle"]
    body = {"x": 1}
    st = rw.standing(rw.BY_NAME["pi"])
    hdr = signed(action, study, method, path, body, role="coordinator", standing=st, sub="console:since-disabled")
    first = client.request(method, path, json=body, headers=hdr)
    again = client.request(method, path, json=body, headers=hdr)
    old = {v3.HEADER: v3.mint(sub="console:since-disabled", role="coordinator", action=action, method=method, path=path,
                              body=body, study=study, standing=st, now=time.time() - sa.ACTOR_TTL - 10)}  # fmt: skip
    late = client.request(method, path, json=body, headers=old)
    for kind, r, want in (("disabled or role changed after minting: first use inside the TTL", first, ""),
                          ("the same claim used again", again, "already used"),
                          ("a claim older than the TTL", late, "has expired")):  # fmt: skip
        why = rw._reason(r)
        out.append({"service": "orchestrator", "kind": kind, "route": f"{method} {path}", "status": r.status_code,
                    "refused": ("yes" if want in why else "NO") if want else "no (D-483: accepted inside the TTL)",
                    "audited": "-" if not want else "yes", "note": why or "past the dependency"})  # fmt: skip
        assert (want in why) if want else why == "", (kind, r.status_code, r.text[:200])
    rw.save_fragment("forged_orchestrator", out)
    assert wrong == []
