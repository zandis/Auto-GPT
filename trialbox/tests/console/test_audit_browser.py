"""T-211c (D-451, ROLE-013): the audit browser of the privacy office and the steward.

* only ``audit.browse`` (privacy office, steward) opens the browser, one patient's report, its file and the
  verification; a coordinator, an investigator, the administrator, a viewer and a CRO account get 403, audited;
* one patient's reveals in two steps: the pseudonym in the patient box, then its report lists every reveal, refusal,
  break-glass use, export and download that names it, and nothing of another patient; no chart number is added;
* reading is audited with the filter, not the result; the file goes through the same guard and is audited;
* filters and the cursor run in the reader: every event is reached page by page, past the old 1,000-event horizon;
* "verify" shows the chain state, the last signed head and each off-box anchor folder's newest head, and a changed
  line turns it to FAIL;
* every event name the code writes has a label in en, ja and zh-TW (a walk of the code's event literals)."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from console import audit_page, i18n_audit
from tb_common.crypto import ed25519_generate

from tests.console.test_console_app import ADMIN_PW, box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _csrf, _user

ROOT = Path(__file__).resolve().parents[2]
A, B = "a1" * 16, "b2" * 16
CHART = "70000054"


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(b["audit"].directory).glob("*.jsonl")):
        for line in f.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("event") == name:
                out.append(rec)
    return out


def _seed(b: dict[str, Any]) -> None:
    """One patient's trail as D-438, D-430 and the export writers record it, and another patient's."""
    au = b["audit"]
    base = {"role": "coordinator", "affiliation": "hospital", "study": "GZQO"}
    au.append("console.reveal_patient", actor="console:crc1", ruleset="GZQO", job_id="01J0000000000000000000000A",
              detail={**base, "pid": A, "purpose": "contact", "reason": "screening_call", "via": "patient_page",
                      "basis": "role", "cap": "1/60"})  # fmt: skip
    au.append("console.reveal_refused", actor="console:pi1", ruleset="GZQO",
              detail={**base, "pid": A, "purpose": "contact", "reason": "", "via": "api", "refused": "delegation"})  # fmt: skip
    au.append("console.breakglass_use", actor="console:admin", ruleset="GZQO",
              detail={"grant": 7, "reason": "=HYPERLINK(\"x\")", "kind": "patient", "what": "patient", "pid": A})  # fmt: skip
    au.append("console.data_export", actor="console:crc1", ruleset="GZQO", detail={"pids": [A, B], "format": "xlsx"})
    au.append("console.download", actor="console:crc1", detail={"filename": f"list-{A[:8]}.xlsx", "pid": A})
    au.append("console.reveal_patient", actor="console:crc2", ruleset="GZQO",
              detail={**base, "pid": B, "purpose": "contact", "reason": "screening_call", "via": "patient_page",
                      "basis": "role", "cap": "2/60"})  # fmt: skip
    au.append("console.login", actor="console:crc1")


def _dpo(b: dict[str, Any]) -> Any:
    return _user(b, "dpo", "privacy")


# ---------------------------------------------------------------------------------------------- who
@pytest.mark.parametrize("role", ["coordinator", "investigator", "admin", "viewer", "cro"])
def test_only_the_privacy_office_and_the_steward_open_the_audit(box: dict[str, Any], role: str) -> None:  # noqa: F811
    _seed(box)
    if role == "admin":
        c, csrf = login(box["app"], "admin", ADMIN_PW)
    else:
        scope = {"affiliation": "cro", "studies": "GZQO", "expires": "2099-12-31"} if role == "cro" else {}
        c = _user(box, f"u-{role}", role, **scope)
        csrf = ""
    before = len(_events(box, "console.denied"))
    for path in ("/audit", f"/audit?pid={A}", "/audit/patients", f"/audit/patients/{A}",
                 f"/audit/patients/{A}/report.csv"):  # fmt: skip
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 403, (role, path, r.status_code)
        assert "data-event=" not in r.text  # no event of the chain
    assert c.post("/audit/verify", data={"csrf": csrf}, follow_redirects=False).status_code == 403
    assert len(_events(box, "console.denied")) >= before + 6
    assert not _events(box, "console.audit_search") and not _events(box, "console.audit_report")
    home = c.get("/home").text if role != "cro" else ""
    assert 'href="/audit"' not in home


@pytest.mark.parametrize("role", ["privacy", "steward"])
def test_the_privacy_office_and_the_steward_read_it(box: dict[str, Any], role: str) -> None:  # noqa: F811
    _seed(box)
    c = _user(box, f"u-{role}", role)
    r = c.get("/audit")
    assert r.status_code == 200
    assert 'data-testid="audit-patient-form"' in r.text and 'data-testid="audit-verify-go"' in r.text
    assert 'href="/audit"' in c.get("/audit").text  # in the menu


# ---------------------------------------------------------------------------------------------- one patient
def test_one_patients_reveals_are_found_in_two_steps(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    dpo = _dpo(box)
    step1 = dpo.get("/audit")
    assert 'action="/audit/patients"' in step1.text
    step2 = dpo.get("/audit/patients", params={"pid": A})  # the patient box, followed to the report
    assert step2.status_code == 200 and step2.url.path == f"/audit/patients/{A}"
    rows = re.findall(r'<tr data-event="([^"]+)">', step2.text)
    assert sorted(rows) == sorted(["console.reveal_patient", "console.reveal_refused", "console.breakglass_use",
                                   "console.data_export", "console.download"])  # fmt: skip
    assert "crc2" not in step2.text  # B's reveal is not A's
    counts = dict(re.findall(r'data-kind="(\w+)" data-n="(\d+)"', step2.text))
    assert counts == {"reveal": "2", "breakglass": "1", "export": "2", "other": "0"}
    for word in ("contact", "screening_call", "patient_page", "delegation", "1/60"):  # what the events hold
        assert word in step2.text
    assert CHART not in step2.text


def test_the_report_names_no_chart_number_and_masks_one_in_the_chain(box: dict[str, Any]) -> None:  # noqa: F811
    box["audit"].append("console.request", actor="console:crc1", detail={"line": f"CASE GZQO mrn={CHART} pid={A}"})
    dpo = _dpo(box)
    page = dpo.get(f"/audit/patients/{A}").text
    assert 'data-event="console.request"' in page and CHART not in page


def test_a_chart_number_in_the_patient_box_is_not_searched_or_echoed(box: dict[str, Any]) -> None:  # noqa: F811
    dpo = _dpo(box)
    r = dpo.get("/audit/patients", params={"pid": CHART}, follow_redirects=False)
    assert r.status_code == 303 and CHART not in r.headers["location"]
    page = dpo.get(r.headers["location"]).text
    assert 'data-testid="audit-bad-pid"' in page and CHART not in page
    assert dpo.get(f"/audit/patients/{CHART}").status_code == 404
    assert all("pid" not in e.get("detail", {}) for e in _events(box, "console.audit_search"))


def test_reading_is_audited_with_the_filter_not_the_result(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    dpo = _dpo(box)
    dpo.get("/audit", params={"kind": "reveal", "who": "crc1", "since": "2020-01-01"})
    dpo.get(f"/audit/patients/{A}")
    dpo.get(f"/audit/patients/{A}/report.csv")
    s = _events(box, "console.audit_search")[-1]
    assert s["actor"] == "console:dpo"
    assert s["detail"] == {"kind": "reveal", "who": "crc1", "from": "2020-01-01"}
    reps = _events(box, "console.audit_report")
    assert [e["detail"] for e in reps] == [{"pid": A, "format": "page"}, {"pid": A, "format": "csv"}]


def test_the_report_file_is_guarded_audited_and_safe_in_a_spreadsheet(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    crc = _user(box, "crc9", "coordinator")
    assert crc.get(f"/audit/patients/{A}/report.csv").status_code == 403
    r = _dpo(box).get(f"/audit/patients/{A}/report.csv", params={"kind": "reveal"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf")  # the byte order mark: Excel reads the file as UTF-8
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert {x["event"] for x in rows} == {"console.reveal_patient", "console.reveal_refused"}
    assert {x["pid"] for x in rows} == {A}
    every = list(
        csv.DictReader(io.StringIO(_dpo_again(box).get(f"/audit/patients/{A}/report.csv").content.decode("utf-8-sig")))
    )
    bg = next(x for x in every if x["event"] == "console.breakglass_use")
    assert bg["reason"].startswith("'=")  # a formula is written as text
    assert bg["label"] == "Break-glass grant used"


def _dpo_again(b: dict[str, Any]) -> Any:
    return login(b["app"], "dpo", PW)[0]


def test_labels_follow_the_page_language(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    dpo = _dpo(box)
    for lang, word in (("ja", "カルテ番号の表示"), ("zh-TW", "顯示病歷號"), ("en", "Chart number shown")):
        dpo.post("/lang", data={"csrf": _csrf(dpo.get("/audit").text), "lang": lang, "back": "/audit"})
        page = dpo.get(f"/audit/patients/{A}").text
        assert word in page, lang
        assert "console.reveal_patient" in page  # the code stays beside the label


# ---------------------------------------------------------------------------------------------- filters and cursor
def test_filters_and_the_cursor_reach_every_event(box: dict[str, Any]) -> None:  # noqa: F811
    for i in range(1100):  # past the old horizon of 20 pages of 50
        box["audit"].append("console.login", actor=f"console:u{i}")
    _seed(box)
    dpo = _dpo(box)
    seen, url, pages = 0, "/audit?event=console.login", 0
    while url:
        page = dpo.get(url).text
        seen += page.count('<tr data-event="console.login">')
        assert '<tr data-event="console.reveal_patient">' not in page
        m = re.search(r'href="(/audit\?[^"]*before=[^"]+)" rel="next"', page)
        url = m.group(1).replace("&amp;", "&") if m else ""
        pages += 1
    assert seen >= 1101 and pages == -(-seen // audit_page.PAGE)
    who = dpo.get("/audit", params={"who": "crc2"}).text
    assert re.findall(r'<tr data-event="([^"]+)">', who) == ["console.reveal_patient"]
    assert 'data-testid="audit-none"' in dpo.get("/audit", params={"since": "2999-01-01"}).text
    kind = re.findall(r'<tr data-event="([^"]+)">', dpo.get("/audit", params={"kind": "breakglass"}).text)
    assert kind == ["console.breakglass_use"]


def test_the_reader_skips_day_files_outside_the_period(tmp_path: Path) -> None:
    (tmp_path / "2026-01-01.jsonl").write_text('{"event":"console.login","ts":"2026-01-01T00:00:00+08:00"}\n')
    (tmp_path / "2026-01-02.jsonl").write_bytes(b"\xff\xfe not text")  # would fail to decode if it were opened
    (tmp_path / "2026-01-03.jsonl").write_text('{"event":"console.logout","ts":"2026-01-03T00:00:00+08:00"}\n')
    f = audit_page.make_filter(until="2026-01-01")
    rows, nxt = audit_page.search(tmp_path, f)
    assert [r.event for r in rows] == ["console.login"] and nxt == ""
    rows, _ = audit_page.search(tmp_path, audit_page.make_filter(since="2026-01-03"))
    assert [r.event for r in rows] == ["console.logout"]


# ---------------------------------------------------------------------------------------------- verify
def test_verify_shows_the_chain_state_and_a_changed_line_fails(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    dpo = _dpo(box)
    csrf = _csrf(dpo.get("/audit").text)
    page = dpo.post("/audit/verify", data={"csrf": csrf}).text
    assert 'data-ok="yes"' in page and 'data-testid="audit-verify-signed"' in page
    ev = _events(box, "console.audit_verify")[-1]
    assert ev["detail"]["ok"] is True and ev["detail"]["anchors"] == 0
    day = sorted(Path(box["audit"].directory).glob("*.jsonl"))[-1]
    lines = day.read_text().splitlines()
    i = next(n for n, x in enumerate(lines) if "console:crc1" in x)
    lines[i] = lines[i].replace("console:crc1", "console:crc7")
    day.write_text("\n".join(lines) + "\n")
    page = dpo.post("/audit/verify", data={"csrf": csrf}).text
    assert 'data-ok="no"' in page and "hash mismatch" in page
    assert dpo.post("/audit/verify", data={"csrf": "forged"}).status_code == 400


def test_verify_shows_the_last_signed_head_and_each_anchor_folder(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(box)
    share = box["dir"] / "share"
    share.mkdir()
    gone = box["dir"] / "not-mounted"
    monkeypatch.setenv("TB_AUDIT_ANCHOR_TARGETS", f"{share}:{gone}")
    priv, pub = ed25519_generate()
    head = box["audit"].sign_head(priv, pub, [share])
    dpo = _dpo(box)
    page = dpo.post("/audit/verify", data={"csrf": _csrf(dpo.get("/audit").text)}).text
    assert 'data-ok="yes"' in page
    signed = re.search(r'data-testid="audit-verify-signed">([^<]+)<', page)
    assert signed and f"event {head['lines']}" in signed.group(1) and head["key_id"][:16] in signed.group(1)
    assert "Anchor folder share: 1 signed heads" in page and "Anchor folder not-mounted: not reachable" in page
    v = audit_page.verify_now(Path(box["audit"].directory), [share])
    assert v["ok"] and v["signed"]["lines"] == head["lines"]


def test_verify_without_an_anchor_folder_says_so(tmp_path: Path) -> None:
    from tb_common.audit import AuditLog

    AuditLog(tmp_path / "a").append("console.login", actor="console:x")
    v = audit_page.verify_now(tmp_path / "a", [])
    assert v["ok"] and v["lines"] == 1 and v["say"] == ["no_anchor"] and v["signed"] is None


# ---------------------------------------------------------------------------------------------- labels
_CALLS = frozenset({"append", "audit", "_audit"})
_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
_NOT_EVENTS = re.compile(r"\.(?:py|json|jsonl|csv|xlsx|pdf|md|txt|yaml|yml|html|zip|log|key|pub)$")


def code_event_names() -> dict[str, str]:
    """Every event literal the code writes: the first argument of ``append``/``audit``/``_audit``, an ``"event": …``
    field of a dict, a value given to a name ``event``. Name -> first place found."""
    found: dict[str, str] = {}

    def keep(value: Any, where: str) -> None:
        if isinstance(value, str) and _NAME.match(value) and not _NOT_EVENTS.search(value):
            found.setdefault(value, where)

    for top in ("services", "libs", "tools"):
        for path in sorted((ROOT / top).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = str(path.relative_to(ROOT))
            for n in ast.walk(tree):
                where = f"{rel}:{getattr(n, 'lineno', 0)}"
                if isinstance(n, ast.Call):
                    f = n.func
                    name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                    if name in _CALLS and n.args and isinstance(n.args[0], ast.Constant):
                        keep(n.args[0].value, where)
                elif isinstance(n, ast.Dict):
                    for k, v in zip(n.keys, n.values, strict=True):
                        if isinstance(k, ast.Constant) and k.value == "event" and isinstance(v, ast.Constant):
                            keep(v.value, where)
                elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "event" for t in n.targets):
                    for c in ast.walk(n.value):
                        if isinstance(c, ast.Constant):
                            keep(c.value, where)
    return found


def test_every_event_the_code_writes_has_a_label() -> None:
    found = code_event_names()
    assert len(found) > 150  # the walk reached the writers
    assert {"console.reveal_patient", "console.breakglass_use", "audit.anchored", "console.audit_search"} <= set(found)
    missing = sorted(f"{name} ({where})" for name, where in found.items() if name not in i18n_audit.EVENTS)
    assert not missing, "event names with no label in console/i18n_audit.py EVENTS:\n" + "\n".join(missing)


def test_the_walk_fails_on_a_new_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check above is not empty by construction: a label removed is a failure."""
    trimmed = dict(i18n_audit.EVENTS)
    del trimmed["console.reveal_patient"]
    monkeypatch.setattr(i18n_audit, "EVENTS", trimmed)
    with pytest.raises(AssertionError, match="console.reveal_patient"):
        test_every_event_the_code_writes_has_a_label()


