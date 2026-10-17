## 19. Positioning and commercial principles

This section places TrialBox v4 against published systems and products. It sets the metric each differentiator must
reach and fixes the commercial rules.

The evidence is `docs/research/2026-10_literature_competitors.md` (October 2026), which corrects `docs/LANDSCAPE.md`. Tags:
- **[V]**: primary or near-primary source.
- **[R]**: trade press or a secondary source.
- **[Vendor]**: reported by the company, with no independent check.
- **[Unverified]**: could not be confirmed.

TrialBox has no peer-reviewed evidence of its own yet. Everything below is a target, not a claim.

### 19.1 Position

TrialBox is an independent appliance owned by the hospital (C-1). It covers the site side of the whole clinical-trial
lifecycle (C-6). It runs on premises first, with hybrid deployment under the data-class policy (C-2′, §7).

Its deterministic core produces counts and tiers:
- IR → CQL/SQL with the equivalence gate;
- quote-verified judging;
- hash-chained audit;
- byte-identical re-runs;
- controlled rounding.

Models read only the residue that the filters cannot decide (C-3). Staff work through a governed Hermes front door in
their own channels (C-10). End users see minimal UI, and administrators have strong control (C-5′).

The 2024–2026 evidence supports three positioning statements.

1. **Accuracy alone is not the moat.**
   - Open baselines are strong and free: TrialGPT, TrialMatchAI, and a local TrialGPT at UT Health San Antonio.
   - UT Southwestern's cloud RAG pipeline reached criterion accuracy 0.94 on 39,182 patients [V, preprint].
   - TrialBox must reach that bar with local open models on code-mixed notes.
   - It must also add what nobody publishes: a certified bound on missed patients, per-criterion abstention at a stated
     error level, and the work after the list.
2. **The sovereign, site-side, whole-lifecycle position is still empty, but its edges are moving.**
   - Lind Asia (27 May 2026) targets Taiwan and Japan [V].
   - Massive Bio entered Korea in September 2026 [Vendor].
   - Veeva offers eSource in SiteVault, which is free to sites [R].
   - ChatGPT for Healthcare connected to Epic in September 2026 [R].
   - Epic's own eligibility AI is still in development [V].
3. **Agents and AI feasibility have no peer-reviewed evidence base.**
   - Even patient–trial matching, the best-evidenced use, is rated "moderate maturity" (PMID 42651288) [V].
   - TrialBox's agent and feasibility claims must therefore be earned prospectively at the site (§16, §20.7).

### 19.2 Differentiators mapped to the twenty innovations

Each innovation ranked in review §3 is a v4 differentiator. For each one the table gives:
- the section that makes it normative;
- one primary metric;
- a target;
- the milestone at which it is first measured.

Items 1–6 are what would make TrialBox unmatched. Items 7–14 widen the lead. Items 15–20 are cheap wins.

| # | Differentiator | Normative in | Primary metric | Target | First at |
| --- | --- | --- | --- | --- | --- |
| 1 | Anytime-valid recall ledger (confidence sequences per canonical criterion, two known-positive lines) | §6, §10 SAFE, App. F | Coverage over 12 simulated monthly looks; new studies certified at first packet | ≥ 95 % over the whole sequence (simulation: repeated Clopper–Pearson missed 9.7 %, the sequence 0.3 %); ≥ 50 % certified at first packet *(est.)* | MS0 (sim.), MS2 |
| 2 | Criterion library with match-then-draft extraction | §6, §10.1 | Share matched to library; structure F1; normalisation per domain | > 60 % after 20 protocols; F1 ≥ 0.85; ≥ 0.80 drug, ≥ 0.70 condition, ≥ 0.65 measurement | MS1 |
| 3 | Two-direction matching engine | §10.5 | `match_registry` recall@500, NDCG@10; tumour-board minutes | ≥ 0.90; ≥ 0.60 *(est.)*; against a site baseline | MS1, MS4 |
| 4 | Data platform with reconciliation and lineage | §5 | Planted-defect detection; days to onboard a source | 100 %; ≤ 10 working days | MS0 |
| 5 | Class-based hybrid LLM control plane | §8 | Class violations; cost per candidate; model-swap time | 0; reported monthly; ≤ 1 working day incl. G5 | MS0 |
| 6 | Hermes front door with capability separation | §9 | Proposal accuracy; capability-bearing injection successes | ≥ 0.95; 0 | MS0, MS3 |
| 7 | Recruitability model and forecast ledger | §10.3, §10.6, §12 | Calibration slope; Brier vs PI estimates | 0.8–1.2 after 10 closed studies; better than PIs | MS1, MS6 |
| 8 | S2b pre-filter with lexicon-recall gating | §4, §10 SAFE | `S2-zero_hit` bound; lexicon recall | Zero-hit exclusion only where recall ≥ 0.98 | MS2 |
| 9 | Sentence-set judgement cache | §4, §10.4 | Hit rate in daily-note clinics | > 80 % after 4 weeks | MS3 |
| 10 | Sponsor deliverable standard (four packs, FHIR/USDM/Dataset-JSON) | §12 | Accepted without rework; days to pack | ≥ 80 % *(est.)*; ≤ 2 working days | MS1, MS4 |
| 11 | Open-data CI and public calibration prior | §16 | Weeks to first certified LTT threshold | ≤ 8 | MS2 |
| 12 | Bake-off as code (OpenRouter, D0, per-language floors) | §8, §16 | Bake-off → champion cycle; stratum gap | ≤ 6 weeks *(est.)*; ≤ 5 points | MS1 (key needed) |
| 13 | Champion/challenger shadow pass | §8 | Shadow evidence before a G5 change | ≥ 4 weeks *(est.)* | MS3 |
| 14 | Alliance language packs and a federated node | §10.12 | Requests answered automatically; ε per quarter | Reported; within the ledger cap | MS5 |
| 15 | PET kit (de-identification, PPRL, synthetic twins) | §7 | Re-identification risk of D2 exports | ≤ the §7 threshold on 100 % of exports | MS1 |
| 16 | Watchlist flips, clinic-day lists, QBCB depth | §10.4 | Watchlist → strong conversions; depth k | Reported per study | MS3 |
| 17 | Five-minute review and exemplar bank | §10.4, §8 | PPV lift per 100 labels | CI excludes 0 after 300 labels *(est.)* | MS3 |
| 18 | eSource packets with lineage | §10.8, §12 | Structured-field agreement; SDV minutes | ≥ 0.95 on 3 closed studies; against a baseline | MS5 |
| 19 | NHI-aware recruitment and coverage analysis | §10.10 | Budget tables accepted; NHI-signal enrolments | Reported per study | MS1, MS4 |
| 20 | Offline prompt and skill optimisation through G5 | §8, §9 | Suite gain per cycle | ≥ 1 point, no other suite down > 0.5 *(est.)* | MS4 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-POS-01 | Each differentiator MUST have an automated measurement (`trialbox eval` or the QA pack) from the milestone in its row. An unmeasured differentiator MUST NOT appear in external material. | I | MS1 |
| PLAN-POS-02 | Each MS gate record (§20.7) MUST report the measured differentiator metrics with value, n, 95 % interval and dataset hash. | I | MS0 |

### 19.3 Head-to-head (refreshed October 2026)

**Corrections to v3 §14.2 and `docs/LANDSCAPE.md`.**

1. **Lind TRIAGE.** The citation "*JCO Oncology Practice*, June 2026: 94.2 % criterion agreement, 806 patients, 168
   trials" could not be verified.
   - The only source is Advocate Health's release. It reports "more than 94 % agreement" over "over 1,700 eligibility
     criteria", retrospective, and says the platform "still requires human review".
   - The journal record, the 94.2 %, and the 98.7/97.6 % sensitivity/specificity are **[Unverified]**.
   - No v4 target or comparison uses the Lind figure.
2. **Epic.** Epic did not ship eligibility AI in November 2025.
   - Its roadmap lists "Evaluate patients for clinical trials using eligibility data and the chart" as **in development,
     target 2026** [V].
   - Forward CTMS rolls out 2026–2027 [R].
3. **Massive Bio.** The "neuro-symbolic, 3,804 patients, F1 0.82" study is Massive Bio's own (vendor-authored) [V].
4. **Azure Trial Matcher** is being retired [Unverified date].
5. **TrialPanorama** has no matching benchmark. The +14.4 % F1 figure belongs to Panacea [V].
6. **Veeva agents** are not confirmed as shipped [Unverified]. SiteVault eSource was presented in April 2026 [R].
7. **Missing players added:** Reify / OneStudyTeam, MDV, Massive Bio, and the UTSW deployment.

| Player | Strongest evidence (tag) | Where it is strong | Where TrialBox must beat it, and how |
| --- | --- | --- | --- |
| **UT Southwestern pipeline** (academic; cloud GPT-4o → 4o-mini → 4.1-mini, RAG) | 39,182 patients, 26 studies (21 oncology), Oct 2024–Sep 2025; on 5,096 coordinator-reviewed criteria: accuracy 0.94 (0.92–0.96), sensitivity 0.98, specificity 0.81, PPV 0.95; ~US$0.12/patient; enrolment and time not measured [V, preprint] | Scale; real EHR; cost. **This is the bar.** | Same accuracy with an on-prem open model on code-mixed notes, and specificity ≥ 0.90. Every `met` has a verified quote. Its failure modes become suites (§16): a Tier-1 gate blocking downstream criteria; timing errors; excluded scanned records. |
| **Lind / Lind Asia** | ">94 % agreement", retrospective [V, release only]; journal claim [Unverified] | Every patient × every study, with evidence; Asian distribution | Independent and hospital-owned, with no revenue share; recall certificate; published Taiwan code-mixed evaluation; NHI; whole lifecycle. Compared only on the same site data. |
| **Triomics** | PRISM, npj Digit Med 2024 [V]; US$22 M Series B [V]; "67 % less chart review" [Vendor] | Oncology depth in Epic and OncoEMR | Oncology through registry and IR v3 line of therapy on in-house HIS; non-oncology; on-prem |
| **Massive Bio** | Prospective, 3,804 patients, F1 0.82 vs 0.47 zero-shot GPT-4 [V, vendor-authored]; Korea entry [Vendor] | Prospective scale; calibrated confidence | Site-owned rather than sponsor-paid; no egress; per-criterion abstention with an LTT error guarantee |
| **Tempus / Deep 6 (TIME)** | One-practice abstract: 66 consents; activation in 10.5 vs 55.4 business days [Vendor] | Start-up speed via the network | Neutral (no testing tie-in); M7 start-up playbooks measured on the site's own activation times |
| **Paradigm Health** | FDA real-time review collaboration [R]; Ochsner +41 % access [R] | Network plus conduct | Sovereign; home-grown HIS; federated alliance feasibility |
| **BEKhealth, Trially, Inato** | AWS listing from ~US$6k/yr [V]; Inato 5,500+ sites, free to sites [R] | Price; speed; sponsor demand | Fixed-price appliance; offline install with validation at the site; hospital-owned outputs |
| **Reify / OneStudyTeam** | 1,800–2,700 sites; Referral Partner Interface [R] | Installed base in enrolment tracking | Not a screening competitor. M6 exports referral and state data that StudyTeam can take in (§12). |
| **Epic (roadmap); ChatGPT for Healthcare in Epic** | In development, 2026 [V]; Epic connection Sept 2026 [R] | In-workflow | Absent from most Taiwanese in-house HIS; source-agnostic; optional CDS Hooks card (§3) |
| **Oracle LSDI; TriNetX** | 122 M records NL cohorting [V]; 280 M+ patients, free node [V/Vendor] | Network-scale counts | Criterion-level, recall-certified counts with data availability disclosed per criterion |
| **IQVIA.ai, Medidata, Veeva** | Medidata feasibility with Claude [Vendor]; SiteVault eSource free [R] | Sponsor-side breadth | The EHR side they cannot see: pre-fill with SDV packets and lineage; CDASH/ODM v2, Dataset-JSON, USDM. Measured as errors prevented against the 8.23 % manual transcription rate [V]. |
| **MDV** (Japan) | 57.56 M-patient EMR DB; feasibility service; delisted 24 Apr 2026 [V] | Japanese data scale | At MS6: "who at this site, with evidence" rather than "how many in Japan" |
| **NTT / Kindai / Chugai** (tsuzumi 2) | Rule vs LLM vs hybrid study, to Mar 2027, no results [V] | Domestic trust | Model-agnostic registry; a domestic model runs under the same validation and certificate |
| **Fujitsu / Nagoya / Gifu** | 1,800 patients; 27 of 42 AI candidates confirmed (**PPV 64 %**); selection time −⅔ [V] | Most relevant Asian real-chart figure | PPV of `strong` ≥ 0.75 on Taiwanese charts, published |
| **TrialGPT 2.0, TrialMatchAI, local TrialGPT** | Top-10 hit 91 % [V, preprint]; top-20 92 % [V]; sensitivity 81.8 % vs 36.4 % manual [V] | Free; ranking quality | TrialBox embeds the method in M5 and adds the deterministic core, certification, lifecycle and validation. A same-data head-to-head ships in the validation pack. |

On the capability matrix of the research note (§2.7), the other players leave four columns empty:
- code-mixed notes;
- abstention with a guarantee;
- recall certificate;
- NHI.

TrialBox's weakest column is peer-reviewed evidence. Closing it is a launch deliverable: the stepped-wedge evaluation
from MS4 and the paper at MS6.

### 19.4 Best-in-class bar per core function

Figures from different datasets are not comparable. A target is met only on the dataset named in the table.

