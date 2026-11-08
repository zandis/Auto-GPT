# How clinical-trial sites in Japan and Taiwan work, and what they need from TrialBox

Field research from public sources, 2026-11-08. Written for the TrialBox owner and builders. Plain English, short sentences. Every claim is tagged: **[S#]** Japan source, **[T#]** Taiwan source, **[G#]** global source (see §9), **(inferred)** = my reading of the evidence, not a measured fact. Nothing here was collected from the two first sites; §8 is the guide for doing that.

---

## 1. The ten things that matter most for TrialBox

1. **The CRC is the user, and in Japan the CRC is usually not a hospital employee.** SMO-employed CRCs now outnumber in-house CRCs (survey: 1,687 SMO vs 1,182 hospital respondents) [S3]. SMO support covers 37% of trials at national university hospitals and 54% at private universities (2023, up from 22% and 44% in 2018) [S2]. An SMO CRC gets a view-only EMR ID per trial, issued about two weeks after application, sometimes one card per trial [S9]. TrialBox accounts must fit this: study-scoped, time-limited, issued by the site, not by Aimedics.
2. **CRCs are overloaded and clerical work drives them out.** Japan: ~6,000 CRCs, 90% women, 30s–40s, turnover 12–15% at SMOs, 7–9% in-house; top exit reasons are "job was mostly paperwork", pay, life events, no career path [S3][S4]. Taiwan: research nurses work ~10 h/day; ~6 h direct care, then ~100 min paperwork, 85 min data handling, 60 min carrying documents between departments [T1]. Anything TrialBox adds must visibly remove a bigger task (this matches TB-DS-17's one rule).
3. **Pre-screening today is a person reading charts one by one.** Japan: doctor or CRC checks each chart against the protocol [S14]. Taiwan: one study nurse read ~2,000 charts to enrol 14 patients against 20–30 criteria [T8]. Trials miss targets: ~80% of Japanese trials failed to enrol on time and about half of sites missed promised numbers (2017) [S10]; Taiwan "often cannot deliver the promised number" and is treated as a back-up country [T7]; recruitment difficulty and slow start-up are the two reasons multinationals skip Taiwan (IRPMA, Mar 2026) [T6].
4. **Nobody will accept a tool that excludes a patient on its own.** Every Japanese AI pilot (Kindai/NTT Data, Nagoya-Gifu/Fujitsu, Osaka/Ubie) ends with "the doctor or CRC makes the final judgement" [S14][S15][S16]. Fujitsu's pilot found 42 candidates of which 27 were eligible (64% precision) [S15]. The two-model agree-to-exclude rule and the "needs information" bucket are the right shape. Show the quote, the date, the criterion.
5. **The hospital network is closed, and the box must be installed as a hospital device.** Japan's 3省2ガイドライン (safety management guideline 6.0, May 2023; 7.0 reported June 2026) bans BYOD in principle, restricts unapproved software, and requires only permitted devices on the network [S22]. NCC: brought-in terminals "cannot connect to the hospital LAN" unless registered as a new hospital terminal with the hospital's security software and a device security form [S24]. Kobe University blocks all external memory on EMR terminals [S23]. Taiwan: hospitals are critical infrastructure under the 2019 Cyber Security Management Act; research-project equipment is a named blind spot; vendor USBs must be scanned and logged; vulnerability scans gate go-live [T17]. Budget weeks, not days, for IT approval, and ship a one-page security sheet in ja/zh-TW.
6. **Data arrives messy and local.** SS-MIX2 exists at ~1,766 facilities (Mar 2025) but quality is uneven: missing standard codes, unmapped department masters, date gaps, vendor "HL7 wording drift"; one hospital matched only 138 of 323 fields [S21]. Taiwan has "30+ EHR systems", heavily customised; CGMH builds its own HIS [T16]; notes mix Chinese and English abbreviations ("DM c/w HTN") [T8]; NHI dates are 7-digit ROC years (1120315 = 2023-03-15) [T19]; Excel opens CSV as CP932/Big5 and garbles UTF-8 [S26][T20]. D-132's "fix what is safe, ask the rest" is necessary, not optional.
7. **Investigator-initiated studies run on Excel and REDCap, and auditors find exactly the errors TrialBox can prevent.** NTUH's 2022–2024 audits: most IITs use Excel or REDCap, not EDC; teams confuse "source" with the Excel/CRF; source and Excel disagree; teams collect more than the approved protocol; screening logs disagree with actual enrolment [T12]. Consent errors: unapproved edits to the ICF, family signing for a capable patient, missing tick boxes, wrong version [T11]. Japan's PMDA looks for whether the trial can be reconstructed from records; ALCOA is guidance, not a finding, and JP GCP defines source as "what the CRF was based on" [S29].
8. **Consent is slow and family-shaped.** Japanese SOPs: CRC sits in on the doctor's explanation, "family present if possible", give time to think, three-copy consent form, CRC checks dates and version, scans to EMR [S13]. Taiwan: only ~12% of the public say they would join research; trust in the doctor is the main predictor [T10]; family objections cite randomisation and "doctor cares more about the trial" [T10]; proxy consent order is fixed by law (spouse → adult children → parents → siblings → grandparents) [T10]. TrialBox should record contact outcomes with these reasons, and never rush the approach.
9. **Help channels are people, not manuals.** Japanese CRCs get information through their SMO head office, the annual "CRCと臨床試験のあり方を考える会議", and JSCPT newsletters; regional CRCs say information does not reach them [S3][S34]. Taiwan has hospital-run CRN/CRC courses and a small association (TACRN) but no national certification [T5]. CMIC moved participant contact to LINE WORKS because phone and e-mail were slow [S30]. The ask-the-box assistant and remote screen help fit; a printed manual will not be read.
10. **Start small is right, and the first measurable win is time.** Pilots quote time: Fujitsu projects candidate selection at one-third of today [S15]; Kameda/Ubie cut registry extraction time 30% [S16]; NCC cut CSR drafting from 120 to 78 working days [S17]. Sites and sponsors will ask for the same number. Measure CRC minutes per candidate before and after.

---

## 2. Personas

Six people. Names are invented; the facts under them are sourced or marked inferred.

### 2.1 佐藤 由紀 (Sato Yuki), SMO CRC, Japan, 31, nurse background
- **Where:** employed by a Tokyo SMO, placed at a 500-bed private hospital and, two days a week, at a national university hospital [S2][S5].
- **Load:** 5 main trials and 3 as back-up this year; typical SMO CRC carries 4–7 main trials and about two sites [S5]. Overtime 10–40 h/month [S35].
- **Day:** morning clinic: sits in on the PI's explanation to a candidate; checks concomitant drugs; books next visits; afternoon: EDC entry (Rave for one sponsor, Veeva for another), answers CRA queries, updates her Excel screening log; evening: writes the "how consent was reached" note for the case file [S13][S8].
- **Tools:** hospital EMR with a view-only ID issued per trial [S9]; Excel; sponsor EDCs; LINE WORKS for participants where the site allows [S30]; a paper 症例ファイル.
- **IT skill:** confident in Excel filters and EDC screens; has never installed software on a hospital PC and is not allowed to; does not know what UTF-8 is (inferred).
- **Fears:** a GCP finding under her name; being blamed for a missed exclusion; a new system that means one more login and one more place to type the same thing; losing EMR access when the trial contract ends [S9].
- **Goals:** fewer charts to read, fewer phone calls, go home on time, pass the next monitoring visit without reprinting the log.

### 2.2 田中 医師 (Dr Tanaka), PI, neurology, Japan head hospital (a 臨床研究中核病院 or similar)
- **Day:** outpatient clinic 40 patients a session; 3–5 minutes between patients; remembers a protocol only when a CRC flags a patient (TB-DS-17 §1.1, and Kindai's description of today's manual process [S14]).
- **Context:** the hospital's ARO has CRCs but is short of QA, IT, regulatory and statistics staff [S6]; trials have been delayed because no CRC could be assigned [S3].
- **Tools:** EMR; e-mail; the hospital's trial-document system (Agatha at many sites) [S28]; a phone that cannot reach the clinical LAN (TB-DS-17).
- **IT skill:** reads e-mail and PDFs; will not learn a new web app for one study.
- **Fears:** the treating doctor of a candidate not being asked first (主治医の了承); a sponsor feasibility answer that turns out wrong; another system to describe to the IRB.
- **Goals:** a short list before clinic, one tap per patient, counts he can trust.

### 2.3 小林 さん (Kobayashi-san), 治験事務局 and IRB office, pharmacist, Japan
- **Role:** runs the trial office under GCP Article 38; receives IRB applications; keeps SOPs; coordinates with the SMO's office staff; issues EMR view IDs to monitors and CRCs [S7][S9]. The SMO does most contract and billing paperwork at sites it fully supports [S2].
- **Tools:** Excel registers, Agatha for electronic trial documents under the ER/ES guideline and the 2014 notice [S28].
- **IT skill:** good with documents; relies on 医療情報部 for anything on the network.
- **Fears:** an electronic record without an audit trail; a device on the network that 医療情報部 has not approved; a PMDA inspection where a record cannot be reconstructed [S29].
- **Goals:** one approved description of TrialBox for the IRB; one list of who has access and until when; exports in the format the 事務局 already files.

### 2.4 林佳穎 (Lin Chia-ying), 研究護理師 / CRC, CGMH Linkou, Taiwan, 29
- **Employment:** per-project contract ("隨計畫約聘") paid from study budgets; starting pay about NT$31,500/month for a bachelor's [T3]. Nurse licence; GCP certificate; renews training hours because the IRB secretariat checks them [T4].
- **Load:** 4 sponsor trials and 1 investigator-initiated study; ~10 h days [T1]; direct patient care takes most of it, then paperwork and data entry and walking documents to other departments [T1].
- **Day:** opens the HIS to read progress notes (English, abbreviated) and nursing notes (Chinese) [T18][T8]; checks 25 criteria against each chart; phones candidates the PI approved; enters data in Rave for sponsor trials and in Excel/REDCap for the IIT [T12]; prepares a monitoring visit.
- **IT skill:** Excel VLOOKUP level; REDCap data entry; has never seen a CSV encoding option; will phone the vendor or ask a colleague before reading a manual (inferred).
- **Fears:** an audit finding that her Excel disagrees with the chart [T12]; being seen as "just an assistant" [T1]; the contract ending with the grant.
- **Goals:** fewer charts to read; a list of who to call and why; not retyping what is already in the HIS.

### 2.5 陳 醫師 (Dr Chen), attending and PI, rheumatology, CGMH, Taiwan
- **Role:** runs outpatient clinics, two sponsor trials and a disease registry kept in REDCap and Excel. Must be the partner of record for any CGRD request by a university researcher [T14].
- **Context:** a CGRD request needs the training course, IRB approval with the CGRD form, an intranet query matching the IRB scope, then an electronic application reviewed by the Medical Research Department; the statistics centre budgets 40–80+ hours per CGRD case [T14]. Retrospective (pre-application-date) chart data can get a consent waiver; prospective collection needs consent [T15].
- **IT skill:** strong clinically; delegates data work to the CRN or a research assistant.
- **Fears:** a feasibility count that double-counts; using data beyond the IRB scope [T12]; a tool that touches the HIS (CGMH builds and guards its own HIS [T16]).
- **Goals:** registry kept current without retyping; weekly candidates; counts for sponsors in minutes.

### 2.6 鈴木 (Suzuki), 医療情報部 engineer, Japan (Taiwan twin: 資訊室 資安 officer)
- **Role:** applies the 3省2ガイドライン; approves every device and software on the clinical network; keeps the internet-separated segment; manages vendor maintenance access [S22][S24].
- **Rules he enforces:** no BYOD; no unregistered USB; brought-in devices registered as hospital terminals with hospital security software and certificates; Wi-Fi on 5 GHz only at some sites [S23][S24]. Taiwan twin: Cyber Security Management Act levels, CISO, vendor security staff, third-party testing above NT$10M, SSDLC checklist, vulnerability scan before go-live [T17].
- **IT skill:** high, but the EMR is a vendor black box and Windows 10 terminals may be on extended support until 2026–2028 [S25].
- **Fears:** malware from an external device (Fukushima Medical University incident) [S23]; a research device nobody told him about [T17].
- **Goals:** one sheet listing ports, directions, accounts, update path, and what leaves the building (nothing).

---

## 3. Today's workflows, step by step

### 3.1 Japan: a sponsor trial at a hospital with SMO support

1. **Feasibility.** Sponsor asks the site (often via the SMO) for a case estimate. The PI guesses from memory; JPMA found sites "cannot adequately grasp feasible numbers" and achievement rates do not improve [S11].
2. **Contract and IRB.** 治験事務局 (or the SMO's office staff) prepares the IRB package; SMO handles cost calculation, contract drafting and invoicing at fully supported sites [S2][S7].
3. **Access.** CRC and monitor apply for EMR view IDs: after contract, about two weeks before first SDV, about two weeks to issue, view-only, per trial [S9].
4. **Candidate finding.** PI and sub-investigators think of patients during clinic; CRC does カルテスクリーニング against inclusion/exclusion criteria before any explanation [S13]; some sites use the EMR vendor's trial option (patient flag, contraindicated-drug check, visit calendar) [S32]. Candidates of other doctors need the treating doctor's agreement first (TB-DS-17; inferred as common practice).
5. **Approach.** The doctor asks the patient; the CRC arranges a time; "family present if possible" [S13].
6. **Explanation and consent.** Doctor explains; CRC sits in, checks understanding, allows thinking time (被験者検討期間); patient signs, then doctor signs; three copies (chart, office, patient); CRC checks date, signature and version; scans to EMR, files the original, writes the consent-path note [S13].
7. **Screening log and visits.** CRC keeps a screening roster and an Excel visit schedule; ~90% of CRCs do schedule management [S8]; CRC reminds patients by phone, or LINE WORKS where approved [S30].
8. **Data.** CRC transcribes EMR values into the sponsor's EDC; double entry is a long-standing burden; SDV omission rules are not standardised [S27].
9. **Monitoring and inspection.** CRA does SDV; PMDA inspects whether the trial can be reconstructed from source; ALCOA gaps get guidance [S29].

**Time (inferred from the above):** feasibility days to weeks; IRB one to two months; EMR ID two weeks; chart screening hours per clinic day; consent across two visits.

### 3.2 Japan: an investigator-initiated or observational study at a core hospital

1. PI drafts the protocol with ARO help; data manager and biostatistician are scarce [S6].
2. Ethics review under the 2021 life-science/medical research ethics guideline (revised 2023; new revision direction Dec 2025) [S19].
3. For existing-information research, publish the study and offer opt-out instead of consent; prospective observational studies default to consent [S19].
4. Data pulled from the EMR by request to 医療情報部, or from the SS-MIX2 store if the hospital has one; quality checks fall on the research team [S21].
5. Registry kept in REDCap or Excel; exports moved by permitted USB or an internal share only [S23].

### 3.3 Taiwan: a sponsor trial at CGMH

1. **Feasibility.** PI estimates; a formal count needs IRB and a CGRD/statistics request taking 40–80+ hours of analyst time [T14], so most feasibility answers are guesses (inferred).
2. **IRB.** Submitted through the hospital's HRPMS system; team training hours are checked [T4][T14]. The new 31-hospital consortium aims at one-stop joint IRB review [T6].
3. **Staffing.** A research nurse or CRC is hired on the project's budget [T3].
4. **Candidate finding.** The CRN reads HIS charts one by one against 20–30 criteria; progress notes are English with abbreviations, nursing notes Chinese [T8][T18]. No intra- or inter-hospital referral mechanism exists [T7].
5. **Approach.** The attending introduces the trial; the CRN explains and follows up. Public willingness is low (~12%) and depends on trust in the doctor [T10]; family may object [T10].
6. **Consent.** Approved ICF version only; capable patient signs in person; witness must be outside the team; tick boxes left blank count as "no"; proxy consent only if the protocol was approved for it [T11].
7. **Visits and data.** CRN schedules, phones, enters Rave/Veeva; for IITs, Excel or REDCap [T12]; carries documents between departments about an hour a day [T1].
8. **Audit.** Hospital audits find ICF, ISF, CRF-source mismatches, protocol deviations and eligibility problems [T12]; national inspection deficiencies have concentrated in "subject data" [T13].

### 3.4 Taiwan: a registry or observational study

1. IRB application in HRPMS; pre-application-date data may get a consent waiver per the MOHW list; prospective data needs consent [T15].
2. Data from CGRD (de-identified, updated yearly, intranet query within IRB scope, electronic application) [T14], or by request to 資訊室, or by the RA copying from the HIS into Excel.
3. Analysis on a hospital workstation; raw data stays inside [T14].

---

## 4. Pain points, ranked

Rank = frequency × harm, from the evidence. "Daily/weekly/monthly" is how often a CRC or PI meets it.

| # | Pain | How often | How much it hurts | Evidence |
|---|---|---|---|---|
| 1 | Reading charts one by one to find candidates; missing patients in free text | Daily | High: trials miss targets; 2,000 charts for 14 enrolled | [S14][T8][S10][T7] |
| 2 | Double entry: EMR → Excel/REDCap/EDC, then SDV | Daily | High: hours per week; source–CRF mismatches are a top audit finding | [S27][T12][T1] |
| 3 | Too many studies per CRC, clerical load, long days | Daily | High: turnover 12–15% (SMO), 10-h days (TW) | [S3][S4][S5][T1] |
| 4 | Consent paperwork errors (version, dates, signatures, tick boxes) | Weekly | High at audit; low daily | [T11][S13][S29] |
| 5 | Feasibility counts are guesses; formal counts take weeks | Monthly | Medium-high: sites over-promise, sponsors drop the country | [S11][T7][T14] |
| 6 | Getting access: EMR IDs per trial, device approval, closed network | Per study / per install | Medium-high: weeks of delay; blocks tools entirely | [S9][S22][S24][T17] |
| 7 | Messy exports: codes unmapped, dates in era/ROC form, encodings, merged cells | Per import | Medium: silent errors; hours of cleaning | [S21][T19][S26][T20] |
| 8 | Slow, careful approach; family and treating-doctor permission; low public willingness | Per candidate | Medium: candidates lost between flag and consent | [S13][T10][S18] |
| 9 | Screening log and visit schedule kept by hand in Excel/paper; mismatches with reality | Weekly | Medium: audit findings; reprinting for monitors | [T12][S8] |
| 10 | Information does not reach regional or junior CRCs; unclear role; no career path | Constant | Medium: skills vary; tools abandoned | [S3][T1][T5] |
| 11 | Tools that do not fit the workflow (CTMS beside Excel) | Per tool | Medium: parallel systems, more typing | [S31] |
| 12 | Language: sponsor systems in English; local staff need ja/zh-TW wording | Daily | Low-medium: slows entry, raises errors | (inferred from [T8][T18]; UI spec §6) |

---

## 5. Data and IT reality, and what it means for the installer and the import

### 5.1 Japan

**EMR market.** 93.7% of hospitals with 400+ beds have an EMR (2023); Fujitsu claims 56% of 500+ bed sites; replacements every 5–7 years [S20]. Vendors: Fujitsu, NEC, SSI, CSI and others; Tokushukai standardised on one vendor to ease screening [S33]. Some EMRs have a trial option (patient flag, calendar) [S32]. Terminals may run Windows 10 on extended security updates into 2026–2028 [S25].

**SS-MIX2.** ~1,766 facilities with standardised storage, ~1,250 exporting prescriptions and lab results (Mar 2025; 1,114 in 2017) [S21]. Known defects: missing standard codes (JLAC10, HOT/YJ), per-hospital customisations, non-unified department masters, deleted-record flags that differ between old and new HIS, missing discharge dates, dates missing in summaries, vendor HL7 wording drift; one hospital matched 138 of 323 comparable fields. Folder-per-patient layout means heavy disk access for searches [S21]. Encoding: HL7 with ISO-2022 escape switching; half-width kana and rare kanji fall outside base profiles [S26].

**Network and devices.** 3省2ガイドライン; MHLW guideline 6.0 (May 2023), 7.0 (June 2026, one source) [S22]: BYOD banned in principle, unapproved software restricted, only permitted devices connect, zero-trust added to network separation. Analysis terminals have no internet; results move by password-protected USB only [S23]. Brought-in devices: register as a hospital terminal, install the hospital's security software, submit a device security form (NCC); forms ask OS, browser, P2P software; certificates for Wi-Fi (Wakayama) [S24]. Approval time is not published; two to six weeks is a reasonable planning figure (inferred from [S9][S24]).

**Records rules.** ER/ES guideline (2005) and the 2014 notice on electronic trial documents: audit trail, access control, CSV-validated systems or documented procedures, tamper evidence (PDF, hash) [S28]. PMDA inspects reconstructability; JP GCP "source" = what the CRF was based on [S29].

**Encodings and formats.** Japanese Excel opens CSV as CP932; UTF-8 without BOM garbles [S26]. Era dates (S/H/R + yy.mm.dd) appear in exports; era boundaries (2019-05-01) trip converters [S26 note]. Full-width digits and half-width kana are common (inferred, D-132).

### 5.2 Taiwan

**HIS.** MOHW: more than 30 EHR systems in use, highly customised, hard to integrate; a 2024–2028 next-generation EHR programme with trial runs at Mackay, CGMH and Chung Shan; goal to merge 19 medical centres' HIS into 4–5 versions [T16]. CGMH builds its own: 資管部 ~135 staff (2012), low-code form editor for hundreds of chart forms, HIMSS EMRAM Stage 7 (2019, 2023), self-built telemedicine software with servers in-house [T16]. Taichung Veterans has a 100-strong in-house IT team [T16]. Expect no public API; expect CSV or view exports negotiated per project.

**CGRD.** De-identified, updated yearly; access requires training (course G3S0RS230001), an attending as partner, IRB approval with the CGRD form, intranet queries within IRB scope, and an electronic application reviewed by the Medical Research Department; statistics centre estimates 40–80+ hours per case; forms ask campus, period and ICD/procedure codes [T14].

**Security.** Cyber Security Management Act (2019); hospitals as critical infrastructure must have a CISO; research-project equipment is a named blind spot; NHI VPN PCs separated from the internet; vendor USBs scanned and logged; vendors need security staff and third-party testing above NT$10M; SSDLC checklists and vulnerability scans before go-live [T17]. A 2025 case of staff installing unapproved software on hospital PCs was treated as "opening a back door" [T17].

**Data content.** Physician notes in English with abbreviations; nursing notes in Chinese; the 病歷中文化 debate is unresolved [T18][T8]. NHI dates are 7-digit ROC (yyymmdd, 1120315 = 2023-03-15) [T19]. Excel garbles UTF-8 CSV; Big5 and UTF-8 coexist [T20]. ICD-10-CM is used for NHI claims (inferred, widely known).

**IRB and data use.** Retrospective data (before application date) may get a consent waiver under the MOHW list; prospective collection needs consent; hospitals require a chart-use application form [T15]. Pre-screening by chart review is IRB-governed and must respect the PDPA and the Human Subjects Research Act [T8].

### 5.3 What this means for the installer

- **Ship as a hospital device.** Provide, in ja and zh-TW: a device security sheet (OS, patches, antivirus accepted, ports, directions, no internet, no USB after install, update path, who holds keys). NCC's form is the template [S24]. Pre-check accepts Windows 11 Pro/Enterprise and Server 2022+ (D-125); be ready to explain why not Windows 10 ESU [S25].
- **Expect the 医療情報部 / 資訊室 to lead.** The CRC cannot install anything. The installer run is an Aimedics-on-site event with IT present (D-125). Plan two to six weeks of approval before that day (inferred).
- **Offline updates by signed file, with a hash the IT officer can check** [S28][T17].
- **Accounts:** hospital AD/LDAP where offered; study-scoped, expiring accounts for SMO CRCs and monitors, matching how EMR IDs are issued [S9].
- **Audit trail on everything** (ER/ES, Part-11 style) and a printable "what this system records" page for the IRB and the 事務局 [S28][T12].

### 5.4 What this means for the import

- **Detect encoding (CP932, Shift_JIS, ISO-2022-JP, Big5, UTF-8 with/without BOM) and show a preview** before anything is saved [S26][T20].
- **Normalise dates with a visible rule:** era (S/H/R, 昭和/平成/令和), ROC 7-digit and 民國xxx年, slashes/dots, two-digit years; ambiguous D/M go to the check list (D-132) [T19][S26].
- **Normalise width:** full-width digits, letters and spaces; half-width kana to full-width [S26].
- **Excel realities:** title rows, merged cells, one sheet per PI, dates stored as text, patient names in the sheet (must be pseudonymised at import) (inferred, D-132).
- **Codes:** JLAC10/HOT/YJ/ICD-10 in Japan, ICD-10-CM and hospital-local codes in Taiwan; a once-per-site mapping page with "unknown code system" share on the readiness page [S21] (D-131).
- **SS-MIX2 specifics:** expect missing standard codes and department master gaps; read deletion flags; validate counts against the hospital's own totals, as Kyushu does [S21].
- **Free text:** Japanese notes; Taiwanese notes in English abbreviations plus Chinese; the local models must handle both and the review card must show the quote [T8][T18].
- **Source-of-truth rule:** coded hospital data as is; LLM-extracted facts proposed until a CRC confirms (D-131) — this is also what auditors want (source vs transcription confusion) [T12].

---

## 6. Adoption and help: what works

**What makes CRCs and PIs adopt.**
- Perceived clinical value and less workload, not features. Primary-care trial software was accepted where it had "perceived clinical value… and streamlined recruitment processes that minimise workload" [G2]. Harmony: 79% of sites used EHR search *with* other methods, never alone [G1].
- No new typing. Double entry is the thing they already hate [S27][T1].
- A human decides. Every Japanese pilot keeps the doctor/CRC as final judge [S14][S15][S16]; Taiwan's TheAI article says the same [T8].
- Permission from above. 医療情報部 and the IRB must say yes before a CRC can touch it [S22][T17]; the PI must agree before a treating doctor's patient is listed (TB-DS-17).
- Own language. Japanese and Taiwanese CRCs work in ja and zh-TW; sponsor systems are in English and resented (inferred from [T8]).

**What makes them abandon.**
- Alerts that fire for the wrong patients or not at all (BPAs not triggering) [G3]; alert fatigue (TB-DS-17 [C4]).
- A tool beside Excel instead of replacing it: CTMS in Japan sat next to per-project Excel sheets and was "hard to use or under-used" when not embedded in the workflow [S31].
- Integration pain: fragmented EMRs block CTMS integration in Japan [S31]; US-built connectors do not fit Taiwan's self-built HIS [T8].
- Vendor numbers that do not match reality (95% accuracy claims without method) [T8]; pilots that only measured retrospectively [S15].

**What help they use.**
- Japan: SMO head office; peers at the annual CRC conference (25th in 2025, certification credits) [S34]; JSCPT newsletters; the 治験事務局. Information does not reach regional CRCs [S3]. Vendor phone support for EDC (inferred).
- Taiwan: hospital research department courses (CMUH CRN/CRC course, GCP credits) [T5]; IRB office; colleagues; LINE groups among study staff and with patients are common in practice (inferred; no formal rule found [T22]).
- Both: phone the person who installed it; screen-share if allowed. Remote help without patient data (D-132) fits; it must be switched on by the hospital [S22][T17].

**Lessons from earlier tools.**
- CTMS: survived at sponsors, weak at Japanese hospitals; Excel stayed [S31].
- EMR-linked trial options (Fujitsu): flags and calendars, used because they live in the EMR [S32].
- eSource/EMR→EDC: wanted for 20 years; blocked by SDV rules and vendor fragmentation [S27].
- AI pre-screening pilots (2025–2026): all retrospective, all keep a human final step, all report time or precision; none yet reports real-world enrolment gain [S14][S15][S16]. TrialBox should publish both precision and CRC minutes.
- Recruitment platforms: Japan's PRO/ad market grew but is marred by low-credibility "paid trial" sites [S10]; Taiwan launched a national patient-registration matching platform in 2026 [T9]. Neither replaces in-hospital screening.

---

## 7. Requirements for TrialBox

Each item cites the evidence that justifies it. "Must" = without it the first two sites will not use the box.

### Must
| # | Requirement | Evidence |
|---|---|---|
| M1 | Install as a registered hospital device with a ja/zh-TW security sheet (ports, directions, no internet, no USB after install, update path, key custody); IT present at install | [S22][S24][T17] |
| M2 | Study-scoped, expiring accounts for SMO CRCs and monitors; site admin issues them; AD/LDAP where offered | [S9][S2] |
| M3 | No automatic exclusion; two-model agreement plus "needs information"; every criterion card shows quote, date and source | [S14][S15][S16][T8] |
| M4 | Zero double entry for anything already coded: read EMR/SS-MIX2/CSV, read REDCap, pre-fill forms; one tap to confirm | [S27][T1][T12] |
| M5 | Import that detects encoding, era/ROC dates, width, merged cells and title rows; shows a preview; fixes only unambiguous cases; lists the rest | [S26][T19][T20][S21] (D-132) |
| M6 | Readiness page with unmapped-code share and "what's missing" before any list is shown | [S21][T16] (D-131) |
| M7 | Audit trail on every fact and every change; printable record description for the IRB and 事務局; export of source vs confirmed vs proposed | [S28][S29][T12] |
| M8 | Screening log, contact outcomes and enrolment report generated from marks, never typed twice; reasons include "treating doctor declined", "family declined", "patient wants time" | [T12][S8][S13][T10] |
| M9 | Consent record checks: approved version, date order (patient before doctor), witness outside team, tick boxes explicit, proxy only if protocol allows | [T11][S13] |
| M10 | Whole UI, help, templates and assistant in ja, zh-TW and en; dates shown in the site's convention with ISO beside | [T8][T18] (UI spec §6) |
| M11 | Works with charts pasted or uploaded one at a time when no feed exists; says plainly what it cannot do yet | [T16][S21] (D-132) |
| M12 | PI list respects the treating-doctor rule: "Ask treating doctor" item, nothing sent to a patient without a doctor | (TB-DS-17 BD-19; inferred from [S13]) |

### Should
| # | Requirement | Evidence |
|---|---|---|
| S1 | Measure and show CRC minutes per candidate and per enrolment, before and after; publish precision and recall per study | [S15][S16][G1] |
| S2 | REDCap two-way sync with per-field ownership and a conflict list, so IITs can leave Excel | [T12] (plan v4) |
| S3 | SS-MIX2 quality report: counts vs hospital totals, missing codes, deletion flags, department master gaps | [S21] |
| S4 | CGRD/CSV mapping templates in zh-TW for ICD-10-CM, lab names and ROC dates; JP templates for JLAC10/YJ/HOT and era dates | [T14][T19][S21] |
| S5 | One-page IRB description template and a "what the box does with charts" explainer for 倫理審査 / 人體試驗委員會, including opt-out/notice wording for observational use | [S19][T15] |
| S6 | Visit schedule and reminders list (CRC home), exportable to the Excel layout the site uses today | [S8][T1] |
| S7 | Ask-the-box assistant answers "why is this patient listed" and "what do I do next" in the user's language; never edits data | [S3][T5] (D-132) |
| S8 | Remote help switched on by the hospital, screen-only, no patient data, with a visible indicator | [S22][T17] (D-132) |
| S9 | Export in formats sites already file: REDCap CSV, ODM, Excel with the site's columns; PDF with hash for 事務局 filing | [S28][T12] |
| S10 | Signed offline updates with a hash the IT officer can verify and a change note in ja/zh-TW | [S28][T17] |

### Could
| # | Requirement | Evidence |
|---|---|---|
| C1 | LINE WORKS / LINE notification path for CRCs and PIs where the hospital allows (after pilot, D-125 apps) | [S30][T22] |
| C2 | Hook into EMR trial flags where the vendor option exists (Fujitsu) | [S32] |
| C3 | Feasibility report that cites which counts rest on coded vs proposed facts, formatted for sponsor feasibility questionnaires | [S11][T7] |
| C4 | Training mode with the synthetic site and a 20-minute guided first run that earns a certificate CRCs can file for training hours | [T4][S3] |
| C5 | Consortium-ready: export a de-identified site summary for the 31-hospital Taiwan consortium's joint reviews | [T6] |

---

## 8. Interview guide for real sites

### 8.1 English (full)

**A. Who you are**
1. What is your role, who employs you (hospital, SMO, project budget), and how many studies do you support now?
2. Walk me through yesterday. Where did the hours go?
3. Which systems did you log into? Which ones do you like, which do you avoid?

**B. Finding and approaching patients**
4. How did the last three enrolled patients come to you? (clinic, referral, chart search, list from IT)
5. How do you screen charts today? How long per chart? What do you miss?
6. Who must agree before a patient is approached? What happens when the treating doctor is not on the study?
7. How often does a candidate say no, and why? Who else is in the room?
8. How do you keep the screening log and visit schedule? Show me (blank or redacted).

**C. Data and records**
9. Where does trial data live for your sponsor trials? For your own studies?
10. What do you type twice? How long does that take per visit?
11. Have you had an audit or monitoring finding about records? What was it?
12. If I gave you an Excel file from another PI, what usually goes wrong when you open it? (dates, characters, layout)

**D. IT and permissions**
13. Who approves a new PC or software on your network? How long did the last one take? What forms?
14. Can the research PC reach the internet? Can you use USB? How do files move between the EMR and your desk?
15. For external staff (SMO CRC, monitor): how do they get EMR access, and for how long?
16. Which Windows version are the clinic and research PCs on?

**E. Help and adoption**
17. When a system confuses you, who do you ask first? (colleague, head office, vendor phone, LINE group, manual)
18. Tell me about a tool you stopped using. Why?
19. What would make you trust a list of candidates from a computer? What would make you distrust it?
20. If this box saved you two hours a week, what would you do with them? Who must approve before you can use it?

**F. For PIs**
21. How do you answer a sponsor's feasibility question today? How confident are you?
22. What would you want to see before clinic, and on what device?
23. What would you tell the IRB about a system that reads charts?

**G. For IT**
24. Which guideline or law governs an on-site appliance here? What is your checklist?
25. What logs, accounts and update process would you require?
26. What has gone wrong with vendor devices before?

### 8.2 日本語（主要質問）
1. ご所属（院内／SMO／研究費雇用）と、現在担当している試験数を教えてください。
2. 昨日一日の業務の流れを教えてください。時間はどこに使われましたか。
3. 直近で登録した3名の被験者は、どのように見つかりましたか（外来、紹介、カルテ検索、医療情報部からのリスト）。
4. カルテスクリーニングは今どのように行い、1件あたり何分かかりますか。見落としやすい点は何ですか。
5. 患者に声をかける前に、誰の了承が必要ですか。主治医が治験担当医でない場合はどうなりますか。
6. 候補者が断る理由で多いものは何ですか。説明にはご家族が同席しますか。
7. スクリーニングログと来院スケジュールは何で管理していますか（Excel、紙、システム）。
8. 電子カルテからEDCや登録票に「二重に入力」している項目は何ですか。1来院あたり何分かかりますか。
9. 記録に関する監査・モニタリングでの指摘を受けた経験はありますか。
10. 他のPIからExcelファイルを受け取ったとき、開いて困ること（和暦、文字化け、セル結合など）は何ですか。
11. 院内ネットワークに新しいPCやソフトを入れる承認は誰が行い、前回はどれくらいかかりましたか。
12. 研究用PCはインターネットに接続できますか。USBは使えますか。電子カルテのデータはどう運びますか。
13. SMOのCRCやモニターの電子カルテ閲覧IDは、どのように、どの期間で発行されますか。
14. システムで困ったとき、最初に誰に聞きますか（同僚、本社、ベンダー電話、LINE、マニュアル）。
15. 使うのをやめたツールはありますか。理由は何ですか。
16. コンピュータが出した候補リストを信頼できると感じる条件、信頼できないと感じる条件は何ですか。
17. （PI向け）依頼者からのfeasibility照会に今どう答えていますか。外来前に何をどの端末で見たいですか。IRBに何を説明する必要がありますか。
18. （医療情報部向け）院内設置のアプライアンスに適用される規程とチェックリストは何ですか。必要なログ、アカウント、更新手順は何ですか。

### 8.3 繁體中文（主要問題）
1. 您的職稱、聘用單位（醫院編制／計畫經費約聘／SMO），以及目前支援的研究案數量？
2. 請描述您昨天一天的工作。時間主要花在哪裡？
3. 最近收案的三位受試者是如何找到的？（門診、轉介、病歷查閱、資訊室名單）
4. 您目前如何篩選病歷？每份病歷大約幾分鐘？最容易漏掉什麼？
5. 接觸病人之前需要誰同意？若主治醫師不是研究團隊成員會如何處理？
6. 候選受試者拒絕的常見原因是什麼？家屬是否會參與決定？
7. 篩選紀錄（screening log）和回診排程用什麼管理？（Excel、紙本、系統）
8. 哪些資料需要從 HIS 重複輸入到 EDC、REDCap 或 Excel？每次訪視大約花多少時間？
9. 是否曾在稽核或監測中被指出紀錄問題？是什麼問題？
10. 若收到其他主持人的 Excel 檔，打開時常遇到什麼困擾？（民國年、亂碼、合併儲存格、標題列）
11. 在院內網路新增電腦或軟體需要誰核准？上次花了多久？需要哪些表單或資安檢核？
12. 研究用電腦能上網嗎？可以使用 USB 嗎？資料如何從 HIS 傳到您的桌面？
13. 申請 CGRD 或資訊室資料的流程是什麼？最近一次等了多久？
14. 系統遇到問題時，您最先問誰？（同事、研究部、廠商電話、LINE 群組、手冊）
15. 有沒有您後來不再使用的工具？為什麼？
16. 什麼條件下您會信任電腦產生的候選名單？什麼情況下不會？
17. （主持人）您目前如何回覆廠商的可行性評估？門診前希望在哪個裝置看到什麼？需要向 IRB 說明什麼？
18. （資訊室／資安）院內自建設備適用哪些法規與檢核表？需要哪些日誌、帳號與更新程序？

---

## 9. Sources

Access date for all: 2026-11-08. "Sourced" = the claim is in the document. "Inferred" items are marked in the text and have no row here.

### Japan [S]
- **[S1]** 日本SMO協会, 「日本SMO協会データ2024（2025年4月実施）」, jasmo.org/assets/pdf/about/data2025.pdf. 22 member companies; SMO staff 4,106; CRC 3,138; 事務局 staff 434; JASMO-certified CRC 1,643; JSCPT-certified 221. Sourced (text layer of the PDF).
- **[S2]** 日本SMO協会 (坂﨑孝平), 厚生科学審議会臨床研究部会ヒアリング資料, 2025-01-29, mhlw.go.jp/content/10808000/001386235.pdf. SMO support share 2018→2023 by hospital type; full-support scope; small-n hard trials raise burden. Sourced.
- **[S3]** 日本臨床薬理学会 認定CRC制度委員会 (渡部歌織), 「本邦におけるCRCを取り巻く状況について」, 厚生科学審議会臨床研究部会 資料4, 2026-03-26, mhlw.go.jp/content/10808000/001679114.pdf. 3,129 responses, ~50% of ~6,000 CRCs; 1,687 SMO vs 1,182 hospital; 90% women; licence holders 2,669/460; 72% of hospital CRCs no career ladder; rotation and fixed-term problems; trials delayed for lack of CRC; information gap in regions; call for DX. Sourced.
- **[S4]** CRCばんく, 「治験コーディネーター（CRC）の離職率と退職理由」, crc-bank.com/crcnorisyokuritsu, data to Nov 2026. SMO 12–15%, in-house 7–9%; reasons. Secondary source citing JASMO 2022 data.
- **[S5]** CRCばんく, 「院内CRCとSMOのCRCの違い」, crc-bank.com/innaicrctosmocrcnochigai; CRCJOB, crcjob.jp/innai-smo-hikaku. ~2 sites, 4–7 main trials/yr (8–14 with sub). Private site, method not stated.
- **[S6]** 厚生労働省 臨床研究部会 参考資料 (2024-08), mhlw.go.jp/content/10808000/001285162.pdf (core-hospital staffing: 24 support staff, 3 DM, 2 biostatisticians); 厚生労働科学研究 分担報告 202506019A (2025), mhlw-grants.niph.go.jp. CRC adequate; QA/IT/regulatory/stats scarce. Sourced.
- **[S7]** 獨協医科大学 治験管理室 seminar090425_05.pdf; 岡山大学病院 shiengyoumu_2018.04.pdf; 日本大学 2016 poster; 厚労省 2006 CRC survey s1023-10_010_019.pdf. Office/IRB/CRC division; CRC find office support hard. Sourced.
- **[S8]** 厚生労働省 2006 CRC業務調査, mhlw.go.jp/shingi/2006/10/dl/s1023-10_010_019.pdf. ~90% of CRCs do schedule management, concomitant drug checks, IC assistance, CRF assistance, monitoring support. Sourced (old).
- **[S9]** 大阪国際がんセンター 電子カルテ閲覧ID (2025-07, 2026-01), oici.jp; 国立がん研究センター東病院 ID application pages, ncc.go.jp; 福岡赤十字病院 閲覧ID申請 (2017). Per-trial IDs, ~2 weeks, view-only, one card per trial. Sourced.
- **[S10]** 薬事日報, 「被験者リクルートメントの現状と課題」, 2017-03-29, yakuji.co.jp/entry57222.html. ~30% cost; ~80% late; half of sites miss; 1 in 4 drop out. Sourced (2017 figures).
- **[S11]** 日本製薬工業協会, 「効率的なFeasibility調査方法の検討に関する報告書」, 2016-06, jpma.or.jp. Sites cannot estimate feasible numbers; achievement rate flat. Sourced.
- **[S12]** 総務省 勧告, 「治験ネットワークの機能強化による症例集積性の向上」, soumu.go.jp/main_content/000213391.pdf. Core-hospital 治験実施率 80% target. Sourced.
- **[S13]** 神戸医療センター 治験プロセスマップ 03 (2023-09-19) and 05, kobe.hosp.go.jp; 大阪南医療センター プロセスマップ 002 (2022-03-28) and 004, osakaminami.hosp.go.jp. Chart screening before explanation; family present if possible; 3-copy consent; CRC checks; scan to EMR. Sourced (text extracted).
- **[S14]** NTTデータ, 「リアルワールドデータを活用した治験候補患者抽出の技術検証を完了」, 2026-05-25; 薬事日報 entry135466; DIGITAL X / 医薬通信社 2026-07-02 on 近畿大学病院・中外製薬・NTT (rule-based vs LLM vs hybrid vs doctor/CRC judgement; tsuzumi2). Sourced.
- **[S15]** IT Leaders (impress), 「名大病院と岐大病院、診療データを生成AIで構造化、治験候補患者の選定時間を3分の1に」, 2025-05-23; 富士通 press release 2025-05-23. 1,800 patients, 3 trials, 42 candidates/27 eligible, ~90% recall, time to 1/3 (projection). Sourced.
- **[S16]** PR TIMES: 亀田総合病院×Ubie (cancer registry extraction −30%); 大阪大学医学部附属病院×Ubie (trial criteria prompts on anonymised data; doctor/CRC final judgement). Sourced.
- **[S17]** 国立がん研究センター中央病院 (中村健一), 「臨床試験プロセスにおける生成AIの利活用」, 医薬品開発協議会 資料4, 2026-02-27, cas.go.jp. CSR drafting 97–100% usable, 120→78 working days; TrialGPT 87.3% (foreign). Sourced (text extracted).
- **[S18]** Eubios Journal of Asian and International Bioethics, "Barriers to Informed Consent in Japan" (Asai, 1996) and related; vignette study (60% defer to physician). Older, clinical not trial-specific. Sourced.
- **[S19]** 文科省・厚労省・経産省, 「人を対象とする生命科学・医学系研究に関する倫理指針 令和5年改正について」, 2023-04; 厚労省 「見直しの方向性について（取りまとめ）」, 2025-12-24 (001726329.pdf). Opt-out for existing information; new opt-out definition proposed. 堺市立病院 research centre note on public-health exception. Sourced.
- **[S20]** 一創 column (issoh.co.jp/column/details/18735) citing 厚労省 医療施設調査 2023 (400+ beds 93.7%) and Fujitsu's own 56% claim. Secondary.
- **[S21]** SS-MIX普及推進コンソーシアム, 木村通男 「SS-MIX2の最新の普及状況（2025年度調査）」; 竹之内 「SS-MIX2初級編」 2024-11, 2025-11; 山下貴範・中島直樹 「SS-MIX2の利活用事例とデータ品質管理」 2024-11-21; AMED 「SS-MIX2標準化ストレージのデータ品質改善の試み」 (000142611.pdf). Facility counts, defect lists, 138/323 fields. Sourced.
- **[S22]** 厚生労働省, 医療情報システムの安全管理に関するガイドライン 第6.0版 概要 (2023-05), mhlw.go.jp/content/10808000/001024389.pdf; システム運用編; commentary noting 第7.0版 (2026-06, single source); 3省2ガイドライン explainers (phchd.com, josis365). BYOD ban, software restriction, device allow-listing, zero trust. Sourced; 7.0 date single-sourced.
- **[S23]** 神戸大学医学部 guideline 2022-08-22 (USB ban, terminals block external memory); 厚生労働省 001519888.pdf (analysis terminals no internet; password-protected USB transfer); Nikkei xTECH on 福島県立医科大学 incident. Sourced.
- **[S24]** 国立がん研究センター中央病院, 「network_environment.pdf」 (brought-in terminals; security spec form); 岐阜県総合医療センター form 04.pdf; 和歌山県立医科大学 besshi_jyunsyujikou.pdf; 厚労省 MIST R7_403_a.pdf (allow only permitted devices). Sourced.
- **[S25]** QST病院 仕様書 51742.pdf: EMR terminals on Windows 10 21H1, ESU plan, delivery 2026-09-30. Sourced (one hospital).
- **[S26]** HELICS/JAMI SS-MIX2 spec & implementation guide (2019); SS-MIX2 標準化ストレージ仕様書 Ver.1.2i (2024-05-16); JIS/ISO-2022-JP references; Excel CP932 CSV behaviour (classmethod, freee help). Sourced; era-date export formats inferred from Zoho/Aspose notes and D-132.
- **[S27]** 薬事日報 p=86270 (NTTデータ・ファイザー・国立がん研究センター東病院 EMR→EDC, 2021); 金沢大学 宮本 論文 (PH-PR-MIYAMOTO-K-91); 規制改革会議 2021 on SDV; 日本大学板橋 2013 DM role. Sourced.
- **[S28]** 大分大学 tiken-denjika-4.pdf; 北里大学病院 em_procedure_v2 (2023-06-26); 相模原病院 guidelines (2024-03-19); 水戸済生会 Agatha. ER/ES指針 (薬食発第0401022号, 2005-04-01); 審査管理課事務連絡 2014-07-01. Sourced.
- **[S29]** PMDA 000239711.pdf and 000215549.pdf (inspection viewpoint); 薬事日報 entry28191 (2012, JP vs ICH source definition); CMIC GCP Letter 2016-05. Sourced.
- **[S30]** シミックヘルスケア press release 2022-09-15 (LINE WORKS/LINE for participant contact); 長崎大学病院 CRC_renraku.pdf. Sourced.
- **[S31]** Oracle Life Sciences Japan blog, eClinical series #3 and #4 (CTMS, Excel coexistence); Research Nester / IMARC Japan CTMS market notes (fragmented EMRs). Vendor/market sources.
- **[S32]** 横浜医療センター, 「煩雑な治験業務を電子カルテシステム連携で効率化」 (Fujitsu NMGCP/Standard trial option). Vendor brochure.
- **[S33]** 徳洲会 統一電子カルテ・スクリーニングアプリ page, cs.tokushukai.or.jp. Sourced.
- **[S34]** 島根大学病院 研修報告 (5_kensyuu_2022.pdf etc.); 日本臨床薬理学会 mailmagazine_021 (2025-05): CRCと臨床試験のあり方を考える会議, 25th in 2025, certification credits. Sourced.
- **[S35]** CRCJOB, crcjob.jp/innai-smo-hikaku (overtime: in-house <10 h/month, SMO 10–40 h). Private site.

### Taiwan [T]
- **[T1]** Kao et al., 「臨床研究護理師對臨床試驗之認知與工作概況」, 臺灣醫學 19(2):117–124, 2015-03. 79 CRNs; 10 h/day; 6 h care; 99.6 min paperwork; 85.1 min data; 60.3 min delivering documents; knowledge gaps; unclear role. Sourced.
- **[T2]** 「臨床研究護理師執行臨床試驗角色職責之探討」, 護理雜誌 2015-06 (80 CRNs); NTU theses 2011 (job satisfaction; >61 h/week) and 2013 (work values). Sourced.
- **[T3]** 長庚醫療財團法人 recruitment notices: 嘉義 2024-01 (隨計畫約聘), 高雄 2021-01 (duties; nurse licence/GCP preferred), 林口 2026-01, 基隆 2025-09 (NT$31,520 / 36,050); 高雄市立凱旋醫院 2026 (NT$38,890). Sourced.
- **[T4]** 國軍高雄總醫院 SOP006 (v15, 2023); 醫學研究倫理基金會 course notices (2025–2026); 元智/中國醫 course agendas. 30 h/6 yr + 9 h ethics; IRB secretariat checks team hours. Sourced (institutional SOPs, not statute text).
- **[T5]** 臺中慈濟 2020 slide (TACRN mention); 中國醫藥大學附設醫院 CRN/CRC course 2026-07; CRC competency research (five levels, eight competencies). Sourced; no national CRC certification found.
- **[T6]** 工商時報, 「台灣藥品臨床試驗曝2大瓶頸」, 2026-03-26 (IRPMA white paper; 372 trials 2024; 31-hospital consortium; one-stop IRB). Sourced.
- **[T7]** 台灣醫藥品法規學會 (TSRAP), law-info article id=332, 2019-10-09. Low achievement rate; back-up country; no referral mechanism; 50% KPI proposal. Sourced (2019).
- **[T8]** TheAI學院, 「臨床試驗最貴的不是藥，是找不到病人」, 2026. 2,000 charts/14 enrolled (anecdote); 20–30 criteria; self-built HIS; mixed zh/en notes; IRB/PDPA; vendor claims unverified. Secondary; vendor figures not independent.
- **[T9]** 工商時報, 「新藥臨床試驗收案速度不夠快 台灣首個媒合平台」, 2026-05-20. ~300 new trials/yr; patient-information gap. Sourced.
- **[T10]** Factors influencing the willingness to participate in medical research: a nationwide survey in Taiwan, PeerJ 2018 (PMC5987748) (~12% willing; trust); Cancer Nursing 2011 (87.5% of cancer patients willing; want staff information); NTU thesis on cancer patients' families; 臺北榮總 IRB slide on proxy order. Sourced.
- **[T11]** 臺大醫院倫理中心季刊 第2期, 「受試者同意書簽署常見錯誤案例探討」 (潘映君), 2024-06. Sourced (text extracted).
- **[T12]** 臺大醫院倫理中心季刊 第7期, 「常見稽核發現與改善方案（一）」 (陳玉夏 et al.), 2025-09. Top-5 IIT findings 2022–2024; Excel/REDCap; source confusion. Sourced (text extracted).
- **[T13]** 台灣與美國新藥臨床試驗主持人查核缺失比較 (thesis, data 2001–2011), airitilibrary U0007-1607201200091100. 58.6% subject-data category. Sourced (old).
- **[T14]** CGMH, "CGRD Data Request and Guide", cghdpt.cgmh.org.tw (search summary; page returned 503 on direct fetch); 林口長庚 巨量資料及統計中心 提案表 (40–80+ h); 長庚醫學研究資料庫資料申請表 2026-04-20; IRB新案申請說明 (HRPMS). Shao et al., Pharmacoepidemiol Drug Saf 2019 and Tsai et al. 2017 (CGRD description). Sourced.
- **[T15]** 臺大醫院倫理中心季刊 第1期, 「大數據或病歷研究常見問題案例探討」, 2024; 馬偕紀念醫院 IRB self-evaluation form (MOHW 2012 waiver list). Sourced.
- **[T16]** Taipei Times 2026-04-14 (MOHW: 30+ EHR systems; next-gen EHR 2024–; trials at Mackay, CGMH, CSMU); iThome 153875 (19 medical centres' HIS → 4–5 versions); iThome 161758 (CGMH low-code forms), 144016 (CGMH telemedicine in-house); CGMH 2012 e-signature slide (資管部 ~135 staff); CGMH journal (EMRAM 7, 2019/2023); HealthTechX on TCVGH 100-strong IT team. Sourced.
- **[T17]** iThome 130157 (資安法 in hospitals, 2019), 148548 (CISO), MOHW IT director on research equipment blind spot; 衛福部 基層醫療院所資安防護參考指引 2020-08-17 (VPN PC separation; vendor USB scan/log); 國家資通安全研究院 templates (vendor security staff, third-party testing ≥ NT$10M, SSDLC); NTNU vulnerability-scan acceptance note; UDN 2025 (unapproved software "back door"). Sourced; primary-care guide is not binding on medical centres.
- **[T18]** 遠見 「病歷中文化立意好」; 慈濟 「如何指導與修改病歷書寫」 (2023) (telegraphic English acceptable); 關鍵評論 and UDN commentary. Sourced.
- **[T19]** 健保署 申報格式 documents (7-digit ROC date: yyy mm dd, zero-padded). Sourced.
- **[T20]** Splunk community thread on Big5/UTF-8 CSV in Excel (generic). Sourced, weak.
- **[T21]** iThome 172898 (NTUH GenAI; heart-failure screening tool for case managers); UDN 9152553 and MOHW press (AI impact research centres 2024). Sourced.
- **[T22]** No Taiwan rule on LINE for participant contact found; US IRB guidance (UW-Madison, AdventHealth) used as reference. LINE prevalence is inferred.

### Global [G]
- **[G1]** Trials 2021, "The use of electronic health records for recruitment in clinical trials: Harmony Outcomes EHR Ancillary Study" (PMC8287813). 79.4% use EHR search with other methods; barriers. Sourced.
- **[G2]** BMC Family Practice 2021, "Challenges to implementing electronic trial data collection in primary care" (Runny Ear). Sourced.
- **[G3]** J Clin Transl Sci 2025, "Root cause analysis of barriers and facilitators to accrual to a pragmatic, EHR-embedded clinical trial" (BPAs not triggering). Sourced.
- **[G4]** WCG 2024 site survey as summarised by Clinical Trial Vanguard (59% of sites lose patients to process inefficiency; 852 sites). Secondary.
- **[G5]** Frost & Sullivan / Novotech white paper (2017) citing 2013 analysis: ~57% of trials fail from low accrual. Secondary, global.

### Local TrialBox documents used for framing
- `trialbox/docs/DECISIONS.md` D-125, D-131, D-132 (2026-11-08); `trialbox/docs/plan/24-plan-v4.md`; `trialbox/docs/plan/design/17-clinical-operations.md` (personas, one rule, BD-19); `09-ui-ux-spec.md` (§6 language/dates).

### Gaps I could not close from public sources
- No official count of in-house vs SMO CRCs per hospital, or trials per in-house CRC in Japan (only private-site estimates).
- No published turnover figure for Taiwanese research nurses; only job-satisfaction surveys.
- No published IT-approval lead time for a vendor appliance at a Japanese or Taiwanese hospital.
- No Taiwanese IRB guidance on LINE for participant contact.
- No Taiwan-wide statistic for the share of trials missing enrolment targets; only qualitative statements (TSRAP 2019, IRPMA 2026).
- JASMO's per-CRC protocol and case charts are images; figures not extracted.
