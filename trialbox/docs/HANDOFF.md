# TrialBox handoff: from the v4 spec to a working end-to-end build

Written 2026-10-24, for the next build session. Branch `claude/trialbox-e2e-build-lcvm9p`, head `6152c39` or later.
Open PR: https://github.com/zandis/Auto-GPT/pull/2. The copy-paste starter prompt is in
[`NEXT_SESSION_PROMPT.md`](NEXT_SESSION_PROMPT.md).

This file says what exists, what the next session builds and in what order, how to run and verify everything, and the
traps already found. The spec (`spec/v4/`) is the contract; this file is the route through it.

---

## 1. What TrialBox is (one paragraph)

An independent, hospital-owned agent for the site-side clinical-trial lifecycle (Taiwan first, Japan next). It reads
the hospital's EMR, research database and registries through a data platform (stages L0–L5). It filters patients with
compiled rules before any model reads a note (cascade S0–S5), and it states how many eligible patients it may have
missed (recall certificate). It answers sponsors with standard deliverables (feasibility pack and others) and helps
staff at every later step. People use email, Teams or LINE through a hardened Hermes front door, or through the native
engine. The deployment is on premises by default, with hybrid cloud allowed only for D0–D2 data.

## 2. State of the repository

### 2.1 Built and tested (v1 code, plus the v4 evidence tools)

| Area | Where | Status |
| --- | --- | --- |
| v1 appliance: mail gateway, orchestrator (FEAS, SCREEN, MICROBATCH, NAV, TWPAS, COHORT), criteria compiler (IR → CQL/SQL), doc parser, adapter, DuckDB lake, HAPI FHIR store, LLM stub | `services/*`, `libs/tb_common`, `libs/tb_contracts`, `deploy/docker-compose*.yml` | Green: 286 unit tests, 59 integration, 6 e2e. Runs on Linux and on Windows (WSL2). |
| Fixes for the 15 deep-review findings | see `docs/PROGRESS.md`, `docs/DECISIONS.md` D-86 | Done |
| Multilingual criterion benchmark | `eval/criterion_ml/` (1,015 physician-labelled pairs; notes in en, zh-TW, ja, mixed) | Done. The zh-TW, ja and mixed notes are machine translations awaiting clinician review (VV-32). |
| Bake-off harness (OpenRouter or any OpenAI-compatible endpoint) | `tools/mlbench.py`, `tests/unit/test_mlbench.py` | Done; **never run live**, because `OPENROUTER_API_KEY` is not set |
| Anytime-valid recall bounds | `libs/tb_common/recall.py`, `tools/recall_sim.py`, `tests/unit/test_recall_cert.py` | Done. Simulation: repeated Clopper–Pearson looks miss 9.7 %, the confidence sequence 0.3 % |
| Open-data end-to-end test | `tools/fetch_open_data.py`, `tools/open_data_e2e.py`, `services/adapter/mapping/mimic/`, `tests/fixtures/open_data/`, `make open-data-e2e`, `docs/OPEN_DATA.md` | Done. MIMIC-IV FHIR demo v2.1.0 against EMPULSE and STARRT-AKI; passes and reproduces |
| v4 specification | `spec/v4/` (9 files + `README.md` index, about 149k words) | Done; four adversarial review rounds, all findings applied |
| Reviews and research | `docs/reviews/`, `docs/research/`, `docs/LANDSCAPE.md` | Done |
| TrialGPT port (NCBI TrialGPT on a local LLM, with its own web UI) | **other branch:** `claude/trialgpt-local-lcvm9p`, folder `trialgpt/` (`trialgpt_local/app.py`, `static/index.html`) | Done there; vendoring into TrialBox is S1-17 |

### 2.2 Specified but not built (v4)

Everything in `spec/v4/` §17.1 marked as a new package: `services/gateway`, `registry`, `guard`, `tracestore`,
`frontdoor_mcp`, `channels`, `dataplat`, `vault`, `omop`, `terminology`, `matching`, `feasibility`, `tracking`,
`lifecycle`, `abstraction`, `closeout`, `nhi`, `network`, `agent`, `deliverables`, `console`, `cds_hooks`, `keys`,
`mcp`, `siem_forwarder`; `libs/tb_llm`, `tb_analytics`, `tb_reports`, `tb_security`, `tb_testkit`;
`integrations/hermes`; `tools/trialbox` (CLI). The orchestrator still stores state in SQLite (`services/orchestrator/db.py`).
The durable Postgres steps and outbox (S1-05) do not exist yet.

### 2.3 Open items carried over