| Function | Bar (holder, tag) | TrialBox target | Measured on | First at |
| --- | --- | --- | --- | --- |
| Criterion judgement, real EHR | Acc 0.94, sens 0.98, spec 0.81, PPV 0.95 (UTSW, cloud) [V, preprint] | Acc ≥ 0.94 and spec ≥ 0.90 with an **on-prem open model**, every language stratum within 5 points | Site `judge_ml`, blinded CRC adjudication | MS3 |
| Criterion judgement, public proxy | GPT-4 0.873 on the 1,015 NCBI pairs; physicians 0.887–0.900 [V] | ≥ 0.85 in en, zh-TW, ja and mixed; false-block upper bound ≤ 0.022 | `eval/criterion_ml` via `tools/mlbench.py` | MS1 |
| Single-trial judgement | 97.9–100 % per criterion; sens 92.3 / spec 93.9 (RECTIFIER) [V] | The same on ≥ 3 non-oncology trials | Validation replay | MS2 |
| Patient-level sensitivity | 81.8 % vs 36.4 % manual (UTHSA) [V] | ≥ 0.90 with a certified recall lower bound ≥ 0.90 at go-live, ≥ 0.95 by MS5 | Recall ledger (chart-review line) | MS3 |
| Real-world PPV, Asian charts | 64 % (Fujitsu) [V] | PPV of `strong` ≥ 0.75 | Silent prospective, wave 1 | MS3 |
| Trial ranking | Top-10 91 % (TrialGPT 2.0) [V, preprint]; top-20 92 % (TrialMatchAI) [V] | Top-5 ≥ 90 % on open site studies, non-oncology included | Tumour-board log | MS4 |
| Coordinator time | −86 % (ICU), −55 % (TrialGPT 2.0), −42.6 % (TrialGPT) [V] | ≥ −50 % per candidate by time-and-motion, not self-report | §20.9 baseline (PLAN-ROL-05) | MS3 |
| Enrolment effect | Eligibility 20.4 vs 12.7 %; enrolment 1.6 vs 0.9 % (JAMA RCT) [V] | Pre-registered stepped-wedge in Taiwan | §16 | MS4 start, MS6 report |
| Criteria parsing | Concept F1 0.891 (C2Q 3.0), 0.894 (AutoCriteria); SQL execution 0.91 (EC2Seq2Sql) [V] | Concept F1 ≥ 0.90 and 0 hallucinated codes; the LLM never writes SQL | `criteria_extract_public` | MS1 |
| Cost per screened patient | US$0.02–0.12, cloud [V] | Reported in NT$ on owned GPUs incl. amortisation; < US$0.05 expected *(est.)* | Gateway cost ledger | MS3 |
| EHR → eCRF | 0 % vs 8.23 % errors; 37 s per CRF; 51 min per participant [V] | ≥ 95 % structured agreement; errors prevented reported | 3 closed studies | MS5 |
| Abstraction | 99 % / 96 % / 91 % (Stanford, 100 patients) [V, preprint] | Equal on code-mixed notes, local model | M8 suite | MS5 |
| Enrolment forecasting | Duration MAE 7.52 months; AUC 0.78; PI Brier 0.38 [V] | Prospective calibration slope 0.8–1.2 on ≥ 20 trials | Forecast ledger | MS6 |
| Local CJK extraction | Macro-F1 0.906 (Gemma-2-27B QLoRA, ja) [V] | ≥ 0.90 on zh-TW code-mixed eligibility atoms | `criteria_zh`, site sets | MS2 |
| Bias | Stable except homelessness; subgroup gap ≤ 7 [V] | Gaps by sex, age band, insurance class and catchment ≤ 5 points or flagged | QA pack | MS3 |
| Structured output | 70/70 valid under schema enforcement [V] | 100 % parseable, logged per call | Gateway audit | MS0 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-BIC-01 | The validation pack (§16) MUST report each measured §19.4 target with n, 95 % interval, dataset hash and the bar it is compared with. Unmeasured targets are listed as such. | I | MS1 |
| PLAN-BIC-02 | A comparison with a competitor figure MUST state that the datasets differ, unless both systems ran on the same data. | I | MS1 |

### 19.5 Claims policy

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-CLM-01 | External material MUST cite only competitor figures tagged [V] or [R], with the source. [Unverified] and [Vendor] figures, including Lind's 94.2 %, MUST NOT be stated as fact. | I | MS1 |
| PLAN-CLM-02 | TrialBox performance figures MUST come from a frozen, signed validation or QA report and state dataset, language strata, n and interval. | I | MS1 |
| PLAN-CLM-03 | Primary evaluations (silent prospective, stepped-wedge) MUST be pre-registered and reported whatever the result, under DECIDE-AI, TRIPOD-LLM and CONSORT-AI headings. | I | MS3 |
| PLAN-CLM-04 | No material MAY describe TrialBox as deciding eligibility; the investigator decides (§15). | I | MS1 |

### 19.6 Pricing and commercial principles

The principles are fixed. Price level and support tiers are open (OD-09).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-COM-01 | TrialBox MUST be priced **per appliance**: one site licence per installation and topology, plus yearly support. There MUST be no per-patient, per-query, per-study, per-enrolment or revenue-share fee in any topology. | I | MS1 |
| PLAN-COM-02 | The hospital MUST own all outputs. These include packets, packs, lists, certificates, the site lexicon, library entries created at the site, adjudications, evaluation sets and the audit ledger. The supplier gets no right of use without a written grant for a named purpose, such as an alliance language pack (ML-12). | I | MS1 |
| PLAN-COM-03 | No sponsor, CRO or data network MAY pay for access to the hospital's patients through TrialBox. TrialBox is party to no per-patient or referral payment. | I | MS1 |
| PLAN-COM-04 | In topologies B and C the hospital MUST contract the tenant and any cloud model directly. The gateway cost ledger (§8) shows those costs without supplier mark-up. | I | MS4 |
| PLAN-COM-05 | The licence MUST NOT depend on buying hardware from the supplier. Any hardware that meets a profile (§4) is acceptable. | I | MS0 |
| PLAN-COM-06 | On termination, the hospital MUST keep read-only use for audit and retention. It MUST be able to export every record in open formats (FHIR R4 NDJSON, OMOP CDM 5.4, Parquet, PDF/A, XLSX, JSON ledger) with a verification procedure. | T | MS3 |
| PLAN-COM-07 | The list price and support-tier contents MUST be published to prospective hospitals. | I | MS4 |
| PLAN-COM-08 | The supplier MUST NOT enter referral, reseller or revenue agreements with screening vendors, sponsors, CROs or data networks that relate to the hospital's patients or data (C-1). | I | MS0 |
| PLAN-COM-09 | Open evaluation assets MAY be published under their source licences (App. H), with the not-clinician-verified status of translations stated. Site-derived data MUST NOT be published without hospital and IRB approval. | I | MS1 |

## 20. Delivery plan

This section defines how v4 is built, validated and put into service. Rollback procedures are normative in §18.5; §20.14
only fixes who invokes them, and how fast, during rollout. Weeks count from the start of sprint 1. All durations are
estimates *(est.)*.

### 20.1 Planning assumptions

| # | Assumption | If wrong |
| --- | --- | --- |
| A1 | Core team of 7 FTE (range 6–8) plus part-time site roles (§20.4) | Each FTE below 7 adds about 12 % to the time to MS3 *(est.)* |
| A2 | Coding agents execute specified tasks. Humans own design authority, gates, validation and the site relationship. | Effort to MS1 rises about 25 % *(est.)* |
| A3 | The first site runs topology A | Topology B first adds about 4 weeks of tenant work *(est.)* |
| A4 | The IRB umbrella application is submitted in week 2 and approved by week 26 *(uncertain)* | MS2 moves week for week; this is the critical path |
| A5 | A de-identified research-DB export (CGRD-type) with an honest-broker enrolment link is available by week 8 | The MS1 validation replay slips |
| A6 | HIS views are ready by week 10, and HL7 v2 or CDC by week 30 | Clinic-day lists stay next-day; the MS2 feed criterion needs a waiver |
| A7 | `OPENROUTER_API_KEY` is available by week 4 | Model choice relies on the on-box bench only |
| A8 | One GB10-class development unit is on hand by week 3 | The bench gate and hardware purchase (OD-11) slip |

**Re-estimation.** The review's M0–M6 ended at week 64. Round 2 had accepted 14 weeks to R1a and 22 weeks to R1b for
the smaller v3 scope with 4 engineers, and the review called 52 weeks optimistic (R3-44).

v4 adds four things:
- a data platform;
- an LLM platform;
- Hermes with a native fallback;
- four deliverable packs.

That is about 2.2× the v3 R1a scope, against 1.75× the team, plus coordination overhead *(est.)*. After MS2 the
clinical calendar sets the pace: IRB approval, at least 8 weeks of silent running, and two-week soaks per wave. The plan
therefore reaches MS3 (first department live) at about week 48 and MS6 at about week 96, with p80 dates about 20 %
later.

### 20.2 Governance

| Body | Chair | Members | Cadence | Decides |
| --- | --- | --- | --- | --- |
| **Steering committee (SC)** | Product owner | Research-office director (clinical trial centre), CISO, QA head, DPO/legal, a PI representative, tech lead | Monthly and at every MS gate | MS and wave go/no-go; scope and budget; acceptance of risks scored ≥ 15; open decisions (§21); validation summary sign-off |
| **Change-control board (CCB)** | Tech lead | QA/validation lead, security engineer, ML/eval engineer; the data steward for data and contract changes; a clinical representative for changes with clinical impact | Weekly; ad hoc for fast-track | All G5 changes (models, prompts, lexicon, thresholds, routing policy, Hermes upgrades, bundles); post-baseline changes to this specification; production configuration; deviation acceptance |
| **Design authority (DA)** | Tech lead (architect) | Workstream leads, security engineer; the DPO for any data-class boundary change | Fortnightly | ADRs (§4); interfaces and contracts (§6); class boundary and routing-policy design (§7, §8); standards (§17) |

Working cadence:
- Stand-ups are daily.
- Sprint reviews are fortnightly. The CRC champion attends from MS1.
- The risk review is fortnightly (§20.13).

Escalation goes from the workstream lead to the DA or the CCB, then to the SC. An item blocked for more than 5 working
days moves up one level.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-GOV-01 | The SC MUST record a go/no-go at every milestone and every rollout wave. The record lists each exit criterion with its evidence, each KRI value, the open risks scored ≥ 15, and the decision with its signatories. | I | MS0 |
| PLAN-GOV-02 | Every G5 change and every post-baseline change to this specification MUST pass the CCB. The submission includes an impact analysis, test evidence and a named rollback unit from §18. Fast-track rollbacks follow §18 and are reviewed at the next CCB. | I | MS0 |
| PLAN-GOV-03 | Any change to which data class may reach which endpoint MUST be approved by the DA, with the security engineer and the DPO present, before it goes to the CCB. | I | MS0 |
| PLAN-GOV-04 | SC, CCB and DA decisions MUST be stored signed-tagged in `docs/governance/` and cross-referenced from the affected ADR, change request or OD. | I | MS0 |

### 20.3 Workstreams and RACI

| WS | Workstream | Lead | Scope |
| --- | --- | --- | --- |
| WS1 | Data platform | Data platform engineer | §5; contracts, OMOP, terminology, MPI, lineage, DQ |
| WS2 | Core and IR | Backend engineer (core) | §6 IR v3; compiler; criterion library; cascade with S2b; cache; evidence; SAFE ledger |
| WS3 | Matching | ML/eval engineer | §10.5; TrialGPT port; retrieval; recruitability model |
| WS4 | LLM platform | LLM platform and security engineer | §8 gateway, registry, routing, guardrails, traces, bake-off, shadow |
| WS5 | Hermes and channels | Backend engineer (workflows) | §9; channels; front-door MCP server; native fallback; signing page |
| WS6 | Deliverables | Backend engineer (core) and clinical informatics | §12 packs, figures, exchange formats |
| WS7 | Security | LLM platform and security engineer with the hospital CISO | §14 |
| WS8 | Validation and QA | QA/validation engineer | §15, §16, §20.6 |
| WS9 | Site enablement | Product owner | §20.9–§20.11 |

RACI roles:
- PO: product owner.
- TL: tech lead / design authority.
- WL: workstream lead.
- QA: validation lead.
- SEC: security engineer and CISO.
- DS: data steward.
- IT: hospital IT.
- RO: research office.
- CL: PI sponsor and CRC champion.
- DPO: DPO, legal and IRB liaison.

| Workstream / decision | PO | TL | WL | QA | SEC | DS | IT | RO | CL | DPO |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WS1 Data platform | I | A | R | C | C | R | R | I | I | C |
| WS2 Core and IR | I | A | R | C | I | C | — | I | C | — |
| WS3 Matching | C | A | R | C | I | I | — | C | C | — |
| WS4 LLM platform | I | A | R | C | R | — | C | — | — | C |
| WS5 Hermes and channels | C | A | R | C | R | — | C | I | C | C |
| WS6 Deliverables | C | A | R | C | I | C | — | R | C | C |
| WS7 Security | I | C | R | C | A | — | R | — | — | C |
| WS8 Validation and QA | I | C | C | A/R | C | C | C | I | C | C |
| WS9 Site enablement | A | C | C | C | I | C | C | R | R | C |
| Class boundary or routing-policy change | I | R | C | C | A | — | I | — | — | C (must approve) |
| G5 change | I | A | R | C | C | — | — | I | C | — |
| Signed bundle release | I | A | R | R | C | — | I | I | — | — |
| MS go/no-go | A | R | C | R | C | C | C | C | C | C |
| Wave go/no-go | A | C | C | R | C | C | C | R | R | I |
| Rollback invocation (§18) | I | A | R | C | C | C | R | I | I | I |

