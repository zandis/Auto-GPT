"""A country is data (plan 10, commitment C-7, card 10C-25, D-1250): the country layer above the site profile.

One file per country describes everything a site of that country gets that a site elsewhere does not. Japan's is
``japan_profile.json`` beside this module (review 11 section 8: parts P1 to P16). The site's country turns it on: the
same reading the site profile's ``country`` is checked against (``tb_common.derived.country_of``, D-1233). Every
behaviour reads its part through :func:`value`; no product code tests a country string for a behaviour of its own
(``tests/unit/test_japan_profile_layer.py`` holds that).

**The same code path for every country.** A reader asks :func:`value` for its key. A site whose country has no layer
gets ``None`` and the reader's other-country default, the value a site with no layer had before; a site whose
country has a layer gets the layer's value. A layer with another country code but the same values gives the same
results by the same calls (the test proves it with a copy renamed to a made-up country).

**A setting a person made wins.** Where a site sets a value by hand (``site.printed_dates``, ``site.year_basis``,
``TB_CONSENT_PROXY``, ``TB_NEW_YEAR_BREAK``, ``TB_DAYS_OFF``, ``TB_DAYS_OPEN``, ``TB_JP_INGREDIENT_ATC``), the hand-set
value is the one read: it is a named person's recorded choice, as the site set-up store wins over the site profile's
table (D-1233). The layer's set-up values (``printed_dates``, ``year_basis``, ``consent_proxy``, the report language,
the source, the mapping) are the defaults the set-up wizards offer and write into a new site's settings
(``tb_common.site_country``); they are never read as a run-time default, so an installed box whose settings do not
name them prints and counts exactly as before (D-1229).

**Versions.** A layer has ``format`` (``tb-country-layer/1``), a ``version`` (MAJOR.MINOR.PATCH) and a digest (the
SHA-256 of the file's bytes). It ships inside the signed update bundle, as the holiday list does (D-1230), so its
version is the release's. The site profile's record names it (:func:`stamp`, ``active.layer``) beside the profile's
own version and digest; the ``terminology.site_profile_load`` audit event is unchanged.

Standard library only: ``tb_common.site_country`` reads it on the host before any image is loaded.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

FORMAT = "tb-country-layer/1"
ROOT = Path(__file__).resolve().parent
FILES = ("japan_profile.json",)  # the layers shipped, one per country (the file names its country)
PARTS = tuple(f"P{i}" for i in range(1, 17))  # review 11 section 8, P1 to P16
NAMES = (
    "Legal pack", "Study kinds", "Committees", "Roles", "Words", "Forms", "Masters", "Chart reading",
    "Dates and calendar", "Privacy guard", "Patient approach", "Money", "Registries", "Interoperability",
    "Procurement and security", "Accessibility and type",
)  # fmt: skip
KINDS = ("behaviour", "wording", "document")
BUILT, PARTLY, DECLARED = "built", "partly built", "declared, not built"
STATES = (BUILT, PARTLY, DECLARED)
EVERYWHERE = "On everywhere, not switched by country: "  # what a part has that the country does not switch
_TOP = {"format", "_what", "country", "version", "parts", "_ruling"}
_PART = {"name", "kind", "state", "cards", "decisions", "values", "readers", "everywhere", "not_built",
         "open_questions"}  # fmt: skip
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_READER = re.compile(r"^[a-z_][a-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_CARD = re.compile(r"^10[A-Z]-[0-9]+[a-z]?$")
_DECISION = re.compile(r"^D-[0-9]+$")


class LayerError(ValueError):
    """A layer file that cannot be used, with the file and the reason."""

    def __init__(self, file: str, reason: str) -> None:
        super().__init__(f"{file}: {reason}")
        self.file, self.reason = file, reason


@dataclass(frozen=True)
class Part:
    id: str
    name: str
    kind: str
    state: str
    cards: tuple[str, ...]
    decisions: tuple[str, ...]
    values: dict[str, Any] = field(default_factory=dict)
    readers: tuple[str, ...] = ()
    everywhere: str = ""  # what of this part is on for every site (not switched by the layer)
    not_built: str = ""
    open_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Layer:
    """One country's layer; :data:`NONE` for a country without one."""

    country: str = ""
    version: str = ""
    digest: str = ""
    file: str = ""
    parts: dict[str, Part] = field(default_factory=dict)

    @property
    def on(self) -> bool:
        return bool(self.country)

    def value(self, part: str, key: str, default: Any = None) -> Any:
        p = self.parts.get(part)
        return p.values.get(key, default) if p is not None else default

    def stamp(self) -> dict[str, str] | None:
        """``{country, version, digest}``, or None for no layer."""
        return {"country": self.country, "version": self.version, "digest": self.digest} if self.on else None


NONE = Layer()


def _strs(v: Any, file: str, where: str, shape: re.Pattern[str] | None = None) -> tuple[str, ...]:
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise LayerError(file, f"{where}: a list of words")
    bad = [x for x in v if shape is not None and not shape.match(x)]
    if bad:
        raise LayerError(file, f"{where}: {bad[0]!r} is not one")
    return tuple(v)


