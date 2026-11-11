"""The consortium's shared code-map registry and its releases (T-316b, WS-09.1, D-419; closes CR-031's code-map part).

    python -m tools.codemap_release check REGISTRY
    python -m tools.codemap_release release REGISTRY --version 2027.1 --author A --approver B --out DIR \\
        [--key PRIVATE_PEM] [--tar] [--record]
    python -m tools.codemap_release verify PACK [--public-key PUBLIC_PEM]
    python -m tools.codemap_release load PACK [--public-key PUBLIC_PEM] [--db-url URL] [--by NAME]
    python -m tools.codemap_release status [--db-url URL]

**The registry** is a git repository hosted by the lead hospital; a map change is a reviewed pull request there.
Its layout (format ``trialbox-codemap/1``)::

    registry.json     format, name, url; ranges [{owner, first, last}] (TB-SHARED ranges, inside the registry band
                      omop.vocab.CODEMAP_MIN..CODEMAP_MAX); systems [{system, owner, kind: shared | local}] (the
                      registry's own code systems); maps [{id, name, owner}]
    concepts.csv      concept_id, system, code, name, domain, owner: the registry's shared concepts, at fixed ids in
                      their owner's range, the same on every box
    maps/<id>.csv     source_system, source_code, source_display, target_system, target_code, target_display,
                      relation (FHIR R4 ConceptMap equivalence, ``tb_common.refdata.RELATIONS``)
    releases/<version>.json   the record of every release made (``release --record`` writes it)

:func:`check` holds every rule and lists every problem: ranges inside the band and apart; a concept in its owner's
range, unique by id and by code; an id once released never renumbered and never reused (against ``releases/``); a
map's relation known, its rows unique, a source system in one map only (a load replaces a source vocabulary's map
rows); and **licences**: every code system a release names is the registry's own, or has a row in
``docs/licences/register.csv`` whose status lets it ship (``cleared``, ``own-work``, ``synthetic``). SNOMED CT
(removed), ATC (permission to ask), WHO ICD-10 and the JP masters (site-loaded) are refused, and so is a system the
register does not know.

**A release** is a refdata pack part (``trialbox-refdata-<date>-codemap-<version>``, D-140, D-170): one ``map`` source
per map, so the update bundle carries it and ``tb_common.refdata`` verifies and stores it like any pack, plus the
release record ``codemap.json`` (version, author, approver, ranges, licences, every file's sha256, the concept ids)
with the registry's concepts in ``codemap/concepts.jsonl.gz``. The author and the approver are two people. With
``--key`` the record is signed (Ed25519, ``codemap.sig``); the box's load with ``--public-key`` refuses a release
without a valid signature. Either way a file whose sha256 differs from the record is refused (a tampered file).

**Loading** (:func:`load`) puts one release into a box's OMOP vocabulary in one transaction: the shared concepts at
their fixed ids (``omop.vocab.seed_registry_concepts``), each map as the map release ``map:codemap-<id>``
(``omop.vocab_load.load_concept_map``), a map the release no longer has taken out, and the ``CODEMAP`` release row;
``omop.vocab.release`` names it. Loading the same release again changes nothing.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import sys
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omop.schema import LOCAL_MIN  # noqa: E402
from omop.vocab import CODEMAP_MAP_PREFIX, CODEMAP_MAX, CODEMAP_MIN  # noqa: E402
from tb_common import crypto, refdata  # noqa: E402

FORMAT = "trialbox-codemap/1"
RELEASE_FORMAT = "trialbox-codemap-release/1"
REGISTER = ROOT / "docs/licences/register.csv"
MAP_COLS = ("source_system", "source_code", "source_display", "target_system", "target_code", "target_display",
            "relation")  # fmt: skip
CONCEPT_COLS = ("concept_id", "system", "code", "name", "domain", "owner")
SHIPPABLE = frozenset({"cleared", "own-work", "synthetic"})  # register statuses whose codes a release may carry
# FHIR code system -> its row in docs/licences/register.csv (the systems the box knows; omop.vocab_load.SYSTEM_VOCAB)
SYSTEM_REGISTER: dict[str, str] = {
    "http://loinc.org": "loinc",
    "http://unitsofmeasure.org": "ucum",
    "http://hl7.org/fhir/sid/icd-10-cm": "icd10cm",
    "urn:tw:nhi:icd-10-cm-2014": "icd10cm-tw",
    "urn:tw:nhi:icd-10-cm-2023": "icd10cm-tw",
    "http://hl7.org/fhir/sid/icd-10": "icd10-who",
    "http://www.whocc.no/atc": "atc",
    "http://snomed.info/sct": "snomed-ct",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
    "https://trialbox.local/fhir/CodeSystem/nhi-drug": "nhi-codes",
    "https://trialbox.local/fhir/CodeSystem/nhi-order": "nhi-codes",
    "urn:tw:nhi:drug": "nhi-codes",
    "urn:oid:1.2.392.200119.4.101.6": "jp-licensed-masters",
    "urn:oid:1.2.392.200119.4.504": "jp-licensed-masters",
    "urn:oid:1.2.392.100495.20.1.73": "jp-licensed-masters",
}
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.-]{0,30}$")
RELEASE_FILE = "codemap.json"
SIGNATURE_FILE = "codemap.sig"
CONCEPTS_FILE = "codemap/concepts.jsonl.gz"


class CodemapError(ValueError):
    """A registry or a release that breaks a rule; ``problems`` lists every broken rule (one line each)."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = list(problems)
        more = f" (+{len(self.problems) - 5} more)" if len(self.problems) > 5 else ""
        super().__init__("; ".join(self.problems[:5]) + more)