### 20.4 Team sizing and roles

| # | Role | FTE | Workstreams | Joins |
| --- | --- | --- | --- | --- |
| 1 | Tech lead / architect (DA chair) | 1.0 | All | Week 1 |
| 2 | Backend engineer: core, IR, deliverables | 1.0 | WS2, WS6 | Week 1 |
| 3 | Backend engineer: workflows, channels, Hermes | 1.0 | WS5 | Week 1 |
| 4 | Data platform engineer (HL7 v2, FHIR Bulk, CDC, OMOP, terminology) | 1.0 | WS1 | Week 1 |
| 5 | ML/evaluation engineer (retrieval, LTT, statistics, bake-off) | 1.0 | WS3, eval | Week 1 |
| 6 | LLM platform and security engineer (gateway, vLLM, SLSA, threat modelling) | 1.0 | WS4, WS7 | Week 1 |
| 7 | QA/validation engineer (GAMP 5, CSA, trace matrices) | 1.0 | WS8 | Week 3 |
| 8 | Clinical informatics and language specialist (recommended) | 0.5–1.0 | Lexicon, annotation, zh-TW/ja, WS6 | Week 6 |
| — | Product owner | 0.5 | WS9, SC chair | Week 1 |
| — | Site roles | CRC champion 0.2; data steward 0.3; IT 0.1–0.2; DPO/legal 0.05–0.1; PI sponsor about 2 h/week per pilot study; annotators per sample | — | Weeks 2–8 |

Effort to MS3 in person-weeks *(est.)*:

| WS1 | WS2 | WS3 | WS4 | WS5 | WS6 | WS7 | WS8 | WS9 | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | 40 | 20 | 30 | 20 | 20 | 22 | 30 | 18 | 250 |

Capacity to week 48 at 7 FTE and 75 % productive time is about 252 person-weeks. That leaves no buffer, which is why
the 8th role is recommended.

Annotation is costed separately:
- Anytime-valid bounds need about twice the single-look samples when no miss is found (Appendix F).
- A 1 % claim at 0 found needs 595 audits.
- At about 2 minutes per audit, that is about 20 annotator hours per canonical-criterion pool *(est.)*.

### 20.5 Environments

| Env | Purpose | Data classes | Models | Where | Promotion in |
| --- | --- | --- | --- | --- | --- |
| DEV | Development, bake-offs, open-data runs | D0, synthetic | Stub; local small models; OpenRouter on the `bakeoff` route (D0 only) | Developer machines, CI runners, dev GB10 | — |
| TEST | CI: contract, integration, e2e, public suites, `redteam` | D0, synthetic | Stub; one pinned small model; recorded outputs | Ephemeral compose | Merge to main |
| VAL | De-identified validation replay; IQ/OQ/PQ; D2 shadow passes | D0, D2 | On-prem registry builds (cloud for D2 only under the §7 sign-off; default off) | Site partition or second box with TRE controls | Signed bundle + CCB |
| STAGE | Inactive blue/green slot; smoke and e2e before switch-over | D3 read-only snapshot pin; outbox paused | Production builds | Production host | Signed bundle + CCB |
| PROD | Production | Per topology (§7, App. G) | Routing policy per topology | Topology A, B or C | STAGE pass + SC wave decision |
| DR | Restore drills and disasters | As PROD, during a drill only | As PROD | Spare box or tenant | §18 runbook |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-ENV-01 | D3 and D4 MUST exist only in PROD, STAGE and DR; VAL holds only D0 and D2. `doctor` MUST verify the environment's class ceiling at start-up. | T | MS0 |
| PLAN-ENV-02 | Only CI-built signed bundles MAY be installed in VAL, STAGE and PROD. The `bakeoff` route MUST be disabled outside DEV. | T | MS0 |
| PLAN-ENV-03 | Every environment's configuration MUST be in Git, with secrets in the key store (§14). `doctor` reports drift. | T | MS1 |
| PLAN-ENV-04 | VAL MUST enforce the TRE controls of §7: no outbound network, a separate DB role, and steward review of outputs. | T | MS1 |
| PLAN-ENV-05 | A DR restore MUST be executed before MS3 and quarterly after that, with a signed record. | D | MS3 |

### 20.6 GAMP 5 V-model deliverables

TrialBox is custom software (GAMP 5 2nd ed., Category 5). Its configured components (vLLM, HAPI, Postgres, Hermes) are
categorised item by item. Validation is risk-based (FDA Computer Software Assurance guidance; GAMP 5 2nd ed.).
`trialbox validate` generates IQ/OQ evidence, and the trace matrix is built from the `@req` markers (§17).

| Deliverable | Owner | Approved by | Content |
| --- | --- | --- | --- |
| Validation plan | QA | MS0 | Scope, risk approach, roles, acceptance; E6(R3) §4.3 and Annex 1 |
| URS | PO, TL | MS0 | This specification (ISO/IEC/IEEE 29148 structure) |
| Risk assessment | QA, TL | MS1, then per release | FMEA per function: patient safety, data integrity, privacy |
| Supplier assessments | QA, SEC | MS1 | Hermes release, vLLM, HAPI, model publishers (licence, origin), cloud provider, IdP |
| DPIA | DPO | MS2 (before identifiable processing) | PDPA basis; cross-border analysis for C; re-identification method |
| Functional and design specifications, ADRs, threat model | WL, TL, SEC | MS1, then per change | Per workstream; C4 and MADR; STRIDE, OWASP LLM Top 10 2025, MITRE ATLAS |
| Site configuration specification | TL, DS, IT | G0 | Topology, profile, sources and contracts, routing, channel engine, thresholds |
| AI credibility file per AI function | ML, QA | Per G5 | Context of use, model risk, evaluation per stratum, failure modes (FDA draft guidance on AI for regulatory decision-making, Jan 2025; EMA reflection paper) |
| IQ / OQ protocols and reports | QA | Per install and release | `trialbox validate`: signatures, SBOM, host, egress, keys; functional suites, FR-SIG negatives, `redteam`, restore |
| PQ protocol and report | QA, CL | Protocol MS2, report MS3 | Silent prospective and wave-1 results against §16 acceptance |
| Traceability matrix | QA | Per release | `tools/trace_matrix.py` |
| SOPs | QA, IT | MS2 | Change control, incident and breach, backup and restore, access recertification, audit-trail review, rollback (§18) |
| Training records | WS9 | Before each wave | Per role (§20.10) |
| Validation summary report; periodic review | QA | MS3 and each MS; yearly | Deviations, open risks, release statement |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-VAL-01 | Each §20.6 deliverable MUST be approved before the SC go/no-go of the milestone in its "Approved by" column. | I | MS0 |
| PLAN-VAL-02 | Every requirement with V = T MUST map to at least one automated test with its `@req` marker before its R milestone. `tools/trace_matrix.py` MUST fail the release otherwise. | T | MS0 |
| PLAN-VAL-03 | OQ MUST be re-executed after every bundle or G5 change, scoped by the CCB's risk assessment, before the STAGE → PROD switch. | T | MS1 |

### 20.7 Milestones MS0–MS6

The review's M0–M6 are renamed MS0–MS6 (modules keep the names M0–M11) and re-estimated (§20.1). "p80" is the week by
which the milestone is 80 % likely to be met *(est.)*.

| MS | Name | Weeks | p80 | Scope |
| --- | --- | --- | --- | --- |
| MS0 | Foundations | 1–10 | 12 | Data platform L0–L5 thin path (Synthea 300k, MIMIC-IV FHIR demo) with reconciliation, publish gate and lineage; durable steps and outbox; `tb-gateway`, registry, routing policy, trace store; front-door MCP server; Hermes and native engines; recall ledger with confidence sequences; public suites in CI; VP, URS, threat model; dev bench |
| MS1 | Feasibility on de-identified data | 11–24 | 28 | IR v3; criterion library (Chia, ClinicalTrials.gov); match-then-draft; cascade S0–S4 with S2b; terminology service; OMOP in L2 for VAL; feasibility pack with figures; recruitability model v1; validation replay; bake-off and shadow builds; bench gate; IQ/OQ; Level A approvals; PET kit |
| MS2 | Pre-screening, silent mode | 25–36 | 42 | IRB and PDPA basis; L3 with MPI merges; HL7 v2 or CDC; shadow clinic-day lists; recall ledger live; LTT from the public prior; `potential` split; multi-span evidence; sentence-set cache; Level B signing; site `judge_ml`; PQ protocol; silent prospective started |
| MS3 | Live, wave 1 (one department) | 37–48 | 56 | ≥ 8 weeks silent comparison with CRC logs; wave 1 with a 2-week soak and hypercare; validation summary report |
| MS4 | Recruitment engine and start-up | 49–64 | 74 | Waves 2–3; accrual and site-performance packs; forecast ledger; M7 playbooks; Teams nudges; patient → trials and tumour board; optional review page; topology C for D1 if OD-02 is decided; stepped-wedge started; offline prompt optimisation |
| MS5 | Conduct and data | 65–80 | 92 | Visits, deviations, SAE clocks, RBQM KRIs, TMF/ISF completeness; eSource packets, pre-fill, query drafts; OMOP endpoint; federated TACTC answer; optional CDS Hooks card; close-out |
| MS6 | Second site and Japan profile | 81–96 | 112 | Second hospital from the offline bundle; JP Core adapter and ja suites; forecast calibration; validation paper; stepped-wedge report |

**Exit criteria and KRIs.** Every exit criterion must be met or waived in writing by the SC with a risk entry. Any KRI
breach at the gate means no-go.

| MS | Exit criteria | Go/no-go KRIs |
| --- | --- | --- |
| MS0 | L1 blocks 100 % of planted defects on Synthea 300k (0.5 % row drop, type drift, duplicate key, null identifier). MIMIC-IV FHIR demo v2.1.0 ingests with 0 blocking DQ errors and complete lineage. Routing property test finds 0 routes from D3/D4 outside the perimeter. Intake e2e passes on `hermes` and `native`. Front-door `redteam` has 0 capability-bearing successes. `recall_cert` coverage is ≥ 95 % over 12 looks. `judge_public` reproduces GPT-4 accuracy 0.873 from recorded outputs. VP and URS are approved. | Critical defects = 0; schedule variance ≤ 2 weeks; TEST class violations = 0 |
| MS1 | `criteria_extract_public` structure F1 ≥ 0.85 and normalisation ≥ 0.80/0.70/0.65. `judge_public` ≥ 0.85 per stratum for the chosen J. S0–S2 funnel within ±15 % of a manual CRC funnel on 5 closed studies. Validation replay on ≥ 10 closed studies in ≥ 3 therapeutic areas, with anytime-valid bounds. Feasibility pack passes G2 on ≥ 2 live requests. Planned load is ≤ 50 % of night capacity (NFR-18). IQ/OQ are signed. The bake-off report exists, or a recorded waiver if there is no key. | PHI or class incidents = 0; D2 exports over the risk threshold = 0; snapshots published with blocking DQ = 0; reconciliation delta ≤ 0.5 % |
| MS2 | IRB approval and PDPA basis are on file. Feed reconciliation is ≤ 0.5 % for 4 weeks. Shadow lists run on ≥ 20 consecutive clinic days. A CS bound exists for every stratum, with both known-positive lines. `lexicon_recall` has run, and zero-hit exclusion is enabled only where recall ≥ 0.98. `judge_ml` has ≥ 100 site items per stratum, with a gap ≤ 5 points. FR-SIG negative tests pass. The PQ protocol is approved. The silent analysis is pre-registered. | PHI incidents = 0; `uncertain` sends = 0; class violations = 0; unresolved Hermes denial anomalies > 48 h = 0 |
| MS3 | ≥ 8 weeks silent prospective, capturing ≥ 0.80 of CRC-identified candidates, with AI-only candidates adjudicated. Chart-review recall lower bound ≥ 0.90. PPV of `strong` ≥ 0.75. CRC minutes per candidate −40 % against baseline. Wave-1 soak is green. Validation summary is signed. DR drill passes. | PHI incidents = 0; `uncertain` sends = 0; recall lower bound ≥ 0.90; abstention error ≤ α per stratum; gate backlog < 48 h; CRC satisfaction ≥ 4/5 |
| MS4 | ≥ 3 departments live after green soaks. Monthly accrual packs for ≥ 10 studies. `match_registry` recall@500 ≥ 0.90 and NDCG@10 ≥ 0.60. Tumour-board use on ≥ 10 cases, timed. If C is enabled: egress test, cost report and DPO sign-off for D1. Stepped-wedge has started. Every projection is in the forecast ledger. | As MS3; cost per candidate within budget; packs needing rework ≤ 20 % |
| MS5 | eSource packets accepted by a CRA on ≥ 1 study. Structured agreement ≥ 0.95 on 3 closed studies. OMOP endpoint used by ≥ 1 OHDSI study with DQD run. Federated TACTC answer with the ε ledger. RBQM KRIs in the Monday digest. | As MS4; SAE clock breaches caused by the box = 0 |
| MS6 | Second site goes from hardware arrival to signed IQ/OQ in ≤ 30 days. JP Core and ja suites are green. Forecast calibration is reported. The paper is submitted. Stepped-wedge is analysed per its pre-registration. | As MS5, at both sites |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-MS-01 | Each milestone MUST close with the PLAN-GOV-01 record and evidence for every exit criterion and KRI above. | I | MS0 |
| PLAN-MS-02 | A milestone still without a go decision at its p80 week MUST trigger a re-plan to the SC within 10 working days. The re-plan presents scope, capacity and date options. | I | MS0 |
| PLAN-MS-03 | No identifiable processing from a live source MAY start before IRB approval and DPIA approval. | I | MS2 |
| PLAN-MS-04 | No message about a live candidate MAY reach a PI or Sub-I before the wave-1 go decision. | T | MS3 |

