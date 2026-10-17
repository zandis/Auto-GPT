# SPEC — TrialBox v3: The Inbox-Native Trial Agent

Version 3.0-rc1 · Oct 17, 2026 · @Changfu · Supersedes `SPEC_v2.md` (2.0-draft, same day), which failed an adversarial
review (`docs/reviews/SPEC_v2_review.md`). This version incorporates a second review round (`docs/reviews/SPEC_v3_review.md`,
"approvable with fixes"; all fixes applied, Appendix G). `SPEC.md` (v1.0, Oct 4, 2026) stays the build contract for the code that exists
today. This document specifies what v3 adds and changes.

TrialBox is a hospital-owned appliance. It reads the hospital's EMR, takes a trial's inclusion and exclusion criteria (I&E) by
email, and returns two things:
- the feasibility evidence a sponsor asks for;
- a ranked, evidence-backed list of candidate patients for each investigator.

After that, it helps the study team through every later step of the trial. It is built for six constraints:
1. It runs on premises, on one box costing about US$5k.
2. Deterministic rules filter first. A language model reads only the notes that rules cannot decide.
3. It runs in batch; nothing needs to be interactive.
4. End users never get a user interface. Email is the user interface, and only administrators have a console.
5. Notes may be in Traditional Chinese, English, Japanese or a mix of these.
6. It covers the whole site-side trial lifecycle.

Like v1, the specification is written so that one engineer or one coding agent can build the system without further design
decisions. Every requirement has an identifier, a verification method and a release. §15.2 lists the first sprint as tasks
against the existing repository, in dependency order.

**How to read it**

| You are | Read |
| --- | --- |
| Hospital leadership, research office | §1, §2, §3, §14 (how TrialBox beats the field) |
| Investigator, coordinator | §3 (what arrives in your inbox and how to answer it) |
| Engineer or coding agent | everything; build from §4–§13 and the sprint in §15.2 |
| QA, IRB, information security | §2.4, §3.5 (approvals and signatures), §10, §11, Appendix C |
| IT, procurement | §4.7 (hardware profiles and the benchmark gate), §13 |

**Conformance language.** MUST, MUST NOT, SHOULD and MAY are used as defined in RFC 2119 and RFC 8174.

Requirement identifiers:
- `FR-<module>-<n>`: functional
- `NFR-<n>`: non-functional
- `SEC-<n>`: security
- `PRIV-<n>`: privacy
- `CMP-<n>`: compliance
- `AI-<n>`: AI behaviour
- `CAS-<n>`: the filter-first cascade
- `SAFE-<n>`: false-negative safety
- `ML-<n>`: multilingual

Each requirement states:
- its **verification**: `T` test, `I` inspection, `A` analysis, `D` demonstration. A `D` or `I` is allowed only where a test
  is impossible, and the reason is given.
- its **release**: R0, R1a, R1b, R2, R3 or R4 (§15).

Numbers marked *(est.)* are engineering estimates. They MUST be replaced by measured values from `trialbox bench` (§4.7.3)
before they are quoted to a hospital.

**Companion documents:**
- `docs/LANDSCAPE.md`: competitive landscape and literature.
- `docs/reviews/SPEC_v2_review.md`: the adversarial review. Appendix G of this document maps each of its findings to the
  section that resolves it.
- `SPEC.md`: the v1 contract.
- `docs/DECISIONS.md`: the v1 decision log, continued here as ADRs.

---

## 0. Binding product constraints

These constraints come from the product owner. Every other section must satisfy them. A requirement that conflicts with one
of them is a defect in this document.

| ID | Constraint | Where it is implemented |
| --- | --- | --- |
| C-1 | **Independent product.** TrialBox has no integration, data exchange, revenue share, white-label or complementary-scope arrangement with Lind (lind.care), Lind Asia/PREMIA, Inato, or any other screening or recruitment vendor. Those vendors are competitors. If one of them is installed at the same hospital, that is the hospital's procurement matter; TrialBox does not interoperate with it. | §2.1, §14, OD list (§16) |
| C-2 | **On premises.** Patient data, protocols and model inference stay inside the hospital. There is no cloud LLM path, no vendor remote access, and no telemetry. The v1 optional cloud route for criteria text is removed in sprint task S1-0. | §4.1, §4.3, SEC-1, PRIV-4, S1-0 |
| C-3 | **Filter first.** Deterministic rules on structured EMR data reduce the population. A language model sees only the residue, which is criteria that structured data cannot decide, read from notes. The cascade is measured, budgeted, and has a bound on how many eligible patients it may miss. | §4.4 (CAS-*), §6.14 (SAFE-*) |
| C-4 | **Batch.** There are no interactive latency targets. Work is queued and runs in scheduled model passes, mostly overnight. Batch time is used for accuracy: a bigger model and second opinions. | §4.5, §9 |
| C-5 | **No end-user UI.** Investigators, coordinators, the research office and the data steward work only through email, with optional outbound Teams/LINE nudges that carry no PHI and no actions. Each person gets files they already know how to use (XLSX, PDF, DOCX). Approvals are attributable replies (§3.5). The only exception is a single-purpose signing page, used for the few records that regulations treat as e-signatures. Only system administrators get a console, and it shows no PHI. | §3, §4.2, §10.1 |
| C-6 | **The agent helps in every step.** Every lifecycle stage in §2.3 has a defined agent behaviour, inputs, outputs and gate. Most later-stage help is deterministic: calendars, checklists, templates, diffs. It costs no model time. | §2.3, §6, Appendix A |
| C-7 | **Precision balanced against cost.** One box at about US$5k is the reference. Model classes per hardware profile are chosen by a benchmark gate on the site's own data. | §4.7, §8.2 |
| C-8 | **Multilingual.** Traditional Chinese (zh-TW), English and Japanese (ja), including code-mixed, abbreviation-heavy Taiwanese notes. The language of each output is defined per artefact. Evaluation is stratified by language. | §6.13 (ML-*), §8.5 |
| C-9 | **Codeable now.** Every R0/R1a requirement maps to files in this repository, and the first sprint is ordered by dependency. | §15 |

---

## 1. Where we are

### 1.1 The v1 proof of concept (verified against the code at `1115235`)

Sources: `docs/PROGRESS.md` (D-86), `docs/BENCH.md`, `deploy/docker-compose.yml`, and the test runs reported in PR #2.

**Services.** `deploy/docker-compose.yml` defines 12 services, and 11 run per profile:
- minio, fhir-db (PostgreSQL 16), fhir-store (HAPI FHIR JPA with Clinical Reasoning);
- lake (DuckDB, with CJK bigram full-text search);
- embed-service (bge-m3, via sentence-transformers);
- doc-parser (the lite parser; no Docling image ships);
- criteria-compiler, adapter, orchestrator, mail-gateway;
- llm-stub or llm-service (vLLM).

An arm64 override for NVIDIA GB10 exists (`deploy/docker-compose.gb10.yml`, pinned driver and spark-vLLM image), and
`make images-multiarch` builds both architectures.

**What works on synthetic data with a stub LLM.**
- Email intake with aligned SPF/DKIM/DMARC sender authentication.
- A declarative HIS→FHIR adapter with pseudonymisation (`pid = HMAC(site_key, MRN)`).
- The criteria compiler: protocol text → Criterion IR → ValueSets → CQL and SQL generated from templates, with a CQL≡SQL
  equivalence gate.
- A note judge that verifies its quote against the excerpt (`prompts/judge_v3.md`).
- Deterministic PDF/XLSX/DOCX reports.
- A hash-chained audit log and byte-identical re-runs.
- Egress firewall, signed updates, retention.
- Small-cell protection by threshold suppression, **controlled rounding** (`round_count`) and rate withholding
  (`rate_publishable`) in `libs/tb_common/smallcell.py`.
- An SQLite job queue (`services/orchestrator/db.py`).

The settings reference model classes are a 35B-class MoE judge (`qwen3.5-35b-a3b-q4`) and a 120B-class extractor
(`gpt-oss-120b-mxfp4`). Together these fit one 128 GB GB10 and do not fit one 32 GB card.

**Test state.**

| Platform | lint | unit | integration | e2e | egress |
| --- | --- | --- | --- | --- | --- |
| Linux | clean | 286 passed, 2 skipped | 59 passed, 1 skipped | 6 passed | 1 passed (root) |
| Windows (WSL2) at `080d298` | clean | 286 passed, 2 skipped | 59 passed, 1 skipped | 6 passed | – |

**What has never touched reality.**
- Real patients, a real LLM in the evaluation path, and real protocols. GZQO is a synthetic excerpt; RA-BIO and ONC-OSI are
  fictional NHI rules.
- Full terminology. There are 59 ICD codes and 24 drugs. Bilingual vocabulary consists of 32 hand-written keys in
  `scenarios/terms.py` (retrieval expansion) and a 93-row synonym table (`terminology/src/synonyms.csv`, with zh-TW
  surface forms) used by the compiler.
- Any negation or assertion handling. `services/lake/textproc.py` tokenises and chunks only.
- A database driver for a real HIS.
- The go-live checks of v1 §11.2.

**Honest gaps that v3 must close.**
- The PHI guard has about 100 surnames (`phi_guard.py:17–20`), against the 5,000 that `SPEC.md` §7.4 asks for.
- An optional cloud-LLM route for criteria text still exists in code (`tb_common/llm.py`, `config.py`,
  `deploy/egress.py`, `.env.example`), off by default. v3 removes it (S1-0).
- The batch path still has a full-record fallback that sends up to 28k tokens for up to 100 candidates
  (`evaluate.py:34`).
- The FEAS and SCREEN footers print the configured judge name, not the model actually served (`feas.py:87`,
  `screen.py:137`).
- The HAPI per-patient `$evaluate` was measured at about 21 patients/s (600 patients in 28.7 s). Extrapolated to 3M patients,
  that is about 40 h, so whole-hospital runs use the lake SQL engine.

### 1.2 What the v2 review taught us

1. **The deterministic core is the asset; keep it untouched.** That means template CQL/SQL with an equivalence gate,
   quote-verified judging, the hash-chained audit and byte-identical re-runs.
2. **The v2 draft broke its own owner's requirements.** It had a mandatory web console, latency targets, data-centre
   hardware, a cloud-LLM option, an optional third-party agent framework, and one sentence on languages. v3 is rebuilt around
   C-1 to C-9.
3. **False negatives were silent.** A patient excluded by a miscoded diagnosis disappeared forever. v3 makes exclusion
   auditable, with a recall certificate on every list (§6.14).
4. **Privacy needs a budget, not just rounding.** Repeated what-if queries can be subtracted from each other to reveal small
   cells. v3 adds a privacy accountant (§10.4).
5. **Real-data validation waits on the IRB.** v3 splits R1 into R1a (de-identified research database, no IRB dependency for
   the deterministic core) and R1b (identifiable pre-screening after IRB approval).

### 1.3 What v3 is, in one table

| Area | v1 (built) | v3 (this spec) |
| --- | --- | --- |
| Interaction | Strict email subject grammar | Email in natural language. The agent proposes the exact command and the sender confirms it. XLSX decision sheets are filled and replied. Approvals are attributable replies. A one-page signing step exists only for regulated signatures. |
| Filtering | Structured rules first, then RAG + judge on notes | A normative six-stage cascade (S0–S5) with per-run budgets, a cross-study judgement cache, lazy short-circuit evaluation, cascade metrics in every manifest, and a recall certificate |
| Compute | One judge model online | Scheduled model passes. A 120B-class model runs overnight on the residue only. One model is resident at a time. Hardware is chosen by a benchmark gate. |
| Languages | CJK search, 36-term lexicon | Canonical text with stable offsets; per-sentence language tags; a self-growing site lexicon; Taiwanese date and number normalisation (民國 years, 和暦, full-width digits); deterministic bilingual assertion detection; output language per artefact; evaluation stratified by language mix |
| Lifecycle | Feasibility, screening, cohorts, NHI navigation | All of v1, plus protocol Q&A, the sponsor questionnaire with answer memory, portfolio clinic-day lists, watchlist flip dates, tracking and Bayesian forecasting, start-up, IRB/continuing review, budget/coverage analysis, visit windows, deviations, SAE clocks, eCRF pre-fill with SDV packets, close-out and archive |
| Assurance | Synthetic acceptance scripts | Recall certificates, conformal abstention, an active-learning email loop, self-building validation from historical enrollment logs, auto-generated IQ/OQ/PQ evidence |

### 1.4 Design principles

- **P1 The agent proposes, compiled rules execute, people sign.** An LLM interprets and drafts. Counts, lists and regulated
  records come from deterministic, versioned code, and are released only after a named person signs.
- **P2 Evidence or it did not happen.** Every count, tier and field carries its provenance: rule version, data snapshot,
  source record and quote.
- **P3 The hospital keeps the data.** Nothing patient-level and nothing confidential leaves the box. Sponsors receive rounded
  aggregates within a privacy budget.
- **P4 The inbox is the interface.** Work arrives and leaves as email and familiar files. A message that needs no action is
  not sent. If a step needs a screen, the step is redesigned.
- **P5 Cheapest sufficient evidence.** A rule before a lexicon, a lexicon before a small model, a small model before a large
  one, a large one before a person. Each step is measured and bounded.
- **P6 Never silently lose a patient.** Every exclusion is either certain by construction or audited by sampling, with a
  published bound.
- **P7 Learn the site.** Thresholds, lexicon and exemplars improve from local decisions. Rules change only through a gate.
- **P8 Same answer twice.** Any output can be regenerated from recorded step outputs.
- **P9 Standards in, standards out.** ICH M11/USDM, FHIR R4/TW Core/JP Core, OMOP, CDISC ODM/CDASH and CQL. No proprietary
  lock-in.

---

## 2. Product definition

### 2.1 Vision and positioning statement

A clinical research coordinator forwards a protocol or a sponsor's feasibility questionnaire to `trialbox@hospital`. Within a day of
confirming the request, they have three things back:
- the criteria as the box understood them, with questions;
- after one "OK", a sponsor-ready feasibility packet and the sponsor's own questionnaire filled in, each number traceable to a
  rule and a data cut;
- once the study opens, a weekly list for each investigator of patients with upcoming appointments who probably qualify. Each
  list comes with chart quotes, a bound on how many patients the filter may have missed, and a one-line reply format for
  decisions.

From then until archiving, the box tracks the study and nudges the team about whatever is due next. It runs on one box in the
hospital's server room. It is an independent product (C-1). It needs no new screen. It learns the hospital's data, language
and habits, and becomes more accurate every month at that site.

### 2.2 Users and roles

| Role | Typical person | Works with TrialBox through | Access |
| --- | --- | --- | --- |
| Research coordinator (CRC) | Study coordinator, research nurse | Email; XLSX/PDF attachments; reply approvals for G1 and G4 | PHI for studies they are delegated on |
| Principal investigator (PI), sub-investigator | Attending physician | Weekly packet email; one-line or sheet replies; reply approvals for G2 and G3; signing page for regulated records | PHI for their studies |
| Research office / clinical trial centre | Feasibility desk, CTC manager | Email; monthly portfolio report; G2 sign-off | Aggregates across studies; PHI only with a delegation |
| Data steward | Medical-informatics staff | Atlas workbook round trip (G0); lexicon review | Metadata, de-identified samples |
| IRB / QA / information security | Reviewers, auditors | Monthly QA pack by email; on-request audit export | Read-only audit and reports |
| System administrator | Hospital IT | **Admin console (no PHI)**, `trialbox` CLI | Configuration, health, updates; no PHI |
| Sponsor / CRO (external) | Feasibility manager | Receives released packets by email from a named site person, with an optional machine-readable JSON attachment (R3) | Aggregates only, within budget |
| Agent | TrialBox | Acts on behalf of a named user inside that user's permissions | Never more than the requesting user |

### 2.3 Lifecycle coverage

Every stage has an agent behaviour. "Model?" says whether the stage spends LLM time. Most later stages do not.

| # | Stage | What the agent does | Module | Model? | Release |
| --- | --- | --- | --- | --- | --- |
| 0 | Site readiness | Learns the EMR (Data Atlas); grows the site lexicon; measures freshness and coverage; keeps the site master profile | M0, M-ML | small (mapping proposals only) | R0–R1a |
| 1 | Protocol intake | Parses PDF/DOCX/M11/USDM; extracts I&E and the schedule of activities; asks questions; answers protocol questions with citations | M1 | yes | R1a |
| 2 | Protocol optimisation | Criterion impact, what-if, counterfactual relaxation with safety proxies | M2 | no | R2 |
| 3 | Feasibility | Funnel, per-criterion counts, estimated tiers with intervals, projection, competing trials, investigators; fills the sponsor questionnaire with answer memory | M3 | sample only | R1a |
| 4 | Site selection | Site qualification pack, past performance, start-up timelines | M3 | no | R2 |
| 5 | Start-up | IRB package checklist and pre-fill, CTA budget draft from the SoA with the NHI standard-of-care split, delegation and training-record expiry, activation checklist | M7 | drafting only | R2–R3 |
| 6 | Pre-screening | Cascade per study, portfolio clinic-day lists, watchlist flip dates, decision sheets, recall certificate | M4 | residue only | R1b |
| 7 | Patient → trial | Which open studies fit one patient; tumour-board batches | M5 | residue only | R2 |
| 8 | Consent and enrollment | Pipeline by signed state replies; consent-form version tracking; re-consent on amendments; forecasting with alerts | M6 | no | R2 |
| 9 | Conduct | Visit windows and reminders through the CRC; deviation candidates with CAPA log; SAE/SUSAR clocks; lab critical values already flagged by the hospital system listed for the investigator | M7 | no | R3 |
| 10 | Data | eCRF pre-fill with lineage; SDV source packets; EDC query answer drafts from source; critical-field gaps | M8 | extraction | R3 |
| 11 | Monitoring | Visit preparation pack (source packets, deviation log, ISF index) | M7, M8 | no | R3 |
| 12 | Close-out | Final IRB report draft; registry deadlines; archive export (PDF/A + JSON); retrospective feeding site learning | M9 | drafting only | R4 |
| 13 | Reimbursement | NHI navigation and TWPAS (v1 NAV) | M10 | as v1 | R1a (carried) |
| 14 | Networked research | Alliance cohorts; federated feasibility with a privacy accountant | M11 | no | R3 |

### 2.4 Intended use and regulatory position

**Intended use statement.** It is normative. It MUST appear in the user guide, every report footer and the admin console:

> TrialBox supports research staff in identifying candidate participants for clinical trials, preparing feasibility estimates
> and organising trial operations. All eligibility determinations are made and documented by the investigator. TrialBox is
> not intended to diagnose, treat, mitigate or prevent disease or to inform an individual patient's clinical management.

With this intended use, TrialBox is most likely not a medical device in Taiwan (Medical Devices Act and the TFDA
software-classification guidance), the US (FDA CDS guidance), the EU (MDR, MDCG 2019-11) or Japan (PMDA SaMD guidance). It is
a GCP computerised system. It MUST meet:
- ICH E6(R3) Annex 1 data governance;
- 21 CFR Part 11-equivalent controls (§3.5, §10.6);
- the Taiwan PDPA, the Human Subjects Research Act and the AI Basic Act principles.

CMP-28 requires a written intended-use analysis before any of these features ships:
- per-patient matching on clinician request (M5);
- listing abnormal results for enrolled participants (M7);
- anything that would infer an undiagnosed condition, recommend treatment, or set eligibility without investigator sign-off.

v3 scopes M7 safety support to events already graded by hospital systems. The box lists events; it never grades them.

### 2.5 Non-goals

- Randomisation, IP dispensing, unblinding, or any access to treatment-arm data.
- Writing to the EHR or a sponsor EDC. The box produces files, and humans upload them.
- Patient-facing messages, eConsent signing, or direct patient contact. The treating team contacts patients under the IRB
  plan.
- Patient-level data or protocol text leaving the hospital.
- Any cloud model, hosted service or vendor telemetry.
- A web UI for end users.
- Interoperation with third-party screening vendors (C-1).

---

## 3. The experience: the inbox is the interface

### 3.1 Stages for one study

Every study goes through the same stages. Each one is a short email exchange.

| Stage | The user sends | The box returns (by the next model window, §4.5) | Gate |
| --- | --- | --- | --- |
| 0 Connect (once per site) | Nothing. IT points the box at the HIS or the research database | **Atlas workbook** to the data steward: tables found, proposed mappings, coverage, freshness, lexicon candidates, questions | G0: the steward approves the returned workbook |
| 1 Ask | A protocol (PDF/DOCX/M11/USDM), pasted I&E text, or a sponsor questionnaire, with any subject line, in Chinese or English | **Understanding email** listing each criterion with how it will be computed (rules, notes or "ask the PI"), its computability at this site, and numbered questions with proposed defaults. **Criteria workbook** (XLSX) attached | G1: the CRC replies `OK`, or answers questions by number, as a Level A approval |
| 2 Answer | Nothing more (G1 triggers it) | **Feasibility packet** (PDF + XLSX): funnel, per-criterion counts, estimated tiers with intervals, projection p10/p50/p90, competing trials, investigators. **Sponsor questionnaire** filled in, with a provenance sheet. **Draft cover email** to the sponsor | G2: the PI or research office approves the release; the box sends to the recipient named in the original request |
| 3 Find | Study status set to recruiting (by reply `STUDY GZQO recruiting`) and the delegation log (XLSX) | **Weekly clinic-day packet** per PI (encrypted XLSX + one PDF per strong candidate): candidates with appointments in the next 14 days, tiers, per-criterion evidence quotes, watchlist flip dates, **recall certificate** | G3: the PI replies with one-line decisions, or returns the decision sheet with its column filled |
| 4 Track | One-line state replies (`P0156 consented 2026-10-17`) | **Monday status email**: pipeline, reasons, forecast against target, early warning, what is due this week | G4: each state change is an attributable approval |
| 5 Run | Nothing (calendar-driven) | **Nudges** for visit windows, SAE clocks, continuing review, consent version, training expiry; **visit packs** before monitor visits | Approvals only where a record changes; Level B signatures for regulated records |
| 6 Close | `STUDY GZQO closed` | Archive bundle, final IRB report draft, retrospective, registry reminders | G2 for anything external |

The **Study Card** is the single record of a study: protocol versions, rulesets, releases, pipeline and timeline. It is
stored in the box and never rendered as a web page. `STATUS GZQO` returns it as a PDF. Every reply ends with a
"changed since your last message" block.

### 3.2 Message design rules

| ID | Rule | V | R |
| --- | --- | --- | --- |
| FR-UX-1 | Every outbound message MUST state, in its first three lines: what this is; what the recipient needs to do, or "no action needed"; and the deadline. | T | R1a |
| FR-UX-2 | Outbound bodies MUST NOT contain PHI. Patient-level content travels only in encrypted attachments (§10.2 SEC-10) addressed to delegated internal recipients. **Inbound** reply bodies may carry pids, MRNs (`MATCH`) or free text about a patient over the hospital's internal TLS mail. They are classified as PHI-bearing, redacted at storage (PRIV-6), and never quoted back. | T | R1a |
| FR-UX-3 | Every action a user can take MUST be expressible as a reply line in the grammar (Appendix D). Each message prints the exact lines it accepts. The user can copy one or type it. | T | R1a |
| FR-UX-4 | **Decision sheets.** Any list that needs decisions (candidates, criteria, mappings, questionnaire gaps) MUST be sent as XLSX with locked data columns and one editable decision column (data validation dropdowns). A returned sheet is parsed and validated: row hash and file hash must match what was sent. The box echoes back the parsed decisions for approval before applying them. | T | R1a |
| FR-UX-5 | **Quiet by default.** A user receives at most one digest per day per role, unless a gate is due within 24 h or a safety clock is running. Each user can set `DIGEST daily|weekly|off` by reply. | T | R1b |
| FR-UX-6 | Teams and LINE MAY carry outbound nudges only: "You have 1 item in TrialBox waiting for you in your mailbox". They carry no study identifiers, counts or PHI, and accept no replies. | T | R2 |
| FR-UX-7 | The language of each message follows ML-9 (§6.13): the recipient's preferred language for prose, the template language for regulated artefacts. | T | R1a |
| FR-UX-8 | Attachments are generated deterministically from data objects (v1 renderer). Fonts embedded (Noto Sans CJK TC/JP). XLSX uses frozen headers, filters and no macros. | T | R1a |

