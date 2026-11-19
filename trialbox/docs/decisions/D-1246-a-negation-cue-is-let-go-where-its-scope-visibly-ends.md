# D-1246 A negation cue is let go where its scope visibly ends; four kinds of miss closed first (10A-1c)

- **Task:** lane J, plan 10 card 10A-1c, the follow-up of 10A-1b (#1117, D-796): fewer inclusions held for a person
  when their line is safe to run, with no negated inclusion run as presence. · **Date:** 2026-11-19 · **Status:**
  reserved
- **Decision:**
  - **Measure first.** 241 synthetic lines were written before any rule changed (en 81, ja 80, zh-TW 80; 121 must be
    held, 120 must run; each names the shape it tests) and were scored on master
    (`tests/fixtures/negated_inclusion/card_10a1c_before.json`). Master missed 4 of them, so the card first closed
    the misses. A second set of fresh lines, written after the code was final, is scored apart
    (`card_10a1c_after.json`).
  - **Misses closed (more holds, by design):**
    - A bare 不 is a Chinese cue ("不飲酒", "且不吸菸"). It is not a cue only in 不良, 不全, 不穩定, 不明, 不足,
      不整, 不規則, 不規律 or 不佳 right after a noun and ending the word ("控制不良之", "心功能不全患者"), and in
      不孕症. As a prefix or before a verb it is a cue ("不足以", "不良於", "不明原因之", "不適合"). Whatever cannot
      be bounded this way stays a cue.
    - なし written in katakana (ナシ, half-width ﾅｼ) is a Japanese cue.
    - 以外 is a Chinese backward cue, as it already was in Japanese ("黑色素瘤以外之…" with 黑色素瘤 coded).
    - R3 lets only "未(經)治療的/之 X" go. Before, it let a negator go over any modifier of up to six characters,
      and "未曾有心臟病之家族史" (no family history of heart disease) ran with 家族史 coded.
    - The concept is looked for in the line as written. Before, it was looked for after the descriptors were
      blanked. A descriptor that reaches into the coded name from before it now holds the line: "小細胞肺癌" in
      "非小細胞肺癌", "Hodgkin lymphoma" in "non-Hodgkin lymphoma". Blanking alone hid the 非, and the line ran.
      In English, a coded name right after a negating prefix in the same word is not that concept: "non" (with a
      hyphen, a space or nothing), "un", "a", "ex-" ("asymptomatic" with "symptomatic gallstones" coded).
  - **Releases added.** Each needs the cue's own object written and the coded concept outside it. None depends on
    a word list of objects, or on how far away the cue is.
    - R8, a modifier: in English the concept, then at once "without" or "not on / with / in / for / from / by",
      then an object ("type 2 diabetes without ketoacidosis"). In Japanese, a cue of absence whose own subject or
      object is written right before it, then at once (の) the concept as its head ("肝硬変のない慢性B型肝炎").
      Chinese "無Y之X" is not released, as it may read "no X of Y".
    - R9, an exception's own object: except, other than, を除く, 除き, 以外, 除…外. The concept outside the object
      runs.
    - R1 gains the noun form of a negated prohibition ("no contraindication to", 禁忌がない, 無禁忌症), beside
      "not contraindicated" and 禁忌なし.
  - **Not released, and why.** A negated second thing that is not a candidate, and a cue's clause before a positive
    item ("no prior X, and confirmed Y", なく、, 且): the object may be the coded concept by another name (#1117).
    A coded name the line does not write (R0).
  - **Rules and near misses** are the RULES table in `tests/unit/test_negated_inclusion_never_compiles_as_presence.py`
    (R8, R9; new lines under R1 and R3). A mutation that drops any condition of R8, R9, the R3 narrowing or the
    descriptor check makes 2 or 3 near-miss lines run.
  - **Changed assertions**, on the lane J lead's ruling: two existing assertions held "Type 2 diabetes mellitus
    without ketoacidosis", which is labelled "runs". The `unseen_at_design.json` row lost its `over_held`, and the
    reused-line test now proves the hold on lines R8 does not release.
- **Why:** after 10A-1b the compiler held lines whose cue is plainly about something else, because a cue was read
  wider than its grammatical scope. The price is a person's look at each such line.
- **Test:** `tests/unit/test_negated_inclusion_never_compiles_as_presence.py` over `tests/fixtures/negated_inclusion/`.
