# D-301 The vocabulary schema: OMOP's vocabulary tables as the one home of codes, the release pin, one chart-number normaliser

**D-301 The OMOP vocabulary tables of schema `omop` are the one home of the codes TrialBox reads; rulesets pin the
terminology release they were compiled against and are refused against another until recompiled; the site concept
block is one million ids; one chart-number normaliser; WHO-only ICD-10 codes count inside their ICD-10-CM family; the
NHIA 2014 to 2023 edition map applies to dated records with a provenance tag.**
Task T-105 (WS-03.3). PR #82 (`agent/T-105-vocabulary-schema`), on master after T-104 (PR #89, D-204). Numbered
D-205 while in draft; renumbered D-301 (plan v6 §6.1 item 3: master's D-205 is the committed goldens). Date 2026-11-10.
Status: proposed (in review). Trace: URS-STW-03, RSK-06; TST-UNIT-04.

## Decision

* **One home, no second schema.** D-151 created the OMOP vocabulary tables in schema `omop`; WS-03.3's `vocab` is
  those tables. `services/omop/vocab_load.py` loads into them, each load a release (`tb_vocab_release`: name, sha256
  of the content, version, source): the compiler's terminology Parquet (concepts per vocabulary, zh-TW names as
  `concept_synonym`, NHI drug to ATC and panel links as `concept_relationship`, the compiler's groupers in
  `tb_term_grouper`, the row the compiler reads beside each concept in `tb_concept_attr`, as D-151's `tb_record.extra`
  carries what a CDM row has no column for); a code-list release (ICD-10-CM FY2027: CMS order file or `code,display`
  CSV; codes it drops become `invalid_reason = 'D'`); the refdata pack's terms (D-140); the JP masters a site loaded
  with the existing loader (`adapter.licensed`, D-137; consumed, not rewritten); edition maps in the refdata parsers'
  row shape; and the site's mapped local codes (`sitesetup.local_code`, D-135) as site-block concepts with a
  `source_to_concept_map` row. Migration 3 of the `omop` store adds the tables (D-204: a new version, never an edit).
* **Ids.** Reference codes loaded without the Athena bundle take box-local ids 2,010,000,000 to 2,099,999,999
  (`tb_ref_concept_seq`), above TrialBox's shared concepts and the catalogue's range. The site's local codes take the
  site block. **The block is one million ids** (the D-151 overflow fix: 47 sites below 2,147,483,647 where ten million
  fitted four); a `TB_OMOP_CONCEPT_BLOCK` whose block would end above 2,147,483,647 is refused (the box does not
  start), never cut short; minting past the block's end is refused by the sequence. Migration 2 keeps its applied
  text (the ten-million `MAXVALUE`); migration 3 narrows the sequence. **No id at or above 2,000,000,000 is ever
  `standard_concept = 'S'`**: every load checks it and rolls back otherwise. The OMOP loader's own lookups are
  unchanged (`*_concept_id` takes only ids below 2e9 with `'S'`, so the D-151 parity is untouched).
* **Same codes, new home.** `criteria_compiler/terminology/resolver.py` is the one module that says where ValueSets
  resolve: `TB_TERMINOLOGY_SOURCE=parquet` (default, the shipped Parquet as before) or `vocab` (the same tables read
  back from the vocabulary, `vocab_load.term_tables`). A vocabulary loaded from the shipped Parquet gives back exactly
  its rows; every committed ruleset's ValueSet names map to the same codes and render the same SQL through both homes
  (test). The committed rulesets, their ValueSets and SQL are not changed.
* **Release pin and recompile flag.** The terminology release is `TR-` and 12 hex over the active releases the
  compiler resolves through (the Parquet, ICD-10-CM, LOINC, ATC); the Parquet's own release and the vocabulary's after
  loading only that Parquet are the same id. The compiler writes it into a new manifest
  (`terminology_release`, schema `ruleset_manifest`). When such a release loads, every approved ruleset is listed in
  `tb_ruleset_release` with `recompile_needed` (a ruleset pinned to the new release is not). A run
  (`orchestrator.scenarios.review.approved_or_none`, through `tb_common.ruleset.load_approved(terminology=...)`) of a
  ruleset pinned to another release, or listed for recompiling, is refused (`RecompileNeeded`) until it is recompiled;
  a manifest without a pin (compiled before D-301) is refused only once the vocabulary lists it. Releases the compiler
  does not read (refdata terms, JP masters, edition maps) change no pin. Loading the same content again changes
  nothing (no new row, no new mark).
* **One chart-number normaliser** (`libs/tb_common/chartno.py`, R-48). `chartno.normalise(site_rule, value)` is the
  only place leading zeros, width and hex case are handled; the site's rule is `TB_CHARTNO_RULE` (`asis` default:
  full width to half width and blanks only; `digits[:width]`; `hex[:width][:upper|lower]`). `tb_common.crypto.
  pid_for_mrn` applies it, so every path from a chart number to a pseudonym (the feed's mapping engine and bulk
  loader, `adapter.pidmap`, site set-up's sheets and charts, a CRC typing a number) agrees; `PidMap` stores the
  number written the site's way and keeps one row per pseudonym. Under the default rule a chart number already
  written the hospital's way hashes and is stored exactly as before (test against the D-09 formula).
* **WHO-only ICD-10** (baseline correction 3). A grouper's ICD-10-CM family (D-113) also covers the WHO ICD-10 codes of
  its prefix: `ValueSets.families` returns each ICD-10-CM family together with its WHO ICD-10 twin
  (`resolver.family_systems`), so both engines read it without a change to the SQL or CQL generator. A WHO-coded
  record inside the family that is not one of the ValueSet's codes (the ValueSet lists ICD-10-CM codes only, so every
  WHO-coded record: `M10.97`, and also `M10.9`) makes the criterion unknown, never a silent false; outside every family
  the record still fails closed through D-130 (`unknown_code_system`). A ValueSet without a family (a plain list) is
  unchanged. The JP masters link a MEDIS code's WHO target to the ICD-10-CM code when it is one (D-137), else to its
  ICD-10-CM category (`TB in CM family`), else to nothing.
* **NHIA 2014 to 2023 map.** `vocab_load.edition_code` gives a record dated before 2025-01-01 the map's single 2023
  target with a provenance tag (`map:<name>@<version>:<relation>:<2014 code>`); a split, a candidate (`relatedto`) or
  no row gives none (the record stays as coded; never a guess). Tested on synthetic rows in the parser's shape.

## Not done here, and why

* The sibling's TW refdata (PR #65, D-170 to D-172) is on master: its parser's rows (`refdata_tw.icd_map_rows`) load
  through `vocab_load.load_concept_map` unchanged (test). `edition_code` is not yet called by the adapter for TW
  records before 2025 (the adapter's pipeline is not this card's; T-105b).
* The console mapping page reads and writes `sitesetup.local_code` through the orchestrator's set-up API; those maps
  reach the vocabulary with `python -m omop vocab local --ws <ws>`, not on each save (the page and its API are owned
  elsewhere).
* Unmatched sheet pseudonyms are not yet listed at publish (R-48's second half).
* `make goldens-check` (T-006, master's D-205) is the merge gate: it passes on this branch with the goldens unchanged.
* The compiler reads its terminology once at start: after a release loads with `TB_TERMINOLOGY_SOURCE=vocab` it
  must be restarted to compile against the new release (until then its rulesets are pinned to the old one and are
  refused, which is safe).
