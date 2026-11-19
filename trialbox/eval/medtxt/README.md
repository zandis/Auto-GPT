# medtxt: reading real Japanese clinical text (NTCIR-16 Real-MedNLP MedTxt-CR / MedTxt-RR)

`tools/medtxt_eval.py`. 215 Japanese case and radiology reports with clinician-made English translations (CC BY 4.0,
Sociocom NAIST, fetched into `.cache/medtxt`, not committed). Each tagged finding becomes "Patients with <finding>."
and is judged against the Japanese original and the English translation; the tag's certainty is the answer key
(present / stated absent / suspected / not mentioned). `_strict` slices drop tags contradicted elsewhere in the report.

- `results/raw/<model>__<lang>.jsonl.gz`: every model answer (`~suspected` = prompt variant)
- `results/scores.json`: block rates per certainty, single models and both-must-block pairs, ja and en
- `key.json`: the answer key of the gate, annotation id -> certainty only (no report text), with the sha256 of the
  corpus files it was built from (`python -m tools.medtxt_gate key` after `fetch`)
- `gate.json`: the control and the candidate pair of the standing gate (`python -m tools.medtxt_gate check`,
  `make medtxt-gate`; D-1325): review 17 §7.3 rules 1 and 2 on the ja items, on the recorded answers
