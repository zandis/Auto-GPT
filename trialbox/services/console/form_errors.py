"""9k-6a (D-1376, review 09 DS-6, A11Y-4): what a failed POST carries back to its form.

A route that refuses a form's values answers with the form's page again, ``FAILED`` (400, the console's status for a
value that does not validate: ``study_setup.py``'s identifiers and IRB record, the study's state, the audit page),
with a :class:`FormErrors` the template hands to the field macro (``templates/_fields.html``):

* ``errors``: one :class:`FieldError` per failing field, in the form's order: the field's ``name`` (the input's
  ``name``, so its id is ``<prefix>-<name>``) and the text key of its message. The summary at the top of the page
  lists the messages as links to the fields; each field shows its own message, tied to it by ``aria-describedby``;
* ``values``: what the person typed, shown again so nothing has to be typed twice; **never** a password, a one-time
  code, a key or the CSRF token (:func:`kept_values`), and a value longer than ``VALUE_MAX`` is cut there.

The texts of the macro and of each converted form's messages are in ``console.i18n_form_errors``, joined into the
catalogue here (as ``admin_flags.py`` joins its own) when a page module imports this one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from console import i18n_form_errors
from console.i18n import CATALOGUES

for _lang, _cat in (("en", i18n_form_errors.EN), ("ja", i18n_form_errors.JA), ("zh-TW", i18n_form_errors.ZH)):
    CATALOGUES[_lang].update(_cat)

#: the status of a page shown again because a value did not validate (as the console's routes answer today: 400; a
#: refusal of a valid request stays 409, a missing right 403)
FAILED = 400
#: a value typed into a field is shown again up to this many characters (the routes cut theirs shorter)
VALUE_MAX = 2000
#: a field whose name says it holds a secret is never shown again, whatever the route passes
SECRET = re.compile(r"(?:^|[_-])(?:password|passwd|pass|pw|otp|totp|code|pin|secret|token|key|csrf)(?:$|[_-])", re.I)


def is_secret(name: str) -> bool:
    """True for a field never shown again: a password, a one-time code, a key, the CSRF token (``csrf``,
    ``password``, ``new_password``, ``enrol_code``, ``otp``, ``api_key`` ...)."""
    return bool(SECRET.search(name))


def kept_values(values: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> dict[str, str]:
    """The typed values to show again: text values only (an upload is never shown again), secrets left out, each
    cut at ``VALUE_MAX``. The last value of a name typed twice wins, as the routes read them."""
    items = values.items() if isinstance(values, Mapping) else values
    out: dict[str, str] = {}
    for name, value in items:
        if isinstance(value, str) and not is_secret(str(name)):
            out[str(name)] = value[:VALUE_MAX]
    return out


@dataclass(frozen=True)
class FieldError:
    """One failing field: the input's ``name`` and the text key of its message (the same words in the summary and
    at the field, as GOV.UK's error summary asks)."""

    name: str
    key: str


@dataclass(frozen=True)
class FormErrors:
    """A failed POST of one form: which form (its ``data-fields`` name), the prefix of its fields' ids, the errors in
    the form's order and the values typed (secrets already left out)."""

    form: str
    prefix: str
    errors: tuple[FieldError, ...]
    values: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.errors)

    def error(self, name: str) -> FieldError | None:
        """The error of the field ``name``, or None."""
        return next((e for e in self.errors if e.name == name), None)

    def value(self, name: str, default: Any = "") -> Any:
        """What was typed into ``name`` (never a secret), else ``default`` (the stored value the page shows)."""
        if is_secret(name):
            return ""
        return self.values.get(name, default)

    def field_id(self, name: str) -> str:
        return f"{self.prefix}-{name}"


def failed(form: str, prefix: str, errors: Iterable[tuple[str, str]],
           values: Mapping[str, Any] | Iterable[tuple[str, Any]] = ()) -> FormErrors:  # fmt: skip
    """The :class:`FormErrors` of a failed POST: ``errors`` as (field name, message key) in the form's order (a
    name given twice keeps its first message), ``values`` the request's form (secrets are left out here)."""
    seen: set[str] = set()
    out: list[FieldError] = []
    for name, key in errors:
        if name not in seen:
            seen.add(name)
            out.append(FieldError(name, key))
    return FormErrors(form=form, prefix=prefix, errors=tuple(out), values=kept_values(values))


# ---------------------------------------------------------------------------------------------- 9k-6b: refusals
#: what a rule of :func:`from_refusal` is: the (field name, message key) a refusal's reason belongs to, or a function
#: of the posted form that gives the list (a refusal that names no field, as "dates are YYYY-MM-DD")
Rule = tuple[str, str] | Callable[[Mapping[str, Any]], list[tuple[str, str]]]


def from_refusal(
    exc: BaseException, table: Mapping[str, Rule], form: Mapping[str, Any]
) -> list[tuple[str, str]] | None:
    """9k-6b (D-1376): the failing fields of a form whose route refuses a wrong value with the console's refusal
    (``problem(400, "request.refused", reason=<English sentence>)``), read from the sentence the route already raises:
    nothing the route checks, or in what order, changes; the refusal is only shown at the field. ``table`` maps each
    sentence the form can raise to a (field name, message key) or to a function of the posted ``form`` that gives
    the list (a refusal that names no field, as "dates are YYYY-MM-DD"). None when ``exc`` is not a refusal, its
    sentence is not on the table, or the function found no field to blame: the caller raises it as before (a refusal
    of a valid request, a 403, a missing study)."""
    if getattr(exc, "key", None) != "request.refused":
        return None
    values = getattr(exc, "values", None)
    reason = values.get("reason") if isinstance(values, Mapping) else None
    rule = table.get(reason) if isinstance(reason, str) else None
    if rule is None:
        return None
    out = rule(form) if callable(rule) else [rule]
    return out or None


def bad_dates(
    form: Mapping[str, Any], names: Iterable[str], key_of: Mapping[str, str], cut: int = 60
) -> list[tuple[str, str]]:
    """The fields of ``names`` (in the form's order) whose typed text is not a day year-month-day, as the stores read
    it (``date.fromisoformat`` of the stripped text; blank is no day and no error), with their message keys."""
    out: list[tuple[str, str]] = []
    for name in names:
        text = str(form.get(name) or "")[:cut].strip()
        if not text:
            continue
        try:
            date.fromisoformat(text)
        except ValueError:
            out.append((name, key_of[name]))
    return out


class Refusal(Exception):
    """A route's check that a form can show at its fields and the ``/api/v1`` twin still raises as the console's
    refusal: ``errors`` the failing (field name, message key) in the form's order, ``problem`` the refusal the route
    raised before 9k-6b (the API route re-raises it; the form route shows the fields)."""

    def __init__(self, errors: list[tuple[str, str]], problem: Exception) -> None:
        super().__init__(str(problem))
        self.errors = errors
        self.problem = problem
