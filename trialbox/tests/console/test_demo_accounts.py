"""T-505b: per-tester demo accounts (ROLE-004, OPS-002, UX-040, FIT-027, ROLE-008 seed half, LIFE-006), their
default language, TOTP enrolment codes, the seeded delegation log, and the persistence switch of ``tools.demo``."""

from __future__ import annotations

import os
import re
import stat
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from console.teamstore import TeamStore
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    _done_screen,
    _ulid,
    box,
    review_book,
)
from tools import demo

A = "a" * 32
NEW_PW = "tester-own-password-01"
# a PoC site: one tester's PI, sub-investigator and CRC on the demo study, a second investigator, the owner's admin
FILE: dict[str, Any] = {
    "accounts": [
        {"username": "tester1.pi", "name": "Tester One", "role": "investigator", "language": "ja",
         "expires": "2027-01-31", "delegation": [{"study": "GZQO", "role": "pi"}]},
        {"username": "tester1.subpi", "name": "Tester One (sub-I)", "role": "investigator", "language": "ja",
         "password_env": "TB_TEST_SUBPI_PW",
         "delegation": [{"study": "GZQO", "role": "sub_pi", "tasks": ["screen", "refer"]}]},
        {"username": "tester1.crc", "role": "coordinator", "language": "zh-TW",
         "delegation": [{"study": "gzqo", "role": "crc"}]},
        {"username": "tester2.pi", "role": "investigator", "language": "zh-TW",
         "delegation": [{"study": "GOUT-COH", "role": "pi"}]},
        {"username": "owner", "role": "admin", "language": "en"},
    ]
}  # fmt: skip


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _seed(b: dict[str, Any], totp: bool = False, env: dict[str, str] | None = None) -> dict[str, list[str]]:
    users = b["users"]
    return demo.seed_accounts(users, TeamStore(), demo.parse_accounts(FILE), today=date(2026, 10, 25),
                              now="2026-10-25T00:00:00+00:00", totp=totp, issued=b["dir"] / demo.ISSUED,
                              environ=env or {}, known_studies={"GZQO", "GOUT-COH"}, audit=b["audit"])  # fmt: skip


def _sign_in(app: Any, user: str, pw: str = NEW_PW) -> TestClient:
    c = TestClient(app)
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert tok
    r = c.post("/login", data={"username": user, "password": pw, "login_csrf": tok.group(1)}, follow_redirects=False)
    assert r.status_code == 303, (user, r.status_code)
    return c


def _issued(b: dict[str, Any]) -> list[list[str]]:
    return [ln.split("\t") for ln in (b["dir"] / demo.ISSUED).read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"password": "x" * 12}, "no passwords in the file"),
        ({"role": "doctor"}, "role must be one of"),
        ({"language": "fr"}, "language must be one of"),
        ({"username": "Bad Name"}, "username must be"),
        ({"role": "coordinator"}, "only an investigator account"),
        ({"delegation": [{"study": "GZQO", "role": "pi", "tasks": ["screen"]}]}, "the PI holds every task"),
        ({"delegation": [{"study": "GZQO", "role": "sub_pi", "tasks": ["approve"]}]}, "unknown task"),
        ({"expires": "31/01/2027"}, "expires must be"),
        ({"password_env": "lower-case"}, "environment variable name"),
    ],
)
def test_the_accounts_file_is_checked(change: dict[str, Any], message: str) -> None:
    row = {**FILE["accounts"][0], **change}
    with pytest.raises(demo.AccountsError, match=message):
        demo.parse_accounts({"accounts": [row]})


def test_the_accounts_file_has_one_pi_per_study_and_unique_names() -> None:
    two = dict(FILE["accounts"][0], username="tester9.pi")
    with pytest.raises(demo.AccountsError, match="two PIs"):
        demo.parse_accounts({"accounts": [FILE["accounts"][0], two]})
    with pytest.raises(demo.AccountsError, match="listed twice"):
        demo.parse_accounts({"accounts": [FILE["accounts"][0], FILE["accounts"][0]]})
    with pytest.raises(demo.AccountsError, match="non-empty"):
        demo.parse_accounts({"accounts": []})
    got = demo.parse_accounts(FILE)
    assert [a.scope for a in got] == ["GZQO", "GZQO", "GZQO", "GOUT-COH", ""]  # the log's studies scope the account