**Critical path and external dependencies.**

| Dependency | Needed by | Owner | Lead time *(est.)* | Fallback |
| --- | --- | --- | --- | --- |
| IRB umbrella approval and PDPA basis (OD-05) | MS2 | DPO / IRB liaison | Submit week 2; 12–24 weeks *(uncertain)* | MS1 continues on de-identified data |
| Research-DB export and honest-broker link | MS1 | Data steward, research office | 4–8 weeks | Synthea and open data; replay moves to MS2 |
| HIS read-only views | MS1–MS2 | Hospital IT | 4–10 weeks | CSV drops under a data contract |
| HL7 v2 or CDC feed | MS2 | IT, HIS vendor | 8–20 weeks *(uncertain)* | Nightly views; next-day lists |
| Hardware (OD-11) | MS0 (dev), MS1 (prod) | PO, IT | 2–8 weeks *(volatile prices)* | P-5090 profile |
| IdP integration (OIDC) | MS2 | IT, SEC | 4–8 weeks | Sealed break-glass accounts; B1 passkeys |
| Clinician review of the zh-TW/ja/mixed note translations | MS2 | Clinical informatics | 4 weeks | Synthetic strata labelled "not clinician-verified" |
| Cloud tenant and contract (OD-02) | MS4 | PO, DPO | 8–16 weeks | Topology A only |

### 20.8 First sprint (weeks 1–3), in dependency order

v3's first task deleted the cloud-LLM path. v4 does the opposite: the cloud branch of `libs/tb_common/llm.py` becomes
gateway routes under class policy (S1-06). Package paths follow the normative layout of §17.1. If the two ever differ, §17.1 governs and
the CCB updates this table. Every task ends with tests carrying `@req` markers.

| # | Task | Deps | Files | Done when |
| --- | --- | --- | --- | --- |
| S1-01 | **Data-class contract.** Add a D0–D4 enum and a `ClassLabel` model; every payload that crosses a boundary carries `data_class`. Contracts come first (§17.2). | — | `libs/tb_contracts/dataclass.py`, `libs/tb_common/policy/classes.py`, `schemas/` (generated), `tests/unit/test_dataclass.py` | A missing or unknown class fails validation; every existing contract has a class; mypy strict passes |
| S1-02 | **L0 Landing.** Immutable landing per source × batch, with a manifest {source, extract_time, rows, bytes, sha256, schema_fingerprint}. | S1-01 | `services/dataplat/landing/`, `libs/tb_contracts/landing.py`, `services/dataplat/sources/` (v1 `services/adapter/sources/` moved) | Re-landing is idempotent; a one-byte change is detected; raw retention is 90 days |
| S1-03 | **L1 Validation and publish gate.** Data contracts; reconciliation against control totals (`count(*)`, `max(delta)`, `count(distinct mrn)`); Kahn-style DQ rules; quarantine with reason codes; steward email; no partial publish. | S1-02 | `services/dataplat/validate/`, `services/dataplat/{contracts,reconcile,dq,publish}/`, `libs/tb_testkit/` (planted-defect generators), `tools/gen_contracts.py` | Each planted defect on Synthea 300k blocks publish with its reason code. MailHog receives the diff. The previous snapshot stays current. |
| S1-04 | **L2–L5 thin path and lineage.** Wrap the v1 adapter as the stages: standardise; pseudonymise with an MRN → MPI merge table; curated snapshot manifest; serving pin. Emit OpenLineage events. | S1-03 | `services/dataplat/{standardise,pseudonymise,curated,serving,mpi,lineage}/` (from v1 `services/adapter/` and `services/lake/` with import shims), `tests/e2e/test_ingest_fhir_demo.py` | The MIMIC-IV FHIR demo (via `tools/fetch_open_data.py`) becomes a snapshot with 0 blocking DQ errors and full lineage. An A40-style fixture maps two MRNs to one pid. |
| S1-05 | **Durable steps and outbox** (v3 S1-6; skip if merged). | S1-01 | `services/orchestrator/` (`db_pg.py`, `outbox.py`), `deploy/topology_a/` (compose) | Kill-loop e2e gives exactly one delivery per outbox row |
| S1-06 | **`tb-gateway` v0 with class policy.** OpenAI-compatible proxy with caller identity, declared class, route lookup, refusal on mismatch, structured-output pass-through, cache keyed by (prompt sha, model sha), and an audit record (prompt sha, model sha, class, tokens, latency, cost, purpose). All callers use `libs/tb_llm`, which talks only to the gateway. Egress lets only the gateway reach model hosts. | S1-01 | `services/gateway/`, `models/routing.yaml`, `libs/tb_llm/` (replaces `libs/tb_common/llm.py`, shim for one milestone), `deploy/egress.py`, `tests/unit/test_routing_policy.py`, `tests/unit/test_egress_rules.py` | A property test over (role, class, profile, topology) finds 0 routes from D3/D4 outside the perimeter. A mismatch is refused and audited. No container other than the gateway has a model-host egress rule. |
| S1-07 | **Model registry v0 and model cards.** Alias → pinned build (SHA-256, revision, quantisation, licence, origin); candidate/shadow/champion/retired statuses; served-model echo. | S1-06 | `services/registry/`, `models/registry.yaml`, `models/cards/`, `tools/trialbox/` (`registry` command) | The gateway resolves aliases from the registry. A stub serving the wrong name is detected. Manifests print the served model and SHA. |
| S1-08 | **Trace store and redaction.** Traces go to a self-hosted store (OD-14) with redaction at write. Extend `phi_guard` with national ID, ARC, passport, phone and address patterns. | S1-06 | `services/tracestore/`, `services/guard/` (PHI recognisers; `libs/tb_common/phi_guard.py` folded in), `eval/suites/deid_synthetic/` | On ≥ 200 synthetic items with planted identifiers, no planted ID appears in traces. Recall is reported. Retention is 90 days. |
| S1-09 | **Front-door MCP server.** Tools: `tb.submit_request`, `tb.status`, `tb.ask_protocol`, `tb.registry_search`, `tb.atlas_describe`, `tb.aggregate_query` (T1, accountant), `tb.resend_released_file`, `tb.ops_read` (exactly the §9.3 list; HELP is served by SOP skills). Each runs in the orchestrator policy context and writes the audit event before returning. | S1-05, S1-06 | `services/frontdoor_mcp/`, `libs/tb_contracts/frontdoor.py`, `tools/mcp_snapshot.py` | Contract tests per tool. No T2/T3 tool is listed. Unauthenticated calls are refused. Small cells are suppressed. |
| S1-10 | **Channel abstraction and native engine.** `Channel` interface; native email and Teams (no PHI); `channels.engine: hermes \| native`. Grammar lines are parsed deterministically; plain text becomes a `classify_intent` proposal via the gateway. | S1-09 | `services/channels/` (base, `native/email`, `native/teams`; v1 `services/mail_gateway/` moved), `schemas/settings.schema.json` | On `native`, 「這個試驗做得起來嗎」 plus a PDF yields a proposal, and `OK` starts FEAS |
| S1-11 | **Hermes, pinned and hardened.** Vendored tag + SHA. Only the front-door MCP toolset. Memory off; approvals manual; cron and unattended denied; MCP sampling and elicitation off; private URLs off. The `tb_policy_audit` plugin's `pre_tool_call` fails closed. | S1-10 | `integrations/hermes/` (`profiles/tb-internal.yaml`, `hermes.lock`, the `tb_policy_audit` plugin), `tests/security/test_hermes_config.py`, `eval/redteam/` | CI lint asserts every setting. The intake e2e passes on `hermes`. `redteam` has 0 capability-bearing successes. Switching to `native` mid-conversation loses no request. |
| S1-12 | **Recall ledger with confidence sequences.** Persist and resume `ConfidenceSequence` state per (canonical criterion, stratum). The certificate has two labelled known-positive lines. Add the `recall_cert` simulation. | S1-05 | `libs/tb_common/recall.py`, `services/orchestrator/calibration/`, `libs/tb_contracts/recall.py`, `eval/suites/recall_cert/` | State round-trips byte-identically. Over 12 looks, CS miss-coverage is ≤ 5 % (reference 0.3 %), and repeated CP exceeds 5 % (reference 9.7 %). |
| S1-13 | **Public suites in CI.** `judge_public` (stub and recorded outputs through the gateway), `ingest_fhir_demo`, and a Chia loader for `criteria_extract_public`. Results are archived with dataset hashes. | S1-04, S1-06 | `tools/trialbox/` (`eval`), `tools/mlbench.py`, `eval/suites/{judge_public,ingest_fhir_demo,criteria_extract_public}/`, `eval/DATASETS.yaml`, `Makefile` (`eval-public`) | The GPT-4 reference reproduces accuracy 0.873 and false-block 0.014 exactly. `ingest_fhir_demo` is green. |
| S1-14 | **Bake-off as code.** `tools/bakeoff.py` drives `mlbench` through the gateway `bakeoff` route (OpenRouter, D0 only). Candidates come from the registry. Per-language floors; cost and latency per 1k items. | S1-07, S1-13 | `tools/bakeoff.py`, `tools/mlbench_tasks/`, `models/routing.yaml`, `models/registry.yaml`, `eval/bakeoff/weights.yaml` | Without a key: `--dry-run` prints the plan and a cost estimate, and a D1 payload on `bakeoff` is refused. With `OPENROUTER_API_KEY`: the report has per-stratum accuracy, false-block rate, bootstrap CIs, cost and latency, and the top two per role become `shadow`. No result is recorded before the run. |
| S1-15 | **IR v3 schema and criterion-library tables.** Line of therapy, attributes, derived calculators, screening/randomisation anchors, organ-function macro; library keyed by canonical hash; Chia seed. | S1-01 | `libs/tb_contracts/criterion_ir.py` (generated schema in `schemas/`), `services/criteria_compiler/library/` | All v1/v3 rulesets validate and re-run byte-identically. The Chia seed loads, and its duplicate rate is reported. |
| S1-16 | **`trialbox doctor` for v4.** Checks topology, environment class ceiling, gateway-only model reach, channel engine and fallback, Hermes pinned SHA, publish-gate state. | S1-06, S1-11 | `tools/trialbox/` (`doctor`), `deploy/check_host.sh` | Fails closed on a D3/D4 route outside the perimeter, an unpinned Hermes image, or D3 data in DEV |

Parallel tracks in sprint 1:
- WS1 runs S1-02 → S1-04.
- WS4 runs S1-06 → S1-08, then S1-14.
- WS5 runs S1-05 → S1-09 → S1-11.
- WS2 runs S1-15 and S1-12.
- WS8 drafts the VP.
- WS9 submits the IRB application and schedules the time-and-motion baseline.

### 20.9 Site rollout waves

| Phase | Entry | Activities | Duration *(est.)* | Exit |
| --- | --- | --- | --- | --- |
| R0 Readiness | Contract; OD-01, OD-11 | Firewall rules, IdP plan, key-ceremony plan, IRB and DPIA submitted, site configuration drafted, baseline time-and-motion scheduled | 2–4 weeks | Checklist signed by IT, DPO and PO |
| R1 Install | Hardware or tenant ready | `trialbox install --topology A\|B\|C --profile <p>` from the signed offline bundle; dual-control key ceremony | 1–3 days | Install record |
| R2 Doctor / bench / validate | Install record | `doctor`; `bench` (NFR-17/18); `validate` (IQ, OQ) | 1 week | IQ/OQ signed |
| R3 Atlas and G0 | IQ/OQ | Source onboarding with contracts; reconciliation; DQ scorecard; terminology coverage; lexicon seed; steward review | 3–6 weeks | G0 approved; ≥ 4 consecutive green publishes |
| R4 Shadow | G0 | Full passes with **no messages to PIs or CRCs**; validation-team review; feasibility on de-identified data; calibration from the public prior | ≥ 4 weeks | Stable metrics; no open critical defect |
| R5 Silent prospective | IRB; MS2 exit | Packets to the CRC champion only; comparison with CRC logs; blinded chart review; care and contact unchanged | ≥ 8 weeks | MS3 criteria; SC go for wave 1 |
| R6 Department waves | SC go | Wave 1: one department. Wave 2: two. Wave 3: the rest, ≤ 3 at a time. Each wave has a ≥ 2-week soak with daily KRI review, then a go/no-go. | 2–4 weeks per wave | All KRIs green over the soak |
| R7 Hypercare | Last wave live | Daily health check; named on-call; twice-weekly CRC check-in; weekly SC summary; critical defects fixed in ≤ 2 working days | 4 weeks | KRIs green for 4 weeks |
| R8 Steady state | Hypercare exit | Monthly QA pack; quarterly access recertification and DR drill; yearly periodic review and pen test | Ongoing | — |

**Rollout KRIs.** These are measured daily during soak and hypercare, and monthly after that.
- **Stop** halts outbound packets for the affected scope and invokes the §18 rollback named in the table.
- **Hold** means no new wave starts until the KRI is green.

