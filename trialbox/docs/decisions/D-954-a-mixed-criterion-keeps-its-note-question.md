# D-954 A mixed criterion whose coded part cannot run keeps its note question

- **Task:** G9 of the integrator's second review of the P1b run (#639, 2026-11-16), named the largest quality loss. Of sigir's 772 compiled criteria the model classed 83 as human, and the compiler demoted 370 more. 111 mixed criteria that had a note question went to a person only because their coded part could not run (`postprocess`, D-910). `demote_uncompilable` keeps such a criterion as note (D-98). This is what produced the all-human and notes-only rulesets. **Date:** 2026-11-16. **Status:** reserved.
- **Decision.** In `postprocess`, a mixed criterion whose coded part cannot run (`logic_invalid`) and that has a note question becomes class note, flagged `coded_part_dropped`, when the notes can settle it (`notes_can_decide`). Otherwise a person keeps it, flagged `notes_cannot_decide_<why>`. A structured criterion, or a mixed one without a note question, still goes to a person.
  - **The notes cannot settle a criterion when** any of these holds:
    - **negated_question:** the question is negated, including "lack", which the polarity rewrite does not cover;
    - **negated_line:** an inclusion's line is a negation ("No significant cardiopulmonary disease" asked as "Does the patient have…");
    - **not_in_notes:** the subject is not in the notes: consent, willingness, plans, contraception or childbearing potential, refusal, an investigator's judgement, prognosis, "able to" or "eligible";
    - **inferred:** the answer would be inferred: a score, a count of criteria, an INR or creatinine, "such as metformin";
    - **fragment:** the line is a fragment of an "or", or says "will be included";
    - **threshold:** the question asks a number;
    - **broad_exclusion:** an exclusion that is not a plain "Does the patient have …" of a named condition, or that uses a severity or organ-level word (serious, severe, significant, uncontrolled, major, any, other, medical, problems, impairment, insufficiency, dysfunction, failure, illness, condition, disorder).
- **Adversarial review** (this card). It judged by hand all 173 criteria the first version moved, against the physicians' gold where it covers them.
  - **74 were risky:**
    - 20 exclusions wider than their line;
    - 21 answers that would be inferred from a drug, a lab value or a score;
    - 22 subjects not in the notes;
    - 7 polarity errors;
    - 6 inclusions narrower than their line.
  - Of the risky exclusions the gold covers, 15 of 25 were "not excluded". The first version would have let the models exclude those patients.
  - The rules above are the review's general ones; it also proposed phrases particular to this run, which are not used.
- **On the run's data** (`raw-traces.json`, against master), 43 criteria move from a person to the notes: 27 exclusions and 16 inclusions.
  - 41 of them the review judged safe.
  - 2 it judged borderline: "malignant celiac node involvement" and "a recurrent hematoma".
  - 130 stay with a person, each flagged with its reason.
  - A note exclusion still needs both models to agree and the note-block policy (D-95 / D-97). F6 is the card for the models' inferred diagnoses.
- **Test:** `tests/unit/test_mixed_keeps_its_note_question.py`.

## A coded part that keeps only an age or a sex never excludes (P2b, 2026-11-17)

Lane H's trace of the P2b launch: `Sm3NCT01227499-EXC-04` "women with pregnant or lactation" came out of ir_extract as
mixed with the coded logic `sex: female` alone, its concept candidates naming pregnancy and lactation. A mixed
exclusion present in the codes excludes (D-98), so every woman was excluded at S1 with no model asked, among them a
patient the gold calls eligible. An exclusion whose coded logic is only an age or a sex while its line names more (a
non-demographic concept candidate) has lost its qualifier: it is flagged `qualifier_dropped` and never compiled; as
this card's rule for a coded part that cannot run, the notes decide a mixed one with its question, a person any other.
An exclusion only about age or sex, and any inclusion (which can only be too permissive this way), are left as they
are. Of the 1,156 criteria P2b extracted (sigir 1,151, jmed 4, tcga 1), two had this shape, both pregnancy or
lactation lines in sigir (SM3NCT01227499, SM3NCT00997100).
