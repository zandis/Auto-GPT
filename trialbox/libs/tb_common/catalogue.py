"""The clinical item catalogue as data (T-107, D-353): ``catalogue/items.csv`` read once, checked, and the rules every
reader shares.

* :func:`items` reads the 469 items (or any catalogue folder: ``TB_CATALOGUE_DIR``, else ``trialbox/catalogue``).
  The file is the input; nothing here writes it (D-180's ``tools/catalogue_verify.py`` owns its columns).
* :func:`check` holds the id rules (D-180, catalogue README): a local item's concept id is in the TB-SHARED catalogue
  band (2,000,001,001 to 2,099,999,999), unique, in file order (rows are appended, never reordered), and never an id
  that ``verification/loinc_decisions.csv`` retired. A LOINC item has no local id. A file that breaks a rule is
  refused as a whole: nothing is loaded from it.
* ``storable`` says which parts of an instrument a site may keep: ``score`` (the total only), ``score+items`` (also
  the item answers), ``score+items+text`` (also the text). :func:`refused_fact` is the chart extraction's gate: a
  fact that names a part of a score-only instrument (``MMSE orientation 4/5``) is dropped, never proposed; the
  total itself (``MMSE 26/30``) is kept.
* :func:`hints_block` is the generated block of extraction hints for a chart-facts prompt version that asks for
  catalogue items. The block is optional: a prompt without it still runs.
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CATALOGUE_DIR = Path(__file__).resolve().parents[2] / "catalogue"
BAND_FIRST = 2_000_001_001  # the first local catalogue id (catalogue README; D-144 keeps 2e9 to 2.1e9 shared)
BAND_LAST = 2_099_999_999  # the TB-SHARED range ends below the first site block (2,100,000,000)
STORABLE = ("score", "score+items", "score+items+text")
LANGS = ("en", "ja", "zh-TW")
_LOINC = re.compile(r"^[0-9]{1,7}-[0-9]$")
_TOTAL_WORDS = frozenset({"", "total", "total score", "score", "合計", "合計点", "總分", "总分", "スコア"})


class CatalogueError(ValueError):
    """A catalogue file that breaks a rule; ``problems`` lists every broken rule (one line each)."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
        self.problems = list(problems)


@dataclass(frozen=True)
class Item:
    id: str
    names: dict[str, str]
    specialties: tuple[str, ...]
    item_type: str
    value_type: str
    unit: str
    loinc: str  # a LOINC code, or "" for a local item
    local_id: int | None  # the TB-SHARED concept id of a local item
    storable: str
    documented_as: str
    criterion_phrasing: str
    extraction_hint: str
    verified: bool
    code_fit: str
    may_exclude: bool
    components: tuple[str, ...] = field(default_factory=tuple)

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names["en"]

    @property
    def keeps_items(self) -> bool:
        """The site may keep the instrument's item answers (``storable`` has ``items``)."""
        return "items" in self.storable.split("+")

    @property
    def keeps_text(self) -> bool:
        return "text" in self.storable.split("+")

    @property
    def domain(self) -> str:
        """The OMOP domain of the item's concept."""
        if self.item_type == "procedure":
            return "Procedure"
        if self.item_type == "device":
            return "Device"
        if self.item_type == "lab" or self.value_type in ("number", "integer", "titer"):
            return "Measurement"
        return "Observation"


def catalogue_dir() -> Path:
    return Path(os.environ.get("TB_CATALOGUE_DIR") or CATALOGUE_DIR)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def retired_ids(folder: Path | None = None) -> set[int]:
    """Local ids a LOINC adoption retired (``verification/loinc_decisions.csv``): never given to another item."""
    path = (folder or catalogue_dir()) / "verification" / "loinc_decisions.csv"
    if not path.exists():
        return set()
    return {int(r["retired_local_id"]) for r in _read(path) if (r.get("retired_local_id") or "").strip().isdigit()}


def _item(r: dict[str, str]) -> Item:
    loinc = (r.get("loinc") or "").strip()
    local = (r.get("omop_concept_id") or "").strip()
    comps = (r.get("components") or "").strip()
    return Item(
        id=r["id"].strip(),
        names={
            "en": r["name_en"].strip(),
            "ja": (r.get("name_ja") or "").strip(),
            "zh-TW": (r.get("name_zh_tw") or "").strip(),
        },
        specialties=tuple(s.strip() for s in (r.get("specialties") or "").split(";") if s.strip()),
        item_type=(r.get("item_type") or "").strip(),
        value_type=(r.get("value_type") or "").strip(),
        unit=(r.get("unit_ucum") or "").strip(),
        loinc="" if loinc == "local" else loinc,
        local_id=int(local) if local.isdigit() else None,
        storable=(r.get("storable") or "").strip(),
        documented_as=(r.get("documented_as") or "").strip(),
        criterion_phrasing=(r.get("criterion_phrasing") or "").strip(),
        extraction_hint=(r.get("extraction_hint") or "").strip(),
        verified=(r.get("verified") or "").strip() == "yes",
        code_fit=(r.get("code_fit") or "").strip(),
        may_exclude=(r.get("may_exclude") or "").strip() == "yes",
        components=tuple(c.strip() for c in comps.split(";") if re.fullmatch(r"[a-z]+\.[a-z0-9_]+", c.strip())),
    )


