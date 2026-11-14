<!-- written by deploy/gcp/results_report.py: do not edit by hand, run the reader again -->

# Defects found by run 20261114T061459Z-02858674

For the integrator. One entry per failed part or failed check. Each entry gives:

- **Symptom**: what was seen.
- **Evidence**: where it can be checked.
- **Cause**.
- **Fix**: what should change.
- **Card**.
- **Status**.

Cause, Fix and Card are empty: the integrator fills them. Lane G changes no product code.

### D1. `scenario-public-medtxt`, stage "MedTxt-CR (ja): case reports pasted, conditions read, negations kept out": a failed check

- **Symptom.** The check "no proposed condition rests only on a mention the corpus marks negative" failed. It returned: `['CR:JP0245-4: 右乳癌術後（４年前）', 'CR:JP1220-162: 平成２年４月４日に食道癌根治術施行。', 'CR:JP1553-37: ７年前に胸腺癌手術', 'CR:JP1553-37: ５年前に下肢静脈瘤手術。', 'CR:JP1553-72: 既往に開腹胆摘、上行結腸早期癌ＥＭＲがある。']`
- **Evidence.** parts/scenario-public-medtxt.json, stage "MedTxt-CR (ja): case reports pasted, conditions read, negations kept out"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D2. `scenario-public-trec`, stage "TREC CT: real trials, patient descriptions, qrels as truth": a failed check

- **Symptom.** The check "every criterion answered" failed. It returned: `7`
- **Evidence.** parts/scenario-public-trec.json, stage "TREC CT: real trials, patient descriptions, qrels as truth"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.

### D3. `scenario-public-trec`, stage "TREC CT: real trials, patient descriptions, qrels as truth": a failed check

- **Symptom.** The check "eligible patients lost by the pair <= 10 % (VALIDATION §3: 3.1 % on the deployed files)" failed. It returned: `(12, 50)`
- **Evidence.** parts/scenario-public-trec.json, stage "TREC CT: real trials, patient descriptions, qrels as truth"
- **Cause.**
- **Fix.**
- **Card.**
- **Status.** Open.
