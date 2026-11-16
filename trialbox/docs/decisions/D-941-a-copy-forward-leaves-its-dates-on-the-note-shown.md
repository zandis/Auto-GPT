# D-941 A copy-forward leaves its dates on the note shown

- **Task:** a safety finding on merged D-905, from the adversarial review of D-940 (#639, 2026-11-16). D-905 shows a note copied forward with the same text once, as the newest copy, and the older copies' dates disappear. "Last dose of pembrolizumab given today", written in January and copied into a June note, was read only under June's date, so a washout criterion would read the dose as June. Before D-905 both dates were shown, and the copy could be seen. Lane A2's backlog (#639). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **The dates go on the shown note.** The note shown for a set of identical copies carries `same_text_also_written_on`: the other copies' dates, oldest first, leaving out the shown note's own date. The models read excerpts as JSON, so they see that the same text was also written on those days. The prompt's text and template are unchanged; only the excerpt's data grows.
  - **Everything else is as before.** A copy of the same day adds no date. A note with no copy carries no such key. Nothing is newly hidden, and `left_out` and `duplicates` are as before.
  - **D-940 is dropped.** The partial copy-forward (an older note whose lines a newer note repeats and extends) stays dropped as built (D-311). Its set-of-lines comparison lost headings and negation, and it lost dates. If it is taken up again, it needs the older lines as one ordered block in the newer note and the dates carried this way.
- **Test:** `tests/unit/test_copy_forward_and_boilerplate.py` (the D-941 part).
