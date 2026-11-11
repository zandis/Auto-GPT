"""Concepts for the OMOP store: the few standard concepts the loader writes, TrialBox's shared concepts and the
site's local concepts (D-151).

* **Standard concepts the loader writes** (:data:`STANDARD`): gender, visit, the EHR type concept, the measurement
  value operators, UTF-8 and concept 0. They are seeded with their OHDSI ids so the Athena bundle, when it is loaded
  (WS-04.2), replaces them with identical rows. The vocabulary, domain and concept-class rows they need are seeded
  as stand-ins with concept 0 until then.
* **TrialBox shared concepts** (:data:`SHARED`, 2,000,000,001 and up): the suspected-diagnosis status, the type
  concepts that tell a site input and a proposed fact from the hospital record, and the panel relationship.
* **Local source concepts** (the site block, ``TB_OMOP_CONCEPT_BLOCK``): one per (code system, code) the feed
  carries, minted once in a TrialBox vocabulary per code system (``TB-ICD10CM``, ``TB-LOINC``, ``TB-ATC``, ``TB-NHI``,
  ...; ``vocabulary_reference`` is the FHIR system URI, so the lake export gets the system back exactly). A local
  concept is never standard (``standard_concept`` NULL). It is the record's ``*_source_concept_id``; the record's
  ``*_concept_id`` is the standard concept when the vocabulary holds one for the same code (a LOINC code with the
  Athena LOINC loaded), else 0 (design §2.2 question 2: no SNOMED, ICD-10-CM as the condition standard).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from tb_common.db import Database

from omop.schema import LOCAL_MIN, OmopError

VALID_FROM, VALID_TO = date(1970, 1, 1), date(2099, 12, 31)

OPERATOR_VOCAB = "TB-OPERATOR"
# OHDSI standard concepts written by the loader (id, name, domain, vocabulary, class, code)
STANDARD: tuple[tuple[int, str, str, str, str, str], ...] = (
    (0, "No matching concept", "Metadata", "None", "Undefined", "No matching concept"),
    (8507, "MALE", "Gender", "Gender", "Gender", "M"),
    (8532, "FEMALE", "Gender", "Gender", "Gender", "F"),
    (9201, "Inpatient Visit", "Visit", "Visit", "Visit", "IP"),
    (9202, "Outpatient Visit", "Visit", "Visit", "Visit", "OP"),
    (9203, "Emergency Room Visit", "Visit", "Visit", "Visit", "ER"),
    (32817, "EHR", "Type Concept", "Type Concept", "Type Concept", "OMOP4976890"),
    # the measurement value operators keep OHDSI's concept ids (what operator_concept_id means to OHDSI tools), but
    # not the SNOMED CT vocabulary and codes they carry in Athena: the box ships no SNOMED CT (T-617b, STD-044)
    (4171756, "<", "Meas Value Operator", OPERATOR_VOCAB, "Qualifier Value", "<"),
    (4171754, "<=", "Meas Value Operator", OPERATOR_VOCAB, "Qualifier Value", "<="),
    (4172703, "=", "Meas Value Operator", OPERATOR_VOCAB, "Qualifier Value", "="),
    (4172704, ">", "Meas Value Operator", OPERATOR_VOCAB, "Qualifier Value", ">"),
    (4171755, ">=", "Meas Value Operator", OPERATOR_VOCAB, "Qualifier Value", ">="),
    (32678, "UTF-8", "Metadata", "Note Encoding", "Undefined", "UTF-8"),
    (21, "Measurement", "Metadata", "Domain", "Domain", "OMOP generated"),
)
GENDER = {"male": 8507, "female": 8532}
# FHIR v3 ActCode encounter class -> OMOP visit; OBSENC and SS (observation, short stay) wait for the vocabulary load
VISIT = {"AMB": 9202, "IMP": 9201, "ACUTE": 9201, "NONAC": 9201, "EMER": 9203}
EHR = 32817
UTF8 = 32678
OPERATOR = {"<": 4171756, "<=": 4171754, "=": 4172703, ">": 4172704, ">=": 4171755}
OPERATOR_CODE = {v: k for k, v in OPERATOR.items()}
# OMOP domain concept ids used in FACT_RELATIONSHIP
DOMAIN_MEASUREMENT = 21

# TrialBox shared concepts (TB-SHARED, design §2.4): fixed ids, the same on every box
SUSPECTED = 2_000_000_001
SITE_INPUT = 2_000_000_011
PROPOSED_FACT = 2_000_000_012
HAS_COMPONENT = 2_000_000_021
COMPONENT_OF = 2_000_000_022
SHARED: tuple[tuple[int, str, str, str, str, str], ...] = (
    (
        SUSPECTED,
        "Suspected diagnosis (FHIR verificationStatus provisional, differential or unconfirmed; 疑い)",
        "Condition Status",
        "TB-SHARED",
        "TB Status",
        "suspected",
    ),
    (SITE_INPUT, "TrialBox site input (sheet, dump or chart)", "Type Concept", "TB-SHARED", "TB Type", "site-input"),
    (
        PROPOSED_FACT,
        "TrialBox proposed fact, not checked by a person",
        "Type Concept",
        "TB-SHARED",
        "TB Type",
        "proposed",
    ),
    (
        HAS_COMPONENT,
        "Has component (panel to component row)",
        "Relationship",
        "TB-SHARED",
        "TB Relationship",
        "has-component",
    ),
    (
        COMPONENT_OF,
        "Component of (component row to panel)",
        "Relationship",
        "TB-SHARED",
        "TB Relationship",
        "component-of",
    ),
)
TB_SHARED_VOCAB_CONCEPT = 2_000_000_000

# FHIR code system URI -> TrialBox source vocabulary (the OMOP vocabulary of the same code system, for standards)
KNOWN_SYSTEMS: dict[str, tuple[str, str | None]] = {
    "http://hl7.org/fhir/sid/icd-10-cm": ("TB-ICD10CM", "ICD10CM"),
    "http://hl7.org/fhir/sid/icd-10": ("TB-ICD10", "ICD10"),
    "http://loinc.org": ("TB-LOINC", "LOINC"),
    "http://www.whocc.no/atc": ("TB-ATC", "ATC"),
    "http://unitsofmeasure.org": ("TB-UCUM", "UCUM"),
    "http://snomed.info/sct": ("TB-SNOMED", "SNOMED"),
    "http://www.nlm.nih.gov/research/umls/rxnorm": ("TB-RXNORM", "RxNorm"),
    "https://trialbox.local/fhir/CodeSystem/nhi-drug": ("TB-NHI-DRUG", None),
    "https://trialbox.local/fhir/CodeSystem/nhi-order": ("TB-NHI-ORDER", None),
    "https://trialbox.local/fhir/CodeSystem/clinical-score": ("TB-SCORE", None),
    "urn:trialbox:demographic": ("TB-DEMOGRAPHIC", None),
}
NO_SYSTEM = "TB-NOSYS"  # a code sent without a system (kept; its system reads back as none)


def vocabulary_id(system: str | None) -> str:
    """The TrialBox vocabulary of a FHIR code system: a known name, else ``TB-`` and 12 hex of the URI's sha1
    (``vocabulary_id`` is 20 characters at most)."""
    if not system:
        return NO_SYSTEM
    known = KNOWN_SYSTEMS.get(system)
    if known:
        return known[0]
    return "TB-" + hashlib.sha1(system.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def standard_vocabulary(system: str | None) -> str | None:
    known = KNOWN_SYSTEMS.get(system or "")
    return known[1] if known else None


def seed(db: Database) -> None:
    """The standard, stand-in and shared rows; idempotent (an Athena load replaces the standard ones in place)."""
    with db.transaction() as tx:
        vocabs = {(c[3], None) for c in STANDARD} | {("TB-SHARED", None)}
        for vid, _ in sorted(vocabs):
            concept = TB_SHARED_VOCAB_CONCEPT if vid == "TB-SHARED" else 0
            name = "TrialBox shared concepts" if vid == "TB-SHARED" else f"{vid} (stand-in until the vocabulary load)"
            tx.execute(
                "INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
                "vocabulary_concept_id) SELECT ?, ?, NULL, NULL, ? WHERE NOT EXISTS "
                "(SELECT 1 FROM vocabulary WHERE vocabulary_id = ?)",
                (vid, name, concept, vid),
            )
        domains = {c[2] for c in (*STANDARD, *SHARED)} | {
            "Condition",
            "Measurement",
            "Drug",
            "Procedure",
            "Observation",
            "Note",
            "Unit",
            "Meas Value",
            "Provider",
            "Visit",
        }
        for d in sorted(domains):
            tx.execute(
                "INSERT INTO domain (domain_id, domain_name, domain_concept_id) SELECT ?, ?, 0 WHERE NOT EXISTS "
                "(SELECT 1 FROM domain WHERE domain_id = ?)",
                (d, d, d),
            )
        classes = {c[4] for c in (*STANDARD, *SHARED)} | {"TB Source Code", "Vocabulary"}
        for k in sorted(classes):
            tx.execute(
                "INSERT INTO concept_class (concept_class_id, concept_class_name, concept_class_concept_id) "
                "SELECT ?, ?, 0 WHERE NOT EXISTS (SELECT 1 FROM concept_class WHERE concept_class_id = ?)",
                (k, k, k),
            )
        for cid, name, dom, voc, cls, code in STANDARD:
            _insert_concept(tx, cid, name, dom, voc, cls, code, "S" if cid else None)
        _insert_concept(
            tx,
            TB_SHARED_VOCAB_CONCEPT,
            "TrialBox shared concepts",
            "Metadata",
            "TB-SHARED",
            "Vocabulary",
            "TB-SHARED",
            None,
        )
        for cid, name, dom, voc, cls, code in SHARED:
            _insert_concept(tx, cid, name, dom, voc, cls, code, None)


def _insert_concept(tx: Any, cid: int, name: str, dom: str, voc: str, cls: str, code: str, std: str | None) -> None:
    tx.execute(
        "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, standard_concept, "
        "concept_code, valid_start_date, valid_end_date, invalid_reason) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL "
        "WHERE NOT EXISTS (SELECT 1 FROM concept WHERE concept_id = ?)",
        (cid, name[:255], dom, voc, cls, std, code, VALID_FROM, VALID_TO, cid),
    )


@dataclass(frozen=True)
class Code:
    system: str | None
    code: str
    display: str | None
    domain: str


class Concepts:
    """Resolves (system, code) to the local source concept (minting it once) and to a standard concept when the
    vocabulary has one. One instance per load, inside the load's transaction."""

    def __init__(self, tx: Any) -> None:
        self.tx = tx
        self.source: dict[tuple[str, str], int] = {}
        self.standard: dict[tuple[str, str], int] = {}
        self.minted = 0

    def prepare(self, codes: Iterable[Code], std_only: Iterable[tuple[str | None, str]] = ()) -> None:
        """Mint the local concepts ``codes`` need; look up standard concepts for them and for ``std_only``."""
        want: dict[tuple[str, str], Code] = {}
        for c in codes:
            if c.code and len(c.code) <= 50:
                want.setdefault((vocabulary_id(c.system), c.code), c)
        self._standards([*((c.system, c.code) for c in want.values()), *std_only])
        if not want:
            return
        vocabs = {v for v, _ in want}
        for vid in sorted(vocabs):
            system = next(c.system for (v, _), c in want.items() if v == vid)
            self._vocabulary(vid, system)
        rows = self.tx.fetchall(
            "SELECT vocabulary_id, concept_code, concept_id FROM concept WHERE vocabulary_id = ANY(?) "
            "AND concept_id >= ?",
            (sorted(vocabs), LOCAL_MIN),
        )
        self.source.update({(v, code): int(cid) for v, code, cid in rows})
        new = [(k, c) for k, c in want.items() if k not in self.source]
        if new:
            ids = [
                int(r[0])
                for r in self.tx.fetchall(
                    "SELECT nextval('tb_local_concept_seq') FROM generate_series(1, ?)", (len(new),)
                )
            ]
            rows_out = []
            for (k, c), cid in zip(new, ids, strict=True):
                self.source[k] = cid
                rows_out.append(
                    (
                        cid,
                        (c.display or c.code)[:255],
                        c.domain,
                        k[0],
                        "TB Source Code",
                        None,
                        c.code,
                        VALID_FROM,
                        VALID_TO,
                        None,
                    )
                )
            self.tx.copy_rows(
                "concept",
                [
                    "concept_id",
                    "concept_name",
                    "domain_id",
                    "vocabulary_id",
                    "concept_class_id",
                    "standard_concept",
                    "concept_code",
                    "valid_start_date",
                    "valid_end_date",
                    "invalid_reason",
                ],
                rows_out,
            )
            self.minted += len(new)

    def _standards(self, pairs: Iterable[tuple[str | None, str]]) -> None:
        std_want: dict[str, set[str]] = {}
        for system, code in pairs:
            sv = standard_vocabulary(system)
            if sv and code:
                std_want.setdefault(sv, set()).add(code)
        for sv, codes in std_want.items():
            for code, cid in self.tx.fetchall(
                "SELECT concept_code, concept_id FROM concept WHERE vocabulary_id = ? AND concept_code = ANY(?) "
                "AND standard_concept = 'S' AND invalid_reason IS NULL AND concept_id < ?",
                (sv, sorted(codes), LOCAL_MIN),
            ):
                self.standard[(sv, str(code))] = int(cid)

    def _vocabulary(self, vid: str, system: str | None) -> None:
        have = self.tx.fetchone("SELECT vocabulary_reference FROM vocabulary WHERE vocabulary_id = ?", (vid,))
        if have is not None:
            if (have[0] or None) != (system or None):
                raise OmopError(f"vocabulary {vid} is {have[0]!r}, not {system!r} (two systems, one short name)")
            return
        if system and len(system) > 255:
            raise OmopError(f"code system URI longer than 255 characters: {system[:60]}...")
        cid = int(self.tx.fetchval("SELECT nextval('tb_local_concept_seq')"))
        name = f"TrialBox source codes: {system or 'no system given'}"
        self.tx.execute(
            "INSERT INTO concept (concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
            "standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason) "
            "VALUES (?, ?, 'Metadata', ?, 'Vocabulary', NULL, ?, ?, ?, NULL)",
            (cid, name[:255], vid, vid, VALID_FROM, VALID_TO),
        )
        self.tx.execute(
            "INSERT INTO vocabulary (vocabulary_id, vocabulary_name, vocabulary_reference, vocabulary_version, "
            "vocabulary_concept_id) VALUES (?, ?, ?, 'site', ?)",
            (vid, name[:255], system, cid),
        )
        self.minted += 1

    def source_id(self, system: str | None, code: str | None) -> int:
        """The local source concept, or 0 when there is no code (or it is longer than a concept code may be)."""
        if not code:
            return 0
        return self.source.get((vocabulary_id(system), code), 0)

    def standard_id(self, system: str | None, code: str | None) -> int:
        sv = standard_vocabulary(system)
        if not code or not sv:
            return 0
        return self.standard.get((sv, code), 0)
