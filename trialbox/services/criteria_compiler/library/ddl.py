"""SQLite DDL of the criterion library (spec v4 §6.3).

``criterion_library`` holds one row per canonical hash with the full record as JSON (the source of truth) and the
columns the repository filters on. The child tables index the record's texts, ValueSets, lexicon keys and the
rulesets that use it, so "which rulesets use this criterion" and "every library criterion with ValueSet X" are plain
queries. Every row is D1: the library never holds patient data.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS criterion_library (
  lib_id          TEXT PRIMARY KEY CHECK (lib_id GLOB 'cl_*'),
  canonical_hash  TEXT NOT NULL UNIQUE CHECK (canonical_hash GLOB 'sha256:*'),
  schema_version  TEXT NOT NULL,
  ir_version      TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'deprecated')),
  kind            TEXT NOT NULL CHECK (kind IN ('inclusion', 'exclusion', 'renewal', 'documentation')),
  class           TEXT NOT NULL CHECK (class IN ('structured', 'note', 'human', 'mixed')),
  seed_source     TEXT NOT NULL CHECK (seed_source IN ('chia', 'ctgov', 'site')),
  approved_gate   TEXT,
  approval_id     TEXT,
  supersedes      TEXT REFERENCES criterion_library (lib_id),
  data_class      TEXT NOT NULL DEFAULT 'D1' CHECK (data_class = 'D1'),
  record_json     TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  CHECK (status <> 'approved' OR (approved_gate IS NOT NULL AND approval_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS criterion_library_status ON criterion_library (status, kind);

CREATE TABLE IF NOT EXISTS criterion_library_text (
  lib_id  TEXT NOT NULL REFERENCES criterion_library (lib_id) ON DELETE CASCADE,
  lang    TEXT NOT NULL,
  source  TEXT NOT NULL,
  text    TEXT NOT NULL,
  PRIMARY KEY (lib_id, lang, source)
);

CREATE TABLE IF NOT EXISTS criterion_library_valueset (
  lib_id               TEXT NOT NULL REFERENCES criterion_library (lib_id) ON DELETE CASCADE,
  valueset_id          TEXT NOT NULL,
  sha                  TEXT NOT NULL,
  terminology_version  TEXT,
  PRIMARY KEY (lib_id, valueset_id)
);
CREATE INDEX IF NOT EXISTS criterion_library_valueset_sha ON criterion_library_valueset (sha);

CREATE TABLE IF NOT EXISTS criterion_library_lexicon_key (
  lib_id    TEXT NOT NULL REFERENCES criterion_library (lib_id) ON DELETE CASCADE,
  entry_id  TEXT NOT NULL,
  PRIMARY KEY (lib_id, entry_id)
);

CREATE TABLE IF NOT EXISTS criterion_library_usage (
  lib_id   TEXT NOT NULL REFERENCES criterion_library (lib_id) ON DELETE CASCADE,
  ruleset  TEXT NOT NULL,
  PRIMARY KEY (lib_id, ruleset)
);
CREATE INDEX IF NOT EXISTS criterion_library_usage_ruleset ON criterion_library_usage (ruleset);

CREATE TABLE IF NOT EXISTS criterion_library_meta (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);
"""
