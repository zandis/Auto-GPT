"""9k-6b (D-1376): converting a form to the field macro changes how a refusal is shown, not what is valid, not who may
post, not what is stored. The proof, for each form converted in journey 1:

``tests/console/data/form_behaviour_9k6b1.json`` holds what the console did on origin/master (the commit this card
branched from, before any form was converted) with a fixed sequence of POSTs per form: valid and invalid payloads,
and posts by a role that may not post. For each step: the status, where a redirect goes, the audit events the step
wrote and the stored result after it. This test replays the same sequences on the tree and requires the same, step by
step. The ``/api/v1`` twins of the IRB record and the committee record are in the sequences too.

The data was written by this same file on master: ``TB_9K6B_CAPTURE=<path> pytest tests/console/test_form_behaviour_9k6b.py``
writes what the tree does instead of comparing. Synthetic values only; a refusal is compared by its status (the page
that shows it is the part this card changes).
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_t102b_roles import _api

DATA = Path(__file__).with_name("data") / "form_behaviour_9k6b1.json"
USERS = {"coordinator": ("crc1", "coordinator"), "pi": ("drsato", "investigator"), "steward": ("stw", "steward")}
VOLATILE = {"at", "ts", "time", "when", "hash", "prev", "prev_hash", "seq", "sha", "mac", "ulid", "session"}
D = "d" * 32

# one sequence per form: (label, role, how, address, data); ``how`` is "form" (POST the data to the address with the
# person's token) or "api" (POST the data as JSON to the API); an address is ``page|action`` or the one address
SEQUENCES: dict[str, dict[str, Any]] = {
    "irb": {
        "japan": False,
        "prep": [],
        "steps": [
            (
                "number missing",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {"approval_no": "", "approved_on": "2026-10-01"},
            ),
            (
                "not a day",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {"approval_no": "I1", "approved_on": "2026-02-30"},
            ),
            (
                "expires early",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {"approval_no": "I1", "approved_on": "2026-10-01", "expires_on": "2026-09-01"},
            ),
            (
                "saved",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {
                    "approval_no": "I1",
                    "approved_on": "2026-10-01",
                    "expires_on": "2027-10-01",
                    "icf_version": "v1.0",
                    "icf_date": "2026-10-01",
                },
            ),
            (
                "change without a reason",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {
                    "approval_no": "I2",
                    "approved_on": "2026-10-01",
                    "expires_on": "2027-10-01",
                    "icf_version": "v1.0",
                    "icf_date": "2026-10-01",
                },
            ),
            (
                "change with a short reason",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {
                    "approval_no": "I2",
                    "approved_on": "2026-10-01",
                    "expires_on": "2027-10-01",
                    "icf_version": "v1.0",
                    "icf_date": "2026-10-01",
                    "reason": "short",
                },
            ),
            (
                "changed",
                "coordinator",
                "form",
                "/studies/GZQO/irb",
                {
                    "approval_no": "I2",
                    "approved_on": "2026-10-01",
                    "expires_on": "2027-10-01",
                    "icf_version": "v1.0",
                    "icf_date": "2026-10-01",
                    "reason": "the number was copied wrong",
                },
            ),
            (
                "api not a day",
                "coordinator",
                "api",
                "/api/v1/studies/GZQO/irb",
                {"approval_no": "I3", "approved_on": "2026-02-30", "reason": "the api says no"},
            ),
            ("a steward may not", "steward", "form", "/studies/GZQO/irb", {"approval_no": "I9"}),
        ],
    },
    "icf": {
        "japan": False,
        "prep": [],
        "steps": [
            (
                "bad version",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "v!#1", "reconsent": "1"},
            ),
            (
                "empty version",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "", "reconsent": "1"},
            ),
            (
                "not a day",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "ICF-1", "version_date": "2026-02-30", "reconsent": "1"},
            ),
            (
                "used before approved",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "ICF-1", "irb_approved_on": "2026-10-05", "effective_from": "2026-10-01", "reconsent": "1"},
            ),
            (
                "added",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {
                    "version": "ICF-2",
                    "version_date": "2026-10-01",
                    "irb_approved_on": "2026-10-02",
                    "effective_from": "2026-10-03",
                    "reconsent": "1",
                    "note": "first",
                },
            ),
            (
                "added without re-consent",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "ICF-3", "irb_approved_on": "2026-10-02", "note": "second"},
            ),
            (
                "withdraw one not listed",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "zzz", "withdraw": "1", "note": "mistake"},
            ),
            (
                "withdraw without a note",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "ICF-3", "withdraw": "1"},
            ),
            (
                "withdrawn",
                "coordinator",
                "form",
                "/studies/GZQO/irb|/studies/GZQO/irb/icf",
                {"version": "ICF-3", "withdraw": "1", "note": "entered by mistake"},
            ),
            ("api bad version", "coordinator", "api", "/api/v1/studies/GZQO/icf", {"version": "v!#1"}),
            ("a steward may not", "steward", "form", "/studies/GZQO/irb|/studies/GZQO/irb/icf", {"version": "ICF-9"}),
        ],
    },
    "committee": {
        "japan": True,
        "prep": [],
        "steps": [
            ("bad kind", "coordinator", "form", "/studies/GZQO/committee", {"kind": "bogus"}),
            (
                "approval without a version",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {"kind": "shishin", "approved_on": "2026-10-01"},
            ),
            (
                "approval in the future",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {"kind": "shishin", "approved_version": "1.0", "approved_on": "2099-01-01"},
            ),
            (
                "a long text",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {"kind": "shishin", "establisher": "x" * 201},
            ),
            (
                "permission version without a date",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {"kind": "shishin", "permission_version": "1.0"},
            ),
            (
                "saved",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {
                    "kind": "shishin",
                    "establisher": "Synthetic University",
                    "current_version": "1.0",
                    "approved_version": "1.0",
                    "approved_on": "2026-10-01",
                    "central": "1",
                    "documents": "Sample notice",
                },
            ),
            (
                "change without a reason",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {"kind": "chiken", "current_version": "1.0", "approved_version": "1.0", "approved_on": "2026-10-01"},
            ),
            (
                "changed",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {
                    "kind": "chiken",
                    "current_version": "1.0",
                    "approved_version": "1.0",
                    "approved_on": "2026-10-01",
                    "reason": "the study is a clinical trial",
                },
            ),
            (
                "permission saved",
                "coordinator",
                "form",
                "/studies/GZQO/committee",
                {
                    "kind": "chiken",
                    "current_version": "1.0",
                    "approved_version": "1.0",
                    "approved_on": "2026-10-01",
                    "permission_version": "1.0",
                    "permitted_on": "2026-10-10",
                    "reason": "the permission arrived",
                },
            ),
            ("api bad kind", "coordinator", "api", "/api/v1/studies/GZQO/committee", {"kind": "bogus"}),
            (
                "api saved",
                "coordinator",
                "api",
                "/api/v1/studies/GZQO/committee",
                {"kind": "tokutei", "current_version": "2.0", "reason": "the api changes the kind"},
            ),
            ("a steward may not", "steward", "form", "/studies/GZQO/committee", {"kind": "shishin"}),
        ],
    },
    "staff": {
        "japan": False,
        "prep": [],
        "steps": [
            ("no name", "steward", "form", "/site/staff", {"kind": "person", "name": "", "department": "Cardiology"}),
            ("a blank name", "steward", "form", "/site/staff", {"kind": "person", "name": "   "}),
            (
                "saved",
                "steward",
                "form",
                "/site/staff",
                {
                    "kind": "person",
                    "name": "Dr Synthetic",
                    "department": "Cardiology",
                    "practitioner_id": "P1",
                    "role": "Physician",
                    "contact": "ext. 1",
                    "username": "",
                },
            ),
            (
                "switch off one not there",
                "steward",
                "form",
                "/site/staff",
                {"kind": "active", "id": "9999", "active": "0"},
            ),
            ("switched off", "steward", "form", "/site/staff", {"kind": "active", "id": "1", "active": "0"}),
            ("a coordinator may not", "coordinator", "form", "/site/staff", {"kind": "person", "name": "Dr X"}),
        ],
    },
    "contact": {
        "japan": False,
        "prep": [],
        "steps": [
            ("both empty", "steward", "form", "/site/staff", {"kind": "contact", "department": "", "name": ""}),
            ("no name", "steward", "form", "/site/staff", {"kind": "contact", "department": "Radiology", "name": ""}),
            ("no department", "steward", "form", "/site/staff", {"kind": "contact", "department": "", "name": "Desk"}),
            (
                "saved",
                "steward",
                "form",
                "/site/staff",
                {"kind": "contact", "department": "Radiology", "name": "Synthetic Desk", "contact": "ext. 2"},
            ),
            (
                "saved again, the same department",
                "steward",
                "form",
                "/site/staff",
                {"kind": "contact", "department": "Radiology", "name": "Other Desk", "contact": "ext. 3"},
            ),
            (
                "a coordinator may not",
                "coordinator",
                "form",
                "/site/staff",
                {"kind": "contact", "department": "X", "name": "Y"},
            ),
        ],
    },
    "optout": {
        "japan": False,
        "prep": [],
        "steps": [
            ("a prefix", "steward", "form", "/site/opt-outs", {"pid": "deadbeef", "source": "paper"}),
            ("thirty-one characters", "steward", "form", "/site/opt-outs", {"pid": "a" * 31, "source": "paper"}),
            ("neither given", "steward", "form", "/site/opt-outs", {"pid": "", "chart_no": "", "source": "paper"}),
            (
                "a chart number of the wrong shape",
                "steward",
                "form",
                "/site/opt-outs",
                {"pid": "", "chart_no": "bad chart!", "source": "paper"},
            ),
            (
                "a pseudonym in the chart field",
                "steward",
                "form",
                "/site/opt-outs",
                {"pid": "", "chart_no": "b" * 32, "source": "paper"},
            ),
            ("saved", "steward", "form", "/site/opt-outs", {"pid": "c" * 32, "source": "paper", "note": "n"}),
            ("saved again, the same", "steward", "form", "/site/opt-outs", {"pid": "c" * 32, "source": "paper"}),
            ("a coordinator may not", "coordinator", "form", "/site/opt-outs", {"pid": "e" * 32, "source": "paper"}),
        ],
    },
    "optout-lift": {
        "japan": False,
        "prep": ["optout_d"],
        "steps": [
            ("a short reason", "steward", "form", "/site/opt-outs", {"pid": D, "lift": "1", "note": "short"}),
            ("no reason", "steward", "form", "/site/opt-outs", {"pid": D, "lift": "1"}),
            (
                "one not on the register",
                "steward",
                "form",
                "/site/opt-outs",
                {"pid": "e" * 32, "lift": "1", "note": "a long enough reason"},
            ),
            (
                "a prefix",
                "steward",
                "form",
                "/site/opt-outs",
                {"pid": D[:8], "lift": "1", "note": "a long enough reason"},
            ),
            (
                "lifted",
                "steward",
                "form",
                "/site/opt-outs",
                {"pid": D, "lift": "1", "note": "the patient asked to return"},
            ),
            (
                "a coordinator may not",
                "coordinator",
                "form",
                "/site/opt-outs",
                {"pid": D, "lift": "1", "note": "a long enough reason"},
            ),
        ],
    },
    "state": {
        "japan": False,
        "prep": [],
        "steps": [
            ("a move that is not one", "coordinator", "form", "/studies/GZQO/state", {"state": "bogus", "reason": "x"}),
            (
                "a pause without a reason",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "paused", "reason": ""},
            ),
            (
                "years not a number",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "closed", "reason": "r", "keep_years": "x"},
            ),
            (
                "years too many",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "closed", "reason": "r", "keep_years": "99"},
            ),
            (
                "years none",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "closed", "reason": "r", "keep_years": "0"},
            ),
            ("paused", "coordinator", "form", "/studies/GZQO/state", {"state": "paused", "reason": "synthetic pause"}),
            ("paused again", "coordinator", "form", "/studies/GZQO/state", {"state": "paused", "reason": "synthetic"}),
            ("opened", "coordinator", "form", "/studies/GZQO/state", {"state": "open", "reason": ""}),
            (
                "a close asks first",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "closed", "reason": "last patient out", "keep_years": "5"},
            ),
            (
                "closed",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "closed", "reason": "last patient out", "keep_years": "5", "confirm": "yes"},
            ),
            (
                "a move from a closed study",
                "coordinator",
                "form",
                "/studies/GZQO/state",
                {"state": "open", "reason": ""},
            ),
        ],
    },
    "take-back": {
        "japan": False,
        "prep": ["closed_today"],
        "steps": [
            (
                "a coordinator may not",
                "coordinator",
                "form",
                "/studies/GZQO/state|/studies/GZQO/state/take-back",
                {"reason": "mistake"},
            ),
            ("no reason", "pi", "form", "/studies/GZQO/state|/studies/GZQO/state/take-back", {"reason": ""}),
            ("a blank reason", "pi", "form", "/studies/GZQO/state|/studies/GZQO/state/take-back", {"reason": "   "}),
            (
                "taken back",
                "pi",
                "form",
                "/studies/GZQO/state|/studies/GZQO/state/take-back",
                {"reason": "closed by mistake"},
            ),
            (
                "too late: it is open",
                "pi",
                "form",
                "/studies/GZQO/state|/studies/GZQO/state/take-back",
                {"reason": "again"},
            ),
        ],
    },
}


def _client(b: dict[str, Any], role: str) -> Any:
    user, kind = USERS[role]
    if b["users"].get(user) is None:
        c = _user(b, user, kind)
        if role == "pi":
            name_pi(b, user)
    else:
        c, _ = login(b["app"], user, PW)
    return c


def _all_events(b: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x]
    return out


def _clean(x: Any) -> Any:
    """A value without what changes from run to run (times, hashes, sequence numbers)."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        x = dataclasses.asdict(x)
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in sorted(x.items()) if k not in VOLATILE}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _event(e: dict[str, Any]) -> dict[str, Any]:
    return {k: _clean(e[k]) for k in ("event", "actor", "ruleset", "detail") if k in e}


