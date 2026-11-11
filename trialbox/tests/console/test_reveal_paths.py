"""T-103 (D-438): one reveal path for every chart-number reveal (CR-024 reveal part, CR-017 long term, ROLE-016).

Every surface that shows a chart number (the patient page, ``/api/v1``, the job page, the candidate page, the referral
print) goes through ``console.reveal.Reveal.identifier``: ``permit`` and the break-glass rule, a purpose and a reason
(with words for "other"), one per-person hourly cap shared by all surfaces and kept in the store, one audit shape for
a reveal and one for a refusal. The orchestrator asks the matrix row and keeps its own cap in its store. Direct tests
per role and surface (the role/route matrix posts ``{}`` and proves nothing here). Synthetic pseudonyms only."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from console.app import create_app
from console.auth import Session
from fastapi.testclient import TestClient
from tb_common import authz
from tb_common import service_auth as sa

from tests.console.test_console_app import PILOT_ENV, _done_screen, _ulid, box, login, name_pi  # noqa: F401 - fixture
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_team_pages import _events, _log_pi_and_sub

A, B = "a" * 32, "b" * 32
ROOT = Path(__file__).resolve().parents[2]
HANDLERS = {"patient_reveal", "api_reveal", "job_reveal", "candidate_reveal", "referral_print_reveal"}


def _api(b: dict[str, Any], user: str, app: Any = None) -> tuple[TestClient, dict[str, str]]:
    api = TestClient(app or b["app"])
    tok = api.post("/api/v1/session", json={"username": user, "password": PW}).json()["token"]
    return api, {"Authorization": f"Bearer {tok}"}


def _session(b: dict[str, Any], user: str) -> Session:
    return Session(user=b["users"].get(user), csrf="-", lang="en", token_sha="-")


def _referral(b: dict[str, Any], pi: TestClient) -> int:
    p = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    r = pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(p)}, follow_redirects=False)
    assert r.status_code == 303
    return int(b["app"].state.helpers.team.referrals("GZQO", A)[-1].id)


def _surfaces(jid: str, ref_id: int) -> list[tuple[str, str, dict[str, str]]]:
    """(name, path, extra form fields) of the four page surfaces; ``/api/v1`` is posted as JSON apart."""
    return [
        ("patient", f"/studies/GZQO/patients/{A}/reveal", {}),
        ("job", f"/pilot/jobs/{jid}/reveal", {"pid": A}),
        ("candidates", f"/studies/GZQO/candidates/{A}/reveal", {"purpose": "contact"}),
        ("referral", f"/studies/GZQO/referrals/{ref_id}/print", {"lang": "en"}),
    ]


# ---------------------------------------------------------------------------------------------- acceptance (1)
def test_every_surface_reveals_for_the_pi_with_one_audit_shape(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(990)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    ref_id = _referral(box, pi)
    csrf = _csrf(pi.get("/home").text)
    for name, path, extra in _surfaces(jid, ref_id):
        r = pi.post(path, data={"csrf": csrf, "reason": "contact", **extra})
        assert r.status_code == 200 and "MRN-000123" in r.text, name
    api, hdr = _api(box, "drsato")
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"}, headers=hdr)
    assert r.status_code == 200 and r.json()["mrn"] == "MRN-000123"
    ev = _events(box, "console.reveal_patient")
    assert [e["detail"]["via"] for e in ev] == ["patient", "job", "candidates", "referral", "api"]
    shape = {"pid", "role", "affiliation", "study", "purpose", "reason", "via", "basis", "cap"}
    for e in ev:
        assert set(e["detail"]) == shape, e["detail"]
        assert e["detail"]["study"] == "GZQO" and e["detail"]["basis"] == "log" and e["detail"]["purpose"]
    assert [e["detail"]["cap"] for e in ev] == [f"{n}/60" for n in range(1, 6)]
    assert [e["detail"]["purpose"] for e in ev] == ["patient", "screening_list", "contact", "referral", "patient"]
    # the purpose and the reason travel to the back end, signed with the account's own role
    assert box["backend"].signed[-5:] == [("reveal", "investigator", "*")] * 5
    assert not _events(box, "console.reveal_refused")


# ---------------------------------------------------------------------------------------------- acceptance (2)
def test_the_61st_reveal_in_an_hour_is_refused_on_either_surface(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(991))
    crc = _user(box, "crc1", "coordinator")
    api, hdr = _api(box, "crc1")
    for i in range(60):  # two surfaces: the page and /api/v1, one cap
        if i % 2:
            r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"}, headers=hdr)
        else:
            r = crc.post(f"/studies/GZQO/patients/{A}/reveal",
                         data={"csrf": _csrf(crc.get("/home").text), "reason": "contact"})  # fmt: skip
        assert r.status_code == 200, i
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"}, headers=hdr)
    assert r.status_code == 429 and r.json()["error"] == "reveal.rate_limited"
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(crc.get("/home").text), "reason": "contact"})
    assert r.status_code == 429 and "MRN-000123" not in r.text
    assert len(box["backend"].revealed) == 60
    refused = _events(box, "console.reveal_refused")
    assert [e["detail"]["refused"] for e in refused] == ["cap", "cap"]
    assert {e["detail"]["via"] for e in refused} == {"api", "patient"}


def test_the_cap_is_in_the_store_shared_by_two_console_processes(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a counter in memory: a second console (another process, a restart) sees the uses of the first."""
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "2")
    jid = _ulid(992)
    _done_screen(box["backend"], jid)
    crc = _user(box, "crc1", "coordinator")
    form = {"csrf": _csrf(crc.get("/home").text), "reason": "consent"}
    assert crc.post(f"/studies/GZQO/patients/{A}/reveal", data=form).status_code == 200
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(box["dir"] / "console2")}
    app2 = create_app(env, backend=box["backend"], audit=box["audit"], users=box["users"])
    crc2, _ = login(app2, "crc1", PW)
    form2 = {"csrf": _csrf(crc2.get("/home").text), "reason": "consent", "pid": A}
    assert crc2.post(f"/pilot/jobs/{jid}/reveal", data=form2).status_code == 200  # the second use, other process
    assert crc2.post(f"/pilot/jobs/{jid}/reveal", data=form2).status_code == 429
    assert crc.post(f"/studies/GZQO/patients/{A}/reveal", data=form).status_code == 429
    assert len(box["backend"].revealed) == 2


