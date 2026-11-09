# TrialBox and Anamnesis: commercial and regulatory assessment (Japan and Taiwan)

| Field | Value |
| --- | --- |
| Date | 2026-11-09 |
| For | Chang-Fu Kuo (CGMH Center for AI in Medicine; owner) and Aimedics |
| Scope | Commercial strategy, regulation, data protection, certification, procurement, business operations, validation evidence. Part 2 of the holistic review. Technical and clinical parts are separate. |
| Read | `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/VALIDATION.md`, `docs/DECISIONS.md`, `docs/plan/design/16-regulatory-position.md`, `docs/plan/design/14-ethics-pack.md`, `docs/plan/design/18-pilot-measurement-templates.md`, `docs/research/2026-10_literature_competitors.md`, `docs/reviews/2026-11-08-fable-standards-security-review.md`, `docs/reviews/2026-11-08-field-research-tw-jp-sites.md`, all `docs/reviews/2026-11-09-*` files, and the console code under `services/console/`. |
| Status | Record. Read-only review. No code changed. Not legal advice. |

**Marks.** `[V]` = checked on the web today (source in the appendix). `[R]` = taken from the repository's own research, which cites its sources; not re-checked today. `[U]` = unverified or inferred; treat as a working assumption until counsel or a vendor confirms.

---

## 0. One-page verdict

**The product.** TrialBox as it stands (feasibility, screening, lifecycle, REDCap sync, mail) is defensible as *non-device research-operations software* in both Japan and Taiwan. The position is written (TB-DS-16), reasoned, and consistent with the 2021/2023 Japanese 該当性 guideline and Taiwan's 醫用軟體 vs 醫療器材軟體 split `[V]`. It has not been reviewed by counsel, no written consultation exists, and the intended-use statement that TB-DS-16 says must appear "in the UI footer, PDFs, mail and sales material" is **not in the code**: the console footers say "a reading aid; the investigator decides", which is good, but the three-language statement and the 「本ソフトウェアは医療機器ではありません」/「本軟體非醫療器材」 line are nowhere in `services/` (checked by grep today).

**The platform.** The owner's 2026-11-09 decision to show **personal lab setpoints** and the **gap finder** to treating physicians about their own patients, labelled "research use, not for diagnosis", is the single largest regulatory risk in the plan. In both countries device status is judged from intended use *as presented to the user*, not from the label alone. A clinician who opens a patient and reads "possible undiagnosed IPF" or "CRP outside this patient's usual range" is receiving clinical decision support. The label helps; it does not settle the matter. The three layers that stay clean are record, timeline and eligibility; phenotype is borderline; forecast/risk (planned for Anamnesis) is a device in both countries without question.

**Commercially**, TrialBox's position is unusual and good: on-prem, no egress, two local models, ja and zh-TW notes, OMOP-native, and a hospital-owned data steward. No competitor in either market sells exactly this. The weaknesses are the ones every hospital buyer will probe first: no ISMS, no SBOM, no pentest report, no SLA, no incident-response plan, no support desk, no published accuracy on real ja or zh-TW charts, and no enrolment-uplift number. The buyer in both countries is the hospital IT department and the research office, not the CRC; the payer is more likely a sponsor-funded research budget than the hospital's own.

**Ten things to do before the first paid site** (details in §7): (1) put the intended-use statement and non-device line in the code and the PDFs; (2) get a written 該当性 view in Japan and a TFDA inquiry record in Taiwan *before* setpoints and gaps reach clinicians, not after; (3) write the 3省2 サービス仕様適合開示書 on the METI 別紙1 template with an SLA; (4) produce a CycloneDX SBOM in the release bundle and commission one external pentest; (5) start an ISO 27001 gap analysis and decide the certification date; (6) write the incident-response plan with the APPI 速報/確報 clocks and the Taiwan 72-hour subject-notice path; (7) run the retrospective accuracy study at CGMH and publish it; (8) write the DPA, the responsibility-boundary (責任分界) sheet, the consortium DSA and the IRB template pack as signable documents; (9) decide whether TrialBox's built-in forms are an eCRF of record (if yes, Part 11-style features and a QMS-lite become mandatory); (10) get the SNOMED quote (US$1,954 per hospital per data-processing system per year, Band A `[V]`) and a decision on who holds it.

---

## 1. Regulatory classification

### 1.1 The tests that apply

**Japan.** The 「プログラムの医療機器該当性に関するガイドライン」 (MHLW, 2021-03-31, partially amended 2023-03-31) asks two questions: is the program intended for diagnosis, treatment or prevention (judged from labelling, explanation and advertising), and could a malfunction affect life or health. No further revision has been published as of today; an MHLW-funded study group (FY2022–23) recommended more worked examples rather than new rules `[V]`. The guideline's non-device examples include hospital administration programs and patient-explanation programs. Trial pre-screening is not listed either way, so TrialBox's position is a reasoned one, not a listed exemption `[R]`.

**IDATEN** (変更計画確認手続制度, 2020) is a post-approval tool: a maker of an approved SaMD files a change plan once and later ships planned improvements by 軽微変更届 `[V]`. It matters to TrialBox only if a module becomes a device; it is then the right way to ship model updates without a new approval each time. **二段階承認** (two-stage approval for SaMD, MHLW notice 医薬機審発1116第2号, 2023-11-16; guidance 2nd edition 2024-06-05) lets a SaMD be approved first on performance and then on clinical benefit `[V]`. Both are relevant to Anamnesis's forecast layer, not to TrialBox today.

**Taiwan.** 醫療器材管理法 (in force 2021-05-01) defines a device by intended use. TFDA's 醫用軟體分類分級參考指引 (revised 2022-09-15 to follow the new Act) separates 醫用軟體 (any software handling health records) from 醫療器材軟體 (software meeting the Act's definition). TFDA's AI/ML SaMD technical guidance (2020/2021) governs registration of devices and explicitly says it does not decide scope `[V]`. Same two-question logic as Japan.

### 1.2 Feature by feature

| Feature | Who sees it | Japan | Taiwan | Verdict | What keeps it out, or what it would need |
| --- | --- | --- | --- | --- | --- |
| Feasibility counts (FEAS) | PI, CRC, sponsor (aggregate) | Not a device | Not a device | **Clean** | Counts only; no patient output; no model (D-101). |
| Screening (SCREEN, S0–S5) | PI, CRC | Not a device if the investigator decides and wording stays "criterion supported by note dated X" | Same | **Clean, conditional** | Keep: two-model rule, "unknown" bucket, no score, no clinical finding wording, no EMR write, no patient contact. Add the footer statement. |
| Lifecycle (consent, visits, AE/deviation logs, forms) | CRC, PI, monitor | Not a device; **but** J-GCP / ER-ES apply if these become the trial record | Not a device; GCP and 醫療法 apply likewise | **Clean for device law; open for GCP** | Decide eCRF-of-record question (§5.7). AE *grading* by a model would cross the line (XL-09). |
| REDCap sync, mail | CRC | Not a device | Not a device | Clean | PPAP zip mail is a policy misfit in Japan (F-review); replace with links. |
| Profile: cited record, timeline | Steward, PI, CRC, clinician (own patients), | Record viewing = listed non-device example | 醫用軟體, not 醫療器材 | **Clean** | Every sentence cited; no inference shown as fact. |
| Profile: phenotype (computed, ATLAS-style; later "latent subtype") | Same | Computed phenotype from codes = cohort definition, clean. "Latent subtype" from an embedding, shown to a clinician = classification of the patient's condition | Same | **Borderline** | Ship computed phenotypes only in v1. Keep latent subtypes PI/steward-only and research-framed. |
| Profile: eligibility | Same | Clean (research operations) | Clean | Clean | Per patient, with verbatim quotes. |
| **Personal lab setpoints** | Clinician sees them (owner decision) | Shown as "value outside this patient's usual range" to a treating physician = information about the patient's state used in care. The 2023 guideline judges by presentation. "Research use" label reduces but does not remove risk. | Same reasoning under 醫療器材管理法 Art. 3 | **On the line; clinician view tilts it toward device** | Options: (a) clinician role sees setpoints only inside a study context (candidate page of a study they are asked to refer to); (b) numbers only, no flag, no colour, no word "abnormal" (the owner already accepted "check mark, never an alert"); (c) written 該当性 view and TFDA inquiry before the clinician view goes live. Recommend a+b+c. |
| **Gap finder** ("suspected IPF, no code") | Clinician sees it (owner decision) | A suggestion of an undiagnosed condition to the treating physician is the textbook diagnosis-support case (XL-01, XL-03) | Same | **Device if shown to clinicians as a clinical suggestion** | Reframe for clinicians as a *referral request from a study*: "Study X's rule flagged this patient; the PI asks whether to introduce them." No disease name on the clinician's view unless the PI has already decided to approach. Keep the full gap view for PI and steward under IRB. Get the written view first. |
| Patients like me (vector neighbours) | PI, CRC, steward; clinician? | Cohort-by-example for research = clean. Shown to a clinician as "patients similar to yours and what happened to them" = treatment-decision support | Same | **Clean for research roles; device-like for clinicians** | Research roles only in v1. Never show outcomes of neighbours on a clinician page. |
| Forecast / risk layer (Anamnesis, later) | Any | Device (Class II or III SaMD) | Device (Class II+) | **Device** | Plan the device route from the start (§1.4). |
| Recontact driven by a model | PI/CRC | The 2018 clinical-research notice does not cover a multi-study tool `[R]`; APPI Art. 41 forbids using 仮名加工情報 to contact a person | Same, plus 人體研究法 consent rules | **Not a device question; a research-law question** | Recontact only inside an IRB protocol, with the treating physician's agreement (owner's referral design is right). |

