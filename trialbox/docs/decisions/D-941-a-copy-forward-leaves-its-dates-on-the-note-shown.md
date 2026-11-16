# D-941 A copy-forward leaves its dates on the note shown

- **Task:** a safety finding on merged D-905, from the adversarial review of D-940 (#639, 2026-11-16). D-905 shows a note copied forward with the same text once, as the newest copy, and the older copies' dates disappear. "Last dose of pembrolizumab given today", written in January and copied into a June note, was read only under June's date, so a washout criterion would read the dose as June. Before D-905 both dates were shown, and the copy could be seen. Lane A2's backlog (#639). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **The copies' first date goes on the shown note.** The note shown for a set of identical copies carries two short values (`tb_llm.budget.COPIES`):
    - `same_text_first_written`: the earliest day the same text was written;
    - `same_text_copies`: how many other copies, of other days, there are.

    A copy of the same day adds nothing. A note with no copy carries neither value. They never grow into a list, whatever the number of copies.
  - **Every path sends them.** What a model is shown of an excerpt is now one function, `tb_llm.budget.shown`. It gives the date, the note type and the text, as D-644 set (never the record's id), plus the copies' two values where the excerpt has them. The cascade's judge and verifier (`GatewayJudge`) and v1 evaluate and CASE (`NoteJudge.judge_excerpts`) all send it.
  - **The budget counts them.** `excerpt_tokens` counts what is shown, and `build` adds the two values' cost to the note's. A note that fits only without them is not squeezed in.
  - **Unchanged.** The prompt's text and template are unchanged; the models read excerpts as JSON. Nothing is newly hidden, and `left_out` and `duplicates` are as before.
  - **The judged-pair store.** Its digest (D-908) changes once for a note with copies, so such pairs are asked again once.
  - **The review (adversarial, required: what the models read).**
    - **Blocker, fixed.** The first version added a list of dates to the excerpt, but both judge paths sent only the three D-644 fields, so no model saw it, and the tests checked only `build`. The tests now check what a model is sent, and the code-path assertions name both senders.
    - **Fixed.** A list of every copy's date was not budgeted and could grow to thousands of tokens. It is now two values, counted.
  - **D-940 is dropped.** The partial copy-forward stays dropped as built (D-311). Its set-of-lines comparison lost headings and negation, and it lost dates. Taken up again, it needs the older lines as one ordered block in the newer note, with the dates carried this way.
- **Test:** `tests/unit/test_copy_forward_and_boilerplate.py` (the D-941 part).
