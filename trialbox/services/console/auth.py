"""Console accounts, sessions and CSRF (spec v4 §3.8, FR-SIG-14 headers; ASVS V2/V3 basics).

* Accounts live in the trial database (PostgreSQL ``trialbox_wf``, schema ``auth``; D-126). There is no default
  password: the first administrator is created by ``python -m console.cli bootstrap-admin`` (random password printed
  once) or, at first start, from the file named by ``TB_CONSOLE_ADMIN_PASSWORD_FILE`` (a compose secret).
* Passwords are stored as scrypt hashes (stdlib ``hashlib.scrypt``, per-user salt); at least 12 characters. A new
  password is refused when it is one of the account's last five (the current one and the four before it, kept as
  their scrypt hashes in ``users.pw_history``) or on the operator's breached-password list (``console.breached``,
  ``TB_CONSOLE_BREACHED_PASSWORDS_FILE``; D-447, CR-033 rest).
* Failed sign-ins are counted per account *and* per address (D-279, SEC-9, CR-116): five failures within 15 minutes
  lock the account for 15 minutes *from that address only*, so an outsider cannot lock a named account out; an address
  with many failures across names is slowed (a doubling wait, at most a minute); and 50 failures on one account from
  any number of addresses lock it everywhere (the backstop against distributed guessing). A wrong second-factor code
  counts as a failed sign-in; an administrator can lift a lock early (``unlock``, audited; D-192). Rows older than the
  15-minute window are deleted as new ones arrive, so the table stays small.
* A password someone else set (an administrator's new account or reset, the command line) must be replaced by its
  owner before the account does anything else (``must_change``; D-279, SEC-1, 21 CFR 11.300): only the owner ever
  knows a password that signs.
* Sessions are server-side: the cookie carries a random token, the table stores only its SHA-256. Idle timeout
  (default 10 min, ``TB_CONSOLE_IDLE_MINUTES``) and absolute lifetime (default 8 h, ``TB_CONSOLE_SESSION_HOURS``).
  Each session has its own CSRF token, checked on every state-changing request.
* Local accounts carry an optional TOTP secret (``console.totp``), sealed with a key outside the database; the
  sign-in in two steps, the enrolment and the hospital identity provider (OIDC) are in ``console.identity`` (D-192).
* Roles: the matrix's (``tb_common.authz_matrix.yaml``): administrator (IT operator, no patient data), coordinator,
  investigator, viewer, CRO, data steward and privacy office (D-280, D-380). What each may do is generated from the
  matrix (``tb_common.authz.role_rights``) for ``/ops/users``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from tb_common.authz import permit

from console.storedb import open_db
from console.timefmt import local_today, site_zone

Role = Literal["admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy"]
# D-280 (OD-5): the data steward keeps the opt-out register and the staff directory and reviews every break-glass use;
# the administrator (IT operator) sees no patient data except by break-glass (``console.breakglass``). D-380 (T-102b):
# the privacy office keeps the opt-out register and the staff directory with the steward, and nobody else does.
ROLES: tuple[Role, ...] = ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")
# D-104: where an account sits. An SMO coordinator is a study-scoped coordinator; a CRO account is aggregate-only.
AFFILIATIONS: tuple[str, ...] = ("hospital", "smo", "cro")
# D-380 (ROLE-011): an SMO or CRO account (by affiliation, or a CRO-role account) names its studies; saving one without
# is refused, and one stored without any sees no study (``NO_STUDY`` stands for "none", never a ruleset id).
SCOPED_AFFILIATIONS: tuple[str, ...] = ("smo", "cro")
NO_STUDY = "-"
SSO_MARK = "sso"  # pw_hash of an account the hospital identity provider signs in (no console password)
OIDC_MARK = "oidc"  # pw_hash of an account signed in through the OIDC provider (Authelia; D-192)
MIN_PASSWORD = 12
PASSWORD_HISTORY = 5  # the current password and the four before it may not be chosen again (D-447; MHLW v7.0)
MAX_FAILURES = 5  # per account and address (D-279)
LOCKOUT = timedelta(minutes=15)
NAME_CEILING = 50  # per account from all addresses: the account locks everywhere (distributed guessing; D-279)
SOURCE_FREE = 10  # failures one address may make across names before each try waits (D-279)
SOURCE_MAX_WAIT = timedelta(seconds=60)  # slowed, never locked: a hospital's shared address keeps working
OIDC_ABSOLUTE = timedelta(minutes=60)  # an OIDC session's lifetime: the directory is asked again (D-279, CR-117)
IDLE = timedelta(minutes=10)  # D-192: the IT security pack's idle lock for shared clinic PCs
ABSOLUTE = timedelta(hours=8)
PENDING_TTL = timedelta(minutes=10)  # between the password and the code (enrolment included; D-192)
OIDC_STATE_TTL = timedelta(minutes=10)  # between leaving for the identity provider and coming back
ENROL_TTL = timedelta(hours=24)  # an administrator's enrolment code for a new authenticator (D-192, review H2)
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
# D-192: the TOTP secret (sealed, console.totp.SecretBox) and the last accepted step (replay guard); the identity
# provider's subject an OIDC account is bound to; the half-done sign-ins (password checked, code not yet) and the
# OIDC round trips in flight. Only hashes of the browser-held tokens are stored.
SCHEMA_V2 = """
ALTER TABLE users ADD COLUMN totp_secret TEXT;
ALTER TABLE users ADD COLUMN totp_step BIGINT;
ALTER TABLE users ADD COLUMN idp_sub TEXT;
ALTER TABLE users ADD COLUMN enrol_code_sha TEXT;
ALTER TABLE users ADD COLUMN enrol_expires TEXT;
ALTER TABLE users ADD COLUMN enrol_reason TEXT;
CREATE TABLE pending_logins (
  token_sha TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  csrf TEXT NOT NULL,
  created TEXT NOT NULL,
  enroll_secret TEXT
);
CREATE TABLE oidc_pending (
  state_sha TEXT PRIMARY KEY,
  nonce TEXT NOT NULL,
  verifier TEXT NOT NULL,
  created TEXT NOT NULL
)
"""
# D-279: ``must_change`` marks a password someone else set (SEC-1); each failure keeps the address it came from
# (SEC-9: the lock is per account and address); each session keeps how it was opened (``via``: an OIDC session has
# a shorter life, CR-117; T-505a refuses an API session as a cookie).
SCHEMA_V3 = """
ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0;
ALTER TABLE login_failures ADD COLUMN source TEXT COLLATE "C" NOT NULL DEFAULT '';
CREATE INDEX login_failures_source ON login_failures (source, at);
CREATE INDEX login_failures_at ON login_failures (at);
ALTER TABLE sessions ADD COLUMN via TEXT NOT NULL DEFAULT ''
"""
# T-209c (D-406, review OPS-059): when each account last opened a session, for the unused-account report
SCHEMA_V4 = """
ALTER TABLE users ADD COLUMN last_login TEXT
"""
# D-447 (T-109b): the scrypt hashes of the account's earlier passwords, newest first, space-separated (password history)
SCHEMA_V5 = """
ALTER TABLE users ADD COLUMN pw_history TEXT
"""
# D-719 (NEW-SEC-3): nobody holds both factors of a protected account. ``opened_by``: who was shown the account's
# first enrolment code (the requester alone, or the person who confirmed); ``holder_set`` 0 until the holder chooses
# the password with that code; ``enrol_used_at``: when the code was first used, and ``enrol_spent_sha`` its hash (so
# only a person who types that code learns it was used). Each factor an administrator set
# (``factor_resets``), each request waiting for a second person (``account_requests``) and each notice the holder
# reads at the next sign-in (``account_notices``). A half-done sign-in that came through the code skips it at the
# authenticator step (``enrol_ok``). Accounts made before keep their factors: nothing here is filled for them.
SCHEMA_V6 = """
ALTER TABLE users ADD COLUMN opened_by TEXT;
ALTER TABLE users ADD COLUMN holder_set INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN enrol_used_at TEXT;
ALTER TABLE users ADD COLUMN enrol_spent_sha TEXT;
ALTER TABLE pending_logins ADD COLUMN enrol_ok INTEGER NOT NULL DEFAULT 0;
CREATE TABLE factor_resets (
  username TEXT COLLATE "C" NOT NULL,
  factor TEXT NOT NULL,
  by_user TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX factor_resets_user ON factor_resets (username, at);
CREATE TABLE account_requests (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  username TEXT NOT NULL,
  payload TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  requested_at TEXT COLLATE "C" NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT,
  decided_at TEXT
);
CREATE TABLE account_notices (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  kind TEXT NOT NULL,
  by_user TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0
)
"""
# STEPS-ROLE (D-877, the owner's D-1063): on a test box an account may act in extra roles (``extra_roles``, granted
# only by the boot tool ``console.steps_roles``), and a session carries the role it acts in (``acting_role``; none:
# the account's own role)
SCHEMA_V7 = """
ALTER TABLE users ADD COLUMN extra_roles TEXT;
ALTER TABLE sessions ADD COLUMN acting_role TEXT
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7)
FACTORS = ("password", "totp")
FACTOR_WINDOW = timedelta(days=30)  # D-719: the owner's rule, not a setting: one factor at a time for 30 days
_COLS = "username, role, mailbox, affiliation, studies, expires"


