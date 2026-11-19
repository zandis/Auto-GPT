# D-1248 An inclusion runs as present only when its line is recognised as a plain assertion (10A-1d)

- **Task:** lane J, plan 10 card 10A-1d, after 10A-1c (#1180, D-1246). A measurement and a draft: the owner has not
  yet said yes to shipping it, because it makes people read more lines. · **Date:** 2026-11-19 · **Status:** reserved
- **What a count here means:** each count below is a count on the lines named with it. None is a claim about the
  reader on other lines.
- **Decision:**
  - **The default turns round.** A structured or mixed inclusion whose logic asks the presence of a concept runs only
    when every clause of its line that names the concept is made of nothing but:
    - the concept's name or a listed synonym (as the extractor gave them);
    - words listed in `services/criteria_compiler/ir_extract/recognised_assertions.yaml`;
    - numbers, Roman numerals, TNM and ICD codes, and listed marks.

    Any other word in that clause holds the line for a person: an unknown word is a reason to hold, never a reason to
    run. A line that never names its concept is held. The hold is the one cards 10A-1 to 10A-1c use (class `human`,
    flag `negated_inclusion_presence`), with the flag `presence_not_recognised` and its own warning added. The cue
    rules (`negation_scope`) still run as a second net: a recognised line that is cued is held. Exclusions, measured
    atoms (a value, a count, the latest result), the console and the model prompts are unchanged.
  - **What is recognised is data a clinician can read.** Per language (English, Japanese, Chinese written either
    way), the file lists classes of words, each with the domains it applies to:
    - assertion frames: "diagnosis of", "patients with", "histologically confirmed", と診断された, を有する, 確診為,
      患有;
    - history ("history of", "prior", 既往, 病史, 曾), used only when the criterion's logic does not ask the concept
      active only;
    - qualifiers of the concept itself: treatment, stage, grade, severity, type, site and laterality, measure and
      threshold, time and duration, the confirming method;
    - criteria words, which count only beside a word that says the patient meets them ("meeting the 2010 ACR/EULAR
      criteria", not "criteria for hypertension");
    - link words, which let another concept the extractor named share the clause ("surgery for colorectal cancer",
      not "metformin allergy");
    - anaphora: a clause that names no concept but points back at one ("Diagnosis pending confirmation") must be
      recognised as well.

    A word that says something else in one domain is listed only for the domain where it qualifies the concept:
    "refractory epilepsy" runs, "refractory rituximab" is held.
  - **Clauses.** A clause ends at ";", a sentence's end, "but", "however", が、, 但 and the like. A comma does not end
    one. A clause that ends in a colon is a heading. What an exception names ("except", "other than", を除く, 以外,
    除…外) is cut out of the clause before it is read; a line whose coded concept is the excepted one is held.
  - **Known words that together say otherwise** are listed as patterns (`holds`) and hold the line:
    - a form's field and its value ("Asthma: 0", "高血圧：2");
    - a zero ("0 cycles");
    - a schedule day ("on day 1", "cycle 1 day 1", 第1天, 1日目);
    - an upper bound on a count of the treatment ("up to 2 prior lines of", 2レジメン以下, 至多兩線);
    - a range of counts from zero.

    Time anchors that may lie after the study starts ("at randomisation", "of the first dose") are not listed; "before
    randomisation" is.
  - **How a frame is added.** Add the words to the right class and language of the YAML file. Then add to
    `tests/fixtures/negated_inclusion/card_10a1d_development.tsv` the line it lets run and its nearest lines that must
    still hold: the same words with a plan, a person, a stop, a symbol, a zero. Run `python -m
    tools.negated_inclusion_score tests/fixtures/negated_inclusion/card_10a1d_development.tsv --rows` and
    `tests/unit/test_inclusion_runs_only_when_recognised.py`. A word that lets one must-hold line run does not go in.
    Never add a word that says the concept is absent, doubtful, planned, stopped, someone else's, or only a heading, a
    definition or an instruction. A word in the YAML must be a string: YAML reads a bare `on` as true, so it is quoted,
    and a non-string word fails the compile.
- **Measured:**
  - **Development set** (`card_10a1d_development.tsv`, 529 synthetic lines: 297 must-hold, 232 must-run; en 221, ja
    154, zh 154). The first 471 were labelled and scored on #1180's head (71e85bbc) before any of this code existed;
    the 58 of the second round came with the frames they test.
    - On 71e85bbc: 201 of the 297 must-hold lines ran; 5 of the 232 must-run lines were held.
    - With this rule: 0 of the 297 ran; the same 5 were held. These 5 are held by the cue rules, not by recognition:
      "Type 2 diabetes. Not pregnant." and its ja and zh twins, and the ja and zh ACR/EULAR criteria lines.
  - **The existing fixture sets** (same scorer). Misses are 0 on each, before and after. Unnecessary holds, before →
    after: `card_10a1b` 17 → 28 of 40; `card_10a1c_after` 25 → 52 of 63; `card_10a1c_before` 82 → 108 of 120;
    `card_10a1c_third` 12 → 36 of 63; `independent_set_1` 0 → 5 of 26; `lines` 12 → 32 of 68; `review_10a1b` 0 → 7
    of 8; `unseen_at_design` 19 → 23 of 23. Most of the new holds are a second, negated thing in the concept's own
    clause ("Type 2 diabetes without ketoacidosis", "インスリン未使用の2型糖尿病患者"). No frame was added for them:
    "Hepatitis C without detectable HCV RNA" has the same structure and means cleared.
  - **The price in reading,** on the repository's stored protocols, each reply compiled through `postprocess` with an
    empty terminology (a line seen in several calls of one set counted once). Inclusion lines held, 71e85bbc → this
    rule:
    - the 15 stored replies under `services/llm_stub/cassettes/ir_extract/` (the seed rulesets and the fixtures):
      67 inclusion lines, 58 coded; 2 → 8;
    - the stored P2b replies (`integrator/p2b-artefacts`): sigir 470 inclusion lines, 331 coded, 16 → 108; jmed 1
      line, 0 → 0; tcga 1 line, 0 → 0;
    - in all, 539 inclusion lines: 18 → 116.

    Of the 98 newly held, some are not plain assertions ("Subject eligible for implantation of a CRT-D device…",
    "Must be starting either STELARA…", "Phase 1 & 2: COPD & ONE of the following criteria:", "Indication for
    long-term anticoagulant therapy…"). Others are plain assertions with one word the lists lack or a name the
    extractor gave no synonym for ("Chronic renal failure requiring hemodialysis.", "合併第二型糖尿病診斷。",
    "アルツハイマー病による軽度認知障害（MCI）または軽度のアルツハイマー型認知症と診断されている者…").
- **Why:** two testers, writing lines without the code, found the cue list's gaps on each round: on master, of lines
  whose concept is not a present fact of the patient, 60 of 186, 53 of 57, 121 of 194 and 62 of 73 ran as present;
  after #1180, 0, 0, 72 and 40. Most of the second tester's are not negations at all. A list of cues always lacks
  the shape nobody listed; a list of what an assertion looks like fails towards a person's look.
- **Test:** `tests/unit/test_inclusion_runs_only_when_recognised.py` (the development set; each rule with the line it
  holds and its near line that runs; an unknown word inside the concept's clause holds each English must-run line,
  one in another clause does not; the reused approved line).
