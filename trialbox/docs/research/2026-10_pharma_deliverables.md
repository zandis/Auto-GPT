# What Pharma Sponsors and CROs Want from a Hospital Site's Data, and How TrialBox Should Report It

*Research brief for TrialBox (on-prem hospital AI for feasibility, pre-screening and trial support from EMR data). Compiled 2026-10-17 from web searches and primary sources. Claims carry URLs. Items I could not confirm against a primary source are marked **[Unverified]**. Vendor capability statements come from vendor marketing and are labelled as such.*

---

## 0. Executive summary

- **There is no industry-standard feasibility report format.** The closest things are TransCelerate's Shared Investigator Platform (SIP) facility/department profile forms, which cover site *capability* rather than patient-data feasibility, ASCO's 2021 call for standardized feasibility questions, and vendor question libraries. CDISC does not publish a feasibility-report standard **[Unverified: none found in searches]**. TrialBox can set its own convention, as long as it borrows from established reporting standards: CONSORT-style flow, RECORD, HARPER and STaRT-RWE provenance, and FHIR/JSON for machine ingestion.
- **What sponsors want from a site is a defensible number and the reasoning behind it.** That means eligible-patient counts per criterion (an attrition waterfall), a realistic enrollment rate with an uncertainty range, demographics that support diversity planning, the competing-trial load, and evidence of the site's past performance. Industry data show why they care: about 11% of activated sites enroll no one and 37% under-enroll ([Fierce Biotech on Tufts CSDD 2013](https://www.fiercebiotech.com/biotech/new-research-from-tufts-center-for-study-of-drug-development-characterizes-effectiveness)).
- **EHR-based feasibility tools converge on the same outputs:** aggregate counts at each site, the impact of each criterion, and demographic splits, all with small-cell suppression and patient-level data kept inside the hospital (EHR4CR/InSite, TriNetX, Deep 6). TrialBox's on-prem model fits this pattern.
- **Recommended deliverables:** (a) Feasibility Packet as PDF/A plus XLSX plus JSON/FHIR; (b) PI Pre-screening Report, internal and identifiable; (c) Monthly Enrollment Report for the sponsor, aggregate only; (d) RWE Cohort Characterisation Report following HARPER and RECORD. Each spec is in Section 5.

---

## 1. Site feasibility: what sponsors ask

### 1.1 Three levels of feasibility

