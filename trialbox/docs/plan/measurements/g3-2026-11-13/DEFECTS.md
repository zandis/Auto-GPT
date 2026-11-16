<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Defects found by run 20261113T044219Z-2b9eec74

For the integrator. One entry per failed part or failed check. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Card**.
- **Status**.

Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.

### D1. `hospital-ja@c1`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-ja@c1.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D2. `hospital-zh-TW@c1`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-zh-TW@c1.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D3. `hospital-ja@c4`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-ja@c4.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D4. `hospital-zh-TW@c4`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-zh-TW@c4.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D5. `g5-tokens`, stage "G-5 token counts: /tokenize against the product's estimates": a failed check

- **Symptom.** The check "the largest real / estimated ratio x 1.05 fits the budget's share (1 / SAFETY = 1.176)" failed. It returned: `{'max_ratio': 1.2121, 'safety_from_measurement': 0.7857}`
- **Evidence.** parts/g5-tokens.json, stage "G-5 token counts: /tokenize against the product's estimates"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D6. `hospital-ja@c16`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-ja@c16.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D7. `hospital-zh-TW@c16`, stage "12 site set-up and data harmonization": a failed check

- **Symptom.** The check "confirmed: it counts like coded data and may exclude (the malignancy), or makes a patient ready" failed. It returned: `(7, {'11636eecbd18695afedf762657d7198c': 'ready', '1d7ad52bf552d27224c430a99575bbf7': 'needs', '2415dcc904961d65cca4011206390fdf': 'not_eligible', '7ea6bc8f855d6b9f78a666947acaa635': 'ready', 'b38a19f2cc4458b55047efdb1f9f9575': 'needs', 'ce6ea4da07c623e0b41e7ac18a98f1e6': 'not_eligible'})`
- **Evidence.** parts/hospital-zh-TW@c16.json, stage "12 site set-up and data harmonization"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D8. `g4-decoding`, stage "G-4 structured output: backend, guided decoding on and off, eager start": a failed check

- **Symptom.** The check "guided on: no answer outside the judge schema" failed. It returned: `1`
- **Evidence.** parts/g4-decoding.json, stage "G-4 structured output: backend, guided decoding on and off, eager start"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D9. `g7-clipped`, stage "G-7 clipped against whole note (LLM-001)": a failed check

- **Symptom.** The check "0 exclusions on a clipped note (no final not met from a clipped note)" failed. It returned: `['LLM-001-zh-TW-denied-list']`
- **Evidence.** parts/g7-clipped.json, stage "G-7 clipped against whole note (LLM-001)"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D10. G-3: the candidate list of hospital-ja depends on the calls in flight

- **Symptom.** The list at 4 in flight differs from the list at 1, 16.
- **Evidence.** parts `hospital-ja@c4`, block `candidates`
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D11. G-3: the candidate list of hospital-zh-TW depends on the calls in flight

- **Symptom.** The list at 4 in flight differs from the list at 1, 16.
- **Evidence.** parts `hospital-zh-TW@c4`, block `candidates`
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.
