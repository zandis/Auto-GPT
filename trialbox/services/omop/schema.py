"""The ``omop`` schema in the trial database: the official OMOP CDM v5.4 DDL plus TrialBox's extension tables (D-151).

**The CDM tables** come from the four PostgreSQL files of OHDSI/CommonDataModel tag v5.4.2, copied unchanged into
``omop/ddl/`` and pinned by sha256 in ``omop/ddl/pin.json`` (a changed file is refused, never applied). Migration 1
is the files' ``CREATE TABLE``, primary-key and index statements for the tables of :data:`CDM_TABLES`, in the files'
order, with ``@cdmDatabaseSchema.`` removed (the store's ``search_path`` is the schema). The foreign-key file is
not applied, as the OHDSI ETL guidance allows: the loader fills concept ids it does not own (0 until the Athena
bundle is loaded) and the Data Quality Dashboard checks the keys as data (``omop.dqd``, ``isForeignKey``) instead.

**The extension tables** (prefix ``tb_``, migration 2) are kept apart from the standard tables, so OHDSI tools see
plain CDM tables:

* ``tb_record``: one row per source record (FHIR resource, or one component row of a panel), keyed by
  (source kind, resource type, source id, part). It says which OMOP row the record became (``cdm_table``,
  ``record_id``), its **record status** (:data:`STATUSES`) and the source's basis tag (D-135), its **provenance**
  (source batch, file and row; first and last batch that carried it; content sha) and ``extra``: the FHIR fields
  OMOP v5.4 has no column for (named by the lake column they restore, e.g. ``recorded``, ``category``, ``local_code``).
* ``tb_record_event``: the append-only history of every record (insert, update with the before-image, tombstone,
  restore, status change), with batch, time, actor and reason.
* ``tb_conflict``: open and resolved conflicts. Two sources that disagree on a fact are recorded, never resolved
  silently; while one is open the fact reads as unknown in the lake (D-144: unknown never excludes).
* ``tb_id_map``: pseudonymous source ids (the patient pseudonym, the staff id, the department code) to the integer
  OMOP ids minted once for them.
* ``tb_appointment``, ``tb_claim``, ``tb_consent``: the three lake tables OMOP v5.4 has no table for (booked visits,
  pre-authorisation claims, research-contact consent), kept local as the design proposed (design §A).
* ``tb_load``: one row per load (batch, counts, seconds).
* ``tb_withheld`` (migration 7, D-441): the pseudonyms the opt-out worker keeps out of the store. Their records are
  tombstoned with the reason ``opted out`` and a later load does not bring them back; a lift deletes the row and
  the next load restores them (nothing is restored by the lift itself).

Local concepts are minted from ``tb_local_concept_seq`` in the site's block (``TB_OMOP_CONCEPT_BLOCK``, default
2,100,000,000; never below 2,000,000,000, which is TrialBox's shared range, D-144). A site block is one million ids
(D-301, the D-151 overflow fix: 47 sites fit below the integer maximum, where ten million fitted four); a block that
would end above 2,147,483,647 is refused. Migration 2 keeps the text it was applied with (ten million, D-204: an
applied migration never changes); migration 3 narrows the sequence to the one-million block and adds the vocabulary
tables of D-301 (``omop.vocab_load``). Migration 4 (T-106, D-339, ``ddl/partitions.sql``) partitions the large
clinical tables by the year of their required date (``omop.partitions``). Migration 5 (T-106b, STD-032) creates the
other fifteen tables of the pinned DDL (:data:`CDM_TABLES_ADDED`) the same way as migration 1, so the store holds all
39 CDM v5.4 tables; the loader writes none of the fifteen yet. Migration 6 (T-202, D-384) gives
``tb_record_event`` the record's own before-image (``record_before``: the ``tb_record`` row as it was before the
change), so the lake can be exported as of an earlier time (``omop.export.export_rows(db, as_of=...)``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import cache
from pathlib import Path

from tb_common.db import Database

DDL_DIR = Path(__file__).resolve().parent / "ddl"
SCHEMA = "omop"
CDM_VERSION = "5.4"

# the CDM tables screening needs (the owner's list) and the ones they reference (provider, care_site)
CDM_TABLES = (
    "person",
    "observation_period",
    "visit_occurrence",
    "condition_occurrence",
    "drug_exposure",
    "procedure_occurrence",
    "measurement",
    "observation",
    "death",
    "note",
    "fact_relationship",
    "care_site",
    "provider",
    "cdm_source",
    "concept",
    "vocabulary",
    "domain",
    "concept_class",
    "concept_relationship",
    "relationship",
    "concept_synonym",
    "concept_ancestor",
    "source_to_concept_map",
    "drug_strength",
)
# T-106b (STD-032): the other fifteen tables of the v5.4 DDL, created empty by migration 5 (an empty table is
# conformant; OHDSI tools such as Achilles, the DQD package and WebAPI expect all 39). Migration 1 keeps its text.
CDM_TABLES_ADDED = (
    "visit_detail",
    "device_exposure",
    "note_nlp",
    "specimen",
    "location",
    "payer_plan_period",
    "cost",
    "drug_era",
    "dose_era",
    "condition_era",
    "episode",
    "episode_event",
    "metadata",
    "cohort",
    "cohort_definition",
)
ALL_CDM_TABLES = CDM_TABLES + CDM_TABLES_ADDED
FILES = ("ddl", "primary_keys", "indices")

# record status (D-151): coded = from the hospital's coded record; the rest as the design's state machine
STATUSES = ("coded", "proposed", "confirmed", "signed", "derived", "rejected", "superseded", "tombstoned")
# the statuses a coded lake table admits (proposed and rejected never; tombstoned and superseded are gone)
COUNTED = frozenset({"coded", "confirmed", "signed", "derived"})
# allowed status changes; every other change is refused (``omop.load.set_status``)
TRANSITIONS: dict[str, frozenset[str]] = {
    "coded": frozenset({"superseded", "rejected", "tombstoned"}),
    "proposed": frozenset({"confirmed", "rejected", "superseded", "tombstoned"}),
    "confirmed": frozenset({"signed", "superseded", "rejected", "tombstoned"}),
    "signed": frozenset({"superseded", "tombstoned"}),
    "derived": frozenset({"superseded", "tombstoned"}),
    "rejected": frozenset({"proposed", "tombstoned"}),
    "superseded": frozenset({"tombstoned"}),
    "tombstoned": frozenset(STATUSES) - {"tombstoned"},  # a record the source sends again comes back
}

LOCAL_MIN = 2_000_000_000  # D-144: local concepts are >= 2e9; TB-SHARED is 2,000,000,000-2,099,999,999
INT4_MAX = 2_147_483_647  # OMOP ids are ``integer``: a site block ends here at the latest
DEFAULT_BLOCK = 2_100_000_000  # the first site block (design §2.4)
BLOCK_SIZE = 1_000_000  # D-301: one million ids per site (the D-151 overflow fix)
V2_BLOCK_SIZE = 10_000_000  # the block size migration 2 was applied with; its text never changes (D-204)
# reference concepts (D-301): the public and licensed code lists loaded without the Athena bundle (ICD-10-CM, LOINC,
# ATC, the NHI lists, MEDIS, JLAC10, YJ, ...) get box-local ids in TrialBox's range, above the shared concepts and
# the catalogue (2,000,001,001 and up, WS-04.1); like every id >= 2e9 they are never standard
REF_MIN, REF_MAX = 2_010_000_000, 2_099_999_999


class OmopError(RuntimeError):
    """The OMOP store refused an operation (a changed pinned file, an older batch, a forbidden status change)."""


def pinned() -> dict[str, str]:
    """``file -> sha256`` of the vendored DDL, checked against ``ddl/pin.json``."""
    pin = json.loads((DDL_DIR / "pin.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for name, want in pin["files"].items():
        got = hashlib.sha256((DDL_DIR / name).read_bytes()).hexdigest()
        if got != want:
            raise OmopError(f"OMOP DDL file {name} does not match its pin ({got[:12]} != {want[:12]})")
        out[name] = got
    return out


_TARGET = re.compile(r"(?:CREATE TABLE|ALTER TABLE|ON|CLUSTER)\s+@cdmDatabaseSchema\.(\w+)", re.IGNORECASE)


def _statements(text: str) -> list[str]:
    out = []
    for raw in text.split(";"):
        body = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        body = "\n".join(line for line in body.splitlines() if not line.strip().startswith("--")).strip()
        if body:
            out.append(body)
    return out


@cache
def cdm_ddl(tables: tuple[str, ...] = CDM_TABLES) -> str:
    """Migration 1: the pinned files' statements for ``tables``, schema placeholder removed."""
    pinned()
    keep = set(tables)
    stmts = []
    for part in FILES:
        text = (DDL_DIR / f"OMOPCDM_postgresql_5.4_{part}.sql").read_text(encoding="utf-8")
        for st in _statements(text):
            m = _TARGET.search(st)
            if m and m.group(1).lower() in keep:
                stmts.append(st.replace("@cdmDatabaseSchema.", ""))
    return ";\n".join(stmts)


