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

0. **It is a tripwire on the product's own texts, not a proof**, as D-1228 says for Japanese. It catches common claim
   forms in the project's own zh-TW texts. Two independent measurements (below) show that it misses claims and refuses
   some honest lines, and every new zh-TW public text still needs a human reading.
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

   The zh-TW table adds classes the Japanese table does not have yet (and English has no claim table at all; widening
   those is outside this card, and a test records the gap):
   - **warning words** (警示, 示警, 警訊, 警報) that are a claim when they are about a patient, a disease or an early
     case; 預警 and 早期預警 are refused outright. **提醒** is a warning only when a disease or an early case follows
     it in its clause (系統提醒醫師注意病人可能的心臟衰竭); about a patient alone it is the product's own reminder
     (提醒您確認病人的同意書);
   - **acting on a disease** (醫療器材管理法 第 3 條: diagnosis, treatment, mitigation, prevention; TFDA 三(三)): 治療,
     治癒, 醫治, 療效, 預防, 防止, 避免, 減少, 降低, 確診. A claim when the product is the subject before it and its
     object is a disease or an early case (使用本系統可預防心肌梗塞, TrialBox 可協助醫師治療氣喘病人), or the product
     stands straight before it (本產品的療效). A treatment the record holds is not the product's act (接受糖尿病治療,
     治療紀錄, 治療組, 治療的病人);
   - **telling a patient's state**: 確定, 告訴, 算出, 評估, 得知, a claim with the product as the subject and a state
     word (罹患, 感染, 病情, 復發 ...) after it (系統會告訴您是否罹患糖尿病); 確定收案人數 and 評估可行性 are not;
   - **deciding for the clinician**: 決定, 決策, 建議, 推薦, 選擇, 指示, a claim with the product as the subject and a
     treatment (治療, 用藥, 劑量, 開刀, 手術, 處方 ...) as its object; 臨床決策 and 誤診 are refused outright; 系統建議您先
     匯出名單 is not.

   預知 is a rate word, and 區分 a finding word.
   `check_claims_ja` is kept as the name D-1228's callers use, and reads with the Japanese table only.

   Shared with Japanese: the normalisation (`clean_ja`: NFKC, invisible characters removed), the sentence split, the
   12-character window and the page reading (`sentences_of_page`). There is no second checker. For text named zh-TW,
   `clean` also removes an ordinary or ideographic space between two Chinese characters (診　斷, 早 期 發 現).
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
     study's screening visit as a point in time (a protocol's 篩選前 90 日內), and the zh-TW names of the published
     instruments and measured items the catalogue holds whose name carries a rate word (`NAMED_INSTRUMENTS_ZH`:
     伯明罕血管炎活動度評分, 國際預後指數, FRAX 十年主要骨鬆性骨折機率 ...). Each of those is a record value named
     by its own name (D-351), the zh-TW counterpart of `NAMED_SCALES`. A test holds that each is in
     `catalogue/items.csv`, that every zh-TW name in the catalogue passes, and that the closest claims (AI 計算病人的
     骨折機率) fail. An allowed context never swallows a
     longer claim: it does not apply when a rate or score word follows it (研究風險預測 is refused; 研究的風險 is not).
   - **A disease object is judged by its class, not only from a list.** A noun that ends in 病 / 症 / 炎 / 癌 / 瘤 /
     衰竭 / 梗塞 / 感染, or in 硬化 / 纖維化 / 鈣化, is a disease (糖尿病, 肺炎, 心衰竭, 肺癌, 肝硬化). Not every 化:
     變化, 自動化 and 標準化 are ordinary words next to a finding word. The words that only look so are excluded: 病人, 病患,
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
     include 本機, the catalogue's own word for the box, 我們 and 這套工具. 系統性 (systematic) is not 系統. For 判斷,
     the state and the decide classes, the **nearest subject before the word** decides: a person nearer than the
     product clears it (本系統提供資料，由醫師判斷), and so does a person's own judgement (本系統不取代醫師的判斷) or a
     person as the subject later in the word's own clause (本系統僅顯示資料，判斷由人負責). The product helping a
     person (AI 協助醫師判斷病情) is still the product's act. So only the product as the subject is refused.
     A person as the subject **yields to a product that does the judgement in the same sentence**: an acting product
     before the word in its own clause (本系統可取代醫師做出診斷, 本系統可以發現醫師遺漏的診斷), an acting product
     anywhere in the sentence with a verb of replacing that is not denied (讓醫師不必再自己診斷，系統全部代勞), a
     causative 讓 + product (讓 AI 為您判斷), or the product's own judgement (依本系統的判斷). A product only showing
     or reading what a person recorded (顯示, 讀取, 列出, 呈現), or straight after a negator (本系統不取代醫師),
     does nothing. 由 and 使 are not read as causatives: 由本系統篩選後，醫師判斷 has the product do the screening,
     not the judgement.
   - **FORBIDDEN's 診斷 and 判定, in text named zh-TW**, are blanked where they are not the product's verdict: a record
     field (診斷日期, 診斷碼), a passive by a qualified person (經診斷為, 經醫師診斷) and a person as the nearest subject
     (醫師依病歷診斷, 研究團隊依計畫書判定). The product as the subject (本系統依病歷診斷, AI 協助醫師診斷) is still
     refused. Text not named zh-TW reads them as before.
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
       claim words. So 不做診斷、預測或風險分層 is one denial, while 本機不提供診斷但會偵測疾病 still refuses 偵測. (A
       first version read the clause ends only up to the claim word, so the "continues a list" look was blind and
       本系統不做診斷、風險分層 was refused; the review found it, and the ends are now read on the whole text.)
     - A verbal negator may stand before an opening quote (本系統不能「診斷癌症」). A negator after the claim word at its
       clause's end denies it too (與病人的疾病風險無關).
     - The disease and early words of a denied clause are denied with it: in 本系統不篩檢疾病，只篩選候選受試者, 疾病 is
       the object of the denial, not of 篩選.
     - Finding candidates who meet a study's criteria early (更早找到可能符合條件的受試者) is the product's purpose, so an
       early word does not make such a finding a claim; a disease word still does.