def test_each_tester_gets_own_account_password_and_enrolment_code(box: dict[str, Any]) -> None:  # noqa: F811
    users = box["users"]
    done = _seed(box, totp=True, env={"TB_TEST_SUBPI_PW": "subpi-from-the-env-01"})
    names = [a["username"] for a in FILE["accounts"]]
    assert done["created"] == names and done["enrol"] == names
    assert done["logged"] == ["tester1.pi@GZQO", "tester1.subpi@GZQO", "tester1.crc@GZQO", "tester2.pi@GOUT-COH"]
    path = box["dir"] / demo.ISSUED
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    issued = _issued(box)
    pw = {r[1]: r[3] for r in issued if r[2] == "password"}
    assert pw["tester1.subpi"] == "from $TB_TEST_SUBPI_PW"  # an environment password is never written down
    generated = [v for k, v in pw.items() if k != "tester1.subpi"]
    assert len(set(generated)) == len(generated) == 4  # separate passwords
    for name, secret in pw.items():
        real = "subpi-from-the-env-01" if name == "tester1.subpi" else secret
        assert users.authenticate(name, real) is not None, name
        assert users.must_change(name), name  # someone else set it: changed at the first sign-in (D-279)
    codes = {r[1]: r[3] for r in issued if r[2] == "enrolment code"}
    assert set(codes) == set(names) and all(users.check_enrol_code(n, c) for n, c in codes.items())
    pi = users.get("tester1.pi")
    assert pi is not None and pi.studies == ("GZQO",) and pi.expires == "2027-01-31"
    log = {e.username: e for e in TeamStore().entries("GZQO")}
    assert log["tester1.pi"].role == "pi" and log["tester1.pi"].end == "2027-01-31"
    assert log["tester1.subpi"].tasks == ("screen", "refer") and log["tester1.crc"].role == "crc"
    # a restart: nothing is created, logged or issued twice, and no password changes
    before = path.read_text(encoding="utf-8")
    again = _seed(box, totp=True, env={"TB_TEST_SUBPI_PW": "another-value-0001"})
    assert again == {"created": [], "logged": [], "enrol": []}
    assert path.read_text(encoding="utf-8") == before and len(TeamStore().entries("GZQO")) == 3
    assert users.authenticate("tester1.subpi", "subpi-from-the-env-01") is not None
    # the built-in shared-password accounts are switched off; the file's admin is kept
    assert demo.switch_off_builtin(users, {"owner"}) == ["admin", "viewer"]
    assert users.get("admin") is None and users.get("owner") is not None


def test_unknown_study_in_the_file_is_refused(box: dict[str, Any]) -> None:  # noqa: F811
    with pytest.raises(demo.AccountsError, match="no study GOUT-COH"):
        demo.seed_accounts(box["users"], TeamStore(), demo.parse_accounts(FILE), today=date(2026, 10, 25),
                           now="2026-10-25T00:00:00+00:00", totp=False, issued=box["dir"] / demo.ISSUED,
                           environ={}, known_studies={"GZQO"})  # fmt: skip
    assert box["users"].get("tester1.pi") is None  # checked before anything is created