@dataclass
class Registry:
    root: Path
    meta: dict[str, Any]
    concepts: list[dict[str, str]]
    maps: dict[str, list[dict[str, str]]]
    previous: list[dict[str, Any]] = field(default_factory=list)  # the release records in releases/

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or "")

    def own_systems(self) -> dict[str, dict[str, Any]]:
        return {str(s.get("system")): s for s in self.meta.get("systems") or []}


# ------------------------------------------------------------------------------------------------ the registry
def _csv(path: Path, cols: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in cols if c not in (rd.fieldnames or [])]
        if missing:
            raise CodemapError([f"{path.name}: missing columns {', '.join(missing)}"])
        return [{c: (r.get(c) or "").strip() for c in cols} for r in rd]


def read_registry(root: Path) -> Registry:
    try:
        meta = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CodemapError([f"{root}: no readable registry.json ({exc})"]) from exc
    concepts = _csv(root / "concepts.csv", CONCEPT_COLS) if (root / "concepts.csv").is_file() else []
    maps = {p.stem: _csv(p, MAP_COLS) for p in sorted((root / "maps").glob("*.csv"))}
    previous = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "releases").glob("*.json"))]
    return Registry(root, meta, concepts, maps, previous)


def register_status(path: Path = REGISTER) -> dict[str, str]:
    """``register row id -> status`` of the licence register."""
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["id"]: r["status"] for r in csv.DictReader(fh)}


