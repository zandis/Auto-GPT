"""Rule cards (RULES-ARCH decision 1): a card is an IR 3.x criterion template with ``{{param}}`` slots, its typed
parameters and its fixtures; :func:`instantiate` turns a card and parameter values into a ``CriterionIRv3``.

A card file is ``cards/<card_id>/<version>.json``::

    {"card_id": "lab.liver.alt_uln", "version": "1.0.0", "sources": ["tpl_..."],
     "params": {"multiple": {"type": "number", "min": 1, "max": 10, "default": 3, "observed_p10_p90": [2.5, 5]}},
     "ir_template": {... an IR 3.x criterion; "{{multiple}}" alone is the typed value ("-{{days}}" its negation),
                     inside text it is spliced ...},
     "fixtures": [{"name": "...", "params": {...}, "facts": [...], "expect": "T"}]}

``sources`` (the template ids the card came from) and ``observed_p10_p90`` are provenance: :func:`card_hash` leaves
them out, so a refresh of either never makes another card. The instance's ``canonical_hash`` is the hash of its
atoms (``card_ref`` and ``flags`` are outside it), so two cards that render the same atoms give the same hash.
Terminology binding is data: a card names value sets, never codes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from tb_contracts.criterion_ir import CriterionIRv3, canonical_hash, jcs

CARDS_DIR = Path(__file__).resolve().parents[2] / "cards"
CARD_ID = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
_SEMVER = r"^\d+\.\d+\.\d+$"
_SLOT = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_WHOLE = re.compile(r"(-?)\{\{([a-z][a-z0-9_]*)\}\}")  # a whole string: the typed value, "-" negates a number


class CardError(ValueError):
    """A card that cannot be loaded, or parameters it does not accept."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Param(_Model):
    type: Literal["integer", "number", "string"]
    min: float | None = None
    max: float | None = None
    values: list[str] | None = Field(default=None, description="string params: the accepted values")
    default: int | float | str | None = None
    observed_p10_p90: tuple[float, float] | None = Field(
        default=None, description="the 10th and 90th centile seen in the source templates; provenance, outside the hash"
    )


class Fixture(_Model):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    index_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expect: Literal["T", "F", "U"]


class Card(_Model):
    card_id: str = Field(pattern=CARD_ID)
    version: str = Field(pattern=_SEMVER)
    title: str | None = None
    sources: list[str] = Field(default_factory=list, description="template ids; provenance, outside the hash")
    params: dict[str, Param] = Field(default_factory=dict)
    ir_template: dict[str, Any]
    fixtures: list[Fixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def _slots(self) -> Card:
        used = set(_SLOT.findall(json.dumps(self.ir_template)))
        if used - set(self.params):
            raise ValueError(f"slots without a param: {', '.join(sorted(used - set(self.params)))}")
        if set(self.params) - used:
            raise ValueError(f"params no slot uses: {', '.join(sorted(set(self.params) - used))}")
        return self


def card_hash(card: Card) -> str:
    """``sha256:`` over the JCS form of the card without its provenance (``sources``, ``observed_p10_p90``)."""
    d = card.model_dump(mode="json", exclude={"sources"})
    for p in d["params"].values():
        p.pop("observed_p10_p90", None)
    return "sha256:" + hashlib.sha256(jcs(d).encode("utf-8")).hexdigest()


def load(card_id: str, version: str, cards_dir: Path = CARDS_DIR) -> Card:
    path = cards_dir / card_id / f"{version}.json"
    if not path.is_file():
        raise CardError(f"no card {card_id}@{version}")
    try:
        card = Card.model_validate_json(path.read_bytes())
    except ValidationError as exc:
        raise CardError(f"card {card_id}@{version}: {exc}") from exc
    if (card.card_id, card.version) != (card_id, version):
        raise CardError(f"{path.name} holds {card.card_id}@{card.version}, not {card_id}@{version}")
    return card


_TYPES: dict[str, type | tuple[type, ...]] = {"integer": int, "number": (int, float), "string": str}


def _check(name: str, p: Param, v: Any) -> None:
    numeric = p.type in ("integer", "number")
    typed = not isinstance(v, bool) and isinstance(v, _TYPES[p.type])  # a bool is no number here
    if not typed:
        raise CardError(f"param {name}: {v!r} is not {p.type}")
    if numeric and ((p.min is not None and v < p.min) or (p.max is not None and v > p.max)):
        raise CardError(f"param {name}: {v} is outside [{p.min}, {p.max}]")
    if p.type == "string" and p.values is not None and v not in p.values:
        raise CardError(f"param {name}: {v!r} is not one of {', '.join(p.values)}")


def _fill(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, values) for v in node]
    if isinstance(node, str):
        whole = _WHOLE.fullmatch(node)
        if whole:
            v = values[whole.group(2)]
            return -v if whole.group(1) else v
        return _SLOT.sub(lambda m: str(values[m.group(1)]), node)
    return node


def instantiate(
    card: Card, params: dict[str, Any], *, criterion_id: str | None = None, ruleset: str | None = None
) -> CriterionIRv3:
    """The criterion ``card`` renders with ``params`` (defaults fill the rest), as IR 3.1.0 with ``card_ref`` set,
    a ``param_outside_p10_p90:<name>`` flag for each value outside its observed centiles, and its canonical hash.

    ``criterion_id`` / ``ruleset`` replace the template's own. Raises :class:`CardError` for an unknown or missing
    param, a wrong type, a value out of range, or a rendered criterion that is not valid IR."""
    unknown = sorted(set(params) - set(card.params))
    if unknown:
        raise CardError(f"{card.card_id}: unknown params {', '.join(unknown)}")
    values: dict[str, Any] = {}
    flags: list[str] = []
    for name, p in card.params.items():
        v = params.get(name, p.default)
        if v is None:
            raise CardError(f"{card.card_id}: param {name} has no value and no default")
        _check(name, p, v)
        if p.observed_p10_p90 and p.type != "string" and not p.observed_p10_p90[0] <= v <= p.observed_p10_p90[1]:
            flags.append(f"param_outside_p10_p90:{name}")
        values[name] = v
    d = _fill(card.ir_template, values)
    d["ir_version"] = "3.1.0"
    d["card_ref"] = {"card_id": card.card_id, "card_version": card.version, "params": values}
    d.update({k: v for k, v in (("id", criterion_id), ("ruleset", ruleset)) if v is not None})
    d.pop("canonical_hash", None)
    if flags:
        d["flags"] = [*d.get("flags", []), *flags]
    try:
        ir = CriterionIRv3.model_validate(d)
    except ValidationError as exc:
        raise CardError(f"{card.card_id}@{card.version} renders an invalid criterion: {exc}") from exc
    return ir.model_copy(update={"canonical_hash": canonical_hash(ir)})
