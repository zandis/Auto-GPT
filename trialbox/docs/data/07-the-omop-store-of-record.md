# 7. The OMOP store of record

OMOP CDM v5.4 in the box's Postgres is the store of record for clinical facts (D-144); the first slice is D-151. The
schema `omop` of the trial database holds the official v5.4 tables (DDL from OHDSI/CommonDataModel v5.4.2, pinned by
sha256 in `services/omop/ddl/pin.json`) and TrialBox's `tb_*` tables beside them: record status, provenance (batch,
file, row), the history of every record, and open and resolved conflicts. It is in every backup.

- **What goes in.** The adapter's NDJSON snapshot (the hospital feed) and the site's published inputs, with
  pseudonyms only: `person_source_value` is the pseudonym, `person_id` an integer minted once. Every code is kept as
  sent in `*_source_value` (ICD-10, LOINC, ATC, NHI, YJ, ...) with a local source concept (ids from 2,100,000,000;
  `TB_OMOP_CONCEPT_BLOCK`); the standard `*_concept_id` is 0 until the vocabulary bundle is loaded.
- **Deletes are tombstones.** A record the hospital no longer sends leaves the standard table; its last content and
  the night it went are kept in `tb_record_event`, with the reason `deleted at the source` or `left the feed` (§9).
- **Disagreements are recorded.** Two sources that give a patient different birth dates, sexes or dates of death open
  a conflict; screening reads the item as unknown until the steward (or the PI, for their study) resolves it. A
  conflict ends only when the sources agree again or a person resolves it: a source that stops sending the item (a
  feed that lacks the patient one night, a deleted sheet row) ends nothing (T-201, D-426). The steward's page
  **Clinical conflicts** (`/data/conflicts`) lists them with each source's value and keeps one value, or keeps the
  item unknown, with a reason; the lake reads the choice from its next rebuild.
- **The lake.** The flag `lake.source=omop` builds the screening lake from OMOP with the same tables and rows; the
  default is still `legacy` (flattened from the NDJSON) until the flag flips on the box (WS-03.5, D-384: CI builds the
  goldens and `e2e_simple` from both sources; the flip procedure is in [Go-live acceptance](../runbook/06-go-live-acceptance.md)
  §6.1). Commands: `python -m omop load --lake <lake>`, `python -m omop status` and `python -m omop dqd` (the Data
  Quality Dashboard-style checks).
- **As of a time** (D-384). Every change event keeps the record as it was (`tb_record_event.record_before`), so the
  lake can be exported as the store stood at an earlier time: `export_rows(db, as_of=...)`. The content (which
  records, values, status, conflicts) is that of the time; an unchanged record's provenance columns and row order are
  those of the last night that carried it.
- **NOTE and NOTE_NLP from site setup** (D-384). A chart a site publishes is a NOTE; a fact read from that chart is a
  NOTE_NLP row (the fact's term, its status in `term_modifiers`). The fact's quote stays in site setup.

## 7.1 Vocabulary

The OMOP vocabulary tables of schema `omop` are the one home of the codes the box reads (D-301; no second schema).
`services/omop/vocab_load.py` loads, each as a release (name, sha256, version, source in `tb_vocab_release`):

- **the terminology Parquet** the compiler ships (ICD-10-CM, LOINC, ATC, the NHI lists, departments, the
  groupers): concepts, zh-TW names as `concept_synonym`, NHI drug to ATC and panel links as
  `concept_relationship`; the compiler's row beside each concept in `tb_concept_attr`;
- **a code-list release** such as ICD-10-CM FY2027 (`read_code_list`: the CMS order file or `code,display` CSV);
  codes it no longer lists are marked deleted, never removed;
- **the refdata pack's terms** (D-140), **the JP masters** a site loaded with `adapter.licensed` (D-137: MEDIS, JLAC10,
  YJ, each linked to the standard code its file gives; a WHO-only ICD-10 code to its ICD-10-CM category), **edition
  maps** such as the NHIA ICD-10-CM 2014 to 2023 map (`source_to_concept_map`, relation in `tb_map_relation`; a record
  before 2025-01-01 gets the 2023 code with a provenance tag, a split or a candidate gives none);
- **the site's local codes** once a person mapped them (`sitesetup.local_code`): a local concept in the site block and
  a `source_to_concept_map` row (not a release: a map changes data, not a compiled ruleset);
- **a release of the consortium's code-map registry** (T-316b, D-419): `tools/codemap_release.py load` verifies the
  release (a refdata pack part with its signed record `codemap.json`; a changed file or a bad signature is refused)
  and loads it in one transaction: the registry's shared concepts at fixed ids, each map as `map:codemap-<id>`, a map
  the release dropped taken out, and the active `CODEMAP` release row. `omop.vocab.release` (and `python -m omop
  vocab status`) names it beside the terminology release.

Ids: the code-map registry's concepts take fixed ids in 2,005,000,000 to 2,009,999,999, the same on every box, in the
ranges its `registry.json` gives each owner; reference codes loaded without the Athena bundle take box-local ids
2,010,000,000 to 2,099,999,999; the site's
local codes take the site block of one million ids from `TB_OMOP_CONCEPT_BLOCK` (default 2,100,000,000; a block that
would end above 2,147,483,647 is refused). No id at or above 2,000,000,000 is ever `standard_concept = 'S'`.

Loading the same content twice changes nothing. A ruleset records the terminology release it was compiled against
(`terminology_release` in its manifest). When a release the compiler resolves through loads (the Parquet, ICD-10-CM,
LOINC, ATC), every approved ruleset is listed in `tb_ruleset_release` with `recompile_needed`, and a run of a ruleset
compiled against another release is refused until it is recompiled. `TB_TERMINOLOGY_SOURCE=vocab` makes the compiler
read the vocabulary (default `parquet`: the shipped Parquet, as before; both give the same ValueSets and SQL).

Chart numbers: `TB_CHARTNO_RULE` (`asis`, the default; `digits[:width]`; `hex[:width][:upper|lower]`) is the site's
chart-number format; `tb_common.chartno.normalise` applies it wherever a chart number becomes a pseudonym, so a
zero-padded number in a PI's list joins the feed's unpadded one (R-48).