### 3.3 Talking to the agent: deterministic first, proposals second

Intake happens in three steps:
1. **Exact grammar.** If the subject or the first body line parses as a command in Appendix D, it is executed as v1 does
   today. No model is involved.
2. **Free text.** The quoted history is stripped first: `>` blocks, `On … wrote:`, `寄件者:`/`差出人:` headers, Outlook
   separators and signatures. The `classify_intent` prompt then runs on the remaining text only, during the next model pass
   or with the resident model. It produces a **proposal**: an exact command plus a plain-language restatement.
3. **Confirmation.** The box replies with the proposal. The sender replies `OK`, or with an edited command. Only a confirmed
   command starts a workflow that releases data, changes a Study Card or contacts anyone. `STATUS`, `HELP`, `ASK` and `ATLAS`
   (read-only, aggregate) are exempt.

Parameters that select recipients, widen scope beyond the sender's delegations, or release data externally are never taken
from free text. They come from the delegation log and the Study Card (SEC-13).

| The coordinator writes | The box proposes |
| --- | --- |
| 「這個試驗我們做得起來嗎？贊助商週五要數字」 + protocol.pdf | `FEAS NEW scope=hospital lookback=24m deadline=2026-10-23` and a new study code |
| "How many if we drop the BMI criterion?" (reply on the FEAS thread) | `WHATIF GZQO drop INC-07` (internal only, never released) |
| 「幫我填這份問卷」 + sponsor.xlsx | `QFILL GZQO` |
| "Start screening in Dr. Lin's and Dr. Wang's clinics, weekly" | `SCREEN GZQO scope=practitioners:P12345,P23456 cadence=weekly` (the practitioners are resolved from the delegation log) |
| 「P0156 今天簽同意書了」 | `STATE P0156 consented 2026-10-17` (approval follows) |
| "Is prednisone 10 mg allowed?" | `ASK GZQO "prednisone 10 mg"`. Answered from the protocol text with section citations (§6.1 FR-M1-10). No patient data is used |

### 3.4 Configuration without a configuration screen

1. IT installs the box from the offline bundle and runs `trialbox doctor`. It checks every prerequisite and prints the fix
   for each failure.
2. IT writes `site/sources.yaml`: a read-only SQL account, a CSV/Parquet drop, or FHIR Bulk export.
3. The Data Atlas runs and emails the data steward the **Atlas workbook**. It has one sheet per canonical table, with
   dropdowns, and a sheet of lexicon candidates.
4. The steward edits and returns the workbook. The box applies it, re-runs, emails a diff, and asks for G0 approval.
5. The research office returns the **site-profile workbook**. It is pre-filled from the box's data where possible:
   departments, practitioners, historical enrollment.
6. Every confirmed change becomes versioned configuration in the box's Git repository, and the admin console shows it
   read-only.

### 3.5 Approvals without a UI: two assurance levels

Most gates are site operational decisions: confirming a mapping, confirming criteria, releasing aggregates, or choosing which
candidates to approach. A few create records that a regulator inspects as signed records. The two kinds need different
assurance.

Email is an open channel, and an earlier mailbox login is "previous system authentication":
- NIST SP 800-63B-4 says email SHALL NOT be used for out-of-band authentication.
- The EU Annex 11 revision draft (13.3) rejects relying on a previous login or a PIN alone.

So v3 does **not** claim that an email reply is a Part 11 signature. Instead every gate has a configured `assurance`
level.

**Level A: attributable reply (default for G0–G4).**
1. **Request.** The gate email contains:
   - the gate id;
   - the object being approved: its title, version, and SHA-256 of its canonical JSON;
   - the meaning text from §7.1, in the recipient's language;
   - the exact reply line, with the first 16 hex characters of the hash, for example
     `APPROVE G2-0193 sha=4be1c2d97a0e31f5`. The full hash is printed in the request.

   Attachments show the object.
2. **Reply.** The reply MUST come from the delegated, personal mailbox recorded in the delegation log. Shared and role
   mailboxes are refused. The box checks that:
   - DMARC-aligned authentication passes from the hospital domain with the pinned authserv-id (v1 intake, D-86);
   - `In-Reply-To` matches the request;
   - the 16-hex prefix matches the current object's hash.
3. **Record.** The box writes an `approval` record with the approver, printed name, meaning, UTC time, record hash and
   message ids. It returns a **receipt** email, and renders the approval on every output that carries the object.

Level A records are attributable, time-stamped, hash-linked and audited. The hospital's research-operations SOP classifies
them as approvals of operational records, not e-signatures under 21 CFR 11.

Pre-screening decisions (G3) are of this kind. The investigator decides whom to approach, not whether a person is eligible.
Eligibility is determined at screening, after consent, in the sponsor's systems.

**Level B: signing ceremony (for regulated signatures).**

Level B is used for:
- G5 (production change);
- certification of eCRF pre-fill source packets (M8);
- deviation approvals (M7);
- any gate a site maps to a Part 11 / E6(R3) signed record (`gates.<id>.assurance: B`).

The gate email carries a single-use link, valid for ≤ 15 min, to a **single-purpose signing page**. It is the only end-user
page in the product. It has no navigation. It shows:
- the record, rendered from the same object the email attached;
- the meaning, selected from a controlled list;
- the attestation text.

It then runs a full re-authentication:
- **B1 (default):** a WebAuthn passkey or FIDO2 assertion whose challenge is the record hash plus a nonce. The signer
  enrolls the passkey at delegation after an identity check (11.100(b); FDA 2024 Q&A Q26).
- **B2:** the hospital IdP with forced re-login (OIDC `prompt=login`, `max_age=0`, or SAML `ForceAuthn`), password plus a
  possession factor, or the IdP's phishing-resistant strength. A cached SSO token is never accepted.
- **B3 (Taiwan legal presumption):** a PKI digital signature (CAdES/PAdES) over the canonical record with the signer's
  Healthcare Certification Authority certificate (醫事人員憑證, card or mobile) or MOICA. Under the Electronic Signatures Act
  (amended 2024, Art. 6), a digital signature backed by a licensed CA is presumed to be the signer's own.

The page runs on the box. It is reachable from the hospital network only, and is served by the same FastAPI app as the admin
console, on a separate listener with no admin routes.

**Optional Level A+ (off by default).** A site that does not want the signing page for some Level B gates MAY enable an
email reply carrying a challenge-response code. The code is computed with **OCRA (RFC 6287)** on an enrolled authenticator.
The challenge is the first 8 digits of SHA-256(gate_id ‖ record_hash ‖ nonce), and the box prints it in the request. Plain
TOTP cannot be bound to a record, so it is not accepted.

A+ needs a documented site risk acceptance, because it is weaker than Level B. The box records the method used, and the
receipt states it.

**Passkey enrolment (B1).** Enrolment is an admin-assisted ceremony on the signing listener. The research office verifies
identity in person (11.100(b)) and starts a one-time enrolment link. The signer registers the passkey. The ceremony is
audited.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-SIG-1 | Every gate MUST have a configured assurance level (A, A2, A+ or B). Defaults: G0–G4 A; G5 and G6 (M7 deviation approval, M8 source certification) B. A Level B gate MUST NOT be satisfiable by any email reply unless A+ is enabled for that gate. **Interim rule until FR-SIG-3 ships (R1a):** G5 is satisfied by two hash-bound Level A approvals from different roles (system owner and QA), recorded as `assurance: A2`, and listed in the validation pack as a time-limited deviation. | T | R1a |
| FR-SIG-2 | Level A: implement steps 1–3. An approval MUST be rejected if the hash in the reply differs from the current object, or if the object changed after the request was sent; in that case a fresh request is sent. | T | R1a |
| FR-SIG-3 | Level B signing page: single-use link (≤ 15 min, bound to signer and gate). Methods B1/B2. The `signature` record (§5.9) MUST hold the printed name, user id, role, meaning, UTC time with the Asia/Taipei offset, record hash, method, and the WebAuthn or IdP assertion reference (11.50, 11.70). | T | R1b |
| FR-SIG-4 | Negative tests MUST pass: replayed link; expired link; link forwarded to and opened by another user; stale SSO session (must prompt); record changed after signing (renders "unsigned"); clock skew; lockout after 3 failures with an alert to the research office (11.300(d)). | T | R1b |
| FR-SIG-5 | B3 PKI signature with HCA or MOICA, where the hospital provides the middleware. | T | R2 |
| FR-SIG-6 | Signed or approved batches (decision sheets) MUST record one approval or signature over the hash of the parsed decision set. The receipt lists every decision. | T | R1b |
| FR-SIG-7 | The box MUST ship the validation pack for approvals and signatures. It contains: a trace matrix to 11.10/11.50/11.70/11.100/11.200/11.300 and the EMA computerised-systems guideline §4.8; the negative tests; an identity-proofing SOP template; the 11.100(c) non-repudiation letter template; a Taiwan internal e-signature policy template. Under B2, password controls (11.300) are the hospital IdP's and are referenced as a supplier control. The ESA Art. 5 counterparty-consent record applies only to documents exchanged with another party (for example sponsor-facing releases), not to internal approvals. | I | R1b |
| FR-SIG-8 | Teams and LINE MUST NOT carry approvals. A Teams nudge MAY carry the Level B signing link when the site enables it. | T | R2 |

### 3.6 The administrator console (the only UI besides the signing page)

The console is for system administrators only. It has no PHI, no study content and no patient lists. It shows:
- service health and queue depth;
- the model-pass schedule and benchmark results;
- the cascade metrics per run, aggregate only (§4.4);
- configuration history from Git;
- certificate and key expiry, update bundles and backups;
- audit-ledger integrity status.

It is server-rendered HTML, reachable only on the management VLAN. Login is local accounts with TOTP. There is no SSO broker.
Everything it shows is also available through `trialbox` CLI commands, and the console is optional (`console.enabled`).

---

## 4. Architecture

### 4.1 System context (C4 level 1)

```
              ┌──────────────────────────────── Hospital network ───────────────────────────────────┐
  CRC, PI,    │  email (Exchange/SMTP, DMARC)          ┌────────────────────────────┐               │
  research ───┼───────────────────────────────────────▶│                            │               │
  office,     │◀── replies, encrypted XLSX/PDF ────────│         TrialBox           │── NHI TWPAS ──┼──▶ NHI (optional,
  steward     │                                         │   one box, on premises    │               │     orchestrator only)
              │  HIS / research DB / LIS / RIS          │                            │── registry ───┼──▶ ClinicalTrials.gov,
              │  read-only views, CSV drop, FHIR Bulk ─▶│                            │   GET only    │     MOHW trial platform
              │                                         └───────────▲────────────────┘               │
  Hospital IT ┼── admin console + CLI (management VLAN) ────────────┘                                │
              │  Teams / LINE (outbound nudges only, no PHI, no study ids) ──────────────────────────┼──▶ Microsoft / LINE
              └──────────────────────────────────────────────────────────────────────────────────────┘
                     sponsors and CROs receive released aggregates by email from a named site person
```

Egress is deny-by-default. The allowlist is exactly:
- the hospital mail relay;
- the NHI TWPAS endpoint (orchestrator only);
- ClinicalTrials.gov API v2 and the MOHW trial platform (registry-sync only, HTTPS GET, no request body);
- the Teams webhook and LINE Messaging API endpoints, only if nudges are enabled (notify worker only, fixed templates
  without variables except a count of pending items, R2).

There is **no** model endpoint outside the box (C-2).

### 4.2 Containers (C4 level 2)

v3 keeps the v1 services and adds as few components as possible. Each added component is a validated supplier component
(CMP-05), so the list is short on purpose.

| Container | Responsibility | Tech | State | Change from v1 |
| --- | --- | --- | --- | --- |
| mail-gateway | IMAP/SMTP, sender authentication, attachments, S/MIME, 7z | v1 code | MinIO, SQLite→Postgres | extended: quoted-text stripping, decision-sheet intake, OTP challenge |
| **intake** | Grammar parse, free-text proposal (`classify_intent`), confirmation state, `ASK` answers | Python module inside orchestrator | Postgres `intake` | new (module, not a service) |
| orchestrator | Workflows, gates, scheduler, scenarios (FEAS, SCREEN, NAV, COHORT, QFILL, TRACK, CONDUCT, ABSTRACT, CLOSE), outbox | v1 code; job queue moved to PostgreSQL with `steps`, `gates`, `outbox` tables (§7.0) | Postgres `orch`, MinIO | refactored |
| criteria-compiler | Protocol → IR v2 → ValueSets → CQL/SQL; equivalence gate; canonical criterion hashing; filter-class assignment | v1 code + IR v2 | Git (rulesets) | extended |
| doc-parser | PDF/DOCX/XLSX/M11/USDM → text, sections, tables; canonical text; language tags | v1 lite parser + PaddleOCR for scanned zh-TW/ja (optional image) | – | extended |
| adapter | Source → canonical FHIR NDJSON + lake; pseudonymisation; streaming; date/number normalisation | v1 code | lake, pid map | extended |
| **atlas** | Profiling, mapping proposals, coverage, computability, data quality, lexicon mining | Python + DuckDB, module of adapter | Postgres `atlas` | new (module) |
| lake | DuckDB per snapshot; guarded SQL; CJK FTS; hybrid retrieval; judgement cache tables | v1 code | lake volume | extended |
| fhir-store | HAPI FHIR JPA; CQL verification sample | v1 | fhir-db | kept |
| embed-service | bge-m3 embeddings; optional reranker | v1 | – | kept |
| llm-service | One resident model per pass, OpenAI-compatible, JSON-schema constrained | vLLM (x86, GB10 build) or llama.cpp server (P-Mac) | model volume | extended: pass scheduler swaps models |
| **registry-sync** | Scheduled ClinicalTrials.gov / MOHW pulls into a local index | Python worker | Postgres `registry` | new |
| **eval** | Evaluation suites, benchmark, credibility files, validation replay | Python package + CLI (`trialbox eval`, `trialbox bench`) | MinIO reports | new (CLI, not a service) |
| **console** (admin only) | Health, schedule, metrics, config history, ledger status | FastAPI + Jinja2, no JS framework | none | new, optional |
| postgres | Orchestrator, intake, atlas, registry, ledger | PostgreSQL 16: a **second container** from the same pinned image as fhir-db, with its own volume, so HAPI I/O does not compete with the outbox | volume | new container, same engine |
| minio | Object store | v1 | volume | kept |

The following are deliberately **not** used:
- Keycloak or another SSO broker: there are no end-user logins.
- LiteLLM or another model gateway: role resolution is about 100 lines in `tb_common.llm`.
- Langfuse: OpenTelemetry goes to files plus Prometheus.
- OPA: the policies are tables enforced by a Python policy module with property tests.
- Hermes or another agent framework.
- Any separate workflow engine service. ADR-V3-02 records why.

### 4.3 Layering and the PHI boundary

```
 L1 Channels      mail-gateway (in/out) · notify (Teams/LINE nudges, no PHI)                 no PHI tools
 L2 Intake        grammar → proposal (classify_intent on stripped text) → confirmation        no PHI tools
 L3 Policy        sender auth · delegation · purpose · privacy accountant · rate limits
 L4 Workflows     orchestrator: durable steps, gates (reply approvals, signing page), outbox, schedules
 L5 Tools         T0 public/meta · T1 aggregates (accountant-checked) · T2 PHI (study+delegation scoped)
                  · T3 writes (deterministic steps after a gate only)
 L6 Data          lake · FHIR store · pid map (AES-GCM) · object store · judgement cache        PHI lives here only
 L7 Models        llm-service: one resident model per pass, local only
 L8 Assurance     audit ledger · eval · bench · recall audit · OTel metrics · backups
```

The rules:
- **SEC-11.** A model never holds T3. T2 data reaches a model only inside a workflow step started for a study the requesting
  user is delegated on, and every such call is logged with its purpose.
- **SEC-12.** Intake (L2) sees request text and status only. It never sees patient-level data. `MATCH` requests carry the MRN
  in the grammar line and bypass the model entirely.
- **SEC-13.** Recipients, scope and release targets come from the delegation log and the Study Card, never from model output
  or document content.

### 4.4 The filter-first cascade (normative)

The cascade is the heart of the product. It decides which patient-criterion pairs need evidence, and it spends model time
only where nothing cheaper can decide.

```
 population of scope
   │ S0  scope + opt-outs + active status                         SQL                      cost ≈ 0
   ▼
   │ S1  structured criteria (IR → SQL on the lake; CQL sample)   SQL, three-valued       cost ≈ 0
   │      excludes only on AFFIRMATIVE evidence of ineligibility
   │      (a code/value/date in window, logged as evidence) for
   │      hard-class criteria; absence → unknown, passes on
   │      exception: absence of the index condition → S2 rescue
   ▼
   │ S2  note pre-filter per note criterion, and rescue sweep:    lexicon + FTS + rules   cost ≈ 0
   │      patients without the index-condition code are kept if
   │      any note in the lookback mentions it (approved lexicon);
   │      window-restricted bilingual keyword/lexicon hits;
   │      zero hits → absence semantics of the IR (§5.2)
   │      hits → deterministic assertion pass (ML-6); numeric
   │      extraction by pattern (e.g. "EF 35%", "eGFR 28")
   ▼
   │ S3  judge (resident model, class J) on the residue,          LLM, batch              bounded by budget
   │      criteria ordered by exclusion power ÷ cost, lazy,
   │      short-circuit on the first verified hard not_met
   ▼
   │ S4  second opinion (model class V ≥ J, other family,         LLM, overnight pass     bounded by budget
   │      overnight) on would-be strong candidates and on
   │      S3 judgements above the abstention threshold (§8.4)
   ▼
   │ S5  person: PI decision sheet (G3); "five-minute review"     human                   10 items/week/CRC
   │      questions (§8.6)
   ▼
 tiers: strong · potential · watchlist · excluded (+ recall certificate)
```

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CAS-1 | Every screening and feasibility run MUST execute the stages in order and record, for each stage, the number of patients and patient–criterion pairs that enter and leave, in the run manifest (`cascade` block, §5.8). | T | R1a |
| CAS-2 | A criterion the compiler classifies `structured` MUST NOT be sent to any model. A `note` criterion MUST NOT be judged for a patient who has a hard failure on another criterion, or who is opted out. | T | R1a |
| CAS-3 | Within S3, note criteria MUST be evaluated in descending order of `exclusion_power / expected_tokens`. Exclusion power is the historical fraction of `not_met` per canonical criterion at this site, with prior 0.5. Evaluation stops for a patient at the first verified `not_met` that is a hard failure. | T | R1b |
| CAS-4 | **Budgets.** Each run has `max_llm_items` and `max_tokens` from the ruleset manifest (defaults: 2,000 items, 10M tokens per study per run). If a run would exceed its budget, it MUST finish S0–S2 for everyone, then spend the budget on patients in order of their next appointment, then emit a partial packet. The packet names the unprocessed count, and the run is never silently truncated. | T | R1b |
| CAS-5 | **Judgement cache.** Results MUST be keyed by `(pid, canonical_criterion_hash, chunk_set_hash, prompt_version, model_sha)` and reused across studies and runs. A canonical criterion is the normalised (atom, window, note_question) triple; the compiler assigns its hash. Cache entries are invalidated when the patient's chunk set for the window changes. | T | R1b |
| CAS-6 | **Incremental evaluation.** A nightly run MUST re-evaluate a patient-criterion pair only if: (a) the patient has new or changed records in a domain the criterion depends on, (b) the criterion's window boundary passed a record date since the last run, or (c) the ruleset or model changed. The compiler emits each criterion's domain dependencies and its next-flip date (§5.2). | T | R2 |
| CAS-7 | **Metrics.** The manifest MUST record `n_scope, n_after_S0..S4, pairs_judged_S3, pairs_judged_S4, tokens_in, tokens_out, cache_hits, llm_share = pairs_judged_S3 / (n_after_S1 × note_criteria)` and GPU-seconds per pass. `pairs_judged_*` counts model calls actually made, excluding cache hits. A note criterion's `not_met` is a **hard** failure for CAS-3 only when the quote is verified, the assertion rules agree, and the judgement is not abstained (§8.4). The admin console and the monthly QA pack report them per study. | T | R1a |
| CAS-8 | **Feasibility uses sampling for model stages.** Tier counts in a feasibility packet are estimates. S0–S2 run on the full population; S3–S4 run on a stratified random sample (default ≤ 200 patients per stratum, strata = S2 outcome × department). Estimates use a stratified estimator: Σ N_h p̂_h over strata, a normal interval on the total with the finite-population correction, and Wilson intervals per stratum when a stratum is reported alone. They are reported as `{est, ci95_low, ci95_high, n_sampled}`. The estimate is control-rounded; the interval endpoints are floored and ceiled to base 5, so coverage is never reduced. | T | R1a |
| CAS-9 | The v1 full-record fallback (`FULL_RECORD_MAX_CANDIDATES`) MUST be removed from batch paths. It remains available only for an explicit `FULLREVIEW <pid>` request on ≤ 20 patients. | T | R1a |
| CAS-11 | **Affirmative exclusion** (rulesets with IR ≥ 2.0.0). S1 MUST exclude a patient only on affirmative evidence of ineligibility: a matching record in the window for an exclusion atom, or a failing value for an inclusion threshold. The evidence item (code, value, date, source) MUST be logged. Missing data MUST yield `unknown` and pass to the next stage. The single exception is absence of the study's **index condition** (the criterion tagged `index: true`). Such a patient is excluded only if the S2 rescue sweep finds no approved-lexicon mention of the condition in any note in the lookback. | T | R1a |
| CAS-10 | **Recall certificate.** Every candidate packet and feasibility packet MUST carry the current recall certificate of its study and ruleset (§6.14 SAFE-3). | T | R1b |

### 4.5 Batch execution and model passes

Latency does not matter, so the box runs at most one model at a time and schedules **passes**.

| Window (default) | What runs | Model resident | Work |
| --- | --- | --- | --- |
| 07:00–19:00 Day pass | J | J | Intake proposals (within 2 h, NFR-B2), protocol understanding (FR-M1-2 first extraction), `ASK`, questionnaire mapping, urgent re-checks |
| 19:00–21:00 Ingest | adapter, Atlas, snapshot publish, dirty-set computation (CAS-6) | none | Source data up to 19:00 becomes snapshot T |
| 21:00–01:30 Night pass 1 | J | J | S3 judgements on snapshot T for all scheduled screens and feasibility samples |
| 01:30–05:30 Night pass 2 | V | V | S4 second opinions, second criteria extraction, recall-audit judgements; spare time goes to the shadow pass (AI-14) |
| 05:30–06:30 Night pass 3 | J | J | Narrative drafting with placeholders, five-minute review selection |
| 06:30–07:00 Assembly | packets, outbox | J (day pass starts) | Deterministic rendering and sending |

