"""Console accounts, sessions and CSRF (spec v4 §3.8, FR-SIG-14 headers; ASVS V2/V3 basics).

* Accounts live in the trial database (PostgreSQL ``trialbox_wf``, schema ``auth``; D-126). There is no default
  password: the first administrator is created by ``python -m console.cli bootstrap-admin`` (random password printed
  once) or, at first start, from the file named by ``TB_CONSOLE_ADMIN_PASSWORD_FILE`` (a compose secret).
* Passwords are stored as scrypt hashes (stdlib ``hashlib.scrypt``, per-user salt); at least 12 characters.
* Five failed logins within 15 minutes lock the account for 15 minutes (audited by the app).
* Sessions are server-side: the cookie carries a random token, the table stores only its SHA-256. Idle timeout 30 min,
  absolute lifetime 8 h. Each session has its own CSRF token, checked on every state-changing request.
* Roles: ``admin`` (start requests, approve, operate) and ``viewer`` (read only).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from console.storedb import open_db

Role = Literal["admin", "coordinator", "investigator", "viewer", "cro"]
ROLES: tuple[Role, ...] = ("admin", "coordinator", "investigator", "viewer", "cro")
# D-104: where an account sits. An SMO coordinator is a study-scoped coordinator; a CRO account is aggregate-only.
AFFILIATIONS: tuple[str, ...] = ("hospital", "smo", "cro")
SSO_MARK = "sso"  # pw_hash of an account the hospital identity provider signs in (no console password)
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=8)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_USERNAME_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

# Version 1 is the schema the SQLite file had, with the D-104 scope columns (D-126). Append new versions; never edit an
# applied one. Times are ISO-8601 text; ``username`` and ``at`` sort and compare byte by byte ("C"), as in SQLite, and
# user names stay case-sensitive (they are stored lower-case).
SCHEMA_V1 = """
CREATE TABLE users (
  username TEXT COLLATE "C" PRIMARY KEY,
  role TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  mailbox TEXT,
  created TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0,
  affiliation TEXT,
  studies TEXT,
  expires TEXT
);
CREATE TABLE sessions (
  token_sha TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  csrf TEXT NOT NULL,
  created TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'en'
);
CREATE INDEX sessions_user ON sessions (username);
CREATE TABLE login_failures (
  username TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX login_failures_user ON login_failures (username, at)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)
_COLS = "username, role, mailbox, affiliation, studies, expires"


class AuthError(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt).decode()}${b64(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(dk)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(dk))


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"passwords must be at least {MIN_PASSWORD} characters")
    if password.strip() != password:
        raise AuthError("passwords must not start or end with white space")


def check_username(username: str) -> str:
    u = username.strip().lower()
    if not 1 <= len(u) <= 32 or not set(u) <= _USERNAME_OK:
        raise AuthError("user names are 1-32 characters: a-z, 0-9, '.', '_' or '-'")
    return u


def random_password() -> str:
    return secrets.token_urlsafe(18)  # 24 characters, ~144 bits


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class User:
    username: str
    role: Role
    mailbox: str | None
    affiliation: str = "hospital"
    studies: tuple[str, ...] = ()  # empty = every study (D-104)
    expires: str | None = None  # ISO date; sign-in refused after it

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_request(self) -> bool:
        """May start requests and edit the registry: administrators and coordinators (D-93)."""
        return self.role in ("admin", "coordinator")

    @property
    def can_view_phi(self) -> bool:
        """May read patient-level results in the browser: the CASE sheet and the pseudonymous candidate rows.
        Administrators, coordinators and investigators (D-101). Chart numbers (reveal, registry export) stay with
        the requesters, who keep the screening log."""
        return self.role in ("admin", "coordinator", "investigator")

    @property
    def can_mark(self) -> bool:
        """May mark weekly-list patients Approach / Not suitable / Need info: investigators (D-104)."""
        return self.role == "investigator"

    @property
    def can_approve(self) -> bool:
        """May approve a study's criteria (S20, FR-AUTH-13, D-108): the investigator only. Administrators and
        coordinators prepare the approval (tick codes) but never approve."""
        return self.role == "investigator"

    @property
    def aggregate_only(self) -> bool:
        """Sees aggregate reports only, in the sponsor (suppressed) form for CRO accounts (D-104)."""
        return self.role in ("viewer", "cro")

    def sees_study(self, ruleset: str) -> bool:
        return not self.studies or ruleset.upper() in self.studies


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    lang: str
    token_sha: str


Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _row_user(row: tuple[object, ...]) -> User:
    u, r, m, aff, studies, exp = row
    st = tuple(x for x in str(studies or "").upper().replace(" ", "").split(",") if x)
    return User(str(u), r, m, str(aff or "hospital"), st, str(exp) if exp else None)  # type: ignore[arg-type]