| KRI | Threshold | Source | Breach action |
| --- | --- | --- | --- |
| PHI incidents | 0 | Incident log, DLP | Stop; breach workflow (§14); rollback (§18) |
| Unexplained class refusals at the gateway | 0 | Gateway audit | Stop the route; routing-policy revert |
| `uncertain` outbox sends | 0 | Outbox | Stop the outbox |
| Chart-review recall lower bound | ≥ 0.90 | Recall ledger | Hold; demote the affected criteria |
| Abstention error per stratum | ≤ α | Calibration monitor | Hold; thresholds back to the previous registry entry |
| PPV of `strong` | ≥ 0.75 after 50 decisions *(est.)* | G3 decisions | Hold; ruleset or threshold review |
| Median G3 gate backlog | < 48 h | Gate store | Hold; review PI load |
| Packets on schedule | ≥ 95 % | Scheduler, outbox | Hold |
| Reconciliation delta | ≤ 0.5 % | L1 | Snapshot pin T−1 (automatic) |
| Hermes capability-bearing injection | 0 | `redteam`, traces | Stop Hermes; `channels.engine: native` |
| CRC satisfaction (monthly, 1–5) | ≥ 4 | Two-question survey | Hold; training or workflow review |
| Candidates per PI per week | ≤ site cap (default 20) | Packets | Hold; adjust cadence or scope |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-ROL-01 | Every site MUST pass R0–R8 in order. Skipping a phase needs an SC waiver with a risk entry. | I | MS3 |
| PLAN-ROL-02 | Each wave MUST have a soak of ≥ 2 weeks with daily KRI review, and an SC go/no-go before the next wave. | I | MS3 |
| PLAN-ROL-03 | A "stop" breach MUST halt outbound packets for the affected scope within 1 hour, through the per-module kill switch (§3). | T | MS3 |
| PLAN-ROL-04 | In shadow mode the outbox MUST refuse and audit any message to a PI, Sub-I or CRC. | T | MS2 |
| PLAN-ROL-05 | The CRC pre-screening time-and-motion baseline MUST be measured, under a fixed protocol, before R4. | D | MS2 |

### 20.10 Training, change management and communication

| Audience | Content | Format | When | Competency check |
| --- | --- | --- | --- | --- |
| CRC | Packets and decision sheets; plain language with Hermes and the grammar fallback (App. D); five-minute reviews; annotation; what the box never does | 60 min hands-on with synthetic packets; 1-page guide (zh-TW, en) | Before R5 (champion); before each wave | Correct decisions on a synthetic packet; annotators reach κ ≥ 0.8 |
| PI / Sub-I | Evidence quotes and tiers; `potential:data_gap` vs `potential:uncertain`; G3 means the investigator decides; Level B ceremony and passkey enrolment | 20 min; 1-page guide; enrolment in person | Before the department's wave | Passkey enrolled; one test signature |
| Research office | Packs; G2; the Hermes aggregate analyst; AI disclosure wording | 45 min | MS1 | Sends a pack through G2 |
| Data steward | Atlas; contracts; DQ scorecard; quarantine; erasure and merges | 2 × 90 min | R3 | Resolves a planted quarantine |
| Administrator / IT | Control plane; kill switches; routing proposals; channel switch; backup and restore; §18 runbooks | 1 day, including a rollback rehearsal | R1–R2 | Bundle rollback and channel switch in STAGE |
| IRB / QA; sponsors / CRAs | QA pack, audit search and certificates; for sponsors, a 1-page note on pack content, provenance and AI disclosure | 45 min; 1-page note | MS2; first pack per sponsor | — |

**Change management.**
- **Champions.** There is one CRC champion per wave and a PI sponsor per pilot study. They see outputs first (R5) and
  shape the guides.
- **Adoption measures.** These are taken from decisions and requests only, with no read-tracking:
  - G3 decisions returned within 7 days;
  - share of requests in plain language;
  - minutes per candidate;
  - satisfaction.
- **Alert fatigue** is documented for EHR trial alerts (Embi & Leonard, JAMIA 2012). The responses are per-PI weekly
  caps, digests, and no message that needs no action (§3).
- **Trust.** Every `met` carries a quote, `potential:uncertain` is shown as uncertain, and the certificate states what
  may have been missed.
- **CRC role.** The box never contacts patients or decides. Time saved is reported as capacity for consent and
  follow-up.
- **Feedback.** Feedback through the front door is triaged weekly by the WS9 lead. Clinical-behaviour changes go to the
  CCB.

**Communication.**

| Audience | Message | Channel | Frequency | Owner |
| --- | --- | --- | --- | --- |
| SC; hospital leadership | Status, KRIs, risks ≥ 15, decisions; one-page outcome summary | SC pack; email | Monthly and at gates; quarterly | PO |
| PIs and Sub-Is in a wave | What changes, when, what to do, whom to ask | Email (zh-TW/en); department meeting | 2 weeks before go-live, at go-live, at end of soak | Research office |
| CRCs | Schedule, training, office hours, known issues | Hermes/email; Teams (no PHI) | Weekly during waves | WS9 lead |
| Data steward, IT | Feeds, DQ, quarantines, maintenance | DQ scorecard email | Per publish; weekly | WS1 lead |
| IRB; QA | Approvals, amendments, deviations, incidents; QA pack | Formal submission; QA pack | As required; monthly | DPO; QA lead |
| Sponsors / CRAs | Pack content, provenance, AI disclosure | Email from a named site person | Per pack | Research office |
| Those affected by an incident or rollback | What happened, impact, actions, next update | §18 templates (zh-TW/en) | Per §14 and §18 timings | Incident commander |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PLAN-TRN-01 | No person MAY receive candidate packets or approve gates before their training record for the role exists. The delegation log and training records (M7) MUST gate recipients. | T | MS3 |
| PLAN-TRN-02 | The CRC and PI 1-page guides MUST exist in zh-TW and en before wave 1, and in ja before MS6. | I | MS3 |
| PLAN-TRN-03 | Annotators MUST reach Cohen's κ ≥ 0.8 on the training set before contributing labels. | T | MS2 |
| PLAN-COMM-01 | Each wave MUST be announced to the affected PIs and CRCs ≥ 2 weeks ahead, in zh-TW and en, with training dates and a named contact. | I | MS3 |
| PLAN-COMM-02 | Incident and rollback communication MUST use the §18 templates and timings and MUST NOT contain PHI. | I | MS2 |

### 20.11 Cost tracking

The following are reported in the SC pack every month:
- engineering burn-up per workstream;
- annotation hours per site (Appendix F);
- the gateway cost ledger per study, module and month (§8);
- hardware and tenant spend;
- bake-off spend, with a cost estimate before each run and PO approval above a set limit.

### 20.12 Assumption checks at each gate

At every MS gate, the SC re-checks assumptions A1–A8 (§20.1). A failed assumption becomes a risk entry (§20.13), and if
it moves a date it triggers PLAN-MS-02.

### 20.13 Risk register

L is likelihood and I is impact, each scored 1–5; the score is L × I. Scores ≥ 15 go to the SC. The register is kept in
`docs/governance/risk_register.yaml`, reviewed fortnightly and included in each SC pack.

| ID | Risk | L | I | Owner | Mitigation | Trigger |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-RK-01 | IRB approval later than week 26 | 4 | 5 | DPO | Submit in week 2; pre-submission meeting; MS1 entirely on de-identified data; umbrella protocol with addenda | No decision by week 20 |
| PLAN-RK-02 | IT bandwidth delays views or feeds | 4 | 4 | WS1 lead | Ready-made contracts and control-total queries; CSV fallback; IT time agreed at R0 | Feed not live 4 weeks after request |
| PLAN-RK-03 | On-prem small models miss the bar on zh-TW code-mixed notes | 3 | 5 | ML lead | Bake-off with per-language floors; larger V model at night; S4 escalation; P-Scale | `judge_ml` stratum below floor or gap > 5 |
| PLAN-RK-04 | No `OPENROUTER_API_KEY`, so the bake-off is delayed | 3 | 2 | PO | Bench-only choice on the dev unit; dry-run plan ready | No key by week 6 |
| PLAN-RK-05 | Machine-translated NCBI notes mislead parity results | 3 | 3 | Clinical informatics | Labelled synthetic strata; clinician review of a stratified sample before MS2; site items decide | Reviewer disagreement > 5 % |
| PLAN-RK-06 | Chia (English) seed matches few Taiwanese protocols | 3 | 3 | WS2 lead | Seed from MOHW-disclosed protocols and TW-site CT.gov records; track match share | < 30 % matched after 10 protocols |
| PLAN-RK-07 | Lexicon recall < 0.98 for most criterion types, so S2b load exceeds the night budget | 3 | 4 | WS2 lead | Embedding screen; sentence-set cache; NFR-18 reduces scope or cadence | Planned load > 50 % of capacity |
| PLAN-RK-08 | Anytime-valid bounds double the audit samples, burdening CRCs | 4 | 3 | QA lead | Pooling per canonical criterion; importance weighting; budgeted monthly load; research-nurse annotators | Annotation hours over budget |
| PLAN-RK-09 | Hermes advisory or breaking upgrade | 3 | 4 | SEC | Pinned vendored release; native fallback tested in CI; upgrades via G5 | Advisory on the pinned version |
| PLAN-RK-10 | Prompt injection via chart content, sponsor documents or email | 3 | 5 | SEC | CDR; quarantined extractor; delimited blocks; guard classifiers; no tools on the judging path; `redteam` | Any capability-bearing success |
| PLAN-RK-11 | PDPA analysis or IRB blocks topology C | 3 | 2 | DPO | A is complete without C | Negative DPO opinion |
| PLAN-RK-12 | No compliant in-country region for topology B | 3 | 3 | PO | A as default; region survey (OD-02) | Survey negative |
| PLAN-RK-13 | Loss of a key engineer | 3 | 4 | TL | Pairing; ADRs; agent runbooks; documented tasks | Resignation or long absence |
| PLAN-RK-14 | Low CRC adoption or PI alert fatigue | 3 | 4 | WS9 lead | Caps, digests, champions, plain-language front door | G3 within 7 days < 60 % |
| PLAN-RK-15 | HIS data quality limits computability (ROC dates, local codes, units) | 4 | 3 | Data steward | DQ scorecard; terminology coverage; mapping proposals via G0 | Atlas coverage < 90 % on a core domain |
| PLAN-RK-16 | MPI merge errors split or join patients | 2 | 5 | WS1 lead | A40 merge table; identity reconciliation; merge reversal; tests | Unexplained distinct-pid change > 0.1 % |
| PLAN-RK-17 | Lifecycle scope creep delays MS2–MS3 | 4 | 3 | PO | CCB scope control; add-ons placed at MS4–MS5 | Unplanned work > 10 % of capacity for 2 sprints |
| PLAN-RK-18 | Validation burden slows releases | 3 | 3 | QA lead | Generated IQ/OQ; CSA risk scoping; trace matrix in CI | Release blocked > 2 weeks |
| PLAN-RK-19 | Model licence or origin terms forbid use | 3 | 4 | Legal | Licence manifest per build; OD-07; ≥ 2 clean candidates per role | Negative review of a champion |
| PLAN-RK-20 | GPU capacity insufficient as studies grow | 3 | 3 | WS4 lead | Bench gate; night budget; cache; P-Scale; cadence reduction | Carry-over on > 3 nights a week |
| PLAN-RK-21 | Ransomware or hardware loss | 2 | 5 | IT, SEC | Immutable backup; off-box ledger anchor; quarterly DR drill | Backup or anchor alarm |
| PLAN-RK-22 | A competitor pre-empts the first site (Lind Asia on-prem, Epic eligibility AI, free SiteVault eSource) | 3 | 3 | PO | Ownership and independence terms (§19.6); published validation; NHI and lifecycle scope | Competitor contract at the target site |
| PLAN-RK-23 | A function is reclassified as SaMD or non-exempt CDS | 2 | 4 | QA, legal | Intended-use control (§2, §15); investigator decides; written analyses | Regulator or IRB query |
| PLAN-RK-24 | A silent false exclusion goes unnoticed | 2 | 5 | QA lead | Confidence-sequence certificate; chart-review line; S2 never excludes by default; demotion | Recall lower bound < 0.90 |
| PLAN-RK-25 | Second site or Japan profile needs rework | 3 | 3 | TL | Offline bundle; contracts; ja suites from MS1; JP Core spike at MS4 | Install > 30 days or ja gap > 5 |
| PLAN-RK-26 | A published claim proves wrong | 2 | 4 | PO | Claims policy (§19.5); pre-registration; no [Unverified] figures cited | Correction request or failed replication |

### 20.14 Rollback during rollout

Rollback units, triggers, procedures, verification and approval authority are normative in §18.5 for each change
class: bundle; model, prompt, lexicon or threshold; ruleset; snapshot; channel; cloud route; whole site. All are run
with `trialbox rollback --class <class> --to <ref>`. This table only sets who normally starts a rollback, and how fast,
during rollout. Where it differs from §18.5.0 (for example, the emergency authority of the system owner), §18.5.0
prevails.

| Phase | Typical class (§18) | Decides | Time to decide |
| --- | --- | --- | --- |
| R1–R2 | Bundle | Tech lead | Same day |
| R3 | Snapshot | Data steward with the WS1 lead | Automatic on gate failure; otherwise same day |
| R4–R5 | Bundle, model/prompt/lexicon/threshold, ruleset, channel | CCB (fast-track allowed); SC informed in R5 | ≤ 2 working days (R4); ≤ 1 (R5) |
| R6–R7 | Any; "stop" KRIs (§20.9) | Incident commander for "stop"; CCB otherwise; SC informed within 24 h | "Stop" ≤ 1 h; others ≤ 1 working day |
| R8 | Any | Per §18 | Per §18 |

