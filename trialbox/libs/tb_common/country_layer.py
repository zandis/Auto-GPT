"""A country is data (plan 10, commitment C-7, card 10C-25, D-1250): the country layer above the site profile.

One file per country describes everything a site of that country gets that a site elsewhere does not. Japan's is
``japan_profile.json`` beside this module (review 11 section 8: parts P1 to P16). The site's country turns it on: the
same reading the site profile's ``country`` is checked against (``tb_common.derived.country_of``, D-1233). Every
behaviour reads its part through :func:`value`. ``tests/unit/test_japan_profile_layer.py`` holds a tripwire, not a
proof, on new country words in the code that ships. It scans Python under ``libs/`` and ``services/``, the box's
set-up tools, and the templates, YAML and JS under ``libs/`` and ``services/`` (their comments left out). It looks for
``jp``, ``jpn``, ``japan``, ``日本``, ``asia/tokyo``, ``tokyo``, ``jst`` and strings starting ``jp_``. It cannot see:
a string built by other means (a join, ``chr``, a slice), the dev and synthetic-data tools (which do not ship), or a
language word (``ja``: a language is not a country).

**A layer that cannot be used reaches its own country only.** A layer is read the first time a site of its country
asks, never at import and never for another country. A file that is missing, unreadable, not whole (:func:`parse`,
:data:`READ`) or names another country makes that country's layer broken: :func:`layer` returns it with its
``problem``, and asking it a value raises :class:`LayerBroken`. Each reader then says its value is not available in
its own safe way (D-1250 lists them), and the box's health says it in red. It never gives another country's value.

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
FILES = {"JP": "japan_profile.json"}  # the layers shipped: a country and its file (the file must name that country)
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
# every value a reader asks a layer for, with its type and (for a text, or each text of a list) its shape: a layer of
# this format carries each one, so a reader never meets a missing value and falls back to another country's (D-1250)
_TEXT = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
READ: dict[tuple[str, str], tuple[type, re.Pattern[str] | None]] = {
    ("P1", "retention_rules"): (str, _TEXT),
    ("P2", "sae_rule_set"): (str, _TEXT),
    ("P3", "committees"): (dict, None),
    ("P5", "report_language"): (str, re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")),
    ("P7", "ingredient_stems"): (bool, None),
    ("P7", "medis_master"): (bool, None),  # D-1261: the site set-up step that loads the MEDIS master
    # the code tables the site set-up maps a site's own codes against (sitesetup.mapping, D-1255): files of the
    # adapter's mapping folder, each of a format the set-up reads, each once
    ("P7", "code_tables"): (
        list,
        re.compile(r"^[a-z0-9_]+/(byomei_to_icd10|jlac10_to_loinc|lab_local_to_loinc|yj_to_atc)\.csv$"),
    ),
    ("P8", "egfr"): (str, _TEXT),
    ("P9", "printed_dates"): (str, _TEXT),
    ("P9", "year_basis"): (str, _TEXT),
    ("P9", "holiday_list"): (str, re.compile(r"^holidays_[a-z]+\.csv$")),
    ("P9", "new_year_break"): (str, re.compile(r"^12-[0-3][0-9]/01-[0-3][0-9]$")),
    ("P11", "consent_proxy"): (bool, None),
    ("P14", "data_source_type"): (str, _TEXT),
    ("P14", "mapping"): (str, re.compile(r"^mapping/[a-z0-9_]+/[a-z0-9_]+\.yaml$")),
    ("P14", "one_zone"): (bool, None),
}
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


class LayerBroken(LayerError):
    """A value asked of a site whose country ships a layer that cannot be used: the reader says the value is not
    available (each in its own safe way, D-1250); it never takes another country's."""


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
    problem: str = ""  # why the country's shipped layer cannot be used ("" when it can, or there is none)

    @property
    def on(self) -> bool:
        return bool(self.country) and not self.problem

    @property
    def broken(self) -> bool:
        return bool(self.problem)

    def value(self, part: str, key: str, default: Any = None) -> Any:
        """``key`` of ``part``; ``default`` without a layer. A broken layer raises :class:`LayerBroken`."""
        if self.problem:
            raise LayerBroken(self.file, self.problem)
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
    that read its values, and a value is never a part's without a key a reader can ask for. Every value a reader asks
    for (:data:`READ`) is there, of its type and shape: a layer without one is refused whole."""
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
    for (pid, key), (kind, shape) in READ.items():
        if key not in parts[pid].values:
            raise LayerError(file, f"parts.{pid}.values: {key!r} is missing (a reader asks for it)")
        got = parts[pid].values[key]
        if type(got) is not kind or not got or (kind is not list and shape is not None and not shape.match(str(got))):
            raise LayerError(file, f"parts.{pid}.values.{key}: {got!r} is not a {kind.__name__} of its shape")
        items: list[Any] = got if isinstance(got, list) else []  # a list: of texts, each of the shape, each once
        for x in items:
            if type(x) is not str or (shape is not None and not shape.match(x)):
                raise LayerError(file, f"parts.{pid}.values.{key}: {x!r} is not a str of its shape")
            if items.count(x) > 1:
                raise LayerError(file, f"parts.{pid}.values.{key}: {x!r} is listed twice")
    return Layer(country, version, hashlib.sha256(raw).hexdigest(), file, parts)


def load(path: Path) -> Layer:
    return parse(path.read_bytes(), path.name)


@cache
def _shipped(code: str) -> Layer:
    """The layer shipped for ``code``, read the first time a site of that country asks (never at import, never for
    another country). :data:`NONE` when the country ships none; a layer whose file cannot be used (missing, unreadable,
    not whole, or naming another country) is returned with its ``problem``, and never raises here."""
    name = FILES.get(code)
    if name is None:
        return NONE
    try:
        lay = load(ROOT / name)
        if lay.country != code:
            raise LayerError(name, f"country {lay.country!r}: the file is the layer of {code}")
        return lay
    except LayerError as exc:
        return Layer(code, file=name, problem=exc.reason)
    except Exception as exc:  # unreadable: a broken layer of this country only, said where it is read
        return Layer(code, file=name, problem=f"cannot be read ({type(exc).__name__}: {str(exc)[:120]})")


def layer(country: str | None) -> Layer:
    """The layer of a site of ``country`` (``JP``, ``jp``; None or "" for none): :data:`NONE` when it has none. A
    broken one is returned with its ``problem`` (:attr:`Layer.broken`); asking it a value raises
    :class:`LayerBroken`. Never raises itself."""
    return _shipped(str(country or "").strip().upper())


def value(country: str | None, part: str, key: str, default: Any = None) -> Any:
    """The value ``key`` of ``part`` for a site of ``country``; ``default`` when the country has no layer. Raises
    :class:`LayerBroken` when the country's layer is broken: the reader then says the value is not available, never
    another country's. The one way a behaviour asks the layer."""
    return layer(country).value(part, key, default)


def having(part: str, key: str) -> Layer:
    """The one layer that carries ``key`` in ``part`` (for a module that is the whole of one country's part, such as
    ``tb_common.committees``); :data:`NONE` when none does. Raises :class:`LayerBroken` when a shipped layer that
    would be asked is broken."""
    found = []
    for code in FILES:
        lay = layer(code)
        if lay.broken:
            raise LayerBroken(lay.file, lay.problem)
        if key in (lay.parts[part].values if part in lay.parts else {}):
            found.append(lay)
    if len(found) > 1:
        raise LayerError(
            found[1].file, f"{part}.{key} is carried by two layers ({found[0].country}, {found[1].country})"
        )
    return found[0] if found else NONE


def stamp(country: str | None) -> dict[str, str] | None:
    """What a record says of the layer a site of ``country`` read: ``{country, version, digest}``, or None (no layer,
    or a broken one: nothing was read from it)."""
    return layer(country).stamp()
