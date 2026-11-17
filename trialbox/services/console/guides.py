"""T-317 (D-774): the role guides, built from the console's own help catalogue (WS-17.1, the training handout).

One source: what Help says on each page is what the guide says. For each role: what the role does
(``help.role.<role>``), what the matrix lets it do (``console.app.role_description``), the pages it opens (each with
``help.page.<slug>``, or ``help.page.<slug>.<role>`` where the page reads differently for the role:
``step4.help_key``), the glossary for a role that sees patients (``life.gloss.*``), the commands to try
(``cmd.ex.<role>.<n>``) and where to ask. :func:`markdown` is the printable guide that ``tools.role_guides`` writes to
``docs/guides/<role>.<lang>.md``; :func:`sections` is what ``/help/guide`` shows. Every word comes from the catalogue,
so a guide in ja or zh-TW has no English unless the catalogue has none (a test holds both)."""

from __future__ import annotations

from typing import Any

from tb_common.authz import conditional, permit

from console.i18n import lookup, translate
from console.step4 import help_key

#: the console's roles, in the order the guides are listed
ROLES = ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")
#: role -> (the column of the generated role-route table for the role at its narrowest, the column at its widest):
#: the investigator the delegation log does not name and the one it names; the SMO's study-scoped coordinator and the
#: hospital's own. A page the widest column opens and the narrowest does not is marked "where your account and the
#: study's delegation log allow". A test holds :data:`ROLE_PAGES` to that table through :data:`PAGES`.
PERSONAS = {"admin": ("admin", "admin"), "coordinator": ("smo", "crc"), "investigator": ("pi", "lpi"),
            "viewer": ("viewer", "viewer"), "cro": ("cra", "cra"), "steward": ("steward", "steward"),
            "privacy": ("privacy", "privacy")}  # fmt: skip
#: help page (``console.step4.HELP_PAGES`` slug) -> (the route the help text describes, the route of the action the
#: page is for, or None). A role's guide lists a page only when the role opens the first and, if any, may do the second:
#: a page that answers but refuses its every action (a viewer on "Start a request") is not the role's page.
PAGES: dict[str, tuple[str, str | None]] = {
    "home": ("GET /home", None),
    "week": ("GET /studies/{rs}/week", None),
    "patient": ("GET /studies/{rs}/patients/{pid}", None),
    "feasibility": ("GET /studies/{rs}/feasibility", None),
    "log": ("GET /studies/{rs}/screening-log", None),
    "cohort": ("GET /studies/{rs}/cohort", None),
    "setup": ("GET /studies/{rs}/setup", None),
    "candidates": ("GET /studies/{rs}/candidates", None),
    "referrals": ("GET /studies/{rs}/referrals", None),
    "edc": ("GET /studies/{rs}/edc", None),
    "subjects": ("GET /studies/{rs}/subjects", None),  # J-4 (D-1224, walk F-08)
    "state": ("GET /studies/{rs}/state", None),
    "reports": ("GET /reports", None),
    "admin": ("GET /admin", None),
    "users": ("GET /ops/users", "POST /ops/users"),
    "account_requests": ("GET /ops/accounts/requests", "POST /ops/accounts/requests"),
    "breakglass": ("GET /breakglass", None),
    "audit": ("GET /audit", None),
    "conflicts": ("GET /data/conflicts", None),
    "dataops": ("GET /data-ops", None),
    "optouts": ("GET /site/opt-outs", "POST /site/opt-outs"),
    "staff": ("GET /site/staff", None),
    "jobs": ("GET /jobs", None),
    "account": ("GET /account", None),
    "notices": ("GET /notices/received", None),
    "notice_settings": ("GET /settings/notices", "POST /settings/notices"),
    "registry": ("GET /pilot/registry/{ruleset}", None),
    "request": ("GET /pilot/request", "POST /pilot/request"),
    "protocol": ("GET /pilot/protocol", "POST /pilot/protocol"),
    "cmd": ("GET /cmd", None),
    "site": ("GET /site", None),
    "ask": ("GET /ask", None),
}
#: role -> its pages in :data:`PAGES` order, each (slug, True when only where the account and the log allow)
ROLE_PAGES: dict[str, tuple[tuple[str, bool], ...]] = {
    "admin": (
        ("home", False),
        ("feasibility", False),
        ("reports", False),
        ("admin", False),
        ("users", False),
        ("account_requests", False),
        ("breakglass", False),
        ("dataops", False),
        ("jobs", False),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("request", False),
        ("protocol", False),
        ("cmd", False),
        ("site", False),
        ("ask", False),
    ),
    "coordinator": (
        ("home", False),
        ("week", False),
        ("patient", False),
        ("feasibility", False),
        ("log", False),
        ("cohort", False),
        ("setup", False),
        ("candidates", False),
        ("referrals", False),
        ("edc", False),
        ("subjects", False),
        ("state", False),
        ("reports", False),
        ("staff", False),
        ("jobs", True),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("registry", False),
        ("request", False),
        ("protocol", False),
        ("cmd", False),
        ("site", False),
        ("ask", False),
    ),
    "investigator": (
        ("home", False),
        ("week", True),
        ("patient", True),
        ("feasibility", False),
        ("log", True),
        ("cohort", True),
        ("setup", False),
        ("candidates", True),
        ("referrals", True),
        ("edc", True),
        ("subjects", True),
        ("state", False),
        ("reports", False),
        ("breakglass", False),
        ("staff", False),
        ("jobs", False),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("registry", True),
        ("cmd", False),
        ("site", False),
        ("ask", False),
    ),
    "viewer": (
        ("home", False),
        ("feasibility", False),
        ("reports", False),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("cmd", False),
        ("ask", False),
    ),
    "cro": (
        ("home", False),
        ("feasibility", False),
        ("reports", False),
        ("account", False),
        ("cmd", False),
        ("ask", False),
    ),
    "steward": (
        ("home", False),
        ("feasibility", False),
        ("reports", False),
        ("account_requests", False),
        ("breakglass", False),
        ("audit", False),
        ("conflicts", False),
        ("dataops", False),
        ("optouts", False),
        ("staff", False),
        ("jobs", False),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("registry", False),
        ("cmd", False),
        ("ask", False),
    ),
    "privacy": (
        ("home", False),
        ("feasibility", False),
        ("reports", False),
        ("audit", False),
        ("optouts", False),
        ("staff", False),
        ("jobs", False),
        ("account", False),
        ("notices", False),
        ("notice_settings", False),
        ("registry", False),
        ("cmd", False),
        ("ask", False),
    ),
}
GLOSSARY = ("participant", "screen_fail", "window", "overdue", "ae", "sae", "deviation")
EXAMPLES = 6  # the help panel's ``cmd.ex.<role>.1`` to ``.6``


