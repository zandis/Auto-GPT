# D-959 A FHIR refusal says what the server said, masked

- **Task:** G11 of the integrator's second review of the P1b run (#639, 2026-11-16). D-910 kept only the error's type and status when the FHIR server refused a ruleset ("FhirEvalError, HTTP 422"), because an `$evaluate` error can quote a patient's id, and the 422 left no log line. 16 of the run's protocols failed with nothing to act on; the causes were a ValueSet id over 64 characters (G1, D-955) and an encounter atom (G2, D-957). **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** `tb_common.fhir.server_said` gives what the server said, safe for a job's error and the log:
  - patient references (`Patient/…`, `subject=…`) are masked;
  - identifying keys such as `mrn=…` are masked (`audit.mask_ids`);
  - identifier-shaped tokens and secrets are masked (`logging.redact`);
  - the text is cut at 300 characters.

  The compiler's equivalence refusal carries it after the type and status, and logs it.
- **Next:** once D-952 is merged, its approval refusal (G3) will use the same function.
- **Test:** `tests/unit/test_fhir_refusal_says_why.py`.