**The whole-product rule.** In Japan, if one function meets the definition, the whole program is regulated (TB-DS-16 §3.1). Taiwan reads the same way in practice. So a clinician-facing gap finder could pull *all of TrialBox* into device status, not just the module. That is the strongest argument for keeping the two layers behind a flag and in a separable "research profile" module with its own intended use, so that a later device route covers that module alone.

### 1.3 Labelling and claims that keep it out

- Put TB-DS-16 §2 (en, ja, zh-TW) in: the console footer, every PDF and XLSX report, the N1/N2 mails, the sales deck, the website, the 開示書. Add 「本ソフトウェアは医療機器ではありません」 and 「本軟體非醫療器材，不作為診斷依據」. Today none of this is in code `[V, grep]`.
- Add a forbidden-word check to `tools/public_walk.js` (診断, 判定, 対象外, 見逃し, AIが判定, 診斷, 判定, 不符合, 建議治療, "diagnosis", "abnormal", "risk score"). The standards review proposed it; it is not built.
- On every profile layer, show "research use, not for diagnosis; no sentence here is a clinical finding" **and** record in the audit which role viewed which layer. The audit is the evidence that the clinician view was research-framed if a regulator asks.
- Marketing: never "finds undiagnosed patients", "AI finds disease", "見逃し防止". Allowed: "finds patients who may meet a study's criteria", "shows what the record says, with the quote".
- Sponsor materials: never present TrialBox outputs as source data unless the eCRF decision (§5.7) says so.

### 1.4 What a device route would cost and take (if a module crosses the line)

| | Japan | Taiwan |
| --- | --- | --- |
| Likely class for setpoint/gap decision support | Class II (管理医療機器) if a 認証基準 fits, otherwise Class II/III 承認 via PMDA. An AI finder suggesting a diagnosis without a certification standard is usually PMDA 承認, Class II or III `[U]`. | Class II (第二等級) 查驗登記 with TFDA; AI/ML technical guidance applies `[V]`. |
| Business licence | 第二種医療機器製造販売業許可 (5-year validity): 総括製造販売責任者, QMS 体制 (QMS省令, revised 2024-03-25 to align with ISO 13485), GVP 体制 `[V]`. | 醫療器材商 licence; QMS compliance under 醫療器材品質管理系統準則 (QSD) `[V]`. |
| Time | RCB certification 3–6 months for a Class II with a standard; PMDA approval 9–14 months (Class II/III); plus 6–12 months to build the QMS and the clinical evaluation. Realistic total from decision to market: 18–30 months `[U, consultancy figures]`. | 6–12 months for registration once QMS and evidence exist; total 12–24 months `[U]`. |
| Fees | Class II certification ¥0.5–1.5 M (consultancy figure); novel Class II/III PMDA submission ~¥13 M `[U]`. QMS build, 62304 documentation, clinical evaluation, RA staff: ¥20–50 M in the first year `[U]`. | TFDA 行政規費 schedule under revision (draft notice 2026-06-30) `[V]`; expect NT$0.1–0.3 M in fees and NT$5–15 M for QMS and evidence `[U]`. |
| Evidence | Clinical performance study against reference standard (chart review / adjudicated diagnosis), analytical validation, cybersecurity file (IEC 81001-5-1), usability (IEC 62366), risk file (ISO 14971), software file (IEC 62304). Two-stage approval possible for the forecast layer `[V]`. | Same standards set; TFDA AI/ML guidance asks for training/test data description, performance, change control `[V]`. |

Nothing here is needed while the product stays non-device. Everything here becomes mandatory the day the gap finder or a forecast is shown to a clinician as clinical information. The cheapest insurance is to design the research-profile module so that it *could* be carved out as a device later: own intended use, own version line, IEC 62304-style records kept from now (§5.7).

### 1.5 FDA/EMA Good AI Practice and the EU AI Act

