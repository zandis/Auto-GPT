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


@pytest.mark.parametrize("key", sorted(SECOND_CHECK))
@pytest.mark.xfail(
    strict=True, reason="V2-01: two orchestrator routes refuse a coordinator the row they declare allows"
)
def test_v2_01_a_route_answers_as_the_row_it_declares(orch: Any, key: tuple[str, str, str]) -> None:
    """D-871 and D-864 record why; the matrix has no row that says so (the guides are frozen)."""
    _, client, _ = orch
    method, template, action = key
    path = rw.orch_fill(template)
    body = rw.orch_body(template)
    st = rw.standing(rw.BY_NAME["crc"])
    r = client.request(method, path, json=body, headers=signed(action, "", method, path, body, role="coordinator",
                                                               standing=st, sub="console:walk-crc"))  # fmt: skip
    assert rw._reason(r) != "right", r.text[:200]


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
    rw.save_fragment("forged_orchestrator", out)
    assert [o for o in out if o["refused"] != "yes" or o["audited"] != "yes"] == []
