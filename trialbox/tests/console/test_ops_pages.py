"""D-178 (review J-09, J-14; WS-08.5, WS-14.7): the administrator's operations screens and the confirmations and undos
of the destructive actions. D-179 (review J-06): the site set-up pages are site-wide; a study-scoped account sees
its studies' readiness only.

Each test fails on the code before D-178/D-179: the routes, the undo actions and the scope rule did not exist."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from console.app import create_app
from console.auth import UserStore
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from markupsafe import escape
from tb_common.audit import AuditLog
from tb_common.authz import ADMIN_ACTIONS, ROLE_ADMIN_ACTIONS, admin_allowed

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    PILOT_ENV,
    FakeBackend,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
)
from tests.console.test_site_setup_pages import PW as SB_PW
from tests.console.test_site_setup_pages import _csrf, sb  # noqa: F401 - the fixture is used by name
from tools.trialbox import backup as bkp
from tools.trialbox import ops as tb_ops
from tools.trialbox import svc_secrets

PW = "operations-password-0001"
ROLES = ("coordinator", "investigator", "viewer", "cro")


def _events(audit_dir: Path, name: str) -> list[dict[str, Any]]:
    out = [json.loads(x) for f in sorted(audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
    return [e for e in out if e.get("event") == name]


@pytest.fixture
def ob(tmp_path: Path) -> dict[str, Any]:
    """A console whose operations run in this process (TB_OPS_RUNNER=inline): a real backup key, two backup
    targets, a data folder, the test's own database, service tokens in a deploy folder."""
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    svc_secrets.init(deploy, uid=None)
    priv, pub = tmp_path / "usb" / "backup.key", deploy / "secrets" / "backup.pub"
    bkp.keygen(priv, pub)
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_text("hello\n")
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    audit = AuditLog(backend.audit_dir)
    users = UserStore()
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    for role in ROLES:
        users.create(role[:5], role, PW, f"{role[:5]}@hospa.test")  # type: ignore[arg-type]
    env = {
        **PILOT_ENV,
        "TB_CONSOLE_DIR": str(tmp_path / "console"),
        "TB_OPS_DIR": str(tmp_path / "ops"),
        "TB_OPS_RUNNER": "inline",
        "TB_OPS_DEPLOY": str(deploy),
        "TB_BACKUP_TARGETS": f"{tmp_path / 'nas'} {tmp_path / 'usbdisk'}",
        "TB_BACKUP_PUBKEY": str(pub),
        "TB_BACKUP_DIRS": f"data={data}",
        "TB_DB_URL": os.environ["TB_DB_URL"],
        "TB_SITE_ID": "TEST",
    }
    app = create_app(env, backend=backend, audit=audit, users=users)
    return {"app": app, "audit": tmp_path / "audit", "users": users, "dir": tmp_path, "deploy": deploy,
            "priv": priv}  # fmt: skip


# ---------------------------------------------------------------------------------------------- the role table
def test_the_role_table_gives_operations_to_the_administrator_only() -> None:
    assert ROLE_ADMIN_ACTIONS["admin"] == frozenset(ADMIN_ACTIONS)
    for role in (*ROLES, "steward", "", "root"):
        assert not any(admin_allowed(role, a) for a in ADMIN_ACTIONS), role


