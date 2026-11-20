"""The MEDIS disease-name master as site set-up reads it (card 10B-22, D-1261): one view of the loaded release.

The site's release is loaded by ``adapter.licensed`` (D-137; at installation, ``sitesetup.medis_release``). The
disease table comes as ``licensed.tables()["medis"]``: one concept for each 病名交換用コード, every row of the code in
``extra["rows"]`` (deleted ones too, with their 移行先病名管理番号), the code's ICD-10 the preferred row's (empty when
its current rows disagree). The index (索引テーブル) is asked one term at a time (``TermStore.lookup_term``).
:func:`rows` and the ``lookup`` given to :func:`by_name` are the only places that know those shapes.

The answers, as lane J ruled them (D-1261):

* **The target (H1).** The master's ICD-10 is WHO ICD-10 (2013), written for comparison by
  ``tb_common.icd10_who.comparable`` (``E119`` -> ``E11.9``; a trailing sub-classification letter left out; ``A99-9``
  and empty give none). It is never taken for its ICD-10-CM namesake: the target is the same-numbered ICD-10-CM code
  only when the list holds it as a billable code (never a category with codes below it), and the page shows the WHO
  code, the ICD-10-CM code's own title and "check that it is the same disease"; a three-character code is the
  family. Otherwise NO suggestion (D-130): the local code stays unmapped, never another disease's code. Every
  confidence is at most 0.80 (:data:`CONFIDENCE`): a person confirms every suggestion of the master.
* **Which entry.** A deleted entry (変更区分 1) is never suggested. One with a 移行先病名管理番号 stands for its
  successor, followed until a current entry (a loop, a missing successor or :data:`MAX_HOPS` steps: nothing); the
  suggestion says so (method ``licensed_successor``).
* **By code.** A 病名交換用コード's current rows. When the hospital's name names neither a row of the code nor one of
  its index terms, the suggestion says the name differs (``licensed_name_differs``, M6).
* **By name.** Compared by the index's one key (``adapter.licensed.index_key``). Order: a row's own 病名表記 first;
  then the index's spellings of a disease (病名修飾語区分 1): 同義語区分 0, then 1 (a near synonym), then a variant
  form (異字体区分 1 or 2), then 2 (a related term, whatever its variant mark: H2). 同義語区分 8 and 9, the code
  ``0000`` and a modifier's spelling are never suggested.
* **Several diseases.** Every candidate is offered, ranked by confidence: the first is the suggestion, ``of`` their
  number and ``candidates`` the others ("one of N"), never one picked in silence. One target that several entries
  give: ``names``.
* **採択区分.** A name of 採択区分 3 borrows a level 1 or 2 name's exchange code: the suggestion shows that name and
  says the hospital's name is its synonym (``synonym``).
* **Hints, never filters.** 単独使用禁止区分 01, 使用分野 2 (Kampo) or 4 (dental) are said (``hints``).
  保険請求外区分 (billing) is not read.
* **The 複数分類コード** is never the entry's code: every one of its codes rides beside the suggestion as ``also``
  (written by the same function), shown as "also classified as".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from tb_common.icd10_who import comparable

DELETED = "1"
MAX_HOPS = 10  # successors followed at most (a longer chain is a damaged release: no suggestion)
NO_TERM = "0000"  # the index's 対応用語コード of no current term
RELATED = 3  # the rank of a related term (同義語区分 2): a candidate labelled "related, check it"


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
    """A name as it is matched: the index's one key (``adapter.licensed.index_key``: NFKC, every blank removed,
    upper case), for a 病名表記 as for an index term (lane J, M1)."""
    from adapter.licensed import index_key

    return index_key(text)


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


# ------------------------------------------------------------------ the ICD-10-CM list: codes, titles, headers
@lru_cache(maxsize=1)
def _cm_titles() -> dict[str, str]:
    import pyarrow.parquet as pq
    from adapter.validate.jpcore import RULES

    path = RULES.parents[2] / "criteria_compiler" / "terminology" / "icd10cm_full.parquet"
    if not path.exists():
        return {}
    t = pq.read_table(path, columns=["code", "display"], use_threads=False)
    return dict(zip(t.column("code").to_pylist(), t.column("display").to_pylist(), strict=True))


@lru_cache(maxsize=1)
def _cm_headers() -> frozenset[str]:
    """The ICD-10-CM codes that have a code below them (a category or subcategory, not billable): never a target."""
    out: set[str] = set()
    for code in _cm_titles():
        head, _, tail = code.partition(".")
        if tail:
            out.add(head)
            out.update(f"{head}.{tail[:i]}" for i in range(1, len(tail)))
    return frozenset(out)


def cm_title(code: str) -> str:
    return _cm_titles().get(code, "")


def target(m: Master, e: Entry) -> tuple[str, str, bool]:
    """``(WHO ICD-10, ICD-10-CM target, family)`` of a current entry (D-1261, lane J ruling H1). The master's code is
    WHO ICD-10 (2013), never taken for its ICD-10-CM namesake: the target is the same-numbered ICD-10-CM code only
    when the list holds it as a billable code (never a category or subcategory with codes below it), and the page
    says it is a same-numbered code to be checked; a three-character code is the family (``family`` True). No such
    code: ``(who, "", False)``, no suggestion."""
    who = comparable(m.icd_of.get(e.exchange, e.icd10))
    if not who:
        return "", "", False
    if who in _cm_titles() and who not in _cm_headers():
        return who, who, "." not in who
    return who, "", False


def _preferred(m: Master, e: Entry) -> Entry:
    """The level 1 or 2 entry an entry's exchange code belongs to (itself when it is one)."""
    current = [x for x in m.by_exchange.get(e.exchange, []) if x.current]
    owners = sorted(current, key=lambda x: (x.adoption if x.adoption.isdigit() else "9", x.number))
    return owners[0] if owners else e


