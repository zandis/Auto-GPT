# D-360 Compose limits, health and the watchdog

- **Task:** T-108a, operations in code, part a (`docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-108a-compose-limits`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-082, OPS-029 (the watchdog; the systemd timer that runs it is T-108b)
- **Builds on:** D-348 (T-673, the compose files and `deploy/images.lock`), D-177 (model-guard), D-178 (`ops`)

## Context

No compose file set a memory or a process cap (CR-082): one runaway service (a DuckDB query, a JVM, vLLM's host
side) could take the memory of every other service on the box, and on a GB10 the 128 GB are shared with the models.
`restart: unless-stopped` acts when a process exits, not when its health check fails: a hung vLLM stays "up" and a
night's screening waits on it (OPS-029).

## Decision

1. **Every service has a memory cap and a pids cap** in every compose stack (base file, GPU profiles, identity,
   test, PoC, test bench, platform). Memory caps follow the Kubernetes form (`deploy/platform/base`); each production
   cap is a setting, `TB_MEM_<NAME>` in `deploy/.env` (`TB_MEM_DB`, `TB_MEM_FHIR`, `TB_MEM_LAKE`, `TB_MEM_EMBED`,
   `TB_MEM_DOCPARSER`, `TB_MEM_COMPILER`, `TB_MEM_ADAPTER`, `TB_MEM_ORCH`, `TB_MEM_MAIL`, `TB_MEM_GATEWAY`,
   `TB_MEM_CONSOLE`, `TB_MEM_LLM`, `TB_MEM_VERIFIER`, `TB_MEM_CADDY`, `TB_MEM_AUTHELIA`). The vLLM servers get 48g of
   host memory each (a sleeping judge keeps its ~18 GB of weights in host memory). The JVM caps sit at least 1 GB over
   their heaps (HAPI 5g over 3g, 8g over 6g on the GB10; the adapter 6g over the validator's 3g). Process caps: 512
   for Python services and Postgres, 1024 for JVM services, 4096 for vLLM.
2. **No CPU cap.** CPU is shared, not used up; a cap only slows a night run, and the cores differ per box.
3. **The lake sizes DuckDB from the cap.** Without `TB_LAKE_MEMORY_LIMIT`, `lake.store.memory_limit` takes 40 % of the
   smaller of physical memory and the container's cgroup cap (`/sys/fs/cgroup/memory.max`). Before, 40 % of the
   host's memory under an 8g cap would have had the lake killed.
4. **Every long-running service has a health check, a capped json-file log and `restart: unless-stopped`.** Caddy
   gets a health site on its own loopback (`http://127.0.0.1:2020/healthz`, never published; the admin API stays
   off). Authelia uses its image's check. One-shot jobs (`restart: "no"`) and test-only or dev-only services need
   caps and a log cap only.
5. **The watchdog.** Each long-running service carries the label `tb.watchdog`: `restart` (all but the database) or
   `report` (the database: a restart does not cure it; a person looks). `python3 -m tools.trialbox watchdog` runs on
   the host with the standard library. A labelled container that Docker calls `unhealthy` for `--after-minutes`
   (default 2) is restarted with `docker restart`, and `ops.watchdog.restart` goes into the audit chain. A `report`
   container gets one `ops.watchdog.unhealthy` per episode. After `--max-restarts` (3) in `--window-hours` (6) it
   stops, audits `ops.watchdog.gave_up` once and leaves the service to a person. A failed restart is audited
   (`ops.watchdog.restart_failed`) and counts toward the cap. The audit line is written inside the orchestrator, as
   `update.py` and `ops.py` do; when that fails it waits in `deploy/watchdog/pending_audit.jsonl` and is written first
   on the next pass. The detail names the service, the container, the minutes unhealthy, the failing streak and the
   last exit code, never the check's output.
6. **The lint.** `tests/unit/test_compose_limits.py` merges each stack and fails on a service without caps, a log
   cap, a restart rule, a health check or a watchdog label; with the compose plugin it also renders every stack with
   `docker compose config`. A new compose file must join a linted stack.

## Consequences

- A site that raises `HAPI_XMX` or `TB_VALIDATOR_XMX` raises `TB_MEM_FHIR` or `TB_MEM_ADAPTER` with it.
- The caps are not measured on a box under a full night. The G1 run and T-214 (Spark) measure them; `TB_MEM_*` moves
  a cap without a release.
- Not in this decision: the systemd timer that runs the watchdog every minute, the egress unit and the start after a
  host restart (T-108b); the "hung vLLM" drill on a real box (T-213); log caps sized from G1 (T-108d).
