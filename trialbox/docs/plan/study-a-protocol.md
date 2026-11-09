# Study A protocol: retrospective accuracy of TrialBox screening at CGMH (draft)

| Field | Value |
| --- | --- |
| Document ID | TB-STUDY-A-01 |
| Version | 0.1, draft for the PI and the CGMH IRB (2026-11-09) |
| Short title | TrialBox Study A: does the candidate list hold up against chart review? |
| Site | Chang Gung Memorial Hospital (CGMH), Taiwan. A Japan site follows under its own protocol. |
| Sponsor of the study | Aimedics (the maker of TrialBox). The conflict of interest is declared in §11. |
| Principal investigator | Changfu Kuo, as the master plan names him (TB-PLAN-05 WS-16.1). **Owner to confirm**: the IRB may prefer a CGMH co-PI with no Aimedics role (§11). |
| Decided by | owner decision of 2026-11-09 (`docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`, "Regulatory and commercial"); D-144; TB-PLAN-05 WS-16.1 |
| Traces to | URS-PI-20, RSK-02, RSK-34, TST-PQ-02 |
| Data rule | TB-SITE-03 (`docs/plan/sites/data-handling-rule.md`) applies to every step |

The zh-TW version follows the English text (§15). The English text governs until the IRB approves a version.

## 1. Why this study

TrialBox reads a hospital's own records and lists patients who may meet a study's criteria. It also lists the patients whose records did not match a criterion, so the investigator can check them. Nobody has yet measured, on real CGMH charts, how often the list is right, or how often a patient is wrongly put on the "criteria not matched" list. Until this study reports, Aimedics makes no claim about accuracy (owner decision; RSK-34).

## 2. Objectives and endpoints

### 2.1 Primary objectives

| No. | Objective | Endpoint | Target (both parts must hold) |
| --- | --- | --- | --- |
| P1 | How often is a patient on the "ready" list really record-eligible? | **Precision** (positive predictive value) of the "ready" list, pooled over the studies | point estimate ≥ 0.75 **and** lower bound of the two-sided 95 % confidence interval > 0.65 |
| P2 | How often does TrialBox wrongly put a patient on the "criteria not matched" list because of a note? | **Wrong-exclusion rate** among patients not matched on a note-based criterion | point estimate ≤ 2 % **and** upper bound of the two-sided 95 % confidence interval ≤ 5 % |

### 2.2 Secondary objectives

