"""D-719 (NEW-SEC-3, the owner 2026-11-14; the deep review's SEC-02): nobody holds both factors of a protected account.

A *protected* account is one of the classes ``patient-data`` (coordinator, investigator), ``steward``, ``privacy`` and
``admin``; ``aggregate`` (viewer, CRO) is not. The matrix has a row per class, ``account.create.<class>``, and
``account.confirm``.

(b), everywhere. A protected account is opened with an enrolment code only: no password is shown to anyone; its
holder signs in once with the code (``/enrol``), chooses the password and, with TOTP on, sets up the authenticator on
their own device. Afterwards someone else sets one factor at a time: a new password, or a new code for the
authenticator, never both within ``FACTOR_WINDOW`` (30 days) unless the holder signed in in between
(``UserStore.factor_held``). Accounts made before D-719 keep their factors; the 30 days count from the first reset
after the update.

(c), where the box has a second person: creating a protected account, changing its studies or resetting a factor is
a request (``account_requests``) that takes effect when another person with ``account.confirm`` (a steward or
another administrator) confirms it; nobody confirms their own, and a person whose account the requester opened (was
shown the code of), or who opened the requester's, is no second person. The code or password is shown to the person
who confirms, not to the one who asked. With no second person, (b) alone applies.

(a), always: the holder reads at the next sign-in who reset which factor when, or when the account was opened; the
steward and the PI of each of the account's studies are told by mail, as for break-glass (``console.breakglass``).
A code already used shows when it was used and is audited.

On a box where one person holds both the administrator's and the steward's account, misuse is seen, not
impossible: the record (D-719) says so.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from tb_common.authz import permit

from console.auth import AuthError, PasswordRejected, User, UserStore, check_password_policy, random_password

CLASS_OF: dict[str, str] = {
    "coordinator": "patient-data",
    "investigator": "patient-data",
    "steward": "steward",
    "privacy": "privacy",
    "admin": "admin",
    "viewer": "aggregate",
    "cro": "aggregate",
}


def account_class(role: str) -> str:
    """The class of an account of ``role``; a role not listed is held as patient-data (the strictest)."""
    return CLASS_OF.get(role, "patient-data")


def protected(role: str) -> bool:
    return account_class(role) != "aggregate"


@dataclass
class Rules:
    """The account rules over one user store; ``tell`` mails the steward and the account's PIs (subject, body)."""

    users: UserStore
    audit: Any
    tell: Callable[[str, str, str, str], None]  # (account, subject, body, by)

    def confirmers(self, requester: str) -> list[User]:
        """The people who may confirm ``requester``'s requests: ``account.confirm``, not the requester, and neither
        opened by the requester nor the requester's opener."""
        mine = self.users.opened_by(requester)
        return [
            u
            for u in self.users.users()
            if u.username != requester
            and permit(u.role, "account.confirm").allowed
            and self.users.opened_by(u.username) != requester
            and u.username != mine
        ]

    def second_person(self, requester: str) -> bool:
        return bool(self.confirmers(requester))

    def may_confirm(self, confirmer: str, requester: str) -> bool:
        return any(u.username == confirmer for u in self.confirmers(requester))

    def refuse_held(self, username: str, factor: str, by: str) -> tuple[str, str] | None:
        """(held factor, until) when ``factor`` may not be set by someone else now; the refusal is audited."""
        held = self.users.factor_held(username, factor)
        if held is None:
            return None
        until = held[1].isoformat()[:16] if held[1] is not None else ""
        self.audit.append("console.factor_refused", actor=f"console:{by}",
                          detail={"user": username, "factor": factor, "held": held[0], "until": until})  # fmt: skip
        return held[0], until

    def open_account(self, name: str, payload: dict[str, str], *, shown_to: str, requested_by: str,
                     confirmed_by: str) -> str:  # fmt: skip
        """Open a protected account by code; the code (for ``shown_to`` once) is returned, never audited."""
        code = self.users.open_by_code(name, payload["role"], payload.get("mailbox") or None, shown_to)  # type: ignore[arg-type]
        made = self.users.set_scope(name, payload.get("affiliation") or "hospital", payload.get("studies") or "",
                                    payload.get("expires") or None)  # fmt: skip
        self.audit.append(
            "console.user",
            actor=f"console:{requested_by}",
            detail={
                "action": "create",
                "user": name,
                "role": made.role,
                "class": account_class(made.role),
                "affiliation": made.affiliation,
                "studies": ",".join(made.studies),
                "expires": made.expires or "",
                "confirmed_by": confirmed_by,
            },
        )
        return code

    def reset_password(self, name: str, *, requested_by: str, confirmed_by: str) -> str:
        password = random_password()
        self.users.set_password(name, password, must_change=True)  # D-279: the holder replaces it at sign-in
        self.users.note_factor_reset(name, "password", requested_by)
        self.users.add_notice(name, "password", requested_by)
        self.audit.append("console.user", actor=f"console:{requested_by}",
                          detail={"action": "reset", "user": name, "confirmed_by": confirmed_by})  # fmt: skip
        self.tell_people(name, "password", requested_by, confirmed_by)
        return password

    @staticmethod
    def _who(name: str, confirmed_by: str) -> dict[str, str]:
        """The audit detail of a reset: the account, and who confirmed it when a second person did."""
        return {"user": name, **({"confirmed_by": confirmed_by} if confirmed_by else {})}

    def reset_totp(self, name: str, how: str, *, requested_by: str, confirmed_by: str) -> str:
        """``how``: ``reset_totp`` (clear the authenticator) or ``enrol_code`` (a code for an account without one)."""
        if how == "enrol_code":
            code = self.users.issue_enrol_code(name)
            self.audit.append(
                "console.enrol_code", actor=f"console:{requested_by}", detail=self._who(name, confirmed_by)
            )
        else:
            code = self.users.reset_totp(name)
            self.audit.append(
                "console.totp_reset", actor=f"console:{requested_by}", detail=self._who(name, confirmed_by)
            )
        self.users.note_factor_reset(name, "totp", requested_by)
        self.users.add_notice(name, "totp", requested_by)
        self.tell_people(name, "totp", requested_by, confirmed_by)
        return code

    def set_scope(self, name: str, payload: dict[str, str], *, requested_by: str, confirmed_by: str) -> User:
        made = self.users.set_scope(name, payload.get("affiliation") or "hospital", payload.get("studies") or "",
                                    payload.get("expires") or None)  # fmt: skip
        self.audit.append(
            "console.user",
            actor=f"console:{requested_by}",
            detail={
                "action": "scope",
                "user": name,
                "affiliation": made.affiliation,
                "studies": ",".join(made.studies),
                "expires": made.expires or "",
                "confirmed_by": confirmed_by,
            },
        )
        return made

    def request(self, kind: str, name: str, payload: dict[str, str], by: str, role: str) -> str:
        rid = self.users.add_request(kind, name, payload, by)
        detail = {"request": rid, "kind": kind, "user": name, "class": account_class(role)}
        self.audit.append("console.account_request", actor=f"console:{by}", detail=detail)
        return rid

    def tell_people(self, name: str, what: str, by: str, confirmed_by: str) -> None:
        line = {"password": "a new password", "totp": "a new authenticator code", "opened": "opened"}[what]
        who = f"{by}, confirmed by {confirmed_by}" if confirmed_by else by
        body = (
            f"TrialBox account {name}: {line}, by {who}.\n\nIf this was not asked for, tell the administrator and "
            "the data steward at once; the account's sign-ins are on the console's audit page (/audit)."
        )
        self.tell(name, f"TrialBox account {name}: {line}", body, by)


