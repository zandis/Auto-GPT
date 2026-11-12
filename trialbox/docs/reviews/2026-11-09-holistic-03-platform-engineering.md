# TrialBox platform and engineering review: the whole, and what it lacks

| Field | Value |
| --- | --- |
| Date | 2026-11-09 |
| Head reviewed | `trialbox/` at `20e89d0` (branch `claude/trialbox-plan-v4-oxn56n`; code equal to `origin/master` `e91871c`, plus the review documents) |
| Reviewer | Principal engineer, clinical data platforms. Read-only. No code changed. |
| Scope | The platform end to end: capability map, architecture coherence, scale and evolution, developer experience, the missing components in priority order, the technical risk register. Component-by-component findings, bugs, security, the database and the data model are in the earlier reviews and are only cited here. |
| Inputs | `docs/ARCHITECTURE.md`, `RUNBOOK.md`, `SECURITY.md`, `DATA.md`, `VALIDATION.md`, `USER_GUIDE.md`; `DECISIONS.md` D-120 to D-140; `docs/plan/24-plan-v4.md`; the owner's decisions of 2026-11-09; the six review parts and the consolidated review; the component reviews (layers 1 and 2); the standalone database review; the patient-data design; `docs/plan/design/19-platform-functions.md` and `19a-completeness-table.md`; `spec/v4/16`; the code under `services/`, `libs/`, `tools/`, `deploy/`, `tests/`, `models/`, `schemas/`; the root workflow `.github/workflows/trialbox-e2e.yml`; the draft of the journey run at `/tmp/claude-0/review-journeys/` (coverage analysis and the first two role results). |
| Status | Record. New facts go into DECISIONS. |

## 0. One page

TrialBox at head is a complete *vertical slice* and an incomplete *platform*. The slice is real: hospital export in, pseudonyms at the door, criteria to SQL with an equivalence gate, a two-model note reader that never excludes alone, a console in three languages for five roles, built-in forms, a lifecycle, REDCap two-way sync, signed updates, encrypted backups, a hash-chained audit. Few products this young have that much working end to end, and the documents say honestly what has not run.

What is missing is the layer *around* the slice that a hospital, a second site and a second engineer need:

1. **No engineering gate.** The 1,423-test suite, lint, mypy, the contracts check and the goldens run on a developer's machine. CI runs one script. There is no release identity (everything is `1.0.0`, no git tag), no SBOM, no hash-pinned lock, no staging or site-acceptance environment, no feature flags.
2. **No operating signal.** No metrics, no alert, no support bundle, no scheduled backup, no fleet view. The box can only be known to be healthy by someone signing in and looking at a tile.
3. **No model lifecycle as a pipeline.** The pieces exist (registry, cards, canary, TREC gate, public_e2e, goldens) but a candidate model or prompt is qualified by hand on a paid VM with results pasted into DECISIONS. Nothing re-runs the gates when a model, prompt, quantisation or vLLM version changes.
4. **Two half-built data platforms and one unwired delivery path.** `services/dataplat` (3,146 lines, L0–L5, lineage, MPI, DQ) is imported by no service. The outbox dispatcher is instantiated nowhere. Terminology lives in five shapes. The orchestrator carries two database modules (`db.py`, `db_pg.py`). The OMOP decision will add a third data model unless the first two are retired first.
5. **The application is a list, not a workflow.** Marks, outcomes and visit windows exist; a task and inbox engine, notifications beyond two morning mails, search, an EMR launch, webhooks, an API contract for integrators and a missing-data model that a CRC can act on do not.
6. **Bus factor one.** One human merges; an AI agent wrote 189 of the last 220 commits in five days. Conventions are consistent because one author wrote them. DECISIONS.md is the only memory of why. The next engineer has a 2,811-line decision log, a 9-file v4 spec that still names removed systems (Hermes, MCP, Podman, OpenBao) and no CONTRIBUTING for `trialbox/`.

Verdict: the architecture is right in the large and the safety core is sound. The platform is at roughly 55 % of what the first paid site needs and 35 % of what ten sites need. The P0 list in §6 is about 14 engineer-weeks. It should go before the OMOP and profile work, because every one of those items (CI gate, release identity, goldens, metrics, connection pool, Postgres image) is cheaper before the data model triples in size.

## 1. Capability map

Legend: **Built** means on master, tested, used by the product. **Partial** means code exists but is incomplete, unwired, CLI-only or untested on its real path. **Missing** means nothing on master. Evidence is a file or a decision.

### 1.1 Data acquisition

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Feeds: CSV, CGRD SQL views, SS-MIX2, FHIR bulk | Built | `services/adapter/sources/*`; `DATA.md` §1. Real SS-MIX2 from a vendor never read (review 06 pilot blockers; the synthetic exporter `tools/ssmix2_export.py` is the only source tested). |
| Site mapping per hospital (YAML, `mapping_check`) | Built | `services/adapter/mapping/`; no page, CLI only (19a FR-PLAT-09). |
| Interface: HL7 v2 parser | Partial | 92-line parser ignores MSH-2 custom delimiters and `&` sub-components (layer 2 §1.1). |
| Interface: HL7 v2 live feed (MLLP), FHIR Subscription, CDC from the HIS | Missing | Nightly file and directory reads only. Fine for the pilot; a hospital that wants same-day screening has no path. |
| Scheduling | Built | APScheduler in the orchestrator and console timers (`scheduler.py`, `console/timers.py`); every run is a job; missed timers catch up (D-130). |
| Back-fill | Partial | The adapter re-reads everything each night; `--since` deltas exist for small hosts (D-80). The owner now wants *all history* loaded at once: no chunked, resumable historical load exists; the adapter holds the whole batch in memory (4.9 GB at 15k patients, A-05). |
| Incremental and change-data capture | Partial | HAPI takes a delta by content hash (D-122). The lake is rebuilt whole every night (`lake/store.py`). No row-level change log; no "what changed since snapshot N". |
| Snapshots and point-in-time | Built | DuckDB per snapshot, 3 nightly + 36 month-ends; jobs pin a snapshot. But site publish mutates the current snapshot in place (FR-REP-02, D-135 "not byte-identical"). |
| Ingest quality gate | Built | 1 % HL7 validator sample, 0.5 % threshold, `ingest_report.json`. |
| **Missing-data model** | Partial | Three-valued logic in SQL (NULL = unknown), 16 reason codes (`tb_common/reasons.py`), fail-closed code families (D-113, D-130). What is missing: a *per-item* statement of why a value is absent (not collected, not mapped, not in feed, suppressed, conflicting), a UI pattern that tells the CRC *which* item to fetch, and a count of missingness per source per month. Text-only lab values become NULL then FALSE (B-01, Blocker in the consolidated review). |

