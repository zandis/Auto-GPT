"""The MEDIS disease-name master as site set-up reads it (card 10B-22, D-1261): one view of the loaded release.

The site's release is loaded by ``adapter.licensed`` (D-137; at installation, ``sitesetup.medis_release``). The
disease table comes as ``licensed.tables()["medis"]``: one concept for each 病名交換用コード, every row of the code in
``extra["rows"]`` (deleted ones too, with their 移行先病名管理番号), the code's ICD-10 the preferred row's (empty when
its current rows disagree). The index (索引テーブル) is asked one term at a time (``TermStore.lookup_term``).
:func:`rows` and the ``lookup`` given to :func:`by_name` are the only places that know those shapes.

The answers, as lane J ruled them (D-1261):

* **Which entry.** A deleted entry (変更区分 1) is never suggested. One with a 移行先病名管理番号 stands for its
  successor, followed until a current entry (a loop, a missing successor or more than ten steps: nothing); the
  suggestion says so (method ``licensed_successor``).
* **By name.** The hospital's name is compared after NFKC, upper case, blanks removed. Order: a row's own 病名表記
  first; then the index's spellings of a disease (病名修飾語区分 1): 同義語区分 0 (the term itself), then 1 (a near
  synonym), then a misspelling or variant form (異字体区分 1 or 2), then 2 (a related term: method
  ``licensed_related``, "check it"). 同義語区分 8 (advised against) and 9 (search only) and the code ``0000`` are
  never suggested; a modifier's spelling never names a disease. Within the first group that answers, every entry
  must give one ICD-10, or nothing is suggested (no guess between diseases).
* **採択区分.** A name of 採択区分 3 is a synonym that borrows a level 1 or 2 name's exchange code: the suggestion
  shows that name (method ``licensed_synonym``: "the same as ...").
* **Hints, never filters.** 単独使用禁止区分 01 ("usually written with a modifier"), 使用分野 2 (mainly Kampo) or 4
  (mainly dental) are said in the method (``licensed_with_modifier``, ``licensed_kampo``, ``licensed_dental``).
  One method is shown: successor, then related, then synonym, then these hints. 保険請求外区分 (billing) is not read.
* **The ICD-10.** Written for comparison by ``tb_common.icd10_who.comparable`` (``E119`` -> ``E11.9``; a trailing
  sub-classification letter left out; ``A99-9`` and empty give none) and taken only when the ICD-10-CM list holds
  that exact code (D-130). Otherwise NO suggestion: the local code stays unmapped, its records unknown, never another
  disease's code. The 複数分類コード is never taken as the entry's code: its codes ride beside the suggestion as
  ``also`` (written by the same function), shown on the local codes page as "also classified as".
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from tb_common.icd10_who import comparable

DELETED = "1"
MAX_HOPS = 10  # successors followed at most (a longer chain is a damaged release: no suggestion)
NO_TERM = "0000"  # the index's 対応用語コード of no current term


@dataclass(frozen=True)
class Entry:
    exchange: str  # 病名交換用コード
    number: str  # 病名管理番号
    name: str  # 病名表記
    change: str  # 変更区分: 0 unchanged, 1 deleted, 3 new, 5 changed
    icd10: str  # ＩＣＤ１０‐２０１３ as the release writes it
    successor: str = ""  # 移行先病名管理番号
    adoption: str = ""  # 採択区分: 1, 2 own the code; 3 a synonym that borrows it
    field: str = ""  # 使用分野: 1 general, 2 mainly Kampo, 4 mainly dental
    no_solo: str = ""  # 単独使用禁止区分: 01 usually with a modifier
    multi_class: str = ""  # ＩＣＤ１０‐２０１３複数分類コード: further ICD-10 codes of the same name

    @property
    def current(self) -> bool:
        return self.change != DELETED


@dataclass(frozen=True)
class Master:
    by_number: dict[str, Entry]
    by_exchange: dict[str, list[Entry]]
    by_name: dict[str, list[Entry]]
    icd_of: dict[str, str]  # the exchange code's ICD-10 as the concept gives it ("" when its rows disagree)


def key(text: str) -> str:
    """A name as it is matched: NFKC, upper case, blanks removed."""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", text or "")).upper()


def _extra(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("extra") or "{}"
    try:
        got = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError):
        return {}
    return got if isinstance(got, dict) else {}


def rows(tables: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> Master | None:
    """The loaded master, or None when no disease table is loaded."""
    diseases = tables.get("medis") or {}
    if not diseases:
        return None
    by_number: dict[str, Entry] = {}
    by_exchange: dict[str, list[Entry]] = {}
    by_name: dict[str, list[Entry]] = {}
    icd_of: dict[str, str] = {}
    for code, concept in diseases.items():
        x = _extra(concept)
        members = x.get("rows")
        if not isinstance(members, list):  # a release loaded one row per code: that row
            members = [{"no": x.get("management_no", ""), "name": concept.get("display", ""),
                        "icd": concept.get("target_code", ""), **x}]  # fmt: skip
        ex = str(code).upper()
        icd_of[ex] = str(concept.get("target_code") or "")
        for m in members:
            e = Entry(ex, str(m.get("no") or ""), str(m.get("name") or ""), str(m.get("change") or "").strip(),
                      str(m.get("icd") or ""), str(m.get("successor") or "").strip(), str(m.get("adoption") or ""),
                      str(m.get("field") or ""), str(m.get("no_solo") or ""),
                      str(m.get("multi_class") or ""))  # fmt: skip
            if e.number:
                by_number[e.number] = e
            by_exchange.setdefault(ex, []).append(e)
            if e.name:
                by_name.setdefault(key(e.name), []).append(e)
    return Master(by_number, by_exchange, by_name, icd_of)


def resolve(m: Master, e: Entry) -> Entry | None:
    """The current entry ``e`` stands for: itself, or its successor's (followed); None when there is none."""
    seen: set[str] = set()
    for _ in range(MAX_HOPS):
        if e.current:
            return e
        if not e.successor or e.successor in seen:
            return None
        seen.add(e.successor)
        nxt = m.by_number.get(e.successor)
        if nxt is None:
            return None
        e = nxt
    return None


