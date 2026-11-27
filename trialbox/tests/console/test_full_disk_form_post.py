# ruff: noqa: F811 - the fixture is imported from another test module and taken by name
"""E2E P-34: with ``/var/lib/docker`` full, a form post (the feedback control on every page) answered ``500 Internal
Server Error``. A write the full disk refuses (the audit's ``AuditFull``, or the system's ``ENOSPC``) now answers a
plain page that says the disk is full and to tell IT (507); any other error stays what it was."""

from __future__ import annotations

import errno
import re
from typing import Any

import pytest
from tb_common.audit import AuditFull, AuditLog

from tests.console.test_console_app import ADMIN_PW, box, login  # noqa: F401


def _csrf(c: Any) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', c.get("/home").text)
    assert m
    return m.group(1)


@pytest.mark.parametrize(
    "full", [AuditFull("audit volume has less than 64 MB free"), OSError(errno.ENOSPC, "No space left on device")]
)
def test_a_form_post_on_a_full_disk_says_so(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, full: OSError
) -> None:
    c, _ = login(box["app"], "admin", ADMIN_PW)
    csrf = _csrf(c)

    def refused(*a: Any, **k: Any) -> None:
        raise full

    monkeypatch.setattr(AuditLog, "append", refused)  # the disk filled up after sign-in
    r = c.post("/feedback", data={"csrf": csrf, "path": "/home", "comment": "x"}, follow_redirects=False)
    assert r.status_code == 507, r.text[:300]
    assert "disk is full" in r.text and 'data-testid="problem-page"' in r.text


def test_another_os_error_is_still_a_server_error(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = login(box["app"], "admin", ADMIN_PW)
    csrf = _csrf(c)

    def broken(*a: Any, **k: Any) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(AuditLog, "append", broken)
    with pytest.raises(PermissionError):
        c.post("/feedback", data={"csrf": csrf, "path": "/home", "comment": "x"}, follow_redirects=False)