### 1.2 Data platform

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Canonical model | Partial | Thirteen flat lake tables in a Python dict (`lake/flatten.py`), unversioned. OMOP CDM v5.4 decided (owner, 2026-11-09), not started. `services/dataplat` has a second canonical layer nobody uses. |
| Terminology service | Partial | Five homes: `criteria_compiler/terminology/*.parquet`, ruleset `valuesets/*.json`, `sitesetup.local_code` (per space), schema `terminology` (licensed JP masters, D-137), schema `refdata` (reference pack, D-140). No concept id shared across them, no versioned concept-map release, no service API. SNOMED has a price (USD 1,954 per system per year) and no decision. |
| Data quality | Partial | Validator sample at ingest; `dataplat/dq` expectations exist but are not on the ingest path; no DQD-style checks (plausibility, temporal, conformance); no DQ dashboard. |
| Lineage and provenance | Partial | Job audit records inputs and output hashes; `dataplat/lineage` emits OpenLineage-shaped events to nothing. No row-level provenance on a clinical fact (source system, record id, snapshot first seen, trust). `site_fact.basis` is the only trust column. |
| Versioning of definitions | Partial | Rulesets are git-tagged per version (good). Lake schema, terminology, mapping YAML, derived-score formulas (`tb_common/derived.py`) and prompts are versioned by file name or not at all. |
| Point-in-time views | Partial | Snapshot pinning gives "as of the night"; nothing gives "as the record stood on date X" (bitemporal). OMOP has no built-in answer either; this must be designed (the design document's `tb_snapshot`, `tb_fact_provenance`). |
| Conflict model | Partial | Field-level ownership and conflicts for *trial* data (`datacore/store.py`, D-123). Nothing for clinical facts; sheet vs feed disagreement cannot be recorded today (owner decision needs it). |
| Pseudonymisation | Built | HMAC per site, AES-GCM pid map, names never past the adapter (`adapter/pidmap.py`). |

### 1.3 Knowledge

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Criteria: text to IR to SQL, equivalence gate, approval | Built | `criteria_compiler`, D-130; one of the strongest parts. |
| Criterion library and reuse across trials | Partial | `criteria_compiler/library/` exists; no page; no "this criterion was approved before for trial X" surfaced to the PI. |
| Phenotypes | Missing | Cohorts are rulesets (GOUT-COH, RA-COH). No phenotype library, no OHDSI definitions, no versioned phenotype with validation record. Decided for the profile work, not started. |
| Scores and derived values | Partial | eGFR and a few atoms rendered into SQL from code (`derived.py`); not data, not steward-readable, not versioned. |
| Catalogue of clinical items | Missing | Decided (LOINC, OMOP, CDISC QRS, NIH CDE mapping) and assigned to "a separate agent"; nothing on master. |
| Reference data: trials, drugs, ICD | Built | Offline reference pack with manifest and NOTICE (D-140). |

### 1.4 AI

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Gateway as the only model path; data-class policy | Built, broken as installed | `services/gateway`; `test_no_direct_model_calls.py`. On an installed box the gateway refuses every PHI call (R-01 Blocker): no step confirmer, `TB_DATA_CLASS` unset, every build `sha256: null`. |
| Model registry and cards | Partial | `models/registry.yaml` (aliases, builds, status champion/shadow/qualified), 21 cards. No hash filled; no tool moves a build through its states; routing to a site pin by hand. |
| Prompt registry and versions | Partial | Prompts are Markdown files (`judge_v3.md`, `judge_v4.md`); `prompt_version` is carried into results and the gateway trace; `prompt_meta.schema.json` exists. No registry object, no diff, no approval, no "which prompt ran on night N" page. |
| Evaluation harness | Partial | Pieces: 54-case pair canary (gate), TREC N-12 (≤ 5 %), `public_e2e` 112 checks, SIGIR bake-off, `judge_eval`, `medtxt_eval`, `open_cohorts_eval`, planted-defect synthetic hospital. No single `trialbox eval qualify <build>` that runs all of them and writes a qualification record; every GPU run was by hand (D-139). |
| Model eval gate in CI | Missing | CI has no GPU and no cassette replay of the gates; `tests/llm` is one file needing a real endpoint. |
| Drift monitoring | Partial | Nightly canary catches a broken or swapped model. Nothing watches answer distributions over time (unknown rate, exclusion rate, agreement rate per criterion per week) or alerts when they move. `metrics.unprocessed` is counted and ignored (A-07). |
| Guardrails | Built | PHI tripwire and recogniser (`guard/`, `phi_guard.py`), schema-bound outputs, quote verification, two-model rule, min confidence. Gaps: no prompt-injection suite (needed before model-proposed gap rules, owner decision), CJK name false positives refuse 3 % of calls. |
| Cost control | Partial | `max_llm_items = 2000` silently truncates (A-07); no per-night budget, no per-study budget, no cost page. The paid cloud run had no cap (D-30). |
| GPU scheduling across screening, profiles, embeddings | Missing | One hold per SCREEN run and a sleep swap (D-116). No queue or priority between the night's screening, the coming profile narratives, embeddings and interactive chat; S3/S4 are single-stream (A-07). The 5090 tier cannot host profiles at all (database review §0.2). |
| Reproducibility of model answers | Overstated | `rerun.py` and ARCHITECTURE §9 promise byte-identical re-runs; D-116 measured ~9 % label drift (A-10). Replay from recorded answers (spec §17.3) is not built. |

### 1.5 Application

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Roles | Partial | Five roles (`auth.py` ROLES). Decided and missing: steward, sub-PI by delegation log, clinician, monitor SDV, break-glass, PI reveal (D-143). Admin can view PHI by default (S-19). One permission function used by pages and API does not exist; checks are scattered. |
| Workflow engine | Partial | Subject state machine with undo (`datacore/lifecycle.py`), visit windows, marks and outcomes. No general task object, no assignment, no due date on a task, no escalation, no SLA. Referral (owner decision of 2026-11-09) needs exactly this: a request with a target, states, reasons and a log. |
| Notifications | Partial | Two morning mails (N1, N2) and per-person notice settings. No in-app notification, no event-driven notice (new candidate, conflict opened, visit overdue today), no digest preferences beyond on/off, no LINE/Teams (deferred, D-125). |
| Tasks and inbox | Missing | "My work" is a computed list per role home. Nothing persists a task, nobody can hand one over, nothing shows "what I owe today across studies". The referral flow, conflicts, proposed facts and uncertain mail sends are four separate queues that should be one inbox. |
| Search | Missing | The header command field opens pages only (D-110). No search over studies, pseudonyms, screening numbers, candidates or audit (19a FR-PLAT-14). |
| Reporting | Partial | Feasibility pack, screening log, enrolment report, research-office XLSX. No ad-hoc report builder, no scheduled report, no cross-study dashboard, no audit CSV. |
| Exports | Built | ODM 1.3, REDCap CSV, XLSX, FHIR QuestionnaireResponse on request. OMOP export deferred. |
| APIs and SDK | Partial | 37 `/api/v1` routes on the console, session-cookie authenticated, no versioned OpenAPI document published, no API tokens for integrators, no SDK, no rate limit per client. The orchestrator API is internal only (good). |
| Webhooks | Missing | No outbound event hook; the only integration surface is mail and REDCap sync. |
| EMR launch / SMART on FHIR | Missing | Nothing. The PI finds the physician "in the real EMR" (owner decision) with no link from TrialBox to the chart and none back. A context-launch link (chart number in a signed URL to the hospital's EMR deep link, or SMART launch where the EMR supports it) is a small item with a large daily-use effect. |
| Help, about, my account | Partial | Help panel (`/help`), `/account`, `/admin/notice`. No about page with release id (D-35). |
| Opt-out and patient notice | Partial | S0 reads a `consent` table from the hospital feed (`cascade/engine.py:255-360`). No page to record an opt-out at the site, no patient notice text, no "excluded by opt-out" count (19a FR-PLAT-22/23). |
| Phone, three languages, accessibility | Built | Walk: 780 checks, axe 0 serious, 44 px targets (D-139). i18n lives in ten Python files of string dicts. |

### 1.6 Platform services

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Identity | Partial | Local accounts with scrypt, lockout, sessions, CSRF, CSP; SSO by trusted header only. No MFA (MHLW v7 asks for it), no OIDC, no LDAP/AD, no password reset flow. Layer 2 recommends Authelia in front. |
| Audit | Built | Hash-chained JSONL, nightly verify and archive, every reveal and output. Gaps: audit written after the state change (A-19), no audit browser with filters or export, no reason-for-change on trial-record edits, no e-signature. |
| Consent and opt-out registry | Partial | See 1.5. No registry of consents as a first-class object with scope, date, withdrawal and source; built-in consent form captures a CRF, not a registry entry. |
| De-identification service | Partial | `tb_common/smallcell.py` suppresses small cells in CRO reports; `deliverables/disclosure.py` exists. No k-anonymity over quasi-identifiers, no date shift, no project pseudonyms, no export manifest. The consortium export the owner approved (k = 5, ±180 days, no quotes, no vectors) has no code. |
| Consortium federation layer | Missing | Decided: signed count files, shared code-map registry hosted at CGMH, de-identified profile exports under IRB. Nothing on master: no cohort-definition exchange format, no receiver, no vocabulary release, no site identity or key exchange. |
| Secrets | Built | Per-service tokens, rotation command, backup key the box cannot read. Rotation of the database password is not atomic (D-27). Keys are created silently beside data (S-11). |
| Object store | Built | Filesystem under `objects` volume with hashes in the audit; MinIO removed (D-121). |

### 1.7 Operations

| Capability | State | Evidence and gap |
| --- | --- | --- |
| Install | Built, unrun on Docker | `install.sh`, tiers from measured records, wizard, network sheet. Never executed against a real Docker daemon end to end (review 05 §1). Egress rules not persisted across reboot (D-01). |
| Update and rollback | Built, unrun on Docker | Signed bundle, backup first, rollback point, `update_drill` in process. No crash-consistency marker, no free-space preflight, no anti-rollback (D-11..13); compose rollback unverified (D-15). |
| Backup and restore | Built, not scheduled | Encrypted to the hospital's key, drill passes in process. No scheduled backup, no age alert, default target is the box's own disk (D-19). |
| Monitoring and alerting | Missing | No `/metrics`, no exporter, no alert channel, no disk or GPU watch (D-22, A-14). The admin health tile is the sum of `/healthz` probes. |
| Support bundle | Missing | RUNBOOK §7 asks the site to send files by hand (D-23). |
| Remote assistance | Missing | By design nothing leaves the box; but there is no PHI-free diagnostic export, no screen-share protocol, no read-only support role with an expiry. |
| Release identity and changelog | Missing | `1.0.0` everywhere, no git tag, no `release.json`, no CHANGELOG (D-35). |
| Fleet management by Aimedics without patient data | Missing | No heartbeat, no release channel, no "which site runs what", no central canary result view. Hospital IT and Aimedics both learn of a failure when a CRC calls. |
| Logs | Built | JSON with PHI scrubber for own services; HAPI, Postgres and vLLM plain text; nightly collection and retention. |
| Host hardening guide | Built | SECURITY §1, `check_host.sh`; NTP drift is a warning not a failure (A-20). |

### 1.8 Engineering system

| Capability | State | Evidence and gap |
| --- | --- | --- |
| CI/CD | Partial, thin | One workflow at the repository root (`.github/workflows/trialbox-e2e.yml`): `make e2e-simple` and the backup drill on pull requests only. No pytest, lint, mypy, contracts check, image build, goldens, `pip-audit`, SBOM, nightly schedule, push-to-master trigger (E-01). The spec §16 promised all of these. |
| Unit tests | Built | 1,423 cases, strong independent oracles, architecture tests for the two key invariants. 18 min serial; autouse Postgres for every test (E-02). |
| Contract tests | Partial | `schemas/` to generated models with drift check (good). No consumer-driven contract test between console and orchestrator, no OpenAPI snapshot, no cross-version replay. |
| Property tests | Missing | No `hypothesis`; the parsers, date normalisers and encodings that fail closed are example-tested only (E-05). |
| End to end | Built, stub only | `e2e_simple` 17 stages, `public_e2e` 112, walk, backup and update drills, `complete_run` 581 checks. Every one runs the stub; the pair has never run `e2e_simple` (R-15). |
| Load tests | Missing | `hospital_sim scale` at 50k on the stub (805 s) is a throughput model, not a load test; zero `perf` tests; no concurrent-user test of the console; no soak over a week of nights. |
| Chaos and restore drills on Docker | Missing | Drills are in process. No kill-a-container, fill-the-disk, restart-Postgres, pull-the-GPU, power-loss-during-update on the compose stack. A-02 shows what one restart does. |
| Security tests | Partial | Egress nftables test, token-everywhere test, service-secret tests. No dependency audit, no DAST, no secret scanning in CI, no threat-model review cadence. |
| Model eval gates | Partial | See 1.4. Not in CI, not automated. |
| Release and versioning | Missing | See 1.7. |
| Environments | Partial | DEV, TEST, VALIDATION, PRODUCTION as a `TB_ENV` string with inconsistent defaults (D-25). No staging box, no site-acceptance environment that mirrors a hospital's proxy, SSO header and mail server. The POC compose is the closest thing. |
| Feature flags | Missing | No flag mechanism. `TB_*` environment variables (121 distinct) do the job badly: 55 undocumented (E-12), read per service, no per-site or per-study switch, no kill switch for a model layer. The profile work alone names five "behind a flag" items. |
| Documentation | Built, with a tail | Eight maintained documents with `doclint`; honest. Behind them: a 9-file v4 spec and a 30-file design set that name removed systems, and a 2,811-line DECISIONS log. |
| ADRs | Built, in one file | DECISIONS.md is an append-only ADR log with evidence per entry. It is the project's best asset and its hardest read. No index by topic, no superseded markers in older entries. |
| Code ownership | Missing | No CODEOWNERS, no CONTRIBUTING for `trialbox/`, no module owner list. The root `CONTRIBUTING.md`, `.devcontainer`, `Dockerfile` and `LICENSE` are Auto-GPT's (E-08). |

### 1.9 Count

| Layer | Built | Partial | Missing |
| --- | --- | --- | --- |
| Data acquisition | 5 | 5 | 1 |
| Data platform | 1 | 7 | 0 |
| Knowledge | 2 | 2 | 2 |
| AI | 2 | 6 | 2 |
| Application | 2 | 8 | 4 |
| Platform services | 3 | 4 | 1 |
| Operations | 4 | 2 | 5 |
| Engineering system | 3 | 6 | 6 |
| **Total** | **22** | **40** | **21** |

The shape is the point: twice as many "partial" as "built". The project starts things well and stops at the demo-able point. The missing items cluster in operations and the engineering system, which is exactly what one builder with an AI agent and no second site has had no reason to feel yet.

## 2. Architecture coherence

### 2.1 What runs today

Thirteen containers from one compose project: console, orchestrator, gateway, mail-gateway, criteria-compiler (JVM image), doc-parser, adapter, lake, embed-service, fhir-store (HAPI), db (Postgres 16 alpine), llm-service and llm-verifier (vLLM), plus llm-stub in test. Nine of them run TrialBox's own code; the caller matrix in `tb_common/service_auth.py` has eight entries.

Behind the nine processes are 21 Python packages under `services/`. Twelve of them are libraries that happen to live beside the services: `datacore`, `sitesetup`, `matching`, `dataplat`, `deliverables`, `registry`, `guard`, `tracestore`, `rc_bridge`, `rc_sim`, `channels`, `llm_stub`.

Size by package (lines of Python): console 15,922; orchestrator 15,679; adapter 3,826; criteria_compiler 3,751; matching 3,481; dataplat 3,146; sitesetup 2,791; datacore 2,182; deliverables 1,925; lake 1,109; gateway 1,098; mail_gateway 971; the rest under 700 each. `tb_common` 4,097; `tb_contracts` 3,893 (generated).

### 2.2 Is the decomposition right for one workstation and a small team?

Too many processes, too few boundaries that matter.

**Boundaries that earn their process.** The gateway: it is the only thing on `model-net`, and the architecture test holds that no other code calls a model. Keep it. The database and the models: external software. The JVM image for the CQL translator: a different runtime. Those four are the real seams.

**Processes that cost more than they protect.** Console and orchestrator talk over HTTP with a service token, yet they share the same Postgres, the same volumes and the same deployment unit; the console polls the orchestrator for job state it could read from the same database. Mail gateway, adapter, lake, embed-service and doc-parser are each a FastAPI wrapper around a library, each with a token, a health check, a port on the network sheet and a crash-loop at start (A-16). Nine health checks, nine tokens, nine log streams and nine `depends_on` for a product that runs on one workstation and is operated by hospital IT who have never seen it. Every one of them is a place where a lost connection (A-02) or a missing `depends_on` shows up as a different symptom.

**The lake is the one hard call.** DuckDB is embedded; two processes cannot write the same file. Today the lake process is the single owner, and the orchestrator's queries cross HTTP as Arrow. When the lake becomes an export from OMOP, the owner is the exporter and readers open the file read-only. Keep the lake as a process only until then.

### 2.3 Duplicated subsystems

| Duplicate | Where | What to do |
| --- | --- | --- |
| Two data platforms | `services/dataplat` (L0–L5, DQ, MPI, lineage, reconcile; wraps `adapter` and `lake`) and `adapter` + `lake` themselves. `dataplat` is imported by no service, only by `tools/cascade_e2e.py`, `tools/trialbox/eval.py`, `tools/testbench`. | Decide once (question Q3). Recommended: lift `dataplat/dq` and `dataplat/lineage` into the adapter's publish path as the trust and provenance columns the design needs; delete the rest. Do not start OMOP with a third layer beside two. |
| Two orchestrator database modules | `orchestrator/db.py` (jobs, pool, candidates) and `orchestrator/db_pg.py` (steps, outbox, `StepStore`); both carry a `MIGRATIONS` tuple. | Merge into one module after the outbox decision. |
| Outbox written, not wired | `orchestrator/outbox.py` (claim-with-lease, probe, `uncertain`, `resolve`, kill-loop test); delivery is in fact a synchronous `POST /send` inside the job (A-13). | Wire it (one dispatcher thread, steps enqueue in the result transaction) or delete it and change ARCHITECTURE §9. A documented retry path that does not exist is worse than none. |
| Terminology in five shapes | Compiler Parquet files; ruleset ValueSet JSON; `sitesetup.local_code`; schema `terminology` (D-137); schema `refdata` (D-140). | One `vocab` schema (concept, vocabulary, relationship, source_to_concept_map, release) as the design's step 3; the compiler's ValueSets resolve through it; the Parquet files become a loader. Do this *before* OMOP's `concept` table or there will be six. |
| Four stores for the site's own facts | `sitesetup.fact`, `datacore.value`, `site` schema (marks, outcomes), `orch.candidates` plus `study` schema. | Acceptable boundaries (trial data vs site set-up vs screening state) if each has one owner module. Write the owner list; forbid cross-schema SQL. |
| i18n in ten Python files | `console/i18n*.py`, `orchestrator/i18n.py`, about 1,100 lines of string dicts with E501 ignored. | One catalogue format (YAML or gettext `.po`) loaded once; a test that every key exists in all three languages. Translators cannot edit Python. |
| Era and Minguo dates in six modules; PHI regexes in three; CSV encoding detection in six | E-05, E-15, layer 2 row 7. | `tb_common/dates.py`, `tb_common/phi.py`, `tb_common/encoding.py`, each with a property test. The PHI divergence is a safety item. |
| Three e2e scaffolds | `e2e_simple.run` (CC 162), `public_e2e.run` (146), `cascade_e2e`. | A `Stage` registry and one runner; the stages are the product's acceptance spec and change every plan step. |
| Hermes remnants | `services/channels` (419 lines, grammar and prompts for a removed agent), `COPY integrations` in the Dockerfile, `f-frontdesk` and `g-guard` aliases in `registry.yaml`, `channel_engine` check in `doctor`. | Keep `channels/grammar.py` (mail commands use it); delete the rest. |
| Two copies of every clinical fact | HAPI and the lake; HAPI read by nothing at run time (D-130). | Demote HAPI to the compile-time gate in CI (design step 11). |

### 2.4 Coupling

- The console imports the orchestrator's contracts and polls its HTTP API; the orchestrator imports `console`'s nothing. Good direction. But the console also opens its own schemas (`site`, `auth`, `datacore`) in the same database the orchestrator writes (`orch`, `study`). Two processes, one database, no declared ownership. The line is in people's heads.
- `matching`, `datacore`, `sitesetup` and `deliverables` are imported by both console and orchestrator. They are libraries; they should live in `libs/`, not `services/`, so the import direction is visible.
- `tb_common` is 31 modules and growing (`refdata`, `smallcell`, `subject`, `pair`, `recall`). It is the de facto domain layer with no internal structure. Split into `tb_core` (config, db, audit, http, auth, crypto) and `tb_domain` (reasons, derived, recall, subject, pair, refdata).
- 121 `TB_*` environment variables, 55 undocumented, read with `os.environ.get` in 60 files. Configuration is the widest coupling in the codebase.

### 2.5 Target architecture, 12 months

```
                           hospital network (TLS proxy, SSO/IdP, mail)
                                        │
   ┌────────────────────────────────────┼─────────────────────────────────────┐
   │ trialbox box (one compose project, one Postgres, one GPU)                │
   │                                                                          │
   │  ┌───────────────────────── tb-app ─────────────────────────┐            │
   │  │ console pages + /api/v1 + jobs + scheduler + timers      │            │
   │  │ datacore · lifecycle · tasks/inbox · referral · notices   │            │
   │  │ matching cascade · feasibility · reports · exports       │            │
   │  │ mail in/out (outbox dispatcher) · audit writer           │            │
   │  └──────────────┬──────────────────────────┬───────────────┘            │
   │                 │ SQL                       │ HTTP + token               │
   │  ┌──────────────▼──────────────┐   ┌────────▼─────────┐  ┌───────────┐  │
   │  │ postgres (Debian, pgvector) │   │ tb-gateway       │  │ tb-compile│  │
   │  │ cdm (OMOP 5.4) · vocab      │   │ data-class policy│  │ doc-parser│  │
   │  │ trial (datacore, tasks)     │   │ registry · pins  │  │ criteria  │  │
   │  │ app (auth, site, jobs,      │   │ swap · budget    │  │ IR→SQL/CQL│  │
   │  │  outbox, audit index)       │   │ trace store      │  │ JVM       │  │
   │  │ vec (note_chunk halfvec)    │   └────────┬─────────┘  └───────────┘  │
   │  └──────────────┬──────────────┘            │ model-net                  │
   │                 │ nightly export            ▼                            │
   │  ┌──────────────▼──────────────┐   ┌──────────────────┐                  │
   │  │ tb-data                     │   │ vLLM judge       │                  │
   │  │ adapter (CSV/SS-MIX2/FHIR)  │   │ vLLM verifier    │                  │
   │  │ → OMOP upsert + provenance  │   │ (or sleep swap)  │                  │
   │  │ → lake export (DuckDB,      │   └──────────────────┘                  │
   │  │   read-only snapshots)      │                                         │
   │  │ embeddings (CPU, nightly)   │   ┌──────────────────┐                  │
   │  │ DQ + lineage on publish     │   │ metrics endpoint │ → hospital       │
   │  └─────────────────────────────┘   │ + heartbeat file │   monitoring     │
   │                                     └──────────────────┘                  │
   └──────────────────────────────────────────────────────────────────────────┘
          │ signed bundle in                       │ PHI-free: release id, health,
          ▼                                        ▼ canary, backup age (opt-in)
   Aimedics release pipeline ──────────────── Aimedics fleet view
   (CI gates · model qualification ·            (no patient data, ever)
    SBOM · release.json · site-acceptance box)
```

Five own processes instead of nine: `tb-app`, `tb-data`, `tb-compile`, `tb-gateway`, plus `postgres` and the two vLLM containers. HAPI runs only in CI for the equivalence gate.

**Merge.** console + orchestrator + mail-gateway → `tb-app` (one process, one scheduler, the outbox dispatcher as a thread, the console reads job state from SQL). adapter + lake + embed-service → `tb-data` (the nightly owner of the export; readers open DuckDB read-only). criteria-compiler + doc-parser → `tb-compile` (already one image). `datacore`, `sitesetup`, `matching`, `deliverables` → `libs/`.

**Split.** Nothing new. The one future split is the Aimedics side: a release pipeline and a fleet view that never see patient data, in a separate repository with a separate deploy.

**Delete.** `services/dataplat` (after lifting `dq` and `lineage`), `services/channels` except `grammar.py`, `services/registry` and `services/tracestore` as services (fold into the gateway), `services/rc_sim` to `tools/` or `tb_testkit`, `orchestrator/db_pg.py` after the outbox decision, the Hermes aliases, the root Auto-GPT tree.

**Order.** The merges are mechanical and should wait until P0 (§6) is done; they make the P0 items (metrics, pool, release id) cheaper to apply once rather than nine times, so do the merges first within P1. Do not merge and migrate to OMOP in the same quarter.

## 3. Scale and evolution

### 3.1 One site to ten sites to a consortium

| Stage | What changes | What exists | What is needed |
| --- | --- | --- | --- |
| One site | Install, run, support one box by hand. | Install, update, backup, audit. | P0 of §6: CI gate, release id, metrics, support bundle, scheduled backup, Docker drills. |
| Ten sites | Aimedics cannot visit each box. Boxes drift in release, model pin, vocabulary release, mapping. Support calls arrive without diagnostics. | Signed bundles; per-site measured serving records; `history.jsonl`. | A release channel (stable/next), a heartbeat file the site may opt to send (release id, health, canary, backup age, disk, mapping version: no PHI), a fleet view at Aimedics, a support bundle, a site-acceptance checklist per release, N-1 compatibility of bundles with site data. |
| Consortium | Counts and de-identified profiles cross hospitals under IRB. The vocabulary and cohort definitions must mean the same thing on every box. | Nothing. | A vocabulary release as a pack part with a release id; a cohort-definition file format with a signature; a count file schema with small-cell suppression and a signature; a receiver; a shared code-map registry at CGMH with a review workflow; a de-identification exporter with a re-identification test; site identity and key exchange. Version skew between boxes becomes the main risk. |

### 3.2 Version skew between sites

Today there is no version to skew. Once there is:

- Contracts are versioned in `schemas/` (for example `ctgov` 2.1.0, `update_manifest` 1.1.0) and generated into code. This is the right basis. Add: a compatibility table (bundle release × data schema version × vocabulary release × model pin), checked by `apply_update` before it touches anything, and anti-rollback (D-13).
- Consortium exchange files must carry `format`, `vocabulary_release`, `cohort_definition_version` and `producer_release`; a receiver refuses what it cannot read and says why. Never "best effort" across versions for counts.
- Rulesets are git-tagged per version and signed in the bundle. A ruleset approved at site A under vocabulary release R1 is not the same ruleset at site B under R2. The equivalence gate must re-run per site per vocabulary release, and the approval page must show which release it was approved against.
- Model pins differ per tier by design. The same prompt on two tiers (8k vs 32k) is two behaviours; the canary and N-12 must be recorded per tier, and the consortium must know which tier produced a count.

### 3.3 Schema evolution under OMOP

- Today's migration runner is a per-schema counter without checksums, split on `;` (E-11). It is fine for twenty small tables. OMOP adds 15+ tables, extension tables (`tb_fact_provenance`, `tb_fact_status`, `tb_conflict`, `tb_snapshot`), pgvector columns and a vocabulary that is *data*, not schema. Before OMOP: whole-script migrations, a sha256 per applied version, a dry-run mode, and a rule that a migration never runs during a job (the update path already stops the stack).
- The vocabulary (Athena-style `concept`, local concepts ≥ 2 B) must be loaded as a versioned release with its own table of releases, never as a migration. A site must be able to hold two releases during a re-approval window.
- The lake export is the compatibility contract for every approved ruleset's SQL: view names and column types must stay byte-stable or every ruleset needs re-approval. Commit the lake schema as data (`lake_meta.schema_version`, a JSON of columns) and a golden that fails on any change. The design's step 0 (goldens) is the single most important precondition.
- Dual-write period: adapter writes NDJSON and OMOP; parity test compares row for row for one night; then the lake flips to the OMOP export behind a flag; then NDJSON stops. This needs the feature-flag mechanism (§6 P0-8) to exist first.
- Backups grow with vectors and the CT.gov JSONB. The backup drill must include `cdm` and `vec` and measure time; a 2 TB disk fills faster than the owner's hardware note assumes once all history and embeddings are in.

### 3.4 Model upgrades and re-validation

What a model change should trigger, as one command, with one stored record:

1. Weight hashes verified and pinned (`pin_model`) — exists.
2. Serving record captured on the uncapped card (`serving_config capture`) — exists.
3. Pair canary, 54 cases, both tiers — exists as a gate at run time, not as a qualification step.
4. TREC N-12 ≤ 5 % — exists as a script run by hand.
5. `public_e2e` 112 checks on the pair — exists, run by hand.
6. Synthetic-hospital planted-defect run and funnel goldens unchanged — exists in pieces.
7. Prompt-injection suite — missing.
8. Drift baseline captured (unknown rate, exclusion rate, agreement per criterion) — missing.
9. A qualification record written to `eval/qualification/<build>.json` and the registry status moved `candidate → qualified → champion` by the tool — missing.
10. The box's admin page shows the champion build, its qualification date and the canary trend — missing.

The same pipeline must run for a *prompt* change, a *quantisation* change and a *vLLM* version change; the box's own rule already says these are model changes (A-17). Today each is a paid afternoon on a VM and a paragraph in DECISIONS. At ten sites that does not scale; at a consortium it is a validation finding.

### 3.5 Multi-tenancy and fleet tooling

Multi-tenancy inside a box is not needed and should not be built. The product is one hospital per box by law and by design. The Aimedics need is different: see many boxes without seeing their data. The minimum is a signed heartbeat the site opts into (release id, image digests, model pins, canary pass/fail and date, last backup age, disk free per volume, container restart counts, DQ summary counts), a fleet page at Aimedics, and a release channel. None of it carries a pseudonym. If a site refuses the heartbeat, the same JSON is the first page of the support bundle.

## 4. Developer experience

### 4.1 How a new engineer gets productive

Good: `README.md` "Try it" works and is honest: `make venv`, `make e2e-simple`, `make demo`. The eight documents are short and current. Every claim names a decision and a test. `doclint` keeps links alive.

Hard: the first `make test` takes 18 minutes serial and starts a throwaway Postgres cluster that leaks on Ctrl-C (E-02). Understanding *why* anything is the way it is means reading DECISIONS.md, 2,811 lines, append-only, with 140 entries whose later ones partly supersede earlier ones without saying so. The v4 spec (`spec/v4/`, nine files) and the design set (`docs/plan/design/`, 30 files) still describe Hermes, MCP, OpenBao, Podman, topology B Helm charts and `services/abstraction`, none of which exist. A newcomer cannot tell which document is the truth without being told "only the eight". There is no `CONTRIBUTING.md` in `trialbox/`; the one at the root is Auto-GPT's.

Estimate: two to three weeks to a first safe pull request for an experienced Python engineer; the domain (JP/TW coding systems, GCP rules, the two-model rule) is the long pole, not the code.

### 4.2 Local environment and dev containers

- The only dev container is Auto-GPT's at the repository root (`.devcontainer/devcontainer.json`), which builds the wrong Dockerfile.
- The developer stack (`make up-test`, 15 GB of images, GreenMail, MailHog) is documented and works, but was last run by the authors "not on Docker here" (D-139, D-140). CI never builds an image.
- Running the console alone needs Postgres binaries on the host (`tools/pglocal.py`) and `PYTHONPATH=libs:services:.`; the Makefile hides this, an IDE does not.
- No `uv.lock`; `make venv` resolves fresh, so two developers get different package sets (E-03, 32 of 74 differ).

Needed: a `trialbox/.devcontainer` with Python 3.12, Postgres 16 binaries, Java 21, Node, `uv sync --frozen`, and the pre-commit hooks; `make test` fast path under five minutes with `pytest-xdist` and the DB fixture made opt-in; one `make check` that is exactly what CI runs.

### 4.3 Docs for contributors

Present: ARCHITECTURE (good), the DECISIONS convention (good), schema-first contracts with a drift check (good), the `req` marker validated against spec IDs (good), docstrings that cite decisions (good).

Missing: `CONTRIBUTING.md` (branching, PR size, the "one PR per step" rule, how to add a decision, how to add a migration, how to add a `TB_*` variable, how to add an i18n string, how to add a scenario); a module map with owners; a "how to run a GPU qualification" page; a one-page "what is retired" list so the spec and design set stop misleading; a glossary (pid, mark, outcome, basis, proposed, space, tier, pin).

### 4.4 Code ownership

No CODEOWNERS. One human reviewer (`zandis`, 38 merge commits) merges pull requests written by an AI agent (189 commits). There is no second human who has read `matching/cascade/engine.py` or `criteria_compiler/compile_sql/generator.py`. For a product whose safety case rests on about six functions (the two-model rule, the quote check, `structured_candidate`, fail-closed families, the pseudonym, the audit append), a named human owner per safety-critical module is the minimum, with a rule that those files need a human review.

### 4.5 The bus factor, with an AI-built codebase as context

Observed properties of the codebase:

- **Consistency is high** because one author wrote 90 % of it in a month: one HTTP factory, one DB layer, one audit API, one error style, ruff and mypy strict clean on 718 files, 40 `type: ignore` in production code.
- **Function size is the symptom of agent-written code.** 29 F-grade and 29 E-grade functions; `e2e_simple.run` CC 162; `console/app.py` 1,724 lines; `console/studies.feas_report` CC 71. An agent that adds a stage appends to the function it was told about. Humans refactor when it hurts; the agent does not feel the hurt.
- **Documentation volume is high and decays fast.** Each step wrote its decision, its runbook paragraph and its spec row. The merge to eight documents (D-139) was the right correction; the spec and design set were left behind as "not maintained" and will mislead.
- **Tests are many and honest, and they were all written by the same mind that wrote the code.** Oracles are independent (planted counts, recounts), which is the saving grace. But the untested paths are the ones the author did not think of, and nobody else has looked: real SS-MIX2 from a vendor, OCR on Japanese scans, the compose rollback, the gateway in PRODUCTION (R-01 is exactly this class of gap).
- **Test reliability.** No order dependence found in a 391-test random sample; 16 `time.sleep`, 10 unfrozen `now()`; the Postgres fixture leaks. Reliability is acceptable today and will not survive `-n auto` without E-02.
- **Memory.** DECISIONS.md is the agent's and the owner's shared memory. It works because the agent reads it. A human replacement will not read 2,811 lines before their first change. The mitigation is cheap: a topic index at the top of DECISIONS, superseded markers, and ARCHITECTURE as the entry point it already is.

The cost of the bus factor, stated plainly: if the owner stops, the product stops. If the agent's context is lost (a new model, a new tool), the next agent has DECISIONS and the tests, which is better than most human teams leave. The highest-value mitigations are a second human engineer with ownership of the safety core, CI that enforces what the author now enforces by habit, and refactoring the twelve giant functions so a stranger can read them.

### 4.6 Journey run (in progress)

The draft at `/tmp/claude-0/review-journeys/cov/analysis.md` measured 44.4 % statement coverage across the role journeys so far (`tools/` at 16 % by design), with 65 console page routes and all 37 `/api/v1` routes never reached by a journey, 938 backend branches not reached, and 41 functions with no reference anywhere. Only the administrator journey had results at the time of reading; the first warning it logged is telling: there is no first-run set-up screen in the console, only the CLI wizard. The number to watch when the run finishes is how many of the 161 console routes a real role can reach by clicking; routes nobody reaches are either dead or missing from the user guide.

## 5. Scale and evolution risks worth naming before §6

Two cross-cutting observations before the list:

- **Order matters more than effort.** Goldens, CI gate, release id, connection pool and the Postgres image are each small. Each becomes large once OMOP, pgvector, profiles and a consortium exist. The owner's decision to run OMOP work "in parallel and merge only after Wave 1" is right; this review adds that the P0 list below is the real precondition, not Wave 1 alone.
- **The platform's weakest layer is the one nobody has been paid to feel yet: operations.** Every operations item below is "missing" because no hospital has run the box for a month. The first one will, and the first support call will be about disk, a reboot or "which version is this".

## 6. Missing components, prioritised

Effort: engineer-days for one engineer who knows the code, including tests and the document change. S ≤ 2, M 3–8, L 9–20, XL > 20.

### P0: before the first pilot site (about 70 days, 14 weeks)

| # | Component | Why now | What "done" is | Effort |
| --- | --- | --- | --- | --- |
| P0-1 | **CI gate** | A green pull request proves one path on one profile (E-01). | Jobs: lint (ruff, mypy, doclint, contracts, shellcheck, hadolint), test (pytest `-n auto`, Postgres service), e2e_simple, goldens, image build, `pip-audit`; on PR and push to master; nightly `public_e2e`, update drill, compose stack with `tests/integration`. | M (5) |
| P0-2 | **Goldens** | Every later step (OMOP, lake export, pool) must prove "counts unchanged". | `tests/golden/`: per-ruleset funnel at 5k and 50k, SCREEN candidate set, FEAS basis table, lake schema JSON; `--update-golden` with a diff; in CI. | S (2) |
| P0-3 | **Release identity and changelog** | A hospital cannot say which release it runs (D-35). | `release.json` baked at bundle build (release id, git sha, image digests, model hashes, schema versions, vocabulary release); shown on `/healthz` and the admin page; git tag; CHANGELOG checked by doclint; image tags per release. | M (4) |
| P0-4 | **Supply chain** | Lock without hashes, venv ≠ image (E-03). | `uv lock`, `uv sync --frozen`, `--require-hashes` in the Dockerfile, digest-pinned base image, CycloneDX SBOM as a bundle payload, THIRD_PARTY_NOTICES with the eight LGPL packages. | S (2) |
| P0-5 | **Metrics and alerts** | No signal between "healthy" and "the CRC calls" (D-22, A-14). | `/metrics` on `tb-app` and the gateway (jobs, canary, mail outbox states, DB pool, disk per volume, backup age, GPU via gateway status); thresholds on the admin tiles; a daily box-health mail to the admin address; VictoriaMetrics + vmalert as an optional compose profile for hospital IT. No pid in a label. | M (6) |
| P0-6 | **Support bundle** | Support asks for "the logs" and gets `.env` (D-23). | `trialbox support-bundle`: release.json, history, doctor and check_host output, compose config with secrets redacted, three days of scrubbed service logs, audit verify result, `df`, `nvidia-smi`, restart counts; a manifest; never `/data`. | S (2) |
| P0-7 | **Scheduled backup with age alert; drills on Docker** | The only automatic backup is the one before an update (D-19); install, update, rollback and restore have never run on a Docker daemon. | Nightly backup job to the configured targets, age on the health tile and in the metrics; a CI job (nightly, self-hosted or a cloud runner) that runs `install.sh` from a bundle on a clean Docker host, applies an update, rolls one back, restores a backup, kills Postgres mid-job and checks recovery. | M (8) |
| P0-8 | **Feature flags** | Five profile items, the OMOP dual-write, S2b on pgvector and the clinician layers are all "behind a flag" with no flag mechanism. | `tb_common/flags.py`: a flag table in Postgres (`app.flag`: name, scope site/study, value, who, when, reason), read with a short cache, shown and set on the admin page, every change audited; `TB_FLAG_*` only for tests. Replace the 55 undocumented `TB_*` knobs that are really flags. | S (3) |
| P0-9 | **Connection pool, reconnect, container limits, start order, Postgres image** | A Postgres restart takes every service down (A-02); no memory limits (A-05); the alpine image cannot take pgvector (layer 2 §1.2). | `psycopg_pool` with `configure=search_path`, `check_connection`; `/healthz` touches the DB; `mem_limit` per container from the tier; `depends_on: service_healthy`; `db` image on Debian with pgvector, digest-pinned, before any real data. | M (5) |
| P0-10 | **Model qualification command** | Every GPU run is by hand; the gateway path has never been run with the pair (R-01, R-15). | `trialbox eval qualify --build <id> --tier <t>`: pin, serving record, canary, N-12, public_e2e through the *gateway*, planted-defect run, goldens, a qualification record in `eval/qualification/`, registry status moved by the tool; the box refuses a champion without a record. Includes fixing R-01. | L (10) |
| P0-11 | **Prompt registry** | Prompts are files; a night cannot be traced to its prompt and schema except through the gateway trace. | Prompts and output schemas as registry objects (id, version, sha256, approved by, date); the gateway resolves by version; the admin page lists the active set; a change needs P0-10. | S (3) |
| P0-12 | **Missing-data model, v1** | B-01 excludes on a text value; "needs information" does not say what information. | A `missing_reason` per item (`not_in_feed`, `not_mapped`, `text_value`, `conflict`, `suppressed`, `proposed_unconfirmed`); carried from the SQL into the candidate and the PI page; the "needs information" list says which item and where it could come from; a per-source missingness count on the readiness page. | M (6) |
| P0-13 | **Roles the pilot needs** | Steward, PI reveal (D-143), admin without PHI, one permission function. | `steward` role; the matrix enforced in one `authz.permit(user, action, object)` used by every page and `/api/v1`; the walk's 403 matrix updated; reason-for-change on trial-record edits. Break-glass and sub-PI delegation move to P1 unless the pilot site has sub-investigators (question Q6). | M (7) |
| P0-14 | **Contributor baseline** | Bus factor (§4). | `trialbox/CONTRIBUTING.md`, CODEOWNERS with a human owner for the safety core, `trialbox/.devcontainer`, a topic index at the top of DECISIONS with superseded markers, a "retired systems" page that the spec and design set link to, the Auto-GPT tree removed from the root. | S (3) |
| P0-15 | **Wire or delete** | Two half-platforms confuse the OMOP work. | Decision Q3 implemented: `dataplat` lifted or deleted; outbox wired or deleted; `db_pg.py` merged; Hermes remnants removed; `datacore`, `sitesetup`, `matching`, `deliverables` moved to `libs/`. | M (4) |

### P1: the first paid sites (about 95 days)

| # | Component | What "done" is | Effort |
| --- | --- | --- | --- |
| P1-1 | **Task and inbox engine** | `app.task` (type, study, subject, assignee or role, due, state, origin event, outcome); created by marks, conflicts, proposed facts, referrals, uncertain sends, overdue visits; one inbox per person across studies; hand-over; N1/N2 become digests of tasks. The referral flow (owner, 2026-11-09) is the first task type. | L (12) |
| P1-2 | **Event-driven notifications** | An `app.event` table written by every state change; notification rules per role and person (in-app, mail, digest); the morning mails rebuilt on it; LINE/Teams later as transports. | M (6) |
| P1-3 | **EMR launch link** | A signed, expiring link from the candidate and patient pages to the hospital's EMR deep link (chart number resolved server-side at click, audited as a reveal); SMART on FHIR launch where the EMR supports it; the reverse (EMR to TrialBox patient page by pseudonym) as a configurable URL pattern. | M (5) |
| P1-4 | **Identity** | Authelia (or the hospital's IdP) in front with OIDC; TOTP fallback; LDAP/AD groups to roles including steward; password reset flow; monthly access report. | L (10) |
| P1-5 | **Search** | Header command field searches studies, pseudonyms, screening numbers, candidates, subjects and audit entries, scoped by role. | S (3) |
| P1-6 | **Vocabulary schema and terminology service** | Design step 3: one `vocab` schema, versioned releases, the compiler and site mapping resolve through it, a coverage report per site, the Parquet files become loaders. Precondition for OMOP. | L (10) |
| P1-7 | **Row-level provenance and trust on the lake** | Design step 2: `source_kind`, `source_system`, `source_record_id`, `trust`, `status_concept`, `value_text`, `lake_meta.schema_version`; the 疑い flag; B-01 and B-09 fixed; goldens identical. | M (5) |
| P1-8 | **Clinical conflicts and "excluded and why"** | Design step 6: `tb_conflict`, detection at ingest and publish, the conflicts page for steward and PI, the excluded-patients page with the weekly sample. | L (12) |
| P1-9 | **Opt-out and consent registry** | A consent object (scope, date, source, withdrawal) with a page to record a site opt-out; S0 reads it; the count on the feasibility page; the patient notice text per site. | M (5) |
| P1-10 | **Service merge** | §2.5: `tb-app`, `tb-data`, `tb-compile`, `tb-gateway`; the network sheet, tokens and health checks shrink accordingly. | L (12) |
| P1-11 | **Property and fuzz tests; parser fix** | `hypothesis` on dates, encodings, HL7 escape and MSH-2; python-hl7 or the 60-line fix; `tb_common/dates.py`, `phi.py`, `encoding.py`. | M (5) |
| P1-12 | **Load and soak** | `perf` suite: 50k ingest, FEAS and SCREEN against budgets at 1/10 scale per commit and full scale nightly; 20 concurrent console users in the walk; a seven-night soak on the site-acceptance box. | M (5) |
| P1-13 | **Site-acceptance environment** | One box (or VM) per release that mirrors a hospital: TLS proxy, SSO header, a real-shaped mail server, a vendor SS-MIX2 sample, a REDCap instance; `tools/acceptance.py` run there and its record attached to the release. | M (5) |
| P1-14 | **Public API contract** | Versioned OpenAPI for `/api/v1`, API tokens per integrator with scopes and rate limits, a snapshot test on the document, a changelog section. | S (3) |
| P1-15 | **Drift monitoring** | Weekly per-criterion rates (unknown, exclude, agreement, confidence) stored and charted on the admin models page; an alert on a two-sigma move; the qualification record as the baseline. | M (4) |
| P1-16 | **Cost and GPU budget** | A per-night model budget per tier with a warning at 80 % and a *fail*, not a silent truncation, at 100 %; a per-study monthly estimate on the study page; concurrency in S3/S4 to use the card. | M (5) |
| P1-17 | **Replay for reproducibility** | Every model answer recorded by input hash; `rerun` replays instead of calling; ARCHITECTURE §9 and acceptance step 6 made true. | M (4) |

### P2: scale (about 110 days, after the first paid sites run)

| # | Component | What "done" is | Effort |
| --- | --- | --- | --- |
| P2-1 | **OMOP CDM core and lake export** | Design steps 4 and 5 with dual-write, parity, flag flip; goldens identical. | XL (25) |
| P2-2 | **pgvector note chunks** | Design step 7a; S2b parity test; backup with `vec`. | L (15) |
| P2-3 | **Phenotype and item catalogue** | Catalogue tables, OHDSI definitions adopted through local maps, scores as data (design step 8), a steward page. | L (15) |
| P2-4 | **De-identification service** | Project pseudonyms, date shift, k-anonymity over quasi-identifiers, quotes off, export manifest, re-identification test on the synthetic hospital, the "what left this box" page. | L (12) |
| P2-5 | **Consortium v1** | Vocabulary release as a pack part, cohort-definition exchange, signed count files with suppression, a receiver, the shared code-map registry workflow, site identity. | XL (20) |
| P2-6 | **Fleet telemetry and release channel** | Opt-in signed heartbeat (no PHI), a fleet page at Aimedics, stable/next channels, N-1 compatibility table enforced by `apply_update`, anti-rollback. | L (12) |
| P2-7 | **Chaos suite** | Scheduled on the acceptance box: kill containers, fill a volume, restart Postgres under load, hang vLLM, power-loss during update; each with an expected recovery and a runbook line. | M (6) |
| P2-8 | **Incremental ingest and CDC** | Row-level change log from the adapter, same-day deltas for feed files, an MLLP or FHIR Subscription listener where a hospital offers one. | M (8) |
| P2-9 | **Historical back-fill** | Chunked, resumable, memory-bounded load of all history by year with progress and a per-year DQ report. | M (5) |
| P2-10 | **Profile narrative and layers** | Design steps 7b and 7c, after the above; device-qualification view written first. | XL (25) |

## 7. Technical risk register

Likelihood and impact: L low, M medium, H high. "Safety" marks a risk that can wrongly exclude a patient, miss a safety event or expose an identified patient.

| # | Risk | L | I | Safety | Mitigation | Owner of the fix |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | The production model path does not run on an installed box (gateway refuses D3; no hashes) and nobody notices until the first night at the site, because every gate used the stub or bypassed the gateway. | H | H | yes (silent "needs information" for every note) | R-01 fix; P0-10 runs `public_e2e` *through the gateway* in PRODUCTION mode; `doctor` fails when the gateway would refuse the judge; Gate G1 on the real pair. | engineering |
| 2 | A Postgres restart, idle timeout or OOM leaves every service broken until a human restarts it; the console still reports healthy. | H | H | no (outage) | P0-9: pool, reconnect, DB in `/healthz`, `depends_on: service_healthy`, memory limits. | engineering |
| 3 | A merge breaks 1,400 tests, mypy or a golden and ships, because CI runs none of them. | H | H | yes (an eligibility SQL change can pass CI) | P0-1, P0-2. | engineering |
| 4 | OMOP, pgvector and profiles are built on today's lake with no goldens, no pool, no release id and no flags; every one of those fixes is then done three times. | H | H | yes (counts drift unnoticed) | Do P0 before design step 2; the funnel goldens are the contract between the two work streams. | owner (sequencing) |
| 5 | Text-only lab values, suspected diagnoses and unmapped local codes exclude patients silently (B-01, 疑い, code silence). | H | H | yes | P1-7 with the missing-data model (P0-12); fail closed on values as on codes; the excluded-and-why page (P1-8). | engineering |
| 6 | No release identity: two boxes on `1.0.0` run different code; an auditor or a CAPA cannot name a release; a support call cannot start. | H | M | no | P0-3. | engineering |
| 7 | Nobody knows a box is unhealthy (disk, backup age, GPU, canary) until a CRC's list fails; the audit's own disk check turns a full disk into an outage. | H | M | no | P0-5, P0-7; `df` in doctor and check_host; log caps. | engineering, site IT |
| 8 | Bus factor one: the owner merges, the agent writes, no second human has read the safety core; a lost context or an absent owner stops the product. | M | H | yes (unreviewed safety change) | P0-14; a second engineer with CODEOWNERS on `matching/`, `criteria_compiler/compile_sql/`, `tb_common/audit.py`, `adapter/pidmap.py`; human review required on those paths. | owner |
| 9 | Model, prompt or vLLM upgrades are qualified by hand on a paid VM; at ten sites the gates are skipped, or run once and assumed for every tier. | M | H | yes (a regressed judge) | P0-10, P0-11, P1-15; one record per build per tier; the box refuses an unqualified champion. | engineering |
| 10 | Vocabulary and ruleset version skew across sites makes consortium counts incomparable; a ruleset approved under release R1 runs under R2 at another site. | M | H | yes (wrong feasibility counts) | P1-6 versioned releases; approval records the release; the equivalence gate re-runs per release; exchange files carry versions and are refused otherwise. | engineering, consortium lead |
| 11 | Two data platforms and an unwired outbox stay beside the new OMOP layer; documentation promises retry semantics the box does not have. | M | M | no | P0-15; ARCHITECTURE §9 corrected if the outbox is deleted. | engineering |
| 12 | The egress table is not persisted; after a reboot four services have unrestricted outbound until someone runs `network.sh apply`. | H | H | yes (PHI egress) | Install a systemd unit (D-01); `doctor` fails when the table is absent in PRODUCTION; the network sheet says so. | engineering |
| 13 | Configuration sprawl (121 `TB_*`, 55 undocumented, inconsistent `TB_ENV` default) produces a box that is PRODUCTION for services and DEV for `doctor`; unsafe defaults (`SECURE_COOKIE=0`) pass the check. | M | H | yes (cookie over http; secure defaults off) | P0-8 (flags replace knobs); one `Env` declaration with a test that every read is declared; `doctor` uses `environment_name`; `check_host` greps for test passwords. | engineering |
| 14 | The GPU is shared by screening, the coming profiles, embeddings and chat with no scheduler or budget; the 5090 tier cannot host profiles; a hung vLLM stalls a run for 600 s per call and cannot be cancelled. | M | M | no (lost nights, cost) | P1-16: budget with fail-not-truncate, concurrency, cancel in the cascade loop, a circuit breaker; the tier table says "no narrative on small". | engineering |
| 15 | The AI-written codebase's giant functions (CC > 100 in the acceptance scripts, `console/app.py` 1,724 lines) and ten i18n Python files make every change by a newcomer risky and slow; refactoring is deferred because the author does not feel it. | M | M | no | `C901` max 25 in `make lint` for new code; the `Stage` registry; i18n to data; split `app.py` by page module; a refactor budget of one day per plan step. | engineering |

Not in the top 15 but recorded: SNOMED licence cost and the non-standard CDM; Gemma 4 licence text unread by counsel; PaddleOCR 2.x API on 3.x; the hosted demo's unsigned patch from metadata; the paid-VM off-switch; audit written after state (A-19); clock drift tolerated (A-20).

## 8. Questions for the owner

Each with options and a recommendation. Decided items of 2026-11-08 and 2026-11-09 are not re-asked.

| # | Question | Options | Recommendation and why |
| --- | --- | --- | --- |
| Q1 | Does the P0 list (§6, about 14 weeks) go before the OMOP, catalogue and profile work, or in parallel with it as the current plan says? | (a) P0 first, OMOP after; (b) parallel with a second engineer; (c) OMOP first. | **(a), or (b) only with a second engineer and the goldens (P0-2) done first.** Every P0 item is a precondition the OMOP work will otherwise re-pay three times (risk 4). |
| Q2 | Service decomposition: merge to five own processes (§2.5) or keep the nine? | (a) merge in P1; (b) keep nine, add the P0 items to each; (c) merge now. | **(a).** The merge is mechanical and removes eight health checks, tokens and crash loops; doing it before P0 delays the gates, doing it never multiplies every operational fix by nine. |
| Q3 | `services/dataplat`: wire its DQ and lineage into the adapter publish gate and delete the rest, move it whole under `tools/`, or delete it? | (a) lift `dq` and `lineage`, delete the rest; (b) `tools/`; (c) delete. | **(a).** The design needs trust and provenance columns at publish; `dq` and `lineage` are the two pieces that fit. The L0–L5 pipeline, MPI and reconcile duplicate what OMOP will provide. |
| Q4 | The outbox: wire the dispatcher or delete it and correct ARCHITECTURE §9? | (a) wire; (b) delete, keep idempotency keys, document synchronous delivery; (c) replace with procrastinate. | **(a).** Mail outages are the most common failure at a hospital; the code exists and is tested; the dispatcher thread lives naturally in `tb-app`. (b) is acceptable if (a) does not fit before the pilot; (c) only if (a) fails. |
| Q5 | Feature flags: a flag table in Postgres with an admin page, or keep environment variables? | (a) flag table; (b) env vars documented; (c) a flag file in `deploy/`. | **(a).** Per-study and per-site switches, audit of who flipped what, and a kill switch at run time cannot be environment variables; the profile work needs five flags on day one. |
| Q6 | Which roles are in the pilot: steward and PI reveal only, or also sub-PI delegation and break-glass? | (a) steward + PI reveal (P0-13); (b) add delegation; (c) add delegation and break-glass. | **(a) unless the pilot site names sub-investigators, then (b).** Break-glass needs a second person on a rota and MFA; both are P1. |
| Q7 | Fleet heartbeat: opt-in signed PHI-free heartbeat to Aimedics, or support bundle only? | (a) opt-in heartbeat plus bundle; (b) bundle only, ever; (c) heartbeat default on. | **(a).** A hospital that refuses sends the same JSON by hand. (c) contradicts "nothing leaves the box unless the site says so". |
| Q8 | Release cadence and channel: monthly releases with a stable and a next channel, or on demand? | (a) monthly, stable/next, N-1 supported; (b) on demand; (c) quarterly. | **(a).** The reference pack already refreshes monthly; a cadence makes the qualification pipeline (P0-10) routine instead of an event. |
| Q9 | Site-acceptance environment: one physical box at Aimedics per tier, one VM, or the cloud GPU VM on demand? | (a) one `large` box at Aimedics plus a VM for `small`; (b) cloud only; (c) none, the first site is the test. | **(a).** The compose path has never run on real Docker; the cloud VM has already cost an unbounded hour (D-30); a hospital must not be the first host. |
| Q10 | EMR launch: a signed deep link into the hospital's EMR (configured URL pattern), SMART on FHIR, or neither in P1? | (a) deep link P1, SMART when a site supports it; (b) SMART only; (c) neither. | **(a).** Japanese and Taiwanese EMRs rarely offer SMART; a URL pattern with a server-side chart-number resolve, audited as a reveal, gives the PI the one click they asked for. |
| Q11 | Task and inbox engine: build it as the base for referral, conflicts and proposed facts (P1-1), or keep four separate queues? | (a) one task engine; (b) separate queues, unify later; (c) referral only. | **(a).** Four queues with four UIs is the current trajectory; the referral decision of 2026-11-09 is the natural first task type and would otherwise be a fifth queue. |
| Q12 | A second human engineer with ownership of the safety core: hire or contract now, or after the pilot? | (a) now, part-time, CODEOWNERS on the six files; (b) after the pilot; (c) the AI agent plus the owner suffices. | **(a).** Risk 8 is the only risk on the register that no code change mitigates. |
| Q13 | SNOMED: record the no-licence decision (`*_concept_id = 0`) in DECISIONS with the USD 1,954 per system per year figure, or buy for the product? | (a) record no-licence for v1; (b) Aimedics buys one affiliate licence per box; (c) wait. | **(a), written down.** Screening does not need it; the consortium's network studies will, and that is the moment to buy per hospital. "Wait" leaves the design document's answer unrecorded. |
| Q14 | The spec (`spec/v4/`) and design set (`docs/plan/design/`): archive with a one-page "retired systems" note, or keep as is? | (a) archive both with the note; (b) keep as is; (c) rewrite. | **(a).** They name Hermes, MCP, Podman, OpenBao and services that do not exist; a newcomer cannot tell. The eight documents and DECISIONS are the truth and should say so at the top of both folders. |

## 9. What is good and should not be touched

- The safety core: fail-closed code families, the two-model rule, the quote check, unknown never excludes, the canary gate. Six functions carry the product; they are tested with independent oracles.
- Pseudonym at the door and the encrypted pid map.
- Schema-first contracts with a drift check.
- The audit chain and its verifier.
- Signed bundles, the backup to a key the box cannot read, measured tiers.
- DECISIONS.md as an evidence-bearing ADR log, and the honesty of "not done" throughout the documents.
- The console's three-language, phone-first, role-home design and the walk that holds it.
- Reproducible gates on synthetic data with recounts from the source.

## Appendix A. Files read

`docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md` §3, `docs/DATA.md` §1–2, `docs/VALIDATION.md` §1, §4, `docs/USER_GUIDE.md` §2, `docs/DECISIONS.md` (D-120 to D-140 headings, D-140 whole), `docs/plan/24-plan-v4.md`, `docs/plan/fable-review-2026-11-08.md`, `docs/plan/design/19-platform-functions.md`, `docs/plan/design/19a-completeness-table.md`, `docs/reviews/2026-11-09-full-system-review.md`, `docs/reviews/2026-11-09-review-parts/01`, `04`, `05`, `docs/reviews/2026-11-09-component-review-layer1.md` §1, `-layer2-verification.md` §1–2, `docs/reviews/2026-11-09-standalone-db-vector-profiling-review.md` §0, §6, `docs/reviews/2026-11-09-design-patient-data-and-roles.md` §1, §5, §6, `docs/reviews/2026-11-09-owner-decisions-data-and-profile.md`, `spec/v4/16_vv_engineering_operations.md` §17, `README.md`, `Makefile`, `pyproject.toml`, `tests/conftest.py`, `.github/workflows/trialbox-e2e.yml` (repository root), `deploy/docker-compose.yml`, `deploy/docker/python.Dockerfile`, `deploy/install.sh` (header), `libs/tb_common/db.py`, `libs/tb_common/config.py`, `libs/tb_common/service_auth.py`, `libs/tb_common/reasons.py`, `services/orchestrator/outbox.py`, `scheduler.py`, `selftest.py`, `app.py` (routes), `services/console/app.py` (imports, routes), `notify.py`, `auth.py`, `services/datacore/lifecycle.py`, `services/gateway/core.py`, `services/dataplat/__init__.py`, `services/matching/cascade/engine.py` (consent), `services/guard/guard.py`, `models/registry.yaml`, `models/routing.yaml`, `tools/trialbox/__main__.py`, `tools/trialbox/doctor.py`; directory listings of `services/`, `libs/`, `tools/`, `tests/`, `eval/`, `schemas/`, `spec/`, `docs/handover/`; `git log` for authorship and cadence; `/tmp/claude-0/review-journeys/cov/analysis.md`, `report.txt` and `results/admin-*.json` (draft).

## Appendix B. Counts used

Own Python: services 66,000 lines (console 15,922; orchestrator 15,679), libs 8,500 (3,893 generated), tools 28,000, tests 26,557 in 157 files (108 unit, 22 integration, 13 console, 3 e2e, 3 testbench, 1 llm). Containers: 13 (9 own). Console routes: 161 (37 `/api/v1`); orchestrator routes: 15. `TB_*` variables read in `libs/` and `services/`: 121. Commits since 2026-10-04: 220, of which 189 by the AI agent and 38 merges by the owner; 131 on 2026-11-08 and 2026-11-09 alone. Unit suite: 1,423 cases, 18 min serial, 84 % coverage of services and libs. Journey draft: 44.4 % statement coverage, 65 page routes and 37 API routes unreached.
