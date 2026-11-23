# D-1182 Every code system loads at install, in one step from one manifest, into the vocabulary and the FHIR store (V-18)

- **Task:** lane V, card V-18 with lane DB's DB-C1 (the owner's rulings and the integrator's comments 7103992051,
  7105754899, 7105876634 and 7107896921 on #639) · **Date:** 2026-11-23
- **Status:** reserved for V-18 (the integrator flips the row when merged)
- **Builds on:** D-1028 (code systems are loaded at install), D-1029 (US public-domain code data may be committed),
  D-1114 (a licensed table names who accepted its licence), D-991 (the services read the loaded code systems)
- **Amends:** D-1181 point 1 ("at install the FHIR store needs nothing but its image and its database"). Its other
  points stand: each ValueSet still reaches the store expanded, and one with no code still lists the no-member code,
  so the compile's equivalence check does not wait on the store's terminology.

## Decision

1. **What goes into the store.** `python -m tools.fhir_codesystems load` loads each code system the box carries as a
   `CodeSystem`, and lane M's mapping tables as `ConceptMap`s:
   - ICD-10-CM;
   - LOINC;
   - ATC;
   - the NHI order codes;
   - the department system;
   - ICD-10-PCS and WHO ICD-10 when loaded at install;
   - the lab, JLAC10, MEDIS and YJ maps.
2. **Only where the licence allows.** A shipped table is loaded when its row of `docs/licences/register.csv` is
   `cleared`, `own-work` or `synthetic`. A table loaded at install (`TB_TERMINOLOGY_DIR`) is loaded when its manifest
   line vouches for it; for a licensed table, that line names who accepted the licence (D-1114). Such a table takes
   the place of the shipped table of its system. ATC's row is `permission-to-ask`, so the shipped `atc.parquet` is not
   loaded; an ATC index the site loads itself is.
3. **Install never stops for a code system.** A system that is missing, refused or not allowed gets a warning, and the
   load goes on. Only a fault (a copy given but refused, or a system given but not stored) is also a line of
   `poc-stops.jsonl` (key `fhir_codesystems/<system>`).
4. **One resource per system.** Each system is a single resource, `tb-<key>`. It carries:
   - a name;
   - a version, which is the source's version plus the first 8 hex of its content hash (`FY2026+4e43519a`);
   - the full sha256 of its content, as an `identifier`;
   - the version it replaces, with that version's history id.

   ICD-10-CM carries its hierarchy: nested concepts, plus each code's `parent` property, which `$lookup` returns.
5. **Update.** `load` is the manual update: one command. It writes new content over the resource, and the store
   keeps the earlier version in the resource's history. Content that has not changed is not written again. The
   scheduled update from the signed bundle runs this same command; it is wired into `update.py` once the owners of
   those files say go (the question on #639).
6. **Rollback.** `rollback <system>` writes back the version the current one replaced, taken from the store's history.
7. **The doctor.** `status` gives each system's version, its hash and the version it replaced. The doctor shows these
   lines once its owner says go.
8. **No early question.** After writing a system, `load` waits, up to `--wait` seconds (default 900), until the store
   answers `$lookup` from the new version. The store stores a large system's codes in the background (98,186 in
   105 s here), and a "not found" it gives meanwhile is cached for that code for minutes. So `load` first waits for
   the time the store takes for that many codes, then asks a code stored late, a different code each time.
9. **The test.** `tests/integration/test_fhir_codesystems_compose.py`: on the stack's store, a loaded code is
   validated, named and placed under its parent; ATC is skipped by its licence; an update names what it replaces; a
   rollback puts it back. `tests/unit/test_fhir_codesystems.py` covers the rules with a store in memory.

