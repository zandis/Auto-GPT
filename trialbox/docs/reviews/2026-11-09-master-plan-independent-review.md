# Independent review of TB-PLAN-05 v1.1 (TrialBox master plan)

| Field | Value |
| --- | --- |
| Reviewed | `trialbox/docs/plan/25-master-plan.md` (TB-PLAN-05 v1.1), `25-traceability.csv`, `sites/site-survey.md` (TB-SITE-01), `sites/it-security-pack.md` (TB-SITE-02), `reviews/2026-11-09-holistic-master-review.md` |
| Ground truth | `reviews/2026-11-09-owner-decisions-data-and-profile.md`; the other 2026-11-09 reviews; `docs/DECISIONS.md` (last entry D-143); code at `a7fcfed` (master contains the wave 1 merge `40606a4`) |
| Date | 2026-11-09 |
| Stance | Read-only. Adversarial by request. Where I estimate a date I say why. |

## 1. Verdict

**Not fit to run as written. Fit with the changes below, on a longer clock.**

The plan is unusually complete as a document: every owner decision is held somewhere, the risk register is real, the traceability skeleton exists, and the shared-host decision was folded in within hours. That is not the same as a plan that puts real patients through the system safely at two hospitals by 2027-02-09. Five things make the written dates unachievable, and three of them are safety or legal rather than schedule:

1. Real hospital data is scheduled to be read by build agents (cloud sessions) in W3, two to three weeks before the DPA, with no rule anywhere that agents never touch site data (PR-01).
2. The whole-hospital identified feed at CGMH requires the hospital's own HIS team to build an export that does not exist; the plan has no line item, owner, hours or lead time for it (PR-02).
3. The plan assumes the existing IRB approvals already cover a model-written profile, vectors, cross-department identified screening and a clinician role that were all designed on 2026-11-09. They cannot. Amendments are a 4–8 week cycle and are planned as the exception (PR-03).
4. 315 reviewer-hours for ~300 pull requests on a GAMP 5 category 5 safety system, by two practising physicians who also carry 118 hours of site work, through 年末年始 and the run-up to Lunar New Year (PR-04).
5. The model pair has never run on a B200; its first run on the hospital's platform is IQ day in W10 (PR-05).