# ------------------------------------------------------------------ what a suggestion is worth (lane J, M7)
#: how a suggestion was found, from the strongest to the weakest. Every confidence is at or below the level of a
#: related term on master (0.80): a person reads and confirms every suggestion of the master (lane J ruling H1 c)
CODE, NAME, INDEX_TERM, NEAR_SYNONYM, VARIANT, SUCCESSOR, RELATED_TERM, NAME_DIFFERS = (
    "licensed_code", "licensed_name", "licensed_index", "licensed_near_synonym", "licensed_variant",
    "licensed_successor", "licensed_related", "licensed_name_differs",
)  # fmt: skip
CONFIDENCE = {CODE: 0.80, NAME: 0.78, INDEX_TERM: 0.76, NEAR_SYNONYM: 0.72, VARIANT: 0.68, SUCCESSOR: 0.64,
              RELATED_TERM: 0.55, NAME_DIFFERS: 0.50}  # fmt: skip
#: the rank of an index row's group (lower first) and the method it gives
INDEX_GROUPS = {0: INDEX_TERM, 1: NEAR_SYNONYM, 2: VARIANT}
RELATED = 3  # the rank of a related term (同義語区分 2)
HINTS = {"01": "with_modifier"}  # 単独使用禁止区分
FIELDS = {"2": "kampo", "4": "dental"}  # 使用分野


def _candidate(m: Master, r: Entry, came: Entry, method: str, who: str, code: str, family: bool) -> dict[str, Any]:
    """One suggested code: ``{system, code, display, method, confidence, who, cm_title, family[, replaced][, also]
    [, synonym][, hints]}``."""
    owner = _preferred(m, r)
    if came is not r:
        method = SUCCESSOR if CONFIDENCE[SUCCESSOR] < CONFIDENCE[method] else method
    out: dict[str, Any] = {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": code, "display": owner.name,
                           "method": method, "confidence": f"{CONFIDENCE[method]:.2f}", "who": who,
                           "cm_title": cm_title(code), "family": family}  # fmt: skip
    also = [c for c in (comparable(x) for x in re.split(r"[^0-9A-Za-z-]+", r.multi_class)) if c and c != who]
    if also:  # shown as "also classified as"; never the suggested code (D-1261)
        out["also"] = also
    if came is not r:
        out["replaced"] = came.number
    if r.adoption == "3" and owner is not r:
        out["synonym"] = True  # the hospital's name is a synonym (採択区分 3) of the name shown
    hints = [h for h in (HINTS.get(r.no_solo), FIELDS.get(r.field)) if h]
    if hints:  # never filters, only said (lane J)
        out["hints"] = hints
    return out


#: the keys of a further candidate as the set-up store keeps it (beside the first, D-1261)
CANDIDATE_KEYS = ("code", "display", "method", "who", "cm_title", "family")


def suggestion(m: Master, items: list[tuple[str, Entry]]) -> dict[str, Any]:
    """The suggestion for the entries a local code or name points at, each with the method it was found by. Every
    entry is resolved (a deleted one to its successor) and taken when it has a target (:func:`target`); one target
    is one candidate, its strongest entry. Several candidates (D-1261, lane J): all of them, ranked by confidence,
    never one picked in silence: the first is the suggestion, ``of`` their number and ``candidates`` the others. One
    target that several master entries (exchange codes) give: ``names``, their number ("one of N names"). None:
    ``{}``."""
    best: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    names: dict[str, set[str]] = {}
    for method, e in items:
        r = resolve(m, e)
        if r is None:
            continue
        who, code, family = target(m, r)
        if not code:
            continue
        c = _candidate(m, r, e, method, who, code, family)
        order = (-float(c["confidence"]), not e.current, e.adoption if e.adoption.isdigit() else "9", r.number)
        names.setdefault(code, set()).add(r.exchange)
        if code not in best or order < best[code][0]:
            best[code] = (order, c)
    ranked = [c for _o, c in sorted(best.values(), key=lambda p: p[0])]
    if not ranked:
        return {}
    out = dict(ranked[0])
    if len(names[out["code"]]) > 1:
        out["names"] = len(names[out["code"]])
    if len(ranked) > 1:
        out["of"] = len(ranked)
        out["candidates"] = [{k: c[k] for k in CANDIDATE_KEYS} for c in ranked[1:]]
    return out


