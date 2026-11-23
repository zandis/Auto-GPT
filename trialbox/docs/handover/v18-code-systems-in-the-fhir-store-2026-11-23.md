# V-18: every code system at install, in one step from one manifest, updated and rolled back (2026-11-23)

**Reader:** the people who build TrialBox: the integrator, lane M (its mapping tables), the owners of the install, the
doctor and the update, and the reviewer.

Card V-18 with lane DB's DB-C1 (lane V; the owner's rulings and the integrator's comments 7103992051, 7105754899,
7105876634 and 7107896921 on #639). Decision D-1182. Findings in the register's `--add-from` form:
`v18-code-systems-in-the-fhir-store-2026-11-23/findings.json`. The hospital's folder layout, for the owner:
`terminology-folder.md`.

## The one step (DB-C1)

`deploy/terminology-update.sh` is the step at install (`install.sh`, after the reference data) and the manual update.
It runs two steps:

1. The hospital's folder (`TB_LICENSED_DIR`) goes into the terminology volume, with no network. These loaders are new
   in `terminology.installed`, and each needs the named person who accepted the licence:
   - SNOMED CT from an RF2 Snapshot;
   - the UMLS from a MetamorphoSys RRF subset;
   - the ATC/DDD index as xlsx, CSV or TSV.

   Each copy is verified by `SHA256SUMS`, `MRFILES.RRF` or a recorded sha256.
2. `python -m tools.terminology_load load` loads, in one run and from the same rows, the vocabulary (`omop.concept`)
   and the FHIR store from one manifest: the shipped tables and those loaded at install, their digest the release.

Its report goes to `deploy/site/terminology-load.json`, and the doctor fails when the readers hold another release. A
system not loaded is a line of `deploy/site/needed.jsonl` (the U-5 page) and of `poc-stops.jsonl`; nothing stops.

Two more changes:
- **Backups:** the hospital's folder and the tables built from licensed copies are left out of every backup. The
  terminology manifest, with each system's name, version and hash, is kept, and a restore reloads the tables.
- **The mapping check:** it reports a mapped code missing from a loaded system.

## The FHIR store

`tools/fhir_codesystems.py` is the FHIR store's part of the step, also runnable alone:

    python -m tools.fhir_codesystems load [--deploy DIR] [--wait 900]
    python -m tools.fhir_codesystems status [--json]
    python -m tools.fhir_codesystems rollback KEY

| System | From | In the store when |
| --- | --- | --- |
| ICD-10-CM (98,186 codes, with its hierarchy) | `icd10cm_full.parquet` | always (register row `icd10cm`, cleared) |
| LOINC | `loinc_tw.parquet`, or the site's `loinc_table` | always (row `loinc`, cleared); the site's table in its place |
| ATC | the site's `atc_index` only | the site loaded its index (row `atc` is `permission-to-ask`: the shipped names are not loaded) |
| NHI order codes | `nhi_order.parquet`, or the site's `nhi_service_list` | always (row `nhi-codes`, cleared) |
| Departments | `department.parquet` | always (row `trialbox-terminology`, own work) |
| ICD-10-PCS, WHO ICD-10 | the site's tables | the site loaded them |
| SNOMED CT, UMLS | the hospital's own copies (`snomed_ct`, `umls_concepts`), with their parents | the hospital's folder holds them |
| Lane M's maps (lab, JLAC10, MEDIS, YJ) | the mapping CSVs, as `ConceptMap` | always (their rows are cleared or own work) |

Each system is one resource, `tb-<key>`. It has a name, a version (`FY2026+4e43519a`: the source's version and the
start of its content hash) and the full sha256 as an identifier. An update writes over it and names the version it
replaces; the store keeps the earlier one in the resource's history, which is what `rollback` writes back. A system that
is missing or not allowed is a warning and a line of `poc-stops.jsonl`, and the load goes on.

## How the store behaved (HAPI as pinned, on Postgres)

- **Validation is cached.** After an update or a rollback, `$lookup` and `$validate-code` keep answering from the
  earlier version until the store's validation cache expires: 374 s here, about ten minutes by the store's own
  figure. A "not found" given while the store is still storing a large system's codes in the background is cached for
  that code the same way. The store stored ICD-10-CM's 98,186 codes in 105 s. A first wait that asked one code over and
  over took 609 s, because its own early question was cached. `load` now waits for the time the store takes for that
  many codes, then asks a different late code each time.
- **One resource per url.** With several `CodeSystem` resources of one url (marked active and retired), the store
  kept answering from an older one. With one resource per system, it answers from the current one.
- **`$subsumes` does not work.** It needs the store's full-text index (Hibernate Search), which the deployed store
  does not run. The hierarchy is given instead by each code's `parent` property, which `$lookup` returns.
- **One lookup quirk.** `$lookup` of `M10.00` answers "code[null]", while `$validate-code` finds the same code and
  `$lookup` finds its neighbours.
- **No effect on the compile's equivalence check.** The check still passes with the systems loaded: #1400's store
  test passed, and the GZQO gout criterion still finds its patient.

## Not in this card

- **The signed update bundle's `terminology` payload, with its rollback:** waits for lane H's H-99 (the same files,
  `update.py` and `verify_update.py`).
- **The scheduled update:** V-19.
- **The install question that writes `acceptance.json`:** lane U.

## Run, and not run

- **Run:** the unit tests and the integration test, on a fresh store of the pinned image on Postgres, run on this
  container.
- **Not run:**
  - the install path end to end;
  - the rehearsal;
  - a real SNOMED CT, UMLS or ATC/DDD release (the loaders ran on synthetic files in the publishers' formats only);
  - a store holding a full SNOMED CT.