def test_sub_investigator_is_refused_approach_and_approval_without_the_tick(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(971))
    _seed(box)
    for name in ("tester1.pi", "tester1.subpi"):
        box["users"].set_password(name, NEW_PW)  # the tester's own password (the forced change is D-279's test)
    sub, pi = _sign_in(box["app"], "tester1.subpi"), _sign_in(box["app"], "tester1.pi")
    wk = sub.get(f"/studies/GZQO/week?list=all&pid={A}")
    assert wk.status_code == 200 and f'data-testid="approach-{A[:8]}"' not in wk.text
    assert sub.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk.text), "mark": "approach"}
                    ).status_code == 403  # fmt: skip
    assert sub.get("/studies/GOUT-COH/candidates").status_code in (403, 404)  # not delegated: out of scope
    book = review_book([("GZQO-INC-01", "inclusion", "structured", "Age 18 or over.", None, 100, None)])
    jid = _ulid(972)
    key = f"outputs/{jid}/review_GZQO_v1.1.0_r1.xlsx"
    box["backend"].objects[key] = book
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    out = JobOutput(filename="review_GZQO_v1.1.0_r1.xlsx", sha256=sha256_bytes(book), minio_key=key, recipients=[],
                    tag="aggregate")  # fmt: skip
    box["backend"].add_job(Job(job_id=jid, type="FEAS", ruleset="GZQO", ruleset_version="1.1.0",
                               requested_by="admin@hospa.test", received_at=now, updated_at=now,
                               state="awaiting_approval", options={}, outputs=[out]))  # fmt: skip
    page = sub.get(f"/pilot/jobs/{jid}/approval").text
    assert sub.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page)}).status_code == 403
    assert 'data-testid="approve"' in pi.get(f"/pilot/jobs/{jid}/approval").text  # the logged PI may approve


def test_testers_land_in_their_own_language(box: dict[str, Any]) -> None:  # noqa: F811
    _seed(box)
    for name in ("tester1.pi", "tester1.crc", "owner"):
        box["users"].set_password(name, NEW_PW)
    app = demo.DefaultLanguage(box["app"], box["users"], {a.username: a.language for a in demo.parse_accounts(FILE)})
    for name, lang in (("tester1.pi", "ja"), ("tester1.crc", "zh-TW"), ("owner", "en")):
        c = _sign_in(app, name)
        home = c.get("/home")
        assert home.status_code == 200 and f'<html lang="{lang}"' in home.text, name
    c = _sign_in(app, "tester1.pi")
    c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": "en", "back": "/home"})
    assert '<html lang="en"' in c.get("/home").text  # one click away; the next sign-in starts in ja again
    assert '<html lang="ja"' in _sign_in(app, "tester1.pi").get("/home").text


def test_keep_reuses_a_finished_seed_and_fresh_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PG_DIR", "")  # registers the undo: prepare_dir sets it, and it must not leak to other tests
    monkeypatch.delenv("TB_PG_DIR")
    work = tmp_path / "demo"
    work.mkdir()
    (work / "marks").write_text("kept")
    assert demo.prepare_dir(work, keep=True) is False  # no finished seed: rebuilt
    assert not (work / "marks").exists() and os.environ["TB_PG_DIR"] == str(work / "pg")
    (work / "marks").write_text("kept")
    (work / demo.STATE).write_text("{}")
    assert demo.prepare_dir(work, keep=True) is True and (work / "marks").read_text() == "kept"
    assert demo.prepare_dir(work, keep=False) is False and not (work / "marks").exists()


def test_served_console_takes_identity_settings_from_the_environment(tmp_path: Path) -> None:
    environ = {"TB_CONSOLE_IDLE_MINUTES": "30", "TB_CONSOLE_SECURE_COOKIE": "1", "TB_DEMO_PASSWORD": "not-passed"}
    env = demo.console_env(tmp_path, environ, accounts=True)
    assert env["TB_CONSOLE_MFA"] == "totp" and env["TB_CONSOLE_IDLE_MINUTES"] == "30"
    assert env["TB_CONSOLE_SECURE_COOKIE"] == "1" and "TB_DEMO_PASSWORD" not in env
    assert "TB_CONSOLE_MFA" not in demo.console_env(tmp_path, {}, accounts=False)  # the built-in demo: as before
    assert demo.console_env(tmp_path, {"TB_CONSOLE_MFA": "off"}, accounts=True)["TB_CONSOLE_MFA"] == "off"