def _current_or_all(entries: list[Entry]) -> list[Entry]:
    """An exchange code's current rows; its every row when all are deleted (their successors are then read)."""
    return [e for e in entries if e.current] or entries


def by_code(m: Master, exchange: str, display: str = "", lookup: Callable[[str], list[dict[str, Any]]] | None = None
            ) -> dict[str, Any]:  # fmt: skip
    """A 病名交換用コード: its current rows; a code whose every row is deleted, their successors. With the local
    ``display`` given and naming neither a row of that code nor one of its index terms, the code is a hospital's own
    code that only looks like the master's: the suggestion says the name differs (lane J, M6)."""
    entries = _current_or_all(m.by_exchange.get(exchange.strip().upper(), []))
    method = CODE
    if display.strip() and entries:
        k = key(display)
        own = any(key(e.name) == k for e in entries)
        listed = own or any(str(row.get("code") or "").upper() == exchange.strip().upper()
                            for row in (lookup(display) if lookup else ()))  # fmt: skip
        if not listed:
            method = NAME_DIFFERS
    return suggestion(m, [(method, e) for e in entries])


def _index_rank(row: Mapping[str, Any]) -> int | None:
    """The group of an index row (lower first), or None when it is never suggested. A related term (同義語区分 2)
    is related whatever its 異字体区分 (lane J, H2)."""
    if str(row.get("target_kind") or "") != "1" or str(row.get("code") or "") in ("", NO_TERM):
        return None
    synonym, variant = str(row.get("synonym") or ""), str(row.get("variant") or "")
    if synonym in ("8", "9"):
        return None
    if synonym == "2":
        return RELATED
    if variant in ("1", "2"):
        return 2
    return {"0": 0, "1": 1}.get(synonym)


def by_name(m: Master, name: str, lookup: Callable[[str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """A local disease name: the 病名表記 first; when it gives no candidate, the index (``lookup(term)``,
    ``TermStore.lookup_term``, asked by the one key :func:`key`), every usable row by its group, each exchange
    code's current rows only (a deleted row's successor is read only when every row is deleted)."""
    k = key(name)
    if not k:
        return {}
    own = suggestion(m, [(NAME, e) for e in m.by_name.get(k, [])])
    if own or lookup is None:
        return own
    items: list[tuple[str, Entry]] = []
    for row in lookup(name):
        rank = _index_rank(row)
        if rank is None:
            continue
        method = RELATED_TERM if rank == RELATED else INDEX_GROUPS[rank]
        items += [(method, e) for e in _current_or_all(m.by_exchange.get(str(row["code"]).upper(), []))]
    return suggestion(m, items)


# ------------------------------------------------------------------ what the set-up store keeps (D-1261)
#: the keys of a suggestion the store keeps beside its code, display, method and confidence (one JSON column)
DETAIL_KEYS = ("who", "cm_title", "family", "also", "replaced", "synonym", "hints", "names", "of", "candidates")


def detail_of(suggestion: Mapping[str, Any]) -> str | None:
    """A suggestion's detail as ``local_code.medis_detail`` keeps it: a JSON object, or None (not the master's)."""
    got = {k: suggestion[k] for k in DETAIL_KEYS if suggestion.get(k) not in (None, "", [], False)}
    return json.dumps(got, ensure_ascii=False, sort_keys=True) if got else None


def detail_read(raw: Any) -> dict[str, Any]:
    """The column back: ``{}`` for NULL (a row from before it) or anything that is not an object; the candidates
    kept only with a code."""
    try:
        got = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(got, dict) or not got:
        return {}
    out = {k: got[k] for k in DETAIL_KEYS if k in got}
    also = out.get("also")
    out["also"] = [str(c) for c in also if str(c).strip()] if isinstance(also, list) else []
    cands = out.get("candidates")
    cands = cands if isinstance(cands, list) else []
    out["candidates"] = [{k: c.get(k, "") for k in CANDIDATE_KEYS} for c in cands
                         if isinstance(c, dict) and c.get("code")]  # fmt: skip
    return out
