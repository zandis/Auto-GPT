<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Defects found by run 20261113T085509Z-c25cea6b

For the integrator. One entry per failed part or failed check. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Card**.
- **Status**.

Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.

### D1. `hospital-ja`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-ja.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D2. `hospital-zh-TW`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-zh-TW.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D3. `g5-tokens`, stage "G-5 token counts: /tokenize against the product's estimates": a failed check

- **Symptom.** The check "the largest real / estimated ratio x 1.05 fits the budget's share (1 / SAFETY = 1.176)" failed. It returned: `{'max_ratio': 1.2121, 'safety_from_measurement': 0.7857}`
- **Evidence.** parts/g5-tokens.json, stage "G-5 token counts: /tokenize against the product's estimates"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D4. `g4-decoding`, stage "G-4 structured output: backend, guided decoding on and off, eager start": a failed check

- **Symptom.** The check "guided on: no answer outside the judge schema" failed. It returned: `1`
- **Evidence.** parts/g4-decoding.json, stage "G-4 structured output: backend, guided decoding on and off, eager start"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.
