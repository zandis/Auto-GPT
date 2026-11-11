# D-370 One ingest stack: the adapter stays, dataplat goes

- **Task:** T-659 (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4)
- **PR:** this branch (`agent/T-659-ingest-decision`)
- **Date:** 2026-11-11
- **Status:** accepted (the owner's answer to Q-18, `docs/plan/28-master-plan-v6.md` §10.4; D-311: no gate)
- **Closes:** DATA-002, the decision half (`docs/reviews/2026-11-10-deep-review/06-data-flow-governance.md`)
- **Removal:** T-659b

## Context

TrialBox has two ingest stacks. `services/adapter` is the one the box runs. `services/dataplat` (stages L0 to L5)
has data contracts, row quarantine, a publish gate, a master patient index and lineage, but nothing in the box runs
it. The two derive different pseudonyms, so a later switch would re-key every pid (DATA-002). The owner answered
Q-18: one stack, the adapter, with the governed stack's controls moved into it.

## Measured facts (origin/master at 3a043b6f, 2026-11-11)

| Fact | `services/adapter` | `services/dataplat` |
| --- | --- | --- |
| Compose service | `adapter` in `deploy/docker-compose.yml` (`uvicorn adapter.app:app`, port 8016); also in the test, secrets, platform and gb10 files | none in any compose file |
| Who starts a night | the orchestrator's `ingest` scenario (`services/orchestrator/scenarios/admin.py`) through `AdapterHttp.run` → `POST /run`; the console's re-run (`services/console/backend.py`) | nobody in `services/`; only `tools/cascade_e2e.py` (`make e2e-cascade`), `tools/trialbox/eval.py` (`ingest_fhir_demo`), `tools/testbench/*` and one phase of `tools/bench.py` |
| Python files outside the package that import it | 56 (services 8, tests 36, tools 12; dataplat itself adds 2) | 10 (tests 5, tools 5) |
| Goldens (`tests/golden/`, `tools/goldens.py`) | built through `tools/omop_parity._ingest` → `adapter.pipeline.run_ingest` | not used |
| `make e2e-simple`, `make backup-drill`, `make open-data-e2e`, the rulesets build | `adapter.pipeline.run_ingest` | not used |
| CI workflows (`.github/workflows/trialbox-*.yml`) | runs its tests | no job names it; only its 5 test files run in the unit suite |
| Pseudonym | `pid = HMAC-SHA-256(site key, chart number)[:32]` (`tb_common.crypto.pid_for_mrn`), used in 17 modules outside dataplat (the orchestrator, site setup, `tools/keys.py` among them) | `pid = HMAC(K_pid, random mpi_id)` (`dataplat/mpi`), used only inside dataplat |
| Dependency direction | imports nothing from dataplat | its L2 and L4 call the adapter (`adapter.mapping.engine`, `adapter.mapping.mimic`, `adapter.pipeline.pseudonymise_bulk`, `adapter.ndjson`) |
| Controls already moved | T-611 completeness gate (`completeness_check`, D-312), T-615b per-file quarantine, validate-first hold (CURRENT stays), T-612 site-key guard | contracts, row quarantine, the seven-condition gate, MPI merges with `pid_alias`, OpenLineage events |
| Size | 5,244 lines of Python | 3,147 lines of Python |

How measured: `grep -rlE "(from\|import) adapter"` and the same for `dataplat` over `*.py`, outside each package;
`grep -rn dataplat deploy Makefile ../.github`; `grep -rn "run_ingest"` over `services` and `tools`; `wc -l`.

## Decision

1. **The adapter is the one ingest stack.** The compose service `adapter` (`deploy/docker-compose.yml`, command
   `uvicorn adapter.app:app`, port 8016) is the one ingest path. The orchestrator's nightly `ingest` scenario and
   the console's re-run keep calling its `POST /run`. No compose file gets a dataplat service.
2. **The pseudonym rule stays** `pid = HMAC-SHA-256(site key, normalised chart number)[:32]`. The random
   `mpi_id` and `K_pid` of dataplat are not adopted. No pid already in the opt-out register, marks, delegation, the
   data core or the audit log is re-keyed.
3. **What moves into the adapter**, each a later card or part of T-659b, smallest first:
   - **Contracts.** The per-table YAML contracts (`dataplat/contracts/demo_his`, `mimic_fhir`) become the adapter's
     table contract next to the T-611 `FeedCompleteness` settings: required table, columns, types, non-null keys,
     enumerations. Breaking drift holds the night; additive drift is a warning in the ingest report.
   - **Quarantine.** Row-level quarantine (null patient key, type mismatch, duplicate key, future date) is added to
     the adapter's per-file quarantine (T-615b). A table whose quarantined share passes its contract maximum holds the
     night. The reason codes stay the ones of `tb_contracts.landing.ReasonCode`.
   - **Publish gate.** The adapter's hold (validate first; T-611 gate; CURRENT stays; nothing pruned) is the gate.
     Each night writes one `PublishGateRecord` (conditions, outcome, reasons) into the ingest report, so the
     readiness page and the audit show one record whatever held the night.
   - **Patient index as an alias table.** A chart-number merge (A → B) adds a row to a new table `pid_alias` in the
     adapter's schema `pidmap`: old pid → surviving pid, reason, ticket, time; append-only. Every reader of a pid
     (opt-out, marks, candidates, the data core) resolves through it. Both chart numbers then give one pid; no row
     is re-keyed. This is the acceptance of DATA-002: an A → B merge maps both to one pid with an alias row.
   - **Lineage.** Each night writes `lineage.json` next to `completeness.json`: input file names and sha256, the
     mapping file and its hash, the snapshot written, the outcome. OpenLineage events are not kept; no service reads
     them.
   - **Reconciliation and DQ.** Only the checks that hold a bad feed the adapter would otherwise publish move:
     source row count against landed count, and distinct patients. The rest of `dataplat/dq` and
     `dataplat/reconcile` is not ported.
4. **What is deleted (T-659b).** The tree `services/dataplat/`; its tests `tests/unit/test_dataplat_gate.py`,
   `test_dataplat_landing.py`, `test_dataplat_thin_path.py`; its schema `mpi` and its row in
   `tests/unit/test_migrations.py`. The callers are moved to the adapter, not deleted: `tools/cascade_e2e.py` and
   `make e2e-cascade` (with `tests/unit/test_cascade_pipeline.py`), `tools/trialbox/eval.py ingest_fhir_demo`,
   `tools/testbench/drivers.py` (`run_dataplat`) and `tools/testbench/e2e_adapter.py`, and the dataplat phase of
   `tools/bench.py`. Each planted defect of `test_dataplat_gate.py` that the adapter does not yet hold is carried
   over as an adapter test before the file goes.
5. **Order.** T-611 (on master) was the first control to move. T-659b may land before the other controls move: its
   acceptance is one ingest path in compose and the tree, and the T-611 fault tests still passing.

## Why the adapter, not dataplat

- **It is what runs.** Compose, the orchestrator's nightly job, the console, the goldens, `make e2e-simple`, the
  backup drill and the rulesets build all go through `adapter.pipeline.run_ingest`. Dataplat has no service.
- **No re-keying.** Every stored pid is `HMAC(site key, chart number)`. Choosing dataplat would change every pid
  in the opt-out register, marks, delegation, the data core and the audit log, a migration with a safety risk
  (an opted-out patient coming back under a new pid, DATA-004).
- **Dataplat already depends on the adapter.** Its standardise and curated stages wrap the adapter's mapping
  engine, MIMIC normaliser and NDJSON writer. Keeping dataplat would still keep most of the adapter.
- **Less to change.** 10 files import dataplat; 56 import the adapter. The controls that matter are small (contracts
  163 lines, publish gate 144, MPI 228) and port one at a time behind tests; the first one (T-611) already has.

## Consequences

- DATA-002 is closed when T-659b lands; this file closes its decision half.
- `services/dataplat` stays on master until T-659b and gets no new features. A card that needs a governed-stack
  control builds it in the adapter.
- The deviation note in `services/dataplat/__init__.py` (move the adapter into dataplat) is void.
- Not chosen: running both stacks, or dataplat as the runner with an adapter shim. Both keep two pseudonym rules.
