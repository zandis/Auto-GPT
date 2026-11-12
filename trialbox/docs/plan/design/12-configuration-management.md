# TB-DS-12 Configuration Management Plan

| Field | Value |
| --- | --- |
| Document ID | TB-DS-12 |
| Title | Configuration Management Plan |
| Version | 0.3 |
| Date | 2026-11-07 |
| Owner | Aimedics engineer (configuration manager) |
| Author | Claude (for Aimedics) |
| Status | Reference. §0, §5.0 and §5.4 apply in the build stage; the rest applies from the first real-data install (hospital stage, H). |
| Standard | ISO 10007:2017 (configuration management); IEEE 828-2012 (configuration management in systems and software engineering) |
| Related | TB-DS-00, TB-DS-00R, TB-DS-20, TB-DS-02 §7–§9, TB-DS-03 (SC-40..42, SC-92..94), TB-DS-04 §9, TB-DS-11, TB-REV-006 findings M-06, M-07 |

**Approvals**

| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Product owner | Changfu Kuo | | |
| Aimedics engineer (configuration manager) | (to be named) | | |
| Japan maintenance team lead | (to be named) | | |

## 0. Build stage (applies now)

While TrialBox is built and tested on synthetic and public data (TB-PLAN-02 `SIMPLE-PLAN.md`, TB-DS-20), configuration management is the repository itself:

| CM function (ISO 10007 §5) | Build-stage practice |
| --- | --- |
| Identification | Source, prompts, rulesets and fixtures are git paths on `zandis/Auto-GPT` master; design documents are identified in TB-DS-00R. |
| Change control | One pull request per build step (TB-DS-20 §2) plus smaller fix PRs. A merged PR with its `docs/DECISIONS.md` D-nnn entry is the change record (§5.0). |
| Status accounting | TB-DS-00R for documents; `docs/DECISIONS.md` for decisions; the PR list for changes (§5.4). |
| Audit | `e2e_simple` and the model gate (N-11, N-12) on each step PR (TB-DS-04); the register is checked against the files at each step PR. |

Nothing in §1–§9 below is required for the build.

## 1. Purpose

TrialBox runs at hospitals without remote access, maintained by one Aimedics engineer and the Japan maintenance team. This plan says what is under configuration control, how each item is identified and versioned, how changes are approved, and what record each release leaves. It follows the configuration-management practice in GAMP 5 (2nd ed.) and IEC 81001-5-1 §5 (software maintenance), scaled to a small team.

## 2. Roles

| Role | Responsibility |
| --- | --- |
| Configuration manager (Aimedics engineer) | Keeps the item list, cuts baselines, signs releases with a second person. |
| Change Control Board (CCB) | Approves changes of class B and C (§5). Members: product owner, Aimedics engineer, Japan maintenance lead; site PI for changes to that site's rulesets, mappings or rule books; site security owner for security-relevant changes. Quorum: product owner or engineer plus one other member. |
| Second signer | Any CCB member other than the author of the change. Required for every release signature (SC-92). |
| Hospital IT | Owns the site's local configuration (network, mail, IdP, backup target) and approves installs at the site. |
| Site PI (`investigator`) | Approves rulesets for that site's studies on one page (SRS AM-01, FR-AUTH-13; TB-DS-00 BD-13) and the site rule book. The coordinator prepares and submits. |
| Build stage (§0) | The builder (Claude) authors each change; the product owner's merge is the approval. No CCB and no second signer in the build stage. |

## 3. Configuration items