class AuthError(ValueError):
    pass


class PasswordRejected(AuthError):
    """A new password the rules refuse; ``code`` is the message key the account page shows (D-447)."""

    def __init__(self, message: str, code: str = "account.err.policy") -> None:
        super().__init__(message)
        self.code = code


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
    """Length, no white space at either end, and not on the operator's breached-password list (D-447). A list that is
    configured and cannot be read refuses every password (fail closed)."""
    from console import breached

    if len(password) < MIN_PASSWORD:
        raise PasswordRejected(f"passwords must be at least {MIN_PASSWORD} characters")
    if password.strip() != password:
        raise PasswordRejected("passwords must not start or end with white space")
    try:
        hit = breached.check(password)
    except breached.BreachedListError as exc:
        msg = f"the breached-password list cannot be used: {exc}"
        raise PasswordRejected(msg, "account.err.breached_list") from exc
    if hit:
        raise PasswordRejected("this password is on the list of breached passwords", "account.err.breached")


def check_username(username: str) -> str:
    u = username.strip().lower()
    if not 1 <= len(u) <= 32 or not set(u) <= _USERNAME_OK:
        raise AuthError("user names are 1-32 characters: a-z, 0-9, '.', '_' or '-'")
    return u


# D-133 (review F-02): a one-time password is read out over the phone or handed over on paper, so it has no
# characters that look alike (0/o, 1/l/i) and comes in groups of four: "k7dm-q3xa-..." (5 groups, ~99 bits).
READABLE = "abcdefghjkmnpqrstuvwxyz23456789"


def random_password(groups: int = 5) -> str:
    return "-".join("".join(secrets.choice(READABLE) for _ in range(4)) for _ in range(groups))


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


API_VIAS = ("api", "api+totp")  # how a bearer session of /api/v1 was opened (T-505a, D-320)


def is_api_via(via: str) -> bool:
    """True for a session opened on ``POST /api/v1/session``: a bearer token, never a cookie (ROLE-001)."""
    return via in API_VIAS


def source_of(host: str | None) -> str:
    """The address a sign-in is counted under (D-279): an IPv4 address as is, an IPv6 address by its /64 (one
    household or one machine holds a whole /64, so counting single IPv6 addresses would not slow anyone). Anything
    else (a test client's name, no peer) is kept as given, cut to 64 characters."""
    h = (host or "").strip()
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return h[:64]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:  # an IPv4 client on a dual-stack socket
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