def _stored(b: dict[str, Any], name: str) -> Any:
    """What the form's records hold now, read from the stores."""
    h = b["app"].state.helpers
    if name in ("irb", "icf"):
        return _clean(
            {"irb": h.team.irb("GZQO"), "icf": h.team.icf_list("GZQO"), "history": h.team.icf_history("GZQO")}
        )
    if name == "committee":
        return _clean({"record": h.team.committee("GZQO"), "permission": h.team.permission("GZQO", "SAMPLE-A"),
                       "history": h.team.committee_history("GZQO")})  # fmt: skip
    if name in ("staff", "contact"):
        return _clean({"staff": h.team.staff(active_only=False), "contacts": h.team.contacts()})
    if name in ("optout", "optout-lift"):
        from tb_common.optout import OptOutRegister

        reg = OptOutRegister()
        return _clean({"current": reg.current(), "events": reg.events()})
    return _clean({"state": h.store.study_state("GZQO"), "history": h.store.state_history("GZQO")})


def _prep(b: dict[str, Any], step: str) -> None:
    if step == "optout_d":
        c = _client(b, "steward")
        r = c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/site/opt-outs").text), "pid": D, "source": "paper"},
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 303
    elif step == "closed_today":
        h = b["app"].state.helpers
        h.store.set_study_state(
            "GZQO", "closed", "synthetic close", "console:test", h.clock().isoformat(), keep_years=1
        )