def _whole_catalogue() -> None:
    """``console.app`` and ``console.breakglass`` add their words (the roles' names and rights) to the catalogue when
    imported; the guide is built outside the running console too (``tools.role_guides``, the tests)."""
    from console import app, breakglass  # noqa: F401 - imported for their words


def title(role: str, lang: str) -> str:
    _whole_catalogue()
    return translate(lang, "guide.title", role=translate(lang, f"role.{role}"))


def sees_patients(role: str) -> bool:
    """A role that sees patient-level data (by role or as the study's delegation log allows): it gets the glossary."""
    return permit(role, "phi.view").allowed or conditional(role, "phi.view")


def examples(role: str, lang: str) -> list[str]:
    out = []
    for n in range(1, EXAMPLES + 1):
        key = f"cmd.ex.{role}.{n}"
        ex = lookup(lang, key)
        if ex is not None:
            out.append(ex.replace("GZQO", "STUDY"))
    return out


def keys(role: str) -> list[str]:
    """Every catalogue key the role's guide uses (a test holds each to every language's own catalogue)."""
    out = [f"role.{role}", "guide.title", "guide.intro", "guide.what", f"help.role.{role}", "guide.rights",
           "guide.pages", "guide.commands", "guide.commands.help", "guide.ask", "guide.ask.text"]  # fmt: skip
    out += ["guide.cond"] if any(c for _s, c in ROLE_PAGES[role]) else []
    out += [k for s, _c in ROLE_PAGES[role] for k in (f"guide.page.{s}", help_key(s, role))]
    out += ["guide.words", *[f"life.gloss.{w}" for w in GLOSSARY]] if sees_patients(role) else []
    out += [f"cmd.ex.{role}.{n}" for n in range(1, EXAMPLES + 1) if f"cmd.ex.{role}.{n}" in _en()]
    return out


def _en() -> dict[str, str]:
    from console.i18n import CATALOGUES

    _whole_catalogue()
    return CATALOGUES["en"]


def sections(role: str, lang: str) -> dict[str, Any]:
    """The guide's parts, in order, all in ``lang``."""
    from console.app import role_description  # the matrix's words for the role (ROLE-018); console.app's own catalogue

    _whole_catalogue()

    def t(key: str, **kw: Any) -> str:
        return translate(lang, key, **kw)

    return {
        "title": title(role, lang),
        "intro": t("guide.intro"),
        "what": (t("guide.what"), t(f"help.role.{role}")),
        "rights": (t("guide.rights"), role_description(role, lang)),
        "pages": (
            t("guide.pages"),
            [
                (t("guide.cond", page=t(f"guide.page.{s}")) if cond else t(f"guide.page.{s}"), t(help_key(s, role)))
                for s, cond in ROLE_PAGES[role]
            ],
        ),
        "words": (t("guide.words"), [t(f"life.gloss.{w}") for w in GLOSSARY]) if sees_patients(role) else None,
        "commands": (t("guide.commands"), t("guide.commands.help"), examples(role, lang)),
        "ask": (t("guide.ask"), t("guide.ask.text")),
    }


def markdown(role: str, lang: str) -> str:
    """The printable guide (``docs/guides/<role>.<lang>.md``)."""
    s = sections(role, lang)
    out = [f"# {s['title']}", "", s["intro"], "", f"## {s['what'][0]}", "", s["what"][1], "",
           f"## {s['rights'][0]}", "", s["rights"][1], "", f"## {s['pages'][0]}", ""]  # fmt: skip
    for name, text in s["pages"][1]:
        out += [f"### {name}", "", text, ""]
    if s["words"]:
        out += [f"## {s['words'][0]}", "", *[f"- {w}" for w in s["words"][1]], ""]
    head, hint, exs = s["commands"]
    out += [f"## {head}", "", hint, "", *[f"- `{x}`" for x in exs], ""] if exs else []
    out += [f"## {s['ask'][0]}", "", s["ask"][1], ""]
    return "\n".join(out)


__all__ = ["PAGES", "PERSONAS", "ROLES", "ROLE_PAGES", "markdown", "sections", "title"]