@dataclass
class Hooks:
    """What the console app lends this module (no import of console.app: it imports us)."""

    need: Callable[[Request], Any]
    page: Callable[..., Response]
    problem: Callable[..., Exception]
    csrf_ok: Callable[[Any, str | None], bool]
    ident: Any  # console.identity.Identity
    login_cookie: str
    session_cookie: str
    secure: bool
    lang_of: Callable[[Request, Any], str]
    client_source: Callable[[Request], str]


def register(app: FastAPI, rules: Rules, h: Hooks) -> None:
    us, au = rules.users, rules.audit

    # ------------------------------------------------------------------ the holder's first sign-in
    def _enrol_page(request: Request, status: int = 200, **ctx: Any) -> Response:
        token = secrets.token_urlsafe(24)
        stewards = ", ".join(u.username for u in us.users() if u.role == "steward")
        resp = h.page(request, "enrol.html", None, status, login_csrf=token, stewards=stewards, **ctx)
        resp.set_cookie(h.login_cookie, token, httponly=True, samesite="strict", secure=h.secure, max_age=900)
        return resp

    @app.get("/enrol")
    def enrol_form(request: Request) -> Response:
        return _enrol_page(request)

    @app.post("/enrol")
    def enrol_submit(
        request: Request,
        username: str = Form(""),
        enrol_code: str = Form(""),
        password: str = Form(""),
        password2: str = Form(""),
        login_csrf: str = Form(""),
    ) -> Response:
        cookie = request.cookies.get(h.login_cookie, "")
        if not cookie or not secrets.compare_digest(cookie, login_csrf):
            raise h.problem(400, "csrf")
        name = username.strip().lower()[:32]
        src = h.client_source(request)
        wait = us.throttled(src)
        if wait:
            au.append("console.login_failed", actor=f"console:{name or '-'}",
                      detail={"factor": "enrol_code", "reason": "slowed", "source": src})  # fmt: skip
            return _enrol_page(request, 429, failed="slowed")
        if us.locked(name, src):
            return _enrol_page(request, 401, failed="locked")
        if password != password2:
            return _enrol_page(request, 400, failed="mismatch", username=name)
        try:
            check_password_policy(password[:256])
        except PasswordRejected as exc:
            return _enrol_page(request, 400, failed="policy", reason=exc.code, username=name)
        except AuthError:
            return _enrol_page(request, 400, failed="policy", reason="account.err.policy", username=name)
        totp_on = bool(h.ident.settings.totp_required)
        outcome = us.redeem(name, enrol_code[:64], password[:256], spend=not totp_on)
        if outcome != "ok":
            us.record_failure(name, src)
            if outcome == "used":
                used = us.enrol_used_at(name)
                au.append("console.enrol_code_reused", actor=f"console:{name}", detail={"used_at": used, "source": src})
                h.ident.after_failure(name, src)
                return _enrol_page(request, 401, failed="used", used_at=used[:16].replace("T", " "))
            au.append("console.login_failed", actor=f"console:{name or '-'}",
                      detail={"factor": "enrol_code", "reason": "enrol_code", "source": src})  # fmt: skip
            h.ident.after_failure(name, src)
            return _enrol_page(request, 401, failed="wrong", username=name)
        opener = us.opened_by(name)
        au.append("console.account_opened", actor=f"console:{name}", detail={"opened_by": opener})
        us.add_notice(name, "opened", opener or "-")
        rules.tell_people(name, "opened", opener or "-", "")
        user = us.get(name)
        assert user is not None
        if totp_on:  # the holder's own device next; the code is not asked again
            resp = h.ident.second_step(user, enrol_ok=True)
            resp.delete_cookie(h.login_cookie)
            return resp
        us.clear_failures(name, src)
        session_token, _ = us.new_session(user, h.lang_of(request, None), "enrol")
        au.append("console.login", actor=f"console:{name}", detail={"role": user.role, "via": "enrol"})
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(h.session_cookie, session_token, httponly=True, samesite="strict", secure=h.secure)
        resp.delete_cookie(h.login_cookie)
        return resp

    # ------------------------------------------------------------------ the second person
    def _confirmer(request: Request, csrf: str | None = None) -> Any:
        sess = h.need(request)
        if csrf is not None and not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not permit(sess.user.role, "account.confirm").allowed:
            au.append("console.denied", actor=f"console:{sess.user.username}",
                      detail={"action": "/ops/accounts/requests"})  # fmt: skip
            raise h.problem(403, "forbidden")
        return sess

    def _list(request: Request, sess: Any, status: int = 200, **ctx: Any) -> Response:
        me = sess.user.username
        rows = [{**r, "mine": r["by"] == me, "may": rules.may_confirm(me, str(r["by"]))} for r in us.requests()]
        return h.page(request, "account_requests.html", sess, status, rows=rows, **ctx)

    @app.get("/ops/accounts/requests")
    def requests_view(request: Request) -> Response:
        return _list(request, _confirmer(request))

    @app.post("/ops/accounts/requests")
    def requests_decide(
        request: Request, csrf: str = Form(""), request_id: str = Form("", alias="request"), decision: str = Form("")
    ) -> Response:
        sess = _confirmer(request, csrf)
        me = sess.user.username
        req = us.get_request(request_id)
        if req is None or req["state"] != "pending":
            raise h.problem(409, "request.refused", reason="this request is no longer waiting")
        by, kind, name = str(req["by"]), str(req["kind"]), str(req["user"])
        payload: dict[str, str] = dict(req["payload"])  # type: ignore[call-overload]
        if not rules.may_confirm(me, by):  # one's own, or the requester's opener or opened account
            why = {"action": "/ops/accounts/requests", "request": req["id"], "reason": "not_second"}
            au.append("console.denied", actor=f"console:{me}", detail=why)
            raise h.problem(403, "forbidden")
        detail = {"request": req["id"], "kind": kind, "user": name, "requested_by": by}
        if decision == "refuse":
            if not us.decide_request(str(req["id"]), "refused", me):
                raise h.problem(409, "request.refused", reason="this request is no longer waiting")
            au.append("console.account_refused", actor=f"console:{me}", detail=detail)
            return _list(request, sess, done="refused")
        if decision != "confirm":
            raise h.problem(400, "request.refused", reason="unknown decision")
        if kind in ("password", "totp"):
            factor = kind
            if rules.refuse_held(name, factor, me) is not None:
                raise h.problem(409, "request.refused", reason="the other factor was set within 30 days")
        if kind == "create" and us.get(name) is not None:
            raise h.problem(409, "request.refused", reason="an account with this name exists")
        if not us.decide_request(str(req["id"]), "confirmed", me):
            raise h.problem(409, "request.refused", reason="this request is no longer waiting")
        secret = ""
        try:
            if kind == "create":
                secret = rules.open_account(name, payload, shown_to=me, requested_by=by, confirmed_by=me)
            elif kind == "password":
                secret = rules.reset_password(name, requested_by=by, confirmed_by=me)
            elif kind == "totp":
                secret = rules.reset_totp(name, payload.get("how", "reset_totp"), requested_by=by, confirmed_by=me)
            elif kind == "scope":
                rules.set_scope(name, payload, requested_by=by, confirmed_by=me)
        except AuthError as exc:
            raise h.problem(409, "request.refused", reason=str(exc)) from exc
        au.append("console.account_confirmed", actor=f"console:{me}", detail=detail)
        # shown once, on this answer only, to the person who confirmed (never in a URL, a log or the audit)
        return _list(request, sess, done="confirmed", secret=secret, secret_kind=kind, secret_user=name)


# D-719 strings: joined into the console catalogues once, when this module is imported
from console.i18n import EN, JA, ZH  # noqa: E402
from console.i18n_accounts import EN as _AC_EN  # noqa: E402
from console.i18n_accounts import JA as _AC_JA  # noqa: E402
from console.i18n_accounts import ZH as _AC_ZH  # noqa: E402

EN.update(_AC_EN)
JA.update(_AC_JA)
ZH.update(_AC_ZH)
