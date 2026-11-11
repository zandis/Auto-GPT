# TrialBox architecture

*Owner: Aimedics engineer. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

This page describes the code at the head of `master`. Each claim names the decision (D-nnn in
[DECISIONS](DECISIONS.md)) and, where it matters, the test that holds it. For hospital IT the one-page port and secret
sheet is `docs/handover/network-sheet.en.md` (also ja and zh-TW).

## 1. The idea

TrialBox holds two kinds of data with different owners (plan v4 §3):

- **Clinical facts** come from the hospital: EMR exports, SS-MIX2, CGRD views, FHIR bundles. TrialBox only reads
  them. They live in a FHIR R4 store (HAPI) and a DuckDB lake.
- **Trial facts** are made at the site: marks, consent, enrolment, visits, CRF answers, AEs, deviations, screening
  numbers, people, settings. TrialBox owns them. They live in one PostgreSQL database, `trialbox_wf` (D-126).

Never two stores of record for one fact. Hospital systems are read one way only; REDCap and spreadsheets sync two
ways (D-123).

## 2. Services

One `docker compose` project, `trialbox` (`deploy/docker-compose.yml` plus one GPU file).

| Service | Code | Port | What it does |
| --- | --- | --- | --- |
| console | `services/console` | 8090 | the product: sign-in, roles, every page, `/api/v1`, the box's timers (N1 07:00, N2 07:30, REDCap 03:00) |
| orchestrator | `services/orchestrator` | 8010 | jobs (FEAS, SCREEN, CASE, NAV, COHORT, ...), reports, delivery, the canary gate |
| gateway | `services/gateway` | 8020 | the only path to a model; routing by data class; the one-GPU sleep swap |
| mail-gateway | `services/mail_gateway` | 8015 | mail in (IMAP) and out (SMTP), sender checks, the outbox |
| criteria-compiler | `services/criteria_compiler` | 8012 | protocol text to criterion IR, then SQL (and CQL for the gate) |
| doc-parser | `services/doc_parser` | 8011 | PDF, Word and text to sections and criteria blocks |
| adapter | `services/adapter` | 8016 | hospital data to FHIR NDJSON and the lake, with pseudonyms |
| lake | `services/lake` | 8013 | DuckDB: read-only SQL, note search (BM25 and embeddings) |
| embed-service | `services/embed_service` | 8014 | embeddings for note search |
| fhir-store | HAPI JPA | 8080 | FHIR R4 store (database `hapi`) |
| db | PostgreSQL 16 | 5432 | databases `hapi` and `trialbox_wf` |
| llm-service, llm-verifier | vLLM 0.32.0 | 8000 | the judge and the verifier (GPU profiles); `llm-stub` without a GPU |

Libraries: `schemas/` is the one source of every contract; `libs/tb_contracts` is generated from it (`make contracts`,
checked by `make lint`). `libs/tb_common` holds config, the audit chain, the database layer (`db.py`, one access layer
with versioned migrations, D-126), service tokens (`service_auth.py`), crypto, the LLM client, the PHI guard, routing
and retention.

Packages inside the services: `datacore` (forms, answers, sync, lifecycle; D-123, D-129, D-134), `sitesetup`
(readiness, chart upload, proposed facts, code mapping; D-135), `matching` (the cascade, coverage), `dataplat` (data
platform L0–L5), `deliverables` (the feasibility pack), `rc_bridge` and `rc_sim` (REDCap and its simulator),
`registry`, `guard`, `tracestore` (model registry, PHI recognisers, redacted traces).

Removed and not coming back: the Hermes agent, the MCP front door, the channel relay and MinIO (D-121); SQLite
stores (D-126); gpt-oss-120b on the Spark (D-124).

## 3. Networks

- `trialbox-net` and `trialbox-model-net` are internal: no route out of the box.
- Only the gateway is on `model-net`, so every model call goes service → gateway → model.
- `trialbox-egress` carries the few services that may leave: mail-gateway (SMTP, IMAP), gateway (a cloud model only
  when the site sets one, never for D3/D4 data), criteria-compiler (ClinicalTrials.gov while `TB_CTGOV_MODE=live`),
  orchestrator (NHI TWPAS, SUBMIT only). The host's nftables table (`deploy/network.sh`) allows only these.
- Only the console is published, on `127.0.0.1:8090`. The hospital reaches it through its own TLS proxy.

Each service has its own token and accepts only its listed callers (`tb_common/service_auth.py`, `CALLERS`; D-138).
Held by `tests/unit/test_service_secrets.py`, `tests/unit/test_network_sheet.py` (every port of the compose files is
on the sheet) and `tests/unit/test_egress_rules.py`. Details: [Security](SECURITY.md).

## 4. The data path