def scope_values(affiliation: str, studies: str, expires: str | None) -> tuple[str, str, str | None]:
    """Checked affiliation, study list and end date of an account (D-104); raises AuthError."""
    aff = (affiliation or "hospital").strip().lower()
    if aff not in AFFILIATIONS:
        raise AuthError(f"affiliation must be one of {', '.join(AFFILIATIONS)}")
    st = ",".join(x for x in studies.upper().replace(" ", "").split(",") if x)
    if st and not all(re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,31}", x) for x in st.split(",")):
        raise AuthError("studies are ruleset ids separated by commas")
    exp = (expires or "").strip() or None
    if exp is not None:
        try:
            date.fromisoformat(exp)
        except ValueError as exc:
            raise AuthError("end date must be YYYY-MM-DD") from exc
    return aff, st, exp


class UserStore:
    """Schema ``auth`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None, clock: Clock = _utcnow) -> None:
        self.db = open_db(url, "auth", MIGRATIONS)
        self.clock = clock

    def close(self) -> None:
        self.db.close()

    def _expired(self, user: User) -> bool:
        return bool(user.expires) and self.clock().date().isoformat() > str(user.expires)

    # ------------------------------------------------------------------ users
    def count(self, role: Role | None = None) -> int:
        if role is None:
            n = self.db.fetchval("SELECT count(*) FROM users WHERE disabled = 0")
        else:
            n = self.db.fetchval("SELECT count(*) FROM users WHERE disabled = 0 AND role = ?", (role,))
        return int(n)

    def users(self) -> list[User]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM users WHERE disabled = 0 ORDER BY username")
        return [_row_user(r) for r in rows]

    def get(self, username: str) -> User | None:
        row = self.db.fetchone(f"SELECT {_COLS} FROM users WHERE username = ? AND disabled = 0", (username,))
        if row is None:
            return None
        user = _row_user(row)
        return None if self._expired(user) else user

    def set_scope(
        self, username: str, affiliation: str = "hospital", studies: str = "", expires: str | None = None
    ) -> User:
        """Affiliation, study scope and end date of an account (D-104). An SMO coordinator is normally scoped to
        the studies on its contract with an end date; a CRO account is aggregate-only whatever its scope."""
        aff, st, exp = scope_values(affiliation, studies, expires)
        with self.db.transaction() as tx:
            n = tx.execute(
                "UPDATE users SET affiliation = ?, studies = ?, expires = ? WHERE username = ?",
                (aff, st or None, exp, username),
            )
            if n != 1:
                raise AuthError(f"no user {username}")
            row = tx.fetchone(f"SELECT {_COLS} FROM users WHERE username = ?", (username,))
        assert row is not None
        return _row_user(row)

    def create(self, username: str, role: Role, password: str, mailbox: str | None = None) -> User:
        u = check_username(username)
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        check_password_policy(password)
        mb = mailbox.strip().lower() if mailbox else None
        if mb is not None and ("@" not in mb or " " in mb):
            raise AuthError("mailbox must be an e-mail address")
        n = self.db.execute(
            "INSERT INTO users (username, role, pw_hash, mailbox, created) VALUES (?,?,?,?,?) "
            "ON CONFLICT (username) DO NOTHING",
            (u, role, hash_password(password), mb, self.clock().isoformat()),
        )
        if n != 1:
            raise AuthError(f"user {u} exists")
        return User(u, role, mb)

    def upsert_sso(self, username: str, role: Role, mailbox: str | None) -> User:
        """The account behind a trusted identity header (D-93): created on first sight with no console password,
        role and mailbox refreshed on every sign-in so a change in the directory applies at once. Never touches an
        account that has a password (a local administrator keeps their rights)."""
        u = check_username(username)
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        mb = mailbox.strip().lower() if mailbox else None
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT pw_hash, disabled FROM users WHERE username = ? FOR UPDATE", (u,))
            if row is None:
                tx.execute(
                    "INSERT INTO users (username, role, pw_hash, mailbox, created) VALUES (?,?,?,?,?)",
                    (u, role, SSO_MARK, mb, self.clock().isoformat()),
                )
            elif row[1]:
                raise AuthError("account disabled")
            elif row[0] == SSO_MARK:
                tx.execute("UPDATE users SET role = ?, mailbox = ? WHERE username = ?", (role, mb, u))
            else:  # a local account: the header never changes its role or mailbox
                row = tx.fetchone(f"SELECT {_COLS} FROM users WHERE username = ?", (u,))
                assert row is not None
                return _row_user(row)
            row = tx.fetchone(f"SELECT {_COLS} FROM users WHERE username = ?", (u,))
        assert row is not None
        user = _row_user(row)
        if self._expired(user):  # D-104: an account past its end date never signs in, SSO or not
            raise AuthError("account expired")
        return user

    def is_sso(self, username: str) -> bool:
        stored = self.db.fetchval("SELECT pw_hash FROM users WHERE username = ?", (username,))
        return bool(stored == SSO_MARK)

    def set_password(self, username: str, password: str) -> None:
        check_password_policy(password)
        pw_hash = hash_password(password)
        with self.db.transaction() as tx:
            if tx.execute("UPDATE users SET pw_hash = ? WHERE username = ?", (pw_hash, username)) != 1:
                raise AuthError(f"no user {username}")
            tx.execute("DELETE FROM sessions WHERE username = ?", (username,))  # sign out everywhere
            tx.execute("DELETE FROM login_failures WHERE username = ?", (username,))

    def disable(self, username: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            tx.execute("DELETE FROM sessions WHERE username = ?", (username,))

    # ------------------------------------------------------------------ login
    def locked(self, username: str) -> bool:
        since = (self.clock() - LOCKOUT).isoformat()
        n = self.db.fetchval("SELECT count(*) FROM login_failures WHERE username = ? AND at >= ?", (username, since))
        return int(n) >= MAX_FAILURES

    def authenticate(self, username: str, password: str) -> User | None:
        """The user, or None (unknown user, wrong password, disabled or locked). Constant work for unknown users."""
        u = username.strip().lower()
        row = self.db.fetchone(f"SELECT {_COLS}, pw_hash FROM users WHERE username = ? AND disabled = 0", (u,))
        stored = str(row[6]) if row else hash_password("unknown-user-dummy-password")
        ok = verify_password(password, stored) and row is not None
        if self.locked(u):
            return None
        if not ok:
            self.db.execute(
                "INSERT INTO login_failures (username, at) VALUES (?,?)", (u[:64], self.clock().isoformat())
            )
            return None
        self.db.execute("DELETE FROM login_failures WHERE username = ?", (u,))
        assert row is not None
        user = _row_user(row[:6])
        return None if self._expired(user) else user

    # ------------------------------------------------------------------ sessions
    def new_session(self, user: User, lang: str = "en") -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self.clock().isoformat()
        self.db.execute(
            "INSERT INTO sessions (token_sha, username, csrf, created, last_seen, lang) VALUES (?,?,?,?,?,?)",
            (_sha(token), user.username, csrf, now, now, lang),
        )
        return token, Session(user, csrf, lang, _sha(token))

    def session(self, token: str | None) -> Session | None:
        if not token or len(token) > 256:
            return None
        sha = _sha(token)
        now = self.clock()
        row = self.db.fetchone(
            "SELECT username, csrf, created, last_seen, lang FROM sessions WHERE token_sha = ?", (sha,)
        )
        if row is None:
            return None
        created, last = datetime.fromisoformat(row[2]), datetime.fromisoformat(row[3])
        user = self.get(str(row[0]))
        if user is None or now - created > ABSOLUTE or now - last > IDLE:
            self.end_session(token)
            return None
        self.db.execute("UPDATE sessions SET last_seen = ? WHERE token_sha = ?", (now.isoformat(), sha))
        return Session(user, str(row[1]), str(row[4]), sha)

    def set_lang(self, session: Session, lang: str) -> None:
        self.db.execute("UPDATE sessions SET lang = ? WHERE token_sha = ?", (lang, session.token_sha))

    def end_session(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_sha = ?", (_sha(token),))

    # ------------------------------------------------------------------ first start
    def bootstrap_from_file(self, path: Path, username: str = "admin", mailbox: str | None = None) -> User | None:
        """Create the first administrator from a secret file when no administrator exists yet; None otherwise."""
        if self.count("admin") > 0 or not path.is_file():
            return None
        password = path.read_text(encoding="utf-8").strip()
        return self.create(username, "admin", password, mailbox)


def csrf_ok(session: Session, submitted: str | None) -> bool:
    return bool(submitted) and hmac.compare_digest(session.csrf, submitted or "")


REVEAL_REASONS = ("contact", "eligibility", "consent", "other")


def reveal_reason(value: str) -> str:
    """FR-AUD-01b: the reason recorded with a chart-number reveal. The console forms always send one of
    ``REVEAL_REASONS``; anything else (an old page, a scripted call) is recorded as ``not given`` so the audit never
    invents one."""
    v = (value or "").strip().lower()
    return v if v in REVEAL_REASONS else "not given"
