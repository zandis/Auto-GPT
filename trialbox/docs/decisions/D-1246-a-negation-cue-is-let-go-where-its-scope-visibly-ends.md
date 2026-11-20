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
    (`independent_set_1.json`, seen). A fresh unseen set measures the final head.
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

      A criterion's own "if receiving X", which is coded in its logic, does not count. Nor does a status word inside
      the coded name ("family history of X" coded).
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
- **Why:** after 10A-1b the compiler held lines whose cue is plainly about something else. Measuring found negated
  lines that still ran.
- **Test:** `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over `tests/fixtures/negated_inclusion/`;
  `tests/unit/test_negated_inclusion_score.py`.