10. **One manifest, one step, three readers (DB-C1).** The manifest is the terminology: the tables shipped in the
    image and the tables loaded at install into `TB_TERMINOLOGY_DIR`. Its digest is the release (`TL-` and 12 hex).
    `deploy/terminology-update.sh` is the one step, at install (run by `install.sh` after the reference data) and as
    the manual update:
    1. The hospital's folder goes into the volume, with no network (`terminology_install folder`).
    2. `python -m tools.terminology_load load` loads the vocabulary (`omop.concept`: the shipped Parquet, and each
       loaded table as its system's code list) and the FHIR store from the same rows, in one run.

    The report goes to `deploy/site/terminology-load.json`. The doctor fails when it names another release than the
    terminology now, or a reader failed.
11. **The hospital's licensed copies.** SNOMED CT, the UMLS and the ATC/DDD index come from the hospital's own copy,
    in its publisher's format. The repository and the bundle never carry them.
    - **SNOMED CT:** an RF2 Snapshot, International or national.
    - **UMLS:** a MetamorphoSys RRF subset (MRCONSO, MRREL).
    - **ATC/DDD index:** xlsx, CSV or TSV.

    Each is verified by its own manifest (`MRFILES.RRF`), a `SHA256SUMS` beside it, or the sha256 the person recorded,
    else by its own headers; the manifest line says which. Each needs the named person who accepted the licence
    (D-1114): `--accepted-by`, or the folder's `acceptance.json`, which lane U's install question writes. SNOMED CT is
    loaded under the owner's academic, non-commercial ruling; `snomed_problems` still blocks shipping any. The folder's
    layout: `docs/handover/terminology-folder.md`; its place, `TB_LICENSED_DIR` (default `deploy/site/terminology`).
12. **What is still needed.** A system not loaded is a line of `deploy/site/needed.jsonl`, which the U-5 page reads
    (U5-1). The line says why, whether it is a fault, and that `deploy/terminology-update.sh` loads it. A system the
    box was not given (no folder for it, nothing shipped, or a licence the box may not carry) is expected, not a fault.
    On the installer's run each fault is also a line of `poc-stops.jsonl`; an expected one is not, so a box given
    nothing lists nothing (H-94: the rehearsal box's install lists nothing). Nothing stops.
13. **Backups.** A table built from a licensed copy (its manifest line names who accepted the licence) and the
    hospital's folder `deploy/site/terminology/` never reach a backup target. `manifest.json` is kept, with each
    system's name, version and hash. A restored box reloads the tables from the hospital's folder; until then the
    doctor names each missing table.
14. **The mapping check** (`tools/mapping_coverage.py`) reports a mapped code that is missing from a system loaded at
    install (LOINC, ATC, the NHI service codes).
15. **The update bundle.** A bundle may carry a code system the box may carry, as payload kind `terminology`
    (`<command>/<file>`: `icd10cm`, `icd10pcs`, `nhi-drugs`, `nhi-services`, and the folder's `VERSION`).
    `tools/release.py`, `tools/sign_bundle.py` and `tools/verify_update.py` refuse any other: a licensed system never
    ships. After the release passed its check, the update does three things:
    1. It keeps the volume's tables aside in `deploy/terminology/previous/<bundle>` (never a licensed one).
    2. It loads each file with no network.
    3. It loads the vocabulary and the FHIR store from the one manifest.

    `deploy/terminology-update.sh --rollback <bundle>` puts the kept tables back, takes away what the update added,
    and reloads both readers. A failure leaves the healthy release, as the reference data's does.
16. **Not in this card.** The scheduled update is V-19; the install question is lane U's.

## Why

The owner's ruling: the store validates codes and gives their names and hierarchy, and the code systems can be
updated and rolled back. One resource per system, because several `CodeSystem` resources with one url left the store
answering from an older one after an update and after a rollback. The licence register is already the one place that
says what the box may carry. Reading it means no second list can drift from it.

## Not chosen

- One resource per version, with `active` and `retired` statuses: the store did not follow the status, and kept
  answering from an older version.
- Loading the shipped ATC names: its licence row asks for written permission first.
- Validating records with the store on write: not asked for. The store validates when it is asked to.
- A second manifest file beside the loader's: the loader's `manifest.json` and the shipped tables are already the
  manifest, so a second file could only drift from them.
- Fetching the licensed copies with the hospital's account: the box never fetches. A person downloads them, and the
  box reads them from the folder.
