# medtxt: reading real Japanese clinical text (NTCIR-16 Real-MedNLP MedTxt-CR / MedTxt-RR)

`tools/medtxt_eval.py`. 215 Japanese case and radiology reports with clinician-made English translations (CC BY 4.0,
Sociocom NAIST, fetched into `.cache/medtxt`, not committed). Each tagged finding becomes "Patients with <finding>."
and is judged against the Japanese original and the English translation; the tag's certainty is the answer key
(present / stated absent / suspected / not mentioned). `_strict` slices drop tags contradicted elsewhere in the report.

- `results/raw/<model>__<lang>.jsonl.gz`: every model answer (`~suspected` = prompt variant)
- `results/scores.json`: block rates per certainty, single models and both-must-block pairs, ja and en