```
hospital export (CSV | SQL view | SS-MIX2 | FHIR bulk)
   │ adapter: site mapping (YAML), pseudonym pid = HMAC(site key, chart number); names and IDs only in the pid map
   ▼
FHIR R4 NDJSON snapshot ──► fhir-store (delta load: only new or changed resources, D-122)
                        └─► lake: DuckDB per snapshot (patient, encounter, condition, observation, medication,
                            procedure, report, document, claim, consent, appointment, practitioner) + note chunks
```

- The nightly ingest (02:00) checks a 1 % HL7 validator sample and fails above 0.5 % errors. The check runs before
  fhir-store and the lake are loaded: a failed night is *held* and `CURRENT` keeps the previous snapshot (D-149).
- A delta night (`--since`) drops what the source deleted (SS-MIX2 flag 0, FHIR bulk `deleted`, a `deleted` column):
  `tombstones.json` beside the snapshot lists them (D-149). It merges over the newest earlier snapshot that passed
  (`passed.json`, else `CURRENT`), never over a held night; with none, the delta night is held. A re-run of a
  promoted night is written to `ndjson-rerun/` and moved in only when it passes (D-271).
- A night that removes all records of a kind, or more than 20 % of them, is held (adapter), refused by the lake
  (an empty or missing folder too, `CURRENT` stays) and by the OMOP loader (every CDM table), unless
  `TB_FEED_DROP_OVERRIDE='<snapshot>: <reason>'` names that night (D-271).
- Each snapshot file records its lake schema version in `lake_meta` and has `.sha256` sidecars; a reader refuses a
  version it does not know. Note vectors live once, in `embed_cache.duckdb`, read by chunk sha (D-149).
- Snapshots kept: 3 nightly and 36 month-ends.
- Every file that leaves the box is a `flow.export` row of the audit chain (export ledger: identifier level, approval,
  sha256, recipients); `python -m tools.trialbox exports --days 30` lists them (D-149).
- Japan: the SS-MIX2 reader handles ADT-00/12/22/52, PPR-01, OMP-01/02/11/12, OML-11 and extended storage; output
  carries JP Core profiles, validated on a sample at ingest (D-122, D-137).
- Taiwan: CSV or CGRD SQL views with TW Core profiles.
- Lake queries are SELECT only (sqlglot guard), read-only, memory-capped and pinned to a snapshot.
- OMOP CDM v5.4 (`services/omop`, schema `omop` of `trialbox_wf`) is the store of record for clinical facts (D-144).
  With `TB_LAKE_SOURCE=omop` the rebuild loads the snapshot and the site's inputs into it (status, provenance,
  tombstones, conflicts in `tb_*` tables) and exports the lake from it, same tables and rows; the default is still
  `legacy` (D-151). With the flag `omop.dual_write` on, the adapter also loads each passed night into it as soon as
  the NDJSON is written, apart from the rebuild; a failed load is in the ingest report and never holds the night. The
  seven large clinical tables are partitioned by year (D-339).
- Feature flags (`tb_common.flags`, MR-090, D-207) are rows of `app.flag` in `trialbox_wf`, each change also a row of
  `app.flag_event` and a `flag.set` audit event with the actor and the reason, made by an administrator on
  `/ops/flags`. Every service reads them through a five-second cache, so a change applies without a restart; only
  declared names exist. An environment variable seeds a flag at the box's first start and is ignored after it
  (`trialbox doctor` warns when it disagrees). The first flag is `lake.source` (seeded by `TB_LAKE_SOURCE`), read
  once when a lake rebuild starts, so a flip applies from the next rebuild and never half-way through one.

Sources, mapping and the data core: [Data and integration](DATA.md).

## 5. The rule path

```
protocol text ─► doc-parser ─► criteria-compiler
   ir_extract (model, schema-bound) ─► criterion IR ─► terminology (value sets)
   ─► SQL (DuckDB templates)  and  CQL (templates)    ← never written by a model
   ─► equivalence gate: CQL on HAPI vs SQL on the lake, ≥ 98 %, with off-list fixtures (D-130)
   ─► S20 approval page: the investigator approves, with labels in the site's language (D-120)
   ─► approved ruleset (git tag <ID>/v<version>)
```

SQL is the only engine at run time; CQL lives only in the compile-time gate (owner decision 3, D-130). A code family
fails closed: a code inside the family but not on the list is unknown, not "no" (D-113). A code in a system nobody can
read is unknown with reason `unknown_code_system` (D-130). Held by `tests/unit/test_valueset_family.py`,
`tests/unit/test_code_coverage.py` and the off-list fixtures `tests/fixtures/equivalence/offlist/`.

## 6. Screening

The SCREEN job runs the cascade (`services/matching/cascade/`):

| Stage | What |
| --- | --- |
| S0 | consent and opt-out |
| S1 | the ruleset SQL in the lake (filters first) |
| S2, S2b | lexicon and semantic ranking of the notes |
| S3 | the judge reads the note and must quote it; the quote is checked against the record |
| S4 | the verifier gives a second opinion |
| S5 | the people: the PI and CRC lists |

