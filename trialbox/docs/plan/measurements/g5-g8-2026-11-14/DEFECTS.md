<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Defects found by run 20261113T231557Z-0e9be8a5

For the integrator. One entry per failed part or failed check. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Card**.
- **Status**.

Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.

### D1. `g8-protocols`, stage "G-8 public protocols compiled with the production judge": a failed check

- **Symptom.** The check "2 protocol(s) compiled with the production judge" failed. It returned: `['CompileFailed: ir_extract: the model did not return usable criteria (gateway refused ir_extract: role_not_allowed); send the protocol again', 'CompileFailed: ir_extract: the model did not return usable criteria (gateway refused ir_extract: role_not_allowed); send the protocol again']`
- **Evidence.** parts/g8-protocols.json, stage "G-8 public protocols compiled with the production judge"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D2. `g8-protocols`, stage "G-8 public protocols compiled with the production judge": a failed check

- **Symptom.** The check "no extension-phase line active without a warning" failed. It returned: `{}`
- **Evidence.** parts/g8-protocols.json, stage "G-8 public protocols compiled with the production judge"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D3. `g8-protocols`, stage "G-8 public protocols compiled with the production judge": a failed check

- **Symptom.** The check "alternative diagnosis groups not flattened to AND" failed. It returned: `{}`
- **Evidence.** parts/g8-protocols.json, stage "G-8 public protocols compiled with the production judge"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.
