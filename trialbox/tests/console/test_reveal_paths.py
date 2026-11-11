"""T-103 (D-438): one reveal path for every chart-number reveal (CR-024 reveal part, CR-017 long term, ROLE-016).

Every surface that shows a chart number (the patient page, ``/api/v1``, the job page, the candidate page, the referral
print) goes through ``console.reveal.Reveal.identifier``: ``permit`` and the break-glass rule, a purpose and a reason
(with words for "other"), one per-person hourly cap shared by all surfaces and kept in the store, one audit shape for
a reveal and one for a refusal. The orchestrator asks the matrix row and keeps its own cap in its store. Direct tests
per role and surface (the role/route matrix posts ``{}`` and proves nothing here). Synthetic pseudonyms only."""

from __future__ import annotations

import ast
import json
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


def _case_job(b: dict[str, Any]) -> str:
    from tests.console.test_console_app import _done_case

    job = _done_case(b["backend"], {"mrn": "70000054", "lang": "en"})
    b["audit"].append("console.request", job_id=job.job_id, ruleset="GZQO", actor="console:admin",
                      detail={"line": "CASE GZQO mrn=••• lang=en", "channel": "web"})  # fmt: skip
    return str(job.job_id)


def _line_records(b: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in _events(b, "console.reveal_patient") if e["detail"]["via"] == "request_line"]


