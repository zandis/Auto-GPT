# D-471 The scale gate: a nightly 50,000-patient run under the compose memory caps with a slow model stand-in, and a lint of fixed limits

- **Task:** T-687 (`docs/plan/28-master-plan-v6.md` §6.2.10; `docs/plan/31-master-plan-v6.1-addendum.md` §3.4, the
  first card of wave C and the test of OD-10)
- **PR:** this branch (`agent/T-687-scale-gate`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** the class of scale review 2026-11-11 §1 (TB-REV scale-timeouts) as a regression gate for F-01 to F-36;
  G1 BUGS.md B2 ("card T-687 is the test that would have caught all of them")
- **Builds on:** D-360 (T-108a, a memory cap on every service), D-445 (T-608, the gateway's timeout budget), D-460
  (T-706, today's defects as strict expected failures by finding id), D-462 (T-722, one rebuild per snapshot)

## Decision

1. **The gate is a nightly CI job, not a pull-request check.** `trialbox-e2e.yml` job `scale-50k` runs
   `tests/perf/test_scale_gate.py` at `TB_SCALE_PATIENTS=50000`: the night's ingest, the lake rebuild through the
   site publish, the screen and the nightly backup, each in its own process with the memory cap of the compose
   service that runs it in production. Pull requests have no Docker and no pgvector; they run the same gate at a
   small size (`tests/unit/test_scale_gate_logic.py`), so the gate's own logic is tested on every pull request.
2. **The caps are read from `deploy/docker-compose.yml`**, never copied: `mem_limit` of `adapter` (ingest), `lake`
   (rebuild and every lake query), `orchestrator` (screen) and `db`, with a `TB_MEM_*` override from the environment
   as compose would read it.
3. **Enforcement is a cgroup (`systemd-run --scope -p MemoryMax=<cap> -p MemorySwapMax=0`) in the nightly job.**
   Docker's `mem_limit` is the cgroup's `memory.max`: the kernel kills the process tree at the cap. Only a cgroup
   reproduces that; `ulimit -v` / `setrlimit(RLIMIT_AS)` limit virtual address space, which DuckDB, Arrow and the
   JVM reserve far beyond what they touch, so they would fail on reservations, not on use. The GitHub runner has
   systemd, cgroup v2 and password-less `sudo`; the job sets `TB_SCALE_ENFORCE=cgroup` and the gate fails if the
   cgroup cannot be made. The lake's DuckDB sizes itself from the cgroup root, which in a container is the container's
   cap: the gate hands the cap to that function (`lake.store._cgroup_memory_max`), and the adapter gets the validator
   heap of its compose environment (`TB_VALIDATOR_XMX`). Where there is none (a developer container, the pull-request run), the gate measures the
   peak resident memory of the whole process tree and fails a phase that went over its cap (mode `measure`); the
   report names the mode.
4. **The slow model stand-in is the existing stub** (`services/llm_stub`), extended with `TB_STUB_LATENCY_S`
   (seconds per call), `TB_STUB_OUTAGE_AFTER` and `TB_STUB_OUTAGE_S` (an outage of 502 answers after the n-th call,
   for that many seconds). The gate restarts the stub process once in the middle of the screen. The nightly values
   (2 s per call, a 40 s outage) are the row's; the gateway, its breaker and its budgets in between are the real
   ones over real HTTP.
5. **Known failures are strict expected failures by finding id and card** (`EXPECTED` in `tools/scale_gate.py`, like
   D-460). The list started with F-01 (T-690), F-02 (T-691), F-05 (T-692) and F-04 (T-689); the gate reproduced F-04
   here (a 1 s and a 5 s outage lost 2 of 5 and 60 of 74 judge calls: the gateway tried a refused call once, then
   its breaker answered for the model). Each card's merge made its checks pass at 200 and 2,000 patients and its line
   was removed: the list is empty since T-689 (D-456). The pull-request tests still show the gate catches each shape:
   a publish that loses its job, a backup with `TB_BACKUP_QUIESCE=pause`, a night and a lake over a too-small cap,
   and an outage the product does not wait through (the stand-in's `TB_STUB_OUTAGE_STATUS=400`). Only the model's
   faults count as lost calls: the product's own list (`tb_llm.outage.MODEL_FAULTS`, with `upstream_down`) and
   `upstream_failed`; a content refusal is reported beside them. A check whose fault never happened (no outage
   reached the stand-in) is blocked, never a pass. A line that starts to pass fails the job until it is removed, in
   the card that fixes it. A size-bound entry applies from its size; below it the check must pass. A check whose
   input a failed phase did not produce is "blocked" and names that phase: never a silent pass.
6. **The limits lint** (`tools/limits_lint.py`, PR CI job `docs`): every `timeout=` literal over 60 s and every
   `LIMIT n` / `limit=n` literal in `services/` must have a line in `tools/limits_allow.yaml` with a reason that
   names its finding (F-nn) or the card that removes it, or why it is not a cut (OD-10). A new literal fails; a line
   whose literal is gone fails too, so the list only shrinks.

## Open

- Not run at 50,000 on the build machine (4 shared cores): the first scheduled run of `scale-50k` is the proof, and
  nothing about 50,000 is proven yet: whether T-692's streaming ingest and rebuild fit 6 GB and 8 GB there, and
  whether T-690's publish and T-691's backup hold at that size. The harness was run at 200, 300 (with the HL7
  validator) and 2,000 patients in `measure` mode (with T-692: adapter peak 0.09 GiB and lake 0.94 GiB at 2,000). If the
  first run shows another failure with a finding of the review (F-07, F-29, F-36 at 50,000), its line is added to
  `EXPECTED` with its card.
- The lint reads literals only: a named constant (`UPSTREAM_READ_S = 180` in `libs/tb_llm`, F-13) or a limit outside
  `services/` is not listed. Widening it is a follow-up.

- The FHIR store (HAPI) is not loaded in the gate (it needs Docker): the backup's database is the run's PostgreSQL,
  not a 20 to 50 GB box database. F-02 fails on the pause itself, which does not depend on the size.
- The screen runs the cascade with the real gateway, not an orchestrator job: the failure share checked during the
  job and the restart of the orchestrator (F-28, T-689) are T-689's acceptance tests.
