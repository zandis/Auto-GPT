<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Defects found by run 20261114T014216Z-cb850470

For the integrator. One entry per failed part or failed check. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Card**.
- **Status**.

Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.

### D1. `g8-protocols`, stage "G-8 public protocols compiled with the production judge": a failed check

- **Symptom.** The check "2 protocol(s) compiled with the production judge" failed. It returned: `["KeyError: 'ValueSet VS_CDR_SCORE not defined for ruleset G8P2'"]`
- **Evidence.** parts/g8-protocols.json, stage "G-8 public protocols compiled with the production judge"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.