- **FDA/EMA Guiding Principles of Good AI Practice in Drug Development** (joint, 2026-01-14): ten principles (human-centric, risk-based, GxP, clear context of use, multidisciplinary, data governance, model development practice, risk-based performance assessment, life-cycle management, plain-language information). Not binding guidance; a foundation for future guidance `[V]`. Effect on TrialBox: EU and US sponsors will ask sites what AI touched their recruitment and how it was validated. Prepare a two-page "context of use" note per the principles (TrialBox's context: pre-screening support, low regulatory impact; the investigator decides; outputs are not trial data). The NIST AI RMF crosswalk the standards review asked for can be the same document.
- **EU AI Act** (Reg. 2024/1689). The Digital Omnibus on AI, agreed 2026-05-07 and in force from August 2026, moves standalone Annex III high-risk obligations to 2027-12-02 and product-embedded (Annex I, e.g. MDR devices) to 2028-08-02 `[V]`. Trial-recruitment support is not an Annex III category. A hospital in Japan or Taiwan is not an EU deployer. An EU sponsor that receives aggregate counts has no AI Act duty from that. If a module ever becomes an MDR device in the EU, Annex I applies from 2028. **Conclusion: not applicable now; note it in TB-DS-16 and re-assess if Aimedics sells into the EU.**

---

## 2. Data protection and research law

### 2.1 Japan

| Instrument | Status today | What it asks of TrialBox | What Aimedics and the site must document |
| --- | --- | --- | --- |
| **APPI 個人情報保護法** | Current law in force; the 2026 amendment bill passed 2026-07-10, promulgated 2026-07-17, staged entry into force within two years (by July 2028). It adds a consent exemption for statistics and AI development, a surcharge (課徴金) system, child-data rules and biometric rules `[V]`. The exact text on 仮名加工情報 and medical data was not checked today `[U]`. | Medical history is 要配慮個人情報. Within one hospital, the hospital is the controller; TrialBox processes under its instruction. Pseudonymised data (仮名加工情報) may be used for research inside the handler but **not to contact the person** (Art. 41). Leak reports to the PPC: 速報 3–5 days, 確報 30/60 days. Security measures (安全管理措置) and a vendor contract with supervision (委託先の監督). | Site: legal category of the hospital (private, 国立大学法人 = 規律移行法人, administrative organ) decides which chapter applies; counsel letter per site. Aimedics: DPA with 委託 terms, a sub-processor list (none, by design), an incident plan with the APPI clocks, a record of processing. The 2026 statistics/AI exemption may make consortium *counts* easier; it does not legalise identified pre-screening. |
| **次世代医療基盤法** | 仮名加工医療情報 route in force since April 2024; first certified 利用事業者 (RIKEN) 2025-02-28; 152 cooperating providers as of 2025-02 `[V]`. | Applies only when data goes to a 認定作成事業者. One hospital's own pre-screening under its IRB is outside it. A consortium that *pools identified or pseudonymised records centrally* would need this route or consent. | Keep the consortium federated (counts and de-identified exports only). Write one paragraph in the DSA saying why the Act does not apply. If CGMH-equivalent Japanese sites later want a central store, this Act is the route. |
| **3省2ガイドライン** | MHLW 安全管理ガイドライン 第7.0版 (June 2026) and METI/MIC 提供事業者 guideline 第2.0版 (2025-03-28) `[R, V]`. | GL7.0: two-factor authentication for systems newly introduced or renewed and running from FY2027; lockout; immutable/offline backup; SBOM; 責任分界; remote-maintenance rules. Provider GL 2.0: サービス仕様適合開示書 and SLA on the 別紙1 template; risk assessment; subcontractor coverage `[V]`. | Aimedics: the 開示書 and SLA (§3), a written ISMS (not yet certified), the 責任分界 sheet, remote-maintenance rules (TrialBox has none; updates are offline, which is good). TOTP is not built; it must be. |
| **生命・医学系指針** | 2023-07-01 edition in force. A revision was approved by the joint committee on 2026-06-02 after a public comment (2025-12-26 to 2026-01-25); promulgation and effective date not confirmed today `[V, U on promulgation]`. The stated aims: simplify the text and strengthen single central review for multi-site studies. | Research on existing records by **opt-out** with notice and ethics review; records of provision; the 2023 edition allowed creating 仮名加工情報 from the institution's own data under opt-out. | Site: the ethics protocol listing TrialBox as the tool, the opt-out notice (TB-TMPL-01 exists in ja), and the FR-STUDY-06 gate in code (refuse SCREEN without an approval record; design only today). Track the 2026 revision; central review will favour a consortium protocol. |
| **J-GCP and ER/ES** | GCP省令 amendment for ICH E6(R3) published as a draft in August 2026, planned promulgation late September 2026 and **effect April 2027**; promulgation not confirmed today `[V, U]`. | If TrialBox's screening log, consent record or CRF rows become trial records: ALCOA+, audit trail, e-signature, validation by risk. Otherwise TrialBox is a worklist and REDCap/EDC is the record. | The eCRF-of-record decision (§5.7). If "worklist", say so on the page and in the 開示書. If "record", build e-signature manifestation, re-authentication, record lock, reason for change. |
| **臨床研究法** (amended 2025-05-31) | In force `[R]`. | Applies to specified clinical research (特定臨床研究); TrialBox is a tool, not the research. | Nothing in code. Mention in the ethics pack. |

### 2.2 Taiwan

| Instrument | Status today | What it asks of TrialBox | What Aimedics and the site must document |
| --- | --- | --- | --- |
| **PDPA 個人資料保護法** | Amendment promulgated 2025-11-11; **effective date still to be set by the Executive Yuan** as of today; it creates the Personal Data Protection Commission (個資會) as single regulator, adds 個資長 duties for public agencies, and penalties for failing to notify breaches or to maintain security plans `[V]`. The 個資會 standing-up date was not confirmed today `[U]`. | Medical records are special data (Art. 6): processing needs a legal basis. Research use without consent only for data that **cannot identify** the person after processing (Art. 6(1)(4)). Identified pre-screening therefore rests on the hospital's care relationship plus IRB approval, not on the research exception. Art. 27 security plan; the 醫院個人資料檔案安全維護計畫實施辦法 applies to hospitals `[V]`. Breach notice to subjects (draft rules: 72 h) `[R]`. Cross-border transfer (Art. 21): the competent ministry may restrict it; no MOHW general order on medical data was found today `[V]`. | Site: counsel letter on the basis for identified pre-screening; IRB approval naming TrialBox; its security plan updated to include the box. Aimedics: DPA under PDPA, incident plan with the 72-hour subject-notice path, data-in-Taiwan statement (the box is on site; nothing leaves). For the consortium: every export is domestic in v1; any export to Japan is an Art. 21 international transfer and needs the DSA to address it, plus 人體研究法 Art. 19(3) approval (below). |
| **人體研究法** | In force (last amended 2019-01-02) `[V]`. | IRB approval before research; consent or a waiver under the MOHW 2012 announcement (得免取得研究對象同意之人體研究案件範圍: minimal-risk research where consent is impracticable and rights are not harmed; de-linked data) `[V]`. **Art. 19(3): providing research material abroad requires IRB approval and MOHW approval**; penalty NT$100k–1M `[V]`. Non-de-linked data destroyed after the study. | Site: IRB protocol per study (identified pre-screening) and one umbrella protocol for the repository and profiles (owner question 37 in the standalone review). Consortium: a Japan-Taiwan exchange of de-identified profiles is "research material abroad" and needs MOHW approval; counts likely do not (counsel). Build the "destroy at study end" path for study-level marks and lists. |
| **人體生物資料庫管理條例** | In force (amended 2021-01-20); an amendment to widen the definition to genomic and imaging data was sent to the Executive Yuan in April 2026 `[V]`. Export of biobank specimens abroad is banned; data export is risk-tiered and limited to listed countries `[V]`. | Applies only if the source is a biobank (the Anamnesis biological layer). Not to TrialBox v1. | When the biological layer arrives: biobank IRB, the 2026 amendment's wider scope, no export of genomic data to Japan without MOHW approval. |
| **GCP 藥品優良臨床試驗作業準則** and 人體試驗管理辦法 | In force; TFDA tracks ICH E6(R3) but no amendment draft was found today `[V, U]`. | The IRB approves the recruitment method, EMR search included. Source-document rules if TrialBox holds trial facts. | Same eCRF decision as Japan. The IRB submission must describe TrialBox's screen as the recruitment method. |
| **醫療法 and 醫療機構電子病歷製作及管理辦法** (2022-07-18) | In force `[V]`. | The hospital's EMR rules flow down to a vendor that reads EMR exports: written contract, encrypted transmission, data stored in Taiwan unless MOHW approves, incident handling, media disposal. | Aimedics: the outsourcing contract clauses the 辦法 requires; a decommission and media-sanitisation procedure (NIST 800-88 purge, certificate); data-in-Taiwan statement. |
| **資通安全管理法** | Amendment passed 2025-08-29, promulgated 2025-09-24, **effective date pending**; MODA becomes competent authority; penalties up to NT$10 M for unreported incidents at designated non-government agencies `[V]`. Hospitals were among the 60 CI hospitals designated in 2019; MOHW is adding security to hospital accreditation, four regional 醫院資安韌性中心 by end-2025, audits of 12 hospitals in 2025 `[V]`. | If CGMH is a designated 特定非公務機關, vendor duties flow down: adequate security management or third-party certification, audit cooperation, incident support within the hospital's 1-hour reporting clock `[R]`. | Aimedics: ISO 27001 gap analysis now, certification planned; the box's incident hooks (who the hospital calls, what logs they get in the first hour). |
| **Constitutional Court 111年憲判字第13號 (2022)** | In force `[R]`. | NHI-sourced data needs an independent oversight mechanism and an opt-out right. | Any NHI-derived feed into TrialBox (claims, TWPAS) needs the opt-out registry at S0 to cover it. Already designed; document it. |

### 2.3 What TrialBox must document, both countries (one list)

1. **Record of processing** per site: data classes D0–D4, tables, retention, who reads what, where it sits (on the box only).
2. **DPIA / PIA** per site (TB-DS-03 §11 has the frame); add the profile, the vector store and the clinician role, which are new and are the most identifying parts.
3. **Legal-basis memo** per site, signed by counsel: pre-screening with re-identification (care relationship + IRB), profiles (same umbrella IRB, owner's option 37a), consortium exports (de-identified; what standard of de-identification; 匿名加工情報 or PDPA "cannot identify").
4. **IRB pack**: protocol text, data-flow figure, opt-out notice in ja/zh-TW, FAQ, screening-log column definitions (TB-TMPL-01 and TB-DS-14 exist; adapt to a named committee).
5. **Incident-response plan** with the APPI (3–5 d / 30–60 d), Taiwan PDPA (72 h to subjects, draft), 資安法 (1 h for designated agencies) and GL7.0 clocks; roles on both sides; what the audit chain gives the hospital in the first hour.
6. **Access log retention** of 10 years for profile views (owner decision) and the EMR 辦法's "full access log for the retention period".
7. **De-identification standard** for the consortium export: k=5 on quasi-identifier combinations, ±180-day shift, no free text, no vectors, rare concepts generalised; a per-release manifest; a first-export dual review (owner accepted).
8. **Data-destruction procedure** for study-level identified lists at study end (人體研究法) and for decommissioned boxes (EMR 辦法).

---

## 3. Certifications and procurement

### 3.1 What hospitals ask a vendor for

| Item | Japan | Taiwan | TrialBox today | Gap and action |
| --- | --- | --- | --- | --- |
| ISO/IEC 27001 (ISMS) | Asked by nearly every 医療情報部; often a bid condition (ISMS or Pマーク) `[U]`; GL7.0 asks hospitals to assess vendors | Hospital accreditation has included ISO 27001 as an indicator since 2019 `[V]`; 資安法 asks designated agencies' vendors for "adequate management or third-party certification" `[V]` | Aimedics has no ISMS | Gap analysis in the next quarter; certify within 12–18 months. Until then, a written ISMS statement mapped to 27002 themes (TB-DS-03 Annex A.2 exists). |
| ISO/IEC 27701 (PIMS) | Rarely asked | Rarely asked | None | Not needed for the pilot; useful when the consortium handles exports at scale. |
| ISO 27799 | Sometimes asked | Rarely | None | Cite it in the 開示書 control mapping; no certificate exists for it. |
| **サービス仕様適合開示書 + SLA** (METI 別紙1) | Expected from any vendor handling 医療情報 `[V]` | n/a (but a Chinese SLA is expected by 資訊室) | Outline only (TB-DS-16 §7) | Write on the 別紙1 template; attach the control mapping; translate the SLA into zh-TW. |
| Taiwan 資安 rules for medical institutions | n/a | CISO, incident reporting, vendor security clauses, SSDLC checklist and vulnerability scan before go-live, vendor USB scanned and logged, vendor security staff and third-party testing above NT$10 M contracts `[R]` | Offline signed updates (good); no vuln scan report; no SSDLC evidence pack | Run CIS Docker/Ubuntu benchmarks and an OWASP ASVS 5.0 self-assessment; produce the SSDLC evidence pack from CI (tests, SAST, dependency scan). |
| **SBOM** | GL7.0 names supply-chain/SBOM measures `[R]` | Expected in SSDLC checklists | **None** (`grep` finds no CycloneDX or SBOM in `tools/`, `deploy/`) | Emit CycloneDX for every image and the Python lock in `make_bundle`; include model file hashes (the serving record already has them). |
| **Penetration test report** | Asked before go-live at most 400+ bed hospitals `[U]` | Required by SSDLC checklists before go-live `[R]` | None | One external pentest of the console, gateway and update path on the real appliance (Linux tier first). Budget ¥2–4 M / NT$0.5–1 M `[U]`. |
| Device security sheet (持込機器) | NCC-style form: OS, patches, antivirus, ports, no internet, no USB, update path, key custody `[R]` | Equivalent 資訊室 form | Network sheet exists in en/ja/zh-TW (`docs/handover/`) | Extend to the full device form. |
| Validation evidence (CSV, GAMP 5) | Sponsors and 治験事務局 ask when records touch trials | Same | TB-DS-04, TB-DS-15 designs; no executed IQ/OQ/PQ | Execute at the pilot; keep the traceability matrix true. |
| Licence and notices | Required in any contract | Required | LGPL list known (8 packages), notices not shipped as a file `[R]` | Ship `NOTICES` with every bundle; counsel on the vLLM/CUDA image redistribution. |

### 3.2 Hospital procurement and timelines

**Japan.**
- National university and NHO hospitals buy HIS by 一般競争入札 with 総合評価, 5–7 year leases `[V]`. A research tool like TrialBox is usually not bought that way: it comes in as (a) a 治験事務局 or 臨床研究支援センター budget item, (b) a 講座 research grant purchase, or (c) sponsor-funded 治験 indirect cost `[U]`. Above the government-procurement threshold (roughly ¥15 M for goods/services at national bodies `[U]`) a public tender is unavoidable; keep the first-year contract under it where lawful.
- Installation approval by the 医療情報部: device registration form, security software, network segment; 2–6 weeks is a reasonable planning figure `[R]`. The whole cycle from first meeting to a running pilot at a university hospital: 6–12 months `[U]`.
- Private hospital groups (Tokushukai, IMS) decide faster and centrally `[U]`.

**Taiwan.**
- CGMH is a 財團法人 (private non-profit) and is **not** bound by the 政府採購法; it buys on its own rules. Public hospitals (NTUH, the Veterans General Hospitals, 三總, municipal hospitals) are bound: the 公告金額 is NT$1.5 M since 2023-01-01 (open tender above it; three written quotes above NT$150k), 查核金額 NT$10 M for services, tender periods 14/21/28 days by tier `[V]`. A first paid site at a public hospital will go to open tender unless priced under NT$1.5 M or run as a research-project purchase.
- The 資訊室 gate is a vulnerability scan and security review before go-live; weeks, not days `[R]`.
- The **台灣臨床試驗中心聯盟** (32 hospitals, formed 2025-12-08, led by TMU and Taichung VGH) is a channel: one-stop services and shared ethics review are its stated aims `[V]`. A consortium offer to the alliance could replace 32 separate sales cycles.

### 3.3 What Aimedics needs ready (the vendor pack)

1. Company documents: registration, insurance certificate (§5.5), ISMS statement, organisation chart with a named security officer and a named 個人情報保護管理者 / 個資保護人員.
2. Product documents: intended-use statement (3 languages), non-device position (TB-DS-16, counsel-reviewed), 開示書 + SLA, device security sheet, network sheet, SBOM, release notes, update procedure, backup and restore procedure, decommission procedure.
3. Evidence: pentest report and remediation letter, ASVS self-assessment, CIS benchmark output, test summary (1,405 unit tests, e2e, walk), serving record, model cards, validation plan (TB-DS-04) and executed IQ/OQ.
4. Legal: DPA, 責任分界 sheet, licence notices, third-party data licences (SNOMED, MEDIS, LOINC acceptance), model licences (Gemma 4 and Qwen3.5 are Apache 2.0 per secondary sources; **read the licence file on the exact checkpoints and keep a copy** `[V, U on the exact checkpoints]`).
5. Clinical: ethics pack (TB-DS-14), screening-log columns, validation study protocol and, as soon as possible, the published retrospective study.

---

## 4. Commercial model

### 4.1 Who pays

| Payer | Japan | Taiwan | Fit for TrialBox |
| --- | --- | --- | --- |
| Hospital (own budget) | Weak. Hospital margins are thin; IT budgets go to the HIS vendor. Core hospitals (臨床研究中核病院, about 15 `[U]`) have research-support budgets. | Weak to medium. Medical centres have research budgets; CGMH is large and self-building. | Pays for the appliance and the platform licence when research output is a strategic goal; needs a champion (the research office head). |
| Sponsor / CRO | Strong. Sponsors already pay sites per-case and per-study fees; feasibility and start-up speed are what they buy. Multinationals skip Japan and Taiwan for slow recruitment `[R]`. | Strong. IRPMA: 372 drug trials in 2024, below Japan (392) and Korea (510); multinationals treat Taiwan as a back-up country `[V]`. | Pays per study or per enrolled patient through the site budget; wants aggregate feasibility packs and enrolment reports; cannot see patient data (CRO monitor SDV only). |
| SMO (Japan) | Medium. SMO CRCs are the majority of CRCs; SMOs sell efficiency to sponsors `[R]`. | n/a (SMO model is small in Taiwan) | An SMO could license TrialBox for the hospitals it serves; account model must fit SMO staff (study-scoped, expiring). |
| Government / consortium | AMED and MHLW fund 中核病院 networks; MOHW funds the 32-hospital alliance and AI impact centres `[V]`. | Same | Grant-funded consortium deployments; the registry and federated counts are grant-shaped deliverables. |

**Recommendation.** A hospital-licensed platform, paid for mostly with sponsor money: the hospital signs the licence (data stays its own), and recovers the cost through per-study activation fees that sponsors pay in the site budget. In Taiwan, start with CGMH as the development partner (no procurement act) and the alliance as the channel. In Japan, start with one 中核病院 through a research grant, and one SMO as the second channel.

### 4.2 Pricing models

| Model | Pro | Con | Where it fits |
| --- | --- | --- | --- |
| Per site, annual platform licence (tiered by GPU tier or bed count) | Simple; predictable; matches the appliance | Hospital must find budget | Base layer. Illustrative: Japan ¥3–8 M/year, Taiwan NT$1.5–4 M/year, hardware extra (RTX PRO 6000 box ~US$12–15k) `[U]`. |
| Per study activation | Sponsor-fundable; scales with use | Admin overhead; IIT studies need a free or cheap tier | Add-on. Illustrative: ¥300–600k or NT$80–150k per sponsor study; free for IITs under a cap `[U]`. |
| Per enrolled patient | Aligns with sponsor value | Perverse incentive; ethics committees dislike per-head payments to a tool vendor; attribution is hard | Avoid as a vendor fee. Use only as a success metric. |
| Platform licence plus services (mapping, training, validation study) | Recovers the real cost (site mapping, code maps, SS-MIX2 quality work) | Services do not scale | Needed in year 1 at every site; price mapping as a fixed-fee project. |
| Consortium fee (registry hosting, map releases, cross-site counts) | Funds the shared infrastructure; grant-shaped | Needs ≥ 3 sites to be worth it | Year 2+. |
| Sponsor data-network subscription (TriNetX model: sites free, sponsors pay for aggregate queries) | Proven model; sites join for free `[V]` | Needs many sites and a central query broker; TrialBox's "no central store" design makes the broker a signed-file exchange | Long-term option for the consortium, not for v1. |

### 4.3 Competitive landscape

| Player | What | Model | Presence in JP/TW | Relevance to TrialBox |
| --- | --- | --- | --- | --- |
| **TriNetX** | Federated network; aggregate counts; NL query beta (2026) `[R]` | Free to HCOs; pharma and CROs pay subscriptions `[V]` | Japan: some members; Taiwan: none found `[R]` | The reference model for the consortium. Does not do note-level screening or lifecycle. |
| **Tempus / Deep 6 AI** | EMR screening; JIT trial activation; 750+ US sites; acquired by Tempus 2025-03-11 `[V]` | Sponsor pays | None | Shows the sponsor-pays model and the "partial match, missing one lab" feature. US-only, cloud. |
| **Inato** | Marketplace plus AI pre-screening; 6,000+ sites by April 2026 `[V]` | Free to sites; sponsor pays | Not found in JP/TW `[V]` | Community-site model; no on-prem. |
| **Paradigm Health** | Matching, feasibility, study conduct; FDA collaboration 2026 `[R]` | Sponsor pays | A Japan oncology collaboration (LC-SCRUM) `[R]` | Network-tied; cloud. |
| **Mendel** | LLM + knowledge graph abstraction `[R]` | Enterprise | None | Modest standalone accuracy; shows the human-plus-AI number sponsors expect. |
| **Clinerion (Citeline/Norstella)** | Patient Network Explorer; hospital-side feasibility and real-time search; acquired 2022/23 `[V]` | Sponsor pays; hospitals get free software | Historically Europe, Turkey, LatAm, some Asia; no JP/TW evidence found `[V]` | The closest "hospital node" model to TrialBox's. Not on-prem LLM. |
| **Japan: NTT / NTT Data / Kindai / Chugai** | LLM (tsuzumi 2) vs rule-based candidate extraction on Kindai's EMR, June 2026 to March 2027 `[V]` | Research; NTT Data markets a 治験候補者選定支援サービス (webinar Oct 2026) `[V]` | Japan | The most direct Japanese competitor-to-be; EHR-vendor-neutral; Japanese model. |
| **Japan: Fujitsu / Nagoya / Gifu** | Structuring plus matching; 27 of 42 flagged confirmed (64 % PPV), time cut by about two-thirds `[R]` | Fujitsu HIS customers | Japan | Sets the published PPV bar on Japanese charts. HIS-tied. |
| **Japan: NEC / Tohoku University** | LLM extraction of endometrial-cancer trial candidates, 2025 `[V]` | Pilot | Japan | HIS-vendor route. |
| **Japan: MDV** | 57.56 M-patient EMR database; feasibility and site selection; delisted April 2026 `[R]` | Sponsor pays | Japan | Feasibility competitor at the sponsor level; no site screening. |
| **Japan: Ubie / Osaka University, Buzzreach, MICIN** | Document AI and recruitment infrastructure `[R]` | Various | Japan | Adjacent. |
| **Taiwan** | No commercial EMR-screening product found. Medical centres build in-house (NTUH LLM coding assistant; CGMH–ASUS AI inference cloud; MOHW AI impact centres at five centres) `[V]`. Academic work only (Tamkang, NTU) `[R]`. | n/a | Taiwan | The field is open. The risk is in-house builds at the big centres and a MOHW-led platform. |
| **China** (Yidu Tech, Taimei) | Regional recruitment systems; agent suites `[R]` | Enterprise | Not in JP/TW | Relevant as a non-PRC-model argument for Japanese and Taiwanese buyers. |

### 4.4 Differentiation, sales cycle, evidence buyers will want

**Differentiation that holds up.**
1. On-prem, no egress, two local open-weight models, hospital-owned steward: the only answer to the closed hospital network and the APPI/PDPA special-data rules that does not need a cloud contract.
2. ja and zh-TW notes, mixed-script Taiwanese notes, SS-MIX2 and CGRD readers: no global vendor has these.
3. Fail-closed design: two-model agreement to exclude, "unknown" bucket, canary gate, byte-identical re-runs, quote verification. This is what Japanese pilots concluded they need ("the doctor or CRC makes the final judgement") `[R]`.
4. OMOP-native repository with a shared concept-map registry: makes the consortium real and makes the product portable to OHDSI network studies later.
5. Whole trial lifecycle on the same box (screening log, consent, visits, AE, REDCap sync): removes double entry, the second-ranked pain `[R]`.

**Differentiation that does not yet exist.** Published accuracy, enrolment uplift, a reference site, certifications, a support organisation.

**Sales cycle.** Expect 9–15 months from first meeting to a paid site in Japan (champion, IRB, 医療情報部, procurement, install), 6–12 months at CGMH, 9–15 months at a Taiwanese public hospital with a tender `[U]`. The consortium shortens this only after the first two sites run.

**Evidence buyers will ask for, in order.**
1. A retrospective accuracy study on real ja and zh-TW charts, against CRC/PI chart review, with PPV, wrong-exclusion rate and abstention rate per criterion type. The bar: PPV ≥ 0.75 (above Fujitsu's 0.64) and wrong exclusions ≤ 2 %.
2. CRC time per candidate before and after (time-motion, not self-report). The bar: ≥ 50 % less.
3. A prospective enrolment comparison. The reference: Unlu et al., JAMA 2025 (RECTIFIER), 4,476 patients randomised, 35 vs 19 enrolled, 458 vs 284 screened-eligible `[V]`.
4. Profile sentence-citation fidelity and a clinician review of narratives.
5. Security evidence (pentest, SBOM, ISMS).
6. A reference site that will take a call.

---

## 5. Business-operations components lacking

### 5.1 Support and SLA
- No support desk, hours, channels, ticket system or escalation path are defined. Japanese sites expect a Japanese-speaking first line in JST business hours and a named 保守 contact; the GL7.0 保守委託機関編 asks the hospital to contract this `[R]`. Taiwanese sites expect zh-TW support and on-site response for hardware.
- No SLA: uptime, response and resolution times by severity, maintenance windows (night jobs run 02:00–07:30; the SLA must protect them), update cadence, end-of-support dates for each tier.
- No remote-maintenance policy. TrialBox has no remote access by design, which is a selling point; say so, and define how diagnostics travel (the audit export and `doctor` output, hashed, by the hospital's mail).
- Action: write the SLA as the 別紙1 SLA section; stand up a ticket system; name a support lead per country; define a hardware RMA path (the GPU is the single point of failure).

### 5.2 Incident response
- No written plan. Needed: severity scale; roles on both sides; the clocks (APPI 3–5 d/30–60 d; Taiwan PDPA 72 h to subjects, draft; 資安法 1 h for designated agencies; GL7.0 reporting); what the box gives the hospital in the first hour (audit chain slice, access log, `secrets status`); communications templates in ja/zh-TW; post-incident review. Also a vulnerability-handling and disclosure policy (IEC 81001-5-1 asks for it).

### 5.3 Release management
- Signed offline updates exist; missing: anti-rollback, key id and expiry in the manifest (F-15), a release calendar, release notes in three languages, a change-class policy (TB-DS-12 has classes A/B/C on paper), a model-update policy (new weights = class C; re-run the canary and N-11/N-12 gates and publish the numbers), end-of-life policy per tier, and a customer-visible changelog.

### 5.4 Training, certification, documentation
- Roles to train: CRC, PI, data steward, administrator, IT. The steward role is new and heavy (code maps, conflicts, exports, break-glass second person); it needs a certification course and a competency record, because the steward is the hospital's accountable person under APPI/PDPA.
- Documentation exists in en with ja/zh-TW UI strings and the network sheet in three languages; the user guide, runbook, security and validation documents are English only. Hospitals will not accept English-only runbooks or security sheets. Needed in ja and zh-TW: user guide per role (one page each; the field research says manuals are not read, so make them one-pagers plus in-product help), the security sheet, the 開示書/SLA, the IRB pack (opt-out notices exist), the release notes.
- Japanese CRC training reaches people through SMO head offices and the annual CRC meeting; Taiwan through hospital CRC courses `[R]`. Plan a train-the-trainer kit for SMOs and the alliance.

### 5.5 Contracts, liability, insurance
Templates that do not exist and are needed for the first contract:
- **Master licence and services agreement** (per country law), with the intended-use statement and the non-device clause, a "no clinical decision" clause, and the hospital's duty to keep IRB approval current.
- **DPA / 委託契約** (APPI 委託; PDPA Art. 27 and the EMR 辦法's required clauses): purposes, instructions, security measures, sub-processors (none), audit rights, breach notice, return/destruction, data stays on site. The "BAA-like" term is this document; there is no HIPAA equivalent in either country.
- **責任分界 sheet** (GL7.0 / provider GL 2.0): who owns the host, the OS patches, the TPM keys, the backups, the network rules, the model files, the user accounts.
- **IRB templates** (exist in draft: TB-DS-14); need a named-committee version per site and a consortium umbrella protocol.
- **Consortium data-sharing agreement**: parties, governance (terminology steward, release approval), export standard (owner's defaults; contracts may only tighten), international-transfer clauses (PDPA Art. 21; 人體研究法 Art. 19(3) MOHW approval for material abroad; APPI third-party provision rules for 匿名加工情報), IP in code maps (open licence recommended), publication rules, liability caps, exit.
- **Sponsor-facing terms**: what a feasibility pack is and is not; no patient-level data; small-cell rules.
- **Liability**: cap at fees paid; exclude clinical decisions; the investigator decides. Buy professional indemnity / E&O and cyber insurance in both countries before the first real-data pilot; hospitals ask for the certificate `[U]`. Product-liability cover becomes relevant only if a module becomes a device.
- **Third-party data licences**: SNOMED CT affiliate licence for non-member territories: **US$1,954 per hospital/institution per Data Processing System per year in Band A** (Japan and Taiwan are high-income); practices US$652; web applications need special permission `[V]`. Decide who holds it (vendor with sub-licensing, or each hospital). MEDIS-DC masters (病名, HOT, JLAC10): download is open but commercial redistribution terms must be read on medis.or.jp; not verified today `[U]`. LOINC: free with account and terms `[R]`. jRCT: public-data terms; bulk or automated collection needs help-desk permission; no API `[V]`. ClinicalTrials.gov: public domain.
- **Model weights**: Gemma 4 family released under Apache 2.0 (April 2026), a change from the old Gemma terms; Qwen3.5 open weights reported as Apache 2.0 (February 2026); both from secondary sources `[V]`. Keep the licence file of the exact checkpoint, keep the quantisation recipe (derivative work), keep attribution in `NOTICES`, and watch trademark use ("built on Gemma" is fine; no Google branding). bge-m3 is MIT `[R]`. Add a model-origin manifest (the competitor research notes Japanese buyers may ask for a non-PRC-model tier) `[R]`.
- **Open-source compliance**: ship licence texts and notices for the eight LGPL packages, the JRE (GPL+CPE), Groonga; counsel on redistributing the vLLM/CUDA image on physical media `[R]`.

### 5.6 Quality management system, ISO 13485, IEC 62304
- **While non-device**: no ISO 13485 and no IEC 62304 obligation. What *is* needed for sponsors and GCP: a QMS-lite (document control, change control, release records, training records, supplier assessment, CAPA), which is what a GAMP 5 supplier audit looks for `[R]`. Start it now; it is cheap and it is the seed of a 13485 system.
- **If any module becomes a device**: Japan's QMS省令 (ISO 13485-based, revised 2024-03-25) and Taiwan's 醫療器材品質管理系統準則 become mandatory for the 製造販売業者 / 醫療器材商 `[V]`; IEC 62304 software-lifecycle records, ISO 14971 risk file (TB-DS-11 already borrows the structure), IEC 62366 usability and IEC 81001-5-1 security files are expected by both regulators. Reconstructing 62304 records after the fact is expensive; keeping lightweight ones now (software requirements, architecture, SOUP list = the SBOM, verification records = the test gates, problem resolution = the issue tracker) costs little.
- **Recommendation**: adopt "62304-shaped" documentation for the research-profile module from its first commit, and scope the QMS-lite so that it can be upgraded to 13485 in 6–9 months if the device decision comes.

### 5.7 The eCRF-of-record decision (blocks several items above)
The plan puts consent, enrolment, visits, AEs, deviations and CRF rows in TrialBox's own Postgres. If a site treats them as source or CRF, J-GCP/ER-ES, Taiwan GCP and sponsor Part 11 expectations apply: e-signature manifestation, re-authentication on sign, record lock, reason for change, validated system. Options: (a) **worklist only** — REDCap/EDC stays the record; the page says so; cheapest; (b) **eCRF of record for IITs only** — build the Part 11-style features, run the TB-DS-15 validation; (c) **full eCRF**. Recommend (a) for the pilot and the first paid site, (b) in year 2 if IIT demand is real. Whatever is chosen must be written into TB-DS-16, the 開示書 and the SDV page.

---

## 6. Validation evidence needed before marketing claims

No marketing claim about accuracy, time saved or enrolment is allowed in either country without the study behind it (Japan: 景品表示法 and the 該当性 advertising test; Taiwan: 公平交易法 and 醫療法 advertising rules `[U]`). The studies, in the order to run them:

### 6.1 Study A: retrospective accuracy against chart review (first; needed for any claim)
- **Site**: CGMH first (zh-TW and mixed-script notes), one Japanese site second (ja, SS-MIX2).
- **Design**: 3–5 completed or running studies with known enrolment. Run TrialBox on a frozen snapshot dated at each study's screening period. Reference standard: independent two-CRC chart review of a stratified sample with PI adjudication of disagreements; CRCs blind to TrialBox output.
- **Primary endpoints**: (1) patient-level PPV of the "ready" list (target ≥ 0.75, lower 95 % CI > 0.65); (2) wrong-exclusion rate among patients TrialBox excluded on notes (target ≤ 2 %, upper 95 % CI ≤ 5 %); (3) criterion-level sensitivity and specificity by criterion type (structured, lab, note-only) with abstention rate.
- **Secondary**: recall of actually enrolled patients (how many enrolled patients TrialBox would have listed), N-11/N-12 style counts, agreement between judge and verifier, time per chart for the CRC with and without the quote card.
- **Sample size**: PPV — 100 "ready" candidates per study gives a 95 % CI half-width of about ±0.085 at p = 0.75; 3 studies = 300 adjudicated candidates. Wrong exclusions — review 300 note-excluded patients per site; with ≤ 3 wrong exclusions the upper 95 % CI is about 2.9 % (rule of three gives 1 % upper bound at 0 events). Criterion level — all criteria of the sampled patients, about 20 per patient, so ≈ 6,000 criterion judgements; inter-rater kappa reported.
- **IRB route**: retrospective, minimal risk, consent waiver under the MOHW 2012 announcement in Taiwan (chart review by the study teams who already have access) and opt-out under the 生命・医学系指針 in Japan; the hospital's chart-use application. Pre-register the analysis plan (OSF or a registry), report with STARD-style completeness.
- **Cost and time**: 4–6 months; CRC hours ≈ 600 at each site `[U]`.

### 6.2 Study B: prospective enrolment and screening efficiency
- **Design**: patient-level randomisation inside each participating study, as in Unlu et al. (JAMA 2025): each new patient in the study's catchment is randomly assigned to manual CRC pre-screening or TrialBox-assisted pre-screening; the investigator's final decision is unchanged in both arms. Alternative where randomisation is impractical: stepped-wedge across 4–6 studies over 12 months.
- **Primary endpoint**: screened-eligible patients per CRC-hour (the JAMA study's 458 vs 284 is the reference). **Key secondary**: enrolments per month (35 vs 19 in the reference), time from flag to consent, CRC minutes per candidate (time-motion sheets in TB-DS-18), screen-failure rate, patient and physician refusal reasons.
- **Sample size**: for enrolments as a Poisson rate with rate ratio 1.8, 80 % power, α = 0.05, about 35 control-arm enrolments and 63 TrialBox-arm enrolments are needed (≈ 100 enrolments pooled across studies). A single study will not reach that; pool 4–6 studies over 12 months or accept the efficiency endpoint as primary (needs about 1,500 randomised patients per arm for a 1.6× rate ratio on screened-eligible `[U, approximate]`).
- **IRB route**: prospective, minimal-risk operational study; waiver of patient consent for the randomised pre-screening step (the patient's trial participation still needs full consent); register the study (jRCT in Japan; ClinicalTrials.gov or the Taiwan registry) `[U on waiver acceptance; counsel]`.
- **Cost and time**: 12–18 months.

### 6.3 Study C: profile narrative fidelity (before any clinician sees a narrative)
- **Design**: 200 profiles (stratified by specialty template), every sentence checked by a clinician against the cited item: supported, unsupported, missing citation, misleading. Also a hallucination red-team set (patients with conflicting records).
- **Endpoints**: sentence-level support ≥ 98 %; unsupported clinical statements = 0 tolerated in the release gate (each is a bug); abstention rate; clinician usefulness (SUS, 5-point).
- **Sample**: 200 profiles × ~30 sentences = 6,000 sentences; at 98 % support the 95 % CI half-width is about ±0.35 %.
- **IRB**: under the repository umbrella protocol; clinician reviewers are study staff.

### 6.4 Study D: gap rules and setpoints (before clinician exposure, in the screening frame)
- **Gap rule precision**: the owner's 7-of-10 switch-on gate has a 95 % interval of about 35–93 %. Add: 100 confirmed hits per rule before any clinician view (±9 %), a rolling check every 50 hits (keep ≥ 70 %), and a negative-control rule set. Report per rule, per site.
- **Setpoints**: analytical validation only in v1 (the method reproduces published personal-setpoint statistics; unit normalisation errors = 0 on a test set). No clinical outcome claim.

### 6.5 Study E: security and operations evidence
- External pentest; backup/restore drill on the real appliance; update/rollback drill on Docker on the hospital platform; 50,000-patient run through the production gateway (gate G1). Not research, but buyers will weigh it like research.

### 6.6 Claims allowed after each study
| After | Claim allowed |
| --- | --- |
| A | "In a retrospective study at [site], TrialBox's candidate list had a PPV of X % and missed Y % of enrolled patients; wrong exclusions on notes were Z %." |
| A + time-motion | "CRC time per candidate fell from X to Y minutes." |
| B | "In a randomised comparison, TrialBox-assisted screening identified X × more eligible patients per CRC-hour; enrolments were X vs Y." |
| C | "Profiles are cited sentence by sentence; in review, X % of sentences were supported by the cited record." |
| None, ever, while non-device | "Finds undiagnosed patients", "detects disease", "improves outcomes", "AI diagnosis". |

---

## 7. Missing components and actions, prioritised

### P0: before the first real-data pilot (CGMH)

| # | Action | Owner | Why |
| --- | --- | --- | --- |
| P0-1 | Put the three-language intended-use statement and non-device line in the console footer, every report, every mail; add the forbidden-word check to the walk. | Aimedics eng | Today it exists only in a document; device status is judged from presentation. |
| P0-2 | Counsel review of TB-DS-16 in Taiwan (and Japan when a Japanese site is named). | Owner | The position is reasoned, not confirmed. |
| P0-3 | Keep setpoints, gap finder and "patients like me" behind a flag, off for the clinician role, until P1-2. Phenotype: computed only. | Owner / eng | The clinician view is the one decision that can make the whole product a device. |
| P0-4 | Legal-basis memo and IRB protocol at CGMH: pre-screening per study plus an umbrella protocol for the repository and profiles; opt-out notice; FR-STUDY-06 gate in code. | Owner, CGMH IRB, eng | 人體研究法, PDPA Art. 6; the gate is design only today. |
| P0-5 | DPA / outsourcing contract with CGMH under the EMR 辦法 and PDPA; 責任分界 sheet; decommission procedure. | Aimedics + counsel | Required clauses; CGMH IT will ask. |
| P0-6 | Incident-response plan with the clocks; one tabletop exercise with CGMH IT. | Aimedics | 資安法, PDPA; CI hospital status. |
| P0-7 | SBOM in the bundle; licence notices file; model-licence copies for the exact checkpoints. | Eng | SSDLC checklist; LGPL obligations. |
| P0-8 | QMS-lite: document control, change classes, release records, training records, issue tracker as problem-resolution log. | Aimedics | Sponsor audits; seed for 13485. |
| P0-9 | Validation Study A protocol written, pre-registered, IRB-submitted at CGMH; chart-review team booked. | Owner | Nothing can be claimed without it. |
| P0-10 | Insurance (E&O, cyber) quotes; decide and bind before real data. | Aimedics | Hospitals ask; a leak without cover is fatal to the company. |
| P0-11 | SNOMED quote requested (US$1,954/hospital/system/year, Band A) and MEDIS terms read; decide holder. | Owner | Blocks the OMOP standard-concept design and the consortium. |
| P0-12 | Support model for the pilot: named contact, hours, ticket channel, hardware RMA. | Aimedics | A pilot with no support path fails on the first GPU fault. |

### P1: before the first paid site

| # | Action | Why |
| --- | --- | --- |
| P1-1 | 開示書 + SLA on the METI 別紙1 template (ja) and a zh-TW SLA; device security sheet in ja/zh-TW. | Every Japanese hospital and 資訊室 asks. |
| P1-2 | Written 該当性 consultation (MHLW 監視指導・麻薬対策課 / PMDA) and a TFDA inquiry record, with the research-profile module described, before setpoints and gaps reach any clinician. | A written view protects the sites and Aimedics; the owner's decision needs it. |
| P1-3 | External pentest and remediation; ASVS 5.0 self-assessment; CIS benchmarks; TOTP/WebAuthn and AD/LDAP in the product (GL7.0 two factors from FY2027). | Go-live gates in both countries. |
| P1-4 | ISO 27001 gap analysis complete; certification scheduled; interim ISMS statement. | Bid condition; 資安法 vendor duty. |
| P1-5 | Study A published (preprint acceptable; journal submitted); time-motion numbers from the pilot. | The first real sales claim. |
| P1-6 | eCRF-of-record decision written into TB-DS-16 and the SDV page; if "record", build the Part 11-style features and execute TB-DS-15. | GCP exposure. |
| P1-7 | Contract set: master licence (JP, TW), DPA (JP 委託, TW), sponsor terms, IRB pack per named committee, steward certification course. | Deal paperwork. |
| P1-8 | Documentation in ja and zh-TW: one-page role guides, security sheet, release notes, runbook for IT. | Hospitals do not accept English-only. |
| P1-9 | Pricing sheet and a sponsor-funding playbook (how a site charges a per-study activation fee in its budget). | The buyer needs to know how to pay. |
| P1-10 | Release management: anti-rollback and key expiry in the manifest; model-update policy with re-run gates; EOL per tier. | Update safety; sponsors ask about change control. |
| P1-11 | GAIP/NIST AI RMF "context of use" note (2 pages) for sponsors. | EU/US sponsor audits. |

### P2: for scale (consortium, Japan, Anamnesis)

| # | Action | Why |
| --- | --- | --- |
| P2-1 | Consortium DSA with international-transfer clauses (PDPA Art. 21, 人體研究法 Art. 19(3) MOHW approval, APPI 匿名加工情報 rules); terminology-steward governance; registry hosted at CGMH with Aimedics releases. | Cross-border profiles are the hardest legal object in the plan. |
| P2-2 | ISO 27001 certified; consider 27701 when exports scale. | Scale procurement. |
| P2-3 | Study B (prospective) across 4–6 studies; publish. | The enrolment claim. |
| P2-4 | Device-route readiness file for the research-profile module: 62304-shaped records, 14971 file, 81001-5-1 file, clinical-evaluation plan, two-stage approval and IDATEN plan in Japan; TFDA AI/ML dossier outline. | The forecast layer is a device; starting late costs a year. |
| P2-5 | Japan entry: one 中核病院 via grant, one SMO channel; SS-MIX2 field validation; MEDIS licences per site; Japanese support desk. | Japan is the larger market and the harder install. |
| P2-6 | Sponsor-facing aggregate network (TriNetX-style) over the signed-file exchange, once ≥ 3 sites run. | The revenue line that does not depend on hospital budgets. |
| P2-7 | 13485 decision point: upgrade the QMS-lite if any module goes the device route. | Mandatory then. |
| P2-8 | Re-assess the EU AI Act and MDR if Aimedics sells to EU sponsors as a deployer or into the EU. | Dates: 2027-12-02 (Annex III), 2028-08-02 (Annex I). |

### 7.4 Owner questions (each with options and a recommendation)

| # | Question | Options | Recommendation and reason |
| --- | --- | --- | --- |
| Q1 | Clinician view of setpoints and gaps in v1? | (a) as decided: shown, labelled research use; (b) shown only inside a study referral context, numbers only, no disease name until the PI approaches; (c) PI and steward only until a written regulatory view. | **(b) now, (a) only after the written view (P1-2).** The label alone does not decide device status; presentation does. (b) keeps the owner's "clinicians from the start" for record, timeline and eligibility, and keeps the two risky layers inside the research frame. |
| Q2 | Device route for the research-profile module: prepare now or wait? | (a) prepare 62304-shaped records now; (b) wait for the forecast layer; (c) never go the device route (stay research-only forever). | **(a).** Cheap now, expensive later; the forecast layer is a device without question and is on the Anamnesis roadmap. |
| Q3 | Who pays for the first paid site? | (a) hospital licence; (b) sponsor per-study fees through the site budget; (c) grant. | **(a) with (b) recovering it; (c) for Japan's first site.** Hospitals need a path to recover the cost; sponsors have the money and the motive. |
| Q4 | Pricing structure? | (a) per site only; (b) per site + per study; (c) per enrolled patient. | **(b).** (c) is unethical-looking and unattributable. |
| Q5 | eCRF of record? | (a) worklist only; (b) record for IITs; (c) full eCRF. | **(a) for pilot and first paid site; (b) in year 2 if demand.** Each step up adds Part 11-style work and a validated-system burden. |
| Q6 | SNOMED licence holder? | (a) Aimedics as vendor with sub-licences; (b) each hospital; (c) consortium lead. | **(a) for the product; (c) if the consortium buys for OHDSI network studies.** Get the quote first; v1 screening does not need SNOMED. |
| Q7 | ISO 27001: when? | (a) certify before the first paid site; (b) gap analysis now, certify within 18 months; (c) only when pharma pays. | **(b).** Certification takes 9–12 months; a gap analysis plus statement satisfies most pilots; 資安法 vendor duties push toward (a) for CI hospitals. |
| Q8 | Pentest scope and timing? | (a) before the pilot on the Linux tier; (b) before the first paid site; (c) per site. | **(a) once, (b) repeat annually.** |
| Q9 | Consortium legal shape? | (a) bilateral DSAs per pair of hospitals; (b) one multilateral DSA with a lead; (c) a legal entity (association) holding the registry. | **(b) now, (c) when ≥ 5 sites.** Cross-border (JP–TW) exchange of de-identified profiles needs MOHW approval under 人體研究法 Art. 19(3) and APPI third-party rules; one agreement is easier to approve than many. |
| Q10 | Model origin policy? | (a) Gemma 4 + Qwen3.5 everywhere; (b) offer a non-PRC-model tier for Japanese sites that ask; (c) Japanese-origin models only in Japan. | **(a) default, (b) as an option.** A second pair needs its own validation; only build it when a buyer requires it in writing. |
| Q11 | Where does the first Japanese site come from? | (a) a 中核病院 via AMED/MHLW grant; (b) an SMO; (c) a private hospital group. | **(a) with (b) as channel.** Core hospitals have research-support staff, SS-MIX2 and IRB capacity; the SMO brings the CRCs. |
| Q12 | Marketing claims policy? | (a) claims only after Study A; (b) vendor-style "up to X %" claims now; (c) no numbers until Study B. | **(a).** Both countries' advertising and device rules judge intended use from marketing; a number without a study is a liability. |

---

## Appendix A. Verified sources (read 2026-11-09)

**Japan regulation**
- PMDA 新旧対照表 of the 該当性 guideline (2021-03-31, amended 2023-03-31): https://www.pmda.go.jp/files/000252068.pdf ; MHLW-funded study on revising the guideline (FY2022–23): https://mhlw-grants.niph.go.jp/system/files/report_pdf/202324012B-sougou.pdf
- IDATEN (変更計画確認手続制度) PMDA/MHLW materials: https://www.pmda.go.jp/files/000282725.pdf ; https://www.mhlw.go.jp/content/11124500/001152089.pdf
- 二段階承認 notice and guidance: https://www.mhlw.go.jp/content/11121000/001279254.pdf ; https://www.pmda.go.jp/files/000269365.pdf
- QMS省令 / 製造販売業 requirements (prefectural guides): https://www.pref.kyoto.jp/yakumu/documents/3qmstaisei.pdf ; https://www.pref.kagawa.lg.jp/documents/7310/r6koshukaisiryou3.pdf
- APPI 2026 amendment (passed 2026-07-10): https://keiyaku-watch.jp/media/hourei/202807-kojinjohohogohou-kaisei/ ; https://www.pwc.com/jp/ja/knowledge/column/awareness-cyber-security/amended-act-on-the-protection-of-personal-information.html
- 生命・医学系指針 2026 revision process: https://www.mext.go.jp/content/20260722-mxt_life_000051165-1.pdf ; 2023 opt-out changes: https://www.mhlw.go.jp/content/10808000/001053257.pdf
- 次世代医療基盤法 仮名加工医療情報: https://www8.cao.go.jp/iryou/kameikakou_kaigi/pdf/report.pdf ; RIKEN first certified user: https://www.riken.jp/pr/news/2025/20250228_1/index.html
- METI 2省ガイドライン 別紙1 (開示書 and SLA reference): https://www.meti.go.jp/policy/mono_info_service/healthcare/02besshi_20250328.docx ; https://www.soumu.go.jp/main_content/000703895.pdf
- GCP省令 amendment for E6(R3), effect planned April 2027: https://www.yakuji.co.jp/?p=137602
- 治験計画届 counts FY2025 (221 initial): https://www.pmda.go.jp/files/000281024.pdf
- jRCT terms (bulk collection needs permission; no API): https://jrct.mhlw.go.jp/agreement
- MEDIS-DC masters (terms not verified): https://square.umin.ac.jp/helics/files/event_20210610/5_MEDIS-DC.pdf

**Taiwan regulation**
- TFDA 醫用軟體分類分級參考指引 index: https://www.fda.gov.tw/tc/siteListContent.aspx?id=34961 ; AI/ML SaMD technical guidance (mirror): https://wd.vghtpe.gov.tw/DMC/files/人工智慧機器學習技術之醫療器材軟體查驗登記技術指引.pdf
- 醫療器材行政規費 draft amendment 2026-06-30: https://www.fda.gov.tw/Tc/newsContent.aspx?cid=3&id=31589
- PDPA amendment 2025-11-11, effective date pending: https://www.leeandli.com/TW/NewslettersDetail/7532.htm ; https://law.lia-roc.org.tw/Law/Content?lsid=fl010627
- PDPA Art. 21 international transfer: https://laws.gov.taipei/Law/Interpretation/RelatedLaw/FE257140 ; 醫院個人資料檔案安全維護計畫實施辦法: https://mohw.gov.tw/dl-62279-5e79fcde-66d2-4254-a973-fc8105b96166.html
- 人體研究法 (Art. 19(3) material abroad; Art. 22 penalties): https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020176 ; MOHW 2012 consent-waiver announcement (as cited by institutions): https://ord.nccu.edu.tw/files/archive/383_9cbeb258.pdf
- 人體生物資料庫管理條例 and export rules: https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=L0020164 ; https://www.mohw.gov.tw/cp-2704-25612-1.html ; 2026 amendment sent to Executive Yuan: https://wantrich.chinatimes.com/news/20260428901223-420501
- 醫療機構電子病歷製作及管理辦法 2022: https://www.ithome.com.tw/news/148275 ; https://lawdata.com.tw/tw/detail.aspx?no=527868
- 資通安全管理法 amendment (passed 2025-08-29, promulgated 2025-09-24, effective date pending): https://www.leeandli.com/TW/NewslettersDetail/7505.htm ; https://newtalk.tw/news/view/2025-08-29/990704 ; MOHW–MODA hospital security measures 2025-08-15: https://mohw.gov.tw/cp-16-83515-1.html ; https://www.ithome.com.tw/news/171883
- 政府採購法 thresholds (公告金額 NT$1.5 M from 2023-01-01): https://purchase.taichung.gov.tw/media/1432323/115年7月3日採購程序補充講義.pdf
- Taiwan trial counts (IRPMA 2024: 372) and the 32-hospital alliance (2025-12-08): https://udn.com/news/story/7266/9404568 ; https://health.tvbs.com.tw/medical/359520
- MOHW AI impact research centres at five medical centres: https://mohw.gov.tw/cp-101-84517-1.html

**International**
- FDA/EMA Guiding Principles of Good AI Practice (2026-01-14): https://www.nsf.org/life-science-regulatory-news/fda-and-ema-release-guiding-principles-of-good-ai-practice-in-drug-development ; https://www.jdsupra.com/legalnews/fda-and-ema-provide-guiding-principles-1493754/
- EU AI Act Digital Omnibus (agreement 2026-05-07; in force August 2026; Annex III to 2027-12-02; Annex I to 2028-08-02): https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/ ; https://www.mondaq.com/eu-digital-omnibus-on-ai-enters-into-force/1825722
- SNOMED International licensing fees (Band A hospital US$1,954 per Data Processing System per year): https://www.snomed.org/licensing
- Gemma 4 Apache 2.0 (secondary): https://www.theregister.com/2026/04/02/googles_gemma_4_open_weights/ ; Qwen3.5 Apache 2.0 (secondary): https://www.nxcode.io/resources/news/qwen-3-5-developer-guide-api-visual-agents-2026
- Unlu et al., JAMA 2025, RECTIFIER RCT (4,476 randomised; 35 vs 19 enrolled; 458 vs 284 screened-eligible): https://www.massgeneralbrigham.org/en/about/newsroom/press-releases/ai-screening-for-clinical-trial-speeds-up-enrollment ; https://www.fiercebiotech.com/medtech/study-shows-generative-ai-can-speed-clinical-trial-enrollment-pennies-patient
- TriNetX model (free to HCOs; sponsors pay): https://pmc.ncbi.nlm.nih.gov/articles/PMC6816049 ; https://www.carilionclinic.org/path-file/1125
- Tempus acquires Deep 6 AI (2025-03-11): https://www.genomeweb.com/cancer/tempus-ai-acquires-clinical-trial-patient-matching-firm-deep-6-ai
- Inato network size (secondary): https://builtincharlotte.com/company/inato/faq/stability-growth
- Clinerion / Citeline: https://www.samedanltd.com/press-releases/clinerion-is-part-of-citeline-a-norstella-company/
- NTT / NTT Data / Kindai / Chugai study (June 2026–March 2027): https://www.nttdata.com/jp/ja/trends/event/archive/2026/027 ; https://digitalpr.jp/r/137869 ; NEC / Tohoku University 2025: https://nk.jiho.jp/article/197232 ; Osaka University feasibility study: https://www.hosp.med.osaka-u.ac.jp/research/files/202606.pdf

## Appendix B. Repository evidence used
- `docs/plan/design/16-regulatory-position.md` (TB-DS-16): intended-use statement and XL-01..07; not reviewed by counsel.
- `docs/reviews/2026-11-08-fable-standards-security-review.md`: gap matrix M1–M12, S1–S8, O1–O6; SaMD §3 with XL-08..10.
- `docs/reviews/2026-11-09-standalone-db-vector-profiling-review.md` §4.5–4.6, §7 Q36–38: profile regulation and access design.
- `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`: the clinician-view decision, consortium export defaults, SNOMED question.
- `docs/reviews/2026-11-09-component-review-layer2-verification.md` §3: licence findings (8 LGPL packages; model licences; SNOMED US$1,954).
- `docs/reviews/2026-11-08-field-research-tw-jp-sites.md`: hospital IT reality, procurement friction, pain ranking, Fujitsu 64 % PPV.
- `docs/research/2026-10_literature_competitors.md`: competitor table and Asia section.
- `services/console/i18n*.py`: footers say "a reading aid; the investigator decides"; no intended-use statement or non-device line (grep 2026-11-09).
- `tools/`, `deploy/`: no SBOM generation (grep 2026-11-09).