def foreign_keys(tables: tuple[str, ...] = CDM_TABLES) -> list[tuple[str, str, str, str]]:
    """``(table, column, referenced table, referenced column)`` of the official constraints file, for the tables
    loaded here: the Data Quality Dashboard's ``isForeignKey`` checks run on these (``omop.dqd``)."""
    pinned()
    text = (DDL_DIR / "OMOPCDM_postgresql_5.4_constraints.sql").read_text(encoding="utf-8")
    pat = re.compile(
        r"ALTER TABLE @cdmDatabaseSchema\.(\w+)\s+ADD CONSTRAINT \w+ FOREIGN KEY \((\w+)\) REFERENCES "
        r"@cdmDatabaseSchema\.(\w+) \((\w+)\)",
        re.IGNORECASE,
    )
    keep = set(tables)
    return [
        (t.lower(), c.lower(), rt.lower(), rc.lower())
        for t, c, rt, rc in pat.findall(text)
        if t.lower() in keep and rt.lower() in keep
    ]


def _block_first() -> int:
    first = int(os.environ.get("TB_OMOP_CONCEPT_BLOCK") or DEFAULT_BLOCK)
    if first < LOCAL_MIN or first >= INT4_MAX:
        raise OmopError(f"TB_OMOP_CONCEPT_BLOCK={first}: local concepts must be >= {LOCAL_MIN:,} (D-144)")
    return first


