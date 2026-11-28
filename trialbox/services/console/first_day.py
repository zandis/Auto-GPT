"""Lane H, PoC item 2: "Your first day" in Help.

One page per role that starts a site (investigator, coordinator, data steward, administrator) at ``/help/first-day``,
and seven one-page procedures at ``/help/first-day?procedure=<name>``, in en, ja and zh-TW. The page shows the signed-in
role's own and links only the procedures that role uses; a role with no first-day page, or a procedure the role does
not use, is a 404 (as ``/help/guide`` gives an account only its own role's guide).

Every button or page a step names is a ``{name}`` filled from the console's own catalogue (:data:`LABELS`), so the
step says what the screen says, in the reader's language, and no label is typed twice. The words are in
``console.i18n_first_day``. Nothing here changes any data."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from tb_common import site_needs

from console.i18n import lookup

#: the procedures, in the order they are met
PROCEDURES = ("install-check", "first-night", "approve-study", "review-list", "contact-consent", "backup-restore",
              "when-held")  # fmt: skip
#: role -> the procedures it uses (the console's roles: investigator is the PI, coordinator the CRC, admin is IT)
ROLE_PROCEDURES: dict[str, tuple[str, ...]] = {
    "investigator": ("install-check", "approve-study", "review-list", "contact-consent", "when-held"),
    "coordinator": ("install-check", "approve-study", "review-list", "contact-consent", "when-held"),
    "steward": ("install-check", "first-night", "when-held"),
    "admin": ("install-check", "first-night", "backup-restore", "when-held"),
}
PROCEDURE_ROLES: dict[str, tuple[str, ...]] = {
    p: tuple(r for r, procs in ROLE_PROCEDURES.items() if p in procs) for p in PROCEDURES
}
#: a label the three languages write the same
SAME_IN_ALL: frozenset[str] = frozenset()
#: placeholder -> the catalogue key of the button, page or tab as the console shows it
LABELS: dict[str, str] = {
    "install": "guide.install", "home": "guide.page.home", "help": "help.title", "help_guide": "help.guide.link",
    "week": "nav.week", "approach": "mark.approach", "need_info": "mark.need_info",
    "not_suitable": "mark.not_suitable", "not_now": "mark.not_now", "ask_doctor": "mark.ask_doctor",
    "undo": "mark.undo", "open_approval": "s20.open", "open_row": "s20.open_row", "read_row": "s20.read_row",
    "approve_all": "s20.approve_all", "tick": "s20.tick", "save_labels": "s20.label.save",
    "state_link": "sstate.link", "move_to": "sstate.move", "open_state": "sstate.open",
    "change_state": "sstate.save", "still_needed": "stillneeded.title", "ops": "ops.title",
    "backups_tab": "ops.tab.backups", "backup_now": "ops.action.backup", "backup_check": "ops.action.backup_check",
    "flags": "flags.title", "restore_hold": "nav.restore_hold", "data_ops": "dataops.title",
    "held_nights": "dataops.held.title", "accept": "dataops.accept", "reject": "dataops.reject",
    "decide": "dataops.submit", "reason": "dataops.reason", "data_step": "datastep.title",
    "record_call": "outcome.quick", "booked": "outcome.reached_booked", "declined": "outcome.reached_declined",
    "not_reached": "outcome.not_reached", "not_approached": "outcome.not_approached", "lost": "outcome.lost_contact",
    "record_consent": "consent.record.do", "referrals": "guide.page.referrals",
    "proc_held": "fd.proc.when-held.title", "proc_backup": "fd.proc.backup-restore.title",
    "proc_contact": "fd.proc.contact-consent.title",
}  # fmt: skip
ALL = frozenset(ROLE_PROCEDURES)
IT_AND_STEWARD = frozenset({"admin", "steward"})
ADMIN = frozenset({"admin"})
#: procedure -> (route, label name, the roles that open the route): a role is shown only links it can open
LINKS: dict[str, tuple[tuple[str, str, frozenset[str]], ...]] = {
    "install-check": (("/home", "home", ALL), ("/help/guide", "help_guide", ALL),
                      ("/admin/still-needed", "still_needed", ADMIN)),
    "first-night": (("/admin/data-step", "data_step", ADMIN), ("/data-ops", "data_ops", IT_AND_STEWARD),
                    ("/admin/still-needed", "still_needed", ADMIN)),
    "approve-study": (("/home", "home", ALL),),
    "review-list": (("/week", "week", ALL),),
    "contact-consent": (("/week", "week", ALL),),
    "backup-restore": (("/admin/ops", "ops", ADMIN), ("/ops/flags", "flags", IT_AND_STEWARD),
                       ("/admin/still-needed", "still_needed", ADMIN)),
    "when-held": (("/data-ops", "data_ops", IT_AND_STEWARD), ("/ops/flags", "flags", IT_AND_STEWARD),
                  ("/week", "week", frozenset({"coordinator", "investigator"}))),
}  # fmt: skip


def _text(lang: str, key: str) -> str:
    return lookup(lang, key) or key


def _labels(lang: str) -> dict[str, str]:
    out = {name: _text(lang, key) for name, key in LABELS.items()}
    need = next(n for n in site_needs.NEEDS if n.key == "backup_key")
    out["backup_key"] = need.title.get(lang) or need.title["en"]
    return out


def title(lang: str) -> str:
    return _text(lang, "fd.title")


def today(role: str, lang: str) -> str:
    return _text(lang, f"fd.today.{role}")


def rules(lang: str) -> list[str]:
    return [_text(lang, f"fd.rule.{n}") for n in range(1, 5)]


def procedure_of(slug: str, role: str, lang: str) -> dict[str, Any]:
    """One procedure in ``lang``: title, when to use it, the steps, the note and the links this role may open."""
    labels = _labels(lang)
    steps, n = [], 1
    while (raw := lookup(lang, f"fd.proc.{slug}.step.{n}")) is not None:
        steps.append(raw.format(**labels))
        n += 1
    return {
        "title": _text(lang, f"fd.proc.{slug}.title"),
        "use": _text(lang, f"fd.proc.{slug}.use").format(**labels),
        "steps": steps,
        "note": _text(lang, f"fd.proc.{slug}.note").format(**labels),
        "links": [(href, labels[name]) for href, name, roles in LINKS[slug] if role in roles],
    }


def register(app: FastAPI, h: Any) -> None:
    @app.get("/help/first-day")
    def first_day_page(request: Request, procedure: str = "") -> Response:
        """The role's first-day page; with ``?procedure=<name>`` one of the role's procedures."""
        sess = h.need(request)
        role = sess.user.role
        if role not in ROLE_PROCEDURES:
            return RedirectResponse("/help/guide", status_code=303)  # no first-day page: the role's own guide
        if procedure:
            if procedure not in ROLE_PROCEDURES[role]:
                raise h.problem(404, "notfound")

            def proc(lang: str) -> dict[str, Any]:
                return procedure_of(procedure, role, lang)

            shown: Response = h.page(request, "first_day_procedure.html", sess, role=role, slug=procedure, proc=proc)
            return shown

        def page(lang: str) -> dict[str, Any]:
            return {"title": title(lang), "today": today(role, lang), "rules": rules(lang),
                    "procs": {s: procedure_of(s, role, lang) for s in ROLE_PROCEDURES[role]}}  # fmt: skip

        response: Response = h.page(request, "first_day.html", sess, role=role, page=page)
        return response
