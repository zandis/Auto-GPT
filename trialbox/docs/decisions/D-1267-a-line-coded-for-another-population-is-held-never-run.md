# D-1267 A line whose coded logic selects another population than its text is held, never run

- **Task:** lane J, card J-R18 (review R22-18; the report on PR #1327). On master 57aeb293 the criteria compiler
  left four kinds of extraction coded with no flag, each run on the wrong population. The worker built them by hand
  for `postprocess.postprocess`, with no model, as `tests/unit/test_exclusion_never_on_a_demographic_alone.py` does.
  **Date:** 2026-11-23. **Status:** reserved.
- **The faults:**
  1. The inclusion "Women of childbearing potential must have a negative pregnancy test" (and
     「妊娠可能な女性は妊娠検査陰性であること」) was coded `sex = female`, so every man failed it. The dropped-qualifier
     rule (`qualifier_dropped`, P2b) covered exclusions only.
  2. 「HIV抗体陰性の患者」 was coded `any HIV`, which only HIV-positive patients meet. The English "HIV-negative
     patients" was already held (`negated_inclusion_presence`, card 10A-1); the Japanese cue list had no 陰性.
  3. Cessations were coded as presence and run as presence, which selects the opposite patients: "Must be off
     corticosteroids for 2 weeks", 「ステロイドを2週間以上休薬している患者」, 「停用類固醇至少兩週」 and "refrained from
     smoking for at least 6 months".
  4. The mixed exclusion "Uncontrolled hypertension despite three antihypertensive drugs" was coded `any hypertension`.
     A mixed exclusion whose code is true is settled at S1 (D-98; `codes_settle` held back only inclusions), so any
     hypertension code excluded the patient with no model asked.
- **Decision:** flags only. The compiler holds such a line or keeps its code from settling it. Nothing is rewritten.
  1. **Conditional inclusions** (`postprocess._CONDITIONAL_PART`). An inclusion that applies to a part of the
     patients, coded as an age or a sex alone, goes to a person, flagged `qualifier_dropped`. The warning names the
     part the code dropped ("drops 'childbearing potential'"). The parts are: of childbearing or reproductive
     potential, WOCBP, able to become pregnant, "if female", 妊娠可能, 妊娠の可能性, 生育能力, 可能懷孕 and 育齡. A mixed
     line goes to a person as well: a note question about a pregnancy test does not say who must answer it.
     "Women with breast cancer" coded as female keeps its sex (men fail it, as they should; the P2b test holds this).
  2. and 3. **Negated and ceased concepts** (`negation_scope`). The cue words were added to the existing lists, and the
     card 10A-1 rule (`negated_inclusion_presence`) holds such lines as it holds "HIV-negative":
     - English, before the concept: `off` (not `off-`), `refrain… from`, `abstain… from`, `discontinu…`;
     - Japanese, after the concept: 陰性, 休薬, 中止;
     - Chinese, both sides: 停用, 停藥, 停药, 中止.

     This is not a new negation engine. The 10A-1 tables and their counts are unchanged (`test_the_counts_the_pull_request_reports`).
  4. **Qualified mixed lines** (`postprocess._QUALIFIES`, `semantics.QUALIFIED`). A mixed line, inclusion or
     exclusion, is flagged `coded_part_qualified` when its text qualifies the concept it codes as presence. The
     qualifiers are uncontrolled, poorly, inadequately or insufficiently controlled, not (adequately or well)
     controlled, despite, refractory, コントロール不良 or 不十分, にもかかわらず, 難治性, 控制不佳, 控制不良, 儘管 and 難治.
     `codes_settle` returns false for a mixed line with that flag. Its code stays a pre-check (no code: the notes
     decide; a code: the notes decide), and it never settles the line.
- **The smaller change, chosen:** the compiler sets the flag and `codes_settle` reads it, one line. The other way,
  `codes_settle` reading the text itself, would put the compiler's word lists in the engine's path and change rulesets
  already approved without a recompile. Every caller of `codes_settle` (the cascade's S1, scenarios, the micro-batch,
  the candidate sheet, site readiness, the public-accuracy rerun) follows the flag with no change of its own.
- **Gate 1 (#1301):** this change stays inside the post-processing flags and `codes_settle`, so a later merge with
  gate 1 is mechanical. It was test-merged before the push, not merged into this branch; the pull request says how
  that went.
- **Not changed:**
  - A *structured* line with a qualifier. "Hypertension not controlled by two agents", coded `any hypertension`, is
    a 10A-1 table row that is expected to run. Holding it would change that test's count, which needs the
    integrator's ruling, so it is left as a question to the coordinator.
  - The goldens and the ruleset snapshots (both lake sources identical).
  - What any role may do or read.
- **Test:** `tests/unit/test_compiler_never_runs_the_wrong_population.py`, the invariant: every line above in the
  languages given, siblings, and the controls ("Female patients aged 18 or older", "History of hypertension", "HIV
  infection" run unflagged; "Receiving off-label methotrexate" is not a cessation). On master 42 of its 48 cases fail.