def concept_block() -> tuple[int, int]:
    """``(first, last)`` id of this site's local concepts: ``TB_OMOP_CONCEPT_BLOCK`` (its first id) and one million
    ids (D-301). Refused below 2,000,000,000 (D-144) and when the block would end above the integer maximum
    (2,147,483,647: OMOP's ``concept_id`` is an ``integer``), never cut short."""
    first = _block_first()
    last = first + BLOCK_SIZE - 1
    if last > INT4_MAX:
        raise OmopError(
            f"TB_OMOP_CONCEPT_BLOCK={first:,}: the block would end at {last:,}, above the integer maximum "
            f"{INT4_MAX:,} (D-301); the last block starts at {INT4_MAX - BLOCK_SIZE + 1:,}"
        )
    return first, last


def tb_ddl() -> str:
    """Migration 2: TrialBox's extension tables (never inside a standard table). Its text is the one applied on
    every box (the ten-million block of D-151; migration 3 narrows it)."""
    first = _block_first()
    last = min(first + V2_BLOCK_SIZE - 1, INT4_MAX)
    statuses = ", ".join(f"'{s}'" for s in STATUSES)
    return f"""
CREATE TABLE tb_record (
    record_key BIGSERIAL PRIMARY KEY,
    source_kind TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    part INTEGER NOT NULL DEFAULT 0,
    cdm_table TEXT,
    record_id INTEGER,
    person_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ({statuses})),
    basis TEXT,
    source_batch TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    content_sha TEXT NOT NULL,
    extra JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    date_imputed BOOLEAN NOT NULL DEFAULT false,
    first_batch TEXT NOT NULL,
    last_batch TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tombstoned_at TIMESTAMPTZ,
    UNIQUE (source_kind, resource_type, source_record_id, part)
);
CREATE INDEX tb_record_target ON tb_record (cdm_table, record_id);
CREATE INDEX tb_record_person ON tb_record (person_id);
CREATE TABLE tb_record_event (
    event_id BIGSERIAL PRIMARY KEY,
    record_key BIGINT NOT NULL REFERENCES tb_record (record_key),
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch TEXT,
    event TEXT NOT NULL CHECK (event IN ('insert', 'update', 'tombstone', 'restore', 'status')),
    from_status TEXT,
    to_status TEXT,
    before_sha TEXT,
    before JSONB,
    actor TEXT NOT NULL DEFAULT 'loader',
    reason TEXT
);
CREATE INDEX tb_record_event_key ON tb_record_event (record_key);
CREATE TABLE tb_conflict (
    conflict_id BIGSERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    item TEXT NOT NULL,
    values_sha TEXT NOT NULL,
    claims JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'resolved', 'withdrawn')),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    detected_batch TEXT,
    resolved_value TEXT,
    resolution TEXT,
    reason TEXT,
    authority TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    closed_batch TEXT
);
CREATE UNIQUE INDEX tb_conflict_live ON tb_conflict (person_id, item, values_sha) WHERE state <> 'withdrawn';
CREATE TABLE tb_id_map (
    id_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    omop_id INTEGER NOT NULL,
    PRIMARY KEY (id_kind, source_id),
    UNIQUE (id_kind, omop_id)
);
CREATE TABLE tb_appointment (
    appointment_id INTEGER PRIMARY KEY,
    person_id INTEGER,
    appointment_datetime TIMESTAMP,
    provider_id INTEGER,
    care_site_id INTEGER,
    status TEXT
);
CREATE TABLE tb_claim (
    claim_id INTEGER PRIMARY KEY,
    person_id INTEGER,
    created DATE,
    product TEXT,
    outcome TEXT,
    approval_start DATE,
    approval_end DATE
);
CREATE TABLE tb_consent (
    consent_id INTEGER PRIMARY KEY,
    person_id INTEGER,
    status TEXT,
    contact_ok BOOLEAN,
    consent_date DATE
);
CREATE TABLE tb_load (
    load_id BIGSERIAL PRIMARY KEY,
    source_kind TEXT NOT NULL,
    batch TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seconds DOUBLE PRECISION,
    counts JSONB NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE SEQUENCE tb_local_concept_seq MINVALUE {first} MAXVALUE {last} START {first} NO CYCLE;
CREATE SEQUENCE tb_person_seq MAXVALUE {INT4_MAX} NO CYCLE;
CREATE SEQUENCE tb_provider_seq MAXVALUE {INT4_MAX} NO CYCLE;
CREATE SEQUENCE tb_care_site_seq MAXVALUE {INT4_MAX} NO CYCLE;
CREATE SEQUENCE tb_row_seq MAXVALUE {INT4_MAX} NO CYCLE
"""