**Most likely real dates** (reasoning in §4): CGMH IQ/OQ on the B200 in March 2027; PQ with real patients in April; full-scope go-live (whole-hospital screening, profiles, prefill) around **2027-04-30**. Japan IQ in February on the box; contract and amendment gate PQ to March–April; full-scope go-live around **2027-05-14**. A reduced-scope go-live (structured screening in the PI's own department, referral, no profiles, no prefill) is feasible at CGMH in the week of **2027-02-15** (after Lunar New Year) and in Japan in early March, under the existing approvals, if the owner accepts a written scope change.

## 2. Counts

| Severity | Count |
| --- | --- |
| Blocker | 6 |
| High | 14 |
| Medium | 16 |
| Low | 4 |
| **Total** | **40** |

## 3. Findings, ranked

Each: ID, severity, where in the plan, the problem, a concrete fix.

### Blockers

**PR-01 (Blocker) Real patient data reaches build agents before the DPA, and nothing forbids it.**
*Where:* WS-10.2 / WS-11.2 (owner "agent (reader)"; acceptance "a 10-patient de-identified sample of the real storage read by the adapter"), §4.2 W3 ("10-patient samples from each site read"), §11 W3, site survey §A.1 and Q37; contrast §4.3 CP-3 ("no real patient data before signature"), owner decision "Aimedics never holds patient data".
*Problem:* The sample is "de-identified where the site requires it", i.e. by default pseudonymised real records including free text, handed over in W3; the DPA is signed W5–W6 at the earliest (§4.2, §11 W5). The reader is a build agent working in a cloud session on this repository (the agent worktrees are checked into the repository root). Nothing in the plan, DECISIONS, the survey or the IT pack says that site data may only be processed on hospital hardware, or that no agent session, worktree, log, test fixture or issue may ever contain it. Under APPI (委託先の監督) and PDPA Art. 6 this is a breach before the pilot starts, and it contradicts the IT pack's "Aimedics never holds patient data" (§A.10) that hospital IT will be asked to rely on. The same gap recurs at W10 ("fixes to the site mapping only" during IQ: on what data, where?).
*Fix:* (a) A written rule in DECISIONS and the plan: D3/D4 data is processed only on the site's hardware or the site's approved private cloud; no agent session, repository, worktree, CI job, log or ticket ever receives it; agents work from a synthetic sample generated from the site's *schema and code lists* (headers, masters, lab table), which the survey already asks for without data (Q24–Q26, Q32). (b) The real 10-patient sample is read by the adapter *on the site's machine* with the site's steward present, and only the adapter's report (counts, unmapped codes, parse errors, no values) leaves. (c) Move the sample after the DPA, or sign a short-form data-processing letter for the sample in W2. (d) Add RSK-39 for it and a TST-SEC item (a CI grep of the repository for the site's code systems and a `.gitattributes`/pre-commit rule). (e) Say all of this in IT pack §A.10.

**PR-02 (Blocker) The CGMH whole-hospital identified export has no owner, hours or lead time.**
*Where:* WS-11 preamble ("the pilot needs an identified feed from the HIS"), WS-11.2, WS-11.3, §4.3 CP-5 ("4 to 6 weeks per site, mostly steward hours"), RSK-28.
*Problem:* CGMH builds its own HIS. An identified, nightly, all-department, all-history export with free-text notes to a new vendor container is a development project for the hospital's HIS team (views, scheduling, privacy sign-off for the extract itself), not a steward mapping task. The plan budgets zero hours for it and no hospital owner. CP-5's fallback ("start with the least: charts pasted and sheets") is incompatible with "whole-hospital screening" in §1.1 item 1 and with the owner's "entire database" decision, so the fallback silently drops the scope the plan says it never drops. Realistically, prioritising, specifying and shipping such an export at a large medical centre takes 2–6 months.
*Fix:* Add WS-11.10 "HIS export build" owned by CGMH 資訊室 / the data-feed owner, with the scope written by W2 (tables, departments, years, note types, nightly or weekly, pseudonymisation at the door), a signed delivery date, and an explicit tiered scope: tier 1 structured data for the participating departments, tier 2 all departments, tier 3 notes. Make tier 1 the G4 entry condition and tiers 2–3 dated. Mirror the item for Japan (SS-MIX2 is a product, but the extended storage and notes are vendor work). Record a "reduced-scope go-live" decision point for the owner at G3 rather than discovering it in W10.

**PR-03 (Blocker) The plan treats IRB amendments as the exception; they are the base case.**
*Where:* §1.4 "IRB", §4.3 CP-4 ("0 weeks if covered"), WS-10.1 / WS-11.1 ("amendment filed by W4"), §4.4 G5 "Low to medium".
*Problem:* The profile (a model-written narrative per patient read by study staff), the vector store, "patients like me", the steward's unrestricted note access, cross-department identified candidate views by a PI with no care relationship, and the clinician role were decided on 2026-11-09. No approval granted before that date names them. The survey (Q12–Q16) will almost certainly return "no" on Q13 or Q14 at both sites. An amendment then goes to the next monthly meeting (submission deadlines are typically two to three weeks before), with Japanese committees often skipping late December and Taiwanese committees thinning before Lunar New Year. Filed in W4 (2026-12-04), approval is realistically late January to February. The plan's own rule ("PQ at that site waits for the amendment") then moves real-patient PQ past 2027-02-09 at both sites.
*Fix:* Draft the amendment text now from the design document and the IT pack's one-pager (WS-13.6 already exists as a deliverable; pull it into W1). Submit at both sites by 2026-11-20 for the December meetings, in parallel with the survey, and withdraw if the survey shows it is unnecessary. Add the committee's meeting and deadline dates to the plan's clock. Raise G5 to High. Keep "PQ waits" as the rule and say what the site does meanwhile (PI-department screening under the existing approval).

**PR-04 (Blocker) Review capacity is a third of what the plan needs, and the shortfall lands on the safety core.**
*Where:* §3 Totals and the "Reading the totals" paragraph; §4.3 CP-5; WS-17.5.
*Problem:* Summing the Size column gives 303 agent sessions and 315.5 reviewer-hours (the table says 298 and "about 330", the text says 320; see PR-27). Of the ~315 hours, ~118 are site work (WS-10, WS-11), ~47 are legal and commercial (WS-15), leaving ~150 hours to review ~280 pull requests: about 32 minutes per PR, for a GAMP 5 category 5 system whose PRs include the permission function, the pid map, the audit chain, the SQL generator, OMOP parity and Part 11 controls. The two reviewers are practising physicians who also run the surveys, the mapping confirmations (12 R each in WS-10.3/11.3), the training and the PQ, through 年末年始 and the fortnight before Lunar New Year. The plan's mitigation ("review in batches at the gates") turns review into sign-off of batches, which is what a sponsor auditor will call out. The safety-core engineer at "about 4 hours a week" cannot cover it either.
*Fix:* (a) Re-plan on 6–8 reviewer-hours a week each (what a clinician can give) and show the consequence honestly. (b) Cut the PR count: one reviewed PR per WS item per gate (about 60–80 PRs), with agent-to-agent review for the rest and human review concentrated on the six safety-core files, the authz matrix, the prefill path and the migrations. (c) Make the safety-core engineer at least two days a week through G3 and the named approver of every safety-core PR. (d) Add a second human reviewer per site for site hours (the steward and the CRC lead), which the owner decision "named hospital staff at each site" already requires. (e) Record reviewer hours actually spent per PR in the release record so the GAMP claim is auditable.

**PR-05 (Blocker) The model pair meets the B200 for the first time on IQ day.**
*Where:* WS-11.8, WS-14.8, §7.3 "IQ, hospital platform", TST-IQ-03, §4.4 G4 ("the shared-host path has never run on a hospital platform").
*Problem:* The only measured serving record is `rtxpro6000` (an SM120 workstation card, CUDA 13.0, driver 580, judge checkpoint in NVFP4, verifier AWQ 4-bit). The B200 is SM100 with the hospital's driver and runtime; kernel availability, MIG behaviour, `gpu_memory_utilization` fractions and throughput all differ. The qualification record (WS-02.2) is per build *per tier*, and the `shared-quota` tier gets its record at IQ in W10, with no fallback but an unspecified private cloud. If the canary or N-12 fails on the quota, PQ cannot start. The acceptance cluster at Aimedics (WS-14.8) is "a Kubernetes or Docker host with a GPU quota": no B200 is named.
*Fix:* Rent a cloud B200 (a GCP A4-class VM) for one or two days in W3–W5, configure a MIG instance matching the quota requested from CGMH, run `qualify` there and commit the `shared-quota` record; require the CGMH quota to be a MIG instance (memory-isolated) and write that into survey Q46 and IT pack §A.6 ("share of SMs" is not an acceptable answer for a PHI workload). Keep the B200 record as the G2 entry condition for WS-11.8.

**PR-06 (Blocker) The go-live window straddles Lunar New Year with reduced staff on the first week of real screening.**
*Where:* Clock row, §4.1 Go-live, §4.2 W12–W13 ("CGMH runs its first week with reduced staff over Lunar New Year"), §1.4 "Go-live order".
*Problem:* 除夕 is Fri 2027-02-05; the Taiwan public holiday runs from 02-05 to about 02-10, and hospital staff take leave the week before. CGMH go-live on Wed 01-27 means the first SAE acknowledgements, the first referrals through treating physicians, the first excluded-list review and the first held-batch decisions by the steward fall in the one week of the year when PIs, CRCs and 資訊室 are least available. "A CGMH contact on duty" is not a safety control for a system whose value is a human reading a list every morning. The plan calls this "a week clear of Lunar New Year"; it is not.
*Fix:* Either go live at CGMH by 01-20 with hypercare finished by 02-03, or go live in the week of 02-15. Given PR-01 to PR-05, the second is the realistic one. State in §4.1 that no site goes live within ten working days before a national holiday period.

### High

**PR-07 (High) Code keeps changing after "feature complete" and after the application pentest.**
*Where:* Gate column: WS-03.5, WS-03.8, WS-07.2, WS-08.6, WS-08.8, WS-11.8, WS-13.2, WS-13.9, WS-14.8, WS-06.12, WS-10.8, WS-11.9 are gated "IQ/OQ"; §4.2 W9 "Fix only"; WS-13.8 "pentest pass 2 on the frozen release".
*Problem:* Backups (WS-08.6), the Windows key wrapping (WS-13.2), REDCap push with arms and repeating instruments (WS-07.2), the lake-from-OMOP flag flip (WS-03.5) and the whole container deployment (WS-14.8) are allowed to land between G3 and G4. The pentest letter and the acceptance record then describe a release that is not the one installed. For GAMP 5 the OQ must run on the frozen release; for the flag flip, changing the screening data path at the site during IQ is the single riskiest moment to do it.
*Fix:* Move every code item to "feature complete" or earlier; keep only site configuration (CC6) and documents after G3. Flip the OMOP flag on the acceptance box before G3 and ship it on; if it is not ready, ship NDJSON for the pilot and say so (the plan's own §4.4 fallback). Re-run the pentest's automated part on the final digest set.

**PR-08 (High) The steward at CGMH is the vendor's owner.**
*Where:* WS-11.3 "Changfu (steward)", WS-08.1 "Changfu, Makoto (as stewards)", WS-16.1 "Changfu (PI)", §7.3 "Aimedics (executor)", WS-12.1 "Changfu (approver)".
*Problem:* The owner decided "Data steward: named hospital staff at each site. Aimedics never holds patient data." The plan makes the Aimedics owner the CGMH steward, the Study A PI, the IQ/OQ executor and the approver of the URS, the risk file and the release record. One person is vendor, site data controller's delegate, investigator and QA approver. A sponsor auditor or the hospital's own QA will not accept the IQ/OQ or the validation summary signed that way, and PDPA/APPI supervision of the 委託先 cannot be exercised by the 委託先.
*Fix:* Name a CGMH employee (病歷室 or 臨床試驗中心 staff) as steward by W2 and give them the steward hours; the owner stays reviewer and PI. The IQ/OQ witness must be hospital IT and the PI, the executor an Aimedics person who is not the approver of the release record; if Aimedics is one person, the safety-core engineer executes and the owner approves. Say so in §7.3.

**PR-09 (High) Prefill and screening accuracy are never measured on real records before real use.**
*Where:* WS-07.1 (accuracy ≥ 0.90 on *synthetic* planted truth), §7.3 PQ ("prefill confirmed on a real record and pushed"), TST-PQ-01 ("0 fail in the script"), WS-06.7 (ten excluded per week), WS-16.1 (Study A results after go-live).
*Problem:* The only real-data checks before go-live are a 10-patient sample for parsing, a known-cohort recount, and "0 fail" in a journey script. Nothing measures how often the judge wrongly excludes a real patient at the site, or how often a prefilled value is wrong, before the PI acts on the list and the CRC confirms values into REDCap. The CRC-confirms control (RSK-20) assumes the CRC reads every draft; automation bias with a 90 %-accurate drafter is the known failure mode and no control addresses it (accept-without-edit rates, dwell time, blind re-entry).
*Fix:* Add two PQ endpoints with numbers: (a) a 100-chart retrospective dry run per site during OQ (the site's real notes, the PI's own study, two CRC readers): wrong-exclusion rate ≤ 2 % and listed-candidate PPV ≥ 0.6 before any excluded list is shown to a PI; (b) 30 real CRF pages double-entered blind versus prefill: post-confirmation field accuracy ≥ 0.98, and the accept-without-edit rate reported weekly with a 5 % blind re-entry sample for the first three months. Add RSK-40 "automation bias on prefill".

**PR-10 (High) On the shared host the key-encryption key has nowhere safe to live.**
*Where:* WS-13.2 (KEK "a DPAPI/TPM service or a boot passphrase"), WS-14.8 ("hardening items that assume a host replaced by the platform's equivalents"), RSK-36 residual S4 P1.
*Problem:* On Kubernetes or a Docker host there is no TPM or DPAPI the container can use; the KEK becomes a Secret readable by every cluster or host administrator, so the pid map, the site keys and the `phi` files are readable by the platform team the plan says is outside the trust boundary. RSK-36's residual P1 is paper.
*Fix:* Decide one of: an external KMS/HSM the hospital operates (ask in survey Q48); a steward-entered passphrase at pod start (manual unseal, documented downtime cost); or accept platform administrators inside the trust boundary, name them individually in the DPA and the 責任分界 sheet, and alert on every secret read. Reword RSK-36 residual accordingly.

**PR-11 (High) Sponsors of the pilot studies are never told TrialBox is in their source-data chain.**
*Where:* WS-07 preamble, WS-07.5 ("never writes to a sponsor EDC"), WS-15.1 ("sponsor-facing terms for feasibility packs"), §9.3 "Trial records".
*Problem:* The owner's EDC decision makes TrialBox part of the trial-data chain. ICH E6(R3) puts oversight of computerised systems used at a site on the sponsor; a monitor who finds model-drafted values behind REDCap or copy-assisted into a sponsor EDC without the sponsor's knowledge will raise a finding against the site. The plan has no notification, no system description for sponsors, and no restriction of prefill to IITs until a sponsor agrees.
*Fix:* Add WS-07.7: a sponsor notification letter and one-page system description per pilot study; prefill is enabled per study only after written sponsor acknowledgement (automatic for IITs where the PI is the sponsor). Put the switch in the study set-up page and audit it.

**PR-12 (High) The non-device statement is contradicted by the product's own vocabulary.**
*Where:* §1.2 ("does not decide whether a patient is eligible"), WS-03.6 and D-143 ("excluded and why" page), RSK-01/RSK-02 ("wrongly excluded"), WS-13.7 forbidden-word list.
*Problem:* The system produces per-patient exclusion decisions with reasons, lists them, and the plan's own risk file calls them exclusions. A PMDA 該当性 reviewer, a TFDA officer or an IRB member reading the statement beside the excluded page will see an eligibility determination presented as a non-decision. "判定" is on the forbidden list; "除外 / excluded" is not.
*Fix:* Harmonise: the product "lists patients whose records do not match a criterion, for the investigator's review"; rename the page ("criteria not matched") in all three languages; add 除外/排除/"excluded" to the forbidden-word check except in the risk file; have counsel read the statement against the UI before it ships (WS-15.4 only reads TB-DS-16).

**PR-13 (High) The zh-TW IT pack calls a re-identifiable repository 去識別化.**
*Where:* IT pack §C.1 ("維護去識別化的研究資料庫"); contrast §A.1 ("pseudonymised"), §B.1 ("仮名化", correct).
*Problem:* Under PDPA, 去識別化 is the standard for data that "cannot identify" the person (Art. 6(1)(4) research exception). TrialBox keeps a pid map and reveals chart numbers to several roles. A privacy officer who signs on the strength of 去識別化 and later learns of the reveal function has been misled, and the legal basis memo (care relationship plus IRB) rests on the opposite claim.
*Fix:* Use 假名化 throughout §C; state in §C.1 and §C.10 that authorised roles can re-identify through a key held on the hospital's platform, and that 去識別化 applies only to exports under §C.5.

**PR-14 (High) Contracts: the plan's 4–8 weeks is counsel time, not hospital time.**
*Where:* §4.3 CP-3, §4.2 W5–W6 ("contracts signed (target)"), WS-15.1, WS-15.2, §7.3 ("PQ needs the signed DPA").
*Problem:* A new master licence plus a DPA with EMR 辦法 clauses at a Taiwanese 財團法人 medical centre goes through 資訊室 security review, 個資 review, 法務 and 院長 signature; a Japanese hospital 委託契約 goes through 契約審査 and 稟議, often with a vendor registration step. Two to four months is normal. Because PQ needs the signed DPA, real patients slip to February–March at best. The plan's "a late contract moves PQ, not IQ" is correct and is exactly why the date fails.
*Fix:* Use an instrument each hospital already has: a 共同研究契約 / 研究協力契約 with data-handling annexes at CGMH (the owner's own affiliation makes this natural) and the hospital's standard 業務委託 template in Japan, with the TrialBox-specific clauses as a short annex. Start both in W1 with the hospitals' templates, not Aimedics' draft. Treat signature as a hard G4 entry condition and show it on the clock.

**PR-15 (High) The acceptance box cannot exist when the plan first needs it.**
*Where:* WS-14.1 (ordered by 2026-11-13, "4 to 8 weeks lead"), WS-14.4, §4.2 W3 ("the acceptance box arrives (if ordered with a short lead) or a rented workstation stands in"), W4 (Windows hardening and pentest pass 1 "on the acceptance box"), G2 ("the acceptance box installed from the media"), TST-OPS-01/02/04 and TST-SEC-07 at G2.
*Problem:* With the plan's own lead time the box arrives between 12-11 and 01-08; G2 is 12-11. Five G2 tests and the first pentest pass depend on it. The rented-workstation hedge is a parenthesis, not a plan item.
*Fix:* Make the rental a W1 action (an RTX PRO 6000 workstation for W2–W7), or move TST-SEC-07, TST-OPS-01/02/04 and pentest pass 1 to G3 and say so in §4.1.

**PR-16 (High) The survey never asks how many patients the hospital has.**
*Where:* Survey §A.4 (Q28 asks years of history, not volume); §1.5 and WS-08.7 (2 TB sized for 50,000 patients); owner "All history now".
*Problem:* Every sizing number in the plan (2 TB, 256 GB RAM, HNSW 10–14 GB, backup under a minute, the night window) is for 50k patients. A regional Japanese hospital with 15–25 years of electronic history holds several hundred thousand patients; a medical centre like CGMH, millions. "All history, all patients, all notes, all embedded" is a decided scope with an unmeasured size. The plan has the 500k projection as a test (TST-PERF-01) but orders the hardware in W1.
*Fix:* Add survey questions: distinct patients, encounters per year, note count and text volume, lab rows per year, current EMR database size. Order the Japan box with 2 × 4 TB or decide a dated history cut at order time. Make the CGMH storage request (Q46) a number from the survey, not "2 TB".

**PR-17 (High) The SAE clock has no system of record and no failure mode in the risk file.**
*Where:* WS-01.1 ("SAE acknowledgement and clocks"), WS-10.6 / WS-11.6, URS-CRC-04, RSK register (no entry).
*Problem:* TrialBox shows a due day per party from site defaults confirmed in W10. If the site rule is entered wrongly, if the box is down, or if the CRC learns to rely on the banner rather than the office SOP, a 7-day fatal-SAE report to the IRB or TFDA is missed. No RSK row covers a wrong or absent clock; RSK-13 covers downtime generically.
*Fix:* State in the SOP and the role guides that the trial office's SAE log remains the record and TrialBox is a reminder; add RSK-41 "SAE reminder wrong or absent" with controls (site rule double-confirmed by the office, an OQ test with a deliberately wrong clock, the banner says "per site rule confirmed by X on date"); make a fatal SAE also mail the office mailbox.

**PR-18 (High) Free-text notes may not exist in the Japan feed.**
*Where:* WS-10.2, WS-10.3, WS-05.1 (profiles cited to notes), survey Q31.
*Problem:* SS-MIX2 standardised storage carries ADT, orders, labs, prescriptions and diagnoses; progress notes and summaries exist only in the extended storage if the EMR vendor writes them there, and many do not. The profile, the citations, the note-based criteria and the embeddings all assume notes. The plan has no branch for "no notes in the feed".
*Fix:* Make Q31 a gate: if the feed carries no notes, the Japan pilot ships structured screening and the record/timeline layers only, with discharge summaries or consult letters added by a dated vendor change request or by pasted charts; write that as a WS-10 fallback and an owner decision at W4.

**PR-19 (High) The hospital platform's isolation and encryption are attested, not verified, and the plan says "verified".**
*Where:* WS-13.9, WS-14.8 (`doctor --platform` checks "storage encryption, network policy"), IT pack §A.6 ("Aimedics verifies at IQ"), §7.1.
*Problem:* A job inside the namespace cannot prove the storage class encrypts at rest, that root access to the volume is logged, or that another tenant cannot mount the volume; it can only test what it can reach (egress, inbound probes from a second namespace it controls). Everything else is the platform team's word.
*Fix:* Split TST-IQ-03 into "tested by TrialBox" (egress, inbound probe, quota refusal, digest match) and "evidenced by the platform" (storage class specification and encryption setting, a CIS Kubernetes or Docker benchmark output, a sample of the audit log showing a root access to the volume, the MIG configuration dump). Require the platform evidence as attachments to the signed supplier assessment. Change "verifies" to "verifies or receives evidence for" in the IT pack.

**PR-20 (High) Baseline measurement overlaps training and IQ, and starts on a Japanese holiday.**
*Where:* §4.2 W9 ("the workload baseline window starts at both sites (01-04 to 01-15; the JP window ... starting 01-11 if the site asks)"), WS-10.7, WS-16.2, survey Q66 ("not 年末年始, not Lunar New Year").
*Problem:* 2027-01-11 is 成人の日. The first week after 年末年始 is not a normal week in a Japanese hospital. A window of 01-04 to 01-15 (or 01-11 to 01-22) overlaps steward certification, CRC and PI training and IQ/OQ in W10, so the baseline measures CRCs already exposed to TrialBox. Study A's time-motion comparison is then unusable.
*Fix:* Run the baseline 2026-11-30 to 2026-12-11 at both sites (before any training), or the two weeks after Lunar New Year if go-live moves. Fix the holiday.

### Medium

**PR-21 (Medium) The Japan box spec overrides an owner decision without asking.**
*Where:* §1.5 (256 GB "the decision said 128 GB"), §2 row 1 ("the 2 TB / 128 GB spec"), owner "First hospital box: 2 TB disk and 128 GB RAM, confirmed per site".
*Problem:* The plan changes a binding decision in a table cell and keeps the old number elsewhere. It may be right (all-history HNSW plus a second model), but it is an owner call and a cost line.
*Fix:* Put it in §13 as Q-28 with the cost difference, get the answer before 11-13, and make §2 consistent.

**PR-22 (Medium) Internal date and duration contradictions.**
*Where:* §4.1 G3 "W8, 2027-01-01 (in practice Mon 2027-01-04)" vs §4.2 W8 "12-28" and W9 "01-04"; §7.3 PQ "the first two weeks of real use" vs §4.1 CGMH PQ 01-18 to 01-22 (five days); §1.4 "CGMH IQ/OQ in W10 (01-11 to 01-13)" is three days for a one-day IQ plus a one-to-two-day OQ with the same team flying to Japan for 01-14; survey Q68 "CGMH before 2027-02-05; Japan the week after" contradicts §4.1 (Japan by 02-03); W3 Monday 11-23 (G1 week) is 勤労感謝の日.
*Fix:* One calendar table in §4 with every date, weekday and holiday, generated, and every other section pointing at it. Give CGMH PQ its ten working days.

**PR-23 (Medium) The traceability CSV is hand-made and disagrees with the plan in 23 places.**
*Where:* `25-traceability.csv`; §7.4 (says the matrix has an `fs` column and evidence is "a test path, a report path or a signed protocol"); §5 "Plan" columns; §8 levels.
*Problem:* The CSV has no `fs` column; every `evidence` cell is a gate label; every status is `planned`. Seventeen URS rows map to different WS items in §5 than in the CSV (for example URS-STW-01 → WS-03.4/03.5/03.7 in §5 but WS-03.1/03.4/06.1 in the CSV; URS-CLN-03 loses WS-15.4; URS-PRV-07 loses WS-06.1). Six tests carry a different level in the CSV than in §8 (TST-EDC-02 I vs E, TST-EDC-03 U vs E, TST-IQ-02 OQ vs IQ, TST-PROF-03/04/05 E vs G). All WS-18 rows are absent (acceptable, but say so). The generator that would catch this is itself a planned item (WS-12.2).
*Fix:* Generate the CSV from the §3, §5, §6 and §8 tables now (a 100-line script), add `fs`, and make the §5 "Plan" column derived from the WS Trace column rather than typed twice.

**PR-24 (Medium) Acceptance criteria that cannot be failed.**
*Where:* WS-01.5 ("the walk checks each sentence, outcome, confirmation and count"); WS-05.1 ("first-build nights estimated and under the site's night window", window undefined); WS-11.8 ("finishes inside the night window with the other tenants running", one night, window undefined); WS-06.4 ("a referral target can always be chosen in three taps"); WS-12.5 ("the re-review scores ≥ 4.5", scale undefined); WS-17.4 ("the first site call has a path"); TST-PERF-01 ("within the night budget"); WS-10.3 / §7.3 OQ ("the known-cohort recount equals the hospital's own counts", no tolerance, no definition of the cohort); §4.5 ("green, or an owner-signed deviation", so every item is waivable); G6 "residual risks accepted".
*Fix:* Define the night window per site in the survey (Q66 area) as a number of hours; WS-11.8 measures five consecutive nights with p95 completion time; the recount has a tolerance (±2 % and every difference explained); the re-review uses the §8 scoring table of VALIDATION.md and names the reviewer; WS-01.5 lists the walk assertions it adds; §4.5 names the items that may *not* be deviated (IRB, DPA, PQ 0 fail on H functions, pentest no open High, isolation tests, backup restore).

**PR-25 (Medium) The interim private cloud is assumed to exist and to be approved.**
*Where:* §1.4 "Interim hosting", §4.3 CP-1 fallback, WS-10.8, WS-11.9, RSK-38.
*Problem:* Neither site has said it has a GPU private cloud approved for identified patient data. The plan's only hardware fallback is therefore unverified, and it adds a migration (one night plus a drill) that is itself a validation event.
*Fix:* Make "does the site have one" a W1 question answered by 11-20 (survey Q45–Q48 moved forward); if the answer is no at a site, write the fallback as a date slip, not as hosting.

**PR-26 (Medium) Nothing merges to master for three weeks while seven agents build in parallel.**
*Where:* §4.4 G1 ("nothing merges to master until G1"), §4.2 W1–W3, owner "merges only after Wave 1".
*Problem:* Goldens, provenance columns, the vocab schema, the steward role and `authz.permit`, the catalogue load and the CI gate are all on branches touching the lake schema, the console and the orchestrator at once. A W3 big-bang merge of seven branches is where safety regressions are introduced and where the review hours of PR-04 evaporate.
*Fix:* Wave 1 is already on master (`40606a4`), so the owner's condition is met: merge continuously behind flags (WS-01.4 flags land first), with the goldens as the merge gate, and keep G1 as a verification of master, not a merge event.

**PR-27 (Medium) The totals do not add up.**
*Where:* §3 Totals table and "Reading the totals".
*Problem:* Summing the Size cells: 303 S and 315.5 R (table: 298 S, "about 330" R; text: "320 review hours"). Per workstream: WS-06 30 S (table 27), WS-10 52 R (table 58), WS-11 54 R (table 60), WS-08 8.5 R (table 9), WS-01 7.5 R (table 7), WS-02 4.5 R (table 5). Small, but a plan that claims traceability should compute its own totals.
*Fix:* Generate the totals from the tables, with the WS-17.5 engineer's hours as a separate line.

**PR-28 (Medium) Windows patching and endpoint security for an offline appliance are not addressed.**
*Where:* IT pack §A.2, §A.7, §A.8; survey Q50.
*Problem:* The appliance is Windows 11 with no internet. Hospital IT will ask how Windows receives security updates (WSUS, offline cab, cadence), whether the hospital's EDR/antivirus must be installed on the host and in WSL2, how it is updated, and who owns the Windows admin account. The pack answers only for TrialBox images.
*Fix:* Add a "host OS lifecycle" row to §A.2 and §A.7: monthly offline Windows update bundle with the TrialBox release, the hospital's EDR agent allowed on the host with the WSL2 exclusion list documented, the host admin account held by hospital IT with the password in the key envelope, and a line in the 責任分界 sheet.

**PR-29 (Medium) The ja and zh-TW survey sections are prose, not forms, and drop content.**
*Where:* Survey §B, §C.
*Problem:* §A is a fillable table; §B and §C compress 68 questions into paragraphs with no answer cells, so the site must answer in English or on a separate sheet. Content drift: Q68 (ja) drops the CGMH date, Q68 (zh) drops "Japan the week after" and contradicts the plan; Q38 (zh) drops the examples; Q21 (ja, zh) drops "after the end of the study or approval"; Q46 (zh) renders "share of SMs or MIG slice" but the pack's §C.6 does not require MIG; IT pack §C.4 drops "SMO staff". The IT pack §B and §C are faithful apart from the 去識別化 term (PR-13).
*Fix:* Mirror §A's table in each language with the same numbering and an answer column; generate all three from one source so the numbers cannot drift; have a native reader (Makoto, a CGMH CRC) sign each language version.

**PR-30 (Medium) Hospital IT questions the pack does not answer.**
*Where:* IT pack §A.3–§A.10.
*Problem:* Missing: RPO and RTO numbers (the backup is nightly, so RPO is 24 h; say it and what is lost); syslog/SIEM forwarding (most 資訊室 and 医療情報部 require it; `/metrics` is not a log); session timeout, password policy numbers, idle lock on shared clinic PCs (Japanese outpatient terminals are shared); account lifecycle when staff leave (AD covers it only if AD is used); vendor on-site access (who from Aimedics will be in the hospital, with what badge and what accounts, since "no remote access" implies on-site work); whether any AI or cloud service is used in *developing* the software and whether developers ever see hospital data (see PR-01); the support organisation behind "a Japanese-speaking first line in JST hours and a zh-TW line" (how many people, where).
*Fix:* Add a §A.11 "operations and people" table with those rows and honest answers; the AI-in-development disclosure in §A.10.

**PR-31 (Medium) Study A's chart-review workload is unfunded and its submission date is unrealistic.**
*Where:* WS-16.1 ("submitted to the CGMH IRB by W4", "the chart-review team and hours funded"), WS-11.7.
*Problem:* 100 ready candidates plus 300 note-excluded patients per study, three to five studies, two independent CRC reviews each: 1,600–4,000 chart reads by CRCs who are also running the pilot. No hours appear in any table. Submission by 12-04 needs a frozen snapshot of real data, which does not exist before the feed (PR-02).
*Fix:* Budget the CRC hours (about 20 minutes per chart), name the team, and submit the protocol when the first real snapshot exists; keep "no claims before Study A" as the control.

**PR-32 (Medium) The candidate view reveals other departments' patients before the treating physician agrees.**
*Where:* WS-06.5, owner "Candidate view", §9.3 "Legal basis for identified pre-screening" (care relationship plus IRB).
*Problem:* The PI has no care relationship with another department's patient; the whole legal basis for that reveal is the IRB's approval of the recruitment method. The plan relies on the survey's Q13 but does not require the IRB text to say *identified* pre-screening across departments *by the PI before referral*. This is the single largest privacy exposure in the design and it is an owner decision, so it must be approved in those words.
*Fix:* Put the exact sentence in the amendment (PR-03) and in the legal-basis memo; add an owner question: should identifiers be revealed only after the treating physician agrees, with the pre-agreement view pseudonymous? If the owner keeps the decision, make it a signed residual risk.

**PR-33 (Medium) Missing risks.**
*Where:* §6.
*Problem:* No row for: site data in agent sessions (PR-01); automation bias on prefill (PR-09); SAE reminder wrong or absent (PR-17); model kernels or driver incompatible on the B200 (PR-05); data volume beyond sizing (PR-16); the hospital's export build late (PR-02); holiday staffing at go-live (PR-06); the steward being the vendor (PR-08); notes absent from the feed (PR-18).
*Fix:* Add RSK-39 to RSK-47 with controls and tests as above; review at G2.

**PR-34 (Medium) Owner decisions are binding but not yet in the controlled log.**
*Where:* Decisions document ("will be entered as a numbered decision in DECISIONS.md when that work's first PR merges"); DECISIONS.md ends at D-143; plan status "Approved in substance".
*Problem:* The plan claims GAMP document control (WS-12.1) while its binding inputs live in a review file that any later edit can change without a sequence number. Several decisions (CGMH B200, CGMH first, interim hosting) already changed within one day.
*Fix:* Enter D-144 (data, profile, roles) and D-145 (hardware, hosting, order, plan approval) now, verbatim, and have the plan cite them.

**PR-35 (Medium) GAMP 5 and ER/ES paperwork gaps.**
*Where:* §7, WS-12.
*Problem:* No signed validation plan (VMP) exists before execution starts (§7 is inside the project plan, approved by the vendor); no periodic review is scheduled; no supplier (Aimedics) assessment the *hospital* can file (sponsors and hospital QA will ask for the vendor's QMS evidence, which WS-12.1 produces but no item hands over); no unique-user control for shared clinic terminals beyond MFA (the ER/ES 真正性 requirement); no data-migration validation protocol for interim-to-final host beyond "a drill".
*Fix:* Split §7 into a standalone VMP signed by the owner, the safety-core engineer and each site's PI before IQ; add a periodic review (six-monthly) to §12; add "vendor assessment pack for the hospital" to WS-13.8; add an idle lock and re-authentication on signature to WS-13.1's acceptance; write the migration as a protocol with row counts, hash and chain verification.

**PR-36 (Medium) CP-2's "local TOTP at go-live if no AD" weakens the G2 identity claim.**
*Where:* §4.3 CP-2, §4.4 G2 fallback ("freeze without AD; AD at IQ"), WS-13.1 gate "design freeze".
*Problem:* AD groups mapping to roles including steward is how rights are revoked when staff leave. Local accounts with TOTP at a hospital mean the trial office manages a second user directory by hand; MHLW GL 7.0 expects directory-based identity where available. Acceptable as a fallback, but it changes the authz tests and the training.
*Fix:* Keep it, but add the account lifecycle procedure for local accounts to the role guides and the OQ, and make "AD within 60 days of go-live" a dated CC6 item.

### Low

**PR-37 (Low) WS-18.7 (a front-end design system assessment) does not belong in the master plan.**
*Fix:* Move to DECISIONS; it dilutes a safety document.

**PR-38 (Low) §7.4 and §8 describe test levels inconsistently (TST-IQ-02 is labelled OQ in §8 and IQ in its ID and the CSV).**
*Fix:* Rename to TST-OQ-02.

**PR-39 (Low) "Aimedics" is used as an organisation with contracts, insurance, a pentest firm, a support desk and a quarterly drill cadence; the plan never says how many people it is.**
*Fix:* One line in §3 conventions naming the humans and their hours, so the site-facing promises in WS-15.5 and WS-17.4 are visibly staffed.

**PR-40 (Low) The 10-patient OQ sample is also the mapping sample.**
*Where:* §7.3 OQ "on the site's own 10-patient sample".
*Problem:* OQ should run on records the mapping was not tuned on.
*Fix:* A second, different 10–20 patient sample for OQ.

## 4. Schedule: what will actually happen, and why

The plan's build estimate (303 sessions, about one agent-day each) is below the reviews' own sizing (420–500 single-engineer days in the holistic master review §1) and assumes 5–7 agents merging daily with 32 minutes of human review per PR (PR-04). I take the build as roughly feasible at 60–70 % of the planned velocity if review is restructured, so feature complete lands late January, not 01-04. The dates are then set by the five non-code chains, each of which the plan underestimates:

| Chain | Plan | Likely | Why |
| --- | --- | --- | --- |
| IRB amendments (PR-03) | 0 weeks or filed W4 | approvals late Jan to Feb 2027 | profiles, vectors, cross-department identified screening and the clinician role are new; monthly meetings; December thin in Japan; late January thin in Taiwan |
| Contracts (PR-14) | signed W6 (12-18) | Feb to Mar 2027 | hospital legal, 個資/資訊室 review, 稟議/院長 signature; a new vendor's master licence is slower than a research agreement |
| CGMH feed (PR-02) | sample W3, mapping W6, real snapshot W10 | structured export Feb to Mar; notes later | the hospital's HIS team must build it; no owner or hours in the plan |
| CGMH B200 quota and platform IQ (PR-05, PR-19) | confirmed in writing W3; IQ 01-11 | quota Dec to Jan; qualification on a rented B200 needed first; IQ Mar | platform team work, security review, MIG configuration, the scan |
| Japan box (PR-15, PR-16) | ordered 11-13, arrives W9 | arrives mid Jan; installed late Jan to Feb | 4–8 weeks lead, 年末年始 in the middle, device registration 2–6 weeks, resizing if PR-16 changes the order |
| Reviewer hours (PR-04) | 13–14 h/week each | 6–8 h/week each | practising physicians, site work, holidays |

Likely dates with the fixes in this review applied:

- **G1** 2026-12-04 (one week late; acceptable).
- **G2 design freeze** 2026-12-18 to 2027-01-08 (identity on a rented box; surveys signed but feeds still unconfirmed).
- **G3 feature complete** late January 2027, with OMOP export, narrative and copy-assist shipping dark under Q-03 as the plan allows.
- **CGMH**: quota and contract February; B200 IQ/OQ **March 2027**; PQ with real patients **April**; full-scope go-live about **2027-04-30**. Reduced scope (structured screening in the PI's department, referral, no profiles or prefill) is possible in the week of **2027-02-15** under the existing approval if the owner signs that scope.
- **Japan**: box installed and IQ in **February**; contract and amendment gate PQ to **March–April**; full-scope go-live about **2027-05-14**; reduced scope early **March**.

If the owner holds 2027-02-09, the only honest version is the reduced scope at both sites, which contradicts "build all, use all" and must be written as a plan change now rather than discovered at G3.

## 5. Completeness against the owner decisions

Every row of the decisions document has a home in the plan; the coverage check in the holistic review (§4, I-01 to I-73) is accurate. Three deviations and two misreadings:

| Decision | Plan | Verdict |
| --- | --- | --- |
| "Data steward: named hospital staff at each site. Aimedics never holds patient data." | Changfu as CGMH steward; agents read real samples | contradicted (PR-08, PR-01) |
| "First hospital box: 2 TB disk and 128 GB RAM" | 256 GB in §1.5, 128 GB in §2 | overridden without a question (PR-21) |
| "Both pilot sites have IRB approval. The site survey confirms that each approval covers whole-hospital screening and patient profiles." | CP-4 "0 weeks if covered" | misread as "covered"; the decision says "confirm" (PR-03) |
| "Go-live within 3 months, real patients screened at both sites" and "as complete as possible" | §4.4 fallback "start with the least: charts pasted and sheets" | the fallback quietly drops whole-hospital screening (PR-02) |
| "The CGMH B200 server is shared with other work ... fixed GPU quota" | "share of SMs or MIG slice" accepted in the survey | a time-slice is not isolation for PHI; the decision needs MIG or a whole GPU (PR-05) |

Correctly carried, and worth saying: the CRC records the doctor's answer; warnings not gates for IRB/ICF; opt-out by the office; inputs-only for pharmacy, TMF and invoicing; printed card and `.ics`; the restricted clinician view with the flag off; abstain under 95 %; nobody edits the narrative; study patients first at night; 7 of 10 for gap rules; the default embedder with the alternative-embedder test; consortium defaults (k = 5, ±180 days, no quotes, no vectors, signed counts, registry at CGMH); SNOMED quote now; Study A thresholds; the business model; Q-05 to Q-27 as accepted.

## 6. Regulatory and validation adequacy

- **GAMP 5**: the category table (§7.1) is right, including the hospital platform as category 1/4 with a supplier assessment. The strategy (§7.2) is right in principle. What is missing is the discipline around it: a signed VMP before execution, a frozen release before OQ (PR-07), independent execution and witness (PR-08), real-data PQ endpoints (PR-09), a periodic review, a vendor assessment pack the hospital can file (PR-35).
- **Part 11 / ER/ES**: WS-07.4 covers signature manifestation, re-authentication, reason for change, record lock, audit export. Missing: the sponsor's acceptance that the system is in the chain (PR-11); an idle lock on shared terminals; a stated policy on the model's draft as an "electronic record" (keep every draft with its fate, which the plan does) and on who owns the REDCap token (survey Q39 asks; the plan should say the site's REDCap admin, never a shared token).
- **IEC 62304-light and ISO 14971**: appropriate for a non-device; the five records exist as a plan item. The risk file lacks the rows in PR-33. Residual acceptance at G6 by the owner alone is weak; the site PIs should co-sign RSK-01, RSK-08 and RSK-19.
- **Intended use / SaMD**: the two-question logic (intended purpose as presented; harm on malfunction) is correctly applied in the source review. The statement is undermined by the product's own "excluded" vocabulary (PR-12). The restriction of setpoints and gaps is right. The 該当性 consultation and TFDA inquiry are "requests sent" by readiness review, so go-live happens on a reasoned position without a written view; acceptable for the research-use layers, provided the statement and the UI say the same thing.
- **APPI / PDPA**: §9.3 is a good mapping. Gaps: the agent exposure (PR-01); 去識別化 vs 假名化 (PR-13); the legal basis for the PI's cross-department identified view must appear in the IRB approval text (PR-32); PDPA Art. 27 security plan at the hospital must be amended to include TrialBox (holistic 02 says so; the plan does not list it as a site task); Japan's 利用目的 publication by the hospital may need an update for research-support processing by a 委託先 (ask in the survey).

## 7. The shared B200 at CGMH

The plan's controls (own namespace, network policy, encrypted volume, root holders named, isolation tests at IQ and after patches, serving record on the quota, quota change as CC6, supplier assessment) are the right list. Four of them are not yet real:

1. *Qualification on the hardware*: never run before IQ (PR-05).
2. *Quota type*: "share of SMs" is time-slicing; only MIG or a whole GPU isolates memory. Specify MIG.
3. *Key custody*: no TPM equivalent; the platform team can read the KEK (PR-10).
4. *Verification vs attestation*: storage encryption and root logging are the platform's word (PR-19).

Also unowned: who pays for and schedules GPU time if the quota is cut during a hospital incident; what the night window is when neighbours run (five nights, not one); what happens when the hospital patches the driver on a Friday (the canary re-run needs someone to read it: name the on-call). Accountability: the hospital operates the platform and is the controller; Aimedics supplies images and checks; the 責任分界 sheet must say in one line who is called first when the morning mail does not arrive.

## 8. Testability: the vague ones

Listed in PR-24. Two more patterns: "as WS-10.x" (WS-11.3 to WS-11.6) inherits criteria that mention Japanese artefacts (SS-MIX2, JLAC10) and should be rewritten for CGMH (NHI order codes, ROC dates, mixed-script notes); and the G1 criterion "false exclusions 0" is on synthetic planted truth, which is right for a gate but must not be quoted to a site as evidence of accuracy (RSK-34).

## 9. Site survey and IT security pack: would a hospital accept them?

**Survey**: the English form is better than most vendors' and asks the right data-feed questions (encodings, era and ROC dates, JLAC10, NHI codes, 疑い, opt-out source, provider field). It would be accepted as a draft. It would come back with: patient and data volumes (PR-16); a request for the ja/zh-TW versions as fillable tables (PR-29); who from the vendor will be on site; and the question "what is the legal basis for a PI viewing other departments' identified records" (PR-32).

**IT pack**: strong on network, supply chain, backups and the shared-host split. It would be accepted as a draft and come back with the list in PR-30 (RPO/RTO, SIEM, session controls, Windows patching, vendor people, AI in development). A privacy office in Taiwan would stop at 去識別化 (PR-13). A 医療情報部 would ask for the 開示書 before, not with, the pack.

**Faithfulness**: the ja and zh-TW IT pack sections are complete and faithful apart from PR-13 and small omissions (SMO in §C.4). The ja and zh-TW survey sections are complete in question count but abridged in several answers and contradict the plan's dates in Q68 (PR-29).

## 10. The biggest threats to a safe go-live

1. **Wrong exclusion of a real patient** on a feed and a model never measured on that site's notes (PR-09), with the only pre-go-live real-data check being ten patients and a weekly sample of ten; mitigated only after Study A reports. The fix is the 100-chart dry run per site before any excluded list is shown.
2. **Missed or late SAE report** from reliance on a reminder with a site rule entered once and no system of record stated (PR-17).
3. **Privacy breach before go-live** through site data in agent sessions or the repository (PR-01), and the cross-department identified candidate view without the exact IRB wording (PR-32).
4. **Platform insiders** reading the pid map through the KEK on the shared host (PR-10).
5. **Data integrity**: model-drafted values confirmed by a fatigued CRC into REDCap with a Part 11 signature that certifies the fatigue (PR-09); the OMOP flag flipped at the site during IQ (PR-07).
6. **Operational**: first week of real use with holiday staffing at CGMH (PR-06).

## 11. Questions the owner must answer

1. Where may real site data be processed, and may any agent session, repository or log ever contain it? (PR-01)
2. Who at CGMH builds the HIS export, by when, and in what tiers; and is a reduced-scope go-live acceptable if tier 2 or 3 is late? (PR-02)
3. Will you file IRB amendments at both sites now, before the survey answers come back? (PR-03)
4. How many review hours a week can you and Makoto really give through January, and may the safety-core engineer be two days a week? (PR-04)
5. May Aimedics rent a cloud B200 for the qualification run in W3–W5, and will CGMH grant a MIG instance rather than a time-slice? (PR-05)
6. CGMH go-live before 01-20 or after Lunar New Year (week of 02-15)? (PR-06)
7. Who is the CGMH steward, if not you? (PR-08)
8. Will prefill be enabled for sponsor studies only after the sponsor's written acknowledgement? (PR-11)
9. 128 GB or 256 GB for the Japan box, and 2 × 2 TB or 2 × 4 TB given "all history" and an unknown patient count? (PR-16, PR-21)
10. Should the PI's candidate view show identifiers before the treating physician agrees, or only after? (PR-32)
11. Which contract instrument does each hospital already have that can carry the data clauses, and who at each hospital owns its signature? (PR-14)
12. Does either site have a GPU private cloud approved for identified patient data today? If not, the fallback is a date slip. (PR-25)
13. If 2027-02-09 is held, do you accept a written reduced scope at both sites, or do you move the date for the full scope?

## 12. Method and limits

I read the plan, the CSV, the two site documents and the holistic master review in full; the owner decisions in full; the regulatory, clinical-operations, platform and full-system reviews in their findings sections; DECISIONS.md by lookup. I checked the code for what the plan says exists (the wave 1 merge is on master; `tools/network_sheet.py`, `tools/serving_config.py` and `tools/acceptance.py` exist; `authz.py`, `tb_common/{dates,encoding,phi}.py`, `trialbox.service`, any steward role, pgvector or OMOP code do not exist yet, which matches the plan's "open" status; the console has five roles behind trusted-header SSO). I summed the Size column and cross-checked every ID in the CSV by script. I did not verify hospital-specific facts (CGMH's platform, either IRB's calendar, either hospital's contract process) beyond general knowledge of how Japanese and Taiwanese hospitals work; where I estimate lead times I say so and they should be confirmed by the site contacts in W1.
