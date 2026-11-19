# D-1247 The zh-TW device-claims check is a second table in D-1228's one rule

- **Task:** card 10C-5b of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C; lane J), the follow-up that D-1228
  names: "zh-TW keeps the older word list (診斷, 排除, 建議治療), weaker than ja". PR #1179.
- **Date:** 2026-11-19
- **Status:** accepted; reserved for the pull request of card 10C-5b (lane J's block D-1220 to D-1319)
- **Builds on:** D-1228 (the Japanese device-claims rule), D-351 (a record's own field and quoted source text are not
  the product's wording), TB-IU-01 (`docs/plan/intended-use.md`)

## Context

Before this card, Traditional Chinese text was checked only against `FORBIDDEN` (診斷, 排除, 建議治療 ...). A zh-TW
string could say the box finds disease (偵測疾病, 早期發現), predicts a patient's risk (預測病人的風險), scores
patients (風險分數) or lists suspected or undiagnosed patients (疑似病例, 未確診), and no test would fail. On master
73835e62 the check refused 1 of 30 fresh zh-TW claims written for this card (`FRESH_1_CLAIMS`).

The 10C-5 worker's read-only survey of master 73835e62 reported 89 zh-TW catalogue strings with a draft term and 5
draft hits, all false alarms. Collected the way `tests/unit/test_wording.py` collects the catalogues (console,
orchestrator, opportunity hub, one row per distinct key), I find **60** distinct strings with a term, not 89; the
survey's method is not recorded, so the gap is not explained. Its five false alarms are confirmed: `footer.statement`,
`consent.help` (主要風險), `feas.s6` (收案預測), `feas.bridge.unknown_system` and `screen.unknown_system` (無法辨識).

## Decision

0. **It is a lint, not a guarantee**, as D-1228 says for Japanese. It checks the project's own zh-TW texts for common
   claim forms; every new zh-TW public text still needs a human reading.
1. **One rule, two tables.** The claim rule in `libs/tb_common/wording.py` is now one function, `check_claims`, over
   `CLAIM_TABLES`: the Japanese table (D-1228's lists, unchanged) and a zh-TW table (`CLAIM_*_ZH`). The classes are
   D-1228's:
   - compound claim nouns refused outright (`CLAIM_OUTRIGHT_ZH`: 早期發現, 風險預測, 風險分數, 預後, 未診斷, 未確診,
     潛在病人, 疑似病例, 預警 ...);
   - finding words (偵測, 檢出, 發現, 找出, 篩檢, 辨識, 識別, 判別, 分流, 遺漏 ...) that are a claim when their object
     is a disease or an early / latent case;
   - rate words (預測, 預估, 風險, 危險, 評分, 分數, 機率, and 疑似) that are a claim when they are about a patient or a
     disease, or the product stands straight before them;
   - 判斷 with the product, the AI, a model or the box (本機) as its subject.

   The zh-TW table adds one class the Japanese table does not have yet: **warning words** (警示, 示警, 警訊, 警報) that
   are a claim when they are about a patient, a disease or an early case; 預警 and 早期預警 are refused outright.
   `check_claims_ja` is kept as the name D-1228's callers use, and reads with the Japanese table only.

   Shared with Japanese: the normalisation (`clean_ja`: NFKC, invisible characters removed), the sentence split, the
   12-character window and the page reading (`sentences_of_page`). There is no second checker.
2. **The caller names the language; the script is never used to guess it.** `check`, `check_claims`, `check_page`
   and `check_file` take `lang`.
   - Text named zh-TW (`zh`, `zh-TW`, `zh-Hant` ...) is read by the zh-TW table, and by the Japanese table as before.
   - Text with no language, or named `ja` or `en`, is read by the Japanese table only, exactly as before this card. A
     Japanese line in kanji only (症例識別番号, 症状評分) is therefore never read by the zh-TW table. An earlier draft
     guessed from the script (kana or not) and refused such lines; the review caught it.
   - A page names its own language (`<html lang="zh-TW">`, set by the console's templates), and `check_page` reads it
     there. So the page walk reads zh-TW pages with the zh-TW table without any change to the walk.
   - The zh-TW catalogue strings are checked named zh-TW (`test_no_zh_tw_catalogue_string_makes_a_device_claim`), and
     so are the criterion labels, by their language key.
3. **What differs is data in the table, per language:**
   - **The words, and the allowed contexts** (`CLAIM_ALLOWED_ZH`, each pinned by a test): a named clinical scale's
     score (ECOG 分數, the `NAMED_SCALES` list shared with Japanese), 分數定義, risk of bias (偏差風險), a study's own
     risks to the participant as a consent form states them (試驗的風險, 風險與好處, 研究為受試者帶來的風險), a study's
     enrolment forecast and a head count (收案預測, 預測隨機分派, 預估人數), a lab's detection limit (偵測極限), and the
     study's screening visit as a point in time (a protocol's 篩選前 90 日內). An allowed context never swallows a
     longer claim: it does not apply when a rate or score word follows it (研究風險預測 is refused; 研究的風險 is not).
   - **A disease object is judged by its class, not only from a list.** A noun that ends in 病 / 症 / 炎 / 癌 / 瘤 /
     衰竭 / 梗塞 / 感染 is a disease (糖尿病, 肺炎, 心衰竭, 肺癌). The words that only look so are excluded: 病人, 病患,
     病歷, 病史, 病房, 病名, 病床, 病例, 病號, 病友, 病理, 病程, and 適應症 (a drug's indication). A short list adds
     names that do not end so (高血壓, 氣喘, 失智 ...). The class looks at the next character, so for zh-TW the window is
     matched on the whole sentence (a cut window would read 病人 as 病); the Japanese window is unchanged.
   - **Simplified Chinese.** Every term is written once, in Traditional. `_zh_both()` adds its Simplified form through
     the character map `_SIMPLIFIED` kept beside the table. `_SAME_ZH` declares the characters written the same in both
     scripts, and a test holds that the two cover every character the table uses. `_ZH_LEXICAL` adds the few words
     that differ by more than their characters (人工智能, 算法, 软件, 医生, 筛查). `FORBIDDEN`'s 診斷 and 建議治療 are
     refused in Simplified (诊断) by the zh-TW table. No new dependency.
   - **The subject.** Chinese marks a subject by position, not by a particle, so an actor or a person is a subject
     unless an attributive 的 / 之 / 所 follows it (醫師參考 AI 的讀取結果判斷 is the physician judging). The actors
     include 本機, the catalogue's own word for the box, and 我們. 系統性 (systematic) is not 系統.
   - **The denial.** Chinese negates **before** the verb. A claim word is denied when the part of its clause before
     it carries an odd number of negators (two cancel, as in Japanese).
     - A verbal negator (不, 未, 無法, 並未, 絕不 ...) counts only when a light verb (用於, 提供, 進行, 做, 給予, 產生,
       發出 ...) or a claim word follows it, after its auxiliaries (會, 能, 可, 再 ...). So 未符合條件之病人的風險 denies
       nothing, and 不只預測 (not only) is no denial.
     - An existential, copular or prohibitive negator (沒有, 毫無, 不具, 不是, 並非, 請勿, 不得 ...) covers the rest of
       its clause, and is counted once (不是 is not also 不 + 是). It does not count when a patient or a disease word
       stands straight before it: 病人沒有風險 is said about the patient.
     - A negated "miss" (沒有漏掉, 不會遺漏) is a claim of completeness, not a denial, so it counts for nothing.
     - 非 alone counts only straight after the product's name (本軟體非醫療器材); 非小細胞肺癌 is a disease name.
     - A clause ends at 。！？；, a line end, 但 / 卻 / 然而 / 而 (not 而非), or a comma that does not continue a list of
       claim words. So 不做診斷、預測或風險分層 is one denial, while 本機不提供診斷但會偵測疾病 still refuses 偵測.
4. **Japanese and English are unchanged, measured against the base 0de6b1d0.** For each item, `check()` was run
   with the language named and with none; the output is identical on 0de6b1d0 and on this branch. The items are:
   - every console, orchestrator and opportunity-hub catalogue string (each with its language);
   - the public site's Japanese text that D-1228's test walks (`check_claims_ja` and `check` named ja);
   - every criterion label and text in `rulesets/*/labels.yaml`;
   - D-1228's own test sentences.

   That is 10,216 ja items and 9,673 en items. The zh-TW items (9,683) are identical too: no zh-TW catalogue string
   or label makes a claim under the new table. D-1228's tests run unchanged. A denial of a `FORBIDDEN` word in text
   named zh-TW (本軟體不用於疾病之診斷) is masked, as D-1228 masks a Japanese one.
5. **The survey's false alarms are resolved by structure, not by exemption.**
   - The statement: its claim words are denied (不用於, 不判定, 不作為, 不發出臨床警示), and it passes the claim rule
     without the `ALLOWED` mask.
   - `consent.help`: the object of 風險 is the study (風險、好處 are what a consent form states).
   - `feas.s6`: the object of 預測 is an enrolment count.
   - The two unknown-system strings: 無法 + 辨識.

   Each case has a test with the closest sentence that lacks the structure, and that sentence is refused. There is no
   per-string exemption, no allow-list entry and no exception file.
6. **Two strings reworded.** `stage.S1` and `overview.models.engine` (zh-TW) listed the record fields as
   年齡、性別、疾病、檢驗、用藥 next to 篩選, a finding word. Both now say 病名, the word the zh-TW catalogue already uses for
   this field (`edc.source.condition`, `site.domain.condition`, `site.codes.kind.dx-text` 文字病名). The Japanese
   strings say 病名 too, and D-351 names a record's own field so.
7. **Reach is D-1228's.** No new file kind is walked. What D-1228's check walks is read with zh-TW where its
   language is known: the catalogues by their key, the pages by `<html lang>`, the criterion labels by their key. Other
   callers that pass no language (some report, mail and document tests) read as before, Japanese only. The zh-TW
   public page `site/pages/index.zh-TW.html` is not walked, and this card does not add it. Read once with this rule,
   it has no device claim, but it does carry three `FORBIDDEN` words (排除 twice, 判定) from before.

## Measured

| Set | Written by | When | Claims refused | Legitimate passed |
| --- | --- | --- | --- | --- |
| `FRESH_1` (30 + 30), before the zh-TW rule existed | the card worker | master 73835e62 | 1 / 30 | 28 / 30 |
| the same | | first draft of the rule | 30 / 30 | 28 / 30 |
| the same | | after one fix (a negator's verb may be the claim word itself) | 30 / 30 | 30 / 30 |
| `FRESH_2` (20 + 20), after the rule was first final | the card worker | first run | 15 / 20 | 16 / 20 |
| the same | | after its fixes | 20 / 20 | 20 / 20 |
| the review's set (82 + 89, 31 in Simplified), written before reading the code | an independent tester | cc197e3b | 59 / 82 | not given here; one regression (ja kanji-only lines) |
| `FRESH_3` (20 + 20), after the review's round | the card worker | __SET3_FIRST__ | __SET3_C__ | __SET3_L__ |

The second set found these faults, all fixed:
- five claims missed: unlisted verbs 察覺, 分辨, 標示, 推估; 提前 / 更早 as "early"; 症, 結節 and 存活 not disease
  words; 傾向 not latent;
- one double count: 不是 and 不具 counted once as a verbal and once as a copular negator, so they cancelled;
- 請勿 not read as a negator;
- two contexts too narrow: 預測可收案, and 研究為受試者帶來的風險.

The test that walks the shipped criterion labels then found one protocol text, 篩選前90日內發生心肌梗塞或中風 (GZQO).
Its 篩選 is the study's screening visit, so that context is now allowed and pinned by a test.

The review found these, all addressed (each with claims and near-misses as tests: `REVIEW_CLAIMS`,
`REVIEW_NEAR_MISSES`):
- the script-guess regression;
- ordinary disease names missing (now the disease class);
- Simplified text not read;
- early warning not a claim class;
- 本機 and 我們 not actors;
- a denial running past 但 or masking a "does not miss";
- an allowed context swallowing 研究風險預測;
- triage (分流) missing from the table.

None of the sets above is unseen by the rule as it now stands, except `FRESH_3` at its first run.

## The Taiwan source (verified 2026-11-19)

- **醫療器材管理法** (statute; the competent authority is 衛生福利部), promulgated 民國 109 年 1 月 15 日 (in force 110 年 5 月 1 日, as the TFDA
  guidance below states), read on 全國法規資料庫 at https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030106:
  **第 3 條** defines a device by its design and use to achieve, among others, the diagnosis, treatment, mitigation or
  direct prevention of human disease (T1 of TB-IU-01 §3); **第 6 條** defines a device advertisement as publicising
  medical efficacy; **第 46 條**, whole: 「非醫療器材，不得為醫療效能之標示或宣傳。但其他法律另有規定者，不在此限。」 (T3); **第 65 條** fines a breach of
  第 46 條 NT$600,000 to NT$25,000,000.
- **醫用軟體分類分級參考指引**, 衛生福利部食品藥物管理署 (TFDA), 104.4.13 制定, 109.12.24 修正, **111.9.15 修正**
  (announced 2022-09-15, FDA器字第1111609211號公告), announcement at
  https://www.fda.gov.tw/tc/siteListContent.aspx?sid=310&id=41636 and the guidance itself at
  https://www.fda.gov.tw/tc/includes/GetFile.ashx?id=f637988574332883487&type=1. Its **section 三** lists the points
  for deciding whether medical software is a device, among them (三) 「是否宣稱具診斷、治療功能或協助診斷、治療」:
  whether the software **claims** a diagnostic or treatment function, which is why a claim in the product's words
  matters. **Section 五(一)** (醫院行政管理軟體, 範例 1) reads hospital administration software that keeps and shows
  records, leaving the judgement to staff and giving no 疾病之判定及建議, as no device. **Section 五(五)** (電腦輔助
  偵測/診斷/分流軟體) places software that helps detect lesions (協助偵測病變) or triages, for example screening for
  patients with acute brain haemorrhage (篩檢急性腦出血病人), in class 2. **Section 五(九)** places software that
  computes a risk probability (風險機率) in class 2. The rule's classes cover these functions said in the product's
  words: detecting disease or lesions (finding words), triage (分流), and risk and probability (rate words).
- This is the project's reading. As TB-IU-01 says, it is not legal advice and is to be confirmed with the regulatory
  adviser (R1, R5).

## Consequences

`docs/plan/intended-use.md` §2 names the zh-TW claim words, and §3 points here for the verified article and section
numbers.

Known limits, stated here rather than chased:
- **a claim split across sentences**: 病人是否罹患肺癌？系統會告訴您。 Each sentence alone makes no claim;
- **a metaphor with no claim word**: 揪出藏在病歷裡的病人, 不再被遺漏;
- unlisted verbs (判讀 is not listed: it is the product's own word for a model reading a record) and disease names
  that neither end in the class's characters nor appear on the list;
- a disease word more than 12 characters from the verb;
- a person subject in a later clause;
- a named scale masking the product's own estimate of it;
- the window's false alarm on 疑似 near a patient word (以疑似亂數決定患者的顯示順序 is refused; a test records it);
- text a caller does not name zh-TW is read as Japanese only. That covers the report, mail and document tests that
  pass no language. They checked zh-TW text against `FORBIDDEN` only before this card, and they still do;
- **an existing over-refusal, not this card's**: `FORBIDDEN`'s 診斷 refuses legitimate zh-TW lines that quote a
  diagnosis as a record fact or a criterion, the same as on master. Examples from the review: 本機只讀取醫師已記錄的
  診斷碼，不自行產生診斷。 and 納入條件：經醫師診斷為第二型糖尿病至少一年。 The review counted ten such lines. A
  follow-up card should judge 診斷 by its object too.

A Chinese word segmenter would read subject and object better than the windows. It is a new dependency, so it waits
on the same owner decision as D-1228's morphological analyser.