A note answer excludes a patient only when both models say "fail" on a verified quote; any disagreement becomes
"unknown", never an exclusion (D-115). Reasons are 16 codes with words in three languages (D-118). The pair canary
(54 questions in en, ja, zh-TW) runs before the night's model jobs and gates note exclusions: if it fails, notes never
exclude (D-117). The structured part runs without a model; FEAS never calls one (D-101). Held by
`tests/unit/test_agreement_judge.py`, `tests/unit/test_canary_gate.py` and `e2e_simple` stages 1 and 3.

## 7. Models and hardware

One pair everywhere (D-124): judge Gemma 4 26B-A4B-it NVFP4 (`j-workhorse`, endpoint `serving`), verifier
Qwen3.5-9B AWQ 4-bit (`v-verifier`, endpoint `verifier`, thinking off).

| Tier | `--gpu` | Box | Layout | Context |
| --- | --- | --- | --- | --- |
| `large` | `rtxpro6000` | RTX PRO 6000 96 GB | both resident, 0.40 + 0.20 of the card | 32k |
| `medium` | `gb10` | DGX Spark | both resident, 0.30 + 0.15 of memory | 16k |
| `small` | `rtx5090` | one RTX 5090 32 GB | sleep swap, one model awake | 8k |

On the 5090 a screening run holds the card, the judge answers first, then the gateway swaps to the verifier, then
back (`services/orchestrator/twophase.py`, `services/gateway/swap.py`; D-116). A tier installs only on a serving
record measured on its own uncapped card (D-124, D-138). Only `large` has one today
(`deploy/measured/serving_config.rtxpro6000.json`). Held by `tests/unit/test_hardware_profiles.py`,
`tests/unit/test_install_tiers.py` and `tests/unit/test_model_swap.py`.

Prompts are registry objects (D-300): the texts live in `libs/tb_llm/prompts/` (one file, the EDC prefill prompt,
is registered at its own path until its folder is free), and `registry.yaml` there lists each version with its
file, sha256, output schema and the schema's sha256, approver, date and qualification record.
`libs/tb_llm/prompt_registry.py` resolves `(id, version)` (newest when none is named) and refuses an unknown version,
a file or schema whose sha differs from the registry, a prompt with no schema for patient data (D2 to D4), and, in
PRODUCTION, a version without a qualification that holds (the prompts in service when the registry was made, text
and schema, are a frozen baseline). Every loader (`tb_common.llm.load_prompt`) reads through it. The gateway
resolves the `X-TB-Prompt` header the same way and refuses a call whose messages are not that template rendered
(the literal text between its `{{ }}` expressions, exact, in order and anchored at both ends; what the expressions
render to is not checked), whose response schema is not the registered one, or, outside DEV and TEST, that does not
send the registered sha; it refuses to start in PRODUCTION on a bad entry, and its trace names `prompt_id@version`.
A job that recorded `judge@4` resolves `judge@4` after `judge@5` is registered. Held by
`tests/unit/test_prompt_registry.py`.

## 8. The console and the work

Five roles: administrator, coordinator (CRC), investigator (PI), CRO monitor and viewer (D-110). Each lands on its
own home. The header command field opens pages only; it never runs a job (D-110). Lists: ready and
needs-information, worked through with marks and a two-tap outcome (D-120). Forms: seven built-in forms in three
languages, with checks, branching and history, exported as ODM 1.3 and REDCap CSV (D-129). Lifecycle: candidate to
completed or withdrawn, visit windows, AEs and deviations (D-134). Site set-up: readiness page, chart upload with
proposed facts, code mapping (D-135). Held by `tests/unit/test_datacore.py`, `tests/unit/test_lifecycle.py`,
`tests/unit/test_site_setup.py`, the page tests in `tests/console/` and the walk. Pages: [User guide](USER_GUIDE.md).

Mail is still a front door: a mail subject such as `FEAS GZQO` is the same call as the console's button, with the same
permissions and audit (D-121). Results go by mail; patient-level files only to the study's internal list, encrypted.

## 9. Jobs, audit and re-runs

- Jobs live in schema `orch` of `trialbox_wf`; every state change and output file goes into the audit chain with its
  sha256 and recipients.
- The audit chain is daily JSONL files, each line hashed with the one before (`tb_common/audit.py`;
  `tools/audit_verify.py`).
- A job's run date is fixed at start, so a re-run on the same snapshot is byte-identical
  (`python -m orchestrator.rerun`, D-82; checked by `e2e_simple` stage "re-run").
- Delivery goes through the outbox, never twice (D-127).

## 10. Where the rest is

Operations: [Runbook](RUNBOOK.md). Controls: [Security](SECURITY.md). Evidence: [Validation](VALIDATION.md). The
v4 specification is `spec/v4/`; the v1 and v3 specifications are in `spec/archive/`.
