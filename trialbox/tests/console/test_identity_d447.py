"""T-109b (D-447), identity leftovers after fix group D-279: a password on the operator's breached-password list or
among the account's last five is refused; ``doctor`` fails a PRODUCTION box where some way into the console asks for
no second factor, and the console agrees; a directory sign-in counts as two factors only when the provider says so;
an actor assertion is accepted once (SEC-17). Synthetic accounts and a synthetic breached list only."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from console import breached
from console.auth import PASSWORD_HISTORY, AuthError, PasswordRejected, UserStore
from console.identity import IdentityConfigError, IdentitySettings
from console.oidc import reports_mfa
from fastapi.testclient import TestClient
from tb_common import service_auth as sa

from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, VIEWER_PW
from tests.console.test_identity import Clock, _app, _password
from tools.trialbox import doctor

#: passwords made up for the synthetic list; none is anyone's
LISTED = ("synthetic-breached-0001", "synthetic-breached-0002", "correct horse battery staple")


def _sha1(pw: str) -> str:
    return hashlib.sha1(pw.encode("utf-8"), usedforsecurity=False).hexdigest().upper()


def _write_list(
    path: Path, passwords: tuple[str, ...], width: int = 40, filler: int = 200, counts: bool = True
) -> Path:
    """A sorted list in the HIBP "ordered by hash" form, with filler hashes around the listed ones."""
    hashes = {_sha1(p)[:width] for p in passwords}
    hashes |= {_sha1(f"filler-{i}")[:width] for i in range(filler)}
    lines = [f"{h}:{i + 1}" if counts else h for i, h in enumerate(sorted(hashes))]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")  # the download has CRLF line ends
    return path


# ---------------------------------------------------------------------------------------------- breached list
@pytest.mark.parametrize("width", [40, 16, 10])
def test_the_breached_list_is_searched_on_disk_full_hashes_or_prefixes(tmp_path: Path, width: int) -> None:
    path = _write_list(tmp_path / "pwned.txt", LISTED, width=width, counts=width == 40)
    for pw in LISTED:
        assert breached.listed(pw, path), pw
    for pw in ("not-on-the-list-2026", "another-fine-passphrase", "filler-x"):
        assert not breached.listed(pw, path), pw
    for i in (0, 57, 199):  # the first, a middle and the last line are all found
        assert breached.listed(f"filler-{i}", path)


def test_a_configured_list_that_cannot_be_used_refuses_every_password(tmp_path: Path) -> None:
    env = {breached.ENV: str(tmp_path / "missing.txt")}
    with pytest.raises(breached.BreachedListError, match="cannot be read"):
        breached.check("any-long-password-here", env)
    bad = tmp_path / "bad.txt"
    bad.write_text("password123\n", encoding="ascii")
    with pytest.raises(breached.BreachedListError, match="first line"):
        breached.listed("any-long-password-here", bad)
    (tmp_path / "empty.txt").write_text("", encoding="ascii")
    with pytest.raises(breached.BreachedListError, match="empty"):
        breached.listed("x" * 12, tmp_path / "empty.txt")
    assert breached.check("any-long-password-here", {}) is False  # no list configured: no check


def test_a_listed_password_is_refused_at_creation_and_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(breached.ENV, str(_write_list(tmp_path / "pwned.txt", LISTED)))
    store = UserStore(clock=Clock())
    with pytest.raises(PasswordRejected) as err:
        store.create("crc.listed", "coordinator", LISTED[0])
    assert err.value.code == "account.err.breached"
    store.create("crc.ok", "coordinator", "a-fine-unlisted-pass-1")
    with pytest.raises(PasswordRejected, match="breached"):
        store.set_password("crc.ok", LISTED[2])
    monkeypatch.setenv(breached.ENV, str(tmp_path / "gone.txt"))  # fail closed
    with pytest.raises(PasswordRejected) as err:
        store.set_password("crc.ok", "a-fine-unlisted-pass-2")
    assert err.value.code == "account.err.breached_list"


# ---------------------------------------------------------------------------------------------- password history
def test_the_last_five_passwords_cannot_be_chosen_again(tmp_path: Path) -> None:
    store = UserStore(clock=Clock())
    pws = [f"history-pass-{i:02d}-xyz" for i in range(PASSWORD_HISTORY + 2)]
    store.create("crc.hist", "coordinator", pws[0])
    for pw in pws[1:PASSWORD_HISTORY]:
        store.set_password("crc.hist", pw, owner=True)
    # current is pws[4]; pws[0..4] are the last five
    for old in pws[:PASSWORD_HISTORY]:
        with pytest.raises(PasswordRejected) as err:
            store.set_password("crc.hist", old, owner=True)
        assert err.value.code == "account.err.reused"
    assert store.authenticate("crc.hist", pws[PASSWORD_HISTORY - 1]) is not None  # a refusal changes nothing
    store.set_password("crc.hist", pws[PASSWORD_HISTORY], owner=True)
    store.set_password("crc.hist", pws[0], owner=True)  # six changes back: allowed again
    assert store.authenticate("crc.hist", pws[0]) is not None
    kept = store.db.fetchval("SELECT pw_history FROM users WHERE username = ?", ("crc.hist",))
    assert len(str(kept).split()) == PASSWORD_HISTORY - 1 and all(h.startswith("scrypt$") for h in str(kept).split())


def test_the_account_page_says_which_rule_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(breached.ENV, str(_write_list(tmp_path / "pwned.txt", LISTED)))
    app, users, _ = _app(tmp_path, Clock(), **PILOT_ENV, TB_CONSOLE_WORKSPACE="on")
    first, now = "viewer-second-pass-26", "viewer-now-pass-2026"
    users.set_password("viewer", first)  # VIEWER_PW, then this one, are earlier passwords now
    users.set_password("viewer", now)
    c = TestClient(app)
    assert _password(c, "viewer", now).status_code == 303

    def change(new: str) -> Any:
        csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").text)
        assert csrf
        form = {"csrf": csrf.group(1), "current": now, "new": new, "again": new}
        return c.post("/account/password", data=form, follow_redirects=False)

    r = change(LISTED[1])
    assert r.status_code == 400 and "known from data breaches" in r.text
    r = change(first)  # one of the last five
    assert r.status_code == 400 and "among your last five" in r.text
    assert change(VIEWER_PW).status_code == 400
    assert users.authenticate("viewer", now) is not None
    r = change("viewer-third-pass-2026")
    assert r.status_code == 303


def test_the_messages_are_in_three_languages_and_pass_the_wording_check() -> None:
    from console.i18n import EN, JA, ZH
    from tb_common import wording

    for key in ("account.err.reused", "account.err.breached", "account.err.breached_list"):
        for cat in (EN, JA, ZH):
            assert cat.get(key), key
            assert not wording.check(cat[key]), (key, cat[key])


# ---------------------------------------------------------------------------------------------- doctor
def _mfa(env: dict[str, str]) -> doctor.Check:
    checks = doctor.run(doctor.DoctorInputs(env={"TB_TOPOLOGY": "A", **env}, host_tz="Asia/Taipei"))
    return next(c for c in checks if c.name == "console_mfa")


OIDC_ENV = {
    "TB_OIDC_ENABLED": "1",
    "TB_OIDC_ISSUER": "https://auth.hosp.test",
    "TB_OIDC_CLIENT_ID": "trialbox",
    "TB_OIDC_REDIRECT_URL": "https://trialbox.hosp.test/auth/oidc/callback",
    "TB_OIDC_GROUP_ROLES": "tb-coordinators:coordinator",
    "TB_OIDC_LOGOUT_URL": "https://auth.hosp.test/logout",
}


@pytest.mark.parametrize(
    ("env", "want"),
    [
        ({"TB_ENV": "PRODUCTION"}, "PASS"),  # the console's default: TOTP
        ({"TB_ENV": "PRODUCTION", "TB_CONSOLE_MFA": "totp"}, "PASS"),
        ({"TB_ENV": "PRODUCTION", "TB_CONSOLE_MFA": "off"}, "FAIL"),  # the acceptance test of T-109b
        ({"TB_ENV": "VALIDATION", "TB_CONSOLE_MFA": "off"}, "FAIL"),
        ({"TB_ENV": "PRODUCTION", "TB_CONSOLE_MFA": "sms"}, "FAIL"),
        ({"TB_ENV": "PRODUCTION", **OIDC_ENV}, "PASS"),
        ({"TB_ENV": "PRODUCTION", **OIDC_ENV, "TB_OIDC_REQUIRE_MFA": "0"}, "FAIL"),
        ({"TB_ENV": "PRODUCTION", "TB_CONSOLE_SSO_HEADER": "remote-user"}, "FAIL"),
        ({}, "PASS"),  # no TB_ENV: read as PRODUCTION, and its default is TOTP
        ({"TB_ENV": "DEV"}, "WARN"),  # DEV and TEST go without TOTP by default (D-192)
        ({"TB_ENV": "TEST", "TB_CONSOLE_MFA": "totp"}, "PASS"),
    ],
)
def test_doctor_fails_production_without_a_second_factor(env: dict[str, str], want: str) -> None:
    c = _mfa(env)
    assert c.status == want, c.detail
    if want == "FAIL":
        assert not doctor.ok([c])


@pytest.mark.parametrize(
    "env",
    [
        {"TB_CONSOLE_MFA": "off"},
        {**OIDC_ENV, "TB_OIDC_REQUIRE_MFA": "0"},
        {**OIDC_ENV},
        {},
    ],
)
def test_doctor_and_the_console_agree_on_mfa(env: dict[str, str], tmp_path: Path) -> None:
    secret = tmp_path / "client-secret"
    secret.write_text("synthetic-client-secret", encoding="utf-8")
    env = {**env, "TB_OIDC_CLIENT_SECRET_FILE": str(secret)} if env.get("TB_OIDC_ENABLED") else env
    for environment in ("PRODUCTION", "VALIDATION"):
        try:
            IdentitySettings.from_env(env, environment, tmp_path)
            starts = True
        except IdentityConfigError:
            starts = False
        assert starts == (_mfa({"TB_ENV": environment, **env}).status == "PASS"), (environment, env)
    if env.get("TB_OIDC_REQUIRE_MFA") == "0":
        IdentitySettings.from_env(env, "TEST", tmp_path)  # a test box may


# ---------------------------------------------------------------------------------------------- OIDC amr
@pytest.mark.parametrize(
    ("amr", "two"),
    [
        (["pwd", "otp", "mfa"], True),  # Authelia, password and TOTP
        (["mfa"], True),
        (["pwd", "hwk"], True),  # password and a security key (WebAuthn)
        (["hwk", "pin"], True),  # a passkey with user verification
        (["hwk", "user"], False),  # a key touched, nobody verified: one factor
        (["swk"], False),  # CR-118: a software key alone counted before
        (["pop"], False),
        (["otp"], False),
        (["pwd"], False),
        ([], False),
    ],
)
def test_a_directory_sign_in_counts_as_two_factors_only_when_the_provider_says_so(amr: list[str], two: bool) -> None:
    assert reports_mfa(amr) is two


# ---------------------------------------------------------------------------------------------- SEC-17 replay
@pytest.fixture
def signing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", "d447-synthetic-service-token-0123456789")
    monkeypatch.delenv(sa.ACTOR_KEYS_ENV, raising=False)
    monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)


def test_a_replayed_assertion_is_refused(signing: None) -> None:
    guard = sa.ReplayGuard()
    h = sa.actor_header("crc.a", session="s1", role="coordinator", scope="RS1")
    a = h[sa.ASSERTION_HEADER]
    assert a.startswith("v2.") and len(a.split(".")) == 5
    who = sa.verify_actor(h[sa.ACTOR_HEADER], a, role="coordinator", scope="RS1", replay=guard)
    assert who.verified and who.name == "crc.a"
    with pytest.raises(sa.ActorError, match="already used"):  # the acceptance test of T-109b (SEC-17)
        sa.verify_actor(h[sa.ACTOR_HEADER], a, role="coordinator", scope="RS1", replay=guard)
    # two calls in the same second carry two assertions, each accepted once
    h2 = sa.actor_header("crc.a", session="s1", role="coordinator", scope="RS1")
    assert h2[sa.ASSERTION_HEADER] != a
    assert sa.verify_actor(h2[sa.ACTOR_HEADER], h2[sa.ASSERTION_HEADER], role="coordinator", scope="RS1",
                           replay=guard).verified  # fmt: skip


def test_a_refused_assertion_is_not_used_up_and_old_entries_go(signing: None) -> None:
    guard = sa.ReplayGuard()
    h = sa.actor_header("crc.b", session="s1", role="coordinator")
    with pytest.raises(sa.ActorError, match="does not verify"):
        sa.verify_actor(h[sa.ACTOR_HEADER], h[sa.ASSERTION_HEADER], role="admin", replay=guard)
    assert len(guard) == 0
    assert sa.verify_actor(h[sa.ACTOR_HEADER], h[sa.ASSERTION_HEADER], role="coordinator", replay=guard).verified
    for i in range(300):  # expired entries are dropped as new ones arrive
        guard.use(f"m{i}", exp=0, now=1)
    guard.use("fresh", exp=10_000, now=5_000)
    assert len(guard) < 300


def test_the_old_form_without_a_nonce_is_refused(signing: None) -> None:
    import hmac as _hmac
    import time

    exp = int(time.time()) + 60
    key = sa.actor_key("d447-synthetic-service-token-0123456789")
    mac = _hmac.new(key, f"v1\ncrc.c\ns1\n{exp}".encode(), hashlib.sha256).hexdigest()
    with pytest.raises(sa.ActorError, match="not signed"):
        sa.verify_actor("crc.c", f"v1.{exp}.s1.{mac}", replay=sa.ReplayGuard())


def test_a_retry_carries_a_fresh_assertion(signing: None) -> None:
    h = {**sa.actor_header("crc.d", session="s9", role="coordinator", scope="*"), "X-Other": "kept"}
    again = sa.resign(h)
    assert again[sa.ASSERTION_HEADER] != h[sa.ASSERTION_HEADER] and again["X-Other"] == "kept"
    assert again[sa.ASSERTION_HEADER].split(".")[2] == "s9"
    guard = sa.ReplayGuard()
    for hdr in (h, again):
        assert sa.verify_actor(hdr[sa.ACTOR_HEADER], hdr[sa.ASSERTION_HEADER], role="coordinator", scope="*",
                               replay=guard).name == "crc.d"  # fmt: skip
    assert sa.resign({"X-Other": "x"}) == {"X-Other": "x"}


def test_the_orchestrator_refuses_a_replayed_reveal_assertion(signing: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end on the orchestrator's own claim check: the second use of one assertion is a 403, audited."""
    from fastapi import HTTPException
    from orchestrator import app as orch_app
    from starlette.requests import Request

    events: list[tuple[str, dict[str, Any]]] = []

    class _Audit:
        def append(self, event: str, **kw: Any) -> None:
            events.append((event, kw))

    class _Orch:
        audit = _Audit()

    monkeypatch.setattr(orch_app, "orch", _Orch)
    h = sa.actor_header("crc.e", session="s1", role="coordinator", scope="RS1")
    raw = [(k.lower().encode(), v.encode()) for k, v in h.items()]

    def req() -> Request:
        return Request({"type": "http", "method": "POST", "path": "/jobs/J1/reveal", "headers": raw,
                        "query_string": b""})  # fmt: skip

    assert orch_app._claim(req()).name == "crc.e"
    with pytest.raises(HTTPException) as err:
        orch_app._claim(req())
    assert err.value.status_code == 403 and "already used" in str(err.value.detail)
    assert events and events[-1][0] == "actor.refused"


def test_a_password_someone_else_sets_is_not_held_to_the_history(tmp_path: Path) -> None:
    """An administrator's reset and the demo's re-seed set a password the owner did not choose; the history binds
    only the owner's own choice (and the replaced hash is kept either way)."""
    store = UserStore(clock=Clock())
    store.create("admin.x", "admin", ADMIN_PW)
    store.set_password("admin.x", ADMIN_PW, must_change=True)
    with pytest.raises(AuthError):
        store.set_password("admin.x", ADMIN_PW, owner=True)