def test_a_chart_number_in_a_request_line_counts_against_the_same_cap(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "1")
    _done_screen(box["backend"], _ulid(993))
    crc = _user(box, "crc1", "coordinator")
    rv = box["app"].state.helpers.reveal
    s = _session(box, "crc1")
    assert rv.shown_in_line(s, "GZQO", "J1", "subject") == "1/1"
    assert rv.shown_in_line(s, "GZQO", "J1", "subject") is None
    assert _events(box, "console.view_id_refused")[-1]["detail"]["limit"] == 1
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(crc.get("/home").text), "reason": "contact"})
    assert r.status_code == 429 and box["backend"].revealed == []


# ---------------------------------------------------------------------------------------------- refusals
# the aggregate-only accounts (viewer, CRO) meet D-146's scope gate before any handler: one ``console.denied``; the
# other roles without the row reach the one path and get one ``console.reveal_refused``
REFUSED_AS = {"viewer": "console.denied", "cro": "console.denied", "steward": "console.reveal_refused",
              "privacy": "console.reveal_refused"}  # fmt: skip


@pytest.mark.parametrize("role", sorted(REFUSED_AS))
def test_a_role_without_the_reveal_row_is_refused_on_every_surface(box: dict[str, Any], role: str) -> None:  # noqa: F811
    assert not authz.permit(role, "id.reveal").allowed and not authz.permit(role, "breakglass.open").allowed
    jid = _ulid(994)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    ref_id = _referral(box, pi)
    who = _user(box, "someone", role)
    csrf = _csrf(who.get("/home").text)
    kind = REFUSED_AS[role]

    def mine() -> list[dict[str, Any]]:
        return [e for e in _events(box, kind) if e["actor"] == "console:someone"]

    for name, path, extra in _surfaces(jid, ref_id):
        before = len(mine())
        r = who.post(path, data={"csrf": csrf, "reason": "contact", **extra})
        assert r.status_code == 403 and "MRN-000123" not in r.text, (role, name)
        assert len(mine()) == before + 1, (role, name)
    api, hdr = _api(box, "someone")
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"}, headers=hdr)
    assert r.status_code == 403
    assert len(mine()) == 5
    if kind == "console.reveal_refused":
        assert {e["detail"]["refused"] for e in mine()} == {"role"} and {e["detail"]["role"] for e in mine()} == {role}
    assert box["backend"].revealed == [] and not _events(box, "console.reveal_patient")


def test_the_administrator_without_a_grant_is_refused_on_every_surface(box: dict[str, Any]) -> None:  # noqa: F811
    """D-280: ``id.reveal`` is false for the administrator; with no grant the break-glass rule refuses too."""
    jid = _ulid(995)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    ref_id = _referral(box, pi)
    admin = _user(box, "it1", "admin")
    csrf = _csrf(admin.get("/home").text)
    for name, path, extra in _surfaces(jid, ref_id):
        r = admin.post(path, data={"csrf": csrf, "reason": "contact", **extra})
        assert r.status_code in (403, 404) and "MRN-000123" not in r.text, name
    assert box["backend"].revealed == [] and not _events(box, "console.reveal_patient")
    refused = [e for e in _events(box, "console.reveal_refused") if e["actor"] == "console:it1"]
    assert refused and {e["detail"]["refused"] for e in refused} == {"role"}


def test_an_investigator_the_log_does_not_reach_is_refused_as_delegation(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(996)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("refer",))  # not ticked "screen"
    csrf = _csrf(sub.get("/home").text)
    r = sub.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 403
    r = sub.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "reason": "contact", "pid": A})
    assert r.status_code == 403
    refused = _events(box, "console.reveal_refused")
    assert [e["detail"]["refused"] for e in refused] == ["delegation", "delegation"]
    assert box["backend"].revealed == []


