"""The clinical item catalogue loaded into the OMOP vocabulary (T-107, WS-04.1, D-353).

Each of the catalogue's items (``catalogue/items.csv``, read and checked by :mod:`tb_common.catalogue`) resolves to
one concept and one domain:

* a **LOINC item** to the standard LOINC concept the vocabulary holds for its code (the Athena bundle,
  :func:`omop.vocab_load.load_athena`). A code the vocabulary lacks is listed as **unmapped**, never invented: the
  report names the item and the code, and the item resolves once the bundle that holds the code is loaded;
* a **local item** to its TrialBox shared concept (vocabulary ``TB-SHARED``, class ``TB Catalogue Item``, the item
  id as ``concept_code``, the English name, the Japanese and Chinese names as synonyms), at the id the catalogue
  gives it (2,000,001,001 and up, the same on every box). A local concept is never standard (D-301).

Ids are stable across loads. A second load of the same file changes nothing. A load that would move an item to
another id, or give an id that already holds another code to a new item, is refused before anything is written
(``CAT-RENUMBER``); a catalogue file that breaks the id rules is refused whole (``CAT-FILE``). Each load that adds
or changes rows is a ``tb_vocab_release`` row named ``CATALOGUE``.

The report (:class:`CatalogueReport`) is the coverage report of this box: resolved, local and unmapped items, the
unmapped ones per specialty. Command line: ``python -m omop.catalogue_load`` (``TB_OMOP_DB_URL`` or ``--db``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_common import catalogue
from tb_common.db import Database

from omop.schema import OmopError
from omop.vocab import VALID_FROM, VALID_TO, seed
from omop.vocab_load import JA, ZH, _release, _synonyms

RELEASE = "CATALOGUE"
VOCAB = "TB-SHARED"
CONCEPT_CLASS = "TB Catalogue Item"


class CatalogueRefused(OmopError):
    def __init__(self, code: str, problems: list[str]) -> None:
        super().__init__(f"{code}: " + "; ".join(problems[:5]))
        self.code = code
        self.problems = problems


@dataclass
class CatalogueReport:
    items: int = 0
    resolved: dict[str, int] = field(default_factory=dict)  # item id -> concept id
    domains: dict[str, str] = field(default_factory=dict)  # item id -> OMOP domain
    local: int = 0
    loinc: int = 0
    unmapped: list[dict[str, str]] = field(default_factory=list)  # {item, loinc, specialties}
    added: int = 0
    new_release: bool = False
    sha256: str = ""

    @property
    def unresolved(self) -> int:
        return len(self.unmapped)

    def unmapped_by_specialty(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for u in self.unmapped:
            for s in u["specialties"].split(";"):
                out.setdefault(s, []).append(u["item"])
        return dict(sorted(out.items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "concepts": len(self.resolved),
            "local": self.local,
            "loinc": self.loinc,
            "unresolved": self.unresolved,
            "unmapped": self.unmapped,
            "unmapped_by_specialty": self.unmapped_by_specialty(),
            "added": self.added,
            "new_release": self.new_release,
            "sha256": self.sha256,
        }


def _sha(folder: Path) -> str:
    return hashlib.sha256((folder / "items.csv").read_bytes()).hexdigest()


def _check_ids(tx: Any, local: list[catalogue.Item]) -> None:
    """``CAT-RENUMBER`` when an item already holds another id, or its id holds another code."""
    by_code = {
        str(code): int(cid)
        for code, cid in tx.fetchall(
            "SELECT concept_code, concept_id FROM concept WHERE vocabulary_id = ? AND concept_class_id = ?",
            (VOCAB, CONCEPT_CLASS),
        )
    }
    ids = [it.local_id for it in local]
    by_id = {
        int(cid): (str(code), str(voc))
        for cid, code, voc in tx.fetchall(
            "SELECT concept_id, concept_code, vocabulary_id FROM concept WHERE concept_id = ANY(?)", (ids,)
        )
    }
    problems = []
    for it in local:
        have = by_code.get(it.id)
        if have is not None and have != it.local_id:
            problems.append(f"{it.id} is concept {have}; the file gives {it.local_id} (ids are never renumbered)")
        held = by_id.get(int(it.local_id or 0))
        if held is not None and held != (it.id, VOCAB):
            problems.append(f"{it.local_id} already holds {held[1]} {held[0]}, not {it.id}")
    if problems:
        raise CatalogueRefused("CAT-RENUMBER", problems)


def load(db: Database, folder: Path | None = None, by: str = "catalogue_load") -> CatalogueReport:
    """Load the catalogue in ``folder`` (the shipped one by default); idempotent. See the module text."""
    folder = folder or catalogue.catalogue_dir()
    try:
        items = catalogue.read(folder)
    except catalogue.CatalogueError as exc:
        raise CatalogueRefused("CAT-FILE", exc.problems) from exc
    seed(db)
    rep = CatalogueReport(items=len(items), sha256=_sha(folder))
    local = [it for it in items if it.local_id is not None]
    with db.transaction() as tx:
        _check_ids(tx, local)
        for dom in sorted({it.domain for it in items}):
            tx.execute(
                "INSERT INTO domain (domain_id, domain_name, domain_concept_id) SELECT ?, ?, 0 WHERE NOT EXISTS "
                "(SELECT 1 FROM domain WHERE domain_id = ?)",
                (dom, dom, dom),
            )
        tx.execute(
            "INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
            "SELECT ?, ?, 0 WHERE NOT EXISTS (SELECT 1 FROM concept_class WHERE concept_class_id = ?)",
            (CONCEPT_CLASS, CONCEPT_CLASS, CONCEPT_CLASS),
        )
        have = {
            int(r[0])
            for r in tx.fetchall(
                "SELECT concept_id FROM concept WHERE concept_id = ANY(?)", ([i.local_id for i in local],)
            )
        }
        for it in local:
            cid = int(it.local_id or 0)
            if cid not in have:
                tx.execute(
                    "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
                    "standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason) "
                    "VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL)",
                    (cid, it.names["en"][:255], it.domain, VOCAB, CONCEPT_CLASS, it.id, VALID_FROM, VALID_TO),
                )
                rep.added += 1
            rep.resolved[it.id] = cid
            rep.domains[it.id] = it.domain
            rep.local += 1
        for lang, names in ((JA, {i.local_id: i.names["ja"] for i in local if i.names["ja"]}),
                            (ZH, {i.local_id: i.names["zh-TW"] for i in local if i.names["zh-TW"]})):  # fmt: skip
            _synonyms(tx, {int(k or 0): v for k, v in names.items()}, lang)
        codes = sorted({it.loinc for it in items if it.loinc})
        std = {
            str(code): (int(cid), str(dom))
            for code, cid, dom in tx.fetchall(
                "SELECT concept_code, concept_id, domain_id FROM concept WHERE vocabulary_id = 'LOINC' "
                "AND concept_code = ANY(?) AND standard_concept = 'S' AND invalid_reason IS NULL",
                (codes,),
            )
        }
        for it in items:
            if not it.loinc:
                continue
            hit = std.get(it.loinc)
            if hit is None:
                rep.unmapped.append({"item": it.id, "loinc": it.loinc, "specialties": ";".join(it.specialties)})
                continue
            rep.resolved[it.id] = hit[0]
            rep.domains[it.id] = hit[1]
            rep.loinc += 1
        rep.new_release = _release(tx, RELEASE, rep.sha256, VOCAB, rep.sha256[:12], str(folder.name), len(items), by)
    return rep


def main(argv: list[str] | None = None) -> int:
    from omop import schema

    p = argparse.ArgumentParser(prog="python -m omop.catalogue_load", description=__doc__.split("\n\n")[0])
    p.add_argument("--db", default=os.environ.get("TB_OMOP_DB_URL") or os.environ.get("TB_DB_URL"))
    p.add_argument("--catalogue", type=Path, default=None)
    a = p.parse_args(argv)
    if not a.db:
        print("no database: give --db or set TB_OMOP_DB_URL", file=sys.stderr)
        return 2
    db = schema.connect(a.db)
    try:
        rep = load(db, a.catalogue)
    except CatalogueRefused as exc:
        print(json.dumps({"refused": exc.code, "problems": exc.problems}, ensure_ascii=False, indent=1))
        return 1
    finally:
        db.close()
    print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