4. **Japanese and English are unchanged, measured against the base 0de6b1d0.** For each item, `check()` was run
   with the language named and with none; the output is identical on 0de6b1d0 and on this branch. The items are:
   - every console, orchestrator and opportunity-hub catalogue string (each with its language);
   - the public site's Japanese text that D-1228's test walks (`check_claims_ja` and `check` named ja);
   - every criterion label and text in `rulesets/*/labels.yaml`;
   - D-1228's own test sentences.

   That is 10,216 ja items and 9,673 en items. The zh-TW items (9,683) are identical too: no zh-TW catalogue string
   or label makes a claim under the new table. Measured again after the second review's round, on the tree merged with
   master 8bfebd70 against master's own rule: ja 10,226 and en 9,683 items identical; of 9,693 zh-TW items two differ
   only in the quoted context (a joined space), with the same word: two older 診斷 hits in RA-JAK's labels. D-1228's tests run unchanged. A denial of a `FORBIDDEN` word in text
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
| `FRESH_3` (20 + 20, three in Simplified), after the review's round | the card worker | first run | 19 / 20 | 20 / 20 |
| the same | | after its one fix (心律不整, 心律不齊, 心房顫動 added to the disease names) | 20 / 20 | 20 / 20 |
| the second review's set (150 + 150), written before reading the code | an independent tester | 8f2bc3db | 116 / 150 (34 passed) | 123 / 150 (27 refused) |
| `REVIEW_2` (32 + 30): the second review's sentences and more in kind, by class | the reviewer and the card worker | 8f2bc3db | 0 / 32 | 16 / 30 |
| the same | | after its round | 32 / 32 | 30 / 30 |
| four honest lines added after, for the two parts a mutation run found untested (接受…治療 and 醫師的判斷 with the product as subject) | the card worker | 8f2bc3db's round | | 4 / 4 |
| the second review's set (150 + 150), re-run by the lane lead | the lane lead | dc72bb45 | 138 / 150 (12 passed; six of them refused at 8f2bc3db) | 144 / 150 (6 refused) |
| `REVIEW_3` (18 + 18): the re-run's six regressions, its listed misses that one line each fixes, and more in kind; the honest lines on both sides | the lead and the card worker | dc72bb45 | 0 / 18 | 16 / 18 |
| the same | | after its round | 18 / 18 | 18 / 18 |

The independent runs are the figures to quote: at cc197e3b 23 of 82 claims passed; at 8f2bc3db 34 of 150 claims
passed and 27 of 150 honest lines were refused; the lead's re-run of that set at dc72bb45 found 12 of 150 claims passing
and 6 of 150 honest lines refused. Six of those 12 had been refused at 8f2bc3db: the second round's person-as-subject
allowance let a product that replaces or supplies the judgement pass. The third round below fixes those six. No
independent run has been made on the head after it.

The lead's re-run found these, addressed in `REVIEW_3`: the six regressions above; two honest lines refused (a product
that only reads a record, 不自行產生診斷, where 自行 now counts as an auxiliary; a product that only shows, in an earlier
clause, before a person judges); and five of its six listed misses, one line each: 低血糖 as a disease, 有沒有得 and
是否得 as states, 確診 used absolutely at the end of its clause with the product as subject, a negated 誤診 counted as a
claim of accuracy (as a negated miss is), and an A-not-A question (能不能, 會不會, 是不是) read as a question, not a
denial. On every catalogue string and criterion label (29,644 items in ja, en and zh-TW) the result is the same as on
dc72bb45.

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

The second review found these, all addressed in `REVIEW_2`: treat / cure / efficacy, prevent / reduce, decide /
recommend and 提醒 had no class (24 of its misses); the verbs 確診, 確定, 預知, 區分, 告訴, 誤診, 評估, 算出 and the
disease 肝硬化; a space inside a word; the clause-end bug above; 判斷 and 判定 refused with a person as the subject;
three denials that failed; two candidate findings refused; and 診斷 as a field, a criterion or a person's act.

The page walk then read the zh-TW `/data/instruments` page for the first time. It found two published instruments
named by their catalogue names (伯明罕血管炎活動度評分, FRAX 十年主要骨鬆性骨折機率), and the allowed instrument
names below answer it.

None of the sets above is unseen by the rule as it now stands: each was used to fix it.

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
- `FORBIDDEN`'s 診斷 in text named zh-TW now passes as a record field, a passive by a qualified person and a person's
  own act. Other forms are still refused as on master: a criterion with no subject (已診斷類風濕關節炎, 懷孕診斷 in
  RA-JAK's labels), and anything in text not named zh-TW;
- the new classes need the product as the subject: 可治療憂鬱症 with no subject is not seen;
- a state before its verb and outside the window: 病人罹患癌症的可能性，會由模型算出 is not seen;
- an A-not-A question about a claim (能不能診斷糖尿病？) is refused as the claim it asks about, whatever the answer;
- the Japanese table has no treat, prevent, state, decide or remind class, and English has no claim table. A test
  records it; widening them is a follow-up.

A Chinese word segmenter would read subject and object better than the windows. It is a new dependency, so it waits
on the same owner decision as D-1228's morphological analyser.