def vocab_ddl() -> str:
    """Migration 3 (D-301): the one-million site block, the reference-concept sequence and the vocabulary's
    TrialBox tables (``omop.vocab_load``): releases, the attributes a concept row has no column for, the compiler's
    groupers, the relation of a map row and the rulesets' release pins."""
    first, last = concept_block()
    return f"""
ALTER SEQUENCE tb_local_concept_seq MINVALUE {first} MAXVALUE {last};
CREATE SEQUENCE tb_ref_concept_seq MINVALUE {REF_MIN} MAXVALUE {REF_MAX} START {REF_MIN} NO CYCLE;
CREATE TABLE tb_vocab_release (
    release_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    vocabulary_id TEXT NOT NULL,
    version TEXT NOT NULL,
    source TEXT NOT NULL,
    rows INTEGER NOT NULL,
    compile BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    loaded_by TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (release_name, sha256)
);
CREATE TABLE tb_concept_attr (
    concept_id INTEGER NOT NULL,
    attr TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (concept_id, attr)
);
CREATE TABLE tb_term_grouper (
    ord INTEGER NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    tbl TEXT NOT NULL,
    code TEXT NOT NULL,
    match TEXT NOT NULL CHECK (match IN ('exact', 'prefix')),
    PRIMARY KEY (domain, name, tbl, code, match)
);
CREATE TABLE tb_map_relation (
    source_vocabulary_id TEXT NOT NULL,
    source_code TEXT NOT NULL,
    target_concept_id INTEGER NOT NULL,
    relation TEXT NOT NULL,
    map_release TEXT NOT NULL,
    PRIMARY KEY (source_vocabulary_id, source_code, target_concept_id)
);
CREATE TABLE tb_ruleset_release (
    ruleset_id TEXT NOT NULL,
    version TEXT NOT NULL,
    compiled_release TEXT NOT NULL,
    recompile_needed BOOLEAN NOT NULL,
    marked_for TEXT NOT NULL,
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ruleset_id, version)
)
"""