| CI class | Examples | Identifier | Where kept | Version scheme |
| --- | --- | --- | --- | --- |
| CI-SRC Source code | services, libs, tools, REDCap External Module (M2) | git path | `zandis/Auto-GPT`, branch `master` | git commit; release tag `tb-vYYYY.MM.N` |
| CI-IMG Container images | trialbox-py, trialbox-jvm, console, rc-bridge | image name + digest | signed registry export inside the release bundle | sha256 digest pinned in the compose file |
| CI-3P Third-party components | HAPI FHIR, Postgres, vLLM, base images, Python/Node/Java packages | name + version + digest | SBOM per release (SC-93) | upstream version; digest pinned |
| CI-MOD Models | judge Gemma 4 26B-A4B NVFP4 (`nvidia/Gemma-4-26B-A4B-NVFP4`), verifier Qwen3.5-9B AWQ 4-bit (`cyankiwi/Qwen3.5-9B-AWQ-4bit`, thinking off), PHI tagger (lead candidate: the judge model behind the regex guard, TB-DS-01 CON-13), bge-m3; names per TB-DS-01 CON-12 | model ID + sha256 of weights, tokenizer, chat template, plus the serving configuration (vLLM version, max-model-len, max-num-seqs, eager flag, memory fractions; FR-MOD-10). The 6 Nov 2026 baseline recorded the configuration but no sha256; the first pinned set is recorded at build step 5 | model bundle; `models/registry.yaml` | `<model>-<quant>-<site-profile>`; hash recorded by `tools/pin_model.py` (SC-42) |
| CI-PRM Prompts and schemas | `judge_v4.md`, ir_extract prompts, output JSON schemas, chat command list | file path | git | prompt name carries a version (`judge_v4`); any wording change makes a new version |
| CI-RS Rulesets | GZQO, RA-BIO, RA-COH, GOUT-COH, ONC-OSI, site study rulesets | `<ID>/v<ver>` git tag | rulesets repository (signed) | git tag; manifest pins prompt and model (SC-40) |
| CI-MAP Site mappings | `site_mapping.yaml` for the Japan head hospital (SS-MIX2) and CGMH | site ID + version | site configuration repository, copy in each site's backup | semantic version; change class B |
| CI-RB Site rule books | abbreviation lexicon, local conventions, 保険病名 rules | site ID + version | as CI-MAP | as CI-MAP |
| CI-TERM Terminology tables | MEDIS 標準病名 maps, JLAC → LOINC, YJ → ingredient, CTCAE grading tables | table name + source version | `terminology/` in git (licence permitting) | source release + local revision |
| CI-SET Site settings | `settings.yaml`, `.env` (non-secret), feature flags, egress allowlist, mail settings | site ID | site configuration repository; secrets excluded | change class B |
| CI-SEC Secrets and keys | HMAC site key shares, pid-map data key, signing keys, REDCap read token, TLS certificates | key ID | vault on the appliance; key ceremony records (TB-DS-03) | key ID + creation date; never in git |
| CI-GATE Gate and test sets | SIGIR, TREC CT, MedTxt, pre-fill set, Japanese PHI set, injection suite | set ID + version | `eval/` (licence permitting) | set version; a change needs CCB approval because it moves the bar |
| CI-DOC Controlled documents | TB-DS-00, TB-DS-00R, TB-DS-01..05, TB-DS-07..12, TB-DS-15..17, TB-DS-19..21, TB-PLAN-01, TB-PLAN-02, TB-TMPL-01, TB-TMPL-07, TB-REC-01, TB-REV-006..006g (TB-DS-00R lists versions) | document ID + version | `/mnt/project-files/trialbox-design/` now; `trialbox/docs/design/` once baselined | `major.minor`; 0.x = draft, 1.0 = first approved; living build documents (TB-DS-20, TB-DS-21) issued at 1.0 (§6) |
| CI-REC Records | release records, SAT records, approvals, training records, pilot reports | record ID | release bundle + site file | immutable once signed |

Items explicitly **not** under configuration control: patient data, snapshots and lake files (they are data, governed by retention rules in TB-DS-00 N-02..N-04), and job outputs (each carries the configuration that produced it).

## 4. Baselines