def licences(reg: Registry, register: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """``system -> what covers it`` (``registry:<owner>`` or ``register:<row>``) for every code system the maps and
    concepts name, and the problems: a system with no row, or whose row does not let it ship."""
    own = reg.own_systems()
    systems = {r["system"] for r in reg.concepts}
    for rows in reg.maps.values():
        for r in rows:
            systems.add(r["source_system"])
            if r["target_system"]:
                systems.add(r["target_system"])
    out: dict[str, str] = {}
    problems: list[str] = []
    for s in sorted(systems):
        if s in own:
            out[s] = f"registry:{own[s].get('owner')}"
            continue
        row = SYSTEM_REGISTER.get(s)
        if row is None or row not in register:
            problems.append(f"code system {s}: no row in the licence register; a release carries no code it cannot "
                            "show a licence for")  # fmt: skip
            continue
        if register[row] not in SHIPPABLE:
            problems.append(f"code system {s}: licence register row {row} is {register[row]}, which may not ship")
            continue
        out[s] = f"register:{row}"
    return out, problems


def check(reg: Registry, register: Mapping[str, str] | None = None) -> list[str]:
    """Every problem of the registry, one line each (empty: it may be released)."""
    p: list[str] = []
    m = reg.meta
    if m.get("format") != FORMAT:
        p.append(f"registry.json: format {m.get('format')!r}, not {FORMAT}")
    if not NAME.match(reg.name):
        p.append(f"registry.json: name {reg.name!r} (lower case letters, digits and hyphens)")
    if not str(m.get("url") or "").strip():
        p.append("registry.json: url is empty (where the registry is hosted)")
    ranges: list[tuple[int, int, str]] = []
    for r in m.get("ranges") or []:
        try:
            first, last, owner = int(r["first"]), int(r["last"]), str(r["owner"]).strip()
        except (KeyError, TypeError, ValueError):
            p.append(f"registry.json: range {r!r} needs owner, first and last")
            continue
        if not owner or first > last or first < CODEMAP_MIN or last > CODEMAP_MAX:
            p.append(f"range {owner or '?'} {first:,}-{last:,}: not inside the registry band "
                     f"{CODEMAP_MIN:,}-{CODEMAP_MAX:,}")  # fmt: skip
            continue
        for a, b, o in ranges:
            if first <= b and a <= last:
                p.append(f"range {owner} {first:,}-{last:,} overlaps {o} {a:,}-{b:,}")
        ranges.append((first, last, owner))
    owners = {o for _, _, o in ranges}
    own = reg.own_systems()
    for s in m.get("systems") or []:
        if not s.get("system") or s.get("kind") not in ("shared", "local") or s.get("owner") not in owners:
            p.append(f"registry.json: system {s!r} needs a system URI, kind shared or local, and an owner with a range")
    declared = {str(x.get("id")): x for x in m.get("maps") or []}
    for mid, x in declared.items():
        if not NAME.match(mid) or not x.get("name") or x.get("owner") not in owners:
            p.append(f"registry.json: map {mid!r} needs an id (lower case), a name and an owner with a range")
        if mid not in reg.maps:
            p.append(f"map {mid}: no file maps/{mid}.csv")
    for mid in reg.maps:
        if mid not in declared:
            p.append(f"maps/{mid}.csv is not declared in registry.json")

    # the shared concepts
    by_id: dict[int, tuple[str, str]] = {}
    by_code: dict[tuple[str, str], int] = {}
    for i, c in enumerate(reg.concepts, start=2):
        where = f"concepts.csv line {i}"
        try:
            cid = int(c["concept_id"])
        except ValueError:
            p.append(f"{where}: concept_id {c['concept_id']!r} is not a number")
            continue
        key = (c["system"], c["code"])
        if not all((c["code"], c["name"], c["domain"])):
            p.append(f"{where}: code, name and domain are required")
        if own.get(c["system"], {}).get("kind") != "shared":
            p.append(f"{where}: system {c['system']} is not one of the registry's shared systems")
        if not any(a <= cid <= b and o == c["owner"] for a, b, o in ranges):
            p.append(f"{where}: id {cid} is not in a range of its owner {c['owner']!r}")
        if cid in by_id:
            p.append(f"{where}: id {cid} twice")
        if key in by_code:
            p.append(f"{where}: {key[0]} {key[1]} twice")
        by_id[cid], by_code[key] = key, cid
    for rec in reg.previous:  # an id once released is never renumbered nor reused
        for cid, system, code in rec.get("concept_ids") or []:
            now = by_code.get((system, code))
            if now is not None and now != cid:
                p.append(f"{system} {code}: released as {cid} in {rec.get('version')}, now {now} (never renumbered)")
            held = by_id.get(int(cid))
            if held is not None and held != (system, code):
                p.append(f"id {cid}: released as {system} {code} in {rec.get('version')}, now {held[0]} {held[1]} "
                         "(an id is never reused)")  # fmt: skip

    # the maps
    source_map: dict[str, str] = {}
    for mid, rows in reg.maps.items():
        seen: set[tuple[str, str, str, str]] = set()
        for i, r in enumerate(rows, start=2):
            where = f"maps/{mid}.csv line {i}"
            if not r["source_system"] or not r["source_code"]:
                p.append(f"{where}: source_system and source_code are required")
            if r["relation"] not in refdata.RELATIONS:
                p.append(f"{where}: relation {r['relation']!r} is not one of {', '.join(refdata.RELATIONS)}")
            elif not r["target_system"] or (r["relation"] != "unmatched" and not r["target_code"]):
                p.append(f"{where}: a {r['relation']} row needs a target (an unmatched row its target system)")
            k = (r["source_system"], r["source_code"], r["target_system"], r["target_code"])
            if k in seen:
                p.append(f"{where}: the same row twice")
            seen.add(k)
            for side in ("source", "target"):
                sys_, code = r[f"{side}_system"], r[f"{side}_code"]
                if own.get(sys_, {}).get("kind") == "shared" and code and (sys_, code) not in by_code:
                    p.append(f"{where}: {side} {sys_} {code} is not a concept in concepts.csv")
            other = source_map.setdefault(r["source_system"], mid)
            if other != mid:
                p.append(f"{where}: source system {r['source_system']} is already mapped by {other} (one map each)")
        if not rows:
            p.append(f"maps/{mid}.csv has no row")
    if not reg.maps:
        p.append("the registry has no map")
    _, lic = licences(reg, register if register is not None else register_status())
    p.extend(lic)
    return list(dict.fromkeys(p))


# ------------------------------------------------------------------------------------------------ a release
def canonical(record: Mapping[str, Any]) -> bytes:
    """The bytes the signature covers: the record as sorted, compact JSON."""
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _content_sha(concepts_sha: str, maps: Iterable[Mapping[str, Any]], version: str) -> str:
    parts = [f"version={version}", f"concepts={concepts_sha}", *sorted(f"{m['id']}={m['sha256']}" for m in maps)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _slug(version: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", version.lower()).strip("-")


def build_release(
    reg: Registry, *, version: str, author: str, approver: str, out: Path, private_key: bytes | None = None,
    register: Mapping[str, str] | None = None, today: date | None = None, record: bool = False,
) -> Path:  # fmt: skip
    """Check the registry and write one release as a refdata pack part under ``out``; returns the pack directory.
    ``record`` also writes the release record into the registry's ``releases/`` (committed with the review)."""
    reg_status = register if register is not None else register_status()
    problems = check(reg, reg_status)
    if not VERSION.match(version):
        problems.append(f"version {version!r}: letters, digits, dots and hyphens")
    if not author.strip() or not approver.strip():
        problems.append("a release names its author and its approver")
    elif author.strip().casefold() == approver.strip().casefold():
        problems.append("the approver of a release is not its author (two people)")
    if any(r.get("version") == version for r in reg.previous):
        problems.append(f"version {version} was released before: a new release takes a new version")
    if problems:
        raise CodemapError(problems)
    lic, _ = licences(reg, reg_status)
    day = today or datetime.now(UTC).date()
    pack = out / f"trialbox-refdata-{day:%Y%m%d}-codemap-{_slug(version)}"
    if pack.exists():
        shutil.rmtree(pack)
    pack.mkdir(parents=True)
    names = {(c["system"], c["code"]): c["name"] for c in reg.concepts}
    declared = {str(x["id"]): x for x in reg.meta["maps"]}
    url = str(reg.meta["url"])
    sources, maps = [], []
    for mid, rows in sorted(reg.maps.items()):
        recs = [
            {**{k: r[k] for k in MAP_COLS},
             "source_display": r["source_display"] or names.get((r["source_system"], r["source_code"]), ""),
             "target_display": r["target_display"] or names.get((r["target_system"], r["target_code"]), ""),
             "extra": {"registry": reg.name, "map": mid}}
            for r in rows
        ]  # fmt: skip
        rel = f"codemap-{mid}/map.jsonl.gz"
        n = refdata.write_jsonl_gz(pack / rel, recs)
        entry = refdata.file_entry(pack, rel, n)
        systems = sorted({r["source_system"] for r in rows} | {r["target_system"] for r in rows if r["target_system"]})
        sources.append({
            "id": f"{CODEMAP_MAP_PREFIX}{mid}", "name": f"{declared[mid]['name']} ({reg.name} {version})",
            "kind": "map", "url": url, "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "download_sha256": entry["sha256"], "version": version, "records": n,
            "licence": f"code-map registry {reg.name}: the member hospitals' own work, shared under the consortium "
                       "agreement",
            "terms": "the codes inside keep their own licences: " + "; ".join(f"{s} ({lic[s]})" for s in systems),
            "attribution": f"{reg.name} code-map registry, map {mid}, owner {declared[mid]['owner']}; authored by "
                           f"{author}, approved by {approver}",
            "distribution": "ship", "files": [entry],
        })  # fmt: skip
        maps.append({"id": mid, "name": declared[mid]["name"], "owner": declared[mid]["owner"], "path": rel,
                     "sha256": entry["sha256"], "records": n, "systems": systems})  # fmt: skip
    crecs = [{"concept_id": int(c["concept_id"]), "system": c["system"], "code": c["code"], "name": c["name"],
              "domain": c["domain"], "owner": c["owner"]} for c in reg.concepts]  # fmt: skip
    cn = refdata.write_jsonl_gz(pack / CONCEPTS_FILE, crecs)
    csha = refdata.sha256_file(pack / CONCEPTS_FILE)
    refdata.write_manifest(pack, day.isoformat(), sources)
    rec: dict[str, Any] = {
        "format": RELEASE_FORMAT,
        "registry": reg.name,
        "url": url,
        "version": version,
        "author": author.strip(),
        "approver": approver.strip(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pack_id": pack.name,
        "ranges": reg.meta["ranges"],
        "systems": reg.meta.get("systems") or [],
        "licences": lic,
        "concepts": {"path": CONCEPTS_FILE, "sha256": csha, "records": cn},
        "maps": maps,
        "concept_ids": sorted([c["concept_id"], c["system"], c["code"]] for c in crecs),
        "content_sha256": _content_sha(csha, maps, version),
    }
    (pack / RELEASE_FILE).write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if private_key is not None:
        (pack / SIGNATURE_FILE).write_bytes(crypto.ed25519_sign(private_key, canonical(rec)))
    if record:
        (reg.root / "releases").mkdir(exist_ok=True)
        (reg.root / "releases" / f"{version}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    return pack


@dataclass
class Release:
    record: dict[str, Any]
    concepts: list[dict[str, Any]]
    maps: dict[str, list[dict[str, Any]]]
    signed: bool


def _gz_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@contextmanager
def _opened(path: Path) -> Iterator[Path]:
    try:
        with refdata.opened(path) as d:
            yield d
    except refdata.PackError as exc:
        raise CodemapError([f"the pack: {exc}"]) from exc


def read_release(path: Path, public_key: bytes | None = None) -> Release:
    """Verify a release (a pack directory or its ``.tar``) and read it. Refused: a file whose sha256 or size differs
    from the manifest or the record; a record that disagrees with the manifest; with ``public_key``, a release with
    no valid signature; an author who approved their own release; a concept outside the registry band."""
    with _opened(path) as d:
        try:
            manifest = refdata.verify(d)
        except refdata.PackError as exc:
            raise CodemapError([f"the pack does not verify: {exc}"]) from exc
        try:
            raw = (d / RELEASE_FILE).read_bytes()
            rec: dict[str, Any] = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise CodemapError([f"no readable {RELEASE_FILE} ({exc})"]) from exc
        sig = d / SIGNATURE_FILE
        signed = False
        if public_key is not None:
            if not sig.is_file():
                raise CodemapError(["the release is not signed, and this box requires a signed release"])
            if not crypto.ed25519_verify(public_key, canonical(rec), sig.read_bytes()):
                raise CodemapError(["the release's signature does not verify (a changed record or another key)"])
            signed = True
        p: list[str] = []
        if rec.get("format") != RELEASE_FORMAT:
            p.append(f"{RELEASE_FILE}: format {rec.get('format')!r}, not {RELEASE_FORMAT}")
        if rec.get("pack_id") != manifest["pack_id"]:
            p.append(f"{RELEASE_FILE} names pack {rec.get('pack_id')!r}, the manifest {manifest['pack_id']!r}")
        author, approver = str(rec.get("author") or ""), str(rec.get("approver") or "")
        if not author or not approver or author.casefold() == approver.casefold():
            p.append("the release needs an author and a different approver")
        version = str(rec.get("version") or "")
        sources = {s["id"]: s for s in manifest["sources"]}
        maps = {str(m["id"]): m for m in rec.get("maps") or []}
        if set(sources) != {f"{CODEMAP_MAP_PREFIX}{mid}" for mid in maps}:
            p.append("the manifest's sources and the release's maps differ")
        for mid, m in maps.items():
            s = sources.get(f"{CODEMAP_MAP_PREFIX}{mid}")
            if s is None:
                continue
            files = {f["path"]: f for f in s["files"]}
            if s.get("version") != version or s.get("kind") != "map":
                p.append(f"map {mid}: the manifest says kind {s.get('kind')} version {s.get('version')}")
            f = files.get(str(m["path"]))
            if f is None or f["sha256"] != m["sha256"] or int(f["records"]) != int(m["records"]):
                p.append(f"map {mid}: {m['path']} differs from the release record (a changed file)")
        c = rec.get("concepts") or {}
        cpath = d / CONCEPTS_FILE
        if c.get("path") != CONCEPTS_FILE or not cpath.is_file() or refdata.sha256_file(cpath) != c.get("sha256"):
            p.append(f"{c.get('path')}: missing or differs from the release record (a changed file)")
        if rec.get("content_sha256") != _content_sha(str(c.get("sha256")), maps.values(), version):
            p.append("the release record's content sha256 does not match its files")
        if p:
            raise CodemapError(p)
        concepts = _gz_rows(cpath)
        ids = sorted([int(x["concept_id"]), x["system"], x["code"]] for x in concepts)
        if ids != [list(x) for x in rec.get("concept_ids") or []] or len(concepts) != int(c.get("records", -1)):
            p.append("the concepts file and the release record's concept ids differ")
        p += [f"concept {x['concept_id']} is outside the registry band" for x in concepts
              if not CODEMAP_MIN <= int(x["concept_id"]) <= CODEMAP_MAX]  # fmt: skip
        if p:
            raise CodemapError(p)
        rows = {mid: _gz_rows(d / str(m["path"])) for mid, m in maps.items()}
    return Release(rec, concepts, rows, signed)


# ------------------------------------------------------------------------------------------------ loading
def load(db: Any, path: Path, *, public_key: bytes | None = None, by: str = "operator") -> dict[str, Any]:
    """Load a verified release into the box's OMOP vocabulary, in one transaction (nothing is written when any
    part is refused). Returns what changed and ``omop.vocab.release`` after it."""
    from omop import vocab, vocab_load

    rel = read_release(path, public_key)
    rec = rel.record
    version = str(rec["version"])
    by_name = f"{by} (release by {rec['author']}, approved by {rec['approver']})"
    out: dict[str, Any] = {"version": version, "signed": rel.signed, "maps": {}, "removed": []}
    with db.transaction() as tx:
        vids = {x["system"]: vocab_load.vocabulary_of(x["system"]) for x in rel.concepts}
        out["concepts"] = vocab.seed_registry_concepts(
            tx,
            [(int(x["concept_id"]), vids[x["system"]][0], str(x["code"]), str(x["name"]), str(x["domain"]))
             for x in rel.concepts],
            {v: s for s, (v, _) in vids.items()},
            version,
        )  # fmt: skip
        for mid, rows in sorted(rel.maps.items()):  # each a savepoint inside this transaction
            res = vocab_load.load_concept_map(db, f"{CODEMAP_MAP_PREFIX}{mid}", rows, version=version, by=by_name)
            out["maps"][mid] = {"new": res.new, "concepts": res.concepts, "changed": res.changed}
        keep = [f"map:{CODEMAP_MAP_PREFIX}{mid}" for mid in rel.maps]
        for (name,) in tx.fetchall(
            "SELECT DISTINCT release_name FROM tb_vocab_release WHERE active AND release_name LIKE ? "
            "AND NOT (release_name = ANY(?))",
            (f"map:{CODEMAP_MAP_PREFIX}%", keep),
        ):
            q = "SELECT DISTINCT source_vocabulary_id FROM tb_map_relation WHERE map_release = ?"
            vocabs = [str(v) for (v,) in tx.fetchall(q, (name,))]
            tx.execute(
                "DELETE FROM source_to_concept_map WHERE source_vocabulary_id = ANY(?) AND source_concept_id >= ?",
                (vocabs, LOCAL_MIN),  # as load_concept_map replaces a map: the box's own concepts (>= 2e9)
            )
            tx.execute("DELETE FROM tb_map_relation WHERE map_release = ?", (name,))
            tx.execute("UPDATE tb_vocab_release SET active = false WHERE release_name = ?", (name,))
            out["removed"].append(str(name).removeprefix(f"map:{CODEMAP_MAP_PREFIX}"))
        rows_total = sum(len(r) for r in rel.maps.values()) + len(rel.concepts)
        out["new"] = vocab.record_codemap(tx, version=version, sha256=str(rec["content_sha256"]),
                                          registry=str(rec["registry"]), rows=rows_total, by=by_name)  # fmt: skip
    out["release"] = vocab.release(db)
    return out


# ------------------------------------------------------------------------------------------------ the command
def _key(path: Path | None) -> bytes | None:
    return path.read_bytes() if path else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.codemap_release", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="every problem of a registry")
    ck.add_argument("registry", type=Path)
    rl = sub.add_parser("release", help="write a release as a refdata pack part")
    rl.add_argument("registry", type=Path)
    rl.add_argument("--version", required=True)
    rl.add_argument("--author", required=True)
    rl.add_argument("--approver", required=True)
    rl.add_argument("--out", type=Path, required=True)
    rl.add_argument("--key", type=Path, help="the registry's Ed25519 private key (PEM) to sign the release")
    rl.add_argument("--tar", action="store_true", help="also write the pack as one .tar")
    rl.add_argument("--record", action="store_true", help="write the release record into the registry's releases/")
    vf = sub.add_parser("verify", help="verify a release and print its record")
    vf.add_argument("pack", type=Path)
    vf.add_argument("--public-key", type=Path)
    ld = sub.add_parser("load", help="load a release into the box's OMOP vocabulary")
    ld.add_argument("pack", type=Path)
    ld.add_argument("--public-key", type=Path)
    ld.add_argument("--db-url")
    ld.add_argument("--by", default="operator")
    st = sub.add_parser("status", help="the box's vocabulary release (omop.vocab.release)")
    st.add_argument("--db-url")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "check":
            problems = check(read_registry(a.registry))
            for line in problems:
                print(line)
            print("ok" if not problems else f"{len(problems)} problem(s)")
            return 1 if problems else 0
        if a.cmd == "release":
            pack = build_release(read_registry(a.registry), version=a.version, author=a.author,
                                 approver=a.approver, out=a.out, private_key=_key(a.key), record=a.record)  # fmt: skip
            print(pack)
            if a.tar:
                print(refdata.pack_tar(pack, pack.parent / f"{pack.name}.tar"))
            return 0
        if a.cmd == "verify":
            rel = read_release(a.pack, _key(a.public_key))
            print(json.dumps({**rel.record, "signed": rel.signed, "concept_ids": len(rel.record["concept_ids"])},
                             indent=1, ensure_ascii=False))  # fmt: skip
            return 0
    except CodemapError as exc:
        for line in exc.problems:
            print(f"refused: {line}", file=sys.stderr)
        return 1
    from omop import schema, vocab

    db = schema.connect(a.db_url)
    try:
        if a.cmd == "load":
            res = load(db, a.pack, public_key=_key(a.public_key), by=a.by)
        else:
            res = vocab.release(db)
        print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
        return 0
    except CodemapError as exc:
        for line in exc.problems:
            print(f"refused: {line}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
