# TB-DS-16 Regulatory Position (Non-Device) and Japanese Vendor Disclosure

| Field | Value |
| --- | --- |
| Document ID | TB-DS-16 |
| Title | Regulatory Position (non-device) and draft サービス仕様適合開示書 outline |
| Version | 0.1 |
| Date | 2026-11-07 |
| Owner | Product owner (Changfu Kuo) |
| Author | Claude (for Aimedics) |
| Status | Draft. Not legal advice. To be reviewed by regulatory counsel in Japan and Taiwan before it is given to a hospital or an authority. |
| Related | TB-DS-00, TB-DS-01 (NFR-COMP-*), TB-DS-03 §14 (regulatory analysis, from which this document is derived), TB-DS-11 §2, TB-TMPL-01 part I, TB-REV-006 findings M-13, M-14 |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner | Changfu Kuo | | |
| Regulatory counsel, Japan | (to be named) | | |
| Regulatory counsel, Taiwan | (to be named) | | |

## 1. Position in one paragraph

TrialBox is research-support software that helps hospital staff estimate how many patients may meet a clinical study's eligibility criteria and prepare candidate lists and research records for human review. It is not intended for the diagnosis, treatment, mitigation or prevention of disease in any patient, does not decide eligibility, does not recommend treatment and does not contact patients. Aimedics therefore considers TrialBox **not a medical device** in Japan (医薬品医療機器等法, program medical device criteria) or in Taiwan (醫療器材管理法). This position depends on the intended use and on the features listed in §4 staying out of the product.

## 2. Intended-use statement (to appear in labelling, user guides, the UI footer and sales material)

> **English.** TrialBox supports clinical research operations. It estimates the number of patients who may meet a research study's eligibility criteria and prepares lists of possible candidates and draft research records for review by qualified research staff. TrialBox does not diagnose, treat or prevent disease, does not determine whether a patient is eligible for a study, does not recommend treatment, and does not contact patients. All outputs must be reviewed by a qualified person.
>
> **日本語.** TrialBox は臨床研究業務を支援するソフトウェアです。研究の参加条件に合う可能性のある患者数を見積もり、研究担当者が確認するための候補者一覧や研究記録の下書きを作成します。疾病の診断・治療・予防を目的とするものではなく、研究参加の可否の判断、治療の推奨、患者への連絡は行いません。出力はすべて資格のある担当者が確認する必要があります。
>
> **繁體中文.** TrialBox 為支援臨床研究作業之軟體，用於估計可能符合研究收案條件之病人數，並產生候選名單及研究紀錄草稿，供合格研究人員審閱。本軟體不用於疾病之診斷、治療或預防，不判定病人是否符合研究資格，不提供治療建議，亦不聯繫病人。所有輸出皆須由合格人員審閱。

Wording elsewhere must not contradict this statement. Marketing claims such as "finds patients the doctor missed for treatment" or "AI diagnosis" are not allowed.

## 3. Japan

### 3.1 Criteria applied