@dataclass(frozen=True)
class User:
    """A console account. Its rights are wrappers over ``tb_common.authz.permit`` (T-102a, D-366): each property reads
    one row of ``authz_matrix.yaml``; none compares the role itself."""

    username: str
    role: Role
    mailbox: str | None
    affiliation: str = "hospital"
    studies: tuple[str, ...] = ()  # empty = every study (D-104); never empty for an SMO or CRO account (D-380)
    expires: str | None = None  # ISO date; sign-in refused after it

    def __post_init__(self) -> None:
        # D-380 (ROLE-011): an SMO or CRO account without studies sees none (fails closed), never every study
        if not self.studies and needs_studies(self.role, self.affiliation):
            object.__setattr__(self, "studies", (NO_STUDY,))

    @property
    def is_admin(self) -> bool:
        """The administrator (the IT operator): the account the operations rows name (T-102c, D-425)."""
        return is_operator(self.role)

    @property
    def sponsor_form(self) -> bool:
        """A sponsor's account (CRO): reports in the sponsor form and the sponsor pack only, never a site page of one
        study (D-104; the matrix's ``report.sponsor_form`` row, T-102c)."""
        return permit(self.role, "report.sponsor_form").allowed

    @property
    def can_request(self) -> bool:
        """May start requests and edit the registry: administrators and coordinators (D-93)."""
        return permit(self.role, "request.prepare").allowed

    @property
    def can_view_phi(self) -> bool:
        """May read patient-level results in the browser: the CASE sheet and the pseudonymous candidate rows.
        Coordinators and investigators (D-101). D-280 (OD-5, CR-023): never the administrator, who reads one
        patient or one job only through a break-glass grant (``console.breakglass``); never the steward here (the
        steward's own pages are T-102b's)."""
        return permit(self.role, "phi.view").allowed

    @property
    def can_reveal(self) -> bool:
        """May see and reveal chart numbers and patient identifying details (audited, rate-limited): administrators,
        coordinators and, by the owner's decision of 2026-11-09 (D-143, reversing D-133's "may not"), the
        investigator, who holds full authorisation for the study. Viewer and CRO (sponsor, monitor) accounts never.
        D-280 (OD-5, CR-023): no longer the administrator, who reveals only under a break-glass grant."""
        return permit(self.role, "id.reveal").allowed

    def sees_ids(self, ruleset: str | None) -> bool:
        """Identifier authority for one study: may reveal and the study is one of the account's (D-143). A job or
        page without a study counts as any study the account sees (an unscoped account)."""
        return self.can_reveal and (self.sees_study(ruleset) if ruleset else not self.studies)

    @property
    def can_mark(self) -> bool:
        """May mark weekly-list patients Approach / Not suitable / Need info: investigators (D-104)."""
        return permit(self.role, "list.mark").allowed

    @property
    def can_approve(self) -> bool:
        """May approve a study's criteria (S20, FR-AUTH-13, D-108): the investigator only. Administrators and
        coordinators prepare the approval (tick codes) but never approve."""
        return permit(self.role, "criteria.approve").allowed

    @property
    def aggregate_only(self) -> bool:
        """Sees aggregate reports only, in the sponsor (suppressed) form for CRO accounts (D-104)."""
        return permit(self.role, "report.aggregate_only").allowed

    def sees_study(self, ruleset: str) -> bool:
        return not self.studies or ruleset.upper() in self.studies


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str
    lang: str
    token_sha: str
    #: STEPS-ROLE (D-877): the account's own role while the session acts in another (``user.role`` is the acting
    #: role then, read by every permission check); None when the session acts in the account's own role
    acting_from: str | None = None


Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _row_user(row: tuple[object, ...]) -> User:
    u, r, m, aff, studies, exp = row
    st = tuple(x for x in str(studies or "").upper().replace(" ", "").split(",") if x)
    return User(str(u), r, m, str(aff or "hospital"), st, str(exp) if exp else None)  # type: ignore[arg-type]


def needs_studies(role: str, affiliation: str) -> bool:
    """D-380 (ROLE-011): an SMO or CRO account must name its studies (by affiliation, or a CRO-role account)."""
    return affiliation in SCOPED_AFFILIATIONS or permit(role, "report.sponsor_form").allowed


def is_operator(role: str) -> bool:
    """The administrator role: the one the operations rows (``ops.view``) name (T-102c, D-425). An operator account
    is the one account without an end date (D-406)."""
    return permit(role, "ops.view").allowed


def scope_values(affiliation: str, studies: str, expires: str | None, role: str = "") -> tuple[str, str, str | None]:
    """Checked affiliation, study list and end date of an account (D-104); raises AuthError. D-380 (ROLE-011): an SMO
    or CRO account without a study is refused."""
    aff = (affiliation or "hospital").strip().lower()
    if aff not in AFFILIATIONS:
        raise AuthError(f"affiliation must be one of {', '.join(AFFILIATIONS)}")
    st = ",".join(x for x in studies.upper().replace(" ", "").split(",") if x)
    if st and not all(re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,31}", x) for x in st.split(",")):
        raise AuthError("studies are ruleset ids separated by commas")
    if not st and needs_studies(role, aff):
        raise AuthError("an SMO or CRO account names its studies (ruleset ids separated by commas)")
    exp = (expires or "").strip() or None
    if exp is not None:
        try:
            date.fromisoformat(exp)
        except ValueError as exc:
            raise AuthError("end date must be YYYY-MM-DD") from exc
    return aff, st, exp