| Item | Blocked on | Next action |
| --- | --- | --- |
| Live multilingual bake-off (task: find the best small LLM per language) | `OPENROUTER_API_KEY` as an environment secret (never pasted in chat) | `python -m tools.mlbench run --models <ids> --langs en zh-TW ja mixed`; later through the gateway as S1-14 |
| Abstention calibration (Learn-then-Test) | model confidence scores from the bake-off | §16.6; `services/orchestrator/calibration/abstain.py` |
| Clinician review of the 3 × 326 translated sentences (VV-32) | a clinician | Until then, non-English floors stay at 0.82 (§16.4) |
| Chia corpus licence (for `criteria_extract_public`) | confirmation (App. H, *uncertain*) | Ship the loader only after it is confirmed |
| IRB, PDPA basis, hospital feeds, hardware | the hospital | Not needed for MS0; work on open data only |

## 3. What "everything end to end" means for the next session

The spec's full plan is MS0–MS6, about 96 weeks for a team of 7. One session cannot build all of it. The goal for the
next session is a **v4 vertical slice**: every layer of the v4 architecture exists as real, tested code on the
critical path, runs end to end on open and synthetic data, and can be driven and inspected from a test web page.
Wherever an external system is out of reach (HIS, IdP, Teams, LINE, NHI, the hospital network), use the fake
transports the spec already names. Breadth on the critical path comes first; depth comes in later milestones.

The end-to-end path the slice must run, from one button or one command:

```
open data (MIMIC-IV FHIR demo, Synthea fixtures, TrialGPT notes, CT.gov records)
  → dataplat L0 landing → L1 validate + reconcile + DQ + publish gate → L2 standardise → L3 pseudonymise (MPI)
  → L4 curated snapshot → L5 serving pin                       (+ OpenLineage events at every stage)
  → trial intake (CT.gov JSON or protocol PDF) → IR v3 → criterion library → SQL/CQL
  → cascade S0 structured → S1 lexicon → S2 / S2b → S3 LLM judge via tb-gateway (D0 notes only) → S4 aggregate → S5 human
  → feasibility pack (tables, figures, PDF/XLSX, small-cell rules) + recall certificate (confidence sequences)
  → reply through the channel engine (native email via MailHog; Teams as a fake transport) and the audit chain
```

## 4. Build order for the next session

Work in this order. Commit and push at the end of every phase with tests green. Each phase lists its spec tasks (§20.8),
the paths (§17.1 governs) and the done-when criteria. Requirement IDs go into the tests as `@req` markers (§17.4).

### Phase 0: baseline (about 30 min)
1. `cd trialbox && make venv` (Python 3.12, uv). Then `make lint` and `make test` must be green.
2. `make open-data-e2e` (needs network access to physionet.org and clinicaltrials.gov) must PASS. The report is written to
   `.cache/open_data/report.md`.
3. Check `docker info`. If Docker works, `make up-test && make test-e2e` must be green. If it does not, use the in-process
   box (`tests/inproc_box.py`) and say so in the PR.

### Phase 1: Sprint 1 of the spec (S1-01, S1-02, S1-03, S1-05, S1-06 v0, S1-12, S1-15 schema)
- **S1-01** data-class contract: `libs/tb_contracts/dataclass.py`, `libs/tb_common/policy/classes.py`; every contract
  carries `data_class` (D0–D4).
- **S1-02** L0 landing: `services/dataplat/landing/`, idempotent manifests with a sha256 and a schema fingerprint.
- **S1-03** L1 validation and publish gate: contracts, reconciliation, DQ (use Great Expectations-style rules in code;
  not Soda Core v4, which is ELv2), quarantine with reason codes, planted-defect generators in `libs/tb_testkit/`.
- **S1-05** durable steps and outbox on Postgres (`services/orchestrator/db_pg.py`, `outbox.py`). A kill-loop test must
  show exactly one delivery per outbox row. Keep SQLite as the test backend only if the spec allows it; otherwise run
  Postgres in compose.
- **S1-06 v0** `tb-gateway` (`services/gateway/`, built in-house; do not use LiteLLM, §8): OpenAI-compatible, class
  check, route refusal, audit record; `libs/tb_llm/` is the only client library; `models/routing.yaml`. Property test:
  0 routes from D3/D4 outside the perimeter.
- **S1-12** recall ledger: persist and resume `ConfidenceSequence` state (`services/orchestrator/recall/`).
- **S1-15** IR v3 schema and criterion-library tables (schema only); every v1 ruleset must still validate and re-run
  byte-identically.

### Phase 2: the rest of MS0 on the critical path
- **S1-04** L2–L5 thin path with lineage. Move `services/adapter/` and `services/lake/` into `services/dataplat/` with
  `git mv`, and keep import shims for one milestone. The MIMIC demo must become a snapshot with 0 blocking DQ errors.
