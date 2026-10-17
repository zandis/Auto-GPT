## 0. Binding constraints

These constraints come from the product owner. Every other section MUST satisfy them, and a requirement that conflicts with one
of them is a defect in this document. Where a constraint changed from v3, the v3 wording is retired and the prime mark (′)
shows the change.

| ID | Constraint | Where it is implemented |
| --- | --- | --- |
| C-1 | **Independence.** No integration, data exchange, revenue share, white-label or complementary-scope arrangement with Lind (lind.care), Lind Asia/PREMIA, Inato, Massive Bio, Triomics or any other screening or recruitment vendor; they are competitors. Hermes Agent (MIT) and the NCBI TrialGPT code (US Government work) are pinned, vendored software with no commercial relationship. Cloud model providers are contracted processors behind `tb-gateway`, not partners. No production path calls trialgpt.app or any third-party matching service. | §2.2, §9 (Hermes upgrade policy), §19, §21 |
| C-2′ | **On premises first; hybrid under the data-class policy.** One image set, three topologies: **A** on-prem appliance (default); **B** the hospital's own in-country cloud tenant with customer-managed keys; **C** hybrid, A or B plus a model egress policy for D0–D2 only. D3/D4 never reach an external model in any topology. Only `tb-gateway` may reach a model endpoint. | §4 (topologies), §7 (data classes, boundary table), §8 (gateway, routing policy), §14 (egress controls), §18 (rollback of cloud routes) |
| C-3 | **Filter first.** Deterministic rules on structured data reduce the population. A model sees only the residue: criteria that structured data cannot decide, read from notes. The S2b semantic pre-filter never excludes, except for criteria whose measured lexicon recall is ≥ 0.98. The cascade is measured and budgeted, and every list carries a recall certificate. | §4 (cascade S0–S5, S2b), §6 (certificate), §10 (SAFE-*) |
| C-4 | **Batch first, interactive where cheap.** Patient-level model work runs in scheduled passes. Batch time buys accuracy: larger models and second opinions. Interactive paths are limited to those §4 lists: conversation, status, protocol Q&A, aggregate queries and bounded single-patient requests. Their latency targets are in §13. | §4, §13 |
| C-5′ | **Minimal UI.** Exactly five surfaces: the email/Teams/LINE conversation; the signing page; an optional review page; the admin control plane (administrators only, no PHI); an optional CDS Hooks card. Any other end-user screen is a defect. | §3.1, §3.5, §3.7, §3.8, §4, §14 |
| C-6 | **Whole lifecycle.** Every stage in §2.4 has a defined agent behaviour, inputs, outputs and gate. Most later-stage help is deterministic and costs no model time. | §2.4, §10, §11, Appendix A |
| C-7 | **Cost/precision balance through the bench gate.** The reference is one box at about US$5k *(est.)*. Model classes per hardware profile, and any cloud route, are chosen by measurement on the site's own data and on public suites. Cloud spend runs against budgets in the gateway. | §4 (profiles, bench gate), §8 (cost model, budgets), §13 |
| C-8 | **Multilingual.** The product handles Traditional Chinese (zh-TW), English, Japanese (ja), and code-mixed, abbreviation-heavy Taiwanese notes. The output language is defined per artefact. Evaluation is stratified by language, with per-language floors. | §3.9, §10 (ML-*), §16 (`judge_ml`, bake-off) |
| C-9 | **Codeable now.** Every MS0/MS1 requirement maps to concrete packages and modules in this repository, and the first sprint is ordered by dependency. | §17, §20 |
| C-10 | **Hermes as the governed front door.** Hermes Agent (pinned release) is the conversation engine on email, Teams, LINE (nudges, non-PHI) and the admin CLI/TUI: staff concierge, aggregate analyst, admin copilot. Its only tools come from the front-door MCP server: no PHI tools, schedules, approvals or writes. Every test passes with `channels.engine: native`. | §3.4, §9, §14, §18 |
| C-11 | **Open-data verifiability.** Every quality claim can be reproduced on open data before site data exists. Public suites run in CI; the bake-off uses D0 data only. A number quoted to a hospital or sponsor comes from a public suite, the site bench or the site's ledger, never a vendor claim. | §1.3, §8, §16 |

**Precedence.** If two constraints pull in different directions, the order is C-2′ (data class), then C-1, then C-3, then
the rest. For example, a cheaper cloud route (C-7) never overrides the data-class policy (C-2′). An interactive answer
(C-4) never bypasses the cascade (C-3).

---

## 1. Where we are

### 1.1 The v1 proof of concept

These facts were verified against the repository at `0803107`. The v1 code is unchanged since `1115235`, except for the
files that `0803107` added (§1.3). The sources are `docs/PROGRESS.md` (D-86), `docs/BENCH.md`, `deploy/docker-compose.yml`
and the code itself. This text corrects the residual errors that the round-2 review found in v3 §1.1 (N-13).

**Services.** `deploy/docker-compose.yml` defines 12 services, 11 per profile: `minio`, `fhir-db` (PostgreSQL 16),
`fhir-store` (HAPI FHIR JPA with Clinical Reasoning), `lake` (DuckDB, CJK bigram FTS), `embed-service` (bge-m3),
`doc-parser` (lite parser; no Docling image), `criteria-compiler`, `adapter`, `orchestrator`, `mail-gateway`, and
`llm-stub` or `llm-service` (vLLM). An arm64 GB10 override exists (`deploy/docker-compose.gb10.yml`).

**What works on synthetic data with a stub LLM.**

| Capability | Where |
| --- | --- |
| Email intake with aligned SPF/DKIM/DMARC and a pinned authserv-id; `In-Reply-To` matching | `services/mail_gateway/intake.py`, `libs/tb_common/subject.py` |
| Declarative HIS→FHIR adapter with pseudonymisation, `pid = HMAC(site_key, MRN)` | `services/adapter/` |
| Criteria compiler: protocol text → Criterion IR → ValueSets → CQL and SQL from templates, with the CQL≡SQL equivalence gate | `services/criteria_compiler/` |
| Note judge that verifies its quote against the excerpt | `services/orchestrator/prompts/judge_v3.md` |
| Deterministic PDF/XLSX/DOCX reports | `services/orchestrator/reports/` |
| Hash-chained audit log; byte-identical re-runs | `libs/tb_common/audit.py`, `services/orchestrator/rerun.py`, `tools/audit_verify.py` |
| Egress allowlist, signed offline updates, retention | `deploy/egress.py`, `tools/sign_bundle.py`, `tools/verify_update.py`, `libs/tb_common/retention.py` |
| Small-cell protection: threshold suppression, controlled rounding (`round_count`), rate withholding (`rate_publishable`) | `libs/tb_common/smallcell.py` |
| SQLite job queue | `services/orchestrator/db.py` |

The settings name two reference model classes: a 35B-class MoE judge (`qwen3.5-35b-a3b-q4`) and a 120B-class extractor
(`gpt-oss-120b-mxfp4`). Together they fit one 128 GB GB10. They do not fit one 32 GB card.

**Test state.**

| Platform | Record | lint | unit | integration | e2e | egress |
| --- | --- | --- | --- | --- | --- | --- |
| Linux | `docs/PROGRESS.md` D-86 | clean | 285 passed, 2 skipped | 59 passed | 6 passed | 1 passed |
| Linux | `0803107` adds two test modules | – | + 11 test functions (`test_mlbench.py` 7, `test_recall_cert.py` 4) | – | – | – |
| Windows (WSL2) | fixes in `f8697a8` | – | counts not recorded | – | – | – |

