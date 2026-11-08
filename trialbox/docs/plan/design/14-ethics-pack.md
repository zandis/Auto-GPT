# TB-TMPL-01 Ethics Committee Submission Pack

| Field | Value |
| --- | --- |
| Document ID | TB-TMPL-01 |
| Title | Ethics Committee Submission Pack (outline and templates) |
| Version | 0.4 (reference; hospital stage only) |
| Date | 2026-11-07 |
| Owner | Product owner (Changfu Kuo); each site PI owns the submitted version |
| Author | Claude (for Aimedics) |
| Status | **Hospital stage only (H).** Not needed while TrialBox is built on synthetic data (`SIMPLE-PLAN.md`). Start with the two-page description in §0; the rest is an appendix for a committee that asks for more. Draft template. Not legal advice. Each hospital's ethics office and privacy office must review and adapt it. |
| Related | TB-DS-00 (BD-04, BD-06, BD-15, BD-16, N-01, N-07, N-16, N-17), TB-TMPL-07 (baseline self-log, screening-log columns), TB-DS-03 (DPIA), TB-DS-04 §8 (pilot validation protocol), TB-DS-11, TB-PLAN-01 (MS-04, MS-11), TB-REV-006 findings F-07, M-08 |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner | Changfu Kuo | | |
| Site PI, Japan head hospital | (to be named) | | |
| Site PI, CGMH | (to be named) | | |
| Privacy office, Japan head hospital (review) | (to be named) | | |
| Privacy office, CGMH (review) | (to be named) | | |

## 0. Two-page description of TrialBox for a PI (TB-REV-006f F6-28)

Use this when a hospital wants to run TrialBox on its own records. In Japan and Taiwan the ethics committee reviews the **study**, not the software; the PI adds a short paragraph about TrialBox to the study's recruitment procedure if the committee asks (see §2 for ready text).

**What TrialBox is.** Software installed on one server inside the hospital network. It helps a study team (1) count how many patients may meet a study's criteria and (2) list patients who may fit, for the team to review. It is a tool like Excel or REDCap. It does not diagnose, treat, decide eligibility or contact patients.

**What data it reads.** A nightly copy of existing hospital records the hospital chooses: demographics, diagnoses, prescriptions, lab results, appointments and clinical notes. On entry each patient's identity is replaced by a code; names and chart numbers are kept separately, encrypted, on the same server.

**Where it runs.** Only on the hospital's server. Language models run on that server's own graphics card. Nothing is sent outside the hospital.

**How it decides nothing.** Structured criteria (age, diagnosis codes, lab values) are checked by fixed rules. Criteria found only in notes are read by local models; a single model never removes a patient, and anything uncertain goes to the investigator.

**Who sees what.** Counts: the study team; outside the hospital only counts of 10 or more. Lists: codes, not names. A chart number: only an authorised investigator or coordinator of that study, one patient at a time, with a reason, recorded. Mail carries codes only.

**Who approaches the patient.** The treating physician, or a study investigator after the treating physician has agreed (主治医の了承 / 主治醫師同意), as the approved protocol states.

**What the PI adds to the study paperwork.** One paragraph (§2) describing the tool, if the committee asks. The hospital's IT approves the server as internal software. A patient opt-out notice (§4) is posted where the study uses opt-out.

**Records kept.** The screening log and audit records for the study's retention period (at least 5 years); data copies for a short time (days for nightly copies, months for month-end copies).

## 1. What the pack contains

