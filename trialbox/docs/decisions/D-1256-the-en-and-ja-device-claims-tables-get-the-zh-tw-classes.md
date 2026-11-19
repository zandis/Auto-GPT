# D-1256 The English and Japanese device-claims tables get the classes D-1247 gave zh-TW

- **Task:** card 10C-5c of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C; lane J), the follow-up that
  D-1247 names: "the Japanese table has no treat, prevent, state, decide or remind class, and English has no claim
  table". PR #1234.
- **Date:** 2026-11-19
- **Status:** accepted; reserved for the pull request of card 10C-5c (lane J's block D-1220 to D-1319)
- **Builds on:** D-1228 (the Japanese device-claims rule), D-1247 (the zh-TW table and its classes), D-351 (a
  record's own field and quoted source text are not the product's wording), TB-IU-01 (`docs/plan/intended-use.md`)

## Context

The rule in `libs/tb_common/wording.py` refuses device-claim wording in the product's own texts. The product must
not say that it diagnoses, treats, prevents or predicts disease, screens for disease, warns early of a condition, or
decides for the clinician. It may say that it helps staff find patients who may match a trial's criteria, and that a
person decides.

D-1247 measured the zh-TW table and added whole classes the first version lacked:
- treat / cure / efficacy;
- prevent / reduce an outcome;
- deciding or recommending for the clinician;
- a reminder that warns of a condition;
- a clinician as the subject, allowed only when no product acts in the sentence;
- true denials and list denials;
- show-only verbs.

Before this card, the Japanese table had none of these classes. English had no claim table at all, only
`FORBIDDEN`'s words ("diagnosis", "risk score", "AI decides" ...). Neither table had been measured for these classes.

## Decision

0. **It is a tripwire on the product's own texts, not a proof**, as D-1228 and D-1247 say. It catches common claim
   forms. The figures below are on a development set that was used to fix the rule, so they say nothing of unseen
   text. **No independent figure exists yet.** The coordinator measures again on sentences this card never saw.
   Every new public text still needs a human reading.
1. **One mechanism, three tables.** The reading of who does an act is now one function, `_subject`, over a
   `Grammar` per language (`GRAMMAR_ZH`, `GRAMMAR_JA`, `GRAMMAR_EN`). It is D-1247's reading:
   - the nearest subject before the word in its clause decides;
   - a person's own act (医師の診断, the physician's diagnosis) is the person's;
   - the product's own act or noun (システムの判断, the system's judgement) is the product's;
   - the product helping a person is still the product's act;
   - a person yields to a product that acts in the same clause, replaces the person in the sentence (代わって,
     replaces), or is a cause (AIに決めさせ);
   - a product that only shows or reads (表示, lists, shows), or is denied, does nothing.

   zh-TW's grammar is built from D-1247's own patterns, so zh-TW reads as before. The classes are read by one
   function, `_claims_in`, for every table. A table holds only data: the words, the objects and the subjects.
   - **Japanese** (text named `ja`) gains these classes:
     - act (治療, 治す, 改善, 予防, 防止, 低減, 減ら, 下げ, 抑制, 回避 ...);
     - state (教え, 伝え, 評価, 確定, 判別 ... with 感染, 罹患, 再発, 重症度 ...);
     - decide (推奨, 提案, 決定, 決め, 選択, 提示 ... about a treatment, a dose, or whether a patient takes part);
     - warn (警告, 警報, アラート);
     - remind (通知, 知らせ, リマインド) about a disease or an early case;
     - "possible" (可能性, 疑い, おそれ), a claim only about a disease;
     - more finding words (フラグ, 見落と, 見過ご, 捉え, 洗い出) and outright nouns (早期警告, 早期診断, 疑い例, 誤診,
       臨床判断支援).

     A disease is judged by its class, as in zh-TW: a noun ending in 病 / 症 / 炎 / 癌 / 腫 / 不全 / 梗塞 / 卒中 /
     細動 / 硬化. 病院, 病名, 病歴, 病棟, 病床, 病理, 病室, 症例 and 適応症 are not diseases. A short list adds 喘息,
     高血圧, 再入院, 死亡 and others. 判断 is read by the shared subject reading.
   - **English** (text named `en`) gets a table:
     - outright phrases (early detection, undiagnosed, undetected, misdiagnosis, prognosis, risk prediction, risk
       score, clinical decision support, high-risk patients);
     - finding a disease (diagnose, detect, identify, recognise, spot, screen, flag, catch, discover, triage, miss,
       overlook);
     - rating a patient or a disease (predict, forecast, risk, likelihood, probability, score, stratify; possible,
       likely, suspected and "may have" only about a disease);
     - warn and alert, about a patient or a disease; remind and notify, about a disease;
     - act (treat, cure, efficacy, improve, prevent, avoid, reduce, lower, manage);
     - state (tell, determine, assess, work out, evaluate whether a patient is infected, ill, eligible);
     - decide (recommend, suggest, choose, decide, prescribe, advise, select, about a treatment or a patient's taking
       part);
     - judge (judge, judgement, diagnose).

     The words are patterns with their inflections, matched as whole words in any case. A disease is a list plus a
     class (-itis, -oma, -emia, -pathy, -osis, but not diagnosis or prognosis). A disease that names a study ("the
     asthma study", "a diabetes trial") is the study's name, not an object. The window is 64 characters, about the
     12 characters of a CJK sentence. A sentence ends at ". ", "! ", "? " or a line end ("6.0 mg/dL" does not end
     one).
2. **What differs is data, per language.**
   - **The subject.**
     - Japanese marks a subject by a particle: が, は, も, により, によって, で, を使うと, のおかげで, なら. A person
       includes a physician named by a 医 compound (専門医, 主治医; not 医療). The product's noun phrase before the
       word (TrialBoxの糖尿病改善) is the product's. A topic or a cleft after the word (診断は医師が行い,
       診断を下すのはAIです) names the subject when none stands before the word. A topic holds over every clause of
       its sentence, so an earlier clause's actor that only shows yields only to a person in the word's own clause.
     - English puts the subject before the verb. A passive's agent after the word (determined by the system,
       avoided with TrialBox, thanks to TrialBox) names it when none stands before. English needs no causative
       pattern: "let the AI decide" has the product straight before the verb.
   - **A record is not the product's act.**
     - Japanese: 治療歴, 治療中, 治療群, 初回治療, 治療を受けた.
     - English: received treatment, treatment arm, previously treated, treated with metformin.
     - A participle that names a record (patients diagnosed with RA) is not a finding unless the product is its
       agent.
   - **The object of a Japanese reminder, state or decision** stands before the verb anywhere in its clause
     (どの患者にインスリンを開始すべきかを…提示). The Japanese window is 16 characters for text named ja, where
     D-1228 had 12.
   - **The denial.**
     - Japanese keeps D-1228's rule: an odd number of negative endings in the rest of the clause.
     - For text named ja, a comma continues a list only between two claim words (診断、予測、スコアリングを行いません).
       In AIが患者のリスクを示し、治療は推奨しません, the comma after a verb ends the clause.
     - A hedge is no denial (予測できるかもしれません).
     - A negated miss (見落とすことはありません) claims completeness, as in zh-TW.
     - English negates before the verb: not, n't, never, no, none, neither, without, cannot.
     - Two English negators cancel (never fails to spot). "Not only", "not just" and "not unusual" deny nothing.
     - "nor" continues a denial, and denies alone only when no other negator stands before it.
     - "Nothing" after the verb denies it (predicts nothing).
     - An English clause ends at a stop, a comma that does not continue a list of claim words, "but", "although",
       "which", "before" and the like. It also ends at "and" or "or" before a verb that is not a claim word, or
       before a finite claim verb. "Does not diagnose, treat or prevent" is one denial; "does not predict a risk and
       gives no score" is two; "does not store names and detects heart disease" refuses "detects".
     - The disease and early words of a denied English clause are denied with it.
   - **FORBIDDEN's verdict words** (診断, 判定; "diagnosis", "diagnoses") pass in text named ja or en in these
     forms: a record field (診断名, 診断日, diagnosis code, date of diagnosis), a passive with no product as its
     agent (関節リウマチと診断された), or a person's own act (医師の診断, 診断は医師が行い, the physician makes the
     diagnosis). The product as the subject is still refused (AIによって…と診断された, the tool's diagnosis). This is
     D-1247's `_record_masked` with each language's field words. Text with no language keeps `FORBIDDEN` exactly as
     before.
   - **The allowed contexts, each pinned by a test:**
     - English: a named scale's score (`NAMED_SCALES`); a z- or T-score; a definition of a score; risk of bias; a
       study's own risks to the participant; an enrolment forecast; "% predicted"; a detection limit; the study's
       screening visit as a point in time (before screening); "possible candidates"; and the catalogue's own
       instrument names (`NAMED_INSTRUMENTS_EN`: International Prognostic Index, FRAX fracture risk ...).
     - Japanese (`CLAIM_ALLOWED_MORE_JA`, beside D-1228's unchanged `CLAIM_ALLOWED_JA`): 参加条件に合う可能性
       (the statement's own words), a z-score, `NAMED_INSTRUMENTS_JA`, and スクリーニング前 as a point in time.
3. **The caller names the language; the script is never used to guess it.**
   - The English table reads only text named `en`. D-1256's Japanese classes read only text named `ja`.
   - Text with no language, or named zh-TW or en, is read by D-1228's Japanese table exactly as before
     (`CLAIM_TABLE_JA_D1228`, and `deny_masked_ja(..., d1228=True)`). So a Chinese line (系統識別碼與病歷號) is
     never read by the Japanese disease class.
   - The pages name their own language (`<html lang>`), so the page walk reads English and Japanese pages with the
     new classes without any change to the walk.
4. **No real text changed verdict without being looked at.** Every catalogue string (console, orchestrator,
   opportunity hub; each named and unnamed), every criterion label, text and source in `rulesets/*/labels.yaml`, and
   the public site's Japanese text were read with `check(text, lang=...)`. That is **29,775 items**: en 9,803, ja
   10,066, zh-TW 9,906. D-1247 counted 29,644 on an older master. The reading ran on master f6c42230 and on this
   branch. **One verdict changed:**
   - `rulesets/RA-JAK/labels.yaml` RA-JAK-INC-02, ja text スクリーニングの6か月以上前に関節リウマチと診断されている
     now passes. It is a protocol's criterion, a passive with no product as its agent, the Japanese counterpart of
     zh-TW's 經診斷為.

   No existing product text is newly refused. The page walk (`tests/console/test_wording_walk.py`, every role,
   three languages) found one over-refusal while the rule was being built: the `/data/instruments` page names the
   catalogue's "FRAX fracture risk" (`catalogue/instruments.csv`). It is now an allowed instrument name, and a test
   holds that every name in that file and in `catalogue/items.csv` passes in its language. Over-refusals of real
   strings found and fixed in the rule along the way:
   - "the chosen study" (a participle, now not a decide word);
   - "Missed" and "a missed test" (a miss word was its own early word);
   - "record contact outcomes" ("outcomes" now only clinical, treatment, health or patient outcomes);
   - RA-JAK and GZQO's スクリーニング前 (now a point in time);
   - "1GPUのモデルの組で…日本語2例を見落としました" (a miss word was its own early word).
5. **Mutation check.** 81 parts of the new rule were each removed in turn: 71 for the classes and 10 for §7. Each
   removal fails at least one test in `tests/unit/test_wording_en_ja_classes.py`, `test_wording_zh_tw.py` or
   `test_wording.py`.
   - The first run showed 17 parts that no test needed. Tests were added for 16 of them (`PARTS_EN`, `PARTS_JA`),
     and English's causative pattern was removed as redundant.
   - The run also found a bug: the English "a denied replacement" pattern lacked a group, so any "no" in a sentence
     denied a replacement. It is fixed.
   - The new tests run against master: 187 of 390 fail. The 203 that pass are honest lines and denials that master
     already passed.
6. **zh-TW reads as before, except for §7's six fixes.** Its fixtures and D-1247's sets run untouched. Two tests of
   `test_wording_zh_tw.py` recorded the gap this card closes, and are updated to say so:
   - `test_one_rule_two_tables` now lists three tables;
   - `test_the_new_classes_are_zh_tw_only_and_the_japanese_table_lacks_them` now asserts the classes in all three
     tables, and that text with no language still has none of them.

   On the 29,775 items, every zh-TW verdict and hit is the same as on master. Read again after §7 and on the merge
   with master d28f6c03 (30,045 items: en 9,893, ja 10,156, zh-TW 9,996), the one verdict change is still
   RA-JAK-INC-02.
7. **From the second review of #1179.** The integrator's second review of #1179 (10C-5b, head 111f5cf6) left 4
   Medium and 2 Low findings on the claims-class code this card extends. Each was reproduced on this card's head
   before the fix, and each has a test that fails without its fix. Where the fault was in the shared code, the fix is
   made for all three tables.
   - **Medium, the record-field exception** (reproduced: yes). 本系統的診斷時間只需一秒 passed: the field word 時間
     after 診斷 cleared the product as its possessor. Now a field or a passive is a record only when the product does
     not act as its subject: as a possessor (本系統的), or as a subject that does more than show or read.
     本系統只顯示診斷碼 still passes. The same holds for "the tool's diagnosis date" in English.
   - **Medium, an existential negation over a later affirmative claim** (reproduced: yes). In
     本系統沒有副作用也能預防肺炎, 沒有 covered the whole clause. Now 也 / 還 / 仍 / 就 / 卻 / 照樣 with 能 / 會 / 可
     after a negator's object starts an affirmative predicate, and the negation stops there. 本系統沒有預防肺炎的功能
     is still a denial.
   - **Medium, a tense marker read as a record** (reproduced: yes). 本系統正在治療肺炎 passed because 正在 counted as
     a record. Now a tense marker (正在, 曾, 已, 先前 ...) straight after the product (with its auxiliaries) is the
     product's act. 接受 is still a record, and so are 病人正在接受肺炎治療 and 曾治療肺炎的病人.
   - **Medium, a clause-final confirmation in one script only** (reproduced: yes). 本系統可確診 was refused and
     本系统可确诊 was not: the rule compared the word with its Traditional spelling. Both spellings now count.
   - **Low, data-lang read as the page's language** (reproduced: yes). `<html lang="zh-TW" data-lang="en">` was read
     as English. The pattern now needs `lang` not preceded by a word character or a hyphen.
   - **Low, a medication record read as a treatment** (reproduced: yes). 系統建議先匯出用藥紀錄 was refused. Now a
     treatment word followed by a record word (紀錄, 記錄, 史, 清單, 資料, 欄位, 歷程) is not the object of a
     decision. Japanese has 歴, 記録, 履歴, 一覧, データ, 欄, and English has records, history, list, data, fields,
     log. 系統建議病人的用藥 is still refused.

## Measured (the development set; not independent)

`DEV_EN` and `DEV_JA` in `tests/unit/test_wording_en_ja_classes.py` hold 150 sentences per language. They were
written from the meaning before any rule changed:
- 50 claims across the classes, with varied verbs, actors, diseases named by class, hedges and passives;
- 50 honest lines: what the box does, true denials, a trial's own criteria with diagnosis or treatment as data, field
  labels and notices;
- 50 near-misses, 25 each way.

"Claims" below counts the 50 claims and the 25 near-miss claims; "honest" counts the 50 honest lines and the 25
near-miss honest lines.

| Language | Class | Before (master f6c42230) | After |
| --- | --- | --- | --- |
| en | find a disease | 2 / 20 | 20 / 20 |
| en | rate (predict, risk, score, possible) | 1 / 11 | 11 / 11 |
| en | warn, remind | 0 / 7 | 7 / 7 |
| en | treat | 0 / 6 | 6 / 6 |
| en | prevent, reduce | 0 / 6 | 6 / 6 |
| en | decide, recommend | 1 / 9 | 9 / 9 |
| en | state | 0 / 4 | 4 / 4 |
| en | judge, diagnose, replace | 4 / 9 | 8 / 9 |
| en | outright | 1 / 3 | 3 / 3 |
| en | **claims refused** | **9 / 75** | **74 / 75** |
| en | honest: criteria / denials / others | 11 / 13, 14 / 16, 46 / 46 | 13 / 13, 16 / 16, 46 / 46 |
| en | **honest lines passed** | **71 / 75** | **75 / 75** |
| ja | find a disease | 10 / 20 | 19 / 20 |
| ja | rate | 8 / 11 | 11 / 11 |
| ja | warn, remind | 1 / 7 | 7 / 7 |
| ja | treat | 0 / 6 | 6 / 6 |
| ja | prevent, reduce | 0 / 6 | 6 / 6 |
| ja | decide, recommend | 2 / 9 | 9 / 9 |
| ja | state | 1 / 4 | 4 / 4 |
| ja | judge, diagnose, replace | 6 / 9 | 8 / 9 |
| ja | outright | 2 / 3 | 3 / 3 |
| ja | **claims refused** | **30 / 75** | **73 / 75** |
| ja | honest: criteria / denials / others | 10 / 13, 15 / 16, 46 / 46 | 13 / 13, 16 / 16, 46 / 46 |
| ja | **honest lines passed** | **71 / 75** | **75 / 75** |

Before, English's few refusals came only from `FORBIDDEN` ("diagnosis", "diagnoses", "risk score"). Its four
over-refusals were "diagnosis" as a record field, a person's diagnosis, and a true denial. Japanese's came from
D-1228's classes and `FORBIDDEN`'s 診断. Its four over-refusals were 診断 as a passive by a physician, a person's
diagnosis or a topic, and 循環器医により…と診断された.

**The after figures are not a measurement**: every sentence was used to fix the rule. The three claims still missed
are kept as `KNOWN_MISSES`. D-1247's experience is the warning: its development sets reached 100 %, then an
independent set written before reading the code found 34 of 150 claims passing.

## Consequences

`docs/plan/intended-use.md` §2 names the en and ja classes (version 0.5).

Known limits, stated rather than chased (`test_the_known_limits_are_what_d1256_says` records them):
- **a claim split across sentences**: "Is the patient sick? The system will tell you.";
- **a metaphor with no claim word**: "shines a light on patients hiding in the records";
- **a claim with no subject** of the act, state and decide classes: "Can treat depression.", 可治療憂鬱症 (as zh-TW);
- **a person's act denied with the product doing it elsewhere**: "Doctors no longer need to diagnose: the software
  does it for them", 医師が診断する必要はなく、ソフトウェアが代わりに行います. The denial masks the verb;
- **読み取り**: the product's own word for a model reading a record, as 判讀 is in zh-TW, so
  うつ病の兆候を読み取ります is not seen;
- **English text not named en is not read by the English table**: the report, mail and document tests that pass no
  language, and the public site's English page, which no test walks (D-1228's site test reads the Japanese pages
  only). Japanese text not named ja is read by D-1228's table only;
- **"diagnosis" with no subject in a criterion** is still refused by `FORBIDDEN`, as on master (RA-JAK-EXC-10's "a
  pregnancy diagnosis within 280 days", GZQO-INC-02's source text). So is 診断 in 痛風の診断 and 妊娠の診断;
- **English words are matched as patterns, not lemmas**: an unlisted verb ("unmask", "surface") or a disease that
  neither ends in the class nor is listed is not seen. A window of 64 characters can reach a disease in a long
  sentence, or miss one further away;
- **"and" and "or"** end an English denial before a non-claim verb or a finite claim verb. A list of nouns joined by
  "and" before a claim word ("does not detect cancer and predict ...") is read as one denial.

A morphological analyser (Japanese) or a parser (English) would read subject and object better than the windows. It
is a new dependency, so it waits on the same owner decision as D-1228's and D-1247's.
