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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from tb_common import box_answers, chartno, dates, firstrun, site_country
from tb_common import preflight as tb_preflight
from tb_common.audit import AuditLog
from tb_common.retention import OVERRIDABLE

from console import totp
from console.auth import AuthError, PasswordRejected, UserStore, check_password_policy
from console.i18n import CATALOGUES, LANGS
from console.i18n_firstrun import EN, JA, ZH
from console.i18n_preflight import EN as _PF_EN
from console.i18n_preflight import JA as _PF_JA
from console.i18n_preflight import ZH as _PF_ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)
for _lang, _cat in (("en", _PF_EN), ("ja", _PF_JA), ("zh-TW", _PF_ZH)):  # 10K-3: the words around the preflight
    CATALOGUES[_lang].update(_cat)

COOKIE = "tb_firstrun"
# the answers take a while to collect; long enough to read every question, short enough that a forgotten page dies
FORM_TTL = timedelta(minutes=30)
PATH = "/login/first-run"
COUNTRY_FLAG = "TB_FIRSTRUN_COUNTRY"  # 10K-1: the country asked first; off by default (what an installer sees first)


def country_on(env: Mapping[str, str]) -> bool:
    """10K-1: the page asks the site's country first (``TB_FIRSTRUN_COUNTRY``); off unless set."""
    return (env.get(COUNTRY_FLAG) or "").strip().lower() in ("1", "true", "on", "yes")


# 10K-1 (review of #1088): the answers a re-shown form carries back, by name: the form's own non-secret fields only
# (an allowlist; a password, a code, a passphrase or a field the form does not have is never sent back). 10K-21: the
# two named people (operational contact names, not secrets); 10K-4: the three host folders
SS_FIELDS = ("ssmix2_root", "ssmix2_order_numbers")
FORM_FIELDS = ("site_name", "tz", "language", "owner_full_name", "owner_username", "owner_email", "box_name",
               "backup_kind", "backup_disk", "backup_share", "source", "chartno_kind", "chartno_width", *SS_FIELDS,
               *OVERRIDABLE, "printed_dates", "year_basis",
               "health_page_person", "tls_root_confirmed_by",
               "backup_dir", "anchor_dir", "log_dir")  # fmt: skip


def offered_sources(country: str, asks_country: bool) -> list[str]:
    """10K-1 (review item 2): the source kinds the page offers. SS-MIX2 only with the country asked and only where
    the country's shipped mapping reads it; without the flag the list is master's."""
    kinds = [k.value for k in box_answers.SourceKind]
    if asks_country and site_country.reads_ssmix2(country):
        return kinds
    return [k for k in kinds if k != box_answers.SourceKind.SSMIX2.value]


def country_values(country: str, hw: dict[str, Any]) -> dict[str, str]:
    """10K-1: the form's first values for a chosen country, from ``tb_common.site_country.TABLE`` only: its zone (else
    the box's own clock zone, as without a country), its report language, and SS-MIX2 as the source where the
    country's shipped mapping reads it. A country the table does not know gives no values."""
    try:
        cd = site_country.defaults(country)
    except ValueError:
        return {}
    out = {"country": cd.country, "tz": cd.tz or str(hw.get("host_tz", ""))}
    out |= {"printed_dates": cd.printed_dates, "year_basis": cd.year_basis}  # 10C-13, 10C-15: shown chosen
    if cd.locale:
        out["language"] = cd.locale
    if cd.data_source_type == "ssmix2":
        out["source"] = box_answers.SourceKind.SSMIX2.value
    return out


def preflight_lines(folder: Path) -> tuple[dict[str, list[dict[str, str]]], str]:
    """10K-3 (D-1361): the live preflight the box installer wrote into the first-run folder
    (``tb_common.preflight.FILE``), as the page shows it in each language, and when it ran. Nothing is checked here:
    the console cannot see the host's clock, disks, TPM or shares. No file: no lines (the page says so)."""
    doc = firstrun.read(folder / tb_preflight.FILE)
    return {lg: tb_preflight.page_lines(doc, lg) for lg in LANGS}, str(doc.get("at", ""))[:25]


