# D-342 The licence register is data, checked at build time; no SNOMED CT ships

- **Task:** T-617b (wave 2 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-617b-licence-register`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Closes:** STD-044 (the rest after T-617a), LLM-012 (licence half), with DEP-011 and PLAN-041 supported

## Context

T-617a wrote `NOTICE` by hand. STD-044 asked for the register behind it as data, for the SNOMED CT remnants to go
(v1 ships without SNOMED CT, Q-22) and for the ATC permission to be asked. LLM-012 found the model licence rows
unchecked and stale, and that nothing read `licence.verified`.

## Decision

1. **One register.** `docs/licences/register.csv` holds one row per source: standard, version, source, licence,
   SPDX id, obligation, holder, status (`cleared`, `own-work`, `synthetic`, `site-loaded`, `permission-to-ask`,
   `removed`), date checked, evidence, licence text sha256 (models), the Athena vocabularies it covers and the
   shipped files it covers (patterns).
2. **The build check.** `python -m tools.licence_register --check` (CI job `docs`, and a unit test) fails when a
   shipped data file has no row, a pattern is stale, a shipped data file names SNOMED CT, a vocabulary the Athena
   loader allows has no row, or a model licence row disagrees with its register row. A shipped data file is a code
   list, map or value set in the demo image (the detector of `tests/unit/test_notice.py`), or any data file in the
   same folder.
3. **Model licences.** In `models/registry.yaml`, `verified: true` needs `register: <id>`, a `model` row with the
   same repository and SPDX id, read from the source at a named revision. A build past `candidate` needs a verified
   licence. `qualify` checks the same, refuses a weight folder with no licence file, and refuses a licence file
   whose sha256 differs from the row's when the row records one.
4. **No SNOMED CT.** The three remnants go:
   - the MIMIC ICU map uses ICD-10-PCS (U.S. public domain). Ventilation is coded by its charted hours; with no end
     time it takes the shortest band;
   - the OMOP measurement operators keep OHDSI's concept ids but not the SNOMED CT vocabulary and codes
     (vocabulary `None`, as concept 0);
   - the TWPAS route code is TW Core's `medication-path-tw` `PO` (CC0).
   A hospital feed that sends SNOMED CT codes is still read; the box only ships none.
5. **ATC.** The request text is `docs/licences/atc-permission-request.md`. It is not sent from the repository. The
   row stays `permission-to-ask` until the owner sends it and records the answer.

## Consequences

- A new code list, map or value set in the image needs a register row in the same pull request.
- The Gemma 4 NVFP4 repository has no LICENSE file. Before `qualify`, the operator puts the Apache 2.0 text in the
  weight folder.
- The embedder (BGE-M3, MIT) has a register row but is not yet a build in the registry (LLM-012).
- `NOTICE` is still written by hand from the register. Rendering it from the CSV is left open.