Industry sources describe feasibility as a funnel that runs from broad to narrow ([CASRAI guide](https://www.casrai.org/guides/clinical-trial-feasibility-assessment); [Citeline feasibility-as-a-service](https://www.citeline.com/en/products-services/clinical/feasibility-as-a-service); [Clinical Leader guide](https://www.clinicalleader.com/topic/clinical-trial-feasibility-a-comprehensive-guide)):

| Level | Question | Typical inputs | Who does it | Where a hospital's EMR helps |
|---|---|---|---|---|
| **Protocol feasibility** | Can the protocol be executed at all? Are the criteria too restrictive, the visit schedule realistic, the standard of care compatible? | Epidemiology, RWD criteria impact, KOL input, benchmark trials | Sponsor clinical development, feasibility team | Criterion-level attrition, lab distributions, SoC pathways. TrialBox can run "what-if" criterion relaxation. |
| **Country feasibility** | Which countries? How many sites per country? | Prevalence, SoC and reimbursement, regulatory timelines, competing trials, historical enrollment | Sponsor or CRO feasibility | Limited. A single site's data cannot describe a country. Only possible if a hospital network federates. |
| **Site feasibility** | Can *this* hospital and PI deliver N patients in T months? | Site questionnaire (CDA first), SIP profile, patient counts, staff, equipment, past performance | CRO and sponsor site-selection teams | **This is TrialBox's core.** It supplies EMR-derived counts in place of guesses. |

Some vendors add a fourth term, "strategic feasibility" (country and site allocation plus timelines) ([Clinical Leader](https://www.clinicalleader.com/topic/clinical-trial-feasibility-a-comprehensive-guide)).

### 1.2 What the site questionnaire asks (common fields)

There is **no single standard questionnaire**. Every sponsor and CRO sends its own, which is the main complaint from sites. ASCO's 2021 research statement, from a task force that included sites, sponsors and CROs, calls current feasibility methods "costly, inconsistent, inefficient, labor intensive, and of uncertain effectiveness." It recommends standardized questions with common terminology, a **standardized site capabilities document**, a single point of contact, and one of three process formats: a short questionnaire plus a pre-study visit, a long questionnaire alone, or a visit or teleconference alone (Kurbegov et al., JCO Oncol Pract 2021;17(1):41-51; [ASCO Post summary](https://ascopost.com/issues/march-10-2021/new-research-statement-recommends-streamlining-and-standardizing-clinical-trial-site-feasibility-assessments/); [ACCC summary](https://accc-cancer.org/acccbuzz/blog-post-template/accc-buzz/2021/03/18/applying-covid-19-lessons-learned-to-improve-cancer-care-research); [AACI poster on site burden](https://www.aaci-cancer.org/Files/Admin/CRI/2020/76-Reducing-Burdens-of-Site-Feasibility-Assessments-for-Conducting-Clinical-Trials.pdf)). Industry coverage repeats the point that standardization cuts variability and allows answers to be reused ([Clinical Research News 2023](https://clinicalresearchnewsonline.com/news/2023/08/18/toward-optimizing-site-feasibility-assessment-for-clinical-trials)). Veeva has released a library of "industry-standard feasibility survey questions with common available answers" ([Veeva](https://www.veeva.com/?p=103244)). SCRS supports standardization and has asked for more flexible questionnaires that let sites describe enrollment scenarios ([SCRS](https://myscrs.org/resources/sites-now/site-collaboration-the-importance-of-site-voices)). I found **no published SCRS standard questionnaire**.

**TransCelerate SIP.** TransCelerate's Site Profile Form, a standardized questionnaire for generic site information, was released together with a common GCP training certificate and an investigator CV template ([BioSpace](https://www.biospace.com/b-transcelerate-biopharma-inc-b-takes-steps-toward-common-clinical-trial-site-qualification-and-training)). It now exists as the SIP **Facility Profile Form** and **Department Profile Form**. TransCelerate states that the SIP initiative was "completed as of 2020"; Cognizant now operates the platform, and sponsor adoption is voluntary ([TransCelerate SIP page](https://www.transceleratebiopharmainc.com/initiatives/shared-investigator-platform/); [CASRAI SIP entry](https://www.casrai.org/dictionary/term/shared-investigator-platform-sip)). I could not retrieve the current field list **[Unverified]**.

**Fields that recur across sponsor and CRO questionnaires.** This list is synthesized from the ASCO statement, vendor libraries and practitioner sources. The exact wording varies, and the list is **[Unverified as a canonical set]**:

1. *Site and investigator*: PI and sub-I names, specialties, GCP training date, years of trial experience, number of trials in the indication over the last 3 to 5 years, current active trials, and the PI's time commitment.
2. *Patient population*: patients seen per year or month with the indication; how many would meet the key inclusion/exclusion criteria; the expected number to screen and enroll per month; the source of the estimate (database query or clinical judgment); referral networks.
3. *Competing studies*: open trials at the site that target the same population.
4. *Standard of care*: current treatment patterns; whether the comparator or background therapy is SoC locally; reimbursement of SoC procedures.
5. *Infrastructure*: pharmacy (IMP storage, temperature logging, −20 °C/−80 °C freezers), lab (local or central, certifications), imaging modalities, infusion chairs, ICU, overnight PK beds, IT and eSource.
6. *Staff*: number of coordinators, research nurses, data managers; language capabilities.
7. *Start-up*: IRB/EC type (central or local), meeting frequency, typical approval time, contract and budget turnaround, CDA status.
8. *Historical performance*: enrollment versus target in prior studies, screen-failure rate, retention, query resolution time, audit and inspection findings.

TrialBox can auto-fill items 2, 3 (via ClinicalTrials.gov), 4 and part of 8, all from data. These are the fields where sites today mostly guess.

### 1.3 Data-driven feasibility from EHR/RWD: what the platforms show

| Platform | Architecture | Outputs shown (per public material) | Source |
|---|---|---|---|
| **TriNetX** | Federated network of HCO EHRs; users see aggregate counts only | Eligible patient count **per HCO**; "analysis of each criterion's effect on eligibility"; dynamic patient count as criteria change; AND/OR logic strongly affects counts | [TriNetX feasibility page](https://trinetx.com/?p=139332) (vendor); [TriNetX 101 training guide, SC-CTSI](https://sc-ctsi.org/uploads/resources/TriNetX-101-Training-Guide-Dec2024.pdf); [WashU: aggregate counts only](https://docs.intra.i2db.washu.edu/platforms/trinetx/explanations/user-support); [BU training slides](https://www.bumc.bu.edu/ohra/files/2025/04/slides-for-website.pdf) |
| **IQVIA Site Suite: Feasibility** | Connected Intelligence; scenario planning across protocol, country and site | Country and site scenario planning and patient-population insight (no sample output is public) | [IQVIA](https://www.iqvia.com/solutions/technologies/site-suite/feasibility) (vendor) |
| **Medidata Intelligent Trials / Study Feasibility** | Benchmarks from Rave EDC history (vendor cites 27k to 38k+ trials) | Site enrollment percentile rank, enrollment-rank variability, relative trial congestion, enrollment competition per site, AI enrollment forecasts at site and country level, "data minimum threshold" | [Medidata Study Feasibility](https://www.medidata.com/en/clinical-trial-products/medidata-ai/clinical-trial-analytics/); [Top-10 pharma case study PDF](https://www.medidata.com/wp-content/uploads/2024/01/Medidata-Intelligent-Trials-Top-10-Pharma-Case-Study-Nov-22.pdf); [2025 training outline](https://www.medidata.com/wp-content/uploads/2024/07/IntelligentTrials_StudyFeasibility_eLO_ENG_2025.1.0_Mar2025.pdf) |
| **Deep 6 AI** | Installed at the site; NLP over structured and unstructured EHR | Aggregated near-real-time eligible counts per site for sponsors; I/E-based estimated count before IRB; identifiable "Cohort Builder" lists after IRB, for the study team only | [Rutgers CTO](https://clinicaltrials.rbhs.rutgers.edu/?p=19833); [IntuitionLabs profile](https://intuitionlabs.ai/software/data-interoperability-healthcare-ai/clinical-trial-matching-and-cohort-id/deep-6-ai) |
| **EHR4CR / InSite (Custodix, governed by i~HD)** | Distributed queries; "patient level data never leaves the connected hospitals" | Aggregated counts per hospital, released only after approval; **small-count suppression**; full audit trail inside the hospital; criteria coded to ICD-10, ATC, LOINC, SNOMED | [EHR4CR final report](https://www.ihi.europa.eu/sites/default/files/uploads/documents/projects/EHR4CR_summary_final_report.pdf); [Kalra, CIOMS](https://cioms.ch/wp-content/uploads/2018/10/3_DipakKalra_Using-EHRs-for-clinical-research-CIOMS-Tallinn.pdf); [Methods Inf Med 2014 pilot, 11 hospitals in 5 countries](https://www.thieme-connect.com/products/all/doi/10.3414/ME13-01-0134) |
| **OHDSI ATLAS / CohortDiagnostics** (open source) | OMOP CDM | Per-inclusion-rule statistics (bitmask), attrition, incidence, index-event breakdown, characterisation | [CohortDiagnostics GitHub](https://github.com/ohdsi/cohortDiagnostics); [OHDSI forum on outputs](https://forums.ohdsi.org/t/summary-of-output-generated-by-cohortdiagnostics/19291) |

**Accuracy caveat that should go into TrialBox disclosures.** In a 10-trial comparison, EHR4CR counts beat the manual process in 3 trials and were worse in 6, while saving about 7 calendar days ([BMC Med Res Methodol 2015](https://link.springer.com/doi/10.1186/s12874-015-0035-9)). A vendor case study for Deep 6 reported 5,024 structured-data hits that fell to 30 after manual verification ([IntuitionLabs](https://intuitionlabs.ai/software/data-interoperability-healthcare-ai/clinical-trial-matching-and-cohort-id/deep-6-ai), vendor-reported). Sponsors know raw EHR counts run high. TrialBox should report *computable-criteria* counts and *chart-review-adjusted* estimates separately (see 5a).

---

## 2. Analyses pharma values from site RWD

### 2.1 Patient counts per criterion (attrition / waterfall)
This is the central deliverable. Each I/E criterion is applied in protocol order, and the table shows the remaining N and the number excluded at each step. Three views are needed:
- **Sequential attrition**: the order-dependent, CONSORT-style funnel. CONSORT 2025 keeps a participant flow diagram alongside its 30-item checklist ([CONSORT 2025, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11996237/); [PubMed](https://pubmed.ncbi.nlm.nih.gov/40228833/)).
- **Marginal (independent) impact**: the percentage of the base population that fails each criterion on its own.
- **Leave-one-out impact**: how many more patients would be eligible if only this criterion were dropped. This is the most useful view for protocol optimisation. OHDSI's inclusion-rule bitmask makes all three views computable ([OHDSI forum](https://forums.ohdsi.org/t/summary-of-output-generated-by-cohortdiagnostics/19291)).

Also report **"unknown / not computable from EMR"** for each criterion, such as ECOG not documented or a biomarker not tested. Sponsors need to know how much of the attrition is unknown rather than truly ineligible.

### 2.2 Incidence and prevalence
Sponsors need the annual count of *new* diagnoses (incidence: the flow of new patients into the trial window) and the prevalent pool. DARWIN EU studies report age- and sex-stratified and age-standardised incidence by calendar year and data source, as well as point and period prevalence ([EMA catalogue, e.g. EUPAS1000000967 myocarditis](https://catalogues.ema.europa.eu/print/pdf/node/4871); [EUPAS1000000088 prevalence methods](https://catalogues.ema.europa.eu/print/pdf/node/3865)) **[Unverified that each node ID maps to the named study]**. For a single hospital, express these as *patients seen per year at the site* and do not present them as population rates, because the denominator is the catchment population, which is unknown.

### 2.3 Demographics and representativeness (diversity)
- **US regulatory status (as of Oct 2026).** FDORA (Dec 2022) requires Diversity Action Plans (DAPs) for Phase 3 and other pivotal studies. FDA issued draft DAP guidance in June 2024 ([King & Spalding](https://www.kslaw.com/insights/articles/finally-fda-issues-updated-draft-guidance-on-diversity-action-plans-mandated-by-fdora)). The draft was removed from FDA's website in late January 2025 after DEI executive orders ([AJMC](https://www.ajmc.com/view/fda-quietly-removes-draft-guidance-on-diversity-in-clinical-trials-following-executive-order-on-dei); [DLA Piper](https://www.dlapiper.com/en/insights/publications/2025/01/fda-actions-addressing-diversity-in-clinical-trials)) and later reportedly restored under a court order **[Unverified, single secondary source]** ([CASRAI](https://casrai.org/guides/fda-diversity-action-plan-clinical-trials)). The statutory deadline for final guidance (about June 2025) passed without a final version, and the DAP obligation only applies to studies that begin enrolling 180 days after final guidance. So the requirement is **not yet in force**, and as of mid-2026 the guidance remains in draft **[Unverified on FDA's own page; one Feb-2026 source claims finalization and is contradicted by later sources]**. FDA's Report to Congress on DAPs for FY2023–24 is at [fda.gov/media/184768](https://www.fda.gov/media/184768/download). The 2020 final guidance on broadening eligibility criteria still stands ([Arnold & Porter](https://www.arnoldporter.com/en/perspectives/advisories/2020/11/final-fda-guidance-d-and-i-in-clinical-development)).
- **Practical implication.** Global sponsors still plan enrollment by race, ethnicity, sex and age, and they ask sites for the demographic mix of *eligible* patients. TrialBox should report demographics for (i) all patients with the condition at the site and (ii) the eligible cohort, alongside an external reference: national disease epidemiology if the sponsor provides it, or the site's general patient population. Use the categories the sponsor requests (US OMB race/ethnicity categories for US filings) and the local categories elsewhere. Sex and age bands are universal.

### 2.4 Treatment patterns (lines of therapy, Sankey)
Sponsors use treatment patterns to check that the comparator is SoC, that patients actually reach the target line of therapy, and how long each line lasts. Oncology lines of therapy have to be derived with explicit rules: eligible drugs, maintenance, allowed gaps, permissible switches within a line, and setting (neoadjuvant, adjuvant, metastatic) ([Flatiron LOT across geographies](https://resources.flatiron.com/lines-of-therapy-across-geographies-bridging-the-gap-between-clinical-practice-real-world-data); [NSCLC LOT rules paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11588435)). OHDSI's treatment-pathway work showed that about 10% (T2DM) to 25% (hypertension) of patients follow a *unique* pathway. The published sunburst data were rolled up to pathways with at least 11 patients, which is a precedent for applying small-cell rules to Sankey and sunburst charts ([Hripcsak et al., PNAS 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4941483); [OHDSI forum](https://forums.ohdsi.org/t/120-day-period-criteria-treatment-pathways-study/9451)).

### 2.5 Time-to-event (Kaplan–Meier)
Sponsors use time-to-event analyses to choose a control-arm event rate for sample-size assumptions, to check that the site's patients progress or die at rates similar to the planned control, and to estimate the time to reaching an eligibility trigger (e.g., time from 1L start to 2L). KM plots should follow the KMunicate recommendations: a risk table showing numbers at risk, censored and with events at set time points, plus confidence bands ([Morris et al., BMJ Open 2019](https://doaj.org/article/9017b5691ded49cdb67a6b2f0811d85f); [KMunicate R package](https://cran.nics.utk.edu/cran/web/packages/KMunicate/refman/KMunicate.html)).

### 2.6 Lab distributions
Lab cut-offs (eGFR, ANC, ALT/AST × ULN, HbA1c, platelets) are where the trade-off between protocol relaxation and eligibility becomes visible. Show the distribution of the most recent value within the look-back window, with the cut-off line drawn on it. Report the share with *no* value in the window separately.

### 2.7 Standard-of-care pathways
Sponsors want the order of diagnostics, referral and treatment, and the time between steps (diagnosis → biomarker test → treatment start). These timings tell them when a pre-screening window exists, for example whether biomarker results come back before 1L starts.

### 2.8 Competing trials
List the trials currently recruiting at the site and nearby for the same condition, drawn from the site CTMS and from ClinicalTrials.gov. ClinicalTrials.gov API v2 is public and returns JSON with condition, status and location filters ([ClinicalTrials.gov API docs](https://clinicaltrials.gov/data-api/api); parameter names such as `query.cond`, `filter.overallStatus`, `filter.geo` **[Unverified against the official spec in this session]**). Medidata treats "relative trial congestion" and "enrollment competition per site" as first-class metrics ([Medidata case study](https://www.medidata.com/wp-content/uploads/2024/01/Medidata-Intelligent-Trials-Top-10-Pharma-Case-Study-Nov-22.pdf)).

### 2.9 Investigator and site performance
Common KPIs: time from submission to site activation, time from activation to first patient in, enrollment rate per site per month, actual versus forecast enrollment (one vendor source triggers mitigation below 80%), screen-failure rate (one vendor source flags above 50%), retention, and query cycle time ([MCC on-time site initiation, Applied Clinical Trials](https://www.appliedclinicaltrialsonline.com/view/mcc-metric-month-time-site-initiation); [vendor overview](https://omnionlinestrategies.com/blog/five-metrics-cros-use-score-clinical-trial-site-performance)). These thresholds come from vendor blogs and are **not consortium standards [Unverified]**. Tufts CSDD (2013; 150 trials, more than 16,000 sites) found 11% of sites enroll zero, 37% under-enroll, 39% meet target and 13% exceed it ([Fierce Biotech](https://www.fiercebiotech.com/biotech/new-research-from-tufts-center-for-study-of-drug-development-characterizes-effectiveness); [Applied Clinical Trials](https://www.appliedclinicaltrialsonline.com/view/enrollment-performance-weighing-facts)).

### 2.10 Enrollment forecasting
- **Poisson–Gamma (Anisimov & Fedorov 2007, *Stat Med* 26:4958–75).** Each centre recruits as a Poisson process whose rate is drawn from a Gamma distribution. Parameters are fitted by ML or Bayesian methods, and the predictive distribution of time-to-target and recruitment by date comes from closed form or simulation. Extensions cover time-varying rates, interim re-prediction and improved intervals ([arXiv 1912.09790](https://arxiv.org/pdf/1912.09790); [arXiv 1910.07965 interim prediction](https://arxiv.org/pdf/1910.07965); [Bath research portal](https://researchportal.bath.ac.uk/en/publications/modelingforecasting-patient-recruitment-in-multicenter-clinical-t/)). JMP Clinical implements the method ([JMP doc](https://www.jmp.com/support/downloads/JMPC70_documentation/OP_C_PR_0001.html)).
- **Bayesian accrual (Gajewski, Simon & Carlson 2008, *Stat Med* 27:2328–40).** Combines prior beliefs with interim data to produce posterior predictive accrual. Implemented in the R package `accrual` ([PubMed](https://pubmed.ncbi.nlm.nih.gov/17979152/); [CRAN accrual](https://cloud.r-project.org/web/packages/accrual/index.html)).
- **For a single site,** TrialBox can build an informative prior for the site's rate λ from the EMR: (new eligible patients per month) × (historical consent rate) × (1 − predicted screen-fail rate). It then updates the prior with actual screening and enrollment once the site is active. The output is a fan chart showing P10, P50 and P90 cumulative enrollment.

### 2.11 Screen-failure prediction
Retrospective evidence supports this. A Gustave Roussy NLP and random-forest model on consultation notes reached AUC 0.88 on 264 held-out reports, with a projected screen-fail reduction from 39.8% to 12.8% (preprint, retrospective) ([medRxiv 2021.02.07.21249271](https://www.medrxiv.org/content/10.1101/2021.02.07.21249271v1)). A UCSD study found a 34% screen-failure rate across 4,060 oncology enrollment events, with most failures having no documented reason ([eScholarship](https://escholarship.org/uc/item/9kp075hd)). For LLM criterion-level matching, TrialGPT reported 87.3% criterion-level accuracy and a 42.6% cut in screening time in a user study, but it was evaluated on synthetic patients ([Jin et al., Nat Commun 2024](https://doaj.org/article/150fab09d4d54427ae8b7572137e0c9c); [NCBI TrialGPT](https://www.ncbi.nlm.nih.gov/research/trialgpt/)). TrialBox should present screen-fail risk as calibrated probabilities with reasons, and should not present it as a verdict.

### 2.12 Protocol optimisation (Trial Pathfinder, criteria relaxation)
Liu et al. (Nature 2021; 592:629–33) emulated completed advanced-NSCLC trials in Flatiron EHR-derived data (61,094 patients, about 280 clinics). Many lab-based exclusions had little effect on the overall-survival hazard ratio. Data-driven relaxation **more than doubled the eligible pool on average** and lowered the OS HR by about 0.05 on average, and the relaxed criteria included more women and older patients ([RePEc record / Nature](https://ideas.repec.org/a/nat/nature/v592y2021i7855d10.1038_s41586-021-03430-5.html); [Stanford Daily](https://www.stanforddaily.com/2021/04/21/new-ai-model-could-make-clinical-trials-more-inclusive/)). A single site cannot emulate trial effects, because it lacks the numbers and comparators. It *can*, however, deliver the leave-one-out eligibility gain for each criterion and show how relaxation shifts demographics (heat map in 5a). Those are the inputs sponsors' protocol-design teams combine across sites.

---

## 3. Standard report formats and figures

### 3.1 Is there an industry standard for feasibility reports?

**No formal standard exists.**
- **TransCelerate**: SIP Facility and Department Profile forms cover *site capability*. They are not a patient-data feasibility report, and the initiative is closed ([TransCelerate](https://www.transceleratebiopharmainc.com/initiatives/shared-investigator-platform/)). TransCelerate's Common Protocol Template and Digital Data Flow work led to **ICH M11 (CeSHarP)**, which reached Step 4 on 19 Nov 2025. Its EU effective date is 11 June 2026, and FDA has an M11 guidance dated May 2026 ([EMA M11 template](https://www.ema.europa.eu/en/documents/template-form/ich-m11-clinical-electronic-structured-harmonised-protocol-cesharp-template-step-5_en.pdf); [FDA M11](https://www.fda.gov/media/192647/download)). M11 and the CDISC USDM model make **eligibility criteria machine-readable**. TrialBox should ingest them, but they define the protocol, not the feasibility report.
- **SCRS**: advocates standardization but has published no feasibility-report template (searches found none) **[Unverified]**.
- **CDISC**: covers protocol (USDM), data collection (CDASH, ODM) and submission (SDTM, ADaM). No feasibility-report standard was found **[Unverified]**.
- **ASCO 2021**: recommends a standardized *site capabilities document* and standardized questions, but publishes no template.
- **Vendor de facto formats**: TriNetX, Medidata and IQVIA each use their own dashboards.

So TrialBox can define its own format. To be credible it should adopt (i) a CONSORT-like attrition diagram, (ii) RECORD/HARPER-style disclosure of data source, code lists and algorithms, (iii) machine-readable outputs (XLSX with a dictionary, JSON or FHIR).

### 3.2 Typical sections in sponsor-facing feasibility outputs (synthesized)
Cover and version → executive summary (eligible N, monthly incidence, forecast) → data source and window → criteria mapping (computable, partially computable, not computable) → attrition → demographics → treatment and SoC → competing trials → site capability → forecast → limitations → provenance and sign-off. This structure is TrialBox's proposal, synthesized from the sources above, and is not a standard.

### 3.3 Figure types and conventions

| Figure | Use | Conventions |
|---|---|---|
| **Attrition flow (CONSORT-style)** | Sequential I/E application | Boxes running top to bottom; side boxes show "excluded: reason (n)"; the final box shows the eligible N. Follow CONSORT 2025 diagram style ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11996237/)). |
| **Waterfall bar** | Same data as bars | X = criteria in protocol order; Y = patients remaining. Floating bars show the drop at each step. Start and end bars are solid. |
| **Funnel** | Recruitment stages (identified → pre-screened → approached → consented → screened → randomized) | Horizontal bars with stage conversion %. |
| **Criterion-impact heat map / tornado** | Leave-one-out gain | Rows = criteria; columns = metrics (marginal fail %, LOO gain n, unknown %, Δ % female, Δ % ≥75 y). |
| **Sankey / sunburst** | Treatment lines | Nodes = regimen class per line; links = transitions. Suppress links below the threshold and pool them as "Other". |
| **Kaplan–Meier** | Time to event | KMunicate: CI bands plus a risk table (at risk / censored / events). |
| **Forest plot** | Subgroup HRs or proportions | Point plus 95% CI; reference line at 1 (HR) or the overall proportion; n per row. |
| **Map** | Catchment / referral origin | Choropleth by coarse region only. HIPAA Safe Harbor permits only 3-digit ZIPs, and only where the 3-digit area has more than 20,000 residents ([TMA summary of HHS guidance](https://www.health.mil/Reference-Center/Fact-Sheets/2014/10/01/Info-Paper-New-Guidance-on-De-Identification-Methods-under-the-HIPAA-Privacy-Rule); [HHS OCR de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)). |
| **Projection fan chart** | Enrollment forecast | X = calendar month; Y = cumulative enrolled. P50 line; P10–P90 band (lighter P5–P95 optional); target line; actuals overlaid. |
| **Histogram / ECDF with cut-off** | Lab criteria | X = lab value (units); Y = patients or cumulative %. Vertical line at the protocol cut-off; % passing annotated. |
| **Population pyramid** | Age × sex | Horizontal bars for 5- or 10-year bands; bands with small cells merged. |

### 3.4 Accessibility rules for figures
- **WCAG 2.x SC 1.4.11 Non-text contrast**: graphical objects needed to understand the chart (bars, lines) need at least 3:1 contrast against adjacent colours, unless the information is also given another way, e.g. direct labels ([DAISY KB](https://kb.daisy.org/publishing/docs/wcag/non-text-contrast.html); [W3C Understanding 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)).
- Use a colour-vision-deficiency-safe palette such as Okabe–Ito, but check each colour's contrast. Yellow on white fails ([ConceptViz reference](https://conceptviz.app/blog/okabe-ito-palette-hex-codes-complete-reference)). Never encode meaning by colour alone: use direct labels, line styles and markers.
- PDFs should be tagged, with alt text for every figure, i.e. **PDF/UA (ISO 14289-1:2014; -2:2024)**. That standard can be combined with **PDF/A** for archiving ([PDF Association](https://pdfa.org/?p=188324); [Mapsoft overview](https://mapsoft.com/posts/pdf-standards-guide.html)).
- Each figure should have a data table behind it in the XLSX/JSON, which also serves as its text alternative.

### 3.5 Data-protection rules for figures (small cells, rounding)
- **CMS cell-size suppression**: cells containing 1–10 may not be shown, and neither may any value from which a 1–10 count can be derived. Zero is allowed. The rule covers percentages and excluded cases ([ResDAC CMS policy](https://resdac.org/node/1506); [HHS CMS cell suppression](https://www.hhs.gov/guidance/document/cms-cell-suppression-policy)).
- **UK/ONS "10-5 rule"**: suppress counts below 10 and round the rest to the nearest 5 ([ONS SDC methods comparison](https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates/methodologies/comparisonofposttabularstatisticaldisclosurecontrolmethods)). NHS bodies use thresholds of 5 or 7 and round to 5, computing totals from unrounded numbers and then rounding ([NHSBSA SDC protocol](https://www.nhsbsa.nhs.uk/sites/default/files/2020-10/nhsbsa-sdc-protocol.pdf)).
- **EHR4CR/InSite** suppresses small counts inside the hospital before any release ([Kalra, CIOMS](https://cioms.ch/wp-content/uploads/2018/10/3_DipakKalra_Using-EHRs-for-clinical-research-CIOMS-Tallinn.pdf)).
- **HIPAA Safe Harbor**: ages ≥90 collapsed into one band; dates reduced to year; 3-digit ZIP only where population >20,000 ([HHS OCR](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html)).
- **EU**: the EHDS Regulation (EU) 2025/327 creates permits for secondary use, but its secondary-use chapter only applies from **March 2029**. Until then GDPR and national law apply ([Arnold & Porter](https://www.arnoldporter.com/en/perspectives/advisories/2025/03/european-health-data-space-regulation-published); [McCann FitzGerald](https://www.mccannfitzgerald.com/knowledge/data-privacy-and-cyber-risk/ehds-regulation-secondary-use-of-electronic-health-data)).
- **Complementary (secondary) suppression**: when one cell in a row or column is suppressed, suppress a second cell, or show the totals as rounded, so the hidden value cannot be recovered by subtraction. This matters especially for waterfalls, where each "excluded n" equals the difference between two adjacent "remaining" values.

**TrialBox default** (configurable per jurisdiction and per hospital DUA): suppress 1–10, displayed as "<11"; zero shown. Round all other sponsor-facing counts to the nearest 5. Percentages are computed from unrounded values, shown to whole numbers, and suppressed when the numerator is suppressed. Sankey links, KM risk-table cells and map regions follow the same threshold. A KM curve is not drawn for strata with fewer than 20 patients **[TrialBox design choice]**.

### 3.6 Reporting standards for RWD/RWE analyses

| Standard | What it is | What TrialBox borrows | Source |
|---|---|---|---|
| **RECORD** (2015) | STROBE extension for routinely collected data; 13 extra items: code lists, algorithm validation, data linkage, data cleaning, access | Code-list appendix, algorithm validation statement, population selection flow | [PLoS Med / PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4595218) |
| **STaRT-RWE** (BMJ 2021) | Structured tables for RWE study implementation: design diagram, cohort entry, exposure, outcome, covariates, attrition | Structured "implementation tables"; design diagram | [BMJ / PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8489282) |
| **HARPER** (ISPE/ISPOR 2022) | Harmonized protocol template for hypothesis-evaluating RWE, from protocol to report | Section skeleton for the RWE Cohort Characterisation report; version-controlled protocol | [Value Health / PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9771861); [ISPOR](https://www.ispor.org/heor-resources/good-practices/article/harmonized-protocol-template-to-enhance-reproducibility-of-hypothesis-evaluating-real-world-evidence-studies-on-treatment-effects) |
| **FDA RWD: EHR and claims** (final, July 2024) | Data relevance and reliability, variable ascertainment and validation, linkage | Data-fitness section; positive predictive value of phenotype algorithms | [FDA](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/real-world-data-assessing-electronic-health-records-and-medical-claims-data-support-regulatory) |
| **FDA RWD/RWE considerations** (final, Aug 2023) | Data access, transparency, monitoring; RWD for identifying trial participants | Audit trail, sponsor access to patient-level data when needed | [FDA](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/considerations-use-real-world-data-and-real-world-evidence-support-regulatory-decision-making-drug) |
| **FDA RWE non-interventional studies** (draft, Mar 2024) | Design, data source and analysis for observational effectiveness and safety studies | Protocol pre-specification | [FDA](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/real-world-evidence-considerations-regarding-non-interventional-studies-drug-and-biological-products) |
| **ICH M14** (Step 4, 4 Sep 2025) | Pharmacoepi safety studies using RWD; fitness-for-use and feasibility assessments before design | Fitness-for-use checklist | [RAPS](https://www.raps.org/resource/ich-adopts-the-m14-guideline-on-observational-stud.html); [EMA](https://www.ema.europa.eu/et/ich-m14-guideline-general-principles-plan-design-analysis-pharmacoepidemiological-studies-utilize-real-world-data-safety-assessment-medicines-scientific-guideline) |
| **ICH E6(R3)** (Step 4, 6 Jan 2025; EU effective 23 Jul 2025) | GCP with explicit attention to data governance and computerized systems | Validation and audit-trail expectations for systems supporting trial conduct | [Swissmedic](https://www.swissmedic.ch/swissmedic/en/home/news/mitteilungen/einfuehrung-leitlinie-ich-gcp-e6-r3.html) |
| **DARWIN EU outputs** | EMA's OMOP-based network; study reports plus interactive Shiny apps; age- and sex-stratified incidence and prevalence; characterisation | Output shapes: incidence by year, age and sex; characterisation tables; companion interactive viewer | [EMA catalogue example](https://catalogues.ema.europa.eu/print/pdf/node/4730); [OHDSI DarwinBenchmark 2025](https://www.ohdsi.org/wp-content/uploads/2025/10/511-Nika-Ioanna_DarwinBenchmark_2025symposium-Ioanna-Nika.pdf) |

---

## 4. Delivery formats: what sponsor systems ingest

| Format | Purpose | Notes for TrialBox |
|---|---|---|
| **PDF/A-2b or -3b plus PDF/UA** | Human-readable, archivable, signable record (eTMF filing) | PDF/A-3 permits embedded attachments, so the XLSX/JSON can travel inside the PDF ([Mapsoft](https://mapsoft.com/posts/pdf-standards-guide.html)). Whether a sponsor eTMF requires PDF/A is **[Unverified]**, but PDF/A is the safe default. |
| **XLSX with a data dictionary sheet** | Feasibility teams paste numbers into their own models and questionnaires | One sheet per table; a `README` sheet; a `dictionary` sheet (variable, label, type, units, derivation, code list ID); a `suppression` flag column; no merged cells. |
| **CSV + JSON (with JSON Schema)** | Machine ingestion into sponsor feasibility platforms and CTMS | Stable keys; ISO 8601 dates; explicit `suppressed: true` instead of blanks; version and hash. |
| **FHIR R4/R5** | Interoperable criteria and aggregate counts | **Group** with the EBM IG *StudyEligibilityCriteria* profile, or **EvidenceVariable**, to express the criteria. The FHIR spec currently uses Group for populations, while EvidenceVariable handles complex criteria (timing, CQL) ([FHIR EvidenceVariable](https://hl7.org/fhir/EvidenceVariable.html); [EBM IG StudyEligibilityCriteria](https://build.fhir.org/ig/HL7/ebm/en/StructureDefinition-study-eligibility-criteria.html); [FHIR-36794](https://jira.hl7.org/browse/FHIR-36794)). **MeasureReport** (type `summary`) carries the aggregate counts, with stratifiers for age, sex or criterion step ([FHIR MeasureReport](https://build.fhir.org/measurereport); [DEQM summary example](https://build.fhir.org/ig/HL7/davinci-deqm/Bundle-multiple-summ-report.json.html)). **ResearchStudy.recruitment** (target/actual) and **ResearchSubject.progress** handle enrollment tracking in R5 ([ResearchStudy](https://build.fhir.org/branches/master/researchstudy.html); [ResearchSubject](https://hl7.org/fhir/ResearchSubject.html)). HL7 Vulcan's RWD retrieval IG (STU) and the FHIR-to-OMOP IG are relevant for EHR-to-research flows ([Vulcan RWD IG](https://build.fhir.org/ig/HL7/vulcan-rwd/); [FHIR-to-OMOP IG](https://hl7.org/fhir/uv/omop/2025Sep/)). |
| **CDISC ODM (v1.3.2 / v2.0)** | eCRF metadata and clinical data exchange (EHR-to-EDC, eSource) | ODM v2.0 was published in 2023, is not backward compatible, and adds nested ItemGroups **[Unverified details, from a search snippet]**. Earlier work shows EMR → ODM eCRF reporters and ODM↔CDA conversion ([Dugas ODM2CDA, PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4494189/); [eSource standards-based trial, arXiv](https://arxiv.org/pdf/1707.07994)). TransCelerate ran an EHR-to-EDC pilot with Duke (2018) ([Clinical Research News](https://www.clinicalresearchnewsonline.com/news/2021/03/24/data-exchange-standards-are-focus-of-transcelerate-s-esource-initiative)). This applies to trial *support* (data transfer after consent), not to feasibility. |
| **OMOP CDM extracts / OHDSI result schemas** | Network studies (DARWIN EU-style); characterisation | If TrialBox maps to OMOP internally, it can emit OHDSI-compatible aggregate result tables, which RWE groups at sponsors already know how to read. |
| **SDTM / ADaM** | Regulatory submission datasets | Not used for feasibility. Relevant only if TrialBox data feed a regulatory RWE submission, under FDA's RWD data-standards expectations **[Unverified scope]**. |

**What sponsors actually ingest today.** Feasibility teams mostly work in **Excel and PowerPoint**, CTMS and site-selection platforms (e.g., Veeva, Medidata, IQVIA), and portal questionnaires. FHIR ingestion for feasibility at sponsors is rare **[Unverified: no adoption data found]**. Recommendation: lead with PDF + XLSX, provide JSON for automation, and offer FHIR as an interoperability option and future-proofing.

---

## 5. Recommended TrialBox report templates

### Common elements (all four reports)

**Header block:** report type, report ID (UUID), version, protocol ID/acronym, sponsor, site name and code, PI, generated timestamp (ISO 8601 with time zone), data cut-off date, TrialBox software version, model versions, and query hash.

**Provenance and reproducibility block (RECORD/HARPER-inspired):**
- Data source: EMR vendor and modules, date range, refresh date, and the share of patients with structured versus note-only data.
- Criteria mapping: each criterion gets an ID, original protocol text, computable logic (SQL/CQL/FHIR), code lists (ICD-10, SNOMED, LOINC, ATC/RxNorm, with versions), look-back window, NLP or LLM involvement (Y/N), and the validation PPV or sensitivity if known.
- An immutable query log ID that lets the hospital re-run the exact query.
- Human review: who reviewed (role), and when.

**Disclosure block:**
- "Counts are derived from routinely collected EMR data at [site] and reflect documentation, not clinical eligibility. Criteria marked *partially/not computable* require chart review."
- "Aggregate counts only. Cells 1–10 are suppressed and shown as '<11'. Other counts are rounded to the nearest 5. Totals may not equal the sum of their parts."
- "No patient-level data left the hospital to produce this report." (Except the Pre-screening Report, which is internal.)
- AI disclosure: which steps used ML or LLMs, and their validation status.
- Sign-off: Site PI or research office approval before release, per local DUA/IRB policy.

**Privacy controls applied to every figure (unless stated otherwise):** suppression threshold k = 11 (configurable); rounding to 5; complementary suppression; no dates finer than month; ages ≥90 collapsed; geography no finer than a region with more than 20,000 population; every figure is rendered from the *already-suppressed* table, never from raw data; automated disclosure check before PDF export.

**Accessibility controls for all figures:** Okabe–Ito-based palette checked to ≥3:1 against the background; direct labels; alt text generated from the data table; minimum 9 pt font in the PDF; colour never used as the only signal.

---

### 5(a) Feasibility Packet (sponsor/CRO-facing, aggregate)

**Purpose:** Answer the sponsor's feasibility questionnaire with EMR-backed numbers and evidence that can be defended.

**Sections**
1. **Cover and executive summary.** One box shows: eligible patients over the last 12 months (computable criteria); estimated eligible after chart-review adjustment (range); new eligible per month; P50 forecast for the requested enrollment period, with the P10–P90 range; key risks (top 3 limiting criteria, competing trials).
2. **Study and data scope.** Protocol version, criteria list, look-back window, index date definition, EMR coverage.
3. **Criteria mapping table.** One row per criterion. Columns: ID, protocol text, computable (Full / Partial / No), logic summary, code-list ref, data completeness %.
4. **Attrition results.** Tables T1–T3 and figures F1–F3 below.
5. **Population characteristics.** Demographics for the condition population and the eligible cohort (T4, F4).
6. **Clinical profile.** Lab distributions for criteria with numeric cut-offs (F5); disease stage and biomarker testing rates.
7. **Treatment patterns and SoC.** Line-of-therapy distribution (T5), Sankey (F6), time from diagnosis to treatment and to target line (T6).
8. **Competing trials.** Table T7 (NCT ID, phase, sponsor, status, overlap estimate with this cohort, where the overlap is computable).
9. **Site capability.** Auto-filled from the hospital profile (SIP-style fields), plus historical performance in this therapeutic area (T8).
10. **Enrollment projection.** Method, assumptions table (T9) and fan chart (F7).
11. **Protocol optimisation insights (optional, on request).** Criterion-impact heat map (F8).
12. **Limitations, provenance, disclosure, sign-off.**
13. **Appendices.** Code lists; query log; data dictionary; glossary.

**Tables**
- T1 Sequential attrition: step #, criterion ID, description, n remaining, n excluded, % excluded of previous step, n "unknown (not documented)".
- T2 Marginal impact: criterion, n failing alone, % of base.
- T3 Leave-one-out gain: criterion, eligible n if criterion removed, Δn, Δ%.
- T4 Demographics: age band × sex; race/ethnicity (where recorded and requested); with columns for condition population, eligible cohort, and a reference population if supplied.
- T5 Line-of-therapy counts: 1L / 2L / 3L+ in the last 12 months; median duration.
- T6 Care-pathway intervals: median (IQR) days between milestones.
- T7 Competing trials.
- T8 Site history: trials in the TA over 3 and 5 years, enrolled/target, screen-fail rate, median activation time.
- T9 Forecast assumptions: incidence of new eligible patients per month, consent rate, screen-fail rate, activation date, ramp-up, competing-trial share. Each assumption has a source (EMR, site history, or sponsor assumption).

**Figures**

| ID | Figure | X axis | Y axis / encoding | Privacy controls specific to this figure |
|---|---|---|---|---|
| F1 | CONSORT-style attrition flow | — (vertical flow) | Boxes: n remaining; side boxes: n excluded by reason | Suppress or round each box; complementary suppression so that no "excluded" side box can be recovered by subtracting adjacent boxes. If any step drops by 1–10, merge it with the adjacent step and footnote the merge. |
| F2 | Waterfall bar | Criteria in protocol order (categorical) | Patients remaining (count, linear, starts at 0) | As F1; bars labelled with rounded values; suppressed bars hatched and labelled "<11". |
| F3 | Criterion "unknown" stacked bar | Criteria | % of patients: pass / fail / unknown (100% stacked) | Percentages hidden where a segment numerator is <11. |
| F4 | Population pyramid (condition vs eligible) | Count (left = female, right = male) | Age bands (10-year; ≥90 merged into 80+ if small) | Merge bands until each cell is ≥11; no individual-level ages. |
| F5 | Lab-value histogram/ECDF with cut-off | Lab value (units, protocol cut-off marked) | Patients (count) or cumulative % | Bin width chosen so no bin has 1–10 patients; extreme tails pooled into "≤x / ≥y" bins; missing-value share in a caption. |
| F6 | Treatment Sankey (Dx → 1L → 2L → 3L+) | Line stage (ordinal) | Link width = patients transitioning; nodes = regimen class | Links <11 are pooled into "Other / small groups". Regimen classes, not individual drugs, if needed to reach thresholds. |
| F7 | Enrollment projection fan chart | Calendar month from site activation | Cumulative patients enrolled | Model output, so no direct small-cell risk. Inputs are drawn from suppressed aggregates. Bands are P10–P90 (dark) and P5–P95 (light); the target appears as a horizontal line. |
| F8 | Criterion-impact heat map | Metrics: fail %, LOO Δn, unknown %, Δ% female, Δ% ≥75 y | Rows = criteria; colour = diverging scale centred on 0 for Δ; value printed in each cell | Cells derived from n <11 are greyed out as "<11". |
| F9 (optional) | Referral catchment map | Region (choropleth) | Patients per region (binned) | Regions with population >20,000 only; bins ≥11; no point maps. |

**Footnotes (standard):** "Counts rounded to nearest 5; '<11' denotes 1–10. Look-back window: [dates]. Index: [definition]. 'Unknown' = criterion not determinable from structured or note data within window. Chart-review adjustment based on PPV from [validation sample, n, date]."

---

### 5(b) Pre-screening Report for the PI (internal, identifiable, under IRB/local policy)

**Purpose:** Give the PI and study team a ranked worklist of candidates with evidence for each criterion, so they can confirm eligibility and approach patients. This report **never leaves the hospital**. The regulatory basis for identifiable pre-screening (HIPAA preparatory-to-research or waiver, local IRB approval, or the national equivalent) must be configured by the site **[jurisdiction-specific]**. This mirrors the Deep 6/Rutgers model: aggregate feasibility before IRB, identifiable lists only to named study team members after IRB ([Rutgers](https://clinicaltrials.rbhs.rutgers.edu/?p=19833)).

**Sections**
1. Header: protocol, PI, run date, data cut-off, criteria version, model versions.
2. Summary: candidates by status (new this run, under review, approached, declined, screened, ineligible on review), and the upcoming-visit calendar.
3. **Candidate worklist table.** Columns: MRN (masked to the last 4 digits in printed copies), name, age, sex, treating physician, next appointment date and clinic, overall match score (0–1, calibrated), screen-fail risk (low/med/high with probability), number of criteria met / not met / unknown, and a "reason to review" flag.
4. **Per-candidate criterion evidence card.** For each criterion: status (Met / Not met / Unknown / Needs confirmation), evidence snippet with source document, date and link back to the EMR, value and cut-off for labs, and model confidence. This follows the TrialGPT criterion-level explanation pattern ([Jin et al. 2024](https://doaj.org/article/150fab09d4d54427ae8b7572137e0c9c)).
5. Time-window alerts: patients whose eligibility window opens or closes soon (e.g., washout ends, lab re-test due, progression on the current line).
6. Audit: who viewed, exported or changed status (ICH E6(R3) computerized-system expectations; [Swissmedic summary](https://www.swissmedic.ch/swissmedic/en/home/news/mitteilungen/einfuehrung-leitlinie-ich-gcp-e6-r3.html)).

**Figures**

| ID | Figure | X axis | Y axis / encoding | Privacy controls |
|---|---|---|---|---|
| P1 | Pre-screen funnel (this protocol, cumulative) | Count (horizontal bars) | Stages: EMR-flagged → PI-reviewed → eligible on review → approached → consented → screened → randomized | Internal use, so no suppression. If exported to the sponsor, it converts automatically to the 5(c) aggregate rules. |
| P2 | Per-candidate criterion matrix | Criteria (columns) | Candidates (rows); cell = Met / Not met / Unknown, using symbols plus colour | Role-based access. Printing requires a reason and is watermarked with the user and time. Screen view shows initials plus masked MRN by default. |
| P3 | Lab trend sparkline per candidate (criterion labs) | Date (last 12 months) | Lab value, with the cut-off band shaded | Shown in the evidence card only; not exportable. |
| P4 | Upcoming-visit timeline | Calendar date (next 4 weeks) | Swim-lanes by clinic; markers = candidate visits | Internal only. |

**Controls:** minimum-necessary fields; no free-text export by default; automatic expiry of printed lists (e.g., 30 days, policy text); a human must confirm before any status change counts toward the sponsor's numbers.

---

### 5(c) Monthly Enrollment Report for the sponsor (aggregate)

**Purpose:** Replace ad-hoc emails and CTMS re-keying with a monthly, consistent, privacy-safe performance report. It also explains *why* enrollment is above or below plan, using EMR pre-screening data that sponsors normally never see.

**Sections**
1. Header and period (calendar month; data cut-off).
2. **KPI tiles:** enrolled this month and cumulative vs target; screened; screen-fail rate (cumulative); pre-screen → consent conversion; days since last randomization; forecast P50 date to reach target.
3. **Recruitment funnel table (month and cumulative):** EMR-identified, PI-reviewed, approached, consented, screened, screen-failed (by reason category), randomized, discontinued.
4. **Screen-failure reasons:** grouped by criterion ID. This is the feedback loop to protocol teams.
5. **Pre-screen reasons for non-approach:** e.g., patient declined, physician declined, logistics, competing trial. Aggregated.
6. **Forecast update:** Poisson–Gamma or Bayesian accrual model refitted with actuals (method stated; [Anisimov](https://arxiv.org/pdf/1912.09790); [Gajewski](https://pubmed.ncbi.nlm.nih.gov/17979152/)).
7. **Diversity tracking (if requested):** enrolled demographics vs the site's eligible-pool demographics vs the sponsor's goal, presented as coarse categories.
8. **Issues and actions:** site-entered narrative (staffing, drug supply, protocol amendment effects).
9. Disclosure, provenance and sign-off.

**Figures**

| ID | Figure | X axis | Y axis / encoding | Privacy controls |
|---|---|---|---|---|
| M1 | Cumulative enrollment vs plan, with fan chart | Calendar month since activation | Cumulative randomized: actual (solid step line), plan (dashed), forecast P50 (line) with P10–P90 band from the current month onward | Cumulative trial counts are generally shared with sponsors (they receive the CRFs). Apply suppression only to *EMR-derived* stages that the sponsor would not otherwise see. |
| M2 | Monthly funnel (stacked or grouped bars) | Month | Count per stage (identified / approached / consented / screened / randomized) | EMR-identified and approached counts 1–10 shown as "<11"; rounded to 5. |
| M3 | Screen-fail reasons (horizontal bar, sorted) | Count (cumulative) | Criterion ID / reason category | Reasons with <11 pooled into "Other". Never show the reason together with demographics, to avoid re-identification. |
| M4 | Conversion-rate run chart | Month | % approached → consented, % screened → randomized; with a median line | Percentages suppressed if the denominator is <11. |
| M5 | Diversity tracker (dot plot) | % of patients | Rows = categories (sex, age band, race/ethnicity where applicable); dots = eligible pool / enrolled / sponsor goal | Categories with enrolled 1–10 shown as "<11" and dots omitted. Categories merged where needed. |

**Machine-readable companions:** JSON plus a FHIR `ResearchStudy.recruitment` (actualNumber) update and a `MeasureReport` (summary) with funnel stages as populations and month as a stratifier ([FHIR ResearchStudy](https://build.fhir.org/branches/master/researchstudy.html); [MeasureReport](https://build.fhir.org/measurereport)).

---

### 5(d) RWE Cohort Characterisation Report (descriptive RWE; HARPER/RECORD-aligned)

**Purpose:** A descriptive, non-interventional characterisation of a disease or treatment cohort at the site, for medical affairs, protocol design, external-control scoping or HEOR. It does **not** estimate comparative effectiveness unless a full HARPER protocol and statistical analysis plan are approved.

**Sections (HARPER-based skeleton)**
1. Title, registration (e.g., HMA-EMA RWD catalogue / EU PAS if applicable), version history ([HARPER](https://pmc.ncbi.nlm.nih.gov/articles/PMC9771861)).
2. Rationale and research question(s), with the pre-specified objectives.
3. **Data source and fitness-for-use:** EMR description, coverage, completeness of key variables, known biases (referral centre, loss to follow-up). Aligned with FDA's July 2024 EHR/claims guidance and the ICH M14 fitness-for-use concept ([FDA](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/real-world-data-assessing-electronic-health-records-and-medical-claims-data-support-regulatory); [RAPS on M14](https://www.raps.org/resource/ich-adopts-the-m14-guideline-on-observational-stud.html)).
4. **Study design diagram** (STaRT-RWE style): timeline showing the look-back, index date, washout, follow-up start and censoring rules ([STaRT-RWE](https://pmc.ncbi.nlm.nih.gov/articles/PMC8489282)).
5. **Cohort definitions:** entry event, inclusion and exclusion, code lists, phenotype validation (PPV and sensitivity, if done) (RECORD items 6.1–7.1; [RECORD](https://pmc.ncbi.nlm.nih.gov/articles/PMC4595218)).
6. **Variables:** exposures, outcomes, covariates, each with operational definitions.
7. **Statistical methods:** descriptive statistics; incidence rates (per 1,000 person-years, Poisson exact CIs); KM; competing-risk methods where relevant; missing-data handling.
8. **Results:**
   - 8.1 Attrition (flow diagram)
   - 8.2 Baseline characteristics ("Table 1")
   - 8.3 Incidence / period prevalence by year, age band and sex
   - 8.4 Treatment patterns
   - 8.5 Time-to-event outcomes
   - 8.6 Subgroups
   - 8.7 Sensitivity analyses
9. Discussion and limitations (representativeness of a single site; documentation bias).
10. Data protection, governance, ethics.
11. Annexes: code lists, the full RECORD checklist with page references, query log, data dictionary.

**Tables:** T-RWE1 attrition; T-RWE2 baseline characteristics (n (%) / median (IQR), with standardized differences if subgroups are compared); T-RWE3 incidence by stratum (events, person-years, rate, 95% CI); T-RWE4 line-of-therapy summary; T-RWE5 KM estimates at landmark times (6, 12, 24 months) with 95% CIs; T-RWE6 missingness by variable.

**Figures**

| ID | Figure | X axis | Y axis / encoding | Privacy controls |
|---|---|---|---|---|
| R1 | Study design diagram | Time relative to index date (days; negative = look-back) | Bands for washout, covariate assessment, exposure, follow-up | No data, so no privacy risk. |
| R2 | Attrition flow (RECORD/CONSORT-style) | — | n remaining / excluded per step | As F1. |
| R3 | Incidence over time | Calendar year | Rate per 1,000 person-years (log scale optional), with 95% CI error bars; facets by sex or age band | Strata with events 1–10 shown as "<11 events" and the rate not plotted. Strata are merged as necessary. |
| R4 | Treatment-pathway Sankey or sunburst | Line stage | Patients per transition | Links <11 pooled (precedent: OHDSI rolled up to pathways with at least 11 patients ([PNAS 2016 / forum](https://forums.ohdsi.org/t/120-day-period-criteria-treatment-pathways-study/9451))). |
| R5 | Kaplan–Meier (KMunicate style) | Months since index | Survival probability (0–1) with 95% CI band; risk table below (at risk / censored / events at 0, 6, 12, 18, 24 months) | Risk-table cells of 1–10 shown as "<11". Curve truncated where fewer than 11 remain at risk. Strata with fewer than 20 patients are not plotted. |
| R6 | Forest plot of subgroup descriptive estimates (e.g., 12-month KM survival or median time to next treatment by subgroup) | Estimate with 95% CI (HR scale log-transformed if HRs are shown) | Rows = subgroups, with n per row; overall estimate as a diamond or reference line | Subgroups with n <11 omitted or merged. Footnote: descriptive and unadjusted unless stated. |
| R7 | Lab-value distributions (box or violin per subgroup) | Subgroup | Lab value (units), with clinical reference range shaded | Box whiskers set at P5–P95, never min/max (extreme values identify people). Outliers not plotted. Groups with n <11 omitted. |
| R8 | Missingness heat map | Variables | Calendar year; colour = % missing | Percentages only; no small-cell issue unless denominators are <11. |

---

## 6. Implementation notes for TrialBox

1. **Ingest structured protocols.** Parse eligibility from ICH M11 / CDISC USDM where the sponsor provides them, and use FHIR Group / EvidenceVariable (EBM IG) as TrialBox's internal criteria representation. Map each criterion to code lists and computable logic, flag criteria that cannot be computed, and capture a human-approved mapping version.
2. **Use one engine for every report.** Run attrition (sequential, marginal and leave-one-out) from a per-patient pass/fail/unknown bitmask (OHDSI-style), and derive all four reports from the same result tables so the numbers agree.
3. **Disclosure-control layer.** Make it a separate, testable module: threshold, rounding, complementary suppression and dominance checks run before any render. Log what was suppressed in an internal-only audit table.
4. **Express uncertainty honestly.** For eligible counts, show the computable count, a chart-review-adjusted estimate with a range, and the share marked unknown. For forecasts, show P10/P50/P90. Avoid point estimates presented without qualification.
5. **Outputs.** Produce PDF/A-3 (PDF/UA-tagged) with the XLSX and JSON embedded; offer FHIR R4 Bundle export (Group + MeasureReport + ResearchStudy). Track ODM export for eCRF prefill as a separate trial-support feature.
6. **Governance.** Sponsor-facing reports require research-office or PI release approval, and the Pre-screening Report stays internal. Configure jurisdiction-specific thresholds: US CMS-style <11, UK 10-5, and local law elsewhere **[configure per site DUA]**.

---

## 7. Open questions and gaps (for follow-up)
- The current SIP Facility/Department Profile field list (Cognizant SIP site) could not be retrieved **[Unverified]**.
- FDA DAP final-guidance status should be checked on FDA's guidance page before any US-facing claim. Sources conflict.
- CDISC ODM v2.0 specifics, and whether any sponsor ingests FHIR MeasureReport for feasibility today **[Unverified]**.
- ClinicalTrials.gov API v2 parameter names should be checked against the official spec.
- Exact TriNetX, IQVIA and Medidata output layouts are known only from marketing and training material. Request sample reports from those vendors or from partner sites to benchmark TrialBox's format.
