# TrialBox v2 — Landscape, Literature and Brainstorm

Oct 17, 2026 · companion to `spec/v4/`. **Corrections (Oct 2026):** see `docs/research/2026-10_literature_competitors.md` §0, which supersedes this file where they differ. Public sources only; tags: [V] verified against a primary source, [R] reported by
trade press or a secondary source, [U] unverified. Funding and product statements are as of the dates given.

## 1. Summary

1. **Nobody occupies the sovereign, site-side, whole-lifecycle corner.** Hospital-side screening vendors are cloud or
   EHR-marketplace products, mostly US and oncology-first; sponsor platforms went agentic in 2026 but sit outside the
   hospital; EHR vendors build screening into their own EHRs, which does not reach hospitals running their own HIS.
2. **Accuracy is not the moat.** Open baselines (TrialGPT and its 2026 multicentre successor, locally hosted TrialGPT
   variants, TrialMatchAI, Yale's OMOP matcher) are strong and free. Value moves to workflow, integration, local
   knowledge, governance and sponsor-grade outputs.
3. **The funnel leaks after the list.** Yale's deployment screened 98,348 patients, found 825 eligible (0.84 %) and enrolled
   117 (14 % of eligible) [V]; a surgical-oncology pilot found 73.5 % of AI matches did not enroll [V]. Products that stop
   at "list delivered" leave most value uncaptured.
4. **There is randomised evidence that AI pre-screening helps.** In the 2025 JAMA randomised trial (4,476 patients),
   AI-assisted pre-screening identified eligible patients in 20.4 % vs 12.7 % with manual screening, and enrollment was
   1.6 % vs 0.9 %, at a model cost of a few cents per patient [V].
5. **Asia is moving to sovereign, on-prem LLM screening.** NTT, NTT DATA, Kindai University Hospital and Chugai are testing
   the domestic tsuzumi 2 model for trial-candidate extraction (June 2026 – March 2027) [V]; Fujitsu ran a similar pilot
   with Nagoya and Gifu university hospitals [V]; TriNetX and Fujitsu formed TriNetX Japan (February 2025) [V].
6. **Taiwan has tailwinds and no incumbent product.** The Taiwan Alliance of Clinical Trial Centers (32 institutions,
   launched 8 December 2025) runs feasibility through a manual PI-database workflow [V]; MOHW's planned "TNet" calls for
   FHIR exchange plus federated learning to find patients and sites [R]; the NHI data act (December 2025) adds an opt-out
   for secondary use [V]. No Taiwanese LLM pre-screening vendor was found.
7. **Payer and reimbursement logic is unoccupied.** NHI prior authorisation (TWPAS), reimbursement-gated eligibility and
   the standard-of-care vs research billing split appear in no competitor's product.

## 2. Market context

- **Enrollment is the bottleneck.** Tufts CSDD puts centralised-outreach recruitment cost at $143 (vaccines) to $11,392
  (immunology) per patient [R]; moving a site from identification to activation takes about seven months and a delayed
  site can cost more than $25,000 before first patient in [V].
- **Feasibility questionnaires are a burden.** Sites complete about 11 questionnaires and 4 pre-study visits a month; each
  questionnaire takes about 4 hours; 81 % of sites call them redundant and 86 % find them similar across sponsors
  (ASCO/AACI 2020) [V]. In 2025 speakers at SCRS recommended a per-site database to pre-fill them [R].
- **Taiwan.** About 300–400 trials a year (Taipei Times, December 2025) [V]; Chang Gung Memorial Hospital sees about
  2.7 million patients a year and runs 300+ industry-sponsored trials (public release, January 2026) [V]; the Chang Gung
  Research Database covers seven institutions [V]. Since 1 January 2025 approved drug-trial protocols are disclosed on
  the MOHW trial platform [R], a machine-readable source of Taiwanese trial criteria.
- **Regulation.** ICH E6(R3) is in force (EU July 2025, FDA September 2025); ICH M11 structured protocols are effective at
  EMA from June 2026; FDA launched a Real-Time Clinical Trials initiative in April 2026 [R], signalling reward for sites
  that can stream validated EHR-derived signals.

## 3. Competitors by category

### 3.1 Hospital-side EHR pre-screening and matching

| Company | What it does | Deployment | Evidence / funding (public) | Limits for a Taiwanese hospital |
| --- | --- | --- | --- | --- |
| Lind / Lind Asia | Screens every patient against every open study with criterion-level evidence; feasibility; accrual tracking | EHR-embedded, FHIR-native SaaS; on-prem option offered in Asia | ">94 % agreement" on >1,700 criteria, retrospective (press release only; the journal claim could not be verified) [Unverified]; Lind Asia JV with PREMIA announced 27 May 2026 for Taiwan, Japan, Korea, Singapore, Australia [V]; seed $5.5 M [V] | Oncology-first; vendor-operated; revenue shared with partners |
| Triomics | Oncology agents over full records with cited answers; matching (PRISM), pre-charting, registry abstraction | Epic/OncoEMR marketplace; no stated on-prem | $22 M Series B (May 2026) [V]; MSK, MD Anderson, Yale [V] | Oncology only; US-EHR-centric |
| Tempus (Deep 6 AI, TIME) | Just-in-time trial network; EHR mining across ~750 provider sites | Cloud | Acquired Deep 6 (March 2025) [V] | Tied to Tempus ecosystem; US |
| BEKhealth | NLP over EHR; site–sponsor matching | Cloud | AWS Marketplace from ~$6 k/yr for 1–10 practices [V] | US-only |
| Trially | Matching, feasibility and an agentic recruiter (voice/text/email) | Cloud; Epic, athena, Oracle integrations | $4.7 M seed (2025) [V] | US |
| Realyze (Carta Healthcare) | UPMC spin-out matching | Cloud | Acquired December 2024 [V] | US |
| Inato | Site marketplace with AI pre-screening | Cloud | ~$35 M raised [R]; free to sites | Community-site focus; a competitor for site attention |
| Epic | "Evaluate patients for clinical trials" in development, target 2026, not shipped (corrected Oct 2026), Cosmos feasibility, Forward CTMS (early adopters Nov 2026) | Hospital-hosted EHR + Cosmos | [R] | Only for Epic hospitals |
| Oracle Health / Life Sciences | Natural-language cohorting over 122 M+ de-identified records; recruitment services | Cloud | 23 Sep 2026 release [V] | Cloud; US |
| Open baselines | TrialGPT 2.0 (preprint), local TrialGPT (JAMIA 2026), Yale CTPM, TrialMatchAI (*Nat Commun* 2026) | Local | §6 | Need integration, governance and workflow |

### 3.2 Trials-as-a-service networks

Paradigm Health ($78 M Series B December 2025; acquired Flatiron's clinical-research business incl. Clinical Pipe
EHR-to-EDC; technology partner for FDA's Real-Time Clinical Trials proof of concept; co-launched LC-SCRUM-CD in Japan with
the National Cancer Center and PREMIA) [V/R]. Formation Bio and Lindus Health are AI-native drug developers and CROs, not
hospital vendors [R]. Grove AI (voice recruitment) was acquired by Hippocratic AI in January 2026 [V].

### 3.3 Sponsor-side feasibility, site selection and RWD

TriNetX (federated; hospitals receive tools and hardware free, sponsors subscribe; no Taiwanese member found) [V/U];
ConcertAI ACT and Cara agents (2026) [V]; IQVIA.ai unified agentic platform (March 2026) [V]; Medidata Plus (July 2026)
and a Claude connector for Medidata Study Feasibility [V]; Veeva Vault and free SiteVault for small sites, Veeva AI agents
rolling out [V/R]; Advarra Site ID (October 2026) [V]; Citeline/Norstella with the Ella assistant and Atlas platform
[V/R]; H1 [R]. All are sponsor-side and predict from historical or claims data; none reads a Taiwanese hospital's EHR.

### 3.4 EHR-to-EDC and eSource

Paradigm Clinical Pipe (deployed in NRG Oncology trials) [V]; IgniteData Archer (UCLH/AstraZeneca pilot) [R]; Yonalink
(21-centre pilot streamed ~93 % of requested data) [V/R]; HL7 Vulcan FHIR-to-EDC work [R]. All assume FHIR from a major
EHR; Taiwanese hospital HIS integration is open.

### 3.5 Protocol design and simulation

Faro Health ($37.3 M Series B August 2026) [V]; Unlearn (TrialPioneer, January 2026) [R]; QuantHealth ($45 M Series B
August 2026) [R]; Owkin [R]. All sponsor-side; they would value site-level criterion attrition from real hospital data.

### 3.6 Asia-Pacific

- **Taiwan:** TCTC disease consortia [V]; TACTC alliance with manual feasibility workflow and plans for a national
  participant enrollment platform [V]; MOHW TNet plans [R]; MOHW AI centres and a 16-hospital federated-learning PoC [R];
  Taiwan AI Labs / DSFed federated learning [R]; TMU's research database converted to OMOP (4.15 M patients) [V].
- **Japan:** NTT tsuzumi 2 with Kindai and Chugai [V]; Fujitsu with Nagoya and Gifu [V]; TriNetX Japan [V];
  LC-SCRUM-CD [V].
- **Korea:** KoNECT feasibility service (42 hospitals plus regional cancer centres, manual counts) [V]; FEEDER-NET OMOP
  network [R].
- **China:** Yidu Tech in-hospital platform including recruitment [R]; Taimei eClinical [R]; LinkDoc [R].

## 4. Positioning

```
                         SITE / HOSPITAL-SIDE
                                  ^
   TrialBox (target) *            |   Epic AI screening + Forward      Triomics   Lind
   NTT tsuzumi 2 / Kindai *       |   Trially   BEKhealth   Realyze/Carta
   Local TrialGPT, Yale CTPM *    |   Veeva SiteVault   Inato
   Fujitsu / Nagoya-Gifu *        |
  ON-PREM /  <--------------------+------------------------------> CLOUD /
  SOVEREIGN                       |                                 VENDOR-HOSTED
   TriNetX (federated node) *     |   Tempus TIME   Paradigm   ConcertAI   Oracle
   KoNECT / TACTC (manual) *      |   IQVIA.ai   Medidata Plus   Veeva AI   Advarra Site ID
   Yidu Tech (China) *            |   Faro   Unlearn   QuantHealth
                                  v
                         SPONSOR / CRO-SIDE        (* in-hospital or federated data residency)
```

## 5. Feature matrix

● core · ◐ partial / announced / via partner · ○ absent or not found

| Player | Protocol design | Feasibility | Site selection | Pre-screening on EHR | Consent | Enrollment tracking | EHR→eCRF | Monitoring | Safety | Close-out | Payer / NHI | On-prem |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **TrialBox v2 (target)** | ◐ | ● | ◐ | ● | ○ | ● | ● | ○ | ◐ | ● | ● | ● |
| Lind / Lind Asia | ◐ | ● | ● | ● | ○ | ● | ◐ | ○ | ○ | ◐ | ○ | ◐ |
| Triomics | ○ | ◐ | ○ | ● | ○ | ◐ | ◐ | ○ | ○ | ○ | ○ | ○ |
| Tempus TIME / Deep 6 | ○ | ● | ● | ● | ◐ | ● | ○ | ○ | ○ | ○ | ○ | ○ |
| Paradigm | ◐ | ● | ● | ● | ◐ | ● | ● | ◐ | ◐ | ◐ | ○ | ○ |
| Epic | ○ | ● | ◐ | ● | ◐ | ◐ | ◐ | ○ | ○ | ○ | ○ | ◐ |
| TriNetX | ◐ | ● | ● | ◐ | ○ | ○ | ○ | ○ | ◐ | ○ | ○ | ● |
| IQVIA.ai | ● | ● | ● | ◐ | ● | ● | ◐ | ● | ● | ● | ◐ | ○ |
| Medidata Plus | ● | ● | ● | ○ | ● | ● | ◐ | ● | ● | ● | ○ | ○ |
| Veeva | ◐ | ◐ | ● | ○ | ● | ● | ○ | ● | ● | ● | ○ | ○ |
| Yidu Tech | ◐ | ● | ● | ● | ◐ | ● | ● | ◐ | ◐ | ◐ | ◐ | ● |
| Open baselines | ○ | ◐ | ○ | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● |

## 6. What the literature says

Full reference list in §9. Implications adopted in the specification:

1. **LLMs extract and normalise; deterministic rules decide.** A prospective study of 3,804 patients reported F1 0.82 for a
   neuro-symbolic multi-agent system against 0.47 for zero-shot GPT-4 [32]; LLM-generated OMOP SQL hallucinated in
   21–50 % of attempts [6].
2. **Judge one criterion at a time, quote the evidence, verify the quote in code.** Time savings of 42.6 % (TrialGPT
   [13]), 55 % (multicentre successor, preprint [14]), about 75 % and 86 % in other deployments. Patient-level accuracy is
   lower than criterion-level (about 0.65 vs 0.84), so rank by criteria met and route unknowns to coordinators.
   Clinicians found model explanations coherent for 75 % of its wrong decisions [19], so plausibility is not proof.
3. **Randomised evidence:** AI pre-screening raised identification and enrollment without demographic shifts [18].
4. **Feasibility must be a calibrated funnel.** PI forecasts were worse than uninformative (Brier 0.38) [24]; about 19 % of
   phase 2/3 trials fail accrual [25]; data-driven relaxation doubled the eligible pool with little change in hazard
   ratios [52].
5. **Local open-weight models are adequate** when adapted: local TrialGPT 81.8 % sensitivity, 97.8 % specificity [15];
   distilled open models match larger ones for matching [16]. Model self-reported confidence is a poor predictor of
   correctness; use verifier agreement and self-consistency.
6. **Taiwan:** notes are Chinese–English code-mixed; there is no published LLM extraction benchmark on Traditional
   Chinese clinical notes, so TrialBox must build its own evaluation set.
7. **Agents add cost faster than accuracy** (over 10× tokens, over 2× latency for small gains in published comparisons);
   use them to orchestrate typed, logged tools.
8. **EHR-to-EDC:** start with structured domains under a full audit trail; narrative fields as proposals.
9. **Evaluate in stages** (DECIDE-AI early evaluation, then stepped-wedge or randomised, reported with TRIPOD-LLM and
   CONSORT-AI).

Acceptance targets derived from the literature: criteria parse concept F1 ≥ 0.88; criterion-level judgement sensitivity
and specificity ≥ 0.90; patient-level pre-screen sensitivity ≥ 0.80 with PPV ≥ 0.70; 100 % of quotes string-verified;
coordinator time −40 %; subgroup F1 gap ≤ 10 points; structured eSource agreement ≥ 95 %; feasibility forecast calibration
slope 0.8–1.2 against actual enrollment within 12 months.

## 7. White space and brainstorm

**White space TrialBox can own**
1. A hospital-owned, no-egress agent: no vendor revenue share, no foreign operator, aligned with PDPA, the Human Subjects
   Research Act and the NHI opt-out.
2. An agent you write to: email and documents in, evidence-backed answers out; no new portal for busy investigators.
3. A Taiwan knowledge layer: NHI codes and reimbursement rules as phenotype signals, cancer-registry fields, Traditional
   Chinese and code-mixed notes, local lab units, TWPAS paperwork.
4. Beyond oncology and beyond sponsor-paid studies: rheumatology, neurology, cardiometabolic, investigator-initiated trials.
5. Feasibility with evidence: criterion-by-criterion, reproducible funnels with provenance that a sponsor can audit.
6. The post-list funnel: clinic-day lists, contact and consent tracking with reasons, conduct support, eCRF pre-fill.
7. A node in national infrastructure: automatic answers to alliance feasibility requests, federated queries, OMOP and FHIR
   compatibility.
8. Portability to Japan and other sovereign-LLM markets: model-agnostic, offline-installable.

**Ideas considered for v2** (✓ adopted into the spec, → later, ✗ rejected)

| Idea | Decision |
| --- | --- |
| Data Atlas with computability scores before promising numbers | ✓ M0 |
| Dual-model extraction and verification, quotes checked in code | ✓ M1, §8.3 |
| Questionnaire autofill with a provenance sheet | ✓ M3 |
| Watchlist tier for patients who will become eligible | ✓ §5.4 |
| Clinic-day lists across all recruiting studies | ✓ M4 (R2) |
| Site-learning loop from PI decisions and outcomes | ✓ §8.6 |
| Coverage analysis (NHI-billable vs research-only) | ✓ M7 |
| eCRF pre-fill with lineage for EDCs without APIs | ✓ M8 |
| Trial-ready cohorts for prevention and dementia studies | ✓ M11 |
| Built-in validation study | ✓ §11.4 |
| Machine-to-machine feasibility via MCP/FHIR for sponsor agents and national platforms | ✓ M3 (R3) |
| Patient-facing chat and outreach | ✗ (outreach goes through the treating physician per IRB plan) |
| Automatic EDC submission | ✗ (humans upload; R3 produces files) |
| Self-improving prompts in production | ✗ (changes only via evaluation and G5) |
| Federated fine-tuning across hospitals | → research collaboration, not product scope |
| Voice agent for coordinators | → after R4, if demanded |

## 8. Threats

1. Contract lock-in with third-party vendors that restricts a hospital-owned tool on sponsor-funded studies.
2. Execution: TrialBox has run only on synthetic data and a stub model; competitors publish accuracy.
3. A national platform choosing another vendor as the federated patient- and site-finding layer.
4. Sponsor-side agent platforms commoditising feasibility from historical data.
5. HIS modernisation bringing bundled EHR-vendor trial modules.
6. Free open baselines lowering the bar for other hospitals' IT teams.
7. Regulatory or privacy shifts (NHI opt-out implementation, IRB views on LLM pre-screening as research).

## 9. References

### 9.1 Literature
(DOIs verified via PubMed or Crossref unless noted. [preprint] = not peer-reviewed at time of check.)

1. Kang T, Zhang S, Tang Y, et al. EliIE: an open-source information extraction system for clinical trial eligibility criteria. *JAMIA* 2017;24(6):1062–71. doi:10.1093/jamia/ocx019
2. Yuan C, Ryan PB, Ta C, et al. Criteria2Query: a natural language interface to clinical databases for cohort definition. *JAMIA* 2019;26(4):294–305. doi:10.1093/jamia/ocy178
3. Fang Y, Idnay B, Sun Y, et al. Combining human and machine intelligence for clinical trial eligibility querying (C2Q 2.0). *JAMIA* 2022;29(7):1161–71. doi:10.1093/jamia/ocac051
4. Kury F, Butler A, Yuan C, et al. Chia, a large annotated corpus of clinical trial eligibility criteria. *Sci Data* 2020;7:281. doi:10.1038/s41597-020-00620-0
5. Park J, Fang Y, Ta C, et al. Criteria2Query 3.0: leveraging generative large language models for clinical trial eligibility query generation. *J Biomed Inform* 2024;154:104649. doi:10.1016/j.jbi.2024.104649
6. Lee KH, Jang S, Kim GJ, et al. LLMs for automating clinical trial criteria conversion to OMOP CDM queries: validation and evaluation study. *JMIR Med Inform* 2025;13:e71252. doi:10.2196/71252
7. Datta S, Lee K, Paek H, et al. AutoCriteria: a generalizable clinical trial eligibility criteria extraction system powered by LLMs. *JAMIA* 2024;31(2):375–85. doi:10.1093/jamia/ocad218
8. Dobbins NJ, Han B, Zhou W, et al. LeafAI: query generator for clinical cohort discovery rivaling a human programmer. *JAMIA* 2023;30(12):1954–64. doi:10.1093/jamia/ocad149
8a. Dobbins NJ, Spital CH, Black RA, et al. Leaf: an open-source, model-agnostic, data-driven web application for cohort discovery and translational biomedical research. *JAMIA* 2020;27(1):109–18. doi:10.1093/jamia/ocz165
9. Idnay B, Liu J, Fang Y, et al. Sociotechnical feasibility of NLP-driven tools in clinical trial eligibility prescreening for ADRD. *JAMIA* 2024;31(5):1062–73. doi:10.1093/jamia/ocae032
10. Rafee A, Riepenhausen S, Neuhaus P, et al. ELaPro, a LOINC-mapped core dataset for top laboratory procedures of eligibility screening for clinical trials. *BMC Med Res Methodol* 2022;22:141. doi:10.1186/s12874-022-01611-y
11. Yang L, Han Y, Liu L, et al. EC2Seq2Sql: patient-trial matching with LLM agents. *PLoS One* 2026. doi:10.1371/journal.pone.0341827
11b. Chen H, Qian L, He X, et al. Clinical trial eligibility criteria decomposition and parsing with LLMs. *Stud Health Technol Inform* 2025. doi:10.3233/SHTI250928
11c. Muqeeth A, Huang Y, Bian J, et al. A multi-model LLM consensus framework to identify EHR-predictable eligibility criteria in NSCLC immunotherapy trials. *AMIA Jt Summits Transl Sci Proc* 2026 (PMID 42317858).
11d. Weyrich J, Dennstädt F, Förster R, et al. Comparing full text and abstract as inputs for LLM-based classification of oncology trial eligibility criteria. *JAMIA Open* 2026. doi:10.1093/jamiaopen/ooag179
12. Wong C, Zhang S, Gu Y, et al. Scaling clinical trial matching using large language models: a case study in oncology. *Proc MLHC* 2023 (PMLR 219). arXiv:2308.02180.
13. Jin Q, Wang Z, Floudas CS, et al. Matching patients to clinical trials with large language models (TrialGPT). *Nat Commun* 2024;15. doi:10.1038/s41467-024-53081-z
14. Fang Y, Jin Q, Tian S, et al.; NIH-TrialBench Consortium; Lu Z. Towards AI-assisted clinical trial matching: practical considerations, multicenter evaluation, and real-world deployment. arXiv:2609.01202, 2026 [preprint].
15. Syed M, Hamidi M, Bikkanuri M, et al. Translating evidence into practice: adapting TrialGPT for real-world clinical trial eligibility screening. *JAMIA* 2026. doi:10.1093/jamia/ocag006
16. Nievas M, Basu A, Wang Y, Singh H. Distilling large language models for matching patients to clinical trials. *JAMIA* 2024;31(9):1953–63. doi:10.1093/jamia/ocae073
17. Unlu O, Shin J, Mailly CJ, et al. Retrieval-augmented generation–enabled GPT-4 for clinical trial screening (RECTIFIER). *NEJM AI* 2024;1(7). doi:10.1056/AIoa2400181 (preprint: medRxiv doi:10.1101/2024.02.08.24302376)
18. Unlu O, Varugheese M, Shin J, et al. Manual vs AI-assisted prescreening for trial eligibility using large language models: a randomized clinical trial. *JAMA* 2025;333(12):1084–7. doi:10.1001/jama.2024.28047
19. Wornow M, Lozano A, Dash D, Jindal J, Mahaffey KW, Shah NH. Zero-shot clinical trial patient matching with LLMs. *NEJM AI* 2025. doi:10.1056/AIcs2400360 (arXiv:2402.05125)
20. Beattie J, Neufeld S, Yang D, et al. Utilizing large language models for enhanced clinical trial matching: a study on automation in patient screening. *Cureus* 2024;16(5):e60044. doi:10.7759/cureus.60044 (medRxiv 2024.04.10.24305571)
21. Beattie J, et al. (Dohopolski M, senior author). Large language model augmented clinical trial screening. medRxiv 2024. doi:10.1101/2024.08.27.24312646 [preprint]
22. Gupta S, Basu A, Nievas M, et al. PRISM: Patient Records Interpretation for Semantic clinical trial Matching system using LLMs. *npj Digit Med* 2024;7:305. doi:10.1038/s41746-024-01274-7
23. Verhagen CT, Westerman G, Heaviland H, et al. Understanding unrealized trial enrollments following patient-to-trial matching with LLMs. *Surgery* 2026. doi:10.1016/j.surg.2025.109915
24. Benjamin DM, Hey SP, MacPherson A, et al. Principal investigators over-optimistically forecast scientific and operational outcomes for clinical trials. *PLoS One* 2022;17:e0262862. doi:10.1371/journal.pone.0262862
25. Carlisle B, Kimmelman J, Ramsay T, MacKinnon N. Unsuccessful trial accrual and human subjects protections: an empirical analysis of recently closed trials. *Clin Trials* 2015;12(1):77–83. doi:10.1177/1740774514558307
26. Abdallah M, Nakken S, Bierkens M, et al. TrialMatchAI: an end-to-end AI-powered clinical trial recommendation system to streamline patient-to-trial matching. *Nat Commun* 2026. doi:10.1038/s41467-026-70509-w (arXiv:2505.08508)
27. Nelson SJ, Drury B, Hood D, et al. EHR-based cohort assessment for multicenter RCTs: a fast and flexible model for identifying potential study sites. *JAMIA* 2022;29(4):652–9. doi:10.1093/jamia/ocab265
28. Hulstaert L, Twick I, Sarsour K, Verstraete H. Enhancing site selection strategies in clinical trial recruitment using real-world data modeling. *PLoS One* 2024;19:e0300109. doi:10.1371/journal.pone.0300109
29. Soto-Rey I, Trinczek B, Girardeau Y, et al. Efficiency and effectiveness evaluation of an automated multi-country patient count cohort system (EHR4CR). *BMC Med Res Methodol* 2015;15:44. doi:10.1186/s12874-015-0035-9
30. Claessens A, Simon A, Manchart A, et al. AI-driven patient screening for clinical trials in pancreatic cancer: the PANCR-AI pilot. *JMIR Cancer* 2026;12:e80268. doi:10.2196/80268
31. Gui X, Lv H, Wang X, et al. Enhancing hepatopathy clinical trial efficiency: a secure, LLM-powered pre-screening pipeline. *BioData Min* 2025. doi:10.1186/s13040-025-00458-5
32. Loaiza-Bonilla A, Yost C, Kurnaz S, et al. Transforming oncology clinical trial matching through neuro-symbolic, multi-agent AI and an oncology-specific knowledge graph: a prospective evaluation in 3804 patients. *ESMO Real World Data Digit Oncol* 2026. doi:10.1016/j.esmorw.2026.100706
33. Gueguen L, Olgiati L, Brutti-Mairesse C, et al. A prospective pragmatic evaluation of automatic trial matching tools in a molecular tumor board. *npj Precis Oncol* 2025;9:28. doi:10.1038/s41698-025-00806-y
34. Stubbs A, Filannino M, Soysal E, et al. Cohort selection for clinical trials: n2c2 2018 shared task track 1. *JAMIA* 2019;26(11):1163–71. doi:10.1093/jamia/ocz163
35. Roberts K, Demner-Fushman D, Voorhees EM, Bedrick S, Hersh WR. Overview of the TREC 2021 Clinical Trials Track. *Proc TREC 2021* (NIST SP 500-335).
36. Roberts K, et al. Overview of the TREC 2022 Clinical Trials Track. *Proc TREC 2022* (NIST SP 500-338). doi:10.6028/NIST.SP.500-338.trials-overview
37. Rybinski M, Kusa W, Karimi S, Hanbury A. Learning to match patients to clinical trials using large language models. *J Biomed Inform* 2024;159:104734. doi:10.1016/j.jbi.2024.104734
38. Morrison BA, Sushil M, Young JS. A systematic review of trial-matching pipelines using large language models. arXiv:2509.19327, 2025 [preprint].
39. Wang Z, Sun J. Trial2Vec: zero-shot clinical trial document similarity search using self-supervision. *Findings of EMNLP* 2022:6377–90. doi:10.18653/v1/2022.findings-emnlp.476
40. Kern KA. TrialTriage, a semiautonomous prescreening workflow for resolving ambiguity in phase I oncology trial eligibility (synthetic cases). *JMIR Form Res* 2026. doi:10.2196/100779
41. Soffer S, Omar M, Efros O, et al. Sociodemographic bias in large language model clinical trial screening. *JAMIA* 2026. doi:10.1093/jamia/ocag058
42. Calaprice-Whitty D, Galil K, Salloum W, et al. Improving clinical trial participant prescreening with AI: AI-assisted vs standard methods in 3 oncology trials. *Ther Innov Regul Sci* 2020;54:69–74. doi:10.1007/s43441-019-00030-4
43. Unger JM, Vaidya R, Hershman DL, et al. Systematic review and meta-analysis of the magnitude of structural, clinical, and physician and patient barriers to cancer clinical trial participation. *J Natl Cancer Inst* 2019;111(3):245–55. doi:10.1093/jnci/djy221
44. Korvin K, Loi Z, Morquin D, et al. LLMs for optimizing clinical trial recruitment in ICUs: application to ventilator-induced diaphragm dysfunction. *Crit Care* 2026. doi:10.1186/s13054-026-06127-1
45. Bieganek C, Aliferis C, Ma S. Prediction of clinical trial enrollment rates. *PLoS One* 2022;17:e0263193. doi:10.1371/journal.pone.0263193
46. Yue L, Xing S, Chen J, Fu T. TrialEnroll: predicting clinical trial enrollment success with deep & cross network and LLMs. *Proc ACM-BCB* 2024. doi:10.1145/3698587.3701375 (arXiv:2407.13115)
47. Nowak S, Wulff B, Layer YC, et al. Privacy-ensuring open-weights LLMs are competitive with closed-weights GPT-4o in extracting chest radiography findings. *Radiology* 2025;314:e240895. doi:10.1148/radiol.240895
48. Yang Z. Machine learning for site risk prediction in clinical trials: development, external validation, and operational application. *Int J Med Inform* 2026. doi:10.1016/j.ijmedinf.2026.106314
49. Posta M, Figler A, Dobolyi Z, Győrffy B. A secure, scalable LLM-based system (CIDER) for high-throughput clinical data extraction from medical reports. *J Med Internet Res* 2026. doi:10.2196/95780
50. Getz KA, Campo RA. New benchmarks characterizing growth in protocol design complexity. *Ther Innov Regul Sci* 2018;52(1):22–8. doi:10.1177/2168479017713039
51. Markey N, Howitt B, El-Mansouri I, et al. Clinical trials are becoming more complex: a machine learning analysis of data from over 16,000 trials. *Sci Rep* 2024;14:3514. doi:10.1038/s41598-024-53211-z
52. Liu R, Rizzo S, Whipple S, et al. Evaluating eligibility criteria of oncology trials using real-world data and AI (Trial Pathfinder). *Nature* 2021;592:629–33. doi:10.1038/s41586-021-03430-5
53. Lee YQ, Wang BH, Su CH, et al. Protected health information recognition of unstructured code-mixed electronic health records in Taiwan. *Stud Health Technol Inform* 2022;290:497–501. doi:10.3233/SHTI220153
54. Lee YQ, Chen CT, Chen CC, et al. Unlocking the secrets behind advanced AI language models in deidentifying Chinese-English mixed clinical text. *J Med Internet Res* 2024;26:e48443. doi:10.2196/48443
55. Kim JH, Ta CN, Liu C, et al. Towards clinical data-driven eligibility criteria optimization for interventional COVID-19 clinical trials. *JAMIA* 2021;28(1):14–22. doi:10.1093/jamia/ocaa276
55a. Kim ES, Uldrick TS, Schenkel C, et al. Continuing to broaden eligibility criteria to make clinical trials more representative and inclusive: ASCO–Friends of Cancer Research joint research statement. *Clin Cancer Res* 2021;27(9):2394–9. doi:10.1158/1078-0432.CCR-20-3852
56. Sen A, Ryan PB, Goldstein A, et al. GIST 2.0: a scalable multi-trait metric for quantifying population representativeness of individual clinical studies. *J Biomed Inform* 2016;63:325–36. doi:10.1016/j.jbi.2016.09.003
57. Campion TR Jr, Sholle ET, Abedian S, et al. Implementation of a commercial federated network of EHR data to enable sponsor-initiated clinical trials at an academic medical center. *Int J Med Inform* 2024;182:105322. doi:10.1016/j.ijmedinf.2023.105322
58. Gallifant J, Chen S, Shin KY, et al. An agentic AI system enhances clinical detection of immunotherapy toxicities: a multi-phase validation study. medRxiv 2026. doi:10.64898/2026.02.26.26347179 [preprint]
59. Jiang Y, Black KC, Geng G, et al. MedAgentBench: a virtual EHR environment to benchmark medical LLM agents. *NEJM AI* 2025. doi:10.1056/AIdbp2500144 (arXiv:2501.14654)
60. Chen E, Postelnik S, Black K, Jiang Y, et al. MedAgentBench v2: improving medical LLM agent design. *Pac Symp Biocomput* 2026. doi:10.1142/9789819824755_0025
61. Liu Y, Carrero ZI, Jiang X, et al. Benchmarking large language model-based agent systems for clinical decision tasks. *npj Digit Med* 2026. doi:10.1038/s41746-026-02443-6
62. Embi PJ, Jain A, Clark J, et al. Effect of a clinical trial alert system on physician participation in trial recruitment. *Arch Intern Med* 2005;165(19):2272–7. doi:10.1001/archinte.165.19.2272
63. Embi PJ, Leonard AC. Evaluating alert fatigue over time to EHR-based clinical trial alerts: findings from a randomized controlled study. *JAMIA* 2012;19(e1):e145–8. doi:10.1136/amiajnl-2011-000743
64. Wang Z, Lin J, Jin Q, Gao J, et al. Benchmarking and developing large language models using one million clinical trials (TrialPanorama). *npj Digit Med* 2026. doi:10.1038/s41746-026-02933-7 (arXiv:2505.16097)
64a. Ni Y, Kennebeck S, Dexheimer JW, et al. Automated clinical trial eligibility prescreening: increasing the efficiency of patient identification for clinical trials in the emergency department. *JAMIA* 2015;22(1):166–78. doi:10.1136/amiajnl-2014-002887
65. Ni Y, Bermudez M, Kennebeck S, et al. A real-time automated patient screening system for clinical trials eligibility in an emergency department: design and evaluation (ACTES). *JMIR Med Inform* 2019;7(3):e14185. doi:10.2196/14185
66. Blasini R, Buchowicz KM, Schneider H, et al. Implementation of inclusion and exclusion criteria in clinical studies in OHDSI ATLAS software. *Sci Rep* 2023;13:22457. doi:10.1038/s41598-023-49560-w
67. Penberthy L, Brown R, Puma F, Dahman B. Automated matching software for clinical trials eligibility: measuring efficiency and flexibility. *Contemp Clin Trials* 2010;31(3):207–17. doi:10.1016/j.cct.2010.03.005
68. Hsieh CY, Su CC, Shao SC, et al. Taiwan's National Health Insurance Research Database: past and future. *Clin Epidemiol* 2019;11:349–58. doi:10.2147/CLEP.S196293
68a. Beauharnais CC, Larkin ME, Zai AH, et al. Efficacy and cost-effectiveness of an automated screening algorithm in an inpatient clinical trial. *Clin Trials* 2012;9(2):198–203. doi:10.1177/1740774511434844
69. Tsai MS, Lin MH, Lee CP, et al. Chang Gung Research Database: a multi-institutional database consisting of original medical records. *Biomed J* 2017;40(5):263–9. doi:10.1016/j.bj.2017.08.002
69a. Haddad T, Helgeson JM, Pomerleau KE, et al. Accuracy of an AI system for cancer clinical trial eligibility screening: retrospective pilot study. *JMIR Med Inform* 2021;9(3):e27767. doi:10.2196/27767
69b. Alexander M, Solomon B, Ball DL, et al. Evaluation of an AI clinical trial matching system in Australian lung cancer patients. *JAMIA Open* 2020;3(2):209–15. doi:10.1093/jamiaopen/ooaa002
70. Shao SC, Chan YY, Kao Yang YH, et al. The Chang Gung Research Database—a multi-institutional electronic medical records database for real-world epidemiological studies in Taiwan. *Pharmacoepidemiol Drug Saf* 2019;28(5):593–600. doi:10.1002/pds.4713
70a. Köpcke F, Prokosch HU. Employing computers for the recruitment into clinical trials: a comprehensive systematic review. *J Med Internet Res* 2014;16(7):e161. doi:10.2196/jmir.3446
71. Nguyen PA, Hsu MH, Chang TH, et al. Taipei Medical University Clinical Research Database: a collaborative hospital EHR database aligned with international common data standards. *BMJ Health Care Inform* 2024;31:e100890. doi:10.1136/bmjhci-2023-100890
71a. Hu YH, Cheng YY, Lan CC, et al. An intelligent trial eligibility screening tool using NLP with a block-based visual programming interface (iTEST). *JMIR Med Inform* 2025;13:e80072. doi:10.2196/80072
72. Ahn S. From invisible to enrolled: how artificial intelligence is reshaping clinical trial recruitment. *Pharmaceut Med* 2026. doi:10.1007/s40290-026-00635-9
73a. Nordo AH, Eisenstein EL, Hawley J, et al. A comparative effectiveness study of eSource used for data capture for a clinical research registry. *Int J Med Inform* 2017;103:89–94. doi:10.1016/j.ijmedinf.2017.04.015
73b. Eisenstein EL, Garza MY, Rocca M, et al. eSource-enabled vs traditional clinical trial data collection methods: a site-level economic analysis. *Stud Health Technol Inform* 2020;270:961–5. doi:10.3233/SHTI200304
73c. Eisenstein EL, Zozus MN, Garza MY, et al. Assessing clinical site readiness for EHR-to-EDC automated data collection. *Contemp Clin Trials* 2023;128:107144. doi:10.1016/j.cct.2023.107144
73d. Garza MY, Rutherford M, Myneni S, et al. Evaluating the coverage of the HL7 FHIR standard to support eSource data exchange implementations for multi-site clinical research. *AMIA Annu Symp Proc* 2020:472–81 (PMID 33936420).
73e. Cheng AC, Banasiewicz MK, Gibbs KW, et al. Multisite evaluation of automated electronic case report form data entry from electronic health records. *J Biomed Inform* 2026. doi:10.1016/j.jbi.2026.105060
73f. Maes C, Kalra D, Acito T, et al. Accelerating eSource scale-up in oncology clinical trials: the i~HD Task Force initiative. *Camb Prism Precis Med* 2025. doi:10.1017/pcm.2025.10004
74. ICH. M11 Clinical electronic Structured Harmonised Protocol (CeSHarP): Guideline, Template and Technical Specification, Step 4, 19 Nov 2025. https://database.ich.org/sites/default/files/ICH_Step4_M11_Final_Guideline_2025_1119.pdf ; EMA Step 5 (effective 11 Jun 2026).
75. CDISC/TransCelerate. Unified Study Definitions Model (USDM) v4, Digital Data Flow. https://www.cdisc.org/ddf (technical documentation; not peer-reviewed).
76. Tufts Center for the Study of Drug Development. Impact Report, Jan/Feb 2013 (site enrollment performance), as reported in Fierce Biotech, 16 Jan 2013. https://www.fiercebiotech.com/biotech/new-research-from-tufts-center-for-study-of-drug-development-characterizes-effectiveness [grey literature]
77. IgniteData/UCLH. EHR-to-EDC live pilot (Archer), press and trade reports 2023: https://www.digitalhealth.net/2023/08/ignitedata-helps-explore-ehr-edc-capture-in-live-pilot-study/ ; https://www.appliedclinicaltrialsonline.com/view/electronic-health-records-to-electronic-data-capture-live-pilot-study [grey literature]
78. TransCelerate BioPharma. eSource Solutions (initiative completed; continued via HL7 Vulcan). https://www.transceleratebiopharmainc.com/assets/esource-solutions/ ; HL7 Vulcan FHIR Accelerator: https://blog.hl7.org/hl7-launches-project-vulcan-fhir-accelerator-program [grey literature]
79. Dickerson JC, McClure MB, Shaw M, et al. Fully automated abstraction of longitudinal breast oncology records with off-the-shelf LLMs. medRxiv 2026. doi:10.64898/2026.03.23.26349012 [preprint]
80. Wang B, Lai J, Cao H, et al. Enhancing the interoperability and transparency of real-world data extraction in clinical research: a ChatGLM implementation in Chinese hospital settings. *Eur Heart J Digit Health* 2024;5(6):712–24. doi:10.1093/ehjdh/ztae066
81. Marsolo K, Kiernan D, Toh S, et al. Assessing the impact of privacy-preserving record linkage on record overlap and patient characteristics in PCORnet. *JAMIA* 2023;30(3):447–55. doi:10.1093/jamia/ocac229
82. Asgari E, Montaña-Brown N, Dubois M, et al. A framework to assess clinical safety and hallucination rates of LLMs for medical text summarisation. *npj Digit Med* 2025;8:274. doi:10.1038/s41746-025-01670-7
83. Wang Z, Gao J, Danek B, et al. Compliance and factuality of large language models for clinical research document generation (InformBench/InformGen). *JAMIA* 2026. doi:10.1093/jamia/ocaf174
84. Markey N, El-Mansouri I, Rensonnet G, et al. From RAGs to riches: utilizing large language models to write documents for clinical trials. *Clin Trials* 2025. doi:10.1177/17407745251320806
85. Bentegeac R, Le Guellec B, Kuchcinski G, et al. Token probabilities to mitigate LLM overconfidence in answering medical questions. *J Med Internet Res* 2025;27:e64348. doi:10.2196/64348
86. Bedi S, Cui H, Fuentes M, et al. Holistic evaluation of large language models for medical tasks with MedHELM. *Nat Med* 2026. doi:10.1038/s41591-025-04151-2
87. Gallifant J, Afshar M, Ameen S, et al. The TRIPOD-LLM reporting guideline for studies using large language models. *Nat Med* 2025;31:60–9. doi:10.1038/s41591-024-03425-5
88. Liu X, Cruz Rivera S, Moher D, et al. Reporting guidelines for clinical trial reports for interventions involving AI: the CONSORT-AI extension. *Nat Med* 2020;26:1364–74. doi:10.1038/s41591-020-1034-x
89. Cruz Rivera S, Liu X, Chan AW, et al. Guidelines for clinical trial protocols for interventions involving AI: the SPIRIT-AI extension. *Lancet Digit Health* 2020;2:e549–60. doi:10.1016/S2589-7500(20)30219-3
90. Vasey B, Nagendran M, Campbell B, et al. Reporting guideline for the early-stage clinical evaluation of decision support systems driven by AI: DECIDE-AI. *Nat Med* 2022;28:924–33. doi:10.1038/s41591-022-01772-9
91. Chen D, Blayne A, Ning T, et al. Reporting completeness of clinical trials evaluating LLM interventions in medicine: systematic review. *BMJ* 2026. doi:10.1136/bmj-2026-100855
92. Chen SF, et al. LLM-assisted systematic review of large language models in clinical medicine. *Nat Med* 2026. doi:10.1038/s41591-026-04229-5
93. Corso F, Peppoloni V, Mazzeo L, et al. Clinician expertise and prompt engineering enhance cancer information extraction in EHRs by small language models. *Commun Med* 2026. doi:10.1038/s43856-026-01790-5
94. Yoshihara H, Maeda H, Hagiwara Y, et al. Fine-tuning LLMs for structured extraction of infectious disease-related information from clinical notes in Japanese primary care. *JMIR Form Res* 2026. doi:10.2196/84974
95. Wiest IC, Wolf F, Leßmann ME, et al. A software pipeline for medical information extraction with LLMs, open source and suitable for oncology (LLM-AIx). *npj Precis Oncol* 2025. doi:10.1038/s41698-025-01103-4
96. Norgeot B, Muenzen K, Peterson TA, et al. Protected Health Information filter (Philter): accurately and securely de-identifying free-text clinical notes. *npj Digit Med* 2020;3:57. doi:10.1038/s41746-020-0258-y
97. Wiest IC, Leßmann ME, Wolf F, et al. Deidentifying medical documents with local, privacy-preserving LLMs: the LLM-Anonymizer. *NEJM AI* 2025. doi:10.1056/AIdbp2400537 (medRxiv 10.1101/2024.06.11.24308355)
98. Yagahara A, Mori H, Nishimoto N. Comparing the accuracy of deidentification in Japanese text using LLMs. *Stud Health Technol Inform* 2025. doi:10.3233/SHTI251144
99. Sarkar AR, Chuang YS, Mohammed N, Jiang X. De-identification is not enough: a comparison between de-identified and synthetic clinical notes. *Sci Rep* 2024;14:29669. doi:10.1038/s41598-024-81170-y
100. Huang CH, Hsiao HJ, Yeh PC, et al. Performance of ChatGPT on Stage 1 of the Taiwanese medical licensing exam. *Digit Health* 2024;10. doi:10.1177/20552076241233144
101. Chen RJ, Wu MS, Tsai LW, et al. Integrating an LLM to streamline nursing handover documentation across multiple hospitals in Taiwan. *J Med Internet Res* 2026. doi:10.2196/81604
102. Li H, Pan W, Rajendran S, Zang C, et al. Empowering clinical trial design with agentic intelligence and real-world data (TrialGenie/EmulatRx). *Nat Commun* 2026;17. doi:10.1038/s41467-026-74501-2 (medRxiv doi:10.1101/2025.04.17.25326033)
103. Wang Z, Xiao C, Sun J. AutoTrial: prompting language models for clinical trial design. *Proc EMNLP* 2023. doi:10.18653/v1/2023.emnlp-main.766
104. Yue L, Xing S, Chen J, Fu T. ClinicalAgent: clinical trial multi-agent system with LLM-based reasoning. *Proc ACM-BCB* 2024. doi:10.1145/3698587.3701359
105. Wang Z, Cao L, Danek B, et al. Accelerating clinical evidence synthesis with large language models (TrialMind). *npj Digit Med* 2025. doi:10.1038/s41746-025-01840-7
106. Schmidgall S, Ziaei R, Harris C, et al. AgentClinic: a multimodal benchmark for tool-using clinical AI agents. *npj Digit Med* 2026. doi:10.1038/s41746-026-02674-7
107. Hripcsak G, Duke JD, Shah NH, et al. Observational Health Data Sciences and Informatics (OHDSI): opportunities for observational researchers. *Stud Health Technol Inform* 2015;216:574–8 (PMID 26262116).
108. Voss EA, Blacketer C, van Sandijk S, et al. European Health Data & Evidence Network—learnings from building out a standardized international health data network. *JAMIA* 2023;31(1):209–19. doi:10.1093/jamia/ocad214
109. Blacketer C, Schuemie MJ, Moinat M, et al. Advancing real-world evidence through a federated health data network (EHDEN): descriptive study. *J Med Internet Res* 2025. doi:10.2196/74119
110. Fleurence RL, Curtis LH, Califf RM, et al. Launching PCORnet, a national patient-centered clinical research network. *JAMIA* 2014;21(4):578–82. doi:10.1136/amiajnl-2014-002747
111. Palchuk MB, London JW, Perez-Rey D, et al. A global federated real-world data and analytics platform for research (TriNetX). *JAMIA Open* 2023;6(2):ooad035. doi:10.1093/jamiaopen/ooad035
112. Yamaguchi M, Inomata S, Harada S, et al. Establishment of the MID-NET medical information database network as a reliable and valuable database for drug safety assessments in Japan. *Pharmacoepidemiol Drug Saf* 2019;28(10):1395–404. doi:10.1002/pds.4879
113. Lee GH, et al. Feasibility study of federated learning on the distributed research network of OMOP common data model. *Healthc Inform Res* 2023;29(2):168–73. doi:10.4258/hir.2023.29.2.168

Additional regulatory context referenced in design implications (no DOI): ICH E6(R3) Good Clinical Practice (Step 4, Jan 2025); US FDA, *Enhancing the Diversity of Clinical Trial Populations — Eligibility Criteria, Enrollment Practices, and Trial Designs* (Guidance, Nov 2020).

### 9.2 Company, market and policy sources
**Lind, PREMIA, CGMH**
- https://www.lind.care/ ; https://www.lind.care/news/
- https://www.globenewswire.com/news-release/2026/05/27/3301922/0/en/premia-and-lind-form-lind-asia-to-expand-ai-powered-clinical-trial-screening-across-asia-pacific.html
- https://www.advocatehealth.org/news/advocate-health-partners-with-ai-startup-to-connect-more-cancer-patients-to-clinical-trials
- https://www.biospace.com/press-releases/illumina-and-premia-partner-to-expand-clinical-access-to-cgp-in-asia
- https://www.biospectrumasia.com/news/96/27694/premia-and-lind-expand-ai-powered-clinical-trial-screening-across-asia-pacific.html
- https://www.ncc.go.jp/en/information/press_release/20241105/index.html (LC-SCRUM-CD)
- https://hitconsultant.net/2024/11/06/japans-national-cancer-center-selects-paradigm-for-nationwide-clinical-trial-network/

**US hospital-side and networks**
- https://triomics.com/ ; https://www.healthcareittoday.com/2026/06/09/trusted-by-leading-cancer-centers-to-solve-oncologys-information-overload-triomics-raises-22-million-to-accelerate-adoption/ ; https://hlth.com/insights/news/triomics-raises-22m-series-b-led-by-battery-ventures-to-scale-oncology-ai-chart-abstraction ; https://www.fiercehealthcare.com/ai-and-machine-learning/where-participation-clinical-trials-cancer-lacks-triomics-could-step
- https://www.businesswire.com/news/home/20250310060228/en/Tempus-Announces-Acquisition-of-Deep-6-AI ; https://www.tempus.com/publications/impact-of-ai-clinical-trial-program-on-screening-matching-and-enrollment-of-patients-over-6-months/ ; https://www.tempus.com/solutions/clinical-trial-recruitment/
- https://www.prnewswire.com/news-releases/paradigm-health-raises-78-million-series-b-to-make-clinical-trials-part-of-routine-care-across-the-us-and-globally-302632924.html ; https://www.clinicaltrialsarena.com/news/paradigm-health-acquires-flatiron-health-clinical-reserach-business/ ; https://aventure.vc/news/2026-06-30-paradigm-health-submits-response-to-fda-real-time-clinical-trials-initiative-rfi
- https://www.bekhealth.com/ ; https://aws.amazon.com/marketplace/pp/prodview-kmhelvjo5koma
- https://www.fiercebiotech.com/cro/health-tech-firm-carta-healthcare-buys-ai-company-matches-oncology-patients-clinical-trials ; https://mobihealthnews.com/news/carta-healthcare-acquires-realyze-intelligence
- https://yespress.io/mendel-ai
- https://www.businesswire.com/news/home/20250910493277/en/Trially-AI-Seed-Round-Secures-4.7M-and-Launches-%E2%80%9CMargo%E2%80%9D-to-Solve-Clinical-Trial-Recruitment-Bottleneck
- https://medcitynews.com/2026/07/grove-ai-voice-agent-agentic-clinical-trial-recruitment-hippocratic/
- https://blog.inato.com/blog/patient-pre-screening ; https://www.fiercehealthcare.com/health-tech/inato-rolls-out-ai-technology-patient-pre-screening-speed-clinical-trial-enrollment ; https://tracxn.com/d/companies/inato/__vX1AGyYp02JVCzkG7j_Lj2YjZnYN0PtI6K5k1irAP68
- https://www.newswire.com/news/carebox-and-the-american-cancer-society-cancer-action-network-are-22006800
- https://www.antidote.me/blog/case-study-how-we-saved-our-client-30-per-patient-in-a-recent-trial
- https://www.businesswire.com/news/home/20210923005816/en/Morgan-Stanley-Expansion-Capital-and-Ally-Bridge-Group-Lead-%24135-Million-Investment-in-Elligo
- https://www.clinicaltrialsarena.com/news/lindus-health-completes-55m-funding-round/ ; https://www.prnewswire.com/news-releases/formation-bio-secures-372mm-series-d-funding-to-grow-drug-pipeline-and-continue-expanding-ai-driven-drug-development-platform-302182347.html ; https://www.fiercebiotech.com/biotech/formation-bios-china-shopping-spree-continues-500m-biobucks-autoimmune-pact

**EHR vendors**
- https://www.healthcareitnews.com/news/himss26-epic-highlight-no-code-agent-factory-and-other-ai-advances ; https://www.advisory.com/daily-briefing/2026/08/26/epic-ugm-ab-oi-ec ; https://www.healthcareittoday.com/2026/08/19/epic-ugm-2026-judy-faulkner-keynote-and-cool-stuff-ahead/ ; https://x.com/HeyEpic/status/2087523299416842653 ; https://www.prnewswire.com/news-releases/epic-launches-life-sciences-program-unifying-clinical-research-with-care-delivery-301624287.html
- https://www.oracle.com/news/announcement/oracle-life-sciences-data-intelligence-help-accelerate-clinical-research-and-commercialization-2026-09-23/ ; https://www.hpcwire.com/bigdatawire/this-just-in/oracle-launches-life-sciences-ai-data-platform-to-support-research-and-clinical-development/ ; https://www.fiercehealthcare.com/ai-and-machine-learning/oracle-ramps-healthcare-ai-tech-unveils-new-features-patients-prior-auth

**Sponsor-side platforms**
- https://www.medidata.com/en/about-us/news-and-press/medidata-launches-medidata-plus-an-ai-native-foundation-built-to-scale-clinical-portfolios/ ; https://hitconsultant.net/2026/07/24/medidata-launches-medidata-plus-clinical-trial-ai-layer/
- https://iqvia.com/newsroom/2026/03/iqvia-unveils-iqvia-ai-a-unified-agentic-ai-platform ; https://www.iqvia.com/newsroom/2026/09/iqvia-predictive-clinical-development-provides-sponsors-with-significant-efficiencies ; https://blogs.nvidia.com/blog/iqvia-agentic-ai-healthcare/ ; https://www.clinicalresearchnewsonline.com/news/2025/06/11/iqvia-nvidia-build-ai-agents-for-clinical-research
- https://sites.veeva.com/ai ; https://www.veeva.com/resources/veeva-sitevault-free-now-available-to-simplify-study-execution-at-clinical-research-sites/ ; https://www.veeva.com/eu/resources/veeva-ai-agents-to-be-released-across-all-veeva-applications/
- https://www.concertai.com/news/concertai-launches-accelerated-clinical-trials-leveraging-agentic-ai-to-streamline-trial-timelines ; https://hitconsultant.net/2026/05/29/concertai-launches-cancerlinq-ai-upgrades-asco/
- https://www.advarra.com/learn/newsroom/advarra-launches-site-identification-technology-with-insights-directly-from-sites/
- https://macaubusiness.com/citeline-unveils-trialtrove-and-sitetrove/ ; https://ai.norstella.com/press-release/recursion-citeline-ai-clintech-partnership-2026/
- https://www.newswise.com/articles/florence-healthcare-unlocks-agentic-ai-across-global-site-network-at-dia-2026
- https://trinetx.com/solutions/live-platform/ ; https://academic.oup.com/jamiaopen/article/6/2/ooad035/7161780 ; https://pubmed.ncbi.nlm.nih.gov/30652541/ ; https://kyodonewsprwire.jp/release/202502124127 ; https://www.prnewswire.com/apac/news-releases/takeda-hospital-group-joins-trinetx-network-to-revolutionize-medical-care-in-japan-302091809.html ; https://yespress.io/trinetx

**EHR-to-EDC**
- https://ignitedata.com/ignitedata-announces-final-close-of-oversubscribed-series-a-led-by-fca-venture-partners-with-the-labcorp-venture-fund-and-epsilon-as-key-investors/
- https://www.yonalink.com/blog-posts/yonalink-announces-the-success-of-the-largest-ever-ehr-to-edc-live-pilot-study-to-solve-the-clinical-trial-data-transfer-problem ; https://pmc.ncbi.nlm.nih.gov/articles/PMC13274265/
- https://resources.flatiron.com/press/nrg-oncology-and-flatiron-health-announce-collaboration-to-leverage-leading-technology-to-drive-more-efficient-clinical-trials

**Design and simulation**
- https://fortune.com/press-releases/faro-series-b-scale-agentic-ai-clinical-development-2026-08-26/
- https://www.clinicaltrialsarena.com/news/ema-qualifies-unlearn-approach/ ; https://yespress.io/unlearn-ai.md
- https://www.mobihealthnews.com/news/quanthealth-lands-45m-ai-clinical-trial-simulations

**Frontier labs and open source**
- https://www.fiercehealthcare.com/ai-and-machine-learning/jpm26-anthropic-launches-claude-healthcare-targeting-health-systems-payers ; https://hitconsultant.net/2026/01/12/anthropic-debuts-claude-for-healthcare-and-life-sciences/ ; https://anthropic.com/news/healthcare-life-sciences
- https://www.biopharmatrend.com/news/sanofi-formation-bio-and-openai-partner-to-innovate-drug-development-with-ai-810/
- https://learn.microsoft.com/en-us/azure/azure-health-insights/trial-matcher/overview
- https://arxiv.org/abs/2609.01202 (TrialGPT 2.0) ; https://pubmed.ncbi.nlm.nih.gov/41637159/ (local TrialGPT, UTHSA) ; https://doi.org/10.1200/CCI-25-00262 (Yale CTPM, PubMed 41512229) ; https://www.nature.com/articles/s41467-026-70509-w (TrialMatchAI) ; https://arxiv.org/abs/2411.14637 (MAKAR) ; https://fedscoop.com/how-nihs-national-library-of-medicine-is-testing-ai-to-match-patients-to-clinical-trials/

**Regulation and policy**
- https://www.fda.gov/news-events/press-announcements/fda-announces-major-steps-implement-real-time-clinical-trials ; https://www.appliedclinicaltrialsonline.com/view/fda-real-time-clinical-trials
- https://www.ich.org/page/efficacy-guidelines ; https://regulation.cde.org.tw/10254/4045/55381/

**Taiwan**
- https://focustaiwan.tw/society/202512080017 ; https://www.taipeitimes.com/News/editorials/archives/2025/12/16/2003848947 ; https://tactc.tw/en/clinical-trial-collaboration/ ; https://n.yam.com/Article/20251209647271
- https://www.taiwanclinicaltrials.tw/ ; https://geneonline.news/exclusive-interview-with-the-taiwan-clinical-trial-consortium/ ; https://e-sub.fda.gov.tw/ClinicalTrialInfo/home ; https://trpma.org.tw/cmn/news/news_6335
- https://tw.stock.yahoo.com/news/btc%E8%81%9A%E7%84%A6%E7%94%9F%E9%86%AB%E7%92%B0%E5%A2%83-%E8%A1%9B%E7%A6%8F%E9%83%A8%E6%8B%9A%E4%BA%9E%E5%A4%AA%E8%87%A8%E5%BA%8A%E8%A9%A6%E9%A9%97%E6%A8%9E%E7%B4%90-ai%E5%8A%A0%E9%80%9F%E5%AF%A9%E6%9F%A5-063922676.html (TNet, 2026-08-24)
- https://geneonline.news/nihdata-taiwan-law-2025/ ; https://www.judicial.gov.tw/tw/cp-1454-696418-cbfe0-1.html ; https://www.tahr.org.tw/news/3522/
- https://geneonline.news/fhir-taiwan-2025/ ; https://www.cna.com.tw/news/ahel/202604130151.aspx ; https://udn.com/news/story/7266/9152553 ; https://aicenter.mohw.gov.tw/AC/cp-7200-82167-208.html
- https://finance.technews.tw/2026/06/10/taiwan-ai-labs-federated-learning/ ; https://www.cio.com.tw/joint-learning-medical-alliance-officially-launched/
- https://www.theai.tw/guide/ai-clinical-trial-recruitment-guide-2026
- https://pmc.ncbi.nlm.nih.gov/articles/PMC6138604 (CGRD) ; https://pure.lib.cgu.edu.tw/en/publications/the-chang-gung-research-databasea-multi-institutional-electronic-/
- https://doaj.org/article/4d987ebf62c74fd4b3616eff273547d2 (TMUCRD OMOP) ; https://www.ohdsi.org/wp-content/uploads/2025/07/OHDSI-APAC-Community-Call-20250619.pdf
- https://www.pwc.tw/en/publications/assets/clinical-trials-whitepaper-en.pdf ; https://www.precisionformedicine.com/blog/taiwans-clinical-trial-landscape-fast-efficient-and-high-quality-research

**Japan, Korea, China, Singapore**
- https://group.ntt/jp/newsrelease/2026/06/30/260630a.html ; https://www.nttdata.com/global/ja/news/topics/2026/063001/ ; https://www.nttdata.com/global/ja/news/topics/2026/052500/ ; https://becarispublishing.com/digital-content/blog-post/chugai-and-partners-evaluate-ai-assisted-clinical-trial-patient-identification-using
- https://it.impress.co.jp/articles/-/27902 ; https://www.thers.ac.jp/news/upload/d8e794920b1fe5c825cefb3f059d215c.pdf (Fujitsu / Nagoya-Gifu)
- https://www.mitsui.com/mgssi/en/report/detail/__icsFiles/afieldfile/2026/10/05/2608_i_kinoshita_e.pdf
- https://khub.konect.or.kr/operational/feasibility-service?lang=en ; https://e-hir.org/journal/view.php?number=1161
- https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0625/2025062500831.pdf (Yidu) ; https://www.theglobeandmail.com/investing/markets/markets-news/Tipranks/3065663/yidu-tech-turns-profitable-as-medical-ai-business-accelerates/ ; https://www.tribuneindia.com/news/business/taimei-technology-and-cr-research-announce-strategic-partnership-to-build-ai-powered-clinical-trial-innovation/amp
- https://www.healthcareitnews.com/news/asia/nuhs-save-850-staff-hours-weekly-new-pharma-ai

**Pricing and benchmarks**
- https://intuitionlabs.ai/articles/clinical-trial-patient-recruitment-vendors-compared ; https://www.referohq.com/blog/clinical-trial-recruitment-cost ; https://intuitionlabs.ai/software/data-interoperability-healthcare-ai/clinical-trial-matching-and-cohort-id/deep-6-ai ; https://www.bekhealth.com/pricing-roi/
