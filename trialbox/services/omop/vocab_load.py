"""The vocabulary's loaders (WS-03.3, D-301): the OMOP vocabulary tables of schema ``omop`` are the one home of the
codes TrialBox reads (no second schema).

What goes in, and where:

* **The terminology Parquet** (``criteria_compiler/terminology/*.parquet``, the compiler's tables, D-122):
  every code becomes a ``concept`` of its vocabulary (``ICD10CM``, ``LOINC``, ``ATC``, ``NHI-DRUG``, ``NHI-ORDER``,
  ``DEPARTMENT``, ``CLINICAL-SCORE``), the zh-TW names ``concept_synonym`` rows (language 4182948), an NHI drug its
  ATC class and a panel component its panel as ``concept_relationship`` rows, the compiler's groupers
  ``tb_term_grouper`` rows. The row the compiler reads (its curated display, its order) rides beside the concept in
  ``tb_concept_attr`` (``term:<table>``), as D-151's ``tb_record.extra`` carries what a CDM row has no column for:
  :func:`term_tables` gives the compiler exactly the tables it was built from (same codes, new home).
* **A code-list release** (:func:`load_code_list`: ICD-10-CM FY2027 from the CMS order file or a ``code,display``
  CSV): new codes are added, names updated, codes the release no longer has are marked ``invalid_reason = 'D'``.
* **The refdata pack's terms** (:func:`load_refdata_terms`, rows of schema ``refdata``'s ``term`` table, D-140).
* **The JP masters** (:func:`load_licensed`: the releases the site loaded with ``adapter.licensed``, D-137): MEDIS
  病名, JLAC10 and YJ codes, each with its link to the standard code the file gives. A MEDIS ICD-10 code that is also
  an ICD-10-CM code links to it (D-137); a WHO-only code links to its ICD-10-CM category (``TB in CM family``,
  baseline correction 3); a code whose category is not in ICD-10-CM links to nothing and stays unknown (D-130).
* **The site's local codes** (:func:`load_local_codes`, ``sitesetup.local_code`` once a person mapped them, D-135):
  a local concept in the site block, minted by the OMOP loader's own :class:`omop.vocab.Concepts` (so the source
  concept of a record and of its map are one), and a ``source_to_concept_map`` row to the mapped code.
* **A map between editions** (:func:`load_concept_map`, e.g. the NHIA ICD-10-CM 2014 <-> 2023 map in the row shape
  of the refdata parsers): ``source_to_concept_map`` rows with their relation in ``tb_map_relation``;
  :func:`edition_code` applies it to a dated record with a provenance tag.

**Ids.** Reference codes (public or licensed lists loaded without the Athena bundle) take box-local ids from
``tb_ref_concept_seq`` (2,010,000,000 to 2,099,999,999); the site's local codes take the site block
(``TB_OMOP_CONCEPT_BLOCK``, one million ids, D-301). Every id >= 2,000,000,000 is never ``standard_concept = 'S'``
(the OHDSI rule for custom concepts); each load checks it and refuses otherwise.

**Releases.** Every load is a ``tb_vocab_release`` row (name, sha256 of its content, version, source). Loading the
same content again changes nothing. The box's *terminology release* (:func:`terminology_release`) is a digest of the
active releases the compiler resolves ValueSets through (:data:`COMPILE_RELEASES`); a ruleset pins the release it
was compiled against (``manifest.terminology_release``). When such a release loads, every approved ruleset is listed
in ``tb_ruleset_release`` with ``recompile_needed`` (:func:`mark_rulesets`), and a run of a ruleset pinned to another
release is refused until it is recompiled (``criteria_compiler.terminology.resolver``).
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from tb_common.db import Database
from tb_common.vocabfold import fold

from omop.schema import LOCAL_MIN, OmopError
from omop.vocab import VALID_FROM, VALID_TO, Code, Concepts

PARQUET = "terminology-parquet"
# the releases the compiler resolves ValueSets through: a new one marks every approved ruleset
COMPILE_RELEASES = frozenset({PARQUET, "ICD10CM", "LOINC", "ATC"})
REF_CLASS = "TB Reference Code"
EN, ZH, JA = 4180186, 4182948, 4181524  # OHDSI language concepts (concept_synonym.language_concept_id)
LANGUAGES = ((EN, "English language", "4180186"), (ZH, "Chinese language", "4182948"), (JA, "Japanese language",
             "4181524"))  # fmt: skip
RELATIONSHIPS = (
    ("Maps to", "Non-standard to standard map (OMOP)", "Mapped from"),
    ("Mapped from", "Standard to non-standard map (OMOP)", "Maps to"),
    ("TB has ATC", "NHI drug code to its ATC class (TrialBox)", "TB ATC of"),
    ("TB ATC of", "ATC class of an NHI drug code (TrialBox)", "TB has ATC"),
    ("TB component of", "Panel component to its panel (TrialBox)", "TB has component"),
    ("TB has component", "Panel to its component (TrialBox)", "TB component of"),
    ("TB in CM family", "WHO-only ICD-10 code to its ICD-10-CM category (TrialBox)", "TB CM family of"),
    ("TB CM family of", "ICD-10-CM category of a WHO-only ICD-10 code (TrialBox)", "TB in CM family"),
)

ICD10CM_URI = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_URI = "http://hl7.org/fhir/sid/icd-10"
# FHIR code system -> reference vocabulary (never ``TB-*``: those are the OMOP loader's local source vocabularies)
SYSTEM_VOCAB: dict[str, tuple[str, str]] = {
    ICD10CM_URI: ("ICD10CM", "Condition"),
    ICD10_URI: ("ICD10", "Condition"),
    "http://loinc.org": ("LOINC", "Measurement"),
    "http://www.whocc.no/atc": ("ATC", "Drug"),
    "https://trialbox.local/fhir/CodeSystem/nhi-drug": ("NHI-DRUG", "Drug"),
    "https://trialbox.local/fhir/CodeSystem/nhi-order": ("NHI-ORDER", "Procedure"),
    "https://trialbox.local/fhir/CodeSystem/department": ("DEPARTMENT", "Observation"),
    "https://trialbox.local/fhir/CodeSystem/clinical-score": ("CLINICAL-SCORE", "Measurement"),
    "urn:oid:1.2.392.200119.4.101.6": ("MEDIS", "Condition"),
    "urn:oid:1.2.392.200119.4.504": ("JLAC10", "Measurement"),
    "urn:oid:1.2.392.100495.20.1.73": ("YJ", "Drug"),
    "urn:tw:nhi:icd-10-cm-2014": ("TW-ICD10CM-2014", "Condition"),
    "urn:tw:nhi:icd-10-cm-2023": ("TW-ICD10CM-2023", "Condition"),
    "urn:tw:nhi:drug": ("TW-NHI-DRUG", "Drug"),
}
# compiler table -> (system column or fixed system, code column)
TERM_TABLES: dict[str, tuple[str, str]] = {
    "icd10cm_full": (ICD10CM_URI, "code"),
    "icd10cm_tw": (ICD10CM_URI, "code"),
    "atc": ("http://www.whocc.no/atc", "code"),
    "loinc_tw": ("@system", "code"),
    "nhi_drug": ("https://trialbox.local/fhir/CodeSystem/nhi-drug", "nhi_code"),
    "nhi_order": ("https://trialbox.local/fhir/CodeSystem/nhi-order", "code"),
    "department": ("https://trialbox.local/fhir/CodeSystem/department", "code"),
}
TERM_FILES = (*TERM_TABLES, "synonyms")
# NHI claims moved from the 2014 to the 2023 ICD-10-CM edition on 2025-01-01 (D-171)
NHIA_EDITION_SWITCH = date(2025, 1, 1)


def vocabulary_of(system: str) -> tuple[str, str]:
    """``(vocabulary_id, domain)`` of a code system: a known name, else ``REF-`` and 12 hex of the URI's sha1."""
    known = SYSTEM_VOCAB.get(system)
    if known:
        return known
    return "REF-" + hashlib.sha1(system.encode("utf-8"), usedforsecurity=False).hexdigest()[:12], "Observation"


@dataclass
class LoadResult:
    name: str
    sha256: str
    new: bool
    concepts: int = 0
    changed: int = 0
    marked: list[str] = field(default_factory=list)
    athena: dict[str, Any] | None = None  # an Athena load: what loaded, what was skipped and why (load_athena)

    def as_dict(self) -> dict[str, Any]:
        out = {"release": self.name, "sha256": self.sha256, "new": self.new, "concepts": self.concepts,
               "changed": self.changed, "marked": self.marked}  # fmt: skip
        if self.athena is not None:
            out["athena"] = self.athena
        return out


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ bookkeeping
def _prepare(tx: Any) -> None:
    """Language concepts, the relationships, the reference class: idempotent."""
    for cid, name, code in LANGUAGES:
        tx.execute(
            "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
            "standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason) "
            "SELECT ?, ?, 'Metadata', 'None', 'Undefined', NULL, ?, ?, ?, NULL "
            "WHERE NOT EXISTS (SELECT 1 FROM concept WHERE concept_id = ?)",
            (cid, name, code, VALID_FROM, VALID_TO, cid),
        )
    for rid, name, rev in RELATIONSHIPS:
        tx.execute(
            "INSERT INTO relationship (relationship_id, relationship_name, is_hierarchical, defines_ancestry, "
            "reverse_relationship_id, relationship_concept_id) SELECT ?, ?, '0', '0', ?, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM relationship WHERE relationship_id = ?)",
            (rid, name, rev, rid),
        )
    tx.execute(
        "INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
        "SELECT ?, ?, 0 WHERE NOT EXISTS (SELECT 1 FROM concept_class WHERE concept_class_id = ?)",
        (REF_CLASS, REF_CLASS, REF_CLASS),
    )


