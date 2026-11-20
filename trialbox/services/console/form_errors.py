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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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
