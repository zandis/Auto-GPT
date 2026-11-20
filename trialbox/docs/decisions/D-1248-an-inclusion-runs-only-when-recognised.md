# D-1248 An inclusion runs as present only when its line is recognised as a plain statement of presence (10A-1d)

- **Task:** lane J, plan 10 card 10A-1d, riding with 10A-1c (#1180, D-1246). · **Date:** 2026-11-20 · **Status:**
  adopted. **The owner ruled yes on 2026-11-19 20:20 UTC** (the integrator's record of the owner's rulings on #639):
  "The inclusion default flips: what is not clearly present does not count as met. It rides with the new head of
  the negation card." The experiment of 2026-11-19 (#1184, closed, last head fde206df) was not adopted as built; its
  record is kept below. This record states the rule as adopted, what it costs, and its limits.
- **What a count here means:** each count is a count on the lines named with it, at the head it was taken on. None
  is a claim about the reader on other lines. Every set named here has been read by the author of this change, so
  none of them measures it on unseen lines; that measurement is the lane J lead's, on new lines.
- **The decision.** A structured or mixed inclusion that asks the presence of a concept runs only when its line is
  positively recognised as a plain statement that the patient has it. Every other line is held for a person
  (`negated_inclusion_presence` with `presence_not_recognised`), with the reason's class in the compiler's warning.
  The cue reading of 10A-1 to 10A-1c stays as a second net: a recognised line that carries a cue is held.
- **Why the experiment's rule was not adopted as built.** It read a clause only when every word was listed. An
  independent tester found it held 88 of 100 ordinary plain lines (`tester4_realistic_runs.tsv`), and an informed
  tester still got 362 of 410 must-hold lines through (`tester4_informed_held.tsv`): a closed word list holds the
  ordinary long tail of a criterion, while its "open" places (measures by shape, any named concept, any listed
  noun) let a line through whatever it said.
- **The rule as adopted** (`services/criteria_compiler/ir_extract/recognition.py`, data in
  `recognised_assertions.yaml`):
  - **What governs the concept's name is a closed list.** In English the phrase whose preposition governs the name
    must be listed ("diagnosis of", "history of", "treated with"; "vaccination for", "risk of", "candidate for" are
    not), and the word right after the name, in brackets too, is read only when listed ("X screening", "X (FH)").
    In Japanese and Chinese nothing unlisted is read after the name until a listed frame or a mark closes it
    ("Xに対するワクチン接種", "X之疫苗接種" never close; "Xを有する小児" closes at を有する), and what owns the name
    through の, が, は, 之 or 的 is read only when listed ("配偶者のX"). In Chinese a run before the name is read only
    when 之 / 的 or a listed frame joins it to the name: a verb stands before its object as a modifier does.
  - **An unlisted word is read only as a content word, where a content word cannot change whether the concept is
    present.** Never a closed-class word (an article, a pronoun, an auxiliary, a modal, a conjunction, a
    preposition: "if", "when", "will", "may", "his" are read only where listed); never a verb form ("-ed", "-ing");
    in Japanese hiragana is read as grammar unless it holds an ending that denies, doubts, wishes, conditions or
    allows (ない, ず, たい, らしい, れば, できる …); never a word of a class that says the concept is not a present
    fact of this patient (doubt, a plan or a need, a risk, another person, an ending, a refusal, an alternative, a
    self-report, a form's value: `unlisted_never`); at most 12 in an English clause, 8 runs in a Japanese or Chinese
    one; none in a clause that names no coded concept.
  - **Held by class, whatever the words:**
    - the concept not named by any name the extractor gave; named only by a name that is part of its coded name
      ("diabetes" for "type 2 diabetes mellitus": the line may be about another kind); a synonym with an unlisted
      modifier before it; a type number in front of the name;
    - the concept as one arm of an alternative the logic does not carry ("X or any other disease", "X, A or B",
      "any of: …", X等, "X / Y"); an arm of the concept's own kind ("kidney transplantation, liver transplantation
      or lung transplantation");
    - a form's mark or an empty field ("X: -", "X ( )", "X ×"; a tick counts only right after its name); a label
      and a bare name ("Section 5.2: X"); a chapter heading; a code that is not one of the concept's own;
    - a bare measured value with no bound ("BMI 22 kg/m2"); TNM zero or x; a bound below one on a grade, a count or
      a rate; below detection; a named risk instrument or a prediction;
    - a definition ("X is defined as", "criteria for X" unless the line says the patient meets them or asserts X
      first); a need or a plan before the name; "before X"; a diagnosis revised to another; a cured response;
    - it ended or lies in the past, unless the atom's own window asks the past (a procedure done "2 years ago" is
      done); the excepted object of an exception.
  - **Another concept counts as one only when the criterion's own logic codes it**, and then only when its own name
    is not a word of a class above. A concept the logic joins to this one by "or" is read as this concept; a
    condition the logic carries ("…, or ≥ 6.0 mg/dL if receiving X" with X one arm of an "or") is read as coded.
  - **An approved criterion reused by an incremental compile** is held when its line names the concept and is not
    recognised. A line that does not name the concept by any name its value set keeps (the coded name and its
    codes' names, often in another language than the line) is not held by this rule: the reading cannot find the
    concept, and a person approved the line. The cue reading still holds it when it carries a cue. Of the 38
    filtered inclusions of the eight rulesets under `rulesets/`, 9 are such lines.
- **What it costs: ordinary plain lines held.** `tests/fixtures/negated_inclusion/card_10a1d_plain.tsv`: 360 ordinary
  plain inclusion lines, 120 each in English, Japanese and Chinese, written for this card by another hand than the
  rule's and never tuned to a rule (synthetic; real-looking registry wording). Held, of 120 per language:

  | | en | ja | zh | all 360 |
  | --- | --- | --- | --- | --- |
  | 65f0753c, the cue reading alone | 1 | 5 | 6 | 12 |
  | the experiment's closed list, as merged (96e1fb96) | 75 | 78 | 84 | 237 |
  | this head: by the cue reading | 1 | 4 | 5 | 10 |
  | this head: not recognised | 15 | 18 | 27 | 60 |
  | this head: held in all | 16 | 22 | 32 | 70 |

  Reasons of the 60: 49 a word or a shape not read, 10 a class hold (a bound on a count, TNM zero, a bare value, an
  alternative), 1 the concept not named. The scorer's logic codes only the line's one concept, so a line whose
  measure or second condition a real extraction would code is read here with that condition as plain words.
  - Other plain sets, held by the cue reading + not recognised, of the plain lines in the set:
    `tester4_realistic_runs` 4 + 19 of 100 (88 with the experiment at 76cbcf79); `tester3_blind` 7 + 31 of 150
    (113 at 76cbcf79); `tester1_round1` 49 + 13 of 109 and `tester1_round2` 2 + 6 of 16 (49 and 1 at #1180's
    71e85bbc); `tester2_round1` 44 + 10 of 122 and `tester2_round2` 22 + 1 of 31 (44 and 21 at 71e85bbc);
    `card_10a1d_development` 4 + 7 of 284.
- **What a held line costs a study: criteria held per stored protocol.** The 15 stored synthetic extraction replies
  under `services/llm_stub/cassettes/ir_extract/`, compiled through `postprocess` with an empty terminology: 71
  inclusion criteria in all (2 to 9 per protocol). Held at 65f0753c: 2 (both in RA-BIO, by the cue reading). Held at
  this head: 3: the same 2, and 1 in GOUT-COH, a Chinese line whose concept the reply names only in English
  ("六個月內曾使用降尿酸藥物" coded "urate-lowering therapy"): reason `not_named`. Twelve of the 15 protocols have no
  held inclusion before or after. A held criterion answers unknown and never excludes; it costs a reviewer's look
  at the compile's draft.
- **Must-hold lines that run** (all sets seen): 0 of 412 on the development set; 0 of 186 and 0 of 57 (tester 1);
  0 of 194 and 0 of 73 (tester 2); 0 of 198, 0 of 70 and 0 of 12 (tester 3 blind, informed, clauses); **12 of 410 on
  `tester4_informed_held`** (en 7, ja 2, zh 3; 204 with the experiment as merged, 362 at 76cbcf79).
  `tester4_arguable` (20 lines the tester would not label; not counted anywhere): 11 run.
- **Limits.** What this rule does not do, said plainly:
  - **A value that contradicts the name.** All 12 lines above are of this kind: "Osteoporosis with T-score above
    -1.0", "Obesity with BMI below 25 kg/m2", "Heart failure with reduced ejection fraction, LVEF ≥ 55%",
    "Hepatitis B with HBsAg < 0.05 IU/mL", 骨質疏鬆症（T值≥-1.0）. The line states the diagnosis and bounds a
    measure; that the bound denies the diagnosis is clinical knowledge the reader does not have. A named
    instrument that scores a risk is held from a list of names; one the list lacks would run the same way.
  - **The places an unlisted word is read are guarded by lists of classes, not by a proof.** An unlisted content
    word of a class nobody listed (a person word such as a job title, an adjective that makes the concept unreal)
    in the rest of a line can run. The lists are in `unlisted_never`; a tester who reads them can write such a
    line. This is the price of reading ordinary lines at all: the closed list held 237 of the 360.
  - **Clinical narrowing is not checked.** A line that runs says the concept is present; whether the logic checks
    every other condition of the line (a stage, a threshold the extraction did not code) is the reviewer's.
  - **A line whose concept is not named in the line's own language is held** on a new compile and not read at all
    on a reused approved criterion (above). An extraction that names concepts in the line's language avoids both.
  - **Languages.** English, Japanese, Chinese (Traditional and Simplified). A line of kanji alone is read as
    Chinese unless it has a character written only in Japanese, and with both languages' class lists.
  - The counts above are on lines the author has seen.
- **Expectations changed,** each because its line does not name the coded concept or is not a plain statement of it,
  and the test is about another rule (the line now names the concept; what the test asserts is unchanged):
  - `test_mixed_and_polarity.py` (the two mixed inclusions' line was "x");
  - `test_mixed_keeps_its_note_question.py::test_a_mixed_criterion_that_runs_is_unchanged` (the line was "line");
  - `test_stray_atom_fields.py::test_a_held_mixed_line_keeps_its_note_question` ("CAP" is written "pneumonia");
  - `test_encounter_atoms_need_a_code.py`: "MDD" is given as the extractor's synonym; "Current hospitalization for
    COPD exacerbation" is now held as not recognised before its missing code is found (its own test), and the
    missing-code rule is tested on "Hospitalization within the past 12 months";
  - `test_negated_inclusion_never_compiles_as_presence.py`: see D-1246 (the per-row check and the counts).
  The AD-MAB and NEUR-COH goldens (`test_synth_ad.py`) pass unchanged.
- **Follow-ups for the lane J lead:** have the extraction name each concept in the line's language (it removes the
  `not_named` holds); keep the names and synonyms a concept was extracted with in its value set, so a reused
  approved line can be read.
- **Test:** `tests/unit/test_inclusion_runs_only_when_recognised.py` (the rule's own tests, the development set, the
  plain set's counts, the mechanical sweep: every must-hold line of the development set with each other noun
  phrase named as a concept, and coded as an atom of an "and", stays held);
  `tests/unit/test_negated_inclusion_never_compiles_as_presence.py`; `tests/unit/test_negated_inclusion_score.py`.
  `python -m tools.negated_inclusion_score <file> --rows` counts the two readings apart, with the reasons.

## The experiment of 2026-11-19 (#1184, not adopted as built), as it was recorded

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
