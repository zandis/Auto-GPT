"""T-317 (D-774): the role guides, built from the console's own help catalogue (WS-17.1, the training handout).

One source: what Help says on each page is what the guide says. For each role: what the role does
(``help.role.<role>``), what the matrix lets it do (``console.app.role_description``), the pages it opens (each with
``help.page.<slug>``), the glossary for a role that sees patients (``life.gloss.*``), the commands to try
(``cmd.ex.<role>.<n>``) and where to ask. :func:`markdown` is the printable guide that ``tools.role_guides`` writes to
``docs/guides/<role>.<lang>.md``; :func:`sections` is what ``/help/guide`` shows. Every word comes from the catalogue,
so a guide in ja or zh-TW has no English unless the catalogue has none (a test holds both)."""

from __future__ import annotations

from typing import Any

from tb_common.authz import conditional, permit

from console.i18n import translate

#: the console's roles, in the order the guides are listed
ROLES = ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")
#: role -> the column of the generated role-route table that is that role at work (the investigator the study's
#: delegation log names; the hospital's coordinator); a test holds :data:`ROLE_PAGES` to that table
PERSONA = {"admin": "admin", "coordinator": "crc", "investigator": "lpi", "viewer": "viewer", "cro": "cra",
           "steward": "steward", "privacy": "privacy"}  # fmt: skip
#: role -> the help pages (``console.step4.HELP_PAGES`` slugs) the role opens, in Help's order
ROLE_PAGES: dict[str, tuple[str, ...]] = {
    "admin": ("home", "week", "feasibility", "reports", "admin", "jobs", "account", "notices", "notice_settings",
              "registry", "request", "protocol", "cmd", "site", "ask"),
    "coordinator": ("home", "week", "patient", "feasibility", "log", "cohort", "setup", "candidates", "referrals",
                    "edc", "reports", "jobs", "account", "notices", "notice_settings", "registry", "request",
                    "protocol", "cmd", "site", "ask"),
    "investigator": ("home", "week", "patient", "feasibility", "log", "cohort", "setup", "candidates", "referrals",
                     "edc", "reports", "jobs", "account", "notices", "notice_settings", "registry", "request",
                     "protocol", "cmd", "site", "ask"),
    "viewer": ("home", "feasibility", "reports", "account", "notices", "notice_settings", "request", "protocol",
               "cmd", "ask"),
    "cro": ("home", "feasibility", "reports", "account", "cmd", "ask"),
    "steward": ("home", "week", "feasibility", "reports", "jobs", "account", "notices", "notice_settings",
                "registry", "request", "protocol", "cmd", "site", "ask"),
    "privacy": ("home", "week", "feasibility", "reports", "jobs", "account", "notices", "notice_settings",
                "registry", "request", "protocol", "cmd", "site", "ask"),
}  # fmt: skip
GLOSSARY = ("participant", "screen_fail", "window", "overdue", "ae", "sae", "deviation")
EXAMPLES = 6  # the help panel's ``cmd.ex.<role>.1`` to ``.6``


def _whole_catalogue() -> None:
    """``console.app`` and ``console.breakglass`` add their words (the roles' names and rights) to the catalogue when
    imported; the guide is built outside the running console too (``tools.role_guides``, the tests)."""
    from console import app, breakglass  # noqa: F401 - imported for their words; console.app imports this module


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
        ex = translate(lang, key)
        if ex != key:
            out.append(ex.replace("GZQO", "STUDY"))
    return out


def sections(role: str, lang: str) -> dict[str, Any]:
    """The guide's parts, in order, all in ``lang``."""
    from console.app import role_description  # the matrix's words for the role (ROLE-018); console.app imports us

    _whole_catalogue()

    def t(key: str, **kw: Any) -> str:
        return translate(lang, key, **kw)

    return {
        "title": title(role, lang),
        "intro": t("guide.intro"),
        "what": (t("guide.what"), t(f"help.role.{role}")),
        "rights": (t("guide.rights"), role_description(role, lang)),
        "pages": (t("guide.pages"), [(t(f"guide.page.{s}"), t(f"help.page.{s}")) for s in ROLE_PAGES[role]]),
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


__all__ = ["PERSONA", "ROLES", "ROLE_PAGES", "markdown", "sections", "title"]