| Part | Content | Japan (生命・医学系指針) | Taiwan (CGMH IRB, 人體研究法 / 個人資料保護法) |
| --- | --- | --- | --- |
| A | Cover letter and summary (one page) | ✓ | ✓ |
| B | Protocol section "Use of TrialBox" (§2) | ✓ | ✓ |
| C | Data-flow figure and data-class table (§3) | ✓ | ✓ |
| D | Privacy impact summary (from TB-DS-03 DPIA) | ✓ | ✓ |
| E | Opt-out notice for feasibility on existing information (§4) | ✓ (情報公開文書) | ✓ (公告) |
| F | Pilot validation protocol: two phases and blinded chart review (§5) | ✓ | ✓ |
| F2 | Workload baseline (2-week staff self-log, one observed clinic half-day; TB-TMPL-07); staff observation agreed by the department head | ✓ | ✓ |
| G | Consent explainer approval process (§6) | ✓ | ✓ |
| H | Security summary (data stays in the hospital; no remote access; 2FA; audit) | ✓ | ✓ |
| I | Non-device statement (TB-DS-16 §2) | ✓ | ✓ |
| J | Contact and complaints information | ✓ | ✓ |

The pack is submitted by the site PI as a new research plan (or an amendment, if a recruitment study already covers it). It covers two activities, which committees may wish to review separately:

1. **Feasibility and pre-screening research** on existing medical information, without new consent, under the opt-out route (Japan: 生命・医学系指針, use of existing information with notice and opt-out; Taiwan: as decided by CGMH IRB, possibly via exempt or expedited review for de-identified aggregate counts). Outputs are counts and pseudonymised candidate lists used inside the hospital.
2. **The pilot validation study**: measuring TrialBox's recall against blinded manual chart review in Phase 1 (parallel), and staff time in Phase 2 (TrialBox-first with a spot-check), which the committee approves explicitly at the week-6 checkpoint (§5).
3. **Identified pre-screening for each study** (flow B, candidate lists that can be resolved to chart numbers) runs only after the committee has approved it for that study, **whatever the study type**: trials, registries and observational studies, including opt-out registries that list new cohort members; TrialBox enforces this from the study's approval record (FR-STUDY-06, TB-DS-00 BD-20).

The site's committee may conclude that activity 1 is a hospital operational activity rather than research. The pack is written so it works either way.

## 2. Protocol section: use of TrialBox (template text)

