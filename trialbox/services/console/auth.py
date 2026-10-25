"""Console accounts, sessions and CSRF (spec v4 §3.8, FR-SIG-14 headers; ASVS V2/V3 basics).

* Accounts live in the console's own SQLite file (``/data/console/console.sqlite``). There is no default password: the
  first administrator is created by ``python -m console.cli bootstrap-admin`` (random password printed once) or, at
  first start, from the file named by ``TB_CONSOLE_ADMIN_PASSWORD_FILE`` (a compose secret).
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
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

Role = Literal["admin", "viewer"]
ROLES: tuple[Role, ...] = ("admin", "viewer")
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=8)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_USERNAME_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY,
  role TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  mailbox TEXT,
  created TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token_sha TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  csrf TEXT NOT NULL,
  created TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS login_failures (
  username TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_failures_user ON login_failures (username, at);
"""


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

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    lang: str
    token_sha: str


Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UserStore:
    def __init__(self, path: Path, clock: Clock = _utcnow) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(SCHEMA)
        self.clock = clock

    # ------------------------------------------------------------------ users
    def count(self, role: Role | None = None) -> int:
        with self._lock:
            if role is None:
                row = self._con.execute("SELECT count(*) FROM users WHERE disabled = 0").fetchone()
            else:
                row = self._con.execute(
                    "SELECT count(*) FROM users WHERE disabled = 0 AND role = ?", (role,)
                ).fetchone()
        return int(row[0])

    def users(self) -> list[User]:
        with self._lock:
            rows = self._con.execute(
                "SELECT username, role, mailbox FROM users WHERE disabled = 0 ORDER BY username"
            ).fetchall()
        return [User(str(u), str(r), m) for u, r, m in rows]  # type: ignore[arg-type]

    def get(self, username: str) -> User | None:
        with self._lock:
            row = self._con.execute(
                "SELECT username, role, mailbox FROM users WHERE username = ? AND disabled = 0", (username,)
            ).fetchone()
        return User(str(row[0]), row[1], row[2]) if row else None

    def create(self, username: str, role: Role, password: str, mailbox: str | None = None) -> User:
        u = check_username(username)
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        check_password_policy(password)
        mb = mailbox.strip().lower() if mailbox else None
        if mb is not None and ("@" not in mb or " " in mb):
            raise AuthError("mailbox must be an e-mail address")
        with self._lock:
            if self._con.execute("SELECT 1 FROM users WHERE username = ?", (u,)).fetchone():
                raise AuthError(f"user {u} exists")
            self._con.execute(
                "INSERT INTO users (username, role, pw_hash, mailbox, created) VALUES (?,?,?,?,?)",
                (u, role, hash_password(password), mb, self.clock().isoformat()),
            )
        return User(u, role, mb)

    def set_password(self, username: str, password: str) -> None:
        check_password_policy(password)
        with self._lock:
            cur = self._con.execute(
                "UPDATE users SET pw_hash = ? WHERE username = ?", (hash_password(password), username)
            )
            if cur.rowcount != 1:
                raise AuthError(f"no user {username}")
            self._con.execute("DELETE FROM sessions WHERE username = ?", (username,))  # sign out everywhere
            self._con.execute("DELETE FROM login_failures WHERE username = ?", (username,))

    def disable(self, username: str) -> None:
        with self._lock:
            self._con.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            self._con.execute("DELETE FROM sessions WHERE username = ?", (username,))

    # ------------------------------------------------------------------ login
    def locked(self, username: str) -> bool:
        since = (self.clock() - LOCKOUT).isoformat()
        with self._lock:
            row = self._con.execute(
                "SELECT count(*) FROM login_failures WHERE username = ? AND at >= ?", (username, since)
            ).fetchone()
        return int(row[0]) >= MAX_FAILURES

    def authenticate(self, username: str, password: str) -> User | None:
        """The user, or None (unknown user, wrong password, disabled or locked). Constant work for unknown users."""
        u = username.strip().lower()
        with self._lock:
            row = self._con.execute(
                "SELECT username, role, mailbox, pw_hash FROM users WHERE username = ? AND disabled = 0", (u,)
            ).fetchone()
        stored = str(row[3]) if row else hash_password("unknown-user-dummy-password")
        ok = verify_password(password, stored) and row is not None
        if self.locked(u):
            return None
        if not ok:
            with self._lock:
                self._con.execute(
                    "INSERT INTO login_failures (username, at) VALUES (?,?)", (u[:64], self.clock().isoformat())
                )
            return None
        with self._lock:
            self._con.execute("DELETE FROM login_failures WHERE username = ?", (u,))
        assert row is not None
        return User(str(row[0]), row[1], row[2])

    # ------------------------------------------------------------------ sessions
    def new_session(self, user: User, lang: str = "en") -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self.clock().isoformat()
        with self._lock:
            self._con.execute(
                "INSERT INTO sessions (token_sha, username, csrf, created, last_seen, lang) VALUES (?,?,?,?,?,?)",
                (_sha(token), user.username, csrf, now, now, lang),
            )
        return token, Session(user, csrf, lang, _sha(token))

    def session(self, token: str | None) -> Session | None:
        if not token or len(token) > 256:
            return None
        sha = _sha(token)
        now = self.clock()
        with self._lock:
            row = self._con.execute(
                "SELECT username, csrf, created, last_seen, lang FROM sessions WHERE token_sha = ?", (sha,)
            ).fetchone()
        if row is None:
            return None
        created, last = datetime.fromisoformat(row[2]), datetime.fromisoformat(row[3])
        user = self.get(str(row[0]))
        if user is None or now - created > ABSOLUTE or now - last > IDLE:
            self.end_session(token)
            return None
        with self._lock:
            self._con.execute("UPDATE sessions SET last_seen = ? WHERE token_sha = ?", (now.isoformat(), sha))
        return Session(user, str(row[1]), str(row[4]), sha)

    def set_lang(self, session: Session, lang: str) -> None:
        with self._lock:
            self._con.execute("UPDATE sessions SET lang = ? WHERE token_sha = ?", (lang, session.token_sha))

    def end_session(self, token: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM sessions WHERE token_sha = ?", (_sha(token),))

    # ------------------------------------------------------------------ first start
    def bootstrap_from_file(self, path: Path, username: str = "admin", mailbox: str | None = None) -> User | None:
        """Create the first administrator from a secret file when no administrator exists yet; None otherwise."""
        if self.count("admin") > 0 or not path.is_file():
            return None
        password = path.read_text(encoding="utf-8").strip()
        return self.create(username, "admin", password, mailbox)


def csrf_ok(session: Session, submitted: str | None) -> bool:
    return bool(submitted) and hmac.compare_digest(session.csrf, submitted or "")
