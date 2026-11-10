"""Where the compiler's ValueSets resolve (WS-03.3, D-301): the one module that says which terminology the compiler
reads, which release that is, whether a ruleset may run against it, and how a WHO-only ICD-10 code meets an ICD-10-CM
grouper.

* **Source** (``TB_TERMINOLOGY_SOURCE``): ``parquet`` (default) reads the terminology Parquet shipped with the
  compiler, as before; ``vocab`` reads the same tables back from the OMOP vocabulary (``omop.vocab_load``), where the
  Parquet, the code-list releases (ICD-10-CM FY2027, ...) and the site's loads live. A box whose vocabulary was
  loaded from the shipped Parquet compiles byte for byte the same ValueSets and SQL either way (same codes, new home;
  ``tests/unit/test_vocab.py`` compiles every committed ruleset's ValueSets through both).
* **Release** (:func:`current_release`): ``TR-`` and 12 hex over the releases the compiler resolves through. A
  compiled ruleset pins it in its manifest (``terminology_release``); :func:`guard` refuses to run a ruleset pinned to
  another release (or one the vocabulary listed as ``recompile_needed``) until it is recompiled. A manifest without a
  pin (the rulesets compiled before D-301) is checked only against the vocabulary's list.
* **WHO-only ICD-10** (baseline correction 3, D-301): a grouper's ICD-10-CM family (D-113) also stands for the WHO
  ICD-10 codes of the same prefix (:func:`family_systems`). A WHO-coded record inside the family whose code is not one
  of the ValueSet's ICD-10-CM codes (a WHO-only code such as ``M10.97``) makes the criterion unknown, never a silent
  false; a WHO code that is also a listed ICD-10-CM code is left to the D-130 runtime check, as before; outside every
  family the record still fails closed through D-130 (``unknown_code_system``).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from criteria_compiler.terminology.mapper import SYSTEMS, TERM_DIR, Terminology

SOURCE_ENV = "TB_TERMINOLOGY_SOURCE"
ICD10CM = SYSTEMS["icd10cm"]
ICD10_WHO = "http://hl7.org/fhir/sid/icd-10"
PARQUET_RELEASE = "terminology-parquet"
TERM_FILES = ("icd10cm_full", "icd10cm_tw", "atc", "loinc_tw", "nhi_drug", "nhi_order", "department", "synonyms")


class TerminologyMismatch(RuntimeError):
    """A ruleset compiled against one terminology release, asked to run against another."""


def source() -> str:
    s = (os.environ.get(SOURCE_ENV) or "parquet").strip().lower()
    if s not in ("parquet", "vocab"):
        raise ValueError(f"{SOURCE_ENV}={s!r}: parquet or vocab")
    return s


def _parquet_sha(directory: Path) -> str:
    h = hashlib.sha256()
    for name in TERM_FILES:
        p = directory / f"{name}.parquet"
        if p.is_file():
            h.update(f"{name}\0".encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def digest(pairs: list[tuple[str, str]]) -> str:
    """The release id over ``(release name, sha256)`` pairs (the same formula as ``omop.vocab_load``)."""
    if not pairs:
        return ""
    body = "\n".join(f"{n}={s}" for n, s in sorted(set(pairs)))
    return "TR-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=8)
def _parquet_release(directory: str, stamp: tuple[tuple[str, float, int], ...]) -> str:
    return digest([(PARQUET_RELEASE, _parquet_sha(Path(directory)))])


def parquet_release(directory: Path = TERM_DIR) -> str:
    """The release of the Parquet in ``directory`` (equal to the vocabulary's after loading only that Parquet)."""
    stamp = tuple(
        (n, (directory / f"{n}.parquet").stat().st_mtime, (directory / f"{n}.parquet").stat().st_size)
        for n in TERM_FILES
        if (directory / f"{n}.parquet").is_file()
    )
    return _parquet_release(str(directory), stamp)


def _vocab_db() -> Any:
    from omop import schema

    return schema.connect()


def current_release() -> str:
    """The release the compiler resolves through right now."""
    if source() == "vocab":
        from omop import vocab_load

        db = _vocab_db()
        try:
            return vocab_load.terminology_release(db)
        finally:
            db.close()
    return parquet_release()


def tables_dir(tables: dict[str, list[dict[str, Any]]], release: str) -> Path:
    """The vocabulary's tables written as the compiler's Parquet files (a cache per release under the temp dir)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out = Path(tempfile.gettempdir()) / f"tb-terminology-{release or 'none'}-{os.getuid()}"
    done = out / ".done"
    if done.is_file():
        return out
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        cols: list[str] = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        pq.write_table(pa.table({c: pa.array([r.get(c) for r in rows], pa.string()) for c in cols}),
                       out / f"{name}.parquet")  # fmt: skip
    done.write_text(json.dumps({"release": release}), encoding="utf-8")
    return out


def terminology(name_synonyms: Any = None) -> Terminology:
    """The compiler's :class:`Terminology` from the configured source, with its ``release`` (``name_synonyms``: the
    loaded zh-TW synonym dictionary, D-172)."""
    if source() != "vocab":
        return Terminology(name_synonyms=name_synonyms)
    from omop import vocab_load

    db = _vocab_db()
    try:
        release = vocab_load.terminology_release(db)
        tables = vocab_load.term_tables(db)
    finally:
        db.close()
    if not tables:
        raise TerminologyMismatch("TB_TERMINOLOGY_SOURCE=vocab but the vocabulary holds no terminology: load it")
    term = Terminology(tables_dir(tables, release), name_synonyms=name_synonyms)
    term.pin(release)
    return term


def family_systems(system: str) -> list[str]:
    """The record systems a grouper family of ``system`` covers: an ICD-10-CM family also covers WHO ICD-10."""
    return [system, ICD10_WHO] if system == ICD10CM else [system]


def recompile_listed(ruleset_id: str, version: str) -> bool:
    """True when the vocabulary listed this ruleset version as ``recompile_needed`` (``vocab`` source only)."""
    if source() != "vocab":
        return False
    db = _vocab_db()
    try:
        row = db.fetchone(
            "SELECT recompile_needed FROM tb_ruleset_release WHERE ruleset_id = ? AND version = ?",
            (ruleset_id, version),
        )
        return bool(row and row[0])
    finally:
        db.close()


def check(ruleset_id: str, version: str, pinned: str | None, release: str, listed: bool = False) -> None:
    """Refuse a run of a ruleset compiled against another release (``pinned``) or listed for recompiling."""
    if pinned and pinned != release:
        raise TerminologyMismatch(
            f"ruleset {ruleset_id} v{version} was compiled against terminology {pinned}; the box now has {release}: "
            "recompile it before it runs (D-301)"
        )
    if listed:
        raise TerminologyMismatch(
            f"ruleset {ruleset_id} v{version} is listed as recompile needed for terminology {release or 'none'} "
            "(D-301): recompile it before it runs"
        )


def guard() -> Callable[[Any], None]:
    """The run-time check ``tb_common.ruleset.load_approved`` applies to an approved manifest."""

    def run(manifest: Any) -> None:
        pinned = getattr(manifest, "terminology_release", None)
        listed = recompile_listed(manifest.id, manifest.version)
        if not pinned and not listed:
            return
        check(manifest.id, manifest.version, pinned, current_release(), listed)

    return run
