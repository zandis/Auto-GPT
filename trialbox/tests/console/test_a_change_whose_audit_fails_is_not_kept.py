"""D-1159 (the register's V3-18, V8-04, V8-07's order): a change and its audit event are one: when the audit write
fails (the audit volume reads full, so ``AuditLog.append`` raises ``AuditFull``), the change is not kept. Each test
makes the write fail for one request and reads the store afterwards. Synthetic accounts and studies only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

import pytest
from console.teamstore import TeamStore
from tb_common.audit import AuditFull

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_d280_breakglass import A, _csrf, _open, _shift, _user

FULL = str(2**40)  # TB_AUDIT_MIN_FREE_MB: no volume has that much free, so every append raises AuditFull


@contextmanager
def _audit_full(mp: pytest.MonkeyPatch) -> Iterator[None]:
    """The audit write fails for what runs inside; the request may end in AuditFull or in a refusal (both a fix)."""
    mp.setenv("TB_AUDIT_MIN_FREE_MB", FULL)
    try:
        with suppress(AuditFull):
            yield
    finally:
        mp.delenv("TB_AUDIT_MIN_FREE_MB")


def _admin(b: dict[str, Any]) -> tuple[Any, str]:
    admin, _ = login(b["app"])
    return admin, _csrf(admin.get("/ops/users").text)


def _row(b: dict[str, Any], name: str) -> tuple[Any, ...]:
    got = b["users"].db.fetchone("SELECT pw_hash, disabled, studies, expires FROM users WHERE username = ?", (name,))
    assert got is not None
    return tuple(got)


def test_a_reset_whose_event_fails_keeps_the_old_password(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    box["users"].create("atreset", "viewer", "atreset-password-01")
    admin, csrf = _admin(box)
    before = _row(box, "atreset")
    with _audit_full(monkeypatch):
        admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "atreset", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert _row(box, "atreset")[0] == before[0], "the password was replaced with no audit event"


def test_a_scope_whose_event_fails_keeps_the_old_scope(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    box["users"].create("atscope", "coordinator", "atscope-password-01")
    box["users"].set_scope("atscope", "hospital", "GZQO")
    admin, csrf = _admin(box)
    before = _row(box, "atscope")
    with _audit_full(monkeypatch):
        admin.post("/ops/users", data={"csrf": csrf, "action": "scope", "username": "atscope",
                                       "affiliation": "hospital", "studies": "GZQO,OTHER1"}, follow_redirects=False)  # fmt: skip
    assert _row(box, "atscope")[2] == before[2], "the scope changed with no audit event"


def test_a_disable_whose_event_fails_keeps_the_account(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    box["users"].create("atoff", "viewer", "atoff-password-01")
    admin, csrf = _admin(box)
    with _audit_full(monkeypatch):
        admin.post("/ops/users", data={"csrf": csrf, "action": "disable", "username": "atoff", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert not _row(box, "atoff")[1], "the account was disabled with no audit event"


def test_an_enable_whose_event_fails_keeps_it_disabled(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    box["users"].create("aton", "viewer", "aton-password-01")
    box["users"].disable("aton")
    admin, csrf = _admin(box)
    with _audit_full(monkeypatch):
        admin.post("/ops/users", data={"csrf": csrf, "action": "enable", "username": "aton"}, follow_redirects=False)
    assert _row(box, "aton")[1], "the account was enabled with no audit event"


def test_an_irb_record_whose_event_fails_is_not_saved(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    crc = _user(box, "atirb", "coordinator")
    page = crc.get("/studies/GZQO/irb").text
    with _audit_full(monkeypatch):
        crc.post("/studies/GZQO/irb", data={"csrf": _csrf(page), "approval_no": "IRB-T-9", "approved_on": "2026-01-02"},
                 follow_redirects=False)  # fmt: skip
    team = TeamStore()
    try:
        assert team.irb("GZQO").approval_no != "IRB-T-9", "the IRB record was saved with no audit event"
    finally:
        team.close()
    ok = crc.post("/studies/GZQO/irb", data={"csrf": _csrf(page), "approval_no": "IRB-T-9", "approved_on": "2026-01-02"},
                  follow_redirects=False)  # fmt: skip
    assert ok.status_code == 303  # the control: the same body is saved when the audit can be written


def test_a_grant_whose_end_event_fails_stays_open(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(997))
    admin, _ = login(box["app"])
    assert _open(admin, kind="patient", ruleset="GZQO", pid=A).headers.get("location") == "/breakglass?done=open"
    page = admin.get("/breakglass").text
    gid = page.split('data-testid="bg-active" data-grant="')[1].split('"')[0]
    with _audit_full(monkeypatch):
        admin.post(f"/breakglass/{gid}/end", data={"csrf": _csrf(page)}, follow_redirects=False)
    assert 'data-testid="bg-active"' in admin.get("/breakglass").text, "the grant ended with no audit event"


def test_a_review_whose_event_fails_is_not_kept(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(998))
    stw = _user(box, "atstw", "steward")
    admin, _ = login(box["app"])
    _open(admin, kind="patient", ruleset="GZQO", pid=A)
    gid = admin.get("/breakglass").text.split('data-testid="bg-active" data-grant="')[1].split('"')[0]
    _shift(box, 61)  # the grant has run out (60 minutes): it may be reviewed
    page = stw.get("/breakglass").text
    with _audit_full(monkeypatch):
        stw.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(page), "note": "matches the ticket"},
                 follow_redirects=False)  # fmt: skip
    assert _reviewed_at(int(gid)) is None, "the review was kept with no audit event"


def _reviewed_at(gid: int) -> Any:
    from console.breakglass_store import BreakGlassStore

    s = BreakGlassStore()
    try:
        g = s.get(gid)
        assert g is not None
        return g.reviewed_at
    finally:
        s.close()


class _Refused(Exception):
    pass


def _fail(*_a: object) -> None:
    raise _Refused("the audit write failed")


def test_the_protected_account_changes_are_not_kept_when_their_event_fails(box: dict[str, Any]) -> None:  # noqa: F811
    """The account rules' paths (D-719: a protected account opened by code, its authenticator reset, an enrolment
    code): the event runs inside the store's transaction, so a failed event keeps nothing."""
    us = box["users"]
    with suppress(_Refused):
        us.open_by_code("atcode", "admin", None, "admin", scope=("hospital", "", None), before_commit=_fail)
    assert not us.role_of("atcode"), "a protected account was opened with no audit event"
    us.create("attotp", "viewer", "attotp-password-01")
    before = us.db.fetchone("SELECT enrol_code_sha FROM users WHERE username = ?", ("attotp",))
    with suppress(_Refused):
        us.reset_totp("attotp", before_commit=_fail)
    with suppress(_Refused):
        us.issue_enrol_code("attotp", before_commit=_fail)
    after = us.db.fetchone("SELECT enrol_code_sha FROM users WHERE username = ?", ("attotp",))
    assert after == before, "an enrolment code was issued with no audit event"