def test_a_request_line_costs_one_use_per_person_job_and_hour_and_refreshes_cost_none(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding 1: watching a running CASE job (a reload every 5 s) must not spend the cap."""
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "2")
    jid = _case_job(box)
    _done_screen(box["backend"], _ulid(993))
    crc = _user(box, "crc1", "coordinator")
    assert "mrn=70000054" not in crc.get(f"/pilot/jobs/{jid}?auto=1").text  # a refresh before any view: masked
    assert not _line_records(box)
    for _ in range(5):
        assert "mrn=70000054" in crc.get(f"/pilot/jobs/{jid}").text
    for _ in range(60):  # five minutes of the page refreshing itself
        assert "mrn=70000054" in crc.get(f"/pilot/jobs/{jid}?auto=1").text
    rec = _line_records(box)
    assert len(rec) == 1 and rec[0]["detail"]["cap"] == "1/2" and rec[0]["detail"]["pid"] == ""
    assert set(rec[0]["detail"]) >= {"pid", "role", "study", "purpose", "reason", "via", "basis", "cap"}
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(crc.get("/home").text), "reason": "contact"})
    assert r.status_code == 200 and "MRN-000123" in r.text  # the cap still has room


def test_a_request_line_over_the_cap_is_masked_and_refused_once(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "1")
    jid = _case_job(box)
    _done_screen(box["backend"], _ulid(989))
    crc = _user(box, "crc1", "coordinator")
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(crc.get("/home").text), "reason": "contact"})
    assert r.status_code == 200
    assert "mrn=70000054" not in crc.get(f"/pilot/jobs/{jid}").text
    refused = _events(box, "console.reveal_refused")
    assert [(e["detail"]["via"], e["detail"]["refused"]) for e in refused] == [("request_line", "cap")]
    assert not _line_records(box)


# ---------------------------------------------------------------------------------------------- whole lists
def test_the_screening_log_export_is_a_reveal(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Review finding 2a: a reason, one use of the cap, one record in the D-438 shape with a count, no pids."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["MRN", "pid", "status"])
    ws.append(["MRN-000123", A, "candidate"])
    ws.append(["MRN-000124", B, "candidate"])
    import io as _io

    buf = _io.BytesIO()
    wb.save(buf)
    monkeypatch.setattr(box["backend"], "registry_export", lambda rs, by, role="", scope="": buf.getvalue())
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "2")
    crc = _user(box, "crc1", "coordinator")
    assert crc.get("/pilot/registry/GZQO/export.xlsx").status_code == 400  # no reason
    assert crc.get("/pilot/registry/GZQO/export.xlsx?reason=other&note=a b c d e f").status_code == 400
    r = crc.get("/pilot/registry/GZQO/export.xlsx?reason=eligibility")
    assert r.status_code == 200 and r.content == buf.getvalue()
    ev = _events(box, "console.reveal_patient")
    assert len(ev) == 1 and ev[0]["detail"]["via"] == "screening_log" and ev[0]["detail"]["count"] == 2
    assert ev[0]["detail"]["pid"] == "" and A not in str(ev[0]) and ev[0]["detail"]["cap"] == "1/2"
    assert [e["detail"]["refused"] for e in _events(box, "console.reveal_refused")] == ["reason", "note"]
    assert crc.get("/pilot/registry/GZQO/export.xlsx?reason=eligibility").status_code == 200
    r = crc.get("/pilot/registry/GZQO/export.xlsx?reason=eligibility")
    assert r.status_code == 429  # the same cap as every other reveal
    admin = _user(box, "it1", "admin")
    assert admin.get("/pilot/registry/GZQO/export.xlsx?reason=contact").status_code == 403


def _workbook_job(b: dict[str, Any], pids: list[str]) -> tuple[str, str]:
    import io as _io
    from datetime import UTC, datetime

    from openpyxl import Workbook
    from tb_common.crypto import sha256_bytes
    from tb_contracts import Job, JobOutput

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["MRN", "pid", "tier"])
    for i, p in enumerate(pids):
        ws.append([f"MRN-00012{i}", p, "high"])
    buf = _io.BytesIO()
    wb.save(buf)
    jid, name = _ulid(778), "candidate_list_GZQO_v1.0.0.xlsx"
    key = f"outputs/{jid}/{name}"
    b["backend"].objects[key] = buf.getvalue()
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    out = JobOutput(filename=name, sha256=sha256_bytes(buf.getvalue()), minio_key=key, recipients=["crc1@hospa.test"],
                    tag="phi")  # fmt: skip
    b["backend"].add_job(Job(job_id=jid, type="SCREEN", ruleset="GZQO", ruleset_version="1.0.0",
                             requested_by="crc1@hospa.test", received_at=now, updated_at=now, state="done",
                             options={}, inputs=[], outputs=[out]))  # fmt: skip
    return jid, name


def test_a_patient_workbook_download_is_a_reveal_and_refused_after_an_opt_out(box: dict[str, Any]) -> None:  # noqa: F811
    """Review finding 2b: the same rule, one record with the count, one use of the cap; a workbook that names a
    patient who opted out since is refused with the reason (run the list again), never served (D-273 PV-4)."""
    jid, name = _workbook_job(box, [A, B])
    crc = _user(box, "crc1", "coordinator")
    url = f"/pilot/jobs/{jid}/files/{name}"
    r = crc.get(url)
    assert r.status_code == 200
    ev = _events(box, "console.reveal_patient")
    assert len(ev) == 1 and ev[0]["detail"]["via"] == "download" and ev[0]["detail"]["count"] == 2
    assert ev[0]["detail"]["cap"] == "1/60" and A not in str(ev[0]["detail"])
    _opt_out(box, B)  # the steward records B's opt-out after the list was made
    assert B in box["app"].state.helpers.gone()
    r = crc.get(url)
    assert r.status_code == 409 and b"MRN-000121" not in r.content
    refused = _events(box, "console.reveal_refused")
    assert [(e["detail"]["via"], e["detail"]["refused"]) for e in refused] == [("download", "opted out")]
    assert len(_events(box, "console.reveal_patient")) == 1


def _opt_out(b: dict[str, Any], pid: str) -> None:
    if b["users"].get("stw") is None:
        b["users"].create("stw", "steward", PW, "stw@hospa.test")
    stw, _ = login(b["app"], "stw", PW)
    r = stw.post("/site/opt-outs", data={"csrf": _csrf(stw.get("/site/opt-outs").text), "pid": pid},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303


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
    calls ``reveal.identifier``."""
    found: dict[str, str] = {}
    for f in sorted((ROOT / "services" / "console").glob("*.py")):
        if f.name == "reveal.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "reveal" in node.name:
                found[node.name] = ast.unparse(node)
    # not reveal handlers: the role property (``permit``), the audit word for a reason, the back end's client call
    assert set(found) - {"can_reveal", "reveal_reason", "reveal"} == HANDLERS
    for name, src in found.items():
        if name in HANDLERS:
            assert src.count(".reveal.identifier(") == 1, name


#: every console call that reads a stored job output, by (module, function), and why it cannot carry a chart number
#: past the one path. A new reader is a failing test until it is listed here with its reason, or goes through
#: ``console.reveal`` (review finding 2: no path that obtains a chart number may return unseen).
OUTPUT_READERS = {
    ("app.py", "_feas_result"): "feasibility aggregate JSON (counts)",
    ("app.py", "_check_split"): "the criteria review HTML (criterion classes)",
    ("app.py", "_consent_card"): "the consent record JSON (pseudonym, no chart number)",
    ("app.py", "job_view_file"): "HTML outputs only: the CASE sheet (chart text, no chart number) and aggregates",
    ("app.py", "_screen_card"): "the summary JSON and the candidate-list JSON (pseudonyms, no chart number)",
    ("app.py", "_case_card"): "the CASE record JSON (pseudonym)",
    ("app.py", "job_file"): "aggregate files; a phi workbook goes through reveal.workbook (asserted below)",
    ("app.py", "sponsor_pack"): "aggregate outputs only",
    ("approval.py", "context"): "the criteria review book (criteria, no patients)",
    ("approval.py", "tick"): "the criteria review book",
    ("approval.py", "label"): "the criteria review book",
    ("approval.py", "approve"): "the criteria review book",
    ("home.py", "load"): "the candidate-list JSON (pseudonyms)",
    ("screening_log.py", "criteria_choices"): "the candidate-list JSON (pseudonyms)",
    ("screening_log.py", "load"): "the candidate-list JSON (pseudonyms)",
}
#: what hands a chart number out of the back end or the pid map: only ``console.reveal`` (and the client) may call it
ID_SOURCES = {"reveal", "registry_export", "resolve_mrns", "pid_names", "mrns", "load_pid_map"}


def test_no_console_path_obtains_a_chart_number_outside_the_one_path() -> None:
    """Review finding 2 (a)-(c): walk every call in the console. A call of an identifier source (the back end's
    reveal and registry export, the pid map) appears only in ``reveal.py`` and the back-end client; every reader of
    a stored output is listed with its reason; the request line and the phi workbook go through the one path."""
    readers: set[tuple[str, str]] = set()
    sources: list[tuple[str, str, int]] = []
    bodies: dict[tuple[str, str], str] = {}

    def visit(node: ast.AST, fname: str, func: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node.name
            bodies[(fname, func)] = ast.unparse(node)
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name == "get_object":
                readers.add((fname, func))
            elif name in ID_SOURCES:
                sources.append((fname, func, node.lineno))
        if (  # the back end's own routes (``/jobs/{id}/reveal``, ``/registry/{rs}/export.xlsx``) named in a call
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(r"/reveal\b|/export\.xlsx", node.value)
            and node.value.startswith(("/jobs", "/registry"))
        ):
            sources.append((fname, func, getattr(node, "lineno", 0)))
        for child in ast.iter_child_nodes(node):
            visit(child, fname, func)

    for f in sorted((ROOT / "services" / "console").glob("*.py")):
        if f.name in ("reveal.py", "backend.py"):
            continue
        visit(ast.parse(f.read_text(encoding="utf-8")), f.name, "<module>")
    assert sources == [], f"a chart number obtained outside console.reveal: {sources}"
    assert readers == set(OUTPUT_READERS), f"stored-output readers changed: {readers ^ set(OUTPUT_READERS)}"
    assert ".reveal.workbook(" in bodies[("app.py", "job_file")]
    assert ".reveal.screening_log(" in bodies[("app.py", "registry_export")]
    assert ".reveal.shown_in_line(" in bodies[("app.py", "shown_ids")]
    assert "console.view_id" not in (ROOT / "services" / "console" / "app.py").read_text(encoding="utf-8")


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


def test_a_token_holder_signing_new_names_meets_the_services_total_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 3: the cap per calling service and name, plus a total per calling service."""
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    from tests.unit.test_service_auth import TOKEN, _fake_box

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "1")
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR_PER_SERVICE", "2")
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(oapp, "orch", lambda: _fake_box(events))
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    client = TestClient(oapp.app)
    codes = []
    for name in ("console:a1", "console:a2", "console:a3"):
        h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header(name, role="coordinator", scope="*")}
        codes.append(client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=h).status_code)
    assert codes == [200, 200, 429]
    assert events[-1]["kind"] == "screen.reveal_refused" and events[-1]["detail"]["reason"] == "service rate limit"


def test_the_whole_registry_export_is_never_given_to_a_break_glass_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 3: a grant covers one patient or one job, never the screening log."""
    from types import SimpleNamespace

    from orchestrator import app as oapp

    from tests.unit.test_service_auth import TOKEN, _fake_box

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    events: list[dict[str, Any]] = []
    fake = _fake_box(events)
    fake.cfg = SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(id="S1")), env=fake.cfg.env)
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    monkeypatch.setattr(oapp, "registry_of", lambda _o: SimpleNamespace(export_xlsx=lambda _rs, _site: b"PK-xlsx"))
    client = TestClient(oapp.app)
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("console:it1", role=authz.BREAK_GLASS_ROLE, scope="*")}
    r = client.get("/registry/GZQO/export.xlsx", headers=h)
    assert r.status_code == 403 and events[-1]["kind"] == "registry.export_refused"
    assert events[-1]["detail"]["reason"].startswith("break-glass")
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("console:crc1", role="coordinator", scope="*")}
    assert client.get("/registry/GZQO/export.xlsx", headers=h).status_code == 200


