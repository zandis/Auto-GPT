"""The gold kind of an accuracy figure (card 10G-38, D-1326): every accuracy report names what its gold is, and no
figure pools two kinds.

The five kinds (review 20, item 20-15; its §7.1 "Gold type" column):

* ``physician``              labels written by physicians or clinicians on the text the box reads
* ``generated and checked``  generated charts with planted truth, verified (review 20 §7.5, stage G3)
* ``translated``             a physician's label carried onto a translation of the text it was written on
* ``structured truth``       the truth a record was built from (JMED-Personas' own conditions)
* ``enrolment``              an investigator's enrolment decision or a coordinator's list (stage G4, shadow mode)

A report writes ``gold_kind``: one of the five, or ``None`` where the repository's documents do not state the kind
of a set (never guessed; listed as open questions on the card's page). A report without the field (every report
stored before this card) is read as ``"not stated"``. A pooled figure needs every part to be of one stated kind:
anything else is refused (:class:`PoolingRefused`), and the parts stay apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

KINDS = ("physician", "generated and checked", "translated", "structured truth", "enrolment")
NOT_STATED = "not stated"

# set -> (kind for every language, or per language), and where the repository says so. A set not here: not stated.
_SETS: dict[str, tuple[str | dict[str, str], str]] = {
    "medtxt": (
        {"ja": "physician", "en": "translated"},
        "review 20 §7.1 (MedTxt: clinician annotation, published); eval/medtxt/README.md (clinician-made English "
        "translations; the label is the Japanese annotation's, tools/medtxt_eval.py)",
    ),
    "criterion_ml": (
        {"en": "physician", "ja": "translated", "zh-TW": "translated", "mixed": "translated"},
        "review 20 §7.1 (criterion_ml: physician labels, translated notes); eval/criterion_ml/README.md (the physician "
        "label `expert_eligibility`)",
    ),
    "sigir": (
        "physician",
        "eval/public_accuracy_key/README.md (the SIGIR pairs and the same physicians' criterion labels); review 20 "
        "§7.6 (criterion_ml (SIGIR), English source)",
    ),
    "jmed": ("structured truth", "review 20 §7.1 (JMED-Personas, key v2: structured truth)"),
}


class PoolingRefused(ValueError):
    """A figure would pool gold of different (or unstated) kinds."""


def of_set(name: str | None, lang: str | None = None) -> str | None:
    """The gold kind of set ``name`` (in ``lang`` where the kind differs by language), or None: not stated."""
    kind = _SETS.get(name or "", (None, ""))[0]
    if isinstance(kind, dict):
        return kind.get(lang or "")
    return kind


def source(name: str) -> str:
    """Where the repository states the kind of set ``name`` ("" when it does not)."""
    return _SETS.get(name, (None, ""))[1]


def read(report: Mapping[str, Any]) -> str:
    """The gold kind a report names; ``"not stated"`` for a report without one (stored before 10G-38) or with None."""
    kind = report.get("gold_kind")
    if kind is None:
        return NOT_STATED
    if kind not in KINDS:
        raise ValueError(f"gold_kind {kind!r} is not one of the five kinds: {', '.join(KINDS)}")
    return str(kind)


def pooled(parts: Iterable[tuple[str, str | None]]) -> str:
    """The one kind of a pooled figure over ``parts`` ((name, gold kind) per part), or :class:`PoolingRefused`.

    One part is never a pool. Two or more must all be of one stated kind: a part whose kind is not stated cannot be
    shown to share the others' kind, so it is refused as well."""
    ps = [(n, NOT_STATED if k is None else k) for n, k in parts]
    for n, k in ps:
        if k not in (*KINDS, NOT_STATED):
            raise ValueError(f"{n}: gold_kind {k!r} is not one of the five kinds: {', '.join(KINDS)}")
    if not ps:
        raise PoolingRefused("not pooled: no parts")
    if len(ps) == 1:
        return ps[0][1]
    kinds = {k for _, k in ps}
    if len(kinds) > 1 or NOT_STATED in kinds:
        named = "; ".join(f"{n}: {k}" for n, k in ps)
        raise PoolingRefused(
            f"not pooled: the gold kinds differ or are not stated ({named}); each kind is reported on its own (D-1326)"
        )
    return ps[0][1]
