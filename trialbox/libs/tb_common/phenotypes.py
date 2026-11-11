"""The catalogue's phenotypes with their status, and the ICD-10-CM run (T-307, WS-04.2, D-375).

* :func:`phenotypes` reads all of ``catalogue/phenotypes.csv`` (164 rows) and joins each OHDSI-linked one to its
  ICD-10-CM concept set in ``phenotype_icd10cm.csv`` (D-180). Its ``status`` is ``synthetic`` when
  ``phenotype_status.csv`` says the set was run on the synthetic hospital with the expected hits, else
  ``not validated here``. ``synthetic`` says the codes find the planted patients; it does not say the definition is
  clinically right, and it changes nothing about ``may_exclude`` (unknown never excludes).
* :func:`run` gives the patients whose diagnosis codes fall in a phenotype's set: a code matches an included code
  or category by prefix (dots ignored) and no excluded one. A local phenotype (no ICD-10-CM set) never runs.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tb_common import catalogue

SYNTHETIC = "synthetic"
NOT_VALIDATED = "not validated here"


@dataclass(frozen=True)
class Phenotype:
    id: str
    name: str
    specialties: tuple[str, ...]
    cohort_ids: tuple[str, ...]
    library_status: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    codes_verified: bool
    may_exclude: bool
    status: str
    status_note: str

    @property
    def runnable(self) -> bool:
        return bool(self.include)

    def matches(self, code: str) -> bool:
        c = _norm(code)
        if not c or not self.include:
            return False
        if any(c.startswith(_norm(x)) for x in self.exclude):
            return False
        return any(c.startswith(_norm(x)) for x in self.include)


def _norm(code: str) -> str:
    return code.strip().upper().replace(".", "")


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _split(v: str | None) -> tuple[str, ...]:
    return tuple(x.strip() for x in (v or "").split(";") if x.strip())


def phenotypes(folder: Path | None = None) -> list[Phenotype]:
    folder = folder or catalogue.catalogue_dir()
    sets = {r["phenotype_id"]: r for r in _read(folder / "phenotype_icd10cm.csv")}
    status = {r["phenotype_id"]: r for r in _read(folder / "phenotype_status.csv")}
    unknown = sorted(set(status) - {r["id"] for r in _read(folder / "phenotypes.csv")})
    if unknown:
        raise catalogue.CatalogueError([f"phenotype_status.csv names {p}, which phenotypes.csv lacks" for p in unknown])
    out = []
    for r in _read(folder / "phenotypes.csv"):
        s = sets.get(r["id"], {})
        st = status.get(r["id"], {})
        ph = Phenotype(
            id=r["id"],
            name=r["name_en"],
            specialties=_split(r.get("specialty")),
            cohort_ids=_split(r.get("ohdsi_pl_cohort_ids")),
            library_status=(r.get("ohdsi_status") or "").strip(),
            include=_split(s.get("icd10cm_include")),
            exclude=_split(s.get("icd10cm_exclude")),
            codes_verified=(s.get("codes_verified") or "") == "yes",
            may_exclude=(r.get("may_exclude") or "") == "yes",
            status=SYNTHETIC if (st.get("status") or "") == SYNTHETIC else NOT_VALIDATED,
            status_note=(st.get("note") or "").strip(),
        )
        if ph.status == SYNTHETIC and not ph.runnable:
            raise catalogue.CatalogueError([f"{ph.id}: marked {SYNTHETIC} but has no ICD-10-CM set to run"])
        out.append(ph)
    return out


def run(ph: Phenotype, diagnoses: Iterable[tuple[str, str]]) -> set[str]:
    """The patients (first of each ``(patient, code)`` pair) with at least one code in ``ph``'s set."""
    return {pid for pid, code in diagnoses if ph.matches(code)}
