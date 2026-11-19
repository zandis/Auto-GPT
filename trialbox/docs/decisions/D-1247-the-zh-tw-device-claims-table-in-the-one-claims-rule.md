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
   D-1228's: compound claim nouns refused outright (`CLAIM_OUTRIGHT_ZH`: 早期發現, 風險預測, 風險分數, 預後, 未診斷,
   未確診, 潛在病人, 疑似病例 ...); finding words (偵測, 檢出, 發現, 找出, 篩檢, 辨識, 識別, 判別 ...) that are a claim
   when their object is a disease or an early / latent case; rate words (預測, 預估, 風險, 危險, 評分, 分數, 機率, and
   疑似) that are a claim when they are about a patient or a disease, or the product stands straight before them;
   判斷 with the product, the AI or a model as its subject. `check_claims_ja` is kept as the name D-1228's callers use
   and runs the same rule. The normalisation (`clean_ja`: NFKC, invisible characters removed), the sentence split, the
   window (12 characters) and the page reading (`sentences_of_page`) are shared. There is no second checker.
2. **What differs is data in the table, per language:**
   - the words, and the allowed contexts (`CLAIM_ALLOWED_ZH`, each pinned by a test): a named clinical scale's score
     (ECOG 分數, the `NAMED_SCALES` list shared with Japanese), 分數定義, risk of bias (偏差風險), a study's own risks to
     the participant as a consent form states them (試驗的風險, 風險與好處, 研究為受試者帶來的風險), a study's enrolment
     forecast and a head count (收案預測, 預測隨機分派, 預估人數), a lab's detection limit (偵測極限);
   - the subject. Chinese marks a subject by position, not by a particle, so an actor or a person is a subject unless
     an attributive 的 / 之 / 所 follows it (醫師參考 AI 的讀取結果判斷 is the physician judging). 系統性 (systematic) is
     not 系統;
   - the denial. Chinese negates **before** the verb. A claim word is denied when the part of its clause before it
     carries an odd number of negators (two cancel, as in Japanese). A verbal negator (不, 未, 無法, 並未, 絕不 ...)
     counts only when, after its auxiliaries (會, 能, 可, 再 ...), a light verb (用於, 提供, 進行, 做, 給予, 產生 ...) or a
     claim word follows it. So 未符合條件之病人的風險 denies nothing, and 不只預測 (not only) is no denial. An
     existential, copular or prohibitive negator (沒有, 毫無, 不具, 不含, 不是, 並非, 請勿, 不得 ...) covers the rest of
     its clause. It does not count when a patient or a disease word stands straight before it (病人沒有風險 is said
     about the patient). 非 alone counts only straight after the product's name (本軟體非醫療器材); 非小細胞肺癌 is a
     disease name. A clause ends at 。！？；, a line end, or a comma that does not continue a list of claim words
     (不做診斷、預測或風險分層 is one denial).
3. **The zh-TW table reads only sentences without kana.** zh-TW never writes kana, and a Japanese sentence nearly
   always has some. The Japanese table still reads every sentence. So Japanese and English results are unchanged:
   `check()` gives the same output on master and on this branch for every console, orchestrator and opportunity-hub
   string in three languages, for the public site's text that the D-1228 test walks, and for D-1228's own test
   sentences (14,272 items compared). D-1228's tests run unchanged. A denial of a `FORBIDDEN` word in zh-TW (本軟體不用於
   疾病之診斷) is masked, as D-1228 masks a Japanese one.
4. **The survey's false alarms are resolved by structure, not by exemption.** The statement: its claim words are denied
   (不用於, 不判定, 不作為), and it passes the claim rule without the `ALLOWED` mask. `consent.help`: the object of 風險
   is the study (風險、好處 are what a consent form states). `feas.s6`: the object of 預測 is an enrolment count.
   The two unknown-system strings: 無法 + 辨識. Each case has a test with the closest sentence that lacks the
   structure, and that sentence is refused. There is no per-string exemption, no allow-list entry and no exception
   file.
5. **One string reworded.** `stage.S1` (zh-TW) said 編碼篩選（年齡、性別、疾病、檢驗、用藥）. That put a finding word
   next to a disease word. It now says 病名 (the record field), as the Japanese string says 病名 and D-351 names a
   record's own field.
6. **Reach is D-1228's.** The rule runs inside `check()`, so every caller applies it: the catalogue tests, the page
   walk, the report and mail tests, and the site test over the files D-1228 walks. No new file kind is walked. The
   zh-TW public page `site/pages/index.zh-TW.html` is not walked; this card does not add it. Read once by hand, it
   has no device claim under this rule, but it does carry three `FORBIDDEN` words (排除 twice, 判定) from before.

## Measured

| Set (written by the card worker) | When | Claims refused | Legitimate lines passed |
| --- | --- | --- | --- |
| `FRESH_1` (30 + 30), before the zh-TW rule existed | master 73835e62 | 1 of 30 | 28 of 30 |
| the same | first draft of the rule | 30 of 30 | 28 of 30 |
| the same | after one fix (a negator's verb may be the claim word itself) | 30 of 30 | 30 of 30 |
| `FRESH_2` (20 + 20), written after the rule was final | the final rule as first run | 15 of 20 | 16 of 20 |
| the same | after the fixes below | 20 of 20 | 20 of 20 |

The second set found real faults:
- five claims missed: unlisted verbs 察覺, 分辨, 標示, 推估; 提前 / 更早 as "early"; 症, 結節 and 存活 not disease
  words; 傾向 not latent;
- one double count: 不是 and 不具 counted once as a verbal and once as a copular negator, so they cancelled;
- 請勿 not read as a negator;
- two contexts too narrow: 預測可收案, and 研究為受試者帶來的風險.

All are fixed and the sentences are now tests. Both sets were written by the same worker who wrote the rule. After the
fixes, the second set is no longer unseen. An independent set, as the lane coordinator ran for D-1228, has not been
run.

## The Taiwan source (verified 2026-11-19)

- **醫療器材管理法** (statute; the competent authority is 衛生福利部), promulgated 民國 109 年 1 月 15 日 (in force 110 年 5 月 1 日, as the TFDA
  guidance below states), read on 全國法規資料庫 at https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030106:
  **第 3 條** defines a device by its design and use to achieve, among others, the diagnosis, treatment, mitigation or
  direct prevention of human disease (T1 of TB-IU-01 §3); **第 6 條** defines a device advertisement as publicising
  medical efficacy; **第 46 條** 「非醫療器材，不得為醫療效能之標示或宣傳。」 (T3); **第 65 條** fines a breach of
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
  computes a risk probability (風險機率) in class 2. The claim classes of this rule are those functions said in the
  product's words.
- This is the project's reading. As TB-IU-01 says, it is not legal advice and is to be confirmed with the regulatory
  adviser (R1, R5).

## Consequences

`docs/plan/intended-use.md` §2 names the zh-TW claim words, and §3 points here for the verified article and section
numbers. Known limits are the Japanese ones in their zh-TW form:
- unlisted verbs and disease names (判讀 is not listed: it is the product's own word for a model reading a record);
- a disease word more than 12 characters from the verb;
- a person subject in a later clause;
- a named scale masking the product's own estimate of it;
- a negator whose clause runs on to a later claim word with no comma between them;
- the window's false alarm on 疑似 near a patient word (以疑似亂數決定患者的顯示順序 is refused; a test records it);
- a zh-TW sentence with kana in it is read by the Japanese table only.

A Chinese word segmenter would read subject and object better than the windows. It is a new dependency, so it waits
on the same owner decision as D-1228's morphological analyser.
