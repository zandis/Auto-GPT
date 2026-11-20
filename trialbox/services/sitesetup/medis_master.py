"""The MEDIS disease-name master as site set-up reads it (card 10B-21, D-1261): one view of the loaded release.

The site's release is loaded by ``adapter.licensed`` (D-137; at installation, ``sitesetup.medis_release``). This
module reads the loaded tables and answers the questions site set-up asks of them:

* **Which entry is meant.** An entry deleted in the release (変更区分 ``1``) is never suggested. One with a 移行先
  病名管理番号 stands for its successor, followed until a current entry (a loop or a missing successor ends it: no
  suggestion); the suggestion then says which deleted entry it came from.
* **By name.** A local disease name is matched, after NFKC with blanks removed, to the 病名表記 of a current entry
  and to the index table's other spellings (索引用語 -> 対応用語コード, a disease's 病名管理番号), when the index is
  loaded. Two current entries of one name with different ICD-10 codes give no answer (no guess between diseases).
* **The ICD-10.** The master's ＩＣＤ１０‐２０１３ is WHO ICD-10 (2013) written without the dot (``E119``). It is
  written with the dot (``tb_common.icd10_who.dotted``) and taken only when the ICD-10-CM list holds that exact code
  (D-130). A WHO code the list does not hold (``E14.9``, ``U04.9``) and an entry with no ICD-10 give NO suggestion:
  the local code stays unmapped until a person maps it, its records unknown, never another disease's code. The
  ＩＣＤ１０‐２０１３複数分類コード (a second classification of the same entry) is never taken as the entry's code.

Rows are read from :func:`adapter.licensed.tables` (``medis``: the exchange code -> ``{display, target_code,
extra}`` with ``management_no``, ``change`` and, when the loader keeps them, ``successor``; ``medis_index``: the
index, when the loader keeps it). :func:`rows` is the one place that knows those shapes.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from tb_common.icd10_who import dotted

DELETED = "1"
MAX_HOPS = 10  # successors followed at most (a chain longer than this is a damaged release: no suggestion)


@dataclass(frozen=True)
class Entry:
    exchange: str  # 病名交換用コード
    number: str  # 病名管理番号
    name: str  # 病名表記
    change: str  # 変更区分: 0 unchanged, 1 deleted, 3 new, 5 changed
    icd10: str  # ＩＣＤ１０‐２０１３ as written in the release
    successor: str = ""  # 移行先病名管理番号

    @property
    def current(self) -> bool:
        return self.change != DELETED


@dataclass(frozen=True)
class Master:
    by_number: dict[str, Entry]
    by_exchange: dict[str, list[Entry]]
    by_name: dict[str, list[Entry]]


def key(text: str) -> str:
    """A name as it is matched: NFKC, blanks removed."""
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", text or ""))


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
    for code, row in diseases.items():
        x = _extra(row)
        e = Entry(
            exchange=str(x.get("exchange_code") or code),
            number=str(x.get("management_no") or ""),
            name=str(row.get("display") or ""),
            change=str(x.get("change") or "").strip(),
            icd10=str(row.get("target_code") or ""),
            successor=str(x.get("successor") or "").strip(),
        )
        if e.number:
            by_number[e.number] = e
        by_exchange.setdefault(e.exchange.upper(), []).append(e)
        if e.name:
            by_name.setdefault(key(e.name), []).append(e)
    for row in (tables.get("medis_index") or {}).values():  # another spelling -> the disease it names
        x = _extra(row)
        if str(x.get("kind") or "1") != "1":  # 病名修飾語区分: only a disease's spelling, never a modifier's
            continue
        target = by_number.get(str(row.get("target_code") or x.get("number") or ""))
        term = str(x.get("term") or row.get("display") or "")
        if target is not None and term:
            names = by_name.setdefault(key(term), [])
            if target not in names:
                names.append(target)
    return Master(by_number, by_exchange, by_name)


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


def icd10cm(e: Entry) -> str:
    """The entry's ICD-10 as an ICD-10-CM code, or "" when it has none or ICD-10-CM does not hold it (D-130)."""
    code = dotted(e.icd10)
    return code if code and code in _cm() else ""


def _one(m: Master, entries: list[Entry]) -> tuple[Entry, Entry] | None:
    """The one current entry a list of entries stands for, with the entry it came from; None when they name
    several diseases (different ICD-10 codes) or none."""
    got = [(r, e) for e in entries if (r := resolve(m, e)) is not None]
    if not got or len({dotted(r.icd10) for r, _ in got}) != 1:
        return None
    got.sort(key=lambda p: (not p[1].current, p[0].number))
    return got[0]


def suggestion(m: Master, entries: list[Entry], display: str = "") -> dict[str, str]:
    """``{system, code, display, method, confidence[, replaced]}`` for the entries a local code or name points at,
    or ``{}`` (no current entry, several diseases, no ICD-10, or an ICD-10 the ICD-10-CM list lacks)."""
    pick = _one(m, entries)
    if pick is None:
        return {}
    r, came = pick
    code = icd10cm(r)
    if not code:
        return {}
    out = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": code, "display": r.name or display,
           "method": "licensed", "confidence": "1.00"}  # fmt: skip
    if came is not r:
        out["replaced"] = came.number  # a deleted entry: its successor is suggested, and the page says so
        out["method"] = "licensed_successor"
    return out


def by_code(m: Master, exchange: str) -> dict[str, str]:
    return suggestion(m, m.by_exchange.get(exchange.strip().upper(), []))


def by_name(m: Master, name: str) -> dict[str, str]:
    return suggestion(m, m.by_name.get(key(name), []))