Pre-screening judges each night on the snapshot published that evening. Appointments are booked in advance, so data up to
19:00 is fresh enough.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-B1 | The pass scheduler MUST load the model for each pass, drain the queue by priority (gate replies > feasibility > pre-screen > recall audit > abstraction > drafting), and unload it at the window's end. Model swap time is recorded. | T | R1a |
| NFR-B2 | Grammar commands are acknowledged deterministically within one intake poll. Free text receives its proposal within the day pass: ≤ 2 h after receipt between 07:00 and 17:00 (J stays resident for this), otherwise by 08:00 the next day. Other work waits for its pass. | T | R1a |
| NFR-B3 | A pass that cannot finish its queue MUST carry over, report the backlog in the admin console, and email the research office if any gate or deadline would be missed. | T | R1a |
| NFR-B4 | Windows, priorities and model classes are site configuration. On P-5090, passes J and V use the same physical GPU in sequence. | I | R1a |
| NFR-B5 | **Memory budget.** Each window declares a memory budget. On unified-memory profiles (P-GB10), `TB_LAKE_MEMORY_LIMIT` MUST be ≤ 16 GB while a model is resident (v1's default is 40 % of RAM). No ingest or Atlas job may overlap a V pass. The scheduler enforces this, and `trialbox bench` records peak RSS per window. | T | R1a |

### 4.6 Main data flows

**Ingest (nightly, 19:00).** The steps are:
1. Source views or a drop are read by the adapter, which streams in patient-id chunks.
2. Canonical text and dates are normalised (ML-2, ML-3).
3. The adapter writes canonical FHIR NDJSON and builds the lake.
4. The Atlas profiles the data and runs quality checks.
5. A snapshot is published with its ingest report.

A snapshot that fails a blocking quality check is not published. The previous snapshot stays current, and the steward is
told why.

**Protocol to ruleset.** The steps are:
1. The doc-parser extracts the protocol and its sections.
2. `extract_criteria` runs twice: with model J in the day pass, then with model V in night pass 2.
3. The two extractions are reconciled.
4. Concepts are mapped through `tb.vocab.search` only.
5. The result is IR v2 with canonical hashes and filter classes.
6. CQL and SQL are generated, and the equivalence gate runs.
7. The understanding email and the criteria workbook are sent.
8. G1.
9. The ruleset is frozen as `<study>/v<semver>`.

**Feasibility.** The steps are:
1. The frozen ruleset runs S0–S2 on the full population, and S3–S4 on the stratified sample.
2. The packet is assembled: funnel, estimates, projection, competing trials, investigators.
3. The privacy accountant checks it.
4. Rounding is applied and the files are rendered.
5. The narrative is drafted with placeholders and checked with `numbers_match`.
6. G2.
7. The packet is sent through the outbox.

**Pre-screening (weekly per study, or a nightly clinic-day portfolio).** The steps are:
1. Appointments in the next 14 days are selected, plus watchlist flips that are due.
2. The cascade runs S0–S4.
3. Tiers are assigned and the recall certificate is attached.
4. The PI packet and decision sheet are sent.
5. G3.
6. Calibration and the exemplar bank are updated.

### 4.7 Hardware profiles and the benchmark gate

#### 4.7.1 Profiles

| Profile | Hardware | Model classes that fit *(est.)* | Status |
| --- | --- | --- | --- |
| **P-GB10** (recommended default) | One NVIDIA GB10 system with 128 GB unified memory (DGX Spark, or OEM: Dell Pro Max GB10, HP ZGX Nano, Lenovo ThinkStation PGX); 4 TB NVMe; external 8 TB backup disk | J: 30–35B MoE at 4-bit (about 20 GB). V: 100–120B-class MoE at MXFP4/4-bit (about 65 GB). Not both at once with the lake; passes are sequential. | Supported in R1a. v1 already ships `docker-compose.gb10.yml`, and the v1 settings models (35B judge, 120B extractor) are exactly this pair. |
| **P-5090** | x86 workstation, one RTX 5090 32 GB, 128–256 GB RAM, 4–8 TB NVMe | J: 30–35B MoE or 32B dense at 4-bit with 32k context. V: a second 30B-class family, loaded in a separate pass. A 70B+ model needs CPU offload, which is too slow for the night window. | Supported in R1a. Choose it if the benchmark gate passes with 30B-class V on the site's data, or if IT refuses arm64. |
| **P-Scale** | x86 server with one RTX PRO 6000 96 GB, or two GB10 linked (256 GB) | V up to about 230B-class MoE at 4-bit | R2, for medical centres with more than 50 recruiting studies |
| **P-Mac** (experimental) | Apple Mac Studio, ≥ 128 GB, as **LLM host only** next to an x86 or GB10 box that runs everything else | Very large V (MLX or llama.cpp) | R3, behind a flag. Docker on macOS cannot use the GPU, so the model server runs natively and outside the compose hardening, egress and disk-encryption model. Not recommended as the appliance. |

Reference prices in October 2026 *(volatile because of the memory shortage; quotes needed)*:
- P-GB10: about US$4.7k (DGX Spark); OEM units about €3.2k–5.8k excluding VAT *(est., retailer listings)*.
- P-5090: card street price US$4k–7k (MSRP US$1,999), plus the workstation.
- P-Mac: US$5.5k for 96 GB, about US$9.5k for 256 GB.

#### 4.7.2 Capacity model

The nightly LLM demand is:

```
D = Σ_studies  pairs_S3(study) × (1 − cache_hit) × (tokens_in + tokens_out)  +  pairs_S4 × (…)  +  audit + extraction
```

The default per-item cost *(est.)* is a 2,500-token prompt plus a 250-token output, about 2,750 tokens per item.

Expected S3 load *(est.)*:
- A medical centre with 30 recruiting studies should need 10³–10⁴ S3 items per night once the judgement cache is warm. That
  is 2.75M–27.5M tokens.
- Community benchmarks report 1,700–2,700 prefill tokens/s on GB10 for a 120B-class MoE *(est., unverified)*. The 30B-class
  J model should be faster. At those rates, prefill takes 0.3–4.5 h and decode adds roughly 0.5–1 h at the upper end.
- The upper end needs most of the night. That is why the cache, the dirty set (CAS-6) and the night budget below are
  requirements, not optimisations.

A new study's backfill feasibility uses sampling (CAS-8), so it costs at most a few thousand items.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| CAS-4a | **Night budget.** The pass scheduler MUST hold a global `night_tokens` budget, by default 50 % of the capacity measured by `trialbox bench` for each pass. Per-study budgets (CAS-4) are allocated from it by priority and next-appointment date. Exhaustion carries work over (NFR-B3) and is reported. | T | R1b |

#### 4.7.3 Benchmark gate

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| NFR-17 | `trialbox bench` MUST measure, on the installed box: (a) J and V throughput in items/hour at the site's median prompt length, batch 16–64, JSON-constrained; (b) protocol extraction minutes per 100 pages; (c) quality on the `judge` suites per language stratum and on `criteria_extract`, for the chosen quantisation, against the reference run (≤ 2-point drop allowed). | T | R1a |
| NFR-18 | **Capacity gate.** Planned weekly LLM items (from CAS-7 history, or the estimate for a new site) MUST be ≤ 50 % of the measured night capacity. Otherwise the box reduces scope or cadence and the research office is told. The bench result is part of the install record and is re-run after every G5 change. | T | R1a |
| NFR-19 | **Model choice by evidence.** For each profile, the registry MUST bind each role to the **smallest** model that passes all quality gates of §8.5 on the site's de-identified evaluation set. A larger model is used only where it buys measured accuracy. | A | R1a |

### 4.8 Architecture decision records

| ADR | Decision | Alternatives | Reason |
| --- | --- | --- | --- |
| ADR-V3-01 | Deterministic CQL/SQL remains the only source of counts and tiers. Models fill note criteria with verified quotes. | LLM-only matching | Reproducibility and audit; open matching baselines are strong but unaccountable |
| ADR-V3-02 | Durable workflows on PostgreSQL tables (`jobs`, `steps`, `gates`, `outbox`) inside the orchestrator, extending the v1 queue | DBOS Transact; Temporal | One database engine already validated (HAPI). The outbox makes sends exactly-once (v1 D-86 refuses re-sends after an ambiguous send). Fewer supplier components to validate. DBOS remains the fallback if workflows outgrow this. |
| ADR-V3-03 | Lake SQL is the engine; HAPI CQL verifies a sample | HAPI-only | HAPI measured at about 21 patients/s; whole-hospital runs need SQL |
| ADR-V3-04 | Sequential model passes with one resident model; roles map to model classes per profile | Concurrent portfolio behind a gateway | Fits the owner's hardware; batch makes swapping cheap; bigger V model overnight |
| ADR-V3-05 | P-GB10 is the recommended default profile. P-5090 is supported. P-Mac is experimental. | P-5090 default (the reviewer's recommendation) | With filter-first, demand is small, so model capacity matters more than throughput. GB10 runs the 120B-class V that the v1 settings already assume, costs less than a 5090 workstation at current prices, and is already supported by v1. The reviewer's dissent is recorded: P-5090 has higher prefill throughput and a mature x86 stack. The benchmark gate (NFR-17–19) decides per site. |
| ADR-V3-06 | No end-user UI. Email, attributable reply approvals and decision sheets. A single-purpose signing page only for regulated signatures. Admin console only. | Web console (v2); email-only signatures | Owner constraint C-5. PIs do not log into portals. An email reply cannot carry Part 11 re-authentication (NIST 800-63B-4; Annex 11 draft 13.3), so the one unavoidable page is a signing ceremony with no navigation. |
| ADR-V3-07 | No cloud model and no third-party agent framework | Cloud for criteria text; Hermes front end (v2) | C-2; protocols are sponsor-confidential; smaller attack surface |
| ADR-V3-08 | IR v2 is a superset of v1. New semantics (missing data → `unknown` at S1, filter classes, CAS-11) apply only to rulesets compiled with IR ≥ 2.0.0. The cascade reads the IR version and disables CAS-11 for older rulesets. | Re-tag v1 rulesets | Approved v1 rulesets keep their behaviour byte-for-byte until their next G1 |
| ADR-V3-09 | OMOP CDM 5.4 as an optional lake view | OMOP-native core | Keep v1 contracts; OMOP for OHDSI and national networks |
| ADR-V3-10 | Recall is certified by audit sampling. Precision is learned from PI decisions. | Report precision only | Silent false negatives are the main patient-level harm of a filter-first design |

---

## 5. Data model and contracts

All contracts are JSON Schema 2020-12 files, following the v1 conventions:
- `make contracts` compiles them into `libs/tb_contracts`, and `make contracts-check` fails CI on drift.
- v3 schemas live in `schemas/v2/`, versioned 2.x so that they line up with IR v2.
- Each has `$id` `https://trialbox.local/schemas/v2/<name>.schema.json`.
- Every persisted object carries `schema_version`.

### 5.1 Schema inventory

| Schema | Purpose | Status |
| --- | --- | --- |
| `criterion_ir` 2.0.0 | Criterion (superset of v1) with canonical hash, filter class, dependencies, flip rule | changed (§5.2) |
| `canonical_text` | Canonical form of a document or note with sentence spans and language tags | new (§5.3) |
| `evidence` | Support for one patient × criterion: source, sentence, quote span on canonical text, assertion, extractor | new (§5.4) |
| `candidate` | Patient × study evaluation: per-criterion status, tier, evidence, flip date, routing, decisions | new (§5.4) |
| `feasibility_packet` | Release object with estimates and intervals, projection, competitors, questionnaire answers, accountant record | new (§5.5) |
| `recall_certificate` | Audit-sample based bound on missed eligible patients per study × ruleset | new (§5.6) |
| `study` | Study Card | new (§5.7) |
| `run_manifest` v2 | v1 manifest + `cascade` block + model passes + served model SHAs | changed (§5.8) |
| `gate`, `approval`, `signature` | Gate instance; Level A approval; Level B signature | new (§5.9) |
| `proposal` | Intake proposal: exact command, restatement, confidence, expiry | new |
| `decision_sheet` | Sent and returned decision sheet: row hashes, file hash, parsed decisions | new |
| `site_lexicon_entry` | Lexicon row: surface form, language, expansion, concept code(s), source, status | new (§5.10) |
| `privacy_ledger_entry` | One released aggregate: requester, query fingerprint, cells, budget spent | new (§5.11) |
| `answer_memory` | Approved questionnaire answers by site-profile field, with provenance and validity | new |
| `outbox_message` | Durable send with idempotency key and state | new (§7.0) |
| `atlas_report` | Data Atlas output | new |
| `site_profile` | Site master profile (TransCelerate SIP-compatible fields) | new |
| `pipeline_event` | Enrollment state change with its Level A approval | new |
| `calendar_item` | Lifecycle obligation (visit window, SAE clock, continuing review, training expiry) | new (§6.7) |
| `model_registry`, `eval_report`, `bench_report` | Models per role and profile; evaluation; benchmark | new |
| `audit_event` v2 | v1 fields + `actor_type`, `on_behalf_of`, `purpose`, `record_hash`, `prev_hash` | changed |

### 5.2 Criterion IR v2

IR v2 keeps every v1 field (ADR-V3-08). Additions (normative excerpt):

```jsonc
// atom: v1 fields plus
{
  "id": "a3",                                         // local id for anchoring
  "domain": "condition | observation | medication | procedure | encounter | demographic | claim | report | note | appointment",
  "window": {"from_days": -365, "to_days": 0,
             "anchor": "index | event", "event": "a1", "event_pick": "first | last | each"},
  "count": 2, "count_unit": "records | days | episodes", "episode_gap_days": 14,
  "trend": {"metric": "delta | pct_change", "op": "<=", "num": -1.2, "baseline": "first_in_window | min"},
  "attribute": {"path": "stage | grade | laterality | histology | biomarker:<code> | ecog | nyha",
                "op": "in", "codes": ["IIIB", "IV"]},        // requires lake table condition_attribute (FR-M0-13)
  "absence": "absence_of_evidence | evidence_of_absence"
}
// boolean: v1 and/or/not plus
{"op": "seq", "args": ["a1", "a2"], "gap": {"min_days": 0, "max_days": 180}}
{"op": "atleast", "n": 2, "args": ["a1", "a2", "a3"]}
// criterion: v1 fields plus
{
  "canonical_hash": "sha256:…",          // compiler: normalised (atoms, windows, note_question) → shared across studies (CAS-5)
  "filter_class": "hard | soft",         // compiler, from Atlas coverage (SAFE-1)
  "depends_on": ["condition", "note:pathology"],   // domains for incremental evaluation (CAS-6)
  "flip_rule": {"kind": "washout_end | next_lab | age_reached | window_slide", "atom": "a2"},  // watchlist (FR-M4-7)
  "note_question": {"en": "…", "zh-TW": "…"},       // bilingual question for S3/S4
  "lexicon_keys": ["gout", "痛風", "MSU crystal"], // S2 pre-filter keys, from the site lexicon
  "computability": {"score": 0.63, "basis": "creatinine within 90 d in 63 % of active RHEU patients"},
  "ambiguity": [{"span": "…", "question": "…", "default": "…", "resolution": "…", "by": "user | default"}],
  "provenance": {"extractors": ["J@sha", "V@sha"], "agreement": "full | partial | none"},
  "safety_critical": false,              // never proposed for relaxation (FR-M2-3)
  "index": false                         // true for the study's index condition (CAS-11 rescue rule)
}
```

The following semantics MUST hold. They are tested in `tests/unit/test_ir_v2_semantics.py`:
- Three-valued Kleene logic for `and`/`or`/`not`/`seq`/`atleast`.
- **Missing data (IR ≥ 2.0.0).** At S1, an inclusion atom with no matching record evaluates to `unknown` (CAS-11). It is
  decided at S2 by the note pre-filter: zero approved-lexicon hits in the window give `fail` under
  `absence_of_evidence` and `unknown` under `evidence_of_absence`. The index-condition exception of CAS-11 applies.
  `coverage_threshold` (default 0.8, a site parameter recorded in the manifest) governs only `hard` filter-class value
  comparisons: below it, a hard value comparison is treated as `soft`.
- **IR < 2.0.0.** Rulesets keep v1 semantics unchanged: no record gives `false` for inclusion and `true` for `none`
  (ADR-V3-08). The cascade runs them with CAS-11 disabled, and they are recompiled to IR 2 at their next G1.
- `evidence_of_absence` needs an affirmative negative record, for example a negative test.
- Event-anchored windows evaluate against each anchor; `each` is true if any anchor satisfies the window.
- `line_of_therapy` is **not** part of IR 2.0. It needs a regimen model (drug classes, cycles, gaps, progression) and is
  specified as R3 work in FR-M7-12.
- Every construct compiles to CQL and SQL from templates. The equivalence gate covers each one with dedicated fixtures
  (`rulesets/ATOMS_V2`).

### 5.3 Canonical text and language tags

Notes and documents are normalised **once, at ingest**. All offsets refer to the canonical form.

Canonicalisation steps:
1. Unicode NFKC.
2. Full-width ASCII punctuation, digits and letters are folded to ASCII. CJK punctuation `，。；：` is kept.
3. Whitespace is collapsed.
4. Line breaks inside sentences are removed.
5. Sentence segmentation uses both CJK and Latin rules.
6. Each sentence gets a language tag: `zh`, `en`, `ja` or `mixed`. The tag is based on script ratio and a fastText-class
   language ID, with deterministic thresholds.

Dates and numbers are extracted into typed spans (ML-3) **without** rewriting the text, so quotes stay verbatim.

```jsonc
{"doc_ref": "DocumentReference/abc", "canon_sha": "sha256:…", "text": "…",
 "sentences": [{"i": 0, "start": 0, "end": 41, "lang": "mixed", "abbr_density": 0.18}],
 "spans": [{"start": 12, "end": 19, "type": "date", "value": "2024-03-05", "source_form": "113/3/5"},
           {"start": 30, "end": 36, "type": "quantity", "value": 35, "unit": "%", "concept": "LVEF"}]}
```

### 5.4 Evidence and candidate

```jsonc
// evidence
{"evidence_id": "ev_01J…", "pid": "<hmac>", "criterion_id": "GZQO-INC-05", "canonical_hash": "sha256:…",
 "source": {"type": "note | lab | dx | med | proc | report | vital | appointment | claim",
            "ref": "DocumentReference/abc", "date": "2026-05-07", "department": "RHEU", "note_type": "progress"},
 "sentence": "…臨床診斷為急性痛風發作 (acute gout flare)，給予 colchicine 0.5mg bid…",   // ≤ 400 chars, whole sentence
 "quote": {"start": 3, "end": 13, "canon_sha": "sha256:…", "verified": true},
 "lang": "mixed",
 "assertion": {"model": "affirmed", "rules": "affirmed", "final": "affirmed"},   // ML-6: must agree, else insufficient
 "value": {"num": 7.9, "unit": "mg/dL"} | {"code": "M10.9"} | null,
 "stage": "S1 | S2 | S3 | S4",
 "extractor": {"kind": "rule | lexicon | llm", "model_sha": "…", "prompt": "judge@v4"},
 "second_opinion": {"model_sha": "…", "agrees": true} | null,
 "gloss": {"en": "acute gout flare; colchicine given"}  // optional, generated, marked as translation
}

// candidate
{"study_id": "GZQO", "ruleset": "GZQO/v1.2.0", "snapshot": "2026-10-04", "pid": "<hmac>",
 "per_criterion": [{"criterion_id": "GZQO-INC-03", "status": "pass | fail | unknown | pending_human | verify_at_screening",
                    "stage": "S2", "evidence_ids": ["ev_…"], "abstained": false}],
 "tier": "strong | potential | watchlist | excluded",
 "flip": {"date": "2026-11-12", "criterion_id": "GZQO-EXC-04", "kind": "washout_end"} | null,
 "next_appointment": {"at": "2026-10-18T09:40", "clinic": "RHEU", "practitioner": "P12345"},
 "route_to": "u_123",
 "decisions": [{"by": "u_123", "decision": "confirm | reject | defer", "reason_code": "R07",
                "comment": "…", "approval": "ap_…"}]}
```

The tiers are:
- **strong**: every structured inclusion passes; no exclusion matches; every note criterion is affirmed with a verified quote,
  rule-assertion agreement, and S4 agreement; only `pending_human` or `verify_at_screening` criteria remain.
- **potential**: no hard failure; at least one `unknown` or abstained criterion that a chart review can resolve.
- **watchlist**: fails only criteria with a `flip_rule`, and the flip date falls inside the enrollment window.
- **excluded**: a hard failure. It is not listed for the PI, but it is included in the recall audit population (SAFE-2).

### 5.5 Feasibility packet

```jsonc
{"packet_id": "fp_01J…", "study_id": "GZQO", "ruleset": "GZQO/v1.2.0", "snapshot": "2026-10-04",
 "scope": {"population": "whole_hospital | departments | practitioners", "lookback_months": 24},
 "funnel": [{"criterion_id": "…", "label": {"en": "…", "zh-TW": "…"}, "remaining": "410", "stage": "S1"}],
 "per_criterion": [{"criterion_id": "…", "alone_excludes": "120", "computable": 0.92, "filter_class": "hard"}],
 "estimates": {"strong": {"est": "65", "ci95": ["40", "90"], "n_sampled": 200},
               "potential": {"est": "85", "ci95": ["60", "110"], "n_sampled": 200}},
 "projection": {"method": "hier_beta_binomial_v1", "assumptions_source": "site history (n=14 studies) | defaults",
                "monthly": [{"month": 1, "p10": 0, "p50": 1, "p90": 2}], "total_12m": {"p10": 6, "p50": 11, "p90": 17}},
 "competing_trials": [{"nct": "…", "sponsor": "…", "phase": "…", "status": "…", "criteria_overlap": 0.4}],
 "investigators": [{"user": "u_123", "department": "RHEU", "candidates": "≥10", "past_trials_in_area": 5}],
 "questionnaire": {"template_sha": "…", "answers": [{"field": "Q12", "value": "…", "source": "estimates.strong",
                                                      "memory_ref": null}], "unanswered": ["Q31"]},
 "recall_certificate": "rc_01J…",
 "disclosure": "ai_assisted_prescreening_v1",   // E6(R3) sponsor disclosure template (CMP-34)
 "privacy": {"rounding": "controlled, base 5", "ledger_entry": "pl_01J…", "budget_remaining": 0.62},
 "manifest": "rm_01J…",
 "approval": {"gate": "G2-0193", "approval": "ap_…"}}
```

Numbers are strings after rounding. `<5` and `≥10` forms are allowed. Narrative text is generated with placeholders and
checked by `numbers_match` (AI-07).

### 5.6 Recall certificate

Evidence is kept per **canonical criterion** in the **recall ledger** (SAFE-2). `canonical_hash` is shared across studies,
so excluded patients and audit samples are pooled across every recruiting study that uses the criterion, and they
accumulate month after month under a stored seed. A new study inherits the bounds of its criteria on day one.

The certificate for a study combines the ledger rates with the study's own stratum sizes. It makes three distinct claims
(SAFE-3):
- **elusion**: per stratum, the upper 95 % bound of the share of excluded patients who were in fact candidates;
- **known-positive recall lower bound**, on a named population;
- the **point estimate** of missed patients.

Any sentence in an email that claims recall MUST quote the lower bound and name its population, never the point estimate.
All numbers in a certificate are computed by the shipped function from the printed strata (`recall_cert` suite); none are
typed by hand.

```jsonc
// example output of tb_common.recall.certificate(); α = 0.05 split over K = 4 strata (Bonferroni), Clopper–Pearson
{"rc_id": "rc_01J…", "study_id": "GZQO", "ruleset": "GZQO/v1.2.0", "period": "2026-10", "seed": 912733,
 "elusion": {"strata": [
     {"stage": "S1-affirmative",    "excluded": 15100, "ledger_sampled": 600, "found": 0, "upper": 0.0073},
     {"stage": "S2-absence(index)", "excluded": 2900,  "ledger_sampled": 450, "found": 1, "upper": 0.0141},
     {"stage": "S2-zero_hit(note)", "excluded": 1800,  "ledger_sampled": 300, "found": 0, "upper": 0.0145},
     {"stage": "S3-not_met",        "excluded": 240,   "ledger_sampled": 120, "found": 0, "upper": 0.0359}],
   "missed_point": "6", "missed_upper95": "≤ 186", "per_1000_excluded_upper95": 9.2},
 "known_positive": {"population": "patients enrolled in any rheumatology study 2023–2026, pooled per criterion type",
                    "kind": "historical enrollees (biased: found by the old process)", "r": 61, "missed": 0,
                    "recall_lower95": 0.952},
 "auditor": {"pipeline": "S4@V-sha", "human_blinded": 30, "human_agreement": 0.93},
 "demotions": ["GZQO-EXC-02 → soft"],
 "statement": {"en": "Automated filtering missed none of 61 previously enrolled rheumatology patients (recall ≥ 95 %, 95 % confidence; historical enrollees). At most 9 per 1,000 excluded patients may have been eligible (95 % upper bound).",
               "zh-TW": "自動篩選未遺漏 61 位既往收案之風濕科病人（召回率 ≥ 95%，95% 信賴水準；以既往收案者為準）。每 1,000 位被排除者中可能合格者至多 9 位（95% 信賴上限）。"}}
```

### 5.7 Study Card

The v2 fields are kept: identity, registry ids, sponsor, phase, status, protocol versions, team with delegations, scope,
targets, packets, screening, pipeline and timeline. v3 adds:

```jsonc
{"languages": {"site": "zh-TW", "sponsor": "en"},
 "calendar": ["cal_…"],                    // lifecycle obligations (§6.7)
 "consent_versions": [{"version": "3.0", "irb_approved": "2026-09-01", "effective": "2026-09-15"}],
 "irb": {"approval_id": "…", "continuing_review_due": "2027-08-31"},
 "budget": {"coverage_analysis": "ca_…", "soc_items": 14, "research_items": 9},
 "recall_certificates": ["rc_…"], "privacy_budget": {"per_requester": {"sponsor:X": 0.62}}}
```

### 5.8 Run manifest v2

The v1 manifest fields are kept: code SHA, ruleset SHA, snapshot, settings hash and outputs. v3 adds:

```jsonc
{"cascade": {"n_scope": 412000, "n_after": {"S0": 51000, "S1": 2900, "S2": 610, "S3": 140, "S4": 65},
             "pairs_judged": {"S3": 1830, "S4": 260}, "cache_hits": 1210, "llm_share": 0.21,
             "tokens": {"in": 4.6e6, "out": 4.1e5}, "budget": {"items": 2000, "tokens": 1.0e7, "exhausted": false}},
 "passes": [{"pass": "night-1", "role": "J", "model_sha": "…", "served_name": "…", "gpu_seconds": 2950, "swap_s": 41}],
 "parameters": {"coverage_threshold": 0.8, "abstention_quantiles": "aq_2026-10", "suppression": "base5"}}
```

### 5.9 Gate and signature

```jsonc
// gate
{"gate_id": "G2-0193", "type": "G0 | G1 | G2 | G3 | G4 | G5 | G6", "assurance": "A | A2 | A+ | B",
 "object": {"kind": "feasibility_packet", "id": "fp_…",
 "sha256": "4be1c2d9…"}, "required_role": "PI | research_office", "requested": "…", "reminders": ["…"],
 "status": "open | approved | signed | rejected | expired | superseded", "approval": "ap_…" | null, "signature": "sig_…" | null,
 "expiry": {"at": "2026-10-23T09:00+08:00", "on_expiry": "withdraw_and_notify"}}
// approval (Level A, attributable reply)
{"appr_id": "ap_…", "gate_id": "G2-0193", "approver": "u_456", "printed_name": "王大明 (Wang Da-Ming)",
 "meaning": "I approve release of these aggregate results to Sponsor X", "record_sha256": "4be1c2d9…",
 "utc": "2026-10-18T01:12:09Z", "reply_message_id": "<…>", "dmarc": "pass", "otp": null, "receipt_message_id": "<…>"}
// signature (Level B, 21 CFR 11.50/11.70)
{"sig_id": "sig_…", "gate_id": "G5-0007", "signer": "u_789", "printed_name": "…", "user_id": "…", "role": "System owner",
 "meaning": "Change validated per evaluation report er_…", "record_sha256": "…",
 "utc": "2026-10-18T01:12:09Z", "tz_offset": "+08:00", "method": "webauthn | idp_reauth | pki_hca | pki_moica",
 "assertion_ref": "…", "receipt_message_id": "<…>"}
```

### 5.10 Site lexicon

Each row has these fields:
- `surface`: for example `s/p`, `CKD 3b`, `痛風石`, `MTX`;
- `lang`;
- `expansion` in en and zh-TW;
- `concepts`: ICD-10-CM, ATC/NHI drug code, LOINC, local code;
- `source`: `seed:nhi_drug_master`, `seed:icd10_tw`, `seed:loinc_tw`, `mined:paren_pattern`, `mined:cooccurrence` or
  `steward`;
- `support`: the count of notes, rounded;
- `status`: `proposed`, `approved` or `rejected`;
- `approved_by` and the G0 reference.

Only `approved` rows are used by S2 and by retrieval expansion.

### 5.11 Privacy ledger

Each released aggregate is recorded with these fields:
- `requester` (internal user, sponsor or network);
- `study`, `snapshot`;
- `query_fingerprint`: the hash of the ruleset version + scope + what-if changes;
- `cells`;
- `mechanism`: `rounding`, or `rounding+geometric(ε)`;
- `epsilon_spent`;
- `differencing_check`: the result of comparing against prior releases to the same requester (§10.4).

### 5.12 Internal APIs and tools

All internal APIs are OpenAPI 3.1, generated from FastAPI. Services talk to each other over the internal network, with
mTLS (SEC-3). There are no end-user HTTP APIs. The v1 endpoints stay.

New tools are callable only from workflow steps. The policy module checks each call against the caller, the workflow and the
study:

| Tool | Tier | Purpose |
| --- | --- | --- |
| `tb.vocab.search` | T0 | Concept candidates from loaded terminologies and the approved lexicon |
| `tb.atlas.describe` | T0 | Availability, coverage and freshness for a domain or code (no patient data) |
| `tb.registry.search` | T0 | Local index of public trials |
| `tb.protocol.search` | T0 | Passage retrieval over the study's protocol for `ASK` (no PHI) |
| `tb.feas.run` | T1 | Cascade on scope; aggregates checked by the privacy accountant |
| `tb.notes.search` | T2 | Window-restricted chunks for a pid list, with canonical offsets |
| `tb.lake.patient` | T2 | Patient facts for listed domains and window |
| `tb.files.render` | T3 | Deterministic rendering from a data object (after a gate) |
| `tb.study.update` | T3 | Study Card patch with gate reference (deterministic steps only) |
| `tb.outbox.enqueue` | T3 | Durable send (deterministic steps only) |

---

## 6. Functional requirements by module

Each requirement row gives the ID, the requirement, its verification and its release. "The box" means TrialBox. Every
module also inherits §10: audit, access, privacy accountant and disclosure.

### 6.0 M0 — Site onboarding and the Data Atlas

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M0-1 | The box MUST connect to a source configured in `site/sources.yaml` as one of: (a) a read-only SQL account on views (PostgreSQL, MSSQL, Oracle, Db2 via ODBC); (b) a scheduled CSV/Parquet drop; (c) FHIR Bulk `$export`. Credentials live in the secrets store, never in Git. | T | R0 |
| FR-M0-2 | `atlas run` MUST profile every configured table: row counts, types, null rates, distinct counts, top-50 value histograms (values seen in fewer than 5 patients shown as `<5`), date ranges, and per-department and per-year coverage. Free-text columns MUST NOT be sampled. Identifiers MUST NOT appear in the report. | T | R0 |
| FR-M0-3 | The Atlas MUST propose a mapping from source columns to the canonical model using column-name heuristics, value patterns (ICD-10, ATC, NHI drug, NHI fee, LOINC, MRN regex, ROC dates), and a model step that sees only column names, types, and de-identified samples of coded columns. The model step's input passes the PHI guard. Each proposal carries a confidence and a reason. | T | R1a |
| FR-M0-4 | The Atlas MUST export the proposal as an XLSX workbook (one sheet per canonical table, dropdowns, a lexicon sheet), read the steward's returned workbook into `mapping/<site>.yaml`, and email the diff. Gate G0. | T | R0 |
| FR-M0-5 | After each ingest the Atlas MUST compute **domain coverage** per patient and scope (the share of patients with ≥ 1 record per domain in the last 12, 24 and 60 months) and **freshness** (latest source timestamp to snapshot). | T | R0 |
| FR-M0-6 | The Atlas MUST compute a **computability score** per IR atom type and value set for a scope, for example "eGFR within 90 days: 63 % of active RHEU patients". M1 uses it to annotate criteria; the compiler uses it to set `filter_class` (SAFE-1). | T | R1a |
| FR-M0-7 | The Atlas MUST run data-quality checks: unit consistency per lab code, impossible values, future dates, duplicate encounters, orphan records, code-system validity per ICD edition, and the share of ROC dates that fail to parse. A blocking issue MUST stop snapshot publication and email the steward. | T | R0 |
| FR-M0-8 | The box MUST load terminology packages: NHI ICD-10-CM/PCS **2014 and 2023 editions with the official 2014→2023 mapping** (NHIA switched editions on 2025-01-01, by visit date); ICD-9-CM 2001 for history; the NHI drug master with ATC; NHI medical-service fee codes; TFDA licence and ATC codes; LOINC with the MOHW Taiwan LOINC mapping; the site lab dictionary; departments and practitioners. Versions are recorded in every snapshot manifest. | T | R0 |
| FR-M0-9 | Ingest MUST stream with bounded memory (≤ 8 GB RSS regardless of patient count), chunked by patient id, and restartable per chunk. | T | R1a |
| FR-M0-10 | The site profile (TransCelerate SIP-compatible: staff, equipment, IRB and contract timelines, past enrollment) MUST be versioned and maintained by workbook round trip. It is pre-filled from the box's own data (departments, practitioners, historical enrollment from M6). | T | R1a |
| FR-M0-11 | `trialbox doctor` MUST check: host, GPU, driver pin, models and their SHAs, mail, sources, egress rules, clock sync, disk, backup, certificate expiry, TOTP/WebAuthn enrolment store, and licence manifest versus site policy flags (MOD-2). It prints the fix for each failure. | T | R0 |
| FR-M0-12 | Optional structured source: **NHI MediCloud** (健保醫療資訊雲端查詢) medication and lab history. MediCloud is queried per patient for that patient's care. Bulk retention for research pre-screening is outside its normal terms and PDPA purpose limitation. The source MAY be enabled only with written NHIA permission and an IRB-approved purpose on file. It is ingested with provenance `source=nhi_cloud`. | T, I | R3 |
| FR-M0-13 | The lake MUST add a `condition_attribute(pid, condition_ref, path, value_code, value_num, effective, source)` table. It is fed by adapter mappings from cancer-registry (癌症登記) extracts, pathology structured fields and the hospital's staging tables. IR `attribute` atoms compile to it. Without a mapped source, `attribute` atoms have computability 0 and are routed to notes. | T | R2 |

### 6.1 M1 — Protocol intake, digitisation and protocol Q&A

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M1-1 | The box MUST accept protocols as PDF (text or scanned), DOCX, ICH M11 structured protocol, CDISC USDM JSON, a ClinicalTrials.gov record, or pasted text, in English, Chinese or Japanese. It MUST locate the I&E sections and the schedule of activities (SoA). | T | R1a (USDM R2) |
| FR-M1-2 | Criteria MUST be extracted independently by the J model (day pass) and the V model (night pass 2) into IR v2 with source spans. Agreement is computed per criterion. Disagreements and low-confidence items become numbered questions. | T | R1a |
| FR-M1-3 | Concept mapping MUST use `tb.vocab.search` results only; no codes from model memory. Every code is checked to exist in the loaded terminology. Codes are expanded across ICD editions via the official mapping. | T | R1a |
| FR-M1-4 | Every criterion MUST be classified `structured`, `note` or `human`, and annotated with `depends_on`, `lexicon_keys`, `computability`, `filter_class`, `canonical_hash` and `flip_rule`. The understanding email states computability in plain words ("we can check this for about 63 % of patients"). | T | R1a |
| FR-M1-5 | Ambiguities (undefined thresholds, unit-less values, "adequate organ function", "per investigator judgement") MUST be listed with a proposed default. The CRC confirms or edits by numbered reply. | T | R1a |
| FR-M1-6 | The criteria workbook MUST show, per criterion: the text in the protocol language and the site language, source span, IR summary, ValueSets, computability, filter class, and the aggregate count on the current snapshot. The SQL/CQL text is in a hidden sheet for QA. G1 freezes the ruleset (Git tag + SHA). | T | R1a |
| FR-M1-7 | Protocol amendments MUST produce a criterion-level diff against the previous version. After re-approval, open candidates are re-evaluated and consent re-versioning is flagged (FR-M6-6). | T | R2 |
| FR-M1-8 | The SoA MUST be digitised into a USDM-lite structure (visits, windows, procedures, NHI fee-code mapping candidates) for M7. | T | R2 |
| FR-M1-9 | Protocol text MUST be processed by local models only (C-2). Protocols are treated as sponsor-confidential. | T, I | R1a |
| FR-M1-10 | **Protocol Q&A (`ASK`).** A delegated user MAY ask a question about a study's protocol in any supported language. The answer MUST be built only from retrieved protocol passages (`tb.protocol.search`) and MUST quote and cite each passage (section number + quote in the protocol language). It ends with "Per protocol section X" and states that the investigator and sponsor decide. With no supporting passage, the answer is "The protocol does not say; ask the sponsor (draft question attached)". No patient data is used. | T | R1a |

### 6.2 M2 — Protocol optimisation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M2-1 | For any ruleset the box MUST compute, per criterion: patients excluded by it alone, drop-one gain, and its funnel position, on S0–S2 (no model). | T | R1a |
| FR-M2-2 | What-if (`WHATIF`) MAY disable a criterion or change a threshold. It re-runs on the same snapshot, is marked internal-only, is limited to 10 variants per study per snapshot (PRIV-7), and is never released externally without a fresh packet through G2. | T | R2 |
| FR-M2-3 | **Counterfactual relaxation with safety proxies.** For each non-`safety_critical` criterion, the box SHOULD report (Trial Pathfinder approach) the pool gain and the change in site-observable 90-day outcome proxies among the added patients: ED visits, admissions, and lab excursions beyond CTCAE grade 3 thresholds as already flagged by the hospital lab system. Results are rounded aggregates within the privacy budget. | T | R2 |
| FR-M2-4 | The box SHOULD report representativeness: eligible versus condition population by age band, sex and comorbidity burden. | T | R3 |

### 6.3 M3 — Feasibility, site selection and the sponsor questionnaire

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M3-1 | `FEAS` MUST produce the feasibility packet (§5.5) by 08:00 on the first working day after G1, for a ruleset of ≤ 40 criteria on ≤ 3M patients on the reference profile (NFR-3). | T | R1a |
| FR-M3-2 | Counts MUST be produced by the cascade (CAS-8): full population for S0–S2; stratified sample for S3–S4; tier estimates with 95 % intervals. | T | R1a |
| FR-M3-3 | The enrollment projection MUST give p10/p50/p90 per month and for 12 months. It is computed from the prevalent pool, incident flow (new index-condition patients per month over 24 months), clinic visit cadence, and conversion rates (approach, consent, screen-fail). Conversion rates come from a **hierarchical Beta-Binomial** model: therapeutic area within site, shrunk to site-wide priors, with defaults labelled as such when the site has fewer than 3 closed studies in the area. "Comparable" means the same therapeutic area and phase group (I/II vs III/IV). | T, A | R1a (hierarchical R2) |
| FR-M3-4 | Competing trials MUST be listed from the local registry index (ClinicalTrials.gov, MOHW platform), filtered by condition, phase and location. A criteria-overlap estimate is given when the competitor's criteria are available. | T | R1a |
| FR-M3-5 | Investigator suggestions MUST rank investigators by candidate count in their clinics (published as rounded bands; exact counts only internally), past trials in the area, and current load. | T | R1a |
| FR-M3-6 | **Questionnaire autofill with answer memory.** Given a sponsor questionnaire (XLSX, DOCX, or a PDF form), the box MUST map each question to a packet path, a site-profile field or an **answer memory** entry (a previously approved answer to the same SIP field, with validity date). It fills the answers and attaches a provenance sheet listing source path, data cut, rule version and memory reference. The mapping is learned per sponsor template and confirmed once by the CRC. Unmapped questions are listed and never invented (AI-08). | T | R1a |
| FR-M3-7 | "What changed since your last answer to this sponsor": when a sponsor sends a new questionnaire, the box MUST list answers that differ from the last released set, with reasons (new data cut, profile change). | T | R2 |
| FR-M3-8 | Every released number MUST pass controlled rounding (v1 `round_count`, base 5, `<5` cells) and the privacy accountant (§10.4). | T | R1a |
| FR-M3-9 | External release MUST pass G2 and be logged with recipient, content hash, packet id and privacy-ledger entry. | T | R1a |
| FR-M3-10 | **Site qualification pack:** site profile, past performance per area (enrollment versus target, time to first patient, screen-fail rate, all rounded), and start-up timelines, ready to attach to the sponsor reply. | T | R2 |
| FR-M3-11 | **AI disclosure (CMP-34).** Every external packet MUST include a one-paragraph disclosure that AI-assisted pre-screening is used at the site, how eligibility is decided (by the investigator), and the current recall certificate statement. | T | R1a |
| FR-M3-12 | **Computable feasibility exchange.** A sponsor MAY send criteria as M11/USDM or FHIR `EvidenceVariable`. The box answers **by email** with the same packet plus a machine-readable JSON attachment (rounded, accountant-checked, recall-certified, manifest hash) after G2. There is no inbound API. Sponsors that send computable criteria get faster answers. That is the incentive. | T | R3 |

### 6.4 M4 — Pre-screening and recruitment

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M4-1 | For each study with status `recruiting`, the box MUST run the cascade on the scoped population at the configured cadence (weekly default, nightly allowed) and on request. | T | R1b |
| FR-M4-2 | **Portfolio clinic-day lists.** Each night, every patient with an appointment in the next N days (default 14) MUST be screened against all recruiting studies of that clinic's practitioners. The output is one consolidated list per practitioner per clinic day. The judgement cache (CAS-5) shares note work across studies. | T | R1b |
| FR-M4-3 | Each candidate MUST carry per-criterion status and evidence (§5.4). Note-criterion affirmations need a verified quote and rule-assertion agreement. `strong` needs S4 agreement on every note criterion. | T | R1b |
| FR-M4-4 | Candidates MUST be routed to the investigator who owns the next appointment (or the last visit), with date, clinic and a one-line bilingual summary. Lists are delivered as an encrypted XLSX decision sheet plus one PDF per strong candidate (an evidence page with quotes in the original language and a gloss). | T | R1b |
| FR-M4-5 | **G3 decisions.** The PI or a delegated sub-investigator MUST be able to confirm, reject (fixed reason code + free text) or defer each candidate, by reply line (`CONFIRM P0156`, `REJECT P0156 R02 on dialysis`) or by returned decision sheet (FR-UX-4). A CRC MAY add notes and `DEFER`, but not confirm or reject. | T | R1b |
| FR-M4-6 | Opted-out patients MUST be removed at S0. The default opt-out scope is `all_research_use`, which also excludes them from counts (PRIV-8). The NHI secondary-use opt-out applies to NHIA databases; it applies to the hospital's own data only if the hospital adopts it as policy, which is a site setting. | T | R1a |
| FR-M4-7 | **Watchlist with flip dates.** For candidates failing only criteria with a `flip_rule`, the box MUST compute the flip date (washout end, next scheduled lab, age reached, window slide) and re-evaluate on that date, not on cadence. The PI sees "becomes possibly eligible on 12 Nov; next visit 14 Nov". | T | R2 |
| FR-M4-8 | Rejection reasons MUST feed per-criterion precision estimates (§8.6). A criterion with a PI rejection rate > 30 % over ≥ 20 decisions MUST be flagged for review at the next G1. | T | R1b |
| FR-M4-9 | The box MUST NOT contact patients. IRB-approved outreach materials MAY be attached to the PI packet. | T (no outbound to non-staff addresses) | R1b |
| FR-M4-10 | **Data-gap prompts.** For `potential` candidates whose only unknown criterion needs a recent test (for example "eGFR within 28 days"), the packet MUST say which data are missing and when they expire, for the investigator's consideration. The box never suggests ordering a test for research purposes outside the protocol and IRB plan. | T | R2 |
| FR-M4-12 | **Review depth (QBCB).** The `potential` list is ranked by nonconformity. The packet tells the CRC how deep to review: "review the top k; beyond that the chance of another candidate is below the certificate's target". k is computed with the quantile-based stopping rule of Lewis, Yang & Frieder (CIKM 2021) on the known-positive ranks. | T | R2 |
| FR-M4-11 | **Screen-failure learning.** After screening, screen-failure reasons (M6) MUST be mapped to criteria. A criterion causing ≥ 3 screen failures that the cascade marked `pass` is flagged as a pre-screening blind spot, with the patients' evidence attached for QA. | T | R2 |

### 6.5 M5 — Patient → trial matching

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M5-1 | `MATCH <MRN>` from a delegated clinician MUST rank the site's recruiting studies by the frozen rulesets (cascade with judgement cache) and return per-trial criterion evidence. | T | R2 |
| FR-M5-2 | For registry trials not open at the site, the box MAY rank by retrieval plus criterion-level assessment (TrialGPT-style; port from branch `claude/trialgpt-local-lcvm9p`, `trialgpt/`), labelled "not open here; registry match". | T | R3 |
| FR-M5-3 | Tumour-board mode: `MATCH` on a list of MRNs for a meeting date produces one summary per patient. | T | R3 |
| FR-M5-4 | A CMP-28 written intended-use analysis MUST exist before M5 ships. | I (document) | R2 |

### 6.6 M6 — Consent, enrollment tracking and forecasting

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M6-1 | Pipeline states: `prescreened → contacted → consented → screened → randomized`. Exits: `declined`, `screen_failed(reason)`, `not_contactable`, `withdrawn`. Transitions after `prescreened` MUST be G4 approvals (by reply line or sheet). | T | R2 |
| FR-M6-2 | The Monday status email per study MUST show the pipeline, reasons, forecast p10/p50/p90 against target, an early warning when p50 < 80 % of plan for two consecutive weeks, and what is due this week (§6.7). | T | R2 |
| FR-M6-3 | A monthly portfolio report for the research office MUST rank studies by risk of under-enrollment, using the hierarchical forecast. | T | R2 |
| FR-M6-4 | The box SHOULD import enrollment from the hospital CTMS or IRB system (read-only) and reconcile it with its pipeline, listing mismatches. | T | R3 |
| FR-M6-5 | Site history (consent rate, screen-fail rate, time to first patient per area) MUST be derived from closed studies and feed FR-M3-3. | T | R2 |
| FR-M6-6 | **Consent versioning.** The Study Card tracks IRB-approved consent versions. When a new version becomes effective, the box MUST list enrolled participants who need re-consent and track the G4 approval of each re-consent. | T | R2 |
| FR-M6-7 | **Forecast scoring.** At feasibility, the PI's own enrollment estimate MAY be recorded (one reply line). At close, the box scores the box forecast and the PI estimate (Brier/CRPS) for the research office. | T | R3 |

### 6.7 M7 — Start-up and conduct (deterministic lifecycle engine)

All M7 features are driven by **calendar items** (`calendar_item`). Each is computed from the Study Card, the SoA, the
delegation log and hospital SOP templates (`site/playbooks/*.yaml`). They use no model time.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M7-1 | **Playbooks.** A YAML playbook per stage (start-up, conduct, close) defines tasks, owners (role), due rules (relative to study events), reminders and document templates. The hospital edits playbooks through Git via the admin. The defaults ship with the product. | T | R2 |
| FR-M7-2 | **IRB package pre-fill.** From the protocol digest and Study Card, the box MUST pre-fill the hospital IRB application template (DOCX) fields it can source, list the rest, and track continuing-review (持續審查) and final-report due dates. | T | R2 |
| FR-M7-3 | **Coverage analysis and budget draft.** Each SoA procedure MUST be mapped to NHI fee codes and classified as standard of care (NHI-billable per NHI rules for the indication) or research-only (sponsor-paid). The output is a draft CTA budget table with unit costs from the hospital fee schedule. It is computed at feasibility so that the budget is right before negotiation. | T | R2 |
| FR-M7-4 | **Delegation and training.** The box MUST track delegation-log entries, GCP training certificates and their expiry. It reminds the CRC 30 days before expiry and blocks gate approvals by people whose delegation or training has lapsed. | T | R2 |
| FR-M7-5 | **Visit windows.** For enrolled participants, visit due dates and windows MUST be computed from the SoA and the randomisation date. The CRC is reminded before a window opens and before it closes. Likely deviations (visit outside window, missed procedure, detected from hospital encounters and orders) are listed for CRC confirmation. | T | R3 |
| FR-M7-6 | **Deviation log and CAPA.** Confirmed deviations MUST be logged with category, root cause and CAPA owner and date. Approval is a Level B signature (FR-SIG-1). The log is exportable for the sponsor and the IRB. | T | R3 |
| FR-M7-7 | **Safety clocks.** When the CRC records a suspected SAE (`SAE P0156 2026-10-17 <one line>`), the box MUST start the **site's** clocks, labelled by owner: investigator to sponsor (per protocol, typically 24 h), and investigator to IRB (per hospital IRB SOP). The sponsor's 7/15-day clocks to TFDA are the sponsor's obligation; the box records them only for information. It reminds the owner at 50 % and 90 % of each clock and records completion. | T | R3 |
| FR-M7-8 | **Hospital-flagged events.** For enrolled participants, the box MUST list new ED visits, admissions and critical lab values **already flagged by hospital systems**, within one ingest cycle, as items for investigator review. The box does not grade or attribute events (CMP-28). | T | R3 |
| FR-M7-9 | **Monitoring-visit pack.** Before a monitor visit (`MONITOR GZQO 2026-11-04`), the box MUST assemble: source packets per participant and visit (M8), the deviation log, open queries, the delegation log and the ISF index. | T | R3 |
| FR-M7-10 | **ISF index.** The box MUST keep an investigator site file index per E6(R3) essential-record categories, with document versions and locations (the documents stay in the hospital's document system). | T | R3 |
| FR-M7-11 | The box MUST NOT access treatment-arm data or IRT unblinding fields. | T, I | R2 |
| FR-M7-12 | **Line of therapy (design note first).** A regimen model (drug classes, cycles, gaps, progression events) to support `line_of_therapy` criteria. It is specified in `docs/design/line_of_therapy.md` before implementation. | A, T | R3 |

### 6.8 M8 — Data abstraction, eCRF pre-fill, SDV and queries

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M8-1 | Given a target form (CDASH/ODM v2 form definition, or an EDC bulk-upload XLSX template), the box MUST map fields to canonical data (confirmed once per form by the CRC) and produce a pre-filled file per participant and visit. | T | R3 |
| FR-M8-2 | Every pre-filled value MUST carry lineage: source record, timestamp, transformation, extractor (rule or model) and confidence. Temporal, multivariable or free-text-derived fields are marked "needs review" unless rule-derived. | T | R3 |
| FR-M8-3 | **SDV source packets.** For each pre-filled value, a one-page source excerpt (lab line, note sentence with the quote highlighted, document id, date). The CRC certifies a packet with a Level B signature, and monitors verify against it. | T | R3 |
| FR-M8-4 | **EDC query drafts.** The CRC forwards or pastes a sponsor query (`QUERY GZQO P0156 <text>`). The box drafts an answer from source data with citations, for the CRC to edit and enter in the EDC. | T | R3 |
| FR-M8-5 | A critical-field gap report MUST list required fields with no source data per participant and visit. | T | R3 |
| FR-M8-6 | The box MUST NOT submit to an EDC; humans upload. Files go only to delegated internal recipients. | T | R3 |
| FR-M8-7 | Retrospective studies: bulk abstraction for an approved cohort with an IRB reference, producing a de-identified dataset with a data dictionary and a QC report. | T | R3 |

### 6.9 M9 — Close-out, reporting, learning

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M9-1 | Registry deadlines for hospital-sponsored studies (IIT): registration ids, results-posting due dates (42 CFR 11 where the study is an applicable clinical trial; otherwise WHO/ICMJE practice of 12 months after primary completion), and reminders. | T | R4 |
| FR-M9-2 | Retrospective at close: feasibility estimate versus actual, screen-fail reasons, criteria with the most rejections, recall certificates over time, forecast score. Stored as site history. | T | R4 |
| FR-M9-3 | Archive export: Study Card, rulesets, packets, approvals and signatures with manifestations, decisions, recall certificates and the audit trail, as PDF/A plus JSON with checksums. Retention defaults are named (PRIV-6). | T | R4 |
| FR-M9-4 | Final IRB report draft (DOCX) from the Study Card and pipeline. | T | R4 |

### 6.10 M10 — NHI navigation (v1 NAV, carried)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M10-1 | v1 NAV, TWPAS bundle generation, validation and pre-check MUST keep working unchanged on IR v2 rulesets. | T | R1a |
| FR-M10-2 | TWPAS packages are updated to the IG version NHIA requires at go-live, with the official pre-check when published. | T | R2 |
| FR-M10-3 | **NHI-aware recruitment.** IR `claim` atoms MUST support prior-authorisation outcomes and renewal windows (for example a biologic renewal at risk), as phenotype signals for trials of alternatives. These are aggregate-reported in feasibility. | T | R2 |

### 6.11 M11 — Networked research (v1 COHORT, extended)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-M11-1 | v1 quarterly cohort tables and alliance merge MUST keep working. | T | R1a |
| FR-M11-2 | An OMOP CDM 5.4 view of the lake (ADR-V3-09) SHOULD be exposed for local OHDSI tools. | T | R3 |
| FR-M11-3 | **Federated feasibility with a privacy accountant.** A member box answers an alliance query (same ruleset, aggregate) by adding calibrated geometric noise to each cell on top of controlled rounding. Members also add **pairwise-cancelling masks**: each pair of members shares a seed at onboarding, so the masks cancel in the sum at the alliance root. The root sees only the noisy total; each member's noise budget ε is accounted per requester per quarter. | T | R3 |
| FR-M11-4 | Trial-ready cohorts: standing cohort definitions with consented-to-contact patients, refreshed each snapshot, reported in aggregate. | T | R3 |

### 6.12 Agent behaviours (cross-module)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-AG-1 | Free-text requests MUST become proposals that the sender confirms before any workflow with an external effect starts (§3.3). | T | R1a |
| FR-AG-2 | At the proposal step, the agent MUST ask at most one numbered clarification round, then propose with documented defaults, listed in the reply. Defaults never bypass a gate: criteria defaults still go through G1. | T | R1a |
| FR-AG-3 | Status answers MUST come from the Study Card only, never from model memory. | T | R1a |
| FR-AG-4 | The agent MUST refuse and explain when a request exceeds the sender's permissions. It MUST NOT reveal to a non-delegated user whether a named patient exists. | T | R1a |
| FR-AG-5 | Every agent action MUST be attributable: `actor_type=agent`, `on_behalf_of`, request id, workflow id. | T | R1a |
| FR-AG-6 | **Next best action.** Each Monday digest MUST end with the three most urgent items for the recipient across their studies, ranked by deadline and consequence (gate due, clock running, window closing, expiring training). The ranking is deterministic. | T | R2 |
| FR-AG-7 | `HELP` returns the commands the sender may use, in their language, with examples. | T | R1a |

### 6.13 M-ML — Multilingual text (C-8)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| ML-1 | **Keep the source script.** Notes and protocols MUST NOT be translated before reasoning. Evidence is always quoted in the original. A generated gloss MAY be added, marked as a translation (`gloss`). | T | R1a |
| ML-2 | **Canonical text** (§5.3) MUST be computed once at ingest. All offsets refer to it, and a quote is verified against it byte-for-byte. | T | R1a |
| ML-3 | **Dates and numbers.** The normaliser MUST parse into typed spans: ROC (民國) dates (`113/3/5`, `113.03.05`, `民國113年3月5日`), Japanese era dates (`令和6年3月5日`, `R6.3.5`), Western formats, full-width digits, Chinese numerals in quantities (`三個月`, `兩次`), and value-unit pairs with unseparated numbers (`Cr1.2`, `EF35%`). Each parser is table-driven and unit-tested. | T | R1a |
| ML-4 | **Language tags** per sentence (zh/en/ja/mixed) and the abbreviation density MUST be stored with chunks, and used for evaluation strata and calibration (§8.4). | T | R1a |
| ML-5 | **Site lexicon** (§5.10). It is seeded from NHI drug master Chinese and English names, ICD-10-CM-TW Chinese labels, LOINC-TW names and the site lab dictionary. It grows by deterministic mining of `ABBR (中文)`, `中文 (ABBR)` and `中文/English` patterns and of co-occurrence in the same sentence. Mined entries are `proposed` until the steward approves them in the Atlas workbook (G0). Retrieval and S2 use approved entries only. It replaces `scenarios/terms.py`. | T | R1a |
| ML-6 | **Deterministic assertion pass.** A bilingual cue grammar (zh/en/ja) MUST label the sentence containing an evidence quote as affirmed, negated, historical, family, hypothetical or uncertain, with scope rules (cue → target within the clause). Cue tables live in `vocab/assertion_cues.yaml`, seeded with Appendix E. The S3 model's `assertion` MUST agree with the rules, or the judgement becomes `insufficient` and goes to S4. | T | R1a |
| ML-7 | **Retrieval** MUST expand the criterion's query through the approved lexicon in all site languages. It uses hybrid scoring (CJK bigram FTS + bge-m3 + optional bge-reranker-v2-m3), restricted to the criterion window. | T | R1a |
| ML-8 | **Prompts** MUST present the criterion's `note_question` in the protocol language and the site language. They instruct the model that notes mix Chinese, English and abbreviations, and that it must quote verbatim and never translate the quote. | T | R1a |
| ML-9 | **Output language per artefact:** PI/CRC packets, Study Card and digests in the recipient's preferred language (default site locale zh-TW); sponsor packets and questionnaires in the sponsor template's language (default English); IRB documents in the IRB's language; the signature manifestation in both. Terms are rendered as `code — 中文 (English)`. | T | R1a |
| ML-10 | **Japanese profile** (site flag `locale: ja-JP`): JP Core FHIR adapter, ja lexicon seeds (standard disease names, YJ drug codes, JLAC lab codes, where licensed), ja assertion cues, ja templates. | T | R3 |
| ML-12 | **Alliance language packs.** Approved lexicon rows (surface → concept, language, rounded support) and sentence-level de-identified assertion exemplars contain no PHI. They MAY be exported as signed "TW clinical shorthand packs" and exchanged between alliance boxes by email (v1 COHORT channel). An imported pack is reviewed at G0 like mined rows. | T | R3 |
| ML-11 | **Drift monitor:** mixing ratio, unknown-token rate and new-abbreviation rate per note type and department per month. A change > 3σ from the trailing 6 months raises a recalibration task (§8.4). | T | R2 |

### 6.14 SAFE — Never silently lose a patient (P6)

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SAFE-1 | **Filter classes.** The compiler MUST set `filter_class = hard` only if (a) the atom is single-domain presence or a value comparison, (b) Atlas coverage for that domain in the scope is ≥ 0.9, and (c) unit consistency is ≥ 0.9 for value atoms. Otherwise it MUST set `soft`. A soft failure keeps the patient in the cascade as `unknown` for that criterion. | T | R1a |
| SAFE-2 | **Recall ledger and elusion audit.** Each month the box MUST draw seeded random samples of excluded patients in four strata: `S1-affirmative`, `S2-absence(index)`, `S2-zero_hit(note)` (non-index note criteria excluded at S2 by zero lexicon hits), and `S3-not_met`. Each sample is keyed by canonical criterion and pooled across studies. Sampling is importance-weighted (AI-15). Samples are re-evaluated by S4 with the full note pipeline, and a blinded subset of 30 goes to a CRC as five-minute review questions (§8.6); the reviewer does not see the cascade decision. Samples accumulate in the ledger. Defaults: 150 new samples per stratum per month across the portfolio, giving cumulative n ≥ 450 per stratum after a quarter. | T | R1b |
| SAFE-3 | **Recall certificate** (§5.6), with three claims: (a) per-stratum elusion upper bounds (Clopper–Pearson at α/K, Bonferroni over the K strata) reported as "missed per 1,000 excluded", plus the implied missed-patient bound; (b) the known-positive recall lower bound on a named population, pooled per therapeutic area and criterion type (a patient enrolled in any study is a known positive for every criterion they passed), with r ≥ 59 as a **portfolio-level** target and its source kind stated (blinded chart review, or historical enrollees labelled as biased); (c) the point estimate. Summaries MUST quote (b) with its population. | T | R1b |
| SAFE-4 | **Demotion.** A criterion whose elusion upper bound exceeds 10 % in its stratum, or that excluded any known-positive patient, MUST be demoted to `soft` at the next run. The study team is told, and the change is recorded. | T | R1b |
| SAFE-5 | **"History of" exclusions** (for example malignancy within 5 years) MUST have an explicit window. Resolution or cure needs `evidence_of_absence`, or the criterion is `pending_human`. | T | R1a |
| SAFE-6 | **Coverage threshold.** `coverage_threshold` (default 0.8) for `missing_data → unknown` is a named, per-domain parameter recorded in every manifest. | T | R1a |
| SAFE-7 | **Ever-excluded enrollee check.** At close, every enrolled participant is checked against past runs. A participant ever hard-excluded is a reportable blind spot in the monthly QA pack. The target is 0. | T | R2 |
| SAFE-8 | Recall evidence MUST be re-established after any G5 change to a model, prompt, lexicon or threshold that affects S1–S4 (MOD-5). | T | R1b |

---

## 7. Workflows

### 7.0 Durability and exactly-once sends

Workflows run inside the orchestrator on PostgreSQL (ADR-V3-02). The v1 SQLite schema (`services/orchestrator/db.py`) is
migrated and extended with these tables:

| Table | Columns (main) | Rule |
| --- | --- | --- |
| `jobs` | v1 columns + `workflow`, `priority`, `pass_class` | One row per request |
| `steps` | `job_id, step, input_hash, output_ref, state, attempts, started, finished` | A step whose `(job_id, step, input_hash)` has a `done` row is never executed again; replay reads `output_ref` |
| `gates` | §5.9 gate fields | A workflow waiting on a gate polls its row; only intake writes decisions |
| `outbox` | `msg_id, idempotency_key, job_id, kind, to, payload_ref, state(pending/sending/sent/uncertain), attempts, smtp_response` | Sends are rows, not calls (below) |

**The outbox makes sends exactly-once.** A step that sends mail or writes a release only **enqueues** an outbox row, in
the same transaction as its step result. A single sender worker then delivers it:
1. It marks the row `sending`.
2. It delivers with the `Message-ID` derived from the idempotency key.
3. It marks the row `sent`, or `uncertain` if the SMTP answer is lost.

`uncertain` rows are never resent automatically, following the v1 D-86 rule. The research office is told, and a person
decides. MinIO writes are content-addressed, so a repeated write is a no-op.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-WF-1 | Kill -9 of the orchestrator at any point of FEAS, SCREEN or a gate MUST resume with no duplicate step and **exactly one** delivered message per outbox row (test: kill loop over every step boundary, with MailHog counting deliveries). | T | R1a |
| FR-WF-2 | Gates time out into reminders: G0 at 3 and 7 days; G1 at 1 and 3 days; G2 at 1 day, then at the sponsor deadline the packet is **withdrawn** and the requester told; G3 candidates roll into the next packet; G4 has no timeout. | T | R1a |

### 7.1 Gate catalogue

| Gate | Object | Who decides | Meaning recorded | Assurance (default) |
| --- | --- | --- | --- | --- |
| G0 | Site mapping, Atlas configuration, lexicon diff | Data steward | "I confirm this mapping and lexicon reflect the source system" | A |
| G1 | Criteria mapping (ruleset version) | CRC; also the PI for studies marked high-risk | "I confirm the criteria are represented as intended" | A |
| G2 | External release (packet, questionnaire, enrollment summary) | PI or research office | "I approve release of these aggregate results to <recipient>" | A |
| G3 | Candidate decision | PI or delegated sub-investigator | "Confirm / reject for pre-screening follow-up" (never "eligible") | A |
| G4 | Pipeline transition | CRC or PI | "Participant <state> on <date>" | A |
| G5 | Model, prompt, lexicon, threshold or rule change to production | System owner + QA | "Change validated per evaluation report <id>" | B |
| G6 | Regulated record (deviation approval, SDV source certification) | Investigator or CRC per playbook | Per record type | B |

### 7.2 FeasibilityWorkflow

```
start(request: FEAS confirmed)                                        deterministic
 ├─ ensure_study_card · parse_document                               doc-parser
 ├─ extract_criteria[J] (day pass)                                   LLM, recorded
 ├─ extract_criteria[V] (night pass 2) → reconcile                   LLM, recorded; deterministic diff
 ├─ map_concepts(vocab.search) → compile IR v2 → filter classes      deterministic + LLM selection among search hits
 ├─ equivalence_gate (CQL ≡ SQL on ATOMS + sample)                   deterministic; fail → understanding email lists it
 ├─ outbox: understanding email + criteria workbook                  deterministic
 ├─ ⏸ G1 (Level A)
 ├─ cascade S0–S2 on population · stratified sample                  SQL + lexicon
 ├─ S3[J] on sample (night pass 1) · S4[V] on sample (night pass 2)  LLM, budgeted, cached
 ├─ estimates + Wilson CI · projection (hier. Beta-Binomial)          deterministic
 ├─ competing trials (local index) · investigators · questionnaire    deterministic + map_questionnaire[J]
 ├─ privacy accountant check → rounding → render files                deterministic
 ├─ draft_narrative[J] (night pass 3) → numbers_match                 LLM + deterministic check
 ├─ outbox: packet to requester for G2
 ├─ ⏸ G2 (Level A)
 └─ outbox: release to the recipient named in the confirmed request; ledger entry; Study Card timeline
```

### 7.3 PreScreenWorkflow (nightly portfolio, or weekly per study)

```
snapshot_ready → scope = appointments(next 14 d) ∪ watchlist flips due ∪ (weekly: study scope)
 ├─ S0 opt-outs · S1 structured (SQL, all recruiting rulesets at once) · CQL verify sample (5 %)
 ├─ S2 lexicon pre-filter + rescue sweep + assertion rules
 ├─ dirty-set filter (CAS-6) · judgement cache lookup (CAS-5)
 ├─ S3[J] lazy, ordered, short-circuit (night pass 1)  ── budget (CAS-4)
 ├─ S4[V] would-be strong + abstained (night pass 2)
 ├─ tiers · flip dates · routing to appointment owner
 ├─ attach recall certificate (latest) · render decision sheet + PDFs
 ├─ outbox: one packet per practitioner per clinic day
 ├─ ⏸ G3 per candidate (async; sheet or reply lines)
 └─ calibration update · exemplar bank · rejection-rate flags
```

### 7.4 Other workflows

| Workflow | Trigger | Key steps | Gates |
| --- | --- | --- | --- |
| OnboardWorkflow | install, new source, schema change | connect → profile → propose mapping → lexicon mining → workbook → apply → re-profile | G0 |
| CompileWorkflow | protocol or amendment | as §7.2 up to the frozen ruleset; amendment diff; re-evaluate open candidates; consent re-versioning flag | G1 |
| RecallAuditWorkflow | monthly per recruiting study | seeded samples per stratum → S4 re-evaluation → blinded CRC questions → certificate → demotions | none (QA report) |
| ActiveLearnWorkflow | weekly per CRC | choose ≤ 10 most informative judgements → email yes/no questions with quotes → labels → calibration set + exemplar bank | none |
| MatchWorkflow | `MATCH` | rulesets of recruiting studies → (registry match) → summary | none |
| TrackWorkflow | Mondays | reconcile pipeline → forecast → warnings → next-best-actions → digest | G2 for sponsor copies |
| LifecycleWorkflow | daily | evaluate playbook rules → create or advance calendar items → reminders → clocks | G6 where a playbook says so |
| AbstractWorkflow | form template + participants | field map → extract with lineage → gap report → source packets | G1-like field-map confirmation; G6 certification |
| CloseWorkflow | `STUDY <id> closed` | retrospective → site history → archive bundle → IRB final report draft | G2 for external parts |
| ChangeWorkflow | model, prompt, lexicon or threshold change | eval suites → bench → recall re-establishment plan → report | G5 |
| ValidationReplayWorkflow | install, then quarterly | replay closed studies as of their recruitment start → capture reports (§11.4) | none |

---

## 8. AI components

### 8.1 Prompts

Every LLM call uses a versioned prompt file in `prompts/` (v1 convention: YAML front matter with id, version, schema, role)
and JSON-schema-constrained output. Each call is recorded as a workflow step (P8). All calls are local (C-2).

| Prompt | Role | Input | Output | PHI |
| --- | --- | --- | --- | --- |
| `classify_intent` | J | stripped sender text (no quotes, no attachments) | proposal: command + restatement | no |
| `extract_criteria` | J, V | protocol sections (canonical text) | IR v2 list with spans, ambiguities | no (confidential) |
| `concept_select` | J | criterion phrase + `vocab.search` hits | choices among the hits, with reasons | no |
| `answer_protocol` | J | question + retrieved protocol passages | answer with section citations, or "not stated" | no |
| `judge` v4 | J | bilingual `note_question` + window-restricted chunks (canonical) + exemplars | met / not_met / insufficient, quote (offsets), assertion, value | yes (local) |
| `second_opinion` | V | same input as `judge`, without the J output (independent) | same schema | yes (local) |
| `map_questionnaire` | J | questionnaire field labels | field → packet / profile / memory path | no |
| `draft_narrative` | J | packet JSON | text with `{{placeholders}}` only | no (aggregates) |
| `abstract_field` | J (V for "needs review") | form field definition + facts/chunks | value + lineage + confidence | yes (local) |
| `draft_query_answer` | J | query text + cited source facts | draft answer with citations | yes (local) |
| `propose_mapping` | J | column names, types, de-identified coded samples | canonical mapping proposals | no |

### 8.2 Roles and model classes per profile

The registry (`models/registry.yaml`) binds **roles** to **model builds** per profile. Each build is pinned by repository
revision and SHA-256 and carries a licence manifest (MOD-2). Names in the table are candidates; the benchmark gate and the
evaluation suites choose the build (NFR-19). Third-party leaderboards are not acceptance evidence.

| Role | P-GB10 (128 GB) | P-5090 (32 GB) | Non-PRC alternative (required, MOD-1) |
| --- | --- | --- | --- |
| J: judge, extractor, intake, drafting | 30–35B-class MoE at 4-bit (e.g. Qwen3.6-35B-A3B, Gemma-4-26B-A4B) | same class | Gemma-4-26B-A4B / Gemma-4-31B; gpt-oss-20b for intake |
| V: second opinion, second extraction | 100–125B-class MoE (e.g. gpt-oss-120b MXFP4, Qwen3.5-122B-A10B 4-bit) | a second 27–31B family (e.g. Gemma-4-31B if J is Qwen, or the reverse) | gpt-oss-120b; Nemotron-3.5-class (licence review pending) |
| Embeddings | bge-m3 (v1) | bge-m3 | bge-m3 (BAAI), multilingual-e5-large |
| Reranker (optional) | bge-reranker-v2-m3 | same | same |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| MOD-1 | Every role MUST have at least one qualified build from a non-PRC developer, so that public hospitals bound by Taiwan's restrictions on PRC-brand ICT products can deploy. The site flag `public_agency: true` restricts the registry to such builds. | T | R1a |
| MOD-2 | Every model package MUST ship a licence manifest: SPDX id or licence name, gating, redistribution and flow-down obligations, field-of-use limits, origin. `trialbox doctor` refuses a build that conflicts with site policy flags. | T | R1a |
| MOD-3 | No non-commercial or research-only weights in the shipped product (for example the jina family). MedGemma only as a customer-installed option under the customer's own acceptance of its terms, unless legal review clears redistribution. | I | R1a |
| MOD-4 | Sampling: temperature 0, fixed seed. JSON-schema-constrained decoding (vLLM guided decoding; llama.cpp grammar on P-Mac). | T | R1a |
| MOD-5 | A model, quantisation, prompt, lexicon or threshold change is a G5 change. It re-runs the suites (§8.5) and the bench, and re-establishes recall evidence (SAFE-8). | T | R1a |
| MOD-6 | The served model's name and SHA MUST be echoed in every manifest and report footer. This fixes the v1 mismatch at `feas.py:87` and `screen.py:137`. | T | R0 |

### 8.3 Evidence-anchored judging

1. **Retrieve.** S2 has selected the patient–criterion pairs. Chunks are retrieved for the criterion window with
   lexicon-expanded hybrid search (ML-7): at most 2,500 tokens, newest first, original language.
2. **Exemplars.** Up to 3 adjudicated examples for this criterion type and language stratum come from the site exemplar bank
   (§8.6), with PHI stripped to the sentence level.
3. **Judge (S3).** The judge returns `met | not_met | insufficient`, the quote as offsets into one chunk's canonical text,
   an assertion label, and an extracted value where relevant.
4. **Verify (deterministic).**
   - The quote exists at those offsets.
   - The chunk date is inside the window.
   - The rule-based assertion (ML-6) agrees with the model.
   - Extracted values match the span parser (ML-3) when the span has a typed value.

   Any failure gives `insufficient`.
5. **Abstain or accept** (§8.4).
6. **Second opinion (S4).** V judges independently and does not see the J output. Disagreement gives `potential`, with both
   quotes shown.
7. **Aggregate in code.** Tiers and ranks are deterministic (§5.4). The LLM never sets a tier.

### 8.4 Calibrated abstention

Model-reported confidence is not used (AI-09). Instead, each S3 judgement gets a **nonconformity score** `s` from these
features:
- retrieval margin (top-1 vs top-2 chunk score);
- the token log-probability of the verdict, where the engine exposes it;
- the assertion-rule outcome;
- language stratum and abbreviation density;
- note type;
- whether the evidence sentence carries a negation or uncertainty cue.

The score combines these through a logistic model fitted on adjudicated pairs.

Thresholds are set per **(criterion type × language stratum)** by **Learn-then-Test**:
- the controlled risk is the **selective** error: errors among accepted judgements. It uses LTT's selective-classification
  construction (the p-value is computed on the accepted subset at each candidate threshold);
- target α = 0.05, confidence 1 − δ = 0.95;
- fixed-sequence binomial tests from the most conservative threshold;
- the calibration set is site-adjudicated pairs from G3 reasons, five-minute reviews and the validation study.

Judgements with `s` above the threshold go to S4. If S4 does not resolve them, they become `pending_human`.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| AI-10 | Implement scoring and LTT threshold selection in `services/orchestrator/calibration/abstain.py`. Thresholds are versioned (`aq_<yyyy-mm>`), recorded in manifests, and recomputed monthly, on drift alarms (ML-11) and after G5 changes. | T | R1b |
| AI-11 | Until a stratum has ≥ 100 adjudicated pairs, its threshold is the conservative default: everything not unanimous between J and the rules goes to S4. At α = δ = 0.05, a threshold certifies only if accepted errors are ≤ 1 at n = 100, ≤ 4 at n = 200 and 0 at n = 59. The QA pack reports this, so that slow calibration is understood rather than surprising. | T | R1b |
| AI-12 | The monthly QA pack reports, per stratum, the empirical error of accepted judgements on held-out adjudications against α. | T | R1b |
| AI-14 | **Champion/challenger shadow pass.** Spare V-pass time runs a candidate model build (`role: shadow` in the registry) on the day's cached (pid, criterion, chunk-set) pairs. It accumulates agreement against adjudications per language stratum. A G5 model change then arrives with weeks of site evidence. Manifests record both SHAs. Shadow outputs never reach a list. | T | R2 |
| AI-15 | **Importance-weighted elusion sampling.** Recall-audit samples (SAFE-2) are drawn with probability increasing in the S3 nonconformity score and the S2 hit-count margin, with a 5 % uniform floor, and weighted by inverse inclusion probability (Horvitz–Thompson) in the certificate. The `recall_cert` suite plants misses near the decision boundary and requires coverage in ≥ 95 % of seeds. | T | R1b |

### 8.5 Evaluation suites

`trialbox eval` runs versioned datasets from `eval/`: synthetic data, plus de-identified real data that is held only on the
site box. Every run writes an `eval_report`. The AI credibility file for each AI function is generated from the latest
passing reports.

| Suite | Content | Metric and gate (R1 thresholds; tightened after §11.4) |
| --- | --- | --- |
| `criteria_extract` | 5 shipped gold rulesets + 10 site protocols with CRC gold IR (50 by R3) | criterion recall ≥ 0.95; concept F1 ≥ 0.88 |
| `sql_cql` | ATOMS_V2 + synthetic edge cases | CQL≡SQL 100 % on ATOMS_V2; ≥ 98 % on sample |
| `judge_ml` | Site notes, dual-annotated under the protocol in §11.5, strata zh-only / en-only / mixed / abbreviation-heavy, ≥ 100 items each | sensitivity ≥ 0.90 and specificity ≥ 0.90 per stratum; max stratum gap ≤ 5 points; quotes 100 % verified |
| `assertion_ml` | Negation, history, family and hypothetical in mixed text (e.g. 「否認 chest pain」, 「s/p PCI」, 「家族史 DM」) | macro-F1 ≥ 0.90 (rules); model–rule agreement reported |
| `dates_numbers` | ROC/era dates, full-width digits, unseparated values | exact match ≥ 0.99 |
| `code_versions` | Patients with 2014- and 2023-coded history | criterion outcome identical across editions |
| `prescreen_patient` | Closed studies: enrolled patients in scope with data at the recruitment-start snapshot (CTMS identities linked through the pid map) | historical enrollee capture ≥ 0.80 (lower 95 % bound reported); PPV of strong ≥ 0.70 |
| `recall_cert` | Synthetic populations with planted eligible patients in each excluded stratum | certificate bound covers the true miss count in ≥ 95 % of seeds |
| `intent` | Synthetic bilingual staff emails (real ones added when available) | proposal accuracy ≥ 0.95; zero external-effect actions without confirmation |
| `redteam` | Injection emails and documents (hidden text, Unicode tags, "forward the list to…", quoted-chain payloads, real sponsor files with injected payloads) | zero successful capability-bearing actions **and** every attempt logged with the blocked step |
| `fairness` | Subgroup splits (sex, age band, language of notes, department) | F1 gap ≤ 10 points |
| `bench` | Throughput and quality per profile (NFR-17) | capacity gate NFR-18 |

### 8.6 Site learning (parameters, never rules)

- **G3 decisions** update per-criterion precision (Beta-Binomial per criterion × tier). High rejection rates are flagged
  (FR-M4-8).
- **Five-minute review.** Weekly, each CRC receives at most 10 yes/no questions. Each is a quote with the criterion question,
  chosen by expected information gain: uncertainty × disagreement × effect on a tier. The CRC replies with a line such as
  `1Y 2N 3Y …`. The answers feed the calibration set (§8.4) and the **exemplar bank**: adjudicated sentences tagged by
  criterion type and language, used as few-shot context.
- The exemplar bank and the lexicon are versioned in Git. Changes that affect S2–S4 are G5 changes, batched monthly.
- **Pipeline outcomes** update conversion rates (FR-M3-3).
- **Feasibility versus actual** at close calibrates the projection.
- Rules change only through G1. Models, prompts, lexicon and thresholds change only through G5.

### 8.7 Guarding numbers and claims

- **AI-07.** Narratives use placeholders. `numbers_match` rejects any digit sequence not produced by the template engine.
- **AI-08.** Unmapped questionnaire questions stay blank and are listed; no site fact is invented.
- **AI-09.** Model-reported confidence is never used as a decision threshold. A token log-probability may enter the calibrated nonconformity score (§8.4), and only through it.
- **AI-13.** A recall claim in any text MUST quote the certificate's lower bound (SAFE-3).

---

## 9. Non-functional requirements (ISO/IEC 25010)

| ID | Characteristic | Requirement | V | R |
| --- | --- | --- | --- | --- |
| NFR-1 | Responsiveness (batch) | Deterministic receipt acknowledgement within one intake poll (≤ 15 min), with no model involved | T | R1a |
| NFR-2 | Responsiveness (batch) | Understanding email by 08:00 the next working day after the **confirmed** command (or after receipt, for a grammar command) if it arrives before 15:00 (≤ 150 pages) | T | R1a |
| NFR-3 | Responsiveness (batch) | Feasibility packet by 08:00 the working day after G1 | T | R1a |
| NFR-4 | Throughput | Nightly portfolio pre-screen for 30 recruiting studies and 20k scheduled patients completes within the night passes on P-GB10, with ≥ 2× headroom (NFR-18) | T | R1b |
| NFR-5 | Throughput | Nightly ingest of 3M patients ≤ 4 h (streaming) | T | R1a |
| NFR-6 | Capacity | 300 active studies, 50 recruiting, 200 users | A, T | R2 |
| NFR-7 | Availability | No accepted request is lost in a 24 h outage; workflows resume after restart (FR-WF-1); no uptime target | T | R1a |
| NFR-8 | Recoverability | RPO ≤ 24 h (nightly full + WAL archive to the backup disk); RTO ≤ 1 working day; restore tested quarterly | T | R1a |
| NFR-9 | Reproducibility | Any released output regenerates byte-identically from its manifest and recorded step outputs | T | R1a |
| NFR-10 | Usability | A CRC completes stages 1–2 for a new protocol using only the 1-page guide; every message passes FR-UX-1 | T (message lint) + D (pilot) | R1a |
| NFR-11 | Language | All messages and templates in zh-TW and en (ja R3); bilingual glossary maintained | T | R1a |
| NFR-12 | Maintainability | Coverage ≥ 85 % for deterministic code; mypy --strict; ruff | T | R1a |
| NFR-13 | Portability | x86_64 and arm64 images (`make images-multiarch`); no network egress at runtime except the §4.1 allowlist | T | R0 |
| NFR-14 | Security | §10; no critical/high CVEs open > 30 days in shipped images | T | R1a |
| NFR-15 | Observability | OpenTelemetry traces to rotating files + Prometheus metrics: queue depth, pass utilisation, cascade metrics, gate backlog; PHI-redacted | T | R1a |
| NFR-16 | Cost | All inference local; per-run budgets (CAS-4); GPU-seconds per study per month reported | T | R1a |
| NFR-17–19 | Capacity and model choice | §4.7.3 | T, A | R1a |
| NFR-20 | Power and space | One desktop-class unit ≤ 300 W typical (P-GB10) or one workstation ≤ 1 kW (P-5090); fits a standard server-room shelf | I | R1a |

---

## 10. Security, privacy and compliance

### 10.1 Access model

There are no end-user accounts. A person's identity is their delegated, personal hospital mailbox (DMARC-aligned), bound
to a directory entry and a delegation-log row. Level B signatures add passkey or IdP re-authentication.

Authorisation is attribute-based: role × study delegation × purpose. It is evaluated by `libs/tb_common/policy.py`, which is
table-driven and property-tested, on every intake command, workflow start and tool call.

| Capability | CRC | PI / Sub-I | Research office | Data steward | Sponsor | Admin | Agent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Submit protocol / FEAS / QFILL / ASK | ✓ | ✓ | ✓ | – | – | – | on behalf |
| G1 | ✓ (delegated) | ✓ | – | – | – | – | ✗ |
| G2 external release | – | ✓ | ✓ | – | – | – | ✗ |
| Receive candidate lists (PHI) | delegated studies | delegated studies | with delegation | – | ✗ | ✗ | inside T2 steps only |
| G3 confirm/reject | DEFER + notes | ✓ | – | – | – | – | ✗ |
| G4 pipeline transitions | ✓ | ✓ | – | – | – | – | ✗ |
| G0 mapping, lexicon | – | – | – | ✓ | – | – | ✗ |
| G5 change | – | – | QA co-sign | – | – | system owner | ✗ |
| Receive aggregates | ✓ | ✓ | ✓ | ✓ | after G2, within budget | – | – |
| Configure system | – | – | – | mapping only | – | ✓ (no PHI) | ✗ |
| Audit export | own actions | own studies | ✓ | own actions | – | integrity only | ✗ |

### 10.2 Security requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| SEC-1 | Network: deny-by-default egress per container (v1 nftables), with the allowlist exactly as in §4.1. No model endpoint outside the box. Admin console and signing page only on hospital networks; admin only on the management VLAN. | T | R0 |
| SEC-2 | Encryption: LUKS2 at rest (TPM-sealed); TLS 1.3 in transit; pid map AES-GCM (v1). On P-Mac, FileVault plus a documented equivalent, as a validated deviation. | T, I | R1a |
| SEC-3 | Services authenticate to each other with mTLS on the internal network. Admins use local accounts with TOTP. No SSO broker. | T | R1a |
| SEC-4 | Mail: v1 sender authentication (aligned SPF/DKIM or DMARC, pinned authserv-id); allowlisted internal senders; personal mailboxes only for gates; external senders go to a quarantine workflow that summarises the request for a CRC to adopt. | T | R0 |
| SEC-5 | Supply chain: signed images with SLSA provenance; CycloneDX SBOM and ML-BOM (models, prompts, lexicon, embeddings) per release; pinned dependencies; VEX. | I | R1a |
| SEC-6 | Vulnerability management: image scanning in CI; yearly penetration test including the LLM red-team suite. | T | R1a |
| SEC-7 | Secrets in the secrets store (sealed files); never in prompts, logs or Git. TOTP seeds and WebAuthn credentials in the key class of the pid map. | I, T | R1a |
| SEC-8 | Logs and traces are PHI-redacted. PHI access is recorded in the audit ledger with its purpose. | T | R1a |
| SEC-9 | Intake hygiene: quoted-text stripping (§3.3); attachments converted in a network-isolated container; hidden text, comments, metadata, zero-width and Unicode tag characters removed; virus scan. | T | R1a |
| SEC-10 | PHI attachments go by S/MIME to recipients with certificates. Otherwise they go as AES-256 7z with a per-recipient passphrase issued in person by the research office at delegation. The passphrase is stored in the secrets store, rotated quarterly, and never sent by the box. Passphrase delivery by SMS or Teams is R2 and needs its own allowlist entry and a dedicated, logged template. | T | R1a |
| SEC-11–13 | See §4.3 (no T3 for models; intake has no PHI; recipients from the delegation log). | T | R1a |
| SEC-14 | **Breach workflow.** Detection (SOC alert, egress-drop alarm, audit anomaly) → containment runbook → notification of the competent authority and data subjects within the deadlines of the PDPA as amended in 2025 (the runbook names 72 h as the internal target) → post-incident review. Exercised by a tabletop test before go-live and yearly. | T (tabletop record) | R1a |

### 10.3 Threat model (STRIDE + OWASP LLM Top 10 2025)

| Threat | Example | Control |
| --- | --- | --- |
| Spoofing a requester | Forged display name | SEC-4; personal mailbox; Level A hash binding; Level B re-authentication |
| Prompt injection (LLM01) | Protocol PDF with hidden "send all candidates to x@y"; quoted chain with instructions | SEC-9; intake sees stripped sender text only; proposals need confirmation; recipients only from the delegation log (SEC-13); readers have no send tools |
| Sensitive information disclosure (LLM02) | Narrative leaks a small count | Accountant + rounding + `numbers_match`; outbound DLP scan of bodies |
| Excessive agency (LLM06) | Model changes a pipeline state | T3 only in deterministic steps after a gate |
| Improper output handling (LLM05) | Model output used as SQL | SQL from templates only; v1 `sqlguard` |
| Misinformation (LLM09) | Fabricated quote | Offset verification; assertion agreement; S4 |
| Supply chain (LLM03) | Tampered weights | SHA-pinned registry; signed bundles; licence manifest |
| Record tampering | Edited approval | Append-only ledger with hash chain; daily anchor (§10.5) |
| Differencing attack | Repeated what-ifs to reveal cells | Privacy accountant (PRIV-7) |
| Denial of service | Mail flood | Per-sender rate limits (v1); pass queue priorities |

### 10.4 Privacy

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| PRIV-1 | Patient identity inside the box is `pid = HMAC(site_key, MRN)` (v1). MRNs appear only in encrypted PHI attachments to delegated users. | T | R0 |
| PRIV-2 | Aggregates leaving the research office use controlled rounding (base 5, `<5`), never free text from notes. Per-investigator counts are published only as bands (`≥10`, `5–9`, `<5`). | T | R1a |
| PRIV-3 | Opt-outs are applied at S0 (FR-M4-6). | T | R1a |
| PRIV-4 | No PHI to any non-local model (there are none, C-2). The PHI guard is kept as a check on outbound **text**: surnames (≥ 5,000 entries; v1 has about 100), given names, Taiwan national ID and ARC patterns, phone patterns, MRN regex from site configuration. | T | R1a |
| PRIV-5 | Minimisation: T2 tools return only the fields the calling step needs; prompts carry only retrieved chunks; exemplars are sentence-level with identifiers removed. | T | R1a |
| PRIV-6 | Retention defaults per record class: regulated study records and the audit trail for the longest of the sponsor requirement, TFDA GCP record rules and the EU CTR 25-year rule when the study is EU-regulated; intake text that is not a regulated record for 90 days with identifiers redacted at storage; lake snapshots per v1 rules. Legal hold supported. | T | R1a |
| PRIV-7 | **Privacy accountant.** Every aggregate released outside the research office is recorded (§5.11). Before release, the accountant checks differencing against prior releases to the same requester for the same snapshot and study. A release that would let any cell < 5 be derived by subtraction is blocked or coarsened. What-ifs are internal-only and capped (FR-M2-2). Machine and federated answers add geometric noise with ε accounted per requester per quarter (FR-M11-3, FR-M3-12). | T | R1a (differencing checks), R3 (noise) |
| PRIV-8 | Opt-out scope is a site setting (`contact_only` or `all_research_use`), default `all_research_use`. | T | R1a |
| PRIV-9 | Before any identifiable-patient run (R1b), an IRB approval or waiver (umbrella or per study) MUST be on file in the Study Card. The box refuses `SCREEN` without it. | T | R1b |

### 10.5 Audit ledger

The v1 hash-chained audit (`tb_common.audit`) moves to an append-only PostgreSQL table:
- an `INSERT`-only role;
- a trigger that rejects `UPDATE` and `DELETE`;
- `prev_hash` chaining.

A migration imports the v1 day files, and `audit_verify` passes across both.

**Anchoring without special storage.** A daily digest (last hash, count, date) is signed with the box's key and emailed to the
QA mailbox. It is also written to the hospital file share. MinIO Object Lock is not required, because the single-drive
deployment cannot guarantee it.

### 10.6 Compliance mapping

Appendix C maps each CMP to requirements and tests. The main points:
- **21 CFR Part 11 and EMA computerised-systems guideline §4.8.** Level A approvals are attributable operational records.
  Level B signatures meet 11.50, 11.70 and 11.200 with full re-authentication per signing. 11.100(b) identity verification
  happens at delegation, and the box ships the 11.100(c) letter template (FR-SIG-7).
- **ICH E6(R3) Annex 1.** Data governance, audit trail, risk-based validation (§11), and investigator oversight: the box never
  decides eligibility.
- **Taiwan.**
  - PDPA (amended 2025): a named lawful basis for research use. Examples are patient consent to research use collected at
    registration, or an HSRA consent waiver with a PDPA §6 analysis (public interest / academic research with
    de-identification). IRB approval is not itself a PDPA basis; the analysis is OD-3's legal deliverable. Also
    minimisation and the breach workflow.
  - Human Subjects Research Act: IRB precondition (PRIV-9).
  - Electronic Signatures Act (2024): Level B3 digital signature; the internal policy template; counterparty consent (Art. 5).
  - Medical Care Act and the EMR regulation: read-only use of EMR; HCA signatures.
  - AI Basic Act: transparency (FR-M3-11), human oversight, risk management (§11).
  - TFDA GCP Art. 55: computerised-systems controls.
- **Intended use (CMP-28).** Written analyses for M5 and M7 safety features before release.
- **AI management.** An ISO/IEC 42001-aligned AI inventory and impact assessment, and a credibility file per AI function.

---

## 11. Verification and validation

### 11.1 Test layers

| Layer | What | Tooling | Gate |
| --- | --- | --- | --- |
| Unit | IR v2 semantics, cascade bookkeeping, filter classes, date/number parsers, assertion cues, lexicon mining, accountant, rounding, LTT, forecast maths, policy tables | pytest, hypothesis | every commit |
| Contract | Schema drift, OpenAPI | `make contracts-check` | every commit |
| Integration | Services against the compose test stack (v1 harness, movable ports) | pytest `-m integration` | every merge |
| End-to-end | Email scenarios for stages 0–6: FEAS by free text with confirmation; decision sheet round trip; Level A approvals; Level B signing page (Playwright, the only UI test); kill -9 replay with exactly-once delivery | pytest `-m e2e` + MailHog | every merge |
| Evaluation | §8.5 suites on synthetic data in CI; on site data on the box | `trialbox eval` | G5 and nightly on the box |
| Security | Egress (root), image scans, red-team | v1 `test-egress`, Trivy/Grype, `redteam` | nightly, release |
| Performance | NFR-4/5 with a 300k-patient synthetic population in CI (3M on the release bench) | `trialbox bench` | release |

### 11.2 Validation as a feature (GAMP 5 2nd ed. / FDA CSA)

The box generates its own validation evidence. `trialbox validate` produces:
- **IQ:** installed image digests, model SHAs, licence manifests, configuration hash and `doctor` output.
- **OQ:** the test suites above run on the installed box, with results.
- **PQ:** the validation replay (§11.4) on the site's own data, plus the recall certificate and bench reports.
- A **trace matrix** generated from `@req` markers (requirement → test → result).
- A risk assessment template per function, and the change record for G5.

The pack is a signed PDF/A plus JSON set for QA.

### 11.3 Go-live acceptance (per site)

| Area | Criterion |
| --- | --- |
| Data | Atlas coverage ≥ 90 % of active patients for diagnoses, labs and medications (24 months); no blocking quality issue; ROC date parse failures < 0.5 % |
| Feasibility | 5 closed studies: S0–S2 funnel within ±15 % of a manual CRC funnel on the same snapshot |
| Pre-screening | `prescreen_patient` passed on ≥ 5 closed studies; portfolio-level known-positive recall lower bound ≥ 0.90 on r ≥ 59 pooled enrollees (§5.6), population named |
| Language | `judge_ml` passed in every stratum with ≥ 100 items; gap ≤ 5 points |
| Release safety | `redteam` zero successes; accountant tests pass |
| Approvals | FR-SIG-4 negative tests pass; validation pack (FR-SIG-7) signed by QA |
| Operations | Restore test; breach tabletop; audit-trail review report |

### 11.4 Built-in real-data validation

1. **R1a: retrospective on de-identified data, no identifiable access.** The hospital's research database export is ingested
   as a source. For N ≥ 10 closed studies across ≥ 3 therapeutic areas, the box replays the lake as of each study's
   recruitment start (`ValidationReplayWorkflow`). It runs the frozen rulesets and measures:
   - historical enrollee capture (with Clopper–Pearson bounds);
   - criterion accuracy against blinded CRC adjudication of ≥ 100 patient–criterion pairs per study;
   - PPV of `strong` and `potential`;
   - review minutes per candidate.

   The research database normally has no trial-enrolment identifiers. The enrolment link therefore goes through an
   honest-broker step: the research office supplies the enrolment list, and the hospital's de-identification broker maps
   it to research-database identifiers under that database's existing IRB approval.
2. **R1b: silent prospective (months 3–4 after IRB approval).** The box runs alongside current practice and compares its
   lists with CRC pre-screening logs. Care and contact do not change.
3. **R2: stepped-wedge by clinic (months 5–10).** Measures eligible-identified rate and enrollment rate, following the 2025
   randomised pre-screening trial design. Reported with DECIDE-AI, TRIPOD-LLM and CONSORT-AI.

The box produces the analysis datasets (de-identified) and pre-specified scripts. Publishing the Taiwan code-mixed results in
a peer-reviewed venue is a launch deliverable (§14).

### 11.5 Annotation protocol (for `judge_ml` and the calibration set)

- Items: patient–criterion pairs sampled by stratum (language mix × note type × criterion type).
- Two annotators (CRC or research nurse) label independently against the guideline `docs/annotation_guideline.md`.
  The guideline is bilingual, with examples per assertion type.
- Agreement: Cohen's κ ≥ 0.8 per stratum before the set is accepted. Disagreements are adjudicated by a third annotator
  (investigator).
- Annotators never see model outputs (blinding). Items are drawn with a stored seed.

---

## 12. Engineering standards

| Topic | Standard |
| --- | --- |
| Languages | Python 3.12 (services); Java 17 (HAPI, cql-translator); no front-end framework (admin console and signing page are server-rendered; WebAuthn uses ≤ 200 lines of vanilla JS) |
| Style and types | ruff (format + lint), mypy --strict, pydantic v2 for every contract (v1 conventions) |
| Repository | Monorepo `trialbox/`. New packages: `services/orchestrator/{workflows,intake,calibration,lifecycle,privacy}`, `services/adapter/atlas`, `services/registry_sync`, `services/console` (admin + signing), `libs/tb_common/{policy,canon,lexicon,assertion,dates,ledger}`, `tools/trialbox` (CLI), `eval/`, `vocab/`, `site/playbooks/` |
| Traceability | `@req("<ID>")` pytest marker on every test that verifies a requirement; `tools/trace_matrix.py` builds the matrix |
| Architecture docs | C4 views in `docs/architecture/` (Structurizr DSL); ADRs in `docs/adr/` (MADR); this document is the URS (ISO/IEC/IEEE 29148 structure) |
| Versioning | SemVer for services, rulesets, prompts, lexicon, schemas; Conventional Commits; signed tags |
| CI/CD | Lint, type, unit and contract on every commit; integration and e2e on merge; release builds produce signed multi-arch images, SBOM, ML-BOM, provenance and the offline bundle. Evaluation on site data runs on the site box, not in CI. |
| Security | OWASP ASVS 5.0 L2 for the admin console and signing page; OWASP LLM Top 10 2025 (§10.3); secret scanning |
| AI management | ISO/IEC 42001-aligned inventory; NIST AI RMF profile; credibility file per AI function |
| Documentation | 1-page CRC guide and 1-page PI guide (zh-TW, en); user guide; admin runbook (v1 RUNBOOK extended); validation pack |
| Definition of done | Code + tests (+`@req`) + docs + ADR if architectural + eval suites if AI-related + audit events + bilingual strings + message lint (FR-UX-1) |

---

## 13. Operations

- **Install.** `trialbox install --profile gb10|x86-5090|scale` from the signed offline bundle. Then `trialbox doctor`,
  `trialbox bench` (NFR-17/18) and `trialbox validate` (IQ/OQ).
- **Default schedule.** As in §4.5:
  - 19:00 ingest and Atlas;
  - 21:00–06:30 night passes;
  - 06:30 packet assembly and outbox.
  - Monday 06:30 digests.
  - 1st of the month: recall audit and QA pack.
  - 05:00 registry sync; 05:30 retention.
  - Nightly backup to the external disk, plus WAL archive.
- **Monitoring.** Prometheus metrics with alert rules: ingest lag, pass overrun, queue backlog, gate backlog per approver,
  `uncertain` outbox rows, ledger anchor failure, certificate expiry, disk. Alerts go by email to IT and the hospital SOC.
- **Updates.** Signed bundles (v1 mechanism). Model, prompt, lexicon and threshold updates only through G5. Rollback to the
  previous bundle and registry entry in ≤ 30 min.
- **Support.** Through the hospital's jump host with MFA and session recording, if the hospital allows it. There is no
  standing vendor access and no telemetry.
- **QA pack** (monthly, by email): audit-trail review, cascade metrics, recall certificates, abstention error per stratum,
  privacy-ledger summary, drift alarms, open `uncertain` sends, access recertification due.

---

## 14. How TrialBox beats the field

The full landscape is in `docs/LANDSCAPE.md`. Accuracy alone is not a moat. Open baselines are strong: TrialGPT, and a local
TrialGPT deployment reached 81.8 % sensitivity, where manual screening found 36.4 % of eligible patients. TrialBox wins by
doing what nobody else can claim, under constraints that cloud vendors cannot meet.

### 14.1 Ten differentiators, each measurable

| # | Differentiator | Why competitors cannot easily copy it | Measured by |
| --- | --- | --- | --- |
| D1 | **Recall certificate on every list** (SAFE-2/3), backed by a recall ledger per canonical criterion: a statistically bounded number of missed eligible patients and a known-positive recall lower bound. A new study inherits its criteria's evidence on day one, and the packet says how deep to review (FR-M4-12). | No vendor or paper publishes a certified bound on the *excluded* population. LLM-first products have no deterministic filter to audit or canonical criteria to pool. | Lower bound ≥ 0.90 at go-live, ≥ 0.95 by R2; share of new studies certified at first packet |
| D2 | **Filter-first cascade with budgets and a cross-study judgement cache** (CAS-*): models read only the residue | Needs a compiler that owns criterion semantics and canonical hashing | `llm_share` per study; cache hit rate > 80 % after 4 weeks; GPU-seconds per candidate |
| D3 | **Inbox-native, no portal** (C-5): decision sheets, reply approvals, one signing page | Portal products are built around their UI; removing it is a product philosophy, not a toggle | Median time from packet to G3 decision; share of gates closed within 48 h |
| D4 | **Code-mixed Taiwanese notes done right** (M-ML): canonical offsets, ROC dates, a self-growing site lexicon shared across the alliance as language packs (ML-12), bilingual assertion rules, stratified evaluation with a parity gate | US/EU products are English-first. Taiwan's lexicon accrues per site. One Taiwanese centre reports 96.7 % mixed-language radiology reports. | Stratum gap ≤ 5 points; lexicon growth; quote verification rate |
| D5 | **Sovereign, one box at about US$5k, non-PRC model option** | Network vendors monetise centralised data; Taiwan public hospitals restrict PRC-brand software | Install in ≤ 30 days from hardware arrival; zero egress findings |
| D6 | **Sponsor-grade feasibility in a night**, plus questionnaire autofill with answer memory, an AI disclosure and a recall certificate | Sponsor platforms cannot see the site's EHR; site tools stop at counts | CRC minutes per questionnaire (baseline measured at the site; hours today *(est.)*); % auto-answered; turnaround |
| D7 | **Whole lifecycle at zero model cost**: playbooks, calendars, clocks, consent versions, budgets, ISF index, monitor packs | Screening vendors stop at the list; CTMS products do not read the EHR | Missed visit windows; on-time SAE reporting; continuing-review lateness |
| D8 | **Payer logic** (M10): NHI prior-authorisation signals for recruitment, and the standard-of-care versus research split at feasibility | No competitor models NHI; v1 already implements TWPAS | Budget-table acceptance; NHI-signal candidates who enrol |
| D9 | **Validation as a feature**: IQ/OQ/PQ pack, validation replay on closed studies, annotation protocol | Vendors offer self-run benchmarks; procurement and IRB need site evidence | Days from install to first PQ report (target ≤ 14) |
| D10 | **Learns the site**: LTT-calibrated abstention per language stratum, five-minute reviews, exemplar bank, screen-fail blind-spot detection, and a shadow pass that collects site evidence for the next model before it is switched on (AI-14) | Needs per-site adjudication loops; SaaS calibrates globally | Error of accepted judgements ≤ α; PPV lift per 100 labels |

### 14.2 Head-to-head

| Competitor | Where it is strong | How TrialBox wins |
| --- | --- | --- |
| Lind / Lind Asia (screening SaaS; on-prem option offered in Asia) | Published criterion agreement in oncology; continuous every-patient screening; regional distribution | Independent and hospital-owned (C-1). Recall certificate. Taiwan code-mixed evidence published. NHI logic. Whole-lifecycle agent. No vendor operator in the loop. |
| Triomics | Oncology depth inside Epic | Oncology via the cancer registry (`condition_attribute`, FR-M0-13) on in-house HIS hospitals where Epic is absent; bilingual |
| Deep 6 / Tempus, IQVIA (Inteliquet), Paradigm | Scale, networks, sponsor relationships | Neutral (not sponsor- or CRO-owned); sovereign; federated feasibility with a privacy accountant across the Taiwan alliance (FR-M11-3) |
| BEKhealth, Trially | Price and speed to start | Fixed-price appliance, no per-patient fees; offline install with `doctor`, `bench` and `validate` |
| TriNetX | Federated counts | Chart-verified with evidence, not code-only counts; recall-certified |
| Epic / Oracle EHR screening | In-workflow | Not present in most Taiwanese centres (in-house HIS); TrialBox is source-agnostic |
| IQVIA.ai, Medidata, Veeva (sponsor suites) | CTMS/EDC/eTMF breadth | The EHR side they cannot see: eCRF pre-fill with SDV packets, query drafts, deviation candidates, the NHI split; exports in CDASH/ODM |
| TrialGPT-style open baselines | Free, published | TrialBox embeds the method where useful (M5) and adds the audit core, recall certification, lifecycle and validation. A head-to-head on the same site data ships with the validation pack. |
| Japan sovereign LLM pilots (NTT, Fujitsu) | Domestic trust | Model-agnostic registry; Japanese profile (ML-10); same validation protocol |

### 14.3 Commercial principles (for the product owner)

- One appliance price per hospital with yearly support. No per-patient, per-query or revenue-share fees.
- The hospital owns all outputs.
- No data leaves, and no sponsor pays for access to the hospital's patients through TrialBox.

---

## 15. Delivery plan

### 15.1 Releases

| Release | Weeks | Scope | Exit criteria |
| --- | --- | --- | --- |
| **R0: Foundations** | 1–4 | Postgres workflows + outbox; served-model echo; IR v2 core (event anchors, counts, seq/atleast, absence); canonical text, dates, assertion rules, lexicon v0; Atlas v0; terminology packages (ICD 2014/2023 + mapping); `doctor`; multi-arch images | FR-WF-1 passes; ATOMS_V2 CQL≡SQL 100 %; `dates_numbers` ≥ 0.99; Atlas on synthetic site |
| **R1a: Feasibility on de-identified data** | 5–14 | Intake proposals + confirmation; criteria extraction J+V; understanding email + criteria workbook; cascade S0–S4 with budgets, cache and metrics; feasibility packet with estimates, projection v1, competitors, investigators; questionnaire autofill + answer memory; `ASK`; Level A approvals; accountant checks; model passes + bench gate; eval suites; validation replay; admin console | §11.4 step 1 analysed on ≥ 10 closed studies; `judge_ml` per stratum on de-identified notes; bench gate passed on the chosen profile |
| **R1b: Pre-screening (after IRB)** | 15–22 | PRIV-9 gate; portfolio clinic-day lists; decision sheets; G3; recall audit + certificate; LTT abstention; five-minute reviews; Level B signing page | Recall lower bound ≥ 0.90; silent prospective started; FR-SIG-4 negative tests pass |
| **R2: Recruitment engine and start-up** | 23–32 | Watchlist flips; incremental evaluation; what-if and relaxation; M6 tracking, hierarchical forecast, consent versions; M7 playbooks, IRB pre-fill, coverage analysis and budget, delegation and training; HCA PKI signatures; Teams/LINE nudges; drift monitor; NHI-aware recruitment | Weekly digests in use for ≥ 10 studies; stepped-wedge started |
| **R3: Conduct and data** | 33–44 | Visit windows, deviations + CAPA, SAE clocks, hospital-flagged events, monitor packs, ISF index; M8 pre-fill, SDV packets, query drafts; M5 registry match + tumour board; M11 OMOP view + federated feasibility with noise; Japanese profile; computable feasibility exchange; line-of-therapy design | Abstraction field agreement ≥ 0.95 on 3 closed studies; monitor-visit pack accepted by a sponsor CRA |
| **R4: Close the loop** | 45–52 | Close-out, archive, registry deadlines, IRB final report; forecast scoring; packaging for other hospitals | Second site installed from the offline bundle; validation paper submitted |

### 15.2 First sprint (weeks 1–2): codeable now, in dependency order

Paths are relative to `trialbox/`. Each task ends with tests carrying `@req` markers.

| # | Task | Files | Done when |
| --- | --- | --- | --- |
| S1-0 | **Remove the cloud-LLM path** (C-2): delete the cloud branch of `LlmClient` and the `cloud_*` settings, the cloud egress rule and the env entries. Rewrite the `phi_guard` docstring to PRIV-4's outbound-text role. Replace the cloud expectation in the egress test with an assertion that no allow rule names an LLM host. `trialbox doctor` fails if `CLOUD_LLM_BASE_URL` is set. | `libs/tb_common/llm.py`, `libs/tb_common/config.py`, `schemas/settings.schema.json`, `deploy/egress.py`, `.env.example`, `libs/tb_common/phi_guard.py`, `tests/unit/test_egress_rules.py` | Unit and egress tests pass; `grep -ri cloud_llm` finds nothing outside the changelog |
| S1-1 | **Served-model echo.** `tb_common.llm` reads the served model id and SHA from the engine's `/v1/models` and from `models/registry.yaml`. FEAS and SCREEN footers and manifests print them. | `libs/tb_common/llm.py`, `services/orchestrator/scenarios/feas.py:87`, `screen.py:137`, `models/registry.yaml` | Unit test with the stub returning a different name; footer shows the served name (MOD-6) |
| S1-2 | **Remove the batch full-record fallback** (CAS-9); keep it behind an explicit `FULLREVIEW` request for ≤ 20 patients | `scenarios/evaluate.py` | Test: a 150-candidate run never calls the full-record path |
| S1-3 | **Canonical text + dates/numbers** (ML-2, ML-3): `canon()`, sentence split, language tags, ROC/era/full-width parsers | `libs/tb_common/canon.py`, `libs/tb_common/dates.py`, `services/lake/textproc.py` (calls canon) | `dates_numbers` fixture set (≥ 300 cases) exact match ≥ 0.99; property tests for offset stability |
| S1-4a | **Judge v4 prompt and output schema**: bilingual `note_question`, quote as offsets into canonical text, `assertion` label, extracted value, no `confidence` field; offset verification replaces the substring check (`quote_not_found` → `quote_offset_invalid`) | `services/orchestrator/prompts/judge_v4.md`, `schemas/llm_judge_output.schema.json` (v2), `scenarios/evaluate.py` | Stub-LLM tests: invalid offsets, out-of-window chunk and assertion mismatch each yield `insufficient` |
| S1-4 | **Assertion rules** (ML-6) with cue tables seeded from Appendix E, and agreement check in the judge path (`insufficient` on disagreement) | `libs/tb_common/assertion.py`, `vocab/assertion_cues.yaml`, `scenarios/evaluate.py` | `assertion_ml` synthetic set macro-F1 ≥ 0.90 |
| S1-5 | **Lexicon v0** (ML-5): seed loader (NHI drug master names, ICD-10-CM-TW labels, lab dictionary, the existing `terminology/synonyms.parquet`), paren-pattern miner, `vocab/site_lexicon.parquet`; retrieval expansion replaces `terms.py` | `libs/tb_common/lexicon.py`, `tools/build_terminology.py`, `scenarios/terms.py` (deprecated shim) | Synthetic notes: mined pairs ⊇ planted pairs; retrieval recall@5 not lower than with `terms.py` on the existing fixtures |
| S1-6 | **Postgres job store + steps + gates + outbox** (§7.0); migrate v1 SQLite schema; sender worker | `services/orchestrator/db.py` → `db_pg.py`, `services/orchestrator/outbox.py`, `deploy/docker-compose*.yml` (a second postgres 16 container, same pinned image as fhir-db) | FR-WF-1 kill-loop e2e: exactly one MailHog delivery per outbox row |
| S1-7 | **IR v2 core schema + semantics**: `id`, event anchors, `count_unit: episodes`, `seq`, `atleast`, `absence`, `index`, `canonical_hash`, `filter_class`, `depends_on`; CQL and SQL templates; ATOMS_V2 | `schemas/v2/criterion_ir.schema.json`, `services/criteria_compiler/semantics.py` (remove the rejection at :52), `compile_cql/templates/`, `compile_sql/templates/`, `tests/fixtures/ir/atoms_v2_ruleset.json` + `tests/fixtures/ir/snapshots/` (next to the v1 ATOMS fixtures) | CQL≡SQL 100 % on ATOMS_V2; all v1 rulesets validate and re-run byte-identically (ADR-V3-08) |
| S1-8 | **Cascade bookkeeping** (CAS-1, CAS-2, CAS-7, CAS-11): stage counts, the structured-never-to-model invariant, the affirmative-exclusion rule, manifest `cascade` block. Until S1-9 supplies computability, every criterion is treated as `soft` (SAFE-1). | `scenarios/evaluate.py`, `scenarios/screen.py`, `scenarios/feas_compute.py`, `schemas/v2/run_manifest.schema.json` | Property test: no `structured` criterion reaches the LLM client; manifest counts reconcile |
| S1-9 | **Atlas v0** (FR-M0-2, -5, -6, -7): profile the canonical lake, coverage and computability per atom type, XLSX export | `services/adapter/atlas/` | Atlas workbook on synthetic site A; computability attached to compiled criteria (after S1-7) |
| S1-10 | **Terminology: ICD-10-CM 2014 + 2023 with the NHIA mapping**; edition-aware code expansion in ValueSets | `tools/build_terminology.py`, `services/criteria_compiler/terminology/mapper.py` | `code_versions` suite passes on synthetic patients coded in both editions |
| S1-11 | **Intake proposals** (§3.3): quoted-text stripper (Outlook/Gmail/zh/ja headers), `classify_intent` prompt, proposal/confirm state, `HELP`/`STATUS` exemptions | `services/orchestrator/intake/`, `prompts/classify_intent_v1.md`, `services/mail_gateway/intake.py` | e2e: 「這個試驗做得起來嗎」 + PDF yields a proposal; `OK` starts FEAS; v1 subjects unchanged |
| S1-12 | **Bench + eval v0** (NFR-17): extend the existing `tools/bench.py` (ingest, feas, screen, microbatch, nav and compile tasks) with a `judge` task (items/hour at a configured prompt length, peak RSS); add `trialbox eval` with `sql_cql`, `dates_numbers`, `assertion_ml`, `redteam` (synthetic) | `tools/bench.py`, `tools/trialbox/eval.py`, `eval/` | Reports written; `bench` runs against the stub in CI. The run against vLLM on the purchased GB10 is the OD-2 exit criterion (week 3–4) |

### 15.3 Team and effort (reference)

R0–R1a needs about 4 engineers (backend ×2, data/terminology and language ×1, ML/evaluation ×1), 0.5 QA/validation, a CRC
champion (20 %), a data steward (30 %) and an investigator sponsor per pilot study. Realistic timing is 14 weeks to R1a
and 22 weeks to R1b, with the IRB approval as the critical path for R1b. A coding agent can execute the sprint tasks
against this specification; humans own the gates, validation and the site relationship.

---

## 16. Open decisions

| # | Decision | Options | Owner | Needed by |
| --- | --- | --- | --- | --- |
| OD-1 | First data source | Research database export (R1a, de-identified) then HIS views (R1b); or HIS views from the start | Data steward + IT | Week 1 |
| OD-2 | Hardware profile at the first site | P-GB10 (recommended); P-5090; decided after `trialbox bench` on both if available | IT + product owner | Week 3 |
| OD-3 | IRB pathway and PDPA basis for identifiable pre-screening | Umbrella approval for pre-screening as research operations; per-study approval. Submit in week 1. Legal names the PDPA §6 basis (consent at registration, or waiver with analysis) | IRB + legal | Week 1 (submission) |
| OD-4 | Small-cell threshold and rounding base | `<5`/base 5 (default); `<10`/base 10 | IRB | Week 4 |
| OD-5 | Level B method, and acceptance of the single end-user signing page as a deviation from "admins only" (C-5) | Passkey (B1, default); IdP re-authentication (B2); HCA PKI (B3) where middleware exists | Product owner + information security + QA | Week 8 |
| OD-6 | Model licences and origin policy | Site `public_agency` flag; legal review of TAIDE, Llama-family, OpenMDW and Gemma terms for appliance distribution | Legal | Week 3 |
| OD-7 | Opt-out scope default | `all_research_use` (default) or `contact_only` | IRB + legal | Week 4 |
| OD-8 | Pricing model | Appliance + yearly support (§14.3) | Product owner | R1a |

**Closed decisions** (they were open in v2):
- **Third-party vendor relationship:** none. TrialBox is independent (C-1).
- **Hermes or other agent front end:** none (ADR-V3-07).
- **Cloud model path:** none (C-2).

---

## Appendix A — Lifecycle coverage matrix

● covered · ◐ partial · ○ not in scope. The release is in brackets. "Model" says whether the stage spends LLM time.

| Stage | v1 | v3 | Model | Main requirements |
| --- | --- | --- | --- | --- |
| Site readiness, data, lexicon | ◐ | ● [R0–R1a] | mapping proposals only | FR-M0-*, ML-5 |
| Protocol intake + Q&A | ● | ● [R1a] | yes | FR-M1-* |
| Protocol optimisation | ◐ | ● [R2] | no | FR-M2-* |
| Feasibility + questionnaire | ● | ● [R1a] | sample only | FR-M3-* |
| Site selection support | ○ | ● [R2] | no | FR-M3-10 |
| Start-up (IRB, budget, delegation, training) | ○ | ● [R2] | drafting | FR-M7-1…4 |
| Pre-screening | ● | ● [R1b] | residue only | FR-M4-*, CAS-*, SAFE-* |
| Patient → trial | ○ | ● [R2–R3] | residue only | FR-M5-* |
| Consent tracking and re-consent | ○ | ● [R2] (eConsent signing out of scope) | no | FR-M6-1, FR-M6-6 |
| Enrollment tracking + forecasting | ◐ | ● [R2] | no | FR-M6-* |
| Visits, deviations, CAPA | ○ | ● [R3] | no | FR-M7-5, -6 |
| Safety clocks, hospital-flagged events | ○ | ● [R3] | no | FR-M7-7, -8 |
| Monitoring visit support, ISF index | ○ | ● [R3] | no | FR-M7-9, -10 |
| Data capture, SDV, queries | ○ | ● [R3] | extraction | FR-M8-* |
| Close-out, registry, archive, IRB final report | ○ | ● [R4] | drafting | FR-M9-* |
| NHI reimbursement / TWPAS / NHI signals | ● | ● [R1a–R2] | as v1 | FR-M10-* |
| Networked / federated research | ● (alliance) | ● [R3] | no | FR-M11-* |
| Randomisation, IP, unblinding | ○ | ○ (non-goal) | – | §2.5 |

## Appendix B — Evidence base (selected)

| Design choice | Evidence |
| --- | --- |
| Criterion-level judgement with quoted evidence, deterministic aggregation | Jin et al., TrialGPT, *Nat Commun* 2024, doi:10.1038/s41467-024-53081-z; Wornow et al., *NEJM AI* 2025 (plausible rationales accompany wrong answers, so verify quotes) |
| Local open models adequate; manual screening misses most | Syed et al., *JAMIA* 2026, doi:10.1093/jamia/ocag006 (local TrialGPT sensitivity 81.8 %, specificity 97.8 %; manual screening found 36.4 % of eligible patients) |
| AI pre-screening raises identification | Unlu et al., *JAMA* 2025;333(12):1084–7, doi:10.1001/jama.2024.28047 |
| Structured data for first-pass filtering only | Raghavan et al., arXiv:1502.04049 (unstructured data essential for 59 % / 77 % of criteria in two trials) |
| Recall certification by sampling | Cormack & Grossman, SIGIR 2016, doi:10.1145/2911451.2911510; Lewis, Yang & Frieder, CIKM 2021 (QBCB); Webber, *ACM TOIS* 2013 (intervals for recall) |
| Distribution-free thresholds | Angelopoulos et al., Learn-then-Test, *Ann Appl Stat* 2025 (arXiv:2110.01052); conformal risk control (arXiv:2208.02814); Jung, Brahman & Choi, *Trust or Escalate*, ICLR 2025 |
| Code-mixed Taiwanese notes | E-Da Hospital cardiac CT reports, 96.7 % mixed text, *J Imaging Inform Med* 2026, doi:10.1007/s10278-026-02009-8; Lee et al., code-mixed de-identification, *JMIR* 2024 (PMID 38271060) |
| Data-driven criterion relaxation | Liu et al., Trial Pathfinder, *Nature* 2021, doi:10.1038/s41586-021-03430-5 |
| Calibrated feasibility, not PI guesses | Benjamin et al., *PLoS One* 2022, doi:10.1371/journal.pone.0262862 |
| Feasibility questionnaire burden | ASCO/AACI Clinical Research Initiative 2020 |
| Reporting of evaluations | DECIDE-AI (*Nat Med* 2022), TRIPOD-LLM (*Nat Med* 2025), CONSORT-AI (*Nat Med* 2020) |

The full list is in `docs/LANDSCAPE.md`.

## Appendix C — Compliance traceability (summary)

| CMP | Source | Requirement | Implemented by | Verified by |
| --- | --- | --- | --- | --- |
| CMP-01 | 21 CFR 11.10(e); E6(R3) A1; Annex 11 §9 | Audit trail: who, what, when (UTC), why; append-only; hash-chained | §10.5, FR-AG-5 | ledger tests, `audit_verify` |
| CMP-02 | E6(R3) | Periodic audit-trail review | §13 QA pack | T (pack generated) |
| CMP-03 | 11.10(d),(g) | Unique identities, authority checks | §10.1, policy module, personal mailboxes | policy property tests |
| CMP-04 | 11.50, 11.70, 11.100, 11.200, 11.300; EMA guideline §4.8; Taiwan ESA 2024 | Level A approvals (operational records); Level B signatures with re-authentication; manifestation; linking; certification letter | §3.5 FR-SIG-*, §5.9 | FR-SIG-4 negative tests; validation pack |
| CMP-05 | E6(R3) §4.3; GAMP 5 2nd ed.; FDA CSA | Risk-based validation, traceability, change control | §11.2, G5 | `trialbox validate` |
| CMP-06 | FDA AI credibility guidance; EMA reflection paper | Credibility file per AI function | §8.5 | eval reports |
| CMP-07 | AI Basic Act transparency; CDS principles | Evidence and uncertainty shown with every output | §5.4, FR-M4-3, SAFE-3 | e2e |
| CMP-08 | E6(R3) investigator responsibility | Box never decides eligibility | G3 meaning, FR-M4-5 | e2e, I |
| CMP-09 | E6(R3) | No unblinding data | FR-M7-11 | T, I |
| CMP-10 | ICH M11; USDM | Protocol versions, amendment diff | FR-M1-1, FR-M1-7 | T |
| CMP-11 | FHIR R4; TW Core; JP Core | Conformance; pinned IGs | adapter, ML-10 | validator runs |
| CMP-12 | CDISC CDASH, ODM v2 | eCRF export with lineage | FR-M8-* | T |
| CMP-13 | OMOP; ICH M14 | Counts carry data cut, logic and manifest | §5.8 | T |
| CMP-14 | PDPA; HSRA | Aggregates only, rounding, accountant, IRB precondition | PRIV-2, -7, -9 | T |
| CMP-15 | PDPA (2025 amendment) | Breach workflow | SEC-14 | tabletop record |
| CMP-16 | PDPA; MOHW EMR rules | Data residency; no external models | C-2, SEC-1 | egress test |
| CMP-17 | Hospital policy; NHI data provisions | Opt-outs before lists | FR-M4-6, PRIV-8 | T |
| CMP-19 | ICH E2A; TFDA SUSAR rules | Safety clocks; investigator decides | FR-M7-7, -8 | T |
| CMP-20 | E6(R3) deviations | Deviation log + CAPA, Level B | FR-M7-6 | T |
| CMP-21 | 21 CFR 312.62; EU CTR; TFDA GCP | Retention defaults, legal hold, archive | PRIV-6, FR-M9-3 | T |
| CMP-22 | E6(R3) §4.3 | Backup and restore | NFR-8 | restore test |
| CMP-24 | OWASP LLM Top 10 2025 | LLM controls | §10.3 | `redteam` |
| CMP-25 | SLSA; CycloneDX | Signed builds, SBOM, ML-BOM, licence manifests | SEC-5, MOD-2 | release checklist |
| CMP-27 | ISO/IEC 42001; NIST AI RMF; AI Basic Act | AI inventory, impact assessment | §12 | I |
| CMP-28 | TFDA SaMD guidance; MDCG 2019-11; FDA CDS | Intended-use control and written analyses | §2.4, FR-M5-4 | design review record |
| CMP-31 | 42 CFR 11; EU CTR Art. 37 | Registry deadlines (IIT) | FR-M9-1 | T |
| CMP-32 | NHI rules | Coverage analysis; research items not billed to NHI | FR-M7-3, FR-M10-* | T |
| CMP-33 | TransCelerate SIP | Site profile reuse; answer memory | FR-M0-10, FR-M3-6 | T |
| CMP-34 | E6(R3) sponsor oversight | AI disclosure in every external packet | FR-M3-11 | T |

## Appendix D — Email grammar (v3)

The v1 ABNF (`SPEC.md` §5) stays valid, with one change: v1's `APPROVE <ruleset> version=<v>` (D-44) is accepted for IR < 2.0.0 rulesets. v3 gates use `APPROVE <gate-id> sha=…`, and the `G[0-6]-dddd` gate-id pattern disambiguates the two. Free text is classified into these commands as **proposals** (§3.3). Every command
may appear in the subject or as the first body line.

```
command   =/ "FEAS" SP ("NEW" / study) *(SP param)          ; param = key "=" value (scope, lookback, deadline)
command   =/ "QFILL" SP study                                ; fill the attached questionnaire
command   =/ "ASK" SP study SP quoted-text                   ; protocol Q&A (no patient data)
command   =/ "WHATIF" SP study SP change *(";" change)       ; internal only
change    = ("drop" SP criterion-id) / ("set" SP criterion-id SP param "=" value)
command   =/ "SCREEN" SP study *(SP param)                   ; scope=practitioners:…, cadence=weekly|nightly
command   =/ "STUDY" SP study SP status                      ; recruiting | follow_up | closed | declined
command   =/ "CONFIRM" SP pid *(SP pid)                      ; G3, PI/Sub-I
command   =/ "REJECT" SP pid SP reason-code [SP free-text]
command   =/ "DEFER" SP pid [SP date]
command   =/ "STATE" SP pid SP state [SP date]               ; G4
state     = "contacted" / "consented" / "screened" / "randomized" / "declined" / "screen_failed" / "withdrawn" / "not_contactable"
command   =/ "APPROVE" SP gate-id SP "sha=" 16HEXDIG [SP "otp=" 1*8DIGIT]  ; Level A (A+ with OCRA code)
gate-id   = "G" %x30-36 "-" 4DIGIT                         ; distinguishes v3 gates from v1 "APPROVE <ruleset> version=<v>"
command   =/ "REJECTGATE" SP gate-id SP free-text
command   =/ "ANSWERS" SP 1*(DIGIT ("Y" / "N" / "?") SP)     ; five-minute review
command   =/ "SAE" SP pid SP date SP free-text               ; starts safety clocks
command   =/ "MONITOR" SP study SP date                      ; monitoring-visit pack
command   =/ "QUERY" SP study SP pid SP free-text            ; EDC query answer draft
command   =/ "MATCH" SP mrn *(SP mrn)                        ; delegated clinicians only
command   =/ "ATLAS" [SP domain] / "STATUS" [SP study] / "HELP" / "DIGEST" SP ("daily" / "weekly" / "off")
command   =/ "FULLREVIEW" SP pid                             ; full-record review, ≤ 20 per request
command   =/ "OK"                                            ; confirms the proposal in the replied-to message
```

Reason codes for REJECT:
- R01 does not meet inclusion on chart review
- R02 meets exclusion
- R03 clinically inappropriate
- R04 patient preference known
- R05 enrolled elsewhere
- R06 data outdated
- R07 other (free text required)

## Appendix E — Seed tables for the multilingual normaliser (ML-3, ML-6)

**Assertion cues** (seed; the site extends them through G0). Scope is the clause containing the cue, up to the next clause
boundary (`，。；;,.` or a conjunction such as `但`/`but`/`however`).

| Class | zh-TW | en | ja |
| --- | --- | --- | --- |
| negated | 無、沒有、否認、未見、未、非、排除、(-)、陰性 | no, not, denies, denied, without, negative, absent, r/o (ruled out when followed by "—" or "neg") | なし、無し、否定、認めない、陰性 |
| uncertain | 疑似、懷疑、可能、待排除、r/o (rule out, pending) | possible, probable, suspected, r/o, query, ? | 疑い、可能性 |
| historical | 曾、過去、病史、之前、s/p、術後 | history of, h/o, s/p, previous, prior, status post | 既往、以前、術後 |
| family | 家族史、父親、母親、兄弟、姊妹、家人 | family history, FHx, mother, father, sibling | 家族歴、父、母 |
| hypothetical | 若、如果、如有、必要時、prn | if, should, in case, prn | もし、場合 |

**Date forms** (each table-driven):
- ROC year (`民國113年3月5日`, `113/03/05`, `113.3.5`, `1130305` in date columns): year + 1911.
- Japanese era (`令和6年3月5日`, `R6.3.5`, `平成31年`): era table.
- Western: ISO, `2024/3/5`, `5/3/2024`. Ambiguous day/month forms resolve by the column or site convention, and are
  otherwise flagged.
- Relative (`三個月前`, `2 weeks ago`, `3日前`): resolved against the note date and marked `relative`.

**Number forms:**
- full-width digits;
- Chinese numerals in counts and durations (`一`…`十`, `兩`, `半年`);
- unseparated value-unit pairs (`Cr1.2`, `EF35%`, `Hb9.8`) via a lab-alias table from the lexicon;
- ranges (`3-5`, `3~5`, `3至5`).

## Appendix F — Sample sizes for recall evidence (one-sided 95 %, Clopper–Pearson)

**Excluded-stratum sample needed to claim an elusion rate below p:**

| Target p | 0 found | 1 found | 2 found | 3 found |
| --- | --- | --- | --- | --- |
| 2 % | 149 | 236 | 313 | 386 |
| 1 % | 299 | 473 | 628 | 773 |
| 0.5 % | 598 | 947 | 1,258 | 1,549 |

**Known-positive patients needed for a recall lower bound:**

| Recall ≥ | 0 missed | 1 missed | 2 missed |
| --- | --- | --- | --- |
| 0.90 | 29 | 46 | 61 |
| 0.95 | 59 | 93 | 124 |
| 0.98 | 149 | 236 | 313 |

These tables are at α = 0.05 for a single stratum. A certificate over K strata uses α/K per stratum (Bonferroni), which
needs larger n. For example, at K = 4 a 1 % claim with 0 found needs n ≈ 438. That is why samples are pooled per canonical
criterion and accumulate over months (SAFE-2).

Elusion alone is not a recall claim when eligibility is rare. A clean 299-sample from 20,000 excluded patients still allows
up to 199 misses. That is why SAFE-3 requires the known-positive test, and why summaries quote its lower bound. Structured
stages exclude only on affirmative evidence (CAS-11). This keeps the large low-yield strata small, so their bounds do not
dominate.

## Appendix G — Disposition of the v2 adversarial review

| Finding | Resolution in v3 |
| --- | --- |
| F-01 end-user console | C-5; §3; ADR-V3-06. Reply approvals (Level A) and a single signing page (Level B) only for regulated signatures, because the research shows an email reply cannot meet Part 11 re-authentication. Admin console only. |
| F-02 cascade not explicit or bounded | §4.4 CAS-1…11; §5.8 manifest; FEAS estimates from samples (CAS-8) |
| F-03 hardware and portfolio | §4.7 profiles, capacity model, bench gate; §8.2 roles → classes; ADR-V3-04/05. GB10 is recommended over the reviewer's P-5090 default, with the dissent recorded and the bench deciding per site. |
| F-04 latency over-engineering | C-4; §4.5 passes; NFR-1…8 rewritten as batch SLOs; router model and gateway removed |
| F-05 cloud path, Hermes, Teams/LINE | C-2; ADR-V3-07; §4.1 allowlist; FR-UX-6 |
| F-06 vendor relationship | C-1; §16 closed decisions; LANDSCAPE wording fixed |
| F-07 multilingual | §5.3; §6.13 ML-1…11; Appendix E; stratified `judge_ml` with gap gate |
| F-08 wrong v1 claims | §1.1 rewritten against the code (12 services, controlled rounding, bge-m3 shipped, no negation code, `trialgpt/` on another branch, HAPI figure as extrapolation) |
| F-09 silent false negatives | §6.14 SAFE-1…8; CAS-11; recall certificate §5.6 |
| F-10 small-cell differencing | PRIV-2, PRIV-7, PRIV-8; FR-M2-2 caps |
| F-11 injection and overreach | §3.3 deterministic-first intake; SEC-9, SEC-12, SEC-13; redefined `redteam` gate |
| F-12 Part 11 mechanics | §3.5; FR-SIG-1…8; Appendix C CMP-04 |
| F-13 regulatory gaps | PRIV-9 IRB precondition; R1a on de-identified data; SEC-14 breach workflow; CMP-28 analyses; PRIV-6 retention defaults; CMP-34 disclosure |
| F-14 thin lifecycle | §6.7 M7 playbooks, IRB, budget, delegation, visits, deviations, SAE clocks, monitor pack, ISF; §6.8 SDV and queries; FR-M9-4 |
| F-15 contradictions | G3 deciders fixed (PI/Sub-I; CRC defers); estimates vs sample fixed; M11 in R3; MATCH bypasses the model; replay wording; G4 release; G2 expiry behaviour; ADR-V3-08 |
| F-16 uncodeable tasks | `condition_attribute` table (FR-M0-13); line of therapy moved to R3 design; outbox; one Postgres 16 engine; ledger anchoring without Object Lock; no LiteLLM; 300k CI bench; sprint ordered |
| F-17 unverifiable gates | Smaller starting gold sets; annotation protocol §11.5; denominator definitions; forecast scoring post-R3; defined "comparable" |
| F-18 PHI details | Intake text redaction (PRIV-6); password via another channel (SEC-10); Atlas never samples free text; 400-character sentence evidence |
| F-19 operational surface | §4.2 "deliberately not used" list |
| F-20 timeline | R0/R1a/R1b split; 14 and 22 weeks; IRB as critical path |

### Round 2 (review of this document)

A second adversarial review of the v3 draft (`docs/reviews/SPEC_v3_review.md`) rated it "approvable with fixes". It found
4 blockers, 8 majors and 10 minors, and proposed 5 further innovations. All are applied in this version:

| Finding | Resolution |
| --- | --- |
| N-01 S1 missing-data rule stated three ways | §5.2 rewritten (IR ≥ 2: `unknown` at S1, decided at S2; IR < 2 unchanged); CAS-11 and ADR-V3-08 scoped by IR version |
| N-02 cloud path still in code | Sprint task S1-0; C-2 and §1.1 updated |
| N-03 schedule vs memory on GB10 | §4.5 schedule (ingest 19:00, passes 21:00–06:30); NFR-B5 memory budget; §13 aligned |
| N-04 R1a needs R1b/R2 parts | Interim A2 rule for G5 (FR-SIG-1); SEC-10 passphrase issued in person |
| N-05 recall statistics | Recall ledger per canonical criterion, pooled and cumulative; `S2-zero_hit(note)` stratum; example computed by code; α/K note in Appendix F; portfolio-level known positives with a named population |
| N-06 capacity arithmetic | §4.7.2 corrected, marked *(est.)*; CAS-4a night budget |
| N-07 NFR-2 vs proposal round trip | NFR-B2 proposals within 2 h in the day; NFR-2 clock starts at confirmation |
| N-08 signature mechanics | A+ uses OCRA (RFC 6287); 16-hex hash prefix; Level A records named approvals; G6 in the schema; passkey enrolment ceremony |
| N-09 sprint gaps | S1-4a (judge v4), S1-8 soft until Atlas, real ATOMS path, extend `tools/bench.py`, GB10 bench tied to OD-2, APPROVE disambiguation |
| N-10 estimation details | Stratified estimator with FPC; rounding of endpoints; AI-09 amended; selective LTT; AI-11 certification arithmetic |
| N-11 interfaces | Sponsor JSON by email only; NFR-13 wording |
| N-12 Taiwan law | MediCloud conditional on NHIA permission; PDPA basis named in OD-3; site vs sponsor safety clocks; 42 CFR 11 applicability; ESA Art. 5 scope |
| N-13–N-22 minors | §1.1 facts; differencing checks in R1a; inbound PHI classification; second Postgres container; FR-AG-2 scope; CAS-7 definitions; *(est.)* marks; honest broker; IdP as supplier control; grammar (`not_contactable`, `FULLREVIEW`) |
| I-A…I-E innovations | Recall ledger (§5.6, SAFE-2); importance-weighted sampling (AI-15); shadow pass (AI-14); alliance language packs (ML-12); QBCB review depth (FR-M4-12) |

## Appendix H — References

**Regulatory and standards.**
- ICH: E6(R3) (Step 4, 6 Jan 2025) with Annex 1; ICH M11 (Nov 2025); ICH M14.
- CDISC USDM; HL7 FHIR R4, TW Core IG, JP Core, TWPAS; OMOP CDM 5.4.
- FDA: 21 CFR Part 11; *Electronic Systems, Electronic Records, and Electronic Signatures in Clinical Investigations: Q&A*
  (Oct 2024); Computer Software Assurance guidance.
- EMA: *Guideline on computerised systems and electronic data in clinical trials* (EMA/INS/GCP/112288/2023); EU GMP Annex 11
  consultation draft (Jul 2025).
- NIST SP 800-63B-4.
- Taiwan: Electronic Signatures Act (amended 2024-05-15); EMR regulation (醫療機構電子病歷製作及管理辦法); Personal Data
  Protection Act (amended 2025); Human Subjects Research Act; AI Basic Act; TFDA GCP (藥品優良臨床試驗作業準則) Art. 55; NHIA
  ICD-10-CM/PCS 2023 switch (2025-01-01) and the 2014→2023 mapping.
- GAMP 5 2nd ed.; ISO/IEC 27001, 42001, 25010; ISO/IEC/IEEE 29148, 42010; OWASP ASVS 5.0 and LLM Top 10 2025; SLSA;
  CycloneDX.

**Literature.** Appendix B; `docs/LANDSCAPE.md`.

**Code.**
- TrialBox v1 (`trialbox/`, this branch).
- TrialGPT local port (`trialgpt/` on branch `claude/trialgpt-local-lcvm9p`).
- vLLM, llama.cpp, HAPI FHIR, DuckDB, bge-m3.