The MHLW guideline 「プログラムの医療機器該当性に関するガイドライン」 (issued 2021-03-31, partially revised 2023-03-31; [MHLW PDF](https://www.mhlw.go.jp/content/11120000/001082227.pdf), checked 2026-11-07) asks two questions:

1. **Intended use:** is the program intended for the diagnosis, treatment or prevention of disease, or to affect the structure or function of the body? This is judged from the labelling, explanatory materials and advertising.
2. **Risk:** if the program malfunctioned, could it affect a person's life or health? Programs with almost negligible risk, equivalent to Class I general medical devices, are excluded.

If any one function of a product meets the definition, the whole product is regulated.

### 3.2 Assessment

| Question | TrialBox | Reasoning |
| --- | --- | --- |
| Intended for diagnosis, treatment or prevention? | No | It supports research operations: counting and listing candidates, drafting research records. No output is used for a patient's care. |
| Similar to listed non-device examples? | Partly | The guideline lists hospital administration programs (viewing records, scheduling) and patient-explanation programs as non-device examples. TrialBox's record viewing, scheduling-related views and the consent explainer resemble these. Clinical-trial support software is not listed explicitly, so this is a reasoned position, not a listed exemption. |
| Could a malfunction affect life or health? | Indirectly at most | A wrong list could delay a patient's chance to join a study (TB-DS-11 H-01) or, if misused, contribute to enrolling an ineligible patient (H-03). Eligibility is confirmed by the investigator under the study protocol and GCP, independently of TrialBox. |
| Used in a clinical trial as an investigational program? | No | TrialBox is not the subject of a trial. |

The guideline also notes that programs used in clinical research may fall outside the Act under a 2018 notice; TrialBox does not rely on that route because it is used for operations around many studies, not as part of one study's protocol.

### 3.3 Consultation option

For unclear cases the guideline points to consultation with MHLW's 監視指導・麻薬対策課 (program device status consultation, per a 2021 administrative notice), and PMDA offers consultations for program medical devices. Recommendation: before selling to pharma (TB-DS-03 §15.3), request a written device-status consultation, with this document and the intended-use statement as the basis. A consultation record strengthens the position for hospital procurement and sponsor audits. (Consultation route details and any fee to be confirmed with counsel; not verified here.)

## 4. Features that would cross the line

Adding any of these would likely make TrialBox (or the module) a program medical device in Japan and a medical device software in Taiwan, and requires a new regulatory assessment through change class C (TB-DS-12 §5):

| ID | Feature | Why |
| --- | --- | --- |
| XL-01 | Suggesting a diagnosis, disease stage or risk score for the patient's care | Diagnosis intent |
| XL-02 | Recommending treatment, dose or drug changes | Treatment intent |
| XL-03 | Alerts to clinicians about a patient's condition outside a research context (for example "possible sepsis") | Monitoring / diagnosis |
| XL-04 | Using imaging or physiological signals to derive findings | Diagnosis support from device data |
| XL-05 | Writing into the clinical EMR (not the research record) | Affects care records |
| XL-06 | Presenting lists to patients directly, or contacting patients | Patient-facing clinical use |
| XL-07 | Marketing as "AI that finds disease" or similar | Intended use is judged from advertising |

AE suggestions (M2) are research-record support for the investigator's GCP duties and stay inside the research context; their wording and placement must make this clear (TB-DS-11 H-06).

## 5. Taiwan

### 5.1 Criteria applied

Taiwan's 醫療器材管理法 (in force since 2021-05-01; [law text](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0030120), not re-read in this pass) defines medical devices by intended use for diagnosis, treatment, mitigation or prevention of disease, or affecting body structure or function, and includes software. TFDA describes medical device software as software that collects, stores, analyses or displays health status, physiological parameters or medical records **and** is classified as a medical device ([TFDA weekly no. 963, 2024-03-01](https://www.fda.gov.tw/Tc/PublishOtherEpaperContent.aspx?id=1498&tid=4657)). TFDA has issued a reference guideline on the classification of medical software (醫用軟體分類分級參考指引); the current version and date were **not verified** in this pass.

### 5.2 Assessment

The same reasoning as Japan applies: TrialBox processes medical records, but its intended use is research operations, not diagnosis, treatment or prevention, and it does not drive care decisions. Software that only manages or displays medical records for administrative or research purposes is generally treated as non-device. Recommendation: confirm with CGMH's research office whether CGMH requires a written TFDA classification inquiry for research-support software; if a pharma customer requires it, file one.

## 6. Other regimes checked

| Regime | Applies? | Note |
| --- | --- | --- |
| J-GCP / ICH E6(R3) | Indirectly | TrialBox is a computerised system used around trials. The validation approach (TB-DS-04, TB-DS-15) follows ICH E6(R3)'s risk-based expectations. TrialBox is not the trial's EDC (TB-DS-00 §2). |
| 21 CFR Part 11 / 電磁的記録指針 (ER/ES) | Not now | TrialBox stays outside the regulated record path; REDCap or the sponsor EDC holds regulated data. Re-assess if EDC-lite holds regulated trial data (report option D). |
| EU MDR | No (no EU deployment) | Re-assess before any EU use. |

## 7. Draft outline: サービス仕様適合開示書 and SLA (Japan)

Japanese hospitals expect vendors of systems handling medical information to disclose how their service meets the provider guideline. The current METI/MIC guideline is 「医療情報を取り扱う情報システム・サービスの提供事業者における安全管理ガイドライン」 **第2.0版, revised 2025-03-28** ([METI page](https://www.meti.go.jp/policy/mono_info_service/healthcare/teikyoujigyousyagl.html), checked 2026-11-07). Its 別紙1 provides a reference example (参考例) of the サービス仕様適合開示書 and SLA; it is a model, not a mandatory form. The outline below follows the usual structure; the final document must be written on 別紙1's template.

| Section | TrialBox content (source) |
| --- | --- |
| 1. 事業者情報 | Aimedics; responsible person; support contact; Japan maintenance team |
| 2. サービス概要 | On-prem appliance; functions; intended use (§2); no cloud processing of patient data |
| 3. 責任分界 | Hospital: network, server room, IdP, backups target, user accounts approval, export from HIS. Aimedics: software, signed updates, models, security fixes, support. Shared: incident response (TB-DS-03 §8.3). |
| 4. 情報の取扱い | Data classes D0–D4; pseudonymisation; PHI pass; what leaves the hospital (PI-released counts only) |
| 5. 技術的安全対策 | 2FA (TOTP), roles and study scopes, encryption at rest and in transit, audit chain, egress allowlist, no inbound access, signed updates, SBOM, vulnerability handling (critical 14 days, high 30 days) |
| 6. 運用・保守 | No remote access; diagnostics bundle without PHI; on-site visits; update windows agreed with hospital IT; rollback |
| 7. 障害・インシデント対応 | Contact routes, response times, notification to the hospital, support for the hospital's PPC and MHLW reporting |
| 8. 事業継続・バックアップ | Nightly encrypted backup to the hospital target; RPO 24 h; RTO 2 working days |
| 9. 委託・再委託 | No subcontractor processes patient data; third-party software listed in the SBOM |
| 10. 契約終了時 | Data return and deletion procedure; deletion certificate |
| 11. 医療情報安全管理ガイドライン第7.0版との対応 | Mapping table from TB-DS-03 controls to the MHLW guideline items |
| SLA | Support hours (working hours, Japan time), response targets per severity (TB-DS-04 §10.5), availability target 99 % in working hours (TB-DS-00 N-14), maintenance windows, reporting |

Taiwan (CGMH): CGMH's own vendor security annex is used instead; its content mirrors sections 3–10.

## 8. Open items

| ID | Item |
| --- | --- |
| RP-01 | Counsel review of the Japan position, including whether clinical-trial support software has any specific MHLW or PMDA guidance not found here. |
| RP-02 | Current title, version and date of the TFDA medical software classification reference guideline; whether CGMH needs a classification inquiry. |
| RP-03 | Consultation route and fee for a written MHLW/PMDA device-status opinion. |
| RP-04 | Write the サービス仕様適合開示書 on 別紙1's template and agree the SLA with the Japan head hospital. |

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 findings M-13 and M-14 and TB-DS-03 §14. MHLW device guideline and METI/MIC provider guideline versions checked against official pages. |