def _vocabulary(tx: Any, vid: str, system: str, version: str) -> None:
    if tx.fetchone("SELECT 1 FROM vocabulary WHERE vocabulary_id = ?", (vid,)) is None:
        tx.execute(
            "INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
            "vocabulary_concept_id) VALUES (?, ?, ?, ?, 0)",
            (vid, f"{vid} (reference codes loaded by TrialBox)", system[:255], version[:255]),
        )
    else:
        tx.execute("UPDATE vocabulary SET vocabulary_version = ? WHERE vocabulary_id = ?", (version[:255], vid))


def _release(tx: Any, name: str, sha: str, vid: str, version: str, source: str, rows: int, by: str) -> bool:
    """Record a release; False (nothing to do) when this content was loaded before. The release of the same name
    loaded last is the active one."""
    have = tx.fetchone("SELECT active FROM tb_vocab_release WHERE release_name = ? AND sha256 = ?", (name, sha))
    if have is not None:
        if not have[0]:  # an older content loaded again becomes the active one
            tx.execute("UPDATE tb_vocab_release SET active = false WHERE release_name = ?", (name,))
            tx.execute("UPDATE tb_vocab_release SET active = true WHERE release_name = ? AND sha256 = ?", (name, sha))
            return True
        return False
    tx.execute("UPDATE tb_vocab_release SET active = false WHERE release_name = ?", (name,))
    tx.execute(
        "INSERT INTO tb_vocab_release (release_name, sha256, vocabulary_id, version, source, rows, compile, "
        "loaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, sha, vid, version, source, rows, name in COMPILE_RELEASES, by),
    )
    return True


def _check_never_standard(tx: Any) -> None:
    n = int(tx.fetchval("SELECT count(*) FROM concept WHERE concept_id >= ? AND standard_concept = 'S'", (LOCAL_MIN,)))
    if n:
        raise OmopError(f"{n} concepts >= {LOCAL_MIN:,} are standard: a custom concept is never standard (D-301)")


def release_digest(active: Iterable[tuple[str, str]]) -> str:
    """``TR-`` and 12 hex over the sorted ``(release name, sha256)`` of the compile releases."""
    pairs = sorted({(n, s) for n, s in active if n in COMPILE_RELEASES})
    if not pairs:
        return ""
    return "TR-" + hashlib.sha256("\n".join(f"{n}={s}" for n, s in pairs).encode("utf-8")).hexdigest()[:12]


def terminology_release(db: Database) -> str:
    """The box's terminology release: the digest of the active compile releases ('' when none is loaded)."""
    rows = db.fetchall("SELECT release_name, sha256 FROM tb_vocab_release WHERE active AND compile")
    return release_digest((str(n), str(s)) for n, s in rows)


def releases(db: Database) -> list[dict[str, Any]]:
    return db.fetchdicts(
        "SELECT release_name, sha256, vocabulary_id, version, source, rows, compile, active, loaded_by, loaded_at "
        "FROM tb_vocab_release ORDER BY loaded_at, release_name"
    )


# ------------------------------------------------------------------------------------------------ concepts
def _ref_ids(tx: Any, vid: str, codes: Iterable[str]) -> dict[str, int]:
    """Existing concept ids of ``codes`` in vocabulary ``vid`` (an Athena row wins over a reference one)."""
    want = sorted(set(codes))
    out: dict[str, int] = {}
    if not want:
        return out
    for code, cid in tx.fetchall(
        "SELECT concept_code, concept_id FROM concept WHERE vocabulary_id = ? AND concept_code = ANY(?) "
        "ORDER BY concept_id DESC",
        (vid, want),
    ):
        out[str(code)] = int(cid)  # ascending ids win: the last write is the lowest id
    return out


def _upsert_concepts(tx: Any, vid: str, domain: str, rows: Mapping[str, str]) -> tuple[dict[str, int], int]:
    """``code -> name``: mint the missing reference concepts, rename changed ones, revive deleted ones. Returns the
    ids and how many rows changed."""
    ids = _ref_ids(tx, vid, rows)
    changed = 0
    have = {
        str(code): (str(name), inv)
        for code, name, inv in tx.fetchall(
            "SELECT concept_code, concept_name, invalid_reason FROM concept WHERE vocabulary_id = ? "
            "AND concept_id >= ?",
            (vid, LOCAL_MIN),
        )
    }
    upd = []
    for code, name in rows.items():
        h = have.get(code)
        if h is not None and (h[0] != (name or code)[:255] or h[1] is not None):
            upd.append(((name or code)[:255], vid, code))
    for u in upd:
        tx.execute(
            "UPDATE concept SET concept_name = ?, invalid_reason = NULL WHERE vocabulary_id = ? AND concept_code = ? "
            "AND concept_id >= 2000000000",
            u,
        )
    changed += len(upd)
    new = sorted(c for c in rows if c not in ids)
    if new:
        nxt = [int(r[0]) for r in tx.fetchall("SELECT nextval('tb_ref_concept_seq') FROM generate_series(1, ?)",
                                              (len(new),))]  # fmt: skip
        out = []
        for code, cid in zip(new, nxt, strict=True):
            ids[code] = cid
            out.append((cid, (rows[code] or code)[:255], domain, vid, REF_CLASS, None, code[:50], VALID_FROM, VALID_TO,
                        None))  # fmt: skip
        tx.copy_rows(
            "concept",
            ["concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id", "standard_concept",
             "concept_code", "valid_start_date", "valid_end_date", "invalid_reason"],
            out,
        )  # fmt: skip
        changed += len(new)
    return ids, changed


def _set_attrs(tx: Any, attr: str, values: Mapping[int, str], replace: bool) -> int:
    """``tb_concept_attr`` rows of one attribute; ``replace`` drops the attribute from concepts not in ``values``."""
    have = {int(c): str(v) for c, v in tx.fetchall("SELECT concept_id, value FROM tb_concept_attr WHERE attr = ?",
                                                    (attr,))}  # fmt: skip
    gone = [c for c in have if c not in values] if replace else []
    for c in gone:
        tx.execute("DELETE FROM tb_concept_attr WHERE concept_id = ? AND attr = ?", (c, attr))
    upd = [(v, c, attr) for c, v in values.items() if c in have and have[c] != v]
    if upd:
        tx.executemany("UPDATE tb_concept_attr SET value = ? WHERE concept_id = ? AND attr = ?", upd)
    new = [(c, attr, v) for c, v in values.items() if c not in have]
    if new:
        tx.copy_rows("tb_concept_attr", ["concept_id", "attr", "value"], new)
    return len(gone) + len(upd) + len(new)


def _synonyms(tx: Any, names: Mapping[int, str], language: int) -> None:
    for cid, name in names.items():
        tx.execute(
            "INSERT INTO concept_synonym (concept_id, concept_synonym_name, language_concept_id) SELECT ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM concept_synonym WHERE concept_id = ? AND concept_synonym_name = ? "
            "AND language_concept_id = ?)",
            (cid, name[:1000], language, cid, name[:1000], language),
        )


def _relate(tx: Any, pairs: Iterable[tuple[int, int]], rel: str, rev: str) -> None:
    for a, b in pairs:
        for x, y, r in ((a, b, rel), (b, a, rev)):
            tx.execute(
                "INSERT INTO concept_relationship (concept_id_1, concept_id_2, relationship_id, valid_start_date, "
                "valid_end_date, invalid_reason) SELECT ?, ?, ?, ?, ?, NULL WHERE NOT EXISTS (SELECT 1 FROM "
                "concept_relationship WHERE concept_id_1 = ? AND concept_id_2 = ? AND relationship_id = ?)",
                (x, y, r, VALID_FROM, VALID_TO, x, y, r),
            )