A rollback during a soak restarts that wave's soak. A wave is rolled back as a whole. Other departments continue only
if the cause is shown not to affect them. Each rollback is an audited change, with a post-rollback review within 5
working days (§18).

## 21. Open decisions

Each decision has three things:
- a default, which the build assumes until the decision is taken;
- an owner;
- a deadline.

Decisions are recorded in `docs/governance/decisions/OD-xx.md`, and the SC minutes cross-reference them (PLAN-GOV-04).
The "v3" column gives the old number of a carried-over decision.

| OD | Decision | Options | Default / recommendation | Owner | Needed by | v3 |
| --- | --- | --- | --- | --- | --- | --- |
| OD-01 | First-site topology | A on-prem; B hospital tenant (in-country, customer-managed keys); C = A or B plus model egress for D0–D2 | A; B/C only where the hospital already runs its HIS or research platform in an in-country tenant | PO, IT, CISO | Week 2 | — |
| OD-02 | Cloud provider and region (B); cloud model endpoints (C) | Providers with a Taiwan region and customer-managed keys *(availability, confidential computing and zero-retention terms per provider: uncertain)* | No cloud at the first site; survey by MS1; decide before MS4 if a sponsor asks for D1 processing | PO, DPO, CISO | MS1 survey; MS4 decision | — |
| OD-03 | Default channel engine | `hermes`; `native` | `hermes` for staff channels after the MS0 exit (front-door `redteam` 0, config lint green), with `native` as hot standby. `native` is the default where the CISO has not accepted the Hermes supplier assessment. | TL, CISO; SC | MS0 gate | Reverses ADR-V3-07 |
| OD-04 | OMOP CDM 5.4 timing | (a) L2 writes OMOP from MS1 for VAL, endpoint at MS5; (b) all zones from MS0; (c) MS5 only | (a): DQD early in VAL; the production endpoint waits for a consumer | WS1 lead, DA | MS0 gate | ADR-V3-09 |
| OD-05 | IRB pathway and PDPA basis | Umbrella approval for pre-screening with per-study addenda, or per-study approval; consent at registration or a waiver with analysis; HSRA | Umbrella, submitted in week 2. Legal names the PDPA article relied on and the cross-border analysis for C. | IRB, legal, DPO | Week 2 / MS2 | OD-3 |
| OD-06 | Level B signing method | B1 passkey; B2 IdP re-authentication; B3 HCA PKI | B1 first; B2 with phishing-resistant MFA; B3 when middleware exists | PO, CISO, QA | MS1 | OD-5 |
| OD-07 | Model origin and licence policy | Site `public_agency` flag (no PRC-origin weights); licence review of Gemma, Llama-family, Qwen, Mistral, gpt-oss, TAIDE, Breeze; Japanese domestic models for MS6 | Bake-offs cover both families (D0). Production follows the site flag. Every role keeps ≥ 2 licence-clean candidates. | Legal, DPO, ML lead | Week 4 | OD-6 |
| OD-08 | Opt-out and consent default | `all_research_use`; `contact_only`; per-scope FHIR `Consent` with an NHI opt-out import | Per-scope `Consent` where recorded; otherwise `all_research_use` | IRB, legal | MS1 | OD-7 |
| OD-09 | Pricing | Appliance + yearly support; yearly subscription; alliance licence (none with per-patient fees, PLAN-COM-01) | Appliance + yearly support, with a published list price | PO | MS1 | OD-8 |
| OD-10 | Data source order | (a) De-identified research DB for MS1, then HIS views and HL7/CDC for MS2; (b) HIS views first; (c) FHIR server first | (a): it matches the IRB path, and replay needs the research DB | Data steward, IT | Week 1 | OD-1 |
| OD-11 | Hardware purchase | P-GB10; P-5090; P-Scale | A GB10-class dev unit in weeks 1–2; production after the MS0 bench and the bake-off shortlist; quotes needed *(volatile prices)* | IT, PO | Week 2; MS0 | OD-2 |
| OD-12 | Small-cell thresholds per disclosure profile (§12.2, §7) | sponsor `<11`/5 and internal `<5`/5; or stricter per IRB | sponsor `<11` with base-5 rounding; internal `<5`; the IRB may tighten either | IRB | MS1 | OD-4 |
| OD-13 | LINE use | None; nudges without PHI | Nudges without PHI, opt-in per user | CISO, research office | MS2 | — |
| OD-14 | Trace-store engine | Langfuse; Phoenix (both self-hosted) | DA decides after a one-week spike on redaction-at-write and retention | TL, SEC | Week 3 | — |
| OD-15 | Sponsor consent for D1 cloud processing (C) | None; per-protocol written consent | Off; consent template by MS4 if OD-02 enables C | Legal, research office | Before MS4 | — |

**Closed decisions.** Changing any of these needs SC approval.

| Decision | Status in v4 | Reference |
| --- | --- | --- |
| Vendor relationship | None: TrialBox is independent | C-1, PLAN-COM-08 |
| Cloud model path | **Reversed from v3.** Allowed for D0–D2 only, through `tb-gateway`. D3 and D4 never reach an external model. | C-2′, §7, §8 |
| Hermes | **Reversed from v3.** Hermes is the governed front door, with a native fallback. | C-10, §9 |
| Workflow engine | PostgreSQL durable steps and outbox, as in v3 | §4, §11 |
| Recall statistics | Anytime-valid confidence sequences | §6, §10, App. F |

---

## Appendix A — Lifecycle coverage matrix

Legend:
- ● covered; ◐ partial; ○ not in scope.
- **MS** is the milestone at which v4 coverage first reaches production.
- **Model time** says whether the stage spends LLM time.
- *New* marks a stage added from review §2(i) (R3-39).
- Module references are to §10.

| Stage | v1 | v3 | v4 | MS | Modules | Model time |
| --- | --- | --- | --- | --- | --- | --- |
| Data platform L0–L5 (*new as a platform*) | ◐ | ◐ | ● | MS0 | §5, FR-M0 | Mapping proposals only (schema metadata) |
| Site readiness, Atlas, DQ scorecard, lexicon | ◐ | ● | ● | MS1 | FR-M0, ML- | Mapping proposals only |
| Protocol intake, criterion library, Q&A | ● | ● | ● | MS1 | FR-M1 | Yes: match-then-draft, Q&A |
| Protocol optimisation (what-if, relaxation) | ◐ | ● | ● | MS4 | FR-M2 | No |
| Feasibility, questionnaire, feasibility pack | ● | ● | ● | MS1 | FR-M3, §12 | Sample only; questionnaire mapping |
| Recruitability model and forecast ledger (*new*) | ○ | ◐ | ● | MS1 / MS4 | FR-M3, FR-M6 | No |
| Site selection, site profile | ○ | ● | ● | MS4 | FR-M3 | No |
| Start-up: budget, coverage analysis, delegation, training; IRB e-submission package (*new*) | ○ | ● | ● | MS4 | FR-M7 | Drafting only |
| Pre-screening, clinic-day lists, recall certificate | ● | ● | ● | MS3 | FR-M4, SAFE- | Residue only |
| Patient → trials, tumour board | ○ | ● | ● | MS4 | FR-M5 | Residue only; registry retrieval |
| Screening-visit checklist pre-filled for the investigator (*new*) | ○ | ○ | ● | MS4 | FR-M4, FR-M7 | No (reuses evidence) |
| Consent tracking and re-consent (signing out of scope) | ○ | ● | ● | MS4 | FR-M6 | No |
| Enrolment tracking, accrual pack | ◐ | ● | ● | MS4 | FR-M6, §12 | No |
| Retention, visit adherence, participant reimbursement reminders (*new*) | ○ | ○ | ● | MS5 | FR-M6, FR-M7 | No |
| Visits, windows, deviations, CAPA | ○ | ● | ● | MS5 | FR-M7 | No |
| Safety clocks, hospital-flagged events, DSMB listings (*DSMB new*) | ○ | ● | ● | MS5 | FR-M7 | No |
| IP accountability prompts; lab-kit and sample logistics (*new*) | ○ | ○ | ● | MS5 | FR-M7 | No |
| RBQM KRIs per study (*new*) | ○ | ○ | ● | MS5 | FR-M7, §12 | No |
| Monitoring support; TMF/ISF completeness vs E6(R3) essential records (*completeness new*) | ○ | ● | ● | MS5 | FR-M7 | No |
| eSource packets, eCRF pre-fill, SDV, query drafts; sponsor-query SLA (*SLA new*) | ○ | ● | ● | MS5 | FR-M8, §12 | Extraction (D3, on-prem only) |
| Site performance pack (*new*) | ○ | ○ | ● | MS4 | FR-M9, §12 | No |
| Close-out, registry, archive, IRB final report, financial reconciliation (*reconciliation new*) | ○ | ● | ● | MS5 | FR-M9 | Drafting only |
| IIT protocol skeleton, ICH M11 template (*new*) | ○ | ○ | ◐ | MS5 | FR-M7, FR-M9 | Drafting under G1-like review (D1) |
| NHI reimbursement, TWPAS, NHI signals | ● | ● | ● | MS1 / MS4 | FR-M10 | As v1 |
| Networked and federated research, language packs | ● | ● | ● | MS5 | FR-M11 | No |
| Staff concierge, aggregate analyst, admin copilot (Hermes) (*new*) | ○ | ○ | ● | MS0 / MS3 | §9, FR-AG | Yes (D1, aggregates; no PHI) |
| Randomisation, IP dispensing, unblinding, eConsent signing, patient contact | ○ | ○ | ○ | — | §2 non-goals | — |

## Appendix B — Evidence base (selected)

DOIs come from `docs/LANDSCAPE.md`, where they were verified against PubMed or Crossref, and from
`docs/research/2026-10_literature_competitors.md`. The full list is in `docs/LANDSCAPE.md`.

| Design choice | Evidence |
| --- | --- |
| Criterion-level judging with verified quotes | Jin Q et al., TrialGPT, *Nat Commun* 2024, doi:10.1038/s41467-024-53081-z; Wornow M et al., *NEJM AI* 2025, doi:10.1056/AIcs2400360 (coherent rationales accompany wrong answers); arXiv 2604.17114 (LLM judges unreliable as verifiers) [preprint] |
| The real-EHR bar | UT Southwestern, medRxiv doi:10.64898/2026.03.20.26348890 [preprint] |
| Randomised evidence for AI pre-screening | Unlu O et al., *JAMA* 2025;333(12):1084–7, doi:10.1001/jama.2024.28047; RECTIFIER, *NEJM AI* 2024, doi:10.1056/AIoa2400181 |
| Local and open models; manual screening misses most | Syed M et al., *JAMIA* 2026, doi:10.1093/jamia/ocag006; PRISM, *npj Digit Med* 2024, doi:10.1038/s41746-024-01274-7; TrialMatchAI, *Nat Commun* 2026, doi:10.1038/s41467-026-70509-w |
| Competitor prospective study | Loaiza-Bonilla A et al. (Massive Bio), *ESMO Real World Data Digit Oncol* 2026, doi:10.1016/j.esmorw.2026.100706 |
| The LLM must not write SQL; normalisation is the weak step | Lee KH et al., *JMIR Med Inform* 2025, doi:10.2196/71252; C2Q 3.0, *J Biomed Inform* 2024, doi:10.1016/j.jbi.2024.104649; EC2Seq2Sql, *PLoS One* 2026, doi:10.1371/journal.pone.0341827 |
| Library seed, ATLAS limits, organ-function panel | Chia, *Sci Data* 2020, doi:10.1038/s41597-020-00620-0; Blasini R et al., *Sci Rep* 2023, doi:10.1038/s41598-023-49560-w; ELaPro, *BMC Med Res Methodol* 2022, doi:10.1186/s12874-022-01611-y |
| Recall certification | Cormack & Grossman, SIGIR 2016, doi:10.1145/2911451.2911510; Waudby-Smith & Ramdas, *JRSS-B* 2024 (betting CS, implemented in `recall.py`); Howard SR et al., *Ann Stat* 2021 *(DOIs of the last two not in the research files; verify before citing)* |
| Thresholds and abstention | Learn-then-Test, arXiv 2110.01052; conformal risk control, arXiv 2208.02814; token probabilities vs verbalised confidence, *JMIR*, doi:10.2196/64348 |
| Constrained decoding | *Healthcare* 2026, doi:10.3390/healthcare14142150 |
| Code-mixed Taiwanese notes | *J Imaging Inform Med* 2026, doi:10.1007/s10278-026-02009-8; Lee YQ et al., *JMIR* 2024, doi:10.2196/48443; CMUH, doi:10.2196/88567 |
| Small models on CJK | *Sci Rep* 2026, doi:10.1038/s41598-026-58622-8 (8B weak on Japanese SOAP); *JMIR Form Res* 2026 e84974 (Gemma-2-27B 0.906); DRAGON, arXiv 2507.20859 (do not translate first) [preprint] |
| Temporal errors; long records | CliniCIRCA, arXiv 2609.19585; arXiv 2604.05190 (criterion-conditioned retrieval) [preprints] |
| Bias; injection through the chart | Soffer S et al., *JAMIA* 2026, doi:10.1093/jamia/ocag058; *Ann Biomed Eng* 2026 (PMID 42745101) |
| EHR → EDC | AMIA Jt Summits 2026 (PMID 42317828); REDCap CDIS, *J Biomed Inform* 2026, doi:10.1016/j.jbi.2026.105060; *ESMO RWD* 2025, doi:10.1016/j.esmorw.2025.100112 |
| Forecasting | Benjamin DM et al., *PLoS One* 2022, doi:10.1371/journal.pone.0262862; Bieganek C et al., *PLoS One* 2022, doi:10.1371/journal.pone.0263193 |
| Post-list leakage; relaxation; alert fatigue | Verhagen CT et al., *Surgery* 2026, doi:10.1016/j.surg.2025.109915; Trial Pathfinder, *Nature* 2021, doi:10.1038/s41586-021-03430-5; Embi & Leonard, *JAMIA* 2012, doi:10.1136/amiajnl-2011-000743 |
| Agents need deterministic tools | *npj Digit Med* 2026, doi:10.1038/s41746-026-02443-6; MedAgentBench, *NEJM AI* 2025, doi:10.1056/AIdbp2500144 |
| Taiwanese research databases | CGRD, *Biomed J* 2017, doi:10.1016/j.bj.2017.08.002; TMUCRD, *BMJ Health Care Inform* 2024, doi:10.1136/bmjhci-2023-100890 |
| Reporting | DECIDE-AI (*Nat Med* 2022); TRIPOD-LLM (*Nat Med* 2025); CONSORT-AI (*Nat Med* 2020) |

