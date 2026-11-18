"""OHDSI Data Quality Dashboard-style checks on the OMOP store (D-151): a small subset, run as SQL on the box.

    python -m omop dqd --json /tmp/dqd.json       # exit 1 when a check fails

Each result has the DQD fields (``checkName``, ``category``, ``subcategory``, ``context``, ``cdmTableName``,
``cdmFieldName``, ``numViolatedRows``, ``numDenominatorRows``, ``pctViolatedRows``, ``threshold`` in percent, and
``status``). The checks:

* **Conformance**: ``isRequired`` and ``isPrimaryKey`` (from the pinned DDL), ``isForeignKey`` (every reference of
  the official constraints file whose two tables are loaded here; the keys are checked as data because the
  constraints are not applied, ``omop.schema``), ``fkDomain`` (gender, visit), ``isStandardValidConcept`` (a
  ``*_concept_id`` is a valid standard concept or 0), and TrialBox's own: local concepts are >= 2,000,000,000 and
  never standard (D-144), every OMOP row has one live provenance record.
* **Completeness**: ``measurePersonCompleteness`` (persons without an observation period),
  ``sourceConceptRecordCompleteness`` (a coded row whose source concept is 0) and
  ``standardConceptRecordCompleteness`` (a row whose standard concept is 0: **known**, with the reason for its
  table, :func:`vocab_gap`: conditions stay 0 for good without SNOMED, drugs and measurements fill in once an
  Athena bundle with RxNorm, ATC and LOINC is loaded, STD-030).
* **Plausibility**: ``plausibleValueLow`` / ``plausibleValueHigh`` (year of birth), ``plausibleAfterBirth``,
  ``plausibleBeforeDeath`` (60 days' grace), ``plausibleStartBeforeEnd``, and TrialBox's count of required dates
  the source did not give (``tbImputedDate``, imputed with the date the record reached TrialBox).

A check is ``pass`` within its threshold, ``fail`` above it, ``known`` when the failure is an expected gap with a
plan (named in ``notes``).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from tb_common.db import Database

from omop.schema import DDL_DIR, LOCAL_MIN, foreign_keys
from omop.vocab_load import athena_loaded

CLINICAL = {
    "visit_occurrence": ("visit_occurrence_id", "visit_concept_id", None, "visit_start_date", "visit_end_date"),
    "condition_occurrence": (
        "condition_occurrence_id",
        "condition_concept_id",
        "condition_source_concept_id",
        "condition_start_date",
        "condition_end_date",
    ),
    "drug_exposure": (
        "drug_exposure_id",
        "drug_concept_id",
        "drug_source_concept_id",
        "drug_exposure_start_date",
        "drug_exposure_end_date",
    ),
    "procedure_occurrence": (
        "procedure_occurrence_id",
        "procedure_concept_id",
        "procedure_source_concept_id",
        "procedure_date",
        "procedure_end_date",
    ),
    "measurement": (
        "measurement_id",
        "measurement_concept_id",
        "measurement_source_concept_id",
        "measurement_date",
        None,
    ),
    "observation": (
        "observation_id",
        "observation_concept_id",
        "observation_source_concept_id",
        "observation_date",
        None,
    ),
    "note": ("note_id", None, None, "note_date", None),
}
PRIMARY = {
    "person": "person_id",
    "provider": "provider_id",
    "care_site": "care_site_id",
    "concept": "concept_id",
    "observation_period": "observation_period_id",
    **{t: v[0] for t, v in CLINICAL.items()},
}
# why a row's standard concept is 0, per table (STD-030): said as it is, not "until the Athena load"
NO_SNOMED = ("no SNOMED CT on the box (no licence, Q-22): ICD-10-CM and ICD-10 are source vocabularies in OMOP and "
             "map only to SNOMED, so condition standard concepts stay 0 with or without Athena")  # fmt: skip


def vocab_gap(table: str, athena: dict[str, str]) -> str:
    """The reason given for ``standardConceptRecordCompleteness`` on ``table``; ``athena`` is
    ``omop.vocab_load.athena_loaded`` (the loaded bundle's vocabularies)."""
    if table == "visit_occurrence":
        return ""
    if table == "condition_occurrence":
        return NO_SNOMED
    if table == "drug_exposure":
        if "RxNorm" in athena and "ATC" in athena:
            return (
                "an NHI or YJ drug code has no OHDSI vocabulary, and an ATC code with no single RxNorm "
                f"ingredient (a combination, or not in the bundle) stays 0 (Athena {athena.get('None', '')})"
            )
        return "no RxNorm on the box: load an Athena bundle with ATC and RxNorm (python -m omop vocab athena)"
    if table == "procedure_occurrence":
        return "procedures are NHI order codes: no OHDSI standard for them (CPT4 and SNOMED are not on the box)"
    if "LOINC" in athena:
        return "a local or site code with no LOINC map stays 0"
    return "no LOINC on the box: load an Athena bundle with LOINC and UCUM (python -m omop vocab athena)"


def required_columns() -> dict[str, list[str]]:
    """``table -> NOT NULL columns`` of the pinned DDL, for the tables the store holds."""
    text = (DDL_DIR / "OMOPCDM_postgresql_5.4_ddl.sql").read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for table, body in re.findall(r"CREATE TABLE @cdmDatabaseSchema\.(\w+) \((.*?)\);", text, flags=re.S):
        if table in (*CLINICAL, "person", "death", "observation_period", "provider", "care_site", "fact_relationship"):
            out[table] = re.findall(r"^\s*(\w+) \w+(?:\(\d+\))? NOT NULL", body, flags=re.M)
    return out


def _result(
    name: str,
    category: str,
    sub: str,
    table: str,
    fld: str | None,
    bad: int,
    den: int,
    threshold: float,
    context: str = "Verification",
    notes: str = "",
    known: str = "",
) -> dict[str, Any]:
    pct = round(100.0 * bad / den, 4) if den else 0.0
    status = "pass" if pct <= threshold else ("known" if known else "fail")
    return {
        "checkName": name,
        "category": category,
        "subcategory": sub,
        "context": context,
        "cdmTableName": table,
        "cdmFieldName": fld,
        "numViolatedRows": bad,
        "numDenominatorRows": den,
        "pctViolatedRows": pct,
        "threshold": threshold,
        "status": status,
        "notes": known if status == "known" else notes,
    }


def run(db: Database, today: date | None = None) -> list[dict[str, Any]]:
    if today is None:
        from tb_common.timeutil import today as site_today

        today = site_today()  # 9l-7: the site's day, not the server's
    out: list[dict[str, Any]] = []
    with db.transaction() as tx:

        def n(sql: str, params: tuple[Any, ...] = ()) -> int:
            return int(tx.fetchval(sql, params) or 0)

        athena = athena_loaded(tx)
        rows = {
            t: n(f"SELECT count(*) FROM {t}")
            for t in (
                *CLINICAL,
                "person",
                "death",
                "observation_period",
                "provider",
                "care_site",
                "fact_relationship",
                "concept",
            )
        }
        # -- conformance
        for table, cols in required_columns().items():
            for col in cols:
                out.append(
                    _result(
                        "isRequired",
                        "Conformance",
                        "Relational",
                        table,
                        col,
                        n(f"SELECT count(*) FROM {table} WHERE {col} IS NULL"),
                        rows[table],
                        0,
                    )
                )
        for table, col in PRIMARY.items():
            dup = n(f"SELECT coalesce(sum(c - 1), 0) FROM (SELECT count(*) c FROM {table} GROUP BY {col}) x")
            out.append(_result("isPrimaryKey", "Conformance", "Relational", table, col, dup, rows[table], 0))
        for table, col, rtable, rcol in foreign_keys():
            bad = n(
                f"SELECT count(*) FROM {table} t WHERE t.{col} IS NOT NULL AND NOT EXISTS "
                f"(SELECT 1 FROM {rtable} r WHERE r.{rcol} = t.{col})"
            )
            out.append(
                _result(
                    "isForeignKey",
                    "Conformance",
                    "Relational",
                    table,
                    col,
                    bad,
                    rows.get(table) or n(f"SELECT count(*) FROM {table}"),
                    0,
                )
            )
        for table, col, domain in (
            ("person", "gender_concept_id", "Gender"),
            ("visit_occurrence", "visit_concept_id", "Visit"),
        ):
            bad = n(
                f"SELECT count(*) FROM {table} t JOIN concept c ON c.concept_id = t.{col} "
                f"WHERE t.{col} <> 0 AND c.domain_id <> ?",
                (domain,),
            )
            out.append(_result("fkDomain", "Conformance", "Value", table, col, bad, rows[table], 0))
        for table, (_, concept, _, _, _) in CLINICAL.items():
            if concept is None:
                continue
            bad = n(
                f"SELECT count(*) FROM {table} t LEFT JOIN concept c ON c.concept_id = t.{concept} "
                f"WHERE t.{concept} <> 0 AND (c.concept_id IS NULL OR c.standard_concept IS DISTINCT FROM 'S' "
                "OR c.invalid_reason IS NOT NULL)"
            )
            out.append(_result("isStandardValidConcept", "Conformance", "Value", table, concept, bad, rows[table], 0))
        bad = n(
            "SELECT count(*) FROM concept WHERE vocabulary_id LIKE 'TB-%' AND vocabulary_id <> 'TB-SHARED' "
            "AND (concept_id < ? OR standard_concept IS NOT NULL)",
            (LOCAL_MIN,),
        )
        out.append(
            _result(
                "tbLocalConceptRange",
                "Conformance",
                "Value",
                "concept",
                "concept_id",
                bad,
                n("SELECT count(*) FROM concept WHERE vocabulary_id LIKE 'TB-%'"),
                0,
                notes="local concepts are >= 2,000,000,000 and never standard (D-144)",
            )
        )
        for table, (pk, *_) in CLINICAL.items():
            bad = n(
                f"SELECT count(*) FROM {table} t WHERE (SELECT count(*) FROM tb_record r WHERE r.cdm_table = ? "
                f"AND r.record_id = t.{pk} AND r.status NOT IN ('tombstoned', 'superseded')) <> 1",
                (table,),
            )
            out.append(
                _result(
                    "tbProvenance",
                    "Conformance",
                    "Relational",
                    table,
                    pk,
                    bad,
                    rows[table],
                    0,
                    notes="every OMOP row has exactly one live source record (tb_record)",
                )
            )
        # -- completeness
        bad = n(
            "SELECT count(*) FROM person p WHERE NOT EXISTS (SELECT 1 FROM observation_period o "
            "WHERE o.person_id = p.person_id)"
        )
        out.append(
            _result(
                "measurePersonCompleteness",
                "Completeness",
                "",
                "observation_period",
                None,
                bad,
                rows["person"],
                0,
                context="Validation",
                notes="a person with no dated record has no observation period",
            )
        )
        for table, (_, concept, source, _, _) in CLINICAL.items():
            if source:
                src_col = source.replace("_concept_id", "_value")
                bad = n(f"SELECT count(*) FROM {table} WHERE {source} = 0 AND {src_col} IS NOT NULL")
                out.append(
                    _result("sourceConceptRecordCompleteness", "Completeness", "", table, source, bad, rows[table], 1)
                )
            if concept:
                bad = n(f"SELECT count(*) FROM {table} WHERE {concept} = 0")
                gap = vocab_gap(table, athena)
                out.append(
                    _result(
                        "standardConceptRecordCompleteness",
                        "Completeness",
                        "",
                        table,
                        concept,
                        bad,
                        rows[table],
                        5,
                        known=gap,
                    )
                )
        # -- plausibility
        out.append(
            _result(
                "plausibleValueLow",
                "Plausibility",
                "Atemporal",
                "person",
                "year_of_birth",
                n("SELECT count(*) FROM person WHERE year_of_birth < 1850"),
                rows["person"],
                1,
                known="year_of_birth 0: no birth date in any source; the person is kept, because OMOP's "
                "'drop the person' convention would exclude an unknown (D-144: unknown never excludes)",
            )
        )
        out.append(
            _result(
                "plausibleValueHigh",
                "Plausibility",
                "Atemporal",
                "person",
                "year_of_birth",
                n("SELECT count(*) FROM person WHERE year_of_birth > ?", (today.year,)),
                rows["person"],
                0,
            )
        )
        for table, (_, _, _, start, end) in CLINICAL.items():
            bad = n(
                f"SELECT count(*) FROM {table} t JOIN person p USING (person_id) WHERE p.birth_datetime IS NOT "
                f"NULL AND t.{start} < p.birth_datetime::date"
            )
            out.append(_result("plausibleAfterBirth", "Plausibility", "Temporal", table, start, bad, rows[table], 1))
            bad = n(
                f"SELECT count(*) FROM {table} t JOIN death d USING (person_id) WHERE t.{start} > d.death_date + 60"
            )
            out.append(_result("plausibleBeforeDeath", "Plausibility", "Temporal", table, start, bad, rows[table], 1))
            if end:
                bad = n(f"SELECT count(*) FROM {table} WHERE {end} IS NOT NULL AND {end} < {start}")
                out.append(
                    _result("plausibleStartBeforeEnd", "Plausibility", "Temporal", table, start, bad, rows[table], 1)
                )
        bad = n(
            "SELECT count(*) FROM observation_period WHERE observation_period_end_date < observation_period_start_date"
        )
        out.append(
            _result(
                "plausibleStartBeforeEnd",
                "Plausibility",
                "Temporal",
                "observation_period",
                "observation_period_start_date",
                bad,
                rows["observation_period"],
                0,
            )
        )
        imputed = n("SELECT count(*) FROM tb_record WHERE date_imputed AND status <> 'tombstoned'")
        live = n(
            "SELECT count(*) FROM tb_record WHERE status <> 'tombstoned' AND cdm_table = ANY(?)", (sorted(CLINICAL),)
        )
        out.append(
            _result(
                "tbImputedDate",
                "Plausibility",
                "Temporal",
                "tb_record",
                "date_imputed",
                imputed,
                live,
                1,
                notes="required dates the source did not give (the date the record reached TrialBox)",
            )
        )
    return out


def relational_violations(tx: Any, person_only: bool = False) -> dict[str, int]:
    """T-611: the Relational conformance checks of :func:`run` (``isRequired``, ``isPrimaryKey``, ``isForeignKey``,
    threshold 0) as ``"<check> <table>.<field>" -> violated rows``, inside the caller's transaction: what a feed load
    compares before and after its own writes (``omop.load``). A violated row of these is a ``fail`` in :func:`run`.
    ``person_only``: only the ``isForeignKey`` checks of references to ``person``."""

    def n(sql: str) -> int:
        return int(tx.fetchval(sql) or 0)

    out: dict[str, int] = {}
    if person_only:
        for table, col, rtable, rcol in foreign_keys():
            if rtable == "person":
                out[f"isForeignKey {table}.{col}"] = n(
                    f"SELECT count(*) FROM {table} t WHERE t.{col} IS NOT NULL AND NOT EXISTS "
                    f"(SELECT 1 FROM {rtable} r WHERE r.{rcol} = t.{col})"
                )
        return out
    for table, cols in required_columns().items():
        for col in cols:
            out[f"isRequired {table}.{col}"] = n(f"SELECT count(*) FROM {table} WHERE {col} IS NULL")
    for table, col in PRIMARY.items():
        if table == "concept":  # the vocabulary, not the feed's
            continue
        out[f"isPrimaryKey {table}.{col}"] = n(
            f"SELECT coalesce(sum(c - 1), 0) FROM (SELECT count(*) c FROM {table} GROUP BY {col}) x"
        )
    for table, col, rtable, rcol in foreign_keys():
        out[f"isForeignKey {table}.{col}"] = n(
            f"SELECT count(*) FROM {table} t WHERE t.{col} IS NOT NULL AND NOT EXISTS "
            f"(SELECT 1 FROM {rtable} r WHERE r.{rcol} = t.{col})"
        )
    return out


def summary(results: list[dict[str, Any]]) -> dict[str, int]:
    out = {"checks": len(results), "pass": 0, "fail": 0, "known": 0}
    for r in results:
        out[r["status"]] += 1
    return out