| Baseline | Content | When |
| --- | --- | --- |
| Build baseline BB-n | Master commit of each merged step PR (tag `tb-build-sN`), TB-DS-20 version, `e2e_simple` and model-gate results attached to the PR | Each merged build-step PR (§0) |
| Design baseline DB-1 (H) | The CI-DOC set at version 1.0, approved | Before the first real-data install |
| Pilot product baseline PB-1 | CI-SRC tag, CI-IMG digests, CI-MOD hashes, CI-PRM versions, CI-RS tags for the pilot studies, CI-GATE results | First real-data release candidate passing all gates (H) |
| Site baseline SB-JP-1, SB-CG-1 | PB-1 plus CI-MAP, CI-RB, CI-SET for that site, SAT record | After site acceptance (TB-DS-15) |
| Later baselines (H, L) | PB-2, SB-*-2 | Each later release |

A baseline is a list of exact identifiers (tag, digests, hashes, versions) in one manifest file, signed. The appliance shows its current baseline on the admin health page.

## 5. Change control

### 5.0 Build stage

A change is a pull request on `zandis/Auto-GPT`. Its record is the PR (description, diff, CI results) plus, where it takes a decision, a `docs/DECISIONS.md` entry `D-nnn` (date, PR, decision, affected TB-DS-01 IDs). The owner's merge approves it. The classes of §5.1 are still written on the PR so the hospital stage inherits a classified history; class C changes (model, prompt, screening logic) attach the N-11 and N-12 results, which the build already runs.

### 5.1 Change classes

| Class | Examples | Approval | Validation |
| --- | --- | --- | --- |
| A Minor | Typo in a UI string; documentation wording; test-only change; non-functional refactor with no output change | Code review by a second person | Unit tests and the end-to-end test pass |
| B Significant | New feature; site mapping change; rule book change; settings change; dependency upgrade; terminology table update | CCB (product owner or engineer + one other); site PI for site items | Relevant test levels + regression on the end-to-end test; SAT steps re-run for affected site items |
| C Critical | Model, quantisation or vLLM change; prompt change; gate set change; screening logic (cascade, exclusion policy); PHI pass; identity, roles, reveal; cryptography; audit chain | Full CCB including security owner; site PI for anything that changes outputs of an approved ruleset | All gate sets on the real GPU; security tests; re-approval of affected rulesets where outputs change (as D-96 did for judge v4) |

Change **significance** (A/B/C above) and change **type** (CC1–CC6, TB-DS-04 §9.3) are two attributes of every change record. Minimum significance by type: CC1 model-affecting → C; CC2 data-path → B (C if DEID changes); CC3 interface → B; CC4 UI/text → A; CC5 security fix → B (C if identity, roles, reveal or crypto); CC6 site configuration → B.

### 5.2 Change request record

Each change has a record (GitHub pull request plus a change record entry) with: ID, class, description, reason, affected CIs, affected requirements (TB-DS-01 IDs) and hazards (TB-DS-11), tests run and results, approvers, and the release it goes into. For class C the record also links the gate results and any ruleset re-approvals.

### 5.3 Emergency changes

A security fix for a critical vulnerability (SC-94: fix critical within 14 days) may go out with the engineer plus one CCB member signing, and full CCB review within 5 working days afterwards.

### 5.4 Status accounting

| Record | Shows | Kept in |
| --- | --- | --- |
| Document register (TB-DS-00R) | Per document: ID, title, file, version, status, owner, approver roles, distribution, next review; updated in the same edit as any document's version | `00-document-register.md` |
| Decision log | Per decision: D-nnn, date, PR, decision in one sentence, affected requirement IDs, superseded D-nnn | `trialbox/docs/DECISIONS.md` |
| Change list | Per PR: number, title, class (§5.1), build step, merged date, merge commit | GitHub pull requests |
| Baseline list | Per baseline: ID (BB-n, DB-1, PB-1, SB-*), commit or manifest, date | Tags in the repository; release records (§7) for H |

## 6. Document control