@lru_cache(maxsize=1)
def _cm() -> frozenset[str]:
    from adapter.validate.jpcore import _icd10cm

    return _icd10cm()


def icd10cm(m: Master, e: Entry) -> str:
    """The ICD-10-CM code of a current entry: its exchange code's ICD-10 (none when the code's rows disagree),
    written for comparison, when the ICD-10-CM list holds it; else "" (D-130)."""
    code = comparable(m.icd_of.get(e.exchange, e.icd10))
    return code if code and code in _cm() else ""


def _preferred(m: Master, e: Entry) -> Entry:
    """The level 1 or 2 entry an entry's exchange code belongs to (itself when it is one)."""
    current = [x for x in m.by_exchange.get(e.exchange, []) if x.current]
    owners = sorted(current, key=lambda x: (x.adoption if x.adoption.isdigit() else "9", x.number))
    return owners[0] if owners else e


def suggestion(m: Master, entries: list[Entry], related: bool = False) -> dict[str, Any]:
    """``{system, code, display, method, confidence[, replaced][, also]}`` for the entries one group of a local code or
    name points at, or ``{}`` (no current entry, several diseases, no ICD-10, or one the ICD-10-CM list lacks)."""
    got = [(r, e) for e in entries if (r := resolve(m, e)) is not None]
    if not got:
        return {}
    codes = {icd10cm(m, r) for r, _e in got}
    if len(codes) != 1 or not next(iter(codes)):
        return {}
    got.sort(key=lambda p: (not p[1].current, p[1].adoption or "9", p[0].number))
    r, came = got[0]
    owner = _preferred(m, r)
    out: dict[str, Any] = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": next(iter(codes)),
                           "display": owner.name, "method": "licensed",
                           "confidence": "0.80" if related else "1.00"}  # fmt: skip
    also = [c for c in (comparable(x) for x in re.split(r"[^0-9A-Za-z-]+", r.multi_class)) if c and c != out["code"]]
    if also:  # shown as "also classified as"; never the suggested code (D-1261)
        out["also"] = also
    if came is not r:
        out |= {"method": "licensed_successor", "replaced": came.number}
    elif related:
        out["method"] = "licensed_related"
    elif r.adoption == "3" and owner is not r:
        out["method"] = "licensed_synonym"
    elif r.no_solo == "01":
        out["method"] = "licensed_with_modifier"
    elif r.field in ("2", "4"):
        out["method"] = {"2": "licensed_kampo", "4": "licensed_dental"}[r.field]
    return out


def by_code(m: Master, exchange: str) -> dict[str, Any]:
    """A 病名交換用コード: its current rows; a code whose every row is deleted, their successors."""
    entries = m.by_exchange.get(exchange.strip().upper(), [])
    return suggestion(m, [e for e in entries if e.current] or entries)


def _index_rank(row: Mapping[str, Any]) -> int | None:
    """The group of an index row (lower first), or None when it is never suggested."""
    if str(row.get("target_kind") or "") != "1" or str(row.get("code") or "") in ("", NO_TERM):
        return None
    synonym, variant = str(row.get("synonym") or ""), str(row.get("variant") or "")
    if synonym in ("8", "9"):
        return None
    if variant in ("1", "2"):
        return 2
    return {"0": 0, "1": 1, "2": 3}.get(synonym)


def by_name(m: Master, name: str, lookup: Callable[[str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """A local disease name: the 病名表記 first, then the index (``lookup(term)``: ``TermStore.lookup_term``)."""
    k = key(name)
    if not k:
        return {}
    own = m.by_name.get(k, [])
    if own:
        return suggestion(m, own)
    if lookup is None:
        return {}
    groups: dict[int, list[Entry]] = {}
    for row in lookup(unicodedata.normalize("NFKC", name).strip().upper()):
        rank = _index_rank(row)
        if rank is not None:
            groups.setdefault(rank, []).extend(m.by_exchange.get(str(row["code"]).upper(), []))
    for rank in sorted(groups):
        if groups[rank]:
            return suggestion(m, groups[rank], related=rank == 3)
    return {}
