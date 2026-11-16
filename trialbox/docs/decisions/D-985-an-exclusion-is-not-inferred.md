# D-985 An exclusion stands on a stated condition, never on an inference

- **Task:** F6 of the integrator's root-cause review of the P1b run (#639, 2026-11-16). A note exclusion was decided by inferring a diagnosis.
  - On jmed, both models agreed four times that a patient had a history of hypertension or diabetes. The quote named only an antihypertensive, or metformin with an HbA1c, and the judge's own reasoning said there was no stated history.
  - On sigir NCT01784523 the judge counted findings into SLE.
  - `both_agree` (D-95) does not protect against an inference both models share.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision** (`matching.inferred`, applied in the cascade's `_map`). An exclusion's "present" stands only on a verified quote (CAS-16) that states the criterion's condition. The quote must name it by one of:
  - three of the criterion's Han or kana characters in a row, or a two-character run (妊娠, 喘息), after its generic words (既往, 患者, がある, the question's があります) are removed;
  - the start of one of its English content words, as a word start ("diabe" finds "diabetic", not "prehypertension"), with trial administration words (comply, protocol, investigator, consent) left out;
  - one of its abbreviations, or an abbreviation or synonym of a concept it names (HTN, T2DM, CKD, MI/STEMI, AFib, HFrEF, lupus for SLE, 妊娠/懷孕, lactating, HSCT, adenocarcinoma).

  - across languages, the cascade's own bilingual terms table (D-103), both ways: an English criterion's words in zh-TW or ja ("gout flare" is stated by 急性痛風發作), and a zh-TW or ja criterion's terms in English. One Han character alone (痛) names nothing.

  The mention must state the condition: not negated, a relative's, a risk, a screen, or a drug or diet for it ("denies diabetes", "family history of hypertension", 高血圧リスク, 糖尿病薬, "diabetic diet").

  A generic diagnosis word (症, 診断, "known") is not the condition: 健康診断で血圧が上昇, or 心房細動と診断され, states no hypertension.

  A quote that does not state the condition is the models' inference: a drug, a dose, a value, or findings counted into a diagnosis. The answer becomes unknown ("inferred: the quote does not state the condition; review") and never a hard fail. The rule reads the quote, never the model's reason, which claimed a diagnosis on every one of these. It reads the criterion's text, never the note question.

  Out of scope: a criterion that is itself a value, a drug or a procedure, and names none of the concepts (ALT > 3x ULN, eGFR < 30, systemic corticosteroids, ワルファリン服用中). There the value or the drug is what the line asks about. An inclusion is never affected.
- **On the run's stored replies** (a cassette, with no model call; unique criterion and quote pairs):
  - jmed: 15 are inferences. Eleven are quotes of a prescribed drug (降圧薬, カルシウム拮抗薬, ARB, ロサルタンとメトホルミン, 降圧薬・スタチン・メトホルミン). Four rest on a generic word or a risk (心房細動と診断され, 健康診断で血圧が上昇, 高血圧リスク). The integrator's four rows are among them.
  - sigir: 5. NCT01784523's findings for SLE, a calf pain read as claudication, a groin mass, palpitations for "non-acute onset", and consent boilerplate ("will comply with the trial protocol") for "any illness ... ability to comply".
  - No quote that states the condition is caught ("既往に高血圧と糖尿病があり", "併存症として高血圧症がありますが、特記すべき家族歴はありません").
  - Whether the models still reach such answers, and how often a stated diagnosis is phrased in a way this rule misses, is what only the GPU can show, on the D-517 gold. A miss goes to review, never out.
- **Review:** an adversarial review of the first cut found the question's filler and generic diagnosis words counted as the condition (two jmed metformin replies and three 診断 replies kept as hard fails), and abbreviations, synonyms and value criteria sent to review. All are fixed and pinned in the test. CI's rerun test then found a cross-language case: the synthetic site's English "Acute gout flare" criterion read against 診斷為急性痛風發作 was called an inference, which moved the patient from excluded to review. The terms table now carries the condition across languages.
- **Test:** `tests/unit/test_no_inferred_diagnosis.py`. The `_map` property test (`test_safety_properties`) gains a quote dimension: an exclusion present on an inference is never a hard fail.
- **Not in this card:** the v1 evaluator's path (`evaluate.py`). Screening runs the cascade, so v1 follows if the integrator wants it.
