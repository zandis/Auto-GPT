"""The code systems the box carries, loaded into the FHIR store (V-18, D-1182; the owner's ruling on #639).

At install, and at each update, every code system the box ships (ICD-10-CM, LOINC, the NHI order codes, the
department system, ATC) and lane M's mapping tables (as ``ConceptMap``) go into the FHIR store, each one only where its
licence lets the box carry it:

* a **shipped** table (``services/criteria_compiler/terminology/*.parquet``, the mapping CSVs) when its row of
  ``docs/licences/register.csv`` is ``cleared``, ``own-work`` or ``synthetic``;
* a table **loaded at install** (``TB_TERMINOLOGY_DIR``, ``terminology.installed``) that its manifest line vouches for
  (a licensed one names who accepted the licence, D-1114). It takes the place of the shipped table of its system.

A system that is missing, refused or not allowed is not loaded: it is one warning and one line of ``poc-stops.jsonl``
(``--deploy``), and the run goes on (exit 0). Each system is one resource, ``tb-<key>``, with a name, a version
(``FY2026+<sha 8>``) and the sha256 of its content (``identifier``). An update writes the new content over it, naming
the version it replaces (``replaces``: that version and its history id). The store keeps every earlier version in the
resource's history, so ``rollback KEY`` writes the one it replaced back. One resource per system: the store answers
``$lookup`` and ``$validate-code`` from one current version of each url, which several resources of one url left
ambiguous (it kept answering from an older one).

    python -m tools.fhir_codesystems load [--fhir URL] [--deploy DIR]   # install and the manual update: one command
    python -m tools.fhir_codesystems status [--json]                    # each system's active version (the doctor)
    python -m tools.fhir_codesystems rollback KEY                       # back to the version the active one replaced

Offline: reads only files on the box and the FHIR store; synthetic or public data only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
TERM = ROOT / "services/criteria_compiler/terminology"
MAPPING = ROOT / "services/adapter/mapping"
TB = "https://trialbox.local/fhir"
TAG = {"system": f"{TB}/CodeSystem/loaded-by", "code": "fhir_codesystems"}
SHA_SYSTEM = f"{TB}/sid/content-sha256"
REPLACES = f"{TB}/StructureDefinition/replaces"
CARRIED = frozenset({"cleared", "own-work", "synthetic"})  # a register status that lets the box carry the content
BY = "fhir_codesystems"
ICD10CM, LOINC, ATC = "http://hl7.org/fhir/sid/icd-10-cm", "http://loinc.org", "http://www.whocc.no/atc"
ICD10_WHO, PCS = "http://hl7.org/fhir/sid/icd-10", "http://www.cms.gov/Medicare/Coding/ICD10"
NHI_ORDER, DEPARTMENT = f"{TB}/CodeSystem/nhi-order", f"{TB}/CodeSystem/department"


@dataclass(frozen=True)
class Source:
    """One code system or mapping table the box may carry."""

    key: str
    kind: str  # CodeSystem or ConceptMap
    url: str  # the system (CodeSystem) or the map's own url (ConceptMap)
    title: str
    path: str  # repository-relative: the file the licence register row names
    reader: Callable[[Path], list[dict[str, str]]]
    loaded: str = ""  # the table loaded at install that takes its place (terminology.installed)
    hierarchy: bool = False  # ICD-10-CM: a code's parent is its longest listed prefix
    source: str = ""  # ConceptMap: the source system
    target: str = ""  # ConceptMap: the target system


def _parquet(path: Path) -> list[dict[str, str]]:
    import pyarrow.parquet as pq

    return [{"code": str(r["code"]), "display": str(r.get("display") or "")}
            for r in pq.read_table(path, columns=None, use_threads=False).to_pylist() if r.get("code")]  # fmt: skip


def _csv(src: str, dst: str, disp: str) -> Callable[[Path], list[dict[str, str]]]:
    def read(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if (r.get(src) or "").strip() and (r.get(dst) or "").strip()]
        return [
            {"code": r[src].strip(), "target": r[dst].strip(), "display": (r.get(disp) or "").strip()} for r in rows
        ]

    return read


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


SOURCES: tuple[Source, ...] = (
    Source(
        "icd10cm", "CodeSystem", ICD10CM, "ICD-10-CM", _rel(TERM / "icd10cm_full.parquet"), _parquet, hierarchy=True
    ),
    Source("loinc", "CodeSystem", LOINC, "LOINC", _rel(TERM / "loinc_tw.parquet"), _parquet, loaded="loinc_table"),
    Source("atc", "CodeSystem", ATC, "ATC", _rel(TERM / "atc.parquet"), _parquet, loaded="atc_index"),
    Source(
        "nhi-order",
        "CodeSystem",
        NHI_ORDER,
        "NHI order codes",
        _rel(TERM / "nhi_order.parquet"),
        _parquet,
        loaded="nhi_service_list",
    ),
    Source("department", "CodeSystem", DEPARTMENT, "Departments", _rel(TERM / "department.parquet"), _parquet),
    Source("icd10pcs", "CodeSystem", PCS, "ICD-10-PCS", "", _parquet, loaded="icd10pcs"),
    Source("icd10-who", "CodeSystem", ICD10_WHO, "WHO ICD-10", "", _parquet, loaded="icd10_who"),
    Source(
        "map-lab-loinc",
        "ConceptMap",
        f"{TB}/ConceptMap/lab-local-to-loinc",
        "Local lab codes to LOINC",
        _rel(MAPPING / "tw_core/lab_local_to_loinc.csv"),
        _csv("local_code", "code", "display"),
        source=f"{TB}/CodeSystem/local-lab",
        target=LOINC,
    ),
    Source(
        "map-jlac10-loinc",
        "ConceptMap",
        f"{TB}/ConceptMap/jlac10-to-loinc",
        "JLAC10 to LOINC",
        _rel(MAPPING / "jp_core/jlac10_to_loinc.csv"),
        _csv("local_code", "code", "display"),
        source=f"{TB}/CodeSystem/jlac10",
        target=LOINC,
    ),
    Source(
        "map-byomei-icd10",
        "ConceptMap",
        f"{TB}/ConceptMap/byomei-to-icd10",
        "MEDIS byomei to ICD-10",
        _rel(MAPPING / "jp_core/byomei_to_icd10.csv"),
        _csv("code", "icd10", "name"),
        source=f"{TB}/CodeSystem/medis",
        target=ICD10_WHO,
    ),
    Source(
        "map-yj-atc",
        "ConceptMap",
        f"{TB}/ConceptMap/yj-to-atc",
        "YJ codes to ATC",
        _rel(MAPPING / "jp_core/yj_to_atc.csv"),
        _csv("yj_code", "atc", "name"),
        source=f"{TB}/CodeSystem/yj",
        target=ATC,
    ),
)


@dataclass
class Outcome:
    key: str
    state: str  # loaded, unchanged, skipped
    detail: str
    id: str = ""


def register_status(path: str, rows: Iterable[Any] | None = None) -> tuple[str, str]:
    """``(row id, status)`` of the licence register row naming ``path``; ``("", "")`` when no row names it."""
    if rows is None:
        from tools.licence_register import load

        rows = load()
    for r in rows:
        if any(path == p or fnmatch(path, p) for p in r.paths):
            return r.id, r.status
    return "", ""


def content(src: Source, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The concepts (CodeSystem) or the map's elements (ConceptMap), sorted, as the resource carries them."""
    if src.kind == "ConceptMap":
        return [{"code": r["code"], **({"display": r["display"]} if r["display"] else {}),
                 "target": [{"code": r["target"], "equivalence": "equivalent"}]}
                for r in sorted(rows, key=lambda r: (r["code"], r["target"]))]  # fmt: skip
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["code"], r["display"])
    flat = [{"code": c, **({"display": d} if d else {})} for c, d in sorted(seen.items())]
    return nest(flat) if src.hierarchy else flat