def test_a_reason_and_words_for_other_on_every_surface(box: dict[str, Any]) -> None:  # noqa: F811
    """ROLE-016: "other" needs a written reason of 10 characters or more on every surface, kept in the record."""
    jid = _ulid(997)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    ref_id = _referral(box, pi)
    csrf = _csrf(pi.get("/home").text)
    for name, path, extra in _surfaces(jid, ref_id):
        assert pi.post(path, data={"csrf": csrf, **extra}).status_code == 400, name  # no reason
        r = pi.post(path, data={"csrf": csrf, "reason": "other", "note": "short", **extra})
        assert r.status_code == 400, name
        r = pi.post(path, data={"csrf": csrf, "reason": "other", "note": "the monitor asked for the source", **extra})
        assert r.status_code == 200 and "MRN-000123" in r.text, name
    api, hdr = _api(box, "drsato")
    url = f"/api/v1/studies/GZQO/patients/{A}/reveal"
    assert api.post(url, json={"reason": "other", "note": "short"}, headers=hdr).status_code == 400
    assert api.post(url, json={"reason": "other", "note": "the monitor asked again"}, headers=hdr).status_code == 200
    refused = _events(box, "console.reveal_refused")
    assert [e["detail"]["refused"] for e in refused] == ["reason", "note"] * 4 + ["note"]
    shown = _events(box, "console.reveal_patient")
    assert len(shown) == 5 and all(len(e["detail"]["note"]) >= 10 for e in shown)
    assert len(box["backend"].revealed) == 5


def test_a_purpose_is_required(box: dict[str, Any]) -> None:  # noqa: F811
    """Every call of the one function names a purpose; the candidate page's comes from its list."""
    _done_screen(box["backend"], _ulid(998))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    csrf = _csrf(pi.get("/home").text)
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 400
    sess = _session(box, "drsato")
    rv = box["app"].state.helpers.reveal
    for bad in ("", "Has Spaces", "x"):
        with pytest.raises(Exception) as exc:
            rv.identifier(sess, "GZQO", A, bad, "contact")
        assert getattr(exc.value, "status", None) == 400 or "400" in repr(exc.value)
    assert [e["detail"]["refused"] for e in _events(box, "console.reveal_refused")] == ["purpose"] * 3
    got = rv.identifier(sess, "GZQO", A, "emr_link", "contact", via="emr")  # T-301a / T-320a: the EMR link's call
    assert got.mrn == "MRN-000123" and got.basis == "log"
    assert _events(box, "console.reveal_patient")[-1]["detail"]["via"] == "emr"


# ---------------------------------------------------------------------------------------------- acceptance (4)
def test_only_thin_handlers_and_the_one_function_reveal() -> None:
    """``grep 'def .*reveal' services/console`` outside ``reveal.py`` lists only the five thin handlers, each of which
    calls ``reveal.identifier``; nothing else asks the back end for a chart number."""
    found: dict[str, str] = {}
    for f in sorted((ROOT / "services" / "console").glob("*.py")):
        if f.name == "reveal.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "reveal" in node.name:
                found[node.name] = ast.unparse(node)
        text = f.read_text(encoding="utf-8")
        if f.name != "backend.py":
            assert not re.search(r"\bbk\.reveal\(|backend\.reveal\(|\.reveal\(job", text), f.name
    # not reveal handlers: the role property (``permit``), the audit word for a reason, the back end's client call
    assert set(found) - {"can_reveal", "reveal_reason", "reveal"} == HANDLERS
    for name, src in found.items():
        if name not in HANDLERS:
            continue
        assert src.count(".reveal.identifier(") == 1, name


# ---------------------------------------------------------------------------------------------- the orchestrator
def test_the_orchestrator_asks_the_matrix_row() -> None:
    from orchestrator import app as oapp

    for role in authz.MATRIX_ROLES:
        assert oapp.id_authority(role) == authz.permit(role, "id.reveal").allowed, role
    assert oapp.id_authority(authz.BREAK_GLASS_ROLE)
    assert not oapp.id_authority("") and not oapp.id_authority("superuser")
    assert not hasattr(oapp, "ID_ROLES")


def test_the_orchestrators_cap_survives_a_restart_and_records_the_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    from tests.unit.test_service_auth import TOKEN, _fake_box

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "1")
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(oapp, "orch", lambda: _fake_box(events))
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    client = TestClient(oapp.app)
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("console:crc1", role="coordinator", scope="*")}
    body = {"pid": "PID-00000001", "purpose": "contact", "reason": "consent"}
    assert client.post("/jobs/J1/reveal", json=body, headers=h).status_code == 200
    ev = events[-1]
    assert (
        ev["kind"] == "screen.reveal" and ev["detail"]["purpose"] == "contact" and ev["detail"]["reason"] == "consent"
    )
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())  # a restart: a new limiter, the same store
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000002"}, headers=h).status_code == 429
    assert events[-1]["detail"]["reason"] == "rate limit"
    bad = {"pid": "PID-00000001", "purpose": "Not A Purpose"}
    assert client.post("/jobs/J1/reveal", json=bad, headers=h).status_code == 422
