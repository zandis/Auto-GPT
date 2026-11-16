# D-952 An approval loads the FHIR server before it releases

- **Task:** G3 of the integrator's second review of the P1b run (#639, 2026-11-16). On NCT00910715 and NCT02380352 the FHIR server refused the approval's load of libraries and value sets (`FhirEvalError`). `Compiler.approve` loaded only after writing the approved files, tagging and promoting the ruleset, and the load was unguarded. So the ruleset was left approved and released while the job failed with an HTTP 500. **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** The load runs before anything is written. A refusal (`FhirEvalError` or a transport error) is a `CompileFailed` at the approve step, which the API answers with a 422. It carries the server's text and is logged. The repo then has no approved files on main, no tag and no promotion, so the reviewer can approve again once the cause is fixed.
  - A load that succeeds approves as before.
  - Libraries and value sets loaded for an approval that then fails to write are harmless: no released ruleset names them, and the next approval overwrites them by id.
- **Not in this card:** the cause of those two refusals. G1 is the ValueSet id over 64 characters, and G11 is the server's text being hidden by D-910.
- **Test:** `tests/unit/test_approve_loads_fhir_first.py`. Two of its tests fail on master.

**Amended 2026-11-16 (after D-959 merged):** the refusal no longer carries the error's raw text, which an `$evaluate` error can fill with a patient's id. A `FhirEvalError` is said through `tb_common.fhir.server_said` (patient references and identifier-shaped tokens masked), in the job's error and in the log; a transport error (`httpx.HTTPError`) is named by its type. Test: `test_a_patients_id_in_the_servers_refusal_is_masked`.