def _run(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    seq = SEQUENCES[name]
    for p in seq["prep"]:
        _prep(b, p)
    seen = len(_all_events(b))
    out: list[dict[str, Any]] = []
    for label, role, how, where, data in seq["steps"]:
        c = _client(b, role)
        if how == "api":
            r = _api(b, USERS[role][0]).post(where, json=data)
        else:
            action = where.split("|")[-1]
            r = c.post(action, data={"csrf": _csrf(c.get("/account").text), **data}, follow_redirects=False)
        events = _all_events(b)
        step: dict[str, Any] = {
            "step": label,
            "status": r.status_code,
            "location": r.headers.get("location", ""),
            "events": [_event(e) for e in events[seen:]],
            "stored": _stored(b, name),
        }
        if how == "api" and r.status_code == 200:
            step["body"] = _clean(r.json())
        seen = len(events)
        out.append(step)
    return out


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_the_form_behaves_as_on_master(
    request: pytest.FixtureRequest, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if SEQUENCES[name]["japan"]:
        monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
        monkeypatch.setenv("TB_SITE_ID", "SAMPLE-A")
    b = request.getfixturevalue("box")
    got = _run(b, name)
    capture = os.environ.get("TB_9K6B_CAPTURE")
    if capture:
        path = Path(capture)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = got
        path.write_text(json.dumps(dict(sorted(data.items())), indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        return
    want = json.loads(DATA.read_text())[name]
    assert [s["step"] for s in got] == [s["step"] for s in want]
    for g, w in zip(got, want, strict=True):
        assert g["status"] == w["status"], (name, g["step"], "status")
        assert g["location"] == w["location"], (name, g["step"], "where it goes")
        assert g["events"] == w["events"], (name, g["step"], "audit events")
        assert g["stored"] == w["stored"], (name, g["step"], "stored result")
        assert g.get("body") == w.get("body"), (name, g["step"], "api body")
