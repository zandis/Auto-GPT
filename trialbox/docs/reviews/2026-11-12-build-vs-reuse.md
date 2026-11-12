# Build versus reuse: what open source could replace, and what is ours to build

Date: 2026-11-12. Asked by the owner: "is any of our construction something someone has open-source and can be used
instead of writing it ourselves?" Scope: `trialbox/` on `master` at `4ed01da3`, and the open pull requests by their
titles and file lists. Method: line counts with `git ls-files` and `wc -l`; module docstrings and the deep review of
2026-11-12 read; outside projects checked by web search on 2026-11-12. No product file was changed. Nothing was run
that costs money. Synthetic data only. Paths are relative to `trialbox/`.

How a fact about an outside project is marked:

- **[V: page]** verified today by a search result; the page is named.
- **[M]** from memory; to be checked on the project's own licence file or release page before anyone acts on it.

No version number or licence term in this file is invented. Where two sources disagreed, both are named.

The hard constraints every candidate was judged against: it runs offline on one box (a Windows workstation with WSL2
and Docker, one GPU); a hospital and a commercial vendor can accept its licence (copyleft such as AGPL or GPL inside
a service image is a problem to name, as the licence gate `tools/supply_chain/licences.py` does); no data leaves the
box; a research lead can operate it, not an IT team; Japanese and Traditional Chinese work where it touches text;
the image can be pinned, rebuilt and scanned.

The verdicts: **ADOPT NOW** (it replaces code not yet written or still in an open pull request, or removes a known
open risk cheaply), **ADOPT AFTER GO-LIVE** (worth it, but ours works and a switch before 2027-04-28 is risk),
**USE BESIDE** (a tool for people or for CI, not in the product), **BENCHMARK ONLY**, **KEEP OURS**.

## 1. The answer in ten lines

1. Most of what could be reused already is: PostgreSQL with pgvector, DuckDB, vLLM, the HL7 validator, the CQL
   translator, Docling, Authelia, Caddy, Prometheus, APScheduler, Trivy, pip-audit, detect-secrets, bandit.
2. About 200,000 lines of Python are not tests. The generic mechanisms this review could name are about 75,000 of
   them, 13,000 of those being message texts (section 3.2). The rest is clinical logic, the console and tools for
   the trial.
3. **Group 1, replaceable outright (可以直接用現成方案取代)** is small: the embedding server, the incremental part of
   the backup, the REDCap simulator, the hand-written OIDC client, the test shard splitter, the bake-off tools, a
   step engine nobody calls. About 4,600 lines to delete over time and roughly 8 to 14 session-days not to spend.
4. **Group 2, partly done by others (部分有人做過)** is the largest: the job queue, the lake's generations, the PHI
   tripwire, the OMOP checks, the keys, the installer and update bundle. A project covers the base; our rules sit
   on top. For most of these the honest verdict before go-live is to keep ours and to stop growing them.
5. **Group 3, nobody has really done it (真的沒人做過)** is where the product is: criteria compiled to SQL that a
   model never writes, the cascade with the two-model rule, the opt-out and erasure obligations across every store,
   and the whole of it on one offline box in three languages. Prior work exists for each part and stops short of
   each (section 6).
6. Three pieces being written right now have a mature project behind them: the embedder image (Hugging Face Text
   Embeddings Inference), the REDCap test instance (a community compose project; PyCap as a second client), the
   incremental backup of wave 3 (restic, and pgBackRest which is already in our database image).
7. Four pieces being written right now have none: the Windows installer, the CGRD connector, the actor assertion,
   the scale gate. They stay ours. Tools that help beside them are named.
8. One candidate is a clear no: a general LLM gateway. The best known one had its release pipeline compromised
   twice in 2026, and its default behaviour (fall back to another model) is the thing our gateway forbids.
9. Three defects found this week would not have happened on a standard tool: jobs re-run from zero after a restart
   (a durable job library), a backup that copies everything every night and fails when a file changes (a
   deduplicating backup tool), and passwords in the support bundle (a secret scanner run on our own output).
10. The fastest gains are not in code. They are the merge gate, the runner queue and the cost of long sessions
    (section 8, actions 1, 2 and 11).

## 2. Summary table, sorted by verdict

"Our lines" are non-test Python lines at `4ed01da3` unless marked. "Replaces" means the part a project would take
over, not the whole file.