def nest(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ICD-10-CM's hierarchy from its codes: a code's parent is its longest proper prefix that is listed (``M10.0``
    under ``M10``, ``M10.00`` under ``M10.0``); a code with none is a root."""
    by = {c["code"]: {**c} for c in flat}
    roots: list[dict[str, Any]] = []
    for code in sorted(by):
        parent = None
        p = code
        while len(p) > 1 and parent is None:
            p = p[:-1].rstrip(".")
            parent = by.get(p)
        if parent:
            # the parent also as the concept's own property: $lookup gives it without the store's full-text index,
            # which hierarchy operations ($subsumes) need and the deployed store does not run
            by[code]["property"] = [{"code": "parent", "valueCode": parent["code"]}]
        (parent.setdefault("concept", []) if parent else roots).append(by[code])
    return roots


def sha(src: Source, items: list[dict[str, Any]], version: str) -> str:
    body = json.dumps({"url": src.url, "version": version, "items": items}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def resource(src: Source, items: list[dict[str, Any]], version: str, origin: str,
             replaces: tuple[str, str] = ("", "")) -> dict[str, Any]:  # fmt: skip
    digest = sha(src, items, version)
    rid = f"tb-{src.key}"
    res: dict[str, Any] = {
        "resourceType": src.kind,
        "id": rid,
        "meta": {"tag": [dict(TAG)]},
        "url": src.url,
        "identifier": [{"system": SHA_SYSTEM, "value": digest}]
        if src.kind == "CodeSystem"
        else {"system": SHA_SYSTEM, "value": digest},
        # the content's hash makes each update's version its own ("FY2026+4e43519a")
        "version": f"{version}+{digest[:8]}",
        "name": "".join(ch for ch in src.title.title() if ch.isalnum()),
        "title": src.title,
        "status": "active",
        "description": f"Loaded by TrialBox from {origin}",
    }
    if replaces[0]:
        # the version this one replaces and its history id (``_history/<n>``): where a rollback goes back to
        res["extension"] = [{"url": REPLACES, "valueString": f"{replaces[0]}|{replaces[1]}"}]
    if src.kind == "CodeSystem":
        res.update({"content": "complete", "count": count(items), "concept": items})
        if src.hierarchy:
            res["hierarchyMeaning"] = "is-a"
            res["property"] = [{"code": "parent", "uri": "http://hl7.org/fhir/concept-properties#parent",
                                "type": "code", "description": "the code's parent in the hierarchy"}]  # fmt: skip
    else:
        res["group"] = [{"source": src.source, "target": src.target, "element": items}]
    return res


def count(items: list[dict[str, Any]]) -> int:
    return sum(1 + count(c.get("concept") or []) for c in items)


class Store:
    """The FHIR store, for the resources this tool loaded (tagged ``loaded-by|fhir_codesystems``)."""

    def __init__(self, base: str, client: httpx.Client | None = None) -> None:
        self.base = base.rstrip("/")
        self.http = client or httpx.Client(timeout=600.0)

    def put(self, res: dict[str, Any]) -> None:
        r = self.http.put(f"{self.base}/{res['resourceType']}/{res['id']}", json=res,
                          headers={"Content-Type": "application/fhir+json"})  # fmt: skip
        if r.status_code >= 400:
            raise RuntimeError(f"PUT {res['resourceType']}/{res['id']}: HTTP {r.status_code} {r.text[:900]}")

    def get(self, kind: str, rid: str, summary: bool = False) -> dict[str, Any] | None:
        """The resource, or without its content (``summary``: no concepts or elements)."""
        params = {"_elements": "id,url,version,status,identifier,extension,title,count,meta"} if summary else None
        r = self.http.get(f"{self.base}/{kind}/{rid}", params=params, headers={"Cache-Control": "no-cache"})
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
        return r.json()

    def answers(self, system: str, code: str) -> str:
        """The version the store answers ``$lookup`` of ``code`` from; empty while it has not stored the code."""
        r = self.http.get(f"{self.base}/CodeSystem/$lookup", params={"system": system, "code": code})
        if r.status_code >= 400:
            return ""
        return next((str(p.get("valueString") or "") for p in r.json().get("parameter") or []
                     if p.get("name") == "version"), "")  # fmt: skip

    def history(self, kind: str, rid: str, vid: str) -> dict[str, Any] | None:
        r = self.http.get(f"{self.base}/{kind}/{rid}/_history/{vid}")
        if r.status_code in (404, 410):
            return None
        r.raise_for_status()
        return r.json()


def digest_of(res: dict[str, Any]) -> str:
    ident = res.get("identifier")
    ident = ident[0] if isinstance(ident, list) and ident else ident
    return str((ident or {}).get("value") or "")


def replaced(res: dict[str, Any]) -> tuple[str, str]:
    """``(version, history id)`` this resource's content replaced; ``("", "")`` for a first load."""
    v = next((str(e.get("valueString")) for e in res.get("extension") or [] if e.get("url") == REPLACES), "")
    version, _, vid = v.rpartition("|") if "|" in v else (v, "", "")
    return version, vid


def pick(src: Source, terminology: Path, register: list[Any] | None) -> tuple[list[dict[str, str]], str, str] | str:
    """``(rows, version, origin)`` of what the box may carry for ``src``, or why nothing is carried."""
    if src.loaded:
        from criteria_compiler.terminology import installed as inst

        try:
            rows = inst.read_table(terminology, src.loaded)
        except inst.TerminologyRefused as exc:
            rows, refused = None, str(exc)
        else:
            refused = ""
        if rows:
            line = inst.manifest(terminology)["tables"].get(src.loaded) or {}
            return ([{"code": str(r.get("code") or r.get("nhi_code") or ""), "display": str(r.get("display") or
                      r.get("name") or "")} for r in rows if r.get("code") or r.get("nhi_code")],
                    str(line.get("version") or "loaded"), f"{src.loaded}, loaded at install")  # fmt: skip
        if refused and not src.path:
            return f"the table loaded at install was refused: {refused}"
    if not src.path:
        return "not loaded at install (the site's own copy; nothing ships)"
    row, status = register_status(src.path, register)
    if status not in CARRIED:
        return (f"its licence register row {row or '(none)'} is {status or 'missing'}: the box may not carry it "
                f"(only {', '.join(sorted(CARRIED))})")  # fmt: skip
    path = ROOT / src.path
    if not path.is_file():
        return f"{src.path} is missing"
    words = next((str(r.raw.get("version") or "") for r in (register or _register()) if r.id == row), "").split()
    first = words[0].strip(",;()") if words else ""
    version = first if any(ch.isdigit() for ch in first) else "shipped"  # the register's prose is not a version
    return src.reader(path), version, f"{src.path} (register row {row})"


def _register() -> list[Any]:
    from tools.licence_register import load

    return load()


def late_codes(items: list[dict[str, Any]], n: int = 400) -> list[str]:
    """The codes the store stores last, last first: the tail of the concepts in the order they were sent (it stores a
    large system's concepts in the background, in that order)."""
    order: list[str] = []
    stack = list(reversed(items))
    while stack:
        c = stack.pop()
        order.append(str(c["code"]))
        stack.extend(reversed(c.get("concept") or []))
    return order[::-1][:n]


STORE_RATE = 1000.0  # concepts the store stored a second, in the background (HAPI 8.12 on Postgres, 98,186 in 105 s)


def wait_stored(store: Store, src: Source, version: str, items: list[dict[str, Any]], seconds: float,
                step: float = 5.0, sleep: Callable[[float], None] | None = None) -> bool:  # fmt: skip
    """Until the store answers ``$lookup`` of a late code from ``version``. A "not found" it gives before it has stored
    a code is kept for minutes (its validation cache), for that code: so the first question waits for the time the
    store takes for a system of this size, and each later one asks a code not asked yet."""
    import time

    nap = sleep or time.sleep
    late = late_codes(items)
    if not late:
        return True
    end = time.monotonic() + seconds
    nap(min(count(items) / STORE_RATE, seconds))
    for code in late:
        if store.answers(src.url, code) == version:
            return True
        if time.monotonic() >= end:
            return False
        nap(step)
    return False


def load(store: Store, terminology: Path, sources: Iterable[Source] | None = None,
         register: list[Any] | None = None, wait: float = 0.0) -> list[Outcome]:  # fmt: skip
    """Load each source the box may carry; never stops for one (its outcome says why it was skipped)."""
    register = register if register is not None else _register()
    out: list[Outcome] = []
    for src in SOURCES if sources is None else sources:
        try:
            got = pick(src, terminology, register)
            if isinstance(got, str):
                out.append(Outcome(src.key, "skipped", got))
                continue
            rows, version, origin = got
            if not rows:
                out.append(Outcome(src.key, "skipped", f"{origin} holds no code"))
                continue
            items = content(src, rows)
            digest = sha(src, items, version)
            cur = store.get(src.kind, f"tb-{src.key}", summary=True)
            if cur is not None and digest_of(cur) == digest:
                out.append(Outcome(src.key, "unchanged", f"{src.title} {cur.get('version')}", cur["id"]))
                continue
            prev = (
                (str(cur.get("version") or ""), str((cur.get("meta") or {}).get("versionId") or ""))
                if cur
                else ("", "")
            )
            res = resource(src, items, version, origin, prev)
            store.put(res)
            what = f"{src.title} {res['version']} ({count(items) if src.kind == 'CodeSystem' else len(items)} entries)"
            what += f", replaces {prev[0]}" if prev[0] else ""
            if wait and src.kind == "CodeSystem" and not wait_stored(store, src, res["version"], items, wait):
                late = f"{what}: the store had not stored its codes after {wait:.0f} s; ask it nothing about it yet"
                out.append(Outcome(src.key, "skipped", late, res["id"]))
                continue
            out.append(Outcome(src.key, "loaded", what, res["id"]))
        except (httpx.HTTPError, RuntimeError, OSError, ValueError, KeyError) as exc:
            out.append(Outcome(src.key, "skipped", f"{type(exc).__name__}: {str(exc)[:200]}"))
    return out


def status(store: Store) -> list[dict[str, str]]:
    """Each system's version in the store and the version it replaced, as the doctor shows it."""
    rows = []
    for src in SOURCES:
        cur = store.get(src.kind, f"tb-{src.key}", summary=True) or {}
        rows.append({"key": src.key, "title": src.title, "kind": src.kind, "version": str(cur.get("version") or ""),
                     "sha256": digest_of(cur), "id": str(cur.get("id") or ""), "replaces": replaced(cur)[0],
                     "state": "loaded" if cur else "not loaded"})  # fmt: skip
    return rows


def rollback(store: Store, key: str) -> str:
    """Write back the version the current one replaced (from the resource's history in the store)."""
    src = next((s for s in SOURCES if s.key == key), None)
    if src is None:
        raise SystemExit(f"{BY}: no code system {key!r} (one of {', '.join(s.key for s in SOURCES)})")
    cur = store.get(src.kind, f"tb-{key}", summary=True)
    if cur is None:
        raise SystemExit(f"{BY}: {key} is not loaded in the FHIR store")
    version, vid = replaced(cur)
    old = store.history(src.kind, f"tb-{key}", vid) if vid else None
    if old is None:
        raise SystemExit(f"{BY}: {key} {cur.get('version')} replaced nothing kept: nothing to roll back to")
    old["meta"] = {"tag": [dict(TAG)]}
    store.put(old)
    return f"{key}: {version} is back in place of {cur.get('version')}"


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import load_env

    p = argparse.ArgumentParser(prog="python -m tools.fhir_codesystems", description=__doc__.split("\n")[0])
    p.add_argument("--fhir", default="", help="the FHIR store's base URL (default: the settings' fhir_base_url)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ld = sub.add_parser("load", help="load every code system the box may carry (install, manual update)")
    ld.add_argument("--terminology", default="", help="TB_TERMINOLOGY_DIR (default: the loader's own)")
    ld.add_argument("--deploy", default="", help="the deploy folder: a skipped system is a line of poc-stops.jsonl")
    ld.add_argument("--wait", type=float, default=900.0, help="seconds to wait for the store to store each system")
    st = sub.add_parser("status", help="each system's active version")
    st.add_argument("--json", action="store_true")
    rb = sub.add_parser("rollback", help="back to the version the active one replaced")
    rb.add_argument("key")
    a = p.parse_args(argv)
    store = Store(a.fhir or load_env().fhir_base_url)
    if a.cmd == "status":
        rows = status(store)
        if a.json:
            print(json.dumps(rows, indent=1))
        for r in rows if not a.json else []:
            print(f"{r['key']}: {r['state']} {r['version']} {r['sha256'][:12]}".rstrip())
        return 0
    if a.cmd == "rollback":
        print(rollback(store, a.key))
        return 0
    from criteria_compiler.terminology import installed as inst

    where = Path(a.terminology) if a.terminology else inst.installed_dir()
    for o in load(store, where, wait=a.wait):
        if o.state == "skipped":
            print(f"{BY}: warning: {o.key} not loaded into the FHIR store: {o.detail}", file=sys.stderr)
            if a.deploy:
                from tools.trialbox import stops

                stops.append(Path(a.deploy), f"{BY}/{o.key}", f"code system {o.key} not loaded into the FHIR store",
                             o.detail, by=BY)  # fmt: skip
        else:
            print(f"{o.key}: {o.state} {o.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