TIMEZONES = tuple(sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/"))))


def box_holds_patients() -> bool | None:
    """NEW-DIN-3 (D-544, D-579): whether the pid map has a row, loaded or staged for a night that is not committed
    yet. The chart-number rule may be chosen only while it has none: another rule gives every patient a second
    pseudonym. None: the map cannot be asked; the rule is then not offered, and the page says that the map could
    not be read (D-710), never that the box holds patients.

    Asking creates nothing: whether the map's schema exists is read from the catalogue over the console's own
    connection (anyone may read that), and the map is opened only when it does.

    NEW-FR-1 (D-710): the map is asked over its own connection. On a box with service roles a store's connection
    takes that store's role, and the role of ``auth`` may not use the ``pidmap`` schema: asked over the ``auth``
    connection the question raised on every such box and the answer was always None."""
    import os

    from tb_common.db import Database

    url = os.environ.get("TB_DB_URL")
    try:
        with Database.connect(url, "auth") as db:  # the console's own schema
            schema = db.schema[: -len("auth")] + "pidmap"
            if not db.fetchval("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = ?)", (schema,)):
                return False  # no schema: nothing was ever loaded into it
        with Database.connect(url, "pidmap") as pm:  # it exists (read above), so nothing is created
            for table in ("pid_map", "pending"):
                if pm.fetchval("SELECT to_regclass(?)", (f'"{schema}".{table}',)) is None:
                    continue  # not made yet
                if pm.fetchval(f'SELECT EXISTS (SELECT 1 FROM "{schema}".{table})'):  # nosec B608 - our own name
                    return True
            return False
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
    country: bool = False  # 10K-1: the country asked first (country_on); off by default
    production: bool = False  # 10K-21 (D-1365): a PRODUCTION box (TB_ENV): what may not stay silent is required


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
        asks_country = h.country
        errors = ctx.pop("errors", {})
        country = str(values.get("country") or "") if asks_country else ""
        try:
            cd = site_country.defaults(country)
        except ValueError:  # a country no list offers (a tampered form): the first question again, said so
            cd, country = site_country.LEGACY, ""
            errors = {**errors, "country": "country"}
        carried = {k: v for k, v in values.items() if k in FORM_FIELDS}
        sources = offered_sources(country, asks_country)
        ask_retention = bool(country) and cd.retention_rules is None
        shown = {*(SS_FIELDS if "ssmix2" in sources else ()), *(OVERRIDABLE if ask_retention else ())}
        # what this page does not ask but an earlier choice of country did: kept, so a change back finds it
        kept = (
            {k: v for k, v in carried.items() if k in (*SS_FIELDS, *OVERRIDABLE) and k not in shown} if country else {}
        )
        secret = str(state["secret"])
        user = str(values.get("owner_username") or "owner")
        held = box_holds_patients()
        pf, pf_at = preflight_lines(folder)
        return h.page(
            request, "firstrun.html", None, status, step="answers", fr_csrf=state["csrf"], values=values,
            ask_chartno=held is False, chartno_unread=held is None, chartno_kinds=chartno.KINDS,
            errors=errors, key=totp.grouped(secret), link=totp.otpauth_uri(secret, user),
            disks=hw.get("disks") or [], tpm=bool(hw.get("tpm")), timezones=TIMEZONES,
            sources=sources, languages=box_answers.LANGUAGES, carried=carried, kept=kept,
            mapped_later=bool(country) and not cd.mapping,
            steward=user, admin=user + box_answers.ADMIN_SUFFIX, ask_country=asks_country, country=country,
            countries=site_country.COUNTRIES, ss_orders=site_country.SSMIX2_ORDER_NUMBERS,
            ask_retention=ask_retention, retention_keys=OVERRIDABLE, printed_styles=dates.PRINTED_STYLES,
            country_dates=(cd.printed_dates, cd.year_basis),
            year_bases=dates.YEAR_BASES, preflight=pf, preflight_at=pf_at, production=h.production, **ctx,
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

    async def first_run_keep(request: Request) -> Response:
        """10K-1 (behind the flag): the country step's buttons, "change the country" and the language buttons post
        the form here; the page comes back with what was typed (the form's own non-secret fields only) and, for a
        chosen country, its defaults (``tb_common.site_country.TABLE``) over the country's own fields. Nothing is
        made here. Registered only with the flag on: without it the route table is master's."""
        data = {k: str(v)[:512] for k, v in (await request.form()).items() if isinstance(v, str)}
        lang(request, data.get("switch_lang") or data.get("lang", ""))
        folder = gate()
        state = pending(request, folder)
        if state is None or not hmac.compare_digest(str(state["csrf"]), data.get("fr_csrf", "")):
            return RedirectResponse(PATH, status_code=303)
        hw = hardware(folder)
        values = {k: v for k, v in data.items() if k in (*FORM_FIELDS, "country")}
        values.setdefault("box_name", str(hw.get("hostname", "trialbox")))
        if "pick_country" in data:
            values.pop("country", None)
            picked = data["pick_country"].strip()
            if picked:
                values["country"] = picked
                values |= country_values(picked, hw)
                if values.get("source") not in offered_sources(picked, True):
                    values.pop("source", None)
        return form(request, folder, state, values=values)

    if h.country:
        app.post(f"{PATH}/answers/keep")(first_run_keep)

    @app.post(f"{PATH}/answers")
    async def first_run_submit(request: Request) -> Response:
        data = {k: str(v)[:512] for k, v in (await request.form()).items() if isinstance(v, str)}
        lang(request, data.get("lang", ""))
        if not h.country:  # 10K-1: asked only behind the flag; a posted answer makes nothing then
            for k in ("country", *OVERRIDABLE, "printed_dates", "year_basis"):  # 10C-13/15: asked with the country
                data.pop(k, None)
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
        if answered and "chartno_rule" not in errors:
            held = box_holds_patients()
            if held is not False:  # D-710: "could not be read" is said as that, not as "holds patients"
                errors["chartno_rule"] = "chartno_locked" if held else "chartno_unread"
        if answers is not None and h.production:  # 10K-21 (D-1365): what a PRODUCTION box may not leave silent
            held = None if answers.chartno_rule else box_holds_patients()
            if not answers.chartno_rule and held is None:  # review of #1175, S2: unread is not "not asked"
                errors.setdefault("chartno_rule", "chartno_unread_production")
            asked = bool(answers.chartno_rule) or held is False  # held: not asked, the box's rule stays
            for gap in box_answers.production_gaps(answers, chartno_asked=asked):
                errors.setdefault(gap.field, gap.code)
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
            # 10C-13, 10C-15 (D-1229): asked with the country; recorded only when answered (the flag off: as before)
            **{k: v for k, v in (("printed_dates", answers.printed_dates), ("year_basis", answers.year_basis)) if v},
        })  # fmt: skip
        resp = h.page(request, "firstrun.html", None, step="done", steward=plans[0].username)
        resp.delete_cookie(COOKIE, httponly=True, samesite="strict", secure=h.secure)  # the flags it was set with
        return resp