## Appendix C — Compliance trace summary

§15 is normative. It holds the trace matrix from each regulatory source to its requirements and verification, the
intended-use analyses and the AI credibility files. This appendix only points to where each family is traced and to its
§20.6 evidence.

| Family | Traced in | Evidence (§20.6) |
| --- | --- | --- |
| 21 CFR Part 11; EMA computerised-systems guideline; Taiwan Electronic Signatures Act | §15, §3, §14 | OQ (FR-SIG negatives); validation summary |
| ICH E6(R3) with Annex 1; TFDA GCP | §15, §10, §11 | PQ; SOPs; audit-trail review |
| GAMP 5 2nd ed.; FDA CSA | §15, §16, §20.6 | VP; risk assessment; IQ/OQ/PQ; trace matrix |
| PDPA; HSRA; NHI data rules; MOHW EMR regulation; ISO 25237 | §7, §15 | DPIA; de-identification certificates; egress tests |
| AI Basic Act; ISO/IEC 42001; NIST AI RMF; FDA/EMA AI guidance | §8, §15 | AI credibility files; model cards; bake-off and shadow reports |
| ISO/IEC 27001; OWASP ASVS 5.0 and LLM Top 10 2025; SLSA; CycloneDX | §14, §15 | Threat model; pen test; SBOM/ML-BOM; `redteam` |
| FHIR R4 4.0.1, TW Core, JP Core; OMOP 5.4; CDISC CDASH, ODM v2, Dataset-JSON, USDM; ICH M11 | §5, §6, §12, §15 | Validator runs; DQD; export conformance tests |

## Appendix D — Grammar reduced to the lines Hermes proposes

Staff write in plain language. Hermes, or `classify_intent` in the native engine, turns the text into **one canonical
line**. That line is a **proposal**: the deterministic intake executes it only after the sender replies `OK`, or when
the sender types the line directly (§3, §9). Free text never acts by itself. The v1 ABNF (`SPEC.md` §5) and the v3
additions stay valid as the typed fallback.

**Lines a proposal may produce** (grammar as in v3, except `row`):

```
command   =/ "FEAS" SP ("NEW" / study) *(SP param)          ; param = key "=" value (scope, lookback, deadline)
command   =/ "QFILL" SP study                                ; fill the attached questionnaire
command   =/ "ASK" SP study SP quoted-text                   ; protocol Q&A (no patient data)
command   =/ "WHATIF" SP study SP change *(";" change)       ; internal only
change    = ("drop" SP criterion-id) / ("set" SP criterion-id SP param "=" value)
command   =/ "SCREEN" SP study *(SP param)                   ; scope=practitioners:…, cadence=weekly|nightly
command   =/ "STUDY" SP study SP status                      ; recruiting | follow_up | closed | declined
command   =/ "CONFIRM" SP row *(SP row)                      ; G3, PI/Sub-I
command   =/ "REJECT" SP row SP reason-code [SP free-text]
command   =/ "DEFER" SP row [SP date]
command   =/ "STATE" SP row SP state [SP date]               ; G4
state     = "contacted" / "consented" / "screened" / "randomized" / "declined" / "screen_failed" / "withdrawn" / "not_contactable"
command   =/ "ANSWERS" SP 1*(DIGIT ("Y" / "N" / "?") SP)     ; five-minute review
command   =/ "MONITOR" SP study SP date                      ; monitoring-visit pack
command   =/ "ATLAS" [SP domain] / "STATUS" [SP study] / "HELP" / "DIGEST" SP ("daily" / "weekly" / "off")
command   =/ "OK"                                            ; confirms the proposal in the replied-to message
row       = packet-id "#" 1*3DIGIT                           ; row handle printed in the packet (v4)
```

A proposal names a candidate by the packet's row handle, never by pid or MRN. The orchestrator resolves the handle
inside the perimeter, and the front door never sees the pid (§9). A typed line may still carry a pid, as in v3.

**Lines never proposed.** These are typed by the person and parsed deterministically.

| Line | Reason |
| --- | --- |
| `APPROVE <gate-id> sha=… [otp=…]`, `REJECTGATE …` | An approval is a human act. Hermes never drafts one; it may only relay a typed reply verbatim. |
| `MATCH <mrn> …` | Carries identifiers (D4); accepted only from delegated clinicians |
| `FULLREVIEW <pid>` | Full-record PHI access, ≤ 20 per request |
| `SAE <pid> <date> …` | Starts regulated safety clocks; must be the investigator's own words |
| `QUERY <study> <pid> …` | Patient-level EDC content (D3) |

Level B signatures are never given by email; they use the signing page (§3). `REJECT` reason codes are unchanged:

| Code | Reason |
| --- | --- |
| R01 | Does not meet inclusion on chart review |
| R02 | Meets exclusion |
| R03 | Clinically inappropriate |
| R04 | Patient preference known |
| R05 | Enrolled elsewhere |
| R06 | Data outdated |
| R07 | Other (free text required) |

## Appendix E — Multilingual seed tables (ML-3, ML-6)

These tables are carried from SPEC_v3 Appendix E. Sites extend them through G0, and alliance language packs extend them
across sites (ML-12).

**Assertion cues.** A cue's scope is its clause, up to the next boundary (`，。；;,.` or a conjunction such as `但`,
`but` or `however`).

| Class | zh-TW | en | ja |
| --- | --- | --- | --- |
| negated | 無、沒有、否認、未見、未、非、排除、(-)、陰性 | no, not, denies, denied, without, negative, absent, r/o (ruled out when followed by "—" or "neg") | なし、無し、否定、認めない、陰性 |
| uncertain | 疑似、懷疑、可能、待排除、r/o (rule out, pending) | possible, probable, suspected, r/o, query, ? | 疑い、可能性 |
| historical | 曾、過去、病史、之前、s/p、術後 | history of, h/o, s/p, previous, prior, status post | 既往、以前、術後 |
| family | 家族史、父親、母親、兄弟、姊妹、家人 | family history, FHx, mother, father, sibling | 家族歴、父、母 |
| hypothetical | 若、如果、如有、必要時、prn | if, should, in case, prn | もし、場合 |

**Code-mixed seeds** (`lang: mixed`, from the `notes_mixed` style of `eval/criterion_ml`):

| Kind | Seeds |
| --- | --- |
| Section headers inside Chinese narrative | `PE:`, `Lab:`, `Imp:`, `Dx:`, `Hx:` |
| Abbreviations | `s/p`, `r/o`, `h/o`, `c/w`, `f/u`, `w/u` |
| Negation | `denied` / `否認` followed by an English term |

**Date forms:**

| Form | Examples | Rule |
| --- | --- | --- |
| ROC year | `民國113年3月5日`, `113/03/05`, `113.3.5`, `1130305` (in date columns) | Year + 1911 |
| Japanese era | `令和6年3月5日`, `R6.3.5`, `平成31年` | Era table |
| Western | ISO, `2024/3/5`, `5/3/2024` | Ambiguous day/month resolved by column or site convention, otherwise flagged |
| Relative | `三個月前`, `2 weeks ago`, `3日前` | Resolved against the note date and marked `relative` |

**Number forms:**
- full-width digits;
- Chinese numerals in counts and durations (`一`…`十`, `兩`, `半年`);
- unseparated value–unit pairs (`Cr1.2`, `EF35%`, `Hb9.8`), read through the lexicon's lab-alias table;
- ranges (`3-5`, `3~5`, `3至5`).

## Appendix F — Statistics for recall evidence

### F.1 Single-look sample sizes (one-sided 95 %, Clopper–Pearson; from SPEC_v3 Appendix F)

These sizes are valid for **one pre-planned look**. v4 uses them for planning, and for the known-positive line at a
certificate date. They are not valid for monthly re-issue on an accumulating ledger (R3-03).

| Elusion below p | 0 found | 1 found | 2 found | 3 found |
| --- | --- | --- | --- | --- |
| 2 % | 149 | 236 | 313 | 386 |
| 1 % | 299 | 473 | 628 | 773 |
| 0.5 % | 598 | 947 | 1,258 | 1,549 |

| Recall ≥ (known positives needed) | 0 missed | 1 missed | 2 missed |
| --- | --- | --- | --- |
| 0.90 | 29 | 46 | 61 |
| 0.95 | 59 | 93 | 124 |
| 0.98 | 149 | 236 | 313 |

### F.2 Confidence-sequence parameters (as implemented in `libs/tb_common/recall.py`)

| Parameter | Value |
| --- | --- |
| Construction | Betting upper confidence sequence for a bounded mean (Waudby-Smith & Ramdas, JRSS-B 2024). Capital K_t(m) = ∏ (1 + λ_i (m − X_i)), where X_i = 1 marks an excluded patient who was in fact a candidate. |
| Validity | Ville's inequality: P(∃t: K_t(true rate) ≥ 1/α) ≤ α. The bound at t is the largest m whose capital has never reached 1/α. It is valid at every look, so monthly re-issue and demotion are allowed. |
| Bet | Predictable plug-in (WSR eq. 26): λ = √(2 log(1/α) / (σ̂² t log(t+1))), with σ̂² = (0.25 + Σ(x − x̄)²)/t, truncated so that 1 + λ(m − x) ≥ 0.5 |
| Grid | 2,001 rates on [0, 1] (resolution 0.0005); running intersection, so the bound never rises |
| α | 0.05 per certificate. Bonferroni α/K over K strata. |
| State | Log-capital and rejection flag per grid point, n, Σx and the squared deviation. Persisted in the ledger (S1-12). |
| Pooling and weights | Per canonical criterion across studies (SAFE-2). The module accepts 0/1 observations only. Horvitz–Thompson-weighted observations (AI-15) need the same construction on weights normalised to [0, 1]; this is a §10 SAFE item and is not yet implemented. |
| Known-positive lines | Two labelled lines, historical enrollees (biased) and blinded chart review, both by Clopper–Pearson at the certificate date. An anytime-valid version of the cumulative chart-review line is a §10 item. |

**Simulation (brief).** Over 12 monthly looks, repeated Clopper–Pearson at fixed α missed the true elusion rate in
**9.7 %** of ledgers; the confidence sequence missed it in **0.3 %**. The nominal rate is 5 %. `recall_cert` reruns
this simulation in CI and requires coverage ≥ 95 % over the whole sequence.

### F.3 The cost of anytime validity

These bounds were computed with `recall.py` at α = 0.05, for one stratum. A sequence's bound depends on the order of
the observations:
- In the first table, the positives are spread evenly.
- In the second table, they fall at positions 25 and 50.

| n | 0 found: CS / CP | 1 found: CS / CP | 2 found: CS / CP |
| --- | --- | --- | --- |
| 150 | 0.0385 / 0.0198 | 0.0475 / 0.0312 | 0.0565 / 0.0414 |
| 300 | 0.0195 / 0.0099 | 0.0240 / 0.0157 | 0.0285 / 0.0208 |
| 600 | 0.0095 / 0.0050 | 0.0120 / 0.0079 | 0.0140 / 0.0105 |
| 1,000 | 0.0055 / 0.0030 | 0.0070 / 0.0047 | 0.0085 / 0.0063 |

| CS certifies elusion below p at n = | 0 found | 1 found | 2 found | CP single look, 0 found |
| --- | --- | --- | --- | --- |
| 2 % | 296 | 365 | 434 | 149 |
| 1 % | 595 | 734 | 872 | 299 |
| 0.5 % | 1,194 | 1,472 | 1,749 | 598 |

With K = 4 strata, a 1 % claim at 0 found needs n = 870 with the sequence, against about 438 with one CP look. When
nothing is found, anytime validity costs about twice the samples. That is why samples are pooled and importance-weighted,
and why annotation load is a tracked risk (PLAN-RK-08).

**Elusion is not recall.** A clean sample of 299 drawn from 20,000 excluded patients still allows up to 199 misses.
Every certificate therefore carries the known-positive lines, and structured stages exclude only on affirmative
evidence (CAS-11).

## Appendix G — Data-class boundary table

This appendix is copied from the brief and review §2(c); §7 is normative. D3 and D4 never reach any external model in
any topology.

| Class | Content |
| --- | --- |
| D0 public | Registry records, public benchmarks, open data |
| D1 confidential, no PHI | Protocol text, sponsor questionnaires, site profile, lexicon, prompts |
| D2 de-identified patient-level | Expert-determined or Safe-Harbor sets, synthetic twins, evaluation sets |
| D3 pseudonymised patient-level | Lake, evidence, judgements, candidate lists |
| D4 identified | Vault, MRNs, names, attachments to PIs |

