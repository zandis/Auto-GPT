# V-18: the code systems in the FHIR store, loaded at install, updated and rolled back (2026-11-23)

**Reader:** the people who build TrialBox: the integrator, lane M (its mapping tables), the owners of the install, the
doctor and the update, and the reviewer.

Card V-18 (lane V; the owner's ruling, the integrator's comment 7103992051 on #639). Decision D-1182. Findings in the
register's `--add-from` form: `v18-code-systems-in-the-fhir-store-2026-11-23/findings.json`.

## What is built

`tools/fhir_codesystems.py`, one command for the install and the manual update:

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

## Waiting on a go (question on #639)

- **`deploy/install.sh`:** one step after `up --wait` that runs `load --deploy`.
- **`tools/trialbox/doctor.py`:** `check_terminology` gains the `status` lines.
- **`tools/trialbox/update.py` and `verify_update.py`:** a `terminology` payload kind and its rollback. There is no
  scheduled updater today ("No auto-update", `apply_update.sh`); the timer is proposed in the question.
- **`tools/mapping_coverage.py` (lane M):** check a mapped code against the loaded system, not only its shape.

## Run, and not run

- **Run:** the unit tests and the integration test, on a fresh store of the pinned image on Postgres, run on this
  container.
- **Not run:** the install path, the doctor and the update (they wait on the go), the rehearsal, and a store with a
  site's licensed tables (none here).