# ---------------------------------------------------------------------------------------------- the record itself
def test_the_record_is_not_a_second_copy_of_an_identifier(box: dict[str, Any]) -> None:  # noqa: F811
    """Review finding 4: the note is kept only for "other" and masked; a pid that is not a pseudonym is "invalid"."""
    _done_screen(box["backend"], _ulid(987))
    crc = _user(box, "crc1", "coordinator")
    csrf = _csrf(crc.get("/home").text)
    url = f"/studies/GZQO/patients/{A}/reveal"
    r = crc.post(url, data={"csrf": csrf, "reason": "contact", "note": "chart 70000054 mrn=70000054 called"})
    assert r.status_code == 200
    assert "note" not in _events(box, "console.reveal_patient")[-1]["detail"]  # not "other": no note kept
    r = crc.post(url, data={"csrf": csrf, "reason": "other", "note": "monitor asked about chart 70000054 mrn=70000054"})
    assert r.status_code == 200
    note = _events(box, "console.reveal_patient")[-1]["detail"]["note"]
    assert "70000054" not in note and "monitor asked" in note
    stw = _user(box, "stw1", "steward")  # refused by the rule, with whatever the URL carried as the pid
    r = stw.post("/studies/GZQO/patients/70000054%20Wang/reveal",
                 data={"csrf": _csrf(stw.get("/home").text), "reason": "contact"})  # fmt: skip
    assert r.status_code == 403
    assert _events(box, "console.reveal_refused")[-1]["detail"]["pid"] == "invalid"
    every = json.dumps(_events(box, "console.reveal_refused") + _events(box, "console.reveal_patient"))
    assert "70000054" not in every and "Wang" not in every
    refused = _events(box, "console.reveal_refused")
    assert all(e["detail"]["pid"] in ("", "invalid", A) for e in refused)


