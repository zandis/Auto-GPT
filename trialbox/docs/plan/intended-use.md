# Intended use and non-device statement (TrialBox)

| Field | Value |
| --- | --- |
| Document ID | TB-IU-01 |
| Version | 0.1, draft (2026-11-09) |
| Replaces | the draft in TB-PLAN-05 §1.2 and TB-DS-16 §2 (`docs/plan/design/16-regulatory-position.md`), which stay as history |
| Decided by | owner decisions of 2026-11-09 ("Profile" SaMD row, "Regulatory and commercial"); D-144; TB-PLAN-05 §1.2, PR-12 |
| Status | **Not legal advice.** Aimedics's reasoned position. Every row marked **[Consultant]** needs a written view from a regulatory consultant in Japan or Taiwan before it is relied on outside Aimedics. |
| Traces to | RSK-34 (claims), RSK-10 and RSK-11 (profile layers), WS-13.7 (forbidden words), WS-15.4 (written views) |

## 1. The statement

It appears in the console footer, every PDF, XLSX and mail, the 開示書, the IRB packs and all sales material.

> **English.** TrialBox supports clinical research operations at a hospital. It builds a pseudonymised research repository from the hospital's own records, estimates how many patients may meet a research study's eligibility criteria, prepares lists of possible candidates with the record passages they rest on, lists the patients whose records do not match a criterion for the investigator's review, writes cited patient summaries for research staff, and drafts research-record values for a qualified person to confirm. TrialBox does not diagnose, treat or prevent disease, does not decide whether a patient is eligible for a study, does not recommend treatment, does not alert clinicians, and does not contact patients. Every output is reviewed by a qualified person. TrialBox is not a medical device.
>
> **日本語.** TrialBox は病院における臨床研究業務を支援するソフトウェアです。病院自身の記録から仮名化された研究用データベースを作成し、研究の参加条件に合う可能性のある患者数を見積もり、根拠となる記録の該当箇所を添えて候補者一覧を作成し、条件に合致しない患者を研究責任者の確認のために一覧にし、研究担当者向けに出典付きの患者要約を作成し、資格のある担当者が確認するための研究記録の値の下書きを作成します。疾病の診断・治療・予防は行わず、研究参加の可否を判断せず、治療を推奨せず、臨床医への警告を行わず、患者へ連絡しません。すべての出力は資格のある担当者が確認します。本ソフトウェアは医療機器ではありません。
>
> **繁體中文.** TrialBox 為支援醫院臨床研究作業之軟體。本軟體以醫院自身之紀錄建立假名化研究資料庫，估計可能符合研究收案條件之病人數，產生附有依據紀錄段落之候選名單，列出紀錄未符合某條件之病人供研究主持人覆核，為研究人員撰寫附出處之病人摘要，並產生研究紀錄數值之草稿供合格人員確認。本軟體不用於疾病之診斷、治療或預防，不判定病人是否符合研究資格，不提供治療建議，不對臨床醫師發出警示，亦不聯繫病人。所有輸出皆由合格人員審閱。本軟體非醫療器材，不作為診斷依據。

## 2. The product's own words must agree

| Rule | Where it bites |
| --- | --- |
| A patient is "not matched on criterion X by record Y", never "excluded". The list is **"Criteria not matched"** (ja 基準に合致しない患者, zh-TW 未符合條件之病人) in every language, the API and the reports (PR-12) | console, `/api/v1`, PDFs, XLSX, mail |
| "除外", "排除", "excluded", 診断, 判定, 対象外, 見逃し, 診斷, "diagnosis", "abnormal", "risk score", "AI decides" are forbidden words, checked by the browser walk (WS-13.7). Only the risk file names the hazard plainly | every page in three languages |
| A drafted eCRF value is a **draft**, shown beside its source, until a person confirms it. It is never called a finding or a result | the EDC prefill screens (D-160) |
| Setpoints are numbers with a "check" mark, never an alert, colour or the word "abnormal" | profile pages |
| The clinician (treating physician) role sees setpoint and gap layers **only inside a study-referral context, as numbers without a disease name, behind a switch that is off by default** (owner decision, "Profile" SaMD row). PIs and stewards see them labelled research use. No forecast layer | profile pages, referral pages |

## 3. Conditions that keep the statement true

Each condition is mapped to the question it answers. Japan: the MHLW 「プログラムの医療機器該当性に関するガイドライン」 (2021-03-31, revised 2023-03-31) asks **J1**, whether the program is intended for diagnosis, treatment or prevention (judged from labelling, explanations and advertising), and **J2**, how likely a malfunction is to harm life or health; one device function makes the whole program a device. Taiwan: 醫療器材管理法 Art. 3 defines a device by intended use (**T1**), and TFDA's 醫用軟體分類分級參考指引 separates 醫用軟體 from 醫療器材軟體 (**T2**: does the software analyse data to give information for diagnosis, treatment, mitigation or prevention for an individual patient). **T3** is the advertising rule under 醫療器材管理法 and 醫療法. Status: **built** (in code and tested), **partly**, or **planned** (with its work item).

