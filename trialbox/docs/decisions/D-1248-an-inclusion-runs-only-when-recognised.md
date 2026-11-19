# D-1248 Running an inclusion only when its line is recognised as a plain assertion: a measured experiment (10A-1d)

- **Task:** lane J, plan 10 card 10A-1d, after 10A-1c (#1180, D-1246). · **Date:** 2026-11-19 · **Status:** not
  adopted. The rule was built and measured in #1184, which stays a draft and does not go on the train. This record
  keeps the rule, the measurements and the conclusion.
- **What a count here means:** each count below is a count on the lines named with it, at the commit named. None is
  a claim about the reader on other lines.
- **The question.** The cue reading (10A-1 to 10A-1c) holds an inclusion when its line carries a negation cue, and
  runs it otherwise. On master, of lines where the coded concept is not a present fact of the patient, two testers'
  sets ran 60 of 186, 53 of 57, 121 of 194 and 62 of 73; after #1180, 0, 0, 72 and 40. Most of the second tester's
  are not negations (a drug stopped or refused, a plan, another person's condition, remission, a heading, a
  checkbox). The card turned the default round: run only a line positively recognised as a plain assertion, hold
  everything else, keep the cue rules as a second net.
- **The rule as built** (#1184, last head 30b3ab75):
  - `services/criteria_compiler/ir_extract/recognition.py` reads each clause of an inclusion line whose logic asks
    the presence of a concept. A clause must be made only of the concept's names, the codes of its value set, an
    abbreviation the line defines for it, other concepts the criterion's logic codes, and words listed in
    `recognised_assertions.yaml`. Anything else holds the line, flagged `negated_inclusion_presence` and
    `presence_not_recognised`.
  - The data file lists, per language (en, ja, zh), frames, history and qualifier classes, each with the domains it
    applies to. It also lists positional words (`{X}`, `{O}`), test words that count only beside a confirming word,
    measures by shape after the concept, and alternatives.
  - It holds a line, whatever its words, on: hold patterns (a form value, a zero, a schedule day, bounds on counts
    and doses, "criteria for X", below detection, a test or vaccination for X, the concept as the object of another,
    a numbered heading); a clause saying the concept ended unless the atom's window ends before the index day; a
    second-net list of non-fact words; and exceptions, which are cut out of the clause.
  - Every clause counts. A line is read in one language. The cue rules still run.
- **Measured.**
  - **Development set** `tests/fixtures/negated_inclusion/card_10a1d_development.tsv`: 696 synthetic lines, 412
    must-hold, 284 must-run, en, ja and zh. The first 471 were written and scored before any code; each later round
    added the frames it tested and their nearest lines, so the set is not an unseen measure.
    - On #1180's head (71e85bbc): 297 of 412 must-hold lines run; 5 of 284 must-run lines are held. Of the first
      471 (Checkpoint A): 182 of 259 ran, 5 of 212 held.
    - With the rule at 30b3ab75: 0 of 412 run; 20 of 284 held.
  - **Mechanical sweep** over the same 412 must-hold lines, each other noun phrase in a line (one at a time, pairs
    when there are 8 or fewer, all together) named as a concept:
    - #1180's head: 278 of the 412 lines run under some naming (1444 variants);
    - with the rule at 30b3ab75: 0 of 1416 variants run; 0 of 842 variants run with the phrases also coded as atoms
      of an "and" logic.
  - **Existing fixture sets** (`tests/fixtures/negated_inclusion/*.json`), unnecessary holds at 71e85bbc → 76cbcf79;
    misses were 0 on each at both: `card_10a1b` 17 → 36 of 40; `card_10a1c_after` 25 → 54 of 63;
    `card_10a1c_before` 82 → 108 of 120; `card_10a1c_third` 12 → 38 of 63; `independent_set_1` 0 → 5 of 26;
    `lines` 12 → 34 of 68; `review_10a1b` 0 → 8 of 8; `unseen_at_design` 19 → 23 of 23.
  - **Testers, scored by the lane J lead on lines this card never saw before each round:**
    - tester 1, blind, at 46170f53: 0 of 186 and 0 of 57 must-hold lines ran; 69 of 109 and 11 of 16 plain lines
      held (49 and 1 at #1180);
    - tester 2, blind, at 46170f53: 1 of 194 and 1 of 73 ran (71 and 40 at #1180; 121 and 62 on master); 78 of 122
      and 30 of 31 plain lines held (44 and 21 at #1180);
    - at ed1ef1a7, the four sets above: 0, 0, 0, 0 ran;
    - tester 3, blind, 348 lines at ed1ef1a7: 1 of 198 ran; 127 of 150 realistic plain assertions held;
    - tester 3 informed (the data file open), at ed1ef1a7: 48 of 70 and 10 of 12 clause-split lines ran;
    - at 76cbcf79: 0, 0, 0, 0, 0 of 198, 0 of 12 ran and 4 of 70 of the attack set; 113 of tester 3's 150 realistic
      plain lines held;
    - tester 4 informed, at 76cbcf79: 362 of 410 must-hold lines ran (en 195 of 213, ja 86 of 103, zh 81 of 94), and
      9 more through direct calls; 88 of 100 realistic plain assertions held.
  - **The price in reading:** inclusion lines held, of 539, on the repository's stored protocols (the 15 replies
    under `services/llm_stub/cassettes/ir_extract/` and the stored P2b replies of `integrator/p2b-artefacts`). Each
    reply was compiled through `postprocess` with an empty terminology; a line seen in several calls of one set
    counts once.
    - 18 at 71e85bbc; 116 at 46170f53; 103 at ed1ef1a7; 105 at 76cbcf79; 109 at 30b3ab75.
    - The 91 newly held at 30b3ab75, labelled by hand:
      - (i) 28 rightly held: a plan, eligibility, a group heading, an unresolved alternative;
      - (ii) 16 held for a missing name: the line never names the concept as the extractor named it;
      - (iii) 43 plain assertions not recognised: one unlisted word or another spelling;
      - (iv) 4 plain assertions held because a second named concept is not coded by the logic.
- **Root causes,** as tester 4 grouped the 362 lines that ran at 76cbcf79:
  - RC1, other concepts were opaque, 101 lines (30b3ab75 addresses part of it);
  - RC2, alternatives listed as frames, and "/" and "・" as link marks, 80 lines ("Diabetes or any other disease",
    糖尿病等の疾患);
  - RC3, a synonym inside a different name, 29 lines ("Type 1 diabetes" with "diabetes" a synonym of type 2;
    小細胞肺癌 with 肺癌 a synonym of 非小細胞肺癌);
  - RC4, measures by shape accept free text and contradicting values, 104 lines ("Obesity with BMI below 25 kg/m2",
    "Distant metastasis (M0)");
  - RC5, marks, 38 lines ("Diabetes: ×", "Diabetes ( )", "Hepatitis B, confirmed (HBsAg: -)");
  - RC6, "according to" or "based on" switches the definition hold off, 5 lines;
  - RC7, endings and the active-only atom, 14 lines ("Hepatitis B in the past", "Insulin, up to 4 weeks before
    screening").
- **Conclusion.** Each round closed the shapes it was shown, and the next informed tester found as many again. The
  number of lines held never came down: 18 to 103-116 of 539 stored lines; 113 of 150 and 88 of 100 realistic
  plain lines. Reversing the default with a listed vocabulary flags most plain lines and still lets an informed
  writer through, so it does not ship.
- **Expectations not changed:** the tests that pin lines as running were left as on master. #1184 lists them:
  - the table property test (274 cases) and the PR-count test in
    `test_negated_inclusion_never_compiles_as_presence.py`;
  - two tests in `test_negated_inclusion_score.py`;
  - the AD-MAB and NEUR-COH goldens (`test_synth_ad.py`);
  - `test_mixed_and_polarity.py`, `test_mixed_keeps_its_note_question.py` and `test_stray_atom_fields.py`;
  - two tests in `test_encounter_atoms_need_a_code.py`.
- **Worth keeping without the rule:** see #1184. The lane J lead decides how they land.
- **Test:** `tests/unit/test_inclusion_runs_only_when_recognised.py` on #1184 (167 cases at 30b3ab75).
