# D-954 A mixed criterion whose coded part cannot run keeps its note question

- **Task:** G9 of the integrator's second review of the P1b run (#639, 2026-11-16), named the largest quality loss. Of sigir's 772 compiled criteria the model classed 83 as human, and the compiler demoted 370 more. 111 mixed criteria that had a note question went to a person only because their coded part could not run (`postprocess`, D-910). `demote_uncompilable` keeps such a criterion as note (D-98). This is what produced the all-human and notes-only rulesets. **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** In `postprocess`, a mixed criterion whose coded part cannot run (`logic_invalid`) and that has a note question becomes class note, flagged `coded_part_dropped`, and the notes decide it, as in `demote_uncompilable`.
  - A negated exclusion question is still rewritten in its positive form.
  - A structured criterion, or a mixed one without a note question, still goes to a person.
- **On the run's data** (`raw-traces.json`, against master), 173 criteria move from a person to the notes: 71 inclusions and 102 exclusions. Nothing else changes.
  - **This widens what the models read and can decide.** A note exclusion excludes only when both models agree and the note-block policy allows it (D-95 / D-97). F6 of the same review found both models agreeing on an inferred diagnosis, and that card is what guards that risk.
  - An adversarial review of the moved questions is this card's own.
- **Test:** `tests/unit/test_mixed_keeps_its_note_question.py`.