| No. | Condition | Answers | Status | Needs a view? |
| --- | --- | --- | --- | --- |
| C1 | The statement of §1 is shown in the console footer, PDFs, XLSX and mail in the user's language | J1, T1, T3 | planned (WS-13.7; the holistic review found it absent from the console) | no |
| C2 | No output is used for an individual patient's care. Outputs go to research staff (steward, PI, sub-PI, CRC, monitor) inside a study, or to a treating physician only as a study's referral request | J1, T2 | built for screening, candidates and referral (D-146, D-147) | **[Consultant]** whether a referral request shown to a treating physician is "information for care" |
| C3 | TrialBox never decides eligibility. The investigator marks Approach; the candidate list and "criteria not matched" are inputs to that decision, each with the record passage it rests on | J1, T2 | built (D-143, D-147) | no |
| C4 | Unknown never excludes: a criterion the record cannot show sends the patient to "needs information", never to "criteria not matched"; a proposed (unconfirmed) fact never counts | J2 | built (D-120, D-135) | no |
| C5 | No alert, score, risk or forecast is shown as a clinical finding. Setpoints are numbers with a "check" mark; the forecast layer is not built | J1, J2, T2 | built for screening; profile layers planned behind flags (WS-05) | **[Consultant]** whether personal lab setpoints shown to a PI under "research use" are device functions |
| C6 | The gap finder is a study-screening rule. A treating physician sees it only inside a study referral, as numbers without a disease name, behind a switch that is off by default, until the written views of §4 exist | J1, T2 | planned (WS-05.6), switch off by default | **[Consultant]** the whole of C6 is the line the written views must confirm |
| C7 | Nothing writes to the EMR. Nothing reaches a patient: no message, list or portal | J1, J2, T1 | built (no EMR or patient channel exists) | no |
| C8 | EDC prefill drafts research-record values from the record with a citation each; a person confirms every value; nothing unconfirmed is sent. This is trial-data management (GCP, ER/ES), not diagnosis | J1, T1 | built (D-160) | **[Consultant]** confirm that drafting eCRF values from records is outside the device definition in both countries |
| C9 | The profile narrative is a cited summary for research staff; every sentence carries its source; the model abstains under 95 % cited sentences; no clinician sees a narrative before Study C passes | J1, J2, T2 | planned (WS-05.1, Study C) | **[Consultant]** whether a narrative summary shown to a PI is a device function |
| C10 | "Patients like me" is for research roles only and never shows outcomes of similar patients | J1, T2 | planned (WS-05.3) | no |
| C11 | No claim about accuracy, time or enrolment before Study A reports; never "finds undiagnosed patients", "detects disease", "AI diagnosis", 見逃し防止 | J1, T3 | policy (RSK-34); Study A protocol drafted (`docs/plan/study-a-protocol.md`) | **[Consultant]** review of the sales claims table before first use |
| C12 | The research-profile module keeps its own intended use and light IEC 62304-shaped records, so that it alone could take a device route later | J1 (whole-product rule) | partly (owner decision; records started) | **[Consultant]** whether a separate module is enough to keep the rest of TrialBox out under the whole-product rule |

## 4. What needs a regulatory consultant's view

Before any condition marked **[Consultant]** is relied on outside Aimedics, and before the clinician switch of C6 is turned on anywhere:

| Item | Japan | Taiwan | Who asks | When |
| --- | --- | --- | --- | --- |
| R1 | A written 該当性 view on TrialBox as a whole, with this statement, the conditions and screenshots of the live UI (not only the documents). The guideline points to a consultation with MHLW (監視指導・麻薬対策課) and PMDA's program-device consultations; the route and fee are to be confirmed by the consultant | A TFDA classification inquiry record on the same pack | owner, through the consultant | requests sent by the readiness review (WS-15.4) |
| R2 | The setpoint and gap layers for clinicians (C5, C6) | the same | as R1 | before the switch is ever on |
| R3 | EDC prefill (C8) as trial-data management | the same | as R1 | before go-live with prefill |
| R4 | The separate-module argument under the whole-product rule (C12) | the same | as R1 | with R1 |
| R5 | The claims table and the sales deck (C11) | advertising under 醫療器材管理法 and 醫療法 | as R1 | before any external material |

The consultant reads the statement against the live UI, not only against this document (TB-PLAN-05 §1.2).

## 5. What would change the position

Any of these makes TrialBox, or the module, a likely device in both countries and needs a new assessment first (TB-DS-16 §4): a diagnosis, stage or risk score for care; a treatment or dose suggestion; an alert to a clinician outside a study; findings from images or signals; writing to the EMR; showing lists to patients or contacting them; marketing it as finding disease; a forecast layer; the gap finder or setpoints shown to a clinician outside a study referral, or with a disease name.

## 6. Change history

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-09 | First draft: statement from TB-PLAN-05 §1.2 kept, ja and zh-TW extended; conditions C1 to C12 mapped to the Japan and Taiwan questions; consultant items R1 to R5 |