@pytest.mark.parametrize("role", ROLES)
def test_every_operations_page_and_action_is_refused_to_other_roles(ob: dict[str, Any], role: str) -> None:
    c, csrf = login(ob["app"], role[:5], PW)
    for path in ("/admin/ops", "/admin/ops?tab=secrets", "/admin/ops/network/network-sheet.en.html"):
        assert c.get(path).status_code == 403, (role, path)
    for action in ("backup", "backup_check", "update_check", "update_apply", "logs_collect", "network_sheet"):
        r = c.post(f"/admin/ops/{action}", data={"csrf": csrf, "confirm": "yes", "bundle": "x.tar"})
        assert r.status_code == 403, (role, action)
    tok = c.post("/api/v1/session", json={"username": role[:5], "password": PW}).json()["token"]
    assert c.get("/api/v1/admin/ops", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    assert not (ob["dir"] / "ops" / "requests").exists() or not list((ob["dir"] / "ops" / "requests").glob("*"))
    denied = [e["detail"]["action"] for e in _events(ob["audit"], "console.denied")]
    assert "/admin/ops" in denied and "/admin/ops/backup" in denied and "/api/v1/admin/ops" in denied
    assert not _events(ob["audit"], "console.ops")


# ---------------------------------------------------------------------------------------------- backups
def test_backup_asks_first_then_runs_is_audited_and_checked(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    page = c.get("/admin/ops")
    assert page.status_code == 200 and 'data-testid="ops-backup-age"' in page.text
    assert "no backup yet" in page.text  # red: nothing yet
    r = c.post("/admin/ops/backup", data={"csrf": csrf})  # no confirmation: the sheet, nothing done
    assert 'data-testid="confirm-text"' in r.text and "services keep running" in r.text  # D-455: nothing stops
    assert 'href="/admin/ops?tab=backups" data-testid="confirm-no"' in r.text
    assert not list((ob["dir"] / "nas").glob("*")) if (ob["dir"] / "nas").exists() else True
    assert not _events(ob["audit"], "console.ops")
    r = c.post("/admin/ops/backup", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/ops?tab=backups&req=")
    files = sorted(p.name for p in (ob["dir"] / "nas").glob("*.tbbak"))
    assert len(files) == 1 and (ob["dir"] / "usbdisk" / files[0]).is_file()
    assert bkp.verify(ob["dir"] / "nas" / files[0], ob["priv"])["ok"]  # a real backup, opened by the key
    page = c.get(r.headers["location"]).text
    assert 'data-state="done"' in page and 'data-testid="ops-result">done' in page and files[0] in page
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert [e["action"] for e in ev] == ["backup", "backup.done"] and ev[1]["ok"] is True
    assert all(e["actor"] == "console:admin" for e in _events(ob["audit"], "console.ops"))
    # the check, without the key: complete in both targets
    r = c.post("/admin/ops/backup_check", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=True)
    assert 'data-state="done"' in r.text and "complete in every target" in r.text
    over = c.get("/admin/ops").text
    assert 'class="pill ok" data-testid="ops-backup-age"' in over  # green: a backup within 36 hours
    health = c.get("/admin?tab=health").text  # the health tab's Operations tile
    assert 'data-testid="tile-ops"' in health and 'class="pill ok" data-testid="tile-ops-backup"' in health
    # a cut file fails the check, and the page says so
    f = ob["dir"] / "usbdisk" / files[0]
    f.write_bytes(f.read_bytes()[:-10])
    r = c.post("/admin/ops/backup_check", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=True)
    assert 'data-testid="ops-result">failed' in r.text and "cut short" in r.text


def test_secrets_are_listed_by_name_and_never_shown(ob: dict[str, Any]) -> None:
    c, _ = login(ob["app"])
    values = [p.read_text().strip() for p in (ob["deploy"] / "secrets").glob("*.token")]
    values += [p.read_text().strip() for p in (ob["deploy"] / "secrets").glob("*") if p.is_file()]
    assert values
    page = c.get("/admin/ops?tab=secrets").text
    assert 'data-secret="orchestrator"' in page and 'data-secret="console"' in page
    tok = c.post("/api/v1/session", json={"username": "admin", "password": ADMIN_PW}).json()["token"]
    api = c.get("/api/v1/admin/ops", headers={"Authorization": f"Bearer {tok}"}).text
    status = (ob["dir"] / "ops" / "status.json").read_text()
    for v in values:
        for line in v.splitlines():
            if len(line) >= 16:
                assert line not in page and line not in api and line not in status
    rows = json.loads(api)["status"]["secrets"]
    assert rows and all(set(r) <= {"name", "present", "age_days", "registered"} for r in rows)


def test_update_check_and_apply_ask_first_and_apply_is_refused_off_a_site_box(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    inc = ob["deploy"] / "updates" / "incoming"
    inc.mkdir(parents=True)
    (inc / "trialbox-1.0.1.tar").write_bytes(b"not a real bundle")
    page = c.get("/admin/ops?tab=update").text
    assert "trialbox-1.0.1.tar" in page and 'data-testid="ops-update_apply-trialbox-1.0.1.tar"' in page
    r = c.post("/admin/ops/update_apply", data={"csrf": csrf, "bundle": "trialbox-1.0.1.tar"})
    assert 'data-testid="confirm-text"' in r.text and "rolls back" in r.text
    assert 'name="bundle" value="trialbox-1.0.1.tar"' in r.text  # the sheet posts the same bundle again
    assert c.post("/admin/ops/update_apply", data={"csrf": csrf, "bundle": "../x"}).status_code == 400
    r = c.post("/admin/ops/update_apply", data={"csrf": csrf, "bundle": "trialbox-1.0.1.tar", "confirm": "yes"},
               follow_redirects=True)  # fmt: skip
    assert 'data-testid="ops-result">failed' in r.text and "site box only" in r.text
    ev = [e["detail"] for e in _events(ob["audit"], "console.ops")]
    assert ev[0] == {"action": "update_apply", "request": ev[0]["request"], "bundle": "trialbox-1.0.1.tar"}


def test_network_sheet_written_and_downloaded_in_three_languages(ob: dict[str, Any]) -> None:
    c, csrf = login(ob["app"])
    assert 'data-testid="ops-sheets-none"' in c.get("/admin/ops?tab=network").text
    r = c.post("/admin/ops/network_sheet", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=True)
    assert 'data-state="done"' in r.text
    for lang in ("en", "ja", "zh-TW"):
        r = c.get(f"/admin/ops/network/network-sheet.{lang}.html")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "8090" in r.text
    assert c.get("/admin/ops/network/..%2Fstatus.json").status_code == 404
    downloads = [
        e["detail"] for e in _events(ob["audit"], "console.ops") if e["detail"]["action"] == "network_download"
    ]
    assert len(downloads) == 3


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_operations_pages_in_three_languages(ob: dict[str, Any], lang: str) -> None:
    c, csrf = login(ob["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    for tab in ("overview", "backups", "update", "logs", "secrets", "network"):
        page = c.get(f"/admin/ops?tab={tab}").text
        assert str(escape(CATALOGUES[lang][f"ops.tab.{tab}"])) in page
        assert not re.search(r"\bops\.[a-z_]+\.[a-z_.]+\b", page.split("<main", 1)[-1]), tab  # no raw key


# ---------------------------------------------------------------------------------------------- J-14: accounts
def test_reset_asks_first_and_disable_has_an_undo(box: dict[str, Any]) -> None:  # noqa: F811
    box["users"].create("nurse.lin", "coordinator", PW, "lin@hospa.test")
    c, csrf = login(box["app"])
    n, _ = login(box["app"], "nurse.lin", PW)
    r = c.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "nurse.lin"})
    assert 'data-testid="confirm-text"' in r.text and "cannot be undone" in r.text
    assert n.get("/home", follow_redirects=False).status_code == 200  # not reset yet: still signed in
    r = c.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "nurse.lin", "confirm": "yes"},
               follow_redirects=True)  # fmt: skip
    assert 'data-testid="users-undo"' in r.text and "nurse.lin is disabled" in r.text
    assert 'data-disabled-user="nurse.lin"' in r.text
    t = TestClient(box["app"])
    tok = re.search(r'name="login_csrf" value="([^"]+)"', t.get("/login").text)
    assert tok
    r = t.post("/login", data={"username": "nurse.lin", "password": PW, "login_csrf": tok.group(1)})
    assert r.status_code == 401  # a disabled account cannot sign in
    r = c.post("/ops/users", data={"csrf": csrf, "action": "enable", "username": "nurse.lin", "confirm": "undo"},
               follow_redirects=True)  # fmt: skip
    assert 'data-testid="users-done"' in r.text and 'data-user="nurse.lin"' in r.text
    login(box["app"], "nurse.lin", PW)  # the old password works again
    acts = [(e["detail"]["action"], e["detail"].get("undo")) for e in _events(box["dir"] / "audit", "console.user")]
    assert acts[-2:] == [("disable", None), ("enable", True)]
    assert c.post("/ops/users", data={"csrf": csrf, "action": "enable", "username": "nurse.lin"}).status_code == 400
    # nobody but the administrator enables an account
    box["users"].create("crc9", "coordinator", PW)
    k, kcsrf = login(box["app"], "crc9", PW)
    assert k.post("/ops/users", data={"csrf": kcsrf, "action": "enable", "username": "nurse.lin"}).status_code == 403


# ---------------------------------------------------------------------------------------------- J-14: facts
def test_reject_asks_first_and_every_fact_decision_can_be_undone(sb: dict[str, Any]) -> None:  # noqa: F811
    from sitesetup import help as site_help

    c, _ = login(sb["app"], "crc", SB_PW)
    page = c.get("/site?study=GZQO").text
    no, text = site_help.PRACTICE_CHARTS[0]
    c.post("/site/charts", data={"csrf": _csrf(page), "ws": "main", "study": "GZQO", "chart_no": no, "text": text})
    r = c.get("/site/facts?study=GZQO")
    fids = re.findall(r'data-testid="confirm-(\d+)"', r.text)
    form = {"csrf": _csrf(page), "ws": "main", "study": "GZQO"}
    # Reject: the sheet first, nothing changes
    r = c.post(f"/site/facts/{fids[0]}", data={**form, "action": "reject"})
    assert 'data-testid="confirm-text"' in r.text and "will not count" in r.text
    assert sb["svc"].store.fact(int(fids[0]))["status"] == "proposed"
    r = c.post(f"/site/facts/{fids[0]}", data={**form, "action": "reject", "confirm": "yes"})
    assert sb["svc"].store.fact(int(fids[0]))["status"] == "rejected"
    assert 'data-testid="fact-undo"' in r.text
    r = c.post(f"/site/facts/{fids[0]}", data={**form, "action": "undo"})
    assert "waiting for a decision again" in r.text and sb["svc"].store.fact(int(fids[0]))["status"] == "proposed"
    # Confirm is one tap (no sheet), with an Undo
    r = c.post(f"/site/facts/{fids[1]}", data={**form, "action": "confirm"})
    assert 'data-testid="fact-undo"' in r.text and sb["svc"].store.fact(int(fids[1]))["status"] == "confirmed"
    # a correction undone puts the model's own value back
    demo = next(f for f in sb["svc"].store.facts("main") if f["domain"] == "demographic" and f["status"] == "proposed")
    before = demo["value"]
    c.post(f"/site/facts/{demo['id']}", data={**form, "action": "correct", "value": "1961-04-04"})
    assert sb["svc"].store.fact(demo["id"])["value"] != before or before == "1961-04-04"
    c.post(f"/site/facts/{demo['id']}", data={**form, "action": "undo"})
    after = sb["svc"].store.fact(demo["id"])
    assert after["status"] == "proposed" and after["value"] == before and after["before"] is None
    # nothing to undo on a proposed fact: refused with a reason, nothing changes
    r = c.post(f"/site/facts/{demo['id']}", data={**form, "action": "undo"})
    assert 'data-testid="fact-err"' in r.text
    acts = [e["detail"]["action"] for e in _events(sb["dir"] / "audit", "console.site_fact")]
    assert acts.count("undo") == 2 and "reject" in acts


# ---------------------------------------------------------------------------------------------- J-14: outcomes
def test_a_closing_outcome_asks_first_and_an_outcome_can_be_undone(box: dict[str, Any]) -> None:  # noqa: F811
    a = "a" * 32
    _done_screen(box["backend"], _ulid(971))
    for name, role in (("crc1", "coordinator"), ("drsato", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(box["app"], "drsato", PW)
    pp = pi.get(f"/studies/GZQO/patients/{a}").text
    pi.post(f"/studies/GZQO/patients/{a}/mark", data={"csrf": _csrf(pp), "mark": "approach"})
    crc, _ = login(box["app"], "crc1", PW)
    page = crc.get(f"/studies/GZQO/patients/{a}").text
    r = crc.post(f"/studies/GZQO/patients/{a}/outcome", data={"csrf": _csrf(page), "outcome": "reached_declined"})
    assert 'data-testid="confirm-text"' in r.text and "declined" in r.text
    assert not _events(box["dir"] / "audit", "console.contact_outcome")
    r = crc.post(f"/studies/GZQO/patients/{a}/outcome",
                 data={"csrf": _csrf(page), "outcome": "reached_declined", "confirm": "yes"}, follow_redirects=True)  # fmt: skip
    assert 'data-testid="outcome-undo"' in r.text
    assert box["backend"].registry[("GZQO", a)].status == "declined"
    r = crc.post(f"/studies/GZQO/patients/{a}/outcome", data={"csrf": _csrf(page), "outcome": "undo"},
                 follow_redirects=True)  # fmt: skip
    assert r.status_code == 200 and "contact outcome is taken back" in r.text
    assert box["backend"].registry[("GZQO", a)].status == "candidate"
    ev = [e["detail"] for e in _events(box["dir"] / "audit", "console.contact_outcome")]
    assert ev[-1]["action"] == "undo" and ev[-1]["undo"] == "reached_declined"
    # an outcome that does not end the contact is one tap; another person cannot undo it
    r = crc.post(f"/studies/GZQO/patients/{a}/outcome", data={"csrf": _csrf(page), "outcome": "not_reached"})
    assert r.status_code == 200 and 'data-testid="confirm-text"' not in r.text
    box["users"].create("crc2", "coordinator", PW)
    other, _ = login(box["app"], "crc2", PW)
    r = other.post(f"/studies/GZQO/patients/{a}/outcome", data={"csrf": _csrf(other.get("/home").text),
                                                                 "outcome": "undo"})  # fmt: skip
    assert r.status_code == 409


# ---------------------------------------------------------------------------------------------- D-179 (J-06)
def test_site_pages_are_site_wide_and_a_scoped_account_sees_readiness_only(sb: dict[str, Any]) -> None:  # noqa: F811
    sb["users"].create("smo", "coordinator", SB_PW, "smo@hospa.test")
    sb["users"].set_scope("smo", "smo", "GZQO", None)
    c, _ = login(sb["app"], "smo", SB_PW)
    r = c.get("/site?study=GZQO")
    assert r.status_code == 200 and 'data-testid="site-scoped"' in r.text and 'data-testid="site-start"' not in r.text
    assert 'href="/site/facts' not in r.text and 'href="/site/charts' not in r.text
    assert c.get("/site/help?study=GZQO").status_code == 200
    for path in ("/site/charts", "/site/facts", "/site/codes", "/site/checks", "/site/sheets", "/site/people",
                 "/site/patients", "/site/start"):  # fmt: skip
        assert c.get(f"{path}?study=GZQO").status_code == 404, path
    tok = c.post("/api/v1/session", json={"username": "smo", "password": SB_PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/v1/site/facts?ws=main", headers=hdr).status_code == 404
    assert c.get("/api/v1/site/codes?ws=main", headers=hdr).status_code == 404
    assert c.get("/api/v1/site/readiness?study=GZQO", headers=hdr).status_code == 200
    r = c.post("/api/v1/site/facts/1", json={"action": "confirm"}, headers=hdr)
    assert r.status_code == 404
    denied = [e["detail"] for e in _events(sb["dir"] / "audit", "console.denied")]
    assert any(d.get("reason") == "study scope" and d["action"] == "/site/facts" for d in denied)
    # the site-wide coordinator still opens every site page
    w, _ = login(sb["app"], "crc", SB_PW)
    for path in ("/site/charts", "/site/facts", "/site/patients"):
        assert w.get(f"{path}?study=GZQO").status_code == 200, path


# ---------------------------------------------------------------------------------------------- the runner itself
def test_the_runner_wraps_the_cli_and_writes_no_secret(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    svc_secrets.init(deploy, uid=None)
    (deploy / "updates" / "incoming").mkdir(parents=True)
    (deploy / "updates" / "incoming" / "b-1.tar").write_bytes(b"x")
    calls: list[list[str]] = []

    def fake(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return "verified\n"

    box_ = tb_ops.Box("compose", deploy, {}, fake)
    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(box_, ops)
    rid = ops.submit("update_check", "console:admin", {"bundle": "b-1.tar"})
    bad = ops.submit("update_check", "console:admin", {"bundle": "../../etc/passwd"})
    runner.run_pending()
    calls[:] = [c for c in calls if "exec" not in c]  # the audit events (tested below)
    assert calls == [["sh", str(tb_ops.ROOT / "tools" / "apply_update.sh"), str(deploy / "updates" / "incoming" /
                                                                                  "b-1.tar"), "--dry-run"]]  # fmt: skip
    good, refused, last = ops.result(rid), ops.result(bad), ops.last("update_check")
    assert good and refused and last
    assert good["ok"] is True and refused["ok"] is False
    assert ops.pending() == [] and last["id"] in (rid, bad)
    local = tb_ops.OpsRunner(tb_ops.Box.local(deploy, {}), ops)
    lr = ops.submit("logs_collect", "console:admin")
    local.run_pending()
    res = ops.result(lr)
    assert res and res["ok"] is False and "site box only" in res["summary"]
    status = (tmp_path / "ops" / "status.json").read_text()
    for p in (deploy / "secrets").glob("*.token"):
        assert p.read_text().strip() not in status
    st = json.loads(status)
    assert st["incoming"][0]["name"] == "b-1.tar" and st["version"]["trialbox"]
    with pytest.raises(tb_ops.OpsFailed):
        ops.submit("rm -rf", "x")


def test_on_a_site_box_the_check_and_the_sheet_run_in_a_container(tmp_path: Path) -> None:
    """The host's python3 has no zstandard or PyYAML: the check and the sheet run in a trialbox-py container."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / "trialbox-CGMH-20261109T010203Z.tbbak").write_bytes(b"x")
    calls: list[list[str]] = []

    def fake(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return '{"ok": true, "chunks": 1, "bytes": 1, "created_at": "2026-11-09T01:02:03+00:00", "sha256": "ab"}'

    box_ = tb_ops.Box("compose", deploy, {"TB_BACKUP_TARGETS": str(nas), "TB_IMAGE": "trialbox-py:9"}, fake)
    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(box_, ops)
    a = ops.submit("backup_check", "console:admin")
    b = ops.submit("network_sheet", "console:admin")
    runner.run_pending()
    calls[:] = [c for c in calls if "exec" not in c]  # the audit events (tested below)
    res_a, res_b = ops.result(a), ops.result(b)
    assert res_a and res_a["ok"] and res_b and res_b["ok"]
    assert calls[0][:4] == ["docker", "run", "--rm", "--network"] and calls[0][-3:] == [
        "tools.trialbox",
        "backup-check",
        "/b/trialbox-CGMH-20261109T010203Z.tbbak",
    ]
    assert "trialbox-py:9" in calls[1] and calls[1][-4:] == ["--env", "/app/deploy/.env", "--out", "/out/network-sheet"]
    assert "none" in calls[0] and "none" in calls[1]  # no network


def test_the_runner_takes_a_request_id_from_its_file_name_only(tmp_path: Path) -> None:
    """The console's folder is writable by the container; the runner is root on the host. An ``id`` field written
    into a request must not choose where the runner writes its result."""
    ops = tb_ops.OpsDir(tmp_path / "ops")
    (ops.root / "requests").mkdir(parents=True)
    stem = "20261110T000000Z-abcdef"
    req = {"id": "../../escaped", "action": "network_sheet", "by": "x", "at": "2026-11-10T00:00:00+00:00"}
    (ops.root / "requests" / f"{stem}.json").write_text(json.dumps(req), encoding="utf-8")
    assert [r["id"] for r in ops.pending()] == [stem]
    runner = tb_ops.OpsRunner(tb_ops.Box.local(tmp_path / "deploy", {}), ops)
    runner.run_one(ops.pending()[0])
    assert not (tmp_path / "escaped.json").exists()
    assert ops.result(stem) is not None and ops.pending() == []
    with pytest.raises(tb_ops.OpsFailed):
        ops.write_result({"id": "../x", "action": "backup"}, True, "", [], "")


def test_one_runner_at_a_time_and_no_link_or_pipe_is_read(tmp_path: Path) -> None:
    """A second runner (the timer while a hand-run ``ops run`` is busy) must not run the same request again; the
    runner is root and the console's user writes ``requests/``, so a link or a pipe there is skipped, never read."""
    import fcntl

    ops = tb_ops.OpsDir(tmp_path / "ops")
    rid = ops.submit("network_sheet", "console:admin")
    secret = tmp_path / "secret.txt"
    secret.write_text(json.dumps({"action": "network_sheet", "by": "x", "at": "2026"}), encoding="utf-8")
    (ops.root / "requests" / "20261110T000000Z-aaaaaa.json").symlink_to(secret)
    os.mkfifo(ops.root / "requests" / "20261110T000000Z-bbbbbb.json")
    assert [r["id"] for r in ops.pending()] == [rid]
    runner = tb_ops.OpsRunner(tb_ops.Box.local(tmp_path / "deploy", {}), ops)
    with open(ops.root / ".runner.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert runner.run_pending() == [] and ops.result(rid) is None  # the other runner has it
        fcntl.flock(held, fcntl.LOCK_UN)
    assert [r["id"] for r in runner.run_pending()] == [rid]
    assert not (ops.root / "results" / "20261110T000000Z-aaaaaa.json").exists()


def test_a_cut_off_or_old_request_is_never_run_again(tmp_path: Path) -> None:
    """A request that started and was cut off (a reboot during an update) has no result: the next round must not run
    it again without a new confirmation. A request that waited longer than MAX_AGE_MIN is not run either."""
    deploy = tmp_path / "deploy"
    (deploy / "updates" / "incoming").mkdir(parents=True)
    (deploy / "updates" / "incoming" / "b-1.tar").write_bytes(b"x")
    calls: list[list[str]] = []

    def fake(argv: Any, timeout: int | None) -> str:
        calls.append(list(argv))
        return "ok\n"

    ops = tb_ops.OpsDir(tmp_path / "ops")
    runner = tb_ops.OpsRunner(tb_ops.Box("compose", deploy, {}, fake), ops)
    cut = ops.submit("update_apply", "console:admin", {"bundle": "b-1.tar"})
    ops.marker(cut).parent.mkdir(parents=True, exist_ok=True)
    ops.marker(cut).write_text(json.dumps({"id": cut, "started": "2026-11-10T01:00:00+00:00"}), encoding="utf-8")
    assert [r["id"] for r in ops.running()] == [cut]
    old = ops.submit("update_check", "console:admin", {"bundle": "b-1.tar"})
    t = (tmp_path / "ops" / "requests" / f"{old}.json").stat().st_mtime - (tb_ops.MAX_AGE_MIN * 60 + 5)
    os.utime(tmp_path / "ops" / "requests" / f"{old}.json", (t, t))
    fresh = ops.submit("update_check", "console:admin", {"bundle": "b-1.tar"})
    runner.run_pending()
    r_cut, r_old, r_fresh = ops.result(cut), ops.result(old), ops.result(fresh)
    assert r_cut and r_cut["state"] == "interrupted" and r_cut["ok"] is False
    assert r_old and r_old["state"] == "expired" and r_old["ok"] is False
    assert r_fresh and r_fresh["state"] == "done" and not ops.marker(fresh).exists()
    applied = [c for c in calls if "apply_update.sh" in " ".join(c)]
    assert len(applied) == 1 and "--dry-run" in applied[0]  # only the fresh check ran; never the cut-off apply
    # each finished request is a console.ops event in the box's audit chain, written inside the orchestrator
    audits = [json.loads(c[-1]) for c in calls if "exec" in c and "orchestrator" in c]
    assert [(x["request"], x["state"]) for x in audits] == [(cut, "interrupted"), (old, "expired"), (fresh, "done")]
    runner.run_pending()
    assert len([c for c in calls if "apply_update.sh" in " ".join(c)]) == 1  # nothing ran again


def test_a_stale_target_fails_the_check_and_a_failed_update_says_so(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "updates").mkdir(parents=True)
    nas, usb = tmp_path / "nas", tmp_path / "usb"
    for t, stamp in ((nas, "20261109T010203Z"), (usb, "20261101T010203Z")):
        t.mkdir()
        (t / f"trialbox-CGMH-{stamp}.tbbak").write_bytes(b"x")

    def fake(argv: Any, timeout: int | None) -> str:
        return '{"ok": true, "chunks": 1, "bytes": 1, "created_at": "2026-11-09T01:02:03+00:00", "sha256": "ab"}'

    box_ = tb_ops.Box("compose", deploy, {"TB_BACKUP_TARGETS": f"{nas} {usb}"}, fake)
    ops = tb_ops.OpsDir(tmp_path / "ops")
    rid = ops.submit("backup_check", "console:admin")
    tb_ops.OpsRunner(box_, ops).run_pending()
    res = ops.result(rid)
    assert res and res["ok"] is False and "missed a backup" in res["summary"]
    lines = [{"bundle": "b-2", "step": "verify", "ok": True, "at": "2026-11-10T01:00:00+00:00"},
             {"bundle": "b-2", "step": "load images", "ok": False, "at": "2026-11-10T01:01:00+00:00"}]  # fmt: skip
    (deploy / "updates" / "history.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert tb_ops.snapshot(box_)["updates"][0]["outcome"] == "failed"


def test_an_outcome_undo_the_registry_refused_is_put_back() -> None:
    from console.sitestore import Outcome, SiteStore

    store = SiteStore()
    try:
        pid = "pid0undo01"
        store.add_outcome("UNDO1", Outcome(pid, "reached_declined", None, None, "crc1", "2026-11-10T09:00:00"),
                          prev_status="contacted")  # fmt: skip
        assert store.undo_outcome("UNDO1", pid, "crc2", "2026-11-10T09:01:00") is None  # only one's own
        got = store.undo_outcome("UNDO1", pid, "crc1", "2026-11-10T09:02:00")
        assert got is not None and got[1] == "contacted" and store.outcomes("UNDO1", pid) == []
        store.restore_outcome("UNDO1", got[0], "2026-11-10T09:02:00")
        assert [o.outcome for o in store.outcomes("UNDO1", pid)] == ["reached_declined"]
    finally:
        store.close()


def test_the_backups_tile_shows_the_last_restore_drill_and_the_command_to_type(ob: dict[str, Any]) -> None:
    """T-730d (D-892): the drill runs on the host with the key; the page shows its last result from the box's
    key-check record and the exact command, with the newest backup's path, never a key path."""
    from tb_common import metrics

    c, csrf = login(ob["app"])
    c.post("/admin/ops/backup", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    newest = sorted((ob["dir"] / "nas").glob("*.tbbak"))[-1]
    page = c.get("/admin/ops?tab=backups").text
    assert 'data-testid="ops-drill-cmd"' in page and "restore-drill" in page and newest.name in page
    assert "none yet" in page and str(ob["priv"]) not in page
    metrics.record_drill(ob["deploy"], {"ok": True, "at": "2026-11-16T01:00:00+00:00", "file": newest.name,
                                        "databases": {"trialbox_wf": {"tables": 3, "rows": 5}}})  # fmt: skip
    c.post("/admin/ops/backup_check", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)  # a new status
    tile = c.get("/admin/ops").text
    drill = tile[tile.index('data-testid="ops-drill"') :][:400]
    assert "passed" in drill and 'class="pill ok"' in drill
    metrics.record_drill(ob["deploy"], {"ok": False, "at": "2026-11-16T02:00:00+00:00", "file": newest.name,
                                        "error": "pg_restore failed"})  # fmt: skip
    c.post("/admin/ops/backup_check", data={"csrf": csrf, "confirm": "yes"}, follow_redirects=False)
    tile = c.get("/admin/ops").text
    drill = tile[tile.index('data-testid="ops-drill"') :][:400]
    assert "failed" in drill and 'class="pill bad"' in drill