class UserStore:
    """Schema ``auth`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(
        self,
        url: str | None = None,
        clock: Clock = _utcnow,
        idle: timedelta = IDLE,
        absolute: timedelta = ABSOLUTE,
        oidc_absolute: timedelta = OIDC_ABSOLUTE,
    ) -> None:
        self.db = open_db(url, "auth", MIGRATIONS)
        self.clock = clock
        self.idle = idle
        self.absolute = absolute
        self.oidc_absolute = oidc_absolute
        self.zone: ZoneInfo | None = None  # the site's zone, set by console.app (D-270)
        self.enrol_ttl = ENROL_TTL  # D-719: TB_CONSOLE_ENROL_CODE_HOURS, set by console.app
        #: STEPS-ROLE (D-877): whether a session may act in an extra role now (the flag on, on a test box: set by
        #: console.app from console.acting); off, every account is its own role only
        self.acting_on: Callable[[], bool] = lambda: False

    def close(self) -> None:
        self.db.close()

    def today(self) -> date:
        """The site's calendar date (D-270): an end date is a site day, and the clock is a UTC instant."""
        return local_today(self.clock(), self.zone or site_zone(None))

    def _expired(self, user: User) -> bool:
        return bool(user.expires) and self.today().isoformat() > str(user.expires)

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
        the studies on its contract with an end date; a CRO account is aggregate-only whatever its scope. D-380
        (ROLE-011): an SMO or CRO account without a study is refused."""
        role = self.db.fetchval("SELECT role FROM users WHERE username = ?", (username,))
        aff, st, exp = scope_values(affiliation, studies, expires, str(role or ""))
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

    def create(
        self, username: str, role: Role, password: str, mailbox: str | None = None, *, must_change: bool = False
    ) -> User:
        """A local account. ``must_change``: the password was set by someone other than the owner (an
        administrator's page, the command line), so the owner must replace it before anything else (D-279)."""
        u = check_username(username)
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        check_password_policy(password)
        mb = mailbox.strip().lower() if mailbox else None
        if mb is not None and ("@" not in mb or " " in mb):
            raise AuthError("mailbox must be an e-mail address")
        n = self.db.execute(
            "INSERT INTO users (username, role, pw_hash, mailbox, created, must_change) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (username) DO NOTHING",
            (u, role, hash_password(password), mb, self.clock().isoformat(), int(must_change)),
        )
        if n != 1:
            raise AuthError(f"user {u} exists")
        return User(u, role, mb)

    def upsert_sso(self, username: str, role: Role, mailbox: str | None) -> User:
        """The account behind a trusted identity header (D-93): created on first sight with no console password,
        role and mailbox refreshed on every sign-in so a change in the directory applies at once. Never signs in
        an account that has a console password or comes from OIDC: a header naming a local administrator is refused
        (D-192, review H1), so the header can never skip the password and the second factor."""
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
            else:  # a local (or OIDC) account: never through the header
                raise AuthError("a local account has this name")
            row = tx.fetchone(f"SELECT {_COLS} FROM users WHERE username = ?", (u,))
        assert row is not None
        user = _row_user(row)
        if self._expired(user):  # D-104: an account past its end date never signs in, SSO or not
            raise AuthError("account expired")
        return user

    def is_sso(self, username: str) -> bool:
        """Signs in through the hospital identity provider (trusted header or OIDC): no console password."""
        stored = self.db.fetchval("SELECT pw_hash FROM users WHERE username = ?", (username,))
        return stored in (SSO_MARK, OIDC_MARK)

    def is_oidc(self, username: str) -> bool:
        return bool(self.db.fetchval("SELECT pw_hash FROM users WHERE username = ?", (username,)) == OIDC_MARK)

    def idp_subject(self, username: str) -> str | None:
        """The identity provider's subject an OIDC account is bound to (T-205: a signature's re-authentication at
        the provider must come back for the same subject)."""
        got = self.db.fetchval("SELECT idp_sub FROM users WHERE username = ?", (username,))
        return str(got) if got else None

    def upsert_oidc(self, username: str, subject: str, role: Role, mailbox: str | None) -> User:
        """The account behind a verified OIDC sign-in (D-192). Created on first sight, bound to the provider's
        subject; the role (from the configured group map) and mailbox are refreshed on every sign-in. Refused for a
        name that belongs to a local or header-SSO account (the provider never takes over a local administrator) or
        to another subject, and for a disabled or expired account."""
        u = check_username(username)
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        if not subject or len(subject) > 255:
            raise AuthError("no subject from the identity provider")
        mb = mailbox.strip().lower() if mailbox else None
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT pw_hash, disabled, idp_sub FROM users WHERE username = ? FOR UPDATE", (u,))
            if row is None:
                tx.execute(
                    "INSERT INTO users (username, role, pw_hash, mailbox, created, idp_sub) VALUES (?,?,?,?,?,?)",
                    (u, role, OIDC_MARK, mb, self.clock().isoformat(), subject),
                )
            elif row[0] != OIDC_MARK:
                raise AuthError("a local account has this name")
            elif row[2] != subject:
                raise AuthError("this name belongs to another directory account")
            elif row[1]:
                raise AuthError("account disabled")
            else:
                tx.execute("UPDATE users SET role = ?, mailbox = ? WHERE username = ?", (role, mb, u))
            row = tx.fetchone(f"SELECT {_COLS} FROM users WHERE username = ?", (u,))
        assert row is not None
        user = _row_user(row)
        if self._expired(user):
            raise AuthError("account expired")
        return user

    def must_change(self, username: str) -> bool:
        """True while the account still has a password its owner did not choose (D-279, SEC-1)."""
        return bool(self.db.fetchval("SELECT must_change FROM users WHERE username = ?", (username,)))

    def set_password(self, username: str, password: str, *, must_change: bool = False, owner: bool = False) -> None:
        """A new password; the account signs out everywhere. ``must_change=True`` when someone other than the owner
        set it (an administrator's reset, the command line): the owner then replaces it at the next sign-in. The
        owner's own change (``/account/password``, after typing the current one) passes False (D-279) and
        ``owner=True``: the owner's choice may not be one of the account's last five passwords (D-447). Every
        change, the owner's or not, keeps the replaced hash in the history."""
        check_password_policy(password)
        pw_hash = hash_password(password)
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT pw_hash, pw_history FROM users WHERE username = ?", (username,))
            earlier = [str(row[0]), *str(row[1] or "").split()] if row is not None else []
            local = row is not None and str(row[0]) not in (SSO_MARK, OIDC_MARK)
            # D-447: the owner's choice is not the current password nor one of the four before it (one scrypt each)
            if owner and local and any(verify_password(password, old) for old in earlier[:PASSWORD_HISTORY]):
                raise PasswordRejected("this password was used recently on this account", "account.err.reused")
            history = " ".join(earlier[: PASSWORD_HISTORY - 1])
            n = tx.execute(
                "UPDATE users SET pw_hash = ?, must_change = ?, pw_history = ? WHERE username = ? "
                "AND pw_hash NOT IN (?, ?)",
                (pw_hash, int(must_change), history or None, username, SSO_MARK, OIDC_MARK),
            )
            if n != 1:  # a directory account has no console password, so none is ever set (D-279, REG-025)
                raise AuthError(f"no user {username} with a console password")
            tx.execute("DELETE FROM sessions WHERE username = ?", (username,))  # sign out everywhere
            tx.execute("DELETE FROM login_failures WHERE username = ?", (username,))
            tx.execute("DELETE FROM pending_logins WHERE username = ?", (username,))  # a half-done sign-in too

    def disable(self, username: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            tx.execute("DELETE FROM sessions WHERE username = ?", (username,))
            tx.execute("DELETE FROM pending_logins WHERE username = ?", (username,))

    def enable(self, username: str) -> None:
        """D-178 (review J-14): the undo of :meth:`disable`. The password is the one the account had; its sessions
        stay ended (the person signs in again)."""
        with self.db.transaction() as tx:
            if tx.execute("UPDATE users SET disabled = 0 WHERE username = ? AND disabled = 1", (username,)) != 1:
                raise AuthError(f"no disabled account {username}")

    def activity(self) -> dict[str, tuple[str, str | None]]:
        """(created, last sign-in) of every active account, both UTC ISO text; the last sign-in is None when the
        account never opened a session since T-209c (D-406, OPS-059: the unused-account report)."""
        rows = self.db.fetchall("SELECT username, created, last_login FROM users WHERE disabled = 0")
        return {str(u): (str(c or ""), str(last) if last else None) for u, c, last in rows}

    def disabled_users(self) -> list[User]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM users WHERE disabled = 1 ORDER BY username")
        return [_row_user(r) for r in rows]

    # ------------------------------------------------------------------ login (D-192; D-279 per address)
    def _failures(self, username: str) -> list[tuple[str, datetime]]:
        """(address, time) of each failure of one account inside the window, newest first."""
        since = (self.clock() - LOCKOUT).isoformat()
        rows = self.db.fetchall(
            "SELECT source, at FROM login_failures WHERE username = ? AND at >= ? ORDER BY at DESC",
            (username.strip().lower()[:64], since),
        )
        return [(str(r[0]), datetime.fromisoformat(str(r[1]))) for r in rows]

    def locked_until(self, username: str, source: str | None = None) -> datetime | None:
        """When a locked account opens again for ``source`` (D-133, review F-05: the sign-in page shows it), or None.

        Locked when five failures within 15 minutes came from that address, or 50 from all addresses together (D-279).
        ``source=None`` asks about any address (the administrator's identity page). Unknown names lock the same way,
        so this tells nothing about which accounts exist."""
        rows = self._failures(username)
        ends: list[datetime] = []
        if len(rows) >= NAME_CEILING:
            ends.append(rows[NAME_CEILING - 1][1] + LOCKOUT)
        by_source: dict[str, list[datetime]] = {}
        for src, at in rows:
            if source is None or src == source:
                by_source.setdefault(src, []).append(at)
        ends.extend(ats[MAX_FAILURES - 1] + LOCKOUT for ats in by_source.values() if len(ats) >= MAX_FAILURES)
        return max(ends) if ends else None

    def locked(self, username: str, source: str | None = None) -> bool:
        """Locked from ``source``, or from any address when it is None (D-279)."""
        return self.locked_until(username, source) is not None

    def throttled(self, source: str) -> int:
        """Seconds the address ``source`` must still wait before its next sign-in try, or 0 (D-279, SEC-9). After
        ``SOURCE_FREE`` failures within 15 minutes across all names, each further try waits twice as long after the
        last failure (1 s, 2 s, 4 s, ... at most ``SOURCE_MAX_WAIT``): guessing is slowed, nobody is locked out."""
        since = (self.clock() - LOCKOUT).isoformat()
        row = self.db.fetchone("SELECT count(*), max(at) FROM login_failures WHERE source = ? AND at >= ?",
                               (source, since))  # fmt: skip
        n = int(row[0]) if row else 0
        if n < SOURCE_FREE or not row or row[1] is None:
            return 0
        wait = min(timedelta(seconds=2 ** min(n - SOURCE_FREE, 16)), SOURCE_MAX_WAIT)
        left = datetime.fromisoformat(str(row[1])) + wait - self.clock()
        return max(0, -(-int(left.total_seconds() * 1000) // 1000))

    def record_failure(self, username: str, source: str = "") -> None:
        """One failed sign-in step (a wrong password or a wrong or replayed second-factor code) from ``source``.
        Rows older than the window go at the same time, so the table holds 15 minutes of failures at most."""
        u = username.strip().lower()[:64]
        now = self.clock()
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM login_failures WHERE at < ?", ((now - LOCKOUT).isoformat(),))
            tx.execute("INSERT INTO login_failures (username, at, source) VALUES (?,?,?)",
                       (u, now.isoformat(), source[:64]))  # fmt: skip

    def clear_failures(self, username: str, source: str | None = None) -> int:
        """Forget an account's failures: from one address (a right sign-in from there) or from all (``None``)."""
        u = username.strip().lower()[:64]
        if source is None:
            return self.db.execute("DELETE FROM login_failures WHERE username = ?", (u,))
        return self.db.execute("DELETE FROM login_failures WHERE username = ? AND source = ?", (u, source))

    def unlock(self, username: str) -> bool:
        """An administrator lifts a lock before it runs out, from every address (D-192; the caller audits it). True
        when it was locked from at least one."""
        was = self.locked(username.strip().lower()[:64], None)
        self.clear_failures(username)
        return was

    def authenticate(self, username: str, password: str, clear_failures: bool = True, source: str = "") -> User | None:
        """The user, or None (unknown user, wrong password, disabled, locked from ``source`` or ``source`` must still
        wait). Constant work for unknown users. With a second factor to come, ``clear_failures=False`` keeps the
        failure count until the code is right, so a known password does not reset the count of wrong codes (D-192).

        A try while the account is locked from this address is recorded under the address only (an empty name): it
        still slows the address, and it never adds to the account's count from all addresses (D-279)."""
        u = username.strip().lower()
        row = self.db.fetchone(f"SELECT {_COLS}, pw_hash FROM users WHERE username = ? AND disabled = 0", (u,))
        stored = str(row[6]) if row else hash_password("unknown-user-dummy-password")
        ok = verify_password(password, stored) and row is not None
        if self.throttled(source):
            return None
        if self.locked(u, source):
            self.record_failure("", source)
            return None
        if not ok:
            self.record_failure(u, source)
            return None
        if clear_failures:
            self.clear_failures(u, source)
        assert row is not None
        user = _row_user(row[:6])
        return None if self._expired(user) else user

    # ------------------------------------------------------------------ sessions
    def new_session(self, user: User, lang: str = "en", via: str = "") -> tuple[str, Session]:
        """A session; ``via`` says how it was opened (``password``, ``password+totp``, ``oidc``, ``sso``, ``api``,
        ``api+totp``; D-279, D-320): an ``oidc`` session lives ``oidc_absolute`` at most, so a person removed from the
        directory loses the console within that time (CR-117)."""
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self.clock().isoformat()
        self.db.execute(
            "INSERT INTO sessions (token_sha, username, csrf, created, last_seen, lang, via) VALUES (?,?,?,?,?,?,?)",
            (_sha(token), user.username, csrf, now, now, lang, via[:16]),
        )
        self.db.execute("UPDATE users SET last_login = ? WHERE username = ?", (now, user.username))  # D-406
        return token, Session(user, csrf, lang, _sha(token))

    def session(self, token: str | None, touch: bool = True, api: bool = False) -> Session | None:
        """The live session of ``token``. ``touch=False`` (a page's own auto-refresh, D-192 review H3) reads the
        session without counting the request as activity, so an open page that refreshes itself still locks.

        A session belongs to one channel (T-505a, D-320, ROLE-001): a token from ``POST /api/v1/session`` (``via``
        ``api`` or ``api+totp``) is a bearer token only and is no cookie for the pages; a page's session is no bearer
        token. ``api=True`` asks for a bearer token. The other channel's token reads as no session; it is not ended."""
        if not token or len(token) > 256:
            return None
        sha = _sha(token)
        now = self.clock()
        row = self.db.fetchone(
            "SELECT username, csrf, created, last_seen, lang, via, acting_role FROM sessions WHERE token_sha = ?",
            (sha,),
        )
        if row is None or is_api_via(str(row[5])) != api:
            return None
        created, last = datetime.fromisoformat(row[2]), datetime.fromisoformat(row[3])
        user = self.get(str(row[0]))
        # D-279 (CR-117): a directory session is asked of the directory again after ``oidc_absolute``
        absolute = min(self.absolute, self.oidc_absolute) if row[5] == "oidc" else self.absolute
        if user is None or now - created > absolute or now - last > self.idle:
            self.end_session(token)
            return None
        if touch:
            self.db.execute("UPDATE sessions SET last_seen = ? WHERE token_sha = ?", (now.isoformat(), sha))
        return self._acting(Session(user, str(row[1]), str(row[4]), sha), str(row[6] or ""))

    # ------------------------------------------------------------------ acting role (STEPS-ROLE, D-877)
    def _acting(self, sess: Session, acting: str) -> Session:
        """The one place a request's role is resolved: the session's acting role, when the flag is on (on a test box)
        and the account still holds that role, replaces the account's role on the session's user, so every permission
        check reads it as it reads an account's role. The user name stays (the delegation log, the audit trail and
        the erasure records name the person). Otherwise the account's own role."""
        if not acting or acting == sess.user.role or acting not in self.extra_roles(sess.user.username):
            return sess
        if not self.acting_on():
            return sess
        return replace(sess, user=replace(sess.user, role=acting), acting_from=sess.user.role)  # type: ignore[arg-type]

    def extra_roles(self, username: str) -> tuple[str, ...]:
        """The roles besides its own an account may act in (a test box only; granted by ``console.steps_roles``)."""
        raw = self.db.fetchval("SELECT extra_roles FROM users WHERE username = ?", (username,))
        return tuple(r for r in str(raw or "").split(",") if r in ROLES)

    def any_extra_roles(self) -> bool:
        return bool(self.db.fetchval("SELECT count(*) FROM users WHERE coalesce(extra_roles, '') <> ''"))

    def grant_roles(self, username: str, roles: list[str], allowed: bool) -> tuple[str, ...]:
        """Let ``username`` act in ``roles`` (its own role left out). ``allowed``: the box is a test box
        (``console.acting.env_allows``); refused otherwise, so the column is never filled on a validation or
        production box. Only the boot tool calls this; no console page does."""
        if not allowed:
            raise AuthError("extra roles are for a test box only (TB_ENV DEV or TEST)")
        own = self.role_of(username)
        if not own:
            raise AuthError(f"no account {username}")
        bad = [r for r in roles if r not in ROLES]
        if bad:
            raise AuthError(f"role must be one of {', '.join(ROLES)} (got {', '.join(bad)})")
        extra = tuple(sorted({r for r in roles if r != own}))
        self.db.execute("UPDATE users SET extra_roles = ? WHERE username = ?", (",".join(extra) or None, username))
        return extra

    def set_acting(self, sess: Session, role: str) -> tuple[str, str]:
        """The session acts in ``role`` from the next request: the account's own role, or one of its extra roles while
        acting is on. Returns (from, to); refused (``AuthError``) otherwise."""
        own = sess.acting_from or sess.user.role
        before = sess.user.role
        if role != own and (not self.acting_on() or role not in self.extra_roles(sess.user.username)):
            raise AuthError("this account may not act in that role")
        self.db.execute("UPDATE sessions SET acting_role = ? WHERE token_sha = ?",
                        (None if role == own else role, sess.token_sha))  # fmt: skip
        return before, role

    def end_sessions(self, username: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE username = ?", (username,))

    # ------------------------------------------------------------------ second factor (D-192)
    def totp_state(self, username: str) -> tuple[str | None, int | None]:
        """(sealed secret, last accepted step) of an account; (None, None) when it has no TOTP yet."""
        row = self.db.fetchone("SELECT totp_secret, totp_step FROM users WHERE username = ?", (username,))
        if row is None or not row[0]:
            return None, None
        return str(row[0]), (int(row[1]) if row[1] is not None else None)

    def set_totp(self, username: str, sealed: str, step: int) -> None:
        """Store a confirmed TOTP secret (the code that confirmed it used ``step``); the enrolment code is used up."""
        n = self.db.execute(
            "UPDATE users SET totp_secret = ?, totp_step = ?, enrol_code_sha = NULL, enrol_expires = NULL, "
            "enrol_reason = NULL WHERE username = ? AND totp_secret IS NULL",
            (sealed, step, username),
        )
        if n != 1:
            raise AuthError("this account already has an authenticator")

    def use_step(self, username: str, step: int) -> bool:
        """Record ``step`` as used; False when it (or a later one) was used already: a replayed code."""
        n = self.db.execute(
            "UPDATE users SET totp_step = ? WHERE username = ? AND totp_secret IS NOT NULL "
            "AND (totp_step IS NULL OR totp_step < ?)",
            (step, username, step),
        )
        return n == 1

    def reset_totp(self, username: str) -> str:
        """An administrator clears an account's authenticator (a lost phone; the caller audits it). The account
        signs out everywhere; the returned enrolment code (shown to the administrator once) is needed, with the
        password, to set up the new authenticator within ``ENROL_TTL`` (D-192, review H2)."""
        code = random_password(4)
        with self.db.transaction() as tx:
            n = tx.execute(
                "UPDATE users SET totp_secret = NULL, totp_step = NULL, enrol_code_sha = ?, enrol_expires = ?, "
                "enrol_reason = 'reset' WHERE username = ?",
                (_sha(code), (self.clock() + self.enrol_ttl).isoformat(), username),
            )
            if n != 1:
                raise AuthError(f"no user {username}")
            tx.execute("DELETE FROM sessions WHERE username = ?", (username,))
            tx.execute("DELETE FROM pending_logins WHERE username = ?", (username,))
        return code

    def issue_enrol_code(self, username: str) -> str:
        """A one-time enrolment code for an account without an authenticator (its first one, e.g. every account
        after the upgrade): shown to the administrator once, valid for ``ENROL_TTL``, only its hash stored."""
        code = random_password(4)
        n = self.db.execute(
            "UPDATE users SET enrol_code_sha = ?, enrol_expires = ?, "
            "enrol_reason = COALESCE(enrol_reason, 'first') WHERE username = ? AND totp_secret IS NULL "
            "AND disabled = 0",
            (_sha(code), (self.clock() + self.enrol_ttl).isoformat(), username),
        )
        if n != 1:
            raise AuthError("no account without an authenticator has this name")
        return code

    def enrol_state(self, username: str) -> tuple[bool, str]:
        """(a live enrolment code exists, why: 'first' or 'reset')."""
        row = self.db.fetchone("SELECT enrol_code_sha, enrol_expires, enrol_reason FROM users WHERE username = ?",
                               (username,))  # fmt: skip
        if row is None or not row[0] or not row[1]:
            return False, "first"
        live = self.clock() <= datetime.fromisoformat(str(row[1]))
        return live, str(row[2] or "first")

    def check_enrol_code(self, username: str, code: str) -> bool:
        """True when ``code`` is the account's live enrolment code (not used up, not expired)."""
        row = self.db.fetchone("SELECT enrol_code_sha, enrol_expires FROM users WHERE username = ?", (username,))
        if row is None or not row[0] or not row[1] or self.clock() > datetime.fromisoformat(str(row[1])):
            return False
        typed = "-".join(p for p in re.split(r"[\s-]+", (code or "").strip().lower()) if p)
        return hmac.compare_digest(str(row[0]).encode(), _sha(typed).encode())

    def new_pending(self, username: str, enrol_ok: bool = False) -> tuple[str, str]:
        """A sign-in whose password was right and whose code is still to come: (browser token, form token).
        ``enrol_ok``: it came through the holder's enrolment code (D-719), which the authenticator step then does
        not ask again."""
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM pending_logins WHERE username = ?", (username,))  # one at a time per account
            tx.execute(
                "INSERT INTO pending_logins (token_sha, username, csrf, created, enrol_ok) VALUES (?,?,?,?,?)",
                (_sha(token), username, csrf, self.clock().isoformat(), int(enrol_ok)),
            )
        return token, csrf

    def pending_enrol_ok(self, token: str | None) -> bool:
        """True when the half-done sign-in came through the holder's enrolment code (D-719)."""
        if not token or len(token) > 256:
            return False
        return bool(self.db.fetchval("SELECT enrol_ok FROM pending_logins WHERE token_sha = ?", (_sha(token),)))

    def pending(self, token: str | None) -> tuple[str, str, str | None] | None:
        """(user name, form token, sealed enrolment secret) of a fresh half-done sign-in, or None."""
        if not token or len(token) > 256:
            return None
        row = self.db.fetchone(
            "SELECT username, csrf, created, enroll_secret FROM pending_logins WHERE token_sha = ?", (_sha(token),)
        )
        if row is None:
            return None
        if self.clock() - datetime.fromisoformat(str(row[2])) > PENDING_TTL:
            self.drop_pending(token)
            return None
        return str(row[0]), str(row[1]), (str(row[3]) if row[3] else None)

    def set_pending_secret(self, token: str, sealed: str) -> None:
        self.db.execute("UPDATE pending_logins SET enroll_secret = ? WHERE token_sha = ?", (sealed, _sha(token)))

    def drop_pending(self, token: str) -> None:
        self.db.execute("DELETE FROM pending_logins WHERE token_sha = ?", (_sha(token),))

    # ------------------------------------------------------------------ both factors (D-719, NEW-SEC-3)
    def open_by_code(self, username: str, role: Role, mailbox: str | None, shown_to: str) -> str:
        """A protected account nobody knows a password of: the returned enrolment code (shown once to
        ``shown_to``) lets its holder choose the password and set up the authenticator (``redeem``)."""
        self.create(username, role, random_password(8), mailbox)
        code = random_password(4)
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE users SET holder_set = 0, opened_by = ?, enrol_code_sha = ?, enrol_expires = ?, "
                "enrol_reason = 'first' WHERE username = ?",
                (shown_to, _sha(code), (self.clock() + self.enrol_ttl).isoformat(), username),
            )
        self.note_factor_reset(username, "totp", shown_to)
        return code

    def opened_by(self, username: str) -> str:
        """Who was shown the account's first enrolment code ("" for an account made before D-719 or not by code)."""
        return str(self.db.fetchval("SELECT opened_by FROM users WHERE username = ?", (username,)) or "")

    def holder_set(self, username: str) -> bool:
        """False while a protected account's holder has not yet chosen a password with the enrolment code."""
        v = self.db.fetchval("SELECT holder_set FROM users WHERE username = ?", (username,))
        return v is None or bool(v)

    def note_factor_reset(self, username: str, factor: str, by: str) -> None:
        if factor not in FACTORS:
            raise AuthError(f"factor must be one of {', '.join(FACTORS)}")
        self.db.execute(
            "INSERT INTO factor_resets (username, factor, by_user, at) VALUES (?,?,?,?)",
            (username, factor, by, self.clock().isoformat()),
        )

    def factor_held(self, username: str, factor: str) -> tuple[str, datetime | None] | None:
        """Why someone else may not set ``factor`` of the account now, or None (D-719): (the factor already set by
        someone else, until when). The other factor was set by someone else within ``FACTOR_WINDOW`` and the
        holder has not signed in since; or (``"code"``, None): the holder has not yet chosen a password with the
        enrolment code, so nobody else sets one. An account with no such row (made before D-719) is never held."""
        if factor == "password" and not self.holder_set(username):
            return "code", None
        other = "totp" if factor == "password" else "password"
        since = (self.clock() - FACTOR_WINDOW).isoformat()
        at = self.db.fetchval(
            "SELECT max(at) FROM factor_resets WHERE username = ? AND factor = ? AND at > ?", (username, other, since)
        )
        if not at:
            return None
        last = self.db.fetchval("SELECT last_login FROM users WHERE username = ?", (username,))
        if last and str(last) > str(at):  # the holder signed in with the other factor after it was set
            return None
        return other, datetime.fromisoformat(str(at)) + FACTOR_WINDOW

    def enrol_used_at(self, username: str) -> str:
        return str(self.db.fetchval("SELECT enrol_used_at FROM users WHERE username = ?", (username,)) or "")

    def redeem(self, username: str, code: str, password: str, *, spend: bool) -> str:
        """The holder's first sign-in (D-719): ``"ok"`` when ``code`` is the account's live enrolment code and the
        holder has not chosen a password yet; the password becomes theirs. ``spend``: no authenticator step follows
        (TOTP off), so the code is used up here; with TOTP on it is used up when the holder's authenticator is set.
        ``"used"`` when the holder's password was already chosen with a code; ``"wrong"`` otherwise."""
        if self.get(username) is None:
            return "wrong"
        typed = "-".join(p for p in re.split(r"[\s-]+", (code or "").strip().lower()) if p)
        if self.holder_set(username):  # the review: "used" only to a person who types the spent code
            spent = self.db.fetchval("SELECT enrol_spent_sha FROM users WHERE username = ?", (username,))
            return "used" if spent and hmac.compare_digest(str(spent).encode(), _sha(typed).encode()) else "wrong"
        if not self.check_enrol_code(username, code):
            return "wrong"
        self.set_password(username, password, must_change=False)
        sql = (
            "UPDATE users SET holder_set = 1, enrol_used_at = ?, enrol_spent_sha = enrol_code_sha, "
            "enrol_code_sha = NULL, enrol_expires = NULL, enrol_reason = NULL WHERE username = ? AND holder_set = 0"
            if spend
            else "UPDATE users SET holder_set = 1, enrol_used_at = ?, enrol_spent_sha = enrol_code_sha "
            "WHERE username = ? AND holder_set = 0"
        )
        n = self.db.execute(sql, (self.clock().isoformat(), username))
        return "ok" if n == 1 else "used"

    def role_of(self, username: str) -> str:
        """The account's role whatever its state (disabled or past its end date too): the review of D-719 found a
        disabled account's reset skipping every rule because ``get`` answers None for it."""
        return str(self.db.fetchval("SELECT role FROM users WHERE username = ?", (username,)) or "")

    def confirming_accounts(self) -> list[tuple[User, bool]]:
        """(account, disabled) of every account that has chosen its own password and is not past its end date:
        a disabled one still counts as the box's second person (the review: disabling the steward must not void
        the rule), an expired one does not (its end date is not the administrator's to bring forward)."""
        rows = self.db.fetchall(f"SELECT {_COLS}, disabled FROM users WHERE holder_set = 1 ORDER BY username")
        out = []
        for r in rows:
            u = _row_user(r[:6])
            if not self._expired(u):
                out.append((u, bool(r[6])))
        return out

    def fail_request(self, rid: str, by: str) -> None:
        """A confirmed request that could not be applied (the account changed in between) is marked failed."""
        self.db.execute("UPDATE account_requests SET state = 'failed', decided_by = ?, decided_at = ? WHERE id = ?",
                        (by, self.clock().isoformat(), rid[:32]))  # fmt: skip

    def add_request(self, kind: str, username: str, payload: dict[str, str], by: str) -> str:
        rid = secrets.token_hex(8)
        self.db.execute(
            "INSERT INTO account_requests (id, kind, username, payload, requested_by, requested_at) "
            "VALUES (?,?,?,?,?,?)",
            (rid, kind, username, json.dumps(payload, sort_keys=True), by, self.clock().isoformat()),
        )
        return rid

    def requests(self) -> list[dict[str, object]]:
        """The requests waiting for a second person, oldest first."""
        rows = self.db.fetchall(
            "SELECT id, kind, username, payload, requested_by, requested_at FROM account_requests "
            "WHERE state = 'pending' ORDER BY requested_at, id"
        )
        return [self._request(r) for r in rows]

    def get_request(self, rid: str) -> dict[str, object] | None:
        row = self.db.fetchone(
            "SELECT id, kind, username, payload, requested_by, requested_at, state FROM account_requests WHERE id = ?",
            (rid[:32],),
        )
        if row is None:
            return None
        out = self._request(row[:6])
        out["state"] = str(row[6])
        return out

    @staticmethod
    def _request(row: tuple[object, ...]) -> dict[str, object]:
        rid, kind, username, payload, by, at = row
        return {"id": str(rid), "kind": str(kind), "user": str(username), "payload": json.loads(str(payload)),
                "by": str(by), "at": str(at), "state": "pending"}  # fmt: skip

    def decide_request(self, rid: str, state: str, by: str) -> bool:
        """Close a waiting request once (``confirmed`` or ``refused``); False when it was no longer waiting."""
        n = self.db.execute(
            "UPDATE account_requests SET state = ?, decided_by = ?, decided_at = ? WHERE id = ? AND state = 'pending'",
            (state, by, self.clock().isoformat(), rid[:32]),
        )
        return n == 1

    def set_opened_by(self, username: str, shown_to: str) -> None:
        self.db.execute("UPDATE users SET opened_by = ? WHERE username = ?", (shown_to, username))

    def add_notice(self, username: str, kind: str, by: str) -> None:
        """A line the holder reads at the next sign-in (D-719): ``password``, ``totp`` or ``opened``."""
        self.db.execute(
            "INSERT INTO account_notices (id, username, kind, by_user, at) VALUES (?,?,?,?,?)",
            (secrets.token_hex(8), username, kind, by, self.clock().isoformat()),
        )

    def take_notices(self, username: str) -> list[tuple[str, str, str]]:
        """(kind, by, at) of the holder's unread notices, oldest first; read once."""
        with self.db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT id, kind, by_user, at FROM account_notices WHERE username = ? AND seen = 0 ORDER BY at, id",
                (username,),
            )
            for r in rows:
                tx.execute("UPDATE account_notices SET seen = 1 WHERE id = ?", (r[0],))
        return [(str(k), str(b), str(a)) for _i, k, b, a in rows]

    def has_notices(self, username: str) -> bool:
        return bool(self.db.fetchval("SELECT count(*) FROM account_notices WHERE username = ? AND seen = 0",
                                     (username,)))  # fmt: skip

    # ------------------------------------------------------------------ OIDC round trips (D-192)
    def put_oidc_state(self, state: str, nonce: str, verifier: str) -> None:
        now = self.clock()
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM oidc_pending WHERE created < ?", ((now - OIDC_STATE_TTL).isoformat(),))
            tx.execute(
                "INSERT INTO oidc_pending (state_sha, nonce, verifier, created) VALUES (?,?,?,?)",
                (_sha(state), nonce, verifier, now.isoformat()),
            )

    def take_oidc_state(self, state: str) -> tuple[str, str] | None:
        """(nonce, PKCE verifier) of a round trip, once: the row is gone after this call. None when unknown or
        older than ten minutes."""
        if not state or len(state) > 256:
            return None
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "DELETE FROM oidc_pending WHERE state_sha = ? RETURNING nonce, verifier, created", (_sha(state),)
            )
        if row is None or self.clock() - datetime.fromisoformat(str(row[2])) > OIDC_STATE_TTL:
            return None
        return str(row[0]), str(row[1])

    def set_lang(self, session: Session, lang: str) -> None:
        self.db.execute("UPDATE sessions SET lang = ? WHERE token_sha = ?", (lang, session.token_sha))

    def end_session(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_sha = ?", (_sha(token),))

    # ------------------------------------------------------------------ first start
    def bootstrap_from_file(self, path: Path, username: str = "admin", mailbox: str | None = None) -> User | None:
        """Create the first administrator from a secret file when no administrator exists yet; None otherwise. The
        password sits in a file that others can read, so the administrator replaces it at first sign-in (D-279)."""
        if self.count("admin") > 0 or not path.is_file():
            return None
        password = path.read_text(encoding="utf-8").strip()
        return self.create(username, "admin", password, mailbox, must_change=True)


def csrf_ok(session: Session, submitted: str | None) -> bool:
    return bool(submitted) and hmac.compare_digest(session.csrf, submitted or "")


REVEAL_REASONS = ("contact", "eligibility", "consent", "other")


def reveal_reason(value: str) -> str:
    """FR-AUD-01b: the reason recorded with a chart-number reveal. The console forms always send one of
    ``REVEAL_REASONS``; anything else (an old page, a scripted call) is recorded as ``not given`` so the audit never
    invents one."""
    v = (value or "").strip().lower()
    return v if v in REVEAL_REASONS else "not given"