| Verdict | Mechanism | Candidate | Our lines it would replace | One-sentence reason |
| --- | --- | --- | --- | --- |
| ADOPT NOW | Embedding server (PR #341, #367) | Hugging Face Text Embeddings Inference | `embed_service/embedder.py` model mode (about 100 of 218), a 949-line hashed lock (#341) | One pinned image instead of a Python and torch stack we lock, scan and patch; decide by a one-day spike before #341 lands. |
| ADOPT NOW | Incremental backup (wave 3, not written) | restic for the lake files; pgBackRest (in the db image) for the database | none today; avoids new code in `tools/trialbox/backup.py` (1,528) | PERF-010, PERF-011 and ENG-011 are what a deduplicating backup tool solves by design; our rules stay as a wrapper. |
| ADOPT NOW | Key back end on Windows (NEW-WIN-8, not written) | Windows DPAPI and BitLocker; `age` for the recovery copy | none today; no new crypto beside `tb_common/kek.py` (604) | The platform already has the mechanism; a second recipient gives the recovery copy OPS-001 says is missing. |
| ADOPT NOW | REDCap conformance (NEW-EDC-1, wave 2) | cassettes from the real instance; PyCap as a second client in R1 to R9 | `rc_sim` (576) stops growing, then goes | Do not make the simulator strict; record the real one. A second, widely used client tells our client's faults from REDCap's. |
| ADOPT NOW | Text decoder for uploads (UX-004, wave 4, not written) | charset-normalizer | none today | Shift_JIS and Big5 detection is a solved problem; write the refusal rule, not the detector. |
| ADOPT NOW | Name detection in the tripwire (NEW-LLM-3/4, wave 2, not written) | a Japanese and a Chinese tokeniser with part-of-speech tags; Presidio as the yardstick | part of `guard/recognisers.py` (218) and `tb_common/phi_guard.py` (298) | LLM-003 is a regular expression guessing where a name starts; a tokeniser knows. Measure before writing more patterns. |
| ADOPT AFTER GO-LIVE | Job queue, leases, resume | DBOS Transact or Procrastinate (both on PostgreSQL) | `orchestrator/db.py`, `db_pg.py`, `outbox.py`, `scheduler.py`, parts of `core.py` and `jobs.py` (about 2,300 of 3,382) | A library gives attempts, leases and recovery; ours got them this week after ARCH-001. Switching the night before go-live is risk. |
| ADOPT AFTER GO-LIVE | Lake snapshots and generations | DuckLake | the snapshot, `CURRENT`, retention and lock handling in `lake/store.py` (about 500 of 1,233) plus #318 | Snapshots, time travel and changed-files-only storage on the two engines we already run; erasure under time travel must be designed first. |
| ADOPT AFTER GO-LIVE | OIDC client | Authlib | `console/oidc.py` (392) | Hand-written token checks are a known risk class; ours is tested and off by default, so it can wait. |
| ADOPT AFTER GO-LIVE | Message catalogues | gettext files with Babel | the mechanism only; 12,973 lines are the texts | Worth it when outside translators join; today the catalogues are complete and tested. |
| ADOPT AFTER GO-LIVE | OMOP quality checks | OHDSI DataQualityDashboard, its SQL generated at build time | `omop/dqd.py` (423) stays as the fast gate | About ten of our checks against the community's full set; first use it beside the box (below). |
| ADOPT AFTER GO-LIVE | Signed update metadata | The Update Framework (python-tuf); cosign for images | `tools/verify_update.py` (554), `tools/sign_bundle.py` (211) | Ours re-implements roll-back and key-rotation rules a standard defines; changing the trust root before go-live is risk. |
| USE BESIDE | Source profiling and code mapping (T-731) | OHDSI WhiteRabbit, Rabbit-in-a-Hat, Usagi | none | The CGRD mapping step is people's work; these are the community's tools for it. |
| USE BESIDE | OMOP characterisation | OHDSI Achilles, DataQualityDashboard on the acceptance box | none | A second opinion on the first real night, from R, not in the product. |
| USE BESIDE | Model evaluation outside qualification | Inspect | `tools/bakeoff.py`, `bakeoff_live.py`, `judge_bakeoff.py`, `mlbench.py` (2,551, frozen to wave 11) | A maintained harness for comparisons; the qualification record stays ours. |
| USE BESIDE | Test splitting | pytest-split (by recorded durations) | `tools/test_shard.py` (176) | Shards by a hash of the path are uneven; durations balance them. |
| USE BESIDE | Secret scan of our own outputs | detect-secrets (already pinned), gitleaks | none | Run it on the support bundle and the logs, not only on the repository (OPS-002). |
| USE BESIDE | Per-test memory limits | memray with its pytest plug-in | none | A cap per test would have shown PERF-001 before a 50,000-patient run. |
| USE BESIDE | Change fragments | towncrier-style fragment files | none | The append-only files every lane edits stop colliding (plan v7 section 5). |
| BENCHMARK ONLY | Trial matching | TrialGPT, Criteria2Query, Leaf and LeafAI | none (`tools/trialgpt_compare.py`, 454, exists) | They answer a different question or need a cloud model; they are yardsticks. |
| BENCHMARK ONLY | Cohort SQL from OMOP | OHDSI ATLAS, CIRCE, Capr | none | A third engine for the differential of T-711, not a run-time engine. |
| BENCHMARK ONLY | PHI detection | Microsoft Presidio | none | English by default; Japanese and Chinese need models and recognisers we would write anyway. |
| KEEP OURS | LLM gateway | LiteLLM proxy and similar | `services/gateway` (2,309), `libs/tb_llm` (1,480) | Its rules are the product's safety; the candidate's 2026 record rules it out. |
| KEEP OURS | Audit hash chain | immudb, Trillian, Rekor | `tb_common/audit.py`, `audit_writer.py`, `tools/audit_verify.py` (1,473) | The defect was a missing timer, not a missing library; a log server is one more thing to run. |
| KEEP OURS | Authorization matrix and `permit` | Casbin, Cedar, OPA, OpenFGA | `tb_common/authz.py` (363), `authz_matrix.yaml` (784) | Seven roles and one function; an engine adds a language and removes nothing. |
| KEEP OURS | Trace store, model and prompt registries | Langfuse, Phoenix, MLflow | `tracestore` (267), `registry` (609), `tb_llm/prompt_registry.py` (722) | Small, with redaction at write and fail-closed pins; the servers are heavier than what they replace. |
| KEEP OURS | Opt-out, erasure, pseudonyms | Fides; gICS, gPAS, Mainzelliste | `tb_common/erasure.py`, `optout.py` (814), `adapter/pidmap.py` (294) | None covers a lake, vectors and backups on one box; three of them are AGPL services. |
| KEEP OURS | Windows installer, CGRD connector, actor assertion, scale gate | none found | PRs #362, T-731, #317, #298 | No project does these; section 4 names what helps beside them. |
| KEEP OURS | Synthetic hospital | Synthea | `tools/synth`, `tools/synth_hospital` and helpers (4,491) | Synthea has no Japanese or Chinese notes, no SS-MIX2 and no per-criterion ground truth. |
| KEEP OURS | Supply-chain, licence, data-scan, doc-lint, decision-index tools | syft, grype, ORT, ScanCode, adr-tools, log4brains | 3,233 + 634 + 616 | They are thin glue over standard scanners already; the rules in them are ours. |

## 3. What was built (step 1)

### 3.1 Services, libraries and tools

"Tests" is rough: the total lines of every test file under `tests/` that imports the package. A test file that
imports three packages is counted three times. Read it as "how much test code would notice a change".

| Package | Python lines, not tests | Files | Test-file lines that import it | What it does |
| --- | --- | --- | --- | --- |
| `services/console` | 36,259 | 101 | 26,364 | The product: sign-in, roles, every page, `/api/v1`, timers. 12,528 of the lines are the message catalogues. |
| `services/orchestrator` | 19,811 | 67 | 37,616 | Jobs (FEAS, SCREEN, CASE, NAV, COHORT and more), reports, delivery, the canary gate. |
| `services/adapter` | 7,868 | 31 | 17,527 | Hospital data (CSV, SQL views, SS-MIX2, FHIR bulk) to FHIR NDJSON and the lake, with pseudonyms and the night's gate. |
| `services/omop` | 5,134 | 11 | 8,110 | The OMOP CDM v5.4 store of record: load, vocabulary, export to the lake, a small set of quality checks. |
| `services/criteria_compiler` | 5,018 | 28 | 17,100 | Protocol text to criterion IR, then SQL and CQL from templates, with the equivalence gate. |
| `services/matching` | 4,382 | 24 | 10,795 | The cascade, coverage, and the vendored registry matcher. |
| `services/datacore` | 4,151 | 13 | 8,849 | Study forms, field values with provenance, two-way sync with each source. |
| `services/edc` | 4,010 | 12 | 4,522 | EDC prefill with citations, signing, ODM and REDCap export. |
| `services/sitesetup` | 3,593 | 11 | 10,616 | Readiness, chart upload, proposed facts, code mapping. |
| `services/lake` | 2,887 | 8 | 20,338 | DuckDB lake per snapshot: read-only SQL, note search. |
| `services/gateway` | 2,309 | 6 | 6,477 | The only path to a model: routing by data class, slots, breaker, the one-GPU swap. |
| `services/deliverables` | 1,925 | 6 | 584 | The feasibility pack (plan v7: drop or move under `tools/`). |
| `services/mail_gateway` | 1,513 | 7 | 2,353 | Mail in and out, sender checks, the outbox. |
| `services/rc_bridge` | 786 | 5 | 4,711 | The REDCap client, link and write-back. |
| `services/llm_stub` | 776 | 3 | 8,071 | A deterministic model stand-in for CPU CI. |
| `services/vec` | 714 | 5 | 1,739 | The vector store in pgvector, the chunker and the note index. |
| `services/doc_parser` | 612 | 4 | 1,969 | PDF, Word and text to sections and criteria blocks (Docling in the production image). |
| `services/registry` | 609 | 4 | 4,703 | Model registry: alias to pinned build, fail closed. |
| `services/rc_sim` | 576 | 3 | 4,696 | A REDCap API simulator written from the public documentation. |
| `services/guard` | 540 | 5 | 5,520 | PHI recognisers for Taiwan and Japan, the tripwire, the planted-instruction screen. |
| `services/patient_profile` | 475 | 2 | 1,168 | The patient twin, assembled from a pinned snapshot. |
| `services/channels` | 420 | 6 | 3,657 | The channel abstraction (frozen). |
| `services/embed_service` | 269 | 3 | 17,669 | Dense embeddings: the pinned embedder in production, feature hashing in CI. |
| `services/tracestore` | 267 | 3 | 2,259 | Redacted model traces with an access log and retention. |
| `services/model_guard` | 218 | 2 | 1,224 | A key-checking front for the model servers' routes outside `/v1`. |
| `services/opportunity_hub` | 218 | 2 | 830 | The hub side of the opportunity feed (frozen). |
| `libs/tb_common` | 16,929 | 58 | 77,068 | Config, audit chain, database layer, service tokens, crypto and keys, PHI guard, erasure, opt-out, flags, metrics. |
| `libs/tb_contracts` | 4,896 | 8 | 35,723 | Generated from `schemas/`: every contract. |
| `libs/tb_llm` | 1,480 | 6 | 7,133 | The one model client, the prompt registry, budgets, outage handling. |
| `libs/tb_testkit` | 254 | 3 | 1,225 | Markers, planted-defect generators, fakes. |
| `tools/` (all) | 70,118 | | | 175 Python files. The largest groups follow. |
| `tools/trialbox` | 12,516 | 19 | | The box's command: backup, restore, update, doctor, watchdog, secrets, logs, platform checks. |
| `tools/synth`, `tools/synth_hospital` | 3,137 | 14 | | The deterministic synthetic hospital. |
| `tools/supply_chain` | 2,314 | 9 | | SBOM, licence and vulnerability gates, the release record. |
| `tools/scenarios.py`, `e2e_simple.py`, `complete_run.py`, `build_site.py` | 7,916 | 4 | | The end-to-end runs and the public site build. |
| `tools/qualify.py` and the evaluation tools | 5,764 | 10 | | Qualification of a model pair, the bake-offs, the canary, the pin. |

Totals: 313,587 Python lines tracked under `trialbox/`; 111,942 of them are in test files.

### 3.2 The home-made mechanisms that are generic infrastructure

| Mechanism | Where | Lines | Test-file lines (rough) | The rule in it that is ours |
| --- | --- | --- | --- | --- |
| Job queue, pinning, scheduler, outbox, durable steps | `orchestrator/db.py`, `db_pg.py`, `outbox.py`, `jobs.py`, `scheduler.py`, `core.py`; `tb_llm/outage.py` | 3,382 | 10,213 | A job reads one lake snapshot from its first call to its end; every state change is audited; a re-run is byte-identical. |
| Lake snapshots, `CURRENT`, locks, SQL guard | `lake/store.py`, `sqlguard.py`, `source.py`, `client.py`, `app.py` | 1,999 | 15,680 | A failed night is held and `CURRENT` stays; a night that drops over 20 % of a kind is refused; SELECT only. |
| Gateway: routing, slots, breaker, retries, budgets, swap | `services/gateway`, `libs/tb_llm` (client, budget, timeouts, outage), `tb_common/policy/classes.py` | 3,416 | 6,198 | No answer from another alias unless the route says so (`gateway/core.py:475`); every refusal audited; the prompt must be the registered one. |
| PHI tripwire and planted-instruction screen | `services/guard`, `tb_common/phi_guard.py` | 838 | 6,853 | Any hit blocks, whatever the class label says; a wrong check digit is still redacted. |
| Embedding service | `services/embed_service` | 269 | 18,050 | PRODUCTION refuses the hash stand-in; the vector's dimension is checked. |
| Vector store and index | `services/vec` | 714 | 1,739 | A note is masked before it is chunked; erasure removes chunks and orphan vectors. |
| Trace store | `services/tracestore` | 267 | 2,259 | Redaction at write; every read needs a purpose and is logged. |
| Model and prompt registries | `services/registry`, `tb_llm/prompt_registry.py` | 1,331 | 7,935 | A build without a sha256 is refused; a prompt whose text or schema differs from the registry is refused. |
| Audit hash chain and its drain | `tb_common/audit.py`, `audit_writer.py`, `tools/audit_verify.py` | 1,473 | 28,403 | One writer role; signed heads; an event carries input and output hashes and recipients. |
| Backup, schedule, restore drill | `tools/trialbox/backup.py`, `backup_schedule.py`, `tools/backup_drill.py` | 3,430 | 6,089 | The box holds only the public key; one snapshot per database; a restore re-applies later opt-outs. |
| Watchdog | `tools/trialbox/watchdog.py` | 394 | 3,354 | A restart on a failed health check is audited. |
| Keys and secrets | `tb_common/kek.py`, `crypto.py`, `tools/keys.py`, `tools/trialbox/svc_secrets.py` | 1,675 | 4,999 | Site keys wrapped under a KEK with Shamir, passphrase or TPM back ends; one token per service. |
| Sign-in: accounts, sessions, TOTP, OIDC | `console/auth.py`, `identity.py`, `oidc.py`, `totp.py` | 2,101 | 10,343 | No default password; no session without a second factor outside DEV and TEST. |
| Authorization and service tokens | `tb_common/authz.py`, `service_auth.py`, `authz_matrix.yaml` | 1,613 | 12,096 | One matrix, one `permit`; each service accepts only its listed callers. |
| Message catalogues | `console/i18n*.py`, `orchestrator/i18n.py` | 12,973 | 16,366 | Every key in three languages, checked by a test; no simplified characters. |
| REDCap client and simulator | `services/rc_bridge`, `services/rc_sim` | 1,362 | 5,201 | Errors map to the interface register; the token is never logged. |
| OMOP loader, vocabulary, export, checks | `services/omop` | 5,134 | 8,430 | Before-images, tombstones, conflicts and provenance in `tb_*` tables. |
| FHIR mapping and validation | `adapter/validate`, `adapter/ndjson.py`, `load_fhir.py`, `tb_common/fhir.py`, three tools | 2,152 | 6,693 | A 1 % sample through the HL7 validator; above 0.5 % errors the night is held. |
| CQL and SQL generators, equivalence gate | `criteria_compiler/compile_cql`, `compile_sql`, `equivalence`, two tools | 2,040 | 15,726 | Templates only, never a model; byte-identical output for the same IR. (This one is product, not infrastructure.) |
| Ingest contracts and quarantine | `adapter/governance.py` | 771 | 488 | A table without a contract holds the night; one gate record per night. |
| Synthetic hospital | `tools/synth`, `tools/synth_hospital`, four helpers | 4,491 | 3,982 | True, false and unknown cases for every criterion, with ground truth. |
| Document parser | `services/doc_parser` | 612 | 2,631 | Hidden text in a mailed protocol is found and reported. |
| Mail gateway | `services/mail_gateway` | 1,513 | 3,767 | Sender checks; patient-level files only to the internal list. |
| Supply chain, images, licence register, security scan | `tools/supply_chain`, `images_lock.py`, `image_pins.py`, `licence_register.py`, `security_scan.py` | 3,233 | 5,372 | The allow-list is per package and per flag; a stricter licence fails again. |
| Data scan | `tools/data_scan.py` | 634 | 751 | No real identifier in the repository or a log, archives included. |
| Doc lint and decision index | `tools/doclint.py`, `decisions_index.py` | 616 | 1,534 | Nine documents; one decision number, one text. |
| Shards, coverage ratchet, mutation | `tools/test_shard.py`, `coverage_ratchet.py`, `mutation.py` | 956 | 906 | Every test in exactly one shard; no package loses coverage unnoticed. |
| Installer, box plan, update bundle | `tools/box`, `tools/trialbox/update.py`, `verify_update.py`, `sign_bundle.py`, the install scripts, `deploy/windows` | 6,144 (Python and shell) | 13,821 | Signed manifest with a release sequence, a lowest installed version, an expiry and key rotation; back up first; roll back on failure. |
| Qualification and evaluation | `tools/qualify.py` and nine tools | 5,764 | 14,978 | A pair becomes `champion` only with a record measured on its own hardware. |
| Feature flags | `tb_common/flags.py` | 424 | 3,342 | Every change audited with actor and reason. |
| Database layer and migrations | `tb_common/db.py`, `migration_baseline.py` | 612 | 10,503 | Versioned, checksummed migrations per schema. |
| Health, metrics, doctor | `tb_common/metrics.py`, `tools/trialbox/doctor.py` | 1,532 | 16,010 | One health level in three places; a check that raises is a FAIL. |
| Egress allow-list | `deploy/egress.py`, `network.sh` | 487 | 7,015 | Default drop from every container network. |
| Sealed object store | `tb_common/objstore.py` | 270 | 4,628 | Patient files sealed at rest (it replaced an AGPL object server, D-121). |

## 4. The pieces being written right now

These come first because a switch is cheapest before the code lands.

### 4.1 The embedder image and server (PR #341, #367; ENG-003, HW-002)

- **What exists outside.** Hugging Face Text Embeddings Inference (TEI): one server binary in a published image,
  with CPU and CUDA variants. Licence Apache-2.0 since April 2024, after a short period under a source-available
  licence [V: the maintainers' announcement of 2024-04-08, quoted by several listings; one old listing still says
  HFOIL, so read the repository's licence file]. Air-gapped use is documented: download the weights, mount them as
  a volume [V: the TEI quick tour]. It serves the family of multilingual encoders our pinned embedder belongs to
  [M]. Infinity is a second such server, MIT [M].
- **What it would replace.** The model mode of `embed_service/embedder.py` and the Python stack under it. PR #341
  adds `deploy/requirements-embed.lock` (949 lines of hashed pins, the torch stack among them), 60 lines of
  `tools/tiny_embedder.py` and about 550 lines of tests for the image.
- **Fit.** Offline: yes. One box: yes, one more container, or none if it takes the place of ours. Languages: the
  model decides, not the server. Pinned and scannable: an image by digest in `deploy/images.lock`, like vLLM.
- **What we would lose.** Nothing the server enforces. Three rules must stay in our client: PRODUCTION refuses the
  hash stand-in; the dimension check; the weights manifest of #367. The hash mode for CPU CI stays ours.
- **Not known.** Whether its CUDA image runs on the box's card generation; whether its vectors equal ours within
  the tolerance of `tools/vec_parity.py`; its throughput on CPU. None was run today.
- **Cost against the dates.** Plan v7 Q3 gives the embedder until 2026-12-04. #341 is written and waits for review.
  A spike is one session-day: start the published image against the mounted weights, run `tools/vec_parity.py` and
  `tools/bench_embed.py`.
- **Verdict: ADOPT NOW, as a spike before #341 is reviewed.** If parity holds, the embed image becomes a pinned
  third-party digest and the 949-line lock is not ours to patch. If it does not, #341 lands as written and nothing
  is lost but the day.

### 4.2 The Windows installer (PR #362, NEW-WIN-1) and the Windows cards

- **What exists outside.** No project installs Docker Engine and the NVIDIA Container Toolkit inside WSL2 from
  offline media and then a compose stack. Zarf is the known air-gap packager; licence Apache-2.0 [V: the Zarf FAQ].
  It is built for Kubernetes [V: its own articles describe Kubernetes delivery; the FAQ says some use it more
  widely]. Our box has no Kubernetes, and the plan freezes that form.
- **What helps beside it.** `wsl --import` and the Windows side's own tools; Pester for the tests (#362 uses it);
  the platform's protected store for NEW-WIN-8 (below).
- **Verdict: KEEP OURS.** 494 lines of PowerShell and 167 of shell are the right size for it.
- **NEW-WIN-8 (not written): ADOPT NOW the platform's mechanism.** The card adds "a key back end for the site keys
  held by Windows". Windows has one (DPAPI, with BitLocker under it). The card should call it, not add a cipher.
  For the recovery copy that OPS-001 found missing, wrap the KEK to two recipients with `age` (BSD-3-Clause [M]):
  the box's own key and a printed one. `tb_common/kek.py` keeps its Shamir and passphrase back ends.

### 4.3 The REDCap test instance (PR #352, NEW-EDC-0) and the conformance run (NEW-EDC-1)

- **What exists outside.** REDCap itself is not open source; plan v7 section 2.4 is right that the zip comes from a
  consortium partner. A community compose project that installs REDCap from a zip the user supplies exists [M: its
  licence and state were not checked today]. PyCap is the common Python client: MIT, version 2.7.0 on the package
  index [V: the PyCap page of the Python package index; a security listing still shows 2.6.0].
- **What it would replace.** `rc_bridge/client.py` is 226 lines of form posts with our error mapping. PyCap would
  replace little of it and would hide the mapping to the interface register. `rc_sim` (576 lines) is the piece to
  retire.
- **What we would lose with PyCap as the client.** The rule that the token is never in an error text, and the
  mapping of 403, 429 and 503 to our register. So it is not the client.
- **Verdict: KEEP OURS for the client and the instance; ADOPT NOW two changes to NEW-EDC-1.** First, do not spend
  the card's "simulator made as strict" half: record cassettes from the real instance and let CI replay them
  (`rc_bridge/cassette.py` exists). EDC-001 was the simulator accepting what REDCap refuses; a second simulator of
  REDCap's rules will drift again. Second, run R1 to R9 through PyCap as well, in the test instance only: where
  PyCap and our client differ, the fault is ours.

### 4.4 The CGRD connector (T-731)

- **What exists outside.** None. CGRD is one institution's research database. The reader is 43 lines today.
- **What helps beside it.** The OHDSI tools made for this step: WhiteRabbit scans a source and writes the report an
  ETL design starts from; Usagi helps a person map local codes [V: the OHDSI software tools page, for what they
  do]. Both are desktop Java programs under Apache-2.0 [M]. Usagi matches on English concept names [M], so Chinese
  drug and order names need our NHI code tables first. They run on the mapping person's machine against a synthetic
  or schema-only extract, never on patient rows outside the box.
- **Verdict: KEEP OURS; USE BESIDE** WhiteRabbit for the scan report of the first read, and Usagi for the local-code
  mapping that NEW-DIN-6 counts.

### 4.5 The night runner, publish(night), lake generations, the resumable job (PR #322, #314, #318, #320; T-689)

- **What exists outside, for jobs.** DBOS Transact: a library, not a server, that checkpoints workflow steps in
  PostgreSQL and resumes after a restart; MIT; version 3.1.0 of 2026-09-24 on a package mirror [V: the package
  index page and the DBOS blog; the newest version is from a mirror]. Its separate management component is under a
  proprietary licence [V: same search]; we would not use it. Procrastinate: a task queue on PostgreSQL with locks;
  MIT; version 2.14.1 seen [V: the Procrastinate page of the package index]. Temporal needs its own server
  cluster; Prefect and Dagster bring a server and a web console; Celery needs a broker [M]. Those four fail "one
  box, a research lead operates it".
- **What exists outside, for the lake.** DuckLake 1.0: tables as Parquet files with the catalogue in a SQL
  database; snapshots, time travel, schema evolution; PostgreSQL is a supported catalogue; MIT; released 2026-04-13
  [V: the DuckLake site's 1.0 post and FAQ]. We already run DuckDB and PostgreSQL. Apache Iceberg and Delta Lake
  need a catalogue service or a JVM for the full feature set; lakeFS and Project Nessie are servers [M].
- **What they would replace.** For jobs: the queue, claim, lease and resume code, about 2,300 of the 3,382 lines,
  and the 763 lines of `StepStore` and `Dispatcher` that ARCH-004 found unused. For the lake: the snapshot folders,
  `CURRENT`, the sidecars, retention (3 nightly, 36 month-ends) and the generation records of #318 and #320.
- **What we would lose.** For jobs: nothing by itself, but our rules sit across the queue: snapshot pinning
  (`orchestrator/jobs.py`), the audit of every state change, the fixed run date, the routing check on patient
  files. They would be rewritten as steps of a workflow. For the lake: the held night, the 20 % drop rule, the
  schema version check, the full-text index per snapshot, and above all erasure. Time travel keeps a deleted row
  readable until old snapshots are expired and their files removed. An opt-out must expire them. That design does
  not exist.
- **Cost against the dates.** T-689 landed this week. #314, #318, #320 and #322 are written (about 5,500 added
  lines with tests) and reviewed in waves 0 to 3. The night is the critical path to both go-lives.
- **Verdict: ADOPT AFTER GO-LIVE, both.** Two things now. Do not extend the home-made queue beyond the lease card
  of wave 1. And when wave 3 reaches "nightly deltas" (PERF-006), read DuckLake first: a delta night and a backup
  that copies only changed files (PERF-010) are what it stores by design.

### 4.6 The actor assertion (PR #317, T-715)

- **What exists outside.** The format is a solved problem: a signed token with an expiry and an audience (JWT), and
  libraries that parse and check it: Authlib, BSD-3-Clause, 1.6.9 and 1.7.1 seen [V: Authlib's licence page and
  package metadata]. A service mesh with workload identities is far too heavy for one box.
- **What it would replace.** Part of `tb_common/actor_v3.py` (232 lines): the encoding and the signature check.
  Not the rule: one minting place, one dependency on every changing route, the route table.
- **Verdict: KEEP OURS.** The pull request is written and the value is in the route table. After go-live, when
  `console/oidc.py` moves to Authlib, the assertion can use the same library's token code.

### 4.7 The scale gate (PR #298, T-687)

- **What exists outside.** Load tools (Locust, k6) drive HTTP; they do not build a 50,000-patient night [M].
  memray measures a Python process's memory and has a pytest plug-in that fails a test over a limit;
  Apache-2.0 [M].
- **Verdict: KEEP OURS; USE BESIDE** a memory limit per test on the ingest and rebuild tests, so the next PERF-001
  fails in the unit job and not in a nightly.

## 5. One section per mechanism (step 2)

### 5.1 LLM gateway: KEEP OURS

- Candidate: LiteLLM proxy. Its licence was not confirmed today [M: MIT with a separately licensed enterprise
  folder].
- Its 2026 record: a release pipeline compromise on 2026-10-21 that published a credential-stealing version; an
  earlier compromise in March 2026; a pre-authentication SQL injection disclosed in April 2026 [V: the project's
  own incident post of 2026-10-21; a Cloud Security Alliance research note of June 2026]. A box that takes updates
  from a signed offline bundle would have been shielded from the first two, but the component sits on the path of
  every patient prompt.
- What ours enforces that it does not: routing by data class with one boundary rule (`gateway/policy.py`); no
  answer from another alias unless the route says `fallback: any`, and the client raises on one
  (`gateway/core.py:475`, `tb_llm/client.py`); the prompt must be the registered template with the registered
  schema; the tripwire runs whatever the label says; every refusal is an audit event; the one-GPU swap.
- vLLM is already the OpenAI-compatible server. The gateway is 2,309 lines of policy, not of plumbing.

### 5.2 PHI detection: BENCHMARK ONLY now, a tokeniser inside ours (ADOPT NOW for NEW-LLM-3/4)

- Candidate: Microsoft Presidio. Its default configuration covers English only; other languages need NLP models
  configured and recognisers written per language [V: Presidio's languages page and FAQ]. Licence MIT [V: only by
  mirrors; read the repository]. No Taiwan or Japan identifier recogniser was found today. Philter is for English
  notes [M].
- What it would replace: the pattern engine of `guard/recognisers.py`, not the patterns. The check-digit rules for
  the Taiwan ID, the ARC and My Number are ours and stay.
- The open defects are LLM-003 (12 of 20 ordinary zh-TW criteria refused as names) and LLM-004 (20 of 61
  identifier forms missed). The first is a regular expression guessing at word boundaries in text without spaces.
  A tokeniser with part-of-speech tags knows where a person's name is. Candidates: spaCy (MIT) with its Japanese
  and Chinese pipelines, GiNZA (MIT), SudachiPy (Apache-2.0) [M, all three].
- Loss if Presidio replaced ours: "any hit blocks" and "a wrong check digit is still redacted" are our policy; the
  trace store's redaction at write calls the same detector.
- First step: add Presidio with a Japanese and a Chinese model as a second scorer in `tools/phi_synth_eval.py`, on
  the sets of `eval/phi_synth`. Keep whichever wins per kind. No image change until it wins.

### 5.3 Evaluation and qualification: KEEP OURS; USE BESIDE Inspect for the frozen bake-offs

- Inspect: MIT, version 0.3.271 on a package mirror [V: package metadata; the maintainer's name differs between
  sources]. promptfoo: MIT, and an acquisition by a model vendor was announced on 2026-03-09 [V: several news
  pages]; it is a Node tool. DeepEval: Apache-2.0 [M].
- `tools/qualify.py` (1,220 lines) writes the record that lets a pair become `champion` on a profile. It checks
  pins, the licence step, the chat template hash and evidence files. No harness does that.
- The bake-off tools (2,551 lines, frozen to wave 11) are ordinary model comparison. When they thaw, write the
  tasks for Inspect and delete them.
- NEW-LLM-6 (the accuracy set per language and stratum, wave 3) must go through our gateway to count, with our
  headers and registered prompts. Keep it in our tools.

### 5.4 Tracing and registries: KEEP OURS

- Langfuse: MIT core with separately licensed enterprise folders [V: its comparison page; one source says
  Apache-2.0, so read the file]. Self-hosting it needs several services beside PostgreSQL [M]. Phoenix: its server
  is under the Elastic License 2.0, which is source-available, not open source [V: comparison pages].
- Ours is 267 lines: redaction at write through the same guard, an access log, a purpose on every read. A tracing
  server would hold patient-derived text unless the redaction stays in front of it, so it removes nothing.

### 5.5 Audit hash chain: KEEP OURS

- immudb: Apache-2.0 by the mirrors found today [V: mirrors and the acknowledgements file]; my memory says it
  changed licence, so read the file. Trillian and Rekor: Apache-2.0 [M]; each needs its own server and database.
- STD-002 (truncate the chain, rewrite the head, verify says PASS) was not a weakness of the chain. The signed
  heads existed and no timer made them. PR #340 fixes that. A log server would have needed the same timer.

### 5.6 Backup: ADOPT NOW for the incremental part

- restic: BSD-2-Clause; 0.19.1 of 2026-07-05 [V: restic's encyclopedia page and project profile]. BorgBackup:
  BSD-3-Clause; 1.4.5 seen [V: its licence file in a distribution's archive]. pgBackRest: 2.60.0 of 2026-10-18;
  the project was archived on 2026-04-27 and resumed on 2026-05-18 with sponsors [V: the pgBackRest site and news
  reports]; its licence was not confirmed today [M: MIT]. It is already in our database image at 2.60.0
  (`deploy/images.lock`). WAL-G: Apache-2.0 [M].
- What they would replace: nothing that exists. They replace what wave 3 is about to write: "backup: incremental,
  lake lock for the listing only, append-only files (PERF-010, PERF-011, ENG-011)". A deduplicating repository
  stores a changed file once, reads a file without holding our lock for the whole run, and does not fail because a
  file grew while it was read.
- What we would lose, and it matters: today the box holds only the public key, so a stolen box cannot read its own
  backups (`backup.py`, `backup-keygen`). restic and Borg encrypt with a secret the box must hold [M]. Two ways to
  keep the rule: an append-only repository on the target, or keep our sealed file for the small and sensitive part
  (the databases' dumps, the keys) and use the tool only for the lake's Parquet and DuckDB files. Our rules stay
  in the wrapper: one snapshot per database, the off-box rule, the age alert, the restore drill, and the re-apply
  of opt-outs registered after the backup.
- A risk to name: pgBackRest's 2026 funding gap. It is in the image and off by default; keep it off until the site
  asks for point-in-time restore.
- First step: a spike of one to two session-days before the wave-3 card starts: restic to a folder target, run
  `tools/backup_drill.py` over it at the dense synthetic profile, measure the second night's size and time.

### 5.7 Watchdog, health, metrics: KEEP OURS

- Docker does not restart a container whose health check fails; small restart helpers exist [M]. Ours is 394
  lines of standard library and audits each restart. Prometheus is already the metrics server.

### 5.8 Secrets and keys: KEEP OURS; the platform's store for NEW-WIN-8

- SOPS: MPL-2.0; `age`: BSD-3-Clause; Vault moved to a source-available licence in 2023 and has an open fork [M,
  all]. A secrets server fails "a research lead operates it".
- `tb_common/kek.py` wraps five keys under a KEK with three back ends. The defect (OPS-001) was a missing recovery
  copy, which is a matter of a second recipient, not of a product. See 4.2.

### 5.9 Sign-in: KEEP the accounts and TOTP; Authlib for the OIDC client AFTER GO-LIVE

- Authelia is already the provider in `deploy/docker-compose.identity.yml`. Keycloak and Authentik are heavier
  servers; Dex is a light one [M]. The hospital's own provider is the real one, so none is added.
- `console/oidc.py` (392 lines) checks the ID token by hand: signature, algorithms, nonce, audience. That is the
  class of code where libraries exist because hand-written checks go wrong. Authlib is BSD-3-Clause [V]. It is off
  unless the site turns it on, and tested; move it after go-live.
- `console/totp.py` is 118 lines over the standard library with the RFC's test vectors. pyotp (MIT [M]) would
  replace it line for line and add a dependency to scan. Keep.

### 5.10 Authorization: KEEP OURS

- Cedar: Apache-2.0; its Python binding is a third party's [V: the Cedar repository listing and the binding's
  listing]. Casbin, OPA and OpenFGA: Apache-2.0 [M]; OPA and OpenFGA are separate servers.
- Ours is one function over a 784-line matrix for seven roles, with a test that enumerates it. An engine would add
  a policy language for the research lead's vendor to learn and would not remove the matrix.

### 5.11 Message catalogues: gettext AFTER GO-LIVE, if translators join

- Babel with gettext files is BSD-licensed; Fluent is Apache-2.0 [M]. Neither language here has plural forms, so
  the gain is tooling for translators and no more merge conflicts in Python files (plan v7 names
  `console/i18n_audit.py` and `i18n_roles.py` as files where cards collide).
- The deep review found 2,841 keys in three languages with none missing. Do not touch it before go-live.

### 5.12 OMOP: KEEP the loader; OHDSI tools BESIDE the box

- DataQualityDashboard: Apache-2.0; 2.8.9 of 2026-05-18 on one mirror and 2.9.1 on another [V: its package pages].
  Achilles: Apache-2.0; needs R 4.0 or later and Java [V: the Achilles package page]. ATLAS with its web service is
  a Java application with its own database; CIRCE turns a cohort definition into SQL; Capr writes such definitions
  from R [M]. FhirToCdm: state not checked [M].
- `omop/dqd.py` (423 lines) is "a small subset" by its own docstring: required fields, keys, year of birth, events
  after birth and before death, start before end. The community's set is about two dozen check types applied
  across every table and field [M].
- Can they run on the box? R and Java are a second and third runtime to pin and scan. So: on the acceptance box and
  at mapping time, beside the product (USE BESIDE). After go-live, generate the dashboard's SQL once at build time
  and run it with our runner, if its SQL-only mode does what its documentation index suggests [M].
- CIRCE and ATLAS as a replacement for our SQL generator: no. They define cohort entry and exit on the CDM. Ours
  answers each criterion as true, false or unknown with the evidence row, on the lake's tables, and fails closed on
  a code family. As a third engine for T-711's differential they are a fair benchmark.

### 5.13 FHIR and CQL: already reused

- `fhir.resources`, the HL7 validator, the CQL translator and HAPI are in use. Plan v7 moves HAPI and the JVM off
  the box and keeps them in CI. `adapter/validate/jpcore.py` (450 lines) exists because the validator needs a JVM
  the box will not have; keep it small and keep the JVM validator as the CI oracle.

### 5.14 Ingest contracts and data quality: KEEP OURS

- Great Expectations and Soda Core: Apache-2.0; pandera: MIT [M, all]. `adapter/governance.py` (771 lines) holds
  the night on a missing contract and writes one gate record. A library would express column rules; it would not
  have written the range rule that DIN-001 lacked (a ROC date read as the year 1150).

### 5.15 Consent, pseudonyms, opt-out, erasure: KEEP OURS

- Mainzelliste: AGPL-3.0-or-later [V: a research-software registry and its maintainers' page]. gICS and gPAS: named
  as free tools in wide use [V: two journal papers]; licence AGPL-3.0 [M]. All three are Java services built for
  networks of sites. An AGPL service in the image is exactly what the licence gate flags. Our pseudonym is one
  keyed hash and a map (294 lines).
- Fides is the open-source framework closest to "erasure across stores": it keeps an inventory of where a
  subject's data lives and runs the deletion with an audit trail [V: its maker's guide]. Licence Apache-2.0 [M].
  It is a server for enterprise databases. It knows nothing of a DuckDB lake, vectors keyed by chunk hash,
  per-snapshot files or a restore that must re-apply later opt-outs. See section 6.3.

### 5.16 Synthetic patients: KEEP OURS

- Synthea: Apache-2.0; its default population is one US state; it exports FHIR, C-CDA and CSV [V: the Synthea
  wiki]. No Japanese or Chinese note generation was found. The repository already uses it for one cohort
  (`tools/synthea_ad_cohort.py`).

### 5.17 Document parsing: already reused

- Docling is the production parser. PaddleOCR and Tesseract (both Apache-2.0 [M]) are the OCR candidates if a site
  mails scanned protocols; neither is needed for go-live.

### 5.18 Supply chain, licences, secret scan: KEEP OURS

- The tools already wrap CycloneDX SBOMs, pip-audit and Trivy with an offline database. Trivy itself was
  compromised on 2026-03-19: a malicious 0.69.4 and re-pointed action tags [V: its maker's incident posts]. Our pin
  is 0.76.2 (`tools/supply_chain/scanners.py`). The lesson is the one the repository already follows: pin by
  digest.
- gitleaks: MIT; detect-secrets: Apache-2.0; trufflehog: AGPL-3.0 [V: several comparison pages]. detect-secrets is
  already pinned. trufflehog's licence is fine for a CI tool and still worth naming.
- ORT and ScanCode [M] are heavier ways to do what `supply_chain/licences.py` (462 lines) does on our SBOMs.

### 5.19 Doc lint and decision records: KEEP OURS

- adr-tools and log4brains keep decision files [M]. Our rule (one number, one text; numbers given by the
  integrator) is 228 lines. A link checker could take the link half of `doclint.py`; the gain is small.

### 5.20 CI: branch protection first; pytest-split BESIDE; no merge queue for us

- GitHub's merge queue runs on private repositories only for organizations on the Enterprise Cloud plan [V: the
  general-availability changelog of 2023-07-12; a 2024 post adds Enterprise Server]. This repository is private
  and owned by a user account (`gh api`, today), and `master` is unprotected (`protected=false`, today). So the
  merge queue is not available; the hand-run merge train (#366) is its substitute. Mergify is a hosted service with
  a paid tier for private repositories [M]; bors is no longer maintained [M].
- pytest-xdist is in use. pytest-split (MIT [M]) splits by recorded durations. `tools/test_shard.py` splits by a
  hash of the path: six shards give about 2.5 times, by the workflow's own comment.

### 5.21 Installer, update bundle: KEEP OURS; a standard AFTER GO-LIVE

- `tools/verify_update.py` and `sign_bundle.py` implement a signed manifest with a release sequence, a lowest
  installed version, an expiry and key rotation. That is the design of The Update Framework [M]. cosign signs
  images and files with a key, offline [M]. Changing the trust root of updates before the first box ships is risk
  with no gain for the site.

### 5.22 Mail gateway, feature flags, migrations, object store: KEEP OURS

- Each is small (1,513, 424, 612 and 270 lines) and each candidate is a server or a framework larger than what it
  replaces. Alembic would fit the migrations, since SQLAlchemy is a dependency [M]; it would not remove the
  "migration hashes" collisions the plan names.

## 6. Group 3, 真的沒人做過 (nobody has really done it): ours to keep, and how the claim was checked

Searches were made today in English, Japanese and Traditional Chinese. "Nobody" means: no open-source project and
no published system found that does the whole thing. It does not mean no vendor has it in private.

### 6.1 Criteria compiled to SQL a model never writes, checked against a second engine

- **What is new.** A model extracts a schema-bound IR. SQL and CQL come from templates. The two are compared on
  fixtures (98 % or better) before a person approves. A code outside a known family is "unknown", not "no".
- **Closest prior work and where it stops.** Criteria2Query 3.0 parses criteria with a cloud model and has the
  model write the SQL for OMOP [V: the OHDSI brief report]; its licence for 3.0 was not found. A two-step
  retrieval text-to-SQL system reports an F1 of 0.75 for cohort identification on OMOP data [V: the arXiv paper
  2502.21107]. A 2025 study of criteria to OMOP SQL reports hallucination rates of 21 to 50 % and recommends
  hybrids with rules [V: JMIR Medical Informatics 2025, e71252]. All three let the model write the query. None was
  found that compiles to CQL as well, or that gates on agreement between two engines.

### 6.2 The cascade and the two-model rule

- **What is new.** Structured filters first, then lexicon and semantic ranking, then a judge that must quote the
  note, a check of the quote against the record, and a second model. Any disagreement, missing quote or sign that
  the two answers came from one model becomes "unknown", never an exclusion (`tb_common/pair.py`). A canary in
  three languages gates the night.
- **Closest prior work and where it stops.** TrialGPT matches a patient summary to trials criterion by criterion
  with a cloud model and reports a 42.6 % cut in screening time [V: the paper on PubMed Central]. It matches one
  patient to many trials; we screen a hospital for one trial. A pre-screening pipeline for one disease area runs
  in a local, air-gapped setting with a proponent, an opponent and a judge that debate to a verdict [V: a paper
  summary page; the paper itself was not read]. That is the nearest design: several models, on premises. It
  resolves a disagreement to an answer; ours refuses to. In Japan, hospital and vendor trials of candidate
  extraction from the record with a language model were announced in 2025 and 2026 [V: a vendor press release of
  2025-03 and trade press of 2026-06]; they are proofs of concept by vendors, with no code. No Traditional Chinese
  source describing an on-premises system was found. A physician-in-the-loop study found a model alone wrongly
  ruled out half of the eligible trials [V: arXiv 2304.07396], which is the case the pair rule is for.

### 6.3 Opt-out and erasure as an obligation of every store

- **What is new.** Every table, lake entry, object prefix and outside store has exactly one declared obligation
  (`tb_common/erasure.py`); an enumerating test fails when a new store has none; a restore re-applies opt-outs
  registered after the backup; the register takes a chart number at the desk and stores only the pseudonym.
- **Closest prior work and where it stops.** Fides (5.15) orchestrates erasure across enterprise databases.
  General guidance describes erasure as a resumable multi-step transaction and warns that time travel keeps
  deleted rows [V: two engineering guides]. Nothing found covers a research lake with per-night snapshots, a
  vector store and encrypted backups on one machine, or ties erasure to a research opt-out register.

### 6.4 The rest that is ours

- The decision function (one place where a verdict becomes a status, T-709) and the 29 reason codes in three
  languages.
- The trial lifecycle and the console: marks, consent, visits, AEs, forms, signing, the seven roles.
- The ingest of SS-MIX2 and of Taiwan's feeds with JP Core and TW Core output, era and ROC dates, local units.
- The qualification record: a model pair is allowed on a hardware profile only by a record measured on it.
- The box form: one Windows workstation that staff also use, offline, restarted without a person.

Effort belongs here. Every hour on a queue, a backup format or an embedding server is an hour not spent on these.

## 7. Groups 1 and 2 in one view

**Group 1, 可以直接用現成方案取代 (can be replaced outright).**

| Piece | By | Verdict | Lines |
| --- | --- | --- | --- |
| Embedding server, model mode | Text Embeddings Inference | ADOPT NOW (spike) | about 100, and a 949-line lock |
| Incremental backup of lake files | restic | ADOPT NOW (spike) | not yet written |
| REDCap simulator | cassettes from the real instance | ADOPT NOW | 576 |
| Unused step engine and dispatcher | nothing: delete (plan v7 section 3.1) | already planned | up to 763 |
| Bake-off tools | Inspect | USE BESIDE, at thaw | 2,551 |
| Test shard splitter | pytest-split | USE BESIDE | 176 |
| OIDC client | Authlib | ADOPT AFTER GO-LIVE | 392 |
| Upload decoder | charset-normalizer | ADOPT NOW | not yet written |

**Group 2, 部分有人做過 (partly done by others).**

| Piece | The base others built | What stays ours on top | Verdict |
| --- | --- | --- | --- |
| Job queue and resume | DBOS Transact, Procrastinate | snapshot pinning, audit, fixed run date | ADOPT AFTER GO-LIVE |
| Lake generations | DuckLake | held nights, drop rule, erasure | ADOPT AFTER GO-LIVE |
| PHI tripwire | tokenisers; Presidio's framework | TW and JP recognisers, "any hit blocks" | ADOPT NOW (tokeniser), BENCHMARK (Presidio) |
| OMOP checks and mapping | OHDSI DQD, Achilles, WhiteRabbit, Usagi | the loader, provenance, tombstones | USE BESIDE |
| Keys | DPAPI, `age`, systemd-creds | the KEK inventory and rotation | ADOPT NOW for NEW-WIN-8 |
| Update bundle | The Update Framework, cosign | back up first, roll back | ADOPT AFTER GO-LIVE |
| Message catalogues | gettext, Babel | the texts | ADOPT AFTER GO-LIVE |
| Gateway | general LLM proxies | every rule in it | KEEP OURS |
| Audit chain | log servers | the writer role, signed heads | KEEP OURS |
| Authorization | policy engines | the matrix | KEEP OURS |
| Erasure | Fides | the obligations table | KEEP OURS |
| Trial matching | TrialGPT, Criteria2Query, Leaf | (group 3) | BENCHMARK ONLY |
| Synthetic hospital | Synthea | notes in ja and zh-TW, ground truth | KEEP OURS |
| Supply chain | Trivy, pip-audit, CycloneDX (in use) | the allow-list rules | KEEP OURS |

## 8. How to go faster, and better

Ranked by gain against cost. Session-days use plan v7's sizes (S up to 1, M 2 to 4, L 5 to 10). Every saving is
this review's estimate, not a measurement.

| # | Action | Kind | Saves | Costs | When | First step |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Protect `master`: required checks, no merge before they end | (d) process, (e) quality | Removes ENG-001 (a pull request was merged 37 minutes before its unit job failed). No lines. | The owner's ten minutes; a paid personal plan may be needed for a private repository [M] | Wave 0, today | The owner sets the rule with `unit` and the fast jobs required (plan v7 wave 0 already asks). |
| 2 | A runner we own for the unit shards | (d) process | Ends the stops when the spending limit is reached (no job started for hours on 2026-11-12). Each stop idles up to seven sessions. | One Linux machine; one session-day; check how self-hosted minutes are billed in 2026 [M] | Wave 0 | Register one self-hosted runner for the `unit-shard` job only; keep hosted runners for image builds. |
| 3 | Embedder: spike the published embedding server before #341 is reviewed | (a) | A 949-line lock and a torch image we would patch for years; 2 to 3 session-days of review and later upkeep | 1 session-day; unknowns in 4.1 | Before 2026-12-04 | Run the image on mounted weights; `tools/vec_parity.py`; decide. |
| 4 | Backup: restic for the lake files, before the wave-3 card | (a), (c) | The incremental design and its tests (M, 2 to 4 days), the lock change (M), the append-only fix (S); PERF-010, PERF-011, ENG-011 | 1 to 2 session-days of spike; the public-key rule needs the split of 5.6 | Spike in wave 1 or 2; build in wave 3 | restic to a folder; `tools/backup_drill.py` at the dense profile; second-night size. |
| 5 | NEW-EDC-1: cassettes, not a stricter simulator; PyCap as a second client | (a), (b) | About half of an M card (1 to 2 days); `rc_sim` (576 lines) retired after go-live; removes the cause of EDC-001 | Half a day to add PyCap to the test instance's image only | Wave 2 | Record R1 to R9 on the instance of #352 with `rc_bridge/cassette.py`. |
| 6 | NEW-WIN-8: the platform's store and a second recipient, no new cipher | (a) | Part of an M card; removes OPS-001 | None beyond the card | Wave 2 | Test DPAPI under the boot task's sign-in type, as the card already says. |
| 7 | NEW-LLM-3/4: measure a tokeniser and Presidio before writing patterns | (a), (e) | Rework of an M card; LLM-003 and part of LLM-004 | 1 session-day to add the scorers; the tokeniser's models must be pinned and scanned | Wave 2, first day of the card | Add both as scorers in `tools/phi_synth_eval.py`. |
| 8 | Stop growing five home-made pieces | (b) | See below; about 6 to 10 session-days over waves 3 to 6 | A decision | Now | The integrator adds the list to plan v7 section 3.2. |
| 9 | Shrink the plan where a card only maintains home-made infrastructure | (c) | See below; about 8 to 15 session-days after go-live | A re-read at wave 6 | At NEW-PLAN-5, end of wave 0 | Mark the cards in section 3.3. |
| 10 | Fragment files for the tables every lane appends to | (d) | Plan v7: six pull requests lost a CI round in one day to collisions in these files | 1 session-day | Wave 0 or 1 | One small file per card under a folder; a tool joins them at lint. Start with `docs/decisions/REGISTRY.md` and the `KNOWN` table. |
| 11 | Shorter sessions with a written hand-off | (d) | A long session costs about US$75 to 95, almost all of it re-reading its own context; seven run in parallel | Discipline | Now | One card per session; end the session when its pull request opens; fixes after review start a new session from a hand-off note of under 100 lines. |
| 12 | Standard tools on our own outputs | (e) | The class of OPS-002 and PERF-001 | 1 session-day | Wave 1 | detect-secrets over a generated support bundle in a unit test; a memory limit on the ingest tests. |
| 13 | Shards by duration | (d) | A few minutes per run; more even shards | Half a day | After action 2 | pytest-split with a recorded durations file, or weights in `tools/test_shard.py`. |

### 8.1 Action 8: what to stop building or freeze, because a tool beside the product is enough for the first box

- `omop/dqd.py`: no new checks. Run DataQualityDashboard and Achilles on the acceptance box for the first real
  night.
- `rc_sim`: no new REDCap rules (action 5).
- The bake-off tools and `tools/mlbench.py`: already frozen; do not thaw them, write for Inspect instead.
- The trace store and the model registry: no new features before go-live. Plan v7 already folds them under the
  gateway.
- `tools/trialbox/platform.py` and `platform_day2.py` (2,671 lines for the Kubernetes form): frozen by plan v7.
  They are still read, linted and tested on every run. Move them out of the per-pull-request jobs, as section 3.2
  says for the form itself.
- Mapping by hand: WhiteRabbit and Usagi beside T-731, in place of a mapping editor of our own.

### 8.2 Action 9: where the plan itself can shrink

| Card | What it maintains | Shrink |
| --- | --- | --- |
| "A lease so two workers cannot resume one job" (wave 1, S) | the home-made queue | Keep: one day. It is the last queue card before go-live. |
| "Delete `StepStore`/`Dispatcher`" (wave 1, S) | dead code, up to 763 lines | Keep, do first: it removes lines every session reads. |
| T-697, the audit writer at a million events a day (wave 6) | the home-made chain's file handling | Measure first on the reference box. If the box makes a tenth of that, drop the card. |
| T-698, the gateway's queue and read limits (wave 6) | the home-made slots | Keep: the limits come from the serving record, which is ours. |
| T-702, the OMOP load staged with COPY (wave 4, L) | the home-made loader | Keep: no tool loads our feed. |
| T-703, PostgreSQL sized from the host (wave 4) | tuning arithmetic | Use the published sizing rules the community tools apply [M]; the card becomes S. |
| "Nightly deltas" (wave 3, M) and the backup cards (wave 3, M, M, S) | the home-made lake and backup | Actions 4 and 4.5: read DuckLake before the delta design; restic for the backup. |
| NEW-STD-3, the traceability table regenerated from tests (wave 7) | a generated document | Keep small: a marker report of pytest, not a tool. |
| T-747 and the merge trains | the home-made substitute for a merge queue | Keep: the merge queue is not available to this repository (5.20). Script the train. |
| T-718, roles per schema (wave 6) | PostgreSQL's own roles | Keep: it is configuration, not infrastructure. |

### 8.3 Process (d)

- **Review.** Keep the adversarial review. Plan v7 records seven reviews and seven defect finds on 2026-11-12. It
  is the cheapest quality step in the project.
- **CI.** The private-repository runner queue and the spending limit stop every session at once. Actions 1, 2 and
  13. The draft-tier split (#342) is right; land it early.
- **Merge trains.** They are the right substitute. A train of twenty cards (#366) is large: when it fails, twenty
  cards wait. Trains of five to eight fail smaller.
- **Session cost.** The cost is context, not typing. Three habits cut it: one card per session; never paste a whole
  CI log into the session (fetch the failing test's lines); keep the files every session must read short, which
  is one more reason for actions 8 and 10 and for deleting dead code first.

### 8.4 Quality (e): where a standard tool would have caught a defect found this week

| Defect | What happened | The standard tool |
| --- | --- | --- |
| ARCH-001, ARCH-004 | A restart re-ran every interrupted job from zero; a durable step engine had been written and nothing called it | A durable job library has attempts, leases and recovery from its first use (4.5). |
| PERF-010, PERF-011, ENG-011 | The backup copies everything every night (100 to 430 GB at real density), holds the lake's lock while it reads, and fails when a file changes under it | A deduplicating backup tool (5.6). |
| OPS-002 | The support bundle kept `SMTP_PASS` and the `TB_DB_PW_*` values; the redaction was a word list of our own | A secret scanner run on the bundle in a test (detect-secrets is already pinned) [M: its keyword list was not checked against these names]. |
| ENG-001 | A pull request was merged before its unit job failed | Branch protection with required checks: the platform's own feature. |
| UX-004 | A Shift_JIS or Big5 file is decoded as UTF-8 with no message | A charset detector, then our refusal. |
| EDC-001 | The simulator accepted what REDCap refuses | The real product, recorded (4.3). |
| DIN-001 | A ROC date was read as the year 1150 and the night passed | Partly: the community's plausibility checks on every date field would likely have flagged it after the load [M]; our subset checks the year of birth only. |

## 9. Not checked

- No candidate was installed or run. Every "fit" above is from documentation and search results.
- Licence files were not opened: the web-fetch tool was not available to this review. Every licence marked [V] is
  from a search result's summary of a page; every one marked [M] is from memory. Both need the file read before a
  decision.
- Not confirmed today: LiteLLM's licence; pgBackRest's licence; immudb's current licence (sources and memory
  disagree); the licences of gICS, gPAS, WhiteRabbit, Usagi, CIRCE, Capr, Trillian, Rekor, Casbin, OPA, OpenFGA,
  pyotp, Keycloak, Dex, SOPS, `age`, Great Expectations, Soda Core, pandera, PaddleOCR, Tesseract, Docling, ORT,
  ScanCode, pytest-split, memray, charset-normalizer, spaCy, GiNZA, SudachiPy, Infinity, DeepEval, Fides, WAL-G,
  python-tuf, cosign, Alembic, towncrier, adr-tools, log4brains; TrialGPT's and Criteria2Query 3.0's licences;
  Leaf's licence and state; the community REDCap compose project.
- Not confirmed today: whether the embedding server's CUDA image supports the box's card; vector parity;
  DuckLake's behaviour with full-text indexes and with physical deletion; restic on a hospital share mounted in
  WSL2; whether Presidio ships any Taiwan or Japan recogniser; how GitHub bills self-hosted runner minutes in
  2026; which personal plan branch protection needs on a private repository.
- Prior work was searched, not surveyed. Papers are cited from search summaries; none was read in full. A vendor
  may have built any of group 3 in private.
- Line counts are of `master` at `4ed01da3`. The open pull requests add about 57 session-days of code not counted
  here (plan v7 section 2.1).
- Not looked at for reuse: the reports (PDF and workbooks), the public site build, the demo tools, the phone app,
  the opportunity feed, `services/channels`.
