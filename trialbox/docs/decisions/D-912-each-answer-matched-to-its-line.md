# D-912 Each extracted criterion is matched to its line

- **Task:** red of lane G's frozen-commit run (#639, 2026-11-16: "model returned N criteria for M lines", HTTP 422, twice); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - An answer with another count of criteria than lines no longer refuses the whole compile.
  - Each answer is matched to its line by the line's text, which the prompt has the model copy verbatim, in order.
  - Lines left without an answer are asked once more, alone. Naming the mismatch to the model would need a new prompt version, because the template shows the lines only, as data.
  - A line still without an answer, or one the model answered twice (it split the line), is kept as a person's check. It is flagged `not_extracted` or `split_by_model` with `needs_review`, and said in the review's warnings.
  - An answer in the model's own words is read by position when the count agrees, as before.
  - Nothing is dropped or merged in silence. Line-anchored extraction (a line id in the answer) was not chosen: the copied text already anchors each answer, and an id needs a new prompt and output schema.
- **Test:** `tests/unit/test_ir_extract_aligned.py`.