def parse(raw: bytes, file: str) -> Layer:
    """A layer from its file's bytes; :class:`LayerError` names what is wrong. Every part P1 to P16 is there, by its
    name; a part ``declared, not built`` carries no values and no readers; a part built (or partly) names the readers
    that read its values, and a value is never a part's without a key a reader can ask for."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LayerError(file, f"not UTF-8 JSON ({exc})") from None
    if not isinstance(doc, dict):
        raise LayerError(file, "not an object")
    unknown = sorted(set(doc) - _TOP)
    if unknown:
        raise LayerError(file, f"unknown key {unknown[0]!r}")
    if doc.get("format") != FORMAT:
        raise LayerError(file, f"format is {doc.get('format')!r}, not {FORMAT}")
    country, version = doc.get("country"), doc.get("version")
    if not isinstance(country, str) or not _COUNTRY.match(country):
        raise LayerError(file, f"country {country!r}: two capital letters")
    if not isinstance(version, str) or not _SEMVER.match(version):
        raise LayerError(file, f"version {version!r}: MAJOR.MINOR.PATCH")
    parts_doc = doc.get("parts")
    if not isinstance(parts_doc, dict) or tuple(parts_doc) != PARTS:
        raise LayerError(file, f"parts: exactly {PARTS[0]} to {PARTS[-1]}, in order")
    parts: dict[str, Part] = {}
    for (pid, p), name in zip(parts_doc.items(), NAMES, strict=True):
        where = f"parts.{pid}"
        if not isinstance(p, dict):
            raise LayerError(file, f"{where}: not an object")
        extra = sorted(set(p) - _PART)
        if extra:
            raise LayerError(file, f"{where}: unknown key {extra[0]!r}")
        if p.get("name") != name:
            raise LayerError(file, f"{where}: name {p.get('name')!r}, not {name!r}")
        if p.get("kind") not in KINDS:
            raise LayerError(file, f"{where}: kind {p.get('kind')!r}, one of {', '.join(KINDS)}")
        if p.get("state") not in STATES:
            raise LayerError(file, f"{where}: state {p.get('state')!r}, one of {', '.join(STATES)}")
        values = p.get("values", {})
        if not isinstance(values, dict) or not all(isinstance(k, str) and _KEY.match(k) for k in values):
            raise LayerError(file, f"{where}.values: an object of lower-case keys")
        readers = _strs(p.get("readers", []), file, f"{where}.readers", _READER)
        if p["state"] == DECLARED and (values or readers or p.get("everywhere")):
            raise LayerError(file, f"{where}: declared, not built, yet it carries values, readers or 'everywhere'")
        if p["state"] != DECLARED and not (readers or p.get("everywhere")):
            raise LayerError(file, f"{where}: {p['state']}, yet nothing reads it and nothing is on everywhere")
        if bool(values) != bool(readers):
            raise LayerError(file, f"{where}: values and readers go together")
        if p.get("everywhere") and not str(p["everywhere"]).startswith(EVERYWHERE):
            raise LayerError(file, f"{where}.everywhere: starts '{EVERYWHERE}'")
        if p["state"] != BUILT and not str(p.get("not_built") or "").strip():
            raise LayerError(file, f"{where}: {p['state']}: 'not_built' says what is missing and which card builds it")
        parts[pid] = Part(
            pid, name, p["kind"], p["state"],
            _strs(p.get("cards", []), file, f"{where}.cards", _CARD),
            _strs(p.get("decisions", []), file, f"{where}.decisions", _DECISION),
            dict(values), readers, str(p.get("everywhere") or ""), str(p.get("not_built") or ""),
            _strs(p.get("open_questions", []), file, f"{where}.open_questions"),
        )  # fmt: skip
    return Layer(country, version, hashlib.sha256(raw).hexdigest(), file, parts)


def load(path: Path) -> Layer:
    return parse(path.read_bytes(), path.name)


@cache
def layers() -> dict[str, Layer]:
    """Every shipped layer by its country (read once). Two files for one country are refused."""
    out: dict[str, Layer] = {}
    for name in FILES:
        lay = load(ROOT / name)
        if lay.country in out:
            raise LayerError(name, f"a second layer for {lay.country} ({out[lay.country].file})")
        out[lay.country] = lay
    return out


def layer(country: str | None) -> Layer:
    """The layer of a site of ``country`` (``JP``, ``jp``; None or "" for none): :data:`NONE` when it has none."""
    return layers().get(str(country or "").strip().upper(), NONE)


def value(country: str | None, part: str, key: str, default: Any = None) -> Any:
    """The value ``key`` of ``part`` for a site of ``country``; ``default`` when the country has no layer, or its
    layer does not carry it. The one way a behaviour asks the layer."""
    return layer(country).value(part, key, default)


def having(part: str, key: str) -> Layer:
    """The one layer that carries ``key`` in ``part`` (for a module that is the whole of one country's part, such as
    ``tb_common.committees``); :data:`NONE` when none does."""
    found = [lay for lay in layers().values() if key in (lay.parts[part].values if part in lay.parts else {})]
    if len(found) > 1:
        raise LayerError(
            found[1].file, f"{part}.{key} is carried by two layers ({found[0].country}, {found[1].country})"
        )
    return found[0] if found else NONE


def stamp(country: str | None) -> dict[str, str] | None:
    """What a record says of the layer a site of ``country`` read: ``{country, version, digest}``, or None."""
    return layer(country).stamp()