# ------------------------------------------------------------------------------------------------ rulesets
def mark_rulesets(db: Database, rulesets_dir: Path | None, release: str) -> list[str]:
    """Every approved ruleset in ``rulesets_dir``, listed with the release it was compiled against and whether it
    must be recompiled for ``release`` (an unpinned ruleset always must). Returns the ids marked."""
    if rulesets_dir is None or not rulesets_dir.is_dir():
        return []
    from tb_common.ruleset import Ruleset, list_rulesets

    marked = []
    with db.transaction() as tx:
        for rid in list_rulesets(rulesets_dir):
            try:
                rs = Ruleset.load(rulesets_dir / rid)
            except (OSError, ValueError):
                continue
            if rs.manifest.status != "approved":
                continue
            pin = getattr(rs.manifest, "terminology_release", None) or ""
            need = pin != release
            tx.execute(
                "INSERT INTO tb_ruleset_release (ruleset_id, version, compiled_release, recompile_needed, marked_for) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (ruleset_id, version) DO UPDATE SET compiled_release = "
                "excluded.compiled_release, recompile_needed = excluded.recompile_needed, marked_for = "
                "excluded.marked_for, marked_at = now()",
                (rs.id, rs.version, pin or "unpinned", need, release),
            )
            if need:
                marked.append(rs.id)
    return marked


def recompile_needed(db: Database) -> list[dict[str, Any]]:
    return db.fetchdicts(
        "SELECT ruleset_id, version, compiled_release, marked_for, marked_at FROM tb_ruleset_release "
        "WHERE recompile_needed ORDER BY ruleset_id, version"
    )


def _after_release(db: Database, res: LoadResult, rulesets_dir: Path | None) -> LoadResult:
    if res.new and res.name in COMPILE_RELEASES:
        res.marked = mark_rulesets(db, rulesets_dir, terminology_release(db))
    return res