1. Precision and wrong-exclusion rate per study and per criterion type (structured code, lab value, note only).
2. Criterion-level sensitivity and specificity by criterion type, with sampling weights (§7.4).
3. Abstention: the share of patients TrialBox put in "needs information", and what the reference standard found for them.
4. Wrong-exclusion rate among patients not matched on a **structured** criterion only.
5. Recall of enrolled patients: of the patients each study really enrolled in the period, how many TrialBox listed as "ready" or "needs information".
6. Agreement between the two reference readers (Cohen's kappa) before adjudication.
7. Agreement between TrialBox's two models on the note-based criteria in the sample.
8. Reader time per chart (a resource figure only).

## 3. Definitions

| Term | Meaning in this study |
| --- | --- |
| Study | one CGMH clinical study (completed or running) whose criteria the study's PI approved in TrialBox |
| Index date | the first day of the study's screening period; TrialBox and the readers use only what was recorded on or before it |
| Snapshot | TrialBox's data as of the index date, frozen and kept for the study's life |
| Ready | TrialBox's candidate list, tier "ready" (every record-assessable criterion met) |
| Needs information | TrialBox's candidate list, tier "needs information" (a criterion unknown from the record) |
| Criteria not matched | TrialBox's list of patients whose records did not match at least one criterion, with the criterion and the record it rests on |
| Record-assessable criterion | a criterion a reader can judge from the chart. Criteria only a person can judge (for example "willing to attend visits") are left out for TrialBox and for the readers alike |
| Record-eligible | the reference standard rates every record-assessable criterion "met" |
| Wrong exclusion (P2) | a patient on the "criteria not matched" list for whom the reference standard rates **every** criterion TrialBox did not match as "met" or "cannot tell from the record", and rates **no** other criterion "not met". Unknown never excludes, so "cannot tell" counts against TrialBox |
| Reference standard | the adjudicated chart review of §5 |

## 4. Design

Retrospective accuracy study at one site, on frozen data, against a blinded chart review. It is reported to the STARD 2015 checklist.

### 4.1 Which studies

Three to five CGMH studies, chosen before any sampling, that:

- had a screening period in the 24 months before the snapshot is made;
- have criteria approved in TrialBox by the study's PI;
- together cover at least two specialties, and at least one has a criterion that only a note can show.

A study whose "ready" list has fewer than 50 patients is still analysed and reported, and one more study is added so that P1 keeps at least 300 patients.

### 4.2 The index test

TrialBox runs once per study on the snapshot dated at the index date. The release, the site mapping, the model pair as installed and the criteria are frozen and recorded (version numbers and hashes) **before** any patient is sampled. A change after that is a new version, and the study is not re-run on it unless a protocol amendment says so. The charts used for the OQ dry run (TB-PLAN-05 WS-16.4) are left out of the Study A samples, because the mapping may have been tuned on them.

## 5. Reference standard

- **Readers.** Two clinicians (physicians, or research nurses with at least two years of trial screening), trained on each study's criteria before reading. They are not part of the TrialBox build, and they are not on the study team of the study they read.
- **What they read.** The patient's CGMH chart in the hospital's own EMR, up to the index date only. A reader who sees later information records it and does not use it.
- **What they record**, per patient and study, on a reading form in a CGMH-hosted REDCap project: each record-assessable criterion as *met*, *not met* or *cannot tell from the record*, with the date and place of the evidence; then the patient's status (record-eligible, not eligible, cannot tell); then minutes spent.
- **Blinding.** Readers never see TrialBox's output, its tier or its quotes. Each reader's list mixes "ready", "needs information" and "not matched" patients in random order, so the list does not reveal TrialBox's call. Readers work independently.
- **Adjudication.** Where the two readers disagree on any criterion or on the status, a third clinician, senior and of the study's specialty, decides after reading the chart and both forms. The adjudicator is also blind to TrialBox's output.
- **Training check.** Before reading, both readers rate 10 practice charts from outside the samples; kappa below 0.6 on patient status triggers retraining.

## 6. Sample size

### 6.1 P1, precision of the "ready" list

- **Sample:** 100 patients drawn at random from each study's "ready" list (all of them if the list is shorter). With three studies, 300 patients; with five, 500.
- **Why 100 per study:** one study of 100 at precision 0.75 gives a 95 % interval of 0.65 to 0.83 (exact), so each study is reported with a usable interval. Pooled over three studies (stratified estimate, §7.2), the half-width is about ±0.049 at 0.75. If the true precision is 0.75, the chance that the pooled lower bound clears 0.65 is about 0.98 (normal approximation). At a true 0.80 it is above 0.99.

### 6.2 P2, wrong exclusion on a note-based criterion

- **Sample:** 400 patients drawn at random from the patients not matched on a note-based criterion, over all studies, allocated to the studies in proportion to their list size (at least 50 per study).
- **Why 400:** the target needs both a point estimate ≤ 2 % and an upper exact (Clopper-Pearson) 95 % bound ≤ 5 %. With 400 patients both hold if and only if there are **at most 8** wrong exclusions (8/400 = 2.0 %, upper bound 3.9 %; 9/400 gives 2.25 %). The design assumes a true rate of about 1.5 %, from the hand audits of public data (`docs/reviews/2026-11-05-public-data-validation.md`: about 3.6 % on public data before the filter-first changes, lower after). The chance of meeting the target is about 0.85 if the true rate is 1.5 % and 0.98 if it is 1.0 %. If the true rate is 2.0 %, the upper bound alone stays ≤ 5 % with a chance of about 0.89, but the point estimate is then above 2 % about half the time, as it must be. With 300 patients the chance at 1.5 % would be 0.83 and at 2.0 % only 0.75 for the upper bound; 400 is the smallest round number that keeps both above 0.85.

### 6.3 Secondary samples

- 50 "needs information" patients per study, at random (abstention, secondary 3).
- 50 patients per study not matched on a structured criterion only (secondary 4).
- Every patient each study enrolled in its screening period, from the trial office's enrolment log (secondary 5). These are checked against TrialBox's buckets; they need no full chart reading unless TrialBox did not list them.

### 6.4 Workload and funding

About 1,000 charts with three studies (300 + 400 + 150 + 150) and about 1,400 with five. Two readers at about 20 minutes a chart, plus adjudication of about 15 % of charts at 30 minutes, is about **740 hours** (three studies) to **1,040 hours** (five studies). This is inside the master plan's budget of 530 to 1,330 hours (WS-16.1). The hours are funded by the study budgets or by Aimedics, never by the pilot CRCs' spare time.

## 7. Analysis plan

The plan is locked and pre-registered (OSF) before the first chart is read. An independent statistician, not employed by Aimedics, runs the locked analysis on CGMH's hardware.

### 7.1 Populations

- **Analysis set:** every sampled patient with a complete adjudicated reading.
- A chart that cannot be opened (no record for the period, record withdrawn) is replaced by the next patient in the same stratum's random order. Each replacement and its reason is reported. Nothing is imputed.

### 7.2 Primary analyses

- **P1.** Precision per study = record-eligible ÷ sampled "ready", with the exact 95 % interval. The pooled precision is the stratified estimate over studies, each study weighted by the size of its "ready" list, with its variance from the strata (studies are fixed strata, not a random sample of studies). The claim covers these studies at CGMH and nothing wider.
- **P2.** Wrong-exclusion rate = wrong exclusions ÷ sampled not-matched patients, with the exact (Clopper-Pearson) 95 % interval. If the per-study floor of 50 makes the sample differ from proportional allocation, the weighted estimate with the Korn-Graubard interval is primary and the unweighted one is shown beside it.
- **Decision.** Each target is met only if both of its parts hold (§2.1). The two targets are judged separately; no multiplicity correction is needed because no claim rests on "either".

### 7.3 Sensitivity analyses

1. "Cannot tell" counted as a correct exclusion (the lenient reading of P2) and as not eligible for P1.
2. Each reader alone, before adjudication.
3. By language of the notes (zh-TW, English, mixed).
4. Leaving out a study whose TrialBox criteria differ from the protocol in any way the PI noted at approval.
5. Leaving out patients for whom a reader recorded that later information was visible.

### 7.4 Secondary analyses

- Criterion-level sensitivity and specificity by criterion type. Because only sampled patients are read, each reading is weighted by the inverse of its sampling probability within its stratum (ready, needs information, not matched on a note, not matched on a structured criterion). Intervals by bootstrap within strata (2,000 resamples).
- Abstention: the share of each study's screened patients in "needs information", and the reference standard's status for the sampled ones.
- Recall of enrolled patients with the exact interval, and each missed patient's reason (not in scope, not matched with the criterion named, not in the snapshot).
- Kappa between readers on patient status and per criterion type.
- Model agreement: the share of sampled note-based calls where both of TrialBox's models agreed.

### 7.5 Reporting

STARD 2015 flow diagram and checklist; per-study and pooled tables; every wrong exclusion listed by criterion type and reason (in aggregate, no quotes); the release, mapping and model versions; deviations from this plan.

## 8. Bias and how the design limits it

| Bias | Risk here | What limits it |
| --- | --- | --- |
| Review bias | readers who know TrialBox's call agree with it | readers and adjudicator blind; lists mixed and shuffled |
| Incorporation bias | the reference uses TrialBox's output | the reference uses only the EMR, never TrialBox |
| Partial verification | only sampled patients are read | sampling probabilities known by design; weighted secondary estimates; primary endpoints are conditional on TrialBox's call, which is what a user sees |
| Spectrum | studies chosen by willing PIs may be easy ones | studies fixed before sampling; at least two specialties; at least one note-only criterion; every study reported |
| Look-ahead | the EMR shows information after the index date | readers told to stop at the index date; they record when they saw later facts; sensitivity analysis 5 |
| Tuning | the mapping fits the sample | everything frozen before sampling; dry-run charts excluded |
| Conflict of interest | the maker runs the study of its product | §11 |
| Reader drift | standards change over months | training check; 5 % of charts re-read by the adjudicator during reading, kappa reported |

## 9. Ethics and the IRB route

- **Committee.** The CGMH Institutional Review Board.
- **Route.** Retrospective chart review with a **waiver of informed consent** under the MOHW 2012 announcement on human research that may be exempt from consent (得免取得研究對象同意之人體研究案件範圍): the study is minimal risk; it cannot practicably be done with consent from about 1,000 to 1,400 patients, many no longer in care; the waiver does not harm their rights; and the data are pseudonymised for analysis. Where the IRB asks for it, the hospital's public research notice names the study and gives an **opt-out** channel. **IRB to confirm** which of the two it requires.
- **Opt-out.** Patients in the hospital's opt-out register, or in TrialBox's opt-out register (D-147), are left out of every sample before it is drawn.
- **No contact.** No patient is contacted. Nothing in the study changes care. TrialBox's output for these past screening periods is never shown to a treating physician as part of this study.
- **Registration.** The analysis plan is pre-registered on OSF before reading starts.

## 10. Data handling (TB-SITE-03)

- All real data stays on CGMH's hardware: TrialBox's snapshot on CGMH's platform, the charts in CGMH's EMR, the reading forms in a CGMH-hosted REDCap project.
- The steward (for the pilot, the CGMH steward named under D-145, with the independent CGMH second reviewer) draws the samples on CGMH's hardware and holds the key from study ID to TrialBox pseudonym. Readers see the chart number in the EMR as part of their normal access; it is never written to the reading form.
- The analysis file holds study IDs, TrialBox's call, the readings and dates turned into days from the index date. It is made and analysed on CGMH's hardware.
- Only aggregate results leave CGMH. No agent session, repository, CI job, log, screenshot or review document receives any real data (TB-SITE-03 §1.2).
- At the end of the study the identified link (study ID to pseudonym) is destroyed, as 人體研究法 requires for data not de-linked, and the analysis file is kept per CGMH's retention rule.

## 11. Conflict of interest and independence

Aimedics makes TrialBox, sponsors this study and would use a good result in sales. The PI named in the plan is Aimedics's owner. To keep the result trustworthy:

- the PI does not read charts, adjudicate or analyse;
- readers, adjudicator and statistician are independent of Aimedics and are paid at a fixed rate that does not depend on the result;
- the CGMH second reviewer co-signs the sampling record and the locked analysis;
- the analysis plan is pre-registered and every deviation is reported;
- the result is reported whatever it is, including a failed target.

**Owner to confirm** whether a CGMH investigator should be named PI instead, which most IRBs would prefer for a study of a sponsor's own product.

## 12. Timeline (fits TB-PLAN-05 §4.0)

| When | What |
| --- | --- |
| 2026-11 (W1–W2) | this draft; the PI's comments; the CGMH IRB's form chosen |
| by 2027-01-08 (G2) | the readers, adjudicator and statistician named; the analysis plan drafted |
| 2027-03-19 | the CGMH notes feed (tier 3) delivered; the first real snapshot can exist |
| 2027-04-12 (W23) | protocol submitted to the CGMH IRB, as the master plan schedules it |
| about 2027-06 | IRB decision (four to eight weeks); OSF pre-registration; studies fixed; TrialBox runs on the index-date snapshots; samples drawn |
| 2027-06 to 2027-09 | chart reading and adjudication |
| 2027-10 | database locked; the statistician runs the locked analysis |
| 2027-11 | report; only now may any accuracy claim be made (RSK-34) |

The IRB decision date is the main risk to this timeline. A delay moves every later line by the same amount.

## 13. What success and failure mean

- **Both targets met:** the result may be quoted in the form of TB-PLAN-05's claims table (for example "In a retrospective study at CGMH, the candidate list had a precision of X; wrong exclusions on notes were Y %").
- **A target missed:** the list that failed stays behind its gate at CGMH (WS-16.4's thresholds already keep it hidden until the site dry run passes), the causes are analysed by criterion type, and a fix is validated before any re-test. No claim is made.

## 14. Open items

1. The PI question (§11).
2. Which IRB form CGMH requires: waiver alone, or waiver plus a public notice with opt-out (§9).
3. The readers' qualification rule if CGMH prefers CRCs to clinicians.
4. The Japan protocol (opt-out under the 生命・医学系指針), after CGMH.

## 15. 繁體中文版（研究計畫書草案）

以下為上述英文版之中文對照。在 IRB 核准任一版本前，以英文版為準。

### 15.1 研究目的

TrialBox 讀取醫院自身的病歷，列出可能符合某研究收案條件的病人，並列出病歷「未符合條件」的病人供研究主持人覆核。目前尚未有人在長庚醫院的真實病歷上測量此名單的正確程度，也未測量病人被錯誤列入「未符合條件」名單的比例。本研究報告前，Aimedics 不對準確度作任何宣稱。

### 15.2 主要與次要指標

| 編號 | 問題 | 指標 | 目標（兩部分皆須達成） |
| --- | --- | --- | --- |
| P1 | 「可收案」名單上的病人，依病歷判斷真正符合條件者佔多少？ | 「可收案」名單之**精確度**（陽性預測值），跨研究合併 | 點估計 ≥ 0.75，且雙尾 95 % 信賴區間下限 > 0.65 |
| P2 | TrialBox 因病歷記載（文字紀錄）而將病人錯列入「未符合條件」者佔多少？ | 以文字紀錄型條件判定未符合之病人中，**錯誤排除率** | 點估計 ≤ 2 %，且雙尾 95 % 信賴區間上限 ≤ 5 % |

次要指標：各研究及各條件類型（結構化代碼、檢驗值、僅文字紀錄）之精確度與錯誤排除率；條件層級之敏感度與特異度（依抽樣機率加權）；「需補資料」比例及其參考標準結果；僅因結構化條件未符合者之錯誤排除率；實際收案病人被列入「可收案」或「需補資料」之比例；兩位審閱者一致性（Cohen's kappa）；TrialBox 兩個模型之一致性；每份病歷審閱時間。

### 15.3 名詞定義

- **研究**：一項長庚醫院已完成或進行中之臨床研究，其收案條件已由該研究主持人在 TrialBox 核准。
- **索引日**：該研究篩選期之第一天；TrialBox 與審閱者僅使用該日（含）以前之紀錄。
- **可依病歷判斷之條件**：可由病歷判斷之條件；僅能由人判斷之條件（如「願意配合回診」）兩方皆不納入。
- **依病歷符合條件**：參考標準判定所有可依病歷判斷之條件皆「符合」。
- **錯誤排除（P2）**：病人列於「未符合條件」名單，而參考標準對 TrialBox 判定未符合之**每一**條件皆判為「符合」或「病歷無法判斷」，且對其他條件**均無**「不符合」。「不明」永不排除，故「無法判斷」計為 TrialBox 之錯誤。

### 15.4 研究設計

單一醫院、回溯性、以凍結資料進行之準確度研究，以盲性病歷審閱為參考標準，依 STARD 2015 報告。納入 3 至 5 項研究：篩選期在建立快照前 24 個月內、收案條件已於 TrialBox 核准、合計涵蓋至少兩個專科、至少一項研究有僅能由文字紀錄判斷之條件。TrialBox 於每項研究之索引日快照上執行一次；版本、院內對應設定、所安裝之模型組合與收案條件在抽樣**前**凍結並記錄。OQ 試行（WS-16.4）用過之病歷不納入本研究樣本。

### 15.5 參考標準

兩位臨床人員（醫師，或具兩年以上試驗篩選經驗之研究護理師）事先接受各研究條件之訓練；不參與 TrialBox 開發，亦不屬於所審研究之研究團隊。審閱者於院內 EMR 閱讀至索引日為止之病歷，於長庚院內 REDCap 審閱表上逐條記錄「符合／不符合／病歷無法判斷」及證據日期與出處，再記錄病人狀態與所花時間。審閱者看不到 TrialBox 之結果；每份審閱清單隨機混合三類病人。兩人意見不一時，由同專科之資深臨床人員閱讀病歷與兩份審閱表後裁定，裁定者亦不知 TrialBox 結果。審閱前以 10 份練習病歷檢核，病人狀態之 kappa 低於 0.6 須重新訓練。

### 15.6 樣本數

- **P1**：每項研究自「可收案」名單隨機抽 100 人（不足則全數）。三項研究共 300 人時，合併半寬約 ±0.049；若真實精確度為 0.75，下限超過 0.65 之機率約 0.98。
- **P2**：自各研究以文字紀錄型條件未符合者隨機抽 400 人，依名單大小比例分配（每項研究至少 50 人）。400 人時，錯誤排除**不超過 8 人**即同時達成點估計 ≤ 2 % 與精確上限 ≤ 5 %（8/400 = 2.0 %，上限 3.9 %）。假設真實比例約 1.5 %，達標機率約 0.85；真實為 1.0 % 時約 0.98。
- **次要樣本**：每項研究隨機抽 50 名「需補資料」者、50 名僅因結構化條件未符合者；各研究篩選期內所有實際收案病人。
- **工作量**：三項研究約 1,000 份病歷、約 740 小時；五項約 1,400 份、約 1,040 小時，在主計畫預算（530 至 1,330 小時）內，由研究經費或 Aimedics 支付，不佔用試行計畫 CRC 之時間。

### 15.7 統計分析

分析計畫於審閱開始前鎖定並於 OSF 預先登錄，由非 Aimedics 僱用之獨立統計人員於長庚院內硬體執行。P1：各研究精確度附精確 95 % 信賴區間；合併值為依各研究「可收案」名單大小加權之分層估計。P2：錯誤排除率附 Clopper-Pearson 精確 95 % 信賴區間；若每研究至少 50 人之規定使樣本偏離比例分配，以加權估計及 Korn-Graubard 區間為主要分析。兩項目標分別判定，兩部分皆須成立。敏感度分析：將「無法判斷」視為正確排除；單一審閱者；依文字紀錄語言；排除條件與計畫書有出入之研究；排除審閱時看到索引日後資訊者。條件層級指標以抽樣機率倒數加權，以分層自助法估計區間。

### 15.8 偏誤控制

審閱者與裁定者皆盲性、清單混合隨機排序；參考標準僅依 EMR；抽樣機率由設計已知；研究於抽樣前確定；審閱者於索引日停止閱讀並記錄是否看到後續資訊；抽樣前凍結所有設定；審閱期間 5 % 病歷由裁定者重讀以監測漂移；利益衝突處理見 15.10。

### 15.9 倫理與資料處理

- 送長庚醫院人體試驗倫理委員會審查，依衛福部 2012 年「得免取得研究對象同意之人體研究案件範圍」申請**免除知情同意**：最低風險、對約 1,000 至 1,400 名病人取得同意不可行、不損及其權益、分析資料已假名化。如 IRB 要求，於院方研究公告中載明本研究並提供**退出**管道（**待 IRB 確認**）。
- 已登記於院方或 TrialBox 退出名冊（D-147）之病人，抽樣前即排除。不聯絡任何病人，不影響醫療。
- 所有真實資料留在長庚院內硬體：TrialBox 快照、EMR 病歷、院內 REDCap 審閱表。由資料管理人（試行期間依 D-145 指定，並有長庚獨立第二覆核人）於院內抽樣並保管研究編號與假名之對照。審閱表不記錄病歷號。分析檔僅含研究編號、TrialBox 判定、審閱結果，日期轉為距索引日天數。僅彙總結果離開長庚。任何 AI 代理工作階段、程式庫、CI、日誌、截圖或審查文件均不接觸真實資料（TB-SITE-03）。研究結束後依人體研究法銷毀可識別之對照。

### 15.10 利益衝突

Aimedics 為 TrialBox 製造商與本研究贊助者；計畫所列主持人為 Aimedics 負責人。主持人不審閱病歷、不裁定、不分析；審閱者、裁定者與統計人員獨立於 Aimedics，酬勞固定且與結果無關；長庚第二覆核人共同簽署抽樣紀錄與鎖定之分析；不論結果如何皆完整發表。**待負責人確認**是否改由長庚研究者擔任主持人。

### 15.11 時程

2026-11 草案；2027-01-08（G2）前確定審閱者、裁定者與統計人員；2027-03-19 長庚文字紀錄資料（第 3 層）到位；2027-04-12（W23）送 IRB；約 2027-06 核准、預先登錄、抽樣；2027-06 至 09 審閱與裁定；2027-10 鎖定資料庫並分析；2027-11 完成報告，此後方可作任何準確度宣稱。
