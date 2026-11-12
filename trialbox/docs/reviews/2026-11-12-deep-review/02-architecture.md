# TB-DR2-02 Architecture and best practice

| | |
| --- | --- |
| Document id | TB-DR2-02 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`, same tree as master) |
| Area | 2. Architecture and best practice. Finding prefix `ARCH` |
| Read | `services/*` (26 packages), `libs/*`, `deploy/docker-compose*.yml`, `deploy/platform`, `deploy/systemd`, `deploy/docker/db-init/30-service-roles.sh`, `docs/ARCHITECTURE.md`, `docs/reviews/2026-11-12-architecture/{decision,lifecycle,trust}.md`, `docs/decisions/REGISTRY.md`, plan v6.1 addendum, scale review of 2026-11-11, G1 bug list |
| Run (all synthetic, on this machine) | (1) an import graph of every service by `ast` (`ARCH/imports.py`); (2) the console's module graph (`ARCH/console_graph.py`); (3) **E1** restart recovery of the orchestrator's job queue on a throwaway PostgreSQL (`ARCH/exp1.py`); (4) **E2** the ingest follow over real HTTP with the real `adapter.app` and `AdapterHttp` on `127.0.0.1:18050`, ingest body replaced by a sleep (`ARCH/exp2.py`, `ARCH/adapter_srv.py`); (5) **E3** two threads on one `tb_common.db.Database`; (6) audit chain append rate and tail-truncation check (`ARCH/audit_bench.py`, `tools/audit_verify.py`); (7) the gateway's routing policy for the roles `judge` and `second_opinion`; (8) the erasure registry counted; (9) two throwaway tests on the role cluster of `test_db_roles.py`: which role can open `ProfileStore` and `NotMatchedStore`; (10) 63 targeted tests: `test_lake_rebuild_lock.py`, `test_polled_jobs.py`, `test_snapshot_holds.py`, `test_erasure_registry.py`, `test_compose_secret_reach.py` (all pass, 41.7 s) |
| Not run | Docker, the compose stack, a GPU, HAPI, a real ingest, the Kubernetes form. Scripts are in the session scratchpad under `ARCH/`, not in the repository |

Paths are relative to `trialbox/`. "Run" in an Evidence cell means the result came from one of the runs above;
"read" means code reading only.

## 1. Reading in ten lines

1. The box is **12 application containers** (17 with the model servers, the guard, Caddy and Authelia) on **one
   PostgreSQL** with 27 schemas and 197 tables, one DuckDB lake on a shared volume, one object folder shared by five
   containers. Sixteen of the 26 `services/*` packages are libraries, not processes.
2. The process boundaries are **not data boundaries**. The console's and the orchestrator's database roles co-own 17
   schemas; the console imports the orchestrator's stores directly (`datacore`, `omop`, `patient_profile`,
   `sitesetup`, `orchestrator.candidates`); the orchestrator imports `adapter.pidmap`, `mail_gateway.store` and
   `lake.store`. The box pays for a distributed system (timeouts, tokens, polled jobs, partial failure) and gets
   little isolation back, except in four places where it is real: doc-parser, mail gateway, gateway, audit writer.
3. **"Is work running?" is answered in eight places** (a queue flag in `orch.jobs`, the adapter's process memory, a
   JSON file per snapshot on the lake volume, `publishing.json` on the orchestrator volume, the mail outbox, the ops
   folder, the watchdog's state file, an end-of-run `dataops.batch` row), and time is kept by **ten timers in three
   technologies** (three APScheduler instances in two processes, cron, four systemd timers, two poll loops).
4. **Run:** two features cannot work on a box installed with the per-service database roles: the console's role
   cannot open the twin store, and schema `tuned` (the PI's weekly not-matched sample) is on no role's list, so the
   orchestrator cannot open it once the console has made it. Tests connect as the admin role and pass.
5. A crash is not survived cleanly. **Run:** a job interrupted by a restart is re-run from zero on every start, with
   no count (six boots, six runs). **Run:** an orchestrator restart during the night's ingest fails the INGEST job
   in 0.2 s with "an ingest is already running" while the adapter goes on unobserved; an adapter restart loses the
   night's state altogether (`{"state": "none"}`).
6. T-690 (polled jobs) merged today with its own state, although the addendum says it "uses T-723's state, not its
   own". T-723 to T-726 (the night as one resumable object, one runner) are the cards that matter most for this
   area and none is built.
7. A durable step engine with leases, attempts and idempotency keys exists (`orchestrator/db_pg.py` `StepStore`,
   `outbox.py` `Dispatcher`, about 760 lines, a kill-loop test) and **no production code calls it**;
   `docs/ARCHITECTURE.md` §9 says delivery goes through it.
8. The topology that is tested is not the one that is deployed: `LakeLocal` (in process) is used by 76 test files,
   `LakeHttp` by 10, `AdapterHttp` by 4, `CompilerHttp` by 2. The G1 failures were in the HTTP layer.
9. Sound, not to be redone: the gateway as the only model path, the audit journal with one writer and a head
   anchor (tail truncation is caught, run), the lake's single lock (T-722), checksummed migrations, the per-route
   caller table (T-713), secrets out of the shared environment (T-212d). Configuration is large (366 declared
   `TB_*` settings, 58 of them limits) and has one dead file (`site_params.yaml`).
10. **No rewrite is justified.** The evidence supports: one job runner and one state store (PostgreSQL) for the
    night, three small process merges, HAPI off the nightly path, and deleting five unused or duplicate parts. That
    fits before 2027-04-28 if T-723/T-726 and T-689 start now.

## 2. The architecture as the code has it

### 2.1 Processes and libraries

| Process (compose service) | Code | Memory cap | Database role | Volumes it writes | Why it is a process |
| --- | --- | --- | --- | --- | --- |
| `db` | PostgreSQL 16 | 4g | — | `db-pg` | the one database (`hapi`, `trialbox_wf`) |
| `fhir-store` | HAPI JPA 8.12 | 5g | `hapi` | — | compile-time CQL gate, TWPAS pre-check |
| `console` | `services/console` | 2g | `tb_console` (22 schemas) | `console-data`, `objects-data`, ops folder | the user-facing surface |
| `orchestrator` | `services/orchestrator` + `datacore`, `edc`, `sitesetup`, `matching`, `deliverables`, `rc_bridge`, `patient_profile` in process | 4g | `tb_orchestrator` (21 schemas) | `orch-data`, `objects-data`, secrets | jobs, scheduler, every domain API |
| `adapter` | `services/adapter` (+ `omop` in process) | 6g | `tb_adapter` (9) | `lake-data`, secrets | ingest, JVM validator |
| `lake` (2 workers) | `services/lake` (+ `vec`, `omop`) | 8g | `tb_lake` (5) | `lake-data` | DuckDB queries, rebuild |
| `embed-service` | `services/embed_service` | 4g | none | — | embeddings; only caller is the lake |
| `criteria-compiler` | `services/criteria_compiler` | 3g | `tb_criteria_compiler` (6) | `rulesets-data`, `objects-data` | the only writer of rulesets; egress to ClinicalTrials.gov |
| `doc-parser` | `services/doc_parser` | 2g | none | `objects-data` | parses outside files; no database (real isolation) |
| `mail-gateway` | `services/mail_gateway` | 1g | `tb_mail_gateway` (2) | `mail-data`, `objects-data` | parses outside mail; egress (real isolation) |
| `gateway` | `services/gateway` + `registry`, `guard`, `tracestore` in process | 2g | `tb_gateway` (2) | `traces-data` | the model perimeter (real isolation) |
| `audit-writer` | `tb_common.audit_writer` | 256m | `tb_audit_writer` (journal, read) | `audit-data` | the one writer of the chain (real isolation) |
| `llm-service`, `llm-verifier`, `model-guard` | vLLM 0.32, `services/model_guard` | 48g each (host RAM), 512m | — | — | the models and their key check |

Libraries only (no process): `channels`, `datacore`, `deliverables`, `edc`, `guard`, `matching`, `omop`,
`opportunity_hub`, `patient_profile`, `rc_bridge`, `rc_sim` (test), `registry`, `sitesetup`, `tracestore`, `vec`,
`llm_stub` (test). The caps of the non-model containers add up to 41.75 GB; with both model servers' host caps the
total is 137.75 GB on a box described as 128 GB (caps, not reservations).

### 2.2 The call graph

HTTP (from `tb_common/service_auth.py:87-96` `CALLERS`, the clients in `orchestrator/clients.py`,
`console/backend.py:253-256`, `mail_gateway/app.py:46`):

```
browser ──► console ──► orchestrator ──► lake ──► embed-service
               │             ├──► adapter ──► lake, fhir-store
               │             ├──► criteria-compiler ──► lake, fhir-store, gateway
               │             ├──► doc-parser ──► gateway
               │             ├──► mail-gateway ──► (SMTP/IMAP)        mail-gateway ──► orchestrator (jobs)
               │             ├──► gateway ──► model-guard ──► vLLM (judge, verifier)
               │             └──► fhir-store
               ├──► adapter (terminology load, run state), mail-gateway, gateway (front desk)
               └──► every service /healthz
every Python service ──► db (own role)        every service ──► audit.append() ──► audit-writer ──► chain files
```

In-process imports that cross a process boundary (run, `ARCH/imports.py`; a selection with file:line):

| Importer (process) | Imports | Where | What it means |
| --- | --- | --- | --- |
| console | `datacore.dataops.DataOps` | `console/dataops_page.py:80` | the console opens the orchestrator's `dataops` store itself |
| console | `sitesetup.store.SetupStore` | `console/instruments_page.py:33` | the same for `sitesetup` |
| console | `patient_profile.twin.ProfileStore` | `console/twin_api.py:38` | the same for `profile` |
| console | `omop.conflicts`, `omop.schema` | `console/conflicts_page.py:46-98` | the console writes conflict decisions into `omop` |
| console | `orchestrator.candidates.counts` | `console/app.py:1846`, `registry_view.py:5` | reads the `orch` schema directly |
| console | `datacore.lifecycle`, `forms`, `branching`, `sponsor`, `export` | 11 files, 18 imports | domain rules duplicated across the HTTP boundary by import |
| console | `tools.cascade_e2e`, `tools.data_scan`, `tools.trialbox.ops`, `tools.pin_provider` | `console/cascade.py:67`, `feedback.py:139`, `demo_guard.py:293`, `ops_pages.py:64`, `cli.py:102` | product code depends on the developer tool tree |
| orchestrator | `adapter.pidmap.PidMap` | `scenarios/screen.py:381`, `twpas.py:55`, `candidates.py:75` | the pid map is read in two processes |
| orchestrator | `mail_gateway.store.MailDB` | `scenarios/retention.py:43` | retention deletes the mail gateway's rows itself |
| orchestrator | `lake.store` (`check_snapshot_age`) | `jobs.py:93` | lake rules run in the orchestrator |
| orchestrator | `embed_service.embedder.HashEmbedder` | `scenarios/screen_cascade.py:366` | a test embedder inside production SCREEN (known, PR #275) |
| orchestrator | `criteria_compiler.*` | 10 files, 17 imports | the compiler's SQL overlay, semantics and review code run in the orchestrator; only compile/diff/approve go over HTTP |
| adapter | `lake.store` (`lake_lock`, `held_snapshots`, `building`), `lake.flatten` | `pipeline.py:730`, `:1076` | two processes write one directory under one `flock` |
| sitesetup (in orchestrator) | `orchestrator.scenarios.evaluate`, `feas_compute` | `sitesetup/readiness.py:226`, `:272` | library imports its host (cycle) |
| matching (in orchestrator) | `orchestrator.recall.ledger`, `orchestrator.scenarios.terms` | `matching/cascade/certificate.py:36`, `engine.py:254` | library imports its host (cycle) |
| deliverables | `orchestrator.reports.common`, `feas_compute._months_shown` | `deliverables/render.py:48`, `pack.py:257` | a private function imported across packages |

Database co-ownership (`deploy/docker/db-init/30-service-roles.sh:36-48`; "owns" is literal, the role is a member of
the group that owns the schema): `tb_console` 22 schemas, `tb_orchestrator` 21; **17 schemas are owned by both**
(`app, datacore, dataops, derived, library, mpi, omop, optout, orch, pidmap, recall, refdata, site, sitesetup, study,
terminology, wf`). `omop` is owned by five roles, `app` by all seven.

### 2.3 Data stores and who writes them

| Store | Where | Writers | Schema versioning | Completeness mark |
| --- | --- | --- | --- | --- |
| `trialbox_wf`: 27 schemas, 197 tables (run: counted from `tb_common.erasure.entries()`) | PostgreSQL | every Python service, each store class through its own single connection | per schema `_schema_version`, checksummed, append-only (`tb_common/db.py:386`); applied **at service start by whichever service constructs the store first** | transaction |
| `audit.journal` | PostgreSQL | every service through `audit.append()` (SECURITY DEFINER) | role script | append-only by trigger; never pruned |
| `hapi` | PostgreSQL (HAPI JPA) | adapter `sync_snapshot` every night | HAPI's own | none (`lake/fhir_ledger`) |
| Lake snapshots `lake/db/<date>.duckdb`, Parquet, `embed_cache.duckdb` | `lake-data` volume | lake service; adapter CLI (`TB_ADAPTER_LAKE=local`) | `lake_meta` version in each file | `.building` → rename, `.sha256` |
| NDJSON nights, `passed.json`, `held.json`, `tombstones.json`, `CURRENT`, `FEED`, `site_key.json`, `holds/*.json`, `locks/*.rebuild.json`, `fhir_ledger`, `site/` | `lake-data` volume | adapter and lake | none | marker files |
| Objects (`outputs/`, `attachments/`, `ctgov/`) | `objects-data` volume, mounted read-write by five containers | orchestrator, console, mail gateway, compiler, doc-parser | none | job state |
| Audit chain `YYYY-MM-DD.jsonl`, `HEAD.json`, signed heads off-box | `audit-data` volume | audit-writer only (D-394) | n/a | hash chain, head anchor |
| Rulesets working copy | `rulesets-data` volume | criteria-compiler only | manifest per ruleset | approval |
| `publishing.json`, job data | `orch-data` volume | orchestrator | none | file |
| Traces | `traces-data` + schema `trace` | gateway | migration | — |
| Keys | `tb-secrets` volume, `deploy/secrets` | host tools; adapter and orchestrator mount it | — | — |
| Pins and routes | `models/registry.yaml`, `registry.site.yaml`, `routing.yaml`, `route_callers.yaml` | host tools | `version:` field | — |

No transaction spans two stores. The night writes, in this order and in one function
(`adapter/pipeline.py:581-857`): pid map (PostgreSQL) → NDJSON → the gate → OMOP (PostgreSQL) → HAPI → lake DuckDB
and `CURRENT` → `passed.json` → `dataops.batch` row and audit event at the end. The order and its failure cases are
the lifecycle note's F-2, F-3, F-4, F-10, F-12; all are still in the tree at `514ae9b` (§3.2).

### 2.4 The job system

| Mechanism | State kept in | Survives a restart of its process? | Evidence |
| --- | --- | --- | --- |
| Orchestrator job queue, 4 worker threads | `orch.jobs` (`queued` flag; no lease, no owner, no attempt count) | re-run from zero, every time (run E1) | `orchestrator/db.py:237-265`, `core.py:595-601` |
| Night's ingest on the adapter | `_runs` dict in process memory | no: the run is forgotten (run E2-B) | `adapter/app.py:38-41`, `:101-107` |
| Lake rebuild | `lake/locks/<snapshot>.rebuild.json` + `flock` | reported `interrupted` by any worker (good) | `lake/store.py:166-217`, `:762-772` |
| Site publish | `<orch-data>/main/publishing.json` | followed again | `sitesetup/service.py:396-424` |
| Mail outbox | schema `mail` (keys, attempts, back-off 60 s to 3600 s, 12 tries) | yes | `mail_gateway/gateway.py:72-80` |
| Console ops requests | files in the ops folder, run by a host systemd timer every minute | yes | `deploy/systemd/trialbox-ops.timer`, `console/ops_pages.py:64` |
| Durable steps and outbox dispatcher | schema `wf` (`steps` with leases and attempts, `outbox`) | designed to; **no production caller** | `orchestrator/db_pg.py:243`, `outbox.py:106`; grep finds callers only in `tests/`, `tools/cascade_e2e.py`, `tools/testbench` |
| Data-operations batch | `dataops.batch`, written once at the end of the run | a killed night leaves no row | `adapter/pipeline.py:840-857` |

Timers: orchestrator APScheduler (INGEST 02:00, MICROBATCH MON 03:00, NAV MON 03:30, COHORT 1st 04:00, RETENTION
05:00, CALIBRATION 1st 05:30, not-matched sample, site publish every 60 s: `scheduler.py:192-199`, `app.py:139`); a
second APScheduler in the same process for the opt-out worker (`datacore/optout_worker.py:349`); console APScheduler
(N1 07:00, N2 07:30, REDCap 03:00, health mail 07:00: `console/timers.py`); host cron (backup 04:45, backup status
hourly: `deploy/backup/trialbox-backup.cron`); systemd timers (ops 1 min, watchdog 1 min, egress refresh 2 min,
weights 01:30); loops (IMAP poll, mail outbox, audit drain, gateway load watch). The APScheduler job stores are in
memory with a six-hour misfire grace (`tb_common/config.py:299`), which is the right setting for a box that reboots.

## 3. Status of earlier findings

### 3.1 Previous deep review (2026-11-10): architecture-relevant Blocker, Critical and High

| Old ID | Severity | Status at `514ae9b` | Evidence |
| --- | --- | --- | --- |
| DATA-001 nightly ingest has no completeness or volume gate | Critical | fixed | `adapter/governance.py:246-294`, `:623-673` (completeness condition of the gate record, drop guard); `TB_FEED_MAX_DROP_PCT` declared. Read, not re-run |
| DATA-002 two ingest stacks | High | fixed | `services/dataplat` is gone; contracts, quarantine, gate, `pid_alias`, lineage are in `adapter/governance.py` and `adapter/pidmap.py` (D-370, D-381) |
| DATA-004 a missing site key is silently created | High | fixed | `adapter/pipeline.py:89-95` `SiteKeyError`, `site_key.json` fingerprint; `adapter/app.py:89` answers `refused`; `load_or_create_key` is now used only by `console/totp.py:104` |
| DATA-021 audit verify has no head anchor | High | fixed (run) | 4,000 synthetic events, last 50 lines dropped: `audit chain FAIL ... the head anchor says event 4000`; with `HEAD.json` removed too: FAIL "no head anchor". Signed off-box heads exist (`audit.py:391`); whether a box has an anchor target configured is an install matter, not checked |
| DATA-022 opt-out removes the patient from lists only | Critical | partly | T-727 registry: 218 entries, 85 `erase`, **60 still owed** (run: `len(erasure.owed())`); clears exist for pool, candidate registry, OMOP, profile, vec. Lake snapshots, NDJSON, embed cache, HAPI, job outputs, traces, backups are owed (T-206b) |
| DATA-024 WAL archiving off, RPO 24 h | High | partly | still off by default (`docker-compose.yml:65`); `backup-install` turns it on "where the image and an off-box share allow it" (`backup_schedule.py` header); T-691 removed the pause. Not run |
| OPS-010 host tree outside the signed bundle | High | fixed (read) | `tools/trialbox/update.py:16-17`, `:272-278` (payload kind `host`, T-631, D-367) |
| OPS-011 a site cannot give the box its mapping or feed | High | fixed (read) | `docker-compose.yml:215-216` (`TB_SOURCE_DIR`, `TB_MAPPING_HOST_DIR`) |
| OPS-027 nothing tells a person the box is unhealthy | High | fixed (read) | `console/metrics_page.py:57`, `deploy/docker-compose.monitoring.yml`, `TB_HEALTH_MAIL_AT` (`console/timers.py`) |
| OPS-049 egress open after a reboot | High | fixed (read) | `deploy/systemd/trialbox-egress.service`; `trialbox.service` `Requires=` it |
| OPS-062 three documents name three host systems | High | partly | addendum §4.4: the box is Linux; the WSL2, Kubernetes, Podman and two-device trees are all still in `deploy/` (ARCH-017) |
| OPS-068 the platform form has no day-2 operation | High | partly | `deploy/platform/base/day2.yaml`, `kind-day2.sh` exist; not run |
| ENG-016, ENG-020 (gate can pass vacuously; cascade exclusion paths untested) | High | not re-checked here | area of the engineering-quality reviewer |

Scale review (2026-11-11) items that are architecture: F-28 (restart re-runs every job from zero, no count):
**open, reproduced** (ARCH-001). F-08 (ingest timed against 7,200 s): fixed by T-690. F-01 (publish against 330 s):
fixed by T-690. F-02 (backup pauses every service): fixed by T-691. F-14 (latest job looked for in the newest 500
jobs): **open** (`console/home.py`, 11 call sites, ARCH-020). F-12 (audit writer reads the whole day file per
event): the append now reads the last line and the anchor only (`audit.py:297-330`), but see ARCH-011 for the
measured rate.

### 3.2 Today's architecture notes (`docs/reviews/2026-11-12-architecture/`): where I agree and disagree

| Note | Their finding | State at `514ae9b` | My view |
| --- | --- | --- | --- |
| trust F1 (every container holds every database password) | High | **fixed** by T-212d: `docker-compose.secrets.yml:36-45` clears each `TB_DB_PW_*`; `test_compose_secret_reach.py` passes (run) | agree with the fix |
| trust F2, F7, F12 (token-only doors) | High/Med | **fixed** for the service level by T-713 (`orchestrator/callers.py`, `route_callers.yaml`); the person still comes from the body on about 40 routes (T-715 not built) | agree; T-715 stays the larger half |
| trust F4, R3 (owner equals writer) | High | open (T-718) | agree. I add: 17 schemas are co-owned by the console and the orchestrator, so T-718 cannot be done schema by schema until the console stops importing the orchestrator's stores (ARCH-005) |
| trust TR-6 "migrations stop running at service start" | proposal | open | agree, independently reached (ARCH-009) |
| lifecycle F-1 (hold during a rebuild) | High | **fixed** by T-722; `test_lake_rebuild_lock.py`, `test_snapshot_holds.py` pass (run) | agree |
| lifecycle F-2, F-3, F-4, F-10, F-12 (the night is not an object) | High/Med | open: `pipeline.py:581-588` (pid map before the gate), `:694-729` (OMOP → FHIR → lake, promote not last), `:840-857` (row at the end) are unchanged | **agree, and it is worse than written**: the note assumes the INGEST job's reply ends the night; since T-690 the night's only state is the adapter's memory, so a restart on either side loses it (ARCH-002, run) |
| lifecycle F-7 (erasure) | High | partly (T-727 merged; 60 clears owed) | agree |
| lifecycle F-8, F-9 (restore and as-of undo opt-outs) | High | open (T-728 not merged) | agree; not re-checked |
| lifecycle G-3 (a new DuckDB file per generation, also for a site publish) | proposal | — | **partly disagree.** Immutable generations are right. Making one by copying the hospital's snapshot for each confirmed chart fact costs a full rebuild (805 s at 50,000 in the scale review) and a full file. For a single box a smaller design reaches the same guarantee: keep the night's file immutable and put the site's confirmed facts in a second, small attached database that queries join; a publish then writes megabytes and the generation is (night file sha, site file sha). Not prototyped; `lake/flatten.py` merges site resources into the same tables today, so this needs a design spike before T-724 is sized |
| lifecycle G-5 / T-726 (steps chained by completion, one runner) | proposal | open | agree; this is the single most valuable architecture card. I add that the console's four timers and the host's backup cron belong in the same runner (ARCH-003) |
| decision H1 to H4, R1 to R3 | High | open; T-705 and T-706 merged as tests with expected failures; T-707 to T-710 not built | agree. I add one simplification: the note keeps v1 and the cascade and unifies their rules; the code would be smaller and the invariant easier to hold if NAV and the MICROBATCH re-check called the cascade and `TB_SCREEN_PIPELINE=v1` and `TB_SCREEN_ENGINE=cql` were removed as run-time choices (§5) |
| decision "SCREEN goldens do not run the cascade" | fact | not re-checked | same class as ARCH-006 (the tested path is not the shipped path) |

## 4. Findings

### 4.1 Table

| ID | Sev | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ARCH-001 | High | A restart re-runs every interrupted job from zero, with no attempt count and no lease. | **Run E1:** one INGEST job, the scenario publishes one file then the process dies; 6 simulated boots → `scenario_runs=6`, 5 `job.requeued` audit events, `orch.jobs` has no `attempt` or `lease` column. Code: `orchestrator/core.py:595-601`, `db.py:259-265`. | A 5-hour SCREEN (G1: 17,960 s at 50,000) never ends on a box that restarts once inside that window (update, watchdog, OOM at the 4g cap). A job that itself kills the process loops until the watchdog gives up after 3 restarts; then the orchestrator stays down and needs SQL by hand. Scale review F-28, still open. | Give `orch.jobs` an attempt count and a lease; resume from recorded steps (the unused `StepStore` already does leases, attempts and recorded step outputs); after N attempts (a declared setting) the job is `failed: interrupted` and the owner is told. | T-689 | Go-live both |
| ARCH-002 | High | The night's ingest cannot be followed across a restart of either side; its only state is the adapter's process memory. | **Run E2-A:** adapter running a night; a second `AdapterHttp.run()` (what a re-queued INGEST job does after an orchestrator restart) → `StepFailed` after 0.2 s, `step=ingest msg='an ingest is already running' detail='adapter HTTP 409'`; the adapter's run is still `running`. **Run E2-B:** adapter killed and restarted mid-run → `StepFailed` after 6.8 s "the adapter no longer knows ingest run ... (it restarted)"; `GET /run` → `{'state': 'none'}`. Code: `adapter/app.py:38-41`, `:49-52`; `orchestrator/clients.py:138-158`; `scenarios/admin.py:72-91`. | Case A: the night completes and is promoted, but the INGEST job is `failed`, the site contact gets a Failed mail, and the follow-ups that hang on the job's reply (after-ingest MICROBATCH, twins: `admin.py:88-90`) never run. The administrator's retry (D-474) then runs a second ingest of the served night (lifecycle F-3). Case B: no record anywhere says how far the night got (pid map written, NDJSON partly written, no `dataops` row). | Short term: on 409 follow the busy run (the 409 already carries `X-TB-Run`), see §8. Proper: the night's state is a row opened at the start and advanced per step (T-723), read by whoever follows. | T-723; NEW-ARCH-1 (S) "INGEST follows the running night on 409" | Go-live both |
| ARCH-003 | High | Eight places hold "is work running" and ten timers in three technologies start work; nothing orders the night except clock times. | §2.4 table (read). Two APScheduler instances in the orchestrator (`scheduler.py:244`, `optout_worker.py:349`), one in the console (`timers.py:107`), cron, four systemd timers. T-690 added two more state stores today (`adapter._runs`, `locks/*.rebuild.json`) although the addendum §3.4 says "it uses T-723's state, not its own". | No one can answer "what is the box doing now" from one place; the health page has to ask each. Every pair of mechanisms is a restart case of its own (ARCH-001, ARCH-002 are two of them). The clock order breaks when the ingest passes an hour (lifecycle F-13). | One runner: the orchestrator's queue, with steps recorded in PostgreSQL. Console timers (N1, N2, REDCap read, health mail) and the backup become jobs it starts by completion; the adapter and the lake execute steps but record them in the same rows. The host keeps the watchdog, the egress timers and the ops runner. | T-726 (extend its scope to the console timers and the backup), T-723 | Go-live both |
| ARCH-004 | Medium | A durable step engine and an outbox dispatcher exist and nothing in production calls them; the architecture page says delivery uses the outbox. | `orchestrator/db_pg.py:243` `StepStore` (leases, attempts, input hash, recorded output), `outbox.py:106` `Dispatcher`; callers found by grep: `tests/unit/test_outbox_killloop.py`, `test_recall_ledger.py`, `tools/cascade_e2e.py`, `tools/testbench/drivers.py` only. `docs/ARCHITECTURE.md:202` "Delivery goes through the outbox, never twice (D-127)"; `docker-compose.yml:48-49` "trialbox_wf for durable steps, outbox and recall ledger". Real delivery: `core.py:539-560` → mail gateway send keys. | About 760 lines and a schema (`wf`) that readers take for the crash-safety of jobs. It is the natural base for ARCH-001 and is being ignored while T-689 is designed. | Decide once: T-689 uses `StepStore` (preferred: it has the kill-loop test), or it is deleted with schema `wf`. Correct ARCHITECTURE §9 either way. | T-689; NEW-ARCH-2 (S) "use or delete StepStore/Dispatcher; fix ARCHITECTURE §9" | Go-live both |
| ARCH-005 | High | Process boundaries are not data boundaries: a distributed monolith. | §2.2 (run: import graph; read: role script). 17 schemas co-owned by `tb_console` and `tb_orchestrator`; the console imports five of the orchestrator's stores; `objects-data` is read-write in five containers; `lake-data` in two. | The costs of separate processes are paid (ARCH-001/002/003, about 20 fixed HTTP timeouts, §4.3, a service token and caller table per hop) while a compromised or buggy console still owns the tables. T-718 (owner ≠ writer) and T-715 (the person verified at the callee) cannot be finished while the console writes the stores itself. | Not a rewrite. (a) Draw the line where isolation is real and keep it: doc-parser, mail gateway, gateway, audit writer. (b) Make console → domain data go one way: either over the orchestrator's routes (remove the five store imports; the console role leaves `datacore, dataops, omop, sitesetup, orch, recall, wf, study, mpi, pidmap`), or accept one process. Pick per §6. (c) An import-lint test fixes the allowed edges. | T-718 depends on it; NEW-ARCH-3 (M) "console reaches domain stores only through orchestrator routes; import lint" | Go-live both (decision and lint), Later (the last stores) |
| ARCH-006 | High | The tested topology is the in-process one; the deployed one is HTTP. | Run (grep counts): `LakeLocal` in 76 test files, `LakeHttp` 10, `AdapterHttp` 4, `CompilerHttp` 2, `ParserHttp` 2, `MailHttp` 2. `tests/inproc_box.py`, `tools/e2e_simple.py:4` ("run in process"), `tools/role_demo.py:1`, the goldens (`tools/goldens.py:329`) all use the in-process clients. The compose job is in `trialbox-e2e.yml` (on demand/nightly), not a required check. | The layer where G1 and the scale review found the blockers (timeouts, polled jobs, restarts, serialisation of large answers) is the least tested. E2 above took one small script to find. | A required CI job that runs `e2e_simple` stages 0 to 3 with the real FastAPI apps and the real `*Http` clients wired through ASGI transports or loopback ports (no Docker needed; E2 shows the pattern), plus kill-and-restart cases for each follower. | T-714 (extend); NEW-ARCH-4 (M) "e2e_simple over the HTTP clients, with restart cases, required" | Go-live both |
| ARCH-007 | Medium | Every store has one connection under one lock; one slow statement blocks every other user of that store in the process. | **Run E3:** a `SELECT 1` on a `Database` while another thread ran a 3 s statement on it waited 2,815 ms. Design stated in `tb_common/db.py:10-12`. The orchestrator's `/healthz` reads the job store through the same connection (`orchestrator/app.py:159-162`). | Console: one slow `site` query stalls every page that reads the site store. Orchestrator: a long `orch` statement (a pool write for a hospital-wide screen) stalls job claims, state changes and the health check together. Not measured at scale. | Keep the serialised writer; give reads and the health check their own connection (two per store, or one shared read connection per process). Measure the longest statement per store in G1. | NEW-ARCH-5 (S) | Go-live both |
| ARCH-008 | Medium | Health is readiness, and the watchdog restarts on it; an orchestrator restart is destructive (ARCH-001). | Read: `/healthz` returns 503 when any check raises (`tb_common/http.py:61-77`); the orchestrator's check reads the database (`app.py:159-162`), the lake's reads `CURRENT` and the vector store, the mail gateway's reads its database and outbox; Docker marks the container unhealthy after 10 failures; the watchdog restarts it, up to 3 times in its window (`tools/trialbox/watchdog.py:316-357`). | A database outage of a few minutes makes every Python service unhealthy; restarting them cures nothing, and each orchestrator restart re-runs all running jobs from zero. | Split `/healthz` (the process answers) from `/readyz` (its dependencies answer). The compose health check and the watchdog use the first; the console's health page shows the second. | NEW-ARCH-6 (S) | Go-live both |
| ARCH-009 | Medium | Schema migrations run at service start, by whichever service constructs the store first, as the owning role; nothing ties a release to a set of schema versions. | Read: 24 `migrate()` call sites, nearly all in store constructors (for example `orchestrator/db.py:156`, `console/storedb.py:23`, `datacore/store.py:64`, `edc/store.py:266`); `tb_common/db.py:46-48`: "A caller that passes fewer versions than are applied ... is not refused". 17 schemas are opened by two processes. | During an update or a rollback an older container runs against a newer schema without a refusal. A failed migration fails one service's start in the middle of `compose up`; the others are already up on the new schema. Owner-level rights in every service exist only so that this can happen (trust F4). | One `trialbox migrate` step in install and update, run as the admin role before the services start; services start with a check ("applied == expected, else refuse") and no DDL right. | T-718 | Go-live both |
| ARCH-010 | Medium | An audit event is not in the transaction of the change it records, although both are in the same database. | Read: `DbAuditWriter` opens its own autocommit connection (`tb_common/audit_writer.py:170`); callers write the store first and append after, for example `core.py:412-413` (`db.put` then `audit.append`), `core.py:322-323`. | A crash between the two loses the event (a job state change, a lifecycle step with no audit line); an append followed by a rolled-back change records something that did not happen. Small window, but the audit is the record a monitor reads. Also: `audit.journal` is never pruned and duplicates the chain. | For state-changing stores, call `audit.append()` on the store's own connection inside the transaction (one SQL function call; the role already has EXECUTE). Keep the separate connection for events with no store change. Decide the journal's retention (drop rows already in a signed chain head). | NEW-ARCH-7 (M) | Go-live both |
| ARCH-011 | Low | The chain's write rate is low and the gateway writes one event per model call. | **Run:** `AuditLog.append`, 2 × 2,000 events: 70 /s then 53 /s on this shared VM (two fsyncs, a directory listing and a torn-line check per event; `audit.py:276-366`). `gateway/core.py:872-919` appends per call. Verify of 4,000 events: 0.13 s. | Not a defect at G1's load (6,704 calls in 5 h). At a batch of 64 concurrent short calls the drain can fall behind; the events wait in the journal, nothing is lost. | Record the measured rate in the capacity statement; if needed, the drain chains a batch with one fsync. | T-734 | Later |
| ARCH-012 | Medium | The console is one 36,227-line package with a 2,127-line `app.py`, three ways of reaching data and developer tools in its import path. | **Run** (`ARCH/console_graph.py`): 101 modules; 39 are `i18n_*.py` dictionaries (12,497 lines); `app.py` imports 45 console modules; `home` is imported by 30; one import cycle of 11 modules that includes `app`; 311 route decorators. Data: six own stores (`auth`, `sitestore`, `teamstore`, `saerecord`, `breakglass`, `feedback`), five imported orchestrator stores (§2.2), and HTTP (`backend.py`). `deploy/docker/python.Dockerfile:33` copies `tools/` (170 files, 68,113 lines, GCP drivers and test benches included) into every service image because the console imports it. It also runs timers and a `tools.cascade_e2e` thread (`cascade.py:67`, `:131`). | Every page change touches `app.py` or `home.py`; a change to a domain rule must be made on both sides of the HTTP boundary; the production image carries the whole developer tool tree. | No rewrite. In order: (1) product code may not import `tools` (move the four functions used into `libs/` or the console); the image then ships `tools/trialbox` only. (2) `app.py` only mounts routers; break the cycle by moving what `about`, `feedback`, `notify`, `rc_read`, `timers` take from `app` into a context object. (3) i18n tables to data files (one loader; the forbidden-word check already reads CSV). (4) ARCH-005 for the stores. | NEW-ARCH-8 (S) "no `tools` import in services; slim image"; NEW-ARCH-9 (M) "console: routers only in app.py, i18n as data" | (1) Go-live both; rest Later |
| ARCH-013 | Medium | Configuration: 366 declared settings, several sources, one dead file and stale examples. | **Run:** `len(tb_common.config.DECLARED) == 366` (203 str, 67 path, 49 int, 29 float, 18 bool), 58 are limits, timeouts or sizes; 481 distinct `TB_*` names in the tree. `site_params.yaml` (repository root, named in SPEC §12.1): grep finds no reader in `services`, `libs`, `tools`, `deploy` or the Makefile. `deploy/settings.example.yaml:30` names `judge: qwen3.5-35b-a3b-q4, extract_local: gpt-oss-120b-mxfp4` and `docker-compose.yml:366-367` defaults to `qwen3.5-35b-a3b-q4`, while ARCHITECTURE §7 says the pair is Gemma 4 26B and Qwen3.5-9B and that gpt-oss-120b was removed (D-124). `deploy/platform/base/settings.example.yaml` is a byte-equal second copy (diff empty). The same people lists exist in `settings.yaml` (`reviewers`, `allowlist`), `site_params.yaml` and the `team` store. | An owner (OD-13: not hospital IT) cannot know which of 366 names matter. Limits that should follow the hardware are 58 separate numbers. Example files teach the wrong model names. | Delete `site_params.yaml`. One example file, generated for the platform form. Group the 58 limit settings under the hardware profile (T-734 computes them; a site file overrides with a reason). Mark each declared setting `owner`, `installer` or `developer` and show only the first group in the wizard. | NEW-ARCH-10 (S) "config hygiene: dead file, one example, settings classed by audience"; T-734 | Go-live both |
| ARCH-014 | Medium | The gateway cannot tell the judge from the verifier: a role does not name a build, and both builds sit on one route for every patient role. Separation is the caller's convention. | **Run:** `RoutingPolicy.load().candidates(role, D3, A, PRODUCTION, ...)` gives, for `judge` and for `second_opinion`, route `patient` with `['j-workhorse@serving', 'v-verifier@verifier']`. `gateway/core.py:466-479`: the build is `body.model`, else `route.builds[0]`. The pair's verifier call uses the **same role** as the judge's (`matching/cascade/judge.py:173-176`: `primary.judge(role=role)`, then `verifier.judge(role=role)`); the two are told apart only by the model name each client was built with (`orchestrator/app.py:79-84`, `TB_GATEWAY_VERIFIER_MODEL`; compose default empty, `docker-compose.yml:253`; `install.sh:302` sets it). The guard is in the caller library: `tb_common/pair.py` `same_model` (fails closed) and `combine`. | Today's callers are protected by `pair.py`. The component that is the policy point for models holds no rule "the second answer of a pair comes from another build": a new caller, or a verifier client built without a model name, gets the judge build twice. | Give the call a seat the gateway can check: a header (`X-TB-Seat: judge` or `verifier`) or two roles, each bound in `routing.yaml` to one build; the gateway refuses a seat on the wrong build. The callers (`cascade/judge.py`, `evaluate.py`, `twophase.py`, the canary) send the seat. This is not a few-line change: both seats use one role today, so a split of the route by role alone would refuse the verifier's own calls. | NEW-ARCH-11 (M) "the gateway binds the pair's seats to builds" | Go-live both |
| ARCH-015 | Medium | The FHIR store is loaded with the whole hospital every night but read only at compile time and for TWPAS. | Read: `adapter/pipeline.py:701-710` (`sync_snapshot` each night); readers: `criteria_compiler/app.py:68` (equivalence gate, 200 sampled patients), `orchestrator/scenarios/twpas.py:156` (pre-check), `screen.py:242` (`TB_SCREEN_ENGINE`, default `sql`; ARCHITECTURE §5: "SQL is the only engine at run time"). It is a 5g JVM container, a store with no "not older than" guard (lifecycle F-4) and no erasure (owed in the registry). Its load time at 50,000 patients is not in the G1 record. | A night step, a failure mode (lifecycle F-2 starts with a fhir-store failure) and an erasure debt for a store that no screening path reads. | Load HAPI on demand: the gate's sample when a ruleset is compiled or approved, the TWPAS patients when a submission is prepared; take `sync_snapshot` out of the night. Remove `TB_SCREEN_ENGINE` as a run-time choice. If the full mirror is wanted for a later FHIR API, make it a step of the night that may fail without failing the night (T-723 makes that expressible). | NEW-ARCH-12 (M) "HAPI off the nightly path" | Go-live both |
| ARCH-016 | Low | Parts the architecture page calls removed, or that serve topologies no site has, are still in the production code path. | Read: `services/channels` (420 lines; docstring "channels.engine: hermes \| native", used by `console/command.py:25`, `proposals.py:20-21,176`); `models/routing.yaml`: 28 roles, topologies A/B/C, zones `tre`, `external`, `dev_public`, an OpenRouter endpoint and cost fields in the file the production gateway loads; `orchestrator/app.py:85-88` a direct `LLM_VERIFIER_BASE_URL` client that bypasses the gateway (unreachable by network on a box, reachable in code); `TB_SCREEN_PIPELINE=v1`. | Readers and reviewers spend time on paths no box takes; each is a switch someone can set. | Rename `channels` to what it is (the command grammar) and drop the engine language; split `routing.yaml` into the box's table and a developer overlay; delete the direct verifier client; see §5 for v1. | NEW-ARCH-13 (S) | Later |
| ARCH-017 | Medium | Seven deployment forms are kept alive for one product whose sites run a dedicated Linux box (OD-11). | Read: 13 `deploy/docker-compose*.yml`; `deploy/platform` (Kustomize base with 9 Deployments and day-2 jobs, 3 overlays, 3 components, `docker-compose.platform.yml`); `deploy/topology_a/podman-compose.yml`; `deploy/two-device/`; `deploy/windows/`; 14 scripts in `deploy/gcp`. Commit `f8ceaa7` "Master fix: the platform copy of the database roles script follows T-203a" is the drift this causes. Addendum §4.4 keeps them "in the tree and in CI as they are". | Every change to a service's environment, volumes, secrets or roles (T-690, T-212d, T-718 next) must be made twice or more, and the second copy is tested less. | Keep them, but generated: one source for the role script and the service table (compose is the source; the Kustomize `apps.yaml`, `db-init` and `settings.example.yaml` are rendered and checked by `make lint`, as contracts already are). Move Podman, two-device and Windows out of the required checks. | NEW-ARCH-14 (M) | Later |
| ARCH-018 | Medium | The console, the only place an owner sees the box's health, starts only after the gateway, the orchestrator and the mail gateway are healthy. | Read: `docker-compose.yml:341-345` (`depends_on` with `service_healthy`); `deploy/systemd/trialbox.service:14` (`up -d --wait --wait-timeout 900`, a fixed 900 s); the gateway exits at start on a perimeter problem (`gateway/app.py:314`) and refuses a bad prompt-registry entry in PRODUCTION. The console already degrades per call (`console/app.py:717` handler for `Unavailable`, health tiles in `backend.py:259-266`). | After an install, an update or a recreate with a model-side fault, the browser gets a connection error instead of the page that says what is wrong. (After a plain reboot Docker restarts existing containers without the dependency order, so this is the update and install path.) | The console depends on `db` only. | NEW-ARCH-15 (S) | Go-live both |
| ARCH-019 | Low | `docs/ARCHITECTURE.md` no longer describes the tree in several places. | Read: §2 table lists no `audit-writer` and no `model-guard` (both in `docker-compose.yml:222`, `:399`); §9 the outbox (ARCH-004) and "audit chain is daily JSONL files" with no mention of the journal; §2 "console: the box's timers" but most timers are the orchestrator's; nothing on the eight job states of §2.4. | The page is the entry point for a new engineer and for hospital IT. | Regenerate the service table from the compose file in `make lint`; rewrite §9 after T-723. | NEW-ARCH-16 (S) | Later |
| ARCH-020 | High | Fixed limits that are not derived from hardware, speed or size, and are not declared settings (OD-10). Worst offenders in §4.3. | Read (grep over `services` and `libs`): about 20 fixed HTTP timeouts, 11 `list_jobs(limit=500)` call sites in `console/home.py`, and the table below. | A result is cut or a step fails at a size the box was sold for, in most cases without telling the user. | Each row of §4.3 names its fix; most are covered by T-700 and T-687 to T-704. The two not covered get a card. | T-700, T-689, T-694; NEW-ARCH-17 (S) "the remaining fixed client timeouts become polled jobs or declared settings" | Go-live both |
| ARCH-021 | High | Two stores are opened by a service whose database role cannot reach the schema; on a box with the D-378 roles the features behind them do not work, and no test can see it. | **Run** (throwaway tests on the role cluster of `tests/unit/test_db_roles.py`, the real role script applied): (a) `ProfileStore()` as `tb_console` → `InvalidSchemaName: no schema has been selected to create in`; as `tb_orchestrator` → opens. The console opens it in `console/twin_api.py:36-40` for `GET /api/v1/studies/{rs}/patients/{pid}/twin` (T-204). (b) Schema `tuned` (`tb_common/notmatched.py:39`, T-310a) is on **no** role's list (`30-service-roles.sh:36-48`); the console opens it at start (`console/notmatched_pages.py:88`) and, having CREATE on the database, makes and owns it; `NotMatchedStore()` as `tb_orchestrator` then fails with the same error, at `orchestrator/notmatched_sample.py:71`, outside that function's `try`. The unit tests connect as `trialbox`, a member of every group. | On a real box the patient twin's read route answers 500, and the PI's weekly sample of not-matched patients (D-446, the site's check on what the models excluded) is never drawn; the only trace is a scheduler error in the orchestrator's log. If the orchestrator happens to create `tuned` first, the console fails at start instead. | (a) The console reads the twin through an orchestrator route (fits ARCH-005), or `profile` joins the console's list. (b) Add `tuned` to both roles' lists in both copies of the role script (§8). (c) The missing test: enumerate every schema the code opens (the erasure registry already lists all 27) and every store a service constructs, and fail when a schema is on no list or a service opens one its role lacks; run the role-cluster tests for the stores themselves, not for a `probe` table. | NEW-ARCH-18 (S) "every store a service opens is on its role's list; enumerating test" | Go-live both |

Counts: Blocker 0, Critical 0, High 7, Medium 10, Low 4.

### 4.2 Detail by ID

**ARCH-001, the run.** `ARCH/exp1.py` builds a real `Orchestrator` on a `JobDB` in a throwaway PostgreSQL, creates
one INGEST job as the scheduler does, and uses a scenario that publishes `list.json` and then raises a
`BaseException` (so no handler of `Orchestrator.run` sees it: the same as a kill). Each "boot" constructs a new
`Orchestrator`, calls `start()` and claims.

```
boot 1: claimed=True state_after_death=running outputs=1 scenario_runs=1
...
boot 6: claimed=True state_after_death=running outputs=1 scenario_runs=6
audit job.requeued events: 5 | any attempt/retry cap column in orch.jobs: []
```

Outputs do not multiply (same file name), and the mail gateway's send key makes a repeated mail one mail. What
multiplies is the work: model calls, lake queries, and for INGEST a whole night.

**ARCH-002, the run.** `ARCH/adapter_srv.py` serves the real `adapter.app` on `127.0.0.1:18050` with `run_ingest`
replaced by a sleep; `ARCH/exp2.py` drives the real `orchestrator.clients.AdapterHttp` with
`TB_JOB_POLL_SECONDS=1`, `TB_JOB_LOST_SECONDS=6`.

```
A1 first INGEST job starts the night: 202 running
A2 re-queued INGEST job after an orchestrator restart -> StepFailed after 0.2s: step=ingest
   msg='an ingest is already running' detail='adapter HTTP 409'
A3 the adapter's run meanwhile: running
B  adapter killed and restarted mid-ingest -> StepFailed after 6.8s: 'The nightly ingest could not be followed to
   its end: the adapter no longer knows ingest run 5e87c848fc55a09b (it restarted)'
B2 what the restarted adapter knows: {'state': 'none'}
```

Case A is reached by ARCH-001 alone: any orchestrator restart between 02:00 and the end of the ingest. The lake's
rebuild job does this better (state in a file, `interrupted` detected through the lock by any worker); the adapter
was given a weaker copy of the same idea in the same pull request.

**ARCH-003, what "one runner" means here.** Not a new framework. The orchestrator already has a queue in
PostgreSQL, job states, an audit event per state change, the administrator's retry (D-474) and a cancel flag. What
is missing is (1) steps inside a job that are recorded when done, (2) a lease so that "running" means a live owner,
(3) long work in another process (adapter, lake) recorded in the same rows rather than in that process, and (4)
start-by-completion instead of start-by-clock for everything after the ingest. (1) and (2) are `StepStore`. (3) is
T-723's row. (4) is T-726.

**ARCH-005, the choice.** The code supports either direction. The in-process form already exists for every hop
(`LakeAPI`, `ParserAPI`, `CompilerAPI`, `MailAPI`, `AdapterAPI` are Protocols with HTTP and local implementations),
so merging is a deployment decision; and the console already calls 6 orchestrator route groups with a signed actor,
so finishing the HTTP direction is also incremental. What does not work is the present middle. §6 gives my
recommendation.

**ARCH-007, the run.**

```
E3: a 'SELECT 1' on the same store while another thread runs a 3 s query waited 2815 ms
```

**ARCH-021, the run.** Two throwaway tests importing the `roles_cluster` fixture and `_as` of
`tests/unit/test_db_roles.py` (a cluster with `deploy/docker/db-init/30-service-roles.sh` applied twice):

```
tb_console in ACCESS for profile : False
RESULT tb_console profile FAILED InvalidSchemaName no schema has been selected to create in
RESULT tb_orchestrator profile opened

RESULT tuned in the role script: False []
RESULT tb_console opened schema tuned
RESULT tb_orchestrator FAILED InvalidSchemaName no schema has been selected to create in LINE 1: CREATE TABLE IF NOT
       EXISTS _schema_version ...
```

The other cross-process store imports of §2.2 were checked against the list by reading and are covered
(`dataops`, `sitesetup`, `omop`, `orch` for the console; `pidmap`, `mail`, `vec`, `profile` for the orchestrator).
This is the same defect class as ARCH-006: the configuration a box runs (per-service roles) is not the one the tests
run (one admin role).

**ARCH-014, the run** (the same candidates for both roles; the verifier's pair call itself is sent with role `judge`).

```
judge          -> route patient candidates in order: ['j-workhorse@serving', 'v-verifier@verifier'] fallback: none
second_opinion -> route patient candidates in order: ['j-workhorse@serving', 'v-verifier@verifier'] fallback: none
```

### 4.3 OD-10: worst hard-coded limits and timeouts

Ordered by what breaks first at a 50,000 to 500,000-patient site. "Declared" means a `TB_*` setting exists.

| # | Where | Value | Grows with | What happens | Covered by |
| --- | --- | --- | --- | --- | --- |
| 1 | `services/console/home.py:268, 313, 328, 510, 560, 582, 766, 829, 979`, `:524` (200); `screening_log.py:60, 387`; `step4.py:291` (200), `:382` (300); `app.py:948` (100) | newest 500 jobs of the box, filtered in the console | studies × nights | a study whose last SCREEN is older than the box's newest 500 jobs shows no list; every page view moves 500 job documents | T-700 |
| 2 | `services/orchestrator/clients.py:87` | 3,600 s for compile, diff, approve (no retry) | lake size (the gate evaluates the lake to sample 200) | approval fails at a large site; the compiler keeps working | T-690 pattern not applied: NEW-ARCH-17 |
| 3 | `services/console/backend.py:253` | 60 s for every console → orchestrator call, 1 retry | list and export size | export or page fails or is retried while the orchestrator still works (scale F-18) | T-700 (partly) |
| 4 | `services/lake/store.py:1074`, `libs/tb_contracts/generated/models.py:620` | 300 s per lake query | patients × rows | FEAS is one query (scale F-29) | T-695 |
| 5 | `services/orchestrator/scenarios/screen_cascade.py:315` | 20,000 model pairs per SCREEN (declared: `TB_SCREEN_MAX_PAIRS`, job option) | patients × note criteria | the rest is "unprocessed (budget)" | T-689 (budget from the population) |
| 6 | `services/orchestrator/scenarios/evaluate.py:47` | full-record read only when ≤ 100 candidates | run size | with 101 candidates nobody gets it (decision M5) | T-710 |
| 7 | `services/orchestrator/scenarios/microbatch.py:108` (1,000), `:133` (100); `notmatched_sample.py:42` (500) | newest N jobs | studies × nights | the night budget is computed from a cut list; the PI sample misses a study | T-700, T-704 |
| 8 | `services/orchestrator/clients.py:76` | 900 s doc-parser | document length, OCR | a long scanned protocol fails | NEW-ARCH-17 |
| 9 | `services/adapter/validate/validator.py:168` (1,800 s), `services/criteria_compiler/compile_cql/translator.py:104` (600 s) | subprocess limits | sample size, ruleset size | the night is held or the compile fails | T-693 |
| 10 | `services/orchestrator/twophase.py:161` (600 s), `services/gateway/swap.py:53` (wake 300 s; declared `TB_SWAP_WAKE_TIMEOUT_S`), `:60` (120 s) | model load time | the card and the weights | a swap on a cold 5090 fails the round | T-667 (measure), T-734 |
| 11 | `services/orchestrator/app.py:727` | 20,000 pids per death check | list size | 422; the console shows "unchecked" (scale F-35) | T-700 |
| 12 | `services/omop/conflicts.py:31` (500 rows), `services/console/breakglass.py:213` (200 grants), `services/console/backend.py:192` (200 audit rows), `libs/tb_common/notmatched.py:189` (500) | newest N | time | older rows leave the page without a notice | T-700 |
| 13 | `services/gateway/load.py:26-31`, `core.py:99`, `app.py:84-86`; `libs/tb_llm/timeouts.py:23-27` | 0.5 s slot wait, 30 s breaker, 40 s stall, 180/210/240 s budgets, 64 in flight | model speed | declared (`TB_GATEWAY_*`), defaults not derived from the serving record | T-734 |
| 14 | `deploy/systemd/trialbox.service:14` | `--wait-timeout 900` | model load time | boot or update fails on a cold load (scale F-24) | T-730 |
| 15 | `services/mail_gateway/gateway.py:76-80` | retry 60 s to 3,600 s, 12 tries, stale after 900 s | — | fixed policy, not a size limit; should be declared with its reason | NEW-ARCH-17 |
| 16 | `services/lake/store.py:142` | hold lives 14 days | job length | a job waiting for approval longer than that loses its pin silently | T-724 |

Input-size caps that are proper bounds on what a person uploads (`MAX_CHART_BYTES`, `ODM MAX_BYTES`,
`MAX_ATTACHMENT_BYTES`, `MAX_UPLOAD`) are not listed: they bound hostile input and are stated to the user.

## 5. What to drop or simplify

1. **`StepStore` / `Dispatcher` and schema `wf`**: use them for T-689 or delete them (ARCH-004). Do not leave a
   third option.
2. **The adapter's own run registry** (`adapter/app.py:38-41`): replaced by T-723's row; until then NEW-ARCH-1.
3. **The nightly HAPI load** (ARCH-015) and `TB_SCREEN_ENGINE`.
4. **`TB_SCREEN_PIPELINE=v1` as a run-time choice.** v1 is still the engine of NAV and the MICROBATCH re-check, so it
   cannot be deleted today; T-709/T-710 should end with those two calling the cascade, and then v1's tiering,
   `note_window` and excerpt code go. Two engines kept in parity by tests is the more expensive design.
5. **`site_params.yaml`** (no reader), the second `settings.example.yaml`, the stale model names (ARCH-013).
6. **`tools/` in the service image** (ARCH-012): 68,113 lines of developer and cloud tooling in every container.
7. **The direct verifier client** (`orchestrator/app.py:85-88`) and the non-box rows of `routing.yaml` (ARCH-016).
8. **The opt-out worker's second scheduler** (`optout_worker.py:349`): one interval job on the orchestrator's
   scheduler.
9. **Hand-kept second deployment forms** (ARCH-017): render them.
10. **`embed-service` as a container** when it runs the same image as the lake (the default): its only caller is
    the lake, which already imports `embed_service.embedder`. Keep the container only on a tier where the embedder
    needs its own image (`TB_EMBED_IMAGE`).

Not to drop: the gateway, model-guard, the audit writer, doc-parser and mail gateway as separate containers; the
lake as a separate query process (DuckDB memory must not be able to kill running jobs).

## 6. Is there a simpler architecture for one box at a hospital?

Yes, and it is mostly about state and runners, less about the number of containers. A rewrite is not supported by
the evidence: every structural defect above has a local repair and the in-process form of every boundary already
exists.

**Target (before 2027-04-28):**

| Today | Target | What changes in code | Risk |
| --- | --- | --- | --- |
| 8 places for "is work running", 10 timers | **One runner, one state store.** `orch.jobs` with lease, attempts and recorded steps; the night is one job whose steps (`ndjson, gate, omop, lake, promote, followups, backup`) are rows; the adapter and the lake execute steps and write those rows; console timers and the backup are jobs started by completion | T-689 on `StepStore`; T-723; T-726 widened; console `timers.py` posts jobs | Medium. The largest piece of work in this area (L + L + M). Mitigated by ARCH-006's HTTP e2e with restart cases landing first |
| File-based state on three volumes (`CURRENT`, `passed.json`, `held.json`, `holds/*.json`, `locks/*.rebuild.json`, `publishing.json`) | **PostgreSQL holds state; volumes hold bytes.** `dataops.generation`, `generation_step`, `served`; holds as rows; `CURRENT` kept as a file written from `served` for tools | T-723, T-724 | Medium. Backup and restore get simpler (one snapshot covers all state); the restore drill must be re-run |
| adapter → lake over HTTP for the rebuild, two processes writing `lake-data` under a `flock` | **The data service does the rebuild in process** (`TB_ADAPTER_LAKE=local` exists: `adapter/cli.py:119-126`); the lake container only answers queries and holds | a compose change and a memory cap; `publish(night)` becomes a local function | Low to medium. Needs one measurement: rebuild memory in the adapter container at 50,000 (§9) |
| `embed-service` container | in the lake/data process when the image is the same | compose only | Low |
| `fhir-store` loaded nightly | loaded on demand (ARCH-015) | adapter, compiler, TWPAS scenario | Medium: the gate and TWPAS must load their own patients first |
| console owns 22 schemas and imports five orchestrator stores | console owns `auth, team, site, breakglass, feedback, sae`; everything else through orchestrator routes with the verified actor | ARCH-005 fix (b), with T-715 | Medium, mechanical, page by page; T-714's fixture makes it testable |
| migrations at service start | one install/update step | T-718 | Low to medium |
| 12 application containers | **10**: db, console, orchestrator, data (adapter + rebuild + embed), lake (queries), criteria-compiler, doc-parser, mail-gateway, gateway, audit-writer; fhir-store on demand | — | — |

**What I do not recommend before go-live:** merging the console into the orchestrator (one user-facing process with
every key is a worse security position than today and T-715 goes the other way); merging the criteria-compiler into
the orchestrator (it is the only writer of rulesets and that separation is real); replacing DuckDB or the lake
format; a workflow engine from outside (Temporal, Celery): `StepStore` plus PostgreSQL is enough for one box and adds
no service.

**Calendar check.** 2026-11-12 to 2027-04-28 is 24 weeks. The night lane (T-689, T-723, T-724, T-725, T-726) is about
3 L and 2 M. If it starts after the decision and trust lanes it will not be validated on hardware before the Taiwan
go-live. It should start now, in parallel, because it touches different files (addendum §6 already says so).

## 7. What the plan must change (inputs to plan v7)

1. **Order.** NEW-ARCH-4 (HTTP e2e with restart cases, M) and NEW-ARCH-1 (S) first; then T-689 **on `StepStore`**
   (decide ARCH-004 in the card); then T-723; then T-726 with the console timers and the backup in scope; T-724 and
   T-725 after T-723. Record in T-690's row that its acceptance ("uses T-723's state") is not met.
2. **A design spike (S) before T-724 is sized:** site facts as a second attached database versus a new file per
   publish (§3.2). The answer changes T-724 from L to M or confirms L.
3. **T-718 gets a predecessor:** NEW-ARCH-3 (the console leaves the orchestrator's stores), else owner ≠ writer
   cannot be reached for 17 schemas.
4. **New small cards, all S, all before go-live:** NEW-ARCH-18 (stores and roles, with its enumerating test: do it
   first, it is a functional defect on every installed box), NEW-ARCH-5 (read connection), NEW-ARCH-6 (`/healthz` vs
   `/readyz`), NEW-ARCH-8 (no `tools` in services), NEW-ARCH-10 (config hygiene), NEW-ARCH-15 (console depends on `db` only), NEW-ARCH-17 (remaining fixed client timeouts).
5. **New medium cards:** NEW-ARCH-7 (audit event in the transaction), NEW-ARCH-11 (the gateway binds the pair's
   seats to builds), NEW-ARCH-12 (HAPI off the nightly path; do it
   inside T-723 since both edit `pipeline.py:694-729`).
6. **After go-live:** NEW-ARCH-9 (console structure), NEW-ARCH-13, NEW-ARCH-14 (rendered deployment forms),
   NEW-ARCH-16 (ARCHITECTURE page generated).
7. **T-734 (capacity statement)** takes the 58 limit settings as its output: each default is computed from the
   serving record and the measured rates, and the statement prints them.

## 8. Small certain fixes (not applied)

1. **ARCH-002, INGEST follows the running night.** `services/orchestrator/clients.py:138-142`: when `POST /run`
   answers 409 and the response carries `X-TB-Run`, set `rid` to that header and go on to the poll instead of
   raising. `ServiceError` must expose the response headers (or use `post_raw` with the status checked by hand).
   About ten lines. Test that fails first: in `tests/unit/test_polled_jobs.py`, start a run on the adapter app, call
   `AdapterHttp.run()` again, expect the report of the first run and not `StepFailed`.
2. **ARCH-021 (b), schema `tuned` on the role list.** `deploy/docker/db-init/30-service-roles.sh:40-47` and the
   copy `deploy/platform/base/db-init/30-service-roles.sh`: add `"tuned"` to the lists of `tb_orchestrator` and
   `tb_console`. Test that fails first: in `tests/unit/test_db_roles.py`, assert that every schema named by
   `tb_common.erasure.entries()` is in `SCHEMAS` (today `tuned` is not); and open `NotMatchedStore` as each of the
   two roles on `roles_cluster`. On a box already installed the schema is owned by whichever service made it; the
   script's existing loop moves objects to the group when it is re-run (install and update re-run it).
3. **ARCH-018, the console starts without the model path.** `deploy/docker-compose.yml:341-345`: keep
   `db: {condition: service_healthy}` only. Test that fails first: a compose-render test (as
   `test_compose_secret_reach.py` renders) asserting the console's `depends_on` is `{db}`. The Kubernetes form already
   starts the console with no ordering (`deploy/platform/base/apps.yaml` has no init container or wait), so the
   console is expected to start alone.

Not offered as a small fix: ARCH-014. Splitting the `patient` route by role looks like a few lines but would refuse
the verifier's own calls, which use the role `judge` (see the row).

## 9. Needs GCP / owner hardware

1. **Rebuild in the data service.** On the target box at 50,000 synthetic patients: run the night with
   `TB_ADAPTER_LAKE=local` and the adapter capped at the sum of today's adapter and lake caps (14g). Record peak
   RSS of the adapter container (`docker stats`, or the cgroup's `memory.peak`) and the rebuild wall time against
   the HTTP form. Pass: no OOM kill, wall time within 10 % of the HTTP form.
2. **HAPI's share of the night.** Same box and data: `python -m adapter.cli run ...` once with `load_fhir=true` and
   once with `false`; record the wall seconds of the `fhir` step from the ingest report. This number decides how
   much ARCH-015 saves; there is no threshold, the number goes into the capacity statement.
3. **Restart during a real night and a real SCREEN.** With the compose stack on the box: `docker restart
   trialbox-orchestrator-1` ten minutes into the 02:00 ingest and again one hour into a 50,000-patient SCREEN;
   `docker restart trialbox-adapter-1` ten minutes into an ingest. Record for each: the job's final state, whether
   `CURRENT` moved, whether the follow-up MICROBATCH ran, model calls made twice (gateway audit count before and
   after). Pass after T-689/T-723: the job resumes, no step runs twice, follow-ups run once.
4. **Audit drain rate on the box's disk.** `ARCH/audit_bench.py` (4,000 appends) on the box's audit volume. Record
   events per second. Pass: at least the peak model-call rate of the measured serving record (`max_num_seqs` divided
   by the median call time).

## 10. What is good

- The gateway: one model path, verified caller bound to the service token, registered prompts, no fallback for
  patient roles, one timeout budget across three layers, slots and a breaker.
- The audit: one writer, a journal no service can change, a head anchor (tail truncation and a missing anchor both
  fail verify, run), signed off-box heads, a resync record after a database restore.
- The lake's single `flock` for rebuild, hold, release and prune, and a rebuild state any worker can read (T-722,
  T-690's lake half); 63 tests pass.
- Checksummed, append-only migrations with a per-schema advisory lock.
- The per-route caller table and the compose secret-reach test: both make a class of mistake fail in CI.
- The declared-settings registry (`tb_common.config.DECLARED`) and the erasure registry (`tb_common.erasure`): the
  pattern "enumerate from the code, fail on an unlisted one" is the right one and should be reused for imports
  (ARCH-005) and deployment forms (ARCH-017).
- Service clients are Protocols with in-process and HTTP implementations, which keeps every option in §6 cheap.
- APScheduler's misfire grace and coalescing are set for a box that reboots.

## 11. What was not checked

- Nothing ran in Docker or on a GPU; the compose files, the systemd units and the Kubernetes form were read only.
- HAPI, the JVM validator and a real ingest did not run; the night's order was read from `pipeline.py`.
- E1 simulates a kill with a `BaseException` inside one Python process; E2 replaces the ingest body with a sleep.
  The control flow under test (queue, clients, adapter app) is the real code.
- The audit rate (53 to 70 events/s) was measured on a VM shared by 13 reviewers; treat it as a floor, not a figure
  for the box.
- ARCH-007's and ARCH-008's impact at scale was reasoned, not measured: I did not find or time the longest statement
  per store.
- The backup's consistency across the two database snapshots and the files (T-691's "window") and the restore path
  were not re-checked; lifecycle F-8, F-9 and F-11 were not re-run.
- The gateway's internals beyond routing and timeouts, the model swap, `tb_common.pair` beyond `same_model`'s
  header, the cascade engine, EDC, REDCap bridge and the mail gateway's intake were not reviewed here.
- `deploy/platform` was surveyed (counts of workloads, the duplicate settings file), not rendered or applied.
- ARCH-021 was run on a local role cluster with the real role script, not on an installed box; no installed box
  was available to confirm the 500 on the twin route or the scheduler error in the orchestrator's log.
- The count of 311 console routes is a count of decorators by grep; the import graphs count `import` statements by
  `ast`, including imports inside functions.
- The test PostgreSQL could not be started under the session scratchpad (`/tmp/claude-0` is mode 0700 and the server
  runs as `postgres`); the clusters for E1, E3, the role tests and the 63 tests ran under `/var/tmp/trialbox-0/ARCH`, removed after.