# ------------------------------------------------------------------------------------------------ the Parquet
def parquet_sha(term_dir: Path) -> str:
    """sha256 over the compiler's table files (name and content), the release's identity."""
    h = hashlib.sha256()
    for name in TERM_FILES:
        p = term_dir / f"{name}.parquet"
        if p.is_file():
            h.update(f"{name}\0".encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def read_parquet_tables(term_dir: Path) -> dict[str, list[dict[str, Any]]]:
    import pyarrow.parquet as pq

    return {n: pq.read_table(term_dir / f"{n}.parquet").to_pylist() for n in TERM_FILES
            if (term_dir / f"{n}.parquet").is_file()}  # fmt: skip


def _row_system(table: str, row: Mapping[str, Any]) -> str:
    sys_col, _ = TERM_TABLES[table]
    return str(row.get("system") or "http://loinc.org") if sys_col == "@system" else sys_col


def load_terminology(
    db: Database, term_dir: Path, *, by: str = "loader", rulesets_dir: Path | None = None
) -> LoadResult:
    """The compiler's terminology tables into the vocabulary (see the module text). Same content twice: no change."""
    sha = parquet_sha(term_dir)
    tables = read_parquet_tables(term_dir)
    res = LoadResult(PARQUET, sha, False)
    with db.transaction() as tx:
        _prepare(tx)
        n_rows = sum(len(v) for v in tables.values())
        if not _release(tx, PARQUET, sha, "TB-TERM", f"terminology Parquet {sha[:12]}", str(term_dir.name), n_rows,
                        by):  # fmt: skip
            return res
        res.new = True
        # names: the curated display wins over the full list's (the compiler's own rule, D-122)
        names: dict[tuple[str, str], tuple[str, str]] = {}
        for table in ("icd10cm_full", *[t for t in TERM_TABLES if t != "icd10cm_full"]):
            for r in tables.get(table, []):
                system = _row_system(table, r)
                code = str(r[TERM_TABLES[table][1]])
                disp = str(r.get("display") or r.get("name") or code)
                names[(system, code)] = (disp, str(r.get("display_zh") or r.get("name_zh") or ""))
        ids: dict[tuple[str, str], int] = {}
        by_vocab: dict[str, tuple[str, str, dict[str, str]]] = {}
        for (system, code), (disp, _) in names.items():
            vid, dom = vocabulary_of(system)
            by_vocab.setdefault(vid, (system, dom, {}))[2][code] = disp
        for vid, (system, dom, rows) in sorted(by_vocab.items()):
            _vocabulary(tx, vid, system, f"terminology Parquet {sha[:12]}")
            got, ch = _upsert_concepts(tx, vid, dom, rows)
            res.changed += ch
            ids.update({(system, c): i for c, i in got.items()})
        res.concepts = len(ids)
        _synonyms(tx, {ids[k]: v[1] for k, v in names.items() if v[1]}, ZH)
        # the compiler's rows, exactly as built (with their order)
        for table in TERM_TABLES:
            vals: dict[int, str] = {}
            for i, r in enumerate(tables.get(table, [])):
                key = (_row_system(table, r), str(r[TERM_TABLES[table][1]]))
                vals[ids[key]] = json.dumps({"_ord": i, **r}, ensure_ascii=False, sort_keys=True)
            res.changed += _set_attrs(tx, f"term:{table}", vals, replace=True)
        atc = {c: i for (s, c), i in ids.items() if s == "http://www.whocc.no/atc"}
        _relate(tx, [(ids[(TERM_TABLES["nhi_drug"][0], str(r["nhi_code"]))], atc[str(r["atc"])])
                     for r in tables.get("nhi_drug", []) if r.get("atc") and str(r["atc"]) in atc],
                "TB has ATC", "TB ATC of")  # fmt: skip
        loinc = "http://loinc.org"
        panels = [
            (ids[(_row_system("loinc_tw", r), str(r["code"]))], ids[(loinc, str(r["component_of"]))])
            for r in tables.get("loinc_tw", [])
            if r.get("component_of") and (loinc, str(r["component_of"])) in ids
        ]
        _relate(tx, panels, "TB component of", "TB has component")
        tx.execute("DELETE FROM tb_term_grouper")
        tx.copy_rows(
            "tb_term_grouper",
            ["ord", "domain", "name", "tbl", "code", "match"],
            [(i, r["domain"], r["name"], r["table"], r["code"], r["match"]) for i, r in
             enumerate(tables.get("synonyms", []))],
        )  # fmt: skip
        _check_never_standard(tx)
    return _after_release(db, res, rulesets_dir)


def term_tables(db: Database) -> dict[str, list[dict[str, Any]]]:
    """The compiler's tables read back from the vocabulary: exactly the rows :func:`load_terminology` stored, in
    their order, with every ``ICD10CM`` code a later code-list release added to ``icd10cm_full``."""
    out: dict[str, list[dict[str, Any]]] = {}
    for table in TERM_TABLES:
        rows = [json.loads(v) for (v,) in db.fetchall(
            "SELECT a.value FROM tb_concept_attr a JOIN concept c ON c.concept_id = a.concept_id "
            "WHERE a.attr = ? AND c.invalid_reason IS NULL", (f"term:{table}",))]  # fmt: skip
        rows.sort(key=lambda r: (r.get("_ord", 1 << 30), str(r.get(TERM_TABLES[table][1]))))
        out[table] = [{k: v for k, v in r.items() if k != "_ord"} for r in rows]
    out["synonyms"] = db.fetchdicts(
        'SELECT domain, name, tbl AS "table", code, match FROM tb_term_grouper ORDER BY ord'
    )
    return {k: v for k, v in out.items() if v}


# ------------------------------------------------------------------------------------------------ code lists
def read_code_list(path: Path) -> list[tuple[str, str]]:
    """A code list release: a ``code,display`` CSV (optionally gzipped, the D-122 source format) or the CMS
    ``icd10cm_order`` file (fixed width: order, code, billable flag, short and long description). Codes as printed
    by CMS without the dot are given their dot (``E119`` -> ``E11.9``)."""
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    text = data.decode("utf-8-sig")
    first = text.split("\n", 1)[0]
    out: list[tuple[str, str]] = []
    if "," in first and first.lower().startswith("code"):
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("code"):
                out.append((r["code"].strip(), (r.get("display") or "").strip()))
        return out
    for line in text.splitlines():
        if len(line) < 16 or not line[:5].strip().isdigit():
            continue
        raw = line[6:13].strip()
        code = raw if len(raw) <= 3 or "." in raw else f"{raw[:3]}.{raw[3:]}"
        out.append((code, line[77:].strip() or line[16:76].strip()))
    return out


def load_code_list(
    db: Database,
    system: str,
    version: str,
    codes: Iterable[tuple[str, str]],
    *,
    source: str,
    by: str = "loader",
    rulesets_dir: Path | None = None,
) -> LoadResult:
    """One release of a code list (ICD-10-CM FY2027, ...): the codes become the vocabulary's valid concepts and
    the codes it no longer lists ``invalid_reason = 'D'``. For ICD-10-CM the compiler's full list follows."""
    rows = {c: d for c, d in codes if c}
    if not rows:
        raise OmopError("the code list is empty")
    vid, dom = vocabulary_of(system)
    sha = _sha(sorted(rows.items()))
    res = LoadResult(vid, sha, False)
    with db.transaction() as tx:
        _prepare(tx)
        if not _release(tx, vid, sha, vid, version, source, len(rows), by):
            return res
        res.new = True
        _vocabulary(tx, vid, system, version)
        ids, res.changed = _upsert_concepts(tx, vid, dom, rows)
        res.concepts = len(ids)
        gone = tx.execute(
            "UPDATE concept SET invalid_reason = 'D' WHERE vocabulary_id = ? AND concept_id >= ? "
            "AND invalid_reason IS NULL AND NOT (concept_code = ANY(?))",
            (vid, LOCAL_MIN, sorted(rows)),
        )
        res.changed += gone
        if system == ICD10CM_URI:
            res.changed += _set_attrs(
                tx, "term:icd10cm_full",
                {ids[c]: json.dumps({"_ord": i, "code": c, "display": d}, ensure_ascii=False, sort_keys=True)
                 for i, (c, d) in enumerate(sorted(rows.items()))},
                replace=True,
            )  # fmt: skip
        _check_never_standard(tx)
    return _after_release(db, res, rulesets_dir)


# ------------------------------------------------------------------------------------------------ refdata, JP masters
def refdata_terms(url: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """The refdata pack's ``term`` rows by source (schema ``refdata``, D-140); empty when no pack is loaded."""
    from tb_common.db import DatabaseError

    try:
        rdb = Database.connect(url, "refdata")
    except DatabaseError:
        return {}
    try:
        if rdb.fetchone("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() "
                        "AND table_name = 'term'") is None:  # fmt: skip
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rdb.fetchdicts("SELECT system, code, display, extra, source_id FROM term ORDER BY system, code"):
            out.setdefault(str(r["source_id"]), []).append(r)
        return out
    finally:
        rdb.close()


def load_refdata_terms(
    db: Database, source_id: str, rows: Iterable[Mapping[str, Any]], *, version: str, by: str = "loader"
) -> LoadResult:
    """One refdata source's terms (``{system, code, display}``) as reference concepts."""
    by_sys: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.get("system") and r.get("code"):
            by_sys.setdefault(str(r["system"]), {})[str(r["code"])] = str(r.get("display") or "")
    name = f"refdata:{source_id}"
    sha = _sha({k: sorted(v.items()) for k, v in sorted(by_sys.items())})
    res = LoadResult(name, sha, False)
    with db.transaction() as tx:
        _prepare(tx)
        if not _release(tx, name, sha, "REFDATA", version, source_id, sum(len(v) for v in by_sys.values()), by):
            return res
        res.new = True
        for system, codes in sorted(by_sys.items()):
            vid, dom = vocabulary_of(system)
            _vocabulary(tx, vid, system, version)
            ids, ch = _upsert_concepts(tx, vid, dom, codes)
            res.concepts += len(ids)
            res.changed += ch
        _check_never_standard(tx)
    return res


def _icd10cm_ids(tx: Any, codes: Iterable[str]) -> dict[str, int]:
    return {
        str(c): int(i)
        for c, i in tx.fetchall(
            "SELECT concept_code, concept_id FROM concept WHERE vocabulary_id = 'ICD10CM' AND concept_code = ANY(?) "
            "AND invalid_reason IS NULL",
            (sorted(set(codes)),),
        )
    }


def who_family(code: str) -> str:
    """The ICD-10-CM category a WHO ICD-10 code belongs to: its first three characters (``M10.97`` -> ``M10``)."""
    return code.replace(".", "")[:3].upper()


def load_licensed(
    db: Database, tables: Mapping[str, Mapping[str, Mapping[str, str]]], *, versions: Mapping[str, str] | None = None,
    by: str = "loader",
) -> list[LoadResult]:  # fmt: skip
    """The JP masters a site loaded (``adapter.licensed.tables()``: ``kind -> code -> {display, target_system,
    target_code}``): each kind one release; its codes reference concepts with their link to the standard code."""
    from adapter.licensed import KINDS

    out = []
    for kind, codes in sorted(tables.items()):
        k = KINDS.get(kind)
        if k is None or not codes:
            continue
        name = f"licensed:{kind}"
        sha = _sha(sorted((c, dict(v)) for c, v in codes.items()))
        res = LoadResult(name, sha, False)
        version = (versions or {}).get(kind) or sha[:12]
        with db.transaction() as tx:
            _prepare(tx)
            vid, dom = vocabulary_of(k.system)
            if not _release(tx, name, sha, vid, version, kind, len(codes), by):
                out.append(res)
                continue
            res.new = True
            _vocabulary(tx, vid, k.system, version)
            ids, res.changed = _upsert_concepts(
                tx, vid, dom, {c: str(v.get("display") or "") for c, v in codes.items()}
            )
            res.concepts = len(ids)
            links: dict[str, list[tuple[int, int]]] = {}
            targets = {c: (str(v.get("target_system") or ""), str(v.get("target_code") or "")) for c, v in
                       codes.items() if v.get("target_code")}  # fmt: skip
            who = [t for _, (s, t) in targets.items() if s == ICD10_URI]
            cm = _icd10cm_ids(tx, who + [who_family(t) for t in who])
            other: dict[str, dict[str, str]] = {}
            for c, (s, t) in targets.items():
                if s == ICD10_URI:
                    if t in cm:  # also an ICD-10-CM code (D-137)
                        links.setdefault("Maps to", []).append((ids[c], cm[t]))
                    elif who_family(t) in cm:  # WHO-only: its ICD-10-CM category (baseline correction 3)
                        links.setdefault("TB in CM family", []).append((ids[c], cm[who_family(t)]))
                    # else: no ICD-10-CM category: unknown (D-130)
                elif s:
                    other.setdefault(s, {})[c] = t
            for s, by_code in other.items():
                tvid, tdom = vocabulary_of(s)
                _vocabulary(tx, tvid, s, "as referenced")
                tids, _ = _upsert_concepts(tx, tvid, tdom, {t: "" for t in by_code.values()})
                links.setdefault("Maps to", []).extend((ids[c], tids[t]) for c, t in by_code.items())
            for rel, pairs in links.items():
                rev = next(r for i, _, r in RELATIONSHIPS if i == rel)
                _relate(tx, pairs, rel, rev)
            _check_never_standard(tx)
        out.append(res)
    return out


# ------------------------------------------------------------------------------------------------ local codes
def load_local_codes(db: Database, rows: Iterable[Mapping[str, Any]], *, by: str = "loader") -> int:
    """``sitesetup.local_code`` rows a person mapped (``system, code, display, domain, mapped_system,
    mapped_code, mapped_display``): the site's local concept (site block, never standard) and its
    ``source_to_concept_map`` row to the mapped code. A remap replaces the row; an unmapped code stays unmapped
    (unknown, D-130). Returns the rows written. Not a release: a map changes the data, never a compiled ruleset."""
    want = [r for r in rows if r.get("code") and r.get("mapped_code")]
    if not want:
        return 0
    dom_of = {"condition": "Condition", "observation": "Measurement", "lab": "Measurement", "medication": "Drug",
              "demographic": "Observation"}  # fmt: skip
    with db.transaction() as tx:
        _prepare(tx)
        concepts = Concepts(tx)
        concepts.prepare(
            Code(str(r.get("system") or "") or None, str(r["code"]), str(r.get("display") or "") or None,
                 dom_of.get(str(r.get("domain") or ""), "Observation")) for r in want
        )  # fmt: skip
        n = 0
        for r in want:
            src = concepts.source_id(str(r.get("system") or "") or None, str(r["code"]))
            if not src:
                continue
            svid = tx.fetchval("SELECT vocabulary_id FROM concept WHERE concept_id = ?", (src,))
            tvid, tdom = vocabulary_of(str(r["mapped_system"]))
            _vocabulary(tx, tvid, str(r["mapped_system"]), "as referenced")
            tids, _ = _upsert_concepts(tx, tvid, tdom, {str(r["mapped_code"]): str(r.get("mapped_display") or "")})
            tx.execute("DELETE FROM source_to_concept_map WHERE source_vocabulary_id = ? AND source_code = ?",
                       (svid, str(r["code"])))  # fmt: skip
            tx.execute(
                "INSERT INTO source_to_concept_map (source_code, source_concept_id, source_vocabulary_id, "
                "source_code_description, target_concept_id, target_vocabulary_id, valid_start_date, valid_end_date, "
                "invalid_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (str(r["code"])[:50], src, svid, str(r.get("display") or "")[:255] or None,
                 tids[str(r["mapped_code"])], tvid, VALID_FROM, VALID_TO),
            )  # fmt: skip
            n += 1
        _check_never_standard(tx)
    return n


def local_code_rows(url: str | None, ws: str) -> list[dict[str, Any]]:
    """The mapped local codes of site set-up space ``ws`` (``sitesetup.store.SetupStore.locals``)."""
    from sitesetup.store import SetupStore

    st = SetupStore(url)
    try:
        return [r for r in st.locals(ws) if r.get("mapped_code")]
    finally:
        st.close()


# ------------------------------------------------------------------------------------------------ edition maps
def load_concept_map(
    db: Database, name: str, rows: Iterable[Mapping[str, Any]], *, version: str, by: str = "loader"
) -> LoadResult:
    """A map between code systems in the refdata parsers' row shape (``source_system, source_code, target_system,
    target_code, relation``; e.g. ``tb_common.refdata_tw.icd_map_rows`` for the NHIA 2014 <-> 2023 map, D-171).
    ``unmatched`` rows (no target) map nothing."""
    pairs = [
        dict(r) for r in rows if r.get("source_code") and r.get("target_code") and r.get("relation") != "unmatched"
    ]
    rel_name = f"map:{name}"
    sha = _sha(sorted((r["source_system"], r["source_code"], r["target_system"], r["target_code"], r["relation"])
                      for r in pairs))  # fmt: skip
    res = LoadResult(rel_name, sha, False)
    with db.transaction() as tx:
        _prepare(tx)
        if not _release(tx, rel_name, sha, "MAP", version, name, len(pairs), by):
            return res
        res.new = True
        src_codes: dict[str, dict[str, str]] = {}
        tgt_codes: dict[str, dict[str, str]] = {}
        for r in pairs:
            src_codes.setdefault(str(r["source_system"]), {})[str(r["source_code"])] = str(
                r.get("source_display") or ""
            )
            tgt_codes.setdefault(str(r["target_system"]), {})[str(r["target_code"])] = str(
                r.get("target_display") or ""
            )
        ids: dict[tuple[str, str], int] = {}
        for system, codes in (*src_codes.items(), *tgt_codes.items()):
            vid, dom = vocabulary_of(system)
            _vocabulary(tx, vid, system, version)
            got, ch = _upsert_concepts(tx, vid, dom, codes)
            res.changed += ch
            ids.update({(system, c): i for c, i in got.items()})
        svids = sorted({vocabulary_of(s)[0] for s in src_codes})
        tx.execute("DELETE FROM source_to_concept_map WHERE source_vocabulary_id = ANY(?) AND source_concept_id IN "
                   "(SELECT concept_id FROM concept WHERE concept_id >= ?)", (svids, LOCAL_MIN))  # fmt: skip
        tx.execute("DELETE FROM tb_map_relation WHERE map_release = ?", (rel_name,))
        stcm, rel = [], []
        for r in pairs:
            svid, tvid = vocabulary_of(str(r["source_system"]))[0], vocabulary_of(str(r["target_system"]))[0]
            s_id = ids[(str(r["source_system"]), str(r["source_code"]))]
            t_id = ids[(str(r["target_system"]), str(r["target_code"]))]
            stcm.append((str(r["source_code"])[:50], s_id, svid, (str(r.get("source_display") or "") or None),
                         t_id, tvid, VALID_FROM, VALID_TO, None))  # fmt: skip
            rel.append((svid, str(r["source_code"]), t_id, str(r["relation"]), rel_name))
        tx.copy_rows(
            "source_to_concept_map",
            ["source_code", "source_concept_id", "source_vocabulary_id", "source_code_description",
             "target_concept_id", "target_vocabulary_id", "valid_start_date", "valid_end_date", "invalid_reason"],
            stcm,
        )  # fmt: skip
        tx.copy_rows("tb_map_relation", ["source_vocabulary_id", "source_code", "target_concept_id", "relation",
                                         "map_release"], rel)  # fmt: skip
        res.concepts = len(ids)
        _check_never_standard(tx)
    return res


@dataclass(frozen=True)
class EditionCode:
    system: str
    code: str
    provenance: str | None  # None: the record's own code, unchanged


# a map row whose relation is one of these gives the record one code; several targets or a candidate never do
_SINGLE = ("equivalent", "wider", "inexact")


def edition_code(
    db: Database, system: str, code: str, record_date: date, *, target_system: str, name: str,
    switch: date = NHIA_EDITION_SWITCH,
) -> EditionCode | None:  # fmt: skip
    """The code a dated record carries in the current edition: a record from before ``switch`` coded in the old
    edition gets the map's one target with a provenance tag (``<map release>@<version>:<relation>:<old code>``); a
    record from ``switch`` on keeps its code. None when the map cannot say (no row, a split into several codes, a
    candidate only): the record stays as coded, and the caller keeps it unknown rather than guessing."""
    if record_date >= switch:
        return EditionCode(system, code, None)
    svid = vocabulary_of(system)[0]
    rel_name = f"map:{name}"
    rows = db.fetchall(
        "SELECT c.concept_code, r.relation, v.version FROM tb_map_relation r JOIN concept c ON c.concept_id = "
        "r.target_concept_id JOIN tb_vocab_release v ON v.release_name = r.map_release AND v.active "
        "WHERE r.source_vocabulary_id = ? AND r.source_code = ? AND r.map_release = ?",
        (svid, code, rel_name),
    )
    usable = [(str(c), str(rel), str(v)) for c, rel, v in rows if rel != "relatedto"]
    if len(usable) != 1 or usable[0][1] not in _SINGLE:
        return None
    tcode, rel, ver = usable[0]
    return EditionCode(target_system, tcode, f"{rel_name}@{ver}:{rel}:{code}")


# ------------------------------------------------------------------------------------------------ Athena bundle
# The vocabularies an Athena bundle may bring onto the box (STD-034) come from the licence register, the one source
# (cards 22-2, T6-5): a vocabulary named in a row's column ``athena`` loads; one named in ``athena_never`` (licence
# class c) never loads and never ships; any other is not on the list. Adding one is a licence matter: a register row
# with its class and evidence first.
REGISTER = Path(__file__).resolve().parents[2] / "docs" / "licences" / "register.csv"


LOADABLE_CLASSES = frozenset({"a", "b", "d", "open"})  # register classes the loader may load; c never


@dataclass(frozen=True)
class AthenaClass:
    """What the licence register says of one Athena vocabulary: its row, the row's class and status, whether the
    loader may load it, and the other names it goes by (``athena_never`` entries ``ID|alias|alias``)."""

    vocabulary: str
    row: str
    klass: str
    status: str
    loadable: bool
    aliases: tuple[str, ...] = ()

    def reason(self) -> str:
        """Why the loader skips it (a loadable vocabulary is never skipped)."""
        where = f"register row {self.row}, class {self.klass or '(none)'}, status {self.status}"
        if self.status == "removed" or (self.klass == "c" and self.status != "site-loaded"):
            return f"licence class must not ship ({where})"
        if self.klass == "c":
            return f"licence class must not ship: the site loads it under its own licence, not this loader ({where})"
        return f"licence class must not ship: the register row does not let it load ({where})"


def _cells(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(";") if x.strip()]


def athena_register(register: Path = REGISTER) -> dict[str, AthenaClass]:
    """``vocabulary_id -> AthenaClass`` of every Athena vocabulary the licence register names. A vocabulary loads
    only when it is in a row's ``athena`` column, that row's class is one of :data:`LOADABLE_CLASSES` and its status
    is not ``removed``, and no row names it in ``athena_never`` (never wins)."""
    with register.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out: dict[str, AthenaClass] = {}
    never: dict[str, AthenaClass] = {}  # folded id or alias -> its never entry
    for r in rows:
        for entry in _cells(r.get("athena_never")):
            names = [x.strip() for x in entry.split("|") if x.strip()]
            klass, status = (r.get("class") or "").strip(), (r.get("status") or "").strip()
            c = out.setdefault(names[0], AthenaClass(names[0], r["id"], klass, status, False, tuple(names[1:])))
            for n in names:
                never.setdefault(fold(n), c)
    for r in rows:
        klass, status = (r.get("class") or "").strip(), (r.get("status") or "").strip()
        ok = klass in LOADABLE_CLASSES and status != "removed"
        for v in _cells(r.get("athena")):
            barred = never.get(fold(v))
            if barred is not None:  # never wins, compared folded (case, spaces, full-width, look-alike letters)
                out[v] = AthenaClass(v, barred.row, barred.klass, barred.status, False)
                continue
            have = out.get(v)
            if have is None or (have.loadable and not ok):  # of two athena rows the stricter
                out[v] = AthenaClass(v, r["id"], klass, status, ok)
    return out


def by_fold(register: Mapping[str, AthenaClass]) -> dict[str, AthenaClass]:
    """Every folded name the register knows (ids and aliases) -> its class; a never entry wins a shared name."""
    out: dict[str, AthenaClass] = {}
    for v, c in sorted(register.items(), key=lambda kv: kv[1].loadable):
        for name in (v, *c.aliases):
            out.setdefault(fold(name), c)
    return out


def _allow(register: Path = REGISTER) -> frozenset[str]:
    try:
        return frozenset(v for v, c in athena_register(register).items() if c.loadable)
    except OSError:  # no register beside the code: nothing loads, and load_athena says why
        return frozenset()


ATHENA_ALLOW = _allow()
NOT_LISTED = "not on the list: no licence register row names it"
ATHENA = "ATHENA"
VOCAB_RELEASE = "ATHENA:"  # one release row per loaded vocabulary: its version in the build record
# What the terms of each licensed vocabulary an Athena bundle may hold say (T-307, D-375; public sources, summarised).
# A load records one acknowledgement per such vocabulary of the bundle: a ``tb_vocab_release`` row named
# ``LICENCE:<vocabulary>`` with these terms, the bundle's sha256 and the person who loaded it (:func:`licence_acks`).
LICENCE = "LICENCE:"
ATHENA_TERMS: dict[str, str] = {
    "LOINC": "LOINC, copyright Regenstrief Institute: free for any use including commercial; the LOINC notice and "
             "version are shown wherever LOINC codes are (https://loinc.org/license/)",
    "UCUM": "UCUM, copyright Regenstrief Institute and the UCUM Organization: free use under the UCUM terms of use, "
            "the notice kept (https://ucum.org/license)",
    "RxNorm": "RxNorm, US National Library of Medicine: the RxNorm-sourced content of the bundle (SAB=RXNORM) carries "
              "no licence restriction; other sources inside RxNorm are not part of the Athena bundle "
              "(https://www.nlm.nih.gov/research/umls/rxnorm/)",
    "RxNorm Extension": "RxNorm Extension, OHDSI: distributed with the OMOP vocabularies, free to use "
                        "(https://athena.ohdsi.org)",
    "ATC": "ATC, WHO Collaborating Centre for Drug Statistics Methodology: the codes are used with the WHOCC "
           "attribution; whether TrialBox needs the Centre's permission is open (T-617b) (https://atcddd.fhi.no)",
}  # fmt: skip
ATHENA_FILES = ("VOCABULARY", "CONCEPT", "CONCEPT_RELATIONSHIP", "CONCEPT_SYNONYM", "CONCEPT_ANCESTOR", "DOMAIN",
                "CONCEPT_CLASS", "RELATIONSHIP")  # fmt: skip
_CONCEPT_COLS = ("concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id", "standard_concept",
                 "concept_code", "valid_start_date", "valid_end_date", "invalid_reason")  # fmt: skip
_REL_COLS = ("concept_id_1", "concept_id_2", "relationship_id", "valid_start_date", "valid_end_date", "invalid_reason")
_REQUIRED = {
    "VOCABULARY": ("vocabulary_id", "vocabulary_name"),
    "CONCEPT": ("concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id", "concept_code",
                "valid_start_date", "valid_end_date"),
    "CONCEPT_RELATIONSHIP": ("concept_id_1", "concept_id_2", "relationship_id", "valid_start_date", "valid_end_date"),
    "CONCEPT_SYNONYM": ("concept_id", "concept_synonym_name", "language_concept_id"),
    "CONCEPT_ANCESTOR": ("ancestor_concept_id", "descendant_concept_id", "min_levels_of_separation",
                         "max_levels_of_separation"),
}  # fmt: skip
# the concept-id columns of each side table: a row is kept only when every one is a kept concept
_SIDE = {"CONCEPT_RELATIONSHIP": ("concept_id_1", "concept_id_2"), "CONCEPT_SYNONYM": ("concept_id",),
         "CONCEPT_ANCESTOR": ("ancestor_concept_id", "descendant_concept_id")}  # fmt: skip


def _athena_file(directory: Path, name: str) -> Path | None:
    for f in (directory / f"{name}.csv", directory / f"{name.lower()}.csv"):
        if f.is_file():
            return f
    return None


def read_athena(directory: Path) -> dict[str, list[dict[str, str]]]:
    """The tables of an Athena download as written (tab-separated, a header row, dates ``YYYYMMDD``, no quoting).
    ``VOCABULARY`` and ``CONCEPT`` are required; the others are read when present."""
    out: dict[str, list[dict[str, str]]] = {}
    for name in ATHENA_FILES:
        f = _athena_file(directory, name)
        if f is None:
            if name in ("VOCABULARY", "CONCEPT"):
                raise OmopError(f"Athena bundle {directory}: {name}.csv is missing")
            continue
        try:
            with f.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
                rows = list(reader)
                have = {k.strip().lower() for k in reader.fieldnames or () if k}
        except UnicodeDecodeError:
            raise OmopError(f"Athena bundle refused: {f.name} is not UTF-8 text (an Athena download is)") from None
        lacking = [c for c in _REQUIRED.get(name, ()) if c not in have]
        if lacking:
            raise OmopError(f"Athena bundle {directory}: {name}.csv lacks the column(s) {', '.join(lacking)}")
        out[name] = [{k.strip().lower(): (v or "") for k, v in r.items() if k} for r in rows]
    return out


def athena_sha(directory: Path) -> str:
    h = hashlib.sha256()
    for name in ATHENA_FILES:
        f = _athena_file(directory, name)
        if f is not None:
            h.update(name.encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _day(value: str) -> date:
    v = value.strip().replace("-", "")
    try:
        return date(int(v[:4]), int(v[4:6]), int(v[6:8]))
    except ValueError as exc:
        raise OmopError(f"Athena date {value!r} is not YYYYMMDD") from exc


def _concept_row(r: Mapping[str, str]) -> tuple[Any, ...]:
    return (int(r["concept_id"]), r["concept_name"][:255], r["domain_id"], r["vocabulary_id"],
            r["concept_class_id"], r.get("standard_concept") or None, r["concept_code"][:50],
            _day(r["valid_start_date"]), _day(r["valid_end_date"]), r.get("invalid_reason") or None)  # fmt: skip


def athena_version(tables: Mapping[str, list[dict[str, str]]]) -> str:
    """The bundle's version: the ``None`` vocabulary's (OMOP's convention for ``cdm_source.vocabulary_version``),
    else the versions of its vocabularies."""
    vocabs = {r["vocabulary_id"]: r.get("vocabulary_version") or "" for r in tables.get("VOCABULARY", [])}
    if vocabs.get("None"):
        return vocabs["None"]
    return "; ".join(f"{k} {v}" for k, v in sorted(vocabs.items()) if v) or "unversioned"


@dataclass
class AthenaSelection:
    """What a download holds against the list: the vocabularies loaded (with their versions) and those skipped,
    each with its reason and the rows left out."""

    release: str
    loaded: dict[str, str]  # vocabulary_id -> vocabulary_version
    skipped: dict[str, str]  # vocabulary_id -> reason
    concepts: dict[str, int]  # vocabulary_id -> concepts in the download
    rows_skipped: dict[str, int]  # table -> rows left out
    removed: dict[str, int] = field(default_factory=dict)  # vocabulary -> its concepts an earlier load left, deleted
    canonical: set[str] = field(default_factory=set)  # the register's ids of the skipped labels it knows

    def as_dict(self) -> dict[str, Any]:
        return {
            "release": self.release,
            "loaded": [{"vocabulary": v, "version": self.loaded[v], "concepts": self.concepts.get(v, 0)}
                       for v in sorted(self.loaded)],
            "skipped": [{"vocabulary": v, "reason": self.skipped[v], "concepts": self.concepts.get(v, 0)}
                        for v in sorted(self.skipped)],
            "counts": {"loaded": len(self.loaded), "skipped": len(self.skipped),
                       "skipped_not_on_the_list": sum(r.startswith("not on the list") for r in self.skipped.values()),
                       "skipped_must_not_ship": sum(r.startswith("licence class") for r in self.skipped.values())},
            "rows_skipped": dict(sorted(self.rows_skipped.items())),
            "removed_from_the_box": dict(sorted(self.removed.items())),
        }  # fmt: skip


def _whole(table: str, line: int, col: str, value: str | None) -> int:
    try:
        return int((value or "").strip())
    except ValueError:
        msg = f"Athena bundle refused: {table}.csv line {line}: {col} {value!r} is not a whole number"
        raise OmopError(msg) from None


def _why(label: str, allow: frozenset[str], folded: Mapping[str, AthenaClass]) -> str:
    c = folded.get(fold(label))
    if c is None:
        return NOT_LISTED
    if not c.loadable:
        return c.reason()
    if label == c.vocabulary:
        return f"not on the list this load was given (register row {c.row} allows it)"
    return f"not on the list: the label {label!r} is not exactly {c.vocabulary!r} (register row {c.row})"


def select_athena(
    tables: dict[str, list[dict[str, str]]], allow: frozenset[str], register: Mapping[str, AthenaClass]
) -> AthenaSelection:
    """Keep, in place, only what is on ``allow``: a ``VOCABULARY`` or ``CONCEPT`` row whose ``vocabulary_id`` is
    exactly an allowed id, and a relationship, synonym or ancestor row whose every concept id (as a number) is a kept
    concept. Every other label is classified with case and spaces folded (``'snomed '`` is SNOMED: must not ship)."""
    folded = by_fold(register)
    versions = {r["vocabulary_id"]: r.get("vocabulary_version") or "" for r in tables["VOCABULARY"]}
    counts: dict[str, int] = {}
    for r in tables["CONCEPT"]:
        counts[r["vocabulary_id"]] = counts.get(r["vocabulary_id"], 0) + 1
    found = set(versions) | set(counts)
    skipped = {v: _why(v, allow, folded) for v in sorted(found - allow)}
    sel = AthenaSelection(athena_version(tables), {v: versions.get(v, "") for v in sorted(found & allow)}, skipped,
                          counts, {})  # fmt: skip
    known = [folded.get(fold(v)) for v in skipped]
    sel.canonical = {k.vocabulary for k in known if k is not None and not k.loadable}
    kept: list[dict[str, str]] = []
    kept_ids: set[int] = set()
    for line, r in enumerate(tables["CONCEPT"], start=2):
        cid = _whole("CONCEPT", line, "concept_id", r.get("concept_id"))
        if r["vocabulary_id"] in allow:
            kept.append(r)
            kept_ids.add(cid)
    news = {"CONCEPT": kept, "VOCABULARY": [r for r in tables["VOCABULARY"] if r["vocabulary_id"] in allow]}
    for name, cols in _SIDE.items():
        if name in tables:
            news[name] = [r for line, r in enumerate(tables[name], start=2)
                          if all(_whole(name, line, c, r.get(c)) in kept_ids for c in cols)]  # fmt: skip
    for name, rows in news.items():
        if len(tables[name]) - len(rows):
            sel.rows_skipped[name] = len(tables[name]) - len(rows)
        tables[name] = rows
    stray = {r["vocabulary_id"] for n in ("CONCEPT", "VOCABULARY") for r in tables[n]} - allow
    if stray:  # cannot happen; a load never goes on with a row off the list
        raise OmopError(f"Athena bundle refused: rows of {', '.join(sorted(stray))} left after selection")
    return sel


def load_athena(
    db: Database,
    directory: Path,
    *,
    allow: frozenset[str] | None = None,
    strict: bool = False,
    by: str = "loader",
    source: str | None = None,
    register: Path = REGISTER,
) -> LoadResult:
    """An Athena bundle the site downloaded (or a vendor built) into the vocabulary tables (STD-030, STD-034).

    The vocabularies on ``allow`` (default: the licence register's column ``athena``, :func:`athena_register`) load;
    every other vocabulary is skipped with its reason (no register row names it; or its row is licence class c, must
    not ship, the site loading it under its own licence) and its rows are left out, with every relationship,
    synonym and ancestor row that touches one of its concepts (:func:`select_athena`). ``LoadResult.athena`` lists
    what loaded with its version and what was skipped and why, with counts. ``strict`` (a release build, STD-034 as
    first written) refuses the whole bundle instead when it holds any vocabulary off the list. A concept id of the
    TrialBox range (>= 2e9) refuses the bundle either way.

    The loaded concepts replace the rows of the same id (the seeded OHDSI concepts among them), their vocabulary,
    domain, class and relationship rows replace theirs, and their relationships, synonyms and ancestors replace those
    of an earlier bundle (rows between two concepts below 2e9). A release row ``ATHENA`` records the content's
    sha256 and :func:`athena_version`, and one row ``ATHENA:<vocabulary>`` per loaded vocabulary its version (the
    build record); the same content again changes nothing. Afterwards a source concept reaches its standard concept
    through ``Maps to`` (an ATC class its RxNorm ingredient, :class:`omop.vocab.Concepts`)."""
    classes = athena_register(register) if register.is_file() else {}
    if allow is None:
        allow = frozenset(v for v, c in classes.items() if c.loadable)
        if not allow:
            raise OmopError(f"Athena bundle refused: no licence register at {register} names a loadable vocabulary "
                            "(column athena)")  # fmt: skip
    folded = by_fold(classes)
    allow = frozenset(v for v in allow if (c := folded.get(fold(v))) is None or c.loadable)  # never wins over allow
    sha = athena_sha(directory)
    tables = read_athena(directory)
    found = {r["vocabulary_id"] for r in tables["VOCABULARY"]} | {r["vocabulary_id"] for r in tables["CONCEPT"]}
    refused = sorted(found - allow)
    if refused and strict:
        raise OmopError(f"Athena bundle refused: vocabularies not on the allow-list: {', '.join(refused)} "
                        "(STD-034; download the bundle without them)")  # fmt: skip
    selection = select_athena(tables, allow, classes)
    if selection.skipped:  # what was loaded is part of the release: a wider list later loads again
        sha = hashlib.sha256(f"{sha}\0{','.join(sorted(selection.loaded))}".encode()).hexdigest()
    try:
        concepts = [_concept_row(r) for r in tables["CONCEPT"]]
    except (KeyError, ValueError) as exc:
        raise OmopError(f"Athena bundle refused: CONCEPT.csv: a malformed value ({type(exc).__name__})") from None
    high = [c[0] for c in concepts if c[0] >= LOCAL_MIN or c[0] < 0]
    if high:
        raise OmopError(f"Athena bundle refused: concept ids outside the OHDSI range (e.g. {high[0]}); "
                        f"ids >= {LOCAL_MIN:,} are TrialBox's own (D-144)")  # fmt: skip
    if not concepts:
        raise OmopError(f"Athena bundle refused: none of its vocabularies is on the list (skipped: "
                        f"{', '.join(refused)})")  # fmt: skip
    version = athena_version(tables)
    res = LoadResult(ATHENA, sha, False, athena=selection.as_dict())
    try:
        return _load_athena_rows(db, directory, tables, concepts, selection, res, allow, version, sha, by, source,
                                 folded)  # fmt: skip
    except (KeyError, ValueError) as exc:
        msg = f"Athena bundle refused: {directory}: a malformed value ({type(exc).__name__})"
        raise OmopError(msg) from None


def _load_athena_rows(
    db: Database, directory: Path, tables: dict[str, list[dict[str, str]]], concepts: list[tuple[Any, ...]],
    selection: AthenaSelection, res: LoadResult, allow: frozenset[str], version: str, sha: str, by: str,
    source: str | None, folded: Mapping[str, AthenaClass],
) -> LoadResult:  # fmt: skip
    with db.transaction() as tx:
        _prepare(tx)
        if not _release(tx, ATHENA, sha, "None", version, source or directory.name, len(concepts), by):
            return res
        res.new = True
        ids = sorted({c[0] for c in concepts})
        tx.execute("CREATE TEMP TABLE tb_athena_concept (LIKE concept) ON COMMIT DROP")
        tx.copy_rows("tb_athena_concept", _CONCEPT_COLS, concepts)
        res.changed = int(tx.fetchval(
            "SELECT count(*) FROM tb_athena_concept a LEFT JOIN concept c ON c.concept_id = a.concept_id WHERE "
            "c.concept_id IS NULL OR (c.concept_name, c.domain_id, c.vocabulary_id, c.concept_class_id, "
            "coalesce(c.standard_concept, ''), c.concept_code, c.valid_start_date, c.valid_end_date, "
            "coalesce(c.invalid_reason, '')) IS DISTINCT FROM (a.concept_name, a.domain_id, a.vocabulary_id, "
            "a.concept_class_id, coalesce(a.standard_concept, ''), a.concept_code, a.valid_start_date, "
            "a.valid_end_date, coalesce(a.invalid_reason, ''))"
        ))  # fmt: skip
        tx.execute("DELETE FROM concept WHERE concept_id IN (SELECT concept_id FROM tb_athena_concept)")
        tx.execute(f"INSERT INTO concept ({', '.join(_CONCEPT_COLS)}) SELECT {', '.join(_CONCEPT_COLS)} "
                   "FROM tb_athena_concept")  # fmt: skip
        for r in tables["VOCABULARY"]:
            vid = r["vocabulary_id"]
            tx.execute("DELETE FROM vocabulary WHERE vocabulary_id = ?", (vid,))
            tx.execute(
                "INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
                "vocabulary_concept_id) VALUES (?, ?, ?, ?, ?)",
                (vid, r["vocabulary_name"][:255], (r.get("vocabulary_reference") or None),
                 (r.get("vocabulary_version") or None), int(r.get("vocabulary_concept_id") or 0)),
            )  # fmt: skip
        _athena_small(tx, tables, concepts)
        rels = [(int(r["concept_id_1"]), int(r["concept_id_2"]), r["relationship_id"], _day(r["valid_start_date"]),
                 _day(r["valid_end_date"]), r.get("invalid_reason") or None)
                for r in tables.get("CONCEPT_RELATIONSHIP", [])]  # fmt: skip
        tx.execute("DELETE FROM concept_relationship WHERE concept_id_1 < ? AND concept_id_2 < ?",
                   (LOCAL_MIN, LOCAL_MIN))  # fmt: skip
        tx.copy_rows("concept_relationship", _REL_COLS, rels)
        if "CONCEPT_SYNONYM" in tables:
            tx.execute("DELETE FROM concept_synonym WHERE concept_id = ANY(?)", (ids,))
            tx.copy_rows("concept_synonym", ["concept_id", "concept_synonym_name", "language_concept_id"],
                         [(int(r["concept_id"]), r["concept_synonym_name"][:1000], int(r["language_concept_id"]))
                          for r in tables["CONCEPT_SYNONYM"]])  # fmt: skip
        if "CONCEPT_ANCESTOR" in tables:
            tx.execute("DELETE FROM concept_ancestor WHERE ancestor_concept_id < ? AND descendant_concept_id < ?",
                       (LOCAL_MIN, LOCAL_MIN))  # fmt: skip
            tx.copy_rows("concept_ancestor", ["ancestor_concept_id", "descendant_concept_id",
                                              "min_levels_of_separation", "max_levels_of_separation"],
                         [(int(r["ancestor_concept_id"]), int(r["descendant_concept_id"]),
                           int(r["min_levels_of_separation"]), int(r["max_levels_of_separation"]))
                          for r in tables["CONCEPT_ANCESTOR"]])  # fmt: skip
        res.concepts = len(concepts)
        _acknowledge(tx, tables, sha, by)
        _record_vocabularies(tx, selection, sha, by)
        selection.removed = _remove_skipped(tx, selection, allow, folded)
        res.athena = selection.as_dict()
        _check_never_standard(tx)
    return res


def _acknowledge(tx: Any, tables: Mapping[str, list[dict[str, str]]], sha: str, by: str) -> None:
    """One acknowledgement row per licensed vocabulary of the bundle (:data:`ATHENA_TERMS`); a vocabulary the bundle
    no longer holds keeps its old row, inactive."""
    versions = {r["vocabulary_id"]: (r.get("vocabulary_version") or "") for r in tables["VOCABULARY"]}
    held = {r["vocabulary_id"] for r in tables["VOCABULARY"]} | {r["vocabulary_id"] for r in tables["CONCEPT"]}
    for vid, terms in ATHENA_TERMS.items():
        name = LICENCE + vid
        if vid not in held:
            tx.execute("UPDATE tb_vocab_release SET active = false WHERE release_name = ?", (name,))
            continue
        _release(tx, name, sha, vid, versions.get(vid) or "unversioned", terms, 0, by)


def _remove_skipped(
    tx: Any, selection: AthenaSelection, allow: frozenset[str], folded: Mapping[str, AthenaClass]
) -> dict[str, int]:
    """The summary is true of the box: concepts (OHDSI range) of a vocabulary this load skipped, and of every
    vocabulary the register says never loads, left by an earlier load (even when this download does not hold it),
    are deleted with their synonyms, relationships and ancestors and their vocabulary row; returns the counts.
    TrialBox's own concepts (>= 2e9) and the seeded TB-* vocabularies are never touched."""
    on_box = {str(v) for (v,) in tx.fetchall("SELECT DISTINCT vocabulary_id FROM concept WHERE concept_id > 0 AND "
                                             "concept_id < ?", (LOCAL_MIN,))}  # fmt: skip
    barred = {v for v in on_box if (c := folded.get(fold(v))) is not None and not c.loadable}
    gone = sorted((set(selection.skipped) | selection.canonical | barred) - allow)
    removed: dict[str, int] = {}
    for vid in gone:
        rows = tx.fetchall("SELECT concept_id FROM concept WHERE vocabulary_id = ? AND concept_id > 0 AND "
                           "concept_id < ?", (vid, LOCAL_MIN))  # fmt: skip
        ids = [int(i) for (i,) in rows]
        if ids:
            tx.execute("DELETE FROM concept_synonym WHERE concept_id = ANY(?)", (ids,))
            tx.execute("DELETE FROM concept_relationship WHERE concept_id_1 = ANY(?) OR concept_id_2 = ANY(?)",
                       (ids, ids))  # fmt: skip
            tx.execute("DELETE FROM concept_ancestor WHERE ancestor_concept_id = ANY(?) OR descendant_concept_id = "
                       "ANY(?)", (ids, ids))  # fmt: skip
            tx.execute("DELETE FROM concept WHERE concept_id = ANY(?)", (ids,))
            removed[vid] = len(ids)
        if tx.fetchone("SELECT 1 FROM concept WHERE vocabulary_id = ?", (vid,)) is None:
            tx.execute("DELETE FROM vocabulary WHERE vocabulary_id = ?", (vid,))
    return removed


def _record_vocabularies(tx: Any, selection: AthenaSelection, sha: str, by: str) -> None:
    """The build record: one ``ATHENA:<vocabulary>`` release row per loaded vocabulary (its version, the download's
    release, its concepts); a vocabulary this download no longer brings keeps its old row, inactive."""
    for (name,) in tx.fetchall("SELECT DISTINCT release_name FROM tb_vocab_release WHERE release_name LIKE ? AND "
                               "active", (VOCAB_RELEASE + "%",)):  # fmt: skip
        if str(name)[len(VOCAB_RELEASE) :] not in selection.loaded:
            tx.execute("UPDATE tb_vocab_release SET active = false WHERE release_name = ?", (name,))
    for vid, ver in selection.loaded.items():
        _release(tx, VOCAB_RELEASE + vid, sha, vid, ver or "unversioned", f"Athena release {selection.release}",
                 selection.concepts.get(vid, 0), by)  # fmt: skip


def licence_acks(db: Any) -> list[dict[str, Any]]:
    """The licence acknowledgements of the active Athena bundle: vocabulary, version, the terms, who loaded it, when."""
    rows = db.fetchall(
        "SELECT vocabulary_id, version, source, loaded_by, loaded_at FROM tb_vocab_release "
        "WHERE release_name LIKE ? AND active ORDER BY vocabulary_id", (LICENCE + "%",))  # fmt: skip
    return [{"vocabulary": v, "version": ver, "terms": t, "acknowledged_by": by, "at": str(at)}
            for v, ver, t, by, at in rows]  # fmt: skip


def _athena_small(tx: Any, tables: Mapping[str, list[dict[str, str]]], concepts: list[tuple[Any, ...]]) -> None:
    """Domain, concept-class and relationship rows: the bundle's replace theirs; one the bundle names without its
    row gets a stand-in (concept 0), as :func:`omop.vocab.seed` does."""
    for r in tables.get("DOMAIN", []):
        tx.execute("DELETE FROM domain WHERE domain_id = ?", (r["domain_id"],))
        tx.execute("INSERT INTO domain (domain_id, domain_name, domain_concept_id) VALUES (?, ?, ?)",
                   (r["domain_id"], r["domain_name"][:255], int(r.get("domain_concept_id") or 0)))  # fmt: skip
    for r in tables.get("CONCEPT_CLASS", []):
        tx.execute("DELETE FROM concept_class WHERE concept_class_id = ?", (r["concept_class_id"],))
        tx.execute(
            "INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
            "VALUES (?, ?, ?)",
            (r["concept_class_id"], r["concept_class_name"][:255], int(r.get("concept_class_concept_id") or 0)),
        )
    for r in tables.get("RELATIONSHIP", []):
        tx.execute("DELETE FROM relationship WHERE relationship_id = ?", (r["relationship_id"],))
        tx.execute(
            "INSERT INTO relationship (relationship_id, relationship_name, is_hierarchical, defines_ancestry, "
            "reverse_relationship_id, relationship_concept_id) VALUES (?, ?, ?, ?, ?, ?)",
            (r["relationship_id"], r["relationship_name"][:255], r.get("is_hierarchical") or "0",
             r.get("defines_ancestry") or "0", r.get("reverse_relationship_id") or r["relationship_id"],
             int(r.get("relationship_concept_id") or 0)),
        )  # fmt: skip
    for d in sorted({c[2] for c in concepts}):
        tx.execute("INSERT INTO domain (domain_id, domain_name, domain_concept_id) SELECT ?, ?, 0 WHERE NOT EXISTS "
                   "(SELECT 1 FROM domain WHERE domain_id = ?)", (d, d, d))  # fmt: skip
    for k in sorted({c[4] for c in concepts}):
        tx.execute("INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
                   "SELECT ?, ?, 0 WHERE NOT EXISTS (SELECT 1 FROM concept_class WHERE concept_class_id = ?)",
                   (k, k, k))  # fmt: skip
    for rid in sorted({r["relationship_id"] for r in tables.get("CONCEPT_RELATIONSHIP", [])}):
        tx.execute(
            "INSERT INTO relationship (relationship_id, relationship_name, is_hierarchical, defines_ancestry, "
            "reverse_relationship_id, relationship_concept_id) SELECT ?, ?, '0', '0', ?, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM relationship WHERE relationship_id = ?)",
            (rid, rid, rid, rid),
        )


def athena_loaded(db: Any) -> dict[str, str]:
    """``vocabulary_id -> version`` of the active Athena bundle's vocabularies (empty when none is loaded)."""
    if db.fetchone("SELECT 1 FROM tb_vocab_release WHERE release_name = ? AND active", (ATHENA,)) is None:
        return {}
    return {str(v): str(ver or "") for v, ver in db.fetchall(
        "SELECT DISTINCT v.vocabulary_id, v.vocabulary_version FROM vocabulary v JOIN concept c ON "
        "c.vocabulary_id = v.vocabulary_id WHERE c.concept_id < ? AND c.concept_id > 0", (LOCAL_MIN,))}  # fmt: skip