def test_every_label_in_three_languages() -> None:
    for table in (i18n_audit.EVENTS, i18n_audit.KEYS, i18n_audit.KINDS):
        for name, labels in table.items():
            assert len(labels) == 3 and all(x.strip() for x in labels), name
            assert labels[1] != labels[0] or not re.search(r"[a-z]{4}", labels[0]), name  # ja is not the English
    assert set(i18n_audit.EN) == set(i18n_audit.JA) == set(i18n_audit.ZH)
    assert set(audit_page.KINDS) | {"other"} == set(i18n_audit.KINDS)
    assert set(audit_page.SHOWN) <= set(i18n_audit.KEYS)
    assert i18n_audit.event_label("ja", "console.login") == "ログイン"
    assert i18n_audit.event_label("ja", "x.unknown") == "x.unknown"


def test_the_verify_api_twin_answers_the_same_and_is_guarded(box: dict[str, Any]) -> None:  # noqa: F811
    """FIT-019 (T-657): the verify button's /api/v1 twin, the session and the row before the body."""
    from fastapi.testclient import TestClient

    _seed(box)
    _user(box, "dpo", "privacy")
    _user(box, "crc5", "coordinator")

    def api(name: str) -> TestClient:
        tok, _ = box["users"].new_session(box["users"].get(name), via="api")
        return TestClient(box["app"], headers={"Authorization": f"Bearer {tok}"})

    assert TestClient(box["app"]).post("/api/v1/audit/verify", json={}).status_code == 401
    assert api("crc5").post("/api/v1/audit/verify", json={}).status_code == 403
    r = api("dpo").post("/api/v1/audit/verify", json={})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["lines"] > 5
    assert _events(box, "console.audit_verify")[-1]["actor"] == "console:dpo"