- **S1-07** model registry v0 and model cards; **S1-08** trace store and PHI guard (TW/JP recognisers).
- **S1-09** front-door MCP server with exactly the 8 tools of §9.3; **S1-10** channel abstraction and the native
  engine (email via MailHog; Teams as a fake transport).
- **S1-13** public suites in CI (`judge_public` must reproduce GPT-4 accuracy 0.873 and false-block 0.014 from the
  recorded outputs); **S1-14** `tools/bakeoff.py` with `--dry-run` (the live run only if the key exists).
- **S1-16** `trialbox doctor`; **S1-17** vendor the TrialGPT port from branch `claude/trialgpt-local-lcvm9p`
  (`git show` or `git checkout <branch> -- trialgpt/...` into `services/matching/registry_match/`). Remove any live CT.gov
  search that sends patient-derived text.
- **S1-11** Hermes (pinned v0.22.2, minimum v0.21.6) only if the release can be fetched and pinned by digest. If it
  cannot, ship the native engine, keep `channels.engine: native`, and record the gap.

### Phase 3: cascade and deliverables end to end (MS1 slice)
- Cascade S0–S5 (§4) over the dataplat L5 snapshot. S3 judges notes through `tb-gateway`. Use only D0 notes: the
  TrialGPT patient notes in `eval/criterion_ml/`. MIMIC demo has no notes. Backends, in order of preference:
  `llm_stub` for deterministic tests, then OpenRouter (D0 only, if the key exists), then a local Ollama if one is present.
- Feasibility pack DL-1 with the §12 figures (at least the waterfall F-F1, fan chart and tornado), PDF and XLSX, with
  sponsor small-cell rules ("<11", base-5 rounding) and internal "<5".
- Recall certificate on each run (strata, Bonferroni or pre-registered α per cell, two known-positive lines).

### Phase 4: the test web ("Test Bench"), see §5

### Phase 5: hardening, docs, PR
- Update `docs/ARCHITECTURE.md`, `README.md`, `docs/OPEN_DATA.md` and the §17.1 table if a path changed.
- Run `make lint`, `make test`, `make open-data-e2e`, the Test Bench browser tests, and the compose e2e if Docker works.
- Open the PR as a draft (see §8 for the base branch), with a test-plan section listing the exact counts.

## 5. The test web ("TrialBox Test Bench")

**The constraint.** C-5′ allows exactly five end-user surfaces, and FR-UX-12 fails CI on any other HTTP route. So the Test
Bench must be a **developer and validation tool**, not a product surface:

| Rule | How |
| --- | --- |
| Not in product images | Lives in `tools/testbench/`, not `services/`. It runs only in a compose profile named `dev` (`deploy/docker-compose.testbench.yml`) or via `make testbench`. A CI test asserts that no production image or production compose file contains it. Exclude it from the FR-UX-12 inventory by that test, not by an allow-list. |
| Never touches real data | It refuses to start unless `TB_ENV` is `DEV` or `TEST`. It loads only datasets whose class in `eval/DATASETS.yaml` (create it; §17.1) is D0 or synthetic. It also refuses to start if a D3/D4 store is configured. |
| Local only | Binds `127.0.0.1` by default. To share it from a cloud VM, put it behind the existing Caddy and login pattern from the TrialGPT cloud deployment. |
| Visible as test | A banner on every page reads "TEST BENCH: synthetic and open data only, not a clinical tool". |
| Spec record | Add a VV requirement row in `spec/v4/16_vv_engineering_operations.md` (§16.2) and the path to the §17.1 table. |

**Stack.** FastAPI with Jinja2, server-rendered, which matches `services/console/`. Use htmx vendored as a file, since
there is no CDN on premises, and Server-Sent Events for live logs. Charts come from the same `libs/tb_reports` figure
code that the deliverables use (PNG or SVG), so the bench shows exactly what a sponsor would receive. Reuse ideas and
code from the TrialGPT web UI (`trialgpt/trialgpt_local/app.py` on the other branch).

**Pages.**