def test_a_refused_attempt_writes_exactly_one_record(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Review finding 5: the back end refuses (opted out, not listed, its cap) or has no number: one refusal record,
    no reveal record."""
    from console.backend import Refused

    _done_screen(box["backend"], _ulid(986))
    crc = _user(box, "crc1", "coordinator")
    csrf = _csrf(crc.get("/home").text)

    def refuse(*_a: Any, **_k: Any) -> str | None:
        raise Refused("this patient opted out")

    monkeypatch.setattr(box["backend"], "reveal", refuse)
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 409
    monkeypatch.setattr(box["backend"], "reveal", lambda *_a, **_k: None)
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 200 and "MRN-000123" not in r.text
    assert not _events(box, "console.reveal_patient")
    assert [e["detail"]["refused"] for e in _events(box, "console.reveal_refused")] == [
        "back end",
        "not in the pid map",
    ]


def test_a_note_of_spaced_letters_is_not_a_reason(box: dict[str, Any]) -> None:  # noqa: F811
    """Review finding 6: ten characters that are not spaces."""
    from console.reveal import note_words

    assert note_words("a b c d e f") == 6 and note_words("monitor  asked") == 12
    _done_screen(box["backend"], _ulid(985))
    crc = _user(box, "crc1", "coordinator")
    csrf = _csrf(crc.get("/home").text)
    url = f"/studies/GZQO/patients/{A}/reveal"
    assert crc.post(url, data={"csrf": csrf, "reason": "other", "note": "a b c d e f g h i"}).status_code == 400
    assert crc.post(url, data={"csrf": csrf, "reason": "other", "note": "a b c d e f g h i j"}).status_code == 200


def test_the_demo_back_end_sends_the_purpose_and_reason() -> None:
    """Review finding 6: ``tools.role_demo.InprocBackend.reveal`` passes what the console's one path sends."""
    from types import SimpleNamespace

    from tools.role_demo import InprocBackend

    sent: list[dict[str, Any]] = []

    def post(url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
        sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {"mrn": "MRN-1"}, text="")

    bk = InprocBackend.__new__(InprocBackend)
    bk.c = SimpleNamespace(post=post)
    assert bk.reveal("J1", "PID-00000001", "console:crc1", role="coordinator", purpose="contact", reason="consent")
    assert sent == [{"pid": "PID-00000001", "purpose": "contact", "reason": "consent"}]
