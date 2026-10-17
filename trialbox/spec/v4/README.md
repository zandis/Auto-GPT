# SPEC — TrialBox v4: the governed, hybrid-ready clinical-trial agent

Version 4.0-draft · Oct 17, 2026 · @Changfu.

**Supersedes:** `SPEC_v3.md` (3.0-rc1). `SPEC.md` (v1.0) stays the build contract for the code that exists today.

**Built from three adversarial review rounds** and six research tracks:
- Reviews: `docs/reviews/SPEC_v2_review.md`, `docs/reviews/SPEC_v3_review.md`, `docs/reviews/SPEC_v3_round3_review.md`.
- Research tracks:
  - data management and FHIR;
  - pharma deliverables;
  - the Hermes agent and LLM operations;
  - cybersecurity;
  - literature and competitors;
  - open data.

Appendix I maps every review finding to the section that resolves it.

TrialBox is an independent, hospital-owned AI agent for the whole site-side clinical-trial lifecycle, Taiwan first and
Japan next. It reads the hospital's EMR, research database and registries through an industrial data platform, filters
patients with compiled rules before any model reads a note, and proves how many eligible patients it may have missed.
It answers sponsors with standard deliverables and helps staff with every later step. People talk to it in plain
language through a hardened Hermes front door, and nobody needs a new portal.

It runs on premises by default. It can also run in the hospital's own cloud tenant, or in a hybrid that sends only
non-patient data to approved cloud models.

## Files

The spec is split into nine files because a single file would be about 1 MB. Section numbers are global.

| File | Sections |
| --- | --- |
| [01_constraints_product_experience.md](01_constraints_product_experience.md) | §0 Binding constraints · §1 Where we are · §2 Product definition · §3 Experience (surfaces per role, Hermes conversation, approvals and the signing page, admin control plane) |
| [04_architecture_llm_hermes.md](04_architecture_llm_hermes.md) | §4 Architecture (topologies A/B/C, C4 views, containers, the cascade S0–S5 + S2b, passes, hardware and bench gate, ADRs) · §8 LLM platform (tb-gateway, registry, routing by data class, guardrails, evaluation, observability, cost) · §9 Hermes Agent (role, front-door MCP tools, hardening, native fallback) |
| [05_data_platform_model_privacy.md](05_data_platform_model_privacy.md) | §5 Data platform (L0–L5 stages; streams for HIS, CDC, CGRD, FHIR Bulk, HL7 v2, registries, cohorts; reconciliation; DQ; terminology; OMOP; identity; lineage) · §6 Data model and contracts (IR v3, criterion library, evidence, certificate, manifests) · §7 Privacy architecture (data classes D0–D4, boundaries per topology, de-identification, PETs, Taiwan/Japan law) |
| [10a_modules_m0_m5_ml_safe.md](10a_modules_m0_m5_ml_safe.md) | §10.0–§10.5 M0 onboarding … M5 matching in both directions · §10.13 ML multilingual · §10.14 SAFE (recall certificate) |
| [10b_modules_m6_m11_workflows.md](10b_modules_m6_m11_workflows.md) | §10.6–§10.12 M6 enrollment … M11 networked research, agent behaviours · §11 Workflows and gates |
| [12_deliverables_nfr.md](12_deliverables_nfr.md) | §12 Pharma deliverables (TrialBox Deliverable Standard: packs, tables, figures, formats, analyses) · §13 Non-functional requirements |
| [14_security_compliance.md](14_security_compliance.md) | §14 Security (frameworks, threat model, identity, keys, network, hardening, LLM/agent controls, SIEM, backup, incident response, control allocation per component) · §15 Compliance (trace matrix, intended use, AI credibility, cross-border) |
| [16_vv_engineering_operations.md](16_vv_engineering_operations.md) | §16 Verification, validation and open data (suites, gates, calibration, bake-off) · §17 Engineering standards · §18 Operations (install, monitoring, **rollback procedures**) |
| [19_positioning_plan_appendices.md](19_positioning_plan_appendices.md) | §19 Positioning · §20 Delivery plan (governance, RACI, environments, milestones MS0–MS6, first sprint, rollout waves, risks) · §21 Open decisions · Appendices A–J |

## How to read it

| You are | Read |
| --- | --- |
| Hospital leadership, research office | §0–§2, §12 (what sponsors receive), §19, §20 |
| Investigator, coordinator | §3, §10 for your stage |
| Engineer or coding agent | everything; start at §4, §5, §8 and the first sprint in §20 |
| QA, IRB, information security | §3 approvals, §7, §14, §15, §16, §18 |
| IT, procurement | §4 hardware and topologies, §13, §14, §18 |

## Conventions

**Requirement keywords.** MUST, SHOULD and MAY are used as defined in RFC 2119 and RFC 8174.

**Requirement rows.** Every requirement is a row `| ID | Requirement | V | R |`:
- V is the verification method: T test, I inspection, A analysis, D demonstration.
- R is the milestone, MS0–MS6 (§20).

Estimates are marked *(est.)*. Facts that could not be verified are marked *(uncertain)* and must be checked before they
are quoted outside the team.

**Requirement ID prefixes:**

| Prefixes | Sections |
| --- | --- |
| C- | §0 |
| FR-UX-, FR-CONV-, FR-SIG- | §3 |
| CAS-, NFR-B, ADR-V4- | §4 |
| DP- | §5 |
| DM- | §6 |
| PRIV- | §7 |
| LLM-, MOD- | §8 |
| HER- | §9 |
| FR-M0…FR-M11, ML-, SAFE-, FR-AG- | §10 |
| FR-WF- | §11 |
| RPT- | §12 |
| NFR- | §13 |
| SEC- | §14 |
| CMP- | §15 |
| VV- | §16 |
| ENG- | §17 |
| OPS- | §18 |
| PLAN- | §20 |
| OD- | §21 |

**Names that must not be confused.** These sets are named differently on purpose:

| Set | Names |
| --- | --- |
| Cascade stages | S0–S5, S2b |
| Data-platform stages | L0–L5 |
| Modules | M0–M11 |
| Milestones | MS0–MS6 |
| Gates | G0–G6 |
| Data classes | D0–D4 |
| Topologies | A, B, C |

**Verified evidence already in the repository:**
- `tools/mlbench.py` and `eval/criterion_ml/`: 1,015 physician-labelled criterion pairs; every note in English,
  Traditional Chinese, Japanese and Taiwanese code-mixed style. The GPT-4 reference accuracy is 0.873.
- `libs/tb_common/recall.py`: anytime-valid recall bounds. In simulation, repeated Clopper–Pearson looks missed the true
  rate in 9.7 % of 12-month ledgers, and the sequence in 0.3 %.
- `tools/fetch_open_data.py`: the MIMIC-IV FHIR demo end-to-end test.
