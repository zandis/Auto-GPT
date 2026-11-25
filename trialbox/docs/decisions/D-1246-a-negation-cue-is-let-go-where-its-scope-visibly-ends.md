# D-1246 A negation cue is let go where its scope visibly ends; misses found on master closed first (10A-1c)

- **Task:** lane J, plan 10 card 10A-1c, the follow-up of 10A-1b (#1117, D-796). The aim is fewer inclusions held
  for a person when their line is safe to run, without running a negated inclusion as presence. · **Date:**
  2026-11-19 · **Status:** reserved
- **What a count here means:** each count below is about the lines it was measured on. None of them is a claim about
  the reader. The reader holds a line when it finds a cue, and runs it when it finds none, so a cue list keeps missing
  shapes nobody listed. Turning that default around (run only a positively recognised assertion; hold everything
  else) is a separate card, which the lane J lead takes to the owner because it raises how many lines a person reads.
- **Decision:**
  - **Measure first.** 241 synthetic lines were written and scored on master before any rule changed: en 81, ja 80,
    zh-TW 80; 121 must be held, 120 must run (`card_10a1c_before.json`). Two more sets were written after code that
    was then final, and are scored apart (`card_10a1c_after.json`, `card_10a1c_third.json`). `python -m
    tools.negated_inclusion_score <file>` scores anyone's file of labelled lines the same way.
  - **An independent tester** wrote and labelled lines before reading any code, then scored them with that tool:
    - round 1, 186 must-hold lines: master missed 60, the head at 227466c3 missed 24;
    - round 2, 57 targeted must-hold lines: master missed 53, 227466c3 missed 49.

    227466c3 also added two misses that master held. The lines that ran at 227466c3 are now regression lines
    (`independent_set_1.json`, seen).

    The lead measured 71e85bbc on the first tester's full files (368 lines): 0 of 186 and 0 of 57 missed (master
    60 and 53); 49 of 109 and 1 of 16 held unnecessarily.

    A second tester wrote 420 new lines, 267 must-hold, wider than negation. At 71e85bbc 72 of 194 and 40 of 73
    were missed (master 121 and 62); 44 of 122 and 21 of 31 were held unnecessarily (master 41 and 19). What still
    runs is mostly not negation at all:
    - drugs stopped, failed, refused or allergic to;
    - plans, bookings and "candidate for";
    - a donor's, partner's, fetus's or child's condition;
    - remission, eradicated, recovered;
    - vaccination against X;
    - headings, definitions and instructions;
    - ⊖, ø and a ticked "No" box.

    These are left to the default-hold card. The same round found one regression at 71e85bbc, which is fixed: "any
    malignancy other than non-melanoma skin cancer" with non-melanoma skin cancer coded ran. The coded name holds a
    descriptor ("non-melanoma"), which was blanked, so the exception's reach did not find the name. A cue's reach is
    now read with the coded name as written. "apart from" and "aside from" join the exception cues.
  - **The hold is a fail-safe flag for the reviewer.** On lines written by people who had not seen it, it still lets
    many not-present lines run. It is not evidence that a line it lets run is a plain assertion.
  - **Misses closed, each by a rule** (more holds, by design):
    - **Chinese 不 and 以外.** A bare 不 is a cue, except in 不良, 不全, 不穩定, 不明, 不足, 不整, 不規則, 不規律 or
      不佳 right after a noun and ending the word, and in 不孕症. 以外 is a backward cue, as in Japanese.
    - **R3** lets only "未(經)治療的/之 X" go. A modifier with its own object may be a possessive
      ("未曾有心臟病之家族史").
    - **Descriptors and prefixes.** The coded name is looked for in the line as written. A descriptor or prefix that
      reaches into it from before, in the same word, is not that concept:
      - en: non (with a hyphen, a space or nothing), un, in, ex-, "a" before a consonant, "an" before a vowel; a word
        ending in -less;
      - ja and zh: 非, 無, 无, 未, 不.

      "anti-" is not a negating prefix.
    - **Status.** A word in the sentence that names the concept and says the concept is not a present fact of the
      patient holds the line. These are ConText's categories, each with examples:
      - uncertain: suspected, possible, r/o, 疑い, 可能性, 疑似, 待排;
      - hypothetical: "if / should X develops", at risk of, prophylaxis, 出現した場合, 若出現;
      - another person's: family history, mother, 家族歴, 母が, 家族史;
      - over: cured, quit, former, 治癒, やめた, 痊癒, 已戒.

      A status word inside the coded name does not count ("family history of X" coded), except a word of doubt
      (the second review, below). A criterion's own "if receiving X" counts unless the logic itself carries the
      condition (the second review, below).
    - **A bound on a count of the concept** holds the line, because zero meets it: "no more than 2 prior lines of",
      2レジメンを超えない, 不超過兩線. "never before" and "no longer" negate.
    - **Words found missing:** katakana ナシ; (−), "：－", ": neg", ": N/A", ": nil", "-ve", absent, w/o, zero,
      wild-type, -independent; 否認, 陰性, ネガティブ, マイナス, なかった, a verb's ず, 不使用; 除外, 毋須, 缺乏.
  - **Releases added.** Each needs the cue's own object written and the coded concept outside it:
    - **R8, a modifier.** en: "X without Y", "X not on Y". ja: a relative clause on absence, released only when its
      own object is marked by を and is not a clause head, or its own subject is another extracted concept. A head
      that is what was never received or given is held ("受けた経験のない化学療法"). Not zh.
    - **R9, an exception's own object.**
    - **R1, the negated-prohibition noun:** "no contraindication to", 禁忌がない, 無禁忌症.
  - **Not released, and why.** These stay held:
    - a negated second thing that is not a candidate;
    - a negated clause before a positive item;
    - a coded name the line does not write (R0).

    In each, the object may be the coded concept by another name (#1117).
  - **Rules and near misses** are the RULES table in `tests/unit/test_negated_inclusion_never_compiles_as_presence.py`.
    Dropping any condition of a rule makes at least one of its near-miss lines run.
  - **Changed assertions,** on the lane J lead's ruling:
    - "Type 2 diabetes mellitus without ketoacidosis" (labelled runs) is no longer pinned as held;
    - "No more than 2 prior lines of chemotherapy" is now a must-hold line, because zero meets it.
- **The second review (2026-11-19, the integrator's second tool, on 65f0753c against its merge base 73835e62).**
  Twelve findings. Each was reproduced through `postprocess` on both commits before anything changed:

  | | finding | at 73835e62 | at 65f0753c | closed by |
  | --- | --- | --- | --- | --- |
  | 1 | "Pulmonary embolism not on CT" (R8, en) | held | **ran** | R8 never lets go a cue whose object is a source of evidence or the patient |
  | 2 | 本人が投与を受けていない化学療法 (R8, ja) | held | **ran** | the を-object must not be the giving or receiving of the head |
  | 3 | 除了患者本人之外，家屬有糖尿病 (R9, zh) | held | **ran** | an exception whose object is the patient is not let go; 家屬, 家人, 配偶 and the like are another person |
  | 4 | "No known contraindications to chemotherapy", 化学療法の禁忌がない, 化學治療無禁忌症 (R1) | held | **ran** | eligibility for the concept holds, read by position round its name |
  | 5 | "Chemotherapy other than as a last resort" (R9, en) | held | **ran** | an exception's object must be a thing, not a condition |
  | 6 | "Chemotherapy. Planned for next week.", 敗血症。待確認。 | ran | ran | a status word in a sentence that names no extracted concept holds |
  | 7 | 若接受化療，須先簽署同意書; 化学療法を受ければ登録可能 | ran | ran | a condition on the concept holds, unless the logic carries it |
  | 8 | 曾患肺結核，目前已康復; 喫煙を中止した患者 | ran | ran | recovered, discontinued, in remission and their ja / zh words are status words |
  | 9 | "Possible sepsis." coded `possible sepsis` | ran | ran | a word of doubt holds even inside the coded name |
  | 10 | "0–3 prior cycles of chemotherapy", 化学療法歴は0～3コース | ran | ran | a count range that starts at zero is a bound zero meets |
  | 11 | status reading quadratic in repeated mentions | 0.08 s for x4000 | 0.47 s | each pattern is read once over the line: 0.15 s |
  | 12 | the per-row test checked only that the flag was absent | | | the per-row test asserts class, flags and logic |

  - The first five were regressions of this card's own releases. Each is closed as a class in en, ja and zh, not by
    its sentence: `tests/fixtures/negated_inclusion/second_review.json` has 75 must-hold lines and 28 near lines
    the cue reading must still let go, and
    `test_the_second_review_each_class_is_held_by_the_cue_reading_and_its_near_line_let_go` runs them against the
    cue reading alone.
  - **Finding 12 and the figures this record quotes.** The per-row test now asserts what each line compiles to: a
    line labelled `runs` keeps its class, carries no hold flag and has the one atom that asks the presence of its
    concept; a held line is a person's check with no executable logic, held by the reading its row names. Run with
    that strict check on 65f0753c, no line labelled `runs` had been passing because another rule had taken its
    logic away: lines held that should run were 8 of 68 (`lines`), 19 of 23 (`unseen_at_design`), 17 of 40
    (`card_10a1b`), 0 of 8 (`review_10a1b`), 82 of 120, 25 of 63 and 12 of 63 (`card_10a1c_before`, `_after`,
    `_third`), 0 of 26 (`independent_set_1`), and every must-hold line of each was held: the figures stand as
    quoted. They are counts through `postprocess`, as before.
  - **At the new head** the cue reading holds, of the same `runs` lines: 8, 19, 17, 1, 82, 26, 13 and 0. The three
    more are a need ("需要化學治療"), "not in remission" and an eligibility, classes the second review added. The
    default (D-1248) holds further `runs` lines of these tables as not recognised: 18, 3, 15, 7, 14, 14, 18 and 3.
    Most of these lines were written as the nearest thing to a negation ("no X, but Y"), not as ordinary criteria;
    what the flip costs on ordinary lines is counted in D-1248.
  - **One assertion changed:** "Serum urate ≥6.8 mg/dL, or ≥6.0 mg/dL if receiving urate-lowering therapy" with the
    therapy as the criterion's whole logic was pinned as running; it is finding 7's class in English and is now
    held. It runs when the logic carries the alternative (the therapy's atom is one arm of an "or"), as the stored
    GZQO protocol codes it.
  - **A defect found on the way:** a concept named in Japanese or Chinese gets a hashed value-set name
    (`VS_C_<hash>`), and what was left of its slug ("c", or "b" for B型肝炎) was read as a name of the concept,
    matching every word that starts with that letter. A hashed name now gives no words.
- **Limits** (kept from the first head, and still true of the cue reading alone): it holds a line when it finds a
  cue or a status word and lets go the rest, so it misses the shape nobody listed. On the second tester's 267
  must-hold lines 71e85bbc missed 112. That is why the default was turned round (D-1248, the owner's ruling of
  2026-11-19): the cue reading is now the second net behind the recogniser, not the gate. Its releases (R1 to R9)
  only matter for a line the recogniser also reads.
- **Why:** after 10A-1b the compiler held lines whose cue is plainly about something else. Measuring found negated
  lines that still ran.
- **Test:** `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over `tests/fixtures/negated_inclusion/`;
  `tests/unit/test_negated_inclusion_score.py`.