| Topology | Definition |
| --- | --- |
| A | On-prem appliance (default) |
| B | The hospital's own in-country cloud tenant with customer-managed keys, private networking and no supplier access |
| C | A or B plus a model egress policy for D0–D2 only, through `tb-gateway` (per-call class check, redaction, logging, budget) |

| Class | On-prem | Hospital tenant (in-country, hospital keys) | Vendor cloud LLM (zero-retention, DPA) | Public cloud (OpenRouter, bake-offs) |
| --- | --- | --- | --- | --- |
| D0 | ✓ | ✓ | ✓ | ✓ |
| D1 | ✓ | ✓ | Only with the sponsor's written consent per protocol (default off; OD-15) | ✗ |
| D2 | ✓ | ✓ (TRE controls) | Only with documented re-identification risk ≤ threshold, the PDPA cross-border analysis, and IRB/DPO sign-off (default off) | ✗ |
| D3 | ✓ | ✓ only if the tenant is attested as the hospital's own perimeter | ✗ | ✗ |
| D4 | ✓ | ✗ unless the HIS itself lives there | ✗ | ✗ |

Class ceilings per environment (§20.5):

| Environment | Classes allowed |
| --- | --- |
| DEV, TEST | D0 and synthetic data |
| VAL | D0 and D2 |
| STAGE, PROD | Per topology |
| DR | As PROD, during a drill only |

## Appendix H — Open-data licence table

Licences are as stated by each source at retrieval. Entries marked *(uncertain)* need legal confirmation before
redistribution. "Bundle" means the data may ship in the offline bundle.

| Dataset | Licence / access | Use and suite | Bundle |
| --- | --- | --- | --- |
| NCBI TrialGPT-Criterion-Annotations: 1,015 pairs, 53 notes (`eval/criterion_ml/`) | U.S. Government Work, public domain (`LICENSE.NCBI`); cite Jin et al. 2024 | Judge evaluation, evidence-span gold, calibration prior: `judge_public` | Yes |
| zh-TW, ja and mixed renderings of the 53 notes | Derivative of public-domain text; TrialBox licence; **not clinician-verified** | Parity checks, not ground truth: `judge_ml` synthetic strata | Yes |
| NCBI TrialGPT cohorts (SIGIR 2016, TREC CT 2021/2022) | Public research collections; TrialGPT code licence unchecked *(uncertain)* | Retrieval and ranking: `match_registry` | Data, after confirming TREC terms |
| MIMIC-IV Demo on FHIR v2.1.0; MIMIC-IV demo | ODbL v1.0; fetched and SHA-verified by `tools/fetch_open_data.py` | FHIR and CSV e2e, DQ sanity: `ingest_fhir_demo` | No (fetched) |
| Synthea | Generator Apache-2.0; data synthetic | Scale, HL7 v2 synthesis, MPI-merge, late arrival: `bench`, `pipeline_scale` | Config yes |
| Chia corpus | Open, attribution *(exact licence uncertain)* | Library seed, extraction gold: `criteria_extract_public` | If confirmed |
| ClinicalTrials.gov (API v2) | NLM terms *(confirm for redistribution)* | Registry sync, seed, e2e fixtures | Fixtures yes |
| MOHW Taiwan trial disclosures | Public *(terms uncertain)* | Taiwanese criteria for the library | No |
| CHIP-CTC, CHIP-STS, CBLUE | Research licences *(commercial use uncertain)* | zh classification after OpenCC conversion, labelled synthetic-TW: `criteria_zh` | No |
| n2c2 2018 Track 1; TREC CT 2023 | DUA *(company eligibility uncertain)*; track terms *(uncertain)* | Optional baselines | No |
| ICD-10-CM TW 2014/2023 with NHIA map; NHI codes | Taiwan open government data licence *(version to confirm)* | Terminology service: `code_versions` | Yes |
| LOINC and LOINC-TW map | LOINC licence (free, registration) | Lab normalisation | Under LOINC terms |
| SNOMED CT | Affiliate licence *(Taiwan membership uncertain)* | Only where the site holds a licence | No |
| MANBYO, JMED and other Japanese dictionaries | Per dictionary *(uncertain)* | ja lexicon (MS6) | Per licence |
| MedCPT; TrialMatchAI (Zenodo 15045515) | Public releases *(licences uncertain)* | Retrieval ablation; optional baseline | Per OD-07 |

## Appendix I — Disposition of review rounds 1–3

### I.1 Rounds 1 and 2 (from SPEC_v3 Appendix G)

| Finding | v4 status |
| --- | --- |
| F-01 end-user console (v3: C-5, inbox only) | Superseded by C-5′ minimal UI (§3) |
| F-04 router model and gateway removed | Partly superseded: batch first is kept (C-4); a class-policy gateway returns (§8) |
| F-05 cloud path, Hermes, Teams/LINE removed | **Reversed by the owner**: C-2′, C-10; Teams cards and LINE nudges without PHI |
| F-16 "no LiteLLM"; F-19 "deliberately not used" list | Superseded by `tb-gateway`, registry and channel engines (§4, §8, §9) |
| F-20 timeline (R0–R1b) | Superseded by MS0–MS6 (§20.7) |
| F-09 silent false negatives; N-05 recall statistics | Carried; statistics replaced by confidence sequences (R3-03) |
| N-02 cloud path still in code (v3 S1-0) | Superseded: the cloud branch becomes gateway routes (S1-06) |
| F-14 thin lifecycle | Extended (R3-39, App. A) |
| F-02, F-03, F-06–F-08, F-10–F-13, F-15, F-17, F-18; N-01, N-03, N-04, N-06–N-22 | Carried as in v3, in the sections that now hold them (§3–§16) |
| I-A…I-E (recall ledger, importance sampling, shadow pass, language packs, QBCB depth) | Innovations 1, 13, 14 and 16 (§19.2) |

### I.2 Round 3 (R3-01…R3-44)

| ID | Sev | Finding | v4 resolution | Sections |
| --- | --- | --- | --- | --- |
| R3-01 | B | IR too narrow; no criterion library | IR v3; library with match-then-draft; normalisation targets per domain | §6, §10.1, §16 |
| R3-02 | B | S2 zero-hit silently excludes | S2 never excludes by default; S2b; zero-hit only where lexicon recall ≥ 0.98 | §4, §10, §16 |
| R3-03 | B | Certificate invalid under optional stopping | Confidence sequences (implemented); two known-positive lines; 12-look suite | §6, §10, App. F; S1-12 |
| R3-04 | M | J/V agreement is not correctness | Agreement with library and gold | §10.1, §16 |
| R3-05 | M | Cache invalidated by any note | Sentence-set key | §4, §10.4 |
| R3-06 | M | `potential` mixes two causes | `potential:data_gap` and `potential:uncertain` | §6, §10.4 |
| R3-07 | M | M5 thin | Two-direction engine reusing the TrialGPT port | §10.5, §16 |
| R3-08 | m | Single-span quotes | ≤ 3 verified spans | §6 |
| R3-09 | B | No stages, controls or lineage | L0–L5; OpenLineage and Provenance | §5; S1-02…04 |
| R3-10 | B | No reconciliation | Control totals; publish gate | §5; S1-03 |
| R3-11 | M | Merges, erasure, late data | MPI merge table; tombstones; dirty-set and late-arrival re-runs | §5, §7 |
| R3-12 | M | No HL7 v2 or CDC | MLLP (ADT/SIU/ORU/MDM); CDC | §5, §13 |
| R3-13 | M | OMOP optional | OMOP CDM 5.4 core; timing OD-04 | §4–§6, §21 |
| R3-14 | M | CGRD treated as a generic source | De-identified TRE zone; never used for lists | §5, §7 |
| R3-15 | m | No terminology service | `$validate-code`, `$translate` | §5 |
| R3-16 | B | No data classes | D0–D4; A/B/C | §0, §7, App. G |
| R3-17 | M | De-identification undefined | Standard, risk method, Five Safes | §7 |
| R3-18 | M | PHI guard thin | Larger dictionaries and patterns; recall gate ≥ 0.98 | §7, §8, §16; S1-08 |
| R3-19 | m | Opt-out is a flag | FHIR `Consent` scopes | §6, §7; OD-08 |
| R3-20 | B | No LLM platform | Gateway, registry, routing, budgets | §8; S1-06/07 |
| R3-21 | M | Unpoliced cloud branch | Gateway routes with class checks and cost | §8; S1-06 |
| R3-22 | M | Reproducibility of cache entries | Recorded outputs for steps and cache | §8, §13 |
| R3-23 | M | No runtime guardrails | Gateway classifiers; citation verifier | §8, §14 |
| R3-24 | m | No trace store | Self-hosted redacted store | §8, §18; OD-14 |
| R3-25 | B | No channel abstraction | `channels.engine: hermes \| native` | §4, §9; S1-10/11 |
| R3-26 | M | Hermes would conflict with approvals and memory | Subordinate: MCP-only tools, no approvals, memory off | §3, §9, §14 |
| R3-27 | M | Grammar burden | Plain language; reduced proposed lines | §3, App. D |
| R3-28 | M | Teams/LINE carry nothing | Cards and nudges without PHI | §3, §9; OD-13 |
| R3-29 | M | Read-only console | Admin control plane | §3, §18 |
| R3-30 | m | Accessibility | WCAG 2.2 AA; mobile email | §3, §13 |
| R3-31 | B | No control allocation or threat model | Per-component allocation; STRIDE, OWASP LLM, ATLAS | §14 |
| R3-32 | M | Identity | IdP with phishing-resistant MFA; mTLS | §14 |
| R3-33 | M | Keys | Hierarchy, KMS/HSM or sealed vault, rotation, dual control | §14 |
| R3-34 | M | Backups mutable | Immutable copy; off-box anchor | §14, §18 |
| R3-35 | m | SIEM, VDP, patches, DLP | All specified | §14, §18 |
| R3-36 | M | No report standard | Four packs | §12 |
| R3-37 | M | No conduct deliverables | Accrual and site-performance packs | §12, §10 |
| R3-38 | m | "JSON" only | FHIR, USDM, Dataset-JSON, ODM v2 | §6, §12 |
| R3-39 | M | Thin lifecycle | §2(i) additions | §2, §10, App. A |
| R3-40 | B | No open-data strategy | Public suites in CI | §16, App. H; S1-13 |
| R3-41 | M | Cold-start calibration | Public prior from the 1,015 annotations | §8, §10, §16 |
| R3-42 | M | No bake-off | `tools/bakeoff.py`, D0 only; results pending the key | §8, §16; S1-14 |
| R3-43 | B | No rollback, milestones, environments or waves | §18 rollback; MS0–MS6; environments; waves | §18, §20 |
| R3-44 | M | Optimistic timeline | Re-estimated for 6–8 people, with p80 dates | §20.1, §20.7 |

Carried-over defects named in round 3:

| Defect | Resolution |
| --- | --- |
| Certificate example mixes the recall claim with a biased population | Two labelled lines, computed by code (§6) |
| NFR-5 does not fit the ingest window | Per-stream ingestion SLOs (§13) |
| CAS-10 numbered after CAS-11 | Renumbered (§4) |

## Appendix J — Glossary (zh-TW / en)

Preferred terms for generated text and guides. A site may override any of them in its lexicon glossary (G0). Japanese
terms are added at MS6.

| English | zh-TW | English | zh-TW |
| --- | --- | --- | --- |
| Abstention | 保留判斷 | Key risk indicator (KRI) | 關鍵風險指標 |
| Accrual pack | 收案進度報告 | Line of therapy | 治療線別 |
| Admin control plane | 管理控制台 | Lineage | 資料血緣 |
| Audit trail | 稽核軌跡 | Master patient index | 病人主索引 |
| Change-control board | 變更管制委員會 | National Health Insurance | 全民健康保險（健保） |
| Clinical research coordinator | 研究護理師 / 臨床研究協調員 | Organ-function macro | 器官功能條件組 |
| Clinic-day list | 門診日候選名單 | Pre-screening | 預篩選 |
| Code-mixed text | 中英夾雜文字 | Principal investigator | 試驗主持人 |
| Confidence sequence | 隨時有效信賴序列 | Prior authorisation | 事前審查 |
| Criterion library | 收案條件庫 | Pseudonymisation | 假名化 |
| Data class | 資料等級 | Reconciliation | 資料核對 |
| Data contract | 資料契約 | Recall certificate | 召回率證明 |
| Data steward | 資料管理負責人 | ROC calendar | 民國紀年 |
| De-identification | 去識別化 | Rollback | 回復 |
| Delegation log | 授權分工紀錄 | Screen failure | 篩選失敗 |
| Design authority | 設計權責小組 | Serious adverse event | 嚴重不良事件 |
| Electronic signature | 電子簽章 | Shadow mode | 影子模式 |
| Eligibility criteria (inclusion / exclusion) | 收案條件（納入 / 排除條件） | Silent prospective | 靜默前瞻運行 |
| Elusion rate | 遺漏率 | Soak period | 穩定觀察期 |
| Enrolment | 收案 | Source data verification | 原始資料查核 |
| Evidence quote | 證據引文 | Sponsor | 試驗委託者 |
| Feasibility | 可行性評估 | Steering committee | 指導委員會 |
| Go/no-go | 執行與否決策 | Sub-investigator | 協同主持人 |
| Honest broker | 誠實仲介 | Trusted research environment | 可信研究環境 |
| Hypercare | 上線加強支援期 | Tumour board | 腫瘤聯合討論會 |
| Informed consent | 受試者同意 | Institutional review board | 人體試驗委員會 |
| Investigator site file | 試驗主持人檔案 | Investigator-initiated trial | 研究者發起試驗 |
