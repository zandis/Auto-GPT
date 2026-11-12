"""The box's first-run wizard (T-729, D-466; plan v6.1 OD-12, OD-13): the pages a box serves before any account
exists, where its owner answers what an owner knows and becomes the first user.

``/login/first-run`` is part of the sign-in surface: no session exists yet, so no role can be checked and no
``permit`` row applies. It is safe on a network because it opens only when all of these hold, and answers 404
otherwise:

* the box was installed in box mode, so ``TB_FIRSTRUN_DIR`` names the first-run folder (``tb_common.firstrun``; the
  host's tmpfs ``/run/trialbox-firstrun``, ``deploy/docker-compose.box.yml``);
* the folder holds a live one-time code, which the installer showed on the box's own screen; five wrong codes void
  it, and the first account made closes it for good;
* the box has no account at all (``UserStore.count() == 0``), checked again when the answers are posted.

Steps: the code (``POST /login/first-run``) sets a short-lived browser token bound to a form token and to the
authenticator key the owner is about to add (kept in the folder, never in the database); the answers (``GET`` and
``POST /login/first-run/answers``) are checked by ``tb_common.box_answers`` plus the console's own password rule and
a code from the new authenticator; then the owner's accounts are made (``box_answers.owner_accounts``: steward and
administrator, OD-12; T-736 changes the duties there), the answers go to the folder for the installer's apply step
(``python -m tools.box apply``), the code is used up, and the page ends on the sign-in.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from tb_common import box_answers, chartno, firstrun
from tb_common.audit import AuditLog

from console import totp
from console.auth import AuthError, PasswordRejected, UserStore, check_password_policy
from console.i18n import CATALOGUES, LANGS
from console.i18n_firstrun import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

COOKIE = "tb_firstrun"
# the answers take a while to collect; long enough to read every question, short enough that a forgotten page dies
FORM_TTL = timedelta(minutes=30)
PATH = "/login/first-run"
TIMEZONES = tuple(sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/"))))


def box_holds_patients() -> bool | None:
    """NEW-DIN-3 (D-544, D-579): whether the pid map has a row. The chart-number rule may be chosen only while it
    has none: another rule gives every loaded patient a second pseudonym. None: the map cannot be asked, which the
    page treats as "it holds patients"."""
    import os

    from tb_common.db import Database

    try:
        with Database.connect(os.environ.get("TB_DB_URL"), "pidmap") as db:
            if db.fetchone("SELECT to_regclass('pid_map')") in (None, (None,)):
                return False  # the map's tables are not made yet: nothing was ever loaded
            row = db.fetchone("SELECT EXISTS (SELECT 1 FROM pid_map)")
            return bool(row and row[0])
    except Exception:
        return None


@dataclass
class FirstRunHooks:
    """What the console app lends this module (no import of console.app: it imports us)."""

    users: UserStore
    audit: AuditLog
    page: Callable[..., Response]
    seal: Callable[[str, str], str]  # the console's TOTP SecretBox: (username, secret) -> sealed
    secure: bool
    folder: Path | None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def register(app: FastAPI, h: FirstRunHooks) -> None:
    us, au = h.users, h.audit

    def is_open() -> bool:
        return firstrun.is_open(h.folder) and us.count() == 0

    def gate() -> Path:
        if not is_open() or h.folder is None:
            raise StarletteHTTPException(404)
        return h.folder

    def hardware(folder: Path) -> dict[str, Any]:
        return firstrun.read(folder / firstrun.HARDWARE)

    def lang(request: Request, chosen: str) -> None:
        if chosen in LANGS:
            request.state.lang = chosen

    def pending(request: Request, folder: Path) -> dict[str, Any] | None:
        state = firstrun.read(folder / firstrun.PENDING)
        token = request.cookies.get(COOKIE, "")
        if not state or not token or not hmac.compare_digest(str(state.get("token_sha", "")), _sha(token)):
            return None
        if datetime.now(UTC) - datetime.fromisoformat(str(state["created"])) > FORM_TTL:
            return None
        return state

    def form(request: Request, folder: Path, state: dict[str, Any], status: int = 200, **ctx: Any) -> Response:
        hw = hardware(folder)
        values = ctx.pop("values", {}) or {"tz": hw.get("host_tz", ""), "box_name": hw.get("hostname", "trialbox")}
        secret = str(state["secret"])
        user = str(values.get("owner_username") or "owner")
        return h.page(
            request, "firstrun.html", None, status, step="answers", fr_csrf=state["csrf"], values=values,
            ask_chartno=box_holds_patients() is False, chartno_kinds=chartno.KINDS,
            errors=ctx.pop("errors", {}), key=totp.grouped(secret), link=totp.otpauth_uri(secret, user),
            disks=hw.get("disks") or [], tpm=bool(hw.get("tpm")), timezones=TIMEZONES,
            sources=[k.value for k in box_answers.SourceKind], languages=box_answers.LANGUAGES,
            steward=user, admin=user + box_answers.ADMIN_SUFFIX, **ctx,
        )  # fmt: skip

    @app.get(PATH)
    def first_run(request: Request) -> Response:
        lang(request, request.query_params.get("lang", ""))
        gate()
        return h.page(request, "firstrun.html", None, step="code", wrong=False)

    @app.post(PATH)
    def first_run_code(request: Request, code: str = Form(""), lang_: str = Form("", alias="lang")) -> Response:
        lang(request, lang_)
        folder = gate()
        if not firstrun.check_code(folder, code[:64]):
            au.append("console.first_run", actor="console:-", detail={"step": "code", "result": "wrong"})
            if not firstrun.is_open(folder):
                raise StarletteHTTPException(404)  # the last allowed wrong code voided it
            return h.page(request, "firstrun.html", None, 403, step="code", wrong=True)
        token = secrets.token_urlsafe(32)
        firstrun.write_private(folder / firstrun.PENDING, {
            "token_sha": _sha(token), "csrf": secrets.token_urlsafe(24), "secret": totp.new_secret(),
            "created": datetime.now(UTC).isoformat(),
        })  # fmt: skip
        resp = RedirectResponse(f"{PATH}/answers" + (f"?lang={lang_}" if lang_ in LANGS else ""), status_code=303)
        resp.set_cookie(
            COOKIE, token, httponly=True, samesite="strict", secure=h.secure, max_age=int(FORM_TTL.total_seconds())
        )
        return resp

    @app.get(f"{PATH}/answers")
    def first_run_answers(request: Request) -> Response:
        lang(request, request.query_params.get("lang", ""))
        folder = gate()
        state = pending(request, folder)
        if state is None:
            return RedirectResponse(PATH, status_code=303)
        return form(request, folder, state)

    @app.post(f"{PATH}/answers")
    async def first_run_submit(request: Request) -> Response:
        data = {k: str(v)[:512] for k, v in (await request.form()).items() if isinstance(v, str)}
        lang(request, data.get("lang", ""))
        folder = gate()
        state = pending(request, folder)
        if state is None or not hmac.compare_digest(str(state["csrf"]), data.get("fr_csrf", "")):
            return RedirectResponse(PATH, status_code=303)
        hw = hardware(folder)
        disks = tuple(str(d.get("path", "")) for d in hw.get("disks") or ())
        answers, problems = box_answers.parse(data, disks=disks)
        errors = {p.field: p.code for p in problems}
        # NEW-DIN-3 (D-544): the rule is an answer only while the box holds no patient; the page does not ask then,
        # and an answer posted all the same makes nothing
        answered = any(
            data.get(k, "").strip() for k in ("chartno_rule", "chartno_kind", "chartno_width", "chartno_case")
        )
        if answered and "chartno_rule" not in errors and box_holds_patients() is not False:
            errors["chartno_rule"] = "chartno_locked"
        pw = data.get("password", "")
        try:
            check_password_policy(pw)
        except PasswordRejected as exc:
            errors["password"] = "password_breached" if exc.code == "account.err.breached" else "password_short"
        if "password" not in errors and pw != data.get("password2", ""):
            errors["password2"] = "password_same"
        step = totp.verify(str(state["secret"]), data.get("totp", ""), time.time(), None)
        if step is None:
            errors["totp"] = "totp"
        kek = ""
        if not hw.get("tpm"):
            kek = data.get("kek", "")
            if len(kek) < 12:
                errors["kek"] = "kek_short"
            elif kek != data.get("kek2", ""):
                errors["kek2"] = "kek_same"
        values = {k: v for k, v in data.items() if k not in ("password", "password2", "totp", "kek", "kek2", "fr_csrf")}
        if errors or answers is None or step is None:
            return form(request, folder, state, 422, values=values, errors=errors)
        if us.count() != 0:
            raise StarletteHTTPException(404)
        plans = box_answers.owner_accounts(answers)
        try:
            for acc in plans:
                us.create(acc.username, acc.role, pw, answers.owner.email)  # type: ignore[arg-type]
                us.set_totp(acc.username, h.seal(acc.username, str(state["secret"])), step)
        except AuthError:  # a second browser finished first, or a name the store refuses
            raise StarletteHTTPException(404) from None
        out = answers.to_json()
        if kek:
            out["kek_passphrase"] = kek  # tmpfs only; the apply step seals the keys with it and removes the file
        firstrun.write_private(folder / firstrun.ANSWERS, out)
        firstrun.close(folder)
        au.append("console.first_run", actor=f"console:{answers.owner.username}", detail={
            "step": "done", "accounts": [a.username for a in plans], "roles": [a.role for a in plans],
            "source": answers.source.value, "backup": answers.backup.kind.value,
            "chartno_rule": answers.chartno_rule,
        })  # fmt: skip
        resp = h.page(request, "firstrun.html", None, step="done", steward=plans[0].username)
        resp.delete_cookie(COOKIE)
        return resp
