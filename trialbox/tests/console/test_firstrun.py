"""T-729 (D-466): the box's first-run wizard. It opens only with the one-time code from the box's screen and only while
no account exists; it makes the owner's accounts (steward and administrator, OD-12) with one password and one
authenticator, hands the answers to the installer's apply step, closes for good, and the owner then signs in with the
password and the authenticator code (TOTP on, as on a PRODUCTION box, over https)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from console import totp
from console.app import create_app
from console.auth import UserStore
from console.i18n import CATALOGUES
from console.i18n_firstrun import EN, JA, ZH
from fastapi.testclient import TestClient
from tb_common import firstrun
from tb_common.audit import AuditLog
from tb_common.wording import check

from tests.console.test_console_app import PILOT_ENV, FakeBackend

PW = "owner-password-0001"
HW = {
    "arch": "x86_64", "cpu_count": 32, "ram_gib": 128, "disk_free_gib": 1800, "tpm": True,
    "disks": [{"path": "/dev/sdb", "size_gib": 3726.0, "transport": "sata", "mounted": ""}],
    "lan": "192.0.2.0/24", "hostname": "box1", "host_tz": "Asia/Tokyo",
}  # fmt: skip


def _box(tmp_path: Path, tpm: bool = True) -> dict[str, Any]:
    folder = tmp_path / "firstrun"
    firstrun.write_private(folder / firstrun.HARDWARE, {**HW, "tpm": tpm})
    code = firstrun.make_code(folder)
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    audit = AuditLog(backend.audit_dir)
    users = UserStore()
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console"), "TB_FIRSTRUN_DIR": str(folder),
           "TB_CONSOLE_MFA": "totp"}  # fmt: skip
    app = create_app(env, backend=backend, audit=audit, users=users)
    return {"app": app, "users": users, "folder": folder, "code": code, "audit": backend.audit_dir}


def _answers(c: TestClient, **over: str) -> tuple[Any, str]:
    page = c.get("/login/first-run/answers")
    assert page.status_code == 200, page.text[-400:]
    key = re.search(r'id="totp-key"[^>]*value="([A-Z2-7 ]+)"', page.text)
    csrf = re.search(r'name="fr_csrf" value="([^"]+)"', page.text)
    assert key and csrf
    secret = key.group(1).replace(" ", "")
    form = {
        "fr_csrf": csrf.group(1), "site_name": "示範醫院A (synthetic)", "tz": "Asia/Tokyo", "language": "ja",
        "owner_full_name": "Dr Owner", "owner_username": "owner", "owner_email": "owner@hospa.test",
        "password": PW, "password2": PW, "totp": totp.totp(secret, time.time()), "box_name": "trialbox",
        "backup_kind": "second_disk", "backup_disk": "/dev/sdb", "source": "spreadsheet",
        **over,
    }  # fmt: skip
    return c.post("/login/first-run/answers", data=form, follow_redirects=False), secret


def _with_code(b: dict[str, Any], code: str | None = None) -> TestClient:
    c = TestClient(b["app"], base_url="https://testserver")
    r = c.post("/login/first-run", data={"code": code or b["code"]}, follow_redirects=False)
    assert r.status_code == 303, r.text[-300:]
    return c


def test_the_first_run_makes_the_owner_and_ends_on_a_sign_in_over_https(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = _with_code(b)
    r, secret = _answers(c)
    assert r.status_code == 200 and 'data-testid="firstrun-done"' in r.text, r.text[-600:]
    users = {u.username: u.role for u in b["users"].users()}
    assert users == {"owner": "steward", "owner-admin": "admin"}  # OD-12: steward, and the administrator's duties
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["tz"] == "Asia/Tokyo" and got["backup"] == {"kind": "second_disk", "disk": "/dev/sdb", "share": ""}
    assert "password" not in json.dumps(got) and "kek_passphrase" not in got  # a TPM box: no passphrase
    assert oct((b["folder"] / firstrun.ANSWERS).stat().st_mode & 0o777) == "0o600"
    assert not firstrun.is_open(b["folder"])  # the code is used up
    # closed for good: the code again, or the page, is 404
    assert TestClient(b["app"]).get("/login/first-run").status_code == 404
    assert c.post("/login/first-run", data={"code": b["code"]}).status_code == 404
    # the owner signs in: password, then the authenticator added in the wizard (TOTP on)
    s = TestClient(b["app"], base_url="https://testserver")
    token = re.search(r'name="login_csrf" value="([^"]+)"', s.get("/login").text)
    assert token
    r = s.post(
        "/login", data={"username": "owner", "password": PW, "login_csrf": token.group(1)}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/login/totp", r.text[-300:]
    mfa = re.search(r'name="mfa_csrf" value="([^"]+)"', s.get("/login/totp").text)
    assert mfa
    step = totp.step_at(time.time()) + 1  # the wizard used this step's code: the next one (inside the window)
    code = totp.hotp(secret, step)
    r = s.post("/login/totp", data={"code": code, "mfa_csrf": mfa.group(1)}, follow_redirects=False)
    assert r.status_code == 303 and "must_change" not in r.headers["location"], r.text[-300:]
    events = [json.loads(x) for f in sorted(b["audit"].glob("*")) if f.is_file()
              for x in f.read_text(encoding="utf-8").splitlines() if x.startswith("{")]  # fmt: skip
    done = [
        e for e in events if e.get("event") == "console.first_run" and (e.get("detail") or {}).get("step") == "done"
    ]
    assert done and done[0]["detail"]["roles"] == ["steward", "admin"]


def test_without_the_code_or_the_folder_or_with_an_account_the_page_is_404(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = TestClient(b["app"])
    assert c.get("/login/first-run").status_code == 200
    assert c.get("/login/first-run/answers", follow_redirects=False).status_code == 303  # no code given yet
    b["users"].create("someone", "viewer", "viewer-password-001")
    assert c.get("/login/first-run").status_code == 404  # an account exists: closed
    other = create_app({**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "c2")}, backend=FakeBackend(),
                       audit=AuditLog(tmp_path / "a2"), users=UserStore())  # fmt: skip
    assert TestClient(other).get("/login/first-run").status_code == 404  # not a box: no first-run folder


def test_five_wrong_codes_void_it(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = TestClient(b["app"])
    for _ in range(firstrun.MAX_TRIES - 1):
        r = c.post("/login/first-run", data={"code": "aaaa-bbbb-cccc-dddd"})
        assert r.status_code == 403 and 'data-testid="firstrun-wrong"' in r.text
    assert c.post("/login/first-run", data={"code": "aaaa-bbbb-cccc-dddd"}).status_code == 404
    assert c.post("/login/first-run", data={"code": b["code"]}).status_code == 404  # void: the box shows a new one
    assert b["users"].count() == 0


def test_bad_answers_are_shown_and_make_nothing(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = _with_code(b)
    r, _ = _answers(c, tz="Mars/Base", password2="something-else-0001", totp="000000", backup_disk="/dev/sdz")
    assert r.status_code == 422
    for field in ("tz", "password2", "totp", "backup_disk"):
        assert f'data-testid="err-{field}"' in r.text, field
    assert PW not in r.text  # a password is never sent back
    assert b["users"].count() == 0 and firstrun.is_open(b["folder"])
    r, _ = _answers(c, password="short", password2="short")
    assert r.status_code == 422 and 'data-testid="err-password"' in r.text


def test_a_box_without_a_tpm_asks_for_the_passphrase_and_keeps_it_on_the_tmpfs_only(tmp_path: Path) -> None:
    b = _box(tmp_path, tpm=False)
    c = _with_code(b)
    r, _ = _answers(c)
    assert r.status_code == 422 and 'data-testid="err-kek"' in r.text
    r, _ = _answers(c, kek="a-long-passphrase-01", kek2="a-long-passphrase-01")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["kek_passphrase"] == "a-long-passphrase-01"


def test_a_stale_or_foreign_browser_token_starts_again(tmp_path: Path) -> None:
    b = _box(tmp_path)
    _with_code(b)
    stranger = TestClient(b["app"])
    stranger.cookies.set("tb_firstrun", "not-the-token")
    assert stranger.get("/login/first-run/answers", follow_redirects=False).status_code == 303
    r = stranger.post("/login/first-run/answers", data={"fr_csrf": "x"}, follow_redirects=False)
    assert r.status_code == 303 and b["users"].count() == 0


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_every_language_has_every_string_and_no_forbidden_word(lang: str) -> None:
    cat = {"en": EN, "ja": JA, "zh-TW": ZH}[lang]
    assert set(cat) == set(EN)
    for key, text in cat.items():
        assert CATALOGUES[lang][key] == text
        assert not check(text), (key, text)
        if lang != "en":  # D-133 glossary (tests/console/test_step4b.py): one hospital word per concept
            for word in ("サインイン", "ジョブ", "(?<!コント)ロール", "(?<!信)箱", "装置", "工作(?![簿日天])", "權杖"):
                assert not re.search(word, text), (key, word)


def test_the_pages_render_in_each_language(tmp_path: Path) -> None:
    b = _box(tmp_path)
    c = TestClient(b["app"])
    for lang, word in (("en", "Set up this TrialBox"), ("ja", "初期設定"), ("zh-TW", "設定這台")):
        r = c.get(f"/login/first-run?lang={lang}")
        assert r.status_code == 200 and word in r.text and not check(r.text), lang