#: migration 6 (T-202, D-384): the before-image of the ``tb_record`` row itself, beside the CDM row's (``before``);
#: NULL on an insert, and on every event written before this migration (an export as of a time before such an event
#: is refused, never guessed)
HISTORY_DDL = "ALTER TABLE tb_record_event ADD COLUMN record_before JSONB"
# D-441 (T-206a): the persons the opt-out worker withholds (pseudonym, since when, why); written by the worker only
WITHHELD_DDL = """
CREATE TABLE tb_withheld (
    pid TEXT PRIMARY KEY,
    since TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason TEXT NOT NULL
)
"""


def migrations() -> list[str]:
    from omop.partitions import migration as partitions_ddl

    return [cdm_ddl(), tb_ddl(), vocab_ddl(), partitions_ddl(), cdm_ddl(CDM_TABLES_ADDED), HISTORY_DDL, WITHHELD_DDL]


def db_url() -> str | None:
    """``TB_OMOP_DB_URL``, else the trial database (``TB_DB_URL``): one Postgres for the box (D-144)."""
    return os.environ.get("TB_OMOP_DB_URL") or os.environ.get("TB_DB_URL")


def schema_for(lake_dir: Path | None) -> str:
    """The OMOP schema behind a lake: ``omop`` for the box's lake (``TB_LAKE_DIR``, or no lake named), and
    ``omop_<10 hex of the path>`` for any other lake directory (a practice site's own space, a test, a tool run):
    two lakes never share a store of record, so one never tombstones the other's records."""
    if lake_dir is None:
        return SCHEMA
    box = os.environ.get("TB_LAKE_DIR")
    path = lake_dir.resolve()
    if box and Path(box).resolve() == path:
        return SCHEMA
    return f"{SCHEMA}_" + hashlib.sha1(str(path).encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


def connect(url: str | None = None, name: str = SCHEMA) -> Database:
    """The OMOP schema ``name`` (``<tb_prefix>omop`` by default), migrated to the current version."""
    db = Database.connect(url or db_url(), name)
    db.migrate(migrations())
    from omop import vocab

    vocab.seed(db)
    return db
