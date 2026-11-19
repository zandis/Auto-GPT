"""Free text typed by a person is masked before it reaches the audit chain (the register's V3-14, V8-03, V8-07; ASVS
7.1.2; plan 8 criterion 8: the chain is never erased, so nothing of a person may stand in it).

A note, a reason or a comment is what a person types; a chart number, a labelled name, a phone or an e-mail typed
there used to be stored as typed. :func:`mask_free_text` masks it as the reveal note always was (D-272's
``mask_ids``, the note masker with the site's chart-number pattern, and any run of six or more digits);
:func:`mask_free_text_in` does so for every free-text key of an audit detail, at any depth; :class:`FreeTextMasked`
wraps an audit writer so every event it writes is masked so. A key that is not free text (an id, a pseudonym, a job,
a state) is never touched: a pseudonym's digits stay readable where the reader may see them. A name with no label
is outside the masker's scope (the register's V5-13)."""

from __future__ import annotations

import re
from typing import Any

from tb_common.audit import ID_MASK, mask_ids
from tb_common.phi_guard import mask_note, site_mrn_regex

#: the detail keys a person types into (a note, a reason, why, a comment)
FREE_TEXT_KEYS = frozenset({"note", "reason", "why", "comment"})
_DIGITS = re.compile(r"\d{6,}")  # a chart number written without its label, when the site's pattern is not readable


def mask_free_text(text: str) -> str:
    """``text`` with its whitespace folded (a label and its value on two lines are one span, as the reveal note
    always folded them) and every identifier the note masker knows replaced."""
    folded = " ".join((text or "").split())
    return _DIGITS.sub(ID_MASK, mask_note(mask_ids(folded), site_mrn_regex()))


def mask_free_text_in(value: Any) -> Any:
    """``value`` (an audit detail) with every free-text key's text masked, at any depth; other keys as they are."""
    if isinstance(value, dict):
        return {k: (mask_free_text(v) if isinstance(v, str) and str(k).lower() in FREE_TEXT_KEYS
                    else mask_free_text_in(v)) for k, v in value.items()}  # fmt: skip
    if isinstance(value, list | tuple):
        return [mask_free_text_in(v) for v in value]
    return value


class FreeTextMasked:
    """An audit writer whose every event has its free text masked (:func:`mask_free_text_in`); everything else is
    the wrapped writer's (its directory, its other methods)."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def append(self, event: str, **fields: Any) -> Any:
        """Free text under ``detail`` or nested in any other argument (the log moves those into the detail), and a
        top-level free-text argument, are masked; every other value is passed as it is."""
        masked = {k: (mask_free_text(v) if isinstance(v, str) and k.lower() in FREE_TEXT_KEYS
                      else mask_free_text_in(v)) for k, v in fields.items()}  # fmt: skip
        return self._inner.append(event, **masked)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)
