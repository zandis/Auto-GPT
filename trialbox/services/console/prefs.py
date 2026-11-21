"""10F-1 (D-1387, review 16 §5.1 "per user"): a person's own preferences, inside what their role already shows.

Four keys, each with a closed set of values; the first value of each is the default (the console as it was before
this card). A preference only chooses how the person's own pages look (density, text size, colour mode) and the
language of their next sessions; it never names a page, a field, a study, a patient, a mail or a notice, and no
value is free text, so none can hold a pseudonym or any other patient-linked word (the table is not patient-linked:
``tb_common.erasure``). What the role shows is decided before a preference is read, by the same checks as before.

Not here, by the owner's ruling of 2026-11-20: quiet hours (and anything that defers or suppresses a notice; an SAE
notice is never affected by a preference, FR-NOTIF-04 stays H).

Stored per person in ``auth.user_pref`` (``console.auth.UserStore.prefs`` / ``set_prefs``); a value equal to the
default is stored as no row. Every change is audited as ``console.pref_set`` (who, key, from, to): the console's
audit family is ``console`` (D-488), so the review's ``pref.set`` is spelled ``console.pref_set``.
"""

from __future__ import annotations

from collections.abc import Mapping

#: each key's closed set; the first value is the default
KEYS: dict[str, tuple[str, ...]] = {
    "density": ("comfortable", "compact"),
    "text_size": ("100", "125", "150"),
    "mode": ("system", "light", "dark", "contrast"),
    "lang": ("auto", "en", "ja", "zh-TW"),
}
DEFAULTS: dict[str, str] = {k: v[0] for k, v in KEYS.items()}
#: the text key of each value's label (literal keys, so ``tools.text_keys`` sees every one); a language is named in
#: its own words (``lang.name.*``), as the header's switch does
LABELS: dict[str, dict[str, str]] = {
    "density": {"comfortable": "pref.density.comfortable", "compact": "pref.density.compact"},
    "text_size": {"100": "pref.text_size.100", "125": "pref.text_size.125", "150": "pref.text_size.150"},
    "mode": {
        "system": "pref.mode.system",
        "light": "pref.mode.light",
        "dark": "pref.mode.dark",
        "contrast": "pref.mode.contrast",
    },
    "lang": {"auto": "pref.lang.auto", "en": "lang.name.en", "ja": "lang.name.ja", "zh-TW": "lang.name.zh-TW"},
}
#: the label of each field and the message of a value outside its set (the same words at the field and in the summary)
FIELD_LABELS: dict[str, str] = {
    "density": "pref.density",
    "text_size": "pref.text_size",
    "mode": "pref.mode",
    "lang": "account.lang",
}
MESSAGES: dict[str, str] = {
    "density": "fe.pref.density",
    "text_size": "fe.pref.text_size",
    "mode": "fe.pref.mode",
    "lang": "fe.pref.lang",
}
FORM = "prefs"  # the form's ``data-fields`` name (9k-6a, D-1376)
PREFIX = "pref"
AUDIT_EVENT = "console.pref_set"


def valid(key: str, value: str) -> bool:
    """True when ``key`` is a preference and ``value`` one of its closed set."""
    return value in KEYS.get(key, ())


def of(stored: Mapping[str, str]) -> dict[str, str]:
    """Every key with its value: a stored one when it is still in the closed set, else the default (a row a later
    release no longer knows is read as the default, never shown)."""
    return {k: stored[k] if valid(k, stored.get(k, "")) else d for k, d in DEFAULTS.items()}


def problems(form: Mapping[str, str]) -> list[tuple[str, str]]:
    """(field, message key) of each posted value outside its key's set, in the form's order. A key not posted is
    left as it is (no problem)."""
    return [(k, MESSAGES[k]) for k in KEYS if k in form and not valid(k, form[k])]


def changes(current: Mapping[str, str], form: Mapping[str, str]) -> dict[str, str]:
    """The posted keys whose value differs from ``current`` (every value already valid)."""
    return {k: form[k] for k in KEYS if k in form and form[k] != current.get(k, DEFAULTS[k])}


def html_attrs(prefs: Mapping[str, str]) -> dict[str, str]:
    """The data attributes ``base.html`` puts on ``<html>`` for the look (``console.css``, the 10F-1 block): only a
    value other than the default, so a page of a person who chose nothing is the page as it was."""
    p = of(prefs)
    out: dict[str, str] = {}
    if p["density"] != DEFAULTS["density"]:
        out["data-density"] = p["density"]
    if p["text_size"] != DEFAULTS["text_size"]:
        out["data-text-size"] = p["text_size"]
    if p["mode"] != DEFAULTS["mode"]:
        out["data-mode"] = p["mode"]
    return out


def session_lang(prefs: Mapping[str, str]) -> str | None:
    """The language a new session starts in: the stored one, or None ("auto": the sign-in page's choice or the
    browser's, as before)."""
    lang = of(prefs)["lang"]
    return None if lang == DEFAULTS["lang"] else lang