The suites were not re-run for this document (no project virtual environment in the authoring container). The history
contains one merged pull request (#1).

**Gaps still open in the code.** v4 closes each of these.

| Gap | Evidence | Closed by |
| --- | --- | --- |
| PHI guard has about 100 ROC surnames and no given names, addresses or employers | `libs/tb_common/phi_guard.py:16–20` | §7 (PHI guard coverage gate) |
| A cloud-LLM branch still exists, off by default | `libs/tb_common/llm.py`, `libs/tb_common/config.py:128–129`, `deploy/egress.py:75`, `.env.example` | §8: becomes the seed of `tb-gateway`. v3 task S1-0 (delete it) is withdrawn. |
| The batch path has a full-record fallback of up to 28k tokens for up to 100 candidates | `services/orchestrator/scenarios/evaluate.py:32–34` | §4 (cascade budgets), FULLREVIEW limits |
| FEAS and SCREEN footers print the configured judge, not the model actually served | `scenarios/feas.py:85–88`, `scenarios/screen.py:137` | §8 (manifest records the served build) |
| The orchestrator `/jobs` API has no authentication and relies on network isolation | `services/orchestrator/app.py:97–120` | §14 (service identity, mTLS) |
| No negation or assertion handling; `services/lake/textproc.py` only tokenises and chunks | code | §10 (ML-6) |
| HAPI per-patient `$evaluate` ran at about 21 patients/s (600 in 28.7 s). Extrapolated to 3M patients, that is about 40 h *(extrapolation)*. | `docs/BENCH.md` | Whole-hospital runs use the lake SQL engine (kept) |

**Terminology in v1.** There are 59 ICD codes and 24 drugs. Retrieval expansion uses 32 hand-written keys in
`scenarios/terms.py`. The compiler uses a 93-row synonym table with zh-TW surface forms
(`services/criteria_compiler/terminology/src/synonyms.csv`).

### 1.2 The TrialGPT port

The port lives in the sibling directory `trialgpt/` (branch `claude/trialgpt-local-lcvm9p`, head `8711899`). It runs NCBI
TrialGPT (Jin et al., *Nat Commun* 15:9074, 2024) on a local model. It is the only part of the codebase that has been run
with real models, and it is the base of the v4 matching engine (§10, M5).

| Part | What it is | State |
| --- | --- | --- |
| Pipeline | Keywords → hybrid BM25 + MedCPT retrieval (RRF, k = 20) → criterion matching → aggregation → ranking (`trialgpt_local/core.py`, `retrieval.py`, `pipeline.py`); NCBI prompts byte for byte, drift-checked | Working; 20 offline test functions |
| Retrieval fidelity | With the paper's gpt-4-turbo keyword file: SIGIR recall@500 **0.931** (paper 0.934); recall@1000 0.964 | Measured |
| Ranking on real local models | SIGIR slice of 6 pairs (2 patients × 3 trials): `gemma4-e4b` NDCG@10 0.930, 0 % parse errors, 167 s/pair; `qwen2.5-1.5b` NDCG@10 0.810, 19.6 % parse errors, 88 s/pair. Paper (GPT-4, 3 cohorts): NDCG@10 0.728. | **Smoke result only**, not comparable to the paper |
| Head-to-head with trialgpt.app | 2 public synthetic patients; top-10 overlap 0.000; same-model cross-evaluation is biased by construction | Physician adjudication pending (`results/h2h/pooled.xlsx`) |
| CGRD validation harness | Pseudonymised notes from a CGRD-format database; blinded trial- and criterion-level workbooks; AUROC, sensitivity, specificity, PPV, Cohen's κ (`trialgpt_local/cgrd/`) | Synthetic CGRD-format data only (`results/cgrd/demo`); no physician answers yet |

v4 reuses the retrieval, criterion-level judgement and aggregation scoring as `services/matching/registry_match/` (§10, M5),
under the cascade's judge, cache and evidence schema.

### 1.3 New open-data assets in the repository

Commit `0803107` added three assets. They make v4's quality gates testable before any site data exists (C-11).

| Asset | Content | What it gives v4 |
| --- | --- | --- |
| `eval/criterion_ml/` | 1,015 physician-labelled patient–criterion pairs (NCBI TrialGPT-Criterion-Annotations, public domain): 53 SIGIR patients, 103 trials, 356 inclusion and 659 exclusion criteria, with expert evidence sentence ids. The 53 notes also exist in zh-TW, ja and Taiwanese code-mixed style, with sentence order, sentence count (326) and numbers preserved. | `judge_ml` seed, evidence-span gold, public calibration prior (§16). Translations are machine-made and **not clinician-verified**: for model comparison and parity, not clinical ground truth. |
| `tools/mlbench.py` | Judging benchmark against any OpenAI-compatible endpoint (OpenRouter or the box's vLLM): accuracy, macro-F1, false-block rate and patient×trial false exclusion with Clopper–Pearson bounds, evidence F1, language parity, cost. Cached and resumable. | Engine of the bake-off (§16) and of the judge-role bench (§4) |
| `libs/tb_common/recall.py` | Clopper–Pearson bounds and an anytime-valid betting confidence sequence (Waudby-Smith & Ramdas, JRSS-B 2024) for elusion rates; certificate combiner (Bonferroni over strata, known-positive lower bound) | Statistics of the recall certificate (§6, §10 SAFE-*) |

**The GPT-4 reference.** These numbers come from scoring the published GPT-4 labels in the dataset with `mlbench`, on all
1,015 pairs. No GPT-4 call was made.

| Metric | Value |
| --- | --- |
| Criterion accuracy | 0.873 (the paper reports 87.3 %) |
| False-block rate (model blocks, physician did not) | 0.014; 95 % upper bound 0.022 |
| Patient × trial false exclusion | 0.101 (8 of 79 patient–trial pairs the physician left open); 95 % upper bound 0.175 |

The last row is why TrialBox certifies recall rather than quoting criterion accuracy: a 1.4 % per-criterion false-block
rate loses about one eligible patient–trial pair in ten. The dataset's `training` flag is not a split (in 129 of its 134
`False` rows GPT-4 disagrees with the physician), so `mlbench` reports those rows as a hard slice.

**Anytime-valid bounds.** In the simulation recorded for v4, over 12 monthly looks, repeated Clopper–Pearson bounds missed
the true elusion rate in 9.7 % of ledgers and the confidence sequence in 0.3 %.
`tests/unit/test_recall_cert.py::test_sequence_covers_true_rate_over_monthly_looks` reproduces the comparison at smaller
scale. Importance (Horvitz–Thompson) weighting and pooling per canonical criterion are not implemented yet (§6, §10).

**In progress:** the end-to-end test on the open MIMIC-IV Clinical Database Demo on FHIR (v2.1.0, 100 patients, ODbL 1.0);
its fetcher `tools/fetch_open_data.py` (checksum-verified, into `.cache/open_data/`) is written but not committed.
**Pending:** the OpenRouter bake-off on D0 data, waiting for the API key. No bake-off results exist and none are quoted.

### 1.4 What has never touched reality

| Area | Status at `0803107` |
| --- | --- |
| Real patients and site protocols | None (GZQO is a synthetic excerpt; RA-BIO and ONC-OSI are fictional NHI rules) |
| A real LLM in the TrialBox evaluation path | None; the only real-model runs are the TrialGPT slices (§1.2), and `mlbench` has scored only published GPT-4 labels |
| Physician adjudication; clinician review of translations | None; workbooks ready but unanswered |
| A database driver for a real HIS; HL7 v2; CDC; OMOP | None |
| IRB approval, DPO sign-off, site go-live checks (v1 §11.2) | None |
| Hermes, cloud routes, signing page, review page, admin control plane | Specified only; never built |
| Hardware | The only bench (`docs/BENCH.md`) ran on a 4-vCPU development host with no GPU and the stub LLM: deterministic shares only. No model latency and no hardware profile of §4 has been measured. |

### 1.5 Corrections to earlier claims

The v4 literature review (`literature_competitors.md` §0) found claims in `docs/LANDSCAPE.md` and the v3 positioning that do
not hold. v4 withdraws or restates them. §19 carries the refreshed positioning.

| Earlier claim | v4 position |
| --- | --- |
| Lind "TRIAGE, JCO OP June 2026", 94.2 % agreement, 806 patients | **Unverified**; no journal record found. Targets do not lean on it. |
| Epic shipped AI chart-vs-criteria checks in Nov 2025 | Not shipped; "in development, 2026" on Epic's roadmap |
| The "neuro-symbolic, 3,804 patients, F1 0.82" study is academic | It is Massive Bio's platform, a competitor (C-1) |
| (missing) reference deployment | UT Southwestern preprint: 39,182 patients, 26 studies, criterion accuracy 0.94, sensitivity 0.98, about US$0.12 per patient, enrolment effect not measured. Its failure modes (hard gate blocking downstream criteria, stale notes read as current, scanned records excluded) are TrialBox design risks. |
| Open models match GPT-4 | Not on n2c2 2018 (best open 89.05 % micro-F1 vs the 0.9163 pre-LLM record) |
| 8B local models suffice for CJK notes | Not for schema-heavy extraction (LLaMA-3.1-8B QLoRA micro-F1 0.49 on Japanese SOAP structuring). The bake-off and bench decide per role (§16). |
| Prompt injection is an email risk | The chart is also an injection channel: referral letters, scanned reports (§8, §14) |

### 1.6 What v4 changes against v3

| Area | v3 (3.0-rc1) | v4 (this document) |
| --- | --- | --- |
| Constraints | C-1…C-9: no cloud path, no end-user UI, no Hermes | C-1…C-11: C-2′ on-prem first with hybrid under policy; C-5′ five minimal surfaces; C-10 Hermes as governed front door; C-11 open-data verifiability |
| Deployment | One appliance (topology A only) | Topologies A, B and C from one image set; data classes D0–D4 decide what may cross where (§4, §7) |
| LLM | `tb_common.llm`, one endpoint, a cloud branch to delete | `tb-gateway`, registry with model cards, routing policy, guardrails, eval and shadow pass, redacted trace store (§8) |
| Front door | Email grammar plus single-shot `classify_intent` | Hermes on email, Teams, LINE and admin CLI/TUI; multi-turn clarification; native fallback (§3.4, §9) |
| End-user UX | 25-command grammar; locked XLSX; one PDF per candidate; Teams/LINE carry nothing | Plain words with the exact line proposed back; one XLSX and one evidence PDF per packet; Teams cards; optional review page and CDS card (§3) |
| Admin | Read-only health console, local TOTP | Control plane: G5 proposals with simulation, kill switches, IdP login, no PHI (§3.8) |
| Data | One adapter | Data platform L0–L5 with contracts, reconciliation, DQ, terminology service, MPI, lineage, OMOP CDM 5.4 core, HL7 v2 and CDC (§5) |
| Privacy | Rounding, HMAC, accountant | Data classes, de-identification standard, PET kit, Five Safes/TRE, consent scopes, PHI-guard gate (§7) |
| Core | IR v2; S2 zero-hit exclusion; chunk-set cache; one `potential` | IR v3; criterion library; S2b; sentence-set cache; `potential:data_gap`/`potential:uncertain`; multi-span evidence (§6, §10) |
| Matching, feasibility | M5 two lines; funnel plus tiers | Two-direction engine on the TrialGPT port; recruitability model and forecast ledger; four sponsor packs (§10, §12) |
| Recall | Repeated Clopper–Pearson | Anytime-valid confidence sequences, pooled and weighted; two known-positive lines (§6, §10) |
| Lifecycle | 15 stages, some one line deep | Twelve additions, from screening-visit checklists to financial reconciliation (§2.4) |
| Security, evaluation, plan | SEC list; site data only; R0–R4 and one sprint | Control allocation per component (§14); open-data programme and bake-off (§16); MS0–MS6, site waves, rollback per change class (§18, §20) |
| Naming | Cascade S0–S5 | Cascade S0–S5 plus S2b. Data platform L0–L5. Milestones MS0–MS6. Modules M0–M11. Gates G0–G6. |

**Release-to-milestone mapping used in requirement rows.** §20 is normative. Requirements carried from v3 keep their IDs, and
their release column maps as follows.

| v3 release | v4 milestone |
| --- | --- |
| R0 | MS0 Foundations |
| R1a | MS1 Feasibility on de-identified data |
| R1b | MS2 Pre-screening silent mode (live use from MS3, wave 1) |
| R2 | MS4 Recruitment engine and start-up |
| R3 | MS5 Conduct and data |
| R4 | MS6 Second site and Japan profile |

---

## 2. Product definition

### 2.1 Vision

A coordinator writes to TrialBox the way they would write to a colleague. They can use email, Teams or, for reminders only,
LINE, in Chinese, English or both. They attach a protocol or a sponsor questionnaire, or simply ask: 「這個試驗我們做得起來嗎？」.
TrialBox answers in the same thread. It says what it understood, asks what it must, and proposes the exact action. One
"OK" later, the work runs.

By the next morning the coordinator has the criteria as the box understood them and, after a release approval, a
sponsor-ready feasibility pack and the sponsor's questionnaire filled in, every number traceable to a rule, a data cut and
a lineage id. Once the study opens, each investigator receives a weekly clinic-day packet (one spreadsheet, one evidence
PDF) of patients with upcoming appointments who probably qualify, with chart quotes and a certified bound on how many the
filter may have missed. The investigator answers in plain words; TrialBox writes back the exact decision lines for a
one-word confirmation. Until archiving, TrialBox tracks the study, assembles start-up, conduct, monitoring and close-out
paperwork, and nudges the team about what is due.

It runs on one box in the hospital or in the hospital's own cloud tenant. Patient data never reaches a model outside the
hospital's perimeter. There is no portal: the only screens are a signing page, an optional review page, an optional EHR
card and the administrators' control plane. TrialBox measures its own accuracy on open data before it sees a patient.

**Positioning statement.** For hospital research offices and investigators in Taiwan, and next in Japan, TrialBox is an
independent, hospital-owned trial agent for the whole site-side lifecycle. Unlike vendor screening services, it keeps
patient data and model inference inside the hospital, and it certifies how many eligible patients its filter may miss. It
works through the channels staff already use. §19 has the competitive detail.

### 2.2 Independence

Independence is a product property, verified at every release (§15, §19):

| Rule | Verification |
| --- | --- |
| No code path, connector, format or contract term for exchange with a screening or recruitment vendor (C-1); TrialBox never reads or writes a co-installed competitor's data | Egress allowlist (§14), connector inventory (§5), contracts register |
| Open-source parts carry no service dependency: Hermes from a vendored, pinned image with catalogue, hosted portal and external logins off (§9); TrialGPT vendored from NCBI | SBOM and ML-BOM review (§14, §17) |
| Cloud providers appear only as routing-policy targets with recorded zero-retention terms; never D3/D4, never a TrialBox key | Routing-policy property tests (§8); egress test (§14) |

### 2.3 Users and roles

| Role | Typical person | Works with TrialBox through | Access |
| --- | --- | --- | --- |
| Research coordinator (CRC) | Study coordinator, research nurse | Conversation (email, Teams); attachments; optional review page; G1, G4 | PHI for delegated studies |
| PI, sub-investigator | Attending physician | Weekly packet; plain-word replies; Teams card; signing page (G6); optional CDS card | PHI for their studies |
| Research office / CTC | Feasibility desk, CTC manager | Aggregate analyst; monthly portfolio report; G2; owns the delegation log | Aggregates; PHI only with a delegation |
| Data steward | Medical-informatics staff | Atlas workbook (G0); DQ and quarantine emails | Metadata, DQ results, de-identified samples |
| Honest broker | De-identification office | Linkage requests by email; PPRL tokens (§7) | Link tables held by the broker, never by the box |
| Privacy officer (DPO) | Data-protection officer | Signs off D2 egress, D2 releases, cross-border analyses (§7) | Privacy ledger; no PHI |
| IRB / QA / infosec | Reviewers, auditors, SOC | QA pack; audit export; SIEM feed (§14) | Read-only audit and reports |
| System owner | Head of research IT or CTC | Accountable for the validated state; co-signs G5 with QA; approves re-enabling after incidents | No PHI |
| Administrator (controller) | Hospital IT | **Admin control plane**, `trialbox` CLI/TUI and the admin copilot. Operates schedules, switches, channels, backups; proposes routing, egress and model changes into G5 (§3.8) | Configuration, policies, system aggregates; **no PHI**; never approves own changes |
| Sponsor / CRO (human recipient) | Feasibility manager, CRA | Released packs by email from a named site person | Aggregates after G2, within budget; no link into the box |
| Sponsor system (machine recipient) | Sponsor feasibility or CTMS platform | Machine-readable attachments to the released email: FHIR `Group` + `EvidenceVariable`, USDM eligibility, Dataset-JSON, hashed manifest (§12) | Same content as the human pack; no inbound API, no pull |
| Alliance root | Coordinating node of an alliance (TACTC/TNet-type) | Receives signed COHORT tables and federated answers; distributes language packs; applies Five Safes | Aggregates with the ε ledger (§7, M11) |
| TrialBox core agent | Orchestrator workflows | Acts for a named user | Never more than that user; T2 tools only in workflow steps |
| Hermes front door | Conversation engine (C-10) | Front-door MCP tools for the authenticated sender | No PHI tools, schedules, approvals or writes |

### 2.4 Lifecycle coverage

Every stage has an agent behaviour. "Model time" says whether the stage spends LLM time and on what. "Input class" is the
highest data class a model sees in that stage (§7). Module allocation is normative in §10.

| # | Stage | What the agent does | Module | Model time | Input class | MS |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Site readiness | Data Atlas and catalog; contracts; DQ scorecard; lexicon growth; site master profile | M0, ML | small: mapping proposals from schema | D1 | MS0–MS1 |
| 1 | Protocol intake | Parses PDF/DOCX/ICH M11/USDM; match-then-draft I&E extraction; schedule of activities; protocol Q&A with citations | M1 | yes | D1 | MS1 |
| 2 | Protocol optimisation | Criterion impact, what-if, relaxation with safety proxies (internal only) | M2 | no | – | MS4 |
| 3 | Feasibility | Attrition waterfall, sampled tiers, recruitability projection, competing trials; sponsor questionnaire with answer memory | M3 | sample only | D3 (sample), D1 | MS1 |
| 4 | Site selection | Site qualification pack, past performance, start-up timelines | M3 | no | – | MS4 |
| 5 | Start-up | IRB package pre-fill and **IRB e-submission package** in the IRB system's import format; CTA budget from the SoA with NHI standard-of-care split; delegation and training expiry | M7 | drafting only | D1 | MS4–MS5 |
| 6 | Pre-screening | Cascade per study; portfolio clinic-day lists; watchlist flip dates; decision packets; recall certificate | M4 | residue only | D3 | MS2–MS3 |
| 7 | Patient → trial | Open studies (compiled rulesets) and registry trials (TrialGPT retrieval and judgement) for one patient; tumour-board batches | M5 | residue only | D3 (patient), D0 (registry) | MS2 (open studies), MS4 (registry) |
| 8 | Consent and enrolment | Pipeline; consent versions and re-consent; **screening-visit eligibility checklist** pre-filled from evidence for the investigator to confirm per criterion (never marked "eligible"); forecast | M6 | no | – | MS4 |
| 9 | Conduct | Visit windows; **retention and visit adherence** (missed-visit risk); deviation candidates with CAPA log; SAE/SUSAR clocks; **IP accountability prompts** (dispensing-log reconciliation, temperature excursions; no randomisation data); **lab-kit and sample logistics**; **participant reimbursement reminders**; hospital-flagged events listed | M7 | no | – | MS5 |
| 10 | Oversight | **RBQM KRIs** (deviation rate, query rate, SAE lateness, consent-version lag) in the Monday digest; **TMF/ISF completeness** against the ICH E6(R3) essential-records list; **DSMB support** (event listings); **sponsor-query SLA tracking** | M7 | no | – | MS5 |
| 11 | Data | eCRF pre-fill with lineage; SDV source packets; EDC query-answer drafts from source; critical-field gaps | M8 | extraction | D3 | MS5 |
| 12 | Monitoring | Visit preparation pack: source packets, deviation log, ISF index, KRI snapshot | M7, M8 | no | – | MS5 |
| 13 | Reporting during conduct | Monthly accrual pack (§12): pipeline, screen-fail and decline Pareto mapped to criteria, actual vs projected, early warnings; site-performance pack on request | M6, M9 | narrative drafting only, numbers deterministic | aggregates (D1) | MS4 |
| 14 | Close-out | Final IRB report draft; registry deadlines; archive export (PDF/A + JSON); **study-level financial reconciliation** (visits completed × budget table); forecast-ledger scoring; retrospective feeding site learning | M9 | drafting only | D1 | MS5–MS6 |
| 15 | Investigator-initiated trials | ICH M11-template protocol skeleton drafted from a concept sheet, under G1-like review | M1, M7 | drafting | D1 | MS5 |
| 16 | Reimbursement | NHI navigation and TWPAS (v1 NAV) | M10 | as v1 | D3 | MS1 (carried) |
| 17 | Networked research | Alliance cohorts; federated feasibility with the privacy accountant; alliance language packs; OMOP endpoint for OHDSI studies | M11 | no | aggregates | MS5 |
| – | Conversation (all stages) | Requests, clarifications, status, protocol Q&A, aggregate questions, admin copilot | Hermes / native | yes (interactive) | D1, or D3 after identifier redaction, on-prem only (§3.4) | MS0 onward |

These remain out of scope and are listed as non-goals in §2.6: randomisation, IP dispensing, unblinding, eConsent signing,
and patient contact.

### 2.5 Intended use and regulatory position

**Intended use statement.** It is normative and unchanged from v3. It MUST appear in the user guide, in every report footer,
on the admin control plane, on the review page and in the CDS Hooks card detail:

> TrialBox supports research staff in identifying candidate participants for clinical trials, preparing feasibility estimates
> and organising trial operations. All eligibility determinations are made and documented by the investigator. TrialBox is
> not intended to diagnose, treat, mitigate or prevent disease or to inform an individual patient's clinical management.

**Device status.** With this intended use, TrialBox is most likely not a medical device in Taiwan (Medical Devices Act; TFDA
guidance on software classification), the US (FDA CDS guidance), the EU (MDR; MDCG 2019-11) or Japan (PMDA SaMD guidance).
The written intended-use analysis (CMP-28, §15) MUST be completed before any of these ship:
- patient → trial matching on clinician request (M5);
- the CDS Hooks card (§3.5);
- listing abnormal results for enrolled participants (M7);
- anything that would infer an undiagnosed condition, recommend treatment, or set eligibility without investigator
  sign-off.

TrialBox lists hospital-graded events. It never grades them.

**GCP computerised system.** TrialBox MUST meet:
- ICH E6(R3) (Annex 1, data governance);
- 21 CFR Part 11-equivalent controls for the records it signs (§3.7, §15);
- the EMA Guideline on computerised systems and electronic data in clinical trials (2023);
- GAMP 5 (2nd ed.) with FDA CSA as the validation approach (§16).

**AI governance.** These apply to the LLM functions:

| Instrument | Status | What v4 does |
| --- | --- | --- |
| Taiwan AI Basic Act | In force since 14 Jan 2026; principle-level; MODA risk framework unpublished as of Sept 2026 *(uncertain)* | Human in the loop at every gate; AI disclosure on outputs; remedy route via the research office; minimisation by class |
| FDA–EMA Guiding Principles of Good AI Practice in Drug Development (Jan 2026) | Non-binding | Context-of-use record per LLM role with risk tier, evidence and life-cycle plan (§8, §15) |
| ISO/IEC 42001:2023 | Certifiable | AI policy, impact assessment, supplier controls (model providers, Hermes) in the QMS (§15) |
| EU AI Act; Japan AI Promotion Act (2025), APPI | Only for EU parties; Japan profile *(details uncertain)* | Analysed per project and before MS6 (§15) |

**Hybrid topology and the law.** In topology C the hospital is the controller and the cloud provider a processor. D1 data
(for example protocol text) reaches a cloud model only with the sponsor's written consent for that protocol. D2 data
reaches one only with a re-identification risk at or below threshold, a PDPA cross-border analysis, and IRB and DPO
sign-off. D3/D4 never do (C-2′). §7 and §15 are normative.

### 2.6 Non-goals

- Randomisation, IP dispensing, unblinding, or any access to treatment-arm data.
- Writing to the EHR, CTMS or a sponsor EDC. TrialBox produces files; people upload them. The CDS card writes nothing.
- Patient-facing messages, eConsent signing or patient contact. LINE is a staff channel only.
- **Sending D3 or D4 data (pseudonymised or identified) to any model outside the hospital's perimeter, in any topology.**
- Patient-level data leaving the hospital other than releases a named person approves under G2.
- Vendor telemetry, vendor remote access, or a hosted TrialBox run by anyone but the hospital.
- An end-user portal, dashboard or web application beyond the five C-5′ surfaces.
- Autonomous actions: no model output releases data, changes a Study Card or contacts anyone without a confirmed proposal
  and its gate.
- Hermes holding PHI tools, schedules, approvals or write access (C-10).
- Interoperation with third-party screening or recruitment vendors (C-1).
- Grading adverse events, inferring undiagnosed conditions, or recommending treatment.

---

## 3. Experience

### 3.1 One surface per role

C-5′ allows five surfaces. Each role gets the fewest that do its job.

| Role | Primary surface | Minimal UI allowed | Never |
| --- | --- | --- | --- |
| PI / sub-I | Weekly packet (one XLSX, one bookmarked evidence PDF); plain-word replies with the exact lines proposed back; Teams card "3 candidates waiting" | Signing page; optional CDS Hooks card (opt-in per site) | Portal, dashboards |
| CRC | Conversation (email, Teams) for requests, status, five-minute review; decision sheets | Signing page; optional review page from the packet | EDC upload, patient contact |
| Research office | Portfolio report; aggregate analyst; G2 by reply | None | PHI |
| Data steward | Atlas workbook; DQ and quarantine emails | None | PHI |
| IRB / QA / infosec | QA pack; audit export; SIEM feed | Read-only audit search on the admin listener *(optional)* | PHI |
| Sponsor / CRA | Packs by email from a named site person | None | Any link into the box |
| Administrator | **Admin control plane** (§3.8), all of it also in the CLI/TUI | – | PHI |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-12 | **Surface inventory.** The product MUST expose to end users only the five C-5′ surfaces. A CI test enumerates every HTTP route on every listener and every outbound channel template, and fails on any route or template that does not belong to a listed surface. | T | MS0 |
| FR-UX-13 | **Consolidated packet.** A clinic-day packet MUST consist of one encrypted XLSX (one row per candidate) and one encrypted, bookmarked PDF. The PDF has one section per candidate, in XLSX row order, with per-criterion evidence quotes and the recall certificate. It replaces v3's one PDF per strong candidate. | T | MS2 |

### 3.2 Stages for one study

Every study goes through the same stages. Each is a short exchange in the user's channel.

| Stage | The user says | TrialBox returns (by the next model window, §4) | Gate |
| --- | --- | --- | --- |
| 0 Connect (once per site) | Nothing; IT points the box at its sources (§5) | **Atlas workbook** to the steward: mappings, contracts, DQ scorecard, lexicon candidates, questions | G0 (steward) |
| 1 Ask | A protocol (PDF/DOCX/M11/USDM), pasted I&E or a questionnaire, in any words | **Understanding message:** each criterion matched to the library or drafted, how it is computed, computability, numbered questions with defaults; **criteria workbook** | G1: `APPROVE G1-… sha=…` (CRC) |
| 2 Answer | Nothing (G1 triggers it) | **Feasibility pack** (§12) with recruitability projection p10/p50/p90; **sponsor questionnaire** with provenance sheet; draft cover email | G2 (PI or research office); sent to the recipient named in the request |
| 3 Find | 「GZQO 開始收案，林醫師和王醫師的門診，每週」 | **Weekly clinic-day packet** per PI (FR-UX-13) with the recall certificate | G3: plain words → proposed lines → `OK` (PI) |
| 4 Track | 「P0156 今天簽同意書了」 | **Monday status**: pipeline, forecast against target, KRIs, what is due | G4 per state change |
| 5 Run | Nothing (calendar-driven) | Nudges (visit windows, SAE clocks, continuing review, consent version, training and kit expiry); monitor-visit packs | Level A for operational records; G6 (Level B) for regulated records |
| 6 Close | 「GZQO 結案」 | Archive bundle, final IRB report draft, financial reconciliation, forecast-ledger score | G2 for anything external |

The **Study Card** is the single record of a study: protocol versions, rulesets, releases, pipeline, timeline and lineage
ids. It is never a web page. "GZQO 現在怎樣?" or `STATUS GZQO` returns it as a PDF with a short summary in the body.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-19 | Every reply about a study MUST end with a "changed since your last message" block, computed from the Study Card event log. Status answers MUST come from the Study Card, never from model memory (see FR-AG-3, §10). | T | MS1 |

### 3.3 Message rules

FR-UX-1, 4, 5, 7 and 8 carry over from v3 unchanged. FR-UX-9, 10 and 11 replace v3 FR-UX-2, 3 and 6, which are retired.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-1 | Every outbound message MUST state, in its first three lines: what this is; what the recipient needs to do, or "no action needed"; and the deadline. | T | MS1 |
| FR-UX-4 | **Decision sheets.** Any list that needs decisions (candidates, criteria, mappings, questionnaire gaps) MUST be sent as XLSX with locked data columns and one editable decision column (data-validation dropdowns). A returned sheet is parsed and validated: the row hash and file hash must match what was sent. The box echoes back the parsed decisions for approval before applying them. | T | MS1 |
| FR-UX-5 | **Quiet by default.** A user receives at most one digest per day per role, unless a gate is due within 24 h or a safety clock is running. Each user can set `DIGEST daily\|weekly\|off` by reply. | T | MS2 |
| FR-UX-7 | The language of each message follows ML-9 (§10): the recipient's preferred language for prose, the template language for regulated artefacts. | T | MS1 |
| FR-UX-8 | Attachments are generated deterministically from data objects (v1 renderer). Fonts are embedded (Noto Sans CJK TC/JP). XLSX uses frozen headers and filters, and has no macros. | T | MS1 |
| FR-UX-9 | **PHI by channel class.** Outbound message bodies on every channel MUST NOT contain PHI. Patient-level content travels only in encrypted attachments to delegated internal recipients (§14), or on the signing and review pages. Pseudonymous candidate aliases (for example `P0156`) MAY appear in bodies addressed to delegated recipients. Inbound text is classified per channel class: **internal email and Teams are PHI-tolerant**, and their text is classed as PHI-bearing, with identifiers tokenised before any model and redacted at storage (§7); **LINE is no-PHI**. Inbound free text about a patient is never quoted back. | T | MS1 |
| FR-UX-10 | **Two ways to say everything.** Every action MUST be expressible both as an exact grammar line (Appendix D) and in plain words to the conversation engine, which proposes the exact line (§3.4). Each message that asks for an action prints the lines it accepts. Lines typed exactly run without a model. | T | MS1 |
| FR-UX-11 | **Teams and LINE.** Teams MAY carry adaptive cards with no PHI and no study-level counts beyond "N items waiting" (FR-UX-14), plus conversation for requests, status and questions. LINE MAY carry outbound nudges only: "You have 1 item in TrialBox waiting in your mailbox". LINE nudges carry no study identifiers, counts or PHI. LINE inbound text is answered only with a canned pointer to email or Teams. | T | MS4 |
| FR-UX-14 | **Teams adaptive card.** A card MUST contain: item type, count, due date, and one button that opens the user's mailbox thread or the review page. It MUST NOT contain names, aliases, study codes (unless the site sets `teams.show_study_code: true`), or approval actions (FR-SIG-8). Cards are delivered through the channel layer from pre-rendered, DLP-checked templates (§9). | T | MS4 |
| FR-UX-15 | **Plain-text alternative.** Every HTML email MUST include a `text/plain` part with the same first three lines and the same reply lines. | T | MS1 |

### 3.4 The conversation model

#### 3.4.1 Channels, identity and the order of intake

Hermes is the conversation engine (C-10). The orchestrator stays the system of record for requests, proposals, gates and
schedules. Hermes holds conversations and calls the front-door MCP tools (§9). With `channels.engine: native`, a thin
in-house engine (`services/channels/native/`) provides the same behaviour with the single-turn `classify_intent` proposal
flow of v3.

| Channel | Sender identity | Class | What it accepts | What it delivers |
| --- | --- | --- | --- | --- |
| Internal email | DMARC-aligned personal mailbox bound to a directory entry and delegation row (v1 intake) | PHI-tolerant | Lines, plain words, attachments (via CDR, §14), Level A approvals | Everything, incl. encrypted attachments and gate requests |
| Teams | Entra ID, tenant-restricted, mapped to the directory entry | PHI-tolerant (site may set no-PHI) | Lines, plain words; **no approvals** | Replies, cards (FR-UX-14) |
| LINE | User id paired once by an email-confirmed code | No-PHI | Nothing actionable | Nudges (FR-UX-11) |
| Admin CLI/TUI | IdP login, management VLAN | No PHI | Copilot questions; admin-typed commands | Health, reports, drafted commands |
| External mail | Not allowlisted | Untrusted | Nothing; quarantined. Documents enter only when staff forward them. | – |

Intake runs in this order, for every inbound message and every channel:
1. **Authenticate** per the table. Unknown senders get no reply; an audit event is written.
2. **Strip** quoted history and signatures (v3 rules: `>` blocks, `On … wrote:`, `寄件者:`/`差出人:`, Outlook separators).
3. **Classify and redact** with the PHI guard. In PHI-tolerant channels identifiers (MRN, national ID, ARC, phone, names)
   become tokens before any model sees the text; in no-PHI channels a hit drops the message with a canned pointer.
4. **Parse the exact grammar** (`libs/tb_common/subject.py`, `services/mail_gateway/intake.py`). A line that parses runs
   deterministically, with no model. Approval lines are accepted only from email (FR-SIG-8).
5. **Converse.** Remaining free text goes to the conversation engine. Its model calls go through `tb-gateway` with the
   declared class: D1 for text without patient content, D3 for redacted text from PHI-tolerant channels. Both route to
   on-prem builds only (§8).
6. **Propose.** Anything with an effect becomes a proposal rendered by the orchestrator (§3.4.2). The engine never renders
   the command itself.

#### 3.4.2 From free text to proposal to confirmation

A **proposal** is an orchestrator object (`libs/tb_common/conversation.py`, table `conversation_proposal`) with these
fields:
- `proposal_id`, `thread_ref`, `sender`, `channel`;
- `commands[]`: exact grammar lines;
- `restatement`: plain language, in the sender's language;
- `defaults[]`: each default applied, with its source;
- `gate`: the gate the commands will need;
- `sha256` over the canonical JSON;
- `expires_at`, default 72 h;
- `status`: `open | confirmed | superseded | expired | withdrawn`.

The conversation engine fills a typed **intent** (`tb.submit_request(type, structured_intent)`), for example
`{kind: "candidate_decisions", refs: [{row: 1, action: "confirm"}, …]}`. The orchestrator resolves the references against
the objects of the thread (packet rows, criteria numbers, study codes) and renders the exact lines. The engine never sees the
alias list behind row numbers, and never invents an identifier.

```
free text ──► intent (Hermes or native) ──► orchestrator resolves refs, applies policy ──► proposal (lines + restatement + hash)
      ▲                                                                                           │
      └──── clarification (≤ 3 turns) ◄── missing / ambiguous / out-of-scope ◄────────────────────┤
                                                                                                  ▼
                               sender replies OK (or edits a line) ──► gate (if any) ──► workflow starts
```

Four rules govern the loop (FR-CONV-3…5): clarify only what blocks a proposal, then propose with listed defaults;
recipients and scope come from the delegation log and Study Card, never from words; `OK` binds to one open, unchanged
proposal; read-only aggregate requests (`STATUS`, `HELP`, `ASK`, `ATLAS`, analyst questions) are answered without a
confirmation step.

#### 3.4.3 Behaviour per role

| Role | What the engine does | Tools it may use (§9) | It never |
| --- | --- | --- | --- |
| CRC | Turns requests into FEAS, QFILL, SCREEN, STATE, STUDY, WHATIF, ASK, DIGEST proposals; answers status and "what is due"; runs the five-minute review by numbered questions | `tb.submit_request`, `tb.status`, `tb.ask_protocol`, `tb.resend_released_file` | Reads patient data; sends to a sponsor |
| PI / sub-I | Turns plain-word candidate decisions into CONFIRM/REJECT/DEFER lines; answers protocol questions with citations; points to the packet section that holds the evidence | `tb.submit_request`, `tb.status`, `tb.ask_protocol` | Says "eligible"; reads the chart |
| Research office | Aggregate analyst: answers portfolio questions over T1 aggregates through the privacy accountant; drafts sponsor cover notes; reminds about G2 items | `tb.aggregate_query`, `tb.status`, `tb.registry_search` | Returns a cell below the small-cell rules; releases anything |
| Data steward | Explains Atlas findings, DQ failures and quarantine reasons; proposes lexicon or mapping lines for G0 | `tb.atlas_describe`, `tb.submit_request` | Approves G0 |
| IRB / QA | Answers questions about the QA pack; files audit-export requests | `tb.status`, `tb.submit_request` | Edits records |
| Administrator (CLI/TUI) | Admin copilot: reads health, queues, bench, eval, gateway and Hermes panels; explains alarms; **drafts** `trialbox` commands and runbook steps for the admin to run | Read-only admin MCP tools (§9) | Executes a command; changes a policy |

#### 3.4.4 Examples

**Coordinator, zh-TW (email).**

| The coordinator writes | TrialBox replies |
| --- | --- |
| 「這個試驗我們做得起來嗎？贊助商週五要數字」 + protocol.pdf | 「我理解為：為這份計畫書做院內可行性評估，範圍全院，回溯 24 個月，期限 2026-10-23（週五）。研究代碼暫定 GZQO。<br>`FEAS NEW scope=hospital lookback=24m deadline=2026-10-23`<br>預設值：回溯期 24 個月（院內慣例）。請回覆「OK」，或修改後回覆。」 |
| 「回溯改成三年」 | New proposal, the old one superseded: `FEAS NEW scope=hospital lookback=36m deadline=2026-10-23` |
| 「幫我填這份問卷」 + sponsor.xlsx | `QFILL GZQO`, with "23 of 31 questions can be answered from site data; 8 need you (list attached)" |
| 「GZQO 開始收案，林醫師和王醫師的門診，每週」 | `STUDY GZQO recruiting` and `SCREEN GZQO scope=practitioners:P12345,P23456 cadence=weekly`. The practitioner ids come from the delegation log. If Dr. Wang is not delegated on GZQO, the reply says so and leaves him out. |
| 「P0156 今天簽同意書了」 | `STATE P0156 consented 2026-10-17`. The reply `OK` is the G4 approval. |
| 「下週有什麼要做的？」 | Direct answer from the Study Cards (no proposal): three items with deadlines, ranked as in FR-AG-6 |

**Coordinator and research office, English (Teams).**

| The user writes | TrialBox replies |
| --- | --- |
| "How many if we drop the BMI criterion?" (on the FEAS thread) | `WHATIF GZQO drop INC-07` (internal only, never released). The result arrives by email after the next pass. |
| "Is prednisone 10 mg allowed?" | `ASK GZQO "prednisone 10 mg"`, answered directly from the protocol with section citations (FR-M1, §10). No patient data is used. |
| "Which of our oncology studies are behind target this quarter?" (research office) | A direct answer from aggregates: "3 of 11 are below 70 % of the projected p50: GZQO, …". Counts are rounded per the small-cell rules, with the data cut stated. |
| "Send the GZQO numbers to the sponsor today" | "I can't choose recipients from a message. The release goes to the recipient named in the original request (`feasibility@…`) once G2 is approved. The G2 request went to Dr. Lin on 16 Oct and is still open; I have added a reminder to her next digest." No proposal is needed: the reminder is a read-only nudge to the existing gate. |

**Investigator, zh-TW (reply to the packet email).**

> 「1跟3可以約，2上個月剛開完刀先不要，4下個月回診再看」

TrialBox replies:

```
您的決定（G3-0412，2026 第 43 週候選名單，雜湊 4be1c2d97a0e31f5）：
CONFIRM P0156 P0203
REJECT P0177 R03   （附註已保存，不在郵件中顯示）
DEFER P0190 2026-11-17
請回覆「OK」確認，或修改上面任一行後回覆。
```

The engine produced only the intent. The orchestrator resolved rows to aliases from the replied-to packet and mapped
"剛開完刀" to R03 (clinically inappropriate). The PI's words are stored redacted and appear only in the encrypted sheet.
"下個月回診" became the next appointment date from the scheduling feed (or today + 30 days, stated in the reply).

**Investigator, English (Teams).** "Confirm the first two, skip the rest for now." The engine replies in Teams: "I've sent
the decision lines to your mailbox for confirmation." The proposal goes by email, because approvals are email-only
(FR-SIG-8).

**Japan profile, ja (email).** 「この試験、当院で何例くらい見込めますか？」 becomes a FEAS proposal with defaults
in Japanese (ML-10, MS6).

#### 3.4.5 Requirements

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-CONV-1 | Intake MUST run in the order of §3.4.1: authenticate, strip, classify and redact, exact grammar, converse, propose. A line that parses exactly MUST NOT be sent to a model. | T | MS0 |
| FR-CONV-2 | The conversation engine MUST produce typed intents through `tb.submit_request` only. The exact command lines in a proposal MUST be rendered by the orchestrator from the resolved intent. A CI test asserts that no Hermes or native-engine output string is ever executed as a command. | T | MS0 |
| FR-CONV-3 | Proposals MUST carry the fields of §3.4.2, MUST expire (default 72 h), and MUST be superseded when the referenced objects change. `OK` confirms only an `open`, unchanged proposal in the replied-to message, from the same sender. | T | MS1 |
| FR-CONV-4 | Clarification MUST be limited to three turns or 48 h per conversation. Each question MUST be numbered and carry a proposed default. After the limit, the engine proposes with the listed defaults or closes with a summary. | T | MS1 |
| FR-CONV-5 | Recipients, delegations, external targets and scope beyond the sender's delegations MUST NOT be taken from free text (SEC-13, §14). A request that exceeds them is refused with the reason and a proposal for the permitted alternative. The engine MUST NOT reveal whether a named patient exists to a non-delegated user. | T | MS1 |
| FR-CONV-6 | Conversation state of record (proposals, clarifications, references) MUST live in the orchestrator (`conversation_*` tables), so a conversation survives an engine switch. Hermes memory is off by default (§9). Hermes session state MUST NOT be needed to complete any request. | T | MS0 |
| FR-CONV-7 | **Native parity.** With `channels.engine: native`, every example in §3.4.4 MUST produce the same proposal lines, except that multi-turn clarification collapses to one numbered round. The intake e2e suite runs on both engines. | T | MS0 |
| FR-CONV-8 | Model calls made for a conversation MUST declare their class: D1, or D3 when the text came from a PHI-tolerant channel. They MUST resolve to on-prem builds only, whatever the topology. | T | MS0 |
| FR-CONV-9 | **Plain-word candidate decisions.** Replies to a packet thread MUST be resolved against that packet's rows by row number, alias or position words ("the first two"). Free-text reasons MUST be mapped to reason codes R01–R07, with the original text kept redacted and never echoed in a body. Relative dates MUST be resolved from the scheduling feed or a stated default, and the reply MUST say which. | T | MS2 |
| FR-CONV-10 | A decision expressed outside email (Teams) MUST produce a proposal delivered to the person's mailbox. The approval is the email reply. | T | MS4 |
| FR-CONV-11 | The engine MUST reply in the language of the user's message, falling back to the preferred language (ML-9). Mixed zh/en messages are answered in the dominant language of the message. Grammar keywords and codes stay in ASCII. | T | MS1 |
| FR-CONV-12 | The admin copilot MUST NOT execute commands or change state. Its tool set is read-only, and drafted commands are printed for the administrator to run. | T | MS0 |
| FR-CONV-13 | The aggregate analyst MUST answer only through `tb.aggregate_query`. Every answer passes the small-cell rules and the privacy accountant and states the data cut. A question whose answer would breach a rule gets the refusal reason, not a partial number. | T | MS1 |
| FR-CONV-14 | External and unauthenticated senders MUST NOT reach the conversation engine. Their mail is quarantined. Attachments forwarded by staff pass the CDR container, and their text enters prompts only inside delimited untrusted blocks (§8, §14). | T | MS0 |
| FR-CONV-15 | Proposal accuracy MUST be measured on a bilingual set of at least 300 synthetic requests (zh-TW, en, code-mixed), with expected lines. The gate is exact-line accuracy ≥ 0.95 and zero wrong-recipient or scope-widening proposals (§16). | T | MS1 |
| FR-CONV-16 | Every turn MUST be attributable: `actor_type` (`user`, `agent`, `hermes`), `on_behalf_of`, channel, request id and proposal id, written to the audit ledger before the reply is sent (FR-AG-5, §10). | T | MS0 |

### 3.5 Candidate decisions: packet, sheet, review page and CDS card

There are four ways to decide on candidates. All of them produce the same object: a **decision set** with a canonical hash,
approved once (FR-SIG-6).

| Way | Who | How it works |
| --- | --- | --- |
| Plain words | PI, sub-I | Reply to the packet email (§3.4.4); TrialBox proposes the lines; the PI replies `OK` |
| Lines | PI, sub-I, CRC (DEFER and notes only) | `CONFIRM`/`REJECT`/`DEFER` lines from the packet, copied or typed |
| Decision sheet | PI, CRC | Fill the decision column of the XLSX and reply with it (FR-UX-4). TrialBox echoes the parsed set and asks for `OK`. |
| Review page *(optional, per site)* | PI, CRC | Open the link in the packet. The page renders the same rows with evidence inline. Choose decisions and submit. The approval is recorded through the same hash-bound mechanism. |

**The review page** exists because Excel discipline is a real burden at 20 candidates per clinic day; it never grows into a
portal. It shows one packet, with no navigation elsewhere. Each row shows the alias, the tier (`strong`,
`potential:data_gap` with what is missing and when it expires, `potential:uncertain` with the undecided quotes, …), the
per-criterion verdicts and the verified quotes in the original language, with an optional marked gloss. The only control
per row is the decision dropdown and a note. Submitting shows the parsed decision set and its hash, and "Approve" records a
Level A approval (FR-SIG-11).

**The CDS Hooks card** *(optional, opt-in per site)* is a CDS Hooks 2.0 `patient-view` service (`services/cds_hooks/`)
returning at most one card, "Possible trial match: see this week's packet", after the CMP-28 analysis (§2.5).

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-16 | **Review page access.** The link MUST be single-recipient and expire with the packet (default 7 days). It opens only after hospital IdP authentication of the bound recipient (OIDC, MFA per hospital policy). It is reachable only from the hospital network, on the signing listener (`services/console/review.py`). It has no admin routes and no third-party scripts. | T | MS4 |
| FR-UX-17 | The review page MUST render from the same packet object as the XLSX and PDF, and show the packet hash. A decision submitted on the page MUST produce the same decision set, and the same hash, as the equivalent sheet or lines. A test compares the three paths on one packet. | T | MS4 |
| FR-UX-18 | The CDS Hooks card MUST contain no PHI beyond what the EHR context already shows, no tier, no evidence and no action buttons. It MUST be returned only for a delegated investigator viewing a patient on that investigator's current packet. Every card served is audited. | T | MS5 |
| FR-UX-20 | Decision sheets, the review page and plain-word replies MUST all support partial decisions. Undecided rows stay open and reappear in the next packet, marked "carried over". | T | MS2 |

### 3.6 Configuration without a configuration screen

Carried over from v3, with the data-platform stages of §5:
1. IT installs for its topology (§18) and runs `trialbox doctor`, which prints the fix for every failed prerequisite.
2. IT writes `site/sources.yaml`, one entry per source and stream type (§5).
3. The first L0–L5 run emails the steward the **Atlas workbook** (one sheet per canonical table, contracts, DQ scorecard,
   lexicon candidates). The steward returns it; the box applies it, re-runs, sends a diff and asks for G0.
4. The research office returns the pre-filled **site-profile workbook** and the **delegation log**. The administrator
   imports the log and the research office approves the import diff (Level A).
5. Every confirmed change becomes versioned configuration in Git, shown on the control plane and changed only through the
   classes of §3.8.

### 3.7 Approvals and signatures

#### 3.7.1 Why two kinds

Most gates are operational decisions (a mapping, criteria, an aggregate release, whom to approach). A few create records
a regulator inspects as signed records. Email is an open channel and a mailbox login is "previous system authentication":
NIST SP 800-63B-4 says email SHALL NOT be used for out-of-band authentication, and the EU Annex 11 revision draft (13.3)
rejects relying on a previous login or a PIN alone. So TrialBox never claims an email reply is a Part 11 signature; every
gate has a configured assurance level.

| Level | Mechanism | Used for (defaults) |
| --- | --- | --- |
| **A** attributable approval | Email reply from the delegated personal mailbox, DMARC-aligned, `In-Reply-To` matched, carrying the 16-hex hash prefix (`APPROVE G2-0193 sha=4be1c2d97a0e31f5`). Or a bound `OK` (G3, G4 only). Or the review page with IdP authentication (method `review_page`). | G0–G4 |
| **A2** dual attributable approval | Two hash-bound Level A approvals from different roles (system owner and QA) | G5 until the signing page ships (interim, listed as a time-limited deviation); G5 **fast-track** for reverting to a stricter routing or egress policy (§3.8) |
| **A+** reply with challenge-response *(off by default)* | Level A plus an OCRA (RFC 6287) code from an enrolled authenticator. The challenge is the first 8 digits of SHA-256(gate_id ‖ record_hash ‖ nonce). Plain TOTP is not accepted. | Any Level B gate a site downgrades, with a documented risk acceptance |
| **B** signing ceremony | Single-purpose signing page with full re-authentication. B1: WebAuthn passkey. B2: IdP forced re-login. B3: PKI signature (HCA or MOICA). | G5; G6 (deviation approval, SDV source certification); any gate a site maps to a Part 11 / E6(R3) signed record |

Level A records are attributable, time-stamped, hash-linked and audited. The hospital's research-operations SOP classifies
them as approvals of operational records, not e-signatures under 21 CFR 11. Pre-screening decisions (G3) are of this kind:
the investigator decides whom to approach, not whether a person is eligible. Eligibility is determined at screening, after
consent, in the sponsor's systems.

**Bound `OK` for G3 and G4.** These are high-volume internal gates. `OK` to a proposal that printed its decision-set hash is
accepted as Level A when four conditions hold: the sender is the delegated decider, DMARC passes,
`In-Reply-To` names the proposal, and the proposal is open and unchanged (FR-SIG-9). G0, G1 and G2 keep the explicit
`APPROVE` line: their objects are configurations and releases, where a deliberate second look is the point.

**Hermes never approves.** The conversation engine may deliver a gate request (an email, or a Teams card pointing to the
mailbox) and propose decision lines. It has no tool that records an approval. Approval lines are parsed only by the
deterministic intake on the email path (FR-CONV-1). A Teams message containing an approval line is answered with a pointer
to the email.

#### 3.7.2 The signing page

The signing page is one of the five C-5′ surfaces. It lives in `services/console/signing.py`, on the signing listener,
which serves no admin routes. It is reachable from the hospital network only.

**Flow.**

| Step | The signer sees | The system checks |
| --- | --- | --- |
| 1 Open | "Sign: G6-0031, deviation approval DEV-GZQO-007 v2" and **Identify**; no record content | Link single-use, ≤ 15 min, bound to signer, gate and record hash |
| 2 Identify | Passkey (B1), IdP login (B2) or certificate (B3) | Subject equals the bound signer; otherwise "This link is for another person", audit event, alert to the research office |
| 3 Review | The record from the same renderer and canonical object as the attachment; full SHA-256 and prefix; meaning from the controlled list; attestation in zh-TW and English | Hash recomputed; on mismatch "This record changed; a new request has been sent" |
| 4 Sign | **Sign**, then a second assertion | B1: WebAuthn, challenge = record hash ‖ nonce, user verification required. B2: OIDC `prompt=login`, `max_age=0` (or SAML `ForceAuthn`), `auth_time` checked. B3: CAdES/PAdES with OCSP. |
| 5 Receipt | Receipt id, name, meaning, time (UTC and Asia/Taipei), method; **Close** only | `signature` record (§6) written, receipt emailed, link dead |

Steps 2 and 4 are the two signings of one continuous session under 11.200(a)(1). Batch signing (several SDV packets of one
visit) lists every record with its hash and signs one manifest hash (FR-SIG-6).

**Page rules.** No navigation, search or other records. Server-rendered HTML; the WebAuthn call is the only script, served
from the box. Headers: `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`, `Referrer-Policy:
no-referrer`, `Cache-Control: no-store`. The signature manifestation (11.50: printed name, date and time, meaning, both
languages) appears on every rendering of the signed record.

**Passkey enrolment (B1).** Enrolment is an admin-assisted ceremony on the signing listener. The research office verifies
identity in person (11.100(b)) and starts a one-time enrolment link. The signer registers the passkey. The ceremony is
audited, and the enrolment record names the verifier.

#### 3.7.3 Requirements

FR-SIG-1…8 carry over from v3. Their release column maps to milestones as in §1.6.

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-SIG-1 | Every gate MUST have a configured assurance level (A, A2, A+ or B). Defaults: G0–G4 A; G5 and G6 B. A Level B gate MUST NOT be satisfiable by any email reply unless A+ is enabled for that gate. **Interim rule until FR-SIG-3 ships:** G5 is satisfied by two hash-bound Level A approvals from different roles (system owner and QA), recorded as `assurance: A2` and listed in the validation pack as a time-limited deviation. | T | MS1 |
| FR-SIG-2 | Level A: an approval MUST be rejected if the hash in the reply differs from the current object, or if the object changed after the request was sent. In that case a fresh request is sent. | T | MS1 |
| FR-SIG-3 | Level B signing page: single-use link (≤ 15 min, bound to signer and gate); methods B1 and B2. The `signature` record (§6) MUST hold the printed name, user id, role, meaning, UTC time with the Asia/Taipei offset, record hash, method, and the WebAuthn or IdP assertion reference (11.50, 11.70). | T | MS2 |
| FR-SIG-4 | Negative tests MUST pass: replayed link; expired link; link forwarded to and opened by another user; stale SSO session (must prompt); record changed after signing (renders "unsigned"); clock skew; lockout after 3 failures with an alert to the research office (11.300(d)). | T | MS2 |
| FR-SIG-5 | B3 PKI signature with HCA or MOICA, where the hospital provides the middleware. | T | MS4 |
| FR-SIG-6 | Signed or approved batches (decision sheets, decision sets, signing manifests) MUST record one approval or signature over the hash of the parsed set. The receipt lists every decision. | T | MS2 |
| FR-SIG-7 | The box MUST ship the validation pack for approvals and signatures. It contains: a trace matrix to 11.10/11.50/11.70/11.100/11.200/11.300 and the EMA computerised-systems guideline §4.8; the negative tests; an identity-proofing SOP template; the 11.100(c) non-repudiation letter template; and a Taiwan internal e-signature policy template. Under B2, password controls (11.300) are the hospital IdP's and are referenced as a supplier control. The ESA Art. 5 counterparty-consent record applies only to documents exchanged with another party. | I | MS2 |
| FR-SIG-8 | Teams and LINE MUST NOT carry approvals. A Teams card MAY carry the Level B signing link when the site enables it. | T | MS4 |
| FR-SIG-9 | **Bound `OK`.** For G3 and G4 only, `OK` MUST be accepted as Level A when the four conditions of §3.7.1 hold. The approval record stores method `reply_ok_bound` and the proposal's full hash. For every other gate, `OK` MUST be refused with the exact `APPROVE` line to use. | T | MS2 |
| FR-SIG-10 | **No approvals through the conversation engine.** No front-door MCP tool and no Hermes or native-engine output MAY create an approval or signature record. A test drives every channel and engine with approval lines and natural-language "approve" variants, and checks that approvals are recorded only from the email intake, the review page and the signing page. | T | MS0 |
| FR-SIG-11 | **Review-page approvals.** A decision set submitted on the review page MUST be recorded as Level A with method `review_page`. The record holds the IdP subject, `auth_time`, link id and decision-set hash. For a gate configured B, submission MUST hand over to the signing ceremony instead. | T | MS4 |
| FR-SIG-12 | **Two-step ceremony.** The signing page MUST NOT render record content before step 2 (identify) succeeds for the bound signer. Step 4 MUST use a fresh assertion bound to the record hash (B1) or a forced re-authentication with `auth_time` after step 3 began (B2). | T | MS2 |
| FR-SIG-13 | Additional negative tests MUST pass: WebAuthn assertion without user verification; credential not enrolled to the signer; IdP subject different from the bound signer; IdP `auth_time` older than the step start; CSRF on the sign action; framing by another origin; link token leaked through `Referer`; double submission from two devices (one signature only); record superseded while the page is open; revoked or expired PKI certificate (B3). | T | MS2 |
| FR-SIG-14 | The signing and review listeners MUST meet OWASP ASVS 5.0 Level 2, with the headers of §3.7.2. They are verified by a DAST run in CI and the yearly penetration test (§14). | T | MS2 |
| FR-SIG-15 | **A2 fast-track.** Reverting the routing policy or egress allowlist to a previously approved, stricter version MAY be approved as A2 (system owner and QA, hash-bound) instead of B. Any change that widens a route, class or egress target MUST be Level B. | T | MS1 |

### 3.8 The admin control plane

The control plane is for administrators. It replaces v3's read-only health console. It is a control surface with no PHI, no
study content and no patient lists. It is server-rendered HTML (`services/console/app.py`), reachable only on the management
VLAN. Login is through the hospital IdP with phishing-resistant MFA. Local break-glass accounts are sealed, and their use
raises an alert (§14).

Everything the plane shows or does is also available as `trialbox` CLI/TUI commands, and the plane is optional
(`console.enabled`). The Hermes admin copilot (FR-CONV-12) reads the same panels and drafts commands; it never runs them.

#### 3.8.1 What an administrator sees

| Panel | Content (aggregate or metadata only) |
| --- | --- |
| Health, schedules | Services, queues, outbox, disk and GPU memory, pass calendar and budgets, bench results, certificate and key expiry |
| Cascade | Per-run manifest metrics (§4): stage counts, model share, cache hits, certificate bounds per study |
| LLM platform | Registry and model cards; routing policy with version and approver; gateway calls, tokens, refusals, class mismatches, latency and cost by role, class and route; guardrail hits; eval, shadow and bake-off reports (§8) |
| Hermes and channels | Engine in use, pinned version and digest, open advisories; sessions, tool calls, policy denials, injection hits, PHI-guard drops per channel |
| Data platform | Freshness and reconciliation per stream; publish gate and quarantines; DQ summary; snapshots; job lineage (no rows) (§5) |
| Privacy | Accountant budget per study; egress counters by class and route; D2 release log (§7) |
| Approvals queue | Gate id, type, role, age, level; **no object content** |
| Security, configuration, identity | Audit-chain and anchor status; backups and last restore test; SIEM forwarding; scans; config and policy history with diffs; pending G5 changes; delegation-log version and expiries |

#### 3.8.2 What an administrator can do

Changes fall into three classes. The rule is asymmetric: **anything that reduces capability, egress or exposure takes effect
at once; anything that widens it goes through G5.**

| Class | Examples | Who and how | Effect |
| --- | --- | --- | --- |
| **Stop** (immediate) | Kill switches (§3.8.3); pause the outbox; pause model passes; disable a cloud route; switch `channels.engine` to `native`; suspend a sender; tighten a rate limit or budget | One administrator. The plane or CLI records a reason; the system owner and QA are notified within 15 min. | ≤ 60 s; audited |
| **Operate** (neutral) | Move a pass within its permitted window; restart a service; run `doctor`, `bench`, `validate`; restore test to the spare; scheduled certificate rotation; import a delegation log (research office approves the diff, Level A); start a DR drill; re-enable a stopped function (after an incident: system-owner Level A with the incident reference, FR-UX-27) | One administrator, audited | As stated |
| **Change** (controlled, G5) | Edit the routing policy; add or widen an egress target; enable a cloud route or a new data class on a route; promote a model, prompt, lexicon or threshold; enable Hermes memory or a new channel; re-enable a cloud route; change gate assurance levels | The administrator proposes. The plane runs the **simulation**, and the system owner and QA approve at Level B (A2 for reverts, FR-SIG-15). The administrator cannot approve their own change. | After approval, through `trialbox apply` with a Git tag; rollback per §18 |

**Routing-policy and egress simulation.** Before a routing-policy or egress change can be submitted to G5, the plane replays
the last 30 days of gateway call metadata against the proposed table. Metadata means role, class, profile, topology, size
and cost, with no content. The report shows:
- calls whose route would change;
- calls that would be refused;
- any call of class D3 or D4 that would reach a non-on-prem build;
- projected cost.

Any D3/D4 call reaching a non-on-prem build fails the simulation, and the change cannot be submitted (C-2′).

#### 3.8.3 Kill switches

| Switch | Scope | Behaviour when off |
| --- | --- | --- |
| `kill outbox` | All outbound messages | Messages stay queued and durable; nothing is sent |
| `kill passes` | Scheduled model passes | Steps stop at the next durable-step boundary and resume later |
| `kill module <M0…M11>` | One module | Requests acknowledged as "paused by the administrator"; gates stay open |
| `kill channel <email\|teams\|line>` | One channel | Inbound gets a canned reply |
| `kill hermes` | Conversation engine | `channels.engine` falls back to `native`; Hermes container stopped; sessions archived; no request lost (outbox) |
| `kill route <id>` / `kill cloud` | One route, or all non-on-prem routes | Gateway refuses them; fallback only to permitted on-prem builds |
| `kill role <llm-role>` | One LLM role | Work waits or takes the deterministic or human path of §4 |

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-21 | The admin control plane MUST show the panels of §3.8.1 and MUST NOT render PHI, study content, protocol text, prompts or model outputs. A test seeds PHI canaries into every store and scans every console and CLI response for them. | T | MS0 |
| FR-UX-22 | Every control-plane action MUST be available as a `trialbox` CLI/TUI command with the same authorisation and audit. The system MUST be fully operable with `console.enabled: false`. | T | MS0 |
| FR-UX-23 | Changes MUST be classed as stop, operate or change (§3.8.2). Stop actions take effect within 60 s and notify the system owner and QA within 15 min. Change actions MUST NOT take effect without the G5 approval of their hash. | T | MS0 |
| FR-UX-24 | The kill switches of §3.8.3 MUST exist, MUST be idempotent, and MUST lose no request or message (durable steps and outbox). Each is exercised in the operational qualification (§16). | T | MS0 |
| FR-UX-25 | Routing-policy and egress changes MUST pass the 30-day simulation before submission. A simulation that routes any D3/D4 call to a non-on-prem build MUST block submission. | T | MS1 |
| FR-UX-26 | **Separation of duties.** An administrator MUST NOT approve a G5 change they proposed, and MUST NOT hold the QA role. Break-glass use MUST raise an alert to the system owner and the SIEM. | T | MS0 |
| FR-UX-27 | Re-enabling a function stopped for an incident MUST record the incident reference and a system-owner approval. Re-enabling a cloud route MUST be a G5 change. | T | MS1 |
| FR-UX-28 | The approvals-queue view MUST show gate metadata only (id, type, role, age, level), never the object, its title or the recipient's decision. | T | MS1 |

### 3.9 Accessibility, mobile email and localisation

| ID | Requirement | V | R |
| --- | --- | --- | --- |
| FR-UX-29 | **WCAG 2.2 Level AA** for the signing page, the review page and the admin control plane. Verified by axe-core in CI on every template and a manual checklist per release: keyboard-only use, focus, target size (2.5.8), accessible authentication (3.3.8), and screen readers (NVDA zh-TW; VoiceOver zh-TW and ja). | T | MS2 |
| FR-UX-30 | **Mobile email.** HTML emails MUST render without horizontal scrolling at 360 px width. Tables are ≤ 600 px wide and degrade to stacked rows. Body text is ≥ 14 px, with contrast ≥ 4.5:1. Tiers and states never rely on colour alone. The first three lines (FR-UX-1) and the reply lines appear before any table. No content exists only in images. | T | MS1 |
| FR-UX-31 | **Accessible attachments.** XLSX: one header row, no merged cells in data regions, named tables, and sheet names in the recipient's language. PDF: tagged, with bookmarks and document language set per section (PDF/UA-1 as the target). Fonts are embedded (FR-UX-8). | T | MS2 |
| FR-UX-32 | **Localisation.** All user-facing strings MUST come from message catalogues (`libs/tb_common/i18n/`, ICU MessageFormat, `zh-TW`, `en`, `ja`). A CI check fails on hard-coded user-facing strings and on missing keys. Regulated templates (attestation, meaning texts, intended use, IRB and sponsor templates) MUST be human-translated and reviewed. Machine translation is never used for them. | T | MS1 |
| FR-UX-33 | **Dates, times and names.** Displayed dates use ISO 8601 by default. A recipient may choose ROC display (民國) for zh-TW or era display (和暦) for ja, but stored values are always ISO. Times show the site zone (Asia/Taipei, or Asia/Tokyo in the Japan profile); signature records also hold UTC. Names follow the locale's order. Terms render as `code — 中文 (English)` (ML-9). | T | MS1 |
| FR-UX-34 | **Language parity in the conversation.** The proposal-accuracy gate (FR-CONV-15) MUST be met in each language stratum (zh-TW, en, code-mixed; ja from MS6) separately, with no stratum more than 5 points below the best. | T | MS1 |
