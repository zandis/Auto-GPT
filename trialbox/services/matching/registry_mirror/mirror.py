"""Read-only access to the local mirror of ClinicalTrials.gov API v2 study records (FR-M5-9).

Accepted files (``*.json`` in a directory, or explicit paths):

* a cached record ``{"nct_id", "retrieved", "source_url", "study": {...}}`` (the layout of
  ``tests/fixtures/open_data/ctgov_*.json`` and of the mirror refresh job);
* a bare API v2 study ``{"protocolSection": {...}}``;
* an API v2 page ``{"studies": [...]}``.

The manifest states how many records the mirror holds, a sha256 over their canonical JSON and the latest fetch time,
so a run can record exactly which registry content it matched against.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from matching.registry_mirror.convert import to_corpus_entry, to_trial

RECRUITING = frozenset({"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"})
_AGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(year|month|week|day|hour|minute)s?\s*$", re.I)
_UNIT_YEARS = {"year": 1.0, "month": 1 / 12, "week": 7 / 365.25, "day": 1 / 365.25, "hour": 1 / 8766, "minute": 0.0}


@dataclass(frozen=True)
class MirrorRecord:
    nct_id: str
    study: dict[str, Any]
    fetched: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class MirrorManifest:
    records: int
    sha256: str
    fetched_at: str  # latest fetch time of any record ("" when unknown)


def _age_years(text: str | None) -> float | None:
    m = _AGE.match(text or "")
    return float(m.group(1)) * _UNIT_YEARS[m.group(2).lower()] if m else None


def _records_in(doc: Any, path: Path) -> Iterator[MirrorRecord]:
    if isinstance(doc, dict) and "study" in doc:
        study = doc["study"]
        nct = str(doc.get("nct_id") or study.get("protocolSection", {}).get("identificationModule", {}).get("nctId"))
        yield MirrorRecord(nct, study, str(doc.get("retrieved") or ""), str(doc.get("source_url") or ""))
    elif isinstance(doc, dict) and "protocolSection" in doc:
        yield MirrorRecord(str(doc["protocolSection"].get("identificationModule", {}).get("nctId", "")), doc)
    elif isinstance(doc, dict) and isinstance(doc.get("studies"), list):
        for s in doc["studies"]:
            yield from _records_in(s, path)
    else:
        raise ValueError(f"{path}: not a ClinicalTrials.gov API v2 study record")


class RegistryMirror:
    """An in-memory view of the stored mirror. It never fetches anything."""

    def __init__(self, records: Iterable[MirrorRecord]) -> None:
        self._records: dict[str, MirrorRecord] = {}
        for r in records:
            if not r.nct_id.startswith("NCT"):
                raise ValueError(f"record without an NCT id: {r.nct_id!r}")
            old = self._records.get(r.nct_id)
            if old is None or r.fetched >= old.fetched:  # the newest fetch of a study wins
                self._records[r.nct_id] = r

    @classmethod
    def from_files(cls, paths: Iterable[Path | str]) -> RegistryMirror:
        recs: list[MirrorRecord] = []
        for p in paths:
            path = Path(p)
            recs.extend(_records_in(json.loads(path.read_text(encoding="utf-8")), path))
        return cls(recs)

    @classmethod
    def from_dir(cls, directory: Path | str, pattern: str = "*.json") -> RegistryMirror:
        return cls.from_files(sorted(Path(directory).glob(pattern)))

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, nct_id: object) -> bool:
        return nct_id in self._records

    def manifest(self) -> MirrorManifest:
        h = hashlib.sha256()
        for nct in sorted(self._records):
            h.update(nct.encode())
            h.update(json.dumps(self._records[nct].study, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        fetched = max((r.fetched for r in self._records.values()), default="")
        return MirrorManifest(len(self._records), "sha256:" + h.hexdigest(), fetched)

    def record(self, nct_id: str) -> MirrorRecord | None:
        return self._records.get(nct_id)

    def get(self, nct_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Trial dicts for the given NCT ids that the mirror holds (missing ids are left out)."""
        return {n: to_trial(self._records[n].study) for n in nct_ids if n in self._records}

    def trials(
        self,
        *,
        recruiting_only: bool = False,
        countries: Sequence[str] | None = None,
        age: float | None = None,
        sex: str | None = None,
    ) -> list[dict[str, Any]]:
        """Trial dicts filtered by status, country (any site in the list), age in years and sex (``male`` /
        ``female``), in NCT id order. Trials without eligibility text are left out (nothing to match)."""
        out = []
        for nct in sorted(self._records):
            study = self._records[nct].study
            p = study.get("protocolSection", {})
            if recruiting_only and p.get("statusModule", {}).get("overallStatus") not in RECRUITING:
                continue
            elig = p.get("eligibilityModule", {})
            if age is not None:
                lo, hi = _age_years(elig.get("minimumAge")), _age_years(elig.get("maximumAge"))
                if (lo is not None and age < lo) or (hi is not None and age > hi):
                    continue
            if sex and elig.get("sex") not in (None, "", "ALL", sex.upper()):
                continue
            t = to_trial(study)
            if countries and not set(countries) & set(t["countries"]):
                continue
            if t["inclusion_criteria"] or t["exclusion_criteria"]:
                out.append(t)
        return out

    def corpus(self, **filters: Any) -> list[dict[str, Any]]:
        """Corpus entries (``{"_id", "title", "text", "metadata"}``) for :class:`HybridIndex`."""
        return [to_corpus_entry(t) for t in self.trials(**filters)]
