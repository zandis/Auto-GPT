# H-128: the approve step seconds on a loaded runner

**Reader:** the people who build TrialBox: the lane H lead, lane A2 and the integrator. Findings for builders, so in
one language.

- **Card:** H-128 (lane H, the integrator's go of 2026-11-24)
- **Date:** 2026-11-24
- **Findings:** [`approve-step-seconds-h128-2026-11-24/findings.json`](approve-step-seconds-h128-2026-11-24/findings.json)
  (H128-01 to H128-02)
- **Tests:** `tests/unit/test_h128_approve_step_seconds_under_load_2026_11_24.py`, and H-45's
  `tests/unit/test_h45_approve_step_seconds_2026_11_19.py` unchanged

## The fault

On CI (job 138429378648, unit shard 6/8, PR #1468) H-45's
`test_compiler_records_its_steps_and_they_add_up` failed on `0 <= steps["compiler.unaccounted"] < 0.2` with
0.7918 s. The steps added up to the wall time; 0.79 s of `Compiler.approve` was in no named step.

## Where the time was

`compiler.unaccounted` is the time between a lap and the next `clock.mark()` of `Compiler.approve`
(`services/criteria_compiler/service.py`). On the approved path there were four such spans: after
`compiler.refresh_installed` (the job id, the date, the decisions), before `compiler.build_artifacts` (the index
date), after `compiler.files` (the FHIR libraries built for the load), and after `compiler.audit_done` (the result).
The third is the only one that reads a file: `fhirhelpers_source()` lists the translator's jars and opens a 4.8 MB jar
on every approval, and the three libraries' CQL and ELM are encoded.

A spy on the clock, with the test run 40 times beside 16 busy processes on 4 cores: that span took 14 to 19 ms, every
other span at most 1 ms. The 0.79 s itself was not reproduced here: 0 of 40 runs failed under that load, and a cold
page cache and a 3-million-object heap did not reproduce it either. A blocked read of the jar, or a full garbage
collection while the libraries are built, in a long-lived CI worker fits it; that is a hypothesis.

## The change

The `clock.mark()` before the FHIR load is gone (one line of a body, lane A2's file): the libraries built for the load
are timed under `compiler.fhir_load`, whose wording in `libs/tb_common/steptime.py` and in
`docs/plan/measurements/approve-profile-2026-11-19.md` now says so. No step name is added or removed. H-45's 0.2 s
bound stays as it was; no assertion changed.

The new test plants a 0.5 s sleep where the FHIRHelpers library is built (in the test's wrapper, not in product
code). On master `compiler.fhir_load` is 0.0 and the sleep is in `compiler.unaccounted`; with the change it is under
`compiler.fhir_load`.

After the change, the same 40 runs under the same load: 40 passed, the largest unnamed span 12 ms (after
`compiler.refresh_installed`).

## Not done

- The other three unnamed spans are left unnamed: none reads a file, and the largest seen under load was 12 ms.
- `fhirhelpers_source()` is not cached; the jar is still read twice per approval (once in `compiler.build_artifacts`).
  That is lane A2's, and it was not asked for.
- Nothing ran on a CI runner; the fix is not shown against the 0.79 s itself.