| Page | What it shows and does |
| --- | --- |
| Run | One button, "Run end to end", per dataset (Synthea site A, MIMIC demo). A live log, then each invariant (monotone funnel, small cells, reproducible second run, 0 blocking DQ, lineage complete) as pass or fail. Also a "Run all tests" button that shells out to pytest and shows the summary. |
| Data platform | L0–L5 per batch: manifest, reconciliation totals, DQ results, quarantine reasons, the lineage graph. A planted-defect injector (row drop, type drift, duplicate key, null identifier) that shows the publish gate blocking. |
| Trials | Pick a cached CT.gov trial or fetch one by NCT id. Shows the parsed criteria, IR v3 JSON, the generated SQL and CQL, and each criterion's class (structured, note, human). |
| Feasibility | Funnel with released and exact columns (exact is allowed here because the data is synthetic or open), sensitivity variants, monthly incidence, the pack figures, and PDF and XLSX download. |
| Patients | Synthetic and open patients only: the per-patient cascade trace S0–S5 with evidence spans and the judge's reasoning. |
| LLM lab | Gateway routing table. Send a test prompt with a chosen data class and see it allowed or refused, with its audit record. Model registry and statuses. The bake-off results table per language. Run a small sample with a chosen model if the key exists, with a cost cap. |
| Recall | Run `recall_sim` with p, looks and ledgers as inputs; chart the confidence sequence against repeated Clopper–Pearson; show a certificate from the last run. |
| Conversation | A simulator: type a message as email or the fake Teams in zh-TW, en or ja, attach a protocol PDF, and see the proposal, `OK`, the job and the reply (MailHog outbox). Use the Hermes engine if it was built, otherwise the native engine. |
| Audit | The audit chain for the session, with `audit_verify` run from the page. |

**Tests for the bench.** Browser smoke tests with Playwright in `tests/testbench/`. Chromium is preinstalled in cloud
sessions (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`); do not run `playwright install`. The tests open every page,
click "Run end to end" on the Synthea fixture, and assert PASS. Add `make testbench` (serve) and `make testbench-test`.

## 6. How to run things

```bash
cd trialbox
make venv                                   # once; Python 3.12 via uv
export PYTHONPATH=libs:services:.           # the tools and tests need it (see trap 1)
make lint                                   # ruff, ruff format, mypy --strict, contract freshness
make test                                   # unit tests, about 3 min
make open-data-e2e                          # fetch MIMIC demo + CT.gov, run, write .cache/open_data/report.md
python -m tools.recall_sim                  # 9.7 % vs 0.3 % (seed 11)
python -m tools.mlbench run --models <ids> --langs en zh-TW ja mixed   # needs OPENROUTER_API_KEY
make up-test && make test-e2e && make test-integration                 # Docker compose stack
```

## 7. Traps already found

1. **Imports from the wrong checkout.** If the venv has another checkout installed in editable mode, tools import that
   code. Always set `PYTHONPATH=libs:services:.` (the Makefile targets do).
2. **Slow VM.** The unit suite takes about 3 min. The open-data test takes about 1.5 min idle, much longer under load,
   so its module timeout is 1 h; the default per-test timeout is 900 s. Run the slow suites separately.
3. **Ports.** Test-stack host ports can be moved with `TB_HOST_<NAME>_PORT` in `deploy/.env`.
4. **FEAS index dates are month-ends.** "Current hospitalisation" becomes "within 30 days before a month-end"
   (see `docs/OPEN_DATA.md`, Limits).
5. **The criterion format cannot express** a relative creatinine rise, urine output, drug dose or route, primary
   diagnosis, or BNP. STARRT-AKI therefore undercounts. IR v3 (S1-15) is where this gets fixed.
6. **Codes in the MIMIC demo are US codes.** 2,054 ICD-9 diagnoses are unmapped, and about 81k lab events have no LOINC.
   They are reported as data-fitness findings, not hidden.
7. **Licences.** Mirth Connect is proprietary since 4.6, so use Eclipse Open Integration Engine for HL7 v2. Soda Core v4
   is ELv2, so do not use it. Debezium on Db2 needs an IBM IIDR licence. MIMIC demo data is ODbL: fetch it at
   run time and never commit it (`.cache/` is gitignored).
8. **LiteLLM.** The PyPI releases 1.82.7 and 1.82.8 were compromised (2026-03-24). The gateway is built in-house for
   that reason.
9. **CodeRabbit** skips this repository (fewer than 10 stars). There is no CI on GitHub, so local checks are the gate.

## 8. Rules for the session

- **Branch.** Work on the branch the session is given. Start it from `origin/claude/trialbox-e2e-build-lcvm9p`. If
  https://github.com/zandis/Auto-GPT/pull/2 is merged by then, start from `master`. If PR #2 is still open, open the new
  PR as a draft with PR #2's branch as its base, so its diff shows only the new work.
- **The repository is public.** Commit only public facts. Do not commit hospital-internal details, partner pricing,
  staff names, credentials, IPs or meeting details. The `docs/research/` files are already sanitised; keep it that way.
- **Secrets.** Never ask the user to paste an API key into chat. Keys go into the cloud environment's secrets.
- **Commits and PRs.** Do not put model identifiers in commit messages, PR text or code comments. End commit messages
  with the session's attribution lines.
- **Data.** Only open or synthetic data in this repository and on the Test Bench. Never real patient data.
- **Spec first.** Where code and spec disagree, change the code, or change the spec in the same commit with a reason.
  §17.1 governs paths.