> **2.x Use of a pre-screening support system (TrialBox)**
>
> The study team will use TrialBox, a software system installed on a server inside [hospital name]'s network, to support (a) estimating how many patients at this hospital may meet the eligibility criteria of a planned study, and (b) preparing lists of patients who may be eligible, for review by the study team.
>
> **What the system does.** TrialBox copies a defined set of existing medical information from the hospital's information system each night: demographics, diagnoses, prescriptions, laboratory results, appointments and clinical notes. On entry, each patient's identity is replaced by a code (a keyed pseudonym); names and chart numbers are kept separately in encrypted form on the same server. Structured criteria (for example age, diagnosis codes, laboratory values) are checked by fixed rules. Criteria that can only be read from notes are read by language models running on the server itself. No data is sent to any external service.
>
> **What the system does not do.** TrialBox does not decide eligibility. It does not contact patients. It does not diagnose or recommend treatment. A model on its own never removes a patient from consideration; when a model judges that a patient does not meet a criterion, the patient is sent to the investigator for review.
>
> **Who sees what.** Counts are available to the study team and, after release by the PI, to the sponsor; counts below 10 are suppressed in anything leaving the hospital. Lists of candidates show codes, not names. Only authorised investigators and coordinators of this study can see a chart number, one patient at a time, after giving a reason; every such view is recorded. A candidate is approached by their treating physician, or by a study investigator after the treating physician has agreed (主治医の了承 / 主治醫師同意), as this protocol's recruitment procedure states [choose one]. TrialBox never contacts a patient.
>
> **Data retention.** The copies used by TrialBox are kept for [N] days (nightly copies) and [N] months (month-end copies). The screening log and audit records are kept for [the study's GCP retention period, at least 5 years]. At the end of the study the study's data in TrialBox is deleted or archived according to the hospital's rules.
>
> **Validation.** The pilot has two phases. In Phase 1 (weeks 1–6) the study team continues its usual screening; TrialBox lists may add candidates, who are approached only after the investigator has checked suitability from the chart. TrialBox's results are compared with a blinded manual review of [100] patients (section [y]). Phase 2 (weeks 7–12) starts only if the week-6 recall check passes and the committee approves it: the team pre-screens from the TrialBox list, and a random 20 % of each clinic list is still screened manually. At no time is anyone excluded by TrialBox output; a patient is not approached only by the investigator's decision.
>
> **No research procedure before consent.** TrialBox never prompts a test or assessment for research purposes before consent. Where data needed for eligibility is missing, the list says it "would need checking after consent"; tests done in routine care follow normal clinical practice.

## 3. Data-flow figure and data classes

Figure (to be drawn for the submission from TB-DS-02 §7):

```
[Hospital information system] --nightly export (hospital network)--> [TrialBox server, inside the hospital]
     identified data (D4)                                                 ├─ identity vault (names, chart numbers; encrypted)  D4
                                                                          ├─ pseudonymised clinical data and notes            D3
                                                                          ├─ free-text PHI pass → scrubbed notes              D3
                                                                          └─ outputs: suppressed counts (D1), candidate lists (D3)
[Study team, hospital web browser] <── lists with codes; chart number on audited request
[Sponsor] <── counts only, released by the PI, small cells suppressed (D1)
Nothing leaves the hospital except PI-released counts.
```

Data classes (TB-DS-00 BD-02; the same table as TB-DS-03 §2.1 and TB-DS-07 §2.1, enforced in code by `libs/tb_common/policy/classes.py`):

| Class | Meaning | Examples |
| --- | --- | --- |
| D4 Identified | Directly identifies a patient | Chart number, name, national ID, insurer number; original (unscrubbed) notes |
| D3 Pseudonymised | Code (pid) instead of chart number; re-identification only with the key held in the identity vault | Clinical data, **scrubbed notes**, candidate lists |
| D2 De-identified | Produced by a registered transform; no reasonable means of re-identification by the recipient | Date-shifted record-level exports (none planned for the pilot) |
| D1 Confidential, no patient data | Not public, but contains no patient-level data | Counts after small-cell suppression (k = 10 for anything leaving the site, TB-DS-00 N-01), configuration, logs without PHI |
| D0 Public | May be published | Public trial registry text, documentation |

**Scrubbed notes remain pseudonymised (D3) and stay inside the hospital.** Removing identifiers from free text lowers the risk inside the hospital; it does not make the notes de-identified.

## 4. Opt-out notice templates

Each template is a starting point for the hospital's own wording and format. Placeholders are in brackets. The hospital publishes the notice on its website and in the hospital, and keeps a record of opt-out requests. The TrialBox consent and opt-out registry (stage S0) removes opted-out patients from counts and lists.

### 4.1 Japanese (情報公開文書・オプトアウト)

> **臨床研究の候補者探索のための診療情報の利用について**
>
> [病院名]では、臨床研究・治験への参加をご検討いただける可能性のある患者さんを探すため、また、当院で研究を実施できるかを検討するため、既存の診療情報（年齢、性別、病名、処方、検査結果、受診予定、診療記録など）を利用します。
>
> **1. 利用の目的** 　研究・治験の参加条件に合う可能性のある患者さんの人数の見積もり、および候補となる患者さんの一覧の作成（研究担当医師による確認のため）。
>
> **2. 利用する情報** 　[期間]に当院を受診された患者さんの診療情報。
>
> **3. 情報の管理** 　情報は当院内に設置したサーバーのみで扱い、院外には送りません。氏名やカルテ番号は記号に置き換えて管理し、元の情報は暗号化して院内で保管します。研究依頼者（製薬企業等）に提供するのは人数などの集計値のみで、個人が特定される情報は提供しません。
>
> **4. 患者さんへのご連絡** 　候補となった患者さんには、主治医から研究についてご説明することがあります。参加は任意で、参加しないことで診療上の不利益を受けることはありません。
>
> **5. 利用を希望されない場合** 　ご自身の情報をこの目的に利用してほしくない場合は、下記までお申し出ください。お申し出の後は利用しません。ただし、すでに集計された人数から除くことはできない場合があります。
>
> **6. 研究責任者・問い合わせ先** 　[診療科・氏名]　[電話番号]　[受付時間]
>
> 本研究は[病院名]倫理審査委員会の承認を得て、病院長の許可のもと実施しています。

### 4.2 Traditional Chinese (公告／退出機制)

> **關於使用病歷資料以尋找臨床研究候選病人之說明**
>
> [醫院名稱]為了評估本院是否能執行特定臨床研究或臨床試驗，並找出可能符合參加條件的病人，將使用院內既有的病歷資料（年齡、性別、診斷、用藥、檢驗結果、預約門診、病歷紀錄等）。
>
> **一、使用目的**　估計可能符合研究條件的病人人數，並製作候選病人名單，供研究醫師審查。
>
> **二、使用資料範圍**　[期間]於本院就診病人的病歷資料。
>
> **三、資料保護**　資料僅在本院院內伺服器處理，不會傳送至院外。姓名及病歷號會以代碼取代，原始資料加密保存於院內。提供給研究委託者（如藥廠）的僅有人數等統計資料，不包含可識別個人的資料。
>
> **四、聯繫病人**　若您成為候選人，將由您的主治醫師向您說明研究內容。是否參加完全出於自願，不參加不會影響您的醫療照護。
>
> **五、不同意使用**　如您不希望您的資料用於上述目的，請與下列聯絡人聯繫，我們將停止使用您的資料。已完成的統計數字可能無法再排除。
>
> **六、計畫主持人及聯絡方式**　[科別、姓名]　[電話]　[服務時間]
>
> 本計畫經[醫院名稱]人體試驗審查委員會（IRB）核准。

### 4.3 English

> **Use of medical records to find possible participants for clinical studies**
>
> [Hospital name] uses existing medical information (age, sex, diagnoses, prescriptions, test results, upcoming appointments and clinical notes) to estimate whether studies can be run at this hospital and to find patients who may be able to take part.
>
> 1. **Purpose.** To estimate how many patients may meet a study's conditions, and to prepare lists of possible candidates for review by the study doctors.
> 2. **Information used.** Records of patients seen at this hospital during [period].
> 3. **Protection.** The information is processed only on a server inside the hospital and is not sent outside. Names and chart numbers are replaced by codes; the originals are kept encrypted inside the hospital. Study sponsors receive only counts, never information that identifies anyone.
> 4. **Contact.** If you are a possible candidate, your own doctor may tell you about the study. Taking part is voluntary and does not affect your care.
> 5. **If you do not want your information used.** Please contact us below and we will stop using your information for this purpose. Counts already produced may not be changeable.
> 6. **Contact.** [Department, name] [Phone] [Hours]
>
> This activity has been approved by the [Hospital name] ethics committee.

## 5. Pilot validation protocol (summary for the committee)

Full protocol: TB-DS-04 §8. Summary:

| Item | Content |
| --- | --- |
| Design | Prospective, single-arm comparison of TrialBox output with blinded manual chart review, per study, in two phases (TB-DS-00 BD-16) |
| Studies | Japan head hospital: early Alzheimer's disease study. CGMH: rheumatology (RA biologic study; optional gout cohort). |
| Phase 1, weeks 1–6 (parallel) | The study team screens as usual. TrialBox lists are additive: a patient found only by TrialBox may be approached after the investigator has checked suitability from the chart. TrialBox output is never used to exclude a patient. |
| Week-6 checkpoint | Phase 2 starts only if pooled recall on the charts reviewed so far is at least a conditional pass (point estimate ≥ 90 %, every miss explained) **and the committee approves Phase 2** (notified or amended according to the committee's rules). Otherwise Phase 1 continues and staff-time results are reported as not measured. |
| Phase 2, weeks 7–12 (TrialBox-first) | The team pre-screens from the TrialBox list; a random 20 % of each study's clinic list (drawn by the system) is still screened manually as a safety net. Staff time per pre-screen (N-17) and net weekly time are measured here against the baseline. |
| Comparison of lists | Produced by the pilot team, who import the coordinator's existing screening log weekly; the coordinator only keeps the log as today. |
| Sample | 100 patients per study at a fixed snapshot, stratified: 30 listed by TrialBox, 50 passed the structured filters but not listed, 20 failed a structured filter within the study's age and diagnosis frame. |
| Blinding | Reviewers do not see TrialBox verdicts. Strata A and B (listed; passed filters, not listed): two reviewers (a coordinator and a physician) per patient, disagreements settled by the PI. Stratum C (failed a structured filter): one reviewer, PI adjudicates only on disagreement with the filter. |
| Data | Reviewers use the full chart in the hospital's EMR. Review forms record per-criterion judgements and an overall judgement, under the patient's study code. |
| Endpoints | Recall (primary, Phase 1 and 2); wrong exclusions; list precision; feasibility count correctness; turnaround; coordinator time per pre-screen and net weekly staff time against the baseline (Phase 2); leaked-PHI rate; usability (SUS; NASA-TLX reported descriptively). |
| Acceptance | Pooled recall ≥ 90 % point estimate and Wilson 95 % lower bound ≥ 75 %, every miss explained (TB-DS-00 N-16). |
| Staff time | Chart review about 78 reviewer hours per study (two reviewers in strata A/B, one in stratum C; TB-DS-04 §8.4), **pilot-only time funded from the pilot budget**, with backfill or seconded reviewers (an SMO CRC or physicians from another department for strata B/C) agreed with the department head; not counted as clinical workload. Phase 1 adds about 1–2 min per candidate for PI marks and contact outcomes, agreed in advance (TB-DS-17 §2.2). Baseline self-log ≈ 10 min/day for 2 CRCs and 2 PIs for 2 weeks. |
| Risks to patients | None from the review itself (no contact, no intervention). Privacy risk controlled as in §2. |
| Duration | 12 weeks per site, chart-review checkpoints at weeks 6 and 12. |
| Stopping | The pilot is paused if a privacy incident occurs or if any patient is excluded by TrialBox output against the Phase-1 additive rule or the Phase-2 rule that no patient is excluded by TrialBox output. |

## 6. Consent explainer approval process (BD-15)

TrialBox drafts a plain-language consent explainer from the study's consent form (ICF). One process applies at every site (TB-DS-00 BD-15 v0.5; the same steps are on S9 and S21 in TB-DS-09):

1. **Draft with the ICF.** The draft is generated when the ICF is added and is labelled "Draft for ethics committee submission" in every language. It goes to the committee **in the same submission as the ICF**; the study team may edit it before submission.
2. **The committee's decision.** The committee approves, approves with changes, or rejects the explainer together with the ICF.
3. **Approval record.** After approval the coordinator enters the approval (committee, number, date, ICF version) on the study set-up page and **uploads the committee-approved explainer file** (stamped PDF or its text). The investigator confirms. TrialBox computes the file's fingerprint (SHA-256) itself; nobody types it.
4. **Committee wording changes without an ICF amendment** (common for 補助説明資料 / 受試者說明補充資料): the coordinator uploads the edited approved file to the same record with the committee letter date; the investigator confirms; nothing is regenerated.
5. **Industry-sponsored trials (企業治験 / 廠商委託試驗):** the sponsor's approval of patient material (date, contact) must be recorded before the explainer goes live.
6. **Go-live is automatic** when steps 3 and, if applicable, 5 are complete. There is no manual release. Only the uploaded approved file is ever shown to patients; if its fingerprint no longer matches the record, it is withdrawn automatically.
7. **ICF amendment:** a new draft goes with the amendment; the current approved file stays live until the amendment's approval is recorded and confirmed.
8. A site or study may switch the explainer off; then only the ICF is used. Every step is recorded in the audit chain with the file fingerprint.

The explainer supplements the approved consent form; it never replaces the consent conversation or the signed consent.

## 7. Questions committees are likely to ask, with answers

| Question | Answer to prepare |
| --- | --- |
| Does any data leave the hospital? | No patient-level data. Only PI-released counts with small cells suppressed. No cloud services, no remote access by the vendor. |
| Can the vendor see patient data? | No. Support uses a diagnostics bundle with no patient data, reviewed by hospital IT before sending. |
| Does a computer decide who may join a study? | No. Eligibility is decided by the investigator under the protocol. A model alone cannot exclude anyone. |
| How do you know it doesn't miss patients? | The pilot measures it against blinded manual review; usual screening continues in Phase 1, and a 20 % manual spot-check continues in Phase 2. |
| Will TrialBox ask staff to do tests before consent? | No. Missing data is shown as "would need checking after consent". |
| Can the committee change the explainer without an ICF amendment? | Yes; the edited approved file is uploaded to the same approval record (§6 step 4). |
| What if a patient opts out? | The opt-out registry removes the patient from counts and lists from the next night. |
| Who contacts patients? | Their treating physician, or a study investigator after the treating physician has agreed (主治医の了承 / 主治醫師同意), as the protocol states. TrialBox never contacts patients. |
| Is it a medical device? | No; see the non-device statement (TB-DS-16). |

## 8. Submission checklist per site

| Item | Japan head hospital | CGMH |
| --- | --- | --- |
| Committee meeting dates obtained | ☐ | ☐ |
| Submission deadline for the target meeting | ☐ | ☐ |
| Parts A–J adapted to the hospital's forms | ☐ | ☐ |
| Opt-out notice adapted and approved by the privacy office | ☐ | ☐ |
| Chart-review reviewers named, hours (≈ 78 h per study, TB-DS-04 §8.4; one reviewer for stratum C) and funding / backfill agreed with the department head | ☐ | ☐ |
| Phase-1 added time per role agreed by PI and CRCs (TB-DS-17 §2.2) | ☐ | ☐ |
| Workload baseline (TB-TMPL-07) agreed with the department head; window avoids 年末年始 / Lunar New Year or the seasonal caveat is stated | ☐ | ☐ |
| Committee's route for approving Phase 2 at week 6 (notification or amendment) and for explainer wording edits confirmed | ☐ | ☐ |
| Sponsor approval practice for patient material (sponsored trials) confirmed with the research office | ☐ | ☐ |
| Data-use and confidentiality agreement with Aimedics | ☐ | ☐ |
| Submitted (target 2026-11-20, TB-PLAN-01 MS-04) | ☐ | ☐ |
| Approval received | ☐ | ☐ |

## Change history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 findings F-07 and M-08. |
| 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b R2-05: §3 figure and class table follow BD-02 and the code classes; scrubbed notes are D3 and stay inside the hospital; suppressed counts are D1. |
| 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006c: two pilot phases with committee approval of Phase 2 in §1, §2 and §5 (C-01); flow-B gate per study (C-19); no research procedure before consent (C-15); chart review as funded pilot-only time with one reviewer in stratum C (C-04); comparison by the pilot team (C-21); baseline Part F2 (C-03); §6 rewritten to BD-15 v0.5 with uploaded approved file, committee-edit path and sponsor step (C-05); checklist items. |
| 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006d: §2 and §7 state the BD-19 rule for who approaches (D-04); §1 item 3 gate for every study type incl. opt-out registries (D-20); chart review 78 h (D-07); §5 stopping rule uses the phase wording (D-01). |
| 0.4 | 2026-11-07 | Claude for Aimedics | TB-REV-006f F6-28: new §0 two-page description; status says hospital stage only. |
