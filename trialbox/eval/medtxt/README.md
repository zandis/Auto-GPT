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
- `results/s2_miss.json`: the S2 miss rate (`python -m tools.medtxt_s2`, no model). Per positive finding, does a key of
  S2's own lexicon (the shipped terms, no site table) hit the finding's sentence, ja and en; `no_key` = no key in that
  script. `fix_list_ja` lists the missed Japanese findings (the tagged words, their English wording and counts)

## Caveat on `results/s2_miss.json`: working estimate

working estimate: NOT for FACTS or any external figure until FU-1652.

The tool has three known measurement limits (review of PR 1652, N1 to N3). The counts in the file are unchanged and
are not corrected for them:

- N1: a Japanese finding and its English finding are paired by order of certainty. If the translation lists findings
  of the same certainty in another order, the pair is wrong and the Japanese finding is scored against another
  finding's English wording (the fix list swaps the English labels of colorectal carcinoma and psoriasis).
- N2: if one report has a second positive tag with the same English wording, that second one is dropped, even when its
  Japanese sentence would have been a hit or a miss of its own. The counts depend on mention order.
- N3: a report where one tag has no match in the other language is left out whole, so its other positives are not in
  the denominator. The miss rate is therefore a rate over the scored positives, not over all 1,690.

FU-1652 fixes N1 to N3 and replaces the file; until then do not quote the rates.