def check(rows: Iterable[Item], retired: set[int]) -> list[str]:
    """Every broken id rule, one line each (empty: the file may be loaded)."""
    problems: list[str] = []
    seen: set[str] = set()
    used: set[int] = set()
    last = 0
    for it in rows:
        if not it.id or it.id in seen:
            problems.append(f"{it.id or '(blank)'}: item id missing or given twice")
        seen.add(it.id)
        if it.storable not in STORABLE:
            problems.append(f"{it.id}: storable {it.storable!r} is not one of {', '.join(STORABLE)}")
        if it.loinc:
            if not _LOINC.match(it.loinc):
                problems.append(f"{it.id}: {it.loinc!r} is not a LOINC code")
            if it.local_id is not None:
                problems.append(f"{it.id}: a LOINC item has no local id ({it.local_id})")
            continue
        if it.local_id is None:
            problems.append(f"{it.id}: a local item needs its concept id")
            continue
        if not BAND_FIRST <= it.local_id <= BAND_LAST:
            problems.append(f"{it.id}: {it.local_id} is outside the catalogue band {BAND_FIRST}-{BAND_LAST}")
        if it.local_id in retired:
            problems.append(f"{it.id}: {it.local_id} was retired by a LOINC adoption and is never reused")
        if it.local_id in used:
            problems.append(f"{it.id}: {it.local_id} is given to two items")
        elif it.local_id <= last:
            problems.append(f"{it.id}: {it.local_id} is out of file order (rows are appended, never renumbered)")
        used.add(it.local_id)
        last = max(last, it.local_id)
    return problems


def read(folder: Path | None = None) -> list[Item]:
    """The items of ``folder`` (the shipped catalogue by default), checked; :class:`CatalogueError` otherwise."""
    folder = folder or catalogue_dir()
    rows = [_item(r) for r in _read(folder / "items.csv")]
    problems = check(rows, retired_ids(folder))
    if problems:
        raise CatalogueError(problems)
    return rows


@lru_cache(maxsize=4)
def _cached(folder: str, mtime: float) -> tuple[Item, ...]:
    return tuple(read(Path(folder)))


def items(folder: Path | None = None) -> tuple[Item, ...]:
    """:func:`read`, cached until ``items.csv`` changes."""
    folder = folder or catalogue_dir()
    return _cached(str(folder), (folder / "items.csv").stat().st_mtime)


def specialties(folder: Path | None = None) -> list[dict[str, str]]:
    """``specialties.csv``: id and the three names, in file order."""
    folder = folder or catalogue_dir()
    return [
        {"id": r["specialty_id"], "en": r["name_en"], "ja": r["name_ja"], "zh-TW": r["name_zh_tw"]}
        for r in _read(folder / "specialties.csv")
    ]


# ------------------------------------------------------------------------------------------------ storable gate
def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s\-_/()（）:：,、]+", " ", t).strip()


def _aliases(it: Item) -> set[str]:
    """Names a chart may use for an instrument: its names and the leading word of the English name (``MMSE``)."""
    out = {_norm(n) for n in it.names.values() if n}
    head = it.names["en"].split(" ")[0]
    if len(head) >= 3 and re.search(r"[A-Z]{2}", head):  # an acronym: MMSE, MoCA, PANSS, MDS-UPDRS
        out.add(_norm(head))
    return out


def refused_fact(term: str, code: str = "", folder: Path | None = None) -> Item | None:
    """The score-only instrument (``storable = score``) whose item answer ``term`` names, or None.

    ``term`` is read against every item's names (and an English acronym, ``MMSE``): a term that is an item's name, or
    the start of one (``MDS-UPDRS Part III``), is that item and is kept; a term that is a score-only instrument's name
    followed by more than a total or a number (``MMSE orientation``) is a part of it and is refused; so is a listed
    component of a score-only instrument, by name or by its LOINC ``code``."""
    t = _norm(term)
    if not t:
        return None
    all_items = items(folder)
    by_id = {i.id: i for i in all_items}
    names = [(a, it) for it in all_items for a in _aliases(it)]
    if any(a.startswith(t) for a, _ in names):
        part = next(it for a, it in names if a.startswith(t))
        for owner in all_items:  # a named component of an instrument whose items may not be kept
            if part.id in owner.components and not owner.keeps_items and not part.keeps_items:
                return owner
        return None
    if code:
        for owner in all_items:
            for comp in owner.components:
                c = by_id.get(comp)
                if c and c.loinc == code and not owner.keeps_items and not c.keeps_items:
                    return owner
    best = max((a for a, _ in names if t.startswith(a + " ")), key=len, default=None)
    if best is None:
        return None
    it = next(i for a, i in names if a == best)
    if it.keeps_items:
        return None
    rest = re.sub(r"[0-9.]+|点|分|points?|pts?", " ", t[len(best) + 1 :])
    rest = re.sub(r"\s+", " ", rest).strip()
    return None if rest in _TOTAL_WORDS else it


# ------------------------------------------------------------------------------------------------ prompt hints
def hints_block(wanted: Iterable[str] | None = None, folder: Path | None = None) -> str:
    """One line per item (``id: name; hint``) for a chart-facts prompt; ``wanted`` limits it to those ids. Items whose
    answers may not be kept say so, so the model is told not to list them."""
    keep = set(wanted) if wanted is not None else None
    lines = []
    for it in items(folder):
        if keep is not None and it.id not in keep:
            continue
        if not it.extraction_hint:
            continue
        only = "" if it.keeps_items else " (total score only; never list its item answers)"
        lines.append(f"- {it.id}: {it.names['en']}{only}. {it.extraction_hint}")
    return "\n".join(lines)