| Step | Rule |
| --- | --- |
| Identification | Every document has an ID from the register (TB-DS-00R), a control table, an approvals block and a change history. |
| Drafting | Versions 0.x. Drafts may change freely; each change is logged. |
| Review | A reviewer other than the author; the review record (as TB-REV-006) is kept. |
| Approval | Named approver roles sign the approvals block; the version becomes 1.0 (or the next major). **Living build documents** (TB-DS-20, TB-DS-21) are issued at 1.0 and changed as x.1, x.2; for them the owner's merge of a step PR that uses them is the approval. |
| Change after approval | Minor wording: x.1; content change: next major, with the approvers re-signing. |
| Change history | Every version has one row: Seq (order), version, date, author, change in at most three lines; detail stays in the review record it cites. |
| Distribution | The register's Distribution column states who receives which document and when. Superseded versions are marked and kept. |
| Location | Drafts in the project files folder; approved versions in the repository under `trialbox/docs/design/` with a PDF export of the signed copy. |

## 7. Release records

Every release produces a record, kept in the bundle and at each site:

1. Release ID and baseline manifest (all identifiers, §4).
2. Change list with change classes and links to change records.
3. Test results: unit, contract, end-to-end, browser walk, gate sets (with the measured numbers against TB-DS-00 N-07, N-09, N-11, N-12), security scans, SBOM diff.
4. Risk file review note (TB-DS-11 §8).
5. Rulesets affected and their approval status.
6. Known issues and workarounds.
7. Install and rollback instructions; the previous baseline to roll back to.
8. Two signatures (author + second signer) and the signing key ID.

At the site, hospital IT records the install date, the result of the post-install checks (TB-DS-15 IQ-01..IQ-05 subset) and any deviation.

## 8. Site configuration custody

Site items (CI-MAP, CI-RB, CI-SET) are written with hospital IT during installation. The master copy is kept by Aimedics in a private site configuration repository, without secrets or patient data; the live copy is on the appliance. A change made at the site (for example a new lab code) is a class B change: it is written into the master copy, reviewed, signed and installed like any other change. The appliance refuses an unsigned mapping file.

## 9. Audits of configuration

| Audit | What | When |
| --- | --- | --- |
| Build check | Register versions match the files; `e2e_simple` green | Each step PR (§0) |
| Functional configuration audit (H) | Each requirement of the release is verified as recorded in the traceability matrix (TB-DS-04 §6) | Before each product baseline |
| Physical configuration audit | The installed digests, hashes and versions match the signed baseline manifest | At SAT and after each install (automated check on the health page) |
| Document audit | Register matches the documents in use; no draft used as approved | Every 6 months |

## References

- ISO 10007:2017 Quality management — Guidelines for configuration management.
- IEEE 828-2012 Configuration Management in Systems and Software Engineering.
- ISPE GAMP 5, 2nd edition (2022), configuration management and change control appendices.
- IEC 81001-5-1:2021 §5 (software maintenance), used for the hospital stage.
- TB-DS-00R Document register; TB-DS-20 Build map; TB-DS-04 Verification.

## Change history

| Seq | Version | Date | Author | Change |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | 2026-11-07 | Claude for Aimedics | First draft, from TB-REV-006 findings M-06 and M-07. |
| 2 | 0.1a | 2026-11-07 | Claude for Aimedics | TB-REV-006b R2-02: §2 site PI approval cites AM-01 / FR-AUTH-13 / BD-13. |
| 3 | 0.2 | 2026-11-07 | Claude for Aimedics | TB-REV-006g Q-30, Q-32, Q-37, S-08: §0 build stage (git, one PR per step, D-nnn); §5.0 build-stage change record; §5.4 status-accounting format; build baseline BB-n; CI-DOC up to TB-DS-21 and TB-REV-006g; living-document version rule; change-history rule; references; history row 0.1a joined, Seq column. |
| 4 | 0.3 | 2026-11-07 | Claude for Aimedics | TB-REV-006f §8 (L8-02, L8-08): CI-MOD names the pinned builds as in TB-DS-01 CON-12 (Gemma 4 26B-A4B NVFP4 judge, Qwen3.5-9B AWQ 4-bit verifier, judge as PHI-tagger candidate) and adds the serving configuration to what is pinned; notes that the 6 Nov baseline has no file hashes. |
