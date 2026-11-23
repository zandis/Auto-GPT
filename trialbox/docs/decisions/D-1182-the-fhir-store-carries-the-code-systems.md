# D-1182 The FHIR store carries the code systems the box may carry, and they can be updated and rolled back (V-18)

- **Task:** lane V, card V-18 (the owner's ruling, the integrator's comment 7103992051 on #639) · **Date:** 2026-11-23
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
3. **Install never stops for a code system.** A system that is missing, refused or not allowed gets a warning and one
   line of `poc-stops.jsonl` (key `fhir_codesystems/<system>`), and the load goes on.
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
